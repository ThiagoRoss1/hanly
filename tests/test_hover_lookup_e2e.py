from __future__ import annotations

import queue
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from threading import Event
from time import monotonic

import pytest
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
from hanly.word_resolver import WordResolver
from hanly_app.capture import CaptureResult, ScreenRect
from hanly_app.composition import create_lookup_controller
from hanly_app.manual_lookup import ManualLookupRuntime, create_manual_lookup

_UI_POINT = Point(120, 80)
_SECOND_POINT = Point(220, 180)
_LATEST_POINT = Point(320, 280)
_IMAGE_BY_POINT = {
    _UI_POINT: ROIImage(2, 1, PixelFormat.RGB_888, b"\x01\x00\x00\x01\x00\x00"),
    _SECOND_POINT: ROIImage(2, 1, PixelFormat.RGB_888, b"\x02\x00\x00\x02\x00\x00"),
    _LATEST_POINT: ROIImage(2, 1, PixelFormat.RGB_888, b"\x03\x00\x00\x03\x00\x00"),
}
_TARGET = Point(1.0, 0.5)
_REGION = ScreenRect(20, 30, 2, 1)
_QUAD = Quad.from_bounding_box(BoundingBox(0, 0, 2, 1))


class _QueueDispatcher:
    def __init__(self) -> None:
        self._pending: queue.Queue[Callable[[], None]] = queue.Queue()
        self.posted_from: list[int] = []
        self.ran_on: list[int] = []

    def __call__(self, callback: Callable[[], None]) -> None:
        self.posted_from.append(threading.get_ident())
        self._pending.put(callback)

    def drain_one(self, timeout: float = 0.1) -> bool:
        try:
            callback = self._pending.get(timeout=timeout)
        except queue.Empty:
            return False
        self.ran_on.append(threading.get_ident())
        callback()
        return True


@dataclass
class _Timer:
    callback: Callable[[], None]
    cancelled: bool = False

    def cancel(self) -> None:
        self.cancelled = True


class _Scheduler:
    def __init__(self) -> None:
        self.calls: list[tuple[float, _Timer]] = []

    def __call__(self, delay_ms: float, callback: Callable[[], None]) -> _Timer:
        timer = _Timer(callback)
        self.calls.append((delay_ms, timer))
        return timer

    def fire_latest(self) -> None:
        _delay_ms, timer = self.calls[-1]
        if not timer.cancelled:
            timer.callback()


class _MouseListener:
    def __init__(self, on_move: Callable[[int, int], None]) -> None:
        self._on_move = on_move
        self.started = 0
        self.stopped = 0

    def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1

    def join(self, timeout: float | None = None) -> None:
        assert timeout == 1.0

    def emit(self, point: Point) -> None:
        self._on_move(int(point.x), int(point.y))


class _MouseListenerFactory:
    def __init__(self) -> None:
        self.listeners: list[_MouseListener] = []

    def __call__(self, on_move: Callable[[int, int], None]) -> _MouseListener:
        listener = _MouseListener(on_move)
        self.listeners.append(listener)
        return listener


class _HotkeyRuntime:
    def register(self) -> None:
        pass

    def shutdown(self) -> None:
        pass


def _hotkey_factory(_handler: object, _bindings: object, _dispatcher: object) -> _HotkeyRuntime:
    return _HotkeyRuntime()


class _Capture:
    def __init__(self, images: Mapping[Point, ROIImage]) -> None:
        self._images = images
        self.cursors: list[Point] = []
        self.called_on: list[int] = []
        self.closed = False

    def capture_at_cursor(self, cursor: Point) -> CaptureResult:
        self.cursors.append(cursor)
        self.called_on.append(threading.get_ident())
        return CaptureResult(self._images[cursor], _REGION, _TARGET)

    def close(self) -> None:
        self.closed = True


class _Popup:
    def __init__(self) -> None:
        self.results: list[LookupResult] = []
        self.opened_on: list[int] = []
        self.closed = False

    def open(self, result: LookupResult) -> None:
        self.results.append(result)
        self.opened_on.append(threading.get_ident())

    def close(self) -> None:
        self.closed = True


class _OCRProvider:
    def __init__(
        self,
        text_by_image: Mapping[ROIImage, str],
        *,
        block_first: bool = False,
    ) -> None:
        self._text_by_image = text_by_image
        self._block_first = block_first
        self.calls: list[ROIImage] = []
        self.called_on: list[int] = []
        self.first_started = Event()
        self.release_first = Event()

    def recognize(self, image: ROIImage) -> Sequence[OCRResult]:
        self.calls.append(image)
        self.called_on.append(threading.get_ident())
        if self._block_first and len(self.calls) == 1:
            self.first_started.set()
            assert self.release_first.wait(timeout=2)
        return (OCRResult(self._text_by_image[image], 0.99, _QUAD),)


