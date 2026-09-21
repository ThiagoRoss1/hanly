from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from hanly.resource_manager import ResourceManager, ResourceManifest, ResourceSpec
from hanly_app import control_center
from hanly_app.capture import ScreenRect
from hanly_app.capture_selector import CaptureSelection
from hanly_app.config import (
    HOVER_DELAY_MAX_MS,
    HOVER_DELAY_MIN_MS,
    AppConfig,
    CaptureMode,
    CaptureRegion,
    ConfigManager,
    OCRBackend,
)
from hanly_app.control_center import (
    ControlCenterBridge,
    ControlCenterUnavailable,
    load_control_center_assets,
)
from hanly_app.desktop_controller import DesktopState
from hanly_app.diagnostics import DiagnosticLog
from hanly_app.permissions import (
    Permission,
    PermissionService,
    PermissionState,
    UnsupportedPermission,
)
from hanly_app.runtime_status import RuntimeStatus

from tests.hanly_fixtures.unchecked import unchecked


class _Runtime:
    def __init__(self) -> None:
        self.events: list[str] = []

    def start(self) -> None:
        self.events.append("start")

    def invalidate(self) -> None:
        self.events.append("invalidate")

    def shutdown(self) -> None:
        self.events.append("shutdown")


class _Controller:
    """A double for the desktop lifecycle seam the Control Center requires."""

    def __init__(self, runtime: _Runtime) -> None:
        self._runtime = runtime
        self.state = DesktopState.NEW
        self.configs: list[AppConfig] = []
        self.preferences: list[tuple[CaptureMode, int | None, ScreenRect | None]] = []

    def start(self) -> None:
        self._runtime.start()
        self.state = DesktopState.RUNNING

    def stop(self) -> None:
        self._runtime.invalidate()
        self.state = DesktopState.PAUSED

    def resume(self) -> None:
        self._runtime.events.append("resume")
        self.state = DesktopState.RUNNING

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


def _bridge(tmp_path: Path) -> tuple[ControlCenterBridge, _Runtime, ConfigManager]:
    model = tmp_path / "model"
    model.mkdir()
    dictionary = tmp_path / "dictionary.sqlite3"
    dictionary.write_bytes(b"dictionary")
    manager = ResourceManager(
        ResourceManifest(
            (
                # A second, deliberately generic resource: the snapshot renders
                # whatever the manifest declares, and KRDICT is the only live
                # one, so nothing here should read as a managed OCR model.
                ResourceSpec(
                    "generic_directory",
                    model,
                    version="v1",
                    installed_version="v1",
                    kind="directory",
                ),
                ResourceSpec(
                    "krdict",
                    dictionary,
                    version="2026.08",
                    installed_version="2026.08",
                    kind="file",
                ),
            )
        ),
        base_path=tmp_path,
    )
    manager.validate()
    config = ConfigManager(tmp_path / "settings.json")
    runtime = _Runtime()
    controller = _Controller(runtime)
    return (
        ControlCenterBridge(
            config_manager=config,
            desktop_controller=controller,
            resource_manager=manager,
            ocr_provider="EasyOCR",
        ),
        runtime,
        config,
    )


def test_bridge_snapshot_contains_real_resources_and_desktop_preferences(tmp_path: Path) -> None:
    bridge, _, _ = _bridge(tmp_path)

    state = bridge.get_state()

    assert state["app"]["state"] == "new"
    assert state["app"]["capture_mode"] == "full_monitor"
    assert state["runtime"]["ocr_provider"] == "EasyOCR"
    assert state["runtime"]["resources"] == [
        {
            "id": "generic_directory",
            "kind": "directory",
            "status": "VALID",
            "version": "v1",
            "compatible": True,
            "checksum": None,
            "diagnostics": [],
        },
        {
            "id": "krdict",
            "kind": "file",
            "status": "VALID",
            "version": "2026.08",
            "compatible": True,
            "checksum": state["runtime"]["resources"][1]["checksum"],
            "diagnostics": [],
        },
    ]


def test_bridge_actions_control_capture_and_persist_settings(tmp_path: Path) -> None:
    bridge, runtime, config = _bridge(tmp_path)

    bridge.start_capture()
    bridge.set_hover_delay(220)
    bridge.set_hotkey("alt+shift+h")
    bridge.set_capture_mode("region")
    bridge.stop_capture()

    assert runtime.events == ["start", "invalidate"]
    assert config.load() == AppConfig(
        hover_delay_ms=220,
        hotkey="alt+shift+h",
        capture_mode=CaptureMode.REGION,
    )
    assert bridge.get_state()["app"]["state"] == "paused"


def test_start_capture_resumes_a_paused_desktop_controller(tmp_path: Path) -> None:
    bridge, runtime, _config = _bridge(tmp_path)

    bridge.start_capture()
    bridge.stop_capture()

    state = bridge.start_capture()

    assert runtime.events == ["start", "invalidate", "resume"]
    assert state["app"]["state"] == "running"


