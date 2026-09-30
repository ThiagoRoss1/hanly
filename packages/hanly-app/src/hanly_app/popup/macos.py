"""Keep the macOS popup panel visible while Hanly is inactive.

Qt tool windows are ``NSPanel`` objects that normally hide on deactivation.
Qt's always-show attribute steals focus here, so this adapter clears the native
property directly without adding an Objective-C dependency.
"""

from __future__ import annotations

import ctypes
import ctypes.util
from threading import RLock

_lock = RLock()
_bridge: _ObjectiveCBridge | None = None


class _ObjectiveCBridge:
    """The two Objective-C message sends this module needs, typed once.

    ``objc_msgSend`` is variadic in C and must be called through a prototype
    matching the selector, so each selector gets its own function object rather
    than one shared pointer whose signature is rewritten per call.
    """

    def __init__(self, runtime: ctypes.CDLL) -> None:
        runtime.sel_registerName.restype = ctypes.c_void_p
        runtime.sel_registerName.argtypes = [ctypes.c_char_p]
        address = ctypes.cast(runtime.objc_msgSend, ctypes.c_void_p).value
        if address is None:
            raise RuntimeError("the Objective-C runtime did not expose objc_msgSend")

        self._window_selector = runtime.sel_registerName(b"window")
        self._set_hides_selector = runtime.sel_registerName(b"setHidesOnDeactivate:")
        self._hides_selector = runtime.sel_registerName(b"hidesOnDeactivate")
        self._send_object = ctypes.CFUNCTYPE(
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
        )(address)
        self._send_bool = ctypes.CFUNCTYPE(
            ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p
        )(address)
        self._send_set_bool = ctypes.CFUNCTYPE(
            None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool
        )(address)

    def window_of(self, view: int) -> int | None:
        """Return the ``NSWindow`` hosting a view, or ``None`` if it has none."""

        window = self._send_object(ctypes.c_void_p(view), self._window_selector)
        return window or None

    def set_hides_on_deactivate(self, window: int, hides: bool) -> None:
        self._send_set_bool(ctypes.c_void_p(window), self._set_hides_selector, hides)

    def hides_on_deactivate(self, window: int) -> bool:
        return bool(self._send_bool(ctypes.c_void_p(window), self._hides_selector))


def _objective_c() -> _ObjectiveCBridge:
    """Load the Objective-C runtime once; it is present in any Cocoa process."""

    global _bridge
    with _lock:
        if _bridge is not None:
            return _bridge

        path = ctypes.util.find_library("objc")
        if path is None:
            raise RuntimeError("macOS did not provide the Objective-C runtime")
        _bridge = _ObjectiveCBridge(ctypes.cdll.LoadLibrary(path))
        return _bridge


def keep_visible_when_inactive(view_pointer: int) -> bool:
    """Let the popup panel behind ``view_pointer`` outlive Hanly losing focus.

    ``view_pointer`` is what ``QWidget.winId()`` returns on macOS: the widget's
    ``NSView``. Returns whether the panel was reached, so a caller that ran
    before the native window existed can tell.
    """

    if view_pointer <= 0:
        return False

    bridge = _objective_c()
    window = bridge.window_of(view_pointer)
    if window is None:
        return False
    bridge.set_hides_on_deactivate(window, False)
    return True


def hides_when_inactive(view_pointer: int) -> bool | None:
    """Report the panel's current setting, for tests and diagnostics."""

    if view_pointer <= 0:
        return None

    bridge = _objective_c()
    window = bridge.window_of(view_pointer)
    return None if window is None else bridge.hides_on_deactivate(window)


__all__ = ["hides_when_inactive", "keep_visible_when_inactive"]
