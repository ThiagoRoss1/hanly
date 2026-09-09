"""macOS screen-recording and Accessibility permission integration."""

from __future__ import annotations

import ctypes
import ctypes.util
import subprocess
from threading import RLock

from .permissions import (
    Permission,
    PermissionActionFailed,
    PermissionState,
    UnsupportedPermission,
)

#: The URLs that open one privacy pane directly, so the user never has to know
#: where in System Settings these controls live.
PRIVACY_PANES: dict[Permission, str] = {
    Permission.SCREEN_RECORDING: (
        "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"
    ),
    Permission.ACCESSIBILITY: (
        "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
    ),
}

#: Long enough for a busy launch service, short enough that a Control Center
#: action never looks hung.
_OPEN_TIMEOUT_SECONDS = 10.0

_lock = RLock()
_frameworks: dict[str, ctypes.CDLL] = {}


def _framework(name: str) -> ctypes.CDLL:
    """Load one system framework once, by the path the linker would use."""

    with _lock:
        loaded = _frameworks.get(name)
        if loaded is not None:
            return loaded

        path = ctypes.util.find_library(name)
        if path is None:
            raise RuntimeError(f"macOS did not provide the {name} framework")
        library = ctypes.cdll.LoadLibrary(path)
        _frameworks[name] = library
        return library


def _core_graphics() -> ctypes.CDLL:
    library = _framework("CoreGraphics")
    for symbol in ("CGPreflightScreenCaptureAccess", "CGRequestScreenCaptureAccess"):
        function = getattr(library, symbol)
        function.restype = ctypes.c_bool
        function.argtypes = []
    return library


def _application_services() -> ctypes.CDLL:
    library = _framework("ApplicationServices")
    library.AXIsProcessTrusted.restype = ctypes.c_bool
    library.AXIsProcessTrusted.argtypes = []
    library.AXIsProcessTrustedWithOptions.restype = ctypes.c_bool
    library.AXIsProcessTrustedWithOptions.argtypes = [ctypes.c_void_p]
    return library


def screen_recording_granted() -> bool:
    """Whether this process may capture other applications' windows."""

    return bool(_core_graphics().CGPreflightScreenCaptureAccess())


def request_screen_recording() -> bool:
    """Run Apple's screen-recording request and report the resulting access.

    The system prompt appears at most once per process for a given decision;
    afterwards this simply reports the standing answer, which is why the caller
    still sends the user to System Settings when it comes back false.
    """

    return bool(_core_graphics().CGRequestScreenCaptureAccess())


def accessibility_trusted() -> bool:
    """Whether this process is trusted to observe input globally."""

    return bool(_application_services().AXIsProcessTrusted())


def request_accessibility() -> bool:
    """Ask macOS to prompt for Accessibility, and report the resulting trust.

    The prompting form of the check is what registers Hanly in the
    Accessibility list, so the user finds an entry to switch on instead of an
    empty pane they are expected to drag an application into.
    """

    services = _application_services()
    options = _prompt_options()
    if options is None:
        return bool(services.AXIsProcessTrusted())

    core_foundation = _framework("CoreFoundation")
    try:
        return bool(services.AXIsProcessTrustedWithOptions(options))
    finally:
        core_foundation.CFRelease(options)


def _export_address(library: ctypes.CDLL, name: str) -> ctypes.c_void_p:
    """Return the address of an exported C object rather than its first word."""

    symbol = ctypes.c_byte.in_dll(library, name)
    return ctypes.c_void_p(ctypes.addressof(symbol))


def _prompt_options() -> ctypes.c_void_p | None:
    """Build the one-entry ``{kAXTrustedCheckOptionPrompt: true}`` dictionary.

    Returns ``None`` when the constants are missing, which leaves the caller
    with the silent check rather than a failed permission action.
    """

    core_foundation = _framework("CoreFoundation")
    services = _application_services()
    core_foundation.CFDictionaryCreate.restype = ctypes.c_void_p
    core_foundation.CFDictionaryCreate.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_long,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    core_foundation.CFRelease.restype = None
    core_foundation.CFRelease.argtypes = [ctypes.c_void_p]

    try:
        prompt_key = ctypes.c_void_p.in_dll(services, "kAXTrustedCheckOptionPrompt")
        true_value = ctypes.c_void_p.in_dll(core_foundation, "kCFBooleanTrue")
        key_callbacks = _export_address(core_foundation, "kCFTypeDictionaryKeyCallBacks")
        value_callbacks = _export_address(
            core_foundation, "kCFTypeDictionaryValueCallBacks"
        )
    except ValueError:
        return None

    keys = (ctypes.c_void_p * 1)(prompt_key)
    values = (ctypes.c_void_p * 1)(true_value)
    options = core_foundation.CFDictionaryCreate(
        None,
        keys,
        values,
        1,
        key_callbacks,
        value_callbacks,
    )
    return ctypes.c_void_p(options) if options else None


def open_privacy_settings(permission: Permission) -> None:
    """Open the System Settings pane that owns one privacy control."""

    pane = PRIVACY_PANES.get(permission)
    if pane is None:
        raise UnsupportedPermission(f"{permission.value} has no System Settings pane")
    try:
        subprocess.run(
            ["/usr/bin/open", pane],
            check=True,
            capture_output=True,
            timeout=_OPEN_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as error:
        # This reaches the Control Center, where a CalledProcessError repr would
        # tell the user nothing about what to do next.
        raise PermissionActionFailed(
            f"Hanly could not open the {permission.value.replace('_', ' ')} "
            "settings; open System Settings > Privacy & Security yourself."
        ) from error


class DarwinPermissionProbe:
    """Answer and request the two grants Hanly Desktop needs on macOS."""

    def state(self, permission: Permission) -> PermissionState:
        """Report the standing decision without prompting the user."""

        if permission is Permission.SCREEN_RECORDING:
            granted = screen_recording_granted()
        elif permission is Permission.ACCESSIBILITY:
            granted = accessibility_trusted()
        else:
            raise UnsupportedPermission(f"macOS does not gate {permission.value}")
        return PermissionState.GRANTED if granted else PermissionState.REQUIRED

    def request(self, permission: Permission) -> PermissionState:
        """Run Apple's own flow, then land the user on the right pane.

        A request that comes back granted is finished. Anything else opens the
        pane, because the system prompt only ever appears once and the user who
        clicks Grant a second time still has to end up somewhere useful.
        """

        if permission is Permission.SCREEN_RECORDING:
            granted = request_screen_recording()
        elif permission is Permission.ACCESSIBILITY:
            granted = request_accessibility()
        else:
            raise UnsupportedPermission(f"macOS does not gate {permission.value}")

        if granted:
            return PermissionState.GRANTED
        open_privacy_settings(permission)
        return PermissionState.REQUIRED


__all__ = [
    "PRIVACY_PANES",
    "DarwinPermissionProbe",
    "accessibility_trusted",
    "open_privacy_settings",
    "request_accessibility",
    "request_screen_recording",
    "screen_recording_granted",
]
