"""The one native property that keeps the popup on screen while Hanly is not.

Everything else about the popup is a Qt window contract and lives in the shared
suite. This is the Objective-C property underneath it, which only a real Cocoa
session can answer for.
"""

from __future__ import annotations

from hanly import DictionaryEntry, LookupResult, LookupStatus

from tests.hanly_fixtures.capabilities import require_modules, unavailable

require_modules("PyQt6.QtWidgets", module_level=True)

from hanly_app.popup import PopupPosition  # noqa: E402
from hanly_app.qt_popup import QtPopupView  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402


def _result() -> LookupResult:
    return LookupResult(
        status=LookupStatus.SUCCESS,
        entries=(
            DictionaryEntry(
                headword="한국어",
                definitions=("the Korean language",),
                part_of_speech="noun",
            ),
        ),
    )


def test_the_popup_is_not_withdrawn_when_hanly_loses_focus(
    qt_application: QApplication, popup_view: QtPopupView
) -> None:
    """The regression: AppKit stops compositing a utility panel on deactivation.

    Qt and NSWindow both keep reporting the popup visible while the window
    server has dropped it, so the property itself is what gets asserted.
    """

    if qt_application.platformName() != "cocoa":
        unavailable("winId() is an NSView only under the cocoa platform plugin")

    from hanly_app.popup_darwin import hides_when_inactive

    assert hides_when_inactive(int(popup_view.winId())) is False

    # Still false across a show/hide cycle, which is when Qt could have
    # replaced the native window under the widget.
    popup_view.show_result(_result(), PopupPosition(60, 60))
    popup_view.hide()
    assert hides_when_inactive(int(popup_view.winId())) is False
