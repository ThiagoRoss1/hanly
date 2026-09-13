"""A popup the cursor can actually reach, and one that still gets out of the way.

The retained target is what the cursor may rest on without Hanly capturing,
recognizing, or dismissing anything: the word the answer came from, plus the
popup frame, plus the narrow corridor between them. Every other movement is a
real exit, and dismisses at once. These drive the real hover runtime with
schedulers the test fires by hand.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from hanly import (
    BoundingBox,
    DictionaryEntry,
    LookupContext,
    LookupResult,
    LookupStatus,
    OCRResult,
    Point,
    Quad,
)
from hanly.word_resolver import WordResolver
from hanly_app.capture import ScreenRect
from hanly_app.hover_lookup import HoverLookupRuntime
from hanly_app.hover_target import (
    POPUP_TRANSFER_MS,
    WORD_MARGIN_PIXELS,
    CaptureOrigins,
    RetainedTarget,
    expanded,
    screen_rect,
)
from hanly_app.lookup_controller import LookupController

from tests.test_hover_lookup import (  # deliberate reuse of one runtime's doubles
    _Capture,
    _ListenerFactory,
    _QueueDispatcher,
    _Scheduler,
    _Worker,
)


def _quad(left: float, top: float, right: float, bottom: float) -> Quad:
    return Quad.from_bounding_box(BoundingBox(int(left), int(top), int(right), int(bottom)))


def test_the_resolver_reports_the_word_not_the_whole_recognized_line() -> None:
    """Protecting the line would freeze hover over every word on it."""

    region = OCRResult(text="책을 읽습니다", confidence=0.9, quad=_quad(0, 0, 120, 20))

    first = WordResolver.word_bounds(region, Point(10.0, 10.0))
    second = WordResolver.word_bounds(region, Point(100.0, 10.0))

    assert first is not None and second is not None
    assert first.right < second.left
    assert first.left >= 0
    assert second.right <= 120
    assert first.top == 0 and first.bottom == 20


def test_a_target_in_whitespace_between_words_has_no_geometry() -> None:
    region = OCRResult(text="책을 읽습니다", confidence=0.9, quad=_quad(0, 0, 120, 20))
    resolution = WordResolver.resolve_target((region,), Point(56.0, 10.0))

    if resolution is None:
        assert WordResolver.word_bounds(region, Point(56.0, 10.0)) is None


def test_the_pipeline_carries_the_word_geometry_into_the_result() -> None:
    from hanly import LookupPipeline, TokenAnalysis

    class _OCR:
        def recognize(self, image: object) -> tuple[OCRResult, ...]:
            del image
            return (OCRResult(text="책을 읽습니다", confidence=0.9, quad=_quad(0, 0, 120, 20)),)

    class _Morphology:
        def analyze(self, text: str) -> tuple[TokenAnalysis, ...]:
            del text
            return (TokenAnalysis(token="책", lemma="책"),)

    class _Dictionary:
        def lookup(self, lemma: str) -> tuple[DictionaryEntry, ...]:
            del lemma
            return (DictionaryEntry(headword="책", definitions=("book",)),)

    from hanly import PixelFormat, ROIImage

    pipeline = LookupPipeline(_OCR(), _Morphology(), _Dictionary())
    image = ROIImage(1, 1, PixelFormat.RGB_888, b"\x00\x00\x00")

    result = pipeline.lookup(image, Point(10.0, 10.0))

    assert result.status is LookupStatus.SUCCESS
    assert result.context is not None
    assert result.context.word_region is not None
    assert result.context.word_region.right < 120


def test_a_word_is_placed_on_the_screen_its_capture_came_from() -> None:
    """A monitor left of the primary one has a negative origin, and a result
    arrives after the cursor has usually moved on."""

    region = ScreenRect(left=-1800, top=-200, width=200, height=100)

    placed = screen_rect(region, BoundingBox(10, 20, 40, 50))

    assert placed == ScreenRect(left=-1790, top=-180, width=30, height=30)


def test_the_protected_area_is_a_union_and_never_a_hull() -> None:
    """The hull of a word and a popup placed diagonally covers whatever is
    between them, which is usually the next word the user wants."""

    target = RetainedTarget(
        1,
        word=ScreenRect(100, 100, 40, 20),
        popup=ScreenRect(300, 300, 320, 180),
    )

    assert target.protects(Point(110.0, 105.0))
    assert target.protects(Point(400.0, 350.0))
    assert not target.protects(Point(220.0, 220.0))


def test_the_word_region_is_expanded_by_a_small_margin() -> None:
    target = RetainedTarget(1, word=ScreenRect(100, 100, 40, 20))

    assert target.protects(Point(98.0, 100.0))
    assert not target.protects(Point(100.0 - WORD_MARGIN_PIXELS - 1, 100.0))
    assert expanded(ScreenRect(0, 0, 10, 10), 4) == ScreenRect(-4, -4, 18, 18)


def test_origins_are_kept_per_request_and_bounded() -> None:
    origins = CaptureOrigins(limit=2)
    origins.remember(1, ScreenRect(0, 0, 10, 10))
    origins.remember(2, ScreenRect(10, 10, 10, 10))
    origins.remember(3, ScreenRect(20, 20, 10, 10))

    assert origins.origin(1) is None
    assert origins.origin(3) == ScreenRect(20, 20, 10, 10)
    assert origins.origin(None) is None


class _Hover:
    """One real hover runtime, with every timer under the test's control."""

    def __init__(self) -> None:
        self.dispatcher = _QueueDispatcher()
        self.scheduler = _Scheduler()
        self.exit_scheduler = _Scheduler()
        self.listeners = _ListenerFactory()
        self.capture = _Capture()
        self.cleared = 0
        self.controller = LookupController(
            lambda: _Worker(), lambda _result: None, result_dispatcher=self.dispatcher
        )
        self.runtime = HoverLookupRuntime(
            self.controller,
            self.capture,
            delay_ms=80,
            scheduler=self.scheduler,
            exit_scheduler=self.exit_scheduler,
            dispatcher=self.dispatcher,
            listener_factory=self.listeners,
            on_invalidate=self._cleared,
        )

    def _cleared(self) -> None:
        self.cleared += 1

    def start(self) -> None:
        self.runtime.start()
        assert self.controller.wait_until_ready(timeout=2)
        self.drain()

    def drain(self) -> None:
        while self.dispatcher.pending:
            self.dispatcher.drain_one()

    def move(self, x: int, y: int) -> None:
        self.listeners.listeners[0].emit(x, y)
        self.drain()

    def retain(self, word: ScreenRect, popup: ScreenRect | None = None) -> None:
        self.runtime.retain(RetainedTarget(1, word, popup))

    def transfer_handle(self) -> object:
        """The crossing's own timer, which never shares the dwell's."""

        for delay, handle in reversed(self.exit_scheduler.calls):
            if delay == pytest.approx(POPUP_TRANSFER_MS):
                return handle
        raise AssertionError("no popup crossing is scheduled")

    def fire_transfer(self) -> None:
        handle = self.transfer_handle()
        assert not getattr(handle, "cancelled")
        getattr(handle, "callback")()

    def close(self) -> None:
        self.runtime.shutdown()


