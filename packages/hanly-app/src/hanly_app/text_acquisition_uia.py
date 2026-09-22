"""Read the text under the pointer through Windows UI Automation.

UI Automation is a COM API, bound here through ``ctypes`` rather than
``comtypes`` for the same reason :mod:`hanly_app.text_acquisition_ax` binds the
macOS accessibility API that way: the desktop carries no COM code-generation
dependency, and four interfaces out of a very large library are wanted, not a
generated projection of all of them.

UIA answers in physical screen pixels across the whole virtual desktop, origin
at the primary monitor and negative coordinates to its left, which is the space
the pointer already arrives in while the process is per-monitor DPI aware. What
UIA does *not* guarantee is that the answer belongs to the pointer at all --
``RangeFromPoint`` is documented to return the *nearest* range -- so everything
read here is evidence for :mod:`hanly_app.text_acquisition` to accept or refuse.

Two providers were measured disagreeing about what a character is: Chromium
counts code points and RichEdit counts UTF-16 code units. Neither reading is
trusted; a narrowed range is asked for both ways and kept only if the text it
returns is the text that was asked for.
"""

from __future__ import annotations

import ctypes
import sys
from math import ceil, floor
from threading import local
from typing import Any

from hanly import BoundingBox, Point

from .text_acquisition import DirectText

# ``WinDLL`` and ``WINFUNCTYPE`` exist only on Windows, and this module is
# imported only there; the other branch keeps it parseable and type-checkable
# on the hosts that run the portable suite.
if sys.platform == "win32":
    _load_library = ctypes.WinDLL
    _native_prototype = ctypes.WINFUNCTYPE
else:  # pragma: no cover - never constructed off Windows
    _load_library = ctypes.CDLL
    _native_prototype = ctypes.CFUNCTYPE

_S_OK = 0
_S_FALSE = 1
#: ``CoInitializeEx`` refusing because this thread is already in another
#: apartment. The apartment is not ours, so it must not be torn down either.
_RPC_E_CHANGED_MODE = 0x80010106
_COINIT_MULTITHREADED = 0x0
_CLSCTX_INPROC_SERVER = 1

#: ``CUIAutomation8``/``IUIAutomation2`` first, because only that interface
#: exposes the call timeouts. ``IUIAutomation2`` derives from ``IUIAutomation``,
#: so every slot below is the same in either.
_CLSID_CUIAUTOMATION8 = "{E22AD333-B25F-460C-83D0-0581107395C9}"
_IID_IUIAUTOMATION2 = "{34723AFF-0C9D-49D0-9896-7AB52DF8CD8A}"
_CLSID_CUIAUTOMATION = "{FF48DBA4-60EF-4201-AA87-54103EEF594E}"
_IID_IUIAUTOMATION = "{30CBE57D-D9D0-452A-AB13-7AC5AC4825EE}"

# Vtable slots, each confirmed against the running system rather than
# transcribed from a header: these interfaces have dozens of methods and a
# wrong slot is an access violation rather than an error code.
_IUNKNOWN_RELEASE = 2
_AUTOMATION_ELEMENT_FROM_POINT = 7
_AUTOMATION_PUT_CONNECTION_TIMEOUT = 61
_AUTOMATION_PUT_TRANSACTION_TIMEOUT = 63
_ELEMENT_GET_CURRENT_PROPERTY_VALUE = 10
_ELEMENT_GET_CURRENT_PATTERN = 16
_TEXT_PATTERN_RANGE_FROM_POINT = 3
_RANGE_CLONE = 3
_RANGE_EXPAND_TO_ENCLOSING_UNIT = 6
_RANGE_GET_BOUNDING_RECTANGLES = 10
_RANGE_GET_TEXT = 12
_RANGE_MOVE_ENDPOINT_BY_UNIT = 14
_RANGE_MOVE_ENDPOINT_BY_RANGE = 15

_UIA_TEXT_PATTERN = 10014
_UIA_IS_PASSWORD_PROPERTY = 30019
_UIA_IS_OFFSCREEN_PROPERTY = 30022

_TEXT_UNIT_CHARACTER = 0
_TEXT_UNIT_LINE = 3
_ENDPOINT_START = 0
_ENDPOINT_END = 1

_VT_BOOL = 11

