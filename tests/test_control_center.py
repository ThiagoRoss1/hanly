from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from hanly.resource_manager import ResourceManager, ResourceManifest, ResourceSpec
from hanly_app.capture import ScreenRect
from hanly_app.config import (
    HOVER_DELAY_MAX_MS,
    HOVER_DELAY_MIN_MS,
    AppConfig,
    CaptureMode,
    ConfigManager,
)
from hanly_app.control_center import (
    ControlCenterBridge,
    ControlCenterHost,
    ControlCenterUnavailable,
    load_control_center_assets,
)
from hanly_app.desktop_controller import DesktopState


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

    def pause(self) -> None:
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
                ResourceSpec(
                    "paddle_detection_model",
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
            ocr_provider="PaddleOCR",
        ),
        runtime,
        config,
    )


def test_bridge_snapshot_contains_real_resources_and_desktop_preferences(tmp_path: Path) -> None:
    bridge, _, _ = _bridge(tmp_path)

    state = bridge.get_state()

    assert state["app"]["state"] == "new"
    assert state["app"]["capture_mode"] == "full_monitor"
    assert state["runtime"]["ocr_provider"] == "PaddleOCR"
    assert state["runtime"]["resources"] == [
        {
            "id": "paddle_detection_model",
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
        config_manager=bridge._config_manager,  # type: ignore[attr-defined]
        update_coordinator=coordinator,  # type: ignore[arg-type]
    )

    assert bridge.get_state()["updates"]["status"] == "available"
    bridge.check_for_updates()
    bridge.install_update("krdict")

    assert coordinator.calls == [("check", None), ("install", "krdict")]


def test_bridge_validates_region_and_monitor_target_choices(tmp_path: Path) -> None:
    bridge, _, _ = _bridge(tmp_path)
    bridge._capture_service = SimpleNamespace(  # type: ignore[attr-defined]
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


def test_host_uses_shared_qt_event_loop_on_main_thread() -> None:
    calls: list[tuple[str, object]] = []

    class _Webview:
        def create_window(self, **kwargs: object) -> object:
            calls.append(("create_window", kwargs))
            return object()

        def start(self, **kwargs: object) -> None:
            calls.append(("start", kwargs))

    host = ControlCenterHost(object(), webview_module=_Webview())

    host.open()

    assert calls[0][0] == "create_window"
    assert calls[1] == ("start", {"gui": "qt", "debug": False})


def test_qt_webengine_is_prepared_before_qapplication_creation() -> None:
    """The shared pywebview backend must load before Qt creates its app."""

    pytest.importorskip("PyQt6")
    import hanly_app.control_center as control_center

    assert hasattr(control_center, "prepare_control_center_qt")
    control_center.prepare_control_center_qt()

    from PyQt6.QtWidgets import QApplication

    assert QApplication.instance() is None


def test_host_rejects_open_from_worker_thread() -> None:
    errors: list[BaseException] = []
    host = ControlCenterHost(object(), webview_module=object())

    def run() -> None:
        try:
            host.open()
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=run)
    thread.start()
    thread.join()

    assert len(errors) == 1
    assert "main thread" in str(errors[0])


def test_control_center_assets_are_packaged_and_have_no_provider_logic() -> None:
    assets = load_control_center_assets()

    assert "<title>Hanly · Control Center</title>" in assets.html
    assert "--jade: #47756D" in assets.css
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
