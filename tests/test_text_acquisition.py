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
_INSIDE = Point(150, 110)
_OUTSIDE = Point(400, 400)


class _Provider:
    def __init__(self, reading: DirectText | None = None, error: Exception | None = None):
        self.reading = reading
        self.error = error
        self.calls: list[tuple[Point, int]] = []

    def read_at(self, point: Point, *, timeout_ms: int) -> DirectText | None:
        self.calls.append((point, timeout_ms))
        if self.error is not None:
            raise self.error
        return self.reading


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
