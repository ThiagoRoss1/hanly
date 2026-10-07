"""The stress page paints a controlled image pixel for pixel and points where it says."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lab.session.corpus import TourTarget
from lab.session.stress import StressItem
from tests.hanly_fixtures.capabilities import require_modules


def _item(image: Path, target: str, point: tuple[float, float]) -> StressItem:
    return StressItem(
        TourTarget(target, "corpus", "", 0, "", 0, None, None, refuse=True),
        "corpus",
        image=str(image),
        image_target=point,
        truth_target="no_korean",
        case=target,
    )


def test_corpus_images_are_placed_one_per_row_at_their_annotated_point(
    qt_application: Any, tmp_path: Path
) -> None:
    require_modules("PyQt6.QtWidgets")
    from PIL import Image

    # Imported here: the page module loads Qt, which this suite needs but no import may force.
    from lab.session.stress_page import StressPage

    small, huge = tmp_path / "small.png", tmp_path / "huge.png"
    Image.new("L", (120, 40), 200).save(small)
    Image.new("L", (40000, 40), 200).save(huge)
    page = StressPage()
    try:
        page.lay_out_plan(
            [
                _item(small, "a", (60.0, 20.0)),
                _item(huge, "b", (1.0, 1.0)),
                _item(small, "c", (0.0, 0.0)),
            ],
            seed=1,
        )
        ratio = page.devicePixelRatioF()
        placed = [p for page_ in page.pages for p in page_.placed]

        assert [p.target.id for p in placed] == ["a", "c"]
        assert page.omitted == [{"target": "b", "reason": "image does not fit"}]
        first, second = placed
        assert abs(first.point.x() - (first.word.left() + 60 / ratio)) <= 1
        assert abs(first.point.y() - (first.word.top() + 20 / ratio)) <= 1
        # Far enough apart that a capture around one never reaches the next.
        assert second.word.top() - first.word.bottom() >= 100
    finally:
        page.close()
