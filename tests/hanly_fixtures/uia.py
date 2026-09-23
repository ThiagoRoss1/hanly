"""A fake UI Automation control and bridge for the Windows text adapter.

The adapter's judgement -- which properties it consults before touching text,
how it isolates a span, which rectangle answers for a pointer, and that it
releases every interface it opens -- is pure Python over a small bridge
surface. These doubles stand in for that surface, so the same judgement can be
exercised on every host, not only on Windows.
"""

from __future__ import annotations

import ctypes
from math import floor
from typing import Any

from hanly import BoundingBox, Point

UIA_IS_PASSWORD = 30019
UIA_IS_OFFSCREEN = 30022

LINE_TOP = 100
LINE_BOTTOM = 130
LINE_LEFT = 200
#: Every fixture line is laid out at ten pixels per character, so a pointer's
#: x coordinate names a character and a character span names a rectangle.
CHARACTER_WIDTH = 10


class FakeRange:
    """A start/end pair over the fake control's text, in Python characters."""

    def __init__(self, control: FakeControl, start: int, end: int) -> None:
        self.control = control
        self.start = start
        self.end = end

    def text(self) -> str:
        return self.control.text[self.start : self.end]


class FakeControl:
    """One line of text answering the way a real UIA provider answers.

    ``unit`` names what this control thinks ``MoveEndpointByUnit`` counts:
    Chromium was measured counting code points and RichEdit UTF-16 code units,
    and the adapter has to reach the same span through either. ``caret`` names
    where ``RangeFromPoint`` puts its degenerate range: before the character
    under the pointer, or at the insertion point nearest the pointer, which is
    after that character when the pointer is on its right half.
    """

    def __init__(
        self,
        text: str,
        *,
        unit: str = "code_points",
        caret: str = "character",
        password: bool = False,
        offscreen: bool = False,
        has_pattern: bool = True,
        denied: bool = False,
        rectangles: list[BoundingBox] | None = None,
        nearest: bool = False,
    ) -> None:
        self.text = text
        self.unit = unit
        self.caret = caret
        self.password = password
        self.offscreen = offscreen
        self.has_pattern = has_pattern
        self.denied = denied
        self.rectangles = rectangles
        self.nearest = nearest

    def index_at(self, point: Point) -> int:
        offset = (point.x - LINE_LEFT) / CHARACTER_WIDTH
        if self.nearest:
            # The failure that would silently define the wrong word: the
            # control answers about whatever is closest instead of refusing.
            return 0
        if self.caret == "nearest":
            return max(0, min(floor(offset + 0.5), len(self.text)))
        return max(0, min(floor(offset), max(len(self.text) - 1, 0)))

    def offsets_of(self, index: int) -> int:
        if self.unit == "code_points":
            return index
        return len(self.text[:index].encode("utf-16-le")) // 2

    def index_of(self, offset: int) -> int | None:
        for index in range(len(self.text) + 1):
            if self.offsets_of(index) == offset:
                return index
        return None

    def box_for(self, start: int, end: int) -> list[BoundingBox]:
        if self.rectangles is not None:
            return self.rectangles
        if end <= start:
            return []
        return [
            BoundingBox(
                left=LINE_LEFT + start * CHARACTER_WIDTH,
                top=LINE_TOP,
                right=LINE_LEFT + end * CHARACTER_WIDTH,
                bottom=LINE_BOTTOM,
            )
        ]


class FakeBridge:
    """Stands in for the COM bridge and counts what the adapter fails to free."""

    def __init__(self, control: FakeControl | None) -> None:
        self.control = control
        self._objects: dict[int, Any] = {}
        self._next = 1
        self.live = 0

    # --- handle bookkeeping ----------------------------------------------

    def hold(self, value: Any) -> ctypes.c_void_p:
        handle = self._next
        self._next += 1
        self._objects[handle] = value
        self.live += 1
        return ctypes.c_void_p(handle)

    def get(self, pointer: ctypes.c_void_p) -> Any:
        assert pointer.value is not None, "the adapter passed back a null interface"
        return self._objects[pointer.value]

    def release(self, pointer: ctypes.c_void_p | None) -> None:
        if pointer and pointer.value in self._objects:
            del self._objects[pointer.value]
            self.live -= 1

    # --- the surface the adapter calls -----------------------------------

    def element_at(self, point: Point) -> ctypes.c_void_p | None:
        return None if self.control is None else self.hold(self.control)

    def flag(self, element: ctypes.c_void_p, property_id: int) -> bool | None:
        control = self.get(element)
        if control.denied:
            return None
        if property_id == UIA_IS_PASSWORD:
            return bool(control.password)
        if property_id == UIA_IS_OFFSCREEN:
            return bool(control.offscreen)
        return None

    def text_pattern(self, element: ctypes.c_void_p) -> ctypes.c_void_p | None:
        control = self.get(element)
        if control.denied or not control.has_pattern:
            return None
        return self.hold(control)

    def range_at(
        self, pattern: ctypes.c_void_p, point: Point
    ) -> ctypes.c_void_p | None:
        control = self.get(pattern)
        index = control.index_at(point)
        return self.hold(FakeRange(control, index, index))

    def clone(self, pointer: ctypes.c_void_p) -> ctypes.c_void_p | None:
        found = self.get(pointer)
        return self.hold(FakeRange(found.control, found.start, found.end))

    def expand(self, pointer: ctypes.c_void_p, unit: int) -> bool:
        found = self.get(pointer)
        found.start, found.end = 0, len(found.control.text)
        return True

    def text_of(self, pointer: ctypes.c_void_p, limit: int) -> str | None:
        return self.get(pointer).text()[:limit]

    def align_endpoint(
        self,
        pointer: ctypes.c_void_p,
        endpoint: int,
        other: ctypes.c_void_p,
        other_endpoint: int,
    ) -> bool:
        found, source = self.get(pointer), self.get(other)
        target = source.start if other_endpoint == 0 else source.end
        if endpoint == 0:
            found.start = target
            found.end = max(found.end, target)
        else:
            found.end = target
            found.start = min(found.start, target)
        return True

    def move_endpoint(
        self, pointer: ctypes.c_void_p, endpoint: int, unit: int, count: int
    ) -> bool:
        found = self.get(pointer)
        control = found.control
        current = found.start if endpoint == 0 else found.end
        moved = control.index_of(control.offsets_of(current) + count)
        if moved is None:
            return False
        if endpoint == 0:
            found.start = moved
            found.end = max(found.end, moved)
        else:
            found.end = moved
            found.start = min(found.start, moved)
        return True

    def rectangles(self, pointer: ctypes.c_void_p) -> list[BoundingBox]:
        found = self.get(pointer)
        return found.control.box_for(found.start, found.end)


def point_at(index: int, *, side: str = "centre") -> Point:
    """The pointer on the ``index``-th character of a fixture line.

    ``side`` puts it on that character's left or right half, where a provider
    reporting the nearest insertion point disagrees about which character it is.
    """

    offset = {"left": 2, "centre": CHARACTER_WIDTH / 2, "right": 8}[side]
    return Point(
        LINE_LEFT + index * CHARACTER_WIDTH + offset,
        (LINE_TOP + LINE_BOTTOM) / 2,
    )
