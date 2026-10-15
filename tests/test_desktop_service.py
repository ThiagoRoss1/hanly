from __future__ import annotations

import base64
import json
import os
import random
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, cast

import pytest
from hanly import DictionaryEntry, LookupResult, LookupStatus, Point
from hanly_app import permissions as permissions_module
from hanly_app import service as service_module
from hanly_app.acquisition.capture import (
    BackendCapture,
    BackendMonitor,
    CaptureService,
    ScreenRect,
)
from hanly_app.config import AppConfig, LookupPreload, OCRBackend
from hanly_app.lookup.controller import LookupController
from hanly_app.service import (
    MAX_FRAME_BYTES,
    MAX_PENDING_REQUESTS,
    MAX_STRUCTURE_DEPTH,
    DesktopService,
    ProtocolFailure,
    Request,
    ServiceError,
    encode_event,
    encode_reply,
    parse_request,
    validate_event,
)
from hanly_app.service import snapshot as snapshot_module
from hanly_app.service.event_loop import SerializedEventLoop
from hanly_app.service.snapshot import MAX_JPEG_BYTES, _encode_jpeg

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("coordinates", "expected"),
    [
        ((-40.5, -3.25, 380, 180), ScreenRect(-41, -4, 381, 181)),
        ((40.0, 30.0, 380, 180), ScreenRect(40, 30, 380, 180)),
    ],
)
def test_popup_geometry_encloses_fractional_native_positions_without_accepting_stale_updates(
    tmp_path: Path, coordinates: tuple[float, float, int, int], expected: ScreenRect,
) -> None:
    service = DesktopService(tmp_path / "config.json")
    service._popup_sequence = 7
    x, y, width, height = coordinates
    params = {"sequence": 7, "x": x, "y": y, "width": width, "height": height}
    try:
        request = parse_request(_frame(_message(
            method="service.popup_geometry", window="popup", params=params,
        )))
        assert service.dispatch(request) == {"accepted": True}
        assert service._popup_actual_rect == expected

        stale = parse_request(_frame(_message(
            method="service.popup_geometry", window="popup", params={**params, "sequence": 6},
        )))
        assert service.dispatch(stale) == {"accepted": False, "stale": True}
        assert service._popup_actual_rect == expected
    finally:
        service.close()


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


def test_popup_presentation_waits_for_rendered_geometry_and_keeps_result_identity(
    tmp_path: Path,
) -> None:
    events: list[dict[str, object]] = []

    class TraceSink:
        def emit(self, event: object) -> None:
            assert isinstance(event, dict)
            events.append(dict(event))

    service = DesktopService(tmp_path / "config.json", trace_sink=TraceSink())
    controller = SimpleNamespace(current_request_id=9)
    service._manual = SimpleNamespace(
        controller=controller,
        word_rect=lambda _result, _request: ScreenRect(20, 30, 40, 20),
        update_popup_geometry=lambda _rect: None,
        hover_runtime=None,
    )
    service._cursor = Point(30, 40)
    service._monitors = [{"bounds": {"left": 0, "top": 0, "width": 1000, "height": 800}}]
    result = LookupResult(
        status=LookupStatus.SUCCESS,
        entries=(DictionaryEntry(headword="학교", definitions=("school",)),),
    )

    def geometry(sequence: int) -> dict[str, Any]:
        return service.dispatch(parse_request(_frame(_message(
            method="service.popup_geometry", window="popup",
            params={"sequence": sequence, "x": 20.5, "y": 54.5, "width": 340, "height": 200},
        ))))

    try:
        published: list[tuple[str, dict[str, Any]]] = []
        service.set_event_sink(lambda name, payload: published.append((name, dict(payload))))
        service._show_popup(result, 9)
        assert published[-1][1]["replacement"] is True
        original_position = published[-1][1]["position"]
        # The word spans y 30-50; the native host places measured cards beside it.
        assert published[-1][1]["band"] == {"top": 24, "bottom": 56}
        assert events == []
        assert geometry(1) == {"accepted": True}
        assert [(event["event_kind"], event["lookup_request_id"]) for event in events] == [
            ("popup_visible", 9),
        ]
        assert events[0]["result_status"] == "SUCCESS"
        assert "학교" not in json.dumps(events)

        geometry(1)
        service._cursor = Point(600, 600)
        service._popup_sync("service.popup_expand", {"sequence": 1, "expanded": True})
        assert published[-1][1]["replacement"] is False
        assert published[-1][1]["position"] == original_position
        assert published[-1][1]["band"] == {"top": 24, "bottom": 56}
        assert service._popup_sequence == 2
        assert geometry(1) == {"accepted": False, "stale": True}
        geometry(2)
        assert len(events) == 1

        controller.current_request_id = 10
        service._show_popup(result, 10)
        controller.current_request_id = 11
        geometry(3)
        assert len(events) == 1

        service._hide_popup(3)
        geometry(3)
        assert len(events) == 1
        assert service._popup_request_id is None
    finally:
        service._manual = None
        service.close()


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

    invalid_context = _message(
        method="native.context",
        params={
            "cursor": {"x": 10, "y": 20},
            "monitors": [],
            "vision_available": "yes",
        },
    )
    with pytest.raises(ProtocolFailure) as error:
        parse_request(_frame(invalid_context))
    assert error.value.code == "invalid_params"
    assert error.value.request_id == "request-1"


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


