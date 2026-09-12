from __future__ import annotations

import ast
import json
import queue
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
from hanly_app.config import AppConfig, ConfigManager
from hanly_app.control_center import ControlCenterBridge, ControlCenterUnavailable
from hanly_app.desktop_controller import DesktopState
from hanly_app.hotkeys import HotkeyAction
from hanly_app.permissions import (
    Permission,
    PermissionService,
    PermissionState,
)
from hanly_app.runtime_status import RuntimeStatusPublisher

#: Bounded so a marshalling regression fails the test instead of hanging it.
_WAIT_SECONDS = 5.0


class _Signal:
    def __init__(self) -> None:
        self.callbacks: list[Callable[[], None]] = []

    def connect(self, callback: Callable[[], None]) -> None:
        self.callbacks.append(callback)


class _Qt:
    def __init__(self) -> None:
        self.aboutToQuit = _Signal()
        self.events: list[object] = []
        #: Stands in for something happening while the loop is running.
        self.during_loop: Callable[[], None] | None = None

    def exec(self) -> int:
        self.events.append("exec")
        if self.during_loop is not None:
            self.during_loop()
        return 7

    def quit(self) -> None:
        self.events.append("quit")

    def exit(self, return_code: int = 0) -> None:
        self.events.append(("exit", return_code))

    def setQuitOnLastWindowClosed(self, closed: bool) -> None:
        self.events.append(("quit_on_last_window_closed", closed))


class _Service:
    def __init__(
        self,
        name: str,
        events: list[str],
        *,
        can_restore_window: bool = True,
    ) -> None:
        self.name = name
        self.events = events
        self.can_restore_window = can_restore_window

    def start(self) -> None:
        self.events.append(f"{self.name}.start")

    def pause(self) -> None:
        self.events.append(f"{self.name}.pause")

    def resume(self) -> None:
        self.events.append(f"{self.name}.resume")

    def refresh(self) -> None:
        self.events.append(f"{self.name}.refresh")

    def show(self) -> None:
        self.events.append(f"{self.name}.show")

    def close(self) -> None:
        self.events.append(f"{self.name}.close")

    def notify_state_changed(self) -> None:
        self.events.append(f"{self.name}.notify")

    def shutdown(self) -> None:
        self.events.append(f"{self.name}.shutdown")

    def begin_shutdown(self) -> None:
        self.events.append(f"{self.name}.begin_shutdown")

    def await_shutdown(self, timeout: float | None = None) -> bool:
        self.events.append(f"{self.name}.await_shutdown")
        return True


def test_desktop_application_runs_and_shuts_down_services_once() -> None:
    """The shell owns the loop, and releases its children in dependency order."""

    events: list[str] = []
    qt = _Qt()
    controller = _Service("controller", events)
    tray = _Service("tray", events)
    control_center = _Service("control", events)
    desktop = DesktopApplication(qt, controller, tray, control_center)

    assert desktop.run() == 7
    desktop.shutdown()

    # Input and the lookup child go first, so an update handoff can only take
    # over once nothing still holds a resource; nothing starts watching the
    # screen before the user asks.
    assert events == [
        "tray.start",
        "control.show",
        "controller.begin_shutdown",
        "controller.await_shutdown",
        "control.shutdown",
        "tray.shutdown",
    ]
    assert ("quit_on_last_window_closed", False) in qt.events
    assert "exec" in qt.events


