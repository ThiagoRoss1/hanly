"""Decide whether the word under the pointer can be read without pixels.

The desktop can sometimes ask the operating system what text is on screen
instead of photographing it. That is faster and exact when it works, and wrong
or unavailable often enough that it may never be trusted on its own: a control
can return the nearest text rather than the text under the pointer, report
geometry in another coordinate space, hand back a password field, or block.

This module owns that judgement and nothing platform-specific. A platform
adapter answers one question -- what does the accessibility layer say is at this
point -- and every rule about whether the answer may be used lives here, so both
desktop platforms reach the same decision from the same evidence.

A refusal is never a failure. Every outcome other than :data:`Outcome.DIRECT`
means the caller captures the screen and runs OCR exactly as it always has.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from hanly import BoundingBox, Point, TextSelection

#: Direct text is worth having only while the pointer is still on it. A slow
#: answer is a wrong answer, so the attempt is abandoned rather than awaited.
DEFAULT_TIMEOUT_MS = 40


class Outcome(Enum):
    """Why this lookup will or will not use direct text."""

    DIRECT = "direct"
    NO_PROVIDER = "no_provider"
    NO_PERMISSION = "no_permission"
    UNSUPPORTED = "unsupported"
    SECURE = "secure"
    NOT_CONTAINING = "not_containing"
    AMBIGUOUS = "ambiguous"
    NOT_KOREAN = "not_korean"
    EMPTY = "empty"
    TIMED_OUT = "timed_out"
    FAILED = "failed"
    SUPERSEDED = "superseded"


@dataclass(frozen=True)
class DirectText:
    """What a platform adapter managed to read at one screen point.

    ``bounds`` is the rectangle the platform says the returned range occupies,
    in the same screen coordinates the pointer was given in. It is evidence,
    not decoration: a rectangle that does not contain the pointer means the
    control answered with the nearest text instead of the text being pointed at.
    """

    text: str
    cursor_index: int
    bounds: BoundingBox | None = None
    secure: bool = False
    role: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise TypeError("direct text must be a string")
        if isinstance(self.cursor_index, bool) or not isinstance(self.cursor_index, int):
            raise TypeError("cursor_index must be an integer")
        if self.cursor_index < 0:
            raise ValueError("cursor_index must not be negative")


@dataclass(frozen=True)
class Acquisition:
    """The decision, with the reason it was reached."""

    outcome: Outcome
    selection: TextSelection | None = None
    bounds: BoundingBox | None = None
    duration_ns: int = 0
    detail: str | None = None

    @property
    def used_direct_text(self) -> bool:
        return self.outcome is Outcome.DIRECT and self.selection is not None


class DirectTextProvider(Protocol):
    """One platform's accessibility reader."""

    def read_at(self, point: Point, *, timeout_ms: int) -> DirectText | None: ...


class DirectTextCoordinator:
    """Apply every rule that decides whether direct text may be used.

    The rules are deliberately all here rather than in a platform adapter: a
    second platform must not be able to relax one by implementing its reader
    differently.
    """

    def __init__(
        self,
        provider: DirectTextProvider | None,
        *,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        permitted: Callable[[], bool] | None = None,
        clock: Callable[[], int] | None = None,
    ) -> None:
        if timeout_ms <= 0:
            raise ValueError("timeout_ms must be positive")
        self._provider = provider
        self._timeout_ms = timeout_ms
        self._permitted = permitted
        self._clock = clock or _monotonic_ns

    @property
    def timeout_ms(self) -> int:
        return self._timeout_ms

    def acquire(
        self,
        point: Point,
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> Acquisition:
        """Read the word at ``point``, or say why the caller must use OCR."""

        started = self._clock()

        def elapsed() -> int:
            return self._clock() - started

        if self._provider is None:
            return Acquisition(Outcome.NO_PROVIDER, duration_ns=elapsed())
        if self._permitted is not None and not self._permitted():
            return Acquisition(Outcome.NO_PERMISSION, duration_ns=elapsed())

        try:
            reading = self._provider.read_at(point, timeout_ms=self._timeout_ms)
        except TimeoutError:
            return Acquisition(Outcome.TIMED_OUT, duration_ns=elapsed())
        except Exception as error:
            return Acquisition(
                Outcome.FAILED, duration_ns=elapsed(), detail=type(error).__name__
            )

        duration = elapsed()
        # The pointer may have moved while the accessibility layer was working,
        # which makes a correct answer about the wrong place.
        if cancelled is not None and cancelled():
            return Acquisition(Outcome.SUPERSEDED, duration_ns=duration)
        if duration > self._timeout_ms * 1_000_000:
            return Acquisition(Outcome.TIMED_OUT, duration_ns=duration)

        return self._judge(reading, point, duration)

    def _judge(
        self, reading: DirectText | None, point: Point, duration: int
    ) -> Acquisition:
        if reading is None:
            return Acquisition(Outcome.UNSUPPORTED, duration_ns=duration)
        # A password field is readable through accessibility on some controls.
        # Nothing of it may be used, traced, cached, or shown.
        if reading.secure:
            return Acquisition(Outcome.SECURE, duration_ns=duration)

        text = reading.text
        if not text.strip():
            return Acquisition(Outcome.EMPTY, duration_ns=duration)
        if reading.bounds is None:
            return Acquisition(Outcome.AMBIGUOUS, duration_ns=duration)
        if not _contains(reading.bounds, point):
            # The control answered with whatever was nearest instead of what
            # the pointer is on, which is the failure that would silently
            # define the wrong word.
            return Acquisition(Outcome.NOT_CONTAINING, duration_ns=duration)
        if reading.cursor_index >= len(text):
            return Acquisition(Outcome.AMBIGUOUS, duration_ns=duration)
        if not _has_hangul(text):
            # Hanly looks up Korean. Latin or numeric text is a correct reading
            # of something this product does not answer.
            return Acquisition(Outcome.NOT_KOREAN, duration_ns=duration)

        selection = TextSelection(
            text=text, cursor_index=reading.cursor_index, source="accessibility"
        )
        return Acquisition(
            Outcome.DIRECT,
            selection=selection,
            bounds=reading.bounds,
            duration_ns=duration,
        )


def _contains(bounds: BoundingBox, point: Point) -> bool:
    return (
        bounds.left <= point.x <= bounds.right
        and bounds.top <= point.y <= bounds.bottom
    )


def _has_hangul(text: str) -> bool:
    return any(
        "ᄀ" <= character <= "ᇿ"
        or "㄰" <= character <= "㆏"
        or "ꥠ" <= character <= "꥿"
        or "가" <= character <= "힣"
        or "ힰ" <= character <= "퟿"
        for character in text
    )


def _monotonic_ns() -> int:
    from time import monotonic_ns

    return monotonic_ns()


__all__ = [
    "Acquisition",
    "default_text_acquisition",
    "DEFAULT_TIMEOUT_MS",
    "DirectText",
    "DirectTextCoordinator",
    "DirectTextProvider",
    "Outcome",
]


def default_text_acquisition() -> DirectTextCoordinator | None:
    """The reader this platform offers, or ``None`` where there is not one.

    Only macOS has an implementation today. Everywhere else this returns
    ``None`` and every hover captures and runs OCR exactly as before, which is
    also what happens on macOS without the accessibility grant.
    """

    from sys import platform

    if platform != "darwin":
        return None
    try:
        from .permissions_darwin import accessibility_trusted
        from .text_acquisition_ax import AccessibilityTextProvider
    except Exception:
        return None
    return DirectTextCoordinator(
        AccessibilityTextProvider(), permitted=accessibility_trusted
    )
