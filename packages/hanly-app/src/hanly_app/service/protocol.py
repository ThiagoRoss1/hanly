"""Strict, bounded JSONL messages for the supervised desktop service."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, NoReturn

PROTOCOL_VERSION = 1
MAX_FRAME_BYTES = 1024 * 1024
MAX_PENDING_REQUESTS = 32
MAX_REQUEST_ID_LENGTH = 64
MAX_STRUCTURE_DEPTH = 32
MAX_ERROR_MESSAGE_LENGTH = 512
MAX_SEQUENCE = 9_007_199_254_740_991
MAX_SELECTION_SNAPSHOT_DIMENSION = 16_384
MAX_SELECTION_SNAPSHOT_PIXELS = 64_000_000
EVENT_NAMES = frozenset(
    {"state", "popup", "popup_hide", "service_status", "native_action", "trace"}
)

WINDOWS = frozenset({"host", "control-center", "popup", "region-selector"})


class ProtocolFailure(ValueError):
    """A request violates the wire contract; an ID is present when safe to echo."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message[:MAX_ERROR_MESSAGE_LENGTH]
        self.request_id = request_id


@dataclass(frozen=True, slots=True)
class Request:
    """A validated request delivered by the native host."""

    request_id: str
    method: str
    params: dict[str, Any]
    window: str


_METHOD_FIELDS: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    # Explicit methods supported by the supervised desktop service.
    "service.hello": (frozenset(), frozenset()),
    "service.shutdown": (frozenset(), frozenset()),
    "settings.prepare": (frozenset({"changes"}), frozenset()),
    "settings.commit": (frozenset({"token"}), frozenset()),
    "settings.abort": (frozenset({"token"}), frozenset()),
    "native.input": (frozenset({"action", "edge"}), frozenset()),
    "native.context": (
        frozenset({"cursor", "monitors"}),
        frozenset({"popup_rect", "registered_hotkeys", "vision_available"}),
    ),
    "native.selection": (frozenset({"active"}), frozenset()),
    "native.selection_snapshot": (frozenset({"bounds"}), frozenset()),
    "native.region_selected": (frozenset({"region"}), frozenset()),
    "service.popup_geometry": (
        frozenset({"sequence", "x", "y", "width", "height"}),
        frozenset(),
    ),
    "service.popup_close": (frozenset({"sequence"}), frozenset()),
    "service.popup_expand": (
        frozenset({"sequence", "expanded"}),
        frozenset(),
    ),
    "update.acknowledge": (
        frozenset(),
        frozenset({"legacy_ready_path", "challenge_path"}),
    ),
    "self_check": (frozenset({"mode"}), frozenset({"image"})),
    "get_state": (frozenset(), frozenset()),
    "update_settings": (frozenset({"changes"}), frozenset()),
    "get_logs": (frozenset(), frozenset()),
    # ControlCenterBridge actions retained as explicit, currently unavailable
    # contracts until their corresponding desktop owners are ported.
    "start_capture": (frozenset(), frozenset()),
    "stop_capture": (frozenset(), frozenset()),
    "set_capture_mode": (frozenset({"mode"}), frozenset()),
    "set_target": (frozenset({"target"}), frozenset()),
    "set_region": (frozenset({"region"}), frozenset()),
    "select_capture_area": (frozenset(), frozenset()),
    "set_hover_delay": (frozenset({"delay_ms"}), frozenset()),
    "set_hotkey": (frozenset({"hotkey"}), frozenset()),
    "grant_permission": (frozenset({"permission"}), frozenset()),
    "refresh_permissions": (frozenset(), frozenset()),
    "retry_runtime": (frozenset(), frozenset()),
    "quit": (frozenset(), frozenset()),
    "check_for_updates": (frozenset(), frozenset()),
    "install_update": (frozenset(), frozenset({"resource_id"})),
    "install_application_update": (frozenset(), frozenset({"confirm_full"})),
    "cancel_update": (frozenset(), frozenset()),
    "open_release_notes": (frozenset(), frozenset()),
    "clear_logs": (frozenset(), frozenset()),
    "export_diagnostics": (frozenset(), frozenset()),
}

