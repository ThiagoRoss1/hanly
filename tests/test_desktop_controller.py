from __future__ import annotations

from hanly_app.desktop_controller import DesktopController, DesktopState


class _LookupRuntime:
    def __init__(self) -> None:
        self.events: list[str] = []

    def start(self) -> None:
        self.events.append("start")

    def invalidate(self) -> None:
        self.events.append("invalidate")

    def shutdown(self) -> None:
        self.events.append("shutdown")


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
    assert runtime.events == ["start", "invalidate"]

    controller.resume()
    controller.resume()
    assert controller.state is DesktopState.RUNNING
    assert runtime.events == ["start", "invalidate", "start"]

    controller.shutdown()
    controller.shutdown()
    assert controller.state is DesktopState.SHUTDOWN
    assert runtime.events == ["start", "invalidate", "start", "invalidate", "shutdown"]


def test_pause_before_start_and_resume_while_new_are_safe_no_ops() -> None:
    runtime = _LookupRuntime()
    controller = DesktopController(runtime)

    controller.pause()
    controller.resume()

    assert controller.state is DesktopState.NEW
    assert runtime.events == []


def test_shutdown_invalidates_before_stopping_runtime() -> None:
    runtime = _LookupRuntime()
    controller = DesktopController(runtime)

    controller.shutdown()

    assert controller.state is DesktopState.SHUTDOWN
    assert runtime.events == ["invalidate", "shutdown"]

