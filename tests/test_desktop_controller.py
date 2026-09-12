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

    def stop(self) -> None:
        self.events.append("stop")

    def set_hover_muted(self, muted: bool) -> None:
        self.events.append(f"mute={muted}")

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


def test_start_stop_resume_and_shutdown_have_explicit_idempotent_states() -> None:
    runtime = _LookupRuntime()
    controller = DesktopController(runtime)

    assert controller.state is DesktopState.NEW

    controller.start()
    controller.start()
    assert controller.state is DesktopState.RUNNING
    assert runtime.events == ["start"]

    controller.stop()
    controller.stop()
    assert controller.state is DesktopState.PAUSED
    assert runtime.events == ["start", "stop"]

    controller.resume()
    controller.resume()
    assert controller.state is DesktopState.RUNNING
    assert runtime.events == ["start", "stop", "resume"]

    controller.shutdown()
    controller.shutdown()
    assert controller.state is DesktopState.SHUTDOWN
    assert runtime.events == ["start", "stop", "resume", "invalidate", "shutdown"]


def test_stop_before_start_and_resume_while_new_are_safe_no_ops() -> None:
    runtime = _LookupRuntime()
    controller = DesktopController(runtime)

    controller.stop()
    controller.resume()

    assert controller.state is DesktopState.NEW
    assert runtime.events == []


def test_stop_and_resume_prefer_runtime_lifecycle_semantics_when_available() -> None:
    runtime = _LookupRuntime()
    controller = DesktopController(runtime)

    controller.start()
    controller.stop()
    controller.resume()

    assert runtime.events == ["start", "stop", "resume"]


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


def test_muting_hover_is_not_a_capture_change() -> None:
    """The distinction this controller exists to keep: a mute leaves the
    session running and its providers loaded, and only Stop releases them."""

    runtime = _LookupRuntime()
    controller = DesktopController(runtime)
    controller.start()

    controller.set_hover_muted(True)
    controller.set_hover_muted(False)

    assert controller.state is DesktopState.RUNNING
    assert runtime.events == ["start", "mute=True", "mute=False"]


def test_muting_a_session_that_is_not_running_does_nothing() -> None:
    runtime = _LookupRuntime()
    controller = DesktopController(runtime)

    controller.set_hover_muted(True)

    assert runtime.events == []
