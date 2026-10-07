"""What a recorded run is, read from what it contains.

Every Lab writer leaves a different layout under ``artifacts/lab/runs/``: a
session (``run``, ``tour``, ``stress``), a fixed-check set, an OCR campaign, a
measurement campaign or an isolated update check. ``run_identity`` recognizes
each from its files and normalizes the facts later steps need -- provenance,
platform, backend, options, plan, rule, completion -- without rewriting
anything. A directory no writer produced stays ``unknown``.

A fact that should exist but cannot be read is ``unknown``; one that does not
apply to the kind is ``not_applicable``. Contradicting observations are listed
in ``conflicts`` rather than resolved by guesswork.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
LAB_ROOT = REPO_ROOT / "artifacts" / "lab"
RUNS_ROOT = LAB_ROOT / "runs"

UNKNOWN = "unknown"
NOT_APPLICABLE = "not_applicable"

#: Session modes, as ``metadata.json`` names them.
SESSION_KINDS = frozenset({"run", "tour", "stress"})
#: Every kind ``run_identity`` can recognize, plus ``unknown``.
KINDS = (
    "run",
    "tour",
    "stress",
    "check",
    "ocr_campaign",
    "real_lookup",
    "real_hover",
    "live_hover",
    "update_check",
    UNKNOWN,
)

#: Evidence each kind is expected to hold; absence is reported, not assumed.
_EVIDENCE = {
    "session": ("metadata.json", "events.jsonl", "processes.jsonl", "summary.md"),
    "stress": ("campaign.json", "campaign.md", "replay", "replay.json"),
    "check": ("metadata.json", "measurements.jsonl", "summary.json", "report.html"),
    "ocr_campaign": ("metadata.json", "corpus-inventory.json", "samples.jsonl", "summary.json"),
    "measurement": ("metadata.json", "summary.json"),
    "update_check": ("summary.json",),
}

#: Options that change what a session hovers; everything else is presentation.
_SESSION_OPTIONS = ("words", "story_sizes", "word_sizes", "seed", "per_family")
#: Lines of ``events.jsonl`` worth decoding; the rest are skipped unparsed.
_EVENT_MARKERS = (
    '"ocr_backend"',
    '"tour_planned"',
    '"tour_finished"',
    '"tour_stopped_by_user"',
    '"tour_aborted"',
    '"session_ended"',
    '"tour_result"',
    '"stress_result"',
)


@dataclass(frozen=True)
class RunIdentity:
    """The normalized facts about one run directory."""

    name: str
    path: Path
    kind: str
    mode: str
    started: str
    commit: str
    #: ``clean``, ``dirty`` or ``unknown``, as the checkout was when the run started.
    source_state: str
    #: True, False, ``unknown`` or ``not_applicable`` (no end-of-run reading).
    source_changed: Any
    system: str
    machine: str
    configured_backend: str
    observed_backends: tuple[str, ...]
    options: dict[str, Any]
    fingerprint: str
    rules: tuple[str, ...]
    measurement_protocol: str
    completion: str
    evidence: dict[str, bool]
    provenance_version: int | None
    conflicts: tuple[str, ...] = ()
    notes: tuple[str, ...] = field(default=())

    @property
    def backend(self) -> str:
        """The one backend this run used, when that can be shown."""

        if len(self.observed_backends) == 1:
            return self.observed_backends[0]
        if self.observed_backends:
            return UNKNOWN
        if self.configured_backend in {"vision", "easyocr"}:
            return self.configured_backend
        return self.configured_backend if self.configured_backend == NOT_APPLICABLE else UNKNOWN

    @property
    def complete(self) -> bool:
        return self.completion == "finished"

    @property
    def compatibility_key(self) -> str:
        """Stable across commits: what must match for two runs to be compared at all."""

        options = json.dumps(self.options, sort_keys=True, ensure_ascii=False)
        digest = hashlib.sha256(options.encode("utf-8")).hexdigest()[:10]
        return f"{self.kind}/{self.system}-{self.machine}/{self.backend}/{digest}"

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["path"] = self.name
        payload["backend"] = self.backend
        payload["compatibility_key"] = self.compatibility_key
        return payload


def run_identity(run_dir: Path) -> RunIdentity:
    """Recognize one run directory and normalize what it says about itself."""

    run_dir = Path(run_dir)
    metadata, metadata_error = _read_json(run_dir / "metadata.json")
    summary, summary_error = _read_json(run_dir / "summary.json")
    notes = [error for error in (metadata_error, summary_error) if error]

    if (
        isinstance(metadata, dict)
        and metadata.get("mode") in SESSION_KINDS
        and (run_dir / "events.jsonl").is_file()
    ):
        return _session(run_dir, metadata, notes)
    if isinstance(metadata, dict) and "run_id" in metadata and "scenario" in metadata:
        return _campaign(run_dir, metadata, summary, notes)
    if isinstance(summary, dict) and _is_update_summary(summary):
        return _update_check(run_dir, summary, notes)
    return _unknown(run_dir, notes)


def recorded_runs(root: Path | None = None) -> list[Path]:
    """Every directory directly under the runs root, oldest name first."""

    base = RUNS_ROOT if root is None else root
    if not base.is_dir():
        return []
    return sorted(path for path in base.iterdir() if path.is_dir() and not path.is_symlink())


def identities(root: Path | None = None) -> Iterator[RunIdentity]:
    for path in recorded_runs(root):
        yield run_identity(path)


def resolve_name(name: str | Path, root: Path | None = None) -> Path:
    """A run named by a bare directory name or a path inside the runs root.

    Anything that would leave the root -- ``..``, an absolute path elsewhere,
    a symlink -- is refused, so a registry entry can never name another place.
    """

    base = (RUNS_ROOT if root is None else root).resolve()
    candidate = Path(name)
    if not candidate.is_absolute():
        candidate = base / candidate if len(candidate.parts) == 1 else Path.cwd() / candidate
    if candidate.is_symlink():
        raise ValueError(f"{name} is a symbolic link; the lab names only real run directories")
    resolved = candidate.resolve()
    if resolved.parent != base or resolved.name in {"", ".", ".."}:
        raise ValueError(f"{name} is not a run directory directly under {base}")
    return resolved


def run_name(name: str) -> str:
    """Validate a bare run name as stored in the registry."""

    path = Path(name)
    if (
        not name
        or name in {".", ".."}
        or len(path.parts) != 1
        or path.is_absolute()
        or "\\" in name
        or "/" in name
    ):
        raise ValueError(f"{name!r} is not a bare run name")
    return name


def fingerprint(rows: Iterable[Any]) -> str:
    """A short, order-sensitive hash of a plan's rows."""

    payload = json.dumps(list(rows), ensure_ascii=False, sort_keys=True, default=str)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# -- sessions ---------------------------------------------------------------------------