_METHOD_WINDOWS: dict[str, frozenset[str]] = {
    "service.hello": frozenset({"host"}),
    "service.shutdown": frozenset({"host"}),
    "settings.prepare": frozenset({"control-center"}),
    "settings.commit": frozenset({"control-center"}),
    "settings.abort": frozenset({"control-center"}),
    "native.input": frozenset({"host"}),
    "native.context": frozenset({"host"}),
    "native.selection": frozenset({"host"}),
    "native.selection_snapshot": frozenset({"host"}),
    "native.region_selected": frozenset({"host"}),
    "service.popup_geometry": frozenset({"popup"}),
    "service.popup_close": frozenset({"popup"}),
    "service.popup_expand": frozenset({"popup"}),
    "update.acknowledge": frozenset({"host"}),
    "self_check": frozenset({"host"}),
    "get_state": frozenset({"control-center"}),
    "update_settings": frozenset({"control-center"}),
    "get_logs": frozenset({"control-center"}),
    "set_region": frozenset({"control-center", "region-selector"}),
}
_DEFAULT_CONTROL_CENTER_WINDOWS = frozenset({"control-center"})


def parse_request(frame: bytes) -> Request:
    """Decode and validate one JSONL request, rejecting ambiguous JSON."""

    if not isinstance(frame, bytes):
        raise TypeError("frame must be bytes")
    if len(frame) > MAX_FRAME_BYTES:
        raise ProtocolFailure("frame_too_large", "Request frame exceeds 1 MiB.")
    if frame.endswith(b"\r"):
        frame = frame[:-1]
    try:
        source = frame.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise ProtocolFailure("invalid_json", "Request frame is not valid UTF-8.") from error

    _check_depth(source)
    try:
        value = json.loads(
            source,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_non_finite,
        )
    except ProtocolFailure:
        raise
    except (json.JSONDecodeError, RecursionError, ValueError) as error:
        raise ProtocolFailure("invalid_json", "Request frame is not valid JSON.") from error

    if not isinstance(value, dict):
        raise ProtocolFailure("invalid_request", "Request must be a JSON object.")

    request_id = value.get("id")
    if not isinstance(request_id, str) or not _valid_request_id(request_id):
        raise ProtocolFailure(
            "invalid_request",
            "Request ID must be 1–64 printable ASCII characters.",
        )

    expected_fields = {"version", "type", "id", "method", "params", "window"}
    if set(value) != expected_fields:
        raise ProtocolFailure(
            "invalid_request",
            "Request has missing or unknown fields.",
            request_id=request_id,
        )
    if type(value["version"]) is not int or value["version"] != PROTOCOL_VERSION:
        raise ProtocolFailure(
            "unsupported_version",
            "Request protocol version is unsupported.",
            request_id=request_id,
        )
    if value["type"] != "request":
        raise ProtocolFailure(
            "invalid_request",
            "Frame type must be request.",
            request_id=request_id,
        )
    method = value["method"]
    if not isinstance(method, str) or not method or not method.isascii():
        raise ProtocolFailure(
            "invalid_request",
            "Request method must be a non-empty ASCII string.",
            request_id=request_id,
        )
    window = value["window"]
    if not isinstance(window, str) or window not in WINDOWS:
        raise ProtocolFailure(
            "invalid_request",
            "Request window is unsupported.",
            request_id=request_id,
        )
    params = value["params"]
    if not isinstance(params, dict):
        raise ProtocolFailure(
            "invalid_request",
            "Request params must be a JSON object.",
            request_id=request_id,
        )

    _validate_method_params(method, params, request_id)
    if method in _METHOD_FIELDS and window not in allowed_windows(method):
        raise ProtocolFailure(
            "unauthorized",
            "Request window is not authorized for this method.",
            request_id=request_id,
        )
    return Request(request_id, method, params, window)


