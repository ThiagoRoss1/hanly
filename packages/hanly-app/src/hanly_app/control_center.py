"""The pywebview Control Center and its UI-independent application bridge.

The bridge exposes snapshots and small desktop actions as JSON-compatible
values. It does not construct providers, open databases, or perform language
processing. ``ControlCenterHost`` deliberately selects pywebview's Qt backend
so it can reuse the ``QApplication`` that already hosts the popup.
"""

from __future__ import annotations

import sys
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any, Protocol, cast

from hanly.resource_manager import ResourceManager

from .capture import CaptureService, MonitorInfo, ScreenRect
from .config import HOVER_DELAY_MAX_MS, HOVER_DELAY_MIN_MS, AppConfig, CaptureMode, ConfigManager
from .desktop_controller import DesktopState
from .hotkeys import HotkeyError, canonical_hotkey
from .runtime import HanlyRuntime
from .update_coordinator import UpdateCoordinator


class ControlCenterUnavailable(RuntimeError):
    """Raised when an intentionally deferred Control Center action is used."""


def prepare_control_center_qt() -> None:
    """Prepare Qt WebEngine before the shared ``QApplication`` is created.

    Qt WebEngine requires either an early import or the shared-OpenGL-context
    application attribute before Qt constructs its application object. Desktop
    startup must call this before creating the popup's ``QApplication``.
    """

    try:
        from PyQt6.QtCore import QCoreApplication, Qt
    except ImportError as error:
        raise ControlCenterUnavailable(
            "the Control Center requires the pywebview Qt6 runtime extra"
        ) from error

    module_name = "PyQt6.QtWebEngineWidgets"
    if QCoreApplication.instance() is not None and module_name not in sys.modules:
        raise ControlCenterUnavailable(
            "prepare_control_center_qt() must run before QApplication is created"
        )

    QCoreApplication.setAttribute(
        Qt.ApplicationAttribute.AA_ShareOpenGLContexts,
    )
    try:
        __import__(module_name)
    except ImportError as error:
        raise ControlCenterUnavailable(
            "the Control Center requires the pywebview Qt6 runtime extra"
        ) from error


class DesktopLifecycle(Protocol):
    """What the Control Center genuinely requires of the desktop controller.

    Every member backs a visible control, so a controller missing one would
    make a button or setting silently do nothing rather than fail visibly.
    """

    @property
    def state(self) -> DesktopState:
        """The current desktop lifecycle state."""

    def start(self) -> None:
        """Start capture from a new or shut-down state."""

    def pause(self) -> None:
        """Stop capture while leaving the desktop startable."""

    def resume(self) -> None:
        """Resume capture after :meth:`pause`."""

    def apply_config(self, config: AppConfig) -> None:
        """Apply persisted desktop preferences to running services."""

    def set_capture_preferences(
        self,
        *,
        capture_mode: CaptureMode,
        monitor: int | None,
        region: ScreenRect | None,
    ) -> None:
        """Apply the selected capture target and region."""


class MonitorSource(Protocol):
    """The monitor enumeration needed to populate target choices."""

    def enumerate_monitors(self) -> Sequence[MonitorInfo]:
        """Return selectable monitors without performing a capture."""


@dataclass(frozen=True, slots=True)
class ControlCenterAssets:
    """The packaged UI files loaded for a pywebview window."""

    html: str
    css: str
    javascript: str
    html_path: Path


@dataclass(frozen=True, slots=True)
class _SelectedRegion:
    """A normalized, serializable region selection."""

    rect: ScreenRect

    def to_dict(self) -> dict[str, int]:
        return {
            "left": self.rect.left,
            "top": self.rect.top,
            "width": self.rect.width,
            "height": self.rect.height,
        }


def load_control_center_assets() -> ControlCenterAssets:
    """Load the HTML/CSS/JS bundle from package data."""

    asset_root = files("hanly_app").joinpath("assets").joinpath("control_center")
    html_path = Path(str(asset_root.joinpath("index.html")))
    return ControlCenterAssets(
        html=asset_root.joinpath("index.html").read_text(encoding="utf-8"),
        css=asset_root.joinpath("control_center.css").read_text(encoding="utf-8"),
        javascript=asset_root.joinpath("control_center.js").read_text(encoding="utf-8"),
        html_path=html_path,
    )


def _inline_assets(assets: ControlCenterAssets) -> str:
    """Make one self-contained document so zipped wheels work as well."""

    document = assets.html.replace(
        '<link rel="stylesheet" href="control_center.css">',
        f"<style>\n{assets.css}\n</style>",
    )
    return document.replace(
        '<script src="control_center.js"></script>',
        f"<script>\n{assets.javascript}\n</script>",
    )


