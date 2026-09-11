"""Removing what Hanly left behind, and nothing else.

Every temporary directory Hanly creates is a small bet that the process will
live long enough to clean it up. A crash, a forced quit, or a rejected update
loses that bet, and the leftovers accumulate in a profile nobody looks at.

This removes them, under rules chosen so that the failure mode is always
leaving something behind rather than deleting something that mattered:

* New work happens under one clearly identified root, in a directory carrying a
  marker with a version, the owner's process identity, and what it was doing.
* A marked directory is reaped only once its owner is gone and it is old
  enough, which means a recycled process id can only make Hanly keep a
  directory, never remove a live one.
* Symlinks are refused outright, and so is any path that does not resolve
  inside the root it was found in.
* A staged update that still holds the only copy of a working installation is
  reported as needing recovery and left exactly where it is. Disk is never a
  reason to delete somebody's last working Hanly.

There is no periodic collection and no sweep of caches Hanly does not own: this
runs at startup and after an operation completes.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

#: Written inside every directory this module is allowed to remove.
MARKER_NAME = ".hanly-owned.json"
MARKER_VERSION = 1

#: How long an abandoned directory must have existed before it is reaped. Long
#: enough that an operation which is merely slow is never mistaken for a dead
#: one.
MIN_AGE_SECONDS = 3600.0

#: Statuses a marked directory can carry.
ACTIVE = "active"
COMPLETE = "complete"
RECOVERY_REQUIRED = "recovery-required"

#: Inside an update transaction, either of these is a copy of an installation
#: that has not been put back. Never remove one to save disk.
UNRESOLVED_UPDATE_ENTRIES = ("previous", "rejected")


class CleanupError(RuntimeError):
    """Raised when a caller asks for a directory this module must not touch."""


@dataclass(frozen=True, slots=True)
class OwnedDirectory:
    """A directory Hanly created, and what it was doing in it."""

    path: Path
    operation: str
    owner_pid: int
    created: float
    status: str = ACTIVE

    def to_marker(self) -> dict[str, object]:
        return {
            "version": MARKER_VERSION,
            "operation": self.operation,
            "owner_pid": self.owner_pid,
            "created": self.created,
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class CleanupReport:
    """What one sweep did, in terms a diagnostics reader can act on."""

    removed: tuple[Path, ...] = ()
    preserved: tuple[Path, ...] = ()
    recovery_required: tuple[Path, ...] = ()
    failures: tuple[tuple[Path, str], ...] = ()

    def merged(self, other: CleanupReport) -> CleanupReport:
        return CleanupReport(
            removed=self.removed + other.removed,
            preserved=self.preserved + other.preserved,
            recovery_required=self.recovery_required + other.recovery_required,
            failures=self.failures + other.failures,
        )

    def messages(self) -> tuple[str, ...]:
        """Say only what is worth saying: removals are routine, losses are not."""

        lines: list[str] = []
        if self.removed:
            lines.append(f"Cleaned up {len(self.removed)} leftover working directories.")
        for path in self.recovery_required:
            lines.append(
                f"An interrupted update still holds a copy of a previous Hanly in "
                f"{path.name}; it was kept rather than removed."
            )
        for path, reason in self.failures:
            lines.append(f"Could not remove {path.name}: {reason}")
        return tuple(lines)


@dataclass(frozen=True, slots=True)
class StagingLocation:
    """Somewhere Hanly is known to create disposable directories."""

    root: Path
    prefix: str
    #: Entries whose presence means this directory is the only copy of
    #: something the user cannot lose.
    keep_if_present: tuple[str, ...] = field(default=())


class OwnedWorkspace:
    """Hanly's own scratch root: everything under it is Hanly's to remove."""

    def __init__(
        self,
        root: Path,
        *,
        min_age_seconds: float = MIN_AGE_SECONDS,
        clock: object = time.time,
    ) -> None:
        self._root = Path(root)
        self._min_age = float(min_age_seconds)
        self._clock = clock

    @property
    def root(self) -> Path:
        return self._root

    def open(self, operation: str) -> OwnedDirectory:
        """Claim a directory for one operation, marked as this process's."""

        if not operation or "/" in operation or "\\" in operation:
            raise CleanupError("an operation name must be one plain path segment")
        created = _now(self._clock)
        directory = self._root / f"{operation}-{os.getpid()}-{int(created)}"
        directory.mkdir(parents=True, exist_ok=True)
        owned = OwnedDirectory(
            path=directory,
            operation=operation,
            owner_pid=os.getpid(),
            created=created,
        )
        _write_marker(owned)
        return owned

    def complete(self, owned: OwnedDirectory) -> None:
        """Remove a finished operation's directory at once."""

        self._require_inside(owned.path)
        _remove_tree(owned.path)

    def require_recovery(self, owned: OwnedDirectory, reason: str) -> None:
        """Keep a directory and say why, so no later sweep reclaims it."""

        self._require_inside(owned.path)
        _write_marker(
            OwnedDirectory(
                path=owned.path,
                operation=owned.operation,
                owner_pid=owned.owner_pid,
                created=owned.created,
                status=RECOVERY_REQUIRED,
            ),
            note=reason,
        )

    def sweep(self) -> CleanupReport:
        """Remove marked directories whose owner is gone and which are old."""

        if not self._root.is_dir():
            return CleanupReport()
        removed: list[Path] = []
        preserved: list[Path] = []
        recovery: list[Path] = []
        failures: list[tuple[Path, str]] = []
        now = _now(self._clock)

        for candidate in sorted(self._safe_children(self._root)):
            marker = _read_marker(candidate)
            if marker is None:
                preserved.append(candidate)
                continue
            if marker.get("status") == RECOVERY_REQUIRED:
                recovery.append(candidate)
                continue
            if not self._reapable(marker, now):
                preserved.append(candidate)
                continue
            failure = _remove_tree(candidate)
            if failure is None:
                removed.append(candidate)
            else:
                failures.append((candidate, failure))

        return CleanupReport(
            removed=tuple(removed),
            preserved=tuple(preserved),
            recovery_required=tuple(recovery),
            failures=tuple(failures),
        )

    def _reapable(self, marker: dict[str, object], now: float) -> bool:
        """Only a directory whose owner is gone and which has aged out."""

        created = marker.get("created")
        owner = marker.get("owner_pid")
        if not isinstance(created, (int, float)) or not isinstance(owner, int):
            return False
        if now - float(created) < self._min_age:
            return False
        if marker.get("status") == COMPLETE:
            return True
        return not _process_alive(int(owner))

    def _safe_children(self, root: Path) -> Iterable[Path]:
        for child in root.iterdir():
            if child.is_symlink() or not child.is_dir():
                continue
            try:
                self._require_inside(child)
            except CleanupError:
                continue
            yield child

    def _require_inside(self, path: Path) -> None:
        """Refuse anything that does not resolve inside the managed root."""

        resolved_root = self._root.resolve()
        try:
            resolved = path.resolve()
        except OSError as error:
            raise CleanupError(f"{path} cannot be resolved: {error}") from error
        if resolved == resolved_root or resolved_root not in resolved.parents:
            raise CleanupError(f"{path} is not inside {self._root}")