@pytest.mark.parametrize(
    ("method", "params"),
    [
        ("native.input", {"action": [], "edge": "pressed"}),
        ("native.input", {"action": "toggle_hover", "edge": {}}),
        ("self_check", {"mode": []}),
    ],
)
def test_unhashable_enum_values_are_correlated_protocol_errors(
    method: str,
    params: dict[str, Any],
) -> None:
    with pytest.raises(ProtocolFailure) as error:
        parse_request(_frame(_message(method=method, params=params)))
    assert error.value.code == "invalid_params"
    assert error.value.request_id == "request-1"


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


def test_selection_snapshot_is_host_only_and_has_strict_pixel_bounds() -> None:
    request = _message(
        method="native.selection_snapshot",
        params={"bounds": {"left": -1200, "top": 0, "width": 1200, "height": 800}},
    )
    assert parse_request(_frame(request)).method == "native.selection_snapshot"

    for window in ("control-center", "popup", "region-selector"):
        with pytest.raises(ProtocolFailure) as error:
            parse_request(_frame({**request, "window": window}))
        assert error.value.code == "unauthorized"

    for width, height in ((16_385, 1), (9_000, 9_000)):
        oversized = _message(
            method="native.selection_snapshot",
            params={"bounds": {"left": 0, "top": 0, "width": width, "height": height}},
        )
        with pytest.raises(ProtocolFailure) as error:
            parse_request(_frame(oversized))
        assert error.value.code == "invalid_params"


def test_event_contract_requires_positive_sequence_and_object_payload() -> None:
    frame = encode_event(1, "service_status", {"state": "running"})
    event = json.loads(frame)
    assert validate_event(event) == event
    assert MAX_PENDING_REQUESTS == 32

    event["sequence"] = 0
    with pytest.raises(ProtocolFailure, match="positive integer"):
        validate_event(event)

    trace = json.loads(encode_event(2, "trace", {"event_kind": "capture"}))
    assert validate_event(trace) == trace


def test_dispatch_queue_enforces_the_pending_request_limit() -> None:
    loop: SerializedEventLoop[int] = SerializedEventLoop()
    assert all(loop.enqueue_request(index) for index in range(MAX_PENDING_REQUESTS))
    assert not loop.enqueue_request(MAX_PENDING_REQUESTS)


def test_mouse_cursor_samples_coalesce_on_the_service_owner_loop(
    tmp_path: Path,
) -> None:
    loop: SerializedEventLoop[object] = SerializedEventLoop()
    service = DesktopService(tmp_path / "cursor-config.json", event_loop=loop)

    for coordinate in range(500):
        service._queue_cursor(Point(float(coordinate), float(coordinate)))

    assert len(loop._callbacks) == 1
    loop.close_input()
    assert loop.run(lambda _item: None)
    assert service._cursor == Point(499.0, 499.0)
    service.close()


def test_settings_prepare_is_not_persisted_until_commit(tmp_path: Path) -> None:
    config_path = tmp_path / "settings.json"
    service = DesktopService(config_path)
    prepare = parse_request(
        _frame(
            _message(
                method="settings.prepare",
                params={"changes": {"theme": "dark"}},
                window="control-center",
            )
        )
    )

    candidate = service.dispatch(prepare)
    assert candidate["settings"]["theme"] == "dark"
    assert service.config_manager.config.theme.value != "dark"
    assert not config_path.exists()

    committed = service.dispatch(
        parse_request(
            _frame(
                _message(
                    method="settings.commit",
                    params={"token": candidate["token"]},
                    window="control-center",
                )
            )
        )
    )
    assert committed["config"]["theme"] == "dark"
    assert json.loads(config_path.read_text(encoding="utf-8"))["theme"] == "dark"
    service.close()


def test_native_region_selection_is_host_only_and_commits_atomically(
    tmp_path: Path,
) -> None:
    service = DesktopService(tmp_path / "settings.json")
    with pytest.raises(ProtocolFailure) as error:
        parse_request(
            _frame(
                _message(
                    method="native.region_selected",
                    params={"region": {"left": 10, "top": 20, "width": 300, "height": 200}},
                    window="region-selector",
                )
            )
        )
    assert error.value.code == "unauthorized"

    service.dispatch(
        parse_request(
            _frame(
                _message(
                    method="native.selection",
                    params={"active": True},
                )
            )
        )
    )
    selected = service.dispatch(
        parse_request(
            _frame(
                _message(
                    method="native.region_selected",
                    params={"region": {"left": 10, "top": 20, "width": 300, "height": 200}},
                )
            )
        )
    )
    assert selected["config"]["capture_mode"] == "region"
    assert selected["config"]["capture_region"] == {
        "left": 10,
        "top": 20,
        "width": 300,
        "height": 200,
    }
    service.close()


