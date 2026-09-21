"""Synthetic tests for the live runner's adapters and lifecycle boundaries."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path

from hanly import PixelFormat, Point, ROIImage
from hanly_app.capture import (
    BackendCapture,
    BackendMonitor,
    CaptureResult,
    ScreenRect,
)

from benchmarks.dev.live_runner import (
    DeferredRoiObserver,
    MarkerHotkey,
    ObservedCaptureSource,
    RuntimeTraceAdapter,
    SessionEvidenceCounts,
    _export_message,
    _freeze_message,
    _run_cleanup_steps,
    freeze_lookup_into,
    production_capture_service,
)
from benchmarks.dev.live_telemetry import (
    LiveTraceRecorder,
    ScenarioPhaseController,
    SessionPrivacy,
)
from benchmarks.dev.microscope import build_ring


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


class _GridBackend:
    """A capture backend that only records which rectangle was asked for."""

    def __init__(self) -> None:
        self.regions: list[ScreenRect] = []

    def enumerate_monitors(self) -> tuple[BackendMonitor, ...]:
        return (BackendMonitor(name="Monitor 1", bounds=ScreenRect(0, 0, 1920, 1080)),)

    def grab(self, region: ScreenRect) -> BackendCapture:
        self.regions.append(region)
        return BackendCapture(
            width=region.width,
            height=region.height,
            rgb=bytes(region.width * region.height * 3),
        )


def test_live_capture_snaps_roi_origins_to_the_production_grid() -> None:
    """A benchmark measuring an unsnapped grid measures a different runtime."""

    backend = _GridBackend()
    service = production_capture_service(backend)

    service.capture_at_cursor(Point(500, 400))
    service.capture_at_cursor(Point(508, 404))

    assert len(backend.regions) == 2
    assert backend.regions[0] == backend.regions[1]
    assert backend.regions[0].left % 32 == 0
    assert backend.regions[0].top % 32 == 0
    assert (backend.regions[0].width, backend.regions[0].height) == (200, 100)


# --- Microscope wiring ------------------------------------------------------


def test_freezing_remembers_the_pinned_lookup_for_a_later_export() -> None:
    ring = build_ring()
    ring.observe_event(
        {"event_kind": "popup_visible", "lookup_request_id": 3, "result_status": "SUCCESS"},
        1,
    )
    holder: list[object] = []

    report = freeze_lookup_into(ring, holder)

    assert report.frozen is not None
    assert holder == [report.frozen]
    assert "pinned lookup 3" in _freeze_message(report)


def test_freezing_nothing_says_so_and_remembers_nothing() -> None:
    holder: list[object] = []

    report = freeze_lookup_into(build_ring(), holder)

    assert report.frozen is None
    assert holder == []
    assert "nothing to pin" in _freeze_message(report)


def test_exporting_before_freezing_asks_for_a_freeze_instead_of_writing(
    tmp_path: Path,
) -> None:
    message = _export_message([], tmp_path, tmp_path)

    assert "press the freeze hotkey first" in message
    assert list(tmp_path.iterdir()) == []


def test_exporting_a_pinned_lookup_writes_it_under_the_run_directory(
    tmp_path: Path,
) -> None:
    ring = build_ring()
    ring.observe_event(
        {"event_kind": "popup_visible", "lookup_request_id": 3, "result_status": "SUCCESS"},
        1,
    )
    holder: list[object] = []
    freeze_lookup_into(ring, holder)
    run_dir = tmp_path / "run-1"

    message = _export_message(holder, run_dir, tmp_path)

    assert message.startswith("export: ")
    assert (run_dir / "frozen-3" / "diagnostic.json").exists()


def test_the_live_adapter_never_persists_raw_text(tmp_path: Path) -> None:
    """Retention is an explicit export of one frozen lookup, not a trace mode."""

    output = tmp_path / "events.jsonl"
    recorder = LiveTraceRecorder(output)
    adapter = RuntimeTraceAdapter(
        recorder, ScenarioPhaseController(), SessionPrivacy(key=b"session")
    )

    adapter.emit(
        {
            "event": "lookup_stage_completed",
            "stage": "ocr",
            "lookup_request_id": 1,
            "ocr_text": "비밀번호",
            "monotonic_ns": 5,
        }
    )
    adapter.record("benchmark_note", text="비밀번호")
    recorder.close()

    persisted = output.read_text(encoding="utf-8")
    assert "비밀번호" not in persisted
    assert '"has_hangul":true' in persisted


# --- Freeze and export are counted apart ------------------------------------


def test_freezes_exports_and_reexports_are_counted_separately(tmp_path: Path) -> None:
    """An earlier run reported nine exports against eight directories."""

    ring = build_ring()
    counts = SessionEvidenceCounts()
    holder: list[object] = []

    # An export before any freeze is refused and writes nothing.
    _export_message(holder, tmp_path / "r", tmp_path, counts)

    for identifier in (1, 2):
        ring.observe_event(
            {
                "event_kind": "popup_visible",
                "lookup_request_id": identifier,
                "result_status": "SUCCESS",
            },
            identifier,
        )
        freeze_lookup_into(ring, holder, counts)
        _export_message(holder, tmp_path / "r", tmp_path, counts)

    # A second freeze of the same lookup, then a re-export of it.
    freeze_lookup_into(ring, holder, counts)
    _export_message(holder, tmp_path / "r", tmp_path, counts)

    summary = counts.as_dict()

    assert summary["frozen_lookups_pinned"] == 3
    assert summary["frozen_lookup_export_attempts"] == 4
    assert summary["frozen_lookup_exports_refused_nothing_frozen"] == 1
    assert summary["frozen_lookup_exports_succeeded"] == 3
    assert summary["frozen_lookup_reexports"] == 1
    # Two distinct lookups were exported, whatever the attempt count says.
    assert summary["frozen_lookups_exported"] == 2
    assert summary["frozen_lookup_exports_failed"] == 0


def test_the_counts_carry_no_identifiers_or_screen_content(tmp_path: Path) -> None:
    ring = build_ring()
    counts = SessionEvidenceCounts()
    holder: list[object] = []
    ring.observe_event(
        {"event_kind": "popup_visible", "lookup_request_id": 42, "result_status": "SUCCESS"},
        1,
    )
    freeze_lookup_into(ring, holder, counts)
    _export_message(holder, tmp_path / "r", tmp_path, counts)

    encoded = json.dumps(counts.as_dict())

    assert all(isinstance(value, int) for value in counts.as_dict().values())
    assert "42" not in encoded