def test_update_actions_are_explicitly_unavailable(tmp_path: Path) -> None:
    bridge, _, _ = _bridge(tmp_path)

    status = bridge.get_state()["updates"]

    assert status == {
        "available": False,
        "status": "unavailable",
        "message": "Resource updates are not configured for this runtime.",
    }
    with pytest.raises(ControlCenterUnavailable):
        bridge.check_for_updates()


def test_update_actions_use_the_application_coordinator(tmp_path: Path) -> None:
    class _Coordinator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, object | None]] = []
            self.state = {
                "available": True,
                "status": "available",
                "message": "Resource updates are available.",
                "resources": [
                    {
                        "id": "krdict",
                        "version": "2",
                        "current_version": "1",
                        "available": True,
                    }
                ],
                "active_resource_id": None,
                "progress": None,
            }

        def snapshot(self) -> dict[str, object]:
            return self.state

        def check_for_updates(self) -> dict[str, object]:
            self.calls.append(("check", None))
            return self.state

        def install_update(self, resource_id: object | None = None) -> dict[str, object]:
            self.calls.append(("install", resource_id))
            return self.state

    bridge, _, _ = _bridge(tmp_path)
    coordinator = _Coordinator()
    bridge = ControlCenterBridge(
        config_manager=bridge._config_manager,
        update_coordinator=unchecked(coordinator),
    )

    assert bridge.get_state()["updates"]["status"] == "available"
    bridge.check_for_updates()
    bridge.install_update("krdict")

    assert coordinator.calls == [("check", None), ("install", "krdict")]


def test_bridge_validates_region_and_monitor_target_choices(tmp_path: Path) -> None:
    bridge, _, _ = _bridge(tmp_path)
    bridge._capture_service = SimpleNamespace(
        enumerate_monitors=lambda: (
            type(
                "Monitor",
                (),
                {"index": 1, "name": "Primary", "bounds": ScreenRect(0, 0, 1920, 1080)},
            )(),
        )
    )

    state = bridge.set_target("monitor:1")
    state = bridge.set_region({"left": 0, "top": 0, "width": 800, "height": 600})

    assert state["app"]["target"] == "monitor:1"
    assert state["app"]["region"] == {"left": 0, "top": 0, "width": 800, "height": 600}
    with pytest.raises(ValueError):
        bridge.set_region({"left": 0, "top": 0, "width": 0, "height": 600})


def test_control_center_assets_are_packaged_and_have_no_provider_logic() -> None:
    assets = load_control_center_assets()

    assert "<title>Hanly · Control Center</title>" in assets.html
    # One token set, redefined for the dark mode the theme control selects.
    assert "--accent: #E88CA1" in assets.css
    assert '[data-mode="dark"]' in assets.css
    assert "function renderState" in assets.javascript
    assert "function renderUpdates" in assets.javascript
    assert "install_update" in assets.javascript
    assert "sqlite" not in assets.javascript.lower()


def test_hover_delay_is_bounded_to_the_supported_range(tmp_path: Path) -> None:
    bridge, _runtime, _manager = _bridge(tmp_path)

    assert bridge.set_hover_delay(HOVER_DELAY_MIN_MS)["config"]["hover_delay_ms"] == (
        HOVER_DELAY_MIN_MS
    )
    assert bridge.set_hover_delay(HOVER_DELAY_MAX_MS)["config"]["hover_delay_ms"] == (
        HOVER_DELAY_MAX_MS
    )
    for rejected in (HOVER_DELAY_MIN_MS - 1, HOVER_DELAY_MAX_MS + 1):
        with pytest.raises(ValueError, match="hover delay must be between"):
            bridge.set_hover_delay(rejected)


def test_the_delay_slider_is_given_the_bounds_python_actually_enforces(
    tmp_path: Path,
) -> None:
    """A slider with its own constants drifts from the validator behind it."""

    bridge, _runtime, _manager = _bridge(tmp_path)

    bounds = bridge.get_state()["runtime"]["hover_delay_bounds"]
    assert bounds == {"min": HOVER_DELAY_MIN_MS, "max": HOVER_DELAY_MAX_MS}
    assert 'id="hover-delay-slider"' in load_control_center_assets().html
    assert "hover_delay_bounds" in load_control_center_assets().javascript


def test_the_installed_version_reaches_the_page_or_nothing_does() -> None:
    """The sidebar shows the running build, and shows nothing if it cannot."""

    from hanly_app import control_center

    version = control_center.ControlCenterBridge().get_state()["runtime"]["app_version"]
    assert version is None or isinstance(version, str)

    def unavailable() -> str:
        raise RuntimeError("no metadata here")

    original = control_center.installed_version
    control_center.installed_version = unavailable
    try:
        snapshot = control_center.ControlCenterBridge().get_state()
    finally:
        control_center.installed_version = original
    assert snapshot["runtime"]["app_version"] is None


