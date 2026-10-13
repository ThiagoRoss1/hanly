"""The React Control Center and popup text stays readable in both themes."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
CONTROL_CENTER_CSS = ROOT / "apps/desktop/src/styles/controlCenter.css"
POPUP_CSS = ROOT / "apps/desktop/src/styles/popup.css"
SMALL_TEXT = 4.5


def _luminance(colour: str) -> float:
    value = colour.lstrip("#")
    channels = [int(value[index : index + 2], 16) / 255 for index in (0, 2, 4)]
    linear = [
        channel / 12.92
        if channel <= 0.04045
        else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(first: str, second: str) -> float:
    lighter, darker = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _theme_tokens() -> dict[str, dict[str, str]]:
    stylesheet = CONTROL_CENTER_CSS.read_text(encoding="utf-8")
    light_block = re.search(r":root\s*\{(?P<body>[^{}]+)\}", stylesheet)
    dark_block = re.search(r'\[data-mode="dark"\]\s*\{(?P<body>[^{}]+)\}', stylesheet)
    assert light_block is not None and dark_block is not None

    def parse(block: str) -> dict[str, str]:
        return dict(re.findall(r"--([\w-]+):\s*(#[0-9A-Fa-f]{6});", block))

    light = parse(light_block.group("body"))
    dark = {**light, **parse(dark_block.group("body"))}
    return {"light": light, "dark": dark}


@pytest.mark.parametrize("mode", ["light", "dark"])
@pytest.mark.parametrize("ink", ["text-primary", "text-secondary", "text-muted"])
@pytest.mark.parametrize("surface", ["surface", "surface-raised", "surface-subtle"])
def test_react_text_tokens_meet_small_text_contrast(mode: str, ink: str, surface: str) -> None:
    tokens = _theme_tokens()[mode]

    assert contrast(tokens[ink], tokens[surface]) >= SMALL_TEXT


def test_popup_uses_the_shared_react_tokens_for_its_text_and_footer() -> None:
    center = CONTROL_CENTER_CSS.read_text(encoding="utf-8")
    popup = POPUP_CSS.read_text(encoding="utf-8")

    for role in ("text-primary", "text-secondary", "text-muted"):
        assert f"var(--{role})" in center
        assert f"var(--{role})" in popup
    assert "background: var(--surface-subtle)" in popup
