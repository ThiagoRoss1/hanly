from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from threading import Event
from typing import Any, cast

import pytest
from hanly import DictionaryEntry, LookupResult, LookupStatus, PixelFormat, Point, ROIImage
from hanly_app.capture import CaptureResult, ScreenRect
from hanly_app.config import AppConfig, HoverActivation
from hanly_app.hotkeys import (
    HotkeyAction,
    HotkeyEdge,
    HotkeyEdgeHandler,
    HotkeyService,
)
from hanly_app.hover_lookup import HoverLookupRuntime
from hanly_app.lookup_controller import LookupController, LookupRequest, ResultDispatcher
from hanly_app.manual_lookup import ManualLookupRuntime, create_manual_lookup

_IMAGE = ROIImage(2, 1, PixelFormat.RGB_888, b"\x00\x00\x00\xff\xff\xff")
_CAPTURE = CaptureResult(_IMAGE, ScreenRect(20, 30, 2, 1), Point(1.0, 0.5))


def _result(headword: str = "책") -> LookupResult:
    return LookupResult(
        status=LookupStatus.SUCCESS,
        entries=(DictionaryEntry(headword=headword, definitions=("book",)),),
    )


#: These tests are about the hover pipeline, not about how it is switched on,
#: so they use the mode that observes for the whole session.
_ALWAYS_ACTIVE = AppConfig(hover_activation=HoverActivation.ALWAYS_ACTIVE)

class _Handle:
    def __init__(self, callback: Callable[[], None]) -> None:
        self.callback = callback
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class _Scheduler:
    def __init__(self) -> None:
        self.calls: list[tuple[float, _Handle]] = []

    def __call__(self, delay_ms: float, callback: Callable[[], None]) -> _Handle:
        handle = _Handle(callback)
        self.calls.append((delay_ms, handle))
        return handle

    def fire(self, index: int = -1) -> None:
        self.calls[index][1].callback()


class _Listener:
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

    def emit(self, x: int, y: int) -> None:
        self._on_move(x, y)


class _ListenerFactory:
    def __init__(self) -> None:
        self.listeners: list[_Listener] = []

    def __call__(self, on_move: Callable[[int, int], None]) -> _Listener:
        listener = _Listener(on_move)
        self.listeners.append(listener)
        return listener


class _Capture:
    def __init__(self, result: CaptureResult = _CAPTURE) -> None:
        self.result = result
        self.cursors: list[Point] = []
        self.called_on: list[int] = []
        self.closed = False

    def capture_at_cursor(self, cursor: Point) -> CaptureResult:
        self.cursors.append(cursor)
        self.called_on.append(threading.get_ident())
        return self.result

    def close(self) -> None:
        self.closed = True


class _Worker:
    def __init__(self, results: Mapping[int, LookupResult] | None = None) -> None:
        self.results = dict(results or {})
        self.started = Event()
        self.release = Event()
        self.calls: list[tuple[LookupRequest, int]] = []

    def __call__(self, request: LookupRequest) -> LookupResult:
        self.calls.append((request, threading.get_ident()))
        self.started.set()
        assert self.release.wait(timeout=2)
        return self.results.get(request.request_id, _result())

    def close(self) -> None:
        pass


class _QueueDispatcher:
    def __init__(self) -> None:
        self.pending: list[Callable[[], None]] = []

    def __call__(self, callback: Callable[[], None]) -> None:
        self.pending.append(callback)

    def drain_one(self) -> None:
        self.pending.pop(0)()


class _HotkeyRuntime:
    def __init__(self) -> None:
        self.registered = False
        self.closed = False

    @property
    def bindings(self) -> Mapping[HotkeyAction, str]:
        return {HotkeyAction.LOOKUP: "<ctrl>+<shift>+<space>"}

    def register(self) -> None:
        self.registered = True

    def shutdown(self) -> None:
        self.closed = True


class _HotkeyFactory:
    def __init__(self) -> None:
        self.runtime = _HotkeyRuntime()

    def __call__(self, _handler, _bindings, _dispatcher) -> _HotkeyRuntime:
        return self.runtime


