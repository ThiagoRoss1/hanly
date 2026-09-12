"""One pywebview window and the GUI loop it runs in.

This is the window itself, not the desktop's lifecycle. The Control Center
runs in its own process (see :mod:`hanly_app.control_center_process`), and the
packaging self-check opens the same window against an in-process bridge; both
go through this host so there is one place that creates the window, insists on
the Qt backend, and owns the loop.

Closing the window destroys it and ends the loop. Whatever started the host
decides what that means — for the child process it means exiting.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from .control_center import (
    ControlCenterUnavailable,
    control_center_document,
    prepare_control_center_qt,
)
from .diagnostics import DiagnosticLog, StartupTimeline
from .qt_bootstrap import ensure_qt_application

#: The backend module Hanly's single-Qt design requires. pywebview falls back
#: to Cocoa, GTK, or WinForms when Qt cannot load, which would silently mix two
#: GUI frameworks in one process.
QT_BACKEND_MODULE = "webview.platforms.qt"

ErrorReporter = Callable[[str, BaseException], None]


class ControlCenterHost:
    """Create the main window once and own the loop it runs in."""

    def __init__(
        self,
        bridge: object,
        *,
        title: str = "Hanly · Control Center",
        width: int = 1080,
        height: int = 760,
        debug: bool = False,
        webview_module: object | None = None,
        diagnostics: DiagnosticLog | None = None,
        timeline: StartupTimeline | None = None,
        on_error: ErrorReporter | None = None,
    ) -> None:
        if width <= 0 or height <= 0:
            raise ValueError("Control Center dimensions must be positive")
        if on_error is not None and not callable(on_error):
            raise TypeError("on_error must be callable")

        self._bridge = bridge
        self._title = title
        self._width = width
        self._height = height
        self._debug = debug
        self._webview = webview_module
        self._diagnostics = diagnostics
        self._timeline = timeline or StartupTimeline()
        self._shown_once = False
        self._on_error = on_error

        self._lock = threading.RLock()
        self._window: Any = None
        self._running = False
        self._visible = False
        self._destroyed = False

    @property
    def created(self) -> bool:
        """Whether the one window exists, whether or not it is on screen."""

        with self._lock:
            return self._window is not None and not self._destroyed

    @property
    def visible(self) -> bool:
        """Whether the window is currently shown, per pywebview's own events."""

        with self._lock:
            return self._visible

    @property
    def running(self) -> bool:
        """Whether this host is inside the GUI event loop."""

        with self._lock:
            return self._running

    @property
    def window(self) -> Any:
        """The pywebview window this host owns, once :meth:`run` created it."""

        with self._lock:
            return self._window

    def run(self, on_started: Callable[[], None] | None = None) -> int:
        """Create the window and run the GUI loop until it is destroyed.

        Blocks on the process main thread and returns once the loop exits.
        ``on_started`` is pywebview's own post-start hook, which it runs off
        the UI thread; the packaging harness drives the window through it.
        """

        if threading.current_thread() is not threading.main_thread():
            raise ControlCenterUnavailable(
                "the Control Center loop must run on the process main thread"
            )
        with self._lock:
            if self._running:
                raise ControlCenterUnavailable("the Control Center loop is already running")
            self._running = True

        webview = self._load_webview()
        self._create_window(webview)
        try:
            self._start_loop(webview, on_started)
        finally:
            with self._lock:
                self._running = False
                self._visible = False
        return 0

    def show(self) -> None:
        """Bring the existing window forward, the ordinary focus path."""

        window = self._require_window()
        self._call_window(window, "show")
        with self._lock:
            self._visible = True

    def hide(self) -> None:
        """Hide the window without destroying it or stopping the loop."""

        window = self._require_window()
        self._call_window(window, "hide")
        with self._lock:
            self._visible = False

    def close(self) -> None:
        """Destroy the window, which ends the loop."""

        with self._lock:
            window = self._window
            if window is None or self._destroyed:
                return
            self._destroyed = True
            self._visible = False
        self._call_window(window, "destroy")

    def evaluate(self, script: str) -> Any:
        """Run one script in the page, tolerating a window that has gone."""

        with self._lock:
            window = self._window
            destroyed = self._destroyed
        evaluate = getattr(window, "evaluate_js", None)
        if window is None or destroyed or not callable(evaluate):
            return None
        try:
            return evaluate(script)
        except Exception as error:
            self._report("Control Center script", error)
            return None

    def _create_window(self, webview: Any) -> None:
        with self._lock:
            if self._window is not None:
                return

        create_window = getattr(webview, "create_window", None)
        if not callable(create_window):
            raise ControlCenterUnavailable("pywebview does not expose create_window")

        window = create_window(
            title=self._title,
            html=control_center_document(),
            js_api=self._bridge,
            width=self._width,
            height=self._height,
            min_size=(760, 560),
            background_color="#F7F8FC",
        )
        self._subscribe(window)
        with self._lock:
            self._window = window
            self._destroyed = False

    def _start_loop(self, webview: Any, on_started: Callable[[], None] | None) -> None:
        start = getattr(webview, "start", None)
        if not callable(start):
            raise ControlCenterUnavailable("pywebview does not expose start")

        self._require_qt_backend(webview)
        options: dict[str, Any] = {"gui": "qt", "debug": self._debug}
        if on_started is not None:
            options["func"] = on_started
        try:
            start(**options)
        except ImportError as error:
            raise ControlCenterUnavailable(
                "pywebview Qt support requires the qt6 optional extra"
            ) from error

    def _require_qt_backend(self, webview: Any) -> None:
        """Fail visibly rather than silently running a non-Qt backend.

        This process's popup-free window, the capture overlay, and Chromium all
        share one ``QApplication``. A fallback to Cocoa, GTK, or WinForms would
        put the window in a second GUI framework inside the same process.
        """

        initialize = getattr(webview, "initialize", None)
        if not callable(initialize):
            return
        backend = initialize("qt")
        name = getattr(backend, "__name__", "")
        if name and name != QT_BACKEND_MODULE:
            raise ControlCenterUnavailable(
                f"pywebview selected the {name} backend; Hanly requires {QT_BACKEND_MODULE}"
            )

    def _subscribe(self, window: Any) -> None:
        """Derive window state from pywebview's events, not from ``start``."""

        events = getattr(window, "events", None)
        if events is None:
            return
        self._subscribe_one(events, "shown", self._on_shown)
        self._subscribe_one(events, "closed", self._on_closed)

    def _subscribe_one(self, events: Any, name: str, handler: Callable[[], Any]) -> None:
        event = getattr(events, name, None)
        if event is None or not hasattr(event, "__iadd__"):
            return
        event += handler
        setattr(events, name, event)

    def _on_shown(self) -> None:
        with self._lock:
            self._visible = True
            first_time = not self._shown_once
            self._shown_once = True
        # Only the first appearance is a startup milestone; showing the window
        # again from the tray is not.
        if first_time:
            self._timeline.reached("window visible")

    def _on_closed(self) -> None:
        with self._lock:
            self._destroyed = True
            self._visible = False
            self._window = None

    def _require_window(self) -> Any:
        with self._lock:
            window = self._window
            destroyed = self._destroyed
        if window is None or destroyed:
            raise ControlCenterUnavailable("the Control Center window is not available")
        return window

    def _call_window(self, window: Any, action: str) -> None:
        """Ask pywebview to mutate the window, which marshals onto Qt itself.

        ``show``, ``hide``, and ``destroy`` emit Qt signals, so a call from a
        transport thread never touches a widget from its own thread.
        """

        method = getattr(window, action, None)
        if not callable(method):
            raise ControlCenterUnavailable(f"pywebview windows cannot {action}")
        try:
            method()
        except Exception as error:
            self._report(f"Control Center {action}", error)

    def _report(self, stage: str, error: BaseException) -> None:
        if self._diagnostics is not None:
            self._diagnostics.report(stage, error)
        if self._on_error is not None:
            self._on_error(stage, error)

    def _load_webview(self) -> Any:
        if self._webview is not None:
            return self._webview
        # Qt WebEngine needs its shared-OpenGL attribute, and Chromium its
        # argument zero, before any Qt object exists in this process.
        prepare_control_center_qt()
        ensure_qt_application(diagnostics=self._diagnostics)
        try:
            import webview
        except ImportError as error:
            raise ControlCenterUnavailable(
                "pywebview is required for the Control Center"
            ) from error
        self._webview = webview
        return webview


__all__ = ["QT_BACKEND_MODULE", "ControlCenterHost", "ErrorReporter"]