def test_selection_backdrop_is_scoped_temporary_and_protocol_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    screen = ScreenRect(-320, 0, 320, 180)
    calls: list[ScreenRect] = []
    closed: list[bool] = []
    trace_events: list[object] = []

    class FakeBackend:
        def enumerate_monitors(self) -> tuple[BackendMonitor, ...]:
            return (BackendMonitor("Display 1", screen),)

        def grab(self, region: ScreenRect) -> BackendCapture:
            calls.append(region)
            return BackendCapture(
                region.width,
                region.height,
                bytes((80, 120, 160)) * region.width * region.height,
            )

        def close(self) -> None:
            closed.append(True)

    class TraceSink:
        def emit(self, event: object) -> None:
            trace_events.append(event)

    monkeypatch.setattr(snapshot_module, "MSSBackend", FakeBackend)
    service = DesktopService(
        tmp_path / "settings.json",
        trace_sink=TraceSink(),
    )
    events: list[tuple[str, object]] = []
    service.set_event_sink(lambda name, payload: events.append((name, dict(payload))))
    service.dispatch(
        parse_request(
            _frame(
                _message(
                    method="native.context",
                    params={
                        "cursor": {"x": -10, "y": 10},
                        "monitors": [
                            {
                                "index": 1,
                                "name": "Display 1",
                                "bounds": {
                                    "left": screen.left,
                                    "top": screen.top,
                                    "width": screen.width,
                                    "height": screen.height,
                                },
                            }
                        ],
                    },
                )
            )
        )
    )
    service._popup_sequence = 4
    service._popup_result = LookupResult(
        status=LookupStatus.SUCCESS,
        entries=(DictionaryEntry(headword="previous popup", definitions=("private",)),),
    )

    snapshot_request = parse_request(
        _frame(
            _message(
                method="native.selection_snapshot",
                params={
                    "bounds": {
                        "left": screen.left,
                        "top": screen.top,
                        "width": screen.width,
                        "height": screen.height,
                    }
                },
            )
        )
    )
    with pytest.raises(ServiceError) as error:
        service.dispatch(snapshot_request)
    assert error.value.code == "unauthorized"

    service.dispatch(
        parse_request(
            _frame(_message(method="native.selection", params={"active": True}))
        )
    )
    assert service._popup_result is None
    assert any(name == "popup_hide" for name, _payload in events)
    response = service.dispatch(snapshot_request)
    image_uri = response["image"]
    assert image_uri.startswith("data:image/jpeg;base64,")
    jpeg = base64.b64decode(image_uri.partition(",")[2], validate=True)
    assert len(jpeg) <= MAX_JPEG_BYTES
    assert len(encode_reply("snapshot", result=response)) <= MAX_FRAME_BYTES
    assert calls == [screen]
    assert closed == [True]

    from PIL import Image

    image = Image.open(BytesIO(jpeg))
    assert image.size == (screen.width, screen.height)
    image.close()
    log_path = service.log.path
    assert log_path is not None
    serialized_public_data = json.dumps(
        {
            "state": service._state(),
            "logs": service._logs(),
            "events": events,
            "trace": trace_events,
            "log_file": log_path.read_text(encoding="utf-8"),
        }
    )
    assert image_uri not in serialized_public_data
    assert "previous popup" not in serialized_public_data
    assert trace_events == []
    service.close()


def test_noisy_selection_snapshot_is_reduced_under_the_jpeg_byte_limit() -> None:
    width = height = 2048
    noise = random.Random(17).randbytes(width * height * 3)

    jpeg = _encode_jpeg(width, height, noise)
    assert len(jpeg) <= MAX_JPEG_BYTES


def test_trace_evidence_crosses_protocol_only_for_explicit_retention(
    tmp_path: Path,
) -> None:
    class ImmediateLoop:
        def post(self, callback: Callable[[], None]) -> None:
            callback()

    class TraceSink:
        def __init__(self, retain_evidence: bool) -> None:
            self.retain_evidence = retain_evidence
            self.events: list[object] = []

        def emit(self, event: object) -> None:
            self.events.append(event)

    for retain_evidence in (False, True):
        sink = TraceSink(retain_evidence)
        service = DesktopService(
            tmp_path / f"settings-{retain_evidence}.json",
            trace_sink=sink,
        )
        setattr(service, "_loop", ImmediateLoop())
        forwarded: list[tuple[str, dict[str, object]]] = []
        service.set_event_sink(
            lambda name, payload: forwarded.append((name, dict(payload)))
        )

        trace_sink = service._trace_sink
        assert trace_sink is not None
        trace_sink.emit(
            {
                "event_kind": "ocr",
                "provider": "vision",
                "ocr_evidence": {"regions": [{"text": "한글", "confidence": 0.9}]},
                "result_evidence": "{\"selected\":\"한글\"}",
            }
        )

        assert len(sink.events) == 1
        assert len(forwarded) == 1
        assert forwarded[0][0] == "trace"
        assert forwarded[0][1]["provider"] == "vision"
        received = sink.events[0]
        assert isinstance(received, dict)
        if retain_evidence:
            assert received["ocr_evidence"] == {
                "regions": [{"text": "한글", "confidence": 0.9}]
            }
            assert forwarded[0][1]["ocr_evidence"] == {
                "regions": [{"text": "한글", "confidence": 0.9}]
            }
            assert forwarded[0][1]["result_evidence"] == "{\"selected\":\"한글\"}"
        else:
            assert "ocr_evidence" not in received
            assert "result_evidence" not in received
            assert "ocr_evidence" not in forwarded[0][1]
            assert "result_evidence" not in forwarded[0][1]

        service.close()