def _session(run_dir: Path, metadata: dict[str, Any], notes: list[str]) -> RunIdentity:
    block = _provenance(metadata)
    events = _session_events(run_dir / "events.jsonl")
    mode = str(metadata["mode"])
    source = block.get("source") if block else None
    if isinstance(source, Mapping):
        commit, state = str(source.get("commit") or UNKNOWN), _state(source)
    else:
        # Before provenance existed, these were read again at shutdown, so a
        # checkout edited during the run would have been recorded instead.
        commit = str(metadata.get("commit") or UNKNOWN)
        state = _state({"dirty": metadata.get("dirty")})
        notes.append("source read at shutdown (recorded before start-time provenance)")
    system, machine = _platform(block, metadata.get("platform"))
    configured = str(
        (block or {}).get("configured_backend")
        or (metadata.get("settings") or {}).get("ocr_backend")
        or UNKNOWN
    )
    observed = tuple(sorted(events["backends"]))
    options = {
        key: _normalized((metadata.get("options") or {}).get(key))
        for key in _SESSION_OPTIONS
        if mode != "run"
    }
    if mode == "stress":
        options["plan"] = metadata.get("plan") or UNKNOWN
    conflicts = _backend_conflicts(configured, observed)
    evidence = _evidence(run_dir, _EVIDENCE["session"])
    if mode == "stress":
        evidence.update(_evidence(run_dir, _EVIDENCE["stress"]))
    return RunIdentity(
        name=run_dir.name,
        path=run_dir,
        kind=mode,
        mode=mode,
        started=str(metadata.get("started") or UNKNOWN),
        commit=commit,
        source_state=state,
        source_changed=_source_changed(block),
        system=system,
        machine=machine,
        configured_backend=configured,
        observed_backends=observed,
        options=options,
        fingerprint=events["fingerprint"] if mode != "run" else NOT_APPLICABLE,
        rules=tuple(sorted(events["rules"])) or ((NOT_APPLICABLE,) if mode == "run" else ()),
        measurement_protocol=str((block or {}).get("measurement_protocol") or UNKNOWN),
        completion=_session_completion(mode, metadata, events),
        evidence=evidence,
        provenance_version=_version(block),
        conflicts=conflicts,
        notes=tuple(notes),
    )