class _KeyListener:
    """A keyboard that both edges of a chord can be delivered through."""

    def __init__(self, callbacks: Mapping[str, HotkeyEdgeHandler]) -> None:
        self.callbacks = dict(callbacks)

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def join(self, timeout: float | None = None) -> None:
        del timeout

    def press(self, binding: str) -> None:
        self.callbacks[binding](HotkeyEdge.DOWN)

    def release(self, binding: str) -> None:
        self.callbacks[binding](HotkeyEdge.UP)


class _RealHotkeys:
    """The production service over a fake keyboard, so edges really travel."""

    def __init__(self) -> None:
        self.listener: _KeyListener | None = None

    def __call__(self, on_action, bindings, dispatcher) -> HotkeyService:
        def factory(callbacks: Mapping[str, HotkeyEdgeHandler]) -> _KeyListener:
            self.listener = _KeyListener(callbacks)
            return self.listener

        return HotkeyService(
            on_action,
            bindings=bindings,
            dispatcher=dispatcher,
            listener_factory=factory,
        )


def _runtime(
    *,
    worker: _Worker | None = None,
    capture: _Capture | None = None,
    on_invalidate: Callable[[], None] | None = None,
) -> tuple[
    HoverLookupRuntime,
    _Scheduler,
    _ListenerFactory,
    _QueueDispatcher,
    _Capture,
    _Worker,
    list[LookupResult],
]:
    scheduler = _Scheduler()
    listeners = _ListenerFactory()
    dispatcher = _QueueDispatcher()
    actual_capture = capture or _Capture()
    actual_worker = worker or _Worker()
    results: list[LookupResult] = []
    controller = LookupController(
        lambda: actual_worker,
        results.append,
        result_dispatcher=dispatcher,
    )
    runtime = HoverLookupRuntime(
        controller,
        actual_capture,
        delay_ms=220,
        scheduler=scheduler,
        dispatcher=dispatcher,
        listener_factory=listeners,
        on_invalidate=on_invalidate,
    )
    return runtime, scheduler, listeners, dispatcher, actual_capture, actual_worker, results


def _await_hover_ready(
    runtime: HoverLookupRuntime,
    dispatcher: _QueueDispatcher,
) -> None:
    assert runtime.controller.wait_until_ready(timeout=2)
    for _ in range(100):
        if dispatcher.pending:
            dispatcher.drain_one()
        if runtime.hover_controller.running:
            return
        Event().wait(0.01)
    raise AssertionError("hover observation did not start after worker readiness")


def test_stable_hover_captures_cursor_roi_and_uses_worker_popup_path() -> None:
    runtime, scheduler, listeners, dispatcher, capture, worker, results = _runtime()
    caller_thread = threading.get_ident()

    runtime.start()
    _await_hover_ready(runtime, dispatcher)
    listeners.listeners[0].emit(120, 80)
    dispatcher.drain_one()
    assert scheduler.calls[0][0] == 220
    scheduler.fire()
    dispatcher.drain_one()

    assert capture.cursors == [Point(120, 80)]
    assert capture.called_on == [caller_thread]
    assert worker.started.wait(timeout=2)
    assert worker.calls[0][0].image is _IMAGE
    assert worker.calls[0][0].target == _CAPTURE.target
    assert worker.calls[0][1] != caller_thread

    worker.release.set()
    for _ in range(20):
        if dispatcher.pending:
            break
        Event().wait(0.01)
    if dispatcher.pending:
        dispatcher.drain_one()

    assert results == [_result()]
    runtime.shutdown()


def test_cursor_movement_clears_any_previous_popup_immediately() -> None:
    cleared: list[str] = []
    runtime, _scheduler, listeners, dispatcher, _capture, _worker, _results = _runtime(
        on_invalidate=lambda: cleared.append("clear")
    )
    runtime.start()
    _await_hover_ready(runtime, dispatcher)

    listeners.listeners[0].emit(10, 20)
    dispatcher.drain_one()

    assert cleared == ["clear"]
    runtime.shutdown()