def test_native_input_reaches_the_prepared_desktop_coordinator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class TraceSink:
        def __init__(self) -> None:
            self.events: list[dict[str, object]] = []

        def emit(self, event: object) -> None:
            assert isinstance(event, dict)
            self.events.append(dict(event))

    class PermissionProbe:
        def state(self, _permission: object) -> permissions_module.PermissionState:
            return permissions_module.PermissionState.GRANTED

        def request(self, permission: object) -> permissions_module.PermissionState:
            return self.state(permission)

    granted = permissions_module.PermissionService(
        PermissionProbe(),
        permissions=(
            permissions_module.Permission.SCREEN_RECORDING,
            permissions_module.Permission.ACCESSIBILITY,
        ),
    )
    monkeypatch.setattr(service_module.application, "create_permission_service", lambda: granted)

    class FakeWorker:
        def __call__(self, _request: object) -> LookupResult:
            return LookupResult(status=LookupStatus.NOT_FOUND)

        def close(self) -> None:
            pass

    class FakeRuntime:
        resource_manager = SimpleNamespace(
            statuses={},
            manifest=(),
            diagnostics=lambda _resource_id: (),
        )

        def resolved_ocr_backend(self) -> OCRBackend:
            return OCRBackend.EASYOCR

        def create_lookup_controller(
            self,
            on_result: Callable[[LookupResult], None] | None = None,
            **options: Any,
        ) -> LookupController:
            return LookupController(
                lambda: FakeWorker(),
                on_result,
                result_dispatcher=options.get("result_dispatcher"),
                thread_name=options.get("thread_name"),
                trace_sink=options.get("trace_sink"),
            )

    class FakeCapture:
        def __init__(self) -> None:
            self.closed = False

        def enumerate_monitors(self) -> tuple[()]:
            return ()

        def capture_at_cursor(self, _cursor: Point) -> object:
            raise AssertionError("the scripted capture hotkey must not capture pixels")

        def close(self) -> None:
            self.closed = True

    class FakeListener:
        def __init__(self, _on_move: Callable[[int, int], None]) -> None:
            self.started = False
            self.stopped = False

        def start(self) -> None:
            self.started = True

        def stop(self) -> None:
            self.stopped = True

        def join(self, timeout: float | None = None) -> None:
            del timeout

    listeners: list[FakeListener] = []

    def make_listener(on_move: Callable[[int, int], None]) -> FakeListener:
        listener = FakeListener(on_move)
        listeners.append(listener)
        return listener

    fake_pynput = ModuleType("pynput")
    fake_mouse = ModuleType("pynput.mouse")
    setattr(fake_mouse, "Listener", make_listener)
    setattr(fake_pynput, "mouse", fake_mouse)
    setattr(fake_pynput, "__path__", [])
    monkeypatch.setitem(sys.modules, "pynput", fake_pynput)
    monkeypatch.setitem(sys.modules, "pynput.mouse", fake_mouse)

    from hanly_app.updates import desktop_runtime

    monkeypatch.setattr(desktop_runtime, "create_update_coordinator", lambda *args, **kwargs: None)

    config_path = tmp_path / "service-settings.json"
    config_path.write_text(
        json.dumps(
            AppConfig(
                lookup_preload=LookupPreload.ON_DEMAND,
                update_checks_enabled=False,
                hover_delay_ms=1000,
            ).to_dict()
        ),
        encoding="utf-8",
    )
    loop: SerializedEventLoop[object] = SerializedEventLoop()
    owner_ready = threading.Event()

    def run_owner() -> None:
        owner_ready.set()
        loop.run(lambda _request: None)

    owner = threading.Thread(target=run_owner, name="scripted-service-owner")
    owner.start()
    assert owner_ready.wait(timeout=2)

    capture = FakeCapture()
    trace_sink = TraceSink()
    provisioned_paths: list[Path] = []

    def provision_runtime(path: Path, _status: Callable[[str], None]) -> Path:
        provisioned_paths.append(path)
        return path

    service = DesktopService(
        config_path,
        runtime_config_path=tmp_path / "runtime.json",
        event_loop=loop,
        runtime_provisioner=provision_runtime,
        runtime_loader=lambda _path: FakeRuntime(),
        capture_service_factory=lambda **_options: cast(CaptureService, capture),
        current_cursor_provider=lambda: Point(420, 330),
        trace_sink=trace_sink,
    )
    emitted: list[tuple[str, dict[str, object]]] = []
    service.set_event_sink(lambda name, payload: emitted.append((name, dict(payload))))

    def call_owner(callback: Callable[[], Any]) -> Any:
        return loop.call_sync(callback, timeout=3)

    def request(
        method: str,
        params: dict[str, Any] | None = None,
        *,
        window: str = "host",
    ) -> dict[str, Any]:
        parsed = parse_request(
            _frame(_message(method=method, params=params, window=window))
        )
        return call_owner(lambda: service.dispatch(parsed))

    try:
        hello = parse_request(_frame(_message()))

        def deliver_hello() -> dict[str, Any]:
            reply = service.dispatch(hello)
            service.after_reply(hello)
            return reply

        assert call_owner(deliver_hello)["service_status"] == "running"
        deadline = time.monotonic() + 5
        while not call_owner(lambda: service.runtime_ready):
            assert time.monotonic() < deadline, "desktop runtime did not become ready"
            time.sleep(0.005)

        manual = call_owner(lambda: service._manual)
        assert manual is not None
        assert manual.controller.wait_until_ready(timeout=3)
        assert provisioned_paths == []

        context = request(
            "native.context",
            {
                "cursor": {"x": 80, "y": 60},
                "monitors": [],
                "registered_hotkeys": {"toggle_capture": "Ctrl+Shift+F12"},
            },
        )
        assert context["accepted"] is True

        press = request(
            "native.input",
            {"action": "toggle_capture", "edge": "pressed"},
        )
        assert press["accepted"] is True
        state = request("get_state", window="control-center")
        assert state["app"]["capture_running"] is True
        assert state["app"]["state"] == "running"

        release = request(
            "native.input",
            {"action": "toggle_capture", "edge": "released"},
        )
        assert release["accepted"] is True
        assert request("get_state", window="control-center")["app"]["state"] == "running"

        stop = request(
            "native.input",
            {"action": "toggle_capture", "edge": "pressed"},
        )
        assert stop["accepted"] is True
        stopped = request("get_state", window="control-center")
        assert stopped["app"]["capture_running"] is False
        assert stopped["app"]["state"] == "paused"
        # Every snapshot, including a bridge method's reply, is ordered within
        # this service's series so the webview can drop one that arrives late.
        refreshed = request("refresh_permissions", window="control-center")
        series = {snapshot["revision"]["series"] for snapshot in (state, stopped, refreshed)}
        assert len(series) == 1
        assert (
            state["revision"]["number"]
            < stopped["revision"]["number"]
            < refreshed["revision"]["number"]
        )

        assert request(
            "native.input",
            {"action": "toggle_capture", "edge": "pressed"},
        )["accepted"] is True
        assert request(
            "native.input",
            {"action": "push_to_hover", "edge": "pressed"},
        )["accepted"] is True
        assert call_owner(lambda: service._cursor) == Point(420, 330)
        assert request(
            "native.input",
            {"action": "push_to_hover", "edge": "released"},
        )["accepted"] is True
        assert capture.closed is False

        while not any(name == "trace" for name, _payload in emitted):
            assert time.monotonic() < deadline + 2
            time.sleep(0.005)

        native_traces = [
            event
            for event in trace_sink.events
            if event["event_kind"] in {"native_context", "native_input"}
        ]
        assert native_traces[0]["registered_hotkey_count"] == 1
        assert all(
            event["event_kind"] == "native_context" or event["accepted"] is True
            for event in native_traces
        )
        assert any(
            event["event_kind"] == "runtime_preparation_completed"
            for event in trace_sink.events
        )
        assert listeners and all(listener.started for listener in listeners)
        assert capture.closed is False
    finally:
        call_owner(service.close)
        loop.stop()
        owner.join(timeout=3)
        assert not owner.is_alive()


