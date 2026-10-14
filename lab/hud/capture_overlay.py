"""Opaque, pointer-transparent raster borders drawn outside the last capture."""

from __future__ import annotations

from threading import Lock
from typing import Any

from hanly_app.runtime_trace import JSONPrimitive
from PIL import Image, ImageDraw

from ..session.raster_fonts import available_fonts, load_font
from ..session.raster_ui import ImageWindow, Rect, UIHost

_REFRESH_MS = 50
_ROI_COLOR = "#eb6834"
_OUTSET = 2
_LABEL_HEIGHT = 15


class CaptureOverlay:
    """Mark a captured ROI with four small opaque windows around its edges."""

    retain_geometry = True

    def __init__(self, ui: UIHost) -> None:
        self._ui = ui
        self._lock = Lock()
        self._pending: list[dict[str, JSONPrimitive]] = []
        self._windows: list[ImageWindow] = []
        self._closed = False
        self._schedule_drain()

    def emit(self, event: Any) -> object:
        with self._lock:
            self._pending.append(dict(event))
        return None

    def _schedule_drain(self) -> None:
        if not self._closed:
            self._ui.call_later(_REFRESH_MS, self._drain)

    def _drain(self) -> None:
        if self._closed:
            return
        with self._lock:
            events = self._pending
            self._pending = []
        for event in events:
            if event.get("event_kind") == "hover_capture_completed":
                roi = _roi(event)
                if roi is not None:
                    self._draw(roi)
        self._schedule_drain()

    def _draw(self, values: tuple[float, float, float, float]) -> None:
        left, top, width, height = values
        geometry = self._ui.geometry
        scale = geometry.pointer_scale
        display_scale = geometry.display_scale
        roi_origin = geometry.from_pointer((left, top))
        roi = Rect(roi_origin.x, roi_origin.y, width / scale, height / scale)
        border = max(1 / display_scale, 2 / display_scale)
        gap = _OUTSET / scale
        outside = gap + border
        strips = [
            Rect(roi.x - outside, roi.y - outside, roi.width + 2 * outside, border),
            Rect(roi.x - outside, roi.bottom + gap, roi.width + 2 * outside, border),
            Rect(roi.x - outside, roi.y - gap, border, roi.height + 2 * gap),
            Rect(roi.right + gap, roi.y - gap, border, roi.height + 2 * gap),
        ]
        label_y = roi.y - gap - _LABEL_HEIGHT
        if label_y < 0:
            label_y = roi.bottom + gap + 2
        label = Rect(roi.x, label_y, 210, _LABEL_HEIGHT)
        bounds = strips + [label]
        images = [_solid(strip, display_scale) for strip in strips]
        images.append(
            _label(
                f"{int(width)}x{int(height)} @ {int(left)},{int(top)}",
                label,
                display_scale,
            )
        )

        if not self._windows:
            self._windows = [
                self._ui.create_window(
                    self._ui.geometry.to_window(Rect(0, 0, 1, 1)),
                    ignore_mouse=True,
                )
                for _ in bounds
            ]
        for window, rect, image in zip(self._windows, bounds, images, strict=True):
            window.set_bounds(geometry.to_window(rect))
            window.set_image(image)
            window.show()

    def close(self) -> None:
        self._closed = True
        for window in self._windows:
            window.close()


def _roi(event: dict[str, JSONPrimitive]) -> tuple[float, float, float, float] | None:
    values = (
        _number(event.get("region_left")),
        _number(event.get("region_top")),
        _number(event.get("roi_width")),
        _number(event.get("roi_height")),
    )
    if any(value is None for value in values):
        return None
    left, top, width, height = values
    assert left is not None and top is not None and width is not None and height is not None
    return left, top, width, height


def _solid(bounds: Rect, scale: float) -> Image.Image:
    return Image.new(
        "RGB",
        (max(1, round(bounds.width * scale)), max(1, round(bounds.height * scale))),
        _ROI_COLOR,
    )


def _label(text: str, bounds: Rect, scale: float) -> Image.Image:
    image = Image.new(
        "RGB",
        (max(1, round(bounds.width * scale)), max(1, round(bounds.height * scale))),
        _ROI_COLOR,
    )
    draw = ImageDraw.Draw(image)
    face = available_fonts(("Menlo", "Consolas", "Apple SD Gothic Neo", "Malgun Gothic"))[0]
    font = load_font(face, max(1, round(8 * scale)))
    draw.text((round(2 * scale), round(2 * scale)), text, font=font, fill="#111318", anchor="lt")
    return image


def _number(value: JSONPrimitive) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


__all__ = ["CaptureOverlay"]
