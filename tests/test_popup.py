from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import Event, Thread

import pytest
from hanly import (
    BoundingBox,
    DictionaryEntry,
    DictionarySense,
    HanlyError,
    LookupContext,
    LookupResult,
    LookupStatus,
    OCRResult,
    PixelFormat,
    Point,
    Quad,
    ROIImage,
    TokenAnalysis,
)
from hanly_app.config import TechnicalDetailLevel
from hanly_app.lookup_controller import LookupController
from hanly_app.popup import (
    PopupController,
    PopupPosition,
    PopupSize,
    ScreenGeometry,
    format_lookup_result,
)

from tests.hanly_fixtures.unchecked import unchecked

_IMAGE = ROIImage(1, 1, PixelFormat.GRAYSCALE_8, b"\x00")


def _success() -> LookupResult:
    evidence = OCRResult(
        text="먹었습니다",
        confidence=0.93,
        quad=Quad.from_bounding_box(BoundingBox(0, 0, 100, 24)),
    )
    return LookupResult(
        status=LookupStatus.SUCCESS,
        entries=(
            DictionaryEntry(
                headword="먹다",
                definitions=("to eat", "consume"),
                part_of_speech="verb",
                source="krdict",
                hanja="食",
            ),
        ),
        context=LookupContext(
            text="먹었습니다",
            lemma="먹다",
            ocr_results=(evidence,),
            selected_ocr=evidence,
            analyses=(
                TokenAnalysis("먹", "먹다", "VV"),
                TokenAnalysis("었", "었", "EP"),
                TokenAnalysis("습니다", "습니다", "EF"),
            ),
        ),
    )


def _non_success(status: LookupStatus) -> LookupResult:
    return LookupResult(
        status=status,
        diagnostics=("diagnostic detail",),
        error=HanlyError("provider unavailable") if status is LookupStatus.ERROR else None,
    )


@dataclass
class _RecordingView:
    events: list[tuple[str, LookupResult | None, PopupPosition | None]]

    def show_result(self, result: LookupResult, position: PopupPosition) -> None:
        self.events.append(("show", result, position))

    def update_result(self, result: LookupResult, position: PopupPosition) -> None:
        self.events.append(("update", result, position))

    def hide(self) -> None:
        self.events.append(("hide", None, None))

    def close(self) -> None:
        self.events.append(("close", None, None))


class _ResizableView(_RecordingView):
    def __init__(self) -> None:
        super().__init__([])
        self.resize_handler: Callable[[PopupSize], None] | None = None
        self.positions: list[PopupPosition] = []

    def set_resize_handler(self, handler: Callable[[PopupSize], None]) -> None:
        self.resize_handler = handler

    def reposition(self, position: PopupPosition) -> None:
        self.positions.append(position)


def test_format_lookup_result_covers_success_normal_outcomes_and_error() -> None:
    success = format_lookup_result(_success())
    assert success.title == "먹다"
    assert success.entry is not None
    assert "to eat" in success.entry.definitions
    assert success.entry.hanja == "食"
    assert success.surface == "먹었습니다"
    assert [piece.role for piece in success.analysis] == [
        "verb stem",
        "past",
        "formal polite",
    ]

    for status in (LookupStatus.EMPTY, LookupStatus.NOT_FOUND, LookupStatus.UNUSABLE):
        content = format_lookup_result(_non_success(status))
        assert content.title
        assert content.body
        assert content.technical_lines == ()

    error = format_lookup_result(_non_success(LookupStatus.ERROR))
    assert error.title == "Lookup failed"
    assert "provider unavailable" not in error.body


def test_technical_details_are_off_basic_and_full_from_real_evidence() -> None:
    off = format_lookup_result(_success(), TechnicalDetailLevel.OFF)
    basic = format_lookup_result(_success(), TechnicalDetailLevel.BASIC)
    full = format_lookup_result(_success(), TechnicalDetailLevel.FULL)

    assert off.technical_lines == ()
    assert basic.technical_lines == ("OCR 93%", "KRDICT")
    assert full.technical_lines[:3] == ("OCR 93%", "KRDICT", "SUCCESS")


def test_presenter_keeps_multiple_entries_and_omits_missing_optional_metadata() -> None:
    result = LookupResult(
        status=LookupStatus.SUCCESS,
        entries=(
            DictionaryEntry("문화", ("culture",), "noun", source="krdict"),
            DictionaryEntry("문화", ("civilization",), "noun", source="krdict"),
        ),
        context=LookupContext(
            text="문화는",
            lemma="문화",
            analyses=(
                TokenAnalysis("문화", "문화", "NNG"),
                TokenAnalysis("는", "는", "JX"),
            ),
        ),
    )

    content = format_lookup_result(result)

    assert content.entry is not None
    assert content.entry.hanja is None
    assert content.entry.vocabulary_level is None
    assert content.other_entries[0].definitions == ("civilization",)
    assert [(piece.text, piece.role) for piece in content.analysis] == [
        ("문화", "noun"),
        ("는", "topic particle"),
    ]


