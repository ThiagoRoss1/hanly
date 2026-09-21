"""Evidence for the region an answer protects, and for whether it was shown.

A retained rectangle in the wrong place suppresses the next capture entirely,
and a suppressed result is indistinguishable from a stale one unless both say
so. These tests pin the coordinate spaces, the transform between them, and the
two presentation outcomes.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from threading import Event
from typing import cast

from hanly import (
    BoundingBox,
    DictionaryEntry,
    HanlyError,
    LookupContext,
    LookupResult,
    LookupStatus,
    OCRResult,
    PixelFormat,
    Point,
    Quad,
    ROIImage,
)
from hanly_app.capture import CaptureResult, ScreenRect
from hanly_app.config import AppConfig, HoverActivation
from hanly_app.hotkeys import HotkeyAction, HotkeyEdge
from hanly_app.hover_target import (
    SCREEN_SCALE,
    TRANSFER_CORRIDOR_PIXELS,
    WORD_MARGIN_PIXELS,
    expanded,
    screen_rect,
)
from hanly_app.lookup_controller import LookupController, LookupRequest, ResultDispatcher
from hanly_app.manual_lookup import create_manual_lookup
from hanly_app.runtime_trace import RuntimeTraceSink

_ORIGIN = ScreenRect(400, 300, 200, 100)
_IMAGE = ROIImage(
    _ORIGIN.width, _ORIGIN.height, PixelFormat.RGB_888, bytes(200 * 100 * 3)
)
_CAPTURE = CaptureResult(_IMAGE, _ORIGIN, Point(100.0, 50.0))
_CURSOR = Point(500.0, 350.0)
_WORD_REGION = BoundingBox(30, 12, 74, 34)
_ALWAYS_ACTIVE = AppConfig(hover_activation=HoverActivation.ALWAYS_ACTIVE)


def _success() -> LookupResult:
    return LookupResult(
        status=LookupStatus.SUCCESS,
        entries=(DictionaryEntry(headword="책", definitions=("book",)),),
        context=LookupContext(
            text="책",
            lemma="책",
            ocr_results=(
                OCRResult("책", 0.9, Quad.from_bounding_box(BoundingBox(0, 0, 100, 40))),
            ),
            word_region=_WORD_REGION,
        ),
    )


class _Sink:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def emit(self, event: Mapping[str, object]) -> None:
        self.events.append(dict(event))

    def of(self, kind: str) -> list[dict[str, object]]:
        return [event for event in self.events if event.get("event_kind") == kind]


class _Dispatcher:
    def __init__(self) -> None:
        self.pending: list[Callable[[], None]] = []

    def __call__(self, callback: Callable[[], None]) -> None:
        self.pending.append(callback)

    def drain(self) -> None:
        while self.pending:
            self.pending.pop(0)()


class _Capture:
    def capture_at_cursor(self, _cursor: Point) -> CaptureResult:
        return _CAPTURE

    def close(self) -> None:
        pass


class _Worker:
    def __init__(self, result: LookupResult) -> None:
        self.result = result
        self.started = Event()

    def __call__(self, _request: LookupRequest) -> LookupResult:
        self.started.set()
        return self.result

    def close(self) -> None:
        pass


class _Runtime:
    def __init__(self, worker: _Worker) -> None:
        self._worker = worker

    def create_lookup_controller(
        self,
        on_result: Callable[[LookupResult], None] | None = None,
        *,
        result_dispatcher: ResultDispatcher | None = None,
        thread_name: str | None = None,
        trace_sink: object | None = None,
        **_options: object,
    ) -> LookupController:
        return LookupController(
            lambda: self._worker,
            on_result,
            result_dispatcher=result_dispatcher,
            thread_name=thread_name,
            trace_sink=cast(RuntimeTraceSink, trace_sink),
        )


class _Hotkeys:
    """A hotkey runtime that registers nothing; these tests call the path."""

    def __call__(
        self,
        _on_action: Callable[[HotkeyAction, HotkeyEdge], None],
        _bindings: Mapping[HotkeyAction | str, str],
        _dispatcher: Callable[[Callable[[], None]], None],
    ) -> _Hotkeys:
        return self

    @property
    def bindings(self) -> Mapping[HotkeyAction, str]:
        return {}

    @property
    def registered(self) -> bool:
        return True

    def register(self) -> None:
        pass

    def shutdown(self) -> None:
        pass


def _lookup_once(result: LookupResult) -> _Sink:
    """Run one manual lookup end to end and return everything it traced."""

    sink = _Sink()
    dispatcher = _Dispatcher()
    worker = _Worker(result)
    composition = create_manual_lookup(
        _Runtime(worker),
        _Capture(),
        lambda _result: None,
        close_popup=lambda: None,
        current_cursor=lambda: _CURSOR,
        dispatcher=dispatcher,
        hotkey_factory=_Hotkeys(),
        trace_sink=sink,
        hover_enabled=True,
        app_config=_ALWAYS_ACTIVE,
        lookup_hotkey="ctrl+alt+space",
    )
    composition.start()
    composition.lookup_at_cursor()
    dispatcher.drain()
    assert worker.started.wait(timeout=2)
    for _ in range(200):
        if dispatcher.pending:
            dispatcher.drain()
            break
        Event().wait(0.01)
    composition.shutdown()
    return sink


def test_the_retained_rectangle_records_both_coordinate_spaces() -> None:
    sink = _lookup_once(_success())

    (event,) = sink.of("retained_target")
    assert (event["roi_word_left"], event["roi_word_top"]) == (
        _WORD_REGION.left,
        _WORD_REGION.top,
    )
    assert (event["roi_word_right"], event["roi_word_bottom"]) == (
        _WORD_REGION.right,
        _WORD_REGION.bottom,
    )
    assert (event["capture_origin_left"], event["capture_origin_top"]) == (
        _ORIGIN.left,
        _ORIGIN.top,
    )
    assert event["screen_scale"] == SCREEN_SCALE


def test_the_recorded_screen_rectangle_is_the_transform_it_names() -> None:
    sink = _lookup_once(_success())

    (event,) = sink.of("retained_target")
    expected = screen_rect(_ORIGIN, _WORD_REGION)
    assert expected is not None
    assert (event["word_left"], event["word_top"]) == (expected.left, expected.top)
    assert (event["word_width"], event["word_height"]) == (
        expected.width,
        expected.height,
    )


def test_the_protected_rectangle_is_recorded_beside_the_unpadded_one() -> None:
    sink = _lookup_once(_success())

    (event,) = sink.of("retained_target")
    word = screen_rect(_ORIGIN, _WORD_REGION)
    assert word is not None
    protected = expanded(word, WORD_MARGIN_PIXELS)
    assert (event["protected_left"], event["protected_top"]) == (
        protected.left,
        protected.top,
    )
    assert (event["protected_width"], event["protected_height"]) == (
        protected.width,
        protected.height,
    )
    assert event["word_margin"] == WORD_MARGIN_PIXELS
    assert event["transfer_corridor"] == TRANSFER_CORRIDOR_PIXELS


def test_a_retained_event_correlates_with_the_lookup_that_produced_it() -> None:
    sink = _lookup_once(_success())

    (retained,) = sink.of("retained_target")
    (delivered,) = sink.of("lookup_current_delivered")
    assert retained["lookup_request_id"] == delivered["lookup_request_id"]


def test_a_success_without_word_geometry_says_why_it_protects_nothing() -> None:
    result = LookupResult(
        status=LookupStatus.SUCCESS,
        entries=(DictionaryEntry(headword="책", definitions=("book",)),),
        context=LookupContext(text="책"),
    )

    sink = _lookup_once(result)

    assert sink.of("retained_target") == []
    (cleared,) = sink.of("retained_target_cleared")
    assert cleared["reason"] == "no_word_region"


def test_an_error_result_is_shown_but_protects_nothing() -> None:
    """An error is worth a card; there is no recognized word to keep it on."""

    sink = _lookup_once(
        LookupResult(
            status=LookupStatus.ERROR,
            diagnostics=("lookup failed",),
            error=HanlyError("lookup failed"),
        )
    )

    assert sink.of("popup_suppressed") == []
    (cleared,) = sink.of("retained_target_cleared")
    assert cleared["reason"] == "not_a_success"


def test_a_current_but_unpresentable_result_is_recorded_as_suppressed() -> None:
    """A silent outcome must not look the same as a stale one."""

    sink = _lookup_once(LookupResult(status=LookupStatus.EMPTY))

    (suppressed,) = sink.of("popup_suppressed")
    assert suppressed["result_status"] == LookupStatus.EMPTY.value
    assert sink.of("popup_visible") == []
    (delivered,) = sink.of("lookup_current_delivered")
    assert suppressed["lookup_request_id"] == delivered["lookup_request_id"]
    assert sink.of("lookup_stale_suppressed") == []
