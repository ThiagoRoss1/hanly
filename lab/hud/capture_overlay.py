"""On-screen outline of the region Hanly actually captured.

Everything is drawn strictly *outside* that region, because a see-through
window is composited into the screen and the capture backend reads the result
back as content. Region geometry belongs in the panel's schematic for the same
reason.
"""

from __future__ import annotations

from threading import Lock
from typing import Any

from hanly_app.runtime_trace import JSONPrimitive
from PyQt6.QtCore import QRect, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter, QPaintEvent, QPen
from PyQt6.QtWidgets import QWidget

_REFRESH_MS = 50
_ROI_COLOR = "#eb6834"
#: Pixels between the drawn outline and the region it marks. The outline must
#: fall entirely outside, or it lands in the next capture of the same area.
_OUTSET = 2


class CaptureOverlay(QWidget):
    """Outline the last captured ROI.

    Capture geometry arrives in virtual-desktop coordinates, the same space
    this widget is positioned in, so no conversion is needed. Events are queued
    and drained on the UI thread, as in the timeline panel.
    """

    def __init__(self, desktop: QRect) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setGeometry(desktop)

        self._desktop = desktop
        self._lock = Lock()
        self._pending: list[dict[str, JSONPrimitive]] = []
        self._roi: QRect | None = None
        self._label = ""

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._drain)
        self._timer.start(_REFRESH_MS)

    def emit(self, event: Any) -> object:
        """Queue one trace event from whichever thread produced it."""

        with self._lock:
            self._pending.append(dict(event))
        return None

    def _drain(self) -> None:
        with self._lock:
            events = self._pending
            self._pending = []
        changed = False
        for event in events:
            changed |= self._apply(event)
        if changed:
            self.update()

    def _apply(self, event: dict[str, JSONPrimitive]) -> bool:
        if event.get("event_kind") != "hover_capture_completed":
            return False

        left = _number(event.get("region_left"))
        top = _number(event.get("region_top"))
        width = _number(event.get("roi_width"))
        height = _number(event.get("roi_height"))
        if None in (left, top, width, height):
            return False
        assert left is not None and top is not None
        assert width is not None and height is not None

        self._roi = QRect(int(left), int(top), int(width), int(height))
        self._label = f"{int(width)}x{int(height)} @ {int(left)},{int(top)}"
        return True

    def paintEvent(self, a0: QPaintEvent | None) -> None:
        del a0
        roi = self._roi
        if roi is None:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Widget coordinates are desktop coordinates shifted by its origin,
        # which is not the origin on a multi-monitor desktop with a secondary
        # display to the left of or above the primary one.
        local = roi.translated(-self._desktop.left(), -self._desktop.top())

        # Outside the region on every side, so the next capture of the same
        # area sees the screen and not this overlay.
        painter.setPen(QPen(QColor(_ROI_COLOR), 1))
        painter.drawRect(local.adjusted(-_OUTSET, -_OUTSET, _OUTSET, _OUTSET))

        painter.setFont(QFont("Consolas", 8))
        painter.drawText(
            local.left() - _OUTSET,
            max(10, local.top() - _OUTSET - 3),
            self._label,
        )
        painter.end()


def _number(value: JSONPrimitive) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


__all__ = ["CaptureOverlay"]
