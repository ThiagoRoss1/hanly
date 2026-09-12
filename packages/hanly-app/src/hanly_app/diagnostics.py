"""Durable desktop diagnostics: an in-memory tail plus a rotating log file.

A windowed packaged build has no console, so a failure that only reaches
stderr is invisible. Everything Hanly reports about its own startup therefore
goes through :class:`DiagnosticLog`: the Control Center reads the recent tail,
and the same records land in a rotating file the user can send on.

Captured screen images and recognized text are never written here.
"""

from __future__ import annotations

import os
import platform
import re
import sys
import threading
import traceback
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic

from .paths import default_log_directory

#: Base name of the current session's log inside the diagnostics directory.
LOG_FILE_NAME = "hanly.log"

#: Rotation bounds. Small enough to attach to a report, large enough to hold a
#: full provisioning session with tracebacks.
MAX_LOG_BYTES = 512 * 1024
LOG_BACKUP_COUNT = 3

#: How many records the Control Center's diagnostics panel can show.
MEMORY_LIMIT = 500

#: Upper bound on one record. A provider can produce a very long message, and
#: neither the panel nor the rotating file should be filled by one of them.
MAX_RECORD_CHARS = 2000

#: What a record without a named subsystem belongs to.
DEFAULT_SUBSYSTEM = "app"

#: Levels a record can carry, in the order a filter offers them.
LEVELS = ("info", "warning", "error")

DiagnosticSink = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class DiagnosticRecord:
    """One thing Hanly reported about itself, with enough to filter on.

    ``display`` is what the one-line surfaces already showed, kept identical so
    that adding structure changed nothing about what a user reads.
    """

    timestamp: str
    level: str
    subsystem: str
    message: str

    @property
    def display(self) -> str:
        if self.subsystem == DEFAULT_SUBSYSTEM:
            return self.message
        return f"{self.subsystem}: {self.message}"

    def to_dict(self) -> dict[str, str]:
        return {
            "timestamp": self.timestamp,
            "level": self.level,
            "subsystem": self.subsystem,
            "message": self.message,
        }