def test_hover_capture_is_gated_until_resident_worker_is_ready() -> None:
    release_factory = Event()
    factory_entered = Event()
    scheduler = _Scheduler()
    listeners = _ListenerFactory()
    dispatcher = _QueueDispatcher()
    capture = _Capture()
    worker = _Worker()

    def factory() -> _Worker:
        factory_entered.set()
        assert release_factory.wait(timeout=2)
        return worker

    controller = LookupController(factory, lambda _result: None)
    runtime = HoverLookupRuntime(
        controller,
        capture,
        scheduler=scheduler,
        dispatcher=dispatcher,
        listener_factory=listeners,
    )

    runtime.start()
    assert factory_entered.wait(timeout=2)
    listeners.listeners[0].emit(50, 60)
    dispatcher.drain_one()

    assert scheduler.calls == []
    assert capture.cursors == []

    release_factory.set()
    for _ in range(100):
        if dispatcher.pending:
            break
        Event().wait(0.01)
    dispatcher.drain_one()

    assert scheduler.calls
    runtime.shutdown()


def test_mouse_move_supersedes_hover_and_stale_result_is_not_presented() -> None:
    runtime, scheduler, listeners, dispatcher, _capture, worker, results = _runtime()
    runtime.start()
    _await_hover_ready(runtime, dispatcher)

    listeners.listeners[0].emit(100, 100)
    dispatcher.drain_one()
    scheduler.fire()
    dispatcher.drain_one()
    assert worker.started.wait(timeout=2)

    listeners.listeners[0].emit(200, 200)
    dispatcher.drain_one()
    worker.release.set()

    for _ in range(20):
        if dispatcher.pending:
            break
        Event().wait(0.01)
    if dispatcher.pending:
        dispatcher.drain_one()

    assert results == []
    runtime.shutdown()


def test_hover_forwards_normal_non_success_result_to_the_existing_popup_sink() -> None:
    not_found = LookupResult(
        status=LookupStatus.NOT_FOUND,
        diagnostics=("Dictionary returned no entries",),
    )
    runtime, scheduler, listeners, dispatcher, _capture, worker, results = _runtime(
        worker=_Worker({1: not_found})
    )
    runtime.start()
    _await_hover_ready(runtime, dispatcher)

    listeners.listeners[0].emit(100, 100)
    dispatcher.drain_one()
    scheduler.fire()
    dispatcher.drain_one()
    assert worker.started.wait(timeout=2)
    worker.release.set()
    for _ in range(20):
        if dispatcher.pending:
            break
        Event().wait(0.01)
    dispatcher.drain_one()

    assert results == [not_found]
    runtime.shutdown()


def test_pause_cancels_pending_hover_and_shutdown_suppresses_queued_work() -> None:
    runtime, scheduler, listeners, dispatcher, capture, worker, results = _runtime()
    runtime.start()
    _await_hover_ready(runtime, dispatcher)

    listeners.listeners[0].emit(10, 20)
    dispatcher.drain_one()
    runtime.pause()
    scheduler.fire()
    assert dispatcher.pending == []
    assert capture.cursors == []

    runtime.resume()
    listeners.listeners[0].emit(30, 40)
    dispatcher.drain_one()
    scheduler.fire()
    dispatcher.drain_one()
    assert worker.started.wait(timeout=2)

    runtime.shutdown()
    worker.release.set()
    for _ in range(20):
        if dispatcher.pending:
            break
        Event().wait(0.01)
    if dispatcher.pending:
        dispatcher.drain_one()

    assert listeners.listeners[0].stopped == 1
    assert capture.closed is False
    assert results == []


