from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from hanly_app.service import (
    MAX_FRAME_BYTES,
    MAX_PENDING_REQUESTS,
    MAX_STRUCTURE_DEPTH,
    DesktopService,
    ProtocolFailure,
    Request,
    ServiceError,
    encode_event,
    parse_request,
    validate_event,
)

ROOT = Path(__file__).resolve().parents[1]


def _message(
    *,
    method: str = "service.hello",
    params: dict[str, Any] | None = None,
    window: str = "host",
    request_id: str = "request-1",
) -> dict[str, Any]:
    return {
        "version": 1,
        "type": "request",
        "id": request_id,
        "method": method,
        "params": {} if params is None else params,
        "window": window,
    }


def _frame(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")


def _python_env() -> dict[str, str]:
    env = os.environ.copy()
    package_paths = [
        str(ROOT / "packages" / "hanly-app" / "src"),
        str(ROOT / "packages" / "hanly" / "src"),
    ]
    existing = env.get("PYTHONPATH")
    if existing:
        package_paths.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(package_paths)
    return env


def test_request_schema_is_strict_and_correlates_safe_errors() -> None:
    message = _message(
        method="update_settings",
        params={"changes": {"theme": "dark"}},
        window="control-center",
    )
    parsed = parse_request(_frame(message))
    assert parsed == Request(
        request_id="request-1",
        method="update_settings",
        params={"changes": {"theme": "dark"}},
        window="control-center",
    )

    with_extra_field = {**message, "extra": True}
    with pytest.raises(ProtocolFailure) as error:
        parse_request(_frame(with_extra_field))
    assert error.value.code == "invalid_request"
    assert error.value.request_id == "request-1"

    with pytest.raises(ProtocolFailure) as error:
        parse_request(_frame(_message(request_id="x" * 65)))
    assert error.value.request_id is None


@pytest.mark.parametrize(
    ("frame", "code"),
    [
        (b'{"x":1,"x":2}', "duplicate_key"),
        (b'{"x":NaN}', "invalid_json"),
        (b"x" * (MAX_FRAME_BYTES + 1), "frame_too_large"),
    ],
)
def test_protocol_rejects_ambiguous_nonfinite_and_oversized_frames(
    frame: bytes,
    code: str,
) -> None:
    with pytest.raises(ProtocolFailure) as error:
        parse_request(frame)
    assert error.value.code == code
    assert error.value.request_id is None


def test_protocol_rejects_deep_structures_and_unknown_methods() -> None:
    nested: Any = None
    for _ in range(MAX_STRUCTURE_DEPTH + 2):
        nested = {"value": nested}
    deeply_nested = _message(
        method="update_settings",
        params={"changes": nested},
        window="control-center",
    )
    with pytest.raises(ProtocolFailure, match="maximum depth"):
        parse_request(_frame(deeply_nested))

    request = parse_request(_frame(_message(method="not.a.method")))
    assert request.method == "not.a.method"


def test_window_authorization_and_region_selector_contract() -> None:
    with pytest.raises(ProtocolFailure) as error:
        parse_request(_frame(_message(method="get_state", window="popup")))
    assert error.value.code == "unauthorized"
    assert error.value.request_id == "request-1"

    request = parse_request(
        _frame(
            _message(
                method="set_region",
                params={"region": {"left": 1, "top": 2, "width": 300, "height": 200}},
                window="region-selector",
            )
        )
    )
    assert request.window == "region-selector"


def test_event_contract_requires_positive_sequence_and_object_payload() -> None:
    frame = encode_event(1, "service_status", {"state": "running"})
    event = json.loads(frame)
    assert validate_event(event) == event
    assert MAX_PENDING_REQUESTS == 32

    event["sequence"] = 0
    with pytest.raises(ProtocolFailure, match="positive integer"):
        validate_event(event)


def test_service_smoke_reports_unready_state_persists_settings_and_rejects_capture(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text('{"capture_monitor":2}', encoding="utf-8")
    service = DesktopService(config_path)

    hello = service.dispatch(parse_request(_frame(_message())))
    assert hello["runtime_ready"] is False
    assert hello["providers_loaded"] is False

    state = service.dispatch(
        parse_request(_frame(_message(method="get_state", window="control-center")))
    )
    assert state["runtime"]["status"]["phase"] == "idle"
    assert state["app"]["capture_running"] is False
    assert state["runtime"]["ocr_provider"] is None
    expected_backends = (
        ["auto", "vision", "easyocr"]
        if sys.platform == "darwin"
        else ["auto", "easyocr"]
    )
    assert state["runtime"]["ocr_backends"] == expected_backends
    assert state["runtime"]["hover_delay_bounds"] == {"min": 20, "max": 2000}
    assert state["app"]["target"] == "monitor:2"

    updated = service.dispatch(
        parse_request(
            _frame(
                _message(
                    method="update_settings",
                    params={"changes": {"theme": "dark"}},
                    window="control-center",
                )
            )
        )
    )
    assert updated["config"]["theme"] == "dark"
    assert json.loads(config_path.read_text(encoding="utf-8"))["theme"] == "dark"

    with pytest.raises(ServiceError) as error:
        service.dispatch(
            parse_request(
                _frame(_message(method="start_capture", window="control-center"))
            )
        )
    assert getattr(error.value, "code", None) == "unavailable"


def test_service_process_uses_protocol_only_on_stdout_and_shuts_down_cleanly(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "service-config.json"
    messages = [
        _message(request_id="hello"),
        _message(method="get_state", window="control-center", request_id="state"),
        _message(
            method="update_settings",
            params={"changes": {"theme": "dark"}},
            window="control-center",
            request_id="settings",
        ),
        _message(method="service.shutdown", request_id="shutdown"),
    ]
    input_bytes = b"".join(_frame(message) + b"\n" for message in messages)
    completed = subprocess.run(
        [sys.executable, "-m", "hanly_app.service", "--app-config", str(config_path)],
        input=input_bytes,
        capture_output=True,
        cwd=ROOT,
        env=_python_env(),
        timeout=15,
        check=False,
    )

    assert completed.returncode == 0
    assert completed.stderr == b""
    replies = [json.loads(line) for line in completed.stdout.splitlines()]
    assert [reply["id"] for reply in replies] == ["hello", "state", "settings", "shutdown"]
    assert all(reply["version"] == 1 and reply["type"] == "reply" for reply in replies)
    assert replies[0]["result"]["providers_loaded"] is False
    assert replies[1]["result"]["runtime"]["status"]["phase"] == "idle"
    assert replies[2]["result"]["config"]["theme"] == "dark"
    assert replies[3]["result"] == {"accepted": True}


def test_service_import_and_hello_do_not_load_qt_or_provider_runtime() -> None:
    script = """
import sys
import tempfile
from pathlib import Path
from hanly_app.service import DesktopService, Request
with tempfile.TemporaryDirectory() as directory:
    service = DesktopService(Path(directory) / 'settings.json')
    assert service.dispatch(Request('h', 'service.hello', {}, 'host'))['providers_loaded'] is False
for prefix in ('PyQt6', 'PySide6', 'webview', 'easyocr', 'torch', 'kiwipiepy'):
    assert not any(name == prefix or name.startswith(prefix + '.') for name in sys.modules), prefix
for name in (
    'hanly_app.control_center.bridge',
    'hanly.easyocr_provider',
    'hanly.kiwi_provider',
    'hanly.krdict_provider',
    'hanly.vision_provider',
):
    assert name not in sys.modules, name
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        cwd=ROOT,
        env=_python_env(),
        timeout=15,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")


def test_service_clean_eof_and_uncorrelated_malformed_frame(tmp_path: Path) -> None:
    command = [
        sys.executable,
        "-m",
        "hanly_app.service",
        "--app-config",
        str(tmp_path / "settings.json"),
    ]
    clean = subprocess.run(
        command,
        input=b"",
        capture_output=True,
        cwd=ROOT,
        env=_python_env(),
        timeout=15,
        check=False,
    )
    assert clean.returncode == 0
    assert clean.stdout == b""
    assert clean.stderr == b""

    malformed = subprocess.run(
        command,
        input=b'{"version":1,"version":1}\n',
        capture_output=True,
        cwd=ROOT,
        env=_python_env(),
        timeout=15,
        check=False,
    )
    assert malformed.returncode == 2
    assert malformed.stdout == b""
    assert malformed.stderr == b"hanly-service: duplicate_key\n"
