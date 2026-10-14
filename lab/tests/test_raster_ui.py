"""Portable contracts for raster fixture geometry and lazy native UI routing."""

from __future__ import annotations

import subprocess
import sys

from PIL import Image

from lab.session.corpus import TourTarget
from lab.session.page import TourPage
from lab.session.raster_ui import DesktopGeometry, Point, Rect


class _ImageWindow:
    def __init__(self, bounds: Rect) -> None:
        self.bounds = bounds
        self.image: Image.Image | None = None
        self.visible = False

    def set_image(self, image: Image.Image) -> None:
        self.image = image.copy()

    def set_bounds(self, bounds: Rect) -> None:
        self.bounds = bounds

    def show(self) -> None:
        self.visible = True

    def hide(self) -> None:
        self.visible = False

    def close(self) -> None:
        self.visible = False


class _UIHost:
    def __init__(self, geometry: DesktopGeometry) -> None:
        self.geometry = geometry
        self.windows: list[_ImageWindow] = []

    def create_window(
        self, bounds: Rect, *, topmost: bool = True, ignore_mouse: bool = True
    ) -> _ImageWindow:
        del topmost, ignore_mouse
        window = _ImageWindow(bounds)
        self.windows.append(window)
        return window

    def call_after(self, callback) -> None:
        callback()

    def call_later(self, delay_ms: int, callback) -> None:
        del delay_ms, callback

    def run(self, poll, *, interval_ms, duration_s, on_duration) -> int:
        del poll, interval_ms, duration_s, on_duration
        return 0

    def close(self) -> None:
        for window in self.windows:
            window.close()


def test_geometry_separates_window_space_from_scaled_pointer_space() -> None:
    geometry = DesktopGeometry(
        bounds=Rect(-1920, -120, 3840, 1200),
        pointer_origin=(-3840, -240),
        pointer_scale=2,
        display_scale=2,
        primary=Rect(1920, 120, 1920, 1080),
    )

    assert geometry.to_pointer(Point(1920, 120)) == (0, 0)
    assert geometry.from_pointer((960, 500)) == Point(2400, 370)
    assert geometry.to_window(Rect(2400, 370, 200, 100)) == Rect(480, 250, 200, 100)


def test_tour_page_renders_target_text_into_a_scaled_rgb_surface() -> None:
    geometry = DesktopGeometry(
        bounds=Rect(-1920, 0, 3840, 1080),
        pointer_origin=(-1920, 0),
        pointer_scale=1,
        display_scale=2,
        primary=Rect(1920, 0, 1920, 1080),
    )
    host = _UIHost(geometry)
    page = TourPage(host)
    target = TourTarget(
        "story-1", "story", "한국어를 읽습니다.", 0, "한국어", 1, "한국어", "한국어"
    )
    try:
        page.lay_out([target], [], [22], [16])

        assert len(page.pages) == 1
        placed = page.pages[0].placed[0]
        assert placed.target is target
        assert placed.word.contains(placed.point)
        assert page.to_global(placed.point) == (
            round(-1920 + placed.point.x),
            round(placed.point.y),
        )
        assert page.show_page(0)
        image = host.windows[0].image
        assert image is not None
        assert image.mode == "RGB"
        assert image.size == (7680, 2160)
        crop = image.crop(
            (
                round(placed.word.left * 2),
                round(placed.word.top * 2),
                round(placed.word.right * 2),
                round(placed.word.bottom * 2),
            )
        )
        colors = crop.getcolors(maxcolors=crop.width * crop.height)
        assert colors is not None and len(colors) > 1
    finally:
        page.close()


def test_lab_imports_do_not_start_or_load_a_platform_window_toolkit() -> None:
    script = (
        "import sys; "
        "import lab.session.runner, lab.session.page, lab.session.stress_page; "
        "loaded = sorted(name for name in sys.modules if "
        "name == 'tkinter' or name.startswith(('AppKit', 'PyQt6'))); "
        "print(','.join(loaded))"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert not result.stdout.strip()
