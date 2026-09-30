"""Quitting Hanly while it is asking where to read."""

from __future__ import annotations

import pytest
from hanly_app.acquisition.selector import CaptureSelection, select_capture_area
from hanly_app.config import Theme
from PyQt6.QtCore import QEvent, QObject, QTimer
from PyQt6.QtWidgets import QApplication, QPushButton


def _visible() -> list[str]:
    widgets = QApplication.topLevelWidgets()
    return [type(widget).__name__ for widget in widgets if widget.isVisible()]


def _press(text: str) -> None:
    for widget in QApplication.topLevelWidgets():
        for button in widget.findChildren(QPushButton):
            if button.text() == text and button.isVisible():
                button.click()


@pytest.mark.parametrize(
    ("stage", "window"), [("prompt", "HanlyPrompt"), ("region", "RegionOverlay")]
)
def test_quit_closes_the_open_choice_and_ends_the_loop(
    qt_application: QApplication, stage: str, window: str
) -> None:
    returned: list[CaptureSelection | None] = []
    open_at_quit: list[list[str]] = []
    after_return: list[list[str]] = []
    timed_out: list[bool] = []

    def choose() -> None:
        returned.append(select_capture_area(Theme.DARK))
        after_return.append(_visible())

    def quit_now() -> None:
        open_at_quit.append(_visible())
        qt_application.quit()

    def give_up() -> None:
        timed_out.append(True)
        for widget in QApplication.topLevelWidgets():
            widget.close()
        qt_application.quit()

    action_timer = QTimer()
    action_timer.setSingleShot(True)
    action_timer.timeout.connect(lambda: _press("Select an area"))
    quit_timer = QTimer()
    quit_timer.setSingleShot(True)
    quit_timer.timeout.connect(quit_now)
    watchdog = QTimer()
    watchdog.setSingleShot(True)
    watchdog.timeout.connect(give_up)

    class OnWindowShown(QObject):
        def eventFilter(self, watched: QObject | None, event: QEvent | None) -> bool:
            if event is not None and event.type() is QEvent.Type.Show and watched is not None:
                if type(watched).__name__ == "HanlyPrompt" and stage == "region":
                    action_timer.start(0)
                elif type(watched).__name__ == window:
                    quit_timer.start(0)
            return False

    shown = OnWindowShown()
    quit_on_last_window = qt_application.quitOnLastWindowClosed()
    qt_application.installEventFilter(shown)
    watchdog.start(5000)
    QTimer.singleShot(0, choose)
    try:
        qt_application.exec()
    finally:
        watchdog.stop()
        quit_timer.stop()
        action_timer.stop()
        qt_application.removeEventFilter(shown)

    assert not timed_out, f"{stage} did not close after Quit"
    assert open_at_quit, f"Quit was not delivered while {stage} was open"
    assert window in open_at_quit[0]
    assert returned == [None]
    assert after_return == [[]]
    assert qt_application.quitOnLastWindowClosed() is quit_on_last_window
