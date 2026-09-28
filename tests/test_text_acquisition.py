"""Whether a word may be read without pixels, and what happens when it may not.

Every outcome other than DIRECT means the caller captures the screen and runs
OCR exactly as before, so these cases are the fallback contract.
"""

from __future__ import annotations

import pytest
from hanly import BoundingBox, Point, TextSelection
from hanly_app.text_acquisition import (
    DEFAULT_TIMEOUT_MS,
    Acquisition,
    DirectText,
    DirectTextCoordinator,
    Outcome,
)

_KOREAN = "초대받았어요"
_BOUNDS = BoundingBox(left=100, top=100, right=200, bottom=120)
_UNSET = object()
_INSIDE = Point(150, 110)
_OUTSIDE = Point(400, 400)


class _Provider:
    """A reader that can also answer about one span, as the real adapter does."""

    def __init__(
        self,
        reading: DirectText | None = None,
        error: Exception | None = None,
        *,
        span_bounds: BoundingBox | None | object = _UNSET,
    ):
        self.reading = reading
        self.error = error
        self.calls: list[tuple[Point, int]] = []
        self.spans: list[tuple[int, int]] = []
        self.lines: list[str] = []
        self._span_bounds = span_bounds

    def read_at(self, point: Point, *, timeout_ms: int) -> DirectText | None:
        self.calls.append((point, timeout_ms))
        if self.error is not None:
            raise self.error
        return self.reading

    def refine_bounds(
        self, point: Point, start: int, end: int, *, line: str, timeout_ms: int
    ) -> BoundingBox | None:
        self.spans.append((start, end))
        self.lines.append(line)
        if self._span_bounds is not _UNSET:
            return self._span_bounds  # type: ignore[return-value]
        # A plausible sub-rectangle inside the line it came from.
        return _BOUNDS


def _reading(**overrides: object) -> DirectText:
    fields: dict[str, object] = {
        "text": _KOREAN,
        "cursor_index": 2,
        "bounds": _BOUNDS,
    }
    fields.update(overrides)
    return DirectText(**fields)  # type: ignore[arg-type]


def _acquire(reading: DirectText | None = None, **kwargs: object) -> Acquisition:
    provider = _Provider(reading if reading is not None else _reading())
    coordinator = DirectTextCoordinator(provider, **kwargs)  # type: ignore[arg-type]
    return coordinator.acquire(_INSIDE)


# --- the one case that bypasses OCR -----------------------------------------


def test_containing_korean_text_is_used_directly() -> None:
    result = _acquire()

    assert result.outcome is Outcome.DIRECT
    assert result.used_direct_text
    assert result.selection == TextSelection(
        text=_KOREAN, cursor_index=2, source="accessibility"
    )
    assert result.bounds == _BOUNDS


def test_the_selection_is_attributed_to_the_acquisition_that_read_it() -> None:
    """The one consumer of `TextSelection.source`: which path produced this."""

    assert _acquire().selection is not None
    assert _acquire().selection.source == "accessibility"  # type: ignore[union-attr]


# --- everything else falls back ---------------------------------------------


def test_no_provider_falls_back() -> None:
    assert DirectTextCoordinator(None).acquire(_INSIDE).outcome is Outcome.NO_PROVIDER


def test_a_denied_permission_falls_back_without_asking_the_provider() -> None:
    provider = _Provider(_reading())
    coordinator = DirectTextCoordinator(provider, permitted=lambda: False)

    result = coordinator.acquire(_INSIDE)

    assert result.outcome is Outcome.NO_PERMISSION
    assert provider.calls == []


def test_an_unsupported_element_falls_back() -> None:
    assert _acquire(reading=None) is not None
    provider = _Provider(None)
    assert DirectTextCoordinator(provider).acquire(_INSIDE).outcome is Outcome.UNSUPPORTED


def test_a_secure_field_is_refused_and_carries_nothing() -> None:
    result = _acquire(_reading(text="", secure=True, role="AXSecureTextField"))

    assert result.outcome is Outcome.SECURE
    assert result.selection is None
    assert result.bounds is None


def test_a_range_that_does_not_contain_the_pointer_is_refused() -> None:
    """Accessibility answers with the nearest text when the pointer is on none."""

    provider = _Provider(_reading())
    coordinator = DirectTextCoordinator(provider)

    result = coordinator.acquire(_OUTSIDE)

    assert result.outcome is Outcome.NOT_CONTAINING
    assert result.selection is None


def test_missing_geometry_is_ambiguous_rather_than_trusted() -> None:
    assert _acquire(_reading(bounds=None)).outcome is Outcome.AMBIGUOUS


def test_an_index_past_the_text_is_ambiguous() -> None:
    assert _acquire(_reading(cursor_index=99)).outcome is Outcome.AMBIGUOUS


def test_empty_text_falls_back() -> None:
    assert _acquire(_reading(text="   ")).outcome is Outcome.EMPTY


@pytest.mark.parametrize("text", ["Hanly 2.0", "12345", "hello world"])
def test_a_correct_reading_of_non_korean_text_falls_back(text: str) -> None:
    assert _acquire(_reading(text=text)).outcome is Outcome.NOT_KOREAN