def _session_events(path: Path) -> dict[str, Any]:
    """The few facts identity needs, decoding only lines that can carry them."""

    found: dict[str, Any] = {
        "backends": set(),
        "rules": set(),
        "names": set(),
        "fingerprint": UNKNOWN,
        "results": 0,
        "exit_code": None,
    }
    try:
        stream = path.open(encoding="utf-8")
    except OSError:
        return found
    with stream:
        for line in stream:
            if not any(marker in line for marker in _EVENT_MARKERS):
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict):
                continue
            name = event.get("event")
            found["names"].add(name)
            backend = event.get("ocr_backend")
            if isinstance(backend, str) and backend:
                found["backends"].add(backend)
            if name in {"tour_result", "stress_result"}:
                found["results"] += 1
                rule = event.get("rule")
                # The first tours stored no rule; which one judged them is not on record.
                found["rules"].add(rule if isinstance(rule, str) else UNKNOWN)
            elif name == "tour_planned" and isinstance(event.get("plan_fingerprint"), str):
                found["fingerprint"] = event["plan_fingerprint"]
            elif name == "session_ended":
                found["exit_code"] = event.get("exit_code")
    return found


def _session_completion(mode: str, metadata: Mapping[str, Any], events: Mapping[str, Any]) -> str:
    names = events["names"]
    if mode == "run":
        if "exit_code" not in metadata and "session_ended" not in names:
            return "interrupted"
        return "finished" if metadata.get("exit_code", events["exit_code"]) == 0 else "failed"
    for name, label in (
        ("tour_stopped_by_user", "stopped_by_user"),
        ("tour_aborted", "aborted"),
        ("tour_finished", "finished"),
    ):
        if name in names:
            return label
    return "interrupted"


# -- campaigns and checks -----------------------------------------------------------------


def _campaign(
    run_dir: Path,
    metadata: dict[str, Any],
    summary: Any,
    notes: list[str],
) -> RunIdentity:
    block = _provenance(metadata)
    scenario = _mapping(metadata.get("scenario"))
    config = _mapping(metadata.get("config"))
    kind, mode, options = _campaign_kind(run_dir, scenario, config)
    if block and block.get("kind") and block["kind"] != kind:
        notes.append(f"provenance says {block['kind']}, contents say {kind}")
    source = block.get("source") if block else None
    if isinstance(source, Mapping):
        state = _state(source)
    elif kind == "check" and isinstance(summary, dict) and "source_dirty" in summary:
        state = _state({"dirty": summary.get("source_dirty")})
        notes.append("source state read after the checks ran (recorded before provenance)")
    else:
        state = UNKNOWN
    system, machine = _platform(block, metadata.get("platform"))
    unstated = UNKNOWN if kind == "ocr_campaign" else NOT_APPLICABLE
    configured = str(config.get("backend") or unstated)
    observed = _campaign_backends(run_dir) if kind == "ocr_campaign" else ()
    evidence_key = kind if kind in {"check", "ocr_campaign"} else "measurement"
    return RunIdentity(
        name=run_dir.name,
        path=run_dir,
        kind=kind,
        mode=mode,
        started=str(metadata.get("timestamp") or UNKNOWN),
        commit=str(metadata.get("commit") or UNKNOWN),
        source_state=state,
        source_changed=_source_changed(block),
        system=system,
        machine=machine,
        configured_backend=configured,
        observed_backends=observed,
        options=options,
        fingerprint=_corpus_fingerprint(run_dir) if kind == "ocr_campaign" else NOT_APPLICABLE,
        rules=(NOT_APPLICABLE,),
        measurement_protocol=str(scenario.get("endpoint") or UNKNOWN),
        completion="finished" if isinstance(summary, dict) else "interrupted",
        evidence=_evidence(run_dir, _EVIDENCE[evidence_key]),
        provenance_version=_version(block),
        conflicts=_backend_conflicts(configured, observed),
        notes=tuple(notes),
    )


