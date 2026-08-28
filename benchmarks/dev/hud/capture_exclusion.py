"""Keep a window out of the pixels Hanly captures.

A window over the screen is composited into it, so the capture backend reads
its pixels back as content -- enough to turn a good recognition into none at
all. Windows can exclude a window at the compositor, keeping it visible to the
person and absent from captures.
"""

from __future__ import annotations

import sys

_WDA_EXCLUDEFROMCAPTURE = 0x00000011


def exclude_from_capture(window_handle: int) -> bool:
    """Hide one native window from screen capture, reporting whether it worked.

    The caller decides what to do when it fails, because the fallback is a
    drawing decision: an overlay that cannot be hidden must at least stop
    filling the area it is reporting on.
    """

    if sys.platform != "win32" or not window_handle:
        return False

    try:
        import ctypes

        set_affinity = ctypes.windll.user32.SetWindowDisplayAffinity
        set_affinity.restype = ctypes.c_bool
        return bool(set_affinity(ctypes.c_void_p(window_handle), _WDA_EXCLUDEFROMCAPTURE))
    except Exception:
        # A missing symbol, an unsupported build, and a rejected handle are all
        # the same answer to the caller: draw as if the overlay were visible.
        return False


__all__ = ["exclude_from_capture"]