class ControlCenterBridge:
    """Expose normalized app/config/resource state to the web UI.

    ``resource_manager`` is read through its normalized metadata API. Concrete
    provider instances and dictionary storage never cross this boundary.
    """

    _UPDATE_STATUS = {
        "available": False,
        "status": "unavailable",
        "message": "Resource updates are not configured for this runtime.",
    }

    def __init__(
        self,
        *,
        config_manager: ConfigManager | None = None,
        desktop_controller: DesktopLifecycle | None = None,
        capture_service: MonitorSource | CaptureService | None = None,
        resource_manager: ResourceManager | None = None,
        update_service: object | None = None,
        update_coordinator: UpdateCoordinator | None = None,
        diagnostics: Callable[[], Sequence[str]] | None = None,
        on_lifecycle_changed: Callable[[], None] | None = None,
        runtime: HanlyRuntime | None = None,
        ocr_provider: str = "PaddleOCR",
    ) -> None:
        if config_manager is not None and not isinstance(config_manager, ConfigManager):
            raise TypeError("config_manager must be a ConfigManager")

        if not isinstance(ocr_provider, str) or not ocr_provider.strip():
            raise ValueError("ocr_provider must be a non-empty string")
        if diagnostics is not None and not callable(diagnostics):
            raise TypeError("diagnostics must be callable")
        if on_lifecycle_changed is not None and not callable(on_lifecycle_changed):
            raise TypeError("on_lifecycle_changed must be callable")

        self._config_manager = config_manager
        self._config = config_manager.config if config_manager is not None else AppConfig()
        self._desktop_controller = desktop_controller
        self._capture_service = capture_service
        self._resource_manager = resource_manager or (
            runtime.resource_manager if runtime is not None else None
        )
        self._ocr_provider = ocr_provider.strip()
        self._diagnostics = diagnostics
        self._on_lifecycle_changed = on_lifecycle_changed
        if update_service is not None and update_coordinator is not None:
            raise ValueError("pass update_service or update_coordinator, not both")
        self._update_coordinator = update_coordinator or (
            UpdateCoordinator(cast(Any, update_service), resource_manager=self._resource_manager)
            if update_service is not None
            else None
        )
        self._capture_running = False
        self._target: str = "cursor"
        self._region: _SelectedRegion | None = None

    def get_state(self) -> dict[str, Any]:
        """Return the complete UI snapshot in JSON-compatible primitives."""

        config = self._current_config()
        state_name = self._desktop_state()
        return {
            "app": {
                "state": state_name,
                "capture_running": self._is_capture_running(state_name),
                "capture_mode": config.capture_mode.value,
                "target": self._target,
                "region": None if self._region is None else self._region.to_dict(),
                "targets": self._targets(),
            },
            "config": config.to_dict(),
            "runtime": {
                "ocr_provider": self._ocr_provider,
                "resources": self._resources(),
                "diagnostics": (
                    list(self._diagnostics()) if self._diagnostics is not None else []
                ),
            },
            "updates": (
                self._update_coordinator.snapshot()
                if self._update_coordinator is not None
                else dict(self._UPDATE_STATUS)
            ),
        }

    def start_capture(self) -> dict[str, Any]:
        """Start capture through the existing desktop lifecycle controller."""

        controller = self._desktop_controller
        if controller is not None:
            if controller.state is DesktopState.PAUSED:
                controller.resume()
            else:
                controller.start()
        self._capture_running = True
        self._notify_lifecycle_changed()
        return self.get_state()

    def stop_capture(self) -> dict[str, Any]:
        """Pause capture through the existing desktop lifecycle controller."""

        if self._desktop_controller is not None:
            self._desktop_controller.pause()
        self._capture_running = False
        self._notify_lifecycle_changed()
        return self.get_state()

    def set_capture_mode(self, mode: object) -> dict[str, Any]:
        """Persist the monitor-wide or selected-region capture mode."""

        self._update_config(capture_mode=mode)
        return self.get_state()

    def set_target(self, target: object) -> dict[str, Any]:
        """Select the cursor target or one of the enumerated monitors."""

        if target == "cursor":
            self._target = "cursor"
        else:
            index = self._target_index(target)
            if not any(item["index"] == index for item in self._targets()):
                raise ValueError(f"unknown capture target: {target!r}")
            self._target = f"monitor:{index}"
        self._apply_capture_preferences()
        return self.get_state()

    def set_region(self, region: Mapping[str, object] | None) -> dict[str, Any]:
        """Store a validated screen-space region for the next capture."""

        if region is None:
            self._region = None
        else:
            self._region = _SelectedRegion(_screen_rect(region))
        self._apply_capture_preferences()
        return self.get_state()

    def set_hover_delay(self, delay_ms: object) -> dict[str, Any]:
        """Persist the debounce delay in milliseconds."""

        if isinstance(delay_ms, bool) or not isinstance(delay_ms, int):
            raise ValueError("hover delay must be an integer number of milliseconds")
        if not HOVER_DELAY_MIN_MS <= delay_ms <= HOVER_DELAY_MAX_MS:
            raise ValueError(
                "hover delay must be between "
                f"{HOVER_DELAY_MIN_MS} and {HOVER_DELAY_MAX_MS} milliseconds"
            )
        self._update_config(hover_delay_ms=delay_ms)
        return self.get_state()

    def set_hotkey(self, hotkey: object) -> dict[str, Any]:
        """Persist a hotkey the desktop listener can actually register."""

        self._update_config(hotkey=_validated_hotkey(hotkey))
        return self.get_state()

    def update_settings(self, changes: Mapping[str, object]) -> dict[str, Any]:
        """Persist a narrow set of desktop preferences from the UI."""

        if not isinstance(changes, Mapping):
            raise TypeError("settings must be a mapping")
        supported = {
            "hotkey",
            "hover_delay_ms",
            "capture_mode",
            "theme",
            "popup_enabled",
            "update_checks_enabled",
        }
        unknown = set(changes) - supported
        if unknown:
            names = ", ".join(sorted(unknown))
            raise ValueError(f"unsupported Control Center setting(s): {names}")
        values = dict(changes)
        if "hotkey" in values:
            values["hotkey"] = _validated_hotkey(values["hotkey"])
        self._update_config(**values)
        return self.get_state()

    def check_for_updates(self) -> dict[str, object]:
        """Schedule a non-blocking update availability check."""

        if self._update_coordinator is None:
            raise ControlCenterUnavailable(self._UPDATE_STATUS["message"])
        self._update_coordinator.check_for_updates()
        return self.get_state()

    def install_update(self, resource_id: object | None = None) -> dict[str, object]:
        """Schedule one non-blocking update installation."""

        if self._update_coordinator is None:
            raise ControlCenterUnavailable(self._UPDATE_STATUS["message"])
        self._update_coordinator.install_update(resource_id)
        return self.get_state()

    def replace_capture_service(
        self,
        capture_service: MonitorSource | CaptureService,
    ) -> None:
        """Use the capture seam rebuilt after safe resource activation."""

        self._capture_service = capture_service

    def apply_live_state(self) -> None:
        """Reapply persisted config and transient target/region state."""

        self._apply_live_config()

    def _current_config(self) -> AppConfig:
        return self._config_manager.config if self._config_manager is not None else self._config

    def _notify_lifecycle_changed(self) -> None:
        if self._on_lifecycle_changed is not None:
            self._on_lifecycle_changed()

    def _update_config(self, **changes: object) -> None:
        if self._config_manager is not None:
            self._config_manager.update(**changes)
        else:
            values: dict[str, Any] = self._config.to_dict()
            values.update(changes)
            self._config = AppConfig.from_dict(values)
        self._apply_live_config()

    def _apply_live_config(self) -> None:
        """Forward persisted settings to a desktop controller when present."""

        if self._desktop_controller is None:
            return
        self._desktop_controller.apply_config(self._current_config())
        self._apply_capture_preferences()

    def _apply_capture_preferences(self) -> None:
        """Forward target and region state through the app-owned seam."""

        if self._desktop_controller is None:
            return
        monitor = None if self._target == "cursor" else self._target_index(self._target)
        region = None if self._region is None else self._region.rect
        self._desktop_controller.set_capture_preferences(
            capture_mode=self._current_config().capture_mode,
            monitor=monitor,
            region=region,
        )

    def _desktop_state(self) -> str:
        if self._desktop_controller is None:
            return "running" if self._capture_running else "new"
        return self._desktop_controller.state.name.lower()

    def _is_capture_running(self, state_name: str) -> bool:
        return state_name == "running" or self._capture_running

    def _targets(self) -> list[dict[str, object]]:
        if self._capture_service is None:
            return []
        try:
            monitors = self._capture_service.enumerate_monitors()
        except Exception:
            return []
        return [
            {
                "index": monitor.index,
                "name": monitor.name,
                "bounds": {
                    "left": monitor.bounds.left,
                    "top": monitor.bounds.top,
                    "width": monitor.bounds.width,
                    "height": monitor.bounds.height,
                },
            }
            for monitor in monitors
        ]

    def _target_index(self, target: object) -> int:
        if isinstance(target, bool):
            raise ValueError("capture target must be cursor or a monitor index")
        if isinstance(target, int):
            return target
        if isinstance(target, str) and target.startswith("monitor:"):
            value = target.removeprefix("monitor:")
            if value.isdigit():
                return int(value)
        raise ValueError("capture target must be cursor or a monitor index")

    def _resources(self) -> list[dict[str, object]]:
        if self._resource_manager is None:
            return []
        try:
            statuses = self._resource_manager.statuses
            specs = {spec.resource_id: spec for spec in self._resource_manager.manifest}
        except Exception:
            return []
        resources: list[dict[str, object]] = []
        for resource_id, metadata in statuses.items():
            spec = specs.get(resource_id)
            resource: dict[str, object] = {
                "id": resource_id,
                "kind": spec.kind if spec is not None else "resource",
                "status": metadata.status.value,
                "version": metadata.version,
                "compatible": metadata.compatible,
                "checksum": metadata.checksum,
                "diagnostics": list(self._resource_manager.diagnostics(resource_id)),
            }
            resources.append(resource)
        return resources


