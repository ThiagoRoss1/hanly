"""Synthetic tests for the live runner's adapters and lifecycle boundaries."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path

from hanly import PixelFormat, Point, ROIImage
from hanly_app.capture import CaptureResult, ScreenRect

from benchmarks.dev.live_runner import (
    DeferredRoiObserver,
    MarkerHotkey,
    ObservedCaptureSource,
    RuntimeTraceAdapter,
    _run_cleanup_steps,
)
from benchmarks.dev.live_telemetry import (
    LiveTraceRecorder,
    ScenarioPhaseController,
    SessionPrivacy,
)


def _rows(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_runtime_adapter_correlates_dwell_dispatch_and_full_popup_latency(
    tmp_path: Path,
) -> None:
    output = tmp_path / "events.jsonl"
    recorder = LiveTraceRecorder(output)
    adapter = RuntimeTraceAdapter(
        recorder,
        ScenarioPhaseController(),
        SessionPrivacy(key=b"session"),
    )

    adapter.emit(
        {
            "event_kind": "hover_mouse_opportunity",
            "timestamp_ns": 100,
            "hover_request_id": 3,
        }
    )
    adapter.emit(
        {
            "event_kind": "hover_stable_fire",
            "timestamp_ns": 250,
            "hover_request_id": 3,
        }
    )
    adapter.emit(
        {
            "event_kind": "hover_submission",
            "timestamp_ns": 300,
            "hover_request_id": 3,
            "lookup_request_id": 8,
        }
    )
    adapter.emit(
        {
            "event_kind": "lookup_dispatch_queued",
            "timestamp_ns": 700,
            "lookup_request_id": 8,
        }
    )
    adapter.emit(
        {
            "event_kind": "popup_visible",
            "timestamp_ns": 800,
            "lookup_request_id": 8,
            "result_status": "SUCCESS",
        }
    )
    recorder.close()

    rows = _rows(output)
    stable = next(row for row in rows if row["event"] == "hover_stable_fire")
    popup = next(row for row in rows if row["event"] == "popup_visible")
    assert stable["dwell_duration_ns"] == 150
    assert popup["hover_request_id"] == 3
    assert popup["hover_to_visible_popup_ns"] == 700
    assert popup["ui_dispatch_to_popup_ns"] == 100
    assert all(row["phase"] == "idle" for row in rows)


def test_runtime_adapter_retires_non_success_popup_correlations(tmp_path: Path) -> None:
    recorder = LiveTraceRecorder(tmp_path / "events.jsonl")
    adapter = RuntimeTraceAdapter(
        recorder,
        ScenarioPhaseController(),
        SessionPrivacy(key=b"session"),
    )
    adapter.emit(
        {
            "event_kind": "hover_submission",
            "timestamp_ns": 100,
            "hover_request_id": 3,
            "lookup_request_id": 8,
        }
    )
    adapter.emit(
        {
            "event_kind": "lookup_dispatch_queued",
            "timestamp_ns": 200,
            "lookup_request_id": 8,
        }
    )
    adapter.emit(
        {
            "event_kind": "popup_suppressed",
            "timestamp_ns": 300,
            "lookup_request_id": 8,
            "result_status": "EMPTY",
        }
    )
    recorder.close()

    assert adapter._lookup_to_hover == {}
    assert adapter._dispatch_started == {}


def test_capture_observer_hashes_frames_off_the_capture_callback(
    tmp_path: Path,
) -> None:
    output = tmp_path / "events.jsonl"
    recorder = LiveTraceRecorder(output)
    privacy = SessionPrivacy(key=b"session")
    observer = DeferredRoiObserver(recorder, privacy)
    capture = CaptureResult(
        ROIImage(2, 1, PixelFormat.RGB_888, b"abcdef"),
        ScreenRect(10, 20, 2, 1),
        Point(1, 0),
    )

    class Source:
        def __init__(self) -> None:
            self.closed = False

        def capture_at_cursor(self, _cursor: Point) -> CaptureResult:
            return capture

        def close(self) -> None:
            self.closed = True

    source = Source()
    wrapped = ObservedCaptureSource(source, observer)
    assert wrapped.capture_at_cursor(Point(11, 20)) is capture
    assert wrapped.capture_at_cursor(Point(11, 20)) is capture
    wrapped.close()
    observer.close()
    recorder.close()

    roi_rows = [row for row in _rows(output) if row["event"] == "roi_observation"]
    assert len(roi_rows) == 2
    assert roi_rows[0]["repeated_frame"] is False
    assert roi_rows[1]["repeated_frame"] is True
    assert roi_rows[1]["repeated_region"] is True
    assert "pixels" not in roi_rows[1]
    assert "roi_bytes" not in roi_rows[1]
    assert source.closed is True


def test_marker_hotkey_uses_canonical_binding_and_bounded_cleanup() -> None:
    callbacks: dict[str, Callable[[], None]] = {}

    class Listener:
        def __init__(self) -> None:
            self.started = False
            self.stopped = False
            self.join_timeout: float | None = None

        def start(self) -> None:
            self.started = True

        def stop(self) -> None:
            self.stopped = True

        def join(self, timeout: float | None = None) -> None:
            self.join_timeout = timeout

    listener = Listener()

    def factory(mapping: Mapping[str, Callable[[], None]]) -> Listener:
        callbacks.update(mapping)
        return listener

    markers: list[str] = []
    marker = MarkerHotkey("Ctrl+Alt+Shift+B", lambda: markers.append("marked"), factory)
    marker.start()
    callbacks["<ctrl>+<shift>+<alt>+b"]()
    marker.stop()

    assert markers == ["marked"]
    assert listener.started is True
    assert listener.stopped is True
    assert listener.join_timeout == 1.0


def test_cleanup_steps_continue_after_one_resource_fails() -> None:
    called: list[str] = []

    def fail() -> None:
        called.append("fail")
        raise RuntimeError("broken cleanup")

    errors = _run_cleanup_steps(
        ("first", lambda: called.append("first")),
        ("failing", fail),
        ("last", lambda: called.append("last")),
    )

    assert called == ["first", "fail", "last"]
    assert errors == ["failing:RuntimeError"]
