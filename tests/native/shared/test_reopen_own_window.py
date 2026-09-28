"""An activation caused by the shell's own modal window is not a Dock click."""

from __future__ import annotations

from hanly_app.app_reopen_darwin import _pointer_on_own_window
from hanly_app.config import Theme
from hanly_app.hanly_dialog import HanlyPrompt
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication


def test_an_open_capture_prompt_counts_as_the_shells_own_window(
    qt_application: QApplication,
) -> None:
    """Showing the prompt activates the shell wherever the pointer is; a reopen
    then covered it with the Control Center on the first click."""

    prompt = HanlyPrompt(theme=Theme.DARK)
    prompt.setWindowModality(Qt.WindowModality.ApplicationModal)
    try:
        prompt.show()
        qt_application.processEvents()
        assert QApplication.activeModalWidget() is prompt
        assert _pointer_on_own_window() is True
    finally:
        prompt.close()
        qt_application.processEvents()
