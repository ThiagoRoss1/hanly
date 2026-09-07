"""The one order in which Hanly brings Qt up, and the one application it uses.

Three things must happen before anything native is constructed, in this order:
the OCR runtime loads its libraries while the process still has its original
library search path, Qt WebEngine gets its shared-OpenGL attribute, and only
then is a ``QApplication`` created -- with a program name, because Qt WebEngine
initializes Chromium's command line from the application arguments and aborts
without argument zero.

Every caller goes through :func:`ensure_qt_application` so that ordering exists
in one place instead of being repeated at each entry into the UI.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .control_center import ControlCenterUnavailable, prepare_control_center_qt
from .diagnostics import DiagnosticLog, install_qt_message_handler
from .ocr_preload import DiagnosticReporter, preload_ocr_runtime

QT_PROGRAM_ARGUMENTS: tuple[str, ...] = ("hanly",)

_application: Any = None


def prepare_qt_runtime(*, on_diagnostic: DiagnosticReporter | None = None) -> None:
    """Load the OCR runtime and Qt WebEngine before any Qt object exists."""

    preload_ocr_runtime(on_diagnostic=on_diagnostic)
    prepare_control_center_qt()


def ensure_qt_application(
    argv: Sequence[str] = QT_PROGRAM_ARGUMENTS,
    *,
    diagnostics: DiagnosticLog | None = None,
) -> Any:
    """Return the process's single ``QApplication``, creating it if needed.

    ``diagnostics``, when given, also receives Qt's own messages, so a fatal
    Qt error is recorded before the abort rather than lost with the missing
    console of a windowed build.
    """

    global _application

    reporter = None if diagnostics is None else diagnostics.add
    prepare_qt_runtime(on_diagnostic=reporter)

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
    "prepare_qt_runtime",
    "qt_application",
]
