"""Keep Korean text fixed while varying crop origins to isolate ROI-grid churn.

Measure selection stability without an expected lemma that could conceal churn;
dictionary accuracy is a separate concern.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from hanly.contracts import PixelFormat, ROIImage

#: Where macOS keeps the Korean system face. Pillow resolves a bare name from
#: its own search path, which hides a wrong literal path behind a working
#: render, so the location is resolved explicitly here instead.
_FONT_CANDIDATES = (
    Path("/System/Library/Fonts/AppleSDGothicNeo.ttc"),
    Path("/System/Library/Fonts/Supplemental/AppleSDGothicNeo.ttc"),
    Path("/System/Library/Fonts/Supplemental/AppleGothic.ttf"),
)


def _korean_font() -> Path:
    for candidate in _FONT_CANDIDATES:
        if candidate.is_file():
            return candidate
    return _FONT_CANDIDATES[0]


KOREAN_FONT = _korean_font()

#: The production capture size, so measurements describe the shipped path.
ROI_WIDTH = 200
ROI_HEIGHT = 100


@dataclass(frozen=True)
class OffsetSample:
    """One crop of the same rendered line, taken at a known origin."""

    origin: int
    image: ROIImage
    #: Where the word's centre sits inside this crop, in ROI pixels.
    target_x: int
    target_y: int


def font_available() -> bool:
    return KOREAN_FONT.is_file()


@lru_cache(maxsize=8)
def _rendered(text: str, font_size: int, dark: bool) -> tuple[bytes, int, int, int]:
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.truetype(str(KOREAN_FONT), font_size)
    text_width = int(font.getlength(text))
    canvas_width = text_width + ROI_WIDTH * 4
    canvas = Image.new("RGB", (canvas_width, ROI_HEIGHT), "#0b0b0b" if dark else "white")
    left = ROI_WIDTH * 2
    ImageDraw.Draw(canvas).text(
        (left, ROI_HEIGHT // 2 - font_size // 2),
        text,
        font=font,
        fill="#e8e8e8" if dark else "black",
    )
    return canvas.tobytes(), canvas.width, left, text_width


def offset_samples(
    text: str,
    *,
    font_size: int = 20,
    dark: bool = True,
    step: int = 8,
    span: int = 96,
) -> tuple[OffsetSample, ...]:
    """Crops of one unchanged line, walking the origin across ``span`` pixels.

    ``step`` defaults below the production 32-pixel grid so a caller can see
    both what the grid quantizes away and what it does not.
    """

    from PIL import Image

    data, canvas_width, left, text_width = _rendered(text, font_size, dark)
    canvas = Image.frombytes("RGB", (canvas_width, ROI_HEIGHT), data)
    centre = left + text_width // 2

    samples: list[OffsetSample] = []
    for offset in range(-span // 2, span // 2 + 1, step):
        crop_left = centre - ROI_WIDTH // 2 + offset
        crop = canvas.crop((crop_left, 0, crop_left + ROI_WIDTH, ROI_HEIGHT))
        samples.append(
            OffsetSample(
                origin=crop_left,
                image=ROIImage(
                    ROI_WIDTH, ROI_HEIGHT, PixelFormat.RGB_888, crop.tobytes()
                ),
                target_x=ROI_WIDTH // 2 - offset,
                target_y=ROI_HEIGHT // 2,
            )
        )
    return tuple(samples)


__all__ = [
    "KOREAN_FONT",
    "ROI_HEIGHT",
    "ROI_WIDTH",
    "OffsetSample",
    "font_available",
    "offset_samples",
]
