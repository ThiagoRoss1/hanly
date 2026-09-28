"""Deciding when a lookup was answered from a crop that cut the word.

The engine only ever sees images, so whether a capture clipped its own subject
is a question about screen geometry and belongs here. One observable condition
authorizes one wider capture: the recognized region the answer came from
reaches the edge of the ROI it was read in, which means the text may continue
past the crop.

This recovers *clipping*, not misrecognition. A word that was fully visible and
read wrongly looks identical to a word read correctly, and guessing at it is
what turns a wrong answer into a confident wrong answer.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass

from hanly import LookupResult, Point, ROIImage

from .capture import CaptureResult, ScreenRect

#: How close to the ROI edge a detected region must come to count as touching
#: it, in ROI pixels.
#:
#: Measured by reproducing the plan's section 2B crops against real EasyOCR: 30
#: cases over five words at 20 px and 32 px, cropped at the first, middle, and
#: last syllable. The smallest gap between a detected region and the nearer ROI
#: edge was 0 px in 12 cases and 2-5 px in a further 6; every remaining case sat
#: at 19 px or more, with nothing between 5 and 19. The threshold sits in that
#: empty band rather than on either cluster.
EDGE_TOLERANCE_PIXELS = 6

#: Extra screen pixels taken on each side of a clipped capture. One ROI width
#: of context is what the measured cases were short by; growing without bound
#: would drift towards the full-screen OCR the architecture forbids.
RECOVERY_MARGIN_PIXELS = 100


@dataclass(frozen=True)
class ClippedEdges:
    """Which sides of the ROI the answer's own text region reached."""

    left: bool
    right: bool

    def __bool__(self) -> bool:
        return self.left or self.right


def clipped_edges(
    result: LookupResult,
    roi_width: int,
    *,
    tolerance: int = EDGE_TOLERANCE_PIXELS,
) -> ClippedEdges:
    """Which ROI edges the region this answer came from reaches.

    Only the region that actually produced the answer is considered. Another
    line elsewhere in the crop touching an edge says nothing about the word the
    user is pointing at.
    """

    context = result.context
    region = context.selected_ocr if context is not None else None
    if region is None or roi_width <= 0:
        return ClippedEdges(False, False)

    xs = [point.x for point in region.quad.points]
    return ClippedEdges(
        left=min(xs) <= tolerance,
        right=max(xs) >= roi_width - tolerance,
    )


def widened_region(
    region: ScreenRect,
    edges: ClippedEdges,
    monitor: ScreenRect,
    *,
    margin: int = RECOVERY_MARGIN_PIXELS,
) -> ScreenRect | None:
    """The screen rectangle to re-capture, or ``None`` when nothing would change.

    The result never leaves the monitor the first capture was taken from, so a
    recovery cannot wander onto another display or off the desktop.
    """

    if not edges:
        return None

    left = region.left - (margin if edges.left else 0)
    right = region.left + region.width + (margin if edges.right else 0)
    left = max(left, monitor.left)
    right = min(right, monitor.left + monitor.width)

    width = right - left
    if width <= region.width:
        # Already against the edge of the display: a wider crop does not exist.
        return None
    return ScreenRect(left, region.top, width, region.height)


def recovery_target(
    region: ScreenRect, target: Point, widened: ScreenRect
) -> Point:
    """The original ROI-local target expressed inside the widened capture."""

    return Point(
        region.left + target.x - widened.left, region.top + target.y - widened.top
    )


#: How many recent requests are remembered as already recovered. A hover
#: session produces requests steadily, so the ledger is bounded rather than
#: growing for the life of the process.
_RECOVERY_LEDGER_LIMIT = 64


class ClippingRecovery:
    """One extra capture when the answer came from text touching the ROI edge.

    This is the only retry in the lookup path, and it is deliberately narrow:
    it recovers a *clipped* reading, never a wrong one. A fully visible word
    that was misrecognized looks identical to one read correctly, so retrying
    on confidence, a dictionary miss, or text shape would turn an honest
    non-success into a confident wrong answer.
    """

    def __init__(
        self,
        *,
        capture: Callable[..., CaptureResult],
        submit: Callable[[ROIImage, Point], object],
        origin_for: Callable[[int | None], ScreenRect | None],
        monitor_for: Callable[[ScreenRect], ScreenRect],
        is_current: Callable[[int], bool],
        trace: Callable[[str, int, str], None] | None = None,
    ) -> None:
        self._capture = capture
        self._submit = submit
        self._origin_for = origin_for
        self._monitor_for = monitor_for
        self._is_current = is_current
        self._trace = trace
        self._spent: OrderedDict[int, bool] = OrderedDict()

    def intercept(self, result: LookupResult, request_id: int | None) -> bool:
        """Recover instead of presenting, when the evidence says text was cut.

        Returns whether a recovery was submitted. ``True`` means the caller
        must not present this result: a newer request is now current and
        presenting the old one would put a stale answer on screen.
        """

        if request_id is None or self._spent.get(request_id) is not None:
            return False

        origin = self._origin_for(request_id)
        if origin is None or not self._is_current(request_id):
            return False

        edges = clipped_edges(result, origin.width)
        if not edges:
            return False

        capture = self._recapture(origin, edges, request_id)
        if capture is None:
            return False

        # Currency is rechecked after the capture, which is the slow part: the
        # pointer may have moved on to a different word while it ran.
        if not self._is_current(request_id):
            return False

        self._remember(request_id)
        self._submit(capture.image, capture.target)
        self._report("clipping_recovery_submitted", request_id, "edge_contact")
        return True

    def spend(self, request_id: int | None) -> None:
        """Mark a request as ineligible, so a recovery cannot recover itself."""

        if request_id is not None:
            self._remember(request_id)

    def _recapture(
        self, origin: ScreenRect, edges: ClippedEdges, request_id: int
    ) -> CaptureResult | None:
        widened = widened_region(origin, edges, self._monitor_for(origin))
        if widened is None:
            self._report("clipping_recovery_skipped", request_id, "no_room")
            return None
        try:
            return self._capture(
                Point(widened.left + widened.width / 2, widened.top + widened.height / 2),
                anchor=widened,
            )
        except Exception:
            self._report("clipping_recovery_failed", request_id, "capture_error")
            return None

    def _remember(self, request_id: int) -> None:
        self._spent[request_id] = True
        while len(self._spent) > _RECOVERY_LEDGER_LIMIT:
            self._spent.popitem(last=False)

    def _report(self, kind: str, request_id: int, reason: str) -> None:
        if self._trace is not None:
            self._trace(kind, request_id, reason)




__all__ = [
    "ClippingRecovery",
    "EDGE_TOLERANCE_PIXELS",
    "RECOVERY_MARGIN_PIXELS",
    "ClippedEdges",
    "clipped_edges",
    "recovery_target",
    "widened_region",
]
