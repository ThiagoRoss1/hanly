"""Hanly desktop application package.

Every name below is loaded on first use. Importing a submodule -- which is
what the frozen runtime hook and the spawned lookup child do -- would
otherwise execute the whole desktop, Control Center and updater included.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .application import (
        DesktopApplication,
        DesktopApplicationError,
        DiagnosticLog,
        default_app_config_path,
        load_update_service,
        run_desktop,
    )
    from .capture import (
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
    from .control_center import (
        ControlCenterAssets,
        ControlCenterBridge,
        ControlCenterUnavailable,
        control_center_document,
        load_control_center_assets,
        prepare_control_center_qt,
    )
    from .control_center_host import ControlCenterHost
    from .control_center_process import ControlCenterOptions, ControlCenterProcess
    from .desktop_controller import DesktopController, DesktopState, LookupRuntime
    from .diagnostics import RotatingLogFile, open_diagnostics
    from .hotkeys import (
        DEFAULT_HOTKEYS,
        DuplicateHotkeyError,
        HotkeyAction,
        HotkeyError,
        HotkeyService,
    )
    from .hover_controller import HoverController, HoverRequest
    from .hover_lookup import HoverLookupRuntime
    from .hover_target import CaptureOrigins, RetainedTarget
    from .job_executor import JobExecutor, Worker
    from .lookup_controller import LookupController, LookupRequest, ResultDispatcher, ResultHandler
    from .lookup_process import LookupEngine, LookupProcessError, LookupSettings
    from .manual_lookup import (
        ManualLookupRuntime,
        ManualLookupStartupError,
        create_manual_lookup,
        create_qt_manual_lookup,
    )
    from .mouse_observer import MouseObserver
    from .ocr_preload import preload_ocr_runtime
    from .owned_cleanup import CleanupReport, OwnedWorkspace
    from .paths import (
        default_log_directory,
        default_runtime_config_path,
        discover_runtime_config,
    )
    from .popup import (
        PopupContent,
        PopupController,
        PopupPosition,
        PopupRuntime,
        PopupSize,
        ScreenGeometry,
        format_lookup_result,
    )
    from .process_transport import Transport, TransportClosed
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
    from .update_coordinator import UpdateCoordinator
    from .update_service import (
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

#: Exported name -> the submodule that defines it.
_EXPORTS: dict[str, str] = {
    "AppConfig": "config",
    "CaptureBackend": "capture",
    "CaptureBackendError": "capture",
    "CaptureError": "capture",
    "CaptureMode": "config",
    "CaptureOrigins": "hover_target",
    "CapturePlan": "capture",
    "CaptureResult": "capture",
    "CaptureService": "capture",
    "CleanupReport": "owned_cleanup",
    "ConfigError": "config",
    "ConfigManager": "config",
    "ConfiguredCaptureService": "capture",
    "ControlCenterAssets": "control_center",
    "ControlCenterBridge": "control_center",
    "ControlCenterHost": "control_center_host",
    "ControlCenterOptions": "control_center_process",
    "ControlCenterProcess": "control_center_process",
    "ControlCenterUnavailable": "control_center",
    "DEFAULT_HOTKEYS": "hotkeys",
    "DesktopApplication": "application",
    "DesktopApplicationError": "application",
    "DesktopController": "desktop_controller",
    "DesktopState": "desktop_controller",
    "DiagnosticLog": "application",
    "DownloadProgress": "update_service",
    "DuplicateHotkeyError": "hotkeys",
    "GitHubReleaseFetcher": "update_service",
    "HanlyRuntime": "runtime",
    "HotkeyAction": "hotkeys",
    "HotkeyError": "hotkeys",
    "HotkeyService": "hotkeys",
    "HoverActivation": "config",
    "HoverController": "hover_controller",
    "HoverLookupRuntime": "hover_lookup",
    "HoverRequest": "hover_controller",
    "JobExecutor": "job_executor",
    "LookupController": "lookup_controller",
    "LookupEngine": "lookup_process",
    "LookupPreload": "config",
    "LookupProcessError": "lookup_process",
    "LookupRequest": "lookup_controller",
    "LookupRuntime": "desktop_controller",
    "LookupSettings": "lookup_process",
    "LookupWorker": "composition",
    "MSSBackend": "capture",
    "ManualLookupRuntime": "manual_lookup",
    "ManualLookupStartupError": "manual_lookup",
    "MonitorInfo": "capture",
    "MouseObserver": "mouse_observer",
    "OwnedWorkspace": "owned_cleanup",
    "PopupContent": "popup",
    "PopupController": "popup",
    "PopupDefaultSize": "config",
    "PopupPosition": "popup",
    "PopupRuntime": "popup",
    "PopupSize": "popup",
    "QtSignalBridge": "signal_bridge",
    "RemoteManifest": "update_service",
    "RemoteResource": "update_service",
    "ResourceFetcher": "update_service",
    "ResourceUpdateError": "update_service",
    "ResultDispatcher": "lookup_controller",
    "ResultHandler": "lookup_controller",
    "RetainedTarget": "hover_target",
    "RotatingLogFile": "diagnostics",
    "RuntimeConfigError": "runtime",
    "RuntimePhase": "runtime_status",
    "RuntimeStatus": "runtime_status",
    "RuntimeStatusPublisher": "runtime_status",
    "RuntimeTraceSink": "runtime_trace",
    "ScreenGeometry": "popup",
    "ScreenRect": "capture",
    "TechnicalDetailLevel": "config",
    "Theme": "config",
    "Transport": "process_transport",
    "TransportClosed": "process_transport",
    "TrayService": "tray",
    "TrayState": "tray",
    "TrayStatus": "tray",
    "UpdateAvailability": "update_service",
    "UpdateCoordinator": "update_coordinator",
    "UpdateResult": "update_service",
    "UpdateService": "update_service",
    "Worker": "job_executor",
    "build_lookup_controller": "composition",
    "build_lookup_worker_factory": "composition",
    "control_center_document": "control_center",
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
    "format_lookup_result": "popup",
    "load_control_center_assets": "control_center",
    "load_runtime": "runtime",
    "load_update_service": "application",
    "open_diagnostics": "diagnostics",
    "preload_ocr_runtime": "ocr_preload",
    "prepare_control_center_qt": "control_center",
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
