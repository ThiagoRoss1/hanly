"""Focused tests for resolving a hovered Korean OCR segment."""

from hanly import BoundingBox, OCRResult, Point, Quad
from hanly.word_resolver import WordResolver
from hanly_fixtures.korean import KOREAN_OCR_RESULTS


def _result(text: str, quad: Quad) -> OCRResult:
    return OCRResult(text=text, confidence=0.9, quad=quad)


def test_resolver_returns_the_text_of_the_quad_containing_the_target() -> None:
    resolver = WordResolver()

    assert resolver.resolve(KOREAN_OCR_RESULTS, Point(x=24, y=24)) == "책을"
    assert resolver.resolve(KOREAN_OCR_RESULTS, Point(x=100, y=24)) == "읽습니다."


def test_resolver_selects_a_word_inside_a_line_level_ocr_region() -> None:
    line = _result(
        "책을 읽습니다.",
        Quad.from_bounding_box(BoundingBox(left=0, top=0, right=192, bottom=48)),
    )

    assert WordResolver.resolve((line,), Point(x=24, y=24)) == "책을"
    assert WordResolver.resolve((line,), Point(x=120, y=24)) == "읽습니다."
    # Word boundaries follow per-script advance widths, so the space occupies
    # only the narrow band its glyph actually renders in.
    assert WordResolver.resolve((line,), Point(x=50, y=24)) == "책을"
    assert WordResolver.resolve((line,), Point(x=62, y=24)) is None


def test_resolver_maps_word_selection_along_a_tilted_line_quad() -> None:
    line = _result(
        "책을 읽습니다.",
        Quad(
            p1=Point(x=0, y=10),
            p2=Point(x=192, y=0),
            p3=Point(x=192, y=48),
            p4=Point(x=0, y=58),
        ),
    )

    # The target follows the slanted text axis rather than the axis-aligned
    # bounding box, and lands inside the second whitespace-delimited word.
    assert WordResolver.resolve((line,), Point(x=120, y=29)) == "읽습니다."


def test_word_selection_is_invariant_to_the_quads_starting_corner() -> None:
    """`Quad` fixes corner order only up to the starting corner, so the same
    physical quad and target must resolve to the same word for every valid
    rotation of that order, including the clockwise top-right start."""

    corners = Quad.from_bounding_box(
        BoundingBox(left=0, top=0, right=192, bottom=48)
    ).points
    rotations = tuple(
        Quad(*(corners[(start + offset) % 4] for offset in range(4))) for start in range(4)
    )
    reversed_orders = tuple(
        Quad(*(corners[(start - offset) % 4] for offset in range(4))) for start in range(4)
    )

    for quad in rotations + reversed_orders:
        line = _result("책을 읽습니다.", quad)
        assert WordResolver.resolve((line,), Point(x=24, y=24)) == "책을"
        assert WordResolver.resolve((line,), Point(x=120, y=24)) == "읽습니다."


def test_word_selection_is_invariant_to_starting_corner_on_a_tilted_quad() -> None:
    corners = Quad(
        p1=Point(x=0, y=10),
        p2=Point(x=192, y=0),
        p3=Point(x=192, y=48),
        p4=Point(x=0, y=58),
    ).points

    for start in range(4):
        quad = Quad(*(corners[(start + offset) % 4] for offset in range(4)))
        line = _result("책을 읽습니다.", quad)
        assert WordResolver.resolve((line,), Point(x=24, y=29)) == "책을"
        assert WordResolver.resolve((line,), Point(x=120, y=29)) == "읽습니다."


def test_resolver_uses_true_quad_hit_testing_not_its_derived_box() -> None:
    tilted = Quad(
        p1=Point(x=10.0, y=10.0),
        p2=Point(x=40.0, y=0.0),
        p3=Point(x=50.0, y=20.0),
        p4=Point(x=20.0, y=30.0),
    )
    result = _result("한글", tilted)

    # This point is in the enclosing BoundingBox, but above the tilted edge.
    assert result.bounding_box == BoundingBox(left=10, top=0, right=50, bottom=30)
    assert WordResolver().resolve((result,), Point(x=12.0, y=2.0)) is None


def test_resolver_accepts_a_target_on_the_quad_boundary() -> None:
    result = _result(
        "한글",
        Quad.from_bounding_box(BoundingBox(left=10, top=10, right=40, bottom=30)),
    )

    assert WordResolver().resolve((result,), Point(x=10.0, y=20.0)) == "한글"


def test_resolver_returns_none_for_empty_or_unusable_inputs() -> None:
    resolver = WordResolver()
    unusable = _result(
        "  \t\n",
        Quad.from_bounding_box(BoundingBox(left=0, top=0, right=10, bottom=10)),
    )

    assert resolver.resolve((), Point(x=1, y=1)) is None
    assert resolver.resolve((unusable,), Point(x=1, y=1)) is None
    assert resolver.resolve((object(),), Point(x=1, y=1)) is None  # type: ignore[arg-type]
    assert resolver.resolve(KOREAN_OCR_RESULTS, None) is None  # type: ignore[arg-type]


