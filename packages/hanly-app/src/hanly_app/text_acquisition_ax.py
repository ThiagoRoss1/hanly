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

#: The native deadline has to be strictly inside the caller's own budget. A
#: call that reaches its messaging timeout still has to return, be classified,
#: and fall back to OCR; if the two deadlines were equal, every such call would
#: instead be reported as too late to use.
_NATIVE_DEADLINE_SHARE = 0.5

#: Secure text is normally a subrole; retain the role check for custom controls.
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
        services.AXUIElementSetMessagingTimeout.restype = ctypes.c_int
        services.AXUIElementSetMessagingTimeout.argtypes = [
            ctypes.c_void_p, ctypes.c_float,
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

    def element_at(
        self, x: float, y: float, timeout_seconds: float
    ) -> ctypes.c_void_p | None:
        system = ctypes.c_void_p(self._services.AXUIElementCreateSystemWide())
        if not system:
            return None
        try:
            # These calls are synchronous and cross into the target
            # application, so a deadline has to be given to the API itself.
            # Measuring elapsed time afterwards discards a late answer but does
            # nothing about an unresponsive application holding the caller.
            self._services.AXUIElementSetMessagingTimeout(
                system, ctypes.c_float(timeout_seconds)
            )
            element = ctypes.c_void_p()
            status = self._services.AXUIElementCopyElementAtPosition(
                system, ctypes.c_float(x), ctypes.c_float(y), ctypes.byref(element)
            )
        finally:
            self.release(system)
        if status != _AX_SUCCESS or not element:
            return None
        # The element is a separate object; the system-wide deadline does not
        # travel with it.
        self._services.AXUIElementSetMessagingTimeout(
            element, ctypes.c_float(timeout_seconds)
        )
        return element

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


def _code_point_index(text: str, utf16_offset: int) -> int | None:
    """Where ``utf16_offset`` falls in ``text``, counted in characters.

    macOS counts UTF-16 code units, so one emoji before the Korean shifts every
    later offset by one. An offset landing inside a surrogate pair names no
    character at all and is refused rather than moved to a neighbouring one,
    because quietly choosing the adjacent character is how the wrong word gets
    defined.
    """

    if utf16_offset < 0:
        return None
    units = text.encode("utf-16-le")
    if utf16_offset * 2 > len(units):
        return None

    prefix = units[: utf16_offset * 2]
    try:
        return len(prefix.decode("utf-16-le"))
    except UnicodeDecodeError:
        # A lone surrogate: the offset is halfway through one character.
        return None


def _utf16_offset(text: str, code_point_index: int) -> int | None:
    """The UTF-16 offset of ``code_point_index``, the inverse of the above.

    The accessibility API is asked about ranges in its own units, so a span the
    caller expressed in characters has to be converted back before it can be
    used to ask anything.
    """

    if not 0 <= code_point_index <= len(text):
        return None
    return len(text[:code_point_index].encode("utf-16-le")) // 2


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

        A share of ``timeout_ms`` becomes the accessibility API's own messaging
        deadline, so an unresponsive application returns an error instead of
        holding the caller, and still returns early enough for that error to be
        classified as an ordinary fallback. The coordinator separately discards
        an answer that arrived too late to be about where the pointer is now.
        """

        bridge = _bridge_once()
        if bridge is None:
            return None

        native_deadline = max(timeout_ms * _NATIVE_DEADLINE_SHARE, 1.0) / 1000.0
        element = bridge.element_at(float(point.x), float(point.y), native_deadline)
        if element is None:
            return None
        try:
            return self._read_element(bridge, element, point)
        finally:
            bridge.release(element)

    def refine_bounds(
        self, point: Point, start: int, end: int, *, timeout_ms: int
    ) -> BoundingBox | None:
        """The rectangle of one span of the line previously read at ``point``.

        ``start`` and ``end`` are character offsets into that line. Asking the
        control itself is the only honest way to get this: a rectangle derived
        by dividing the line's own rectangle would be a guess that happens to
        look right in a monospaced font.
        """

        bridge = _bridge_once()
        if bridge is None:
            return None

        native_deadline = max(timeout_ms * _NATIVE_DEADLINE_SHARE, 1.0) / 1000.0
        element = bridge.element_at(float(point.x), float(point.y), native_deadline)
        if element is None:
            return None
        try:
            role = self._string_attribute(bridge, element, "AXRole")
            if role is None or self._secure_element(bridge, element, role):
                return None
            return self._span_bounds(bridge, element, point, start, end)
        finally:
            bridge.release(element)

    def _span_bounds(
        self,
        bridge: _AccessibilityBridge,
        element: ctypes.c_void_p,
        point: Point,
        start: int,
        end: int,
    ) -> BoundingBox | None:
        """Convert a character span of the line back into an accessibility range."""

        if end <= start:
            return None

        index = self._index_at(bridge, element, point)
        if index is None:
            return None
        line = self._line_range(bridge, element, index)
        if line is None:
            return None
        line_start, line_length = line
        text = self._string_for_range(bridge, element, line_start, line_length)
        if text is None:
            return None

        # The line may have changed under the pointer between the two calls;
        # a span that no longer fits it cannot be asked about.
        first = _utf16_offset(text, start)
        last = _utf16_offset(text, end)
        if first is None or last is None or last <= first:
            return None
        return self._bounds_for_range(
            bridge, element, line_start + first, last - first
        )

    def _read_element(
        self,
        bridge: _AccessibilityBridge,
        element: ctypes.c_void_p,
        point: Point,
    ) -> DirectText | None:
        role = self._string_attribute(bridge, element, "AXRole")
        if role is None:
            return None
        if self._secure_element(bridge, element, role):
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
        # Everything above counts in UTF-16 code units, which is what the
        # accessibility API speaks. Everything below counts code points, which
        # is what Python and the engine contracts speak. This is the boundary,
        # so the conversion happens here and nowhere else.
        cursor_index = _code_point_index(text, index - start)
        if cursor_index is None:
            return None

        bounds = self._bounds_for_range(bridge, element, start, length)
        return DirectText(
            text=text,
            cursor_index=cursor_index,
            bounds=bounds,
            role=role,
        )

    def _secure_element(
        self, bridge: _AccessibilityBridge, element: ctypes.c_void_p, role: str
    ) -> bool:
        return (
            role in _SECURE_ROLES
            or self._string_attribute(bridge, element, "AXSubrole") in _SECURE_ROLES
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
