"""The popup's window contract: visible, on top, and never focused.

The bug these cover is not a rendering bug. Showing the result surface used to
activate the whole process, which on macOS pulls the Control Center in front of
whatever the user was reading -- so the assertions are about the flags and
attributes that decide activation, and about the fact that the popup is a
top-level window rather than a child of the main window.
"""

from __future__ import annotations

import pytest
from hanly import DictionaryEntry, LookupResult, LookupStatus

from tests.hanly_fixtures.capabilities import require_modules

require_modules("PyQt6.QtWidgets", module_level=True)

from hanly_app.popup import PopupPosition  # noqa: E402
from hanly_app.qt_popup import QtPopupView  # noqa: E402
from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtGui import QColor, QPixmap  # noqa: E402
from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402


def _result() -> LookupResult:
    return LookupResult(
        status=LookupStatus.SUCCESS,
        entries=(
            DictionaryEntry(headword="사과", definitions=("apple",), part_of_speech="noun"),
        ),
    )


def test_the_popup_is_a_top_level_window_not_a_control_center_child(
    popup_view: QtPopupView,
) -> None:
    assert popup_view.parent() is None
    assert popup_view.isWindow() is True


def test_the_popup_never_takes_focus_or_activates_the_application(
    popup_view: QtPopupView,
) -> None:
    flags = popup_view.windowFlags()

    assert flags & Qt.WindowType.WindowDoesNotAcceptFocus
    assert popup_view.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating) is True


def test_the_popup_stays_a_frameless_always_on_top_tool_window(
    popup_view: QtPopupView,
) -> None:
    flags = popup_view.windowFlags()

    assert flags & Qt.WindowType.FramelessWindowHint
    assert flags & Qt.WindowType.WindowStaysOnTopHint
    assert flags & Qt.WindowType.Tool


def test_showing_and_updating_still_renders_and_repositions(
    qt_application: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Record the placement asked for, which is the part Hanly decides.

    Where a top-level window finally lands is the window system's answer, and
    it differs by platform, work area, and frame; the view's contract is that
    both showing and updating render the result and request its position.

    The recorder replaces the bound method rather than overriding it in a
    subclass: ``QWidget.move`` is overloaded, and a narrower override is only
    valid where the Qt stubs are absent.
    """

    view = QtPopupView()
    moved_to: list[tuple[int, int]] = []
    placed = view.move

    def record(x: int, y: int) -> None:
        moved_to.append((x, y))
        placed(x, y)

    monkeypatch.setattr(view, "move", record)
    try:
        view.show_result(_result(), PopupPosition(120, 140))
        assert view.isVisible() is True

        view.update_result(_result(), PopupPosition(220, 260))
        assert view.isVisible() is True
        assert moved_to == [(120, 140), (220, 260)]
    finally:
        view.close()


def test_hiding_and_closing_the_popup_still_work(popup_view: QtPopupView) -> None:
    popup_view.show_result(_result(), PopupPosition(10, 10))

    popup_view.hide()
    assert popup_view.isVisible() is False

    popup_view.show_result(_result(), PopupPosition(20, 20))
    assert popup_view.close() is True
    assert popup_view.isVisible() is False


def test_an_explicit_parent_is_still_honoured_for_callers_that_pass_one(
    qt_application: QApplication,
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


def test_the_popup_paints_its_own_panel_background(popup_view: QtPopupView) -> None:
    """A translucent widget is cleared to nothing unless it paints itself.

    Without the paint handler the popup reached the screen as bare text over
    whatever was behind it, which is not a readable dictionary result. Rendering
    the widget onto a known background runs the same paint path the screen does.
    """

    popup_view.show_result(_result(), PopupPosition(60, 60))
    canvas = QPixmap(popup_view.size())
    canvas.fill(QColor("white"))

    popup_view.render(canvas)

    centre = canvas.toImage().pixelColor(popup_view.width() // 2, popup_view.height() // 2)
    assert centre == QColor("#20252b")