class _MorphologyProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.called_on: list[int] = []

    def analyze(self, text: str) -> Sequence[TokenAnalysis]:
        self.calls.append(text)
        self.called_on.append(threading.get_ident())
        return (TokenAnalysis(token=text, lemma=text),)


class _DictionaryProvider:
    def __init__(self, definitions: Mapping[str, tuple[str, ...]]) -> None:
        self._definitions = definitions
        self.calls: list[str] = []
        self.called_on: list[int] = []

    def lookup(self, lemma: str) -> Sequence[DictionaryEntry]:
        self.calls.append(lemma)
        self.called_on.append(threading.get_ident())
        definitions = self._definitions.get(lemma, ())
        if not definitions:
            return ()
        return (DictionaryEntry(headword=lemma, definitions=definitions),)


class _TargetRecordingResolver:
    def __init__(self) -> None:
        self._delegate = WordResolver()
        self.targets: list[Point] = []

    def resolve_target(
        self,
        ocr_results: Sequence[OCRResult] | None,
        target: Point | None,
    ) -> tuple[OCRResult, str] | None:
        if isinstance(target, Point):
            self.targets.append(target)
        return self._delegate.resolve_target(ocr_results, target)


class _PipelineRuntime:
    def __init__(
        self,
        ocr: _OCRProvider,
        morphology: _MorphologyProvider,
        dictionary: _DictionaryProvider,
        resolver: _TargetRecordingResolver,
    ) -> None:
        self.ocr = ocr
        self.morphology = morphology
        self.dictionary = dictionary
        self.resolver = resolver

    def create_lookup_controller(
        self,
        on_result: Callable[[LookupResult], None] | None = None,
        *,
        result_dispatcher: Callable[[Callable[[], None]], None] | None = None,
        thread_name: str | None = None,
    ):
        return create_lookup_controller(
            lambda: self.ocr,
            lambda: self.morphology,
            lambda: self.dictionary,
            on_result,
            word_resolver_factory=lambda: self.resolver,
            result_dispatcher=result_dispatcher,
            thread_name=thread_name,
        )


def _runtime(
    *,
    definitions: Mapping[str, tuple[str, ...]],
    block_first: bool = False,
) -> tuple[
    ManualLookupRuntime,
    _Scheduler,
    _MouseListenerFactory,
    _QueueDispatcher,
    _Capture,
    _Popup,
    _OCRProvider,
    _MorphologyProvider,
    _DictionaryProvider,
    _TargetRecordingResolver,
]:
    dispatcher = _QueueDispatcher()
    scheduler = _Scheduler()
    listeners = _MouseListenerFactory()
    capture = _Capture(_IMAGE_BY_POINT)
    popup = _Popup()
    text_by_image = {
        _IMAGE_BY_POINT[_UI_POINT]: "책",
        _IMAGE_BY_POINT[_SECOND_POINT]: "둘째",
        _IMAGE_BY_POINT[_LATEST_POINT]: "마지막",
    }
    ocr = _OCRProvider(text_by_image, block_first=block_first)
    morphology = _MorphologyProvider()
    dictionary = _DictionaryProvider(definitions)
    resolver = _TargetRecordingResolver()
    manual = create_manual_lookup(
        _PipelineRuntime(ocr, morphology, dictionary, resolver),
        capture,
        popup.open,
        close_popup=popup.close,
        current_cursor=lambda: _UI_POINT,
        dispatcher=dispatcher,
        hotkey_factory=_hotkey_factory,
        shutdown_scheduler=lambda callback: callback(),
        hover_enabled=True,
        hover_delay_ms=175,
        hover_scheduler=scheduler,
        hover_listener_factory=listeners,
    )
    return (
        manual,
        scheduler,
        listeners,
        dispatcher,
        capture,
        popup,
        ocr,
        morphology,
        dictionary,
        resolver,
    )


def _submit_hover(
    listener: _MouseListener,
    point: Point,
    dispatcher: _QueueDispatcher,
    scheduler: _Scheduler,
) -> None:
    listener.emit(point)
    assert dispatcher.drain_one()
    scheduler.fire_latest()
    assert dispatcher.drain_one()