def validate_event(value: object) -> dict[str, Any]:
    """Validate a versioned event frame for future service-to-host events."""

    if not isinstance(value, dict):
        raise ProtocolFailure("invalid_event", "Event must be a JSON object.")
    if set(value) != {"version", "type", "sequence", "event", "payload"}:
        raise ProtocolFailure("invalid_event", "Event has missing or unknown fields.")
    if type(value["version"]) is not int or value["version"] != PROTOCOL_VERSION:
        raise ProtocolFailure("unsupported_version", "Event protocol version is unsupported.")
    sequence = value["sequence"]
    if type(sequence) is not int or not 0 < sequence <= MAX_SEQUENCE:
        raise ProtocolFailure("invalid_event", "Event sequence must be a positive integer.")
    if value["type"] != "event":
        raise ProtocolFailure("invalid_event", "Frame type must be event.")
    if not isinstance(value["event"], str) or not value["event"] or not value["event"].isascii():
        raise ProtocolFailure("invalid_event", "Event name must be a non-empty ASCII string.")
    if value["event"] not in EVENT_NAMES:
        raise ProtocolFailure("invalid_event", "Event name is not supported.")
    if not isinstance(value["payload"], dict):
        raise ProtocolFailure("invalid_event", "Event payload must be a JSON object.")
    if value["event"] == "native_action":
        payload = value["payload"]
        if (
            set(payload) != {"action"}
            or not isinstance(payload["action"], str)
            or payload["action"] not in {"restart_required", "quit"}
        ):
            raise ProtocolFailure("invalid_event", "Native action payload is unsupported.")
    return value


def encode_reply(
    request_id: str,
    *,
    result: Mapping[str, Any] | None = None,
    error: Mapping[str, str] | None = None,
) -> bytes:
    """Encode exactly one correlated success or error reply."""

    if not _valid_request_id(request_id):
        raise ValueError("reply ID must be 1–64 printable ASCII characters")
    if (result is None) == (error is None):
        raise ValueError("reply must contain exactly one of result or error")
    if result is not None and not isinstance(result, Mapping):
        raise TypeError("reply result must be an object")
    if error is not None:
        if set(error) != {"code", "message"}:
            raise ValueError("reply error must contain code and message")
        if not all(isinstance(error[key], str) for key in ("code", "message")):
            raise TypeError("reply error code and message must be strings")
        if len(error["message"]) > MAX_ERROR_MESSAGE_LENGTH:
            raise ValueError("reply error message exceeds its bound")

    envelope: dict[str, Any] = {
        "version": PROTOCOL_VERSION,
        "type": "reply",
        "id": request_id,
    }
    if result is not None:
        envelope["result"] = dict(result)
    else:
        envelope["error"] = dict(error or {})
    return _encode_frame(envelope)


def encode_event(sequence: int, event: str, payload: Mapping[str, Any]) -> bytes:
    """Encode one strictly validated service-to-host event."""

    value = {
        "version": PROTOCOL_VERSION,
        "type": "event",
        "sequence": sequence,
        "event": event,
        "payload": dict(payload),
    }
    validate_event(value)
    return _encode_frame(value)


def _encode_frame(value: Mapping[str, Any]) -> bytes:
    try:
        frame = (
            json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as error:
        raise ValueError("message contains a value outside the JSON contract") from error
    if len(frame) - 1 > MAX_FRAME_BYTES:
        raise ValueError("encoded frame exceeds 1 MiB")
    try:
        _check_depth(frame[:-1].decode("utf-8"))
    except ProtocolFailure as error:
        raise ValueError("encoded frame exceeds the structure depth limit") from error
    return frame


def _validate_method_params(
    method: str,
    params: dict[str, Any],
    request_id: str,
) -> None:
    spec = _METHOD_FIELDS.get(method)
    if spec is None:
        # Unknown method is an application-level error and therefore remains
        # correlated to the valid request ID.
        return
    required, optional = spec
    keys = set(params)
    if not required <= keys or keys - required - optional:
        raise ProtocolFailure(
            "invalid_params",
            "Method params have missing or unknown fields.",
            request_id=request_id,
        )
    _validate_param_values(method, params, request_id)


def allowed_windows(method: str) -> frozenset[str]:
    """Return the host-derived window identities allowed to call a method."""

    return _METHOD_WINDOWS.get(method, _DEFAULT_CONTROL_CENTER_WINDOWS)


def known_method(method: str) -> bool:
    """Whether a method belongs to the desktop-service public contract."""

    return method in _METHOD_FIELDS


def _valid_request_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= MAX_REQUEST_ID_LENGTH
        and value.isascii()
        and all(char.isalnum() or char in "-._:" for char in value)
    )