def test_persisted_hotkeys_are_validated_by_the_desktop_canonicalizer(
    tmp_path: Path,
) -> None:
    """A hotkey the listener could never register must not reach the config
    file, because the next startup would fail while registering it."""

    bridge, _runtime, _manager = _bridge(tmp_path)

    assert bridge.set_hotkey("ctrl+alt+k")["config"]["hotkey"] == "ctrl+alt+k"
    for rejected in ("!!!", "ctrl+ctrl+a", "ctrl+", 5):
        with pytest.raises(ValueError):
            bridge.set_hotkey(rejected)
    with pytest.raises(ValueError):
        bridge.update_settings({"hotkey": "ctrl+ctrl+a"})
    assert bridge.get_state()["config"]["hotkey"] == "ctrl+alt+k"


def test_ui_script_resolves_the_bridge_after_pywebview_injects_it() -> None:
    """pywebview adds ``window.pywebview.api`` after the document is parsed,
    so a bridge captured at parse time stays null and every control dies."""

    javascript = load_control_center_assets().javascript

    assert "const api = window.pywebview" not in javascript
    assert "function bridge()" in javascript
    assert "const api = bridge();" in javascript


class _StubCoordinator:
    """A coordinator double exposing only the snapshot the bridge reads."""

    def __init__(self, application: object) -> None:
        self._application = application
        self.application_installs = 0
        self.confirmed_full = False
        self.cancels = 0

    def snapshot(self) -> dict[str, object]:
        return {
            "available": False,
            "status": "current",
            "message": "checked",
            "resources": [],
            "active_resource_id": None,
            "progress": None,
            "application": self._application,
            "restart_required": False,
        }

    def install_application_update(self, confirm_full: object = False) -> dict[str, object]:
        self.application_installs += 1
        self.confirmed_full = bool(confirm_full)
        return self.snapshot()

    def cancel_update(self) -> dict[str, object]:
        self.cancels += 1
        return self.snapshot()


def _bridge_with_application(application: object) -> ControlCenterBridge:
    return ControlCenterBridge(
        update_coordinator=cast(Any, _StubCoordinator(application)),
    )


def test_the_application_update_reaches_the_ui_snapshot() -> None:
    application = {
        "current_version": "0.1.0",
        "latest_version": "0.2.0",
        "release_url": "https://github.com/example/hanly/releases/tag/v0.2.0",
        "available": True,
        "installable": True,
        "message": "Hanly 0.2.0 is available. You are running 0.1.0.",
    }

    state = _bridge_with_application(application).get_state()

    assert state["updates"]["application"] == application


def test_updating_the_application_is_installed_in_app_not_in_a_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The primary update action never reaches the browser."""

    opened: list[str] = []
    monkeypatch.setattr(control_center.webbrowser, "open", lambda url: opened.append(url))
    coordinator = _StubCoordinator(
        {
            "available": True,
            "installable": True,
            "release_url": "https://github.com/example/hanly/releases/tag/v0.2.0",
            "current_version": "0.1.0",
            "latest_version": "0.2.0",
            "message": "available",
        }
    )
    bridge = ControlCenterBridge(update_coordinator=cast(Any, coordinator))

    bridge.install_application_update()

    assert coordinator.application_installs == 1
    assert opened == []


def test_installing_an_application_update_without_a_channel_is_refused() -> None:
    with pytest.raises(ControlCenterUnavailable):
        ControlCenterBridge().install_application_update()


def test_release_notes_open_the_url_the_check_returned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[str] = []
    monkeypatch.setattr(control_center.webbrowser, "open", lambda url: opened.append(url))
    bridge = _bridge_with_application(
        {
            "available": True,
            "installable": True,
            "release_url": "https://github.com/example/hanly/releases/tag/v0.2.0",
            "current_version": "0.1.0",
            "latest_version": "0.2.0",
            "message": "available",
        }
    )

    bridge.open_release_notes()

    assert opened == ["https://github.com/example/hanly/releases/tag/v0.2.0"]


@pytest.mark.parametrize(
    "application",
    [
        None,
        {"available": True, "release_url": None},
        {"available": True, "release_url": "javascript:alert(1)"},
        {"available": True, "release_url": "http://github.com/example/hanly/releases/tag/v1"},
        {"available": True, "release_url": "https://evil.test/releases/tag/v1"},
        {"available": True, "release_url": "https://github.com.evil.test/releases/tag/v1"},
        {"available": True, "release_url": "https://github.com/example/hanly/issues/1"},
    ],
)
def test_only_a_github_release_page_from_the_last_check_can_be_opened(
    application: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Neither the UI nor a hostile release payload picks the browser target."""

    opened: list[str] = []
    monkeypatch.setattr(control_center.webbrowser, "open", lambda url: opened.append(url))

    with pytest.raises(ControlCenterUnavailable):
        _bridge_with_application(application).open_release_notes()

    assert opened == []


