"""The shortcut vocabulary the service shares with the native host.

The native root registers global shortcuts and reports each combination's
press and release; this module names the actions they stand for and keeps one
canonical spelling for persisted bindings. Nothing here touches the keyboard.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from typing import TypeAlias


class HotkeyAction(str, Enum):
    """Actions that a desktop shortcut may request from application orchestration."""

    #: One capture and lookup at the cursor. The desktop gives it no shortcut;
    #: :meth:`ManualLookupRuntime.lookup_at_cursor` keeps it for a client.
    LOOKUP = "lookup"
    #: Held, not tapped: hover follows the chord and stops when it is let go.
    PUSH_TO_HOVER = "push_to_hover"
    #: Mute and continue automatic hover, without touching capture or residency.
    TOGGLE_HOVER = "toggle_hover"
    #: Start and stop the capture session itself, which is what releases the
    #: lookup providers.
    TOGGLE_CAPTURE = "toggle_capture"


class HotkeyEdge(str, Enum):
    """Which half of a physical key press this delivery is.

    A hold needs both; a toggle acts on ``DOWN`` and ignores ``UP``.
    """

    DOWN = "down"
    UP = "up"


class HotkeyError(ValueError):
    """Raised for a binding that is not a usable key combination."""


HotkeyHandler: TypeAlias = Callable[[HotkeyAction, HotkeyEdge], None]


def desktop_shortcut_defaults(platform: str) -> tuple[str, str, str]:
    """Return hold, hover toggle and capture toggle defaults for the host."""

    if platform == "darwin":
        return "ctrl+cmd+h", "ctrl+cmd+p", "ctrl+cmd+r"
    return "ctrl+shift+space", "ctrl+shift+f9", "ctrl+shift+f10"


_MODIFIER_ALIASES = {
    "ctrl": "<ctrl>",
    "control": "<ctrl>",
    "shift": "<shift>",
    "alt": "<alt>",
    "option": "<alt>",
    "cmd": "<cmd>",
    "command": "<cmd>",
    "win": "<cmd>",
    "windows": "<cmd>",
    "super": "<cmd>",
}

_SPECIAL_KEY_ALIASES = {
    "space": "<space>",
    "enter": "<enter>",
    "return": "<enter>",
    "esc": "<esc>",
    "escape": "<esc>",
    "tab": "<tab>",
    "backspace": "<backspace>",
    "delete": "<delete>",
    "insert": "<insert>",
    "home": "<home>",
    "end": "<end>",
    "pageup": "<page_up>",
    "pagedown": "<page_down>",
    "up": "<up>",
    "down": "<down>",
    "left": "<left>",
    "right": "<right>",
}


#: Where each modifier sits in the canonical spelling; anything else follows.
_MODIFIER_ORDER = {"<ctrl>": 0, "<shift>": 1, "<alt>": 2, "<cmd>": 3}


def _canonical_sort_key(part: str) -> tuple[int, str]:
    return (_MODIFIER_ORDER.get(part, len(_MODIFIER_ORDER)), part)


def _canonical_key_part(part: str) -> str:
    token = part.strip().lower()
    if not token:
        raise HotkeyError("hotkey combinations cannot contain empty key parts")

    if token.startswith("<") or token.endswith(">"):
        if not (token.startswith("<") and token.endswith(">")):
            raise HotkeyError(f"invalid hotkey key part: {part!r}")
        token = token[1:-1].strip()
        if not token:
            raise HotkeyError(f"invalid hotkey key part: {part!r}")

    if token in _MODIFIER_ALIASES:
        return _MODIFIER_ALIASES[token]
    if token in _SPECIAL_KEY_ALIASES:
        return _SPECIAL_KEY_ALIASES[token]
    if len(token) == 1:
        return token

    # Named keys are spelled in angle brackets. Accept only identifiers there;
    # punctuation cannot form a valid binding.
    if not token.replace("_", "").isalnum():
        raise HotkeyError(f"invalid hotkey key part: {part!r}")
    return f"<{token}>"


def canonical_hotkey(value: str) -> str:
    """Normalize a human-written combination, raising on anything unusable.

    Exposed so callers that persist a hotkey can reject a spelling before the
    native host is asked to register it.
    """

    if not isinstance(value, str) or not value.strip():
        raise HotkeyError("hotkey bindings must be non-empty strings")

    parts = [_canonical_key_part(part) for part in value.split("+")]
    if len(set(parts)) != len(parts):
        raise HotkeyError(f"hotkey binding contains a duplicate key: {value!r}")

    # A combination is unordered. Canonical sorting catches the same binding
    # written as ``shift+ctrl+k`` and ``ctrl+shift+k`` while keeping the usual
    # modifier-first spelling expected by pynput and configuration files.
    return "+".join(sorted(parts, key=_canonical_sort_key))


__all__ = [
    "HotkeyAction",
    "HotkeyEdge",
    "HotkeyError",
    "HotkeyHandler",
    "canonical_hotkey",
    "desktop_shortcut_defaults",
]