#: UI Automation rejects anything below fifty milliseconds for either call
#: timeout, which is already wider than the caller's whole budget, so this is
#: not the deadline -- the caller's is. It is set because the default
#: transaction timeout is twenty seconds, and a provider wedged for that long
#: would hold the one worker thread away from every later hover.
_NATIVE_TIMEOUT_MS = 50

#: The "line" a browser reports can be an entire paragraph. Past this the text
#: comes back truncated, and then the truncation point rather than the pointer
#: decides every offset, so such a line is refused instead of guessed at.
_MAX_LINE_CHARACTERS = 4096


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _VariantValue(ctypes.Union):
    _fields_ = [
        ("bool_value", ctypes.c_short),
        ("bstr_value", ctypes.c_void_p),
        ("array_value", ctypes.c_void_p),
        ("_widest", ctypes.c_longlong),
    ]


class _VARIANT(ctypes.Structure):
    _fields_ = [
        ("vt", ctypes.c_ushort),
        ("_reserved", ctypes.c_ushort * 3),
        ("value", _VariantValue),
        ("_tail", ctypes.c_longlong),
    ]


class _UIABridge:
    """One thread's COM apartment, automation client, and typed entry points.

    Every method converts an expected UIA refusal -- a failed ``HRESULT``, a
    null interface, an unsupported pattern -- into ``None`` or ``False``. A
    native exception must never reach the application through this seam.
    """

    def __init__(
        self,
        ole32: ctypes.CDLL,
        oleaut32: ctypes.CDLL,
        automation: ctypes.c_void_p,
        *,
        owns_apartment: bool,
    ) -> None:
        self._ole32 = ole32
        self._oleaut32 = oleaut32
        self._automation = automation
        self._owns_apartment = owns_apartment

    def limit_calls(self, milliseconds: int) -> None:
        for slot in (
            _AUTOMATION_PUT_CONNECTION_TIMEOUT,
            _AUTOMATION_PUT_TRANSACTION_TIMEOUT,
        ):
            self._method(self._automation, slot, ctypes.c_int)(
                self._automation, milliseconds
            )

    # --- COM plumbing -----------------------------------------------------

    @staticmethod
    def _method(interface: ctypes.c_void_p, slot: int, *argtypes: type) -> Any:
        """The ``slot``-th entry of an interface's vtable, as a callable.

        Declared as returning a plain ``long`` rather than ``ctypes.HRESULT``
        so a failing call is a value to inspect instead of an exception to
        catch on the hot path.
        """

        table = ctypes.cast(interface, ctypes.POINTER(ctypes.c_void_p))[0]
        entry = ctypes.cast(table, ctypes.POINTER(ctypes.c_void_p))[slot]
        prototype = _native_prototype(ctypes.c_long, ctypes.c_void_p, *argtypes)
        return prototype(entry)

    def release(self, interface: ctypes.c_void_p | None) -> None:
        if interface:
            self._method(interface, _IUNKNOWN_RELEASE)(interface)

    def dispose(self) -> None:
        """Drop the automation client and leave the apartment this bridge entered."""

        self.release(self._automation)
        self._automation = ctypes.c_void_p()
        if self._owns_apartment:
            self._ole32.CoUninitialize()
            self._owns_apartment = False

    def _string(self, pointer: int | None) -> str | None:
        """Read and free a ``BSTR``."""

        if not pointer:
            return None
        try:
            return ctypes.cast(ctypes.c_void_p(pointer), ctypes.c_wchar_p).value
        finally:
            self._oleaut32.SysFreeString(ctypes.c_void_p(pointer))

    # --- elements ---------------------------------------------------------

    def element_at(self, point: Point) -> ctypes.c_void_p | None:
        element = ctypes.c_void_p()
        status = self._method(
            self._automation,
            _AUTOMATION_ELEMENT_FROM_POINT,
            _POINT,
            ctypes.POINTER(ctypes.c_void_p),
        )(
            self._automation,
            _POINT(int(point.x), int(point.y)),
            ctypes.byref(element),
        )
        return element if status == _S_OK and element else None

    def _property(
        self, element: ctypes.c_void_p, property_id: int
    ) -> _VARIANT | None:
        value = _VARIANT()
        status = self._method(
            element,
            _ELEMENT_GET_CURRENT_PROPERTY_VALUE,
            ctypes.c_int,
            ctypes.POINTER(_VARIANT),
        )(element, property_id, ctypes.byref(value))
        return value if status == _S_OK else None

    def flag(self, element: ctypes.c_void_p, property_id: int) -> bool | None:
        """A boolean element property, or ``None`` when it is not one.

        UIA answers a property it cannot supply with a reserved sentinel rather
        than an error, so the variant's own type is what decides whether there
        was an answer at all.
        """

        value = self._property(element, property_id)
        if value is None:
            return None
        try:
            return bool(value.value.bool_value) if value.vt == _VT_BOOL else None
        finally:
            self._oleaut32.VariantClear(ctypes.byref(value))

    def text_pattern(self, element: ctypes.c_void_p) -> ctypes.c_void_p | None:
        pattern = ctypes.c_void_p()
        status = self._method(
            element,
            _ELEMENT_GET_CURRENT_PATTERN,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_void_p),
        )(element, _UIA_TEXT_PATTERN, ctypes.byref(pattern))
        return pattern if status == _S_OK and pattern else None

    # --- text ranges ------------------------------------------------------

    def range_at(
        self, pattern: ctypes.c_void_p, point: Point
    ) -> ctypes.c_void_p | None:
        text_range = ctypes.c_void_p()
        status = self._method(
            pattern,
            _TEXT_PATTERN_RANGE_FROM_POINT,
            _POINT,
            ctypes.POINTER(ctypes.c_void_p),
        )(pattern, _POINT(int(point.x), int(point.y)), ctypes.byref(text_range))
        return text_range if status == _S_OK and text_range else None

    def clone(self, text_range: ctypes.c_void_p) -> ctypes.c_void_p | None:
        copy = ctypes.c_void_p()
        status = self._method(
            text_range, _RANGE_CLONE, ctypes.POINTER(ctypes.c_void_p)
        )(text_range, ctypes.byref(copy))
        return copy if status == _S_OK and copy else None

    def expand(self, text_range: ctypes.c_void_p, unit: int) -> bool:
        status = self._method(
            text_range, _RANGE_EXPAND_TO_ENCLOSING_UNIT, ctypes.c_int
        )(text_range, unit)
        return status == _S_OK

    def text_of(self, text_range: ctypes.c_void_p, limit: int) -> str | None:
        found = ctypes.c_void_p()
        status = self._method(
            text_range,
            _RANGE_GET_TEXT,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_void_p),
        )(text_range, limit, ctypes.byref(found))
        if status != _S_OK:
            return None
        return self._string(found.value)

    def move_endpoint(
        self, text_range: ctypes.c_void_p, endpoint: int, unit: int, count: int
    ) -> bool:
        moved = ctypes.c_int()
        status = self._method(
            text_range,
            _RANGE_MOVE_ENDPOINT_BY_UNIT,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
        )(text_range, endpoint, unit, count, ctypes.byref(moved))
        return status == _S_OK

    def align_endpoint(
        self,
        text_range: ctypes.c_void_p,
        endpoint: int,
        other: ctypes.c_void_p,
        other_endpoint: int,
    ) -> bool:
        status = self._method(
            text_range,
            _RANGE_MOVE_ENDPOINT_BY_RANGE,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_int,
        )(text_range, endpoint, other, other_endpoint)
        return status == _S_OK

    def rectangles(self, text_range: ctypes.c_void_p) -> list[BoundingBox]:
        """Every rectangle the range occupies, one per visual line."""

        array = ctypes.c_void_p()
        status = self._method(
            text_range,
            _RANGE_GET_BOUNDING_RECTANGLES,
            ctypes.POINTER(ctypes.c_void_p),
        )(text_range, ctypes.byref(array))
        if status != _S_OK or not array:
            return []
        try:
            return _boxes_from(self._read_doubles(array))
        finally:
            self._oleaut32.SafeArrayDestroy(array)

    def _read_doubles(self, array: ctypes.c_void_p) -> list[float]:
        first, last = ctypes.c_long(), ctypes.c_long()
        if self._oleaut32.SafeArrayGetLBound(array, 1, ctypes.byref(first)) != _S_OK:
            return []
        if self._oleaut32.SafeArrayGetUBound(array, 1, ctypes.byref(last)) != _S_OK:
            return []

        values: list[float] = []
        for position in range(first.value, last.value + 1):
            element = ctypes.c_double()
            index = ctypes.c_long(position)
            if self._oleaut32.SafeArrayGetElement(
                array, ctypes.byref(index), ctypes.byref(element)
            ) != _S_OK:
                return []
            values.append(element.value)
        return values