def sweep_staging(
    locations: Sequence[StagingLocation],
    *,
    min_age_seconds: float = MIN_AGE_SECONDS,
    clock: object = time.time,
) -> CleanupReport:
    """Reap abandoned staging in the places Hanly is known to create it.

    These directories predate the marker, so ownership cannot be read from
    them: age is the only evidence, and anything holding a copy of something
    irreplaceable is reported instead of removed.
    """

    report = CleanupReport()
    now = _now(clock)
    for location in locations:
        report = report.merged(_sweep_one(location, now, min_age_seconds))
    return report


def _sweep_one(
    location: StagingLocation, now: float, min_age_seconds: float
) -> CleanupReport:
    if not location.root.is_dir():
        return CleanupReport()

    removed: list[Path] = []
    preserved: list[Path] = []
    recovery: list[Path] = []
    failures: list[tuple[Path, str]] = []
    root = location.root.resolve()

    for candidate in sorted(location.root.glob(f"{location.prefix}*")):
        if candidate.is_symlink() or not candidate.is_dir():
            continue
        if candidate.resolve().parent != root:
            continue
        if any((candidate / name).exists() for name in location.keep_if_present):
            recovery.append(candidate)
            continue
        if not _older_than(candidate, now, min_age_seconds):
            preserved.append(candidate)
            continue
        failure = _remove_tree(candidate)
        if failure is None:
            removed.append(candidate)
        else:
            failures.append((candidate, failure))

    return CleanupReport(
        removed=tuple(removed),
        preserved=tuple(preserved),
        recovery_required=tuple(recovery),
        failures=tuple(failures),
    )