def test_a_timeout_falls_back() -> None:
    provider = _Provider(error=TimeoutError("blocked"))
    assert DirectTextCoordinator(provider).acquire(_INSIDE).outcome is Outcome.TIMED_OUT


def test_an_answer_that_arrived_too_late_is_discarded() -> None:
    """A correct answer about where the pointer *was* is not usable."""

    ticks = iter([0, (DEFAULT_TIMEOUT_MS + 5) * 1_000_000])
    coordinator = DirectTextCoordinator(_Provider(_reading()), clock=lambda: next(ticks))

    assert coordinator.acquire(_INSIDE).outcome is Outcome.TIMED_OUT


def test_a_provider_exception_falls_back_and_names_the_type() -> None:
    provider = _Provider(error=RuntimeError("accessibility died"))

    result = DirectTextCoordinator(provider).acquire(_INSIDE)

    assert result.outcome is Outcome.FAILED
    assert result.detail == "RuntimeError"


def test_a_superseded_request_is_abandoned_before_it_is_used() -> None:
    provider = _Provider(_reading())
    coordinator = DirectTextCoordinator(provider)

    result = coordinator.acquire(_INSIDE, cancelled=lambda: True)

    assert result.outcome is Outcome.SUPERSEDED
    assert result.selection is None


def test_every_outcome_other_than_direct_declines_to_supply_a_selection() -> None:
    for outcome in Outcome:
        if outcome is Outcome.DIRECT:
            continue
        assert not Acquisition(outcome).used_direct_text


def test_the_timeout_must_be_positive() -> None:
    with pytest.raises(ValueError):
        DirectTextCoordinator(None, timeout_ms=0)


# --- narrowing a line to the word the pointer is inside ----------------------


@pytest.mark.parametrize(
    ("text", "cursor_index", "word", "narrowed_index"),
    [
        ("초대받았어요", 2, "초대받았어요", 2),
        ("🙂🙂초대받았어요", 2, "초대받았어요", 0),
        ("🙂🙂초대받았어요", 4, "초대받았어요", 2),
        ("Hello 초대받았어요", 8, "초대받았어요", 2),
        ("초대받았어요 (2026)", 1, "초대받았어요", 1),
        ("초대 받다", 4, "받다", 1),
    ],
)
def test_a_line_is_narrowed_to_the_korean_the_pointer_is_inside(
    text: str, cursor_index: int, word: str, narrowed_index: int
) -> None:
    """A control returns a whole line; the engine answers one word."""

    result = _acquire(_reading(text=text, cursor_index=cursor_index))

    assert result.outcome is Outcome.DIRECT
    assert result.selection is not None
    assert (result.selection.text, result.selection.cursor_index) == (
        word,
        narrowed_index,
    )


def test_a_mixed_line_answers_exactly_as_the_word_alone_would() -> None:
    mixed = _acquire(_reading(text="🙂🙂초대받았어요", cursor_index=2))
    alone = _acquire(_reading(text="초대받았어요", cursor_index=0))

    assert mixed.selection == alone.selection


@pytest.mark.parametrize(
    ("text", "cursor_index"),
    [
        ("🙂🙂초대받았어요", 0),   # the pointer is on the emoji
        ("Hello 초대", 1),        # the pointer is on the Latin word
        ("초대 받다", 2),          # the pointer is on the space between words
    ],
)
def test_a_pointer_resting_outside_korean_falls_back(
    text: str, cursor_index: int
) -> None:
    """The nearest Hangul on the line is not what the reader is pointing at."""

    assert _acquire(_reading(text=text, cursor_index=cursor_index)).outcome is (
        Outcome.NOT_KOREAN
    )


@pytest.mark.parametrize("placeholder", ["\ufffc", "\ufffd", "\n", "\u200b", "\ue000"])
def test_a_placeholder_under_the_pointer_is_left_to_ocr(placeholder: str) -> None:
    """Chromium reports a canvas or image as U+FFFC; its pixels still need OCR."""

    reading = _reading(text=f"초대{placeholder}받다", cursor_index=2)
    assert _acquire(reading).outcome is Outcome.UNSUPPORTED


# --- the retained rectangle belongs to the word, not the line ----------------

_WORD_BOUNDS = BoundingBox(left=150, top=100, right=190, bottom=120)


def _mixed(span_bounds: BoundingBox | None | object = _UNSET) -> _Provider:
    """`Hello 초대받았어요`, whose line rectangle spans the Latin too."""

    return _Provider(
        DirectText(text="Hello 초대받았어요", cursor_index=8, bounds=_BOUNDS),
        span_bounds=span_bounds,
    )


def test_a_narrowed_word_is_retained_by_its_own_rectangle() -> None:
    provider = _mixed(_WORD_BOUNDS)

    result = DirectTextCoordinator(provider).acquire(_INSIDE)

    assert result.outcome is Outcome.DIRECT
    assert result.selection is not None and result.selection.text == "초대받았어요"
    assert result.bounds == _WORD_BOUNDS
    # The span asked about is the Korean run, in characters of the line.
    assert provider.spans == [(6, 12)]