def _validate_param_values(
    method: str,
    params: dict[str, Any],
    request_id: str,
) -> None:
    def fail(message: str) -> NoReturn:
        raise ProtocolFailure("invalid_params", message, request_id=request_id)

    string_params = {
        "set_capture_mode": ("mode", 32),
        "set_hotkey": ("hotkey", 128),
        "grant_permission": ("permission", 64),
    }
    if method in string_params:
        key, maximum = string_params[method]
        if key in params and not isinstance(params[key], str):
            fail(f"{key} must be a string.")
        if key in params and (not params[key] or len(params[key]) > maximum):
            fail(f"{key} must be a non-empty string within its length bound.")
    if "resource_id" in params and params["resource_id"] is not None:
        if (
            not isinstance(params["resource_id"], str)
            or not params["resource_id"]
            or len(params["resource_id"]) > 64
        ):
            fail("resource_id must be a string or null.")
    if method == "set_target":
        target = params["target"]
        if isinstance(target, bool) or not isinstance(target, (str, int)):
            fail("target must be a string or integer.")
        if isinstance(target, int) and not 1 <= target <= 100_000:
            fail("target monitor index must be positive.")
    if method == "set_region":
        region = params["region"]
        if region is not None and not isinstance(region, dict):
            fail("region must be an object or null.")
        if isinstance(region, dict):
            expected = {"left", "top", "width", "height"}
            if set(region) != expected or any(
                type(region[key]) is not int for key in expected
            ):
                fail("region must contain integer left, top, width, and height fields.")
            if not -100_000 <= region["left"] <= 100_000:
                fail("region left is outside the supported bounds.")
            if not -100_000 <= region["top"] <= 100_000:
                fail("region top is outside the supported bounds.")
            if not 1 <= region["width"] <= 100_000:
                fail("region width is outside the supported bounds.")
            if not 1 <= region["height"] <= 100_000:
                fail("region height is outside the supported bounds.")
    if method == "set_hover_delay":
        if type(params["delay_ms"]) is not int:
            fail("delay_ms must be an integer.")
        if not 20 <= params["delay_ms"] <= 2000:
            fail("delay_ms must be between 20 and 2000.")
    if method == "set_capture_mode" and params["mode"] not in {
        "full_monitor",
        "region",
    }:
        fail("mode must be full_monitor or region.")
    if method == "set_target":
        target = params["target"]
        if isinstance(target, str) and target != "cursor":
            prefix, separator, index = target.partition(":")
            if (
                prefix != "monitor"
                or not separator
                or not index.isdigit()
                or len(index) > 6
                or int(index) < 1
            ):
                fail("target must be cursor or a monitor index.")
    if method == "update_settings":
        changes = params["changes"]
        if not isinstance(changes, dict):
            fail("changes must be an object.")
        supported = {
            "hotkey",
            "hover_hotkey",
            "capture_hotkey",
            "hover_activation",
            "lookup_preload",
            "ocr_backend",
            "hover_delay_ms",
            "capture_mode",
            "theme",
            "popup_enabled",
            "popup_default_size",
            "technical_details",
            "update_checks_enabled",
        }
        if set(changes) - supported:
            fail("changes contains an unsupported setting.")
        if "capture_region" in changes:
            fail("capture_region cannot be changed by update_settings.")
        string_fields = {
            "hotkey",
            "hover_hotkey",
            "capture_hotkey",
            "hover_activation",
            "lookup_preload",
            "ocr_backend",
            "capture_mode",
            "theme",
            "popup_default_size",
            "technical_details",
        }
        for key in string_fields.intersection(changes):
            if not isinstance(changes[key], str) or len(changes[key]) > 128:
                fail(f"{key} must be a string within its length bound.")
        for key in {"popup_enabled", "update_checks_enabled"}.intersection(changes):
            if type(changes[key]) is not bool:
                fail(f"{key} must be a boolean.")
        if "hover_delay_ms" in changes and type(changes["hover_delay_ms"]) is not int:
            fail("hover_delay_ms must be an integer.")
    if method == "install_application_update" and "confirm_full" in params:
        if type(params["confirm_full"]) is not bool:
            fail("confirm_full must be a boolean.")
    if method in {"settings.prepare"}:
        changes = params["changes"]
        if not isinstance(changes, dict):
            fail("changes must be an object.")
        _validate_settings_changes(changes, fail)
    if method in {"settings.commit", "settings.abort"}:
        token = params["token"]
        if not isinstance(token, str) or not 1 <= len(token) <= 64 or not token.isascii():
            fail("token must be a non-empty ASCII string within its length bound.")
    if method == "native.input":
        if not isinstance(params["action"], str) or params["action"] not in {
            "push_to_hover",
            "toggle_hover",
            "toggle_capture",
        }:
            fail("action is not a supported native hotkey action.")
        if not isinstance(params["edge"], str) or params["edge"] not in {
            "pressed",
            "released",
        }:
            fail("edge must be pressed or released.")
    if method == "native.context":
        cursor = params["cursor"]
        if not isinstance(cursor, dict) or set(cursor) != {"x", "y"}:
            fail("cursor must contain x and y coordinates.")
        for coordinate in cursor.values():
            if not _bounded_coordinate(coordinate):
                fail("cursor coordinates are outside the supported bounds.")
        monitors = params["monitors"]
        if not isinstance(monitors, list) or len(monitors) > 32:
            fail("monitors must be a list containing at most 32 displays.")
        for monitor in monitors:
            _validate_monitor(monitor, fail)
        if "popup_rect" in params:
            _validate_rect(params["popup_rect"], fail, "popup_rect")
        if "registered_hotkeys" in params:
            _validate_registered_hotkeys(params["registered_hotkeys"], fail)
        if "vision_available" in params and type(params["vision_available"]) is not bool:
            fail("vision_available must be a boolean.")
    if method == "native.selection" and type(params["active"]) is not bool:
        fail("active must be a boolean.")
    if method == "native.selection_snapshot":
        bounds = params["bounds"]
        _validate_rect(bounds, fail, "bounds")
        width, height = bounds["width"], bounds["height"]
        left, top = bounds["left"], bounds["top"]
        if (
            width > MAX_SELECTION_SNAPSHOT_DIMENSION
            or height > MAX_SELECTION_SNAPSHOT_DIMENSION
            or width * height > MAX_SELECTION_SNAPSHOT_PIXELS
        ):
            fail("snapshot bounds exceed the supported pixel limits.")
        if (
            not -100_000 <= left + width <= 100_000
            or not -100_000 <= top + height <= 100_000
        ):
            fail("snapshot bounds extend outside the supported coordinates.")
    if method == "native.region_selected":
        region = params["region"]
        if not isinstance(region, dict):
            fail("region must be an object.")
        _validate_rect(region, fail, "region")
    if method.startswith("service.popup_"):
        if type(params["sequence"]) is not int or not 0 < params["sequence"] <= MAX_SEQUENCE:
            fail("sequence must be a positive popup sequence.")
        if method == "service.popup_geometry":
            if not _bounded_coordinate(params["x"]) or not _bounded_coordinate(params["y"]):
                fail("popup position is outside the supported bounds.")
            for key in ("width", "height"):
                if type(params[key]) is not int or not 1 <= params[key] <= 1000:
                    fail(f"popup {key} must be between 1 and 1000.")
        if method == "service.popup_expand" and type(params["expanded"]) is not bool:
            fail("expanded must be a boolean.")
    if method == "update.acknowledge":
        paths = {
            key: params[key]
            for key in ("legacy_ready_path", "challenge_path")
            if key in params
        }
        if len(paths) != 1:
            fail("exactly one update handoff path must be provided.")
        selected = next(iter(paths.values()))
        if not isinstance(selected, str) or not 1 <= len(selected) <= 4096:
            fail("update handoff path must be a bounded absolute path.")
        if not selected.startswith("/") and not (
            len(selected) >= 3 and selected[1:3] in {":\\", ":/"}
        ):
            fail("update handoff path must be absolute.")
    if method == "self_check":
        if not isinstance(params["mode"], str) or params["mode"] not in {
            "inventory",
            "ocr",
            "worker",
            "ui",
        }:
            fail("mode is not a supported self-check mode.")
        image = params.get("image")
        if image is not None:
            if not isinstance(image, str) or not 1 <= len(image) <= 4096:
                fail("image must be a bounded absolute path.")
            if not image.startswith("/") and not (
                len(image) >= 3 and image[1:3] in {":\\", ":/"}
            ):
                fail("image must be an absolute path.")


