"""UI-independent cursor stability and hover-trigger state."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from math import isfinite
from threading import RLock, Timer
from typing import Protocol, TypeAlias

from hanly import Point


class Cancellable(Protocol):
    """Handle returned by a stability scheduler."""

    def cancel(self) -> None:
        """Prevent the scheduled callback when it has not started."""


StabilityCallback: TypeAlias = Callable[[], None]


class HoverScheduler(Protocol):
    """Schedule one callback after a delay expressed in milliseconds."""

    def __call__(self, delay_ms: float, callback: StabilityCallback) -> Cancellable:
        """Schedule ``callback`` and return its cancellable handle."""


HoverDispatcher: TypeAlias = Callable[[StabilityCallback], None]
StablePointHandler: TypeAlias = Callable[["HoverRequest"], None]


@dataclass(frozen=True)
class HoverRequest:
    """Immutable identity and point for one latest-wins hover attempt."""

    request_id: int
    point: Point

    def __post_init__(self) -> None:
        if isinstance(self.request_id, bool) or not isinstance(self.request_id, int):
            raise TypeError("request_id must be an integer")
        if self.request_id <= 0:
            raise ValueError("request_id must be positive")
        if not isinstance(self.point, Point):
            raise TypeError("point must be a Point")


def _threading_scheduler(delay_ms: float, callback: StabilityCallback) -> Cancellable:
    """Provide a small non-UI fallback scheduler for direct use."""

    timer = Timer(delay_ms / 1000.0, callback)
    timer.daemon = True
    timer.start()
    return timer


def _inline_dispatch(callback: StabilityCallback) -> None:
    callback()


class HoverController:
    """Decide when a stable cursor point may trigger automatic lookup.

    Each movement replaces the previous attempt and invalidates its request.
    The controller never observes the OS, captures pixels, or submits lookup
    work; its handler receives only an immutable :class:`HoverRequest`.
    """

    def __init__(
        self,
        on_stable: StablePointHandler,
        *,
        delay_ms: float = 150,
        scheduler: HoverScheduler | None = None,
        dispatcher: HoverDispatcher | None = None,
    ) -> None:
        if not callable(on_stable):
            raise TypeError("on_stable must be callable")
        if isinstance(delay_ms, bool) or not isinstance(delay_ms, (int, float)):
            raise TypeError("delay_ms must be a number")
        if not isfinite(delay_ms) or delay_ms <= 0:
            raise ValueError("delay_ms must be positive")
        if scheduler is not None and not callable(scheduler):
            raise TypeError("scheduler must be callable")
        if dispatcher is not None and not callable(dispatcher):
            raise TypeError("dispatcher must be callable")

        self._on_stable = on_stable
        self._delay_ms = float(delay_ms)
        self._scheduler = scheduler or _threading_scheduler
        self._dispatcher = dispatcher or _inline_dispatch
        self._lock = RLock()
        self._running = True
        self._closed = False
        self._generation = 0
        self._next_request_id = 1
        self._current_request: HoverRequest | None = None
        self._timer: Cancellable | None = None
        self._last_timer_fired_generation: int | None = None

    @property
    def delay_ms(self) -> float:
        """Configured experimental stability delay in milliseconds."""

        return self._delay_ms

    @property
    def running(self) -> bool:
        """Whether movement events are currently accepted."""

        with self._lock:
            return self._running and not self._closed

    @property
    def closed(self) -> bool:
        """Whether shutdown has permanently closed the controller."""

        with self._lock:
            return self._closed

    @property
    def pending(self) -> bool:
        """Whether one stability timer is currently pending."""

        with self._lock:
            return self._timer is not None

    @property
    def current_request(self) -> HoverRequest | None:
        """Return the latest request, or ``None`` after invalidation."""

        with self._lock:
            return self._current_request

    @property
    def current_request_id(self) -> int | None:
        """Return the latest positive request ID, if one is current."""

        request = self.current_request
        return request.request_id if request is not None else None

    def start(self) -> None:
        """Resume accepting movement events; repeated starts are harmless."""

        with self._lock:
            if self._closed:
                raise RuntimeError("hover controller has been shut down")
            self._running = True

    def pause(self) -> None:
        """Pause movement handling and invalidate timer/dispatch callbacks."""

        with self._lock:
            if self._closed:
                return
            self._running = False
            timer = self._invalidate_locked()
        self._cancel(timer)

    def resume(self) -> None:
        """Resume after :meth:`pause` without restoring an old attempt."""

        self.start()

    def set_delay_ms(self, delay_ms: float) -> None:
        """Apply a new stability delay, rescheduling a pending attempt.

        The current point remains the same, but the old timer and generation
        are invalidated so a callback already racing with this update cannot
        deliver the attempt under the previous configuration.
        """

        if isinstance(delay_ms, bool) or not isinstance(delay_ms, (int, float)):
            raise TypeError("delay_ms must be a number")
        if not isfinite(delay_ms) or delay_ms <= 0:
            raise ValueError("delay_ms must be positive")

        with self._lock:
            if self._closed:
                return
            self._delay_ms = float(delay_ms)
            request = self._current_request if self._running else None
            old_timer = self._timer
            self._timer = None
            self._generation += 1
            generation = self._generation
            self._last_timer_fired_generation = None

        self._cancel(old_timer)
        if request is None:
            return

        try:
            timer = self._scheduler(
                self._delay_ms,
                lambda: self._timer_fired(request, generation),
            )
            if not callable(getattr(timer, "cancel", None)):
                raise TypeError("scheduler must return a cancellable handle")
        except Exception:
            with self._lock:
                if self._generation == generation and self._current_request is request:
                    self._current_request = None
                    self._generation += 1
            raise

        with self._lock:
            if (
                self._closed
                or not self._running
                or self._generation != generation
                or self._current_request is not request
                or self._last_timer_fired_generation == generation
            ):
                cancel_timer = timer
            else:
                self._timer = timer
                cancel_timer = None
        self._cancel(cancel_timer)

    def invalidate(self) -> None:
        """Invalidate the current attempt while continuing to observe points."""

        with self._lock:
            if self._closed:
                return
            timer = self._invalidate_locked()
        self._cancel(timer)

    def shutdown(self) -> None:
        """Close the controller and suppress all queued or future callbacks."""

        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._running = False
            timer = self._invalidate_locked()
        self._cancel(timer)

    def on_position(self, point: Point) -> None:
        """Replace the pending attempt for a newly observed screen point."""

        if not isinstance(point, Point):
            raise TypeError("point must be a Point")

        with self._lock:
            if self._closed:
                return
            if not self._running:
                return

            old_timer = self._timer
            self._timer = None
            self._generation += 1
            generation = self._generation
            self._last_timer_fired_generation = None
            request = HoverRequest(self._next_request_id, point)
            self._next_request_id += 1
            self._current_request = request

        self._cancel(old_timer)

        try:
            timer = self._scheduler(
                self._delay_ms,
                lambda: self._timer_fired(request, generation),
            )
            if not callable(getattr(timer, "cancel", None)):
                raise TypeError("scheduler must return a cancellable handle")
        except Exception:
            with self._lock:
                if self._generation == generation and self._current_request is request:
                    self._current_request = None
                    self._generation += 1
            raise

        with self._lock:
            if (
                self._closed
                or not self._running
                or self._generation != generation
                or self._current_request is not request
                or self._last_timer_fired_generation == generation
            ):
                cancel_timer = timer
            else:
                self._timer = timer
                cancel_timer = None
        self._cancel(cancel_timer)

    def is_current(self, request: HoverRequest | int) -> bool:
        """Return whether a request is still the latest non-invalidated one."""

        request_id = request.request_id if isinstance(request, HoverRequest) else request
        if isinstance(request_id, bool) or not isinstance(request_id, int):
            return False
        with self._lock:
            current = self._current_request
            return current is not None and current.request_id == request_id

    def _timer_fired(self, request: HoverRequest, generation: int) -> None:
        with self._lock:
            if (
                self._closed
                or not self._running
                or self._generation != generation
                or self._current_request is not request
            ):
                return
            self._last_timer_fired_generation = generation
            self._timer = None
            dispatcher = self._dispatcher

        dispatcher(
            lambda: self._deliver_if_current(request, generation),
        )

    def _deliver_if_current(self, request: HoverRequest, generation: int) -> None:
        with self._lock:
            if (
                self._closed
                or not self._running
                or self._generation != generation
                or self._current_request is not request
            ):
                return
            handler = self._on_stable
        handler(request)

    def _invalidate_locked(self) -> Cancellable | None:
        timer = self._timer
        self._timer = None
        self._generation += 1
        self._last_timer_fired_generation = None
        self._current_request = None
        return timer

    @staticmethod
    def _cancel(timer: Cancellable | None) -> None:
        if timer is not None:
            timer.cancel()


__all__ = [
    "Cancellable",
    "HoverController",
    "HoverDispatcher",
    "HoverRequest",
    "HoverScheduler",
    "StablePointHandler",
]