def test_resolver_skips_a_near_collinear_sliver_quad() -> None:
    """Four almost-collinear points pass Quad construction but enclose only
    float noise, so the resolver must treat them as unusable rather than as a
    hit its containment maths cannot place a point inside."""

    sliver = _result(
        "책",
        Quad(
            p1=Point(0.0, 0.0),
            p2=Point(100.0, 30.0),
            p3=Point(100.0, 30.0 + 1e-12),
            p4=Point(0.0, 1e-12),
        ),
    )

    assert WordResolver.resolve((sliver,), Point(x=50.0, y=15.0)) is None


def test_resolver_still_accepts_a_thin_but_real_quad() -> None:
    thin = _result(
        "책",
        Quad.from_bounding_box(BoundingBox(left=0, top=0, right=120, bottom=2)),
    )

    assert WordResolver.resolve((thin,), Point(x=60.0, y=1.0)) == "책"


def test_a_nested_candidate_wins_over_the_region_enclosing_it() -> None:
    """Both regions contain the point equally well by proportion, so the more
    specific one is the better evidence."""

    candidates = (
        _result(
            "책",
            Quad.from_bounding_box(BoundingBox(left=0, top=0, right=40, bottom=40)),
        ),
        _result(
            "을",
            Quad.from_bounding_box(BoundingBox(left=10, top=10, right=30, bottom=30)),
        ),
    )

    assert WordResolver().resolve(candidates, Point(x=20, y=20)) == "을"


def test_overlapping_text_lines_resolve_to_the_line_the_point_sits_inside() -> None:
    """A dense paragraph makes an OCR adapter emit line quads that overlap
    vertically. Refusing to answer there is what made the popup work on loosely
    spaced text and silently fail on a chat transcript."""

    upper = _result(
        "읽습니다.",
        Quad.from_bounding_box(BoundingBox(left=40, top=6, right=120, bottom=30)),
    )
    lower = _result(
        "책은",
        Quad.from_bounding_box(BoundingBox(left=30, top=27, right=66, bottom=43)),
    )
    candidates = (upper, lower)

    # Deep inside either line, that line answers.
    assert WordResolver().resolve(candidates, Point(x=60, y=12)) == "읽습니다."
    assert WordResolver().resolve(candidates, Point(x=45, y=40)) == "책은"
    # Inside the two-pixel overlap, one of them still answers.
    assert WordResolver().resolve(candidates, Point(x=50, y=28)) is not None


def test_resolver_keeps_candidate_handling_deterministic_in_provider_order() -> None:
    first = _result(
        "첫째",
        Quad.from_bounding_box(BoundingBox(left=0, top=0, right=20, bottom=20)),
    )
    second = _result(
        "둘째",
        Quad.from_bounding_box(BoundingBox(left=20, top=0, right=40, bottom=20)),
    )
    resolver = WordResolver()

    assert resolver.resolve((first, second), Point(x=10, y=10)) == "첫째"
    assert resolver.resolve((first, second), Point(x=30, y=10)) == "둘째"
    assert resolver.resolve((first, second), Point(x=10, y=10)) == "첫째"


def test_word_boundaries_follow_rendered_character_widths() -> None:
    """A space is roughly a third the width of a Hangul syllable. Treating every
    character as equally wide gave whitespace an oversized hit region, which a
    user experiences as a dead zone sitting over a real glyph."""

    line = _result(
        "책을 읽습니다.",
        Quad.from_bounding_box(BoundingBox(left=0, top=0, right=192, bottom=48)),
    )

    dead = [
        x for x in range(0, 192) if WordResolver.resolve((line,), Point(x=x, y=24)) is None
    ]

    # The whole gap sits between the two words rather than intruding on either.
    assert 0 < len(dead) <= 16
    assert all(WordResolver.resolve((line,), Point(x=x, y=24)) is None for x in dead)
    assert max(dead) - min(dead) == len(dead) - 1
    assert WordResolver.resolve((line,), Point(x=min(dead) - 1, y=24)) == "책을"
    assert WordResolver.resolve((line,), Point(x=max(dead) + 1, y=24)) == "읽습니다."


def test_latin_and_punctuation_advances_do_not_shift_korean_words() -> None:
    line = _result(
        "책을 ok.",
        Quad.from_bounding_box(BoundingBox(left=0, top=0, right=100, bottom=24)),
    )

    assert WordResolver.resolve((line,), Point(x=10, y=12)) == "책을"
    assert WordResolver.resolve((line,), Point(x=90, y=12)) == "ok."