_thread_state = local()


def _bridge_for_thread() -> _UIABridge | None:
    """This thread's bridge, entering an apartment on first use.

    COM state belongs to a thread, not a process, and the service calls this
    adapter from exactly one long-lived worker. The bridge is therefore cached
    per thread and released by :meth:`UIAutomationTextProvider.release_thread`
    on that same thread.
    """

    if not getattr(_thread_state, "attempted", False):
        _thread_state.attempted = True
        _thread_state.bridge = _create_bridge()
    bridge: _UIABridge | None = _thread_state.bridge
    return bridge


def _create_bridge() -> _UIABridge | None:
    try:
        ole32 = _load_library("ole32", use_last_error=True)
        oleaut32 = _load_library("oleaut32", use_last_error=True)
    except OSError:
        return None

    _declare(ole32, oleaut32)
    # Multithreaded, because this runs on a worker that has no message pump and
    # must never be asked to run one.
    entered = ole32.CoInitializeEx(None, _COINIT_MULTITHREADED)
    if entered not in (_S_OK, _S_FALSE, _RPC_E_CHANGED_MODE):
        return None
    owns_apartment = entered != _RPC_E_CHANGED_MODE

    automation, timed = _create_automation(ole32)
    if automation is None:
        if owns_apartment:
            ole32.CoUninitialize()
        return None

    bridge = _UIABridge(ole32, oleaut32, automation, owns_apartment=owns_apartment)
    if timed:
        bridge.limit_calls(_NATIVE_TIMEOUT_MS)
    return bridge


