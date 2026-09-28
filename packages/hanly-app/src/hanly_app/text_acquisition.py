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
means the caller captures the screen and runs OCR exactly as it always has --
except :data:`Outcome.NOT_KOREAN`, which is itself an answer: the control read
the pointer's character exactly, and it is not Korean.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from threading import Condition, Event, Thread, current_thread
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
        self._binding_failed = False

    @property
    def timeout_ms(self) -> int:
        return self._timeout_ms

    def bind_worker(self) -> bool:
        """Let the adapter prepare the thread that will perform every read.

        Windows needs this: COM apartments belong to a thread rather than to a
        process, so the one worker has to enter one before the first read and
        leave it after the last. An adapter that needs nothing says nothing.
        Returns whether the thread is ready; a failed one reads nothing.
        """

        self._binding_failed = not self._notify_provider("bind_thread")
        return not self._binding_failed

    def release_worker(self) -> None:
        """Undo a successful :meth:`bind_worker`, on that same thread."""

        self._notify_provider("release_thread")

    def _notify_provider(self, hook: str) -> bool:
        callback = getattr(self._provider, hook, None)
        if not callable(callback):
            return True
        try:
            callback()
        except Exception:
            return False
        return True

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
        if self._binding_failed:
            return Acquisition(Outcome.FAILED, duration_ns=elapsed())
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
        # A control hands back a whole line, while the engine answers one word.
        # The pixel path narrows a recognized line with its resolver; here the
        # equivalent is the run of Korean the pointer is inside, so a line that
        # mixes scripts answers exactly as that word alone would.
        narrowed = _korean_run(text, reading.cursor_index)
        if narrowed is None:
            if _stands_in_for_content(text[reading.cursor_index]):
                # An embedded object -- Chromium's U+FFFC for a canvas or an
                # image -- has no text of its own; its pixels are OCR's to read.
                return Acquisition(Outcome.UNSUPPORTED, duration_ns=duration)
            # The pointer rests on real text that is not Korean.
            return Acquisition(Outcome.NOT_KOREAN, duration_ns=duration)

        word, cursor_index, start = narrowed
        bounds = self._precise_bounds(point, reading, start, start + len(word))
        if bounds is None:
            # The line's own rectangle would retain everything beside the word,
            # including text this lookup is not about. Better to let OCR answer
            # than to claim a region this word does not occupy.
            return Acquisition(Outcome.AMBIGUOUS, duration_ns=duration)

        selection = TextSelection(
            text=word, cursor_index=cursor_index, source="accessibility"
        )
        return Acquisition(
            Outcome.DIRECT,
            selection=selection,
            bounds=bounds,
            duration_ns=duration,
        )

    def _precise_bounds(
        self, point: Point, reading: DirectText, start: int, end: int
    ) -> BoundingBox | None:
        """The rectangle of the narrowed word, or ``None`` to refuse the read.

        A provider that cannot answer about a span keeps the rectangle it gave,
        which is the whole line; that is only right when the line *is* the word,
        so anything narrower is refused rather than approximated. A provider
        that can answer is handed the line it read, and must refuse if the
        control no longer shows exactly that line.
        """

        refine = getattr(self._provider, "refine_bounds", None)
        line = reading.bounds
        if not callable(refine):
            return line if (start, end) == (0, len(reading.text)) else None

        try:
            bounds = refine(
                point, start, end, line=reading.text, timeout_ms=self._timeout_ms
            )
        except Exception:
            return None
        if not isinstance(bounds, BoundingBox):
            return None
        # It must be the pointer's own word, and it must sit inside the line it
        # was taken from; either failure means the control answered about
        # something else.
        if not _contains(bounds, point):
            return None
        if line is not None and not _encloses(line, bounds):
            return None
        return bounds


def _contains(bounds: BoundingBox, point: Point) -> bool:
    return (
        bounds.left <= point.x <= bounds.right
        and bounds.top <= point.y <= bounds.bottom
    )


def _korean_run(text: str, cursor_index: int) -> tuple[str, int, int] | None:
    """The unbroken Korean the pointer is inside, where it sits, and where it starts.

    ``None`` when the pointer rests on anything that is not Korean, so a reader
    pointing at an emoji or a Latin word is not answered with the nearest
    Hangul that happens to share the line. The start offset lets the
    caller ask the platform about exactly this span.
    """

    if not 0 <= cursor_index < len(text) or not _is_hangul(text[cursor_index]):
        return None

    start = cursor_index
    while start > 0 and _is_hangul(text[start - 1]):
        start -= 1
    end = cursor_index + 1
    while end < len(text) and _is_hangul(text[end]):
        end += 1
    return text[start:end], cursor_index - start, start