def test_native_and_preparation_trace_fields_exclude_native_context_details(
    tmp_path: Path,
) -> None:
    class TraceSink:
        def __init__(self) -> None:
            self.events: list[dict[str, object]] = []

        def emit(self, event: object) -> None:
            assert isinstance(event, dict)
            self.events.append(dict(event))

    trace_sink = TraceSink()
    service = DesktopService(tmp_path / "trace-config.json", trace_sink=trace_sink)
    service.dispatch(
        parse_request(
            _frame(
                _message(
                    method="native.context",
                    params={
                        "cursor": {"x": 200, "y": 300},
                        "monitors": [
                            {
                                "index": 1,
                                "name": "Private display name",
                                "bounds": {"left": 0, "top": 0, "width": 800, "height": 600},
                            }
                        ],
                        "registered_hotkeys": {"toggle_capture": "Ctrl+Shift+F12"},
                    },
                )
            )
        )
    )
    service._startup_generation = 1
    service._startup_failed(1, RuntimeError("private exception detail"))

    context_trace = next(
        event
        for event in trace_sink.events
        if event["event_kind"] == "native_context"
    )
    assert context_trace["registered_hotkey_count"] == 1
    assert "registered_hotkeys" not in context_trace
    assert "Private display name" not in json.dumps(context_trace)

    failure_trace = next(
        event for event in trace_sink.events if event["event_kind"] == "runtime_preparation_failed"
    )
    assert failure_trace["phase"] == "runtime"
    assert "private exception detail" not in json.dumps(failure_trace)
    service.close()


def test_real_runtime_waits_for_host_vision_capability_before_composition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from hanly_app.runtime import HanlyRuntime

    runtime = HanlyRuntime(
        config_path=tmp_path / "runtime.json",
        resource_manager=cast(Any, object()),
        krdict_path=tmp_path / "krdict.sqlite3",
        ocr_backend=OCRBackend.AUTO,
    )
    service = DesktopService(tmp_path / "settings.json")
    composed: list[HanlyRuntime] = []
    monkeypatch.setattr(
        service,
        "_compose_runtime",
        lambda value, _path: composed.append(value),
    )

    service._startup_generation = 1
    service._runtime_loaded(1, runtime, runtime.config_path)

    assert service._runtime is None
    assert service._pending_runtime == (1, runtime, runtime.config_path)
    assert composed == []

    service.dispatch(
        parse_request(
            _frame(
                _message(
                    method="native.context",
                    params={
                        "cursor": {"x": 20, "y": 30},
                        "monitors": [],
                        "vision_available": True,
                    },
                )
            )
        )
    )

    assert service.runtime_ready
    assert len(composed) == 1
    assert composed[0] is not runtime
    assert composed[0].vision_available is True
    assert runtime.vision_available is None
    service.close()


