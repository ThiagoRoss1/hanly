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
) -> threading.Thread:
    """Publish ready or failed once worker construction settles.

    The wait happens on its own daemon thread because provider construction
    warms EasyOCR and Kiwi, which must never run on the UI thread.
    """

    def wait() -> None:
        ready = source.wait_until_ready()
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
    "ReadinessSource",
    "RuntimePhase",
    "RuntimeStatus",
    "RuntimeStatusPublisher",
    "StatusDispatcher",
    "StatusObserver",
    "watch_worker_readiness",
]
