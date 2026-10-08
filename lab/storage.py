"""Where the Lab's disk goes, and the one narrow kind of clean-up it may do.

``inventory`` only reads. It sizes the runs root, the corpus, other Lab
material, older benchmark artifacts and ``dist/``, and says who owns each:
the Lab (a writer it recognizes), packaging (a name ``tools/build_package.py``
produces) or nobody it can name (``unknown``).

``preview`` proposes deleting only working subtrees that the writer of a run
declared disposable in that run's own ``lab_provenance`` -- an update check's
unpacked installation, a stress run's browser profile -- after the writer kept
the logs that explain the run. A run root, its recordings, measurements,
reports, frozen exports, replay material, a pinned, active, unfinished or
unrecognized run, and anything outside the canonical runs root are never
proposed. ``apply`` deletes exactly a saved preview, after checking that every
target is still the same directory with the same contents and still eligible;
it refuses the whole plan otherwise and reports a partial result if deletion
stops midway. ``dist/`` is reported, never collected.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import time
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .identity import LAB_ROOT, REPO_ROOT, RUNS_ROOT, RunIdentity, run_identity
from .pins import Registry, load

PLAN_SCHEMA = 1
#: A run touched more recently than this may still be writing.
ACTIVE_WINDOW_SECONDS = 15 * 60
#: Never a disposable subtree, whatever a declaration says.
PRESERVED = frozenset(
    {
        "metadata.json",
        "events.jsonl",
        "processes.jsonl",
        "measurements.jsonl",
        "samples.jsonl",
        "summary.json",
        "summary.md",
        "report.html",
        "report.json",
        "campaign.json",
        "campaign.md",
        "campaign.html",
        "replay",
        "replay.json",
        "corpus-inventory.json",
        "logs",
    }
)
#: What ``tools/build_package.py`` writes under ``dist/``.
PACKAGING_NAMES = frozenset(
    {"macos", "windows", "linux", "release", "reports", ".native", ".pyinstaller", "reconstructed"}
)
_PACKAGING_PREFIX = "hanly-desktop-"
_REPARSE_POINT = 0x400


class StorageError(RuntimeError):
    """A plan cannot be applied safely; nothing further is deleted."""


@dataclass(frozen=True)
class Size:
    bytes: int = 0
    files: int = 0
    links: int = 0
    newest: float = 0.0

    def __add__(self, other: Size) -> Size:
        return Size(
            self.bytes + other.bytes,
            self.files + other.files,
            self.links + other.links,
            max(self.newest, other.newest),
        )


@dataclass
class Entry:
    path: str
    area: str
    ownership: str
    size: Size
    kind: str = "not_applicable"
    completion: str = "not_applicable"
    protection: list[str] = field(default_factory=list)
    active: bool = False
    disposable_bytes: int = 0


# -- inventory ----------------------------------------------------------------------------


def inventory(
    repo_root: Path | None = None,
    registry: Registry | None = None,
    *,
    now: float | None = None,
) -> dict[str, Any]:
    """Read-only accounting of every location the Lab and packaging write to."""

    repo_root = REPO_ROOT if repo_root is None else repo_root
    lab_root = repo_root / "artifacts" / "lab"
    runs_root = lab_root / "runs"
    registry = load(runs_root=runs_root) if registry is None else registry
    now = time.time() if now is None else now
    entries: list[Entry] = []

    for path in _children(runs_root):
        entries.append(_run_entry(path, repo_root, registry, now))
    corpus = lab_root / "corpus"
    if corpus.exists():
        entries.append(Entry(_relative(corpus, repo_root), "corpus", "lab", measure(corpus)))
    for path in _children(lab_root, include_files=True):
        if path.name in {"runs", "corpus", "pins.json"} or path.name.startswith(".gc-"):
            continue
        entries.append(Entry(_relative(path, repo_root), "other_lab", "unknown", measure(path)))
    for path in _children(repo_root / "artifacts", include_files=True):
        if path.name != "lab":
            entries.append(Entry(_relative(path, repo_root), "legacy", "unknown", measure(path)))
    for path in _children(repo_root / "dist", include_files=True):
        owner = "packaging" if _packaging_owned(path.name) else "unknown"
        entries.append(Entry(_relative(path, repo_root), "dist", owner, measure(path)))

    totals: dict[str, dict[str, int]] = {}
    for entry in entries:
        bucket = totals.setdefault(f"{entry.area}/{entry.ownership}", {"bytes": 0, "entries": 0})
        bucket["bytes"] += entry.size.bytes
        bucket["entries"] += 1
    return {
        "repo_root": ".",
        "entries": [_entry_dict(entry) for entry in entries],
        "totals": dict(sorted(totals.items())),
        "total_bytes": sum(entry.size.bytes for entry in entries),
        "dangling_pins": [pin.run for pin in registry.dangling()],
        "note": "dist/ is reported only; the Lab never collects it",
    }


def _run_entry(path: Path, repo_root: Path, registry: Registry, now: float) -> Entry:
    identity = run_identity(path)
    size = measure(path)
    roles = sorted(registry.roles(path.name))
    active = _active(identity, size, now)
    declared = _declared(identity)
    disposable = sum(measure(path / name).bytes for name in declared if (path / name).is_dir())
    return Entry(
        path=_relative(path, repo_root),
        area="runs",
        ownership="unknown" if identity.kind == "unknown" else "lab",
        size=size,
        kind=identity.kind,
        completion=identity.completion,
        protection=roles
        + (["active"] if active else [])
        + (["unrecognized"] if identity.kind == "unknown" else []),
        active=active,
        disposable_bytes=disposable,
    )


def _entry_dict(entry: Entry) -> dict[str, Any]:
    payload = asdict(entry)
    payload["size"] = asdict(entry.size)
    return payload


def _packaging_owned(name: str) -> bool:
    return name in PACKAGING_NAMES or name.startswith(_PACKAGING_PREFIX)


def _children(root: Path, *, include_files: bool = False) -> list[Path]:
    if not root.is_dir() or root.is_symlink():
        return []
    return sorted(
        path
        for path in root.iterdir()
        if path.name != ".DS_Store" and (include_files or (path.is_dir() and not path.is_symlink()))
    )


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def measure(root: Path, *, strict: bool = False) -> Size:
    """Sizes without following any link; a link counts as itself, never its target.

    ``strict`` raises on anything unreadable instead of skipping it, which is
    what deciding a deletion needs: an unread directory is an unknown one.
    """

    try:
        info = os.lstat(root)
    except OSError:
        return Size()
    if _is_link(info) or not stat.S_ISDIR(info.st_mode):
        return Size(info.st_size, 1, int(_is_link(info)), info.st_mtime)
    total = Size(0, 0, 0, info.st_mtime)
    for entry in _walk(root, strict=strict):
        try:
            entry_info = entry.stat(follow_symlinks=False)
        except OSError:
            if strict:
                raise
            continue
        if _is_link(entry_info):
            total += Size(0, 0, 1, entry_info.st_mtime)
        elif stat.S_ISDIR(entry_info.st_mode):
            total += Size(0, 0, 0, entry_info.st_mtime)
        else:
            total += Size(entry_info.st_size, 1, 0, entry_info.st_mtime)
    return total


def _walk(root: Path, *, strict: bool = False) -> Iterator[os.DirEntry[str]]:
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    yield entry
                    if entry.is_dir(follow_symlinks=False) and not _is_link(
                        entry.stat(follow_symlinks=False)
                    ):
                        stack.append(Path(entry.path))
        except OSError:
            if strict:
                raise
            continue


def _is_link(info: os.stat_result) -> bool:
    # A Windows junction is a reparse point that ``S_ISLNK`` does not report.
    attributes = getattr(info, "st_file_attributes", 0)
    return stat.S_ISLNK(info.st_mode) or bool(attributes & _REPARSE_POINT)


# -- eligibility --------------------------------------------------------------------------


def _declared(identity: RunIdentity) -> list[str]:
    """Subtrees this run's own writer recorded as disposable, minus anything preserved."""

    record = "summary.json" if identity.kind == "update_check" else "metadata.json"
    try:
        payload = json.loads((identity.path / record).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    block = payload.get("lab_provenance") if isinstance(payload, dict) else None
    if not isinstance(block, dict) or not isinstance(block.get("version"), int):
        return []
    names = block.get("disposable")
    if not isinstance(names, list):
        return []
    # Folded: macOS and Windows file systems are case-insensitive, so REPLAY is replay.
    preserved = {name.casefold() for name in PRESERVED}
    return [
        name
        for name in names
        if isinstance(name, str)
        and name.casefold() not in preserved
        and not name.casefold().startswith("frozen-")
        and len(Path(name).parts) == 1
        and name not in {".", ".."}
    ]


def _active(identity: RunIdentity, size: Size, now: float) -> bool:
    """Recently written, or a recognized run that never recorded its end."""

    return now - size.newest < ACTIVE_WINDOW_SECONDS or identity.completion == "interrupted"


def _refusal(identity: RunIdentity, registry: Registry, now: float, runs_root: Path) -> str | None:
    """Why this run's declared subtrees may not be collected, or ``None``."""

    if identity.kind == "unknown":
        return "no Lab writer is recognized; manual or ambiguous material is never collected"
    if identity.path.resolve().parent != runs_root.resolve():
        return "outside the canonical runs root"
    if registry.roles(identity.name):
        return f"pinned ({', '.join(sorted(registry.roles(identity.name)))})"
    if _active(identity, measure(identity.path), now):
        return f"active or unfinished ({identity.completion})"
    return None


# -- preview and apply --------------------------------------------------------------------


def preview(
    runs_root: Path | None = None,
    registry: Registry | None = None,
    *,
    now: float | None = None,
) -> dict[str, Any]:
    """The deterministic plan: every eligible target and why everything else is kept."""

    # Resolved per call, not at import, so a relocated root is the one honoured.
    runs_root = RUNS_ROOT if runs_root is None else runs_root
    _require_canonical(runs_root)
    registry = load(runs_root=runs_root) if registry is None else registry
    now = time.time() if now is None else now
    targets: list[dict[str, Any]] = []
    kept: list[dict[str, str]] = []
    for path in _children(runs_root):
        identity = run_identity(path)
        declared = [name for name in _declared(identity) if (path / name).exists()]
        if not declared:
            continue
        refusal = _refusal(identity, registry, now, runs_root)
        for name in declared:
            subtree = path / name
            problem = refusal or _subtree_problem(subtree)
            if problem:
                kept.append({"run": path.name, "subtree": name, "reason": problem})
                continue
            info = os.lstat(subtree)
            size = measure(subtree)
            targets.append(
                {
                    "run": path.name,
                    "subtree": name,
                    "kind": identity.kind,
                    "bytes": size.bytes,
                    "files": size.files,
                    "device": info.st_dev,
                    "inode": info.st_ino,
                    "content": content_fingerprint(subtree),
                }
            )
    body = {"schema_version": PLAN_SCHEMA, "targets": targets}
    return {
        **body,
        "plan_id": _plan_id(body),
        "kept": kept,
        "reclaimable_bytes": sum(target["bytes"] for target in targets),
    }


def write_plan(plan: dict[str, Any], lab_root: Path | None = None) -> Path:
    path = (LAB_ROOT if lab_root is None else lab_root) / f".gc-plan-{plan['plan_id'][:16]}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    return path


def apply(
    plan_path: Path,
    runs_root: Path | None = None,
    registry: Registry | None = None,
    *,
    now: float | None = None,
) -> dict[str, Any]:
    """Delete exactly the targets of a saved preview, or nothing at all.

    Every target is re-validated first -- still eligible, still the same
    directory, still the same contents -- and one stale target refuses the
    whole plan. A failure or interruption during deletion stops at once and
    the result says which targets were deleted, which one was partial and
    which were never attempted.
    """

    runs_root = RUNS_ROOT if runs_root is None else runs_root
    _require_canonical(runs_root)
    plan = _load_plan(plan_path)
    registry = load(runs_root=runs_root) if registry is None else registry
    now = time.time() if now is None else now
    problems = [
        f"{target['run']}/{target['subtree']}: {problem}"
        for target in plan["targets"]
        if (problem := _revalidate(target, runs_root, registry, now))
    ]
    if problems:
        raise StorageError("the plan is stale; nothing was deleted:\n  " + "\n  ".join(problems))

    result: dict[str, Any] = {"plan_id": plan["plan_id"], "deleted": [], "status": "complete"}
    pending = list(plan["targets"])
    while pending:
        target = pending[0]
        name = f"{target['run']}/{target['subtree']}"
        try:
            _delete_tree(runs_root / target["run"] / target["subtree"])
        except BaseException as error:
            result.update(
                status="interrupted" if isinstance(error, KeyboardInterrupt) else "partial",
                partial=name,
                error=type(error).__name__,
                not_attempted=[f"{t['run']}/{t['subtree']}" for t in pending[1:]],
            )
            if not isinstance(error, (OSError, StorageError, KeyboardInterrupt)):
                raise
            return result
        result["deleted"].append(name)
        pending.pop(0)
    return result


def _revalidate(
    target: dict[str, Any], runs_root: Path, registry: Registry, now: float
) -> str | None:
    run = runs_root / str(target["run"])
    if run.is_symlink() or not run.is_dir():
        return "the run is gone or no longer a directory"
    identity = run_identity(run)
    if str(target["subtree"]) not in _declared(identity):
        return "the run's writer no longer declares it disposable"
    refusal = _refusal(identity, registry, now, runs_root)
    if refusal:
        return refusal
    subtree = run / str(target["subtree"])
    problem = _subtree_problem(subtree)
    if problem:
        return problem
    info = os.lstat(subtree)
    if (info.st_dev, info.st_ino) != (target["device"], target["inode"]):
        return "it is a different directory than the one previewed"
    if content_fingerprint(subtree) != target["content"]:
        return "its contents changed since the preview"
    return None


def _subtree_problem(subtree: Path) -> str | None:
    try:
        info = os.lstat(subtree)
    except OSError:
        return "missing"
    if _is_link(info):
        return "a link, which the Lab never follows"
    if not stat.S_ISDIR(info.st_mode):
        return "not a directory"
    try:
        links = measure(subtree, strict=True).links
    except OSError:
        return "it cannot be read completely, so what it holds is unknown"
    if links:
        return "holds a link, which the Lab never follows"
    return None


def content_fingerprint(root: Path) -> str:
    """Every path, size and modification time under ``root``, hashed."""

    rows = []
    for entry in _walk(root, strict=True):
        info = entry.stat(follow_symlinks=False)
        relative = Path(entry.path).relative_to(root).as_posix()
        rows.append(f"{relative}\0{info.st_size}\0{info.st_mtime_ns}")
    return hashlib.sha256("\n".join(sorted(rows)).encode("utf-8")).hexdigest()


def _delete_tree(root: Path) -> None:
    """Remove a validated subtree bottom-up, refusing any link met on the way."""

    directories = [root]
    for entry in _walk(root, strict=True):
        info = entry.stat(follow_symlinks=False)
        if _is_link(info):
            raise StorageError(f"a link appeared under {root}")
        if stat.S_ISDIR(info.st_mode):
            directories.append(Path(entry.path))
        else:
            if sys.platform == "win32" and not info.st_mode & stat.S_IWRITE:
                os.chmod(entry.path, stat.S_IWRITE)
            os.unlink(entry.path)
    for directory in sorted(directories, key=lambda path: len(path.parts), reverse=True):
        os.rmdir(directory)


def _require_canonical(runs_root: Path) -> None:
    """The runs root itself must be where it claims to be, not a redirection."""

    if not runs_root.is_dir():
        raise StorageError(f"{runs_root} does not exist")
    if runs_root.resolve() != runs_root.absolute():
        raise StorageError(f"{runs_root} is redirected through a link; refusing")


def _plan_id(body: dict[str, Any]) -> str:
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _load_plan(path: Path) -> dict[str, Any]:
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise StorageError(f"{path} is not a readable plan") from error
    if not isinstance(plan, dict) or plan.get("schema_version") != PLAN_SCHEMA:
        raise StorageError(f"{path} is not a version {PLAN_SCHEMA} plan")
    body = {"schema_version": PLAN_SCHEMA, "targets": plan.get("targets")}
    if not isinstance(plan.get("targets"), list) or plan.get("plan_id") != _plan_id(body):
        raise StorageError(f"{path} was edited after the preview; make a new one")
    for target in plan["targets"]:
        try:
            names = (str(target["run"]), str(target["subtree"]))
        except (KeyError, TypeError) as error:
            raise StorageError(f"{path} holds a malformed target") from error
        if any(len(Path(name).parts) != 1 or name in {".", ".."} for name in names):
            raise StorageError(f"{path} names a target outside a run root")
    return plan


__all__ = [
    "ACTIVE_WINDOW_SECONDS",
    "PRESERVED",
    "StorageError",
    "apply",
    "content_fingerprint",
    "inventory",
    "measure",
    "preview",
    "write_plan",
]