def test_the_running_shell_is_what_answers_a_waiting_update_handoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The handoff keeps the previous installation until this build answers, so
    the milestone is the shell running - Qt, the interpreter, and this build's
    own collected dependencies have all started by then. A window the user
    never opened, and a resource that downloads afterwards, say nothing about
    whether the swap produced a working Hanly."""

    from importlib import metadata

    monkeypatch.setattr(metadata, "version", lambda name: "0.2.0")
    ready = tmp_path / "transaction" / "ready"
    acknowledge = application_module._update_acknowledgement(ready, DiagnosticLog())
    assert acknowledge is not None

    acknowledge()

    assert ready.read_text(encoding="utf-8") == "0.2.0"


def test_a_launch_no_handoff_is_waiting_on_writes_no_acknowledgement() -> None:
    assert application_module._update_acknowledgement(None, DiagnosticLog()) is None


def test_an_unwritable_acknowledgement_is_reported_and_never_stops_the_launch(
    tmp_path: Path,
) -> None:
    """Failing to answer costs the update, which rolls back. Refusing to open
    would cost the user their Hanly for a file they never asked about."""

    diagnostics = DiagnosticLog()
    blocked = tmp_path / "file" / "ready"
    blocked.parent.write_text("not a directory", encoding="utf-8")

    acknowledge = application_module._update_acknowledgement(blocked, diagnostics)
    assert acknowledge is not None
    acknowledge()

    assert any("Update acknowledgement" in entry for entry in diagnostics.snapshot())


def test_desktop_actions_refresh_tray_and_capture_control_center_errors() -> None:
    events: list[str] = []
    diagnostics = DiagnosticLog()
    qt = _Qt()
    controller = _Service("controller", events)
    tray = _Service("tray", events)

    class BrokenControl(_Service):
        def show(self) -> None:
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
    assert "Control Center: host failed" in diagnostics.snapshot()
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


def test_an_explicit_runtime_config_is_used_without_provisioning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--runtime-config` is an operator choice: it neither creates files nor
    reaches the release channel behind the caller's back."""

    config = tmp_path / "explicit.json"

    def forbidden(path: str | Path, **_options: object) -> Path:
        raise AssertionError("explicit runtime config must not provision")

    monkeypatch.setattr(application_module, "provision_runtime_config", forbidden)

    assert application_module.resolve_runtime_config(config) == config


def test_automatic_launch_provisions_the_discovered_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    discovered = tmp_path / "runtime.json"
    calls: list[Path] = []

    monkeypatch.setattr(application_module, "discover_runtime_config", lambda: discovered)

    def provision(path: str | Path, **options: object) -> Path:
        calls.append(Path(path))
        assert callable(options["on_status"])
        return discovered

    monkeypatch.setattr(application_module, "provision_runtime_config", provision)

    assert application_module.resolve_runtime_config(None) == discovered
    assert calls == [discovered]


def test_fresh_automatic_launch_provisions_the_default_config_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    default = tmp_path / "Hanly" / "runtime.json"
    calls: list[Path] = []

    monkeypatch.setattr(application_module, "discover_runtime_config", lambda: None)
    monkeypatch.setattr(application_module, "default_runtime_config_path", lambda: default)

    def provision(path: str | Path, **options: object) -> Path:
        calls.append(Path(path))
        assert callable(options["on_status"])
        return default

    monkeypatch.setattr(application_module, "provision_runtime_config", provision)

    assert application_module.resolve_runtime_config(None) == default
    assert calls == [default]


def test_startup_resource_status_is_visible_on_the_cli(
    capsys: pytest.CaptureFixture[str],
) -> None:
    application_module._report_startup_status("Checking resources...")

    assert capsys.readouterr().err == "Hanly: Checking resources...\n"


