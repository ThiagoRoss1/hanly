"""The Windows title bar, in Hanly's colours rather than a plain white strip.

Desktop Window Manager draws the frame of a normal window, and it takes a dark
mode and, from Windows 11, an explicit caption colour. Both are attributes of
the one native window, so nothing here replaces the frame or its controls.
"""

from __future__ import annotations

import sys

#: ``DWMWA_USE_IMMERSIVE_DARK_MODE``, honoured from Windows 10 20H1.
_DWMWA_USE_IMMERSIVE_DARK_MODE = 20
#: ``DWMWA_CAPTION_COLOR`` and ``DWMWA_TEXT_COLOR``, Windows 11 only; an older
#: build refuses them and keeps its own caption, which is the dark mode above.
_DWMWA_CAPTION_COLOR = 35
_DWMWA_TEXT_COLOR = 36

_SWP_FRAME_ONLY = 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020

#: The Control Center's own surface and ink for each mode (its ``--surface``
#: and ``--text-primary`` tokens), so the frame and the page meet without a seam.
FRAME_COLOURS = {
    "light": ("#FAFAF9", "#202124"),
    "dark": ("#1C1D20", "#F2F2F3"),
}


def colorref(hex_colour: str) -> int:
    """``#RRGGBB`` as the ``0x00BBGGRR`` value Win32 calls a ``COLORREF``."""

    value = hex_colour.lstrip("#")
    red, green, blue = int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
    return red | (green << 8) | (blue << 16)


def apply_frame_theme(hwnd: int, mode: str) -> bool:
    """Match one window's frame to ``mode``; whether dark mode was accepted."""

    if sys.platform != "win32" or mode not in FRAME_COLOURS:
        return False

    import ctypes
    from ctypes import wintypes

    dwmapi = ctypes.windll.dwmapi
    handle = wintypes.HWND(hwnd)

    def set_attribute(attribute: int, value: int) -> bool:
        data = wintypes.DWORD(value)
        status = dwmapi.DwmSetWindowAttribute(
            handle, attribute, ctypes.byref(data), ctypes.sizeof(data)
        )
        return int(status) == 0

    caption, text = FRAME_COLOURS[mode]
    dark = set_attribute(_DWMWA_USE_IMMERSIVE_DARK_MODE, 1 if mode == "dark" else 0)
    set_attribute(_DWMWA_CAPTION_COLOR, colorref(caption))
    set_attribute(_DWMWA_TEXT_COLOR, colorref(text))
    # Windows 10 repaints a frame's mode only when the frame is recalculated.
    ctypes.windll.user32.SetWindowPos(handle, None, 0, 0, 0, 0, _SWP_FRAME_ONLY)
    return dark


def allow_parent_foreground() -> None:
    """From the process the user just clicked, let its parent take the front.

    Windows gives the foreground only to a process the user is interacting
    with. The Control Center has that right while its button is pressed; the
    shell, which shows the dialog that press asked for, does not until it is
    handed over.
    """

    if sys.platform != "win32":
        return
    try:
        import ctypes
        import os

        ctypes.windll.user32.AllowSetForegroundWindow(os.getppid())
    except Exception:
        pass


__all__ = ["FRAME_COLOURS", "allow_parent_foreground", "apply_frame_theme", "colorref"]
