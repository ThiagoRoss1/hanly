"""Record everything the running desktop reports, without slowing it down.

The desktop's trace seam, its diagnostics log and the lab's own driver all feed
one ``LabRecorder``. Producers only timestamp and enqueue; a daemon thread
writes ``events.jsonl``. Listeners (the tour driver, the HUD) see each event
synchronously and must return promptly.

``events.jsonl`` never holds recognized text or OCR geometry, whatever the
session. Listeners see those fields in memory; only the tour driver keeps any of
it, derived and bound to one verified hover (``driver.py``).
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from hanly_app.diagnostics import DiagnosticLog, RotatingLogFile, sanitize_text
from hanly_app.lookup.evidence import EVIDENCE_FIELDS as _APP_EVIDENCE_FIELDS

from ..live_telemetry import LiveTraceRecorder

#: Fields that carry recognized text or where text sits on screen.
CONTENT_FIELDS = frozenset(_APP_EVIDENCE_FIELDS) | {"ocr_boxes"}
_ALIASES = frozenset({"event", "event_kind", "monotonic_ns", "timestamp_ns", "thread_ident"})


def is_content_field(key: str) -> bool:
    """Whether a trace field may carry screen content; unknown evidence fails closed."""

    return key in CONTENT_FIELDS or key.endswith("_evidence")

_STARTUP_PHASE = re.compile(r"^(?P<name>.+?): (?P<ms>\d+) ms \((?P<outcome>[^)]*)\)$")
_STARTUP_MILESTONE = re.compile(r"^(?P<name>.+?) at (?P<ms>\d+) ms$")

Listener = Callable[[str, int, Mapping[str, Any]], None]


class LabRecorder:
    """The desktop's ``RuntimeTraceSink``, extended with lab-owned events.

    ``retain_evidence``/``retain_geometry`` are the attributes the production
    composition reads to decide whether to attach evidence to stage events.
    """

    def __init__(self, path: Path, *, retain_evidence: bool, retain_geometry: bool) -> None:
        self.retain_evidence = retain_evidence
        self.retain_geometry = retain_geometry
        self.origin_ns = time.perf_counter_ns()
        self._recorder = LiveTraceRecorder(path, queue_size=65_536)
        self._listeners: list[Listener] = []
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {}

    @property
    def dropped_events(self) -> int:
        return self._recorder.dropped_events

    @property
    def counts(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counts)

    def subscribe(self, listener: Listener) -> None:
        with self._lock:
            self._listeners.append(listener)

    def emit(self, event: Mapping[str, Any]) -> object:
        """Consume one production trace event."""

        name = event.get("event_kind", event.get("event"))
        if not isinstance(name, str):
            return None
        stamp = event.get("timestamp_ns", event.get("monotonic_ns"))
        observed = stamp if isinstance(stamp, int) else time.perf_counter_ns()
        fields = {key: value for key, value in event.items() if key not in _ALIASES}
        self._publish(name, observed, fields, source="app")
        return None

    def lab(self, event: str, /, **fields: Any) -> None:
        """Record an event the lab itself caused or observed."""

        self._publish(event, time.perf_counter_ns(), fields, source="lab")

    def close(self) -> None:
        self._recorder.close(timeout=5.0)

    def _publish(self, name: str, observed: int, fields: dict[str, Any], *, source: str) -> None:
        with self._lock:
            self._counts[name] = self._counts.get(name, 0) + 1
            listeners = tuple(self._listeners)
        durable = {key: value for key, value in fields.items() if not is_content_field(key)}
        self._recorder.record_at(
            name, observed, by=source, t_ms=(observed - self.origin_ns) / 1e6, **durable
        )
        for listener in listeners:
            try:
                listener(name, observed, fields)
            except Exception:
                # A broken listener is a lab bug; it must never become an app failure.
                continue


class LabDiagnosticLog(DiagnosticLog):
    """The session log, also mirrored into the lab timeline.

    Startup phases become structured events so the report can draw them. Other
    lines keep their subsystem and level, with the user's home directory and
    secrets removed, as an exported diagnostics bundle would.
    """

    def __init__(self, recorder: LabRecorder, log_file: Path) -> None:
        super().__init__(RotatingLogFile(log_file))
        self._lab = recorder

    def record(self, subsystem: str, message: str, *, level: str = "info") -> None:
        super().record(subsystem, message, level=level)
        text = str(message).strip()
        if subsystem == "Startup":
            phase = _STARTUP_PHASE.match(text)
            if phase is not None:
                self._lab.lab(
                    "startup_phase",
                    name=phase["name"],
                    duration_ms=int(phase["ms"]),
                    outcome=phase["outcome"],
                )
                return
            milestone = _STARTUP_MILESTONE.match(text)
            if milestone is not None:
                self._lab.lab(
                    "startup_milestone", name=milestone["name"], at_ms=int(milestone["ms"])
                )
                return
        self._lab.lab(
            "diagnostic",
            subsystem=str(subsystem),
            level=level,
            message=sanitize_text(text)[:240],
        )


__all__ = ["CONTENT_FIELDS", "LabDiagnosticLog", "LabRecorder", "is_content_field"]
