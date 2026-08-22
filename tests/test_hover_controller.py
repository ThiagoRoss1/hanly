from __future__ import annotations

from collections.abc import Callable

import pytest
from hanly import Point
from hanly_app.hover_controller import HoverController, HoverRequest


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


def _controller(
    stable: list[HoverRequest],
    *,
    scheduler: _Scheduler | None = None,
    posted: list[Callable[[], None]] | None = None,
    delay_ms: float = 150,
) -> tuple[HoverController, _Scheduler, list[Callable[[], None]]]:
    timer_scheduler = scheduler or _Scheduler()
    dispatch_queue = posted if posted is not None else []

    def dispatch(callback: Callable[[], None]) -> None:
        dispatch_queue.append(callback)

    return (
        HoverController(
            stable.append,
            scheduler=timer_scheduler,
            dispatcher=dispatch,
            delay_ms=delay_ms,
        ),
        timer_scheduler,
        dispatch_queue,
    )


def test_default_delay_is_150_milliseconds_and_stable_point_is_dispatched() -> None:
    stable: list[HoverRequest] = []
    controller, scheduler, posted = _controller(stable)

    controller.on_position(Point(10, 20))

    assert scheduler.calls[0][0] == 150
    scheduler.fire()
    assert stable == []
    assert len(posted) == 1

    posted.pop()()

    assert stable[0].point == Point(10, 20)
    assert stable[0].request_id == 1


def test_configured_hover_delay_is_forwarded_to_scheduler() -> None:
    stable: list[HoverRequest] = []
    scheduler = _Scheduler()
    posted: list[Callable[[], None]] = []

    controller = HoverController(
        stable.append,
        scheduler=scheduler,
        dispatcher=posted.append,
        delay_ms=220,
    )

    controller.on_position(Point(10, 20))

    assert controller.delay_ms == 220
    assert scheduler.calls[0][0] == 220


def test_each_movement_cancels_prior_timer_and_supersedes_current_request() -> None:
    stable: list[HoverRequest] = []
    controller, scheduler, posted = _controller(stable)

    controller.on_position(Point(1, 2))
    first = controller.current_request
    controller.on_position(Point(3, 4))
    second = controller.current_request

    assert first is not None and second is not None
    assert first.request_id == 1
    assert second.request_id == 2
    assert controller.is_current(first) is False
    assert controller.is_current(second) is True
    assert scheduler.calls[0][1].cancelled is True

    scheduler.fire(0)
    scheduler.fire(1)
    assert len(posted) == 1
    posted.pop()()
    assert stable == [second]


def test_stale_queued_timer_and_dispatch_callbacks_are_suppressed() -> None:
    stable: list[HoverRequest] = []
    controller, scheduler, posted = _controller(stable)

    controller.on_position(Point(1, 1))
    scheduler.fire()
    controller.on_position(Point(2, 2))
    posted.pop()()

    assert stable == []
    scheduler.fire()
    posted.pop()()
    assert [request.point for request in stable] == [Point(2, 2)]


def test_at_most_one_timer_remains_pending_after_many_movements() -> None:
    stable: list[HoverRequest] = []
    controller, scheduler, _posted = _controller(stable)

    for coordinate in range(20):
        controller.on_position(Point(coordinate, coordinate))

    assert controller.pending is True
    assert sum(not handle.cancelled for _delay, handle in scheduler.calls) == 1


def test_delay_must_be_positive() -> None:
    with pytest.raises(ValueError, match="delay"):
        HoverController(lambda _request: None, delay_ms=0)
    with pytest.raises(ValueError, match="delay"):
        HoverController(lambda _request: None, delay_ms=-1)


def test_invalidate_suppresses_timer_and_dispatch_and_clears_current() -> None:
    stable: list[HoverRequest] = []
    controller, scheduler, posted = _controller(stable)

    controller.on_position(Point(1, 2))
    request = controller.current_request
    scheduler.fire()
    controller.invalidate()

    assert request is not None
    assert controller.current_request is None
    assert controller.is_current(request) is False
    posted.pop()()
    assert stable == []


def test_pause_suppresses_queued_callbacks_until_resume() -> None:
    stable: list[HoverRequest] = []
    controller, scheduler, posted = _controller(stable)

    controller.on_position(Point(1, 2))
    scheduler.fire()
    controller.pause()
    posted.pop()()
    assert stable == []

    controller.resume()
    controller.on_position(Point(3, 4))
    scheduler.fire()
    posted.pop()()
    assert [request.point for request in stable] == [Point(3, 4)]


def test_shutdown_is_idempotent_and_suppresses_all_future_work() -> None:
    stable: list[HoverRequest] = []
    controller, scheduler, posted = _controller(stable)

    controller.on_position(Point(1, 2))
    scheduler.fire()
    controller.shutdown()
    controller.shutdown()
    posted.pop()()

    assert stable == []
    assert controller.closed is True
    assert controller.current_request is None
    controller.on_position(Point(3, 4))
    assert len(scheduler.calls) == 1


def test_request_is_frozen_and_request_ids_are_positive() -> None:
    request = HoverRequest(7, Point(1, 2))

    with pytest.raises(AttributeError):
        request.request_id = 8  # type: ignore[misc]

    with pytest.raises(ValueError, match="positive"):
        HoverRequest(0, Point(1, 2))
