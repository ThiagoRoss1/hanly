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

from collections.abc import Callable, Sequence
from typing import Any

from .control_center import ControlCenterUnavailable
from .diagnostics import DiagnosticLog, install_qt_message_handler

QT_PROGRAM_ARGUMENTS: tuple[str, ...] = ("hanly",)

_application: Any = None
_invoker: Any = None


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


def install_qt_thread_invoker() -> Callable[[Callable[[], None]], None]:
    """Return a callable that runs work on the thread owning the Qt loop.

    Must be called from that thread, because the object it posts through
    belongs to whichever thread created it. Cocoa refuses application-level
    work from anywhere else, and the Control Center's requests arrive on its
    transport reader thread.
    """

    global _invoker

    if _invoker is None:
        _invoker = _build_invoker()
    return _invoker.post


def _build_invoker() -> Any:
    from PyQt6.QtCore import QObject, Qt, pyqtSignal, pyqtSlot

    class _QueuedInvoker(QObject):
        requested = pyqtSignal(object)

        def __init__(self) -> None:
            super().__init__()
            # PyQt6's stubs only declare the single-argument connect(), so the
            # connection type has to be passed past the type checker.
            self.requested.connect(  # type: ignore[call-arg]
                self._run, Qt.ConnectionType.QueuedConnection
            )

        def post(self, callback: Callable[[], None]) -> None:
            self.requested.emit(callback)

        @pyqtSlot(object)
        def _run(self, callback: object) -> None:
            if callable(callback):
                callback()

    return _QueuedInvoker()


__all__ = [
    "QT_PROGRAM_ARGUMENTS",
    "ensure_qt_application",
    "install_qt_thread_invoker",
    "qt_application",
]