@pytest.fixture
def hover() -> Iterator[_Hover]:
    harness = _Hover()
    harness.start()
    yield harness
    harness.close()


def test_moving_inside_the_word_captures_nothing_and_keeps_the_popup(
    hover: _Hover,
) -> None:
    hover.retain(ScreenRect(100, 100, 40, 20))
    hover.scheduler.calls.clear()

    hover.move(110, 105)
    hover.move(120, 108)

    assert hover.capture.cursors == []
    assert hover.cleared == 0
    assert hover.scheduler.calls == []


def test_moving_into_the_popup_keeps_it_open(hover: _Hover) -> None:
    hover.retain(ScreenRect(100, 100, 40, 20), ScreenRect(160, 120, 320, 180))
    hover.scheduler.calls.clear()

    hover.move(300, 200)

    assert hover.cleared == 0
    assert hover.capture.cursors == []


def test_crossing_the_gap_towards_the_popup_keeps_the_answer(hover: _Hover) -> None:
    """The corridor exists so the popup can be reached, and only for that."""

    hover.retain(ScreenRect(100, 100, 40, 20), ScreenRect(300, 100, 320, 180))

    hover.move(200, 110)

    assert hover.cleared == 0
    assert hover.capture.cursors == []
    assert hover.runtime.retained_target is not None

    # The crossing is capped: a cursor parked in the gap does not hold it.
    hover.fire_transfer()
    assert hover.cleared == 1
    assert hover.runtime.retained_target is None


def test_leaving_the_word_in_any_other_direction_dismisses_at_once(
    hover: _Hover,
) -> None:
    """The defect this replaces: every exit paid a delay, and on the real Qt
    scheduler the next dwell took the delay's timer, so nothing dismissed."""

    hover.retain(ScreenRect(100, 100, 40, 20), ScreenRect(300, 100, 320, 180))

    hover.move(120, 400)

    assert hover.cleared == 1
    assert hover.runtime.retained_target is None


def test_a_retained_word_with_no_popup_dismisses_on_the_first_exit(
    hover: _Hover,
) -> None:
    hover.retain(ScreenRect(100, 100, 40, 20))

    hover.move(200, 200)

    assert hover.cleared == 1
    assert hover.runtime.retained_target is None


def test_turning_back_while_crossing_dismisses_the_answer(hover: _Hover) -> None:
    hover.retain(ScreenRect(100, 100, 40, 20), ScreenRect(300, 100, 320, 180))
    hover.move(220, 110)
    assert hover.cleared == 0

    hover.move(180, 110)

    assert hover.cleared == 1
    assert hover.runtime.retained_target is None