def _declare(ole32: ctypes.CDLL, oleaut32: ctypes.CDLL) -> None:
    """Give every entry point a signature before it is called.

    ctypes assumes a C ``int`` return, which truncates the 64-bit pointers and
    handles these functions deal in.
    """

    ole32.CLSIDFromString.restype = ctypes.c_long
    ole32.CLSIDFromString.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(_GUID)]
    ole32.CoInitializeEx.restype = ctypes.c_long
    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    ole32.CoUninitialize.restype = None
    ole32.CoUninitialize.argtypes = []
    ole32.CoCreateInstance.restype = ctypes.c_long
    ole32.CoCreateInstance.argtypes = [
        ctypes.POINTER(_GUID),
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(_GUID),
        ctypes.POINTER(ctypes.c_void_p),
    ]

    oleaut32.VariantClear.restype = ctypes.c_long
    oleaut32.VariantClear.argtypes = [ctypes.POINTER(_VARIANT)]
    oleaut32.SysFreeString.restype = None
    oleaut32.SysFreeString.argtypes = [ctypes.c_void_p]
    oleaut32.SafeArrayDestroy.restype = ctypes.c_long
    oleaut32.SafeArrayDestroy.argtypes = [ctypes.c_void_p]
    oleaut32.SafeArrayGetLBound.restype = ctypes.c_long
    oleaut32.SafeArrayGetLBound.argtypes = [
        ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_long),
    ]
    oleaut32.SafeArrayGetUBound.restype = ctypes.c_long
    oleaut32.SafeArrayGetUBound.argtypes = [
        ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_long),
    ]
    oleaut32.SafeArrayGetElement.restype = ctypes.c_long
    oleaut32.SafeArrayGetElement.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_long), ctypes.c_void_p,
    ]


def _create_automation(ole32: ctypes.CDLL) -> tuple[ctypes.c_void_p | None, bool]:
    """The automation client, and whether it accepts call timeouts."""

    for class_id, interface_id, timed in (
        (_CLSID_CUIAUTOMATION8, _IID_IUIAUTOMATION2, True),
        (_CLSID_CUIAUTOMATION, _IID_IUIAUTOMATION, False),
    ):
        instance = ctypes.c_void_p()
        status = ole32.CoCreateInstance(
            ctypes.byref(_guid(ole32, class_id)),
            None,
            _CLSCTX_INPROC_SERVER,
            ctypes.byref(_guid(ole32, interface_id)),
            ctypes.byref(instance),
        )
        if status == _S_OK and instance:
            return instance, timed
    return None, False


def _guid(ole32: ctypes.CDLL, literal: str) -> _GUID:
    parsed = _GUID()
    ole32.CLSIDFromString(literal, ctypes.byref(parsed))
    return parsed