def update_staging_locations(
    install_root: Path | None, temporary_root: Path
) -> tuple[StagingLocation, ...]:
    """Name the places an interrupted update leaves work behind.

    The staged build sits beside the installation so the swap is a rename, and
    the handoff script sits in the system temporary directory so it can delete
    the transaction it is finishing. Both outlive a process that is killed.
    """

    locations = [StagingLocation(root=temporary_root, prefix="hanly-update.")]
    if install_root is not None:
        locations.append(
            StagingLocation(
                root=install_root.parent,
                prefix=".hanly-update-",
                keep_if_present=UNRESOLVED_UPDATE_ENTRIES,
            )
        )
    return tuple(locations)


def _older_than(path: Path, now: float, min_age_seconds: float) -> bool:
    try:
        return now - path.stat().st_mtime >= min_age_seconds
    except OSError:
        return False


def _write_marker(owned: OwnedDirectory, note: str = "") -> None:
    payload = owned.to_marker()
    if note:
        payload["note"] = note
    marker = owned.path / MARKER_NAME
    try:
        marker.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    except OSError as error:
        raise CleanupError(f"could not mark {owned.path}: {error}") from error


def _read_marker(directory: Path) -> dict[str, object] | None:
    """Read a directory's own claim of ownership, or refuse to touch it."""

    marker = directory / MARKER_NAME
    if marker.is_symlink() or not marker.is_file():
        return None
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("version") != MARKER_VERSION:
        return None
    return payload


def _process_alive(pid: int) -> bool:
    """Whether a process id is in use right now.

    A recycled id belonging to something else answers yes, which keeps the
    directory. That is the error worth making.
    """

    if pid <= 0:
        return False
    if os.name == "nt":
        return _windows_process_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Somebody else's process holds the id, so it is certainly in use.
        return True
    except OSError:
        return True
    return True


def _windows_process_alive(pid: int) -> bool:
    import ctypes

    process_query_limited_information = 0x1000
    still_active = 259
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return True
        return code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def _remove_tree(path: Path) -> str | None:
    """Remove a directory, returning why it could not be removed."""

    if path.is_symlink():
        return "it is a symbolic link"
    try:
        shutil.rmtree(path)
    except FileNotFoundError:
        return None
    except OSError as error:
        return str(error)
    return None


def _now(clock: object) -> float:
    return float(clock() if callable(clock) else time.time())


__all__ = [
    "ACTIVE",
    "COMPLETE",
    "MARKER_NAME",
    "MARKER_VERSION",
    "MIN_AGE_SECONDS",
    "RECOVERY_REQUIRED",
    "UNRESOLVED_UPDATE_ENTRIES",
    "CleanupError",
    "CleanupReport",
    "OwnedDirectory",
    "OwnedWorkspace",
    "StagingLocation",
    "sweep_staging",
    "update_staging_locations",
]