def test_resource_refresh_preserves_host_vision_and_applies_ocr_preference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from hanly.vision_provider import VisionProvider
    from hanly_app.runtime import HanlyRuntime

    def unexpected_probe() -> bool:
        raise AssertionError("service refresh must not probe the Vision framework")

    monkeypatch.setattr(VisionProvider, "is_available", unexpected_probe)
    runtime = HanlyRuntime(
        config_path=tmp_path / "runtime.json",
        resource_manager=cast(Any, object()),
        krdict_path=tmp_path / "krdict.sqlite3",
        ocr_backend=OCRBackend.AUTO,
    )
    service = DesktopService(tmp_path / "settings.json")
    service._native_context_received = True
    service._vision_available = True
    service.bridge._vision_available = True
    composed: list[HanlyRuntime] = []
    restarts: list[bool] = []
    monkeypatch.setattr(service, "_compose_runtime", lambda value, _path: composed.append(value))
    monkeypatch.setattr(service, "retry_runtime", lambda: restarts.append(True))

    service._replace_runtime(runtime, runtime.config_path)

    assert composed[0].vision_available is True
    assert composed[0].resolved_ocr_backend() is OCRBackend.VISION
    assert service._runtime is composed[0]

    service._update_settings({"ocr_backend": OCRBackend.EASYOCR.value})

    assert restarts == [True]
    refreshed_preferences = service._runtime_for_host(runtime)
    assert refreshed_preferences.vision_available is True
    assert refreshed_preferences.resolved_ocr_backend() is OCRBackend.EASYOCR
    service.close()


def test_retry_discards_a_pending_runtime_from_the_previous_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from hanly_app.runtime import HanlyRuntime

    stale = HanlyRuntime(
        config_path=tmp_path / "stale-runtime.json",
        resource_manager=cast(Any, object()),
        krdict_path=tmp_path / "krdict.sqlite3",
        ocr_backend=OCRBackend.AUTO,
    )
    replacement = object()
    service = DesktopService(
        tmp_path / "settings.json",
        runtime_config_path=tmp_path / "runtime.json",
        runtime_loader=lambda _path: replacement,
    )
    composed: list[object] = []
    monkeypatch.setattr(
        service,
        "_compose_runtime",
        lambda value, _path: composed.append(value),
    )
    service._startup_generation = 1
    service._pending_runtime = (1, stale, stale.config_path)

    service.retry_runtime()
    deadline = time.monotonic() + 3
    while not service.runtime_ready:
        assert time.monotonic() < deadline, "retry did not finish runtime preparation"
        time.sleep(0.005)
    service._runtime_loaded(1, stale, stale.config_path)

    assert composed == [replacement]
    assert service._pending_runtime is None
    assert service._runtime is replacement
    service.close()


def test_push_to_hover_rejects_stale_cursor_when_native_read_fails(
    tmp_path: Path,
) -> None:
    class TraceSink:
        def __init__(self) -> None:
            self.events: list[dict[str, object]] = []

        def emit(self, event: object) -> None:
            assert isinstance(event, dict)
            self.events.append(dict(event))

    trace_sink = TraceSink()

    def unavailable_cursor() -> Point:
        raise OSError("private platform failure")

    service = DesktopService(
        tmp_path / "cursor-failure-settings.json",
        current_cursor_provider=unavailable_cursor,
        trace_sink=trace_sink,
    )
    actions: list[tuple[object, object]] = []
    native = service._make_hotkey_runtime(lambda action, edge: actions.append((action, edge)))
    native.apply_registered({"push_to_hover": "Ctrl+Shift+Space"})
    service._native_hotkeys = native
    service._cursor = Point(25, 35)

    response = service.dispatch(
        Request(
            "push",
            "native.input",
            {"action": "push_to_hover", "edge": "pressed"},
            "host",
        )
    )

    assert response == {"accepted": False}
    assert actions == []
    assert service._cursor == Point(25, 35)
    input_trace = next(
        event for event in trace_sink.events if event["event_kind"] == "native_input"
    )
    assert input_trace["accepted"] is False
    assert "private platform failure" not in json.dumps(input_trace)
    service.close()


def test_capture_shortcut_permission_refusal_has_safe_trace_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class TraceSink:
        def __init__(self) -> None:
            self.events: list[dict[str, object]] = []

        def emit(self, event: object) -> None:
            assert isinstance(event, dict)
            self.events.append(dict(event))

    class PermissionProbe:
        def state(self, _permission: object) -> permissions_module.PermissionState:
            return permissions_module.PermissionState.REQUIRED

        def request(self, permission: object) -> permissions_module.PermissionState:
            return self.state(permission)

    refused = permissions_module.PermissionService(
        PermissionProbe(),
        permissions=(
            permissions_module.Permission.SCREEN_RECORDING,
            permissions_module.Permission.ACCESSIBILITY,
        ),
    )
    monkeypatch.setattr(
        service_module.application,
        "create_permission_service",
        lambda: refused,
    )
    trace_sink = TraceSink()
    service = DesktopService(
        tmp_path / "capture-refusal-settings.json",
        trace_sink=trace_sink,
    )
    service._runtime = object()
    service._status.update("ready", "desktop service", "Ready.")

    def apply_capture_action(_action: object, edge: object) -> None:
        if edge == service_module.application.HotkeyEdge.DOWN:
            try:
                service._start_capture()
            except service_module.application.ControlCenterUnavailable:
                pass

    hotkeys = service._make_hotkey_runtime(apply_capture_action)
    hotkeys.apply_registered({"toggle_capture": "Ctrl+Shift+F12"})
    service._native_hotkeys = hotkeys

    result = service.dispatch(
        Request(
            "permission-refusal",
            "native.input",
            {"action": "toggle_capture", "edge": "pressed"},
            "host",
        )
    )

    assert result == {"accepted": True}
    failure = next(
        event
        for event in trace_sink.events
        if event["event_kind"] == "capture_start_failed"
    )
    assert failure["event"] == "capture_start_failed"
    assert failure["code"] == "permission_required"
    assert "Screen Recording" not in json.dumps(failure)
    service.close()


