"""Observable desktop runtime readiness, independent of per-request lookups.

Capture lifecycle (``DesktopState``) answers "is Hanly watching the screen?".
This module answers the separate question "can Hanly look a word up at all?",
so preparing, failing, or retrying provider initialization is visible in the
interface without inventing a lookup request to carry the news.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

RuntimePhase = Literal["idle", "preparing", "ready", "failed", "stopping", "stopped"]

#: Must schedule the observer and return; see ``ResultDispatcher``.
StatusDispatcher = Callable[[Callable[[], None]], None]

StatusObserver = Callable[["RuntimeStatus"], None]


@dataclass(frozen=True, slots=True)
class RuntimeStatus:
    """One immutable snapshot of runtime readiness.

    ``stage`` names the step being attempted ("resources", "lookup providers")
    and ``message`` is the user-facing sentence for it.
    """

    phase: RuntimePhase
    stage: str = ""
    message: str = ""

    @property
    def ready(self) -> bool:
        return self.phase == "ready"

    @property
    def failed(self) -> bool:
        return self.phase == "failed"

    def to_dict(self) -> dict[str, str]:
        """Return the JSON-compatible form the Control Center bridge exposes."""

        return {"phase": self.phase, "stage": self.stage, "message": self.message}


#: What the interface calls the application as a whole. Readiness, residency
#: and capture intent are all still available separately; this is the one label
#: a user reads, derived from them rather than guessed beside them.
ActivityState = Literal["preparing", "stopped", "armed", "running", "stopping", "error"]

#: The engine's own residency vocabulary, which is not the same question.
ENGINE_SLEEPING = "sleeping"
ENGINE_PREPARING = "preparing"
ENGINE_READY = "ready"
ENGINE_ERROR = "error"

#: The word each derived activity is shown as. One mapping so the tray title
#: and the Control Center cannot drift into different vocabularies.
ACTIVITY_LABELS: dict[str, str] = {
    "preparing": "Preparing",
    "stopped": "Stopped",
    "armed": "Armed",
    "running": "Running",
    "stopping": "Stopping",
    "error": "Error",
}


@dataclass(frozen=True, slots=True)
class ApplicationSnapshot:
    """One coherent answer to "what is Hanly doing?", derived in one place.

    Every field is a fact some surface already had; what was missing was one
    owner deriving the label from all of them at once. The tray reading
    capture state while the page read readiness is how a Hanly whose providers
    were still loading described itself as running.
    """

    activity: ActivityState
    detail: str
    runtime: RuntimeStatus
    engine_state: str
    engine_message: str
    capture_requested: bool
    hover_muted: bool

    @property
    def busy(self) -> bool:
        """Whether something is still expected to change on its own."""

        return self.activity in ("preparing", "stopping")

    def to_dict(self) -> dict[str, object]:
        """Return the JSON-compatible form the Control Center bridge exposes."""

        return {
            "activity": self.activity,
            "detail": self.detail,
            "capture_requested": self.capture_requested,
            "hover_muted": self.hover_muted,
            "engine": {"state": self.engine_state, "message": self.engine_message},
            "runtime": self.runtime.to_dict(),
        }


def derive_application_snapshot(
    runtime: RuntimeStatus,
    *,
    engine_state: str = ENGINE_SLEEPING,
    engine_message: str = "",
    capture_requested: bool = False,
    stopping: bool = False,
    hover_muted: bool = False,
    hover_detail: str = "",
    wakes_on_demand: bool = False,
) -> ApplicationSnapshot:
    """Turn the separate runtime facts into the one label the interface shows.

    Readiness comes first because a session that cannot look anything up yet is
    preparing whatever capture was asked for, and a session that failed to
    prepare is in error whatever the engine reports afterwards.
    """

    activity, detail = _activity(
        runtime,
        engine_state=engine_state,
        engine_message=engine_message,
        capture_requested=capture_requested,
        stopping=stopping,
        hover_muted=hover_muted,
        hover_detail=hover_detail,
        wakes_on_demand=wakes_on_demand,
    )
    return ApplicationSnapshot(
        activity=activity,
        detail=detail,
        runtime=runtime,
        engine_state=engine_state,
        engine_message=engine_message,
        capture_requested=capture_requested,
        hover_muted=hover_muted,
    )


def _activity(
    runtime: RuntimeStatus,
    *,
    engine_state: str,
    engine_message: str,
    capture_requested: bool,
    stopping: bool,
    hover_muted: bool,
    hover_detail: str,
    wakes_on_demand: bool,
) -> tuple[ActivityState, str]:
    if runtime.phase == "failed":
        return "error", runtime.message or "Hanly could not prepare its lookup runtime."
    if stopping:
        return "stopping", "Releasing the lookup engine."
    if runtime.phase in ("idle", "preparing"):
        return "preparing", runtime.message or _stage_detail(runtime.stage)
    if not capture_requested:
        return "stopped", "Start capture to let Hanly read the screen."
    return _started_activity(
        engine_state=engine_state,
        engine_message=engine_message,
        hover_muted=hover_muted,
        hover_detail=hover_detail,
        wakes_on_demand=wakes_on_demand,
    )


def _started_activity(
    *,
    engine_state: str,
    engine_message: str,
    hover_muted: bool,
    hover_detail: str,
    wakes_on_demand: bool,
) -> tuple[ActivityState, str]:
    """Describe a started session by what its providers are actually doing."""

    if engine_state == ENGINE_ERROR:
        return "error", engine_message or "The lookup engine stopped."
    if engine_state == ENGINE_PREPARING:
        return "preparing", engine_message or "Loading the lookup engine."
    if engine_state == ENGINE_SLEEPING and wakes_on_demand:
        return "armed", "Hanly loads the lookup engine on the first lookup."
    if hover_muted:
        return "running", "Hover paused."
    return "running", hover_detail or "Hanly is watching the screen."


def _stage_detail(stage: str) -> str:
    return f"Working on {stage}." if stage else "Hanly is getting ready."


class ReadinessSource(Protocol):
    """The readiness surface :func:`watch_worker_readiness` consumes."""

    def wait_until_ready(self, timeout: float | None = None) -> bool:
        """Block off the UI thread until provider construction settles."""

    @property
    def initialization_error(self) -> BaseException | None:
        """The original worker-construction failure, if there was one."""


class RuntimeStatusPublisher:
    """Hold the latest status snapshot and notify observers about changes.

    Observers run through ``dispatcher`` because tray, popup, and Control
    Center mutations must happen on the UI thread while the transitions
    themselves are reported from worker threads.
    """

    def __init__(self, dispatcher: StatusDispatcher | None = None) -> None:
        if dispatcher is not None and not callable(dispatcher):
            raise TypeError("dispatcher must be callable")

        self._dispatcher = dispatcher or _inline_dispatch
        self._lock = threading.RLock()
        self._status = RuntimeStatus("idle")
        self._observers: list[StatusObserver] = []

    @property
    def status(self) -> RuntimeStatus:
        with self._lock:
            return self._status

    def subscribe(self, observer: StatusObserver) -> None:
        """Register an observer and hand it the current snapshot immediately."""

        if not callable(observer):
            raise TypeError("observer must be callable")
        with self._lock:
            self._observers.append(observer)
            status = self._status
        self._notify_one(observer, status)

    def publish(self, status: RuntimeStatus) -> RuntimeStatus:
        """Replace the snapshot and notify observers, skipping a no-op change."""

        if not isinstance(status, RuntimeStatus):
            raise TypeError("status must be a RuntimeStatus")
        with self._lock:
            if status == self._status:
                return status
            self._status = status
            observers = tuple(self._observers)

        for observer in observers:
            self._notify_one(observer, status)
        return status

    def update(self, phase: RuntimePhase, stage: str = "", message: str = "") -> RuntimeStatus:
        """Publish a status built from its parts."""

        return self.publish(RuntimeStatus(phase, stage, message))

    def fail(self, stage: str, error: BaseException) -> RuntimeStatus:
        """Publish an actionable failure carrying the original cause's text."""

        return self.publish(RuntimeStatus("failed", stage, str(error) or type(error).__name__))

    def _notify_one(self, observer: StatusObserver, status: RuntimeStatus) -> None:
        def deliver() -> None:
            try:
                observer(status)
            except Exception:
                # A status observer is a presentation callback. Losing one must
                # not strand the thread that reported the transition.
                pass

        self._dispatcher(deliver)


