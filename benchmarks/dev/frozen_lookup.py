"""Hold recent lookups in memory so one of them can be pinned and inspected.

The point of a hover popup is that it disappears. That makes a wrong answer
almost impossible to study: by the time you have read it, the cursor has moved
and the next lookup has replaced everything. Freezing pins one completed lookup
so its pixels, geometry, decisions, and outputs stay inspectable afterwards.

**Freezing writes nothing.** Real screen pixels, recognized text, and provider
crops live in this bounded ring and nowhere else; they disappear with the
process. Persisting any of it is a separate explicit export, which is the only
thing in this package that touches the gitignored artifact root.

Correlation is by identifier. A capture arrives with the hover request it was
taken for, ``hover_submission`` joins that hover to a lookup, and every later
stage names the lookup. Nothing here depends on the order events happen to
arrive in.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from hanly import ROIImage
from hanly_app.capture import CapturePlan, CaptureResult, ScreenRect
from hanly_app.lookup_evidence import decode_evidence

#: How many recent lookups stay inspectable. Each one holds one ROI (about
#: 60 KB at the production size) plus its events, so this is a few megabytes.
DEFAULT_RING_SIZE = 24

#: Events that end a lookup. A record with one of these is coherent enough to
#: freeze; one without is still in flight and would freeze a partial answer.
TERMINAL_EVENTS = frozenset(
    {
        "popup_visible",
        "popup_suppressed",
        "lookup_stale_suppressed",
        "lookup_current_delivered",
        "lookup_error",
        "lookup_cancelled_early",
        "hover_capture_error",
        "hover_submission_error",
    }
)

#: Which stage event carries which decoded evidence payload.
_STAGE_EVIDENCE = {
    "ocr": "ocr_evidence",
    "token_selection": "resolution_evidence",
    "morphology": "morphology_evidence",
    "dictionary": "dictionary_evidence",
}


@dataclass(frozen=True)
class CaptureEvidence:
    """The exact ROI one lookup was given, and how it was arrived at."""

    observed_ns: int
    region: ScreenRect
    roi: ROIImage
    roi_digest: str
    plan: CapturePlan | None = None
    hover_request_id: int | None = None
    lookup_request_id: int | None = None


@dataclass(frozen=True)
class FrozenLookup:
    """One completed lookup, pinned. Immutable once returned.

    ``missing`` names every part of the evidence graph that is genuinely
    unavailable and why, so a gap reads as a gap rather than as a zero.
    """

    frozen_at_ns: int
    hover_request_id: int | None
    lookup_request_id: int | None
    capture: CaptureEvidence | None
    events: tuple[dict[str, Any], ...]
    stages: dict[str, dict[str, Any]]
    terminal_event: str | None
    result_status: str | None
    missing: tuple[str, ...]
    #: The recognizer that actually produced this lookup's OCR, as the worker
    #: reported it. ``None`` means no OCR stage ran, never "probably the
    #: configured one": on an ``auto`` runtime that resolves per machine.
    backend: str | None = None
    #: A staged EasyOCR run attached after the fact. It is always
    #: ``comparison_replay`` evidence unless the lookup itself ran staged.
    staged: Any | None = None

    @property
    def complete(self) -> bool:
        """Whether every stage of the evidence graph is present."""

        return not self.missing


class _Record:
    """One lookup as it accumulates. Never handed out; frozen into a value."""

    def __init__(self, hover_request_id: int | None, lookup_request_id: int | None) -> None:
        self.hover_request_id = hover_request_id
        self.lookup_request_id = lookup_request_id
        self.capture: CaptureEvidence | None = None
        self.events: list[dict[str, Any]] = []
        self.terminal_event: str | None = None
        self.last_seen_ns = 0

    def add(self, event: dict[str, Any], observed_ns: int) -> None:
        self.events.append(event)
        self.last_seen_ns = max(self.last_seen_ns, observed_ns)
        kind = event.get("event_kind") or event.get("event")
        if isinstance(kind, str) and kind in TERMINAL_EVENTS:
            self.terminal_event = kind


class LookupRing:
    """A bounded, thread-safe ring of recent correlated lookups.

    Every method is called from a producer that must not block: the capture
    path, the trace sink, and a global hotkey callback. The lock is held only
    for dictionary bookkeeping, never for encoding or I/O.
    """

    def __init__(self, size: int = DEFAULT_RING_SIZE) -> None:
        if size < 1:
            raise ValueError("ring size must be positive")
        self._size = size
        self._lock = threading.RLock()
        self._records: list[_Record] = []
        self._by_hover: dict[int, _Record] = {}
        self._by_lookup: dict[int, _Record] = {}
        self.dropped_captures = 0

    def observe_capture(
        self,
        capture: CaptureResult,
        digest: str,
        observed_ns: int,
        *,
        hover_request_id: int | None = None,
        lookup_request_id: int | None = None,
    ) -> None:
        """Retain one ROI by reference, keyed to the request it belongs to."""

        if hover_request_id is None and lookup_request_id is None:
            self.dropped_captures += 1
            return
        evidence = CaptureEvidence(
            observed_ns=observed_ns,
            region=capture.region,
            roi=capture.image,
            roi_digest=digest,
            plan=capture.plan,
            hover_request_id=hover_request_id,
            lookup_request_id=lookup_request_id,
        )
        with self._lock:
            record = self._record_for(hover_request_id, lookup_request_id)
            record.capture = evidence
            record.last_seen_ns = max(record.last_seen_ns, observed_ns)

    def observe_event(self, event: dict[str, Any], observed_ns: int) -> None:
        """File one raw trace event under the lookup it names."""

        hover_id = _identifier(event.get("hover_request_id"))
        lookup_id = _identifier(event.get("lookup_request_id"))
        if hover_id is None and lookup_id is None:
            return
        with self._lock:
            record = self._record_for(hover_id, lookup_id)
            record.add(dict(event), observed_ns)

    def freeze(self) -> FrozenLookup | None:
        """Pin the most recent completed lookup, or nothing if none is.

        Selection and copying happen under the lock so a lookup that completes
        during the freeze cannot contribute half of its evidence.
        """

        with self._lock:
            candidates = [record for record in self._records if record.terminal_event]
            if not candidates:
                return None
            record = max(candidates, key=lambda item: item.last_seen_ns)
            return _freeze(record)

    def records(self) -> int:
        """How many lookups the ring currently holds."""

        with self._lock:
            return len(self._records)

    def _record_for(
        self, hover_request_id: int | None, lookup_request_id: int | None
    ) -> _Record:
        """Find or create the record these identifiers belong to, and link them.

        A hover and a lookup identifier arriving together are what join a
        capture to the stages that read it, so seeing both merges the two
        indexes onto one record.
        """

        record = None
        if hover_request_id is not None:
            record = self._by_hover.get(hover_request_id)
        if record is None and lookup_request_id is not None:
            record = self._by_lookup.get(lookup_request_id)
        if record is None:
            record = _Record(hover_request_id, lookup_request_id)
            self._records.append(record)
            self._evict()

        if hover_request_id is not None:
            record.hover_request_id = hover_request_id
            self._by_hover[hover_request_id] = record
        if lookup_request_id is not None:
            record.lookup_request_id = lookup_request_id
            self._by_lookup[lookup_request_id] = record
        return record

    def _evict(self) -> None:
        """Drop the oldest records, unregistering only what still points at them.

        Two records can end up claiming one identifier: a lookup-only event
        arriving before the hover record that later adopts the same lookup id
        leaves the first one orphaned. Popping that orphan's key blindly would
        unregister the live record instead, and the next lookup-only event would
        then start a third record holding nothing but a terminal event -- a
        frozen lookup that reads as a capture failure that never happened.
        """

        while len(self._records) > self._size:
            evicted = self._records.pop(0)
            for index, key in (
                (self._by_hover, evicted.hover_request_id),
                (self._by_lookup, evicted.lookup_request_id),
            ):
                if key is not None and index.get(key) is evicted:
                    del index[key]


def _freeze(record: _Record) -> FrozenLookup:
    """Copy one accumulating record into an immutable pinned value."""

    from time import perf_counter_ns

    events = tuple(dict(event) for event in record.events)
    stages = _decoded_stages(events)
    return FrozenLookup(
        frozen_at_ns=perf_counter_ns(),
        hover_request_id=record.hover_request_id,
        lookup_request_id=record.lookup_request_id,
        capture=record.capture,
        events=events,
        stages=stages,
        terminal_event=record.terminal_event,
        result_status=_result_status(events),
        missing=_missing(record, stages),
        backend=_backend(events),
    )


def _decoded_stages(events: tuple[dict[str, Any], ...]) -> dict[str, dict[str, Any]]:
    """Decode each stage's private evidence payload, keeping the last of each."""

    stages: dict[str, dict[str, Any]] = {}
    for event in events:
        stage = event.get("stage")
        if not isinstance(stage, str):
            continue
        field_name = _STAGE_EVIDENCE.get(stage)
        if field_name is None:
            continue
        payload = decode_evidence(event.get(field_name))
        if payload is not None:
            stages[stage] = payload
    return stages