def _validated_hotkey(hotkey: object) -> str:
    """Reject a spelling the desktop hotkey listener could not register."""

    if not isinstance(hotkey, str):
        raise ValueError("hotkey must be a string")
    try:
        canonical_hotkey(hotkey)
    except HotkeyError as error:
        raise ValueError(f"unsupported hotkey: {error}") from error
    return hotkey


def _region_bound(values: Mapping[str, object], field: str) -> int:
    """Read one region field as a plain integer, rejecting bools and others."""

    value = values.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("region bounds must be integer left, top, width, and height values")
    return value


def _screen_rect(values: Mapping[str, object]) -> ScreenRect:
    return ScreenRect(
        left=_region_bound(values, "left"),
        top=_region_bound(values, "top"),
        width=_region_bound(values, "width"),
        height=_region_bound(values, "height"),
    )


class ControlCenterHost:
    """Open the Control Center through pywebview's shared Qt event loop.

    pywebview requires ``start`` on the process main thread. Process startup
    must call :func:`prepare_control_center_qt` before constructing the shared
    ``QApplication``. The Qt backend then reuses that application, so this host
    must be opened by the Qt UI dispatcher and must not spawn a second Python
    thread or a second GUI loop.
    """

    def __init__(
        self,
        bridge: ControlCenterBridge | object,
        *,
        title: str = "Hanly · Control Center",
        width: int = 1080,
        height: int = 760,
        debug: bool = False,
        webview_module: object | None = None,
    ) -> None:
        if width <= 0 or height <= 0:
            raise ValueError("Control Center dimensions must be positive")
        self._bridge = bridge
        self._title = title
        self._width = width
        self._height = height
        self._debug = debug
        self._webview = webview_module
        self._window: object | None = None
        self._opened = False

    @property
    def opened(self) -> bool:
        """Whether this host currently owns an open pywebview window."""

        return self._opened

    def open(self) -> None:
        """Create and run the Qt-backed window on the process main thread."""

        if threading.current_thread() is not threading.main_thread():
            raise ControlCenterUnavailable(
                "Control Center must be opened from the Qt/main thread"
            )
        if self._opened:
            return
        webview = self._load_webview()
        assets = load_control_center_assets()
        create_window = getattr(webview, "create_window", None)
        start = getattr(webview, "start", None)
        if not callable(create_window) or not callable(start):
            raise ControlCenterUnavailable("pywebview does not expose create_window/start")

        self._window = create_window(
            title=self._title,
            html=_inline_assets(assets),
            js_api=self._bridge,
            width=self._width,
            height=self._height,
            min_size=(760, 560),
            background_color="#F7F8FC",
        )
        self._opened = True
        try:
            start(gui="qt", debug=self._debug)
        except ImportError as error:
            raise ControlCenterUnavailable(
                "pywebview Qt support requires the qt6 optional extra"
            ) from error
        finally:
            self._opened = False
            self._window = None

    def close(self) -> None:
        """Close the window if pywebview has created one."""

        window = self._window
        destroy = getattr(window, "destroy", None)
        if callable(destroy):
            destroy()
        self._opened = False

    def _load_webview(self) -> object:
        if self._webview is not None:
            return self._webview
        prepare_control_center_qt()
        try:
            import webview
        except ImportError as error:
            raise ControlCenterUnavailable(
                "pywebview is required for the Control Center"
            ) from error
        self._webview = webview
        return webview


__all__ = [
    "ControlCenterAssets",
    "ControlCenterBridge",
    "ControlCenterHost",
    "ControlCenterUnavailable",
    "load_control_center_assets",
    "prepare_control_center_qt",
]
