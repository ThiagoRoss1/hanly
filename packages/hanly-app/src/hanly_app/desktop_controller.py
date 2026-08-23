"""Desktop lifecycle orchestration independent of any UI framework."""

from __future__ import annotations

from enum import Enum, auto
from typing import Protocol

from .capture import ScreenRect
from .config import AppConfig, CaptureMode


class LookupRuntime(Protocol):
    """The lifecycle and live-settings seam the desktop actually requires.

    Every member is used by the production desktop path, so a runtime that
    omits one is a composition error the type checker reports rather than a
    silently ignored pause, setting, or shutdown.
    """

    def start(self) -> None:
        """Start accepting lookup work."""

    def pause(self) -> None:
        """Stop observing input while remaining startable."""

    def resume(self) -> None:
        """Resume observing input after :meth:`pause`."""

    def invalidate(self) -> None:
        """Invalidate work that is currently in flight or queued."""

    def shutdown(self) -> None:
        """Release UI-owned resources without waiting for the worker."""

    def begin_shutdown(self) -> None:
        """Request shutdown from a thread that must not block, such as the UI."""

    def await_shutdown(self, timeout: float | None = None) -> bool:
        """Wait for worker-owned resources to close after ``begin_shutdown``."""

    def apply_config(self, config: AppConfig) -> None:
        """Apply live desktop preferences to already-running services."""

    def set_capture_preferences(
        self,
        *,
        capture_mode: CaptureMode,
        monitor: int | None,
        region: ScreenRect | None,
    ) -> None:
        """Apply live capture target and region choices."""


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
        self._lookup_runtime.pause()
        self._state = DesktopState.PAUSED

    def resume(self) -> None:
        """Resume accepting lookup work after a pause."""

        if self._state is not DesktopState.PAUSED:
            return
        self._lookup_runtime.resume()
        self._state = DesktopState.RUNNING

    def apply_config(self, config: AppConfig) -> None:
        """Forward live desktop preferences to the running lookup runtime."""

        if not isinstance(config, AppConfig):
            raise TypeError("config must be an AppConfig")
        self._lookup_runtime.apply_config(config)

    def set_capture_preferences(
        self,
        *,
        capture_mode: CaptureMode,
        monitor: int | None,
        region: ScreenRect | None,
    ) -> None:
        """Forward live target/region choices to the lookup runtime."""

        self._lookup_runtime.set_capture_preferences(
            capture_mode=capture_mode,
            monitor=monitor,
            region=region,
        )

    def replace_runtime(self, lookup_runtime: LookupRuntime) -> None:
        """Install a fresh runtime after the previous one shut down for update."""

        if self._state is not DesktopState.SHUTDOWN:
            raise RuntimeError("desktop runtime can be replaced only after shutdown")
        self._lookup_runtime = lookup_runtime
        self._state = DesktopState.NEW

    def begin_shutdown(self) -> None:
        """Request shutdown without waiting for worker-owned resources."""

        if self._state is DesktopState.SHUTDOWN:
            return
        try:
            self._lookup_runtime.invalidate()
        finally:
            try:
                self._lookup_runtime.begin_shutdown()
            finally:
                self._state = DesktopState.SHUTDOWN

    def await_shutdown(self, timeout: float | None = None) -> bool:
        """Wait for a requested shutdown to release worker-owned resources."""

        return self._lookup_runtime.await_shutdown(timeout)

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
