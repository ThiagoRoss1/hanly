from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from threading import Event, Thread
from typing import Any, cast

import pytest
from hanly import DictionaryEntry, LookupResult, LookupStatus, PixelFormat, Point, ROIImage
from hanly_app.capture import CaptureResult, ScreenRect
from hanly_app.hotkeys import (
    HotkeyAction,
    HotkeyEdge,
    HotkeyEdgeHandler,
    HotkeyService,
)
from hanly_app.lookup_controller import LookupController, LookupRequest, ResultDispatcher
from hanly_app.manual_lookup import (
    ManualLookupRuntime,
    create_manual_lookup,
    create_qt_manual_lookup,
)

_IMAGE = ROIImage(2, 1, PixelFormat.RGB_888, b"\x00\x00\x00\xff\xff\xff")
#: The one-shot lookup no longer has a default shortcut, so a test that drives
#: that path binds one explicitly, the way an embedding client would.
_LOOKUP_BINDING = "ctrl+alt+space"
_CANONICAL_LOOKUP_BINDING = "<ctrl>+<alt>+<space>"

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
    def __init__(self, callbacks: Mapping[str, HotkeyEdgeHandler]) -> None:
        self.callbacks = dict(callbacks)
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def join(self, timeout: float | None = None) -> None:
        assert timeout == 1.0

    def trigger(self, binding: str, edge: HotkeyEdge = HotkeyEdge.DOWN) -> None:
        self.callbacks[binding](edge)


class _HotkeyFactory:
    def __init__(self) -> None:
        self.listener: _Listener | None = None
        self.dispatcher: ResultDispatcher | None = None

    def __call__(self, on_action, bindings, dispatcher):
        self.dispatcher = dispatcher

        def listener_factory(callbacks: Mapping[str, HotkeyEdgeHandler]) -> _Listener:
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
        # The composition passes the optional seams through only when a caller
        # supplied them, so this double has to accept them the same way.
        **options: object,
    ) -> LookupController:
        assert on_result is not None
        assert result_dispatcher is not None
        self.dispatcher = result_dispatcher
        self.controller = LookupController(
            lambda: self.worker,
            on_result,
            result_dispatcher=result_dispatcher,
            thread_name=thread_name,
            **cast(Any, options),
        )
        return self.controller


class _TraceSink:
    """Collect the runtime trace the manual path emits."""

    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def emit(self, event: Mapping[str, object]) -> None:
        self.events.append(dict(event))

    def kinds(self, prefix: str) -> list[str]:
        return [
            str(event["event_kind"])
            for event in self.events
            if str(event["event_kind"]).startswith(prefix)
        ]

    def first(self, kind: str) -> dict[str, object]:
        for event in self.events:
            if event["event_kind"] == kind:
                return event
        raise AssertionError(f"no {kind} event was emitted")


def _composition(
    *,
    worker: _Worker | None = None,
    trace_sink: _TraceSink | None = None,
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
        trace_sink=trace_sink,
        # The one-shot lookup has no default shortcut any more, so a test that
        # is about that path has to bind it the way an embedding client would.
        lookup_hotkey=_LOOKUP_BINDING,
    )
    return composition, queue, hotkeys, capture, popup, actual_worker


def test_lookup_hotkey_posts_to_ui_captures_there_and_delivers_result_on_ui() -> None:
    composition, queue, hotkeys, capture, popup, worker = _composition()
    ui_thread = threading.get_ident()

    composition.start()
    assert hotkeys.listener is not None
    listener = hotkeys.listener
    trigger_thread = Thread(
        target=listener.trigger,
        args=(_CANONICAL_LOOKUP_BINDING,),
    )
    trigger_thread.start()
    trigger_thread.join(timeout=5)

    assert not trigger_thread.is_alive()
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


def test_app_config_initializes_hotkey_and_capture_mode() -> None:
    from hanly_app.config import AppConfig, CaptureMode

    queue = _QueueDispatcher()
    hotkeys = _HotkeyFactory()
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
        app_config=AppConfig(hotkey="alt+shift+h", capture_mode=CaptureMode.REGION),
    )

    assert composition.capture_service.capture_mode is CaptureMode.REGION
    composition.start()
    assert hotkeys.listener is not None
    assert "<shift>+<alt>+h" in hotkeys.listener.callbacks
    composition.shutdown()


def test_superseded_manual_lookup_result_is_not_presented() -> None:
    composition, queue, hotkeys, capture, popup, worker = _composition()
    composition.start()
    assert hotkeys.listener is not None
    listener = hotkeys.listener
    binding = _CANONICAL_LOOKUP_BINDING

    listener.trigger(binding)
    queue.drain_one()
    assert worker.started.wait(timeout=2)

    listener.trigger(binding)
    queue.drain_one()
    worker.release.set()

    for _ in range(20):
        if queue.pending:
            break
        Event().wait(0.01)
    assert len(queue.pending) == 1
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

    hotkeys.listener.trigger(_CANONICAL_LOOKUP_BINDING)
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
    hotkeys.listener.trigger(_CANONICAL_LOOKUP_BINDING)
    queue.drain_one()
    assert worker.started.wait(timeout=2)

    # Shutting down on this thread would block on the worker still holding
    # ``release``, so a regression has to surface as a bounded wait rather than
    # as a stopwatch reading that a loaded machine can fail on its own.
    finished = Event()

    def shut_down() -> None:
        composition.shutdown()
        finished.set()

    shutdown_thread = Thread(target=shut_down)
    shutdown_thread.start()
    try:
        assert finished.wait(timeout=5), "shutdown waited for the running lookup"
        assert capture.closed
        assert popup.closed
        assert worker.release.is_set() is False
    finally:
        # Releasing and joining here as well: a failed assertion above must not
        # leave the worker blocked or the shutdown thread outliving the test.
        worker.release.set()
        shutdown_thread.join(timeout=5)
        assert not shutdown_thread.is_alive()

    for _ in range(20):
        if queue.pending:
            break
        Event().wait(0.01)
    if queue.pending:
        queue.drain_one()
    assert popup.results == []


