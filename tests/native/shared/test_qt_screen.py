"""A real desktop session answers for its own screen.

The portable suite covers both branches of the guard with an injected probe.
This is the one thing it cannot cover: that an ordinary session actually
reaches Qt's primary screen, so the guard does not refuse a working desktop.
"""

from __future__ import annotations

from tests.hanly_fixtures.capabilities import require_modules

require_modules("PyQt6.QtWidgets", module_level=True)

from hanly_app.qt_bootstrap import verify_primary_screen  # noqa: E402
from PyQt6.QtGui import QGuiApplication  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402


def test_a_real_session_reports_a_primary_screen(qt_application: QApplication) -> None:
    assert QGuiApplication.primaryScreen() is not None

    verify_primary_screen()
