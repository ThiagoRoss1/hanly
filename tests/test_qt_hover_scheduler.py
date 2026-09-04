"""Focused tests for the Qt-timer hover debounce."""

from __future__ import annotations

import threading
from collections.abc import Callable

import pytest

pytest.importorskip("PyQt6.QtWidgets")

from hanly_app.qt_hover_scheduler import QtHoverScheduler  # noqa: E402
from PyQt6.QtCore import QCoreApplication, QEventLoop, QTimer  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def application() -> QApplication:
    existing = QCoreApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    return QApplication([])


def _spin(milliseconds: int) -> None:
    """Run the event loop for a fixed span, to show something never happens."""

    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


def _spin_until(ready: Callable[[], bool], *, timeout_ms: int = 5000) -> bool:
    """Run the event loop until ``ready`` holds, or give up at the deadline.

    Waiting a fixed span for a callback that is supposed to arrive makes a busy
    machine look like a broken scheduler, so the deadline is generous and only
    the arrival ends the wait.
    """

    loop = QEventLoop()
    poll = QTimer()
    poll.setInterval(1)

    def check() -> None:
        if ready():
            loop.quit()

    poll.timeout.connect(check)
    poll.start()
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    poll.stop()
    return ready()


def test_scheduled_callback_runs_on_the_qt_thread_without_a_timer_thread(
    application: QApplication,
) -> None:
    scheduler = QtHoverScheduler()
    fired: list[int] = []
    before = threading.active_count()

    scheduler(10, lambda: fired.append(threading.get_ident()))

    assert _spin_until(lambda: bool(fired))
    assert fired == [threading.get_ident()]
    assert threading.active_count() == before


def test_cancelled_delay_never_fires(application: QApplication) -> None:
    scheduler = QtHoverScheduler()
    fired: list[str] = []

    handle = scheduler(10, lambda: fired.append("stale"))
    handle.cancel()
    _spin(80)

    assert fired == []


def test_rescheduling_replaces_the_pending_delay_and_reuses_one_timer(
    application: QApplication,
) -> None:
    """Cursor movement reschedules on every event, so the scheduler must
    replace the pending delay rather than accumulate timers."""

    scheduler = QtHoverScheduler()
    fired: list[str] = []
    before = threading.active_count()

    def record(index: int) -> Callable[[], None]:
        return lambda: fired.append(f"move-{index}")

    for index in range(50):
        scheduler(10, record(index))

    assert _spin_until(lambda: bool(fired))
    assert fired == ["move-49"]
    assert threading.active_count() == before


def test_cancelling_a_superseded_handle_leaves_the_newer_delay_pending(
    application: QApplication,
) -> None:
    scheduler = QtHoverScheduler()
    fired: list[str] = []

    stale = scheduler(10, lambda: fired.append("stale"))
    scheduler(10, lambda: fired.append("current"))
    stale.cancel()

    assert _spin_until(lambda: bool(fired))
    assert fired == ["current"]