def test_a_hotkey_another_application_owns_costs_only_that_shortcut() -> None:
    """Registration happens with the session, not with capture. Losing a
    combination to another application must not also cost the user the popup,
    the tray, and everything else the session was about to provide."""

    class _FailingHotkeys:
        def __init__(self) -> None:
            self.shutdown_calls = 0

        def __call__(self, on_action, bindings, dispatcher) -> _FailingHotkeys:
            del on_action, bindings, dispatcher
            return self

        @property
        def bindings(self) -> Mapping[HotkeyAction, str]:
            return {}

        @property
        def registered(self) -> bool:
            return False

        def register(self) -> None:
            raise RuntimeError("hotkey is already claimed by another process")

        def shutdown(self) -> None:
            self.shutdown_calls += 1

    reported: list[str] = []
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
        on_error=lambda stage, error: reported.append(f"{stage}: {error}"),
    )

    composition.start()

    assert reported == ["Keyboard shortcuts: hotkey is already claimed by another process"]
    assert composition.prepared is True
    assert composition.started is True
    assert not popup.closed
    assert not capture.closed

    composition.shutdown()
    assert popup.closed
    assert capture.closed
    assert hotkeys.shutdown_calls == 1


def test_qt_composition_shares_one_dispatcher_between_hotkeys_and_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``create_qt_manual_lookup`` is the composition the alpha actually runs.
    Both the hotkey service and the lookup controller must post through the
    same Qt dispatcher instance."""

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
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


def test_the_manual_hotkey_path_traces_every_stage_it_reaches() -> None:
    """The one-shot hotkey has no visible effect of its own until the popup.

    A global key combination that is consumed by the window server looks
    identical, from the outside, whether it reached capture, stopped at an
    unavailable screen, or never arrived: the trace is what says which.
    """

    trace = _TraceSink()
    composition, queue, hotkeys, capture, popup, worker = _composition(trace_sink=trace)
    composition.start()
    assert hotkeys.listener is not None

    hotkeys.listener.trigger(_CANONICAL_LOOKUP_BINDING)
    queue.drain_one()
    assert worker.started.wait(timeout=2)
    worker.release.set()
    for _ in range(20):
        if queue.pending:
            break
        Event().wait(0.01)
    queue.drain_one()

    assert trace.kinds("manual_") == [
        "manual_action_received",
        "manual_capture_completed",
        "manual_submission",
    ]
    captured = trace.first("manual_capture_completed")
    assert (captured["roi_width"], captured["roi_height"]) == (
        _CAPTURE.image.width,
        _CAPTURE.image.height,
    )
    assert trace.first("manual_submission")["lookup_request_id"] == 1
    assert popup.results == [_success()]
    composition.shutdown()


def test_a_manual_lookup_that_cannot_capture_says_where_it_stopped() -> None:
    trace = _TraceSink()
    composition, queue, hotkeys, capture, popup, _ = _composition(trace_sink=trace)

    def failing_capture(cursor: Point) -> CaptureResult:
        raise RuntimeError("the screen is unavailable")

    capture.capture_at_cursor = failing_capture  # type: ignore[method-assign]
    composition.start()
    assert hotkeys.listener is not None

    hotkeys.listener.trigger(_CANONICAL_LOOKUP_BINDING)
    queue.drain_one()

    assert trace.kinds("manual_") == ["manual_action_received", "manual_action_error"]
    error = trace.first("manual_action_error")
    assert error["stage"] == "screen capture"
    assert error["error_type"] == "RuntimeError"
    # The user still hears about it, in the popup rather than only in a trace.
    assert popup.results[0].status is LookupStatus.ERROR
    composition.shutdown()


def test_the_manual_hotkey_still_completes_a_lookup_after_capture_stops() -> None:
    """Stop ends the capture session; the one-shot hotkey is a separate trigger.

    This is the Stop-then-hotkey path a user takes to look one word up without
    Hanly watching the screen, so the whole sequence has to still run.
    """

    trace = _TraceSink()
    composition, queue, hotkeys, capture, popup, worker = _composition(trace_sink=trace)
    composition.start()
    assert hotkeys.listener is not None
    composition.stop()

    hotkeys.listener.trigger(_CANONICAL_LOOKUP_BINDING)
    queue.drain_one()
    assert worker.started.wait(timeout=2)
    worker.release.set()
    for _ in range(20):
        if queue.pending:
            break
        Event().wait(0.01)
    queue.drain_one()

    assert trace.kinds("manual_") == [
        "manual_action_received",
        "manual_capture_completed",
        "manual_submission",
    ]
    assert capture.cursors == [_CURSOR]
    assert popup.results == [_success()]
    composition.shutdown()


def test_a_hotkey_that_arrives_before_the_session_is_prepared_is_ignored() -> None:
    """There is no lookup path to submit to yet, so the action is dropped
    rather than turned into an error popup about a stopped executor."""

    trace = _TraceSink()
    composition, queue, hotkeys, capture, _, _ = _composition(trace_sink=trace)
    # register() without prepare() is what the hotkey factory double gives us,
    # so the listener exists before the runtime accepts actions.
    composition.hotkeys.register()
    assert hotkeys.listener is not None

    hotkeys.listener.trigger(_CANONICAL_LOOKUP_BINDING)
    queue.drain_one()

    assert trace.kinds("manual_") == ["manual_action_ignored"]
    assert capture.called_on == []
    composition.shutdown()