class RotatingLogFile:
    """A size-bounded, lock-protected append-only text file.

    Rotation keeps ``hanly.log`` current and moves older content to
    ``hanly.log.1`` and up. Writes never raise: an unwritable profile
    directory degrades diagnostics, it does not stop the desktop.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        max_bytes: int = MAX_LOG_BYTES,
        backup_count: int = LOG_BACKUP_COUNT,
    ) -> None:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        if backup_count < 0:
            raise ValueError("backup_count must not be negative")

        self._path = Path(path)
        self._max_bytes = max_bytes
        self._backup_count = backup_count
        self._lock = threading.RLock()
        self._failed = False

    @property
    def path(self) -> Path:
        return self._path

    @property
    def usable(self) -> bool:
        """Whether writes are still reaching the file."""

        with self._lock:
            return not self._failed

    def write(self, record: str) -> None:
        """Append one record, rotating first when the file is already full."""

        payload = _bounded(record)
        payload = payload if payload.endswith("\n") else f"{payload}\n"
        with self._lock:
            if self._failed:
                return
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                self._rotate_if_full(len(payload.encode("utf-8")))
                with self._path.open("a", encoding="utf-8", newline="\n") as stream:
                    stream.write(payload)
                    stream.flush()
            except OSError:
                # One unwritable profile directory is reported once, through
                # the in-memory tail, and then stops costing an attempt per
                # record.
                self._failed = True

    def _rotate_if_full(self, incoming_bytes: int) -> None:
        try:
            current_size = self._path.stat().st_size
        except OSError:
            return
        if current_size + incoming_bytes <= self._max_bytes:
            return

        if self._backup_count == 0:
            # Keeping no backups still has to bound the file. Without this the
            # current log simply grows for ever, which is the one outcome
            # rotation exists to prevent.
            self._path.unlink(missing_ok=True)
            return

        for index in range(self._backup_count, 0, -1):
            source = self._path if index == 1 else self._backup(index - 1)
            destination = self._backup(index)
            if source.exists():
                destination.unlink(missing_ok=True)
                source.replace(destination)

    def _backup(self, index: int) -> Path:
        return self._path.with_name(f"{self._path.name}.{index}")


class DiagnosticLog:
    """Thread-safe diagnostics shared with the Control Center and the log file.

    ``add`` records the one-line form both surfaces show; ``report`` adds the
    chained traceback to the file only, keeping the UI list readable while the
    original cause survives for a bug report.
    """

    def __init__(
        self,
        file: RotatingLogFile | None = None,
        *,
        limit: int = MEMORY_LIMIT,
    ) -> None:
        if limit <= 0:
            raise ValueError("limit must be positive")

        self._lock = threading.RLock()
        self._records: list[DiagnosticRecord] = []
        self._file = file
        self._limit = limit

    @property
    def file(self) -> RotatingLogFile | None:
        """The rotating file this log also writes to, when one is installed."""

        return self._file

    @property
    def path(self) -> Path | None:
        """Where a user can find the durable log, if there is one."""

        return None if self._file is None else self._file.path

    def add(self, message: str) -> None:
        """Record one unattributed line, the way every caller already did."""

        self.record(DEFAULT_SUBSYSTEM, message)

    def record(self, subsystem: str, message: str, *, level: str = "info") -> None:
        """Record one line against the part of Hanly that produced it."""

        normalized = _bounded(str(message).strip())
        if not normalized:
            return
        entry = DiagnosticRecord(
            timestamp=_timestamp(),
            level=level if level in LEVELS else "info",
            subsystem=_bounded(str(subsystem).strip() or DEFAULT_SUBSYSTEM, 80),
            message=normalized,
        )
        with self._lock:
            self._records.append(entry)
            if len(self._records) > self._limit:
                del self._records[: len(self._records) - self._limit]
        self._write(f"[{entry.level}] {entry.display}", timestamp=entry.timestamp)

    def report(self, stage: str, error: BaseException) -> None:
        """Record a failure: one line for the UI, the full chain for the file."""

        self.record(stage, str(error), level="error")
        self._write(_formatted_traceback(stage, error))

    def snapshot(self) -> tuple[str, ...]:
        """The one-line tail the Control Center has always shown."""

        with self._lock:
            return tuple(entry.display for entry in self._records)

    def records(self) -> tuple[DiagnosticRecord, ...]:
        """The same tail, with the level and subsystem a filter needs."""

        with self._lock:
            return tuple(self._records)

    def clear(self) -> None:
        """Forget the in-memory tail; the rotating file is separate."""

        with self._lock:
            self._records.clear()

    def _write(self, record: str, *, timestamp: str | None = None) -> None:
        if self._file is None:
            return
        self._file.write(f"{timestamp or _timestamp()} {record}")


class StartupTimeline:
    """Record how long each named startup phase took, into the session log.

    These are diagnostics, not an SLA: they exist so a launch that felt slow
    can be read back from the log a user already sends. A timeline without a
    log records nothing, which is what a component with no diagnostics wants.
    """

    def __init__(
        self,
        log: DiagnosticLog | None = None,
        *,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._log = log
        self._clock = clock
        self._started = clock()

    @contextmanager
    def phase(self, name: str, *, attempt: int | None = None) -> Iterator[None]:
        """Time one phase, recording a failure with the same duration."""

        started = self._clock()
        try:
            yield
        except BaseException as error:
            self.mark(
                name,
                self._clock() - started,
                outcome=f"failed: {type(error).__name__}",
                attempt=attempt,
            )
            raise
        self.mark(name, self._clock() - started, attempt=attempt)

    def mark(
        self,
        name: str,
        seconds: float,
        *,
        outcome: str = "ok",
        attempt: int | None = None,
    ) -> None:
        """Record an already-measured phase, such as one timed before this log."""

        if self._log is None:
            return
        detail = outcome if attempt is None else f"{outcome}, attempt {attempt}"
        self._log.record("Startup", f"{name}: {seconds * 1000:.0f} ms ({detail})")

    def reached(self, name: str) -> None:
        """Record a milestone as elapsed time, not as a cost of its own."""

        if self._log is None:
            return
        elapsed = (self._clock() - self._started) * 1000
        self._log.record("Startup", f"{name} at {elapsed:.0f} ms")


def open_diagnostics(
    directory: str | Path | None = None,
    *,
    versions: Mapping[str, str] | None = None,
) -> DiagnosticLog:
    """Start a session log in the per-user diagnostics directory.

    Call this before any native runtime is initialized, so a failure during
    OCR preload or Qt startup is already being recorded. An unwritable
    location returns a memory-only log rather than failing the launch.
    """

    root = Path(directory) if directory is not None else default_log_directory()
    log = DiagnosticLog(RotatingLogFile(root / LOG_FILE_NAME))
    log.add(f"Hanly session started; diagnostics log: {log.path}")
    for name, value in (versions or runtime_versions()).items():
        log.add(f"version {name}: {value}")
    if log.file is not None and not log.file.usable:
        return DiagnosticLog()
    return log


def runtime_versions(packages: Iterable[str] = ()) -> dict[str, str]:
    """Collect the identities a diagnostics reader needs to reproduce a run."""

    from importlib.metadata import PackageNotFoundError, version

    names = tuple(packages) or (
        "hanly",
        "hanly-app",
        "PyQt6",
        "PyQt6-WebEngine",
        "pywebview",
        "pystray",
        "easyocr",
        "torch",
        "kiwipiepy",
    )
    collected = {
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "frozen": str(bool(getattr(sys, "frozen", False))),
    }
    for name in names:
        try:
            collected[name] = version(name)
        except PackageNotFoundError:
            collected[name] = "not installed"
    return collected


#: Field names whose value is never worth sharing, whatever it holds.
_SECRET_HINTS = ("token", "secret", "password", "credential", "api_key", "apikey")


def sanitize_text(text: str, *, home: Path | None = None) -> str:
    """Make one line safe to hand to somebody else.

    An exported bundle leaves the machine, so the user's own directory names go
    with it unless they are removed. The local rotating log is deliberately not
    put through this: it stays on the machine, and a debuggable absolute path
    is exactly what makes it worth keeping.
    """

    cleaned = str(text)
    root = str(home if home is not None else Path.home())
    if root and root != os.sep:
        cleaned = cleaned.replace(root, "~")
    return _redact_secrets(cleaned)


def _redact_secrets(text: str) -> str:
    """Replace anything that reads as a credential with a marker."""

    lowered = text.lower()
    if not any(hint in lowered for hint in _SECRET_HINTS):
        return text
    parts = re.split(r"([=:]\s*)", text)
    for index in range(0, len(parts) - 2, 2):
        if any(hint in parts[index].lower() for hint in _SECRET_HINTS):
            parts[index + 2] = "[redacted]"
    return "".join(parts)


def sanitize_value(value: object, *, home: Path | None = None) -> object:
    """Sanitize a JSON-shaped value, keeping its structure."""

    if isinstance(value, str):
        return sanitize_text(value, home=home)
    if isinstance(value, Mapping):
        return {
            str(key): (
                "[redacted]"
                if any(hint in str(key).lower() for hint in _SECRET_HINTS)
                else sanitize_value(item, home=home)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_value(item, home=home) for item in value]
    return value


def diagnostics_bundle(
    records: Iterable[DiagnosticRecord],
    *,
    state: Mapping[str, object] | None = None,
    versions: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> dict[str, object]:
    """Build the report a user can attach to a message about a problem.

    It carries what makes a failure reproducible -- versions, platform, whether
    this is a packaged build, the preferences that change behaviour, resource
    and engine state, and the recent records -- and nothing about what was on
    the screen. Hanly never writes captured pixels or recognized text into
    diagnostics, so there is none here to remove.
    """

    return {
        "generated": _timestamp(),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": sys.version.split()[0],
            "frozen": bool(getattr(sys, "frozen", False)),
        },
        "versions": dict(versions or runtime_versions()),
        "state": sanitize_value(dict(state or {}), home=home),
        "records": [
            sanitize_value(record.to_dict(), home=home) for record in records
        ],
    }


def install_qt_message_handler(log: DiagnosticLog) -> bool:
    """Route Qt's own messages into the log, flushing fatals before the abort.

    Qt writes its fatal diagnostics to stderr and then aborts the process,
    which in a windowed build means the message is lost exactly when it
    matters most. Returns whether the handler could be installed.
    """

    try:
        from PyQt6.QtCore import QtMsgType, qInstallMessageHandler
    except ImportError:
        return False

    def handler(mode: object, _context: object, message: object) -> None:
        text = f"Qt {getattr(mode, 'name', mode)}: {message}"
        log.add(text)
        if mode is QtMsgType.QtFatalMsg:
            _flush_standard_streams()

    qInstallMessageHandler(handler)
    return True


def _formatted_traceback(stage: str, error: BaseException) -> str:
    chain = "".join(
        traceback.format_exception(type(error), error, error.__traceback__)
    ).rstrip()
    return f"{stage} traceback:\n{chain}"


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _bounded(text: str, limit: int = MAX_RECORD_CHARS) -> str:
    """Keep one record inside its own bound, saying that it was cut."""

    if len(text) <= limit:
        return text
    return f"{text[: limit - 1]}\u2026"


def _flush_standard_streams() -> None:
    """Flush stdout/stderr, tolerating the absent streams of a windowed build."""

    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None:
                stream.flush()
        except (OSError, ValueError):
            continue


__all__ = [
    "DEFAULT_SUBSYSTEM",
    "LEVELS",
    "LOG_BACKUP_COUNT",
    "LOG_FILE_NAME",
    "MAX_LOG_BYTES",
    "MAX_RECORD_CHARS",
    "MEMORY_LIMIT",
    "DiagnosticLog",
    "DiagnosticRecord",
    "DiagnosticSink",
    "StartupTimeline",
    "RotatingLogFile",
    "diagnostics_bundle",
    "install_qt_message_handler",
    "open_diagnostics",
    "runtime_versions",
    "sanitize_text",
    "sanitize_value",
]