def _encloses(outer: BoundingBox, inner: BoundingBox) -> bool:
    return (
        outer.left <= inner.left
        and outer.top <= inner.top
        and inner.right <= outer.right
        and inner.bottom <= outer.bottom
    )


#: Characters a control uses in place of content it cannot express as text.
_PLACEHOLDERS = frozenset({"\ufffc", "\ufffd"})


def _stands_in_for_content(character: str) -> bool:
    """Whether ``character`` is a placeholder rather than a glyph of its own.

    Control, format, private-use and unassigned code points never draw text
    the reader could be pointing at, so like the object replacement character
    they say nothing about what is on screen there.
    """

    return character in _PLACEHOLDERS or unicodedata.category(character)[0] == "C"


def _is_hangul(character: str) -> bool:
    return (
        "ᄀ" <= character <= "ᇿ"
        or "㄰" <= character <= "㆏"
        or "ꥠ" <= character <= "꥿"
        or "가" <= character <= "힣"
        or "ힰ" <= character <= "퟿"
    )


def _monotonic_ns() -> int:
    from time import monotonic_ns

    return monotonic_ns()


__all__ = [
    "Acquisition",
    "DirectTextService",
    "default_text_acquisition",
    "DEFAULT_TIMEOUT_MS",
    "DirectText",
    "DirectTextCoordinator",
    "DirectTextProvider",
    "Outcome",
]


def default_text_acquisition() -> DirectTextService | None:
    """The reader this platform offers, or ``None`` where there is not one.

    macOS reads through accessibility and Windows through UI Automation.
    Anywhere else this returns ``None`` and every hover captures and runs OCR
    exactly as before, which is also what happens on macOS without the
    accessibility grant.
    """

    from sys import platform

    if platform == "darwin":
        coordinator = _darwin_coordinator()
    elif platform == "win32":
        coordinator = _windows_coordinator()
    else:
        return None
    return None if coordinator is None else DirectTextService(coordinator)


def _darwin_coordinator() -> DirectTextCoordinator | None:
    try:
        from .permissions_darwin import accessibility_trusted
        from .text_acquisition_ax import AccessibilityTextProvider
    except Exception:
        return None
    return DirectTextCoordinator(
        AccessibilityTextProvider(), permitted=accessibility_trusted
    )


def _windows_coordinator() -> DirectTextCoordinator | None:
    """Windows needs no grant: UI Automation is readable by any process.

    What it can read is bounded by integrity level instead, and a window this
    process may not query simply answers nothing, which is an ordinary refusal
    rather than a permission the user could give.
    """

    try:
        from .text_acquisition_uia import UIAutomationTextProvider
    except Exception:
        return None
    return DirectTextCoordinator(UIAutomationTextProvider())


@dataclass(frozen=True)
class _Job:
    """One scheduled acquisition and the deadline it must answer by."""

    generation: int
    point: Point
    deadline_ns: int
    deliver: Callable[[Acquisition], None]
    delivered: Event