def test_opening_release_notes_without_an_update_channel_is_refused() -> None:
    with pytest.raises(ControlCenterUnavailable):
        ControlCenterBridge().open_release_notes()


def test_the_primary_update_action_installs_in_app_and_the_browser_is_secondary() -> None:
    """Every bridge call the UI can make for an application update, and which
    one the markup makes primary."""

    assets = load_control_center_assets()

    assert "install_application_update" in assets.javascript
    assert "open_release_page" not in assets.javascript
    # The update panel is built from the coordinator's snapshot, so which
    # action is primary is decided in the script rather than in the markup.
    assert '"Install update", "btn btn-primary"' in assets.javascript
    assert '"View release notes", "btn btn-quiet"' in assets.javascript
    # The one action that reaches a browser is the notes, and only the notes.
    browser_calls = [
        line for line in assets.javascript.splitlines() if "open_release_notes" in line
    ]
    assert len(browser_calls) == 1
    assert "View release notes" in browser_calls[0]


def test_selecting_a_capture_area_persists_what_the_selector_returned(
    tmp_path: Path,
) -> None:
    """Suspending observation belongs to the selector, which owns the Qt thread."""

    bridge, runtime, settings = _bridge(tmp_path)
    controller = cast(Any, bridge)._desktop_controller
    controller.start()
    chosen = CaptureSelection.for_region(ScreenRect(12, 24, 400, 300))

    def select() -> CaptureSelection:
        runtime.events.append("select")
        return chosen

    cast(Any, bridge)._select_capture_area = select

    state = bridge.select_capture_area()

    assert "select" in runtime.events
    assert state["app"]["region"] == {"left": 12, "top": 24, "width": 400, "height": 300}
    assert state["app"]["capture_mode"] == "region"
    assert settings.config.capture_region == CaptureRegion(12, 24, 400, 300)
    assert controller.state is DesktopState.RUNNING


def test_cancelling_a_capture_selection_changes_nothing(tmp_path: Path) -> None:
    bridge, _, settings = _bridge(tmp_path)
    bridge.set_region({"left": 1, "top": 2, "width": 30, "height": 40})
    before = settings.config
    cast(Any, bridge)._select_capture_area = lambda: None

    state = bridge.select_capture_area()

    assert settings.config == before
    assert state["app"]["region"] == {"left": 1, "top": 2, "width": 30, "height": 40}


def test_selecting_a_whole_monitor_clears_region_mode(tmp_path: Path) -> None:
    bridge, _, settings = _bridge(tmp_path)
    bridge.set_region({"left": 1, "top": 2, "width": 30, "height": 40})
    bridge.set_capture_mode("region")
    cast(Any, bridge)._select_capture_area = CaptureSelection.whole_monitor

    bridge.select_capture_area()

    assert settings.config.capture_mode is CaptureMode.FULL_MONITOR


def test_capture_selection_is_reported_as_unavailable_without_a_selector(
    tmp_path: Path,
) -> None:
    bridge, _, _ = _bridge(tmp_path)

    with pytest.raises(ControlCenterUnavailable, match="capture selection"):
        bridge.select_capture_area()


def test_the_window_can_end_the_session_itself(tmp_path: Path) -> None:
    """The tray is not a route on every desktop; the window always is."""

    quits: list[str] = []
    bridge, _, _ = _bridge(tmp_path)
    cast(Any, bridge)._on_quit = lambda: quits.append("quit")

    state = bridge.quit()

    assert quits == ["quit"]
    assert "app" in state


def test_quitting_is_reported_as_unavailable_without_a_way_to_quit(
    tmp_path: Path,
) -> None:
    bridge, _, _ = _bridge(tmp_path)

    with pytest.raises(ControlCenterUnavailable, match="quit"):
        bridge.quit()


def test_runtime_status_and_log_location_reach_the_page(tmp_path: Path) -> None:
    bridge = ControlCenterBridge(
        runtime_status=lambda: RuntimeStatus("failed", "resources", "no dictionary"),
        log_path=tmp_path / "logs" / "hanly.log",
    )

    runtime = bridge.get_state()["runtime"]

    assert runtime["status"] == {
        "phase": "failed",
        "stage": "resources",
        "message": "no dictionary",
    }
    assert runtime["log_path"] == str(tmp_path / "logs" / "hanly.log")


def test_retrying_is_refused_until_startup_supplies_the_action(tmp_path: Path) -> None:
    bridge, _, _ = _bridge(tmp_path)
    with pytest.raises(ControlCenterUnavailable, match="retry"):
        bridge.retry_runtime()

    retries: list[str] = []
    bridge.set_retry(lambda: retries.append("retry"))
    bridge.retry_runtime()

    assert retries == ["retry"]