def test_update_coordinator_checks_availability_as_soon_as_it_is_exposed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = object()
    calls: list[str] = []
    coordinator_options: dict[str, object] = {}

    class _Coordinator:
        def __init__(self, received: object, **options: object) -> None:
            assert received is service
            coordinator_options.update(options)

        def check_for_updates(self) -> dict[str, object]:
            calls.append("check")
            return {"status": "checking"}

    monkeypatch.setattr(application_module, "load_update_service", lambda *_args: service)
    monkeypatch.setattr(application_module, "UpdateCoordinator", _Coordinator)
    manager = ResourceManager(ResourceManifest(()))
    config = tmp_path / "runtime.json"
    config.write_text(
        json.dumps(
            {
                "resources": {
                    "krdict": {
                        "kind": "krdict",
                        "path": "krdict.sqlite3",
                        "installed_version": "1",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    result = application_module._update_coordinator(config, manager, DiagnosticLog())

    assert result is not None
    assert calls == ["check"]
    record_install = coordinator_options["record_install"]
    assert callable(record_install)
    record_install(
        types.SimpleNamespace(
            resource=types.SimpleNamespace(resource_id="krdict", version="2"),
            validation=types.SimpleNamespace(integrity_identity="120:900"),
        )
    )
    # One write carries both: the version that was installed and the identity of
    # the bytes the installer already scanned.
    recorded = json.loads(config.read_text(encoding="utf-8"))["resources"]["krdict"]
    assert recorded["installed_version"] == "2"
    assert recorded["verified_identity"] == "120:900"


def test_windowed_startup_failure_uses_native_error_reporter(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    messages: list[str] = []
    monkeypatch.setattr(application_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(application_module, "_show_native_startup_error", messages.append)

    application_module.report_startup_error(RuntimeError("resource release unavailable"))

    assert messages == ["Hanly Desktop: resource release unavailable"]
    assert "resource release unavailable" in capsys.readouterr().err


def test_a_machine_driven_startup_failure_never_opens_a_modal_dialog(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A frozen --self-check that raised one waited out the packaging harness's
    whole deadline for a click nobody was there to make."""

    def refuse(_message: str) -> None:
        raise AssertionError("a modal dialog must not be opened for a self-check")

    monkeypatch.setattr(application_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(application_module, "_show_native_startup_error", refuse)

    application_module.report_startup_error(
        RuntimeError("no dictionary"), interactive=False
    )

    assert "no dictionary" in capsys.readouterr().err


def test_native_startup_reporter_preloads_ocr_before_opening_the_qt_dialog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    # A session that can present a dialog at all; the headless case is below.
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")

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

    def bootstrap() -> object:
        events.append("bootstrap")
        return _Application(["hanly"])

    monkeypatch.setattr(application_module, "ensure_qt_application", bootstrap)

    application_module._show_native_startup_error("resource setup failed")

    # The shared bootstrap owns the OCR-before-Qt ordering on this path too.
    assert events == ["bootstrap", "qt", "Hanly Desktop", "resource setup failed"]


def _runtime_config(tmp_path: Path) -> Path:
    config = tmp_path / "runtime.json"
    config.write_text(
        json.dumps(
            {
                "resources": {
                    "krdict": {
                        "kind": "krdict",
                        "path": "krdict.sqlite3",
                        "installed_version": "1",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return config


def _coordinator_with_recorded_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, automatic_check: bool
) -> tuple[object, list[str]]:
    service = object()
    checks: list[str] = []

    class _Coordinator:
        def __init__(self, received: object, **options: object) -> None:
            assert received is service

        def check_for_updates(self) -> dict[str, object]:
            checks.append("check")
            return self.snapshot()

        def snapshot(self) -> dict[str, object]:
            return {"status": "checking" if checks else "idle", "resources": []}

    monkeypatch.setattr(application_module, "load_update_service", lambda *_args: service)
    monkeypatch.setattr(application_module, "UpdateCoordinator", _Coordinator)
    coordinator = application_module._update_coordinator(
        _runtime_config(tmp_path),
        ResourceManager(ResourceManifest(())),
        DiagnosticLog(),
        automatic_check=automatic_check,
    )
    return coordinator, checks


def test_disabling_update_checks_stops_the_unattended_startup_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``update_checks_enabled`` is off, so nothing reaches the network on its own."""

    coordinator, checks = _coordinator_with_recorded_checks(
        tmp_path, monkeypatch, automatic_check=False
    )

    assert coordinator is not None
    assert checks == []


def test_a_manual_check_still_works_while_automatic_checks_are_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The setting governs the unattended check, never the button the user presses."""

    coordinator, checks = _coordinator_with_recorded_checks(
        tmp_path, monkeypatch, automatic_check=False
    )
    assert coordinator is not None

    ControlCenterBridge(update_coordinator=cast(Any, coordinator)).check_for_updates()

    assert checks == ["check"]


def test_the_startup_check_runs_when_the_setting_leaves_it_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _coordinator, checks = _coordinator_with_recorded_checks(
        tmp_path, monkeypatch, automatic_check=True
    )

    assert checks == ["check"]


def test_the_desktop_passes_the_persisted_setting_to_the_coordinator() -> None:
    """The tests above hand ``_update_coordinator`` the flag directly, so only
    the composition site proves the stored setting is what reaches it. Reading
    the call out of the syntax tree keeps that independent of Qt and of how the
    call happens to be formatted."""

    source = Path(application_module.__file__).read_text(encoding="utf-8")
    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_update_coordinator"
    )
    passed = {keyword.arg: ast.unparse(keyword.value) for keyword in call.keywords}

    assert passed["automatic_check"] == "self._settings.config.update_checks_enabled"


def test_unreadable_preferences_do_not_stop_the_interface_from_opening(
    tmp_path: Path,
) -> None:
    """A setting cannot be fixed from a window that never appears."""

    settings_path = tmp_path / "config.json"
    settings_path.write_text("{not json", encoding="utf-8")
    diagnostics = DiagnosticLog()

    settings = application_module._load_settings(settings_path, diagnostics)

    assert settings.config == AppConfig()
    assert any("Preferences" in message for message in diagnostics.snapshot())


class _QtOwnedController:
    """Records which thread each Qt-owned lifecycle call actually arrived on."""

    def __init__(self, state: DesktopState = DesktopState.NEW) -> None:
        self.state = state
        self.calls: list[str] = []
        self.threads: list[threading.Thread] = []

    def _record(self, name: str) -> None:
        self.calls.append(name)
        self.threads.append(threading.current_thread())

    def start(self) -> None:
        self._record("start")
        self.state = DesktopState.RUNNING

    def pause(self) -> None:
        self._record("pause")
        self.state = DesktopState.PAUSED

    def resume(self) -> None:
        self._record("resume")
        self.state = DesktopState.RUNNING

    def apply_config(self, _config: AppConfig) -> None:
        self._record("apply_config")

    def set_capture_preferences(self, **_preferences: object) -> None:
        self._record("set_capture_preferences")

    def begin_shutdown(self) -> None:
        self._record("begin_shutdown")

    def await_shutdown(self, _timeout: float | None = None) -> bool:
        self._record("await_shutdown")
        return True


class _Desktop:
    """The half of ``DesktopApplication`` a session actually reaches for."""

    def __init__(self) -> None:
        self.closing = threading.Event()
        self.updates: list[object] = []
        self.quits = 0

    def attach_updates(self, coordinator: object) -> None:
        self.updates.append(coordinator)

    def quit(self) -> None:
        self.quits += 1

    def request_capture(self) -> None:
        return None

    def resume_capture(self) -> None:
        return None

    def pause_capture(self) -> None:
        return None

    def open_control_center(self) -> None:
        return None


def _session(
    tmp_path: Path,
    pending: queue.Queue[Callable[[], None]],
    *,
    permission_service: PermissionService | None = None,
) -> tuple[Any, _Desktop]:
    """Build the real session over doubles, with a dispatcher we can drive.

    Composition itself dispatches the first status snapshot, so the queue is
    drained here and holds only what the action under test put there.

    Permissions are supplied rather than probed: the default is the empty
    service every non-macOS platform gets, so no test result depends on the
    privacy settings of the machine it runs on.
    """

    session = application_module._DesktopSession(
        ConfigManager(tmp_path / "config.json"),
        diagnostics=DiagnosticLog(),
        status=RuntimeStatusPublisher(pending.put),
        dispatcher=pending.put,
        permission_service=permission_service or PermissionService(),
    )
    desktop = _Desktop()
    session.attach(cast(Any, desktop))
    while not pending.empty():
        pending.get_nowait()
    return session, desktop


def test_control_center_actions_reach_the_controller_on_the_qt_thread(
    tmp_path: Path,
) -> None:
    """pywebview calls the bridge off Qt, and capture is Qt-owned throughout."""

    pending: queue.Queue[Callable[[], None]] = queue.Queue()
    session, _ = _session(tmp_path, pending)
    controller = _QtOwnedController()
    session._controller = controller

    worker = threading.Thread(target=session.bridge.start_capture, name="pywebview")
    worker.start()
    try:
        dispatched = pending.get(timeout=_WAIT_SECONDS)
        # The bridge's own thread got as far as the seam and no further.
        assert controller.calls == []
        dispatched()
    finally:
        worker.join(_WAIT_SECONDS)

    assert controller.calls == ["start"]
    assert controller.threads == [threading.main_thread()]


def test_a_cancelled_selection_restores_observation_in_one_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Suspend, choose, and restore have to be one indivisible action."""

    pending: queue.Queue[Callable[[], None]] = queue.Queue()
    session, _ = _session(tmp_path, pending)
    controller = _QtOwnedController(DesktopState.RUNNING)
    session._controller = controller

    def cancelled() -> None:
        controller.calls.append("overlay")
        return None

    monkeypatch.setattr(application_module, "select_capture_area", cancelled)

    worker = threading.Thread(target=session.bridge.select_capture_area)
    worker.start()
    try:
        dispatched = pending.get(timeout=_WAIT_SECONDS)
        dispatched()
    finally:
        worker.join(_WAIT_SECONDS)

    assert controller.calls == ["pause", "overlay", "resume"]
    assert pending.empty()
    assert controller.state is DesktopState.RUNNING


def test_releasing_a_failed_attempt_waits_off_the_qt_thread(tmp_path: Path) -> None:
    """A retry must not freeze the window for the whole shutdown timeout."""

    class _Coordinator:
        def __init__(self) -> None:
            self.shutdowns: list[bool] = []

        def shutdown(self, wait: bool = False) -> None:
            self.shutdowns.append(wait)

    pending: queue.Queue[Callable[[], None]] = queue.Queue()
    session, desktop = _session(tmp_path, pending)
    controller = _QtOwnedController(DesktopState.RUNNING)
    session._controller = controller
    updates = _Coordinator()
    session._updates = updates

    worker = threading.Thread(target=session.release, name="hanly-startup")
    worker.start()
    try:
        dispatched = pending.get(timeout=_WAIT_SECONDS)
        dispatched()
    finally:
        worker.join(_WAIT_SECONDS)

    assert controller.calls == ["begin_shutdown", "await_shutdown"]
    # Only the detach belongs to Qt; the join runs where release was called.
    assert controller.threads == [threading.main_thread(), worker]
    assert updates.shutdowns == [True]
    assert desktop.updates == [None]
    assert session.state is DesktopState.NEW


def test_a_tray_without_a_way_back_ends_the_session_with_its_window() -> None:
    """Started is not usable: an Xorg tray has no menu to reopen anything, and
    a Hanly the user cannot reach is worse than one that ends when it closes."""

    events: list[str] = []
    qt = _Qt()
    tray = _Service("tray", events, can_restore_window=False)
    desktop = DesktopApplication(
        qt, _Service("controller", events), tray, _Service("control", events)
    )

    qt.during_loop = desktop.control_center_closed
    desktop.run()

    assert desktop.tray_usable is False
    assert any("cannot reopen" in message for message in desktop.diagnostics)
    assert "quit" in qt.events


def test_a_closed_window_leaves_a_usable_tray_running() -> None:
    events: list[str] = []
    qt = _Qt()
    desktop = DesktopApplication(
        qt,
        _Service("controller", events),
        _Service("tray", events),
        _Service("control", events),
    )

    qt.during_loop = desktop.control_center_closed
    desktop.run()

    assert desktop.tray_usable is True
    assert "quit" not in qt.events


def test_a_capture_action_before_activation_is_refused_not_a_lifecycle_failure(
    tmp_path: Path,
) -> None:
    """Starting while resources are still being prepared is ordinary news."""

    pending: queue.Queue[Callable[[], None]] = queue.Queue()
    session, _ = _session(tmp_path, pending)

    assert session.can_start_capture is False
    with pytest.raises(ControlCenterUnavailable, match="still preparing"):
        session.start()
    assert pending.empty()

    controller = _QtOwnedController(DesktopState.PAUSED)
    session._controller = controller
    session.start()

    assert session.can_start_capture is True
    assert controller.calls == ["resume"]


def test_the_tray_reports_a_refused_start_without_a_lifecycle_traceback() -> None:
    """The tray runs in a Qt slot, so a refusal has to come back as a note."""

    events: list[str] = []
    diagnostics = DiagnosticLog()

    class _Refusing(_Service):
        def start(self) -> None:
            raise ControlCenterUnavailable("Hanly is still preparing its lookup runtime.")

    desktop = DesktopApplication(
        _Qt(),
        _Refusing("controller", events),
        _Service("tray", events),
        _Service("control", events),
        diagnostics=diagnostics,
    )
    desktop.request_capture()

    assert diagnostics.snapshot() == ("Hanly is still preparing its lookup runtime.",)
    assert "controller.start" not in events


def test_a_runtime_that_never_lets_go_keeps_its_resources_and_stops_the_retry(
    tmp_path: Path,
) -> None:
    """A replacement must not be composed over providers that are still open."""

    class _Stubborn(_QtOwnedController):
        def __init__(self) -> None:
            super().__init__()
            self.waits = 0

        def await_shutdown(self, _timeout: float | None = None) -> bool:
            self.waits += 1
            return False

    pending: queue.Queue[Callable[[], None]] = queue.Queue()
    session, _ = _session(tmp_path, pending)
    controller = _Stubborn()
    session._controller = controller

    with pytest.raises(application_module.DesktopApplicationError):
        session.release()

    assert controller.calls == ["begin_shutdown"]
    assert session._pending_release == [controller]

    with pytest.raises(application_module.DesktopApplicationError):
        session.release()

    # The runtime nobody could stop is waited for again, not forgotten.
    assert controller.waits == 2
    assert session._pending_release == [controller]


def test_a_macos_bundle_never_keeps_mutable_configuration_inside_itself(
    tmp_path: Path,
) -> None:
    """Writing beside the program would write into the signed, replaced bundle."""

    program = tmp_path / "Applications" / "Hanly.app" / "Contents" / "MacOS" / "hanly-desktop"
    program.parent.mkdir(parents=True)
    program.write_bytes(b"frozen")
    inside = program.parent / RUNTIME_CONFIG_NAME
    inside.write_text("{}", encoding="utf-8")

    environment = {"LOCALAPPDATA": str(tmp_path / "settings")}
    per_user = default_runtime_config_path(environment)
    per_user.parent.mkdir(parents=True)
    per_user.write_text("{}", encoding="utf-8")

    assert discover_runtime_config(environment, program) == per_user


def test_a_headless_session_reports_to_stderr_instead_of_aborting_on_qt(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Qt aborts the process when no platform plugin loads, and an abort is not
    an exception this can catch, so Qt is never asked without a display."""

    def refuse() -> object:
        raise AssertionError("Qt must not be started without a display")

    monkeypatch.setattr(application_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(application_module.sys, "platform", "linux")
    monkeypatch.setattr(application_module, "ensure_qt_application", refuse)
    for name in ("DISPLAY", "WAYLAND_DISPLAY", "QT_QPA_PLATFORM"):
        monkeypatch.delenv(name, raising=False)

    application_module.report_startup_error(RuntimeError("no dictionary"))

    assert "no dictionary" in capsys.readouterr().err
    assert application_module._can_show_native_dialog({"DISPLAY": ":0"}) is True
    assert application_module._can_show_native_dialog({}) is False


class _ScriptedProbe:
    """Answers from the test rather than from this machine's privacy settings."""

    def __init__(self, missing: Permission | None) -> None:
        self._missing = missing

    def state(self, permission: Permission) -> PermissionState:
        return (
            PermissionState.REQUIRED
            if permission is self._missing
            else PermissionState.GRANTED
        )

    def request(self, permission: Permission) -> PermissionState:
        raise AssertionError("starting capture must not request a permission")


def _scripted_permissions(missing: Permission | None) -> PermissionService:
    return PermissionService(
        _ScriptedProbe(missing),
        permissions=(Permission.SCREEN_RECORDING, Permission.ACCESSIBILITY),
        cache_seconds=0.0,
    )


def test_start_is_refused_before_the_qt_thread_when_a_grant_is_missing(
    tmp_path: Path,
) -> None:
    """Both Start routes converge here, and the check must not reach Qt.

    A privacy check is a round trip to the system, so it happens on the
    caller's thread rather than inside the lifecycle dispatch.
    """

    pending: queue.Queue[Callable[[], None]] = queue.Queue()
    session, _ = _session(
        tmp_path,
        pending,
        permission_service=_scripted_permissions(Permission.SCREEN_RECORDING),
    )
    controller = _QtOwnedController(DesktopState.PAUSED)
    session._controller = controller

    with pytest.raises(ControlCenterUnavailable, match="Screen Recording"):
        session.start()

    assert controller.calls == []
    assert pending.empty()


def test_the_tray_start_is_refused_by_the_same_grant_check(tmp_path: Path) -> None:
    """The tray does not go through the Control Center, so it needs the guard."""

    pending: queue.Queue[Callable[[], None]] = queue.Queue()
    session, _ = _session(
        tmp_path,
        pending,
        permission_service=_scripted_permissions(Permission.ACCESSIBILITY),
    )
    session._controller = _QtOwnedController(DesktopState.PAUSED)
    diagnostics = DiagnosticLog()
    desktop = DesktopApplication(
        _Qt(),
        session,
        _Service("tray", []),
        _Service("control", []),
        diagnostics=diagnostics,
    )

    desktop.request_capture()

    assert diagnostics.snapshot() == (
        "Hanly needs Accessibility access before it can watch the screen.",
    )


def test_a_granted_machine_starts_capture_normally(tmp_path: Path) -> None:
    pending: queue.Queue[Callable[[], None]] = queue.Queue()
    session, _ = _session(
        tmp_path,
        pending,
        permission_service=_scripted_permissions(None),
    )
    controller = _QtOwnedController(DesktopState.PAUSED)
    session._controller = controller

    session.start()

    assert controller.calls == ["resume"]


def test_shortcuts_a_backend_refused_are_not_reported_as_registered(
    tmp_path: Path,
) -> None:
    """Registration is allowed to fail without costing the session. Saying it
    succeeded is what leaves a user pressing a key that does nothing."""

    class _Hotkeys:
        def __init__(self, registered: bool) -> None:
            self.registered = registered
            self.bindings = {HotkeyAction.LOOKUP: "ctrl+shift+space"}

    class _Manual:
        def __init__(self, registered: bool) -> None:
            self.hotkeys = _Hotkeys(registered)

    pending: queue.Queue[Callable[[], None]] = queue.Queue()
    session, _ = _session(tmp_path, pending)

    session._manual = cast(Any, _Manual(True))
    assert session.registered_hotkeys() == {"lookup": "ctrl+shift+space"}

    session._manual = cast(Any, _Manual(False))
    assert session.registered_hotkeys() == {}