class DirectTextService:
    """Run native acquisitions away from the caller's thread, one at a time.

    Accessibility calls are synchronous IPC into another application, so they
    must not execute on the thread that draws. They are also not reliably
    interruptible: a messaging deadline makes the ordinary case return, but the
    caller still cannot be left waiting on a target that never answers. So a
    worker performs the call and a watcher answers the deadline, whichever
    happens first delivers exactly one outcome, and the other is discarded.

    Only the newest request matters. A hover that supersedes another replaces
    the pending job rather than queueing behind it, so a slow target cannot
    build up a backlog of calls against stale pointer positions.
    """

    def __init__(
        self,
        coordinator: DirectTextCoordinator,
        *,
        clock: Callable[[], int] | None = None,
    ) -> None:
        self._coordinator = coordinator
        self._clock = clock or _monotonic_ns
        self._condition = Condition()
        self._pending: _Job | None = None
        self._active: _Job | None = None
        self._generation = 0
        self._closed = False
        # Daemon threads: a composition that is built and dropped without a
        # shutdown must not keep the interpreter alive, and a native call that
        # cannot be interrupted must not delay exit either. An orderly
        # :meth:`close` still joins them.
        self._worker = Thread(
            target=self._work, name="hanly-text-acquisition", daemon=True
        )
        self._watcher = Thread(
            target=self._watch, name="hanly-acquisition-deadline", daemon=True
        )
        self._worker.start()
        self._watcher.start()

    @property
    def timeout_ms(self) -> int:
        return self._coordinator.timeout_ms

    def submit(self, point: Point, deliver: Callable[[Acquisition], None]) -> int:
        """Schedule one acquisition, superseding any request not yet started.

        Returns the generation that identifies it, which the caller can compare
        against its own currency before acting on the outcome.
        """

        with self._condition:
            if self._closed:
                raise RuntimeError("text acquisition service is closed")
            self._generation += 1
            generation = self._generation
            self._pending = _Job(
                generation=generation,
                point=point,
                deadline_ns=self._clock() + self._coordinator.timeout_ms * 1_000_000,
                deliver=deliver,
                delivered=Event(),
            )
            self._condition.notify_all()
            return generation

    def close(self) -> None:
        """Stop both threads and abandon anything still running.

        A native call already in progress cannot be cancelled, so its answer is
        simply never delivered; the job's latch makes that safe.
        """

        with self._condition:
            if self._closed:
                return
            self._closed = True
            self._pending = None
            self._condition.notify_all()
        # Delivery runs on a service thread, so a caller may well be closing
        # from inside its own callback. Joining the thread doing the closing
        # would raise; the rest of the shutdown is already done.
        current = current_thread()
        for thread in (self._worker, self._watcher):
            if thread is not current:
                thread.join(timeout=5.0)

    def _work(self) -> None:
        # A binding that failed part-way has nothing of its own to undo, and
        # undoing it anyway could leave an apartment that was never entered.
        bound = self._coordinator.bind_worker()
        try:
            self._consume()
        finally:
            if bound:
                self._coordinator.release_worker()

    def _consume(self) -> None:
        while True:
            with self._condition:
                while not self._closed and self._pending is None:
                    self._condition.wait()
                if self._closed:
                    return
                job = self._pending
                self._pending = None
                self._active = job
            if job is None:
                continue

            outcome = self._run(job)
            with self._condition:
                if self._active is job:
                    self._active = None
                # The watcher is waiting on this job; tell it the job is over
                # rather than leaving it to notice on a timeout.
                self._condition.notify_all()
            self._deliver(job, outcome)

    def _run(self, job: _Job) -> Acquisition:
        if job.delivered.is_set() or self._clock() >= job.deadline_ns:
            return Acquisition(Outcome.TIMED_OUT)
        try:
            return self._coordinator.acquire(
                job.point, cancelled=lambda: self._superseded(job)
            )
        except Exception as error:
            return Acquisition(Outcome.FAILED, detail=type(error).__name__)

    def _watch(self) -> None:
        while True:
            with self._condition:
                if self._closed:
                    return
                jobs = [
                    candidate for candidate in (self._active, self._pending)
                    if candidate is not None and not candidate.delivered.is_set()
                ]
                job = min(jobs, key=lambda candidate: candidate.deadline_ns) if jobs else None
                if job is None:
                    self._condition.wait()
                    continue
                remaining = (job.deadline_ns - self._clock()) / 1_000_000_000
                if remaining > 0:
                    self._condition.wait(timeout=remaining)
                    continue
            # The native call is still running and cannot be stopped. The
            # caller is released to capture instead of waiting for it, and the
            # answer it eventually produces is dropped by the latch.
            self._deliver(job, Acquisition(Outcome.TIMED_OUT))

    def _deliver(self, job: _Job, outcome: Acquisition) -> None:
        if job.delivered.is_set():
            return
        with self._condition:
            if job.delivered.is_set():
                return
            job.delivered.set()
            closed = self._closed
            if self._generation != job.generation:
                outcome = Acquisition(Outcome.SUPERSEDED)
            elif self._clock() >= job.deadline_ns:
                outcome = Acquisition(Outcome.TIMED_OUT)
        if closed:
            return
        try:
            job.deliver(outcome)
        except Exception:
            # The caller's delivery is not this service's business, and a
            # failure in it must not take the worker down: nothing would
            # consume later jobs, so a hover would wait for an outcome that
            # never came and never fall back to capture either.
            pass

    def _superseded(self, job: _Job) -> bool:
        with self._condition:
            return self._closed or self._generation != job.generation