def _campaign_kind(
    run_dir: Path, scenario: Mapping[str, Any], config: Mapping[str, Any]
) -> tuple[str, str, dict[str, Any]]:
    if "app_lab" in scenario:
        scenarios = sorted(str(item) for item in scenario.get("app_lab") or ())
        return "check", ",".join(scenarios) or UNKNOWN, {"scenarios": scenarios}
    name = str(scenario.get("name") or "")
    if name.startswith("ocr_") and (run_dir / "corpus-inventory.json").exists():
        options = {
            key: _normalized(config.get(key))
            for key in ("mode", "warmup", "samples", "iou_threshold", "cpu_threads", "repeats")
            if key in config
        }
        return "ocr_campaign", str(config.get("mode") or name), options
    for prefix, kind in (
        ("real_lookup", "real_lookup"),
        ("real_hover", "real_hover"),
        ("live_hover", "live_hover"),
    ):
        if name.startswith(prefix):
            return kind, name, {"scenario": name}
    return UNKNOWN, name or UNKNOWN, {}


def _campaign_backends(run_dir: Path) -> tuple[str, ...]:
    found: set[str] = set()
    try:
        with (run_dir / "samples.jsonl").open(encoding="utf-8") as stream:
            for line in stream:
                try:
                    backend = json.loads(line).get("backend")
                except (ValueError, AttributeError):
                    continue
                if isinstance(backend, str):
                    found.add(backend)
    except OSError:
        return ()
    return tuple(sorted(found))


def _corpus_fingerprint(run_dir: Path) -> str:
    inventory, _ = _read_json(run_dir / "corpus-inventory.json")
    if not isinstance(inventory, dict):
        return UNKNOWN
    stated = inventory.get("fingerprint")
    if isinstance(stated, str):
        return stated
    # Older inventories carry only counts, which identify the slice but not its images.
    return UNKNOWN


# -- update checks --------------------------------------------------------------------------


def _is_update_summary(summary: Mapping[str, Any]) -> bool:
    return (
        summary.get("mode") in {"install", "cancel", "rollback"}
        and "source_tag" in summary
        and "remnants" in summary
        and isinstance(summary.get("events"), list)
    )


def _update_check(run_dir: Path, summary: dict[str, Any], notes: list[str]) -> RunIdentity:
    block = _provenance(summary)
    source = block.get("source") if block else None
    system, machine = _platform(block, None)
    return RunIdentity(
        name=run_dir.name,
        path=run_dir,
        kind="update_check",
        mode=str(summary.get("mode")),
        started=str((block or {}).get("started") or UNKNOWN),
        commit=str(source.get("commit") or UNKNOWN) if isinstance(source, Mapping) else UNKNOWN,
        source_state=_state(source) if isinstance(source, Mapping) else UNKNOWN,
        source_changed=_source_changed(block),
        system=system,
        machine=machine,
        configured_backend=NOT_APPLICABLE,
        observed_backends=(),
        options={"mode": summary.get("mode"), "source_tag": summary.get("source_tag")},
        fingerprint=NOT_APPLICABLE,
        rules=(NOT_APPLICABLE,),
        measurement_protocol=NOT_APPLICABLE,
        completion="finished" if "passed" in summary else "interrupted",
        evidence=_evidence(run_dir, _EVIDENCE["update_check"]),
        provenance_version=_version(block),
        notes=tuple(notes),
    )