def test_mouse_move_before_hover_submission_does_not_cancel_manual_lookup() -> None:
    runtime, scheduler, listeners, dispatcher, _capture, worker, results = _runtime()
    runtime.start()
    _await_hover_ready(runtime, dispatcher)

    manual_request = runtime.controller.submit(_IMAGE, Point(0, 0))
    assert worker.started.wait(timeout=2)

    worker.release.set()
    for _ in range(20):
        if dispatcher.pending:
            break
        Event().wait(0.01)
    dispatcher.drain_one()
    assert results == [_result()]

    listeners.listeners[0].emit(30, 40)
    dispatcher.drain_one()
    assert runtime.controller.is_current(manual_request)

    scheduler.fire()
    dispatcher.drain_one()
    for _ in range(20):
        if dispatcher.pending:
            break
        Event().wait(0.01)
    dispatcher.drain_one()

    assert results == [_result(), _result()]
    runtime.shutdown()


def test_invalid_capture_result_is_reported_without_submitting_unbounded_work() -> None:
    errors: list[tuple[str, BaseException]] = []
    scheduler = _Scheduler()
    listeners = _ListenerFactory()
    dispatcher = _QueueDispatcher()
    worker = _Worker()
    controller = LookupController(lambda: worker, lambda _result: None)
    runtime = HoverLookupRuntime(
        controller,
        _Capture(result=cast(CaptureResult, object())),
        delay_ms=100,
        scheduler=scheduler,
        dispatcher=dispatcher,
        listener_factory=listeners,
        on_error=lambda stage, error: errors.append((stage, error)),
    )
    runtime.start()
    _await_hover_ready(runtime, dispatcher)
    listeners.listeners[0].emit(1, 2)
    dispatcher.drain_one()
    scheduler.fire()
    dispatcher.drain_one()

    assert errors and errors[0][0] == "hover capture"
    assert worker.started.is_set() is False
    runtime.shutdown()


def test_manual_composition_attaches_hover_to_the_same_controller_capture_and_popup() -> None:
    scheduler = _Scheduler()
    listeners = _ListenerFactory()
    dispatcher = _QueueDispatcher()
    worker = _Worker()
    capture = _Capture()

    class _RuntimeComposition:
        def create_lookup_controller(
            self,
            on_result: Callable[[LookupResult], None] | None = None,
            *,
            result_dispatcher: ResultDispatcher | None = None,
            thread_name: str | None = None,
        ) -> LookupController:
            del thread_name
            assert on_result is not None
            assert result_dispatcher is not None
            return LookupController(
                lambda: worker,
                on_result,
                result_dispatcher=result_dispatcher,
            )

    popup_results: list[LookupResult] = []
    hotkeys = _HotkeyFactory()
    manual = create_manual_lookup(
        _RuntimeComposition(),
        capture,
        popup_results.append,
        close_popup=lambda: None,
        current_cursor=lambda: Point(0, 0),
        dispatcher=dispatcher,
        hotkey_factory=hotkeys,
        hover_enabled=True,
        hover_delay_ms=120,
        hover_scheduler=scheduler,
        hover_listener_factory=listeners,
        app_config=_ALWAYS_ACTIVE,
    )
    manual.start()
    assert manual.hover_runtime is not None
    _await_hover_ready(manual.hover_runtime, dispatcher)
    listeners.listeners[0].emit(50, 60)
    dispatcher.drain_one()
    scheduler.fire()
    dispatcher.drain_one()
    assert worker.started.wait(timeout=2)
    worker.release.set()
    for _ in range(20):
        if dispatcher.pending:
            break
        Event().wait(0.01)
    dispatcher.drain_one()

    assert popup_results == [_result()]

    manual.stop()
    # Pausing stops watching the screen; the session and its shortcuts stay up.
    assert manual.started is False
    assert manual.prepared is True
    assert listeners.listeners[0].stopped == 1
    manual.start()
    assert len(listeners.listeners) == 2
    assert listeners.listeners[1].started == 1
    manual.shutdown()



