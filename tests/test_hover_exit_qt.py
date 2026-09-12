"""The exit path over the production Qt timers, not over a test double.

``tests/test_hover_target.py`` drives the same runtime with schedulers it fires
by hand, which proves the geometry. This one proves the part a fake scheduler
cannot: with the real ``QtHoverScheduler``, leaving a retained word dismisses
the answer, and the dwell armed for the next word does not take the crossing's
timer away from it.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from hanly import LookupResult, LookupStatus, PixelFormat, Point, ROIImage

pytest.importorskip("PyQt6.QtWidgets")

from hanly_app.capture import CaptureResult, ScreenRect  # noqa: E402
from hanly_app.hover_lookup import HoverLookupRuntime  # noqa: E402
from hanly_app.hover_target import POPUP_TRANSFER_MS, RetainedTarget  # noqa: E402
from hanly_app.lookup_controller import LookupController, LookupRequest  # noqa: E402
from hanly_app.qt_hover_scheduler import QtHoverScheduler  # noqa: E402
from PyQt6.QtCore import QCoreApplication, QEventLoop, QTimer  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

_IMAGE = ROIImage(2, 1, PixelFormat.RGB_888, b"\x00\x00\x00\xff\xff\xff")
_WORD = ScreenRect(100, 100, 40, 20)
_POPUP = ScreenRect(300, 100, 320, 180)
_DWELL_MS = 80


@pytest.fixture(scope="module")
def application() -> QApplication:
    existing = QCoreApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    return QApplication([])


class _Listener:
    def __init__(self, on_move: Callable[[int, int], None]) -> None:
        self.on_move = on_move

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def join(self, timeout: float | None = None) -> None:
        del timeout


class _Listeners:
    def __init__(self) -> None:
        self.listeners: list[_Listener] = []

    def __call__(self, on_move: Callable[[int, int], None]) -> _Listener:
        listener = _Listener(on_move)
        self.listeners.append(listener)
        return listener


class _Capture:
    def __init__(self) -> None:
        self.cursors: list[Point] = []

    def capture_at_cursor(self, cursor: Point) -> CaptureResult:
        self.cursors.append(cursor)
        return CaptureResult(_IMAGE, ScreenRect(0, 0, 2, 1), Point(1.0, 0.5))


def _worker(request: LookupRequest) -> LookupResult:
    del request
    return LookupResult(status=LookupStatus.NOT_FOUND)


def _spin(milliseconds: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


def _runtime(cleared: list[int]) -> tuple[HoverLookupRuntime, _Listeners, _Capture]:
    listeners = _Listeners()
    capture = _Capture()
    runtime = HoverLookupRuntime(
        LookupController(lambda: _worker, lambda _result: None),
        capture,
        delay_ms=_DWELL_MS,
        scheduler=QtHoverScheduler(),
        exit_scheduler=QtHoverScheduler(),
        listener_factory=listeners,
        on_invalidate=lambda: cleared.append(1),
    )
    runtime.start()
    assert runtime.controller.wait_until_ready(timeout=5.0)
    _spin(20)
    return runtime, listeners, capture


def test_leaving_a_retained_word_dismisses_it_on_the_real_qt_scheduler(
    application: QApplication,
) -> None:
    """The measured failure: no dismissal at all, because the dwell scheduled
    on the way out replaced the exit's callback on the one shared timer."""

    del application
    cleared: list[int] = []
    runtime, listeners, _capture = _runtime(cleared)
    try:
        runtime.retain(RetainedTarget(1, _WORD, _POPUP))
        listeners.listeners[0].on_move(120, 400)
        _spin(20)

        assert cleared == [1]
        assert runtime.retained_target is None

        # The dwell armed by that same movement still belongs to the next word.
        _spin(_DWELL_MS + 60)
        assert cleared == [1]
    finally:
        runtime.shutdown()


def test_a_crossing_to_the_popup_outlives_the_dwell_it_shares_the_moment_with(
    application: QApplication,
) -> None:
    del application
    cleared: list[int] = []
    runtime, listeners, capture = _runtime(cleared)
    try:
        runtime.retain(RetainedTarget(1, _WORD, _POPUP))
        listeners.listeners[0].on_move(220, 110)
        _spin(20)

        assert cleared == []
        assert runtime.retained_target is not None
        # Nothing is captured against the empty gap between the two.
        assert capture.cursors == []

        _spin(int(POPUP_TRANSFER_MS) + 80)
        assert cleared == [1]
        assert runtime.retained_target is None
    finally:
        runtime.shutdown()
