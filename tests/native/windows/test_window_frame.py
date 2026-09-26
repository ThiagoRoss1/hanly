"""The Control Center's title bar takes the page's mode at once, on a real window.

Windows 10 accepts the dark-mode attribute without redrawing the caption, which
then keeps its previous colour until the window is next activated. What is
checked here is the drawn caption, not the attribute.
"""

from __future__ import annotations

import ctypes
import time
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

import pytest
from hanly_app.window_frame_win32 import apply_frame_theme

from tests.hanly_fixtures.capabilities import unavailable

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QApplication, QWidget

# Only a Windows host collects this module; the type check also runs elsewhere.
_windll: Any = getattr(ctypes, "windll", None)


def _caption_luminance(window: QWidget) -> float:
    frame = window.frameGeometry()
    # The caption strip: below the resize border, clear of the title text.
    x, y = frame.x() + frame.width() // 2 + 60, frame.y() + 15
    screen = _windll.user32.GetDC(0)
    try:
        colour = _windll.gdi32.GetPixel(screen, x, y)
    finally:
        _windll.user32.ReleaseDC(0, screen)
    red, green, blue = colour & 0xFF, (colour >> 8) & 0xFF, (colour >> 16) & 0xFF
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _settle(application: QApplication) -> None:
    for _ in range(12):
        application.processEvents()
        time.sleep(0.04)


@pytest.fixture
def active_window(qt_application: QApplication) -> Iterator[QWidget]:
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QWidget

    window = QWidget(None, Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
    window.setWindowTitle("Hanly frame")
    window.resize(420, 140)
    window.show()
    window.raise_()
    window.activateWindow()
    _settle(qt_application)
    if _windll.user32.GetForegroundWindow() != int(window.winId()):
        window.close()
        unavailable("Windows did not give the test window the foreground")
    yield window
    window.close()
    _settle(qt_application)


def test_the_active_title_bar_is_redrawn_in_the_chosen_mode(
    qt_application: QApplication, active_window: QWidget
) -> None:
    handle = int(active_window.winId())

    for mode in ("dark", "light", "dark", "light"):
        apply_frame_theme(handle, mode)
        _settle(qt_application)
        luminance = _caption_luminance(active_window)
        if mode == "dark":
            assert luminance < 80, f"caption still light after choosing dark ({luminance:.0f})"
        else:
            assert luminance > 180, f"caption still dark after choosing light ({luminance:.0f})"
