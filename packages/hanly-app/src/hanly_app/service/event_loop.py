"""Single-owner dispatcher and timer queue for the supervised service."""

from __future__ import annotations

import heapq
import threading
from collections import deque
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass, field
from time import monotonic
from typing import Generic, TypeVar

T = TypeVar("T")
Callback = Callable[[], None]

MAX_QUEUED_CALLBACKS = 64


class EventLoopOverloaded(RuntimeError):
    """Raised when a callback producer exceeds the bounded owner queue."""


@dataclass(order=True, slots=True)
class _Scheduled:
    deadline: float
    order: int
    handle: TimerHandle = field(compare=False)
    callback: Callback = field(compare=False)


class TimerHandle:
    """Cancellation token for a callback scheduled on the owner loop."""

    def __init__(self) -> None:
        self._cancelled = False
        self._lock = threading.Lock()

    @property
    def cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True


class SerializedEventLoop(Generic[T]):
    """Dispatch requests, callbacks, and timers on the calling thread.

    Producers may be OS listeners, lookup workers, or the stdin reader. They
    only enqueue bounded work; all service state and protocol output remain
    owned by the thread running :meth:`run`.
    """

    def __init__(self, *, max_requests: int = 32) -> None:
        if max_requests <= 0:
            raise ValueError("max_requests must be positive")
        self._max_requests = max_requests
        self._condition = threading.Condition()
        self._requests: deque[T] = deque()
        self._callbacks: deque[Callback] = deque()
        self._timers: list[_Scheduled] = []
        self._next_timer_order = 0
        self._input_closed = False
        self._stopped = False
        self._fatal = False
        self._owner_ident: int | None = None

    def post(self, callback: Callback) -> None:
        """Queue one callback without running it on the producer thread."""

        if not callable(callback):
            raise TypeError("callback must be callable")
        with self._condition:
            if self._stopped or self._fatal:
                return
            if len(self._callbacks) >= MAX_QUEUED_CALLBACKS:
                raise EventLoopOverloaded("service callback queue is full")
            self._callbacks.append(callback)
            self._condition.notify()

    @property
    def in_owner_thread(self) -> bool:
        """Whether the calling thread currently owns service state."""

        return threading.get_ident() == self._owner_ident

    def enqueue_request(self, request: T) -> bool:
        """Admit one decoded protocol message, bounded to the wire limit."""

        with self._condition:
            if self._stopped or self._fatal or len(self._requests) >= self._max_requests:
                return False
            self._requests.append(request)
            self._condition.notify()
            return True

    def call_later(self, delay_ms: float, callback: Callback) -> TimerHandle:
        """Schedule a callback on the owner thread after ``delay_ms``."""

        if not callable(callback):
            raise TypeError("callback must be callable")
        if delay_ms < 0:
            raise ValueError("delay_ms must not be negative")
        handle = TimerHandle()
        with self._condition:
            if self._stopped or self._fatal:
                handle.cancel()
                return handle
            self._next_timer_order += 1
            heapq.heappush(
                self._timers,
                _Scheduled(
                    monotonic() + float(delay_ms) / 1000,
                    self._next_timer_order,
                    handle,
                    callback,
                ),
            )
            # A newly inserted timer may precede the current queue head.
            self._condition.notify()
        return handle

    def call_sync(self, callback: Callable[[], T], *, timeout: float = 10.0) -> T:
        """Run on the owner thread and return its value to a worker caller."""

        if not callable(callback):
            raise TypeError("callback must be callable")
        if threading.get_ident() == self._owner_ident:
            return callback()
        result: Future[T] = Future()

        def run_callback() -> None:
            if result.set_running_or_notify_cancel():
                try:
                    result.set_result(callback())
                except BaseException as error:
                    result.set_exception(error)

        self.post(run_callback)
        return result.result(timeout=timeout)

    def close_input(self) -> None:
        """Mark clean EOF; already-admitted work is still dispatched."""

        with self._condition:
            self._input_closed = True
            self._condition.notify_all()

    def fail_input(self) -> None:
        """Stop after a malformed or over-capacity input frame."""

        with self._condition:
            self._fatal = True
            self._condition.notify_all()

    def stop(self) -> None:
        """Stop after the current owner callback or request completes."""

        with self._condition:
            self._stopped = True
            self._timers.clear()
            self._callbacks.clear()
            self._requests.clear()
            self._condition.notify_all()

    def run(self, handle_request: Callable[[T], None]) -> bool:
        """Run until EOF, explicit shutdown, or fatal framing input.

        The return value is false only for a fatal input condition.
        """

        if not callable(handle_request):
            raise TypeError("handle_request must be callable")
        self._owner_ident = threading.get_ident()
        while True:
            item: tuple[str, object] | None
            with self._condition:
                item = self._next_item_locked()
                while item is None:
                    if self._fatal or self._stopped:
                        return not self._fatal
                    if self._input_closed and not self._requests and not self._callbacks:
                        return True
                    timeout = self._next_timeout_locked()
                    self._condition.wait(timeout)
                    item = self._next_item_locked()

            kind, value = item
            if kind == "request":
                handle_request(value)  # type: ignore[arg-type]
            elif kind == "callback":
                try:
                    value()  # type: ignore[operator]
                except Exception:
                    # The callback owner logs meaningful errors at its source.
                    # An uncaught observer must not kill protocol dispatch.
                    continue
            else:
                try:
                    value()  # type: ignore[operator]
                except Exception:
                    continue

            with self._condition:
                if self._fatal or self._stopped:
                    return not self._fatal

    def _next_item_locked(self) -> tuple[str, object] | None:
        if self._fatal or self._stopped:
            return None
        if self._callbacks:
            return ("callback", self._callbacks.popleft())
        if self._requests:
            return ("request", self._requests.popleft())

        now = monotonic()
        while self._timers and self._timers[0].handle.cancelled:
            heapq.heappop(self._timers)
        if self._timers and self._timers[0].deadline <= now:
            scheduled = heapq.heappop(self._timers)
            if scheduled.handle.cancelled:
                return None
            return ("timer", scheduled.callback)
        return None

    def _next_timeout_locked(self) -> float | None:
        while self._timers and self._timers[0].handle.cancelled:
            heapq.heappop(self._timers)
        if not self._timers:
            return None
        return max(0.0, self._timers[0].deadline - monotonic())


__all__ = ["EventLoopOverloaded", "SerializedEventLoop", "TimerHandle"]
