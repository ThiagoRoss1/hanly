"""The direct-text path through the worker, and its fallback to OCR.

The rule under test is that valid direct text bypasses recognition entirely,
and that everything else reaches the unchanged capture-and-OCR path.
"""

from __future__ import annotations

import pickle
from typing import Any

import pytest
from hanly import (
    BoundingBox,
    DictionaryEntry,
    DictionarySense,
    LexicalCandidate,
    LookupStatus,
    MorphologyAnalysis,
    OCRResult,
    PixelFormat,
    Point,
    Quad,
    ROIImage,
    TextSelection,
    TokenAnalysis,
)
from hanly_app.composition import LookupWorker
from hanly_app.lookup_controller import LookupRequest

_IMAGE = ROIImage(40, 20, PixelFormat.RGB_888, bytes(40 * 20 * 3))
_TARGET = Point(20, 10)
_KOREAN = "초대받았어요"


class _ExplodingOCR:
    """Any recognition at all is a failure of the direct path."""

    def __init__(self) -> None:
        self.calls = 0

    def recognize(self, image: ROIImage) -> tuple[OCRResult, ...]:
        self.calls += 1
        raise AssertionError("the direct path must not reach OCR")


class _OCR:
    def __init__(self) -> None:
        self.calls = 0

    def recognize(self, image: ROIImage) -> tuple[OCRResult, ...]:
        self.calls += 1
        return (
            OCRResult(
                text=_KOREAN,
                confidence=0.95,
                quad=Quad.from_bounding_box(BoundingBox(0, 0, 40, 20)),
            ),
        )


class _Morphology:
    def analyze(self, text: str) -> MorphologyAnalysis:
        del text
        return MorphologyAnalysis(
            tokens=(
                TokenAnalysis(
                    token="초대", lemma="초대", part_of_speech="NNG", start=0, length=2
                ),
            ),
            candidates=(
                LexicalCandidate(lemma="초대", start=0, end=6, part_of_speech="NNG"),
            ),
        )


class _Dictionary:
    def __init__(self, known: bool = True) -> None:
        self.known = known
        self.queries: list[str] = []

    def lookup(self, lemma: str) -> tuple[DictionaryEntry, ...]:
        self.queries.append(lemma)
        if not self.known or lemma != "초대":
            return ()
        return (
            DictionaryEntry(
                headword="초대",
                senses=(DictionarySense(definition="An act.", gloss="invitation"),),
            ),
        )


class _Sink:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def emit(self, event: Any) -> None:
        self.events.append(dict(event))


def _selection_request(**kwargs: Any) -> LookupRequest:
    return LookupRequest(
        1,
        None,
        _TARGET,
        selection=TextSelection(text=_KOREAN, cursor_index=0, source="accessibility"),
        **kwargs,
    )


def test_direct_text_answers_without_calling_ocr() -> None:
    ocr = _ExplodingOCR()
    worker = LookupWorker(lambda: ocr, _Morphology, _Dictionary)
    try:
        result = worker(_selection_request())
    finally:
        worker.close()

    assert result.status is LookupStatus.SUCCESS
    assert result.entries[0].headword == "초대"
    assert ocr.calls == 0


def test_a_validated_dictionary_miss_does_not_fall_into_ocr() -> None:
    """A word that was read correctly and is simply absent stays absent."""

    ocr = _ExplodingOCR()
    worker = LookupWorker(lambda: ocr, _Morphology, lambda: _Dictionary(known=False))
    try:
        result = worker(_selection_request())
    finally:
        worker.close()

    assert result.status is LookupStatus.NOT_FOUND
    assert ocr.calls == 0


def test_a_captured_request_still_runs_the_unchanged_ocr_path() -> None:
    ocr = _OCR()
    worker = LookupWorker(lambda: ocr, _Morphology, _Dictionary)
    try:
        result = worker(LookupRequest(1, _IMAGE, _TARGET))
    finally:
        worker.close()

    assert result.status is LookupStatus.SUCCESS
    assert ocr.calls == 1


def test_a_superseded_direct_request_is_not_executed() -> None:
    ocr = _ExplodingOCR()
    worker = LookupWorker(lambda: ocr, _Morphology, _Dictionary)
    request = _selection_request()
    request.cancel()
    try:
        with pytest.raises(Exception):
            worker(request)
    finally:
        worker.close()

    assert ocr.calls == 0