def _validate_settings_changes(changes: dict[str, Any], fail: Any) -> None:
    supported = {
        "hotkey",
        "hover_hotkey",
        "capture_hotkey",
        "hover_activation",
        "lookup_preload",
        "ocr_backend",
        "hover_delay_ms",
        "capture_mode",
        "theme",
        "popup_enabled",
        "popup_default_size",
        "technical_details",
        "update_checks_enabled",
    }
    if set(changes) - supported:
        fail("changes contains an unsupported setting.")
    string_fields = {
        "hotkey",
        "hover_hotkey",
        "capture_hotkey",
        "hover_activation",
        "lookup_preload",
        "ocr_backend",
        "capture_mode",
        "theme",
        "popup_default_size",
        "technical_details",
    }
    for key in string_fields.intersection(changes):
        if not isinstance(changes[key], str) or len(changes[key]) > 128:
            fail(f"{key} must be a string within its length bound.")
    for key in {"popup_enabled", "update_checks_enabled"}.intersection(changes):
        if type(changes[key]) is not bool:
            fail(f"{key} must be a boolean.")
    if "hover_delay_ms" in changes and type(changes["hover_delay_ms"]) is not int:
        fail("hover_delay_ms must be an integer.")


def _validate_monitor(
    monitor: object,
    fail: Callable[[str], NoReturn],
) -> None:
    if not isinstance(monitor, dict) or set(monitor) != {"index", "name", "bounds"}:
        fail("each monitor must contain index, name, and bounds.")
    if type(monitor["index"]) is not int or not 1 <= monitor["index"] <= 100_000:
        fail("monitor index is outside the supported bounds.")
    if not isinstance(monitor["name"], str) or len(monitor["name"]) > 128:
        fail("monitor name must be a string within its length bound.")
    _validate_rect(monitor["bounds"], fail, "monitor bounds")


