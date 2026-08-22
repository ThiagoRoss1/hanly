"""Hanly desktop application package."""

from .capture import (
    CaptureBackend,
    CaptureBackendError,
    CaptureError,
    CaptureResult,
    CaptureService,
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
from .config import AppConfig, CaptureMode, ConfigError, ConfigManager, Theme
from .desktop_controller import DesktopController, DesktopState, LookupRuntime
from .hotkeys import (
    DEFAULT_HOTKEYS,
    DuplicateHotkeyError,
    HotkeyAction,
    HotkeyError,
    HotkeyService,
)
from .job_executor import JobExecutor, Worker
from .lookup_controller import LookupController, LookupRequest, ResultDispatcher, ResultHandler
from .manual_lookup import (
    ManualLookupRuntime,
    ManualLookupStartupError,
    create_manual_lookup,
    create_qt_manual_lookup,
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
from .runtime import (
    HanlyRuntime,
    RuntimeConfigError,
    create_lookup_controller_from_config,
    create_worker_factory_from_config,
    load_runtime,
)

__all__ = [
    "AppConfig",
    "CaptureBackend",
    "CaptureBackendError",
    "CaptureError",
    "CaptureMode",
    "CaptureResult",
    "CaptureService",
    "ConfigError",
    "ConfigManager",
    "DEFAULT_HOTKEYS",
    "DesktopController",
    "DesktopState",
    "DuplicateHotkeyError",
    "HanlyRuntime",
    "HotkeyAction",
    "HotkeyError",
    "HotkeyService",
    "JobExecutor",
    "LookupController",
    "LookupRequest",
    "LookupRuntime",
    "LookupWorker",
    "MSSBackend",
    "ManualLookupRuntime",
    "ManualLookupStartupError",
    "MonitorInfo",
    "PopupContent",
    "PopupController",
    "PopupPosition",
    "PopupRuntime",
    "PopupSize",
    "ResultDispatcher",
    "ResultHandler",
    "RuntimeConfigError",
    "ScreenGeometry",
    "ScreenRect",
    "Theme",
    "Worker",
    "build_lookup_controller",
    "build_lookup_worker_factory",
    "create_lookup_controller",
    "create_lookup_controller_from_config",
    "create_lookup_worker_factory",
    "create_manual_lookup",
    "create_qt_manual_lookup",
    "create_worker_factory_from_config",
    "format_lookup_result",
    "load_runtime",
]