def test_the_trace_records_which_acquisition_read_the_word_but_not_the_word() -> None:
    sink = _Sink()
    worker = LookupWorker(
        lambda: _ExplodingOCR(), _Morphology, _Dictionary, trace_sink=sink
    )
    try:
        worker(_selection_request())
    finally:
        worker.close()

    acquisition = [
        e for e in sink.events if e.get("event_kind") == "lookup_acquisition"
    ]
    assert [e["acquisition_source"] for e in acquisition] == ["accessibility"]
    assert all(e.get("ocr_stage_skipped") for e in acquisition)
    blob = repr(sink.events)
    assert _KOREAN not in blob and "초대" not in blob


def test_direct_and_captured_requests_cannot_share_a_cache_entry() -> None:
    ocr = _OCR()
    worker = LookupWorker(lambda: ocr, _Morphology, _Dictionary)
    try:
        worker(_selection_request())
        worker(LookupRequest(2, _IMAGE, _TARGET))
    finally:
        worker.close()

    # The captured request was really executed rather than served the direct
    # answer from a colliding key.
    assert ocr.calls == 1


def test_a_request_without_pixels_or_a_selection_is_rejected() -> None:
    with pytest.raises(TypeError):
        LookupRequest(1, None, _TARGET)


def test_a_selection_request_survives_the_process_transport() -> None:
    from hanly_app.lookup_process import _lookup_message, _request_from

    restored = _request_from(_lookup_message(_selection_request()))

    assert restored.image is None
    assert restored.selection == TextSelection(
        text=_KOREAN, cursor_index=0, source="accessibility"
    )


def test_a_captured_request_still_survives_the_process_transport() -> None:
    from hanly_app.lookup_process import _lookup_message, _request_from

    restored = _request_from(_lookup_message(LookupRequest(3, _IMAGE, _TARGET)))

    assert restored.selection is None
    assert restored.image is not None and restored.image.width == 40


def test_a_selection_message_carries_no_pixel_fields() -> None:
    from hanly_app.lookup_process import _lookup_message

    message = _lookup_message(_selection_request())

    assert "data" not in message and "width" not in message
    # It still has to survive the real pickling the transport performs.
    assert pickle.loads(pickle.dumps(message))["selection_text"] == _KOREAN


# --- the hover runtime schedules, then acts on the outcome -------------------


class _Capture:
    def __init__(self) -> None:
        self.calls = 0

    def capture_at_cursor(self, cursor: Point) -> Any:
        from hanly_app.capture import CaptureResult, ScreenRect

        self.calls += 1
        return CaptureResult(
            image=_IMAGE,
            region=ScreenRect(left=0, top=0, width=40, height=20),
            target=Point(20, 10),
        )


class _Service:
    """Stands in for the threaded service, delivering on demand."""

    def __init__(self, outcome: Any = None) -> None:
        self.outcome = outcome
        self.submissions = 0
        self.closed = False
        self._deliver: Any = None

    def submit(self, point: Point, deliver: Any) -> int:
        self.submissions += 1
        self._deliver = deliver
        return self.submissions

    def deliver_now(self) -> None:
        assert self._deliver is not None
        self._deliver(self.outcome)

    def close(self) -> None:
        self.closed = True


def _hover_runtime(service: Any) -> tuple[Any, _Capture, list[Any], Any]:
    from hanly_app.hover_lookup import HoverLookupRuntime
    from hanly_app.lookup_controller import LookupController

    submitted: list[Any] = []

    class _Worker:
        def __call__(self, request: LookupRequest) -> Any:
            from hanly import LookupResult

            return LookupResult(status=LookupStatus.NOT_FOUND)

        def close(self) -> None:
            return None

    controller = LookupController(_Worker)
    controller.start()
    original = controller.submit_selection

    def _spy(selection: TextSelection, target: Point, **kwargs: Any) -> Any:
        submitted.append(selection)
        return original(selection, target, **kwargs)

    controller.submit_selection = _spy  # type: ignore[method-assign]
    capture = _Capture()
    runtime = HoverLookupRuntime(
        controller, capture, delay_ms=1, acquisition=service
    )
    runtime._hover.is_current = lambda request: True  # type: ignore[method-assign]
    return runtime, capture, submitted, controller


def _hover_request() -> Any:
    from hanly_app.hover_lookup import HoverRequest

    return HoverRequest(request_id=1, point=Point(20, 10))