def _boxes_from(values: list[float]) -> list[BoundingBox]:
    """Rectangles from UIA's flat ``left, top, width, height`` quadruples.

    Outward to whole pixels rather than truncated: the box is used to decide
    whether it holds the pointer, and a rectangle that rounded inwards could
    lose a pointer the control really is reporting about.
    """

    boxes: list[BoundingBox] = []
    for index in range(0, len(values) - 3, 4):
        left, top, width, height = values[index : index + 4]
        if width <= 0 or height <= 0:
            continue
        boxes.append(
            BoundingBox(
                left=floor(left),
                top=floor(top),
                right=ceil(left + width),
                bottom=ceil(top + height),
            )
        )
    return boxes


def _rect_for_point(boxes: list[BoundingBox], point: Point) -> BoundingBox | None:
    """The rectangle the pointer is inside, from a range that may wrap lines.

    A run split across two visual lines has two rectangles and only one of them
    is the pointer's. When none of them is, a single rectangle is still handed
    back so the caller's own containment rule can refuse it with real evidence;
    several are not, because nothing says which would have been meant.
    """

    for box in boxes:
        if _contains(box, point):
            return box
    return boxes[0] if len(boxes) == 1 else None


def _contains(box: BoundingBox, point: Point) -> bool:
    return box.left <= point.x <= box.right and box.top <= point.y <= box.bottom


def _span_offsets(text: str, start: int, end: int) -> tuple[tuple[int, int, int], ...]:
    """How far to move a line's endpoints to isolate ``text[start:end]``.

    Each candidate is ``(start, end, total)`` in one provider's idea of a
    character. Chromium counts code points and RichEdit counts UTF-16 code
    units, so both are offered and the caller keeps whichever returns the text
    that was actually asked for.
    """

    code_points = (start, end, len(text))
    units = (
        len(text[:start].encode("utf-16-le")) // 2,
        len(text[:end].encode("utf-16-le")) // 2,
        len(text.encode("utf-16-le")) // 2,
    )
    return (code_points,) if code_points == units else (code_points, units)


