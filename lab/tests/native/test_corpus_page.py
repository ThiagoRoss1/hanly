"""The native raster host paints the controlled corpus and owns its pixels."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest
from PIL import Image

from lab.session.corpus import TourTarget
from lab.session.raster_ui import create_ui_host
from lab.session.stress import StressItem
from lab.session.stress_page import StressPage
from tests.hanly_fixtures.capabilities import require_display, require_modules, unavailable

pytestmark = pytest.mark.native


def _item(image: Path, target: str, point: tuple[float, float]) -> StressItem:
    return StressItem(
        TourTarget(target, "corpus", "", 0, "", 0, None, None, refuse=True),
        "corpus",
        image=str(image),
        image_target=point,
        truth_target="no_korean",
        case=target,
    )


def test_native_window_paints_corpus_pixels_and_is_owned(tmp_path: Path) -> None:
    require_display()
    require_modules("PIL")
    mss = pytest.importorskip("mss")
    if sys.platform == "darwin":
        require_modules("AppKit", "Foundation", "PyObjCTools")
    else:
        require_modules("tkinter")
    try:
        ui = create_ui_host()
    except RuntimeError as error:
        unavailable(str(error))

    small = tmp_path / "small.png"
    huge = tmp_path / "huge.png"
    Image.new("RGB", (120, 40), "#dc2828").save(small)
    Image.new("RGB", (40000, 40), "#28dc28").save(huge)
    page = StressPage(ui)
    try:
        page.lay_out_plan(
            [
                _item(small, "a", (60.0, 20.0)),
                _item(huge, "b", (1.0, 1.0)),
                _item(small, "c", (0.0, 0.0)),
            ],
            seed=1,
        )
        placed = [item for page_data in page.pages for item in page_data.placed]
        assert [item.target.id for item in placed] == ["a", "c"]
        assert page.omitted == [{"target": "b", "reason": "image does not fit"}]
        first = placed[0]
        assert first.word.width == 120 / page.display_scale
        assert first.word.height == 40 / page.display_scale
        assert page.show_page(0)

        started = time.monotonic()
        ui.run(
            lambda: 0 if time.monotonic() - started >= 0.25 else None,
            interval_ms=20,
            duration_s=None,
            on_duration=lambda: None,
        )
        x, y = page.to_global(first.point)
        if sys.platform in {"darwin", "win32"}:
            from lab.session.ownership import owner_at

            assert owner_at(x, y) == os.getpid()

        with mss.mss() as screen:
            pixel = screen.grab({"left": x - 2, "top": y - 2, "width": 5, "height": 5}).rgb
        center = 2 * (5 * 3) + 2 * 3
        red, green, blue = pixel[center : center + 3]
        assert red > 180 and green < 80 and blue < 80
    finally:
        page.close()
        ui.close()
