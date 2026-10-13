"""Qt-free service operations available during desktop migration."""

from __future__ import annotations

import sys
from importlib import metadata
from pathlib import Path
from typing import Any

from hanly_app.config import (
    HOVER_DELAY_MAX_MS,
    HOVER_DELAY_MIN_MS,
    ConfigError,
    ConfigManager,
)
from hanly_app.diagnostics import DiagnosticLog
from hanly_app.paths import default_app_config_path

from .protocol import (
    MAX_FRAME_BYTES,
    MAX_PENDING_REQUESTS,
    PROTOCOL_VERSION,
    Request,
    allowed_windows,
    known_method,
)

IMPLEMENTED_METHODS = frozenset(
    {
        "service.hello",
        "service.shutdown",
        "get_state",
        "update_settings",
        "get_logs",
    }
)


class ServiceError(RuntimeError):
    """A correlated application error suitable for a protocol reply."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class DesktopService:
    """Own settings and diagnostics without importing a desktop UI runtime."""

    def __init__(self, config_path: str | Path | None = None) -> None:
        self.config = ConfigManager(config_path or default_app_config_path())
        self.config.load()
        self.log = DiagnosticLog()
        self.log.record("Service", "Qt-free desktop service protocol started.")
        self.shutdown_requested = False

    def dispatch(self, request: Request) -> dict[str, Any]:
        """Run one authorized method or return an explicit unavailable error."""

        if not known_method(request.method):
            raise ServiceError("unknown_method", "Request method is not supported.")
        if request.window not in allowed_windows(request.method):
            raise ServiceError("unauthorized", "Request window is not authorized.")
        if request.method not in IMPLEMENTED_METHODS:
            raise ServiceError(
                "unavailable",
                "This desktop operation is not connected in the migration foundation.",
            )

        if request.method == "service.hello":
            return self._hello()
        if request.method == "service.shutdown":
            self.shutdown_requested = True
            return {"accepted": True}
        if request.method == "get_state":
            return self._state()
        if request.method == "update_settings":
            return self._update_settings(request.params["changes"])
        if request.method == "get_logs":
            return self._logs()
        raise AssertionError("implemented service method has no handler")

    def _hello(self) -> dict[str, Any]:
        return {
            "service": "hanly-desktop",
            "protocol_version": PROTOCOL_VERSION,
            "service_status": "running",
            "runtime_ready": False,
            "providers_loaded": False,
            "limits": {
                "max_frame_bytes": MAX_FRAME_BYTES,
                "max_pending": MAX_PENDING_REQUESTS,
            },
            "implemented_methods": sorted(IMPLEMENTED_METHODS),
        }

    def _state(self) -> dict[str, Any]:
        config = self.config.config.to_dict()
        state_message = "Desktop runtime is not initialized by the migration foundation."
        return {
            "app": {
                "state": "stopped",
                "activity": "stopped",
                "detail": state_message,
                "capture_running": False,
                "capture_mode": config["capture_mode"],
                "target": _target_name(config["capture_monitor"]),
                "region": config["capture_region"],
                "targets": [],
            },
            "config": config,
            "runtime": {
                "status": {
                    "phase": "idle",
                    "stage": "desktop_composition",
                    "message": state_message,
                },
                "engine": {
                    "state": "sleeping",
                    "message": "Lookup providers are not initialized.",
                },
                "ocr_provider": None,
                "ocr_backends": _ocr_backends(),
                "app_version": _installed_version(),
                "hover_delay_bounds": {
                    "min": HOVER_DELAY_MIN_MS,
                    "max": HOVER_DELAY_MAX_MS,
                },
                "hotkeys": {},
                "resources": [],
                "diagnostics": list(self.log.snapshot()),
                "log_path": None,
            },
            "updates": {
                "available": False,
                "status": "unavailable",
                "message": "Update services are not connected in the migration foundation.",
            },
            "permissions": {
                "available": False,
                "supported": False,
                "items": [],
                "message": "Permission checks are not connected in this build.",
            },
        }

    def _update_settings(self, changes: object) -> dict[str, Any]:
        if not isinstance(changes, dict):
            raise ServiceError("invalid_params", "changes must be an object.")
        try:
            self.config.update(**changes)
        except ConfigError as error:
            raise ServiceError("service_error", "Settings could not be persisted.") from error
        except (TypeError, ValueError) as error:
            message = str(error)[:512] or "Settings are invalid."
            raise ServiceError("invalid_params", message) from error
        return self._state()

    def _logs(self) -> dict[str, Any]:
        # Keep replies comfortably below the 1 MiB frame cap, including when
        # records contain multi-byte text.
        records = [record.to_dict() for record in self.log.records()][-100:]
        return {
            "records": records,
            "levels": ["info", "warning", "error"],
            "subsystems": sorted({record["subsystem"] for record in records}),
            "log_path": None,
        }


def _installed_version() -> str | None:
    try:
        return metadata.version("hanly-app")
    except metadata.PackageNotFoundError:
        return None


def _target_name(monitor: object) -> str:
    if monitor is None:
        return "cursor"
    return f"monitor:{monitor}"


def _ocr_backends() -> list[str]:
    choices = ["auto", "easyocr"]
    if sys.platform == "darwin":
        choices.insert(1, "vision")
    return choices
