"""Which process owns the window at a screen point, asked of the window server.

A tour keeps recognized text, so before each hover it verifies that the capture
region belongs to its fixture page or the native Hanly desktop. Anything else
means another application is on top, and the hover is skipped rather than read.
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
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsIconic.restype = wintypes.BOOL
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD

    owner: int | None = None

    def visit(handle: int, _parameter: int) -> bool:
        nonlocal owner
        if not user32.IsWindowVisible(handle) or user32.IsIconic(handle):
            return True
        bounds = wintypes.RECT()
        if not user32.GetWindowRect(handle, ctypes.byref(bounds)):
            return False
        if not (bounds.left <= x < bounds.right and bounds.top <= y < bounds.bottom):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(handle, ctypes.byref(pid))
        owner = int(pid.value) or None
        return False

    # WindowFromPoint performs input hit testing, which skips the Lab's opaque
    # WS_EX_TRANSPARENT fixture. Check visible windows in desktop stacking order.
    user32.EnumWindows(callback_type(visit), 0)
    return owner


__all__ = ["owner_at"]
