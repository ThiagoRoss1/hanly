"""Qt-free application composition for the supervised Hanly desktop service."""

from __future__ import annotations

import json
import math
import threading
import uuid
from collections.abc import Callable, Mapping
from dataclasses import fields, is_dataclass, replace
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hanly import BoundingBox, LookupResult, Point

from hanly_app.acquisition.capture import (
    DEFAULT_ROI_GRID,
    CaptureService,
    ScreenRect,
)
from hanly_app.acquisition.selection import CaptureSelection
from hanly_app.config import (
    AppConfig,
    CaptureMode,
    ConfigError,
    ConfigManager,
    LookupPreload,
)
from hanly_app.control_center.bridge import (
    ControlCenterBridge,
    ControlCenterUnavailable,
)
from hanly_app.desktop_controller import DesktopController, DesktopState
from hanly_app.diagnostics import DiagnosticLog, RotatingLogFile
from hanly_app.hotkeys import HotkeyAction, HotkeyEdge
from hanly_app.paths import (
    default_app_config_path,
    default_log_directory,
    default_runtime_config_path,
    discover_runtime_config,
)
from hanly_app.permissions import (
    CAPTURE_PERMISSIONS,
    PermissionService,
    create_permission_service,
    missing_permission_refusal,
)
from hanly_app.popup.presentation import (
    PopupController,
    PopupPosition,
    PopupSize,
    ScreenGeometry,
    format_lookup_result,
)
from hanly_app.runtime_status import (
    RuntimeStatusPublisher,
    derive_application_snapshot,
)
from hanly_app.runtime_trace import RuntimeTraceSink, emit_trace

from .event_loop import SerializedEventLoop
from .protocol import (
    MAX_FRAME_BYTES,
    MAX_PENDING_REQUESTS,
    MAX_STRUCTURE_DEPTH,
    PROTOCOL_VERSION,
    Request,
    allowed_windows,
    known_method,
)
from .snapshot import SnapshotError, capture_selection_backdrop, native_monitor_rects

if TYPE_CHECKING:
    from hanly_app.hover.lookup import CaptureObserver

IMPLEMENTED_METHODS = frozenset(
    {
        "service.hello",
        "service.shutdown",
        "settings.prepare",
        "settings.commit",
        "settings.abort",
        "native.input",
        "native.context",
        "native.selection",
        "native.selection_snapshot",
        "native.region_selected",
        "service.popup_geometry",
        "service.popup_close",
        "service.popup_expand",
        "update.acknowledge",
        "self_check",
        "get_state",
        "update_settings",
        "get_logs",
        "start_capture",
        "stop_capture",
        "set_capture_mode",
        "set_target",
        "set_region",
        "select_capture_area",
        "set_hover_delay",
        "set_hotkey",
        "grant_permission",
        "refresh_permissions",
        "retry_runtime",
        "quit",
        "check_for_updates",
        "install_update",
        "install_application_update",
        "cancel_update",
        "open_release_notes",
        "clear_logs",
        "export_diagnostics",
    }
)
_UNSAFE_TRACE_VALUE = object()


