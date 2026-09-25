"""Routing a macOS application reactivation back to the Control Center.

On macOS the shell owns the Dock tile; the Control Center child runs as an
accessory with none of its own. Clicking Hanly in the Dock therefore activates
the *shell*, which by itself does nothing visible while the child sits
minimized. This connects that activation to the one existing open path.

It deliberately does not create a window, a child, an entry point, or a second
Dock identity: it calls the same action the tray menu calls.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Any

#: Ignore activations that arrive closer together than this. macOS can deliver
#: several while a window is coming forward, and each one would send another
#: focus message down the transport.
_REACTIVATION_DEBOUNCE_SECONDS = 0.5


class ApplicationReopenFilter:
    """Call ``on_reopen`` when macOS reactivates this application.

    ``should_reopen`` decides whether a reactivation means anything. It exists
    so a Control Center the user deliberately closed is not resurrected by an
    ordinary Command-Tab back to Hanly. ``clicked_own_window`` tells a click on
    one of the shell's own windows -- the popup's Expand or Close -- apart from
    the Dock: both activate the application, only one asks for the window.
    """

    def __init__(
        self,
        on_reopen: Callable[[], None],
        should_reopen: Callable[[], bool],
        *,
        clicked_own_window: Callable[[], bool] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if not callable(on_reopen) or not callable(should_reopen):
            raise TypeError("on_reopen and should_reopen must be callable")

        self._on_reopen = on_reopen
        self._should_reopen = should_reopen
        self._clicked_own_window = clicked_own_window
        self._clock = clock or _monotonic
        self._last_reopen = float("-inf")

    def application_activated(self) -> bool:
        """Handle one activation; returns whether the reopen actually ran."""

        now = self._clock()
        if now - self._last_reopen < _REACTIVATION_DEBOUNCE_SECONDS:
            return False
        if self._clicked_own_window is not None and self._clicked_own_window():
            return False
        if not self._should_reopen():
            return False

        self._last_reopen = now
        self._on_reopen()
        return True


def install_reopen_filter(
    application: Any,
    on_reopen: Callable[[], None],
    should_reopen: Callable[[], bool],
) -> ApplicationReopenFilter | None:
    """Watch a ``QApplication`` for reactivation, on macOS only.

    Returns the filter so a caller can keep it alive and a test can drive it;
    ``None`` on any other platform, where the Dock does not exist.
    """

    if sys.platform != "darwin":
        return None

    # A substituted or headless application need not publish activation. It
    # then simply has no Dock route, which costs a tray click rather than
    # breaking the shell's own startup.
    signal = getattr(application, "applicationStateChanged", None)
    connect = getattr(signal, "connect", None)
    if not callable(connect):
        return None

    from PyQt6.QtCore import Qt

    reopen = ApplicationReopenFilter(
        on_reopen, should_reopen, clicked_own_window=_pointer_on_own_window
    )

    def _state_changed(state: Qt.ApplicationState) -> None:
        if state is Qt.ApplicationState.ApplicationActive:
            reopen.application_activated()

    connect(_state_changed)
    return reopen


def _pointer_on_own_window() -> bool:
    """Whether the pointer rests on a visible window of this process.

    A Dock click leaves the pointer on the Dock; a click that activated the
    shell through its popup or selection dialog leaves it on that window.
    """

    from PyQt6.QtGui import QCursor
    from PyQt6.QtWidgets import QApplication

    pointer = QCursor.pos()
    return any(
        window.isVisible() and window.frameGeometry().contains(pointer)
        for window in QApplication.topLevelWidgets()
    )


def _monotonic() -> float:
    from time import monotonic

    return monotonic()


__all__ = ["ApplicationReopenFilter", "install_reopen_filter"]