def _backend(events: tuple[dict[str, Any], ...]) -> str | None:
    """Name the recognizer that read this lookup's pixels.

    Taken from the OCR stage event the worker emitted, so it describes the
    provider that ran rather than whatever configuration says today. A staged
    EasyOCR replay is a separate record and never reaches this field.
    """

    for event in reversed(events):
        if event.get("stage") != "ocr":
            continue
        backend = event.get("ocr_backend")
        if isinstance(backend, str) and backend:
            return backend
    return None


def _result_status(events: tuple[dict[str, Any], ...]) -> str | None:
    """Read the outcome from whichever event actually reported one.

    A presented result names its status directly; a suppressed or silently
    delivered one does not, so the pipeline's own completion event is the
    fallback rather than leaving the record without an outcome at all.
    """

    for event in reversed(events):
        status = event.get("result_status")
        if isinstance(status, str):
            return status
    for event in reversed(events):
        if event.get("stage") != "total_pipeline":
            continue
        outcome = event.get("outcome")
        if isinstance(outcome, str):
            return outcome
    return None


#: The evidence graph, in the order a lookup walks it.
_STAGE_ORDER = ("ocr", "token_selection", "morphology", "dictionary")


def _missing(record: _Record, stages: dict[str, dict[str, Any]]) -> tuple[str, ...]:
    """Name every absent part of the evidence graph, with a reason.

    A stage that never ran is not the same as a stage that ran and reported
    nothing: an empty OCR pass answers the question for everything after it,
    and a cache hit answers it for OCR itself. Only a stage that should have
    spoken and did not is a gap.
    """

    missing: list[str] = []
    if record.capture is None:
        missing.append("capture:no ROI was observed for this request")
    elif record.capture.plan is None:
        missing.append("capture_plan:the capture source reported no plan")

    reached = _last_stage_reached(record.events, stages)
    for index, stage in enumerate(_STAGE_ORDER):
        if stage in stages:
            continue
        if stage == "ocr" and _ocr_was_skipped(record.events):
            missing.append("ocr:skipped; an earlier answer was reused")
        elif index > reached:
            missing.append(f"{stage}:not reached; the lookup ended earlier")
        else:
            missing.append(f"{stage}:no evidence was emitted for this stage")
    return tuple(missing)


def _last_stage_reached(
    events: list[dict[str, Any]], stages: dict[str, dict[str, Any]]
) -> int:
    """How far along the graph this lookup actually got.

    Derived from the stage events themselves rather than from the result, so a
    lookup that stopped because OCR read nothing says so at the stage that
    stopped it.
    """

    reached = -1
    for event in events:
        stage = event.get("stage")
        if isinstance(stage, str) and stage in _STAGE_ORDER:
            reached = max(reached, _STAGE_ORDER.index(stage))
    for stage in stages:
        if stage in _STAGE_ORDER:
            reached = max(reached, _STAGE_ORDER.index(stage))
    return reached


def _ocr_was_skipped(events: list[dict[str, Any]]) -> bool:
    return any(event.get("ocr_stage_skipped") is True for event in events)


def _identifier(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


@dataclass(frozen=True)
class FreezeReport:
    """What a freeze attempt found, for a developer watching the terminal."""

    frozen: FrozenLookup | None
    records_held: int
    reason: str | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)


__all__ = [
    "DEFAULT_RING_SIZE",
    "TERMINAL_EVENTS",
    "CaptureEvidence",
    "FreezeReport",
    "FrozenLookup",
    "LookupRing",
]