def _await_hover_ready(
    manual: ManualLookupRuntime,
    dispatcher: _QueueDispatcher,
) -> None:
    hover = manual.hover_runtime
    assert hover is not None
    assert manual.controller.wait_until_ready(timeout=2)
    deadline = monotonic() + 2
    while not hover.hover_controller.running and monotonic() < deadline:
        dispatcher.drain_one(timeout=0.05)
    assert hover.hover_controller.running


def _wait_for_popup(
    dispatcher: _QueueDispatcher,
    popup: _Popup,
    count: int,
    timeout: float = 2,
) -> None:
    deadline = monotonic() + timeout
    while len(popup.results) < count and monotonic() < deadline:
        dispatcher.drain_one(timeout=min(0.05, max(0.0, deadline - monotonic())))
    assert len(popup.results) >= count


@pytest.mark.parametrize(
    ("definitions", "expected_status"),
    [
        ({"책": ("book",)}, LookupStatus.SUCCESS),
        ({}, LookupStatus.NOT_FOUND),
    ],
)
def test_hover_e2e_runs_real_pipeline_and_uses_manual_popup_sink(
    definitions: Mapping[str, tuple[str, ...]],
    expected_status: LookupStatus,
) -> None:
    (
        manual,
        scheduler,
        listeners,
        dispatcher,
        capture,
        popup,
        ocr,
        morphology,
        dictionary,
        resolver,
    ) = _runtime(definitions=definitions)
    ui_thread = threading.get_ident()

    try:
        manual.start()
        _await_hover_ready(manual, dispatcher)
        listener = listeners.listeners[0]
        _submit_hover(listener, _UI_POINT, dispatcher, scheduler)
        _wait_for_popup(dispatcher, popup, 1)

        assert scheduler.calls[0][0] == 175
        assert capture.cursors == [_UI_POINT]
        assert capture.called_on == [ui_thread]
        assert ocr.calls == [_IMAGE_BY_POINT[_UI_POINT]]
        assert morphology.calls == ["책"]
        assert dictionary.calls == ["책"]
        assert ocr.called_on[0] != ui_thread
        assert morphology.called_on[0] == ocr.called_on[0]
        assert dictionary.called_on[0] == ocr.called_on[0]
        assert resolver.targets == [_TARGET]
        assert popup.results[0].status is expected_status
        assert popup.opened_on == [ui_thread]
        assert manual.controller.current_request_id is not None
        assert popup.results[0].context is not None
    finally:
        manual.shutdown()


def test_hover_e2e_supersedes_stale_movement_and_keeps_latest_work_bounded() -> None:
    (
        manual,
        scheduler,
        listeners,
        dispatcher,
        capture,
        popup,
        ocr,
        morphology,
        dictionary,
        resolver,
    ) = _runtime(
        definitions={"책": ("book",), "둘째": ("second",), "마지막": ("latest",)},
        block_first=True,
    )
    try:
        manual.start()
        _await_hover_ready(manual, dispatcher)
        listener = listeners.listeners[0]
        _submit_hover(listener, _UI_POINT, dispatcher, scheduler)
        assert ocr.first_started.wait(timeout=2)

        _submit_hover(listener, _SECOND_POINT, dispatcher, scheduler)
        _submit_hover(listener, _LATEST_POINT, dispatcher, scheduler)
        assert len(ocr.calls) == 1

        ocr.release_first.set()
        _wait_for_popup(dispatcher, popup, 1)

        assert ocr.calls == [_IMAGE_BY_POINT[_UI_POINT], _IMAGE_BY_POINT[_LATEST_POINT]]
        assert capture.cursors == [_UI_POINT, _SECOND_POINT, _LATEST_POINT]
        assert resolver.targets == [_TARGET]
        assert morphology.calls == ["마지막"]
        assert dictionary.calls == ["마지막"]
        result = popup.results[0]
        assert result.context is not None
        assert result.context.text == "마지막"
        assert result.entries[0].headword == "마지막"
    finally:
        ocr.release_first.set()
        manual.shutdown()


def test_hover_e2e_pause_cancels_pending_delay_before_capture_or_lookup() -> None:
    (
        manual,
        scheduler,
        listeners,
        dispatcher,
        capture,
        popup,
        ocr,
        _morphology,
        _dictionary,
        _resolver,
    ) = _runtime(definitions={"책": ("book",)})
    try:
        manual.start()
        _await_hover_ready(manual, dispatcher)
        listener = listeners.listeners[0]
        listener.emit(_UI_POINT)
        assert dispatcher.drain_one()

        manual.pause()
        scheduler.fire_latest()

        assert capture.cursors == []
        assert ocr.calls == []
        assert popup.results == []
        assert listener.stopped == 1
    finally:
        manual.shutdown()