class UIAutomationTextProvider:
    """Read the line under a screen point, when a control exposes text at all."""

    def bind_thread(self) -> None:
        """Enter the apartment and build the client before the first hover.

        Called once on the service's worker thread, so the cost of entering COM
        and creating the automation client is not paid inside a lookup.
        """

        _bridge_for_thread()

    def release_thread(self) -> None:
        """Undo :meth:`bind_thread`, on the thread that performed it."""

        bridge = getattr(_thread_state, "bridge", None)
        _thread_state.bridge = None
        _thread_state.attempted = False
        if bridge is not None:
            bridge.dispose()

    def read_at(self, point: Point, *, timeout_ms: int) -> DirectText | None:
        """Return what UI Automation says is at ``point``.

        ``timeout_ms`` is the caller's budget and is not passed to UIA: its own
        call timeouts have a fifty millisecond floor, wider than the budget, so
        they are set once at construction and the deadline stays the caller's.
        """

        bridge = _bridge_for_thread()
        if bridge is None:
            return None

        element = bridge.element_at(point)
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

        ``start`` and ``end`` are character offsets into that line. The control
        is asked about the span rather than the line's own rectangle being
        divided up, which would be a guess that only looks right in a
        monospaced font.
        """

        bridge = _bridge_for_thread()
        if bridge is None:
            return None

        element = bridge.element_at(point)
        if element is None:
            return None
        try:
            return self._span_bounds(bridge, element, point, start, end)
        finally:
            bridge.release(element)

    # --- reading ----------------------------------------------------------

    def _read_element(
        self, bridge: _UIABridge, element: ctypes.c_void_p, point: Point
    ) -> DirectText | None:
        if bridge.flag(element, _UIA_IS_PASSWORD_PROPERTY):
            # Reported without its contents, so the caller refuses it by reason
            # rather than by an empty answer it cannot explain. Chromium really
            # does expose a text pattern on a password field.
            return DirectText(text="", cursor_index=0, secure=True)
        if bridge.flag(element, _UIA_IS_OFFSCREEN_PROPERTY):
            # Scrolled away or behind another window: whatever it would report
            # is not what the pointer is over.
            return None

        pattern = bridge.text_pattern(element)
        if pattern is None:
            return None
        try:
            return self._read_pattern(bridge, pattern, point)
        finally:
            bridge.release(pattern)

    def _read_pattern(
        self, bridge: _UIABridge, pattern: ctypes.c_void_p, point: Point
    ) -> DirectText | None:
        found = bridge.range_at(pattern, point)
        if found is None:
            return None
        try:
            line = self._line_of(bridge, found)
            if line is None:
                return None
            try:
                return self._reading(bridge, line, found, point)
            finally:
                bridge.release(line)
        finally:
            bridge.release(found)

    def _reading(
        self,
        bridge: _UIABridge,
        line: ctypes.c_void_p,
        found: ctypes.c_void_p,
        point: Point,
    ) -> DirectText | None:
        text = bridge.text_of(line, _MAX_LINE_CHARACTERS)
        if text is None or len(text) >= _MAX_LINE_CHARACTERS:
            return None

        cursor_index = self._cursor_index(bridge, line, found, text)
        if cursor_index is None:
            return None

        bounds = _rect_for_point(bridge.rectangles(line), point)
        return DirectText(text=text, cursor_index=cursor_index, bounds=bounds)

    @staticmethod
    def _line_of(
        bridge: _UIABridge, found: ctypes.c_void_p
    ) -> ctypes.c_void_p | None:
        """The whole line holding a degenerate range, so a word is not cut in half."""

        line = bridge.clone(found)
        if line is None:
            return None
        if bridge.expand(line, _TEXT_UNIT_LINE):
            return line
        bridge.release(line)
        return None

    @staticmethod
    def _cursor_index(
        bridge: _UIABridge,
        line: ctypes.c_void_p,
        found: ctypes.c_void_p,
        text: str,
    ) -> int | None:
        """Where in the line the pointer is, counted in Python characters.

        Taken from the text before the pointer rather than from a character
        count, which is the one measure the two providers agree on: whatever a
        provider thinks a character is, the string it hands back decodes to
        code points here.
        """

        prefix = bridge.clone(line)
        if prefix is None:
            return None
        try:
            if not bridge.align_endpoint(prefix, _ENDPOINT_END, found, _ENDPOINT_START):
                return None
            before = bridge.text_of(prefix, _MAX_LINE_CHARACTERS)
        finally:
            bridge.release(prefix)

        # A prefix that is not the line's own beginning means the control
        # answered about some other range, and nothing about it locates the
        # pointer.
        if before is None or not text.startswith(before):
            return None
        return len(before)

    # --- narrowing --------------------------------------------------------

    def _span_bounds(
        self,
        bridge: _UIABridge,
        element: ctypes.c_void_p,
        point: Point,
        start: int,
        end: int,
    ) -> BoundingBox | None:
        pattern = bridge.text_pattern(element)
        if pattern is None:
            return None
        try:
            found = bridge.range_at(pattern, point)
            if found is None:
                return None
            try:
                line = self._line_of(bridge, found)
            finally:
                bridge.release(found)
            if line is None:
                return None
            try:
                return self._narrowed(bridge, line, point, start, end)
            finally:
                bridge.release(line)
        finally:
            bridge.release(pattern)

    def _narrowed(
        self,
        bridge: _UIABridge,
        line: ctypes.c_void_p,
        point: Point,
        start: int,
        end: int,
    ) -> BoundingBox | None:
        text = bridge.text_of(line, _MAX_LINE_CHARACTERS)
        if text is None or not 0 <= start < end <= len(text):
            # The line may have changed under the pointer between the read and
            # this call; a span that no longer fits it cannot be asked about.
            return None

        wanted = text[start:end]
        for first, last, total in _span_offsets(text, start, end):
            span = self._span_of(bridge, line, first, last, total)
            if span is None:
                continue
            try:
                if bridge.text_of(span, _MAX_LINE_CHARACTERS) == wanted:
                    return _rect_for_point(bridge.rectangles(span), point)
            finally:
                bridge.release(span)
        return None

    @staticmethod
    def _span_of(
        bridge: _UIABridge,
        line: ctypes.c_void_p,
        first: int,
        last: int,
        total: int,
    ) -> ctypes.c_void_p | None:
        span = bridge.clone(line)
        if span is None:
            return None
        moved = bridge.move_endpoint(
            span, _ENDPOINT_START, _TEXT_UNIT_CHARACTER, first
        ) and bridge.move_endpoint(
            span, _ENDPOINT_END, _TEXT_UNIT_CHARACTER, last - total
        )
        if moved:
            return span
        bridge.release(span)
        return None


__all__ = ["UIAutomationTextProvider"]