def _validate_rect(
    value: object,
    fail: Callable[[str], NoReturn],
    name: str,
) -> None:
    if not isinstance(value, dict) or set(value) != {"left", "top", "width", "height"}:
        fail(f"{name} must contain left, top, width, and height.")
    if type(value["left"]) is not int or not -100_000 <= value["left"] <= 100_000:
        fail(f"{name} left is outside the supported bounds.")
    if type(value["top"]) is not int or not -100_000 <= value["top"] <= 100_000:
        fail(f"{name} top is outside the supported bounds.")
    for key in ("width", "height"):
        if type(value[key]) is not int or not 1 <= value[key] <= 100_000:
            fail(f"{name} {key} is outside the supported bounds.")


def _validate_registered_hotkeys(
    value: object,
    fail: Callable[[str], NoReturn],
) -> None:
    allowed = {"push_to_hover", "toggle_hover", "toggle_capture"}
    if not isinstance(value, dict) or set(value) - allowed:
        fail("registered_hotkeys has unsupported actions.")
    if any(not isinstance(binding, str) or len(binding) > 128 for binding in value.values()):
        fail("registered hotkey bindings must be bounded strings.")


def _bounded_coordinate(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and abs(value) <= 100_000
        and value == value
        and abs(value) != float("inf")
    )


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolFailure("duplicate_key", "JSON object contains a duplicate key.")
        result[key] = value
    return result


def _reject_non_finite(value: str) -> None:
    raise ProtocolFailure("invalid_json", "JSON numbers must be finite.")


def _check_depth(source: str) -> None:
    depth = 0
    quoted = False
    escaped = False
    for character in source:
        if quoted:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
            continue
        if character == '"':
            quoted = True
        elif character in "[{":
            depth += 1
            if depth > MAX_STRUCTURE_DEPTH:
                raise ProtocolFailure(
                    "structure_too_deep",
                    "JSON structure exceeds the maximum depth.",
                )
        elif character in "]}":
            depth -= 1
