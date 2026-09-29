"""Hanly desktop application package.

Every name below is loaded on first use. Importing a submodule -- which is
what the frozen runtime hook and the spawned lookup child do -- would
otherwise execute the whole desktop, Control Center and updater included.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hanly_app.acquisition.capture import (
        CaptureBackend,
        CaptureBackendError,
        CaptureError,
        CapturePlan,
        CaptureResult,
        CaptureService,
        ConfiguredCaptureService,
        MonitorInfo,
        MSSBackend,
        ScreenRect,
    )
    from hanly_app.control_center.bridge import (
        ControlCenterAssets,
        ControlCenterBridge,
        ControlCenterUnavailable,
        control_center_document,
        load_control_center_assets,
        prepare_control_center_qt,
    )
    from hanly_app.control_center.host import ControlCenterHost
    from hanly_app.control_center.process import ControlCenterOptions, ControlCenterProcess
    from hanly_app.hover.controller import HoverController, HoverRequest
    from hanly_app.hover.lookup import HoverLookupRuntime
    from hanly_app.hover.mouse_observer import MouseObserver
    from hanly_app.hover.target import CaptureOrigins, RetainedTarget
    from hanly_app.lookup.controller import (
        LookupController,
        LookupRequest,
        ResultDispatcher,
        ResultHandler,
    )
    from hanly_app.lookup.executor import JobExecutor, Worker
    from hanly_app.lookup.preload import preload_ocr_runtime
    from hanly_app.lookup.process import LookupEngine, LookupProcessError, LookupSettings
    from hanly_app.lookup.transport import Transport, TransportClosed
    from hanly_app.popup.presentation import (
        PopupContent,
        PopupController,
        PopupPosition,
        PopupRuntime,
        PopupSize,
        ScreenGeometry,
        format_lookup_result,
    )
    from hanly_app.updates.cleanup import CleanupReport, OwnedWorkspace
    from hanly_app.updates.coordinator import UpdateCoordinator
    from hanly_app.updates.resource_service import (
        DownloadProgress,
        GitHubReleaseFetcher,
        RemoteManifest,
        RemoteResource,
        ResourceFetcher,
        ResourceUpdateError,
        UpdateAvailability,
        UpdateResult,
        UpdateService,
    )

    from .application import (
        DesktopApplication,
        DesktopApplicationError,
        DiagnosticLog,
        default_app_config_path,
        load_update_service,
        run_desktop,
    )
    from .composition import (
        LookupWorker,
        build_lookup_controller,
        build_lookup_worker_factory,
        create_lookup_controller,
        create_lookup_worker_factory,
    )
    from .config import (
        AppConfig,
        CaptureMode,
        ConfigError,
        ConfigManager,
        HoverActivation,
        LookupPreload,
        PopupDefaultSize,
        TechnicalDetailLevel,
        Theme,
    )
    from .desktop_controller import DesktopController, DesktopState, LookupRuntime
    from .diagnostics import RotatingLogFile, open_diagnostics
    from .hotkeys import (
        DEFAULT_HOTKEYS,
        DuplicateHotkeyError,
        HotkeyAction,
        HotkeyError,
        HotkeyService,
    )
    from .manual_lookup import (
        ManualLookupRuntime,
        ManualLookupStartupError,
        create_manual_lookup,
        create_qt_manual_lookup,
    )
    from .paths import (
        default_log_directory,
        default_runtime_config_path,
        discover_runtime_config,
    )
    from .qt_bootstrap import ensure_qt_application
    from .runtime import (
        HanlyRuntime,
        RuntimeConfigError,
        create_lookup_controller_from_config,
        create_worker_factory_from_config,
        load_runtime,
    )
    from .runtime_status import (
        RuntimePhase,
        RuntimeStatus,
        RuntimeStatusPublisher,
        watch_worker_readiness,
    )
    from .runtime_trace import RuntimeTraceSink, emit_trace
    from .signal_bridge import QtSignalBridge
    from .tray import TrayService, TrayState, TrayStatus

#: Exported name -> the submodule that defines it.
_EXPORTS: dict[str, str] = {
    "AppConfig": "config",
    "CaptureBackend": "acquisition.capture",
    "CaptureBackendError": "acquisition.capture",
    "CaptureError": "acquisition.capture",
    "CaptureMode": "config",
    "CaptureOrigins": "hover.target",
    "CapturePlan": "acquisition.capture",
    "CaptureResult": "acquisition.capture",
    "CaptureService": "acquisition.capture",
    "CleanupReport": "updates.cleanup",
    "ConfigError": "config",
    "ConfigManager": "config",
    "ConfiguredCaptureService": "acquisition.capture",
    "ControlCenterAssets": "control_center.bridge",
    "ControlCenterBridge": "control_center.bridge",
    "ControlCenterHost": "control_center.host",
    "ControlCenterOptions": "control_center.process",
    "ControlCenterProcess": "control_center.process",
    "ControlCenterUnavailable": "control_center.bridge",
    "DEFAULT_HOTKEYS": "hotkeys",
    "DesktopApplication": "application",
    "DesktopApplicationError": "application",
    "DesktopController": "desktop_controller",
    "DesktopState": "desktop_controller",
    "DiagnosticLog": "application",
    "DownloadProgress": "updates.resource_service",
    "DuplicateHotkeyError": "hotkeys",
    "GitHubReleaseFetcher": "updates.resource_service",
    "HanlyRuntime": "runtime",
    "HotkeyAction": "hotkeys",
    "HotkeyError": "hotkeys",
    "HotkeyService": "hotkeys",
    "HoverActivation": "config",
    "HoverController": "hover.controller",
    "HoverLookupRuntime": "hover.lookup",
    "HoverRequest": "hover.controller",
    "JobExecutor": "lookup.executor",
    "LookupController": "lookup.controller",
    "LookupEngine": "lookup.process",
    "LookupPreload": "config",
    "LookupProcessError": "lookup.process",
    "LookupRequest": "lookup.controller",
    "LookupRuntime": "desktop_controller",
    "LookupSettings": "lookup.process",
    "LookupWorker": "composition",
    "MSSBackend": "acquisition.capture",
    "ManualLookupRuntime": "manual_lookup",
    "ManualLookupStartupError": "manual_lookup",
    "MonitorInfo": "acquisition.capture",
    "MouseObserver": "hover.mouse_observer",
    "OwnedWorkspace": "updates.cleanup",
    "PopupContent": "popup.presentation",
    "PopupController": "popup.presentation",
    "PopupDefaultSize": "config",
    "PopupPosition": "popup.presentation",
    "PopupRuntime": "popup.presentation",
    "PopupSize": "popup.presentation",
    "QtSignalBridge": "signal_bridge",
    "RemoteManifest": "updates.resource_service",
    "RemoteResource": "updates.resource_service",
    "ResourceFetcher": "updates.resource_service",
    "ResourceUpdateError": "updates.resource_service",
    "ResultDispatcher": "lookup.controller",
    "ResultHandler": "lookup.controller",
    "RetainedTarget": "hover.target",
    "RotatingLogFile": "diagnostics",
    "RuntimeConfigError": "runtime",
    "RuntimePhase": "runtime_status",
    "RuntimeStatus": "runtime_status",
    "RuntimeStatusPublisher": "runtime_status",
    "RuntimeTraceSink": "runtime_trace",
    "ScreenGeometry": "popup.presentation",
    "ScreenRect": "acquisition.capture",
    "TechnicalDetailLevel": "config",
    "Theme": "config",
    "Transport": "lookup.transport",
    "TransportClosed": "lookup.transport",
    "TrayService": "tray",
    "TrayState": "tray",
    "TrayStatus": "tray",
    "UpdateAvailability": "updates.resource_service",
    "UpdateCoordinator": "updates.coordinator",
    "UpdateResult": "updates.resource_service",
    "UpdateService": "updates.resource_service",
    "Worker": "lookup.executor",
    "build_lookup_controller": "composition",
    "build_lookup_worker_factory": "composition",
    "control_center_document": "control_center.bridge",
    "create_lookup_controller": "composition",
    "create_lookup_controller_from_config": "runtime",
    "create_lookup_worker_factory": "composition",
    "create_manual_lookup": "manual_lookup",
    "create_qt_manual_lookup": "manual_lookup",
    "create_worker_factory_from_config": "runtime",
    "default_app_config_path": "application",
    "default_log_directory": "paths",
    "default_runtime_config_path": "paths",
    "discover_runtime_config": "paths",
    "emit_trace": "runtime_trace",
    "ensure_qt_application": "qt_bootstrap",
    "format_lookup_result": "popup.presentation",
    "load_control_center_assets": "control_center.bridge",
    "load_runtime": "runtime",
    "load_update_service": "application",
    "open_diagnostics": "diagnostics",
    "preload_ocr_runtime": "lookup.preload",
    "prepare_control_center_qt": "control_center.bridge",
    "run_desktop": "application",
    "watch_worker_readiness": "runtime_status",
}


def __getattr__(name: str) -> Any:
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f".{module}", __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *_EXPORTS})


__all__ = [
    "AppConfig",
    "CaptureBackend",
    "CaptureBackendError",
    "CaptureError",
    "CaptureMode",
    "CapturePlan",
    "CaptureResult",
    "CaptureService",
    "ConfiguredCaptureService",
    "ConfigError",
    "ConfigManager",
    "ControlCenterAssets",
    "ControlCenterBridge",
    "ControlCenterHost",
    "ControlCenterOptions",
    "ControlCenterProcess",
    "ControlCenterUnavailable",
    "DEFAULT_HOTKEYS",
    "DesktopApplication",
    "DesktopApplicationError",
    "DesktopController",
    "DesktopState",
    "DiagnosticLog",
    "DownloadProgress",
    "DuplicateHotkeyError",
    "HanlyRuntime",
    "GitHubReleaseFetcher",
    "HotkeyAction",
    "HotkeyError",
    "HotkeyService",
    "HoverController",
    "HoverLookupRuntime",
    "HoverRequest",
    "JobExecutor",
    "LookupController",
    "LookupRequest",
    "LookupRuntime",
    "LookupWorker",
    "MSSBackend",
    "ManualLookupRuntime",
    "ManualLookupStartupError",
    "MonitorInfo",
    "MouseObserver",
    "PopupContent",
    "PopupController",
    "PopupDefaultSize",
    "PopupPosition",
    "PopupRuntime",
    "PopupSize",
    "ResultDispatcher",
    "ResultHandler",
    "RotatingLogFile",
    "RuntimeConfigError",
    "RuntimePhase",
    "RuntimeStatus",
    "RuntimeStatusPublisher",
    "RuntimeTraceSink",
    "QtSignalBridge",
    "RemoteManifest",
    "RemoteResource",
    "ResourceFetcher",
    "ResourceUpdateError",
    "ScreenGeometry",
    "ScreenRect",
    "Theme",
    "TechnicalDetailLevel",
    "TrayService",
    "TrayState",
    "TrayStatus",
    "UpdateAvailability",
    "UpdateCoordinator",
    "UpdateResult",
    "UpdateService",
    "CaptureOrigins",
    "CleanupReport",
    "HoverActivation",
    "LookupEngine",
    "LookupPreload",
    "LookupProcessError",
    "LookupSettings",
    "OwnedWorkspace",
    "RetainedTarget",
    "Transport",
    "TransportClosed",
    "Worker",
    "build_lookup_controller",
    "build_lookup_worker_factory",
    "create_lookup_controller",
    "create_lookup_controller_from_config",
    "create_lookup_worker_factory",
    "create_manual_lookup",
    "create_qt_manual_lookup",
    "control_center_document",
    "create_worker_factory_from_config",
    "default_app_config_path",
    "ensure_qt_application",
    "default_log_directory",
    "default_runtime_config_path",
    "discover_runtime_config",
    "format_lookup_result",
    "emit_trace",
    "load_runtime",
    "load_update_service",
    "load_control_center_assets",
    "open_diagnostics",
    "prepare_control_center_qt",
    "preload_ocr_runtime",
    "run_desktop",
    "watch_worker_readiness",
]
