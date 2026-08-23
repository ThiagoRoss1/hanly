"""Deliver terminal interrupts while the Qt event loop owns the main thread.

Qt's event loop runs in C++, so a Python-level ``SIGINT`` handler is only
invoked once the interpreter next executes bytecode.  Without something that
returns to Python periodically, Ctrl+C is deferred for as long as the loop is
idle.  The periodic no-op timer here exists solely to provide that boundary.
"""

from __future__ import annotations

import signal
import threading
from collections.abc import Callable
from types import FrameType
from typing import Protocol, cast


class _TimerSignal(Protocol):
    def connect(self, callback: Callable[[], None]) -> None: ...


class SignalTimer(Protocol):
    @property
    def timeout(self) -> _TimerSignal: ...

    def start(self, milliseconds: int) -> None: ...

    def stop(self) -> None: ...


class QtApplicationExit(Protocol):
    def exit(self, return_code: int = 0) -> None: ...


#: What :func:`signal.signal` accepts and returns, spelled out so the module
#: seam below can be typed without falling back to ``Any``.
SignalHandler = (
    Callable[[int, FrameType | None], object] | int | signal.Handlers | None
)


class SignalModule(Protocol):
    """The three members of :mod:`signal` this bridge uses.

    Declared so tests can substitute the module without mutating real process
    signal state, and so the parameter does not have to widen to ``Any``.
    """

    SIGINT: signal.Signals

    def getsignal(self, signalnum: int, /) -> SignalHandler: ...

    def signal(self, signalnum: int, handler: SignalHandler, /) -> SignalHandler: ...


TimerFactory = Callable[[], SignalTimer]
ShutdownCallback = Callable[[], None]
SignalErrorHandler = Callable[[BaseException], None]


class QtSignalBridge:
    """Install a small Qt pulse so Python can dispatch ``SIGINT`` reliably."""

    def __init__(
        self,
        application: QtApplicationExit,
        shutdown: ShutdownCallback,
        *,
        timer_factory: TimerFactory | None = None,
        signal_module: SignalModule = signal,
        on_error: SignalErrorHandler | None = None,
        interval_ms: int = 100,
    ) -> None:
        if not callable(shutdown):
            raise TypeError("shutdown must be callable")
        if isinstance(interval_ms, bool) or not isinstance(interval_ms, int):
            raise TypeError("interval_ms must be an integer")
        if interval_ms <= 0:
            raise ValueError("interval_ms must be positive")
        self._application = application
        self._shutdown = shutdown
        self._timer_factory = timer_factory or _qt_timer
        self._signal = signal_module
        self._on_error = on_error
        self._interval_ms = interval_ms
        self._timer: SignalTimer | None = None
        self._previous_handler: SignalHandler = None
        self._installed = False
        self._handled = False

    @property
    def installed(self) -> bool:
        return self._installed

    @property
    def handled(self) -> bool:
        return self._handled

    def install(self) -> None:
        """Install the SIGINT handler and a no-op Qt timer on the main thread."""

        if self._installed:
            return
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("Qt SIGINT handling must be installed on the main thread")
        timer = self._timer_factory()
        timer.timeout.connect(_pulse)
        previous = self._signal.getsignal(self._signal.SIGINT)
        self._signal.signal(self._signal.SIGINT, self._handle_sigint)
        try:
            timer.start(self._interval_ms)
        except Exception:
            self._signal.signal(self._signal.SIGINT, previous)
            raise
        self._timer = timer
        self._previous_handler = previous
        self._installed = True

    def close(self) -> None:
        """Stop the pulse and restore the process's previous SIGINT handler."""

        if not self._installed:
            return
        self._installed = False
        timer = self._timer
        self._timer = None
        previous = self._previous_handler
        self._previous_handler = None
        if timer is not None:
            timer.stop()
        if previous is not None:
            self._signal.signal(self._signal.SIGINT, previous)

    def _handle_sigint(self, _signum: int, _frame: FrameType | None) -> None:
        # Both parameters are required by Python's signal-handler contract and
        # are intentionally unused here.
        if self._handled:
            return
        self._handled = True
        # Restore the prior handler first so a second Ctrl+C can still interrupt
        # a dependency that blocks during graceful cleanup.
        self.close()
        try:
            self._shutdown()
        except BaseException as error:
            if self._on_error is not None:
                self._on_error(error)
        finally:
            self._application.exit(130)


def _qt_timer() -> SignalTimer:
    # Imported lazily so this module stays importable without the Qt extra.
    from PyQt6.QtCore import QTimer

    # ``QTimer.timeout`` is a ``pyqtBoundSignal`` whose stubbed ``connect``
    # signature cannot satisfy a structural Protocol, so the match is asserted
    # once here rather than spreading PyQt types through the module.
    return cast(SignalTimer, QTimer())


def _pulse() -> None:
    """Give the interpreter a periodic bytecode boundary inside Qt's loop."""


__all__ = [
    "QtApplicationExit",
    "QtSignalBridge",
    "ShutdownCallback",
    "SignalErrorHandler",
    "SignalHandler",
    "SignalModule",
    "SignalTimer",
    "TimerFactory",
]