class ServiceError(RuntimeError):
    """A correlated application error suitable for a protocol reply."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message[:512]


class _NativeHotkeyRuntime:
    """Translate host-owned native key edges into the existing action seam."""

    _ACTION_NAMES = {
        "push_to_hover": HotkeyAction.PUSH_TO_HOVER,
        "toggle_hover": HotkeyAction.TOGGLE_HOVER,
        "toggle_capture": HotkeyAction.TOGGLE_CAPTURE,
    }

    def __init__(self, handler: Callable[[HotkeyAction, HotkeyEdge], None]) -> None:
        self._handler = handler
        self._actual: dict[str, str] = {}
        self._configured: dict[HotkeyAction, str] = {}
        self._closed = False

    @property
    def bindings(self) -> Mapping[HotkeyAction, str]:
        return {
            self._ACTION_NAMES[name]: binding
            for name, binding in self._actual.items()
            if name in self._ACTION_NAMES and binding
        }

    @property
    def registered(self) -> bool:
        return bool(self._actual) and not self._closed

    def register(self) -> None:
        """Confirm the host owns registrations; never register OS keys here."""

    def rebind(self, action: HotkeyAction, binding: str) -> None:
        self._configured[action] = binding

    def unbind(self, action: HotkeyAction) -> None:
        self._configured.pop(action, None)

    def apply_registered(self, bindings: Mapping[str, str]) -> None:
        self._actual = dict(bindings)

    def dispatch(self, action: str, edge: str) -> bool:
        if self._closed or action not in self._ACTION_NAMES:
            return False
        self._handler(
            self._ACTION_NAMES[action],
            HotkeyEdge.DOWN if edge == "pressed" else HotkeyEdge.UP,
        )
        return True

    def shutdown(self) -> None:
        self._closed = True
        self._actual.clear()


class _ServiceLifecycle:
    """Keep bridge lifecycle identity stable while a runtime is replaced."""

    def __init__(self) -> None:
        self.controller: DesktopController | None = None

    @property
    def state(self) -> DesktopState:
        return DesktopState.NEW if self.controller is None else self.controller.state

    def replace(self, manual: Any | None) -> None:
        self.controller = None if manual is None else DesktopController(manual)

    def start(self) -> None:
        if self.controller is None:
            raise RuntimeError("desktop runtime is not prepared")
        self.controller.start()

    def stop(self) -> None:
        if self.controller is not None:
            self.controller.stop()

    def resume(self) -> None:
        if self.controller is not None:
            self.controller.resume()

    def apply_config(self, config: AppConfig) -> None:
        if self.controller is not None:
            self.controller.apply_config(config)

    def set_capture_preferences(
        self,
        *,
        capture_mode: CaptureMode,
        monitor: int | None,
        region: ScreenRect | None,
    ) -> None:
        if self.controller is not None:
            self.controller.set_capture_preferences(
                capture_mode=capture_mode,
                monitor=monitor,
                region=region,
            )


class _PopupModelView:
    """No-window view used only for the existing pure placement controller."""

    def show_result(self, result: Any, position: PopupPosition) -> None:
        del result, position

    def update_result(self, result: Any, position: PopupPosition) -> None:
        del result, position

    def hide(self) -> None:
        pass

    def close(self) -> None:
        return None


class DesktopService:
    """Own protocol operations and lazily compose the existing desktop runtime."""

    def __init__(
        self,
        config_path: str | Path | None = None,
        *,
        runtime_config_path: str | Path | None = None,
        roi_size: tuple[int, int] = (200, 100),
        installation_root: str | Path | None = None,
        root_pid: int | None = None,
        event_loop: SerializedEventLoop[Any] | None = None,
        runtime_loader: Callable[[Path], Any] | None = None,
        runtime_provisioner: Callable[[Path, Callable[[str], None]], Path] | None = None,
        trace_sink: RuntimeTraceSink | None = None,
        capture_service_factory: Callable[..., CaptureService] | None = None,
        current_cursor_provider: Callable[[], Point] | None = None,
        capture_observer: CaptureObserver | None = None,
        self_check_mode: str | None = None,
    ) -> None:
        self.config_manager = ConfigManager(config_path or default_app_config_path())
        self.config_manager.load()
        log_path = default_log_directory() / "hanly.log"
        if config_path is not None:
            log_path = Path(config_path).expanduser().resolve().parent / "logs" / "hanly.log"
        self.log = DiagnosticLog(RotatingLogFile(log_path))
        self.log.record("Service", "Hanly desktop service started.")

        self.runtime_config_path = (
            Path(runtime_config_path).expanduser().resolve()
            if runtime_config_path is not None
            else None
        )
        self.installation_root = (
            Path(installation_root).expanduser().resolve()
            if installation_root is not None
            else None
        )
        self.root_pid = root_pid
        self.self_check_mode = self_check_mode
        self.roi_size = roi_size
        self._loop = event_loop
        self._runtime_loader = runtime_loader
        self._runtime_provisioner = runtime_provisioner
        self._capture_service_factory = capture_service_factory
        self._current_cursor_provider = current_cursor_provider or _read_current_cursor
        self._capture_observer = capture_observer
        if self_check_mode is not None and self_check_mode not in {
            "inventory",
            "ocr",
            "worker",
            "ui",
        }:
            raise ValueError("self_check_mode is unsupported")
        self._provided_trace_sink = trace_sink
        self._trace_sink = (
            None if trace_sink is None else _ForwardingTraceSink(self, trace_sink)
        )
        self._event_sink: Callable[[str, Mapping[str, Any]], None] | None = None
        self._event_sequence = 0
        self._shutdown_requested = False
        self._hello_seen = False
        self._startup_generation = 0
        self._startup_thread: threading.Thread | None = None
        self._pending_runtime: tuple[int, Any, Path] | None = None
        self._native_context_received = False
        self._vision_available = False
        self._runtime: Any | None = None
        self._capture: CaptureService | None = None
        self._manual: Any | None = None
        self._updates: Any | None = None
        self._lifecycle = _ServiceLifecycle()
        self._permissions: PermissionService = create_permission_service()
        self._status = RuntimeStatusPublisher(
            dispatcher=self._dispatch_callback,
        )
        self._engine_state = ("sleeping", "Lookup providers are not loaded.")
        self._native_hotkeys: _NativeHotkeyRuntime | None = None
        self._cursor: Point | None = None
        self._cursor_lock = threading.Lock()
        self._pending_cursor: Point | None = None
        self._cursor_update_queued = False
        self._monitors: list[dict[str, Any]] = []
        self._registered_hotkey_context: dict[str, str] = {}
        self._popup_sequence = 0
        self._popup_result: LookupResult | None = None
        self._popup_request_id: int | None = None
        self._popup_presented = False
        self._popup_position: PopupPosition | None = None
        self._popup_size = PopupSize()
        self._popup_expanded = False
        self._popup_actual_rect: ScreenRect | None = None
        self._selection_active = False
        self._selection_resume_hover = False
        self._hover_muted = False
        self._last_update_snapshot: dict[str, Any] | None = None
        self._pending_settings: dict[str, tuple[dict[str, object], dict[str, object]]] = {}

        self.bridge = ControlCenterBridge(
            config_manager=self.config_manager,
            desktop_controller=self._lifecycle,
            diagnostics=lambda: self.log.snapshot()[-100:],
            on_lifecycle_changed=self._publish_state,
            runtime_status=lambda: self._status.status,
            capture_ready=lambda: self._runtime is not None,
            on_quit=self._request_quit,
            log_path=log_path,
            permission_service=self._permissions,
            ocr_provider="Not reported",
            engine_status=self._engine_snapshot,
            registered_hotkeys=self._registered_hotkeys,
            application_snapshot=self._application_snapshot,
            diagnostic_log=self.log,
            vision_available=lambda: self._vision_available,
        )
        self.bridge.set_retry(self.retry_runtime)

    @property
    def shutdown_requested(self) -> bool:
        return self._shutdown_requested

    @property
    def runtime_ready(self) -> bool:
        return self._runtime is not None and self._status.status.ready

    def set_event_sink(
        self,
        sink: Callable[[str, Mapping[str, Any]], None] | None,
    ) -> None:
        self._event_sink = sink

    def bind_event_loop(self, loop: SerializedEventLoop[Any]) -> None:
        self._loop = loop
        self._status = RuntimeStatusPublisher(dispatcher=self._dispatch_callback)
        self.bridge._runtime_status = lambda: self._status.status

    def after_reply(self, request: Request) -> None:
        """Start preparation only after the host has received service.hello."""

        if request.method != "service.hello" or self._hello_seen:
            return
        self._hello_seen = True
        if self.self_check_mode is None:
            self._begin_runtime_preparation()

    def dispatch(self, request: Request) -> dict[str, Any]:
        """Run one authorized method on the serialized service owner thread."""

        if not known_method(request.method):
            raise ServiceError("unknown_method", "Request method is not supported.")
        if request.window not in allowed_windows(request.method):
            raise ServiceError("unauthorized", "Request window is not authorized.")

        method = request.method
        params = request.params
        if method == "service.hello":
            return self._hello()
        if method == "service.shutdown":
            self._shutdown_requested = True
            return {"accepted": True}
        if method == "get_state":
            return self._state()
        if method == "get_logs":
            return self._logs()
        if method == "settings.prepare":
            return self._prepare_settings(params["changes"])
        if method == "settings.commit":
            return self._commit_settings(params["token"])
        if method == "settings.abort":
            return {"aborted": self._pending_settings.pop(params["token"], None) is not None}
        if method == "native.context":
            return self._native_context(params)
        if method == "native.input":
            return self._native_input(params)
        if method == "native.selection":
            return self._native_selection(params["active"])
        if method == "native.selection_snapshot":
            return self._native_selection_snapshot(params["bounds"])
        if method == "native.region_selected":
            return self._native_region_selected(params["region"])
        if method.startswith("service.popup_"):
            return self._popup_sync(method, params)
        if method == "update.acknowledge":
            return self._acknowledge_update(params)
        if method == "self_check":
            return self._run_self_check(params)

        return self._bridge_method(method, params)

    def close(self) -> None:
        """Stop observation, close the lookup child, and release updater work."""

        self._shutdown_requested = True
        self._startup_generation += 1
        self._pending_runtime = None
        startup = self._startup_thread
        if startup is not None and startup is not threading.current_thread():
            startup.join(timeout=5.0)
        manual = self._manual
        if manual is not None:
            try:
                manual.begin_shutdown()
                if not manual.await_shutdown(timeout=10.0):
                    self.log.record(
                        "Shutdown",
                        "Lookup cleanup did not finish before the service closed.",
                        level="warning",
                    )
            except Exception as error:
                self.log.record(
                    "Shutdown",
                    f"Lookup cleanup failed ({type(error).__name__}).",
                    level="warning",
                )
        if self._updates is not None:
            try:
                self._updates.shutdown(wait=False)
            except Exception:
                self.log.record("Shutdown", "Update cleanup failed.", level="warning")
        if self._capture is not None and manual is None:
            self._capture.close()

    def _hello(self) -> dict[str, Any]:
        return {
            "service": "hanly-desktop",
            "protocol_version": PROTOCOL_VERSION,
            "service_status": "running",
            "runtime_ready": self.runtime_ready,
            "providers_loaded": self._engine_state[0] == "ready",
            "limits": {
                "max_frame_bytes": MAX_FRAME_BYTES,
                "max_pending": MAX_PENDING_REQUESTS,
            },
            "implemented_methods": sorted(IMPLEMENTED_METHODS),
        }

    def _state(self) -> dict[str, Any]:
        state = self.bridge.get_state()
        state["runtime"]["diagnostics"] = state["runtime"].get("diagnostics", [])[-100:]
        return state

    def _logs(self) -> dict[str, Any]:
        result = self.bridge.get_logs()
        records = result.get("records", [])
        result["records"] = records[-100:] if isinstance(records, list) else []
        return result

    def _bridge_method(self, method: str, params: Mapping[str, Any]) -> dict[str, Any]:
        handlers: dict[str, tuple[str, tuple[str, ...]]] = {
            "start_capture": ("start_capture", ()),
            "stop_capture": ("stop_capture", ()),
            "set_capture_mode": ("set_capture_mode", ("mode",)),
            "set_target": ("set_target", ("target",)),
            "set_region": ("set_region", ("region",)),
            "select_capture_area": ("select_capture_area", ()),
            "set_hover_delay": ("set_hover_delay", ("delay_ms",)),
            "set_hotkey": ("set_hotkey", ("hotkey",)),
            "update_settings": ("update_settings", ("changes",)),
            "grant_permission": ("grant_permission", ("permission",)),
            "refresh_permissions": ("refresh_permissions", ()),
            "retry_runtime": ("retry_runtime", ()),
            "quit": ("quit", ()),
            "check_for_updates": ("check_for_updates", ()),
            "install_update": ("install_update", ("resource_id",)),
            "install_application_update": ("install_application_update", ("confirm_full",)),
            "cancel_update": ("cancel_update", ()),
            "open_release_notes": ("open_release_notes", ()),
            "clear_logs": ("clear_logs", ()),
            "export_diagnostics": ("export_diagnostics", ()),
        }
        handler = handlers.get(method)
        if handler is None or method not in IMPLEMENTED_METHODS:
            raise ServiceError("unavailable", "This desktop operation is not connected.")
        name, fields = handler
        try:
            if method == "start_capture":
                result = self._start_capture()
            elif method == "update_settings":
                result = self._update_settings(params["changes"])
            else:
                result = getattr(self.bridge, name)(
                    *(params[field] for field in fields if field in params)
                )
        except ControlCenterUnavailable as error:
            raise ServiceError("unavailable", str(error)) from error
        except ConfigError as error:
            raise ServiceError("service_error", "Settings could not be persisted.") from error
        except (TypeError, ValueError) as error:
            raise ServiceError("invalid_params", _safe_message(error)) from error
        except Exception as error:
            self.log.record("Service", f"{method} failed ({type(error).__name__}).", level="error")
            raise ServiceError(
                "service_error", "The desktop operation could not be completed."
            ) from error
        return result if isinstance(result, dict) else {"accepted": True}

    def _prepare_settings(self, changes: object) -> dict[str, Any]:
        if not isinstance(changes, dict):
            raise ServiceError("invalid_params", "changes must be an object.")
        if len(self._pending_settings) >= 32:
            raise ServiceError("busy", "Too many settings changes are awaiting confirmation.")
        try:
            candidate = self.bridge._candidate(changes)
            if (
                candidate.ocr_backend.value == "vision"
                and "vision" not in self.bridge._ocr_backends()
            ):
                raise ControlCenterUnavailable("Apple Vision is only available on macOS")
            _validate_shortcut_set(candidate)
        except (TypeError, ValueError, ControlCenterUnavailable) as error:
            code = (
                "unavailable"
                if isinstance(error, ControlCenterUnavailable)
                else "invalid_params"
            )
            raise ServiceError(code, _safe_message(error)) from error

        token = uuid.uuid4().hex
        self._pending_settings[token] = (dict(changes), candidate.to_dict())
        return {"token": token, "settings": candidate.to_dict()}

    def _commit_settings(self, token: str) -> dict[str, Any]:
        pending = self._pending_settings.get(token)
        if pending is None:
            raise ServiceError("not_found", "Settings preparation token is no longer valid.")
        changes, candidate = pending
        if self.config_manager.config.to_dict() | changes != candidate:
            # The candidate is based on the stored snapshot; reject a stale
            # native registration transaction instead of overwriting newer state.
            current_candidate = self.config_manager.candidate(**changes).to_dict()
            if current_candidate != candidate:
                self._pending_settings.pop(token, None)
                raise ServiceError(
                    "conflict",
                    "Settings changed while the native shortcut was prepared.",
                )
        try:
            state = self._update_settings(changes)
        except (TypeError, ValueError) as error:
            raise ServiceError("invalid_params", _safe_message(error)) from error
        except ConfigError as error:
            raise ServiceError("service_error", "Settings could not be persisted.") from error
        self._pending_settings.pop(token, None)
        self._publish_state()
        return state

    def _update_settings(self, changes: Mapping[str, object]) -> dict[str, Any]:
        """Persist settings and restart provider residency when OCR changes."""

        previous_backend = self.config_manager.config.ocr_backend
        state = self.bridge.update_settings(changes)
        if (
            "ocr_backend" in changes
            and self.config_manager.config.ocr_backend is not previous_backend
        ):
            # The lookup child receives a concrete backend at creation. Retire
            # that worker before composing the next one with the new preference.
            self.retry_runtime()
            state = self._state()
        return state

    def _native_context(self, params: Mapping[str, Any]) -> dict[str, Any]:
        self._native_context_received = True
        self._vision_available = params.get("vision_available", False) is True
        self.bridge._vision_available = self._vision_available
        cursor = params["cursor"]
        self._cursor = Point(float(cursor["x"]), float(cursor["y"]))
        self._monitors = [dict(monitor) for monitor in params["monitors"]]
        if "registered_hotkeys" in params:
            self._registered_hotkey_context = dict(params["registered_hotkeys"])
            if self._native_hotkeys is not None:
                self._native_hotkeys.apply_registered(self._registered_hotkey_context)
            registered_count = sum(
                bool(self._registered_hotkey_context.get(action))
                for action in _NativeHotkeyRuntime._ACTION_NAMES
            )
            emit_trace(
                self._trace_sink,
                "native_context",
                registered_hotkey_count=registered_count,
            )
        pending = self._pending_runtime
        if pending is not None:
            self._pending_runtime = None
            generation, runtime, runtime_path = pending
            if generation == self._startup_generation and not self._shutdown_requested:
                self._runtime_loaded(generation, runtime, runtime_path)
        if "popup_rect" in params and self._popup_sequence:
            rect = params["popup_rect"]
            self._set_popup_geometry(
                self._popup_sequence,
                ScreenRect(rect["left"], rect["top"], rect["width"], rect["height"]),
            )
        self._publish_state()
        return {"accepted": True}

    def _native_input(self, params: Mapping[str, Any]) -> dict[str, Any]:
        native = self._native_hotkeys
        action = params["action"]
        edge = params["edge"]
        accepted = False
        if native is not None:
            if (
                action == HotkeyAction.PUSH_TO_HOVER.value
                and edge == "pressed"
                and not self._refresh_native_cursor()
            ):
                accepted = False
            else:
                accepted = native.dispatch(action, edge)
        emit_trace(
            self._trace_sink,
            "native_input",
            action=action,
            edge=edge,
            accepted=accepted,
        )
        return {"accepted": accepted}

    def _start_capture(self) -> dict[str, Any]:
        try:
            return self.bridge.start_capture()
        except Exception as error:
            if self._permissions.missing(CAPTURE_PERMISSIONS):
                code = "permission_required"
            elif isinstance(error, ControlCenterUnavailable):
                code = "not_ready"
            else:
                code = "start_failed"
            emit_trace(
                self._trace_sink,
                "capture_start_failed",
                code=code,
            )
            raise

    def _refresh_native_cursor(self) -> bool:
        try:
            cursor = self._current_cursor_provider()
        except Exception:
            cursor = None
        if (
            not isinstance(cursor, Point)
            or not math.isfinite(cursor.x)
            or not math.isfinite(cursor.y)
        ):
            self.log.record(
                "Keyboard shortcuts",
                "Push to Hover was ignored because the cursor position was unavailable.",
                level="warning",
            )
            return False
        self._store_cursor(cursor)
        return True

    def _native_selection(self, active: bool) -> dict[str, Any]:
        if active == self._selection_active:
            return {"active": self._selection_active}
        self._selection_active = active
        if active:
            self._hide_current_popup()
        hover = None if self._manual is None else self._manual.hover_runtime
        if active:
            self._selection_resume_hover = bool(hover is not None and hover.running)
            if self._selection_resume_hover and hover is not None:
                hover.pause()
        else:
            should_resume = self._selection_resume_hover
            self._selection_resume_hover = False
            if should_resume and hover is not None:
                hover.resume()
        self._publish_state()
        return {"active": active}

    def _native_selection_snapshot(self, value: object) -> dict[str, str]:
        if not self._selection_active:
            raise ServiceError(
                "unauthorized", "A backdrop is available only during capture-area selection."
            )
        if not isinstance(value, dict) or set(value) != {
            "left",
            "top",
            "width",
            "height",
        }:
            raise ServiceError("invalid_params", "bounds must be a screen rectangle.")
        try:
            bounds = ScreenRect(**value)
            monitors = native_monitor_rects(self._monitors)
            image = capture_selection_backdrop(bounds, monitors)
        except (TypeError, ValueError) as error:
            raise ServiceError(
                "invalid_params", "bounds must be a valid screen rectangle."
            ) from error
        except SnapshotError as error:
            raise ServiceError("unavailable", str(error)) from error
        return {"image": image}

    def _native_region_selected(self, raw_region: Mapping[str, Any]) -> dict[str, Any]:
        if not self._selection_active:
            raise ServiceError("unauthorized", "No capture selection is active.")
        region = ScreenRect(
            raw_region["left"],
            raw_region["top"],
            raw_region["width"],
            raw_region["height"],
        )
        self.bridge._apply_selection(CaptureSelection.for_region(region))
        self._publish_state()
        return self._state()

    def _popup_sync(self, method: str, params: Mapping[str, Any]) -> dict[str, Any]:
        sequence = params["sequence"]
        if sequence != self._popup_sequence:
            return {"accepted": False, "stale": True}
        if method == "service.popup_geometry":
            left, top = math.floor(params["x"]), math.floor(params["y"])
            # Native logical positions can fall between device pixels. Retain
            # the smallest integer rectangle containing the whole popup.
            right = math.ceil(params["x"] + params["width"])
            bottom = math.ceil(params["y"] + params["height"])
            rect = ScreenRect(left, top, right - left, bottom - top)
            self._set_popup_geometry(sequence, rect)
            self._note_popup_visible()
            return {"accepted": True}
        if method == "service.popup_close":
            self._hide_popup(sequence)
            return {"accepted": True}
        self._popup_expanded = params["expanded"]
        self._popup_size = _popup_size(self._popup_expanded)
        if self._popup_result is not None and self._cursor is not None:
            self._show_popup(
                self._popup_result,
                self._popup_request_id,
                expanded=self._popup_expanded,
            )
        return {"accepted": True}

    def _acknowledge_update(self, params: Mapping[str, Any]) -> dict[str, Any]:
        if self.installation_root is None:
            raise ServiceError("unavailable", "The installation root is not configured.")
        try:
            from hanly_app.updates.desktop_runtime import acknowledge_update_handoff

            acknowledge_update_handoff(
                install_root=self.installation_root,
                legacy_ready_path=params.get("legacy_ready_path"),
                challenge_path=params.get("challenge_path"),
            )
        except Exception as error:
            raise ServiceError(
                "handoff_rejected", "Update handoff could not be acknowledged."
            ) from error
        return {"acknowledged": True}

    def _run_self_check(self, params: Mapping[str, Any]) -> dict[str, Any]:
        mode = params["mode"]
        if self.self_check_mode is None or mode != self.self_check_mode:
            raise ServiceError(
                "unauthorized",
                "This self-check mode was not authorized by the host.",
            )
        try:
            from hanly_app.service.self_check import run_service_self_check

            report = run_service_self_check(
                mode,
                params.get("image"),
                runtime_config=self.runtime_config_path,
            )
        except (OSError, ValueError) as error:
            raise ServiceError(
                "self_check_failed",
                "The service self-check could not complete.",
            ) from error
        if not isinstance(report, dict):
            raise ServiceError(
                "self_check_failed",
                "The service self-check returned an invalid report.",
            )
        normalized = dict(report)
        normalized["mode"] = mode
        if type(normalized.get("ok")) is not bool:
            normalized["ok"] = False
        return normalized

    def _begin_runtime_preparation(self) -> None:
        if self.self_check_mode is not None:
            return
        if self._runtime is not None or self._startup_thread is not None:
            return
        self._pending_runtime = None
        self._startup_generation += 1
        generation = self._startup_generation
        self._status.update("preparing", "resources", "Preparing Hanly resources…")
        self._publish_status()
        thread = threading.Thread(
            target=self._prepare_runtime_worker,
            args=(generation,),
            name="hanly-service-runtime-prepare",
            daemon=True,
        )
        self._startup_thread = thread
        thread.start()

    def _prepare_runtime_worker(self, generation: int) -> None:
        try:
            runtime_path = self.runtime_config_path
            if runtime_path is None:
                runtime_path = discover_runtime_config() or default_runtime_config_path()
                provisioner = self._runtime_provisioner
                if provisioner is None:
                    from hanly_app.first_run import provision_runtime_config

                    def provisioner(path: Path, status: Callable[[str], None]) -> Path:
                        return provision_runtime_config(path, on_status=status)

                runtime_path = provisioner(
                    runtime_path,
                    lambda message: self._post_status_message(generation, message),
                )
            loader = self._runtime_loader
            if loader is None:
                from hanly_app.runtime import load_runtime

                loader = load_runtime
            runtime = loader(runtime_path)
        except Exception as error:
            def report_failure(failure: BaseException = error) -> None:
                self._startup_failed(generation, failure)

            self._post_owner(report_failure)
            return
        self._post_owner(lambda: self._runtime_loaded(generation, runtime, runtime_path))

    def _runtime_loaded(self, generation: int, runtime: Any, runtime_path: Path) -> None:
        if generation != self._startup_generation or self._shutdown_requested:
            return
        self._startup_thread = None
        from hanly_app.runtime import HanlyRuntime

        if isinstance(runtime, HanlyRuntime):
            if not self._native_context_received:
                self._pending_runtime = (generation, runtime, runtime_path)
                return
            runtime = self._runtime_for_host(runtime)
        self._pending_runtime = None
        try:
            self._compose_runtime(runtime, runtime_path)
        except Exception as error:
            self._startup_failed(generation, error)
            return
        self._runtime = runtime
        self._status.update("ready", "desktop service", "Hanly is ready.")
        self._publish_status()
        self._publish_state()
        emit_trace(self._trace_sink, "runtime_preparation_completed", phase="runtime")

    def _compose_runtime(self, runtime: Any, runtime_path: Path) -> None:
        from hanly_app.manual_lookup import create_manual_lookup
        from hanly_app.updates.desktop_runtime import create_update_coordinator

        capture_factory = self._capture_service_factory or CaptureService
        capture = capture_factory(roi_size=self.roi_size, roi_grid=DEFAULT_ROI_GRID)
        manual_holder: list[Any] = []

        def popup(result: Any) -> None:
            request_id = (
                manual_holder[0].controller.current_request_id
                if manual_holder
                else None
            )
            self._show_popup(result, request_id)

        def toggle_capture() -> None:
            if self._lifecycle.state is DesktopState.RUNNING:
                self.bridge.stop_capture()
            else:
                self._start_capture()

        def toggle_hover() -> None:
            controller = self._lifecycle.controller
            if controller is None or controller.state is not DesktopState.RUNNING:
                return
            self._hover_muted = not self._hover_muted
            controller.set_hover_muted(self._hover_muted)
            self._publish_state()

        def hover_listener_factory(on_position: Callable[[int, int], None]) -> Any:
            from pynput import mouse

            def on_move(x: int, y: int) -> None:
                point = Point(float(x), float(y))
                self._queue_cursor(point)
                on_position(x, y)

            return mouse.Listener(on_move=on_move)

        manual = create_manual_lookup(
            runtime,
            capture,
            popup,
            close_popup=self._hide_current_popup,
            clear_popup=self._hide_current_popup,
            current_cursor=self._current_cursor,
            dispatcher=self._dispatch_callback,
            hover_enabled=True,
            app_config=self.config_manager.config,
            hotkey_factory=self._make_hotkey_runtime,
            hover_listener_factory=hover_listener_factory,
            hover_scheduler=self._schedule,
            exit_scheduler=self._schedule,
            idle_scheduler=lambda seconds, callback: self._schedule(seconds * 1000, callback),
            shutdown_scheduler=self._schedule_shutdown_work,
            on_toggle_capture=toggle_capture,
            on_toggle_hover=toggle_hover,
            on_engine_state=self._post_engine_state,
            trace_sink=self._trace_sink,
            capture_observer=self._capture_observer,
            on_diagnostic=lambda message: self.log.record("Lookup", message),
            on_error=lambda stage, error: self.log.record(
                stage, f"Lookup operation failed ({type(error).__name__}).", level="error"
            ),
            on_initialization_error=lambda error: self._post_owner(
                lambda: self._engine_failed(error)
            ),
            on_stopped=lambda: self._post_owner(self._publish_state),
            capture_refusal=lambda: missing_permission_refusal(
                self._permissions.missing(CAPTURE_PERMISSIONS)
            ),
        )
        manual_holder.append(manual)
        self._manual = manual
        self._capture = capture
        self._lifecycle.replace(manual)
        if self._registered_hotkey_context and self._native_hotkeys is not None:
            self._native_hotkeys.apply_registered(self._registered_hotkey_context)
        self.bridge.attach_runtime(
            runtime,
            capture,
            update_coordinator=None,
        )
        self.bridge._ocr_provider = lambda: _ocr_display_name(runtime)
        manual.prepare()

        def report(subsystem: str, message: str) -> None:
            self.log.record(subsystem, message, level="error")

        def before_install(_resource_id: str) -> None:
            manual = self._call_owner(lambda: self._manual)
            if manual is None:
                return
            self._call_owner(manual.stop)
            if not manual.await_shutdown(timeout=30.0):
                raise TimeoutError("lookup worker did not release its resources")

        def after_install(_resource_id: str) -> None:
            from hanly_app.runtime import load_runtime

            manual = self._call_owner(lambda: self._manual)
            if manual is not None:
                self._call_owner(manual.begin_shutdown)
                if not manual.await_shutdown(timeout=10.0):
                    raise TimeoutError("lookup worker did not shut down after update")
            refreshed = load_runtime(runtime_path)
            self._call_owner(lambda: self._replace_runtime(refreshed, runtime_path))

        self._updates = create_update_coordinator(
            runtime_path,
            runtime.resource_manager,
            install_root=self.installation_root,
            root_pid=self.root_pid,
            report=report,
            before_install=before_install,
            after_install=after_install,
            on_restart_required=lambda: self._post_owner(
                lambda: self._emit_event("native_action", {"action": "restart_required"})
            ),
            automatic_check=self.config_manager.config.update_checks_enabled,
        )
        if self._updates is not None:
            self.bridge._update_coordinator = self._updates
            self._last_update_snapshot = self._updates.snapshot()
            self._schedule(250, self._publish_update_progress)
        self.bridge.set_retry(self.retry_runtime)
        self._status.update("ready", "desktop service", "Hanly is ready.")

    def _replace_runtime(self, runtime: Any, runtime_path: Path) -> None:
        runtime = self._runtime_for_host(runtime)
        self._manual = None
        self._capture = None
        self._lifecycle.replace(None)
        self._runtime = None
        self._compose_runtime(runtime, runtime_path)
        self._runtime = runtime
        self._publish_state()

    def _runtime_for_host(self, runtime: Any) -> Any:
        """Resolve app OCR preferences with the host's Vision capability."""

        from hanly_app.runtime import HanlyRuntime

        if not isinstance(runtime, HanlyRuntime):
            return runtime
        return replace(
            runtime,
            ocr_backend=self.config_manager.config.ocr_backend,
            vision_available=self._vision_available,
        )

    def _startup_failed(self, generation: int, error: BaseException) -> None:
        if generation != self._startup_generation or self._shutdown_requested:
            return
        self._startup_thread = None
        self._pending_runtime = None
        if self._manual is not None:
            self._manual.begin_shutdown()
        elif self._capture is not None:
            self._capture.close()
        if self._updates is not None:
            self._updates.shutdown(wait=False)
        self._manual = None
        self._capture = None
        self._updates = None
        self._lifecycle.replace(None)
        self.log.record(
            "Runtime",
            f"Runtime preparation failed ({type(error).__name__}).",
            level="error",
        )
        emit_trace(self._trace_sink, "runtime_preparation_failed", phase="runtime")
        self._status.update(
            "failed",
            "runtime preparation",
            "Hanly could not prepare its runtime. Check Diagnostics for details.",
        )
        self._publish_status()
        self._publish_state()

    def _engine_failed(self, error: BaseException) -> None:
        self.log.record("Lookup", f"Lookup runtime failed ({type(error).__name__}).", level="error")
        self._engine_state = ("error", "Lookup providers could not start.")
        self._publish_state()

    def _post_engine_state(self, state: str, message: str) -> None:
        self._post_owner(lambda: self._set_engine_state(state, message))

    def _set_engine_state(self, state: str, message: str) -> None:
        self._engine_state = (state, message[:512])
        self._publish_state()

    def _engine_snapshot(self) -> Mapping[str, str]:
        engine = None if self._manual is None else self._manual.engine
        if engine is not None:
            state = engine.state
            return {"state": state, "message": self._engine_state[1]}
        return {"state": self._engine_state[0], "message": self._engine_state[1]}

    def _application_snapshot(self) -> Any:
        controller = self._lifecycle.controller
        capture_requested = controller is not None and controller.state is DesktopState.RUNNING
        engine = self._engine_snapshot()
        return derive_application_snapshot(
            self._status.status,
            engine_state=engine["state"],
            engine_message=engine["message"],
            capture_requested=capture_requested,
            stopping=bool(self._manual is not None and self._manual.retiring),
            hover_muted=bool(self._manual is not None and self._manual.hover_muted),
            wakes_on_demand=self.config_manager.config.lookup_preload is LookupPreload.ON_DEMAND,
        )

    def _registered_hotkeys(self) -> Mapping[str, str]:
        if self._native_hotkeys is None:
            return {}
        return {
            action.value: binding
            for action, binding in self._native_hotkeys.bindings.items()
        }

    def _make_hotkey_runtime(
        self,
        handler: Callable[[HotkeyAction, HotkeyEdge], None],
        _bindings: Mapping[HotkeyAction | str, str],
        _dispatcher: Callable[[Callable[[], None]], None],
    ) -> _NativeHotkeyRuntime:
        self._native_hotkeys = _NativeHotkeyRuntime(handler)
        return self._native_hotkeys

    def _current_cursor(self) -> Point:
        if self._cursor is None:
            raise RuntimeError("native cursor context is not available")
        return self._cursor

    def _store_cursor(self, cursor: Point) -> None:
        self._cursor = cursor

    def _schedule_shutdown_work(self, callback: Callable[[], None]) -> None:
        thread = threading.Thread(
            target=callback,
            name="hanly-service-lookup-retire",
            daemon=True,
        )
        thread.start()

    def _publish_update_progress(self) -> None:
        updates = self._updates
        if updates is None or self._shutdown_requested:
            return
        snapshot = updates.snapshot()
        if snapshot != self._last_update_snapshot:
            self._last_update_snapshot = snapshot
            self._publish_state()
        self._schedule(250, self._publish_update_progress)

    def _show_popup(
        self,
        result: LookupResult,
        request_id: int | None,
        *,
        expanded: bool | None = None,
    ) -> None:
        if not self.config_manager.config.popup_enabled:
            return
        cursor = self._current_cursor()
        screen = self._screen_for(cursor)
        config = self.config_manager.config
        expanded = (
            config.popup_default_size.value == "expanded"
            if expanded is None
            else expanded
        )
        size = _popup_size(expanded)
        word = (
            self._manual.word_rect(result, request_id)
            if self._manual is not None
            else None
        )
        anchor = (
            None
            if word is None
            else BoundingBox(word.left, word.top, word.right, word.bottom)
        )
        popup_controller = PopupController(_PopupModelView(), popup_size=size)
        position = popup_controller.open(result, cursor, screen, anchor=anchor)
        if self._popup_result is not result or self._popup_request_id != request_id:
            self._popup_presented = False
        self._popup_result = result
        self._popup_request_id = request_id
        self._popup_position = position
        self._popup_size = size
        self._popup_expanded = expanded
        self._popup_sequence += 1
        self._popup_actual_rect = ScreenRect(position.x, position.y, size.width, size.height)
        content = format_lookup_result(result, config.technical_details)
        self._emit_event(
            "popup",
            {
                "sequence": self._popup_sequence,
                "content": _plain(content),
                "position": {"x": position.x, "y": position.y},
                "size": {"width": size.width, "height": size.height},
                "expanded": expanded,
                "technical_details": config.technical_details.value,
                "theme": config.theme.value,
            },
        )
        sequence = self._popup_sequence

        def retain_geometry() -> None:
            self._retain_popup_geometry(sequence, request_id)

        self._post_owner(retain_geometry)

    def _retain_popup_geometry(self, sequence: int, request_id: int | None) -> None:
        if sequence != self._popup_sequence or self._manual is None:
            return
        if request_id != self._manual.controller.current_request_id:
            return
        if self._popup_actual_rect is not None:
            self._manual.update_popup_geometry(self._popup_actual_rect)

    def _screen_for(self, cursor: Point) -> ScreenGeometry:
        for monitor in self._monitors:
            bounds = monitor["bounds"]
            left, top = bounds["left"], bounds["top"]
            right, bottom = left + bounds["width"], top + bounds["height"]
            if left <= cursor.x < right and top <= cursor.y < bottom:
                return ScreenGeometry(left, top, bounds["width"], bounds["height"])
        if self._monitors:
            bounds = self._monitors[0]["bounds"]
            return ScreenGeometry(
                bounds["left"], bounds["top"], bounds["width"], bounds["height"]
            )
        if self._capture is not None:
            monitors = self._capture.enumerate_monitors()
            if monitors:
                bounds = monitors[0].bounds
                return ScreenGeometry(
                    bounds.left, bounds.top, bounds.width, bounds.height
                )
        raise RuntimeError("native display geometry is not available")

    def _set_popup_geometry(self, sequence: int, rect: ScreenRect) -> None:
        if sequence != self._popup_sequence:
            return
        self._popup_actual_rect = rect
        if self._manual is not None:
            self._manual.update_popup_geometry(rect)

    def _note_popup_visible(self) -> None:
        """Record one current answer after React reports its native frame."""

        result = self._popup_result
        if result is None or self._popup_presented:
            return
        request_id = self._popup_request_id
        if request_id is not None and (
            self._manual is None
            or request_id != self._manual.controller.current_request_id
        ):
            return
        # Geometry follows rendering and a successful native resize. Publishing
        # the service event alone cannot establish presentation.
        self._popup_presented = True
        emit_trace(
            self._trace_sink,
            "popup_visible",
            stage="popup_visible",
            lookup_request_id=request_id,
            result_status=result.status.value,
        )

    def _hide_current_popup(self) -> None:
        if self._popup_sequence:
            self._hide_popup(self._popup_sequence)

    def _hide_popup(self, sequence: int) -> None:
        if sequence != self._popup_sequence:
            return
        if self._manual is not None and self._manual.hover_runtime is not None:
            self._manual.hover_runtime.clear_target()
        self._popup_result = None
        self._popup_request_id = None
        self._popup_presented = False
        self._popup_actual_rect = None
        self._emit_event("popup_hide", {"sequence": sequence})

    def _request_quit(self) -> None:
        self._emit_event("native_action", {"action": "quit"})

    def _publish_state(self) -> None:
        if self._event_sink is None:
            return
        self._emit_event("state", self._state())

    def _publish_status(self) -> None:
        self._emit_event(
            "service_status",
            {
                **self._status.status.to_dict(),
                "runtime_ready": self.runtime_ready,
                "providers_loaded": self._engine_state[0] == "ready",
            },
        )

    def _emit_event(self, name: str, payload: Mapping[str, Any]) -> None:
        self._event_sequence += 1
        sink = self._event_sink
        if sink is not None:
            sink(name, payload)

    def _dispatch_callback(self, callback: Callable[[], None]) -> None:
        loop = self._loop
        if loop is None:
            callback()
            return
        loop.post(callback)

    def _post_owner(self, callback: Callable[[], None]) -> None:
        self._try_post_owner(callback)

    def _try_post_owner(self, callback: Callable[[], None]) -> bool:
        try:
            self._dispatch_callback(callback)
        except Exception as error:
            self.log.record(
                "Service",
                f"An owner callback could not be scheduled ({type(error).__name__}).",
                level="warning",
            )
            return False
        return True

    def _queue_cursor(self, cursor: Point) -> None:
        """Coalesce mouse-motion samples into one owner-loop callback."""

        with self._cursor_lock:
            self._pending_cursor = cursor
            if self._cursor_update_queued:
                return
            self._cursor_update_queued = True
        if not self._try_post_owner(self._flush_cursor):
            with self._cursor_lock:
                self._cursor_update_queued = False

    def _flush_cursor(self) -> None:
        with self._cursor_lock:
            cursor = self._pending_cursor
            self._pending_cursor = None
            self._cursor_update_queued = False
        if cursor is not None:
            self._store_cursor(cursor)

    def _call_owner(self, callback: Callable[[], Any]) -> Any:
        loop = self._loop
        return callback() if loop is None else loop.call_sync(callback, timeout=60.0)

    def _schedule(self, delay_ms: float, callback: Callable[[], None]) -> Any:
        loop = self._loop
        if loop is None:
            raise RuntimeError("service event loop is not running")
        return loop.call_later(delay_ms, callback)

    def _post_status_message(self, generation: int, message: str) -> None:
        self._post_owner(lambda: self._set_status_message(generation, message))

    def _set_status_message(self, generation: int, message: str) -> None:
        if generation != self._startup_generation:
            return
        self._status.update("preparing", "resources", message[:512])
        self._publish_status()

    def retry_runtime(self) -> None:
        if self._startup_thread is not None and self._startup_thread.is_alive():
            return
        if self._updates is not None:
            update_state = self._updates.snapshot()
            if update_state.get("status") in {"checking", "preparing"} or bool(
                update_state.get("awaiting_confirmation")
            ):
                raise ControlCenterUnavailable(
                    "Wait for the current update operation to finish before retrying Hanly."
                )
            self._updates.shutdown(wait=False)
        self._startup_generation += 1
        generation = self._startup_generation
        manual = self._manual
        self._runtime = None
        self._status.update("preparing", "runtime retry", "Retrying Hanly runtime preparation…")
        self._publish_status()
        if manual is None:
            self._finish_runtime_retry(generation)
            return

        manual.begin_shutdown()

        def wait_for_shutdown() -> None:
            if not manual.await_shutdown(timeout=10.0):
                self._post_owner(lambda: self._runtime_retry_failed(generation))
                return
            self._post_owner(lambda: self._finish_runtime_retry(generation))

        worker = threading.Thread(
            target=wait_for_shutdown,
            name="hanly-service-runtime-retry",
            daemon=True,
        )
        self._startup_thread = worker
        worker.start()

    def _finish_runtime_retry(self, generation: int) -> None:
        if generation != self._startup_generation or self._shutdown_requested:
            return
        self._manual = None
        self._capture = None
        self._updates = None
        self._pending_runtime = None
        self._lifecycle.replace(None)
        self._startup_thread = None
        self._begin_runtime_preparation()

    def _runtime_retry_failed(self, generation: int) -> None:
        if generation != self._startup_generation or self._shutdown_requested:
            return
        self._startup_thread = None
        self._status.update(
            "failed",
            "runtime retry",
            "Hanly could not stop its lookup worker. Retry after it has shut down.",
        )
        self._publish_status()
        self._publish_state()


