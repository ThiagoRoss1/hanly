"""Read the text under the pointer through the macOS accessibility API.

The four calls this needs are bound through ``ctypes`` rather than pyobjc, for
the same reason :mod:`hanly_app.popup_darwin` does it: the desktop does not
carry an Objective-C dependency.

Accessibility answers in the screen's own coordinate space with the origin at
the top left, which is what the capture path already uses, so the rectangle it
reports can be compared against the pointer directly. What it does *not*
guarantee is that the answer belongs to the pointer at all -- a control may
return its nearest range -- so everything this module reads is evidence for
:mod:`hanly_app.text_acquisition` to accept or refuse.
"""

from __future__ import annotations

import ctypes
import ctypes.util
from threading import RLock

from hanly import BoundingBox, Point

from .text_acquisition import DirectText

_lock = RLock()
_bridge: _AccessibilityBridge | None = None

#: ``AXError`` success.
_AX_SUCCESS = 0
#: ``AXValueType`` members this module reads or writes.
_AX_VALUE_CGPOINT = 1
_AX_VALUE_CGRECT = 3
_AX_VALUE_CFRANGE = 4
#: ``kCFNumberLongType``.
_CF_NUMBER_LONG = 10

#: Roles whose contents are a secret the user typed.
_SECURE_ROLES = frozenset({"AXSecureTextField"})


class _CFRange(ctypes.Structure):
    _fields_ = [("location", ctypes.c_long), ("length", ctypes.c_long)]


class _CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class _CGSize(ctypes.Structure):
    _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]


class _CGRect(ctypes.Structure):
    _fields_ = [("origin", _CGPoint), ("size", _CGSize)]