def watch_worker_readiness(
    source: ReadinessSource,
    publisher: RuntimeStatusPublisher,
    *,
    stage: str = "lookup providers",
    ready_message: str = "Hanly is ready.",
    thread_name: str = "hanly-runtime-readiness",
    is_current: Callable[[], bool] | None = None,
) -> threading.Thread:
    """Publish ready or failed once worker construction settles.

    The wait happens on its own daemon thread because provider construction
    warms EasyOCR and Kiwi, which must never run on the UI thread.

    ``is_current`` is the composition's answer to "does this worker still own
    the runtime?". A retried or replaced attempt leaves its watcher waiting on
    a runtime nobody is using any more, and that watcher must not report the
    readiness of the live one.
    """

    def wait() -> None:
        ready = source.wait_until_ready()
        if is_current is not None and not is_current():
            return
        if ready:
            publisher.update("ready", stage, ready_message)
            return
        error = source.initialization_error
        publisher.fail(
            stage,
            error if error is not None else RuntimeError("lookup providers did not start"),
        )

    thread = threading.Thread(target=wait, name=thread_name, daemon=True)
    thread.start()
    return thread


def _inline_dispatch(callback: Callable[[], None]) -> None:
    callback()


__all__ = [
    "ENGINE_ERROR",
    "ENGINE_PREPARING",
    "ENGINE_READY",
    "ENGINE_SLEEPING",
    "ACTIVITY_LABELS",
    "ActivityState",
    "ApplicationSnapshot",
    "ReadinessSource",
    "RuntimePhase",
    "RuntimeStatus",
    "RuntimeStatusPublisher",
    "StatusDispatcher",
    "StatusObserver",
    "derive_application_snapshot",
    "watch_worker_readiness",
]
