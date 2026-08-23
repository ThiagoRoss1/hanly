from __future__ import annotations

import signal
from collections.abc import Callable
from typing import Any

from hanly_app.signal_bridge import QtSignalBridge, SignalHandler


class _Timeout:
    def __init__(self) -> None:
        self.callback: Callable[[], None] | None = None

    def connect(self, callback: Callable[[], None]) -> None:
        self.callback = callback


class _Timer:
    def __init__(self) -> None:
        self.timeout = _Timeout()
        self.started: list[int] = []
        self.stopped = False

    def start(self, milliseconds: int) -> None:
        self.started.append(milliseconds)

    def stop(self) -> None:
        self.stopped = True


class _Signals:
    """A stand-in for :mod:`signal` so tests never touch process signal state."""

    SIGINT = signal.SIGINT

    def __init__(self) -> None:
        self.previous: SignalHandler = signal.SIG_DFL
        self.handler: SignalHandler = self.previous

    def getsignal(self, _number: int, /) -> SignalHandler:
        return self.handler

    def signal(self, _number: int, handler: SignalHandler, /) -> SignalHandler:
        old = self.handler
        self.handler = handler
        return old


class _Application:
    def __init__(self) -> None:
        self.exit_codes: list[int] = []

    def exit(self, return_code: int = 0) -> None:
        self.exit_codes.append(return_code)


def test_sigint_runs_graceful_shutdown_and_exits_qt_with_130() -> None:
    application = _Application()
    signals = _Signals()
    timer = _Timer()
    events: list[str] = []
    bridge = QtSignalBridge(
        application,
        lambda: events.append("shutdown"),
        timer_factory=lambda: timer,
        signal_module=signals,
    )

    bridge.install()
    bridge.install()

    assert timer.started == [100]
    assert timer.timeout.callback is not None
    handler = signals.handler
    assert callable(handler)
    handler(signals.SIGINT, None)
    handler(signals.SIGINT, None)

    assert events == ["shutdown"]
    assert application.exit_codes == [130]
    assert timer.stopped is True
    assert signals.handler is signals.previous
    assert bridge.handled is True


def test_shutdown_failure_is_reported_but_still_exits() -> None:
    application = _Application()
    signals = _Signals()
    timer = _Timer()
    errors: list[BaseException] = []

    def fail() -> None:
        raise RuntimeError("cleanup failed")

    bridge = QtSignalBridge(
        application,
        fail,
        timer_factory=lambda: timer,
        signal_module=signals,
        on_error=errors.append,
    )
    bridge.install()
    handler: Any = signals.handler
    handler(signals.SIGINT, None)

    assert [str(error) for error in errors] == ["cleanup failed"]
    assert application.exit_codes == [130]