def _unknown(run_dir: Path, notes: list[str]) -> RunIdentity:
    return RunIdentity(
        name=run_dir.name,
        path=run_dir,
        kind=UNKNOWN,
        mode=UNKNOWN,
        started=UNKNOWN,
        commit=UNKNOWN,
        source_state=UNKNOWN,
        source_changed=UNKNOWN,
        system=UNKNOWN,
        machine=UNKNOWN,
        configured_backend=UNKNOWN,
        observed_backends=(),
        options={},
        fingerprint=UNKNOWN,
        rules=(),
        measurement_protocol=UNKNOWN,
        completion=UNKNOWN,
        evidence={},
        provenance_version=None,
        notes=tuple(notes),
    )


# -- shared readers ---------------------------------------------------------------------


def _read_json(path: Path) -> tuple[Any, str | None]:
    if not path.is_file():
        return None, None
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, ValueError) as error:
        return None, f"{path.name} unreadable ({type(error).__name__})"


def _provenance(record: Mapping[str, Any]) -> dict[str, Any] | None:
    block = record.get("lab_provenance")
    return block if isinstance(block, dict) else None


def _version(block: Mapping[str, Any] | None) -> int | None:
    value = (block or {}).get("version")
    return value if isinstance(value, int) else None


def _state(source: Mapping[str, Any] | None) -> str:
    if not isinstance(source, Mapping):
        return UNKNOWN
    state = source.get("state")
    if state in {"clean", "dirty", "unknown"}:
        return str(state)
    dirty = source.get("dirty")
    return UNKNOWN if not isinstance(dirty, bool) else "dirty" if dirty else "clean"


def _source_changed(block: Mapping[str, Any] | None) -> Any:
    if not block or "source_at_end" not in block:
        return NOT_APPLICABLE if block else UNKNOWN
    changed = block.get("source_changed")
    return UNKNOWN if changed is None else bool(changed)


def _platform(block: Mapping[str, Any] | None, recorded: Any) -> tuple[str, str]:
    stated = (block or {}).get("platform")
    if isinstance(stated, Mapping):
        return str(stated.get("system") or UNKNOWN), str(stated.get("machine") or UNKNOWN)
    if isinstance(recorded, Mapping):
        return str(recorded.get("system") or UNKNOWN), str(recorded.get("machine") or UNKNOWN)
    if isinstance(recorded, str) and recorded.split():
        # Sessions wrote "System release machine" before provenance existed.
        parts = recorded.split()
        return parts[0], parts[-1] if len(parts) > 1 else UNKNOWN
    return UNKNOWN, UNKNOWN


def _backend_conflicts(configured: str, observed: tuple[str, ...]) -> tuple[str, ...]:
    conflicts = []
    if len(observed) > 1:
        conflicts.append(f"more than one OCR backend observed: {', '.join(observed)}")
    if configured in {"vision", "easyocr"} and observed and set(observed) != {configured}:
        conflicts.append(f"configured {configured} but observed {', '.join(observed)}")
    return tuple(conflicts)


def _evidence(run_dir: Path, names: Iterable[str]) -> dict[str, bool]:
    return {name: (run_dir / name).exists() for name in names}


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _normalized(value: Any) -> Any:
    return list(value) if isinstance(value, tuple) else value


__all__ = [
    "KINDS",
    "LAB_ROOT",
    "NOT_APPLICABLE",
    "REPO_ROOT",
    "RUNS_ROOT",
    "UNKNOWN",
    "RunIdentity",
    "fingerprint",
    "identities",
    "recorded_runs",
    "resolve_name",
    "run_identity",
    "run_name",
]
