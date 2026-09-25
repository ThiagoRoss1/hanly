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

import os
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .app_icon import APPLICATION_NAME, qt_icon
from .control_center import ControlCenterUnavailable
from .diagnostics import DiagnosticLog, install_qt_message_handler

QT_PROGRAM_ARGUMENTS: tuple[str, ...] = ("hanly",)

XCB_PLATFORM = "xcb"
XCB_PLUGIN_FILE = "libqxcb.so"

XCB_SYSTEM_PACKAGES = (
    "libxcb-cursor0, libxcb-icccm4, libxcb-keysyms1, libxcb-shape0, "
    "libxcb-xkb1, libxkbcommon-x11-0"
)

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
    console of a windowed build. Construction is preceded by
    :func:`verify_platform_plugin`, because one class of Qt failure is an
    abort rather than a message.
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
        verify_platform_plugin()
        _claim_platform_identity()
        _application = QApplication(list(argv) or list(QT_PROGRAM_ARGUMENTS))
        _apply_identity(_application)
    return _application


#: Groups every Hanly process under one taskbar entry and one icon on Windows,
#: instead of under the interpreter that happens to run them.
WINDOWS_APP_USER_MODEL_ID = "io.github.thiagoross1.hanly"


def _claim_platform_identity() -> None:
    """Name the process before the platform reads its name, which it does once.

    A source run is ``python3.13`` to macOS and ``python.exe`` to Windows; a
    frozen build already carries its own name, and setting it again is harmless.
    Cosmetic, so a failure here never stops Hanly starting.
    """

    try:
        if sys.platform == "darwin":
            from Foundation import NSBundle

            info = NSBundle.mainBundle().infoDictionary()
            if info is not None:
                info["CFBundleName"] = APPLICATION_NAME
        elif sys.platform == "win32":
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                WINDOWS_APP_USER_MODEL_ID
            )
    except Exception:
        pass


def _apply_identity(application: Any) -> None:
    """Show Hanly's name and icon on every window this process opens."""

    try:
        application.setApplicationDisplayName(APPLICATION_NAME)
        application.setWindowIcon(qt_icon())
    except Exception:
        pass


#: How the primary screen is asked for. Injectable because the answer, not the
#: Qt call, is what the decision below is made from.
ScreenProbe = Callable[[], object | None]


def verify_primary_screen(probe: ScreenProbe | None = None) -> None:
    """Fail before a library reads the geometry of a screen that is not there.

    Qt initializes in a session with no screen and only says so fatally later.
    pywebview then asks the primary screen for its geometry while creating the
    window, without checking that there is one, and the failure surfaces from
    inside that library rather than from Hanly.

    This runs after the application exists, so it cannot prevent an abort
    inside ``QApplication`` itself; that case stays with the packaging
    self-check's stage markers and Qt's own message handler.
    """

    screen = (_primary_screen if probe is None else probe)()
    if screen is None:
        raise ControlCenterUnavailable(
            "this session has no usable screen; the Control Center needs a desktop"
        )


def _primary_screen() -> object | None:
    from PyQt6.QtGui import QGuiApplication

    return QGuiApplication.primaryScreen()


def verify_platform_plugin(environment: Mapping[str, str] | None = None) -> None:
    """Fail with an exception where Qt would abort the process instead.

    Qt calls ``qFatal`` when its platform plugin cannot be loaded, which is a
    ``SIGABRT`` no caller can catch. Only Linux can reach that: its xcb plugin
    depends on X client libraries that live outside the application, while the
    Windows and macOS plugins link against the operating system itself.
    """

    if not sys.platform.startswith("linux"):
        return

    env = os.environ if environment is None else environment
    if _selected_platform(env) != XCB_PLATFORM:
        return
    if not env.get("DISPLAY"):
        raise ControlCenterUnavailable(
            "Hanly cannot open a window: this session has no X display (DISPLAY is unset)"
        )

    plugin = _xcb_plugin_path()
    if plugin is not None:
        _load_plugin(plugin)


def _selected_platform(environment: Mapping[str, str]) -> str:
    """Name the plugin Qt will try first, the way Qt itself resolves it.

    ``QT_QPA_PLATFORM`` may carry a semicolon-separated fallback list, and the
    first entry is the one whose absence would end the process.
    """

    named = environment.get("QT_QPA_PLATFORM", "").split(";")[0].strip()
    if named:
        return named
    return "wayland" if environment.get("WAYLAND_DISPLAY") else XCB_PLATFORM


def _xcb_plugin_path() -> Path | None:
    """Locate the plugin file, or return ``None`` when Qt ships none to check."""

    from PyQt6.QtCore import QLibraryInfo

    plugins = QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath)
    if not plugins:
        return None
    candidate = Path(plugins) / "platforms" / XCB_PLUGIN_FILE
    return candidate if candidate.is_file() else None


def _load_plugin(plugin: Path) -> None:
    """Resolve the plugin's own dependencies, where a gap is still catchable."""

    import ctypes

    try:
        ctypes.CDLL(str(plugin))
    except OSError as error:
        raise ControlCenterUnavailable(
            f"Hanly cannot open a window: Qt's {XCB_PLATFORM} platform plugin "
            f"could not be loaded ({error}). Install the X client libraries it "
            f"needs: {XCB_SYSTEM_PACKAGES}."
        ) from error


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
            # PyQt6's stubs declare connect() with the slot alone, so the
            # explicit connection type goes through an untyped reference
            # rather than a suppression that goes stale when they improve.
            connect: Any = self.requested.connect
            connect(self._run, Qt.ConnectionType.QueuedConnection)

        def post(self, callback: Callable[[], None]) -> None:
            self.requested.emit(callback)

        @pyqtSlot(object)
        def _run(self, callback: object) -> None:
            if callable(callback):
                callback()

    return _QueuedInvoker()


__all__ = [
    "QT_PROGRAM_ARGUMENTS",
    "XCB_PLATFORM",
    "XCB_PLUGIN_FILE",
    "XCB_SYSTEM_PACKAGES",
    "ensure_qt_application",
    "install_qt_thread_invoker",
    "qt_application",
    "verify_platform_plugin",
    "verify_primary_screen",
]
