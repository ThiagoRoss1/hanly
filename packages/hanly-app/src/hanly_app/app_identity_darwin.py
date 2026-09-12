"""What macOS thinks this process is, for the windows Hanly does not own.

Every process that creates a ``QApplication`` becomes a Regular application:
one Dock tile, one menu bar, one entry in the app switcher. The shell is that
application. The Control Center lives in a child process and creates a
``QApplication`` of its own, so without this it became a second, identical
Hanly beside the real one.

An Accessory application has no Dock tile and no menu bar, and its windows
still appear and still take the keyboard, which is exactly what a panel owned
by another process needs. It has to be activated explicitly, because showing a
window no longer brings an application forward on its own.
"""

from __future__ import annotations

import ctypes
import ctypes.util
from threading import RLock

#: ``NSApplicationActivationPolicyAccessory``: visible windows, no Dock tile.
ACCESSORY_POLICY = 1

_lock = RLock()
_bridge: _ApplicationBridge | None = None


class _ApplicationBridge:
    """The four Objective-C message sends this module needs, typed once.

    ``objc_msgSend`` is variadic in C and must be called through a prototype
    matching the selector, so each shape gets its own function object rather
    than one shared pointer whose signature is rewritten per call.
    """

    def __init__(self, runtime: ctypes.CDLL) -> None:
        runtime.sel_registerName.restype = ctypes.c_void_p
        runtime.sel_registerName.argtypes = [ctypes.c_char_p]
        runtime.objc_getClass.restype = ctypes.c_void_p
        runtime.objc_getClass.argtypes = [ctypes.c_char_p]
        address = ctypes.cast(runtime.objc_msgSend, ctypes.c_void_p).value
        if address is None:
            raise RuntimeError("the Objective-C runtime did not expose objc_msgSend")

        self._runtime = runtime
        self._shared_selector = runtime.sel_registerName(b"sharedApplication")
        self._policy_selector = runtime.sel_registerName(b"activationPolicy")
        self._set_policy_selector = runtime.sel_registerName(b"setActivationPolicy:")
        self._activate_selector = runtime.sel_registerName(b"activateIgnoringOtherApps:")
        self._send_object = ctypes.CFUNCTYPE(
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
        )(address)
        self._send_long = ctypes.CFUNCTYPE(
            ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p
        )(address)
        self._send_set_long = ctypes.CFUNCTYPE(
            ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long
        )(address)
        self._send_set_bool = ctypes.CFUNCTYPE(
            None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool
        )(address)

    def application(self) -> int:
        cls = self._runtime.objc_getClass(b"NSApplication")
        shared = self._send_object(ctypes.c_void_p(cls), self._shared_selector)
        if not shared:
            raise RuntimeError("macOS did not provide a shared NSApplication")
        return int(shared)

    def policy(self, application: int) -> int:
        return int(self._send_long(ctypes.c_void_p(application), self._policy_selector))

    def set_policy(self, application: int, policy: int) -> bool:
        return bool(
            self._send_set_long(
                ctypes.c_void_p(application), self._set_policy_selector, policy
            )
        )

    def activate(self, application: int) -> None:
        self._send_set_bool(
            ctypes.c_void_p(application), self._activate_selector, True
        )


def _objective_c() -> _ApplicationBridge:
    """Load the Objective-C runtime once; it is present in any Cocoa process."""

    global _bridge
    with _lock:
        if _bridge is not None:
            return _bridge

        path = ctypes.util.find_library("objc")
        if path is None:
            raise RuntimeError("macOS did not provide the Objective-C runtime")
        _bridge = _ApplicationBridge(ctypes.cdll.LoadLibrary(path))
        return _bridge


def run_as_accessory_application() -> bool:
    """Stop this process from being a second user-facing Hanly.

    Returns whether the policy is now Accessory. Must run before any window
    exists: a Dock tile that has already appeared does not go away.
    """

    bridge = _objective_c()
    application = bridge.application()
    if bridge.policy(application) == ACCESSORY_POLICY:
        return True
    return bridge.set_policy(application, ACCESSORY_POLICY)


def activate_application() -> None:
    """Bring this process forward, which showing a window no longer does.

    An Accessory application is not activated by its own windows appearing, so
    the shell asking for the Control Center has to say so explicitly.
    """

    bridge = _objective_c()
    bridge.activate(bridge.application())


def activation_policy() -> int | None:
    """Report the current policy, for tests and diagnostics."""

    try:
        bridge = _objective_c()
    except RuntimeError:
        return None
    return bridge.policy(bridge.application())


__all__ = [
    "ACCESSORY_POLICY",
    "activate_application",
    "activation_policy",
    "run_as_accessory_application",
]
