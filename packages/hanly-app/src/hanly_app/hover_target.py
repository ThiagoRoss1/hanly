"""What the cursor may move over without losing the answer it is reading.

A popup that disappears the moment the cursor moves towards it cannot be read,
and one that survives any movement covers the next word. Between those, Hanly
keeps a successful result while the cursor is still on the word it describes or
on the popup itself, and gives a short grace for the gap between the two.

The protected area is deliberately a union of two rectangles rather than one
rectangle around both: the hull of a word and a popup placed diagonally from it
covers whatever is in between, which is usually other words the user wants to
look up.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from threading import RLock

from hanly import BoundingBox, Point

from .capture import ScreenRect

#: How far past the recognized word the cursor may stray and still count as on
#: it. Small on purpose: this covers the estimate in the word's own bounds, not
#: the distance to the next word.
WORD_MARGIN_PIXELS = 4

#: How long a result survives a real exit. Long enough to cross the gap to the
#: popup, short enough that a deliberate move away feels immediate.
EXIT_GRACE_MS = 120.0

#: How many recent captures keep their screen origin. The executor bounds work
#: to one running plus one latest pending, so this is already generous.
ORIGIN_LIMIT = 8


@dataclass(frozen=True, slots=True)
class RetainedTarget:
    """One successful result, and where on screen it came from."""

    lookup_request_id: int
    word: ScreenRect
    popup: ScreenRect | None = None

    def protects(self, point: Point, *, margin: int = WORD_MARGIN_PIXELS) -> bool:
        """Whether the cursor is still on the word, or on the popup itself."""

        return expanded(self.word, margin).contains(point) or (
            self.popup is not None and self.popup.contains(point)
        )

    def with_popup(self, popup: ScreenRect | None) -> RetainedTarget:
        """Adopt the frame the popup actually took, once it has been placed."""

        return replace(self, popup=popup)


def expanded(rect: ScreenRect, margin: int) -> ScreenRect:
    """Grow a rectangle by a margin on every side."""

    if margin <= 0:
        return rect
    return ScreenRect(
        left=rect.left - margin,
        top=rect.top - margin,
        width=rect.width + margin * 2,
        height=rect.height + margin * 2,
    )


def screen_rect(
    region: ScreenRect, bounds: BoundingBox, *, scale: float = 1.0
) -> ScreenRect | None:
    """Place an ROI-local box on the screen the capture came from.

    The origin travels with the request that produced it rather than with a
    latest global capture: by the time a result arrives the cursor has usually
    moved, and a later capture describes somewhere else entirely.

    ``scale`` is the one place image pixels and screen coordinates could
    diverge. On macOS they do not -- the capture backend reports the same
    logical geometry Qt does, and a captured ROI is the same size as the region
    asked for -- so it is 1.0 here and remains a named input for the platforms
    where that still has to be checked.
    """

    if scale <= 0:
        return None
    left = region.left + int(bounds.left / scale)
    top = region.top + int(bounds.top / scale)
    width = max(1, int((bounds.right - bounds.left) / scale))
    height = max(1, int((bounds.bottom - bounds.top) / scale))
    return ScreenRect(left=left, top=top, width=width, height=height)


class CaptureOrigins:
    """Where each recent request's ROI sat on the screen.

    Both triggers write here and the result handoff reads it, so this is shared
    by composition rather than owned by either path.
    """

    def __init__(self, limit: int = ORIGIN_LIMIT) -> None:
        if limit <= 0:
            raise ValueError("limit must be positive")
        self._limit = limit
        self._lock = RLock()
        self._origins: dict[int, ScreenRect] = {}

    def remember(self, request_id: int, region: ScreenRect) -> None:
        with self._lock:
            self._origins[request_id] = region
            while len(self._origins) > self._limit:
                self._origins.pop(next(iter(self._origins)))

    def origin(self, request_id: int | None) -> ScreenRect | None:
        if request_id is None:
            return None
        with self._lock:
            return self._origins.get(request_id)

    def clear(self) -> None:
        with self._lock:
            self._origins.clear()


__all__ = [
    "EXIT_GRACE_MS",
    "ORIGIN_LIMIT",
    "WORD_MARGIN_PIXELS",
    "CaptureOrigins",
    "RetainedTarget",
    "expanded",
    "screen_rect",
]