def test_the_ui_thread_only_schedules_and_never_performs_the_read() -> None:
    """Scheduling must return before the native call has produced anything."""

    from hanly_app.text_acquisition import Acquisition, Outcome

    service = _Service(Acquisition(Outcome.UNSUPPORTED))
    runtime, capture, _submitted, controller = _hover_runtime(service)
    try:
        assert runtime._start_direct_text(_hover_request()) is True
        assert service.submissions == 1
        # Nothing has been decided yet, so nothing has been captured either.
        assert capture.calls == 0
    finally:
        runtime.shutdown()
        controller.stop(wait=True)


@pytest.mark.parametrize(
    "outcome",
    [
        "no_provider", "no_permission", "unsupported", "secure", "not_containing",
        "ambiguous", "not_korean", "empty", "timed_out", "failed", "superseded",
    ],
)
def test_every_refusal_reaches_the_capture_path(outcome: str) -> None:
    """A refusal is never a failure: it is the ordinary OCR lookup."""

    from hanly_app.text_acquisition import Acquisition, Outcome

    service = _Service(Acquisition(Outcome(outcome)))
    runtime, capture, submitted, controller = _hover_runtime(service)
    try:
        runtime._start_direct_text(_hover_request())
        service.deliver_now()
    finally:
        runtime.shutdown()
        controller.stop(wait=True)

    assert submitted == []
    assert capture.calls == 1


def test_an_unverifiable_windows_cursor_is_captured_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider answering with a shorter prefix never names the wrong syllable."""

    from hanly_app import text_acquisition_uia as uia
    from hanly_app.text_acquisition import DirectTextCoordinator

    from tests.hanly_fixtures.uia import FakeBridge, FakeControl, point_at

    bridge = FakeBridge(FakeControl("초대받았어요"))
    honest = bridge.text_of

    def text_of(pointer: Any, limit: int) -> str | None:
        span = bridge.get(pointer)
        return "초" if (span.start, span.end) == (0, 2) else honest(pointer, limit)

    bridge.text_of = text_of  # type: ignore[method-assign]
    monkeypatch.setattr(uia, "_bridge_for_thread", lambda: bridge)
    acquired = DirectTextCoordinator(uia.UIAutomationTextProvider()).acquire(
        point_at(2)
    )

    service = _Service(acquired)
    runtime, capture, submitted, controller = _hover_runtime(service)
    try:
        runtime._start_direct_text(_hover_request())
        service.deliver_now()
    finally:
        runtime.shutdown()
        controller.stop(wait=True)

    assert not acquired.used_direct_text
    assert submitted == []
    assert capture.calls == 1


def test_valid_direct_text_submits_a_selection_and_captures_nothing() -> None:
    from hanly_app.text_acquisition import Acquisition, Outcome

    service = _Service(
        Acquisition(
            Outcome.DIRECT,
            selection=TextSelection(
                text=_KOREAN, cursor_index=0, source="accessibility"
            ),
            bounds=BoundingBox(10, 10, 60, 30),
        )
    )
    runtime, capture, submitted, controller = _hover_runtime(service)
    try:
        runtime._start_direct_text(_hover_request())
        service.deliver_now()
    finally:
        runtime.shutdown()
        controller.stop(wait=True)

    assert capture.calls == 0
    assert [item.text for item in submitted] == [_KOREAN]
    assert all(item.source == "accessibility" for item in submitted)


def test_an_outcome_arriving_after_the_hover_moved_on_is_discarded() -> None:
    from hanly_app.text_acquisition import Acquisition, Outcome

    service = _Service(
        Acquisition(
            Outcome.DIRECT,
            selection=TextSelection(text=_KOREAN, cursor_index=0),
        )
    )
    runtime, capture, submitted, controller = _hover_runtime(service)
    runtime._hover.is_current = lambda request: False
    try:
        runtime._start_direct_text(_hover_request())
        service.deliver_now()
    finally:
        runtime.shutdown()
        controller.stop(wait=True)

    assert submitted == []
    assert capture.calls == 0


def test_without_a_reader_the_runtime_never_tries_direct_text() -> None:
    runtime, capture, submitted, controller = _hover_runtime(None)
    try:
        assert runtime._start_direct_text(_hover_request()) is False
    finally:
        runtime.shutdown()
        controller.stop(wait=True)

    assert submitted == []


def test_shutdown_closes_the_acquisition_service() -> None:
    service = _Service()
    runtime, _capture, _submitted, controller = _hover_runtime(service)
    runtime.shutdown()
    controller.stop(wait=True)

    assert service.closed is True


# --- the acquisition label is a route, not content ---------------------------


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("accessibility", "accessibility"),
        ("ocr", "ocr"),
        ("private_ascii_text", "unknown"),
        ("A" * 200_000, "unknown"),
        ("초대받았어요-secret", "unknown"),
        ("\x00\x01evil", "unknown"),
        ('{"json":"injection"}', "unknown"),
    ],
    ids=["accessibility", "ocr", "ascii-content", "oversized", "korean", "control", "json"],
)
def test_only_a_bounded_route_label_reaches_the_trace(
    source: str, expected: str
) -> None:
    """A trace must not grow without bound, nor carry recognized text."""

    sink = _Sink()
    worker = LookupWorker(
        lambda: _ExplodingOCR(), _Morphology, _Dictionary, trace_sink=sink
    )
    try:
        worker(
            LookupRequest(
                1,
                None,
                _TARGET,
                selection=TextSelection(text=_KOREAN, cursor_index=0, source=source),
            )
        )
    finally:
        worker.close()

    events = [e for e in sink.events if e.get("event_kind") == "lookup_acquisition"]
    assert [e["acquisition_source"] for e in events] == [expected]
    blob = repr(sink.events)
    assert _KOREAN not in blob
    assert len(blob) < 10_000


# --- a dispatcher that rejects the outcome -----------------------------------


class _Rejecting:
    """A UI dispatcher whose target is gone, as a destroyed Qt bridge would be."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, callback: Any) -> None:
        self.calls += 1
        raise RuntimeError("초대받았어요 at (20, 10) wrapped object has been deleted")