def test_the_page_says_when_a_region_scope_has_no_region_to_read() -> None:
    """A monitor can disappear between sessions; the fallback must be visible."""

    assets = load_control_center_assets()

    assert "reading the whole monitor" in assets.javascript
    assert 'capture_mode === "region"' in assets.javascript


def test_start_capture_is_refused_while_the_runtime_is_still_preparing() -> None:
    """A preparing runtime refuses Start rather than reporting a live capture."""

    runtime = _Runtime()
    controller = _Controller(runtime)
    ready = [False]
    bridge = ControlCenterBridge(
        desktop_controller=controller,
        capture_ready=lambda: ready[0],
        runtime_status=lambda: RuntimeStatus("preparing", "resources", "Preparing..."),
    )

    with pytest.raises(ControlCenterUnavailable, match="still preparing"):
        bridge.start_capture()

    assert runtime.events == []
    assert bridge.get_state()["app"]["capture_running"] is False

    ready[0] = True
    state = bridge.start_capture()

    assert runtime.events == ["start"]
    assert state["app"]["capture_running"] is True


class _PermissionProbe:
    """Scripted platform answers for the bridge's permission snapshot."""

    def __init__(self, **states: PermissionState) -> None:
        self.states = {Permission(name): state for name, state in states.items()}
        self.requests: list[Permission] = []

    def state(self, permission: Permission) -> PermissionState:
        return self.states[permission]

    def request(self, permission: Permission) -> PermissionState:
        self.requests.append(permission)
        self.states[permission] = PermissionState.GRANTED
        return PermissionState.GRANTED


def _permission_service(**states: PermissionState) -> PermissionService:
    return PermissionService(
        _PermissionProbe(**states),
        permissions=(Permission.SCREEN_RECORDING, Permission.ACCESSIBILITY),
        cache_seconds=0.0,
    )


def test_the_snapshot_reports_each_permission_with_its_own_state() -> None:
    bridge = ControlCenterBridge(
        permission_service=_permission_service(
            screen_recording=PermissionState.GRANTED,
            accessibility=PermissionState.REQUIRED,
        )
    )

    permissions = bridge.get_state()["permissions"]

    assert permissions["supported"] is True
    assert [(item["id"], item["state"]) for item in permissions["items"]] == [
        ("screen_recording", "granted"),
        ("accessibility", "required"),
    ]
    accessibility = permissions["items"][1]
    assert accessibility["label"] == "Accessibility"
    assert accessibility["granted"] is False
    assert accessibility["requirement"]


def test_a_missing_screen_recording_grant_says_so_next_to_the_restart_note() -> None:
    """macOS may not hand a running process a grant the user just gave."""

    bridge = ControlCenterBridge(
        permission_service=_permission_service(
            screen_recording=PermissionState.REQUIRED,
            accessibility=PermissionState.GRANTED,
        )
    )

    items = {item["id"]: item for item in bridge.get_state()["permissions"]["items"]}

    assert "restarted" in items["screen_recording"]["restart_note"]
    assert items["accessibility"]["restart_note"] == ""


def test_start_capture_is_refused_with_the_grant_that_is_missing() -> None:
    runtime = _Runtime()
    controller = _Controller(runtime)
    bridge = ControlCenterBridge(
        desktop_controller=controller,
        permission_service=_permission_service(
            screen_recording=PermissionState.REQUIRED,
            accessibility=PermissionState.GRANTED,
        ),
    )

    with pytest.raises(ControlCenterUnavailable, match="Screen Recording"):
        bridge.start_capture()

    assert runtime.events == []
    assert bridge.get_state()["app"]["capture_running"] is False


def test_granting_a_permission_flips_the_state_the_page_renders_next() -> None:
    runtime = _Runtime()
    controller = _Controller(runtime)
    service = _permission_service(
        screen_recording=PermissionState.REQUIRED,
        accessibility=PermissionState.GRANTED,
    )
    bridge = ControlCenterBridge(desktop_controller=controller, permission_service=service)

    state = bridge.grant_permission("screen_recording")

    items = {item["id"]: item for item in state["permissions"]["items"]}
    assert items["screen_recording"]["state"] == "granted"
    assert bridge.start_capture()["app"]["capture_running"] is True


def test_rechecking_permissions_asks_the_system_again() -> None:
    probe = _PermissionProbe(
        screen_recording=PermissionState.REQUIRED,
        accessibility=PermissionState.GRANTED,
    )
    service = PermissionService(
        probe,
        permissions=(Permission.SCREEN_RECORDING, Permission.ACCESSIBILITY),
        cache_seconds=3600.0,
    )
    bridge = ControlCenterBridge(permission_service=service)
    assert bridge.get_state()["permissions"]["items"][0]["state"] == "required"

    probe.states[Permission.SCREEN_RECORDING] = PermissionState.GRANTED
    state = bridge.refresh_permissions()

    assert state["permissions"]["items"][0]["state"] == "granted"


