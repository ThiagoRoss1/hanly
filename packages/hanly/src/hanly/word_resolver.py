"""Resolve the OCR word under an engine-level target point."""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from .contracts import OCRResult, Point, Quad

_GEOMETRY_EPSILON = 1e-9

# Character advances relative to a full-width Hangul syllable. Used to place
# word boundaries along a line quad; see :func:`_advance_weight`.
_FULL_WIDTH_ADVANCE = 1.0
_LATIN_ADVANCE = 0.55
_SPACE_ADVANCE = 0.35
_PUNCTUATION_ADVANCE = 0.35
_NARROW_PUNCTUATION = frozenset(".,:;!?'\"·`^|")


@runtime_checkable
class TargetResolver(Protocol):
    """The resolver seam :class:`LookupPipeline` composes.

    Application composition may substitute a resolver (see the desktop
    package's ``word_resolver_factory``), so the pipeline depends on this
    structural contract rather than on :class:`WordResolver` itself.
    """

    def resolve_target(
        self,
        ocr_results: Sequence[OCRResult] | None,
        target: Point | None,
    ) -> tuple[OCRResult, str] | None:
        """Return the OCR region containing ``target`` and the word at it."""


class WordResolver:
    """Select the Korean word under a target point.

    The resolver deliberately owns no cursor or capture integration. The
    caller supplies a point in the same normalized coordinate space as the
    OCR quads. A point must be inside the actual quadrilateral: the derived
    integer bounding box is useful for coarse consumers but cannot decide a
    hit for tilted text. PaddleOCR commonly returns one line-level quad, so a
    second, local hit test maps the target's position along that quad to the
    whitespace-delimited word inside the recognized text.

    OCR adapters already provide reading order, so candidate handling keeps
    that order and never depends on set/dict iteration or confidence as an
    implicit tie-breaker. A target inside no candidate returns ``None``, as
    does a target in the whitespace between words.

    Several candidates may legitimately contain one target: an OCR adapter
    reading a dense paragraph emits line quads that overlap vertically where
    the lines are tightly set, so a point near a line boundary falls inside
    two of them. That is ordinary output rather than ambiguity, and refusing
    to answer showed up as a popup that worked on loosely spaced text and
    silently failed on a chat transcript. The line the point sits furthest
    inside wins.
    """

    @staticmethod
    def resolve(
        ocr_results: Sequence[OCRResult] | None,
        target: Point | None,
    ) -> str | None:
        """Return the whitespace-delimited OCR word at ``target``.

        Empty/whitespace-only text, malformed sequence members, degenerate
        quads, a missing target, and zero or multiple geometric hits are all
        normal no-result outcomes. OCR confidence is intentionally not
        thresholded here; confidence policy belongs to the later pipeline.
        """

        resolution = WordResolver.resolve_target(ocr_results, target)
        return None if resolution is None else resolution[1]

    @staticmethod
    def resolve_target(
        ocr_results: Sequence[OCRResult] | None,
        target: Point | None,
    ) -> tuple[OCRResult, str] | None:
        """Return the selected OCR region and word at ``target``.

        The region is retained so the pipeline can apply confidence policy to
        the OCR evidence that actually contains the target, even when that
        evidence contains several whitespace-delimited words.
        """

        if target is None or not isinstance(target, Point) or ocr_results is None:
            return None

        try:
            candidates = tuple(ocr_results)
        except TypeError:
            return None

        hits: list[OCRResult] = []
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
                hits.append(result)

        if not hits:
            return None

        result = hits[0] if len(hits) == 1 else _most_interior(hits, target)
        word = _word_at_target(result.text, result.quad, target)
        if word is None:
            return None
        return result, word


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


def _word_at_target(text: str, quad: Quad, target: Point) -> str | None:
    """Map a target's local horizontal position to one OCR word.

    The axis derived by :func:`_text_axis` is stable for the tilted
    quadrilaterals emitted by an OCR adapter. The OCR contract exposes only the
    line quad, so character positions are estimated from per-script advance
    weights rather than measured. Treating every character as equally wide is
    what this deliberately avoids: a space is roughly a third the width of a
    Hangul syllable, so a uniform mapping gives whitespace an oversized hit
    region and shifts every character after it, which reads to a user as a dead
    zone over a real glyph.
    """

    if not text:
        return None

    fraction = _horizontal_fraction(quad, target)
    if fraction is None:
        return None

    index = _character_index(text, fraction)
    if text[index].isspace():
        return None

    start = index
    while start > 0 and not text[start - 1].isspace():
        start -= 1

    end = index + 1
    while end < len(text) and not text[end].isspace():
        end += 1

    word = text[start:end].strip()
    return word or None