def _manual_composition(
    *,
    worker_factory: Callable[[], object] | None = None,
    scheduler: object | None = None,
    app_config: object | None = None,
    on_error: Callable[[str, BaseException], None] | None = None,
    hotkeys: object | None = None,
) -> tuple[
    ManualLookupRuntime, _QueueDispatcher, _ListenerFactory, _Capture, list[LookupResult]
]:
    listeners = _ListenerFactory()
    dispatcher = _QueueDispatcher()
    capture = _Capture()
    worker = _Worker()
    popup_results: list[LookupResult] = []

    class _RuntimeComposition:
        def create_lookup_controller(
            self,
            on_result: Callable[[LookupResult], None] | None = None,
            *,
            result_dispatcher: ResultDispatcher | None = None,
            thread_name: str | None = None,
        ) -> LookupController:
            del thread_name
            assert on_result is not None
            return LookupController(
                worker_factory or (lambda: worker),
                on_result,
                result_dispatcher=result_dispatcher,
            )

    manual = create_manual_lookup(
        _RuntimeComposition(),
        capture,
        popup_results.append,
        close_popup=lambda: None,
        current_cursor=lambda: Point(0, 0),
        dispatcher=dispatcher,
        hotkey_factory=cast(Any, hotkeys or _HotkeyFactory()),
        hover_enabled=True,
        hover_scheduler=cast(Any, scheduler or _Scheduler()),
        hover_listener_factory=listeners,
        hover_on_error=on_error,
        app_config=cast(Any, app_config or _ALWAYS_ACTIVE),
    )
    return manual, dispatcher, listeners, capture, popup_results


def _drain(dispatcher: _QueueDispatcher) -> None:
    while dispatcher.pending:
        dispatcher.drain_one()


def _settle(dispatcher: _QueueDispatcher, listeners: _ListenerFactory,
            scheduler: _Scheduler, x: int) -> None:
    """Emit one movement and let its stability delay expire."""

    listeners.listeners[-1].emit(x, 10)
    _drain(dispatcher)
    scheduler.fire()
    _drain(dispatcher)


def test_fatal_lookup_failure_stops_hover_instead_of_capturing_forever() -> None:
    """A worker whose providers cannot be constructed kills the single-use
    executor. Hover must then stop observing rather than keep capturing the
    screen for results that can never arrive."""

    def failing_factory() -> object:
        raise RuntimeError("OCR is unavailable: model files are missing")

    events: list[tuple[str, str]] = []
    scheduler = _Scheduler()
    manual, dispatcher, listeners, capture, popup_results = _manual_composition(
        worker_factory=failing_factory,
        scheduler=scheduler,
        on_error=lambda stage, error: events.append((stage, str(error))),
    )
    manual.start()
    hover = manual.hover_runtime
    assert hover is not None

    for _ in range(500):
        _drain(dispatcher)
        if hover.failed:
            break
        Event().wait(0.01)
    assert manual.controller.accepting is False

    assert hover.failed is True
    assert hover.running is False
    assert hover.mouse_observer.running is False

    captures_after_failure = len(capture.cursors)
    listeners.listeners[-1].emit(90, 10)
    _drain(dispatcher)
    assert len(capture.cursors) == captures_after_failure

    assert [stage for stage, _ in events] == ["automatic hover disabled"]
    with pytest.raises(RuntimeError, match="until Hanly is restarted"):
        hover.resume()
    manual.shutdown()


def test_invalidate_keeps_observing_while_pause_stops_observation() -> None:
    """Dropping the current attempt is a currency operation; only pause may
    deregister the global listener."""

    manual, dispatcher, listeners, capture, popup_results = _manual_composition()
    manual.start()
    hover = manual.hover_runtime
    assert hover is not None

    manual.invalidate()
    assert hover.running is True
    assert hover.mouse_observer.running is True
    assert listeners.listeners[0].stopped == 0

    manual.stop()
    assert hover.running is False
    assert hover.mouse_observer.running is False
    assert listeners.listeners[0].stopped == 1

    manual.start()
    assert hover.running is True
    manual.shutdown()