def test_an_unknown_permission_name_from_the_page_is_refused() -> None:
    bridge = ControlCenterBridge(permission_service=_permission_service())

    with pytest.raises(UnsupportedPermission):
        bridge.grant_permission("camera")


def test_platforms_without_privacy_gates_neither_report_nor_refuse() -> None:
    """No invented permission UI, and no refusal, off macOS."""

    runtime = _Runtime()
    bridge = ControlCenterBridge(desktop_controller=_Controller(runtime))

    assert bridge.get_state()["permissions"] == {"supported": False, "items": []}
    assert bridge.start_capture()["app"]["capture_running"] is True
    assert runtime.events == ["start"]


class _Bindings:
    """A lifecycle whose ``apply_config`` registers shortcuts, or refuses to."""

    def __init__(self, *, refuse: str | None = None, refuse_restore: bool = False) -> None:
        self.state = DesktopState.NEW
        self.applied: list[AppConfig] = []
        self.registered = AppConfig()
        self.rebinds = 0
        self._refuse = refuse
        self._refuse_restore = refuse_restore

    def start(self) -> None:
        self.state = DesktopState.RUNNING

    def stop(self) -> None:
        self.state = DesktopState.PAUSED

    def resume(self) -> None:
        self.state = DesktopState.RUNNING

    def apply_config(self, config: AppConfig) -> None:
        rebinding = config.hotkey != self.registered.hotkey or (
            config.hover_hotkey != self.registered.hover_hotkey
        )
        if rebinding and self._refuse is not None:
            raise RuntimeError(self._refuse)
        if rebinding:
            self.rebinds += 1
            if self._refuse_restore and self.rebinds > 1:
                raise RuntimeError("macOS refused to put the previous shortcut back")
        self.applied.append(config)
        self.registered = config

    def set_capture_preferences(self, **_options: object) -> None:
        pass


def _rebinding_bridge(
    tmp_path: Path, controller: _Bindings
) -> tuple[ControlCenterBridge, ConfigManager]:
    manager = ConfigManager(tmp_path / "settings.json")
    bridge = ControlCenterBridge(
        config_manager=manager,
        desktop_controller=cast(Any, controller),
        registered_hotkeys=lambda: {
            "lookup": controller.registered.hotkey,
            "toggle_hover": controller.registered.hover_hotkey,
        },
        engine_status=lambda: {"state": "sleeping", "message": "not loaded"},
    )
    return bridge, manager


def test_a_shortcut_is_registered_before_it_is_stored(tmp_path: Path) -> None:
    """A refused registration must never leave saved settings describing keys
    the user's keyboard does not have."""

    controller = _Bindings()
    bridge, manager = _rebinding_bridge(tmp_path, controller)

    bridge.update_settings({"hover_hotkey": "ctrl+alt+j"})

    assert controller.registered.hover_hotkey == "ctrl+alt+j"
    assert manager.config.hover_hotkey == "ctrl+alt+j"
    assert ConfigManager(tmp_path / "settings.json").load().hover_hotkey == "ctrl+alt+j"


def test_a_refused_registration_changes_nothing(tmp_path: Path) -> None:
    controller = _Bindings(refuse="another application already uses that shortcut")
    bridge, manager = _rebinding_bridge(tmp_path, controller)

    with pytest.raises(Exception, match="another application"):
        bridge.update_settings({"hotkey": "ctrl+alt+k"})

    assert manager.config.hotkey == AppConfig().hotkey
    assert not (tmp_path / "settings.json").exists()


def test_a_save_that_fails_after_registration_puts_the_shortcuts_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = _Bindings()
    bridge, manager = _rebinding_bridge(tmp_path, controller)

    def refuse(_config: AppConfig | None = None) -> AppConfig:
        raise OSError("the settings file is read only")

    monkeypatch.setattr(manager, "save", refuse)

    with pytest.raises(OSError, match="read only"):
        bridge.update_settings({"hotkey": "ctrl+alt+k"})

    assert controller.registered.hotkey == AppConfig().hotkey
    assert bridge.get_state()["runtime"]["hotkeys"]["lookup"] == AppConfig().hotkey


