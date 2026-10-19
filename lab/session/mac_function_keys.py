"""Synthesize macOS function-primary-key edges with their Fn interpretation."""

from __future__ import annotations

import importlib
import re
import sys
from collections.abc import Callable, Sequence
from typing import Any, Protocol

_FUNCTION_KEY = re.compile(r"f([1-9]|1[0-9]|20)\Z")
_MODIFIER_FLAGS = {
    "ctrl": "kCGEventFlagMaskControl",
    "control": "kCGEventFlagMaskControl",
    "shift": "kCGEventFlagMaskShift",
    "alt": "kCGEventFlagMaskAlternate",
    "option": "kCGEventFlagMaskAlternate",
    "cmd": "kCGEventFlagMaskCommand",
    "command": "kCGEventFlagMaskCommand",
}


class QuartzAPI(Protocol):
    """The public CoreGraphics calls needed for one synthetic keyboard edge."""

    kCGEventFlagMaskSecondaryFn: int
    kCGHIDEventTap: int

    def CGEventCreateKeyboardEvent(self, source: None, virtual_key: int, key_down: bool) -> Any: ...

    def CGEventSetFlags(self, event: Any, flags: int) -> None: ...

    def CGEventPost(self, tap: int, event: Any) -> None: ...


def dispatch_key_edge(
    keyboard: Any,
    key: Any,
    key_name: str,
    *,
    pressed: bool,
    modifier_names: Sequence[str],
    quartz_loader: Callable[[], QuartzAPI] | None = None,
) -> None:
    """Use public Quartz only for F1–F20 on macOS; keep other input on pynput."""

    if sys.platform != "darwin" or _FUNCTION_KEY.fullmatch(key_name) is None:
        method = keyboard.press if pressed else keyboard.release
        method(key)
        return

    quartz = (quartz_loader or _load_quartz)()
    virtual_key = _virtual_keycode(key)
    flags = quartz.kCGEventFlagMaskSecondaryFn
    for modifier in modifier_names:
        flag = _MODIFIER_FLAGS.get(modifier)
        if flag is not None:
            flags |= getattr(quartz, flag)

    event = quartz.CGEventCreateKeyboardEvent(None, virtual_key, pressed)
    if event is None:
        raise RuntimeError("Lab could not create a macOS function-key event")
    quartz.CGEventSetFlags(event, flags)
    quartz.CGEventPost(quartz.kCGHIDEventTap, event)


def _virtual_keycode(key: Any) -> int:
    value = getattr(key, "value", None)
    virtual_key = getattr(value, "vk", None)
    if isinstance(virtual_key, bool) or not isinstance(virtual_key, int):
        raise RuntimeError("Lab cannot read the public pynput function-key virtual code")
    return virtual_key


def _load_quartz() -> QuartzAPI:
    try:
        return importlib.import_module("Quartz")
    except ImportError as error:
        raise RuntimeError(
            "Lab function keys on macOS need the hanly-app PyObjC runtime"
        ) from error


__all__ = ["QuartzAPI", "dispatch_key_edge"]
