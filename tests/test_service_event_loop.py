"""Portable timer and popup-crossing behavior on the service owner loop."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from time import monotonic, sleep

import pytest
from hanly import LookupResult, LookupStatus, PixelFormat, Point, ROIImage
from hanly_app.acquisition.capture import CaptureResult, ScreenRect
from hanly_app.hover.controller import HoverController, HoverRequest
from hanly_app.hover.lookup import HoverLookupRuntime
from hanly_app.hover.target import POPUP_TRANSFER_MS, RetainedTarget
from hanly_app.lookup.controller import LookupController, LookupRequest
from hanly_app.service.event_loop import SerializedEventLoop


class _OwnerLoop:
    def __init__(self) -> None:
        self.loop: SerializedEventLoop[object] = SerializedEventLoop()
        self.ready = threading.Event()
        self.ident = 0

        def run() -> None:
            self.ident = threading.get_ident()
            self.ready.set()
            self.loop.run(lambda _request: None)

        self.thread = threading.Thread(target=run, name="test-service-owner")
        self.thread.start()
        assert self.ready.wait(timeout=2)

    def call(self, callback: Callable[[], object]) -> object:
        return self.loop.call_sync(callback, timeout=2)

    def close(self) -> None:
        self.loop.stop()
        self.thread.join(timeout=2)
        assert not self.thread.is_alive()


@pytest.fixture
def owner_loop() -> Iterator[_OwnerLoop]:
    owner = _OwnerLoop()
    try:
        yield owner
    finally:
        owner.close()


def test_timer_callback_runs_on_the_serialized_owner_thread(
    owner_loop: _OwnerLoop,
) -> None:
    fired = threading.Event()
    callback_threads: list[int] = []

    def callback() -> None:
        callback_threads.append(threading.get_ident())
        fired.set()

    owner_loop.loop.call_later(10, callback)

    assert fired.wait(timeout=2)
    assert callback_threads == [owner_loop.ident]


def test_hover_debounce_cancels_superseded_and_paused_callbacks(
    owner_loop: _OwnerLoop,
) -> None:
    stable: list[Point] = []
    fired = threading.Event()

    def on_stable(request: HoverRequest) -> None:
        stable.append(request.point)
        fired.set()

    controller = HoverController(
        on_stable,
        delay_ms=40,
        scheduler=owner_loop.loop.call_later,
        dispatcher=owner_loop.loop.post,
    )
    owner_loop.call(controller.start)

    def move(index: int) -> None:
        controller.on_position(Point(index, index))

    for index in range(50):
        def enqueue_move(index: int = index) -> None:
            move(index)

        owner_loop.loop.post(enqueue_move)
    owner_loop.call(lambda: None)

    assert fired.wait(timeout=2)
    assert stable == [Point(49, 49)]

    owner_loop.call(lambda: controller.on_position(Point(500, 500)))
    owner_loop.call(controller.pause)
    quiet_period = threading.Event()
    owner_loop.loop.call_later(100, quiet_period.set)

    assert quiet_period.wait(timeout=2)
    assert stable == [Point(49, 49)]
    owner_loop.call(controller.shutdown)


def test_cancelling_one_event_loop_timer_leaves_the_newer_timer_pending(
    owner_loop: _OwnerLoop,
) -> None:
    fired: list[str] = []
    completed = threading.Event()

    stale = owner_loop.loop.call_later(60, lambda: fired.append("stale"))

    def finish() -> None:
        fired.append("current")
        completed.set()

    current = owner_loop.loop.call_later(100, finish)
    stale.cancel()

    assert completed.wait(timeout=2)
    assert fired == ["current"]
    assert current.cancelled is False


class _Listener:
    def __init__(self, on_move: Callable[[int, int], None]) -> None:
        self._on_move = on_move

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def join(self, timeout: float | None = None) -> None:
        del timeout

    def move(self, x: int, y: int) -> None:
        self._on_move(x, y)


class _ListenerFactory:
    def __init__(self) -> None:
        self.listeners: list[_Listener] = []

    def __call__(self, on_move: Callable[[int, int], None]) -> _Listener:
        listener = _Listener(on_move)
        self.listeners.append(listener)
        return listener


class _Capture:
    def __init__(self) -> None:
        self.cursors: list[Point] = []
        self._image = ROIImage(1, 1, PixelFormat.RGB_888, b"\x00\x00\x00")

    def capture_at_cursor(self, cursor: Point) -> CaptureResult:
        self.cursors.append(cursor)
        return CaptureResult(self._image, ScreenRect(0, 0, 1, 1), Point(0, 0))


def _start_hover_runtime(
    owner_loop: _OwnerLoop,
    *,
    sticky: bool,
    on_invalidate: Callable[[], None] | None = None,
) -> tuple[
    HoverLookupRuntime,
    LookupController,
    _ListenerFactory,
    _Capture,
    threading.Event,
]:
    def worker(_request: LookupRequest) -> LookupResult:
        return LookupResult(status=LookupStatus.NOT_FOUND)

    controller = LookupController(lambda: worker, result_dispatcher=owner_loop.loop.post)
    listeners = _ListenerFactory()
    capture = _Capture()
    invalidated = threading.Event()

    def notify_invalidated() -> None:
        invalidated.set()
        if on_invalidate is not None:
            on_invalidate()

    runtime = HoverLookupRuntime(
        controller,
        capture,
        delay_ms=100,
        scheduler=owner_loop.loop.call_later,
        exit_scheduler=owner_loop.loop.call_later,
        dispatcher=owner_loop.loop.post,
        listener_factory=listeners,
        on_invalidate=notify_invalidated,
        transfer_ms=POPUP_TRANSFER_MS,
        sticky=sticky,
    )
    owner_loop.call(runtime.start)
    assert controller.wait_until_ready(timeout=3)

    deadline = monotonic() + 3
    while not owner_loop.call(lambda: runtime.hover_controller.running):
        assert monotonic() < deadline, "hover did not return to the service owner loop"
        sleep(0.005)

    return runtime, controller, listeners, capture, invalidated


def _stop_hover_runtime(
    owner_loop: _OwnerLoop,
    runtime: HoverLookupRuntime,
    controller: LookupController,
) -> None:
    owner_loop.call(runtime.shutdown)
    assert controller.join(timeout=3)


def test_popup_crossing_survives_a_concurrent_dwell_until_its_grace_expires(
    owner_loop: _OwnerLoop,
) -> None:
    invalidation_threads: list[int] = []

    def invalidate() -> None:
        invalidation_threads.append(threading.get_ident())

    runtime, controller, listeners, capture, invalidated = _start_hover_runtime(
        owner_loop, sticky=True, on_invalidate=invalidate
    )

    cleared_dwell = threading.Event()
    dwell_threads: list[int] = []

    def stable(_request: HoverRequest) -> None:
        dwell_threads.append(threading.get_ident())
        cleared_dwell.set()

    dwell = HoverController(
        stable,
        delay_ms=20,
        scheduler=owner_loop.loop.call_later,
        dispatcher=owner_loop.loop.post,
    )
    try:
        owner_loop.call(
            lambda: runtime.retain(
                RetainedTarget(
                    1,
                    ScreenRect(100, 100, 40, 20),
                    ScreenRect(300, 100, 320, 180),
                )
            )
        )
        listeners.listeners[0].move(220, 110)
        owner_loop.call(lambda: None)
        assert owner_loop.call(lambda: runtime.retained_target is not None)
        assert capture.cursors == []

        owner_loop.call(dwell.start)
        owner_loop.call(lambda: dwell.on_position(Point(600, 500)))
        assert cleared_dwell.wait(timeout=1)
        assert dwell_threads == [owner_loop.ident]
        assert owner_loop.call(lambda: runtime.retained_target is not None)

        assert invalidated.wait(timeout=2)
        assert invalidation_threads == [owner_loop.ident]
        assert owner_loop.call(lambda: runtime.retained_target is None)
        assert capture.cursors == []
    finally:
        owner_loop.call(dwell.shutdown)
        _stop_hover_runtime(owner_loop, runtime, controller)


@pytest.mark.parametrize("sticky", [False, True])
def test_leaving_a_retained_word_obeys_the_selected_dismissal_policy(
    owner_loop: _OwnerLoop,
    sticky: bool,
) -> None:
    runtime, controller, listeners, capture, invalidated = _start_hover_runtime(
        owner_loop, sticky=sticky
    )
    quiet_period = threading.Event()
    try:
        owner_loop.call(
            lambda: runtime.retain(
                RetainedTarget(
                    1,
                    ScreenRect(100, 100, 40, 20),
                    ScreenRect(300, 100, 320, 180),
                )
            )
        )
        listeners.listeners[0].move(120, 400)
        owner_loop.call(lambda: None)

        assert owner_loop.call(lambda: runtime.retained_target is None)
        assert capture.cursors == []
        if sticky:
            owner_loop.loop.call_later(150, quiet_period.set)
            assert quiet_period.wait(timeout=2)
            assert not invalidated.is_set()

            owner_loop.call(runtime.dismiss)
            assert invalidated.wait(timeout=1)
        else:
            assert invalidated.wait(timeout=1)
    finally:
        _stop_hover_runtime(owner_loop, runtime, controller)
