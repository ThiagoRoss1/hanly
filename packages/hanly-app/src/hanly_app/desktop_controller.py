"""Desktop lifecycle orchestration independent of any UI framework."""

from __future__ import annotations

from enum import Enum, auto
from typing import Protocol


class LookupRuntime(Protocol):
    """The narrow lifecycle seam required by :class:`DesktopController`."""

    def start(self) -> None:
        """Start accepting lookup work."""

    def invalidate(self) -> None:
        """Invalidate work that is currently in flight or queued."""

    def shutdown(self) -> None:
        """Stop runtime resources and wait for graceful cleanup."""


class DesktopState(Enum):
    """States relevant to the intentionally small desktop foundation."""

    NEW = auto()
    RUNNING = auto()
    PAUSED = auto()
    SHUTDOWN = auto()


class DesktopController:
    """Coordinate startup, pause/resume, and shutdown of a lookup runtime."""

    def __init__(self, lookup_runtime: LookupRuntime) -> None:
        self._lookup_runtime = lookup_runtime
        self._state = DesktopState.NEW

    @property
    def state(self) -> DesktopState:
        return self._state

    def start(self) -> None:
        """Start the lookup runtime once and enter ``RUNNING``."""

        if self._state is not DesktopState.NEW:
            return
        self._lookup_runtime.start()
        self._state = DesktopState.RUNNING

    def pause(self) -> None:
        """Invalidate active lookup work and enter ``PAUSED``."""

        if self._state is not DesktopState.RUNNING:
            return
        self._lookup_runtime.invalidate()
        self._state = DesktopState.PAUSED

    def resume(self) -> None:
        """Resume accepting lookup work after a pause."""

        if self._state is not DesktopState.PAUSED:
            return
        self._lookup_runtime.start()
        self._state = DesktopState.RUNNING

    def shutdown(self) -> None:
        """Invalidate outstanding work and stop the runtime exactly once."""

        if self._state is DesktopState.SHUTDOWN:
            return

        try:
            self._lookup_runtime.invalidate()
        finally:
            try:
                self._lookup_runtime.shutdown()
            finally:
                self._state = DesktopState.SHUTDOWN
