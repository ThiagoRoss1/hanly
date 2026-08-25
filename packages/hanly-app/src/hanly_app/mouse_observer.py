"""Global cursor observation with a normalized application-facing seam."""

from __future__ import annotations

from collections.abc import Callable
from threading import RLock
from typing import TYPE_CHECKING, Protocol, TypeAlias

from hanly import Point

if TYPE_CHECKING:
    # Keep the optional OS integration out of module import and type-only code.
    from pynput import mouse


class MouseListener(Protocol):
    """Minimal listener lifecycle hidden behind the mouse observer seam."""

    def start(self) -> None:
        """Start receiving global mouse events."""

    def stop(self) -> None:
        """Stop receiving global mouse events."""


MousePositionHandler: TypeAlias = Callable[[Point], None]
MouseDispatcher: TypeAlias = Callable[[Callable[[], None]], None]
MouseListenerFactory: TypeAlias = Callable[
    [Callable[[int, int], None]], MouseListener
]


def _inline_dispatch(callback: Callable[[], None]) -> None:
    callback()


def _pynput_listener_factory(
    on_move: Callable[[int, int], None],
) -> MouseListener:
    """Construct the concrete listener only when observation starts."""

    try:
        from pynput import mouse as pynput_mouse
    except ImportError as error:
        raise RuntimeError(
            "pynput is required to observe global mouse movement"
        ) from error

    return _PynputListener(pynput_mouse.Listener(on_move=on_move))


class _PynputListener:
    """Contain the external pynput listener behind :class:`MouseListener`."""

    def __init__(self, listener: mouse.Listener) -> None:
        self._listener = listener

    def start(self) -> None:
        self._listener.start()

    def stop(self) -> None:
        self._listener.stop()

    def join(self, timeout: float | None = 1.0) -> None:
        self._listener.join(timeout)


def _stop_listener(listener: MouseListener) -> None:
    """Stop and boundedly join a listener when its backend provides ``join``."""

    listener.stop()

    join = getattr(listener, "join", None)
    if not callable(join):
        return

    try:
        join(timeout=1.0)
    except TypeError:
        # Small test doubles and third-party wrappers may expose join() without
        # the standard thread timeout parameter.
        try:
            join()
        except RuntimeError:
            pass
    except RuntimeError:
        # A pynput callback can stop its own listener; joining that thread is
        # impossible, and stopping has already requested the needed cleanup.
        pass


class MouseObserver:
    """Observe global cursor movement and publish normalized screen points.

    The observer never decides whether a point represents a hover and never
    performs capture, OCR, or lookup.  ``dispatcher`` should enqueue the
    delivery callback and return immediately when the application has a UI or
    orchestration thread to protect from the pynput listener thread.
    """

    def __init__(
        self,
        on_position: MousePositionHandler,
        *,
        dispatcher: MouseDispatcher | None = None,
        listener_factory: MouseListenerFactory | None = None,
    ) -> None:
        if not callable(on_position):
            raise TypeError("on_position must be callable")
        if dispatcher is not None and not callable(dispatcher):
            raise TypeError("dispatcher must be callable")
        if listener_factory is not None and not callable(listener_factory):
            raise TypeError("listener_factory must be callable")

        self._on_position = on_position
        self._dispatcher = dispatcher or _inline_dispatch
        self._listener_factory = listener_factory or _pynput_listener_factory
        self._lock = RLock()
        self._listener: MouseListener | None = None
        self._running = False
        self._generation = 0
        self._pending_point: Point | None = None
        self._delivery_pending = False

    @property
    def running(self) -> bool:
        """Whether this observer currently owns an active listener."""

        with self._lock:
            return self._running

    def start(self) -> None:
        """Start one listener; repeated starts leave the current one intact."""

        listener: MouseListener | None = None
        try:
            with self._lock:
                if self._running:
                    return

                self._generation += 1
                listener = self._listener_factory(self._handle_move)
                if not callable(getattr(listener, "start", None)):
                    raise TypeError("mouse listener must provide start()")
                if not callable(getattr(listener, "stop", None)):
                    raise TypeError("mouse listener must provide stop()")
                self._listener = listener
                self._running = True
                listener.start()
        except Exception:
            with self._lock:
                self._listener = None
                self._running = False
            if listener is not None:
                try:
                    _stop_listener(listener)
                except Exception:
                    pass
            raise

    def stop(self) -> None:
        """Stop observation and suppress deliveries already queued by dispatch."""

        with self._lock:
            listener = self._listener
            self._listener = None
            self._running = False
            self._generation += 1
            self._pending_point = None
            self._delivery_pending = False

        if listener is not None:
            _stop_listener(listener)

    def _handle_move(self, x: int, y: int) -> None:
        point = Point(float(x), float(y))

        with self._lock:
            if not self._running:
                return
            self._pending_point = point
            if self._delivery_pending:
                return
            self._delivery_pending = True
            dispatcher = self._dispatcher
            generation = self._generation

        def deliver() -> None:
            with self._lock:
                if not self._running or generation != self._generation:
                    return
                latest = self._pending_point
                self._pending_point = None
                self._delivery_pending = False
                handler = self._on_position
            if latest is not None:
                handler(latest)

        try:
            dispatcher(deliver)
        except BaseException:
            with self._lock:
                if generation == self._generation:
                    self._pending_point = None
                    self._delivery_pending = False
            raise


__all__ = [
    "MouseDispatcher",
    "MouseListener",
    "MouseListenerFactory",
    "MouseObserver",
    "MousePositionHandler",
]
