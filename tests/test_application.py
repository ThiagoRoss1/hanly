from __future__ import annotations

import json
import sys
import threading
import types
from collections.abc import Callable
from pathlib import Path
from threading import Event, Thread
from time import monotonic
from typing import Any, cast

import hanly_app.application as application_module
import pytest
from hanly.resource_manager import ResourceManager, ResourceManifest, ResourceSpec
from hanly_app.application import (
    RUNTIME_CONFIG_NAME,
    DesktopApplication,
    DiagnosticLog,
    default_app_config_path,
    default_runtime_config_path,
    discover_runtime_config,
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


def test_the_runtime_configuration_sits_beside_the_settings_file(tmp_path: Path) -> None:
    environment = {"LOCALAPPDATA": str(tmp_path)}

    runtime = default_runtime_config_path(environment)

    assert runtime.name == RUNTIME_CONFIG_NAME
    assert runtime.parent == default_app_config_path(environment).parent


def test_a_packaged_launch_prefers_the_configuration_beside_the_executable(
    tmp_path: Path,
) -> None:
    """A packaged user should not have to pass --runtime-config to start the app."""

    application_dir = tmp_path / "hanly-desktop"
    application_dir.mkdir()
    executable = application_dir / "hanly-desktop.exe"
    executable.write_bytes(b"frozen")
    beside = application_dir / RUNTIME_CONFIG_NAME
    beside.write_text("{}", encoding="utf-8")

    settings_root = tmp_path / "settings"
    environment = {"LOCALAPPDATA": str(settings_root)}
    per_user = default_runtime_config_path(environment)
    per_user.parent.mkdir(parents=True)
    per_user.write_text("{}", encoding="utf-8")

    assert discover_runtime_config(environment, executable) == beside


def test_the_per_user_configuration_is_used_when_none_ships_with_the_build(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "bin" / "hanly-desktop.exe"
    executable.parent.mkdir()
    executable.write_bytes(b"frozen")

    environment = {"LOCALAPPDATA": str(tmp_path / "settings")}
    per_user = default_runtime_config_path(environment)
    per_user.parent.mkdir(parents=True)
    per_user.write_text("{}", encoding="utf-8")

    assert discover_runtime_config(environment, executable) == per_user


def test_discovery_reports_nothing_rather_than_guessing(tmp_path: Path) -> None:
    executable = tmp_path / "bin" / "hanly-desktop.exe"
    executable.parent.mkdir()
    executable.write_bytes(b"frozen")

    assert discover_runtime_config({"LOCALAPPDATA": str(tmp_path / "empty")}, executable) is None


def test_explicit_runtime_config_skips_first_run_bootstrap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "operator-runtime.json"
    calls: list[Path] = []

    def forbidden_bootstrap(path: str | Path) -> Path:
        calls.append(Path(path))
        raise AssertionError("explicit runtime config must not bootstrap")

    monkeypatch.setattr(application_module, "bootstrap_runtime_config", forbidden_bootstrap)
    monkeypatch.setattr(
        application_module,
        "run_desktop",
        lambda runtime_config, **_options: (
            0 if Path(runtime_config) == config else 1
        ),
    )

    assert application_module.main(["--runtime-config", str(config)]) == 0
    assert calls == []


def test_automatic_launch_bootstraps_the_discovered_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    discovered = tmp_path / "runtime.json"
    calls: list[Path] = []

    monkeypatch.setattr(application_module, "discover_runtime_config", lambda: discovered)

    def bootstrap(path: str | Path) -> Path:
        calls.append(Path(path))
        return discovered

    monkeypatch.setattr(
        application_module,
        "bootstrap_runtime_config",
        bootstrap,
    )
    monkeypatch.setattr(application_module, "run_desktop", lambda *_args, **_kwargs: 0)

    assert application_module.main([]) == 0
    assert calls == [discovered]


def test_fresh_automatic_launch_bootstraps_the_default_config_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    default = tmp_path / "Hanly" / "runtime.json"
    calls: list[Path] = []

    monkeypatch.setattr(application_module, "discover_runtime_config", lambda: None)
    monkeypatch.setattr(application_module, "default_runtime_config_path", lambda: default)

    def bootstrap(path: str | Path) -> Path:
        calls.append(Path(path))
        return default

    monkeypatch.setattr(application_module, "bootstrap_runtime_config", bootstrap)
    monkeypatch.setattr(application_module, "run_desktop", lambda *_args, **_kwargs: 0)

    assert application_module.main([]) == 0
    assert calls == [default]


def test_windowed_startup_failure_uses_native_error_reporter(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    messages: list[str] = []
    monkeypatch.setattr(application_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(application_module, "_show_native_startup_error", messages.append)

    application_module._report_startup_error(RuntimeError("resource release unavailable"))

    assert messages == ["Hanly Desktop: resource release unavailable"]
    assert "resource release unavailable" in capsys.readouterr().err


def test_native_startup_reporter_preloads_ocr_before_opening_the_qt_dialog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class _Application:
        @classmethod
        def instance(cls) -> None:
            return None

        def __init__(self, _argv: object) -> None:
            events.append("qt")

        def activeWindow(self) -> None:
            return None

    class _MessageBox:
        @staticmethod
        def critical(_parent: object, title: str, message: str) -> None:
            events.extend([title, message])

    widgets = types.ModuleType("PyQt6.QtWidgets")
    widgets.QApplication = _Application  # type: ignore[attr-defined]
    widgets.QMessageBox = _MessageBox  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "PyQt6.QtWidgets", widgets)
    monkeypatch.setattr(application_module, "preload_ocr_runtime", lambda: events.append("ocr"))

    application_module._show_native_startup_error("resource setup failed")

    assert events == ["ocr", "qt", "Hanly Desktop", "resource setup failed"]
