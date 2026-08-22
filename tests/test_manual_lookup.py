from __future__ import annotations

import os
import threading
from collections.abc import Callable, Mapping
from threading import Event, Thread
from time import monotonic

import pytest
from hanly import DictionaryEntry, LookupResult, LookupStatus, PixelFormat, Point, ROIImage
from hanly_app.capture import CaptureResult, ScreenRect
from hanly_app.hotkeys import HotkeyService
from hanly_app.lookup_controller import LookupController, LookupRequest, ResultDispatcher
from hanly_app.manual_lookup import (
    ManualLookupRuntime,
    ManualLookupStartupError,
    create_manual_lookup,
    create_qt_manual_lookup,
)

_IMAGE = ROIImage(2, 1, PixelFormat.RGB_888, b"\x00\x00\x00\xff\xff\xff")
_CURSOR = Point(120.0, 80.0)
_CAPTURE = CaptureResult(_IMAGE, ScreenRect(20, 30, 2, 1), Point(1.0, 0.5))


def _success(headword: str = "책") -> LookupResult:
    return LookupResult(
        status=LookupStatus.SUCCESS,
        entries=(DictionaryEntry(headword=headword, definitions=("book",)),),
    )


class _QueueDispatcher:
    def __init__(self) -> None:
        self.pending: list[Callable[[], None]] = []
        self.posted_from: list[int] = []
        self.ran_on: list[int] = []

    def __call__(self, callback: Callable[[], None]) -> None:
        self.posted_from.append(threading.get_ident())
        self.pending.append(callback)

    def drain_one(self) -> None:
        callback = self.pending.pop(0)
        self.ran_on.append(threading.get_ident())
        callback()


class _Listener:
    def __init__(self, callbacks: Mapping[str, Callable[[], None]]) -> None:
        self.callbacks = dict(callbacks)
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def join(self, *, timeout: float | None = None) -> None:
        assert timeout == 1.0

    def trigger_lookup(self, binding: str) -> None:
        self.callbacks[binding]()


class _HotkeyFactory:
    def __init__(self) -> None:
        self.listener: _Listener | None = None
        self.dispatcher: ResultDispatcher | None = None

    def __call__(self, on_action, bindings, dispatcher):
        self.dispatcher = dispatcher

        def listener_factory(callbacks: Mapping[str, Callable[[], None]]) -> _Listener:
            self.listener = _Listener(callbacks)
            return self.listener

        return HotkeyService(
            on_action,
            bindings=bindings,
            dispatcher=dispatcher,
            listener_factory=listener_factory,
        )


class _Capture:
    def __init__(self) -> None:
        self.called_on: list[int] = []
        self.cursors: list[Point] = []
        self.closed = False

    def capture_at_cursor(self, cursor: Point) -> CaptureResult:
        self.called_on.append(threading.get_ident())
        self.cursors.append(cursor)
        return _CAPTURE

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


class _Worker:
    def __init__(self, result: LookupResult | None = None) -> None:
        self.called_on: list[int] = []
        self.started = Event()
        self.release = Event()
        self.result = result or _success()

    def __call__(self, request: LookupRequest) -> LookupResult:
        self.called_on.append(threading.get_ident())
        self.started.set()
        assert self.release.wait(timeout=2)
        return self.result

    def close(self) -> None:
        pass


class _Runtime:
    def __init__(self, worker: _Worker) -> None:
        self.worker = worker
        self.controller: LookupController | None = None
        self.dispatcher: ResultDispatcher | None = None

    def create_lookup_controller(
        self,
        on_result: Callable[[LookupResult], None] | None = None,
        *,
        result_dispatcher: ResultDispatcher | None = None,
        thread_name: str | None = None,
    ) -> LookupController:
        assert on_result is not None
        assert result_dispatcher is not None
        self.dispatcher = result_dispatcher
        self.controller = LookupController(
            lambda: self.worker,
            on_result,
            result_dispatcher=result_dispatcher,
            thread_name=thread_name,
        )
        return self.controller


def _composition(
    *,
    worker: _Worker | None = None,
) -> tuple[ManualLookupRuntime, _QueueDispatcher, _HotkeyFactory, _Capture, _Popup, _Worker]:
    queue = _QueueDispatcher()
    hotkeys = _HotkeyFactory()
    capture = _Capture()
    popup = _Popup()
    actual_worker = worker or _Worker()
    composition = create_manual_lookup(
        _Runtime(actual_worker),
        capture,
        popup.open,
        close_popup=popup.close,
        current_cursor=lambda: _CURSOR,
        dispatcher=queue,
        hotkey_factory=hotkeys,
    )
    return composition, queue, hotkeys, capture, popup, actual_worker


