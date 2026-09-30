"""Protect the current word, popup, and narrow corridor between them.

Keep these areas separate: their combined bounding hull would shield other words
from hover lookup.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from threading import RLock

from hanly import BoundingBox, Point

from hanly_app.acquisition.capture import ScreenRect

#: How far past the recognized word the cursor may stray and still count as on
#: it. Small on purpose: this covers the estimate in the word's own bounds, not
#: the distance to the next word.
WORD_MARGIN_PIXELS = 4

#: How long the cursor may spend crossing the gap between a word and its popup.
#: This is a cap on a transfer that is already under way, not a delay every
#: exit pays: a cursor leaving in any other direction is dismissed at once.
POPUP_TRANSFER_MS = 120.0

#: How far to either side of the straight line from the word to the popup the
#: cursor may stray and still count as crossing towards it. Narrow on purpose:
#: a wider band would cover the words beside the one being left.
TRANSFER_CORRIDOR_PIXELS = 24

#: How many recent captures keep their screen origin. The executor bounds work
#: to one running plus one latest pending, so this is already generous.
ORIGIN_LIMIT = 8

#: The ratio between captured image pixels and screen coordinates. See
#: :func:`screen_rect`: it is the one place the two spaces could diverge, and on
#: the platforms measured so far they do not.
SCREEN_SCALE = 1.0


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


def nearest_point(rect: ScreenRect, point: Point) -> Point:
    """The point of ``rect`` closest to ``point``, which is inside it if it is."""

    return Point(
        min(max(point.x, float(rect.left)), float(rect.left + rect.width)),
        min(max(point.y, float(rect.top)), float(rect.top + rect.height)),
    )


def distance_to(rect: ScreenRect, point: Point) -> float:
    """How far the cursor is from a rectangle, in screen pixels."""

    near = nearest_point(rect, point)
    return hypot(point.x - near.x, point.y - near.y)


def in_transfer_corridor(
    point: Point,
    origin: Point,
    popup: ScreenRect,
    *,
    half_width: int = TRANSFER_CORRIDOR_PIXELS,
) -> bool:
    """Whether the cursor is in the narrow band from ``origin`` to the popup.

    Deliberately a band around one line rather than a rectangle enclosing both:
    the hull of a word and a popup placed diagonally from it covers whatever is
    between them, which is usually the next words the user wants to read.
    """

    return _distance_to_segment(point, origin, nearest_point(popup, origin)) <= half_width


def _distance_to_segment(point: Point, start: Point, end: Point) -> float:
    span_x, span_y = end.x - start.x, end.y - start.y
    length_squared = span_x * span_x + span_y * span_y
    if length_squared <= 0:
        return hypot(point.x - start.x, point.y - start.y)
    position = ((point.x - start.x) * span_x + (point.y - start.y) * span_y) / length_squared
    clamped = min(max(position, 0.0), 1.0)
    return hypot(
        point.x - (start.x + clamped * span_x), point.y - (start.y + clamped * span_y)
    )


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
    region: ScreenRect, bounds: BoundingBox, *, scale: float = SCREEN_SCALE
) -> ScreenRect | None:
    """Convert a word's ROI box to screen coordinates for popup protection.

    Use its request's capture origin, not the latest capture, which may differ for a
    stale result. Scale image pixels into screen units: macOS logical geometry uses
    1.0; other platforms supply their scale explicitly.
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
        self._words: dict[int, ScreenRect] = {}

    def remember(self, request_id: int, region: ScreenRect) -> None:
        with self._lock:
            self._origins[request_id] = region
            self._trim()

    def remember_word(self, request_id: int, word: ScreenRect) -> None:
        """Record a word read without pixels, whose own rectangle is known.

        Direct text answers with the word's screen bounds rather than a capture
        region, and its result carries no ROI-local geometry to map.
        """

        with self._lock:
            self._words[request_id] = word
            self._trim()

    def origin(self, request_id: int | None) -> ScreenRect | None:
        if request_id is None:
            return None
        with self._lock:
            return self._origins.get(request_id)

    def word(self, request_id: int | None) -> ScreenRect | None:
        if request_id is None:
            return None
        with self._lock:
            return self._words.get(request_id)

    def clear(self) -> None:
        with self._lock:
            self._origins.clear()
            self._words.clear()

    def _trim(self) -> None:
        for recent in (self._origins, self._words):
            while len(recent) > self._limit:
                recent.pop(next(iter(recent)))


__all__ = [
    "ORIGIN_LIMIT",
    "POPUP_TRANSFER_MS",
    "SCREEN_SCALE",
    "TRANSFER_CORRIDOR_PIXELS",
    "WORD_MARGIN_PIXELS",
    "CaptureOrigins",
    "RetainedTarget",
    "distance_to",
    "expanded",
    "in_transfer_corridor",
    "nearest_point",
    "screen_rect",
]
