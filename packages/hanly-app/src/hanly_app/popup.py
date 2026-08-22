"""Qt-independent popup state, result formatting, and placement.

The desktop lookup pipeline hands this module a completed :class:`LookupResult`.
No OCR, morphology, dictionary, or widget implementation belongs here.  A
small view protocol keeps placement and lifecycle behavior testable without the
optional PyQt6 dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import floor
from typing import Protocol

from hanly import LookupResult, LookupStatus, Point


@dataclass(frozen=True)
class ScreenGeometry:
    """Available screen rectangle in virtual-desktop coordinates."""

    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("screen geometry dimensions must be positive")

    @property
    def left(self) -> int:
        return self.x

    @property
    def top(self) -> int:
        return self.y

    @property
    def right(self) -> int:
        """Exclusive right edge, matching Qt's available geometry semantics."""

        return self.x + self.width

    @property
    def bottom(self) -> int:
        """Exclusive bottom edge, matching Qt's available geometry semantics."""

        return self.y + self.height


@dataclass(frozen=True)
class PopupSize:
    """Estimated popup size used before a concrete widget has been laid out."""

    width: int = 320
    height: int = 180

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("popup size dimensions must be positive")


@dataclass(frozen=True)
class PopupPosition:
    """Top-left popup position in virtual-desktop coordinates."""

    x: int
    y: int


@dataclass(frozen=True)
class PopupContent:
    """Simple presentation data consumed by the concrete UI adapter."""

    title: str
    lines: tuple[str, ...]


class PopupView(Protocol):
    """Minimal view lifecycle required by :class:`PopupController`."""

    def show_result(self, result: LookupResult, position: PopupPosition) -> None:
        """Render and show a new result at ``position``."""

    def update_result(self, result: LookupResult, position: PopupPosition) -> None:
        """Render an already visible result at ``position``."""

    def hide(self) -> None:
        """Hide the popup without destroying its view."""

    def close(self) -> bool | None:
        """Release the concrete view resources."""


class LookupStopper(Protocol):
    """Narrow shutdown seam used by the UI-thread lifecycle."""

    def stop(self, *, wait: bool) -> None:
        """Stop lookup work, optionally waiting for its worker thread."""


def format_lookup_result(result: LookupResult) -> PopupContent:
    """Convert a normalized result into provider-independent display text."""

    if not isinstance(result, LookupResult):
        raise TypeError("result must be a LookupResult")

    if result.status is LookupStatus.SUCCESS:
        entry = result.entries[0]
        title = entry.headword
        lines: list[str] = []
        if entry.part_of_speech:
            lines.append(entry.part_of_speech)
        lines.extend(entry.definitions)
        for additional_entry in result.entries[1:]:
            lines.append(f"{additional_entry.headword}: {'; '.join(additional_entry.definitions)}")
        return PopupContent(title, tuple(lines))

    titles = {
        LookupStatus.EMPTY: "No text recognized",
        LookupStatus.NOT_FOUND: "No dictionary entry",
        LookupStatus.UNUSABLE: "Lookup unavailable",
        LookupStatus.ERROR: "Lookup error",
    }
    lines = list(result.diagnostics)
    if result.error is not None:
        error_text = str(result.error)
        if error_text and error_text not in lines:
            lines.append(error_text)
    return PopupContent(titles[result.status], tuple(lines))


class PopupController:
    """Own popup placement and lifecycle for completed lookup results."""

    def __init__(
        self,
        view: PopupView,
        *,
        popup_size: PopupSize | None = None,
        offset: int = 16,
    ) -> None:
        if offset < 0:
            raise ValueError("popup offset must not be negative")
        self._view = view
        self._popup_size = popup_size or PopupSize()
        self._offset = offset
        self._visible = False
        self._result: LookupResult | None = None
        self._position: PopupPosition | None = None

    @property
    def popup_size(self) -> PopupSize:
        """Return the size used for pure placement calculations."""

        return self._popup_size

    @property
    def visible(self) -> bool:
        """Whether the popup view is currently shown."""

        return self._visible

    @property
    def result(self) -> LookupResult | None:
        """Return the latest result, including while the popup is hidden."""

        return self._result

    @property
    def position(self) -> PopupPosition | None:
        """Return the latest resolved position."""

        return self._position

    def position_for(self, cursor: Point, screen: ScreenGeometry) -> PopupPosition:
        """Place the popup beside ``cursor`` while keeping it on ``screen``."""

        if not isinstance(cursor, Point):
            raise TypeError("cursor must be a Point")
        if not isinstance(screen, ScreenGeometry):
            raise TypeError("screen must be a ScreenGeometry")

        width, height = self._popup_size.width, self._popup_size.height
        x = floor(cursor.x + self._offset)
        y = floor(cursor.y + self._offset)

        if x + width > screen.right:
            x = floor(cursor.x - self._offset - width)
        if y + height > screen.bottom:
            y = floor(cursor.y - self._offset - height)

        # Clamping also covers a popup larger than the available work area.
        x = min(max(x, screen.left), max(screen.left, screen.right - width))
        y = min(max(y, screen.top), max(screen.top, screen.bottom - height))
        return PopupPosition(x, y)

    def open(
        self,
        result: LookupResult,
        cursor: Point,
        screen: ScreenGeometry,
    ) -> PopupPosition:
        """Open the V1 popup trigger or update its visible result."""

        if not isinstance(result, LookupResult):
            raise TypeError("result must be a LookupResult")
        position = self.position_for(cursor, screen)

        if self._visible:
            self._view.update_result(result, position)
        else:
            self._view.show_result(result, position)
            self._visible = True
        self._result = result
        self._position = position
        return position

    def update(
        self,
        result: LookupResult,
        cursor: Point,
        screen: ScreenGeometry,
    ) -> PopupPosition:
        """Update the result, opening the view when it is currently hidden."""

        return self.open(result, cursor, screen)

    def hide(self) -> None:
        """Hide the popup while retaining the latest result for a later open."""

        if not self._visible:
            return
        self._view.hide()
        self._visible = False

    def clear(self) -> None:
        """Hide the popup and drop the result it was showing.

        Used when the user stops capture: whatever the popup last displayed
        describes work that is no longer running.
        """

        self.hide()
        self._result = None
        self._position = None

    def close(self) -> None:
        """Hide and release the popup view."""

        self.hide()
        self._view.close()

    def shutdown(self, lookup_controller: LookupStopper) -> None:
        """Close the UI-side popup and request non-blocking lookup shutdown.

        The caller is expected to invoke this from the UI thread. Waiting for
        the worker there can deadlock when a queued result still needs that UI
        thread, so joining is intentionally left to a non-UI owner.
        """

        self.close()
        lookup_controller.stop(wait=False)


class PopupRuntime:
    """Small composition seam for popup shutdown from a UI lifecycle."""

    def __init__(self, popup: PopupController, lookup_controller: LookupStopper) -> None:
        self._popup = popup
        self._lookup_controller = lookup_controller

    def shutdown(self) -> None:
        """Close the popup and stop lookup without joining on the UI thread."""

        self._popup.shutdown(self._lookup_controller)


__all__ = [
    "LookupStopper",
    "PopupContent",
    "PopupController",
    "PopupPosition",
    "PopupRuntime",
    "PopupSize",
    "PopupView",
    "ScreenGeometry",
    "format_lookup_result",
]
