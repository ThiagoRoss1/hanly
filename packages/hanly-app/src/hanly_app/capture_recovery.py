"""Deciding when a lookup was answered from a crop that cut the word.

The engine only ever sees images, so whether a capture clipped its own subject
is a question about screen geometry and belongs here. One observable condition
authorizes one wider capture: the recognized region the answer came from
reaches the edge of the ROI it was read in, which means the text may continue
past the crop.

This recovers *clipping*, not misrecognition. A word that was fully visible and
read wrongly looks identical to a word read correctly, and guessing at it is
what turns a wrong answer into a confident wrong answer.

Not wired into hover or manual lookup: the one-shot recapture that used these
helpers was rolled back on 2026-09-20 (see the vision-hover stabilization
checkpoint) and removed in the 2026-09-28 cleanup. The measured helpers stay
as the tested basis for revisiting it.
"""

from __future__ import annotations

from dataclasses import dataclass

from hanly import LookupResult, Point

from .capture import ScreenRect

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


__all__ = [
    "EDGE_TOLERANCE_PIXELS",
    "RECOVERY_MARGIN_PIXELS",
    "ClippedEdges",
    "clipped_edges",
    "recovery_target",
    "widened_region",
]
