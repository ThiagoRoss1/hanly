"""The popup's window contract: visible, on top, and never focused.

The bug these cover is not a rendering bug. Showing the result surface used to
activate the whole process, which on macOS pulls the Control Center in front of
whatever the user was reading -- so the assertions are about the flags and
attributes that decide activation, and about the fact that the popup is a
top-level window rather than a child of the main window.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator

import pytest
from hanly import DictionaryEntry, LookupResult, LookupStatus

pytest.importorskip("PyQt6.QtWidgets")

from hanly_app.popup import PopupPosition  # noqa: E402
from hanly_app.qt_popup import QtPopupView  # noqa: E402
from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtGui import QColor, QPixmap  # noqa: E402
from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402


@pytest.fixture(scope="module")
def application() -> QApplication:
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    return QApplication([])


@pytest.fixture
def view(application: QApplication) -> Iterator[QtPopupView]:
    popup = QtPopupView()
    yield popup
    popup.close()


def _result() -> LookupResult:
    return LookupResult(
        status=LookupStatus.SUCCESS,
        entries=(
            DictionaryEntry(headword="사과", definitions=("apple",), part_of_speech="noun"),
        ),
    )


def test_the_popup_is_a_top_level_window_not_a_control_center_child(
    view: QtPopupView,
) -> None:
    assert view.parent() is None
    assert view.isWindow() is True


def test_the_popup_never_takes_focus_or_activates_the_application(
    view: QtPopupView,
) -> None:
    flags = view.windowFlags()

    assert flags & Qt.WindowType.WindowDoesNotAcceptFocus
    assert view.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating) is True


def test_the_popup_stays_a_frameless_always_on_top_tool_window(
    view: QtPopupView,
) -> None:
    flags = view.windowFlags()

    assert flags & Qt.WindowType.FramelessWindowHint
    assert flags & Qt.WindowType.WindowStaysOnTopHint
    assert flags & Qt.WindowType.Tool


class _PlacementRecordingView(QtPopupView):
    """Record the placement asked for, which is the part Hanly decides.

    Where a top-level window finally lands is the window system's answer, and
    it differs by platform, work area, and frame; the view's contract is that
    both showing and updating render the result and request its position.
    """

    def __init__(self) -> None:
        super().__init__()
        self.moved_to: list[tuple[int, int]] = []

    # Deliberately narrower than QWidget.move's QPoint overload: the view under
    # test is only ever moved by coordinates, and widening this to accept both
    # would trade a clear signature for an unpack that can fail differently.
    def move(self, x: int, y: int) -> None:  # type: ignore[override]
        self.moved_to.append((x, y))
        super().move(x, y)


def test_showing_and_updating_still_renders_and_repositions(
    application: QApplication,
) -> None:
    view = _PlacementRecordingView()
    try:
        view.show_result(_result(), PopupPosition(120, 140))
        assert view.isVisible() is True

        view.update_result(_result(), PopupPosition(220, 260))
        assert view.isVisible() is True
        assert view.moved_to == [(120, 140), (220, 260)]
    finally:
        view.close()


def test_hiding_and_closing_the_popup_still_work(view: QtPopupView) -> None:
    view.show_result(_result(), PopupPosition(10, 10))

    view.hide()
    assert view.isVisible() is False

    view.show_result(_result(), PopupPosition(20, 20))
    assert view.close() is True
    assert view.isVisible() is False


def test_an_explicit_parent_is_still_honoured_for_callers_that_pass_one(
    application: QApplication,
) -> None:
    """The window contract is about flags, not about forbidding a parent.

    ``create_qt_manual_lookup`` takes an optional parent, and a benchmark
    harness may pass one; production composition passes none.
    """

    parent = QWidget()
    popup = QtPopupView(parent)
    try:
        assert popup.parent() is parent
        assert popup.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating) is True
    finally:
        popup.close()
        parent.close()


def test_the_popup_paints_its_own_panel_background(view: QtPopupView) -> None:
    """A translucent widget is cleared to nothing unless it paints itself.

    Without the paint handler the popup reached the screen as bare text over
    whatever was behind it, which is not a readable dictionary result. Rendering
    the widget onto a known background runs the same paint path the screen does.
    """

    view.show_result(_result(), PopupPosition(60, 60))
    canvas = QPixmap(view.size())
    canvas.fill(QColor("white"))

    view.render(canvas)

    centre = canvas.toImage().pixelColor(view.width() // 2, view.height() // 2)
    assert centre == QColor("#20252b")


@pytest.mark.skipif(sys.platform != "darwin", reason="the panel property is macOS-only")
def test_the_popup_is_not_withdrawn_when_hanly_loses_focus(
    application: QApplication, view: QtPopupView
) -> None:
    """The regression: AppKit stops compositing a utility panel on deactivation.

    Qt and NSWindow both keep reporting the popup visible while the window
    server has dropped it, so the property itself is what gets asserted.
    """

    if application.platformName() != "cocoa":
        pytest.skip("winId() is an NSView only under the cocoa platform plugin")

    from hanly_app.popup_darwin import hides_when_inactive

    assert hides_when_inactive(int(view.winId())) is False

    # Still false across a show/hide cycle, which is when Qt could have
    # replaced the native window under the widget.
    view.show_result(_result(), PopupPosition(60, 60))
    view.hide()
    assert hides_when_inactive(int(view.winId())) is False


def test_a_widget_with_no_native_window_is_reported_rather_than_crashing() -> None:
    from hanly_app.popup_darwin import hides_when_inactive, keep_visible_when_inactive

    assert keep_visible_when_inactive(0) is False
    assert hides_when_inactive(0) is None
