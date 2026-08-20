"""Resolve the OCR region under an engine-level target point."""

from collections.abc import Sequence

from .contracts import OCRResult, Point, Quad

_GEOMETRY_EPSILON = 1e-9


class WordResolver:
    """Select one non-empty OCR segment containing a target point.

    The resolver deliberately owns no cursor or capture integration. The
    caller supplies a point in the same normalized coordinate space as the
    OCR quads. A point must be inside the actual quadrilateral: the derived
    integer bounding box is useful for coarse consumers but cannot decide a
    hit for tilted text.

    OCR adapters already provide reading order, so candidate handling keeps
    that order and never depends on set/dict iteration or confidence as an
    implicit tie-breaker. If zero or more than one usable candidate contains
    the target, resolution is ambiguous and returns ``None``.
    """

    @staticmethod
    def resolve(
        ocr_results: Sequence[OCRResult] | None,
        target: Point | None,
    ) -> str | None:
        """Return the sole OCR text hit at ``target`` or ``None``.

        Empty/whitespace-only text, malformed sequence members, degenerate
        quads, a missing target, and zero or multiple geometric hits are all
        normal no-result outcomes. OCR confidence is intentionally not
        thresholded here; confidence policy belongs to the later pipeline.
        """

        if target is None or not isinstance(target, Point) or ocr_results is None:
            return None

        try:
            candidates = tuple(ocr_results)
        except TypeError:
            return None

        hits: list[str] = []
        for result in candidates:
            if not isinstance(result, OCRResult):
                continue
            text = result.text
            if not isinstance(text, str):
                continue
            text = text.strip()
            if not text or not _usable_quad(result.quad):
                continue
            if _contains(result.quad, target):
                hits.append(text)

        if len(hits) != 1:
            return None
        return hits[0]


def _usable_quad(quad: Quad) -> bool:
    """Return whether a quad encloses a usable polygonal area.

    ``Quad`` already rejects a shape with no extent on an axis, but four
    nearly collinear points still pass construction and enclose only float
    noise. An exact ``!= 0.0`` test would call such a sliver usable while the
    containment code, which works to a scaled epsilon, cannot meaningfully
    place a point inside it. The threshold is scaled from the quad's own
    extent for the same reason tolerances are scaled there: a large negative
    desktop origin must not inflate it.
    """

    points = quad.points
    area_twice = sum(
        point.x * points[(index + 1) % len(points)].y
        - point.y * points[(index + 1) % len(points)].x
        for index, point in enumerate(points)
    )
    scale = max(1.0, quad.width, quad.height)
    return abs(area_twice) > _GEOMETRY_EPSILON * scale * scale


def _contains(quad: Quad, target: Point) -> bool:
    """Test a point against a quad, including its boundary.

    Ray casting works for either clockwise or counter-clockwise provider
    output. Boundary checks happen first so a target exactly on an OCR edge
    is not affected by the ray's direction or floating-point division.
    """

    points = quad.points
    xs = [point.x for point in points]
    ys = [point.y for point in points]
    # Scale tolerances from the local geometry rather than absolute desktop
    # coordinates. A monitor can legitimately have a large negative origin;
    # its coordinate magnitude must not turn a one-pixel edge into a huge tolerance.
    scale = max(
        1.0,
        max(xs) - min(xs),
        max(ys) - min(ys),
        abs(target.x - min(xs)),
        abs(target.y - min(ys)),
    )
    tolerance = _GEOMETRY_EPSILON * scale
    if (
        target.x < min(xs) - tolerance
        or target.x > max(xs) + tolerance
        or target.y < min(ys) - tolerance
        or target.y > max(ys) + tolerance
    ):
        return False

    for index, start in enumerate(points):
        end = points[(index + 1) % len(points)]
        if _on_segment(target, start, end, scale):
            return True

    inside = False
    for index, start in enumerate(points):
        end = points[(index + 1) % len(points)]
        crosses_target_y = (start.y > target.y) != (end.y > target.y)
        if not crosses_target_y:
            continue
        intersection_x = start.x + (target.y - start.y) * (end.x - start.x) / (
            end.y - start.y
        )
        if target.x < intersection_x:
            inside = not inside
    return inside


def _on_segment(target: Point, start: Point, end: Point, scale: float) -> bool:
    """Return whether ``target`` lies on the closed segment ``start``-``end``."""

    dx = end.x - start.x
    dy = end.y - start.y
    cross = (target.x - start.x) * dy - (target.y - start.y) * dx
    tolerance = _GEOMETRY_EPSILON * max(
        scale,
        abs(dx),
        abs(dy),
        abs(target.x - start.x),
        abs(target.y - start.y),
    )
    if abs(cross) > tolerance * max(1.0, scale):
        return False

    return (
        min(start.x, end.x) - tolerance <= target.x <= max(start.x, end.x) + tolerance
        and min(start.y, end.y) - tolerance <= target.y <= max(start.y, end.y) + tolerance
    )


__all__ = ["WordResolver"]
