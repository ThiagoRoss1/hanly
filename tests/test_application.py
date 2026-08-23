from __future__ import annotations

import json
import threading
from collections.abc import Callable
from pathlib import Path
from threading import Event, Thread
from time import monotonic
from typing import Any, cast

from hanly.resource_manager import ResourceManager, ResourceManifest, ResourceSpec
from hanly_app.application import (
    DesktopApplication,
    DiagnosticLog,
    default_app_config_path,
    load_update_service,
)


class _Signal:
    def __init__(self) -> None:
        self.callbacks: list[Callable[[], None]] = []

    def connect(self, callback: Callable[[], None]) -> None:
        self.callbacks.append(callback)


class _Qt:
    def __init__(self) -> None:
        self.aboutToQuit = _Signal()
        self.events: list[object] = []

    def exec(self) -> int:
        self.events.append("exec")
        return 7

    def quit(self) -> None:
        self.events.append("quit")

    def exit(self, return_code: int = 0) -> None:
        self.events.append(("exit", return_code))


class _Service:
    def __init__(self, name: str, events: list[str]) -> None:
        self.name = name
        self.events = events

    def start(self) -> None:
        self.events.append(f"{self.name}.start")

    def pause(self) -> None:
        self.events.append(f"{self.name}.pause")

    def resume(self) -> None:
        self.events.append(f"{self.name}.resume")

    def refresh(self) -> None:
        self.events.append(f"{self.name}.refresh")

    def open(self) -> None:
        self.events.append(f"{self.name}.open")

    def close(self) -> None:
        self.events.append(f"{self.name}.close")

    def shutdown(self) -> None:
        self.events.append(f"{self.name}.shutdown")

    def begin_shutdown(self) -> None:
        self.events.append(f"{self.name}.begin_shutdown")

    def await_shutdown(self, timeout: float | None = None) -> bool:
        self.events.append(f"{self.name}.await_shutdown")
        return True


def test_desktop_application_runs_and_shuts_down_services_once() -> None:
    events: list[str] = []
    qt = _Qt()
    controller = _Service("controller", events)
    tray = _Service("tray", events)
    control_center = _Service("control", events)
    desktop = DesktopApplication(qt, controller, tray, control_center)

    assert desktop.run() == 7
    desktop.shutdown()

    assert events == [
        "controller.start",
        "tray.start",
        "tray.refresh",
        "tray.shutdown",
        "control.close",
        "controller.begin_shutdown",
        "controller.await_shutdown",
    ]
    assert qt.events == ["exec"]


def test_desktop_actions_refresh_tray_and_capture_control_center_errors() -> None:
    events: list[str] = []
    diagnostics = DiagnosticLog()
    qt = _Qt()
    controller = _Service("controller", events)
    tray = _Service("tray", events)

    class BrokenControl(_Service):
        def open(self) -> None:
            raise RuntimeError("host failed")

    desktop = DesktopApplication(
        qt,
        controller,
        tray,
        BrokenControl("control", events),
        diagnostics=diagnostics,
    )
    desktop.start_capture()
    desktop.pause_capture()
    desktop.resume_capture()
    desktop.open_control_center()
    desktop.quit()

    assert "controller.pause" in events
    assert "controller.resume" in events
    assert diagnostics.snapshot() == ("Control Center: host failed",)
    assert qt.events == ["quit"]


def test_update_service_is_optional_and_uses_configured_github_adapter(tmp_path: Path) -> None:
    resource = tmp_path / "resource.bin"
    resource.write_bytes(b"resource")
    manager = ResourceManager(ResourceManifest((ResourceSpec("resource", resource),)))
    manager.validate()
    config = tmp_path / "runtime.json"
    config.write_text(
        json.dumps(
            {
                "updates": {
                    "github": {
                        "owner": "acme",
                        "repository": "hanly",
                        "manifest_asset": "resources.json",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    assert load_update_service(config, manager) is not None
    config.write_text("{}", encoding="utf-8")
    assert load_update_service(config, manager) is None


def test_default_app_config_prefers_local_app_data(tmp_path: Path) -> None:
    assert default_app_config_path({"LOCALAPPDATA": str(tmp_path)}) == (
        tmp_path / "Hanly" / "config.json"
    ).resolve()


def test_shutdown_during_an_active_install_does_not_wait_for_a_dead_qt_loop() -> None:
    """Once the Qt loop stops it can no longer run dispatched callbacks, so a
    worker parked on ``_dispatch_sync`` must be released rather than block
    shutdown for the whole dispatch timeout."""

    from hanly_app.application import DesktopShuttingDown, _dispatch_sync

    closing = Event()
    dispatched: list[Callable[[], None]] = []
    outcome: list[BaseException] = []
    entered = Event()

    def dead_dispatcher(callback: Callable[[], None]) -> None:
        dispatched.append(callback)  # a stopped loop never runs it
        entered.set()

    def worker() -> None:
        try:
            _dispatch_sync(dead_dispatcher, lambda: None, cancel=closing, timeout=30.0)
        except BaseException as error:  # noqa: BLE001 - recorded for the assertion
            outcome.append(error)

    thread = Thread(target=worker, daemon=True)
    thread.start()
    assert entered.wait(timeout=5)

    started = monotonic()
    closing.set()
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert monotonic() - started < 2.0
    assert isinstance(outcome[0], DesktopShuttingDown)


def test_application_shutdown_releases_update_workers_before_waiting() -> None:
    events: list[str] = []
    qt = _Qt()
    controller = _Service("controller", events)

    class _Updates:
        def shutdown(self, *, wait: bool = False) -> None:
            events.append(f"updates.shutdown(closing={desktop.closing.is_set()})")

    desktop = DesktopApplication(
        qt,
        controller,
        _Service("tray", events),
        _Service("control", events),
        update_coordinator=cast(Any, _Updates()),
    )
    desktop.shutdown()

    assert "updates.shutdown(closing=True)" in events
    assert events.index("controller.begin_shutdown") < events.index(
        "controller.await_shutdown"
    )


def test_install_preparation_never_joins_the_lookup_worker_on_the_qt_thread() -> None:
    """A running OCR job must not freeze the popup, tray, or Control Center:
    the Qt thread only requests teardown, and the wait happens off it."""

    from hanly_app.application import _dispatch_sync

    qt_thread = threading.get_ident()
    joined_on: list[int] = []
    requested_on: list[int] = []

    class _Runtime:
        def begin_shutdown(self) -> None:
            requested_on.append(threading.get_ident())

        def await_shutdown(self, timeout: float | None = None) -> bool:
            joined_on.append(threading.get_ident())
            return True

    runtime = _Runtime()
    pending: list[Callable[[], None]] = []

    def qt_dispatcher(callback: Callable[[], None]) -> None:
        pending.append(callback)

    def before_install() -> None:
        _dispatch_sync(qt_dispatcher, runtime.begin_shutdown, timeout=5.0)
        runtime.await_shutdown(1.0)

    worker = Thread(target=before_install, daemon=True)
    worker.start()
    for _ in range(200):
        if pending:
            break
        Event().wait(0.01)
    pending.pop(0)()  # the Qt thread runs only the non-blocking request
    worker.join(timeout=5)

    assert requested_on == [qt_thread]
    assert joined_on and joined_on[0] != qt_thread
