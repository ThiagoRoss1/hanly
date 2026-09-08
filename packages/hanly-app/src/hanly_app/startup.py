"""Runtime preparation that happens after the interface is already open.

Resolving a runtime configuration provisions resources and may download a
hundred-megabyte dictionary, and loading it validates every file. None of that
may run on the UI thread, and none of it may run before the user has a window
to watch it in. :class:`StartupCoordinator` therefore does the heavy half on
its own thread and dispatches only the composition step back onto Qt.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from .diagnostics import DiagnosticLog, StartupTimeline
from .runtime import HanlyRuntime
from .runtime_status import RuntimeStatusPublisher, StatusDispatcher

#: Off the UI thread: resolve, provision, and validate a runtime configuration.
RuntimePreparer = Callable[[Path | None], HanlyRuntime]

#: On the UI thread: compose the desktop services around a prepared runtime.
RuntimeActivator = Callable[[HanlyRuntime], None]

#: Off the UI thread: release a previous attempt's services, marshalling
#: whatever part of that belongs to Qt and returning only once the previous
#: providers have actually let their resources go.
RuntimeReleaser = Callable[[], None]

#: What the interface shows while resources are being prepared.
RELEASING_STAGE = "previous runtime"
PREPARING_STAGE = "resources"
ACTIVATING_STAGE = "lookup providers"


class StartupCoordinator:
    """Run one runtime preparation at a time, and let the user retry it."""

    def __init__(
        self,
        prepare: RuntimePreparer,
        activate: RuntimeActivator,
        *,
        status: RuntimeStatusPublisher,
        dispatcher: StatusDispatcher,
        diagnostics: DiagnosticLog | None = None,
        release: RuntimeReleaser | None = None,
        timeline: StartupTimeline | None = None,
    ) -> None:
        for name, seam in (
            ("prepare", prepare),
            ("activate", activate),
            ("dispatcher", dispatcher),
        ):
            if not callable(seam):
                raise TypeError(f"{name} must be callable")
        if release is not None and not callable(release):
            raise TypeError("release must be callable")

        self._prepare = prepare
        self._activate = activate
        self._release = release
        self._status = status
        self._dispatcher = dispatcher
        self._diagnostics = diagnostics or DiagnosticLog()
        self._timeline = timeline or StartupTimeline()

        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._explicit_runtime: Path | None = None
        self._attempts = 0
        self._reserved = False
        self._release_pending = False
        self._closing = threading.Event()

    @property
    def preparing(self) -> bool:
        """Whether a preparation attempt is currently running.

        A thread is not alive until it has actually been started, so the
        reservation, not the thread, is what says the slot is taken.
        """

        with self._lock:
            if self._reserved:
                return True
            thread = self._thread
        return thread is not None and thread.is_alive()

    @property
    def attempts(self) -> int:
        """How many preparations have been started, including retries."""

        with self._lock:
            return self._attempts

    def start(self, explicit_runtime: Path | None = None) -> None:
        """Begin preparing the runtime, returning immediately.

        A second call while an attempt is running is ignored, so a retry
        cannot start a duplicate download or a second worker.
        """

        thread = self._reserve(explicit_runtime)
        if thread is None:
            return

        self._status.update(
            "preparing", PREPARING_STAGE, "Preparing Hanly's resources..."
        )
        thread.start()

    def retry(self) -> None:
        """Release the failed attempt's services and prepare again.

        Retrying answers a failure, so an attempt that is still preparing, or
        one that already succeeded, is left alone. Releasing happens on the
        preparation thread, ahead of the new attempt, rather than beside it: a
        replacement must never be composed while the previous providers still
        hold their models and database handles.
        """

        with self._lock:
            if not self._status.status.failed:
                return
            thread = self._reserve(self._explicit_runtime, release_previous=True)
        if thread is None:
            return

        self._status.update(
            "preparing", PREPARING_STAGE, "Preparing Hanly's resources..."
        )
        thread.start()

    def _reserve(
        self,
        explicit_runtime: Path | None,
        *,
        release_previous: bool = False,
    ) -> threading.Thread | None:
        """Take the single preparation slot, or return ``None`` if it is taken.

        Admission and the attempt number are decided together under one lock,
        so two retries arriving at once cannot both be let in during the moment
        between creating a thread and starting it.
        """

        with self._lock:
            if self._closing.is_set() or self.preparing:
                return None
            self._reserved = True
            self._explicit_runtime = explicit_runtime
            self._release_pending = release_previous and self._release is not None
            self._attempts += 1
            thread = threading.Thread(
                target=self._run,
                args=(explicit_runtime, self._attempts),
                name="hanly-startup",
                daemon=True,
            )
            self._thread = thread
            return thread

    def begin_shutdown(self) -> None:
        """Stop reporting and stop activating, without waiting for the thread."""

        self._closing.set()

    def await_shutdown(self, timeout: float = 10.0) -> bool:
        """Wait for a running preparation to finish after ``begin_shutdown``."""

        with self._lock:
            thread = self._thread
        if thread is None or thread is threading.current_thread():
            return True
        thread.join(timeout)
        return not thread.is_alive()

    def _run(self, explicit_runtime: Path | None, attempt: int) -> None:
        try:
            self._prepare_attempt(explicit_runtime, attempt)
        finally:
            # The slot is held for the whole attempt, and activation is only
            # retryable once it has published a failure of its own.
            with self._lock:
                self._reserved = False

    def _prepare_attempt(self, explicit_runtime: Path | None, attempt: int) -> None:
        if not self._release_previous(attempt):
            return

        try:
            with self._timeline.phase(PREPARING_STAGE, attempt=attempt):
                runtime = self._prepare(explicit_runtime)
        except BaseException as error:
            self._fail(PREPARING_STAGE, error, attempt)
            return

        if self._superseded(attempt):
            return
        self._status.update(
            "preparing", ACTIVATING_STAGE, "Loading the lookup engine..."
        )
        self._dispatcher(lambda: self._activate_on_ui(runtime, attempt))

    def _release_previous(self, attempt: int) -> bool:
        """Give up the failed attempt's services, and say whether to continue."""

        with self._lock:
            release = self._release if self._release_pending else None
            self._release_pending = False
        if release is None:
            return True

        self._status.update(
            "preparing", RELEASING_STAGE, "Closing the previous attempt..."
        )
        try:
            with self._timeline.phase(RELEASING_STAGE, attempt=attempt):
                release()
        except BaseException as error:
            self._fail(RELEASING_STAGE, error, attempt)
            return False
        self._status.update(
            "preparing", PREPARING_STAGE, "Preparing Hanly's resources..."
        )
        return True

    def _activate_on_ui(self, runtime: HanlyRuntime, attempt: int) -> None:
        if self._superseded(attempt):
            return
        try:
            with self._timeline.phase(ACTIVATING_STAGE, attempt=attempt):
                self._activate(runtime)
        except BaseException as error:
            self._fail(ACTIVATING_STAGE, error, attempt)

    def _fail(self, stage: str, error: BaseException, attempt: int) -> None:
        self._diagnostics.report(f"Startup ({stage})", error)
        if self._superseded(attempt):
            return
        self._status.fail(stage, error)

    def _superseded(self, attempt: int) -> bool:
        """Whether shutdown, or a later attempt, made this one irrelevant."""

        if self._closing.is_set():
            return True
        with self._lock:
            return attempt != self._attempts


__all__ = [
    "ACTIVATING_STAGE",
    "PREPARING_STAGE",
    "RELEASING_STAGE",
    "RuntimeActivator",
    "RuntimePreparer",
    "RuntimeReleaser",
    "StartupCoordinator",
]
