from __future__ import annotations

import pytest
from hanly_app.hotkeys import HotkeyError, canonical_hotkey, desktop_shortcut_defaults


@pytest.mark.parametrize(
    ("written", "canonical"),
    [
        ("SHIFT+CTRL+<space>", "<ctrl>+<shift>+<space>"),
        ("command+control+H", "<ctrl>+<cmd>+h"),
        ("option+shift+f9", "<shift>+<alt>+<f9>"),
        ("ctrl+PageDown", "<ctrl>+<page_down>"),
        (" alt + return ", "<alt>+<enter>"),
    ],
)
def test_bindings_have_one_modifier_first_spelling(written: str, canonical: str) -> None:
    assert canonical_hotkey(written) == canonical


@pytest.mark.parametrize(
    "written", ["", "   ", "ctrl++h", "ctrl+<h", "ctrl+<>", "ctrl+f-9", "ctrl+ctrl+h"]
)
def test_unusable_bindings_are_rejected(written: str) -> None:
    with pytest.raises(HotkeyError):
        canonical_hotkey(written)


@pytest.mark.parametrize("platform", ["win32", "linux", "darwin"])
def test_desktop_defaults_match_platform_without_function_keys_on_mac(platform: str) -> None:
    expected = (
        ("ctrl+cmd+h", "ctrl+cmd+p", "ctrl+cmd+r") if platform == "darwin"
        else ("ctrl+shift+space", "ctrl+shift+f9", "ctrl+shift+f10")
    )
    assert desktop_shortcut_defaults(platform) == expected
    assert len({canonical_hotkey(binding) for binding in expected}) == 3
