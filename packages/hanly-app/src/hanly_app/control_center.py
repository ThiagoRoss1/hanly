"""The pywebview Control Center and its UI-independent application bridge.

The bridge exposes snapshots and small desktop actions as JSON-compatible
values. It does not construct providers, open databases, or perform language
processing. ``ControlCenterHost`` deliberately selects pywebview's Qt backend
so it can reuse the ``QApplication`` that already hosts the popup.
"""

from __future__ import annotations

import json
import sys
import urllib.parse
import webbrowser
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from importlib.resources import files
from pathlib import Path
from typing import Any, Protocol

from hanly.resource_manager import ResourceManager

from .capture import CaptureService, MonitorInfo, ScreenRect
from .capture_selector import CaptureSelection
from .config import (
    HOVER_DELAY_MAX_MS,
    HOVER_DELAY_MIN_MS,
    AppConfig,
    CaptureMode,
    CaptureRegion,
    ConfigManager,
    HoverActivation,
    LookupPreload,
)
from .desktop_controller import DesktopState
from .diagnostics import LEVELS, DiagnosticLog, diagnostics_bundle
from .hotkeys import HotkeyError, validate_binding
from .permissions import (
    START_CAPTURE_PERMISSIONS,
    PermissionService,
    missing_permission_refusal,
    permission_from_id,
)
from .runtime import HanlyRuntime
from .runtime_status import ApplicationSnapshot, RuntimeStatus
from .update_coordinator import UpdateCoordinator


class ControlCenterUnavailable(RuntimeError):
    """Raised when an intentionally deferred Control Center action is used."""


#: What a capture action is told when no prepared runtime exists yet. Starting
#: before preparation finishes is an ordinary rejection, not a lifecycle fault.
RUNTIME_NOT_READY = "Hanly is still preparing its lookup runtime."


#: Shows the selection overlay and returns the choice, or ``None`` if the user
#: cancelled. Supplied by composition so the bridge stays free of Qt. The
#: selector owns suspending and restoring observation for the choice: the
#: overlay covers the virtual desktop, and only composition knows the thread
#: that may touch capture.
CaptureAreaSelector = Callable[[], "CaptureSelection | None"]


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