def test_presenter_allows_surface_and_lemma_to_match_without_fake_analysis() -> None:
    result = LookupResult(
        status=LookupStatus.SUCCESS,
        entries=(DictionaryEntry("문화", ("culture",), "noun"),),
        context=LookupContext(text="문화", lemma="문화"),
    )

    content = format_lookup_result(result)

    assert content.surface == content.lemma == "문화"
    assert content.analysis == ()


def test_popup_position_flips_and_clamps_at_screen_edges() -> None:
    screen = ScreenGeometry(0, 0, 800, 600)
    controller = PopupController(_RecordingView([]), popup_size=PopupSize(200, 120), offset=12)

    assert controller.position_for(Point(10, 20), screen) == PopupPosition(22, 32)
    assert controller.position_for(Point(790, 590), screen) == PopupPosition(578, 458)
    assert controller.position_for(Point(0, 0), screen) == PopupPosition(12, 12)


def test_popup_position_stays_on_virtual_screen_with_nonzero_origin() -> None:
    screen = ScreenGeometry(-1280, 0, 1280, 1024)
    controller = PopupController(_RecordingView([]), popup_size=PopupSize(300, 180), offset=16)

    position = controller.position_for(Point(-1_275, 1_015), screen)

    assert position == PopupPosition(-1259, 819)
    assert screen.left <= position.x <= screen.right - controller.popup_size.width
    assert screen.top <= position.y <= screen.bottom - controller.popup_size.height


def test_popup_show_update_hide_and_close_lifecycle() -> None:
    view = _RecordingView([])
    controller = PopupController(view, popup_size=PopupSize(100, 80))
    screen = ScreenGeometry(0, 0, 500, 500)

    first_position = controller.open(_success(), Point(10, 10), screen)
    second_result = _success()
    controller.open(second_result, Point(20, 20), screen)
    controller.hide()
    controller.close()

    assert first_position == PopupPosition(26, 26)
    assert [event[0] for event in view.events] == ["show", "update", "hide", "close"]
    assert controller.visible is False
    assert controller.result is second_result


@pytest.mark.parametrize(
    "status",
    (
        LookupStatus.EMPTY,
        LookupStatus.NOT_FOUND,
        LookupStatus.UNUSABLE,
        LookupStatus.ERROR,
    ),
)
def test_popup_renders_non_success_in_the_existing_view(
    status: LookupStatus,
) -> None:
    view = _RecordingView([])
    controller = PopupController(view)
    screen = ScreenGeometry(0, 0, 500, 500)
    controller.open(_success(), Point(10, 10), screen)

    position = controller.open(_non_success(status), Point(20, 20), screen)

    assert position == PopupPosition(36, 36)
    assert controller.visible is True
    assert controller.result is not None
    assert controller.result.status is status
    assert [event[0] for event in view.events] == ["show", "update"]


def test_variable_size_placement_and_resize_stay_inside_the_screen() -> None:
    view = _RecordingView([])
    controller = PopupController(view, popup_size=PopupSize(340, 220))
    screen = ScreenGeometry(-1000, -200, 1000, 700)

    compact = controller.position_for(Point(-8, 490), screen)
    expanded = controller.position_for(
        Point(-8, 490), screen, PopupSize(386, 620)
    )

    assert compact == PopupPosition(-364, 254)
    assert expanded.x >= screen.left
    assert expanded.y >= screen.top
    assert expanded.x + 386 <= screen.right
    assert expanded.y + 620 <= screen.bottom


def test_interactive_resize_repositions_and_reports_the_final_geometry() -> None:
    view = _ResizableView()
    geometries: list[tuple[PopupPosition, PopupSize]] = []
    controller = PopupController(
        view,
        popup_size=PopupSize(340, 220),
        on_geometry_changed=lambda position, size: geometries.append((position, size)),
    )
    controller.open(_success(), Point(790, 590), ScreenGeometry(0, 0, 800, 600))
    assert callable(view.resize_handler)

    view.resize_handler(PopupSize(386, 500))

    assert view.positions[-1] == PopupPosition(388, 74)
    assert controller.position == PopupPosition(388, 74)
    assert geometries[-1] == (PopupPosition(388, 74), PopupSize(386, 500))


def test_popup_requires_normalized_lookup_result() -> None:
    controller = PopupController(_RecordingView([]))

    with pytest.raises(TypeError, match="LookupResult"):
        controller.open(unchecked(object()), Point(0, 0), ScreenGeometry(0, 0, 100, 100))