class _AccessibilityBridge:
    """The accessibility and CoreFoundation entry points, typed once."""

    def __init__(self, services: ctypes.CDLL, core: ctypes.CDLL) -> None:
        self._services = services
        self._core = core

        services.AXUIElementCreateSystemWide.restype = ctypes.c_void_p
        services.AXUIElementCreateSystemWide.argtypes = []
        services.AXUIElementCopyElementAtPosition.restype = ctypes.c_int
        services.AXUIElementCopyElementAtPosition.argtypes = [
            ctypes.c_void_p, ctypes.c_float, ctypes.c_float,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        services.AXUIElementCopyAttributeValue.restype = ctypes.c_int
        services.AXUIElementCopyAttributeValue.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
        ]
        services.AXUIElementCopyParameterizedAttributeValue.restype = ctypes.c_int
        services.AXUIElementCopyParameterizedAttributeValue.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        services.AXValueCreate.restype = ctypes.c_void_p
        services.AXValueCreate.argtypes = [ctypes.c_int, ctypes.c_void_p]
        services.AXValueGetValue.restype = ctypes.c_bool
        services.AXValueGetValue.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p,
        ]

        core.CFNumberCreate.restype = ctypes.c_void_p
        core.CFNumberCreate.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p,
        ]
        core.CFNumberGetValue.restype = ctypes.c_bool
        core.CFNumberGetValue.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p,
        ]
        core.CFStringCreateWithCString.restype = ctypes.c_void_p
        core.CFStringCreateWithCString.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32,
        ]
        core.CFStringGetLength.restype = ctypes.c_long
        core.CFStringGetLength.argtypes = [ctypes.c_void_p]
        core.CFStringGetCString.restype = ctypes.c_bool
        core.CFStringGetCString.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32,
        ]
        core.CFRelease.restype = None
        core.CFRelease.argtypes = [ctypes.c_void_p]
        core.CFGetTypeID.restype = ctypes.c_ulong
        core.CFGetTypeID.argtypes = [ctypes.c_void_p]
        core.CFStringGetTypeID.restype = ctypes.c_ulong
        core.CFStringGetTypeID.argtypes = []

        self._strings: dict[str, ctypes.c_void_p] = {}

    # --- CoreFoundation helpers ------------------------------------------

    def string(self, value: str) -> ctypes.c_void_p:
        """A retained ``CFString`` for an attribute name, created once."""

        cached = self._strings.get(value)
        if cached is None:
            cached = ctypes.c_void_p(
                self._core.CFStringCreateWithCString(
                    None, value.encode("utf-8"), 0x08000100
                )
            )
            self._strings[value] = cached
        return cached

    def text_of(self, reference: ctypes.c_void_p) -> str | None:
        if not reference or self._core.CFGetTypeID(reference) != self._core.CFStringGetTypeID():
            return None
        length = self._core.CFStringGetLength(reference)
        # Worst case for UTF-8 is four bytes per UTF-16 unit, plus a terminator.
        buffer = ctypes.create_string_buffer(length * 4 + 1)
        if not self._core.CFStringGetCString(
            reference, buffer, len(buffer), 0x08000100
        ):
            return None
        return buffer.value.decode("utf-8", errors="replace")

    def number(self, value: int) -> ctypes.c_void_p:
        """A ``CFNumber``, which is what the line attributes take."""

        payload = ctypes.c_long(value)
        return ctypes.c_void_p(
            self._core.CFNumberCreate(None, _CF_NUMBER_LONG, ctypes.byref(payload))
        )

    def number_value(self, reference: ctypes.c_void_p) -> int | None:
        payload = ctypes.c_long()
        if not self._core.CFNumberGetValue(
            reference, _CF_NUMBER_LONG, ctypes.byref(payload)
        ):
            return None
        return int(payload.value)

    def release(self, reference: ctypes.c_void_p | None) -> None:
        if reference:
            self._core.CFRelease(reference)

    # --- accessibility ----------------------------------------------------

    def element_at(self, x: float, y: float) -> ctypes.c_void_p | None:
        system = ctypes.c_void_p(self._services.AXUIElementCreateSystemWide())
        if not system:
            return None
        try:
            element = ctypes.c_void_p()
            status = self._services.AXUIElementCopyElementAtPosition(
                system, ctypes.c_float(x), ctypes.c_float(y), ctypes.byref(element)
            )
        finally:
            self.release(system)
        return element if status == _AX_SUCCESS and element else None

    def attribute(
        self, element: ctypes.c_void_p, name: str
    ) -> ctypes.c_void_p | None:
        value = ctypes.c_void_p()
        status = self._services.AXUIElementCopyAttributeValue(
            element, self.string(name), ctypes.byref(value)
        )
        return value if status == _AX_SUCCESS and value else None

    def parameterized(
        self, element: ctypes.c_void_p, name: str, parameter: ctypes.c_void_p
    ) -> ctypes.c_void_p | None:
        value = ctypes.c_void_p()
        status = self._services.AXUIElementCopyParameterizedAttributeValue(
            element, self.string(name), parameter, ctypes.byref(value)
        )
        return value if status == _AX_SUCCESS and value else None

    def value_create(self, kind: int, payload: ctypes.Structure) -> ctypes.c_void_p:
        return ctypes.c_void_p(
            self._services.AXValueCreate(kind, ctypes.byref(payload))
        )

    def value_read(
        self, reference: ctypes.c_void_p, kind: int, target: ctypes.Structure
    ) -> bool:
        return bool(
            self._services.AXValueGetValue(reference, kind, ctypes.byref(target))
        )


def _bridge_once() -> _AccessibilityBridge | None:
    global _bridge
    with _lock:
        if _bridge is not None:
            return _bridge
        services_path = ctypes.util.find_library("ApplicationServices")
        core_path = ctypes.util.find_library("CoreFoundation")
        if services_path is None or core_path is None:
            return None
        try:
            _bridge = _AccessibilityBridge(
                ctypes.CDLL(services_path), ctypes.CDLL(core_path)
            )
        except (OSError, AttributeError):
            return None
        return _bridge