def control_center_document(assets: ControlCenterAssets | None = None) -> str:
    """Return the window's HTML as one self-contained document.

    Inlining the stylesheet and script is what lets the packaged build and a
    zipped wheel serve the same page without a file server.
    """

    return _inline_assets(assets if assets is not None else load_control_center_assets())


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
        resource_manager: ResourceManager | None = None,
        update_coordinator: UpdateCoordinator | None = None,
        diagnostics: Callable[[], Sequence[str]] | None = None,
        on_lifecycle_changed: Callable[[], None] | None = None,
        runtime_status: Callable[[], RuntimeStatus] | None = None,
        capture_ready: Callable[[], bool] | None = None,
        on_select_capture_area: CaptureAreaSelector | None = None,
        on_quit: Callable[[], None] | None = None,
        log_path: Path | None = None,
        permission_service: PermissionService | None = None,
        ocr_provider: str = "EasyOCR",
        engine_status: Callable[[], Mapping[str, str]] | None = None,
        registered_hotkeys: Callable[[], Mapping[str, str]] | None = None,
        application_snapshot: Callable[[], ApplicationSnapshot] | None = None,
        diagnostic_log: DiagnosticLog | None = None,
    ) -> None:
        if config_manager is not None and not isinstance(config_manager, ConfigManager):
            raise TypeError("config_manager must be a ConfigManager")

        if not isinstance(ocr_provider, str) or not ocr_provider.strip():
            raise ValueError("ocr_provider must be a non-empty string")
        if diagnostics is not None and not callable(diagnostics):
            raise TypeError("diagnostics must be callable")
        if on_lifecycle_changed is not None and not callable(on_lifecycle_changed):
            raise TypeError("on_lifecycle_changed must be callable")
        if runtime_status is not None and not callable(runtime_status):
            raise TypeError("runtime_status must be callable")
        if capture_ready is not None and not callable(capture_ready):
            raise TypeError("capture_ready must be callable")
        if on_select_capture_area is not None and not callable(on_select_capture_area):
            raise TypeError("on_select_capture_area must be callable")
        if on_quit is not None and not callable(on_quit):
            raise TypeError("on_quit must be callable")
        if engine_status is not None and not callable(engine_status):
            raise TypeError("engine_status must be callable")
        if registered_hotkeys is not None and not callable(registered_hotkeys):
            raise TypeError("registered_hotkeys must be callable")
        if application_snapshot is not None and not callable(application_snapshot):
            raise TypeError("application_snapshot must be callable")
        if permission_service is not None and not isinstance(permission_service, PermissionService):
            raise TypeError("permission_service must be a PermissionService")

        self._config_manager = config_manager
        self._config = config_manager.config if config_manager is not None else AppConfig()
        self._desktop_controller = desktop_controller
        # Both arrive with the prepared runtime, through attach_runtime().
        self._capture_service: MonitorSource | CaptureService | None = None
        self._resource_manager = resource_manager
        self._ocr_provider = ocr_provider.strip()
        self._diagnostics = diagnostics
        self._runtime_status = runtime_status
        self._engine_status = engine_status
        self._registered_hotkeys = registered_hotkeys
        self._application_snapshot = application_snapshot
        self._diagnostic_log = diagnostic_log
        self._capture_ready = capture_ready
        # Bound by set_retry() once startup exists to retry.
        self._on_retry_runtime: Callable[[], None] | None = None
        self._select_capture_area = on_select_capture_area
        self._on_quit = on_quit
        self._log_path = log_path
        # An empty service is the honest answer off macOS, and it keeps every
        # caller below free of a platform test.
        self._permissions = permission_service or PermissionService()
        self._on_lifecycle_changed = on_lifecycle_changed
        self._update_coordinator = update_coordinator
        self._capture_running = False

    def get_state(self) -> dict[str, Any]:
        """Return the complete UI snapshot in JSON-compatible primitives."""

        config = self._current_config()
        state_name = self._desktop_state()
        activity = self._activity_snapshot()
        return {
            "app": {
                "state": state_name,
                "activity": activity["activity"],
                "detail": activity["detail"],
                "capture_running": self._is_capture_running(state_name),
                "capture_mode": config.capture_mode.value,
                "target": _target_name(config.capture_monitor),
                "region": (
                    None if config.capture_region is None else config.capture_region.to_dict()
                ),
                "targets": self._targets(),
            },
            "config": config.to_dict(),
            "runtime": {
                "ocr_provider": self._ocr_provider,
                "resources": self._resources(),
                "status": self._status_snapshot(),
                "engine": self._engine_snapshot(),
                "hotkeys": self._registered_bindings(),
                "log_path": None if self._log_path is None else str(self._log_path),
                "diagnostics": (
                    list(self._diagnostics()) if self._diagnostics is not None else []
                ),
            },
            "updates": (
                self._update_coordinator.snapshot()
                if self._update_coordinator is not None
                else dict(self._UPDATE_STATUS)
            ),
            "permissions": self._permissions_snapshot(),
        }

    def start_capture(self) -> dict[str, Any]:
        """Start capture through the existing desktop lifecycle controller.

        A build that reports readiness is asked before anything is touched, so
        an action arriving while resources are still being prepared is refused
        with a sentence instead of leaving the page showing a running capture.
        """

        if self._capture_ready is not None and not self._capture_ready():
            raise ControlCenterUnavailable(RUNTIME_NOT_READY)
        missing = self._permissions.missing(START_CAPTURE_PERMISSIONS)
        if missing:
            raise ControlCenterUnavailable(missing_permission_refusal(missing))

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
            monitor: int | None = None
        else:
            monitor = self._target_index(target)
            if not any(item["index"] == monitor for item in self._targets()):
                raise ValueError(f"unknown capture target: {target!r}")
        self._update_config(capture_monitor=monitor)
        return self.get_state()

    def set_region(self, region: Mapping[str, object] | None) -> dict[str, Any]:
        """Store a validated screen-space region for the next capture."""

        self._update_config(
            capture_region=None if region is None else _capture_region(region)
        )
        return self.get_state()

    def select_capture_area(self) -> dict[str, Any]:
        """Choose what Hanly watches, from settings rather than at launch.

        The selector suspends observation for the duration of the choice.
        Cancelling leaves every previous choice in place.
        """

        if self._select_capture_area is None:
            raise ControlCenterUnavailable(
                "capture selection is not available in this build"
            )

        selection = self._select_capture_area()
        if selection is not None:
            self._apply_selection(selection)
        return self.get_state()

    def _apply_selection(self, selection: CaptureSelection) -> None:
        """Persist one capture choice, keeping mode and region consistent."""

        if selection.capture_mode is CaptureMode.REGION and selection.region is not None:
            self._update_config(
                capture_mode=CaptureMode.REGION,
                capture_region=CaptureRegion(
                    selection.region.left,
                    selection.region.top,
                    selection.region.width,
                    selection.region.height,
                ),
            )
            return
        self._update_config(capture_mode=CaptureMode.FULL_MONITOR)

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
            "hover_hotkey",
            "hover_activation",
            "lookup_preload",
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
        for field in ("hotkey", "hover_hotkey"):
            if field in values:
                values[field] = _validated_hotkey(values[field])
        if "hover_activation" in values:
            values["hover_activation"] = _validated_choice(
                values["hover_activation"], HoverActivation, "hover activation"
            )
        if "lookup_preload" in values:
            values["lookup_preload"] = _validated_choice(
                values["lookup_preload"], LookupPreload, "lookup engine preload"
            )
        self._update_config(**values)
        return self.get_state()

    def grant_permission(self, permission: object) -> dict[str, Any]:
        """Run the operating system's own grant flow for one permission.

        Hanly never grants anything itself: this opens Apple's request or the
        exact System Settings pane and then reports what the system says.
        """

        self._permissions.request(permission_from_id(permission))
        return self.get_state()

    def refresh_permissions(self) -> dict[str, Any]:
        """Re-read privacy status now, after the user changed it elsewhere."""

        self._permissions.invalidate()
        return self.get_state()

    def retry_runtime(self) -> dict[str, Any]:
        """Re-attempt resource preparation and provider construction."""

        if self._on_retry_runtime is None:
            raise ControlCenterUnavailable(
                "this Hanly build cannot retry runtime preparation"
            )
        self._on_retry_runtime()
        return self.get_state()

    def quit(self) -> dict[str, Any]:
        """End the session from the main window.

        The tray is not a guaranteed route on every desktop, so the window
        that is always reachable carries the action that always works.
        """

        if self._on_quit is None:
            raise ControlCenterUnavailable("this Hanly build cannot quit from the window")
        self._on_quit()
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

    def install_application_update(self) -> dict[str, object]:
        """Download, verify, and stage the newer application build inside Hanly.

        This is the primary update action. The browser is never part of it.
        """

        if self._update_coordinator is None:
            raise ControlCenterUnavailable(self._UPDATE_STATUS["message"])
        self._update_coordinator.install_application_update()
        return self.get_state()

    def open_release_notes(self) -> dict[str, object]:
        """Open the release notes for the build the last check reported.
                            
        Reading the notes is the one thing Hanly cannot show in-app. The URL
        is the one the release channel returned, re-checked against the host
        and path a release page actually has, so neither the UI nor a hostile
        release payload can turn this into an arbitrary browser launch.
        """

        if self._update_coordinator is None:
            raise ControlCenterUnavailable(self._UPDATE_STATUS["message"])
        application = self._update_coordinator.snapshot().get("application")
        url = application.get("release_url") if isinstance(application, Mapping) else None
        if not isinstance(url, str) or not _is_release_page(url):
            raise ControlCenterUnavailable("no application release page is available")
        webbrowser.open(url)
        return self.get_state()

    def get_logs(self) -> dict[str, object]:
        """Return the recent records, with what a filter needs to narrow them."""

        log = self._diagnostic_log
        records = [] if log is None else [record.to_dict() for record in log.records()]
        return {
            "records": records,
            "levels": list(LEVELS),
            "subsystems": sorted({str(record["subsystem"]) for record in records}),
            "log_path": None if self._log_path is None else str(self._log_path),
        }

    def clear_logs(self) -> dict[str, object]:
        """Forget the displayed records and empty the file they were written to.

        Both, because a Clear that left the file behind would be a promise the
        next diagnostics export immediately broke. A file that cannot be
        emptied is reported rather than quietly skipped.
        """

        log = self._diagnostic_log
        if log is None:
            raise ControlCenterUnavailable("this Hanly build keeps no diagnostics log")
        log.clear()
        failure = _empty_log_file(log)
        state = self.get_logs()
        if failure is not None:
            raise ControlCenterUnavailable(
                f"The displayed records were cleared, but the log file was not: {failure}"
            )
        return state

    def export_diagnostics(self) -> dict[str, object]:
        """Write a shareable report beside the log and say where it went.

        Explicit, and to a place the user can find: this is the file somebody
        attaches to a message about a problem, so it carries versions,
        platform, preferences, and recent records, and never a path from this
        machine or anything that was on the screen.
        """

        log = self._diagnostic_log
        if log is None or self._log_path is None:
            raise ControlCenterUnavailable("this Hanly build keeps no diagnostics log")

        records = log.records()
        bundle = diagnostics_bundle(records, state=self._export_state())
        destination = self._log_path.with_name(
            f"hanly-diagnostics-{_export_stamp()}.json"
        )
        try:
            destination.write_text(
                json.dumps(bundle, indent=2, sort_keys=True, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as error:
            raise ControlCenterUnavailable(
                f"the diagnostics report could not be written: {error}"
            ) from error
        return {"path": str(destination), "records": len(records)}

    def _export_state(self) -> dict[str, object]:
        """What makes a failure reproducible, and nothing about the screen."""

        config = self._current_config()
        return {
            "preferences": config.to_dict(),
            "capture": {
                "mode": config.capture_mode.value,
                "has_region": config.capture_region is not None,
            },
            "desktop_state": self._desktop_state(),
            "runtime_status": self._status_snapshot(),
            "engine": self._engine_snapshot(),
            "hotkeys": self._registered_bindings(),
            "resources": self._resources(),
            "permissions": self._permissions_snapshot(),
            "ocr_provider": self._ocr_provider,
        }

    def set_retry(self, on_retry_runtime: Callable[[], None]) -> None:
        """Bind the retry action once startup preparation exists to retry."""

        if not callable(on_retry_runtime):
            raise TypeError("on_retry_runtime must be callable")
        self._on_retry_runtime = on_retry_runtime

    def attach_runtime(
        self,
        runtime: HanlyRuntime,
        capture_service: MonitorSource | CaptureService,
        update_coordinator: UpdateCoordinator | None = None,
    ) -> None:
        """Bind the services that exist only once the runtime is prepared.

        The window opens before any of this exists, so the bridge starts with
        no resources, no monitors, and no update channel and gains them here.
        """

        self._resource_manager = runtime.resource_manager
        self._capture_service = capture_service
        if update_coordinator is not None:
            self._update_coordinator = update_coordinator
        self._apply_live_config()

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
        """Change one or more preferences as a single transaction.

        A shortcut has to be registered with the operating system before it is
        stored, or a refused registration leaves the saved settings describing
        keys the user's keyboard does not have. So: validate, register, persist,
        and only then publish. A save that fails after a successful
        registration puts the previous shortcuts back.
        """

        previous = self._current_config()
        candidate = self._candidate(changes)
        if not _rebinds(previous, candidate):
            self._persist(candidate)
            self._apply_live_config()
            return

        self._apply(candidate)
        try:
            self._persist(candidate)
        except Exception:
            self._restore(previous)
            raise
        self._apply_live_config()

    def _candidate(self, changes: Mapping[str, object]) -> AppConfig:
        """Validate the change without storing or applying any part of it."""

        if self._config_manager is not None:
            return self._config_manager.candidate(**changes)
        values: dict[str, Any] = self._config.to_dict()
        values.update(changes)
        return AppConfig.from_dict(values)

    def _persist(self, config: AppConfig) -> None:
        if self._config_manager is not None:
            self._config_manager.save(config)
        else:
            self._config = config

    def _restore(self, previous: AppConfig) -> None:
        """Put the previous shortcuts back, and never call a loss a success."""

        try:
            self._apply(previous)
        except Exception as error:
            raise ControlCenterUnavailable(
                "Hanly could not save that change, and could not put your previous "
                f"shortcuts back either: {error}. Check the Shortcuts section for "
                "what is registered now."
            ) from error

    def _apply(self, config: AppConfig) -> None:
        """Apply one configuration to the running services, persisted or not."""

        if self._desktop_controller is None:
            return
        self._desktop_controller.apply_config(config)
        self._apply_capture_preferences(config)

    def _apply_live_config(self) -> None:
        """Forward persisted settings to a desktop controller when present."""

        self._apply(self._current_config())

    def _apply_capture_preferences(self, config: AppConfig) -> None:
        """Forward the persisted target and region through the app-owned seam."""

        if self._desktop_controller is None:
            return
        region = config.capture_region
        self._desktop_controller.set_capture_preferences(
            capture_mode=config.capture_mode,
            monitor=config.capture_monitor,
            region=(
                None
                if region is None
                else ScreenRect(region.left, region.top, region.width, region.height)
            ),
        )

    def _permissions_snapshot(self) -> dict[str, Any]:
        """Report privacy status, and whether this platform gates anything.

        ``supported`` is how the page knows to render nothing at all rather
        than an empty and slightly ominous "Permissions" heading.
        """

        return {
            "supported": self._permissions.supported,
            "items": [status.to_dict() for status in self._permissions.statuses()],
        }

    def _status_snapshot(self) -> dict[str, str]:
        """Report runtime readiness, which is not the capture lifecycle.

        A desktop that is ``RUNNING`` may still be preparing providers, so the
        two are reported separately rather than collapsed into one word.
        """

        if self._runtime_status is None:
            return RuntimeStatus("idle").to_dict()
        return self._runtime_status().to_dict()

    def _engine_snapshot(self) -> dict[str, str]:
        """Report where the lookup engine is, which is not shell readiness.

        Hanly can be ready to look a word up while the providers are asleep:
        the engine loads on demand. Collapsing the two would make the interface
        say a lookup is impossible when it merely has to wait a moment.
        """

        if self._engine_status is None:
            return {"state": "unknown", "message": ""}
        return {str(key): str(value) for key, value in self._engine_status().items()}

    def _activity_snapshot(self) -> dict[str, str]:
        """The one derived label, or the honest unknown before one exists."""

        if self._application_snapshot is None:
            return {"activity": "preparing", "detail": ""}
        snapshot = self._application_snapshot()
        return {"activity": snapshot.activity, "detail": snapshot.detail}

    def _registered_bindings(self) -> dict[str, str]:
        """Report the shortcuts actually registered, not the stored intent.

        After a rebind that the operating system refused, these are what the
        user's keyboard will really do, and the page shows those rather than a
        preference that never took effect.
        """

        if self._registered_hotkeys is None:
            return {}
        return {str(key): str(value) for key, value in self._registered_hotkeys().items()}

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


#: The only host a release page may live on, and the path segment that says
#: the URL is one. Anything else is not opened, whoever supplied it.
_RELEASE_HOST = "github.com"
_RELEASE_PATH = "/releases/"


def _is_release_page(url: str) -> bool:
    parts = urllib.parse.urlsplit(url)
    return (
        parts.scheme == "https"
        and parts.netloc == _RELEASE_HOST
        and _RELEASE_PATH in parts.path
    )


def _empty_log_file(log: DiagnosticLog) -> str | None:
    """Truncate the rotating log and its backups, saying what stopped it."""

    file = log.file
    if file is None:
        return None
    paths = [file.path] + [
        file.path.with_name(f"{file.path.name}.{index}") for index in range(1, 10)
    ]
    for path in paths:
        try:
            if path.is_file():
                path.unlink()
        except OSError as error:
            return str(error)
    return None


def _export_stamp() -> str:
    """A file name that sorts, and that a second export cannot collide with."""

    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _rebinds(previous: AppConfig, candidate: AppConfig) -> bool:
    """Whether this change asks the operating system for different shortcuts."""

    return (
        previous.hotkey != candidate.hotkey
        or previous.hover_hotkey != candidate.hover_hotkey
    )


def _validated_choice(value: object, choices: type[Enum], label: str) -> str:
    """Reject a choice the page invented, naming what was actually offered."""

    if isinstance(value, choices):
        return str(value.value)
    try:
        return str(choices(value).value)
    except ValueError as error:
        offered = ", ".join(str(item.value) for item in choices)
        raise ValueError(f"{label} must be one of: {offered}") from error


def _validated_hotkey(hotkey: object) -> str:
    """Reject a combination this machine's own backend could not register.

    Checking the spelling alone would let a user save something that silently
    does nothing, because the running platform has no key at that position.
    """

    if not isinstance(hotkey, str):
        raise ValueError("hotkey must be a string")
    try:
        validate_binding(hotkey)
    except (HotkeyError, RuntimeError) as error:
        raise ValueError(f"unsupported hotkey: {error}") from error
    return hotkey


def _region_bound(values: Mapping[str, object], field: str) -> int:
    """Read one region field as a plain integer, rejecting bools and others."""

    value = values.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("region bounds must be integer left, top, width, and height values")
    return value


def _capture_region(values: Mapping[str, object]) -> CaptureRegion:
    return CaptureRegion(
        left=_region_bound(values, "left"),
        top=_region_bound(values, "top"),
        width=_region_bound(values, "width"),
        height=_region_bound(values, "height"),
    )


def _target_name(monitor: int | None) -> str:
    return "cursor" if monitor is None else f"monitor:{monitor}"


__all__ = [
    "CaptureAreaSelector",
    "ControlCenterAssets",
    "ControlCenterBridge",
    "ControlCenterUnavailable",
    "RUNTIME_NOT_READY",
    "control_center_document",
    "load_control_center_assets",
    "prepare_control_center_qt",
]
