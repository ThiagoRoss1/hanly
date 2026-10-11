"""Which process owns the window at a screen point, asked of the window server.

A tour keeps recognized text, so before each hover it proves the pixels under
the capture region are this process's own window (the tour page, or Hanly's
popup, which the shell draws). Anything else means another application is on
top, and the hover is skipped rather than read.
"""

from __future__ import annotations

import sys

#: The Dock's window level; everything at or above it is system chrome.
_SYSTEM_CHROME_LAYER = 20


def owner_at(x: float, y: float) -> int | None:
    """PID owning the topmost visible window at a global point; ``None`` if unknown."""

    if sys.platform == "darwin":
        return _darwin_owner(x, y)
    if sys.platform == "win32":
        return _windows_owner(x, y)
    return None


def _darwin_owner(x: float, y: float) -> int | None:
    try:
        import Quartz
    except ImportError:
        return None
    windows = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
        Quartz.kCGNullWindowID,
    )
    # Front to back. Application windows sit on layers 0 (normal) to 8 (modal);
    # the Dock (20), status items and the screenshot service (24+) keep
    # invisible full-screen windows above everything, which cover nothing.
    for window in windows or ():
        if window.get("kCGWindowAlpha", 1) == 0:
            continue
        layer = window.get("kCGWindowLayer", 0)
        if not 0 <= layer < _SYSTEM_CHROME_LAYER:
            continue
        bounds = window.get("kCGWindowBounds") or {}
        left, top = bounds.get("X", 0), bounds.get("Y", 0)
        if left <= x < left + bounds.get("Width", 0) and top <= y < top + bounds.get("Height", 0):
            return int(window.get("kCGWindowOwnerPID", -1))
    return None


def _windows_owner(x: float, y: float) -> int | None:
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    handle = user32.WindowFromPoint(wintypes.POINT(int(x), int(y)))
    if not handle:
        return None
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(handle, ctypes.byref(pid))
    return int(pid.value) or None


__all__ = ["owner_at"]