def test_lookup_hotkey_posts_to_ui_captures_there_and_delivers_result_on_ui() -> None:
    composition, queue, hotkeys, capture, popup, worker = _composition()
    ui_thread = threading.get_ident()

    composition.start()
    assert hotkeys.listener is not None
    listener = hotkeys.listener
    trigger_thread = Thread(
        target=listener.trigger_lookup,
        args=("<ctrl>+<shift>+<space>",),
    )
    trigger_thread.start()
    trigger_thread.join(timeout=2)

    assert capture.called_on == []
    assert len(queue.pending) == 1
    queue.drain_one()

    assert capture.called_on == [ui_thread]
    assert capture.cursors == [_CURSOR]
    assert worker.started.wait(timeout=2)
    assert worker.called_on[0] != ui_thread

    worker.release.set()
    for _ in range(20):
        if queue.pending:
            break
        Event().wait(0.01)
    assert len(queue.pending) == 1
    queue.drain_one()

    assert popup.results == [_success()]
    assert popup.opened_on == [ui_thread]
    assert hotkeys.dispatcher is queue
    composition.shutdown()


def test_superseded_manual_lookup_result_is_not_presented() -> None:
    composition, queue, hotkeys, capture, popup, worker = _composition()
    composition.start()
    assert hotkeys.listener is not None
    listener = hotkeys.listener
    binding = "<ctrl>+<shift>+<space>"

    listener.trigger_lookup(binding)
    queue.drain_one()
    assert worker.started.wait(timeout=2)

    listener.trigger_lookup(binding)
    queue.drain_one()
    worker.release.set()

    for _ in range(20):
        if queue.pending:
            break
        Event().wait(0.01)
    assert len(queue.pending) == 2
    queue.drain_one()
    assert popup.results == []
    queue.drain_one()
    assert popup.results == [_success()]
    composition.shutdown()


def test_normal_non_success_result_reaches_the_same_popup_path() -> None:
    result = LookupResult(
        status=LookupStatus.NOT_FOUND,
        diagnostics=("Dictionary returned no entries",),
    )
    composition, queue, hotkeys, _capture, popup, worker = _composition(
        worker=_Worker(result)
    )
    composition.start()
    assert hotkeys.listener is not None

    hotkeys.listener.trigger_lookup("<ctrl>+<shift>+<space>")
    queue.drain_one()
    assert worker.started.wait(timeout=2)
    worker.release.set()
    for _ in range(20):
        if queue.pending:
            break
        Event().wait(0.01)
    queue.drain_one()

    assert popup.results == [result]
    composition.shutdown()


def test_shutdown_returns_without_waiting_for_lookup_or_hotkey_cleanup() -> None:
    composition, queue, hotkeys, capture, popup, worker = _composition()
    composition.start()
    assert hotkeys.listener is not None
    hotkeys.listener.trigger_lookup("<ctrl>+<shift>+<space>")
    queue.drain_one()
    assert worker.started.wait(timeout=2)

    started = monotonic()
    composition.shutdown()
    elapsed = monotonic() - started

    assert elapsed < 0.5
    assert capture.closed
    assert popup.closed
    assert worker.release.is_set() is False

    worker.release.set()
    for _ in range(20):
        if queue.pending:
            break
        Event().wait(0.01)
    if queue.pending:
        queue.drain_one()
    assert popup.results == []


def test_failed_hotkey_registration_still_closes_popup_and_capture() -> None:
    """A runtime that cannot register its hotkey must not strand the popup and
    capture service it already owns behind a permanently closed flag."""

    class _FailingHotkeys:
        def __init__(self) -> None:
            self.shutdown_calls = 0

        def __call__(self, on_action, bindings, dispatcher) -> _FailingHotkeys:
            del on_action, bindings, dispatcher
            return self

        def register(self) -> None:
            raise RuntimeError("hotkey is already claimed by another process")

        def shutdown(self) -> None:
            self.shutdown_calls += 1

    queue = _QueueDispatcher()
    hotkeys = _FailingHotkeys()
    capture = _Capture()
    popup = _Popup()
    composition = create_manual_lookup(
        _Runtime(_Worker()),
        capture,
        popup.open,
        close_popup=popup.close,
        current_cursor=lambda: _CURSOR,
        dispatcher=queue,
        hotkey_factory=hotkeys,
        shutdown_scheduler=lambda callback: callback(),
    )

    with pytest.raises(ManualLookupStartupError):
        composition.start()

    assert popup.closed
    assert capture.closed
    assert hotkeys.shutdown_calls == 1
    assert composition.started is False
    # Shutdown stays idempotent, so a caller's own cleanup is still safe.
    composition.shutdown()
    assert hotkeys.shutdown_calls == 1


def test_qt_composition_shares_one_dispatcher_between_hotkeys_and_results() -> None:
    """``create_qt_manual_lookup`` is the composition the alpha actually runs.
    Both the hotkey service and the lookup controller must post through the
    same Qt dispatcher instance."""

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PyQt6.QtWidgets")
    from hanly_app.qt_popup import QtResultDispatcher
    from PyQt6.QtWidgets import QApplication

    application = QApplication.instance() or QApplication([])
    assert application is not None

    runtime = _Runtime(_Worker())
    hotkeys = _HotkeyFactory()
    capture = _Capture()
    composition = create_qt_manual_lookup(
        runtime,
        capture,
        hotkey_factory=hotkeys,
        shutdown_scheduler=lambda callback: callback(),
    )

    assert isinstance(runtime.dispatcher, QtResultDispatcher)
    assert hotkeys.dispatcher is runtime.dispatcher
    assert composition.controller is runtime.controller

    composition.shutdown()
    assert capture.closed
