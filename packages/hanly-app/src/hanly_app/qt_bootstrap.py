"""The one ``QApplication`` a Hanly process owns, created in one place.

Qt registers window classes on construction and never unregisters them, so a
second application object in the same process is not a fresh start. Every
caller goes through :func:`ensure_qt_application` so that decision exists once.

The program name is not cosmetic: Qt WebEngine initializes Chromium's command
line from the application arguments and aborts without argument zero. The
shell has no WebEngine, but the Control Center child creates its application
through this same function.

Nothing heavy is imported here. Qt WebEngine belongs to the Control Center
child and the OCR runtime to the lookup child; the shell has neither.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .control_center import ControlCenterUnavailable
from .diagnostics import DiagnosticLog, install_qt_message_handler

QT_PROGRAM_ARGUMENTS: tuple[str, ...] = ("hanly",)

_application: Any = None


def ensure_qt_application(
    argv: Sequence[str] = QT_PROGRAM_ARGUMENTS,
    *,
    diagnostics: DiagnosticLog | None = None,
) -> Any:
    """Return this process's single ``QApplication``, creating it if needed.

    ``diagnostics``, when given, also receives Qt's own messages, so a fatal
    Qt error is recorded before the abort rather than lost with the missing
    console of a windowed build.
    """

    global _application

    try:
        from PyQt6.QtWidgets import QApplication
    except ImportError as error:
        raise ControlCenterUnavailable(
            "Hanly Desktop requires the hanly-app runtime extra with Qt6"
        ) from error

    if diagnostics is not None:
        install_qt_message_handler(diagnostics)

    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        _application = existing
    elif not isinstance(_application, QApplication):
        _application = QApplication(list(argv) or list(QT_PROGRAM_ARGUMENTS))
    return _application


def qt_application() -> Any:
    """Return the already-created application, or ``None`` before bootstrap."""

    return _application


__all__ = [
    "QT_PROGRAM_ARGUMENTS",
    "ensure_qt_application",
    "qt_application",
]
