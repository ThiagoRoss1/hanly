"""The two real production failures this Wave 3 change exists to correct.

The inputs are private screen captures under the gitignored artifact root, so
they cannot be committed. When they are absent this skips rather than pretending
to have run; when they are present it is the strongest evidence available that
the correction still holds, because the pixels are the original failure.

`benchmarks/dev` owns the tooling that produced them:
`live-hover`, freeze, then export.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from hanly import PixelFormat, Point, ROIImage
from hanly.vision_provider import VisionConfig, VisionProvider
from hanly.word_resolver import WordResolver

RUN = Path("artifacts/benchmarks/runs/ef2c1ffc-3746-4b94-a40a-680b7e9e29c3")

#: The word under the recorded cursor in each exported capture. `frozen-8` is
#: the control: it succeeded before the change and must keep succeeding.
CASES = {
    "frozen-8": "깨뜨렸습니다",
    "frozen-9": "초대받았어요",
    "frozen-10": "떨어뜨렸어요",
}
REGRESSED = ("frozen-9", "frozen-10")


def _load(name: str) -> tuple[ROIImage, Point]:
    directory = RUN / name
    if not (directory / "input.png").is_file():
        pytest.skip(f"{directory} is not present on this machine")
    pytest.importorskip("PIL")
    from PIL import Image

    diagnostic = json.loads((directory / "diagnostic.json").read_text(encoding="utf-8"))
    target = diagnostic["capture"]["plan"]["target"]
    with Image.open(directory / "input.png") as opened:
        rgb = opened.convert("RGB")
    roi = ROIImage(rgb.width, rgb.height, PixelFormat.RGB_888, rgb.tobytes())
    return roi, Point(target["x"], target["y"])


def _resolved(roi: ROIImage, target: Point, scale: int) -> str | None:
    results = VisionProvider(VisionConfig(input_scale=scale)).recognize(roi)
    resolution = WordResolver.resolve_target_detail(list(results), target)
    return None if resolution is None else resolution.text


@pytest.mark.parametrize("name", REGRESSED)
def test_the_real_failure_is_corrected(name: str) -> None:
    roi, target = _load(name)

    assert _resolved(roi, target, scale=2) == CASES[name]


@pytest.mark.parametrize("name", REGRESSED)
def test_the_real_failure_still_reproduces_without_the_correction(name: str) -> None:
    """Guards the evidence, not the fix: if this stops failing at 1x, the
    captures no longer reproduce the defect and the fix needs re-justifying."""

    roi, target = _load(name)

    assert _resolved(roi, target, scale=1) != CASES[name]


def test_the_control_capture_is_unaffected() -> None:
    """It succeeded before the change; the change must not have moved it."""

    roi, target = _load("frozen-8")

    assert _resolved(roi, target, scale=1) == CASES["frozen-8"]
    assert _resolved(roi, target, scale=2) == CASES["frozen-8"]