def _validate_shortcut_set(config: AppConfig) -> None:
    from hanly_app.hotkeys import validate_binding

    bindings: dict[str, str] = {}
    for name, value in (
        ("push_to_hover", config.hotkey),
        ("toggle_hover", config.hover_hotkey),
        ("toggle_capture", config.capture_hotkey),
    ):
        if not value.strip():
            continue
        normalized = validate_binding(value)
        if normalized in bindings:
            raise ValueError("Two actions cannot use the same shortcut.")
        bindings[normalized] = name


def _popup_size(expanded: bool) -> PopupSize:
    return PopupSize(width=460, height=420) if expanded else PopupSize()


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _plain(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _ocr_display_name(runtime: Any) -> str:
    try:
        from hanly_app.runtime import ocr_display_name

        return ocr_display_name(runtime.resolved_ocr_backend())
    except Exception:
        return "Not reported"


def _read_current_cursor() -> Point:
    """Read the current desktop cursor without starting an observer."""

    from pynput import mouse

    x, y = mouse.Controller().position
    return Point(float(x), float(y))


def _safe_message(error: BaseException) -> str:
    message = str(error).strip()
    if not message:
        return "The request parameters are invalid."
    return message[:512]


class _ForwardingTraceSink:
    """Forward explicitly enabled traces to the lab sink and protocol host."""

    def __init__(self, service: DesktopService, sink: RuntimeTraceSink) -> None:
        self._service = service
        self._sink = sink
        self.retain_evidence = getattr(sink, "retain_evidence", False) is True

    def emit(self, event: Mapping[str, object]) -> None:
        payload = _forwarded_trace_payload(event, retain_evidence=self.retain_evidence)
        self._sink.emit(payload)
        loop = self._service._loop
        if loop is None:
            return
        try:
            loop.post(lambda: self._service._emit_event("trace", payload))
        except Exception:
            return


def _is_trace_scalar(value: object) -> bool:
    return value is None or isinstance(value, (str, int, bool)) or (
        isinstance(value, float) and math.isfinite(value)
    )


def _forwarded_trace_payload(
    event: Mapping[str, object],
    *,
    retain_evidence: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    evidence_bytes = 0
    for key, value in event.items():
        if not isinstance(key, str):
            continue
        is_evidence = key.endswith("_evidence")
        if is_evidence and not retain_evidence:
            continue

        safe_value: Any = value
        if not _is_trace_scalar(value):
            if not (is_evidence and isinstance(value, Mapping)):
                continue
            safe_value = _json_safe_trace_value(value)
            if safe_value is _UNSAFE_TRACE_VALUE or not isinstance(safe_value, dict):
                continue
        if is_evidence:
            try:
                encoded_size = len(
                    json.dumps(
                        safe_value,
                        ensure_ascii=False,
                        allow_nan=False,
                        separators=(",", ":"),
                    ).encode("utf-8")
                )
            except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
                continue
            if evidence_bytes + encoded_size > MAX_FRAME_BYTES // 2:
                continue
            evidence_bytes += encoded_size
        payload[key] = safe_value
    return payload


def _json_safe_trace_value(value: object, depth: int = 0) -> Any:
    if depth > MAX_STRUCTURE_DEPTH:
        return _UNSAFE_TRACE_VALUE
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else _UNSAFE_TRACE_VALUE
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            return _UNSAFE_TRACE_VALUE
        result: dict[str, Any] = {}
        for key, item in value.items():
            safe_item = _json_safe_trace_value(item, depth + 1)
            if safe_item is _UNSAFE_TRACE_VALUE:
                return _UNSAFE_TRACE_VALUE
            result[key] = safe_item
        return result
    if isinstance(value, list):
        result_list: list[Any] = []
        for item in value:
            safe_item = _json_safe_trace_value(item, depth + 1)
            if safe_item is _UNSAFE_TRACE_VALUE:
                return _UNSAFE_TRACE_VALUE
            result_list.append(safe_item)
        return result_list
    return _UNSAFE_TRACE_VALUE
