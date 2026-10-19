"""A separate native window that covers part of a tour page."""

from __future__ import annotations

import sys

from PIL import Image, ImageDraw

from .raster_fonts import available_fonts, load_font
from .raster_ui import Rect, create_ui_host


def main() -> None:
    if len(sys.argv) != 5:
        raise SystemExit("usage: python -m lab.session.cover LEFT TOP WIDTH HEIGHT")
    left, top, width, height = (int(value) for value in sys.argv[1:5])
    ui = create_ui_host()
    geometry = ui.geometry
    local = geometry.from_pointer((left, top))
    scale = geometry.pointer_scale
    bounds = geometry.to_window(Rect(local.x, local.y, width / scale, height / scale))
    window = ui.create_window(bounds, topmost=True, ignore_mouse=False)
    image = Image.new("RGB", (max(1, width), max(1, height)), "#2a5aa0")
    draw = ImageDraw.Draw(image)
    face = available_fonts(("Malgun Gothic", "Apple SD Gothic Neo", "Noto Sans CJK KR"))[0]
    font = load_font(face, round(28 * geometry.display_scale))
    draw.multiline_text(
        (image.width / 2, image.height / 2),
        "Another application\n다른 프로그램 창",
        font=font,
        fill="white",
        anchor="mm",
        align="center",
        spacing=10,
    )
    window.set_image(image)
    window.show()
    ui.run(lambda: None, interval_ms=200, duration_s=None, on_duration=lambda: None)


if __name__ == "__main__":
    main()
