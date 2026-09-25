"""Hanly's own prompt, as the capture-area question uses it."""

from __future__ import annotations

from hanly_app.config import Theme
from hanly_app.hanly_dialog import HanlyPrompt
from hanly_app.qt_theme import PALETTES
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QPushButton


def _prompt(theme: Theme = Theme.DARK) -> tuple[HanlyPrompt, QPushButton, QPushButton, QPushButton]:
    prompt = HanlyPrompt(theme=theme)
    prompt.setWindowTitle("Where should Hanly read?")
    prompt.setText("Choose the area Hanly should watch.")
    whole = prompt.addButton("Whole monitor", HanlyPrompt.ButtonRole.AcceptRole)
    region = prompt.addButton("Select an area", HanlyPrompt.ButtonRole.ActionRole)
    cancel = prompt.addButton("Cancel", HanlyPrompt.ButtonRole.RejectRole)
    return prompt, whole, region, cancel


def test_the_prompt_reports_the_answer_clicked(qt_application: QApplication) -> None:
    prompt, whole, region, _cancel = _prompt()
    try:
        region.click()
        assert prompt.clickedButton() is region
        assert prompt.result() == 1
        assert whole.isDefault()
    finally:
        prompt.close()


def test_cancel_backs_out_and_sits_before_the_answers(qt_application: QApplication) -> None:
    prompt, _whole, _region, cancel = _prompt()
    try:
        prompt.show()
        qt_application.processEvents()
        buttons = sorted(prompt.findChildren(QPushButton), key=lambda button: button.x())
        assert [button.text() for button in buttons] == [
            "Cancel", "Whole monitor", "Select an area"
        ]
        cancel.click()
        assert prompt.clickedButton() is cancel
        assert prompt.result() == 0
    finally:
        prompt.close()


def test_the_prompt_is_hanly_styled_and_kept_in_front(qt_application: QApplication) -> None:
    for theme, mode in ((Theme.DARK, "dark"), (Theme.LIGHT, "light")):
        prompt, *_ = _prompt(theme)
        try:
            assert PALETTES[mode]["bg"] in prompt.styleSheet()
            assert PALETTES[mode]["accent"] in prompt.styleSheet()
            assert prompt.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
            assert prompt.isModal()
        finally:
            prompt.close()
