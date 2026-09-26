"""Small text in Hanly's own windows stays readable in both themes."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from hanly_app.qt_theme import PALETTES

ROOT = Path(__file__).parents[1]
CSS = ROOT / "packages/hanly-app/src/hanly_app/assets/control_center/control_center.css"

#: WCAG AA for text under 18 pt, which is all of the popup's secondary text.
SMALL_TEXT = 4.5


def _luminance(colour: str) -> float:
    value = colour.lstrip("#")
    channels = [int(value[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(first: str, second: str) -> float:
    lighter, darker = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


@pytest.mark.parametrize("mode", ["light", "dark"])
@pytest.mark.parametrize("ink", ["ink", "ink2", "ink3"])
@pytest.mark.parametrize("surface", ["bg", "foot"])
def test_popup_text_meets_small_text_contrast(mode: str, ink: str, surface: str) -> None:
    palette = PALETTES[mode]

    assert contrast(palette[ink], palette[surface]) >= SMALL_TEXT


@pytest.mark.parametrize("mode", ["light", "dark"])
@pytest.mark.parametrize("surface", ["bg", "foot"])
def test_the_three_inks_keep_their_order(mode: str, surface: str) -> None:
    palette = PALETTES[mode]
    ratios = [contrast(palette[ink], palette[surface]) for ink in ("ink", "ink2", "ink3")]

    assert ratios == sorted(ratios, reverse=True)
    assert ratios[1] - ratios[2] >= 0.5


def test_the_control_center_muted_text_is_the_popups_tertiary_ink() -> None:
    muted = re.findall(r"--text-muted: (#[0-9A-Fa-f]{6});", CSS.read_text(encoding="utf-8"))

    assert muted == [PALETTES["light"]["ink3"], PALETTES["dark"]["ink3"]]