def test_a_rejected_outcome_is_traced_by_its_class_alone() -> None:
    """The native worker can neither capture nor touch Qt; it can only record."""

    from hanly_app.text_acquisition import Acquisition, Outcome

    service = _Service(Acquisition(Outcome.UNSUPPORTED))
    runtime, capture, submitted, controller = _hover_runtime(service)
    sink, dispatcher = _Sink(), _Rejecting()
    runtime._trace_sink = sink
    runtime._dispatcher = dispatcher
    try:
        assert runtime._start_direct_text(_hover_request())
        service.deliver_now()  # must not raise into the service's thread
    finally:
        runtime.shutdown()
        controller.stop(wait=True)

    [event] = [e for e in sink.events if e["event_kind"] == "hover_direct_text_dispatch_failed"]
    assert event["error_type"] == "RuntimeError"
    assert event["hover_request_id"] == 1
    serialized = repr(event)
    assert "초대" not in serialized and "deleted" not in serialized and "(20" not in serialized
    assert dispatcher.calls == 1
    assert capture.calls == 0 and submitted == []


def test_an_outcome_after_shutdown_is_suppressed_without_a_failure() -> None:
    from hanly_app.text_acquisition import Acquisition, Outcome

    service = _Service(Acquisition(Outcome.UNSUPPORTED))
    runtime, capture, submitted, controller = _hover_runtime(service)
    sink, dispatcher = _Sink(), _Rejecting()
    runtime._trace_sink = sink
    runtime._dispatcher = dispatcher
    runtime._start_direct_text(_hover_request())
    runtime.shutdown()
    controller.stop(wait=True)

    service.deliver_now()

    assert dispatcher.calls == 0
    assert not [e for e in sink.events if e["event_kind"] == "hover_direct_text_dispatch_failed"]
    assert capture.calls == 0 and submitted == []


def test_a_rejecting_dispatcher_does_not_stop_the_real_worker() -> None:
    """Later hovers must still be read after one outcome could not be handed over."""

    from threading import Event

    from hanly_app.text_acquisition import (
        DirectText,
        DirectTextCoordinator,
        DirectTextService,
    )

    class _Reader:
        def read_at(self, point: Point, *, timeout_ms: int) -> DirectText | None:
            return None

    service = DirectTextService(DirectTextCoordinator(_Reader()))
    runtime, capture, submitted, controller = _hover_runtime(service)
    rejected, delivered = Event(), Event()

    def dispatcher(callback: Any) -> None:
        if not rejected.is_set():
            rejected.set()
            raise RuntimeError("rejected")
        delivered.set()

    runtime._dispatcher = dispatcher
    try:
        runtime._start_direct_text(_hover_request())
        assert rejected.wait(timeout=5.0)
        runtime._start_direct_text(_hover_request())
        assert delivered.wait(timeout=5.0), "the worker stopped after a rejection"
    finally:
        runtime.shutdown()
        controller.stop(wait=True)