def test_ui_shutdown_uses_non_waiting_lookup_stop_against_queued_dispatch() -> None:
    from hanly_app.popup import PopupRuntime

    dispatch_entered = Event()
    release_dispatch = Event()
    worker_closed = Event()
    pending_callbacks: list[object] = []

    class Worker:
        def __call__(self, _request: object) -> LookupResult:
            return _success()

        def close(self) -> None:
            worker_closed.set()

    def blocking_dispatch(callback: object) -> None:
        pending_callbacks.append(callback)
        dispatch_entered.set()
        release_dispatch.wait(timeout=2)

    view = _RecordingView([])
    popup = PopupController(view)
    lookup = LookupController(Worker, lambda _result: None, result_dispatcher=blocking_dispatch)
    lookup.start()
    lookup.submit(_IMAGE, Point(10, 10))
    assert dispatch_entered.wait(timeout=2)

    # The dispatch is still blocked, so shutting down on this thread would wait
    # for it. A bounded join turns that regression into a failure instead of a
    # stopwatch reading that a loaded machine can fail on its own.
    finished = Event()

    def shut_down() -> None:
        PopupRuntime(popup, lookup).shutdown()
        finished.set()

    shutdown_thread = Thread(target=shut_down)
    shutdown_thread.start()
    try:
        assert finished.wait(timeout=5), "shutdown waited for the blocked dispatch"
        assert not release_dispatch.is_set()
        assert [event[0] for event in view.events] == ["close"]
    finally:
        # Releasing and joining here as well: a failed assertion above must not
        # leave the dispatch blocked or the shutdown thread outliving the test.
        release_dispatch.set()
        shutdown_thread.join(timeout=5)
        assert not shutdown_thread.is_alive()

    assert worker_closed.wait(timeout=2)
    assert pending_callbacks


def test_qt_import_and_dispatch_are_optional() -> None:
    qt = pytest.importorskip("PyQt6.QtCore")
    from hanly_app.qt_popup import QtResultDispatcher

    app = qt.QCoreApplication.instance() or qt.QCoreApplication([])
    dispatcher = QtResultDispatcher()
    events: list[str] = []

    dispatcher(lambda: events.append("delivered"))
    assert events == []
    app.processEvents()
    assert events == ["delivered"]


def test_clear_hides_the_popup_and_drops_the_result_it_was_showing() -> None:
    events: list[tuple[str, LookupResult | None, PopupPosition | None]] = []
    view = _RecordingView(events)
    controller = PopupController(view, popup_size=PopupSize(200, 120))

    controller.open(
        _success(),
        Point(10, 10),
        ScreenGeometry(0, 0, 800, 600),
    )
    assert controller.visible is True

    controller.clear()

    assert controller.visible is False
    assert controller.result is None
    assert [name for name, _, _ in events][-1] == "hide"


def test_a_widget_with_no_native_window_is_reported_rather_than_crashing() -> None:
    """The adapter answers for a pointer of zero without loading a runtime, so
    a caller that ran before the native window existed gets a value, not an
    Objective-C message to nothing."""

    from hanly_app.popup_darwin import hides_when_inactive, keep_visible_when_inactive

    assert keep_visible_when_inactive(0) is False
    assert hides_when_inactive(0) is None


def test_presentation_carries_short_glosses_without_inventing_them() -> None:
    """A gloss-less provider must reach the popup as a plain definition."""

    glossed = format_lookup_result(
        LookupResult(
            status=LookupStatus.SUCCESS,
            entries=(
                DictionaryEntry(
                    headword="사과하다",
                    senses=(
                        DictionarySense(
                            definition="To admit one's own mistakes.",
                            gloss="apologize",
                            sense_id="1",
                        ),
                    ),
                ),
            ),
        )
    )
    assert glossed.entry is not None
    assert glossed.entry.senses[0].gloss == "apologize"
    assert glossed.entry.definitions == ("To admit one's own mistakes.",)

    plain = format_lookup_result(
        LookupResult(
            status=LookupStatus.SUCCESS,
            entries=(DictionaryEntry("책", ("a book",)),),
        )
    )
    assert plain.entry is not None
    assert plain.entry.senses[0].gloss is None
    assert plain.entry.senses[0].definition == "a book"


class _DismissableView(_ResizableView):
    def __init__(self) -> None:
        super().__init__()
        self.dismiss_handler: Callable[[], None] | None = None

    def set_dismiss_handler(self, handler: Callable[[], None]) -> None:
        self.dismiss_handler = handler


def test_an_in_card_dismissal_clears_the_popup_and_notifies_composition() -> None:
    """The popup never accepts focus, so a control inside it is the only
    dismissal a user can always reach. It must also tell the hover runtime."""

    view = _DismissableView()
    controller = PopupController(view)
    dismissed: list[str] = []
    controller.set_dismissed_handler(lambda: dismissed.append("forget"))

    controller.open(_success(), Point(10, 10), ScreenGeometry(0, 0, 1000, 800))
    assert controller.visible is True
    assert view.dismiss_handler is not None

    view.dismiss_handler()

    assert controller.visible is False
    assert controller.result is None
    assert dismissed == ["forget"]