def test_configured_hover_delay_reaches_the_scheduler() -> None:
    scheduler = _Scheduler()
    manual, dispatcher, listeners, capture, popup_results = _manual_composition(
        scheduler=scheduler,
        app_config=AppConfig(
            hover_delay_ms=220, hover_activation=HoverActivation.ALWAYS_ACTIVE
        ),
    )
    manual.start()
    assert manual.hover_runtime is not None
    _await_hover_ready(manual.hover_runtime, dispatcher)
    listeners.listeners[0].emit(40, 10)
    dispatcher.drain_one()

    assert [delay for delay, _ in scheduler.calls] == [220.0]
    manual.shutdown()


def test_pausing_capture_clears_the_visible_lookup_popup() -> None:
    """Whatever the popup last showed describes work that is no longer
    running, so stopping capture must not leave it on screen."""

    cleared: list[str] = []
    closed: list[str] = []
    listeners = _ListenerFactory()
    dispatcher = _QueueDispatcher()
    worker = _Worker()

    class _RuntimeComposition:
        def create_lookup_controller(
            self,
            on_result: Callable[[LookupResult], None] | None = None,
            *,
            result_dispatcher: ResultDispatcher | None = None,
            thread_name: str | None = None,
        ) -> LookupController:
            del thread_name
            assert on_result is not None
            return LookupController(
                lambda: worker, on_result, result_dispatcher=result_dispatcher
            )

    manual = create_manual_lookup(
        _RuntimeComposition(),
        _Capture(),
        lambda result: None,
        close_popup=lambda: closed.append("close"),
        clear_popup=lambda: cleared.append("clear"),
        current_cursor=lambda: Point(0, 0),
        dispatcher=dispatcher,
        hotkey_factory=_HotkeyFactory(),
        hover_enabled=True,
        hover_scheduler=cast(Any, _Scheduler()),
        hover_listener_factory=listeners,
        app_config=_ALWAYS_ACTIVE,
    )
    manual.start()

    # Dropping stale currency alone must not disturb the popup.
    manual.invalidate()
    assert cleared == []

    manual.stop()
    assert cleared == ["clear"]
    assert closed == []

    manual.shutdown()
    assert closed == ["close"]


_PUSH = "<ctrl>+<shift>+<space>"
_PUSH_CONFIG = AppConfig(hover_activation=HoverActivation.PUSH_TO_HOVER)


def _push_composition() -> tuple[
    ManualLookupRuntime, _QueueDispatcher, _ListenerFactory, _Capture, _RealHotkeys
]:
    hotkeys = _RealHotkeys()
    manual, dispatcher, listeners, capture, _results = _manual_composition(
        app_config=_PUSH_CONFIG, hotkeys=hotkeys
    )
    return manual, dispatcher, listeners, capture, hotkeys


def test_push_to_hover_observes_only_while_the_chord_is_held() -> None:
    """The whole point of the default mode: no observation, no dwell, and no
    capture while the keys are up."""

    manual, dispatcher, listeners, capture, hotkeys = _push_composition()
    manual.start()
    assert manual.hover_runtime is not None
    _await_hover_ready(manual.hover_runtime, dispatcher)
    assert hotkeys.listener is not None

    # Started, but nothing held: movement reaches no listener at all.
    assert listeners.listeners[-1].stopped == 1

    hotkeys.listener.press(_PUSH)
    _drain(dispatcher)
    assert manual.hover_runtime.accepting is True
    listeners.listeners[-1].emit(10, 20)
    _drain(dispatcher)

    hotkeys.listener.release(_PUSH)
    _drain(dispatcher)

    assert manual.hover_runtime.accepting is False
    manual.shutdown()


def test_a_repeated_push_press_is_one_activation() -> None:
    manual, dispatcher, listeners, capture, hotkeys = _push_composition()
    manual.start()
    assert manual.hover_runtime is not None
    _await_hover_ready(manual.hover_runtime, dispatcher)
    assert hotkeys.listener is not None
    started = len(listeners.listeners)

    hotkeys.listener.press(_PUSH)
    hotkeys.listener.press(_PUSH)
    _drain(dispatcher)

    # One press, one observation: auto-repeat must not re-arm anything.
    assert len(listeners.listeners) == started + 1
    manual.shutdown()


