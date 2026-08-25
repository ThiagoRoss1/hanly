"""Focused tests for the production-owned optional runtime trace sink."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Mapping, Sequence
from threading import Event
from typing import cast

from hanly import (
    BoundingBox,
    DictionaryEntry,
    LookupResult,
    LookupStatus,
    OCRResult,
    PixelFormat,
    Point,
    Quad,
    ROIImage,
    TokenAnalysis,
)
from hanly_app.capture import CaptureResult, ScreenRect
from hanly_app.composition import LookupWorker
from hanly_app.hover_controller import HoverScheduler
from hanly_app.hover_lookup import HoverLookupRuntime
from hanly_app.lookup_controller import LookupController, LookupRequest
from hanly_app.runtime_trace import JSONPrimitive, emit_trace

_IMAGE = ROIImage(
    width=2,
    height=1,
    pixel_format=PixelFormat.GRAYSCALE_8,
    data=b"\x00\xff",
)
_TARGET = Point(x=5, y=5)
_OCR_RESULT = OCRResult(
    text="읽습니다.",
    confidence=0.95,
    quad=Quad.from_bounding_box(BoundingBox(left=0, top=0, right=10, bottom=10)),
)
_ENTRY = DictionaryEntry(headword="읽다", definitions=("to read",), part_of_speech="동사")


class _Sink:
    def __init__(self) -> None:
        self.events: list[dict[str, JSONPrimitive]] = []

    def emit(self, event: Mapping[str, JSONPrimitive]) -> None:
        # A sink is intentionally handed JSON-safe values only.
        json.dumps(event)
        self.events.append(dict(event))


class _FailingSink:
    def emit(self, _event: Mapping[str, JSONPrimitive]) -> None:
        raise RuntimeError("sink failed")


class _RetainingSink(_Sink):
    retain_text = True


class _OCRProvider:
    def recognize(self, image: ROIImage) -> Sequence[OCRResult]:
        assert image is _IMAGE
        return (_OCR_RESULT,)


class _Resolver:
    def resolve_target(
        self,
        ocr_results: Sequence[OCRResult] | None,
        target: Point | None,
    ) -> tuple[OCRResult, str] | None:
        assert tuple(ocr_results or ()) == (_OCR_RESULT,)
        assert target is _TARGET
        return _OCR_RESULT, "읽습니다."


class _Morphology:
    def analyze(self, text: str) -> Sequence[TokenAnalysis]:
        assert text == "읽습니다."
        return (TokenAnalysis(token="읽습니다", lemma="읽다", part_of_speech="동사"),)


class _Dictionary:
    def lookup(self, lemma: str) -> Sequence[DictionaryEntry]:
        assert lemma == "읽다"
        return (_ENTRY,)


class _Worker:
    def __call__(self, request: LookupRequest) -> LookupResult:
        return LookupResult(status=LookupStatus.EMPTY)

    def close(self) -> None:
        pass


class _Handle:
    def __init__(self, callback: Callable[[], None]) -> None:
        self.callback = callback
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class _Scheduler:
    def __init__(self) -> None:
        self.handles: list[_Handle] = []

    def __call__(self, _delay_ms: float, callback: Callable[[], None]) -> _Handle:
        handle = _Handle(callback)
        self.handles.append(handle)
        return handle

    def fire(self) -> None:
        handle = self.handles[-1]
        if not handle.cancelled:
            assert callable(handle.callback)
            handle.callback()


class _Listener:
    def __init__(self, on_move: Callable[[int, int], None]) -> None:
        self.on_move = on_move

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def emit(self, x: int, y: int) -> None:
        assert callable(self.on_move)
        self.on_move(x, y)


class _ListenerFactory:
    def __init__(self) -> None:
        self.listener: _Listener | None = None

    def __call__(self, on_move: Callable[[int, int], None]) -> _Listener:
        self.listener = _Listener(on_move)
        return self.listener


class _Capture:
    def capture_at_cursor(self, cursor: Point) -> CaptureResult:
        assert cursor == Point(10, 10)
        return CaptureResult(
            image=_IMAGE,
            region=ScreenRect(0, 0, 2, 1),
            target=Point(1, 0),
        )


def test_emit_trace_is_json_safe_monotonic_and_swallowing_sink_failures() -> None:
    """This catches missing safe emission and wall-clock/non-JSON event fields."""

    sink = _Sink()
    emit_trace(
        sink,
        "test_event",
        lookup_request_id=7,
        hover_request_id=3,
        count=2,
        classification="success",
    )
    emit_trace(sink, "second_event")
    emit_trace(_FailingSink(), "ignored_event")

    event = sink.events[0]
    assert event["event_kind"] == "test_event"
    assert event["event"] == "test_event"
    assert event["monotonic_ns"] == event["timestamp_ns"]
    assert event["lookup_request_id"] == 7
    assert event["hover_request_id"] == 3
    assert isinstance(event["timestamp_ns"], int)
    assert event["thread_id"] == threading.get_ident()
    assert isinstance(event["timestamp_ns"], int)
    assert isinstance(sink.events[1]["timestamp_ns"], int)
    assert sink.events[1]["timestamp_ns"] >= event["timestamp_ns"]


def test_lookup_worker_records_private_safe_stage_timings_with_request_correlation() -> None:
    """This catches raw OCR/lemma leakage and instrumentation outside the worker seam."""

    sink = _Sink()
    worker = LookupWorker(
        lambda: _OCRProvider(),
        lambda: _Morphology(),
        lambda: _Dictionary(),
        word_resolver_factory=lambda: _Resolver(),
        trace_sink=sink,
    )

    request = LookupRequest(4, _IMAGE, _TARGET, hover_request_id=9)
    result = worker(request)
    worker.close()

    assert result.status is LookupStatus.SUCCESS
    stages = {
        event.get("stage")
        for event in sink.events
        if event["event_kind"] == "lookup_stage_completed"
    }
    assert stages == {"ocr", "token_selection", "morphology", "dictionary", "total_pipeline"}
    for event in sink.events:
        assert event["lookup_request_id"] == 4
        assert event["hover_request_id"] == 9
        assert "읽습니다" not in event.values()
        assert "읽다" not in event.values()
        assert "headword" not in event
        assert isinstance(event["timestamp_ns"], int)
    assert all(
        isinstance(event.get("duration_ns"), int)
        for event in sink.events
        if event["event_kind"] == "lookup_stage_completed"
    )
    ocr_event = next(
        event
        for event in sink.events
        if event.get("stage") == "ocr"
        and event["event_kind"] == "lookup_stage_completed"
    )
    morphology_event = next(
        event
        for event in sink.events
        if event.get("stage") == "morphology"
        and event["event_kind"] == "lookup_stage_completed"
    )
    assert ocr_event["region_count"] == 1
    assert ocr_event["hangul_region_count"] == 1
    assert ocr_event["ocr_char_count"] == len("읽습니다.")
    assert ocr_event["hangul_char_count"] == 4
    assert ocr_event["punctuation_char_count"] == 1
    assert ocr_event["confidence_min"] == 0.95
    assert ocr_event["confidence_max"] == 0.95
    assert morphology_event["hangul_token_count"] == 1


def test_lookup_worker_emits_raw_ocr_only_for_explicit_retaining_sink() -> None:
    sink = _RetainingSink()
    worker = LookupWorker(
        lambda: _OCRProvider(),
        lambda: _Morphology(),
        lambda: _Dictionary(),
        word_resolver_factory=lambda: _Resolver(),
        trace_sink=sink,
    )

    worker(LookupRequest(1, _IMAGE, _TARGET))
    worker.close()

    ocr_event = next(event for event in sink.events if event.get("stage") == "ocr")
    assert ocr_event["ocr_text"] == "읽습니다."


def test_lookup_controller_trace_maps_submit_and_suppresses_stale_delivery() -> None:
    """This catches missing immutable request IDs at the controller boundary."""

    sink = _Sink()
    delivered: list[LookupResult] = []
    started = Event()
    release = Event()

    class _BlockingWorker:
        def __call__(self, request: LookupRequest) -> LookupResult:
            started.set()
            assert release.wait(1)
            return LookupResult(status=LookupStatus.EMPTY)

        def close(self) -> None:
            pass

    controller = LookupController(
        lambda: _BlockingWorker(),
        delivered.append,
        trace_sink=sink,
    )
    controller.start()
    request = controller.submit(_IMAGE, _TARGET, hover_request_id=11)
    assert started.wait(1)
    controller.invalidate()
    release.set()
    controller.stop()

    assert request.hover_request_id == 11
    assert not delivered
    kinds = {event["event_kind"] for event in sink.events}
    assert "lookup_submit" in kinds
    assert "lookup_invalidate" in kinds
    assert "lookup_cancelled_early" in kinds
    assert "lookup_dispatch_queued" not in kinds


def _await_hover_ready(runtime: HoverLookupRuntime) -> None:
    """Block until hover observation is armed.

    Providers are constructed on the executor thread, and hover stays paused
    until that finishes, so a position emitted before then is recorded as a
    missed opportunity and schedules nothing. The wait keeps the test about
    tracing rather than about which thread won.
    """

    assert runtime.controller.wait_until_ready(timeout=5)
    for _ in range(500):
        if runtime.hover_controller.running:
            return
        Event().wait(0.01)
    raise AssertionError("hover observation did not start after worker readiness")


def test_hover_runtime_trace_carries_hover_to_lookup_and_capture_timing() -> None:
    """This catches missing hover opportunities, capture timing, and ID mapping."""

    sink = _Sink()
    scheduler = _Scheduler()
    listener_factory = _ListenerFactory()
    controller = LookupController(lambda: _Worker(), trace_sink=sink)
    runtime = HoverLookupRuntime(
        controller,
        _Capture(),
        scheduler=cast(HoverScheduler, scheduler),
        listener_factory=listener_factory,
        trace_sink=sink,
    )
    runtime.start()
    _await_hover_ready(runtime)
    assert listener_factory.listener is not None
    listener_factory.listener.emit(10, 10)
    scheduler.fire()
    runtime.shutdown()
    controller.join(1)

    events = sink.events
    kinds = {event["event_kind"] for event in events}
    assert {
        "hover_mouse_opportunity",
        "hover_stable_fire",
        "hover_capture_attempted",
        "hover_capture_completed",
        "hover_submission",
    } <= kinds
    submission = next(event for event in events if event["event_kind"] == "hover_submission")
    assert submission["hover_request_id"] == 1
    assert submission["lookup_request_id"] == 1
    capture = next(event for event in events if event["event_kind"] == "hover_capture_completed")
    assert isinstance(capture["duration_ns"], int)
