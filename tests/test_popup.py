from __future__ import annotations

from dataclasses import dataclass
from threading import Event
from time import monotonic

import pytest
from hanly import (
    DictionaryEntry,
    HanlyError,
    LookupResult,
    LookupStatus,
    PixelFormat,
    Point,
    ROIImage,
)
from hanly_app.lookup_controller import LookupController
from hanly_app.popup import (
    PopupController,
    PopupPosition,
    PopupSize,
    ScreenGeometry,
    format_lookup_result,
)

_IMAGE = ROIImage(1, 1, PixelFormat.GRAYSCALE_8, b"\x00")


def _success() -> LookupResult:
    return LookupResult(
        status=LookupStatus.SUCCESS,
        entries=(
            DictionaryEntry(
                headword="먹다",
                definitions=("to eat", "consume"),
                part_of_speech="verb",
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


def test_format_lookup_result_covers_success_normal_outcomes_and_error() -> None:
    success = format_lookup_result(_success())
    assert success.title == "먹다"
    assert "to eat" in success.lines

    for status in (LookupStatus.EMPTY, LookupStatus.NOT_FOUND, LookupStatus.UNUSABLE):
        content = format_lookup_result(_non_success(status))
        assert content.title
        assert "diagnostic detail" in content.lines

    error = format_lookup_result(_non_success(LookupStatus.ERROR))
    assert error.title == "Lookup error"
    assert "provider unavailable" in error.lines


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
    second_result = _non_success(LookupStatus.NOT_FOUND)
    controller.open(second_result, Point(20, 20), screen)
    controller.hide()
    controller.close()

    assert first_position == PopupPosition(26, 26)
    assert [event[0] for event in view.events] == ["show", "update", "hide", "close"]
    assert controller.visible is False
    assert controller.result is second_result


def test_popup_requires_normalized_lookup_result() -> None:
    controller = PopupController(_RecordingView([]))

    with pytest.raises(TypeError, match="LookupResult"):
        controller.open(object(), Point(0, 0), ScreenGeometry(0, 0, 100, 100))  # type: ignore[arg-type]


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

    started = monotonic()
    PopupRuntime(popup, lookup).shutdown()
    elapsed = monotonic() - started

    assert elapsed < 1
    assert [event[0] for event in view.events] == ["close"]

    release_dispatch.set()
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
