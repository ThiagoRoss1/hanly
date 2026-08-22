from __future__ import annotations

from collections.abc import Callable

from hanly import Point
from hanly_app.mouse_observer import MouseObserver


class _Listener:
    def __init__(self, on_move: Callable[[int, int], None]) -> None:
        self._on_move = on_move
        self.started = 0
        self.stopped = 0

    def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1

    def emit(self, x: int, y: int) -> None:
        self._on_move(x, y)


def _observer(
    on_position: Callable[[Point], None],
    *,
    dispatcher: Callable[[Callable[[], None]], None] | None = None,
) -> tuple[MouseObserver, list[_Listener]]:
    listeners: list[_Listener] = []

    def factory(on_move: Callable[[int, int], None]) -> _Listener:
        listener = _Listener(on_move)
        listeners.append(listener)
        return listener

    return (
        MouseObserver(
            on_position,
            dispatcher=dispatcher,
            listener_factory=factory,
        ),
        listeners,
    )


def test_movement_events_are_published_as_accurate_screen_points() -> None:
    received: list[Point] = []
    observer, listeners = _observer(received.append)

    observer.start()
    listeners[0].emit(-125, 840)

    assert received == [Point(-125, 840)]


def test_movement_handler_runs_only_through_the_injected_dispatcher() -> None:
    received: list[Point] = []
    posted: list[Callable[[], None]] = []
    observer, listeners = _observer(received.append, dispatcher=posted.append)

    observer.start()
    listeners[0].emit(12, 34)

    assert received == []
    assert len(posted) == 1

    posted[0]()

    assert received == [Point(12, 34)]


def test_start_and_stop_are_idempotent() -> None:
    observer, listeners = _observer(lambda _point: None)

    observer.start()
    observer.start()
    observer.stop()
    observer.stop()

    assert len(listeners) == 1
    assert listeners[0].started == 1
    assert listeners[0].stopped == 1
    assert observer.running is False


def test_queued_movement_is_suppressed_after_stop() -> None:
    received: list[Point] = []
    posted: list[Callable[[], None]] = []
    observer, listeners = _observer(received.append, dispatcher=posted.append)

    observer.start()
    listeners[0].emit(20, 30)
    observer.stop()

    posted[0]()

    assert received == []


def test_restart_creates_a_fresh_listener_after_stop() -> None:
    received: list[Point] = []
    observer, listeners = _observer(received.append)

    observer.start()
    observer.stop()
    observer.start()
    listeners[1].emit(50, 60)

    assert received == [Point(50, 60)]
    assert [listener.started for listener in listeners] == [1, 1]


def test_old_queued_movement_stays_suppressed_after_restart() -> None:
    received: list[Point] = []
    posted: list[Callable[[], None]] = []
    observer, listeners = _observer(received.append, dispatcher=posted.append)

    observer.start()
    listeners[0].emit(20, 30)
    observer.stop()
    observer.start()

    posted[0]()

    assert received == []
