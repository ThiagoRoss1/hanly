"""Quitting Hanly while it is asking where to read."""

from __future__ import annotations

import time

import pytest
from hanly_app.capture_selector import CaptureSelection, select_capture_area
from hanly_app.config import Theme
from PyQt6.QtCore import QTimer
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

    def choose() -> None:
        returned.append(select_capture_area(Theme.DARK))
        after_return.append(_visible())

    def quit_now() -> None:
        open_at_quit.append(_visible())
        qt_application.quit()

    def give_up() -> None:
        # Only reached if quit left the choice open; close it so the run ends.
        for widget in QApplication.topLevelWidgets():
            widget.close()
        qt_application.quit()

    quit_on_last_window = qt_application.quitOnLastWindowClosed()
    QTimer.singleShot(0, choose)
    if stage == "region":
        QTimer.singleShot(250, lambda: _press("Select an area"))
    QTimer.singleShot(700, quit_now)
    QTimer.singleShot(5000, give_up)
    started = time.monotonic()
    qt_application.exec()
    elapsed = time.monotonic() - started

    assert window in open_at_quit[0]
    assert returned == [None]
    assert after_return == [[]]
    assert elapsed < 3.0
    assert qt_application.quitOnLastWindowClosed() is quit_on_last_window