def test_pushing_while_capture_is_stopped_does_nothing_and_does_not_latch() -> None:
    """A hold must not allocate a capture session behind the user's back, and
    the press that did nothing must not be inherited by the next Start."""

    manual, dispatcher, listeners, capture, hotkeys = _push_composition()
    manual.prepare()
    assert hotkeys.listener is not None

    hotkeys.listener.press(_PUSH)
    _drain(dispatcher)

    assert manual.started is False
    assert capture.cursors == []

    manual.start()
    assert manual.hover_runtime is not None
    _await_hover_ready(manual.hover_runtime, dispatcher)

    assert manual.hover_runtime.accepting is False
    manual.shutdown()


def test_a_chord_held_across_start_needs_a_fresh_press() -> None:
    manual, dispatcher, listeners, capture, hotkeys = _push_composition()
    manual.start()
    assert manual.hover_runtime is not None
    _await_hover_ready(manual.hover_runtime, dispatcher)
    assert hotkeys.listener is not None
    hotkeys.listener.press(_PUSH)
    _drain(dispatcher)
    assert manual.hover_runtime.accepting is True

    manual.stop()
    manual.start()
    _await_hover_ready(manual.hover_runtime, dispatcher)

    assert manual.hover_runtime.accepting is False
    hotkeys.listener.press(_PUSH)
    _drain(dispatcher)
    assert manual.hover_runtime.accepting is True
    manual.shutdown()


def test_switching_to_always_active_clears_the_held_chord() -> None:
    manual, dispatcher, listeners, capture, hotkeys = _push_composition()
    manual.start()
    assert manual.hover_runtime is not None
    _await_hover_ready(manual.hover_runtime, dispatcher)
    assert hotkeys.listener is not None
    hotkeys.listener.press(_PUSH)
    _drain(dispatcher)

    manual.apply_config(_ALWAYS_ACTIVE)
    _drain(dispatcher)

    # Always active observes for the whole session, and the release of a chord
    # that no longer means anything must not switch it off again.
    assert manual.hover_runtime.accepting is True
    hotkeys.listener.release(_PUSH)
    _drain(dispatcher)
    assert manual.hover_runtime.accepting is True
    manual.shutdown()


def test_the_capture_shortcut_reaches_whoever_owns_the_session() -> None:
    toggles: list[str] = []
    hotkeys = _RealHotkeys()
    listeners = _ListenerFactory()
    dispatcher = _QueueDispatcher()
    worker = _Worker()

    class _RuntimeComposition:
        def create_lookup_controller(
            self,
            on_result: Callable[[LookupResult], None] | None = None,
            *,
            result_dispatcher: ResultDispatcher | None = None,
            thread_name: str | None = None,
        ) -> LookupController:
            del thread_name
            assert on_result is not None
            return LookupController(
                lambda: worker, on_result, result_dispatcher=result_dispatcher
            )

    manual = create_manual_lookup(
        _RuntimeComposition(),
        _Capture(),
        lambda _result: None,
        close_popup=lambda: None,
        current_cursor=lambda: Point(0, 0),
        dispatcher=dispatcher,
        hotkey_factory=hotkeys,
        hover_enabled=True,
        hover_scheduler=cast(Any, _Scheduler()),
        hover_listener_factory=listeners,
        app_config=_PUSH_CONFIG,
        on_toggle_capture=lambda: toggles.append("toggle"),
    )
    manual.prepare()
    assert hotkeys.listener is not None

    hotkeys.listener.press("<ctrl>+<shift>+<f10>")
    _drain(dispatcher)
    hotkeys.listener.release("<ctrl>+<shift>+<f10>")
    _drain(dispatcher)

    # One tap, one toggle: the release is not a second press.
    assert toggles == ["toggle"]
    manual.shutdown()
