"""Session-scoped whole-monitor or drag-region selection for ``hanly run``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .bootstrap import DEFAULT_OCR_RUNTIME_MODULE
from .capture import ScreenRect
from .config import CaptureMode


class CaptureSelectorError(RuntimeError):
    """Raised when the interactive capture selector cannot be shown."""


@dataclass(frozen=True, slots=True)
class CaptureSelection:
    """One launch-time capture choice; cancellation is represented by ``None``."""

    capture_mode: CaptureMode
    region: ScreenRect | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.capture_mode, CaptureMode):
            raise TypeError("capture_mode must be a CaptureMode")
        if self.capture_mode is CaptureMode.REGION:
            if not isinstance(self.region, ScreenRect):
                raise ValueError("region mode requires a screen region")
        elif self.region is not None:
            raise ValueError("whole-monitor mode cannot carry a region")

    @classmethod
    def whole_monitor(cls) -> CaptureSelection:
        return cls(CaptureMode.FULL_MONITOR)

    @classmethod
    def for_region(cls, region: ScreenRect) -> CaptureSelection:
        return cls(CaptureMode.REGION, region)


def select_capture_area(
    ocr_module: str = DEFAULT_OCR_RUNTIME_MODULE,
) -> CaptureSelection | None:
    """Ask for a whole monitor or a snipping-style region before app startup.

    ``ocr_module`` must name the backend the session will actually use. This
    runs before Qt, and Hanly's Windows native ordering requires the OCR stack
    to load first; preparing a backend the session then does not use loads a
    second native stack for nothing, which is visible as startup delay and
    retained memory.
    """

    from .bootstrap import preload_ocr_runtime

    preload_ocr_runtime(module_name=ocr_module)
    QApplication, QMessageBox = _import_qt_widgets()

    _prepare_web_engine()
    application = _shared_application(QApplication)
    application.setQuitOnLastWindowClosed(False)
    prompt = QMessageBox()
    prompt.setWindowTitle("Start Hanly")
    prompt.setText("Choose the area Hanly should observe for this session.")
    whole_button = prompt.addButton(
        "Whole monitor", QMessageBox.ButtonRole.AcceptRole
    )
    region_button = prompt.addButton(
        "Select an area", QMessageBox.ButtonRole.ActionRole
    )
    cancel_button = prompt.addButton(QMessageBox.StandardButton.Cancel)
    prompt.exec()
    clicked = prompt.clickedButton()
    if clicked is cancel_button or clicked is None:
        return None
    if clicked is whole_button:
        return CaptureSelection.whole_monitor()
    if clicked is not region_button:
        return None

    region = _select_region(application)
    return None if region is None else CaptureSelection.for_region(region)


def _import_qt_widgets() -> tuple[Any, Any]:
    """Import the Qt widgets this module needs, as a seam tests can fail.

    Qt is an optional runtime extra, so its absence is a normal startup
    condition rather than a crash. Isolating the import keeps that path
    reachable from a test instead of only from a machine without Qt.
    """

    try:
        from PyQt6.QtWidgets import QApplication, QMessageBox
    except ImportError as error:
        raise CaptureSelectorError("capture selection requires the Qt runtime") from error
    return QApplication, QMessageBox


def _prepare_web_engine() -> None:
    """Set up Qt WebEngine before this module constructs a QApplication.

    The Control Center's WebEngine requires its shared-OpenGL attribute before
    Qt builds an application object, and the chooser now builds the one the
    desktop goes on to reuse. Failure is ignored here: desktop startup repeats
    this call and owns reporting a genuinely missing Qt runtime.
    """

    from .control_center import ControlCenterUnavailable, prepare_control_center_qt

    try:
        prepare_control_center_qt()
    except ControlCenterUnavailable:
        pass


#: Holds the process's QApplication so it outlives this module's callers.
#: Qt registers window classes on construction and does not unregister them on
#: destruction, so letting the chooser's application fall out of scope and
#: building a second one for the desktop makes Qt re-register classes it
#: already owns. One application per process avoids that entirely.
_application: object | None = None


def _shared_application(application_type: Any) -> Any:
    """Return the one QApplication for this process, creating it if needed."""

    global _application

    existing = application_type.instance()
    if isinstance(existing, application_type):
        _application = existing
    elif not isinstance(_application, application_type):
        _application = application_type([])
    return _application


def _select_region(application: object) -> ScreenRect | None:
    """Run the lazy Qt overlay and return global virtual-desktop coordinates."""

    from PyQt6.QtCore import QPoint, QRect, Qt
    from PyQt6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter, QPaintEvent, QPen
    from PyQt6.QtWidgets import QApplication, QDialog

    if not isinstance(application, QApplication):
        raise TypeError("application must be a QApplication")
    screens = application.screens()
    if not screens:
        raise CaptureSelectorError("no screen is available for capture selection")
    geometries = [screen.geometry() for screen in screens]
    left = min(geometry.left() for geometry in geometries)
    top = min(geometry.top() for geometry in geometries)
    right = max(geometry.right() for geometry in geometries)
    bottom = max(geometry.bottom() for geometry in geometries)

    class RegionOverlay(QDialog):
        def __init__(self) -> None:
            flags = (
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.Tool
                | Qt.WindowType.WindowStaysOnTopHint
            )
            super().__init__(None, flags)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setCursor(Qt.CursorShape.CrossCursor)
            self.setGeometry(left, top, right - left + 1, bottom - top + 1)
            self.origin: QPoint | None = None
            self.selection: QRect | None = None
            self.result_region: ScreenRect | None = None

        def mousePressEvent(self, event: QMouseEvent | None) -> None:
            if event is None:
                return
            if event.button() is Qt.MouseButton.RightButton:
                self.reject()
                return
            if event.button() is Qt.MouseButton.LeftButton:
                self.origin = event.position().toPoint()
                self.selection = QRect(self.origin, self.origin)
                self.update()

        def mouseMoveEvent(self, event: QMouseEvent | None) -> None:
            if event is None or self.origin is None:
                return
            self.selection = QRect(self.origin, event.position().toPoint()).normalized()
            self.update()

        def mouseReleaseEvent(self, event: QMouseEvent | None) -> None:
            if (
                event is None
                or event.button() is not Qt.MouseButton.LeftButton
                or self.origin is None
            ):
                return
            rectangle = QRect(self.origin, event.position().toPoint()).normalized()
            if rectangle.width() < 2 or rectangle.height() < 2:
                self.origin = None
                self.selection = None
                self.update()
                return
            global_rectangle = QRect(
                self.x() + rectangle.x(),
                self.y() + rectangle.y(),
                rectangle.width(),
                rectangle.height(),
            )
            if not any(geometry.contains(global_rectangle) for geometry in geometries):
                self.origin = None
                self.selection = None
                self.update()
                return
            self.result_region = ScreenRect(
                global_rectangle.x(),
                global_rectangle.y(),
                rectangle.width(),
                rectangle.height(),
            )
            self.accept()

        def keyPressEvent(self, event: QKeyEvent | None) -> None:
            if event is None:
                return
            if event.key() == Qt.Key.Key_Escape:
                self.reject()
                return
            super().keyPressEvent(event)

        def paintEvent(self, _event: QPaintEvent | None) -> None:
            painter = QPainter(self)
            painter.fillRect(self.rect(), QColor(10, 14, 18, 150))
            if self.selection is not None:
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
                painter.fillRect(self.selection, Qt.GlobalColor.transparent)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
                painter.setPen(QPen(QColor(84, 208, 255), 2))
                painter.drawRect(self.selection)
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(
                self.rect().adjusted(24, 24, -24, -24),
                Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter,
                "Drag inside one monitor · Esc or right-click to cancel",
            )

    overlay = RegionOverlay()
    overlay.exec()
    return overlay.result_region


__all__ = ["CaptureSelection", "CaptureSelectorError", "select_capture_area"]