def _most_interior(hits: list[OCRResult], target: Point) -> OCRResult:
    """Return the candidate whose text line the target sits furthest inside.

    Overlap between OCR line quads is vertical, so vertical margin separates
    them, but measured as a fraction of the line's own height, otherwise a
    tall quad always outranks the shorter one nested inside it. A genuine
    nesting scores equally on that fraction and is settled by area, which
    prefers the more specific region. Provider reading order breaks anything
    still equal.
    """

    def rank(indexed: tuple[int, OCRResult]) -> tuple[float, float, int]:
        index, result = indexed
        box = result.bounding_box
        height = max(1, box.bottom - box.top)
        margin = min(target.y - box.top, box.bottom - target.y) / height
        area = (box.right - box.left) * (box.bottom - box.top)
        return (-margin, area, index)

    return min(enumerate(hits), key=rank)[1]


def _character_index(text: str, fraction: float) -> int:
    """Return the character whose estimated advance span contains ``fraction``."""

    advances = [_advance_weight(character) for character in text]
    total = sum(advances)
    if total <= 0.0:
        return min(len(text) - 1, max(0, int(fraction * len(text))))

    travelled = fraction * total
    consumed = 0.0
    for index, advance in enumerate(advances):
        consumed += advance
        if travelled < consumed:
            return index
    return len(text) - 1


def _advance_weight(character: str) -> float:
    """Return one character's width relative to a full-width Hangul syllable.

    These are coarse typographic ratios, not font metrics. They only need to be
    good enough to keep word boundaries near their rendered position, and being
    approximately right is a large improvement over assuming every character is
    equally wide.
    """

    if character.isspace():
        return _SPACE_ADVANCE
    if character in _NARROW_PUNCTUATION:
        return _PUNCTUATION_ADVANCE
    if character.isascii():
        return _LATIN_ADVANCE
    return _FULL_WIDTH_ADVANCE


def _horizontal_fraction(quad: Quad, target: Point) -> float | None:
    """Return target position along a quad's left-to-right text axis."""

    axis = _text_axis(quad)
    if axis is None:
        return None

    left, right = axis
    dx = right.x - left.x
    dy = right.y - left.y
    length_squared = _squared_length(left, right)

    fraction = ((target.x - left.x) * dx + (target.y - left.y) * dy) / length_squared
    tolerance = _GEOMETRY_EPSILON * max(1.0, abs(dx), abs(dy))
    if fraction < -tolerance or fraction > 1 + tolerance:
        return None
    return min(1.0, max(0.0, fraction))


def _text_axis(quad: Quad) -> tuple[Point, Point] | None:
    """Return the midpoints of the two edges that cap a text line's ends.

    Only the quad's shape is used. `Quad` fixes corner order no further than
    "the order the provider reported them, conventionally clockwise", so the
    starting corner is not part of the contract and cannot be assumed to be
    the top-left one. Of the two opposite edge pairs, the shorter pair caps
    the ends of a line, which holds for tilted quads as well as upright ones.
    """

    points = quad.points
    edges = tuple((points[index], points[(index + 1) % 4]) for index in range(4))
    caps = min(
        ((edges[0], edges[2]), (edges[1], edges[3])),
        key=lambda pair: sum(_squared_length(*edge) for edge in pair),
    )

    start = _midpoint(*caps[0])
    end = _midpoint(*caps[1])
    if _squared_length(start, end) <= _GEOMETRY_EPSILON:
        return None

    # Shape alone leaves the reading direction ambiguous by 180 degrees. V1
    # resolves Korean text that reads left to right on screen, so the cap with
    # the smaller x starts the axis; y breaks the tie for near-vertical quads.
    if (end.x, end.y) < (start.x, start.y):
        start, end = end, start
    return start, end


def _midpoint(start: Point, end: Point) -> Point:
    return Point(x=(start.x + end.x) / 2, y=(start.y + end.y) / 2)


def _squared_length(start: Point, end: Point) -> float:
    dx = end.x - start.x
    dy = end.y - start.y
    return dx * dx + dy * dy


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


__all__ = ["TargetResolver", "WordResolver"]