class AccessibilityTextProvider:
    """Read the character range under a screen point, when a control offers one."""

    def read_at(self, point: Point, *, timeout_ms: int) -> DirectText | None:
        """Return what accessibility says is at ``point``.

        ``timeout_ms`` is not enforced here. The accessibility calls are
        synchronous and the system applies its own per-call deadline, so the
        coordinator measures the elapsed time and discards a late answer
        instead of this module pretending to interrupt one.
        """

        del timeout_ms
        bridge = _bridge_once()
        if bridge is None:
            return None

        element = bridge.element_at(float(point.x), float(point.y))
        if element is None:
            return None
        try:
            return self._read_element(bridge, element, point)
        finally:
            bridge.release(element)

    def _read_element(
        self,
        bridge: _AccessibilityBridge,
        element: ctypes.c_void_p,
        point: Point,
    ) -> DirectText | None:
        role = self._string_attribute(bridge, element, "AXRole")
        if role in _SECURE_ROLES:
            # Reported without its contents, so the caller can refuse it by
            # reason rather than by an empty answer it cannot explain.
            return DirectText(text="", cursor_index=0, secure=True, role=role)

        index = self._index_at(bridge, element, point)
        if index is None:
            return None
        line = self._line_range(bridge, element, index)
        if line is None:
            return None
        start, length = line
        text = self._string_for_range(bridge, element, start, length)
        if text is None:
            return None
        bounds = self._bounds_for_range(bridge, element, start, length)
        return DirectText(
            text=text,
            cursor_index=max(0, index - start),
            bounds=bounds,
            role=role,
        )

    @staticmethod
    def _string_attribute(
        bridge: _AccessibilityBridge, element: ctypes.c_void_p, name: str
    ) -> str | None:
        value = bridge.attribute(element, name)
        if value is None:
            return None
        try:
            return bridge.text_of(value)
        finally:
            bridge.release(value)

    @staticmethod
    def _index_at(
        bridge: _AccessibilityBridge, element: ctypes.c_void_p, point: Point
    ) -> int | None:
        position = bridge.value_create(
            _AX_VALUE_CGPOINT, _CGPoint(float(point.x), float(point.y))
        )
        try:
            answer = bridge.parameterized(element, "AXRangeForPosition", position)
        finally:
            bridge.release(position)
        if answer is None:
            return None
        try:
            found = _CFRange()
            if not bridge.value_read(answer, _AX_VALUE_CFRANGE, found):
                return None
            return int(found.location)
        finally:
            bridge.release(answer)

    @staticmethod
    def _line_range(
        bridge: _AccessibilityBridge, element: ctypes.c_void_p, index: int
    ) -> tuple[int, int] | None:
        """The whole line holding ``index``, so a word is not cut in half.

        Both line attributes take a plain number rather than a range, which is
        the one place this API's parameter types are not interchangeable.
        """

        wanted = bridge.number(index)
        try:
            line = bridge.parameterized(element, "AXLineForIndex", wanted)
        finally:
            bridge.release(wanted)
        if line is None:
            return None
        try:
            line_number = bridge.number_value(line)
        finally:
            bridge.release(line)
        if line_number is None:
            return None

        marker = bridge.number(line_number)
        try:
            answer = bridge.parameterized(element, "AXRangeForLine", marker)
        finally:
            bridge.release(marker)
        if answer is None:
            return None
        try:
            found = _CFRange()
            if not bridge.value_read(answer, _AX_VALUE_CFRANGE, found):
                return None
            if found.length <= 0:
                return None
            return int(found.location), int(found.length)
        finally:
            bridge.release(answer)

    @staticmethod
    def _string_for_range(
        bridge: _AccessibilityBridge,
        element: ctypes.c_void_p,
        start: int,
        length: int,
    ) -> str | None:
        wanted = bridge.value_create(_AX_VALUE_CFRANGE, _CFRange(start, length))
        try:
            answer = bridge.parameterized(element, "AXStringForRange", wanted)
        finally:
            bridge.release(wanted)
        if answer is None:
            return None
        try:
            return bridge.text_of(answer)
        finally:
            bridge.release(answer)

    @staticmethod
    def _bounds_for_range(
        bridge: _AccessibilityBridge,
        element: ctypes.c_void_p,
        start: int,
        length: int,
    ) -> BoundingBox | None:
        wanted = bridge.value_create(_AX_VALUE_CFRANGE, _CFRange(start, length))
        try:
            answer = bridge.parameterized(element, "AXBoundsForRange", wanted)
        finally:
            bridge.release(wanted)
        if answer is None:
            return None
        try:
            rect = _CGRect()
            if not bridge.value_read(answer, _AX_VALUE_CGRECT, rect):
                return None
        finally:
            bridge.release(answer)
        if rect.size.width <= 0 or rect.size.height <= 0:
            return None
        return BoundingBox(
            left=int(rect.origin.x),
            top=int(rect.origin.y),
            right=int(rect.origin.x + rect.size.width),
            bottom=int(rect.origin.y + rect.size.height),
        )


__all__ = ["AccessibilityTextProvider"]