def test_selection_backdrop_rejects_bounds_outside_the_monitor_union(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend_called = False

    class NeverCapture:
        def __init__(self) -> None:
            nonlocal backend_called
            backend_called = True
            raise AssertionError("out-of-scope backdrop must be rejected before capture")

    monkeypatch.setattr(snapshot_module, "MSSBackend", NeverCapture)
    service = DesktopService(tmp_path / "settings.json")
    service._monitors = [
        {
            "index": 1,
            "name": "Display 1",
            "bounds": {"left": 0, "top": 0, "width": 320, "height": 180},
        }
    ]
    service._selection_active = True
    with pytest.raises(ServiceError) as error:
        service.dispatch(
            Request(
                "snapshot",
                "native.selection_snapshot",
                {"bounds": {"left": 300, "top": 100, "width": 40, "height": 40}},
                "host",
            )
        )
    assert error.value.code == "unavailable"
    assert not backend_called
    service.close()


def test_selection_backdrop_accepts_uniform_retina_pixels_without_changing_bounds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    screen = ScreenRect(0, 0, 320, 180)
    captured: list[ScreenRect] = []

    class RetinaBackend:
        def enumerate_monitors(self) -> tuple[BackendMonitor, ...]:
            return (BackendMonitor("Display 1", screen),)

        def grab(self, region: ScreenRect) -> BackendCapture:
            captured.append(region)
            return BackendCapture(640, 360, bytes((20, 40, 60)) * (640 * 360))

        def close(self) -> None:
            return None

    monkeypatch.setattr(snapshot_module, "MSSBackend", RetinaBackend)
    service = DesktopService(tmp_path / "settings.json")
    service._monitors = [
        {
            "index": 1,
            "name": "Display 1",
            "bounds": {"left": 0, "top": 0, "width": 320, "height": 180},
        }
    ]
    service._selection_active = True

    response = service._native_selection_snapshot(
        {"left": 0, "top": 0, "width": 320, "height": 180}
    )
    image_data = base64.b64decode(response["image"].partition(",")[2], validate=True)

    from PIL import Image

    image = Image.open(BytesIO(image_data))
    assert image.size == (640, 360)
    image.close()
    assert captured == [screen]
    service.close()


def test_selection_backdrop_rejects_raw_capture_over_64_megapixels() -> None:
    screen = ScreenRect(0, 0, 4096, 4096)
    closed: list[bool] = []

    class OversizedBackend:
        def enumerate_monitors(self) -> tuple[BackendMonitor, ...]:
            return (BackendMonitor("Display 1", screen),)

        def grab(self, region: ScreenRect) -> BackendCapture:
            assert region == screen
            return BackendCapture(16_384, 16_384, b"")

        def close(self) -> None:
            closed.append(True)

    with pytest.raises(snapshot_module.SnapshotError, match="raw capture limit"):
        snapshot_module.capture_selection_backdrop(
            screen,
            (screen,),
            backend_factory=OversizedBackend,
        )
    assert closed == [True]


def test_update_handoff_acknowledgement_is_host_only_and_install_scoped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from hanly_app.updates import desktop_runtime

    install_root = tmp_path / "Hanly.app"
    receipt_directory = tmp_path / "receipts"
    receipt_directory.mkdir()
    challenge = receipt_directory / "challenge-current.json"
    challenge.write_text("{}", encoding="utf-8")
    acknowledged: list[tuple[Path, Path]] = []

    monkeypatch.setattr(
        desktop_runtime,
        "receipt_store",
        lambda _root: SimpleNamespace(directory=receipt_directory),
    )
    monkeypatch.setattr(
        desktop_runtime,
        "confirm_started_v2",
        lambda path, *, install_root: acknowledged.append((path, install_root)),
    )

    service = DesktopService(
        tmp_path / "settings.json",
        installation_root=install_root,
        root_pid=4321,
    )
    request = parse_request(
        _frame(
            _message(
                method="update.acknowledge",
                params={"challenge_path": str(challenge)},
            )
        )
    )
    assert service.dispatch(request) == {"acknowledged": True}
    assert acknowledged == [(challenge, install_root.resolve())]

    with pytest.raises(ProtocolFailure) as unauthorized:
        parse_request(
            _frame(
                _message(
                    method="update.acknowledge",
                    params={"challenge_path": str(challenge)},
                    window="control-center",
                )
            )
        )
    assert unauthorized.value.code == "unauthorized"

    outside = tmp_path / "someone-elses-challenge.json"
    outside.write_text("{}", encoding="utf-8")
    with pytest.raises(ServiceError) as error:
        service.dispatch(
            Request(
                "outside",
                "update.acknowledge",
                {"challenge_path": str(outside)},
                "host",
            )
        )
    assert error.value.code == "handoff_rejected"
    assert acknowledged == [(challenge, install_root.resolve())]
    service.close()


def test_host_self_check_is_scoped_and_skips_interactive_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from hanly_app.service import self_check

    calls: list[tuple[str, str | None, Path | None]] = []

    def run_check(
        mode: str,
        image: str | None = None,
        *,
        runtime_config: Path | None = None,
    ) -> dict[str, object]:
        calls.append((mode, image, runtime_config))
        return {"ok": True, "versions": {"hanly-app": "1.1.0"}}

    monkeypatch.setattr(self_check, "run_service_self_check", run_check)
    runtime_path = tmp_path / "runtime.json"
    service = DesktopService(
        tmp_path / "settings.json",
        runtime_config_path=runtime_path,
        self_check_mode="inventory",
    )
    hello = Request("hello", "service.hello", {}, "host")
    service.dispatch(hello)
    service.after_reply(hello)
    assert service._startup_thread is None

    result = service.dispatch(
        Request("check", "self_check", {"mode": "inventory"}, "host")
    )
    assert result == {
        "mode": "inventory",
        "ok": True,
        "versions": {"hanly-app": "1.1.0"},
    }
    assert calls == [("inventory", None, runtime_path.resolve())]

    other_service = DesktopService(tmp_path / "other-settings.json")
    with pytest.raises(ServiceError) as error:
        other_service.dispatch(
            Request("check", "self_check", {"mode": "inventory"}, "host")
        )
    assert error.value.code == "unauthorized"
    other_service.close()
    service.close()


def test_service_smoke_reports_unready_state_persists_settings_and_rejects_capture(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text('{"capture_monitor":2}', encoding="utf-8")
    service = DesktopService(config_path)

    hello = service.dispatch(parse_request(_frame(_message())))
    assert hello["runtime_ready"] is False
    assert hello["providers_loaded"] is False

    service.dispatch(
        parse_request(
            _frame(
                _message(
                    method="native.context",
                    params={
                        "cursor": {"x": 0, "y": 0},
                        "monitors": [],
                        "vision_available": sys.platform == "darwin",
                    },
                )
            )
        )
    )

    state = service.dispatch(
        parse_request(_frame(_message(method="get_state", window="control-center")))
    )
    assert state["runtime"]["status"]["phase"] == "idle"
    assert state["app"]["capture_running"] is False
    assert state["runtime"]["ocr_provider"] == "Not reported"
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
    service.close()


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
    frames = [json.loads(line) for line in completed.stdout.splitlines()]
    replies = [frame for frame in frames if frame["type"] == "reply"]
    assert [reply["id"] for reply in replies] == ["hello", "state", "settings", "shutdown"]
    assert all(reply["version"] == 1 and reply["type"] == "reply" for reply in replies)
    assert replies[0]["result"]["providers_loaded"] is False
    assert replies[1]["result"]["runtime"]["status"]["phase"] in {
        "idle",
        "preparing",
    }
    assert replies[2]["result"]["config"]["theme"] == "dark"
    assert replies[3]["result"] == {"accepted": True}
    events = [frame for frame in frames if frame["type"] == "event"]
    assert [event["sequence"] for event in events] == sorted(
        event["sequence"] for event in events
    )


def test_explicit_shutdown_exits_while_supervisor_keeps_stdin_open(
    tmp_path: Path,
) -> None:
    command = [
        sys.executable,
        "-m",
        "hanly_app.service",
        "--app-config",
        str(tmp_path / "settings.json"),
    ]
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=ROOT,
        env=_python_env(),
    )
    assert process.stdin is not None
    assert process.stdout is not None
    output_stream = process.stdout

    frames: list[dict[str, Any]] = []
    shutdown_reply_seen = threading.Event()

    def read_replies() -> None:
        for line in output_stream:
            frame = json.loads(line)
            frames.append(frame)
            if frame.get("type") == "reply" and frame.get("id") == "shutdown":
                shutdown_reply_seen.set()
                return

    reader = threading.Thread(target=read_replies, daemon=True)
    reader.start()
    process.stdin.write(
        b"".join(
            _frame(message) + b"\n"
            for message in (
                _message(request_id="hello"),
                _message(method="service.shutdown", request_id="shutdown"),
            )
        )
    )
    process.stdin.flush()

    try:
        assert shutdown_reply_seen.wait(timeout=10), "service did not reply to shutdown"
        assert process.wait(timeout=15) == 0
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        process.stdin.close()
        reader.join(timeout=2)

    shutdown = next(
        frame for frame in frames if frame.get("type") == "reply" and frame.get("id") == "shutdown"
    )
    assert shutdown["result"] == {"accepted": True}
    assert process.stderr is not None
    assert process.stderr.read() == b""


def test_protocol_output_suppresses_python_and_native_stdout_noise() -> None:
    script = """
import os
from hanly_app.service.server import _protocol_output
with _protocol_output() as writer:
    print('python noise')
    os.write(1, b'native noise\\n')
    writer.write(b'{\"type\":\"reply\"}\\n')
    writer.flush()
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        cwd=ROOT,
        env=_python_env(),
        timeout=10,
        check=False,
    )

    assert completed.returncode == 0
    assert completed.stdout == b'{"type":"reply"}\n'


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
assert 'hanly_app.acquisition.selector' not in sys.modules
for name in (
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