def test_a_lost_binding_is_never_reported_as_a_saved_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both halves failed, so the page is told to look at what is registered
    rather than at a preference that never took effect."""

    controller = _Bindings(refuse_restore=True)
    bridge, manager = _rebinding_bridge(tmp_path, controller)

    def refuse(_config: AppConfig | None = None) -> AppConfig:
        raise OSError("the settings file is read only")

    monkeypatch.setattr(manager, "save", refuse)

    with pytest.raises(ControlCenterUnavailable, match="previous shortcuts back"):
        bridge.update_settings({"hotkey": "ctrl+alt+k"})


def test_a_setting_that_changes_no_shortcut_is_stored_then_applied(
    tmp_path: Path,
) -> None:
    controller = _Bindings()
    bridge, manager = _rebinding_bridge(tmp_path, controller)

    bridge.update_settings({"lookup_preload": "always"})

    assert manager.config.lookup_preload.value == "always"
    assert controller.applied[-1].lookup_preload.value == "always"


def test_popup_preferences_are_persisted_and_applied_live(tmp_path: Path) -> None:
    controller = _Bindings()
    bridge, manager = _rebinding_bridge(tmp_path, controller)

    state = bridge.update_settings(
        {"popup_default_size": "expanded", "technical_details": "full"}
    )

    assert manager.config.popup_default_size.value == "expanded"
    assert manager.config.technical_details.value == "full"
    assert controller.applied[-1] == manager.config
    assert state["config"]["popup_default_size"] == "expanded"


def test_the_snapshot_reports_the_engine_apart_from_shell_readiness(
    tmp_path: Path,
) -> None:
    controller = _Bindings()
    bridge, _manager = _rebinding_bridge(tmp_path, controller)

    runtime = bridge.get_state()["runtime"]

    assert runtime["engine"] == {"state": "sleeping", "message": "not loaded"}
    assert runtime["status"]["phase"] == "idle"
    assert runtime["hotkeys"]["toggle_hover"] == AppConfig().hover_hotkey


def test_an_invented_activation_choice_names_what_was_offered(tmp_path: Path) -> None:
    controller = _Bindings()
    bridge, _manager = _rebinding_bridge(tmp_path, controller)

    with pytest.raises(ValueError, match="always_active"):
        bridge.update_settings({"hover_activation": "sometimes"})


def test_every_new_preference_has_a_control_on_the_page() -> None:
    """A setting the page cannot reach is a setting the user does not have."""

    assets = load_control_center_assets()

    for element in ("lookup-preload", "live-engine", "hover-mode-rows", "shortcut-list",
                    "theme-choices", "popup-size-choices", "technical-detail-choices",
                    "hover-delay-slider", "hover-delay-value"):
        assert f'id="{element}"' in assets.html, element
    for choice in ("when_capture_starts", "always", "on_demand"):
        assert f'value="{choice}"' in assets.html, choice
    # The shortcut rows and the activation modes are rendered from the config
    # field names, so those are what the script has to name.
    for field in ("hover_hotkey", "capture_hotkey", "hover_activation",
                  "always_active", "push_to_hover", "theme", "popup_default_size",
                  "technical_details"):
        assert field in assets.javascript, field
    assert "update_settings" in assets.javascript


def _log_bridge(tmp_path: Path) -> tuple[ControlCenterBridge, DiagnosticLog, Path]:
    from hanly_app.diagnostics import RotatingLogFile

    log_path = tmp_path / "logs" / "hanly.log"
    log = DiagnosticLog(RotatingLogFile(log_path))
    bridge = ControlCenterBridge(
        config_manager=ConfigManager(tmp_path / "settings.json"),
        diagnostics=log.snapshot,
        diagnostic_log=log,
        log_path=log_path,
    )
    return bridge, log, log_path


def test_the_logs_panel_is_given_records_and_what_to_filter_them_by(
    tmp_path: Path,
) -> None:
    bridge, log, _path = _log_bridge(tmp_path)
    log.record("Capture", "Hanly is watching the screen.")
    log.report("Startup", RuntimeError("no runtime"))

    logs = bridge.get_logs()
    records = cast(list[dict[str, str]], logs["records"])

    assert [record["subsystem"] for record in records] == ["Capture", "Startup"]
    assert [record["level"] for record in records] == ["info", "error"]
    assert logs["subsystems"] == ["Capture", "Startup"]
    assert logs["levels"] == ["info", "warning", "error"]


def test_clearing_empties_both_the_panel_and_the_file(tmp_path: Path) -> None:
    """A Clear that left the file behind is a promise the next export breaks."""

    bridge, log, log_path = _log_bridge(tmp_path)
    log.record("Capture", "Hanly is watching the screen.")
    assert log_path.is_file()

    logs = bridge.clear_logs()

    assert logs["records"] == []
    assert not log_path.exists()


def test_a_file_that_cannot_be_emptied_is_reported_rather_than_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge, log, log_path = _log_bridge(tmp_path)
    log.record("Capture", "watching")
    real_unlink = Path.unlink

    def refuse(self: Path, missing_ok: bool = False) -> None:
        if self == log_path:
            raise PermissionError("the log file is in use")
        real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", refuse)

    with pytest.raises(ControlCenterUnavailable, match="log file was not"):
        bridge.clear_logs()
    assert log.records() == ()


def test_the_export_writes_a_shareable_report_beside_the_log(tmp_path: Path) -> None:
    bridge, log, log_path = _log_bridge(tmp_path)
    log.record("Capture", "Hanly is watching the screen.")

    saved = bridge.export_diagnostics()

    written = Path(str(saved["path"]))
    assert written.parent == log_path.parent
    assert saved["records"] == 1
    payload = json.loads(written.read_text(encoding="utf-8"))
    assert payload["state"]["preferences"]["hotkey"] == AppConfig().hotkey
    assert payload["records"][0]["subsystem"] == "Capture"
    assert "platform" in payload and "versions" in payload


def test_a_build_without_a_log_says_so_rather_than_exporting_nothing(
    tmp_path: Path,
) -> None:
    bridge = ControlCenterBridge(config_manager=ConfigManager(tmp_path / "settings.json"))

    with pytest.raises(ControlCenterUnavailable, match="no diagnostics log"):
        bridge.export_diagnostics()
    with pytest.raises(ControlCenterUnavailable, match="no diagnostics log"):
        bridge.clear_logs()


def test_the_logs_panel_renders_records_with_text_content_only() -> None:
    """A log line can hold anything an operating system put in an error."""

    assets = load_control_center_assets()

    for element in ("log-list", "log-levels", "log-subsystem", "log-search"):
        assert f'id="{element}"' in assets.html, element
    for action in ("refresh-logs", "copy-logs", "clear-logs", "export-diagnostics"):
        assert f'id="{action}"' in assets.html, action
    body = assets.javascript.split("function renderLogs(", 1)[1].split("function loadLogs", 1)[0]
    # Records reach the page only through the one element helper, which sets
    # text and never markup.
    assert "innerHTML" not in body
    assert "el(" in body
    helper = assets.javascript.split("function el(", 1)[1].split("function attr(", 1)[0]
    assert "textContent" in helper
    assert "innerHTML" not in helper


def test_the_update_panel_states_what_is_downloaded_and_what_remains() -> None:
    """A percentage on its own is what made the last update look frozen: the
    page has to say the size, the bytes left, and which stage is running."""

    assets = load_control_center_assets()

    assert 'id="activity-list"' in assets.html
    for fragment in (
        "function describePlan",
        "function describeTransfer",
        '"Download full update"',
        "remaining",
    ):
        assert fragment in assets.javascript, fragment
    # Both are real bridge operations, not page-local state. The second click
    # authorizing a full download is the argument, not a different action.
    assert '"Cancel", "btn btn-sm btn-quiet", "cancel_update"' in assets.javascript
    assert '"install_application_update", "true"' in assets.javascript


def test_a_download_at_one_hundred_percent_is_not_reported_as_finished() -> None:
    """Explaining the gap is the whole point of the byte line: the payload is
    in and the files are still being replaced."""

    javascript = load_control_center_assets().javascript

    assert "remaining" in javascript
    assert "formatBytes" in javascript
    # Stage labels come from the coordinator's phases, so the page never
    # invents one smooth percentage across network, unpacking and restart.
    for phase in ("inspecting", "unpacking", "preparing"):
        assert phase in javascript, phase


def test_the_activity_tail_is_bounded_rather_than_appended_to() -> None:
    """The snapshot crosses a pipe on every poll, so an ever-growing log would
    make a long update slower the longer it ran."""

    from hanly_app.update_coordinator import ACTIVITY_LIMIT

    assert ACTIVITY_LIMIT <= 200
    javascript = load_control_center_assets().javascript
    body = javascript.split("function renderActivity(", 1)[1].split("// ---- readiness", 1)[0]
    assert "clear(list)" in body
    assert "appendChild(list)" not in body


def test_the_readiness_panel_names_the_recognizer_actually_in_use() -> None:
    """The panel showed a hardcoded "EasyOCR" whatever the preference said.

    The label is resolved on read rather than captured at construction, because
    the recognizer is a live setting and the bridge outlives a change to it.
    """

    from hanly_app.runtime import ocr_display_name

    selected = {"backend": OCRBackend.AUTO}
    bridge = ControlCenterBridge(
        ocr_provider=lambda: ocr_display_name(selected["backend"])
    )

    selected["backend"] = OCRBackend.EASYOCR
    assert bridge.get_state()["runtime"]["ocr_provider"] == "EasyOCR"

    selected["backend"] = OCRBackend.VISION
    assert bridge.get_state()["runtime"]["ocr_provider"] == "Apple Vision"


def test_a_plain_string_recognizer_label_still_works() -> None:
    state = ControlCenterBridge(ocr_provider="EasyOCR").get_state()

    assert state["runtime"]["ocr_provider"] == "EasyOCR"
