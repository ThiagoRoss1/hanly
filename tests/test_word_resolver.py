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


def test_resolver_returns_none_when_target_hits_multiple_candidates() -> None:
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

    assert WordResolver().resolve(candidates, Point(x=20, y=20)) is None


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
