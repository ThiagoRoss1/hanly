"""Optional PyQt6 adapter for the Qt-independent popup seam.

Import this module only when the desktop UI dependency is installed. The base
``hanly_app`` package and :mod:`hanly_app.popup` remain usable without PyQt6.
"""

from __future__ import annotations

from collections.abc import Callable

from hanly import LookupResult, Point
from PyQt6.QtCore import QObject, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QApplication, QFrame, QLabel, QVBoxLayout, QWidget

from .popup import (
    LookupStopper,
    PopupController,
    PopupPosition,
    PopupRuntime,
    PopupSize,
    ScreenGeometry,
    format_lookup_result,
)


class _QueuedCallbackBridge(QObject):
    """Deliver callbacks in the bridge object's (UI) thread."""

    callback_ready = pyqtSignal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        # The explicit queued type keeps dispatch non-blocking even when a
        # caller happens to emit from the UI thread itself. PyQt6's stubs only
        # declare the single-argument connect(), so the connection type has to
        # be passed past the type checker.
        self.callback_ready.connect(  # type: ignore[call-arg]
            self._run, Qt.ConnectionType.QueuedConnection
        )

    @pyqtSlot(object)
    def _run(self, callback: object) -> None:
        if callable(callback):
            callback()


class QtResultDispatcher:
    """Post a result callback to the UI thread and return immediately.

    Construct this object on the UI thread and pass it as the
    ``LookupController(result_dispatcher=...)`` dependency. Emitting a queued
    signal never waits for the callback, which keeps worker shutdown safe.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        self._bridge = _QueuedCallbackBridge(parent)

    def __call__(self, callback: Callable[[], None]) -> None:
        self._bridge.callback_ready.emit(callback)


class QtPopupView(QFrame):
    """Borderless, always-on-top V1 popup view."""

    def __init__(self, parent: QWidget | None = None) -> None:
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        super().__init__(parent, flags)
        self.setObjectName("hanlyPopup")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(
            "QFrame#hanlyPopup { background: #20252b; border: 1px solid #59636e; "
            "border-radius: 8px; }"
            "QLabel { color: #f5f7fa; background: transparent; }"
            "QLabel#hanlyPopupTitle { font-size: 18px; font-weight: 600; }"
            "QLabel#hanlyPopupBody { font-size: 13px; }"
        )

        self._title = QLabel(self)
        self._title.setObjectName("hanlyPopupTitle")
        self._body = QLabel(self)
        self._body.setObjectName("hanlyPopupBody")
        self._body.setWordWrap(True)
        self._body.setTextFormat(Qt.TextFormat.PlainText)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(6)
        layout.addWidget(self._title)
        layout.addWidget(self._body)
        self.setFixedSize(320, 180)

    @property
    def popup_size(self) -> PopupSize:
        """Return the concrete fixed size used by the V1 placement baseline."""

        return PopupSize(self.width(), self.height())

    def _render(self, result: LookupResult) -> None:
        content = format_lookup_result(result)
        self._title.setText(content.title)
        self._body.setText("\n".join(content.lines) or "No additional details.")

    def _show_at(self, result: LookupResult, position: PopupPosition) -> None:
        self._render(result)
        self.move(position.x, position.y)
        self.show()
        self.raise_()

    def show_result(self, result: LookupResult, position: PopupPosition) -> None:
        self._show_at(result, position)

    def update_result(self, result: LookupResult, position: PopupPosition) -> None:
        self._show_at(result, position)


class QtPopupTrigger:
    """Open a popup result at the current cursor and available screen."""

    def __init__(self, popup: PopupController) -> None:
        self._popup = popup

    def open(self, result: LookupResult) -> PopupPosition:
        """Owned V1 result trigger used by lookup callbacks."""

        cursor = QCursor.pos()
        screen = QApplication.screenAt(cursor) or QApplication.primaryScreen()
        if screen is None:
            raise RuntimeError("no Qt screen is available for popup placement")
        geometry = screen.availableGeometry()
        return self._popup.open(
            result,
            Point(float(cursor.x()), float(cursor.y())),
            ScreenGeometry(geometry.x(), geometry.y(), geometry.width(), geometry.height()),
        )


class QtPopupRuntime:
    """Compose the Qt popup, open trigger, dispatcher, and UI shutdown seam."""

    def __init__(self, lookup_controller: LookupStopper) -> None:
        self.dispatcher = QtResultDispatcher()
        self.view = QtPopupView()
        self.popup = PopupController(self.view, popup_size=self.view.popup_size)
        self.trigger = QtPopupTrigger(self.popup)
        self._runtime = PopupRuntime(self.popup, lookup_controller)

    def open(self, result: LookupResult) -> PopupPosition:
        """Open the V1 popup trigger for a completed lookup result."""

        return self.trigger.open(result)

    def shutdown(self) -> None:
        """Hide UI and request non-blocking lookup shutdown."""

        self._runtime.shutdown()


__all__ = [
    "QtPopupRuntime",
    "QtPopupTrigger",
    "QtPopupView",
    "QtResultDispatcher",
]