def test_refinement_is_handed_the_exact_line_that_was_read() -> None:
    """The adapter can only refuse changed content if it knows what was read."""

    provider = _mixed(_WORD_BOUNDS)

    DirectTextCoordinator(provider).acquire(_INSIDE)

    assert provider.lines == ["Hello 초대받았어요"]


def test_a_reader_that_cannot_check_the_line_is_refused() -> None:
    """An adapter unaware of the line could return bounds for other content."""

    class _Unchecked(_Provider):
        def refine_bounds(  # type: ignore[override]
            self, point: Point, start: int, end: int, *, timeout_ms: int
        ) -> BoundingBox | None:
            return _WORD_BOUNDS

    provider = _Unchecked(
        DirectText(text="Hello 초대받았어요", cursor_index=8, bounds=_BOUNDS)
    )

    assert DirectTextCoordinator(provider).acquire(_INSIDE).outcome is (
        Outcome.AMBIGUOUS
    )


def test_the_whole_line_rectangle_is_never_reused_for_a_part_of_it() -> None:
    """Retaining the line would hold the answer over `Hello` as well."""

    result = DirectTextCoordinator(_mixed(_WORD_BOUNDS)).acquire(_INSIDE)

    assert result.bounds != _BOUNDS


@pytest.mark.parametrize(
    "span_bounds",
    [
        None,                                        # the control cannot say
        BoundingBox(left=300, top=300, right=340, bottom=320),  # elsewhere entirely
        BoundingBox(left=0, top=0, right=1000, bottom=500),     # outside the line
    ],
)
def test_bounds_that_are_missing_or_wrong_fall_back_to_ocr(
    span_bounds: BoundingBox | None,
) -> None:
    result = DirectTextCoordinator(_mixed(span_bounds)).acquire(_INSIDE)

    assert result.outcome is Outcome.AMBIGUOUS
    assert result.selection is None


def test_a_failure_while_asking_for_bounds_falls_back_to_ocr() -> None:
    class _Failing(_Provider):
        def refine_bounds(
            self, point: Point, start: int, end: int, *, line: str, timeout_ms: int
        ) -> BoundingBox | None:
            raise RuntimeError("the control stopped answering")

    provider = _Failing(
        DirectText(text="Hello 초대받았어요", cursor_index=8, bounds=_BOUNDS)
    )

    assert DirectTextCoordinator(provider).acquire(_INSIDE).outcome is (
        Outcome.AMBIGUOUS
    )


def test_asking_for_bounds_is_given_the_same_deadline() -> None:
    provider = _mixed(_WORD_BOUNDS)
    seen: list[int] = []

    def refine(
        point: Point, start: int, end: int, *, line: str, timeout_ms: int
    ) -> BoundingBox:
        seen.append(timeout_ms)
        return _WORD_BOUNDS

    provider.refine_bounds = refine  # type: ignore[method-assign]

    DirectTextCoordinator(provider, timeout_ms=25).acquire(_INSIDE)

    assert seen == [25]


def test_a_pure_korean_line_keeps_its_own_rectangle() -> None:
    """The line is the word, so nothing narrower has to be asked about."""

    provider = _Provider(_reading(text=_KOREAN, cursor_index=2))

    result = DirectTextCoordinator(provider).acquire(_INSIDE)

    assert result.outcome is Outcome.DIRECT
    assert result.bounds == _BOUNDS


def test_a_reader_without_precise_geometry_refuses_a_narrowed_word() -> None:
    """Approximating the rectangle would retain text this answer is not about."""

    class _LineOnly:
        def read_at(self, point: Point, *, timeout_ms: int) -> DirectText:
            return DirectText(
                text="Hello 초대받았어요", cursor_index=8, bounds=_BOUNDS
            )

    assert DirectTextCoordinator(_LineOnly()).acquire(_INSIDE).outcome is (
        Outcome.AMBIGUOUS
    )


def test_a_reader_without_precise_geometry_still_answers_a_whole_line_word() -> None:
    class _LineOnly:
        def read_at(self, point: Point, *, timeout_ms: int) -> DirectText:
            return DirectText(text=_KOREAN, cursor_index=2, bounds=_BOUNDS)

    result = DirectTextCoordinator(_LineOnly()).acquire(_INSIDE)

    assert result.outcome is Outcome.DIRECT
    assert result.bounds == _BOUNDS


def test_emoji_prefixed_korean_is_retained_by_its_own_rectangle() -> None:
    provider = _Provider(
        DirectText(text="🙂🙂초대받았어요", cursor_index=2, bounds=_BOUNDS),
        span_bounds=_WORD_BOUNDS,
    )

    result = DirectTextCoordinator(provider).acquire(_INSIDE)

    assert result.selection is not None
    assert (result.selection.text, result.selection.cursor_index) == ("초대받았어요", 0)
    assert result.bounds == _WORD_BOUNDS
    assert provider.spans == [(2, 8)]
