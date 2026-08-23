from __future__ import annotations

from hanly_app.capture import ScreenRect
from hanly_app.config import AppConfig, CaptureMode
from hanly_app.desktop_controller import DesktopController, DesktopState


class _LookupRuntime:
    """A double implementing the whole production runtime seam."""

    def __init__(self) -> None:
        self.events: list[str] = []
        self.configs: list[AppConfig] = []
        self.preferences: list[tuple[CaptureMode, int | None, ScreenRect | None]] = []
        self.awaited: list[float | None] = []

    def start(self) -> None:
        self.events.append("start")

    def pause(self) -> None:
        self.events.append("pause")

    def resume(self) -> None:
        self.events.append("resume")

    def invalidate(self) -> None:
        self.events.append("invalidate")

    def shutdown(self) -> None:
        self.events.append("shutdown")

    def begin_shutdown(self) -> None:
        self.events.append("begin_shutdown")

    def await_shutdown(self, timeout: float | None = None) -> bool:
        self.awaited.append(timeout)
        return True

    def apply_config(self, config: AppConfig) -> None:
        self.configs.append(config)

    def set_capture_preferences(
        self,
        *,
        capture_mode: CaptureMode,
        monitor: int | None,
        region: ScreenRect | None,
    ) -> None:
        self.preferences.append((capture_mode, monitor, region))


def test_start_pause_resume_and_shutdown_have_explicit_idempotent_states() -> None:
    runtime = _LookupRuntime()
    controller = DesktopController(runtime)

    assert controller.state is DesktopState.NEW

    controller.start()
    controller.start()
    assert controller.state is DesktopState.RUNNING
    assert runtime.events == ["start"]

    controller.pause()
    controller.pause()
    assert controller.state is DesktopState.PAUSED
    assert runtime.events == ["start", "pause"]

    controller.resume()
    controller.resume()
    assert controller.state is DesktopState.RUNNING
    assert runtime.events == ["start", "pause", "resume"]

    controller.shutdown()
    controller.shutdown()
    assert controller.state is DesktopState.SHUTDOWN
    assert runtime.events == ["start", "pause", "resume", "invalidate", "shutdown"]


def test_pause_before_start_and_resume_while_new_are_safe_no_ops() -> None:
    runtime = _LookupRuntime()
    controller = DesktopController(runtime)

    controller.pause()
    controller.resume()

    assert controller.state is DesktopState.NEW
    assert runtime.events == []


def test_pause_and_resume_prefer_runtime_lifecycle_semantics_when_available() -> None:
    runtime = _LookupRuntime()
    controller = DesktopController(runtime)

    controller.start()
    controller.pause()
    controller.resume()

    assert runtime.events == ["start", "pause", "resume"]


def test_shutdown_invalidates_before_stopping_runtime() -> None:
    runtime = _LookupRuntime()
    controller = DesktopController(runtime)

    controller.shutdown()

    assert controller.state is DesktopState.SHUTDOWN
    assert runtime.events == ["invalidate", "shutdown"]


def test_shutdown_runtime_can_be_replaced_after_safe_resource_activation() -> None:
    first = _LookupRuntime()
    replacement = _LookupRuntime()
    controller = DesktopController(first)
    controller.start()
    controller.shutdown()

    controller.replace_runtime(replacement)
    controller.start()

    assert controller.state is DesktopState.RUNNING
    assert first.events == ["start", "invalidate", "shutdown"]
    assert replacement.events == ["start"]
