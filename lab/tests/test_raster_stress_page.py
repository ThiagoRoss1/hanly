"""Portable stress-page layout contracts for source images and omissions."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from lab.session.corpus import TourTarget
from lab.session.raster_ui import DesktopGeometry, Rect
from lab.session.stress import StressItem
from lab.session.stress_page import StressPage
from lab.tests.test_raster_ui import _UIHost


def _item(image: Path, target: str, point: tuple[float, float]) -> StressItem:
    return StressItem(
        TourTarget(target, "corpus", "", 0, "", 0, None, None, refuse=True),
        "corpus",
        image=str(image),
        image_target=point,
        truth_target="no_korean",
        case=target,
    )


def test_corpus_images_keep_the_annotated_physical_pixel_and_omit_oversized(
    tmp_path: Path,
) -> None:
    geometry = DesktopGeometry(
        bounds=Rect(-100, -40, 1200, 800),
        pointer_origin=(-200, -80),
        pointer_scale=2,
        display_scale=2,
        primary=Rect(100, 40, 1000, 720),
    )
    host = _UIHost(geometry)
    small = tmp_path / "small.png"
    huge = tmp_path / "huge.png"
    Image.new("RGB", (120, 40), "#dc2828").save(small)
    Image.new("RGB", (40000, 40), "#28dc28").save(huge)
    page = StressPage(host)
    try:
        page.lay_out_plan(
            [_item(small, "a", (60.0, 20.0)), _item(huge, "b", (1.0, 1.0))],
            seed=1,
        )

        placed = [item for page_data in page.pages for item in page_data.placed]
        assert [item.target.id for item in placed] == ["a"]
        assert page.omitted == [{"target": "b", "reason": "image does not fit"}]
        first = placed[0]
        assert first.point.x == first.word.left + 30
        assert first.point.y == first.word.top + 10
        assert first.word.width == 60
        assert first.word.height == 20
        assert page.show_page(0)
        image = host.windows[0].image
        assert image is not None
        x = round(first.point.x * 2)
        y = round(first.point.y * 2)
        assert image.getpixel((x, y)) == (220, 40, 40)
    finally:
        page.close()