def test_entering_the_popup_ends_the_crossing(hover: _Hover) -> None:
    hover.retain(ScreenRect(100, 100, 40, 20), ScreenRect(300, 100, 320, 180))
    hover.move(220, 110)
    crossing = hover.transfer_handle()

    hover.move(400, 150)

    assert getattr(crossing, "cancelled")
    assert hover.cleared == 0
    assert hover.runtime.retained_target is not None


def test_a_real_exit_arms_a_dwell_for_the_next_word_and_no_exit_delay(
    hover: _Hover,
) -> None:
    hover.retain(ScreenRect(100, 100, 40, 20))
    hover.scheduler.calls.clear()
    hover.exit_scheduler.calls.clear()

    hover.move(400, 400)

    assert [delay for delay, _handle in hover.scheduler.calls] == [80]
    assert hover.exit_scheduler.calls == []


def test_a_newer_result_cannot_be_dismissed_by_an_old_crossing(hover: _Hover) -> None:
    hover.retain(ScreenRect(100, 100, 40, 20), ScreenRect(300, 100, 320, 180))
    hover.move(220, 110)
    stale = hover.transfer_handle()

    hover.runtime.retain(RetainedTarget(2, ScreenRect(400, 400, 40, 20)))
    getattr(stale, "callback")()

    assert hover.cleared == 0
    retained = hover.runtime.retained_target
    assert retained is not None and retained.lookup_request_id == 2


def test_retaining_a_new_result_cancels_the_crossing_of_the_old_one(
    hover: _Hover,
) -> None:
    hover.retain(ScreenRect(100, 100, 40, 20), ScreenRect(300, 100, 320, 180))
    hover.move(220, 110)
    stale = hover.transfer_handle()

    hover.runtime.retain(RetainedTarget(2, ScreenRect(400, 400, 40, 20)))

    assert getattr(stale, "cancelled")


def test_pausing_forgets_the_retained_target(hover: _Hover) -> None:
    hover.retain(ScreenRect(100, 100, 40, 20))

    hover.runtime.pause()

    assert hover.runtime.retained_target is None


def test_invalidating_forgets_the_retained_target(hover: _Hover) -> None:
    hover.retain(ScreenRect(100, 100, 40, 20))

    hover.runtime.invalidate()

    assert hover.runtime.retained_target is None


def test_movement_with_nothing_retained_clears_immediately(hover: _Hover) -> None:
    """Unchanged behaviour for the results that are never shown at all."""

    hover.move(400, 400)

    assert hover.cleared == 1


def _success_with_geometry() -> LookupResult:
    return LookupResult(
        status=LookupStatus.SUCCESS,
        entries=(DictionaryEntry(headword="책", definitions=("book",)),),
        context=LookupContext(text="책을", lemma="책", word_region=BoundingBox(10, 20, 40, 50)),
    )


def test_a_presented_result_retains_the_word_its_own_capture_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.test_hover_lookup import _manual_composition

    manual, _dispatcher, _listeners, _capture, _results = _manual_composition()
    origins = _origins_of(manual)
    origins.remember(7, ScreenRect(500, 400, 200, 100))

    manual.note_presented(_success_with_geometry(), 7, ScreenRect(700, 500, 320, 180))

    hover = manual.hover_runtime
    assert hover is not None
    retained = hover.retained_target
    assert retained is not None
    assert retained.word == ScreenRect(510, 420, 30, 30)
    assert retained.popup == ScreenRect(700, 500, 320, 180)
    manual.shutdown()


def test_a_result_without_geometry_retains_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.test_hover_lookup import _manual_composition

    manual, _dispatcher, _listeners, _capture, _results = _manual_composition()
    plain = LookupResult(
        status=LookupStatus.SUCCESS,
        entries=(DictionaryEntry(headword="책", definitions=("book",)),),
    )

    manual.note_presented(plain, 7, None)

    hover = manual.hover_runtime
    assert hover is not None
    assert hover.retained_target is None
    manual.shutdown()


def _origins_of(manual: object) -> CaptureOrigins:
    origins = getattr(manual, "_origins")
    assert isinstance(origins, CaptureOrigins)
    return origins


def test_a_capture_target_change_forgets_the_retained_target() -> None:
    from hanly_app.config import CaptureMode

    from tests.test_hover_lookup import _manual_composition

    manual, _dispatcher, _listeners, _capture, _results = _manual_composition()
    _origins_of(manual).remember(7, ScreenRect(500, 400, 200, 100))
    manual.note_presented(_success_with_geometry(), 7, None)
    hover = manual.hover_runtime
    assert hover is not None and hover.retained_target is not None

    manual.set_capture_preferences(
        capture_mode=CaptureMode.FULL_MONITOR, monitor=2, region=None
    )

    assert hover.retained_target is None
    manual.shutdown()
