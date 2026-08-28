"""Deterministic tests for the live benchmark telemetry helpers."""

from __future__ import annotations

import csv
import json
from io import StringIO
from pathlib import Path
from typing import Any

from benchmarks.dev.live_telemetry import (
    LIVE_PHASES,
    LiveResourceSampler,
    LiveSummary,
    LiveTraceRecorder,
    ScenarioPhaseController,
    SessionPrivacy,
)


def test_recorder_is_bounded_non_blocking_and_writes_monotonic_events(tmp_path: Path) -> None:
    output = tmp_path / "events.jsonl"
    ticks = iter([100, 200, 300])
    recorder = LiveTraceRecorder(output, queue_size=1, clock=lambda: next(ticks), start=False)
    assert recorder.record("hover_opportunity", request_id="r1") is True
    # A full queue is observable, but never makes the producer wait.
    assert recorder.record("capture_started", request_id="r1") is False
    recorder.start()
    recorder.close()

    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert [row["monotonic_ns"] for row in rows] == [100]
    assert rows[0]["event"] == "hover_opportunity"
    assert recorder.dropped_events == 1
    assert recorder.write_errors == 0


def test_recorder_swallows_writer_errors(tmp_path: Path) -> None:
    output = tmp_path / "events.jsonl"
    output.write_bytes(b"not a directory")
    recorder = LiveTraceRecorder(output / "child.jsonl")
    assert recorder.record("event") is True
    recorder.close()
    assert recorder.write_errors >= 1


def test_recorder_adapts_production_runtime_events_without_retimestamping(
    tmp_path: Path,
) -> None:
    output = tmp_path / "events.jsonl"
    recorder = LiveTraceRecorder(output, clock=lambda: 999)
    assert recorder.emit(
        {
            "event_kind": "hover_mouse_opportunity",
            "timestamp_ns": 123,
            "hover_request_id": 7,
        }
    ) is True
    recorder.close()

    [row] = [
        json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()
    ]
    assert row["event"] == "hover_mouse_opportunity"
    assert row["monotonic_ns"] == 123
    assert "event_kind" not in row
    assert "timestamp_ns" not in row


def test_phase_controller_cycles_through_approved_scenarios() -> None:
    controller = ScenarioPhaseController()
    assert controller.current == "idle"
    transitions = [controller.advance() for _ in LIVE_PHASES]
    assert [transition.phase for transition in transitions] == [*LIVE_PHASES[1:], "idle"]
    assert transitions[0].marker_index == 1


def test_privacy_redacts_text_headwords_window_names_and_pixels() -> None:
    privacy = SessionPrivacy(key=b"test-session-key")
    result = privacy.redact(
        {
            "ocr_text": "한국어 123",
            "headword": "한국어",
            "window_title": "private window",
            "roi_bytes": b"pixels",
            "roi_width": 20,
            "roi_height": 10,
        }
    )
    assert "ocr_text" not in result
    assert "headword" not in result
    assert "window_title" not in result
    assert result["has_hangul"] is True
    assert result["hangul_char_count"] == 3
    assert result["roi_digest"] == privacy.roi_digest(b"pixels", 20, 10)
    assert "roi_bytes" not in result


def test_privacy_can_retain_text_and_digest_is_session_keyed() -> None:
    first = SessionPrivacy(key=b"one")
    second = SessionPrivacy(key=b"two")
    assert first.redact({"text": "한국"}, retain_text=True)["text"] == "한국"
    assert first.roi_digest(b"same", 1, 4) != second.roi_digest(b"same", 1, 4)


class _FakeProcess:
    def __init__(self) -> None:
        self.calls = 0

    def cpu_percent(self, interval: float | None = None) -> float:
        self.calls += 1
        return 2.5

    def memory_info(self) -> Any:
        return type("Memory", (), {"rss": 1234})()

    def num_threads(self) -> int:
        return 4


def test_resource_sampler_writes_cpu_rss_phase_and_thread_count() -> None:
    output = StringIO()
    process = _FakeProcess()
    sampler = LiveResourceSampler(
        output,
        process=process,
        clock=lambda: 12.5,
        wall_clock_ns=lambda: 999,
        phase=lambda: "idle",
    )
    assert sampler.sample_once() is True
    row = next(csv.DictReader(StringIO(output.getvalue())))
    assert row == {
        "timestamp": "999",
        "monotonic_ns": "12500000000",
        "phase": "idle",
        "cpu_percent": "2.5",
        "rss_bytes": "1234",
        "thread_count": "4",
    }


def test_resource_sampler_reuses_one_process_for_cpu_deltas() -> None:
    output = StringIO()
    process = _FakeProcess()
    factory_calls = 0

    def process_factory() -> _FakeProcess:
        nonlocal factory_calls
        factory_calls += 1
        return process

    sampler = LiveResourceSampler(output, process_factory=process_factory)
    sampler.sample_once()
    sampler.sample_once()

    assert factory_calls == 1
    assert process.calls == 2


def test_live_summary_correlates_latency_and_counts_idle_resources() -> None:
    events = [
        {"event": "session_started", "monotonic_ns": 0, "phase": "idle"},
        {"event": "hover_opportunity", "monotonic_ns": 1_000_000_000, "phase": "empty"},
        {
            "event": "capture_completed",
            "monotonic_ns": 1_100_000_000,
            "capture_latency_ns": 100_000_000,
        },
        {
            "event": "ocr_completed",
            "monotonic_ns": 1_300_000_000,
            "ocr_latency_ns": 200_000_000,
            "has_hangul": False,
        },
        {"event": "ocr_suppressed", "monotonic_ns": 2_000_000_000, "reason": "repeated_region"},
        {
            "event": "ocr_completed",
            "monotonic_ns": 3_000_000_000,
            "ocr_latency_ns": 300_000_000,
            "has_hangul": True,
        },
        {"event": "dictionary_result", "monotonic_ns": 3_100_000_000, "status": "hit"},
        {
            "event": "popup_visible",
            "monotonic_ns": 3_200_000_000,
            "hover_to_popup_ns": 2_200_000_000,
        },
        {"event": "work_stale", "monotonic_ns": 4_000_000_000},
        {"event": "session_finished", "monotonic_ns": 5_000_000_000},
    ]
    process = [
        {"phase": "idle", "cpu_percent": "1.0", "rss_bytes": "100"},
        {"phase": "idle", "cpu_percent": "3.0", "rss_bytes": "120"},
        {"phase": "empty", "cpu_percent": "30", "rss_bytes": "130"},
    ]
    summary = LiveSummary.from_records(events, process)
    assert summary["session_duration_ns"] == 5_000_000_000
    assert summary["hover_opportunities"] == 1
    assert summary["ocr_invocations"] == 2
    assert summary["ocr_invocation_rate_per_second"] == 0.4
    assert summary["capture_latency_ns"]["p50"] == 100_000_000
    assert summary["ocr_latency_ns"]["p95"] == 300_000_000
    assert summary["hover_to_popup_latency_ns"]["p50"] == 2_200_000_000
    assert summary["repeated_region_suppressed"] == 1
    assert summary["stale_work"] == 1
    assert summary["hangul_detections"] == 1
    assert summary["non_hangul_results"] == 1
    assert summary["dictionary_hits"] == 1
    assert summary["idle_resource_use"]["cpu_percent"]["p50"] == 2.0


def test_live_summary_understands_production_trace_vocabulary() -> None:
    events = [
        {"event": "session_started", "monotonic_ns": 0},
        {
            "event": "hover_mouse_opportunity",
            "monotonic_ns": 100,
            "hover_request_id": 1,
        },
        {
            "event": "hover_capture_completed",
            "monotonic_ns": 200,
            "duration_ns": 20,
        },
        {
            "event": "lookup_stage_completed",
            "stage": "ocr",
            "monotonic_ns": 300,
            "duration_ns": 50,
            "region_count": 1,
            "hangul_region_count": 1,
        },
        {
            "event": "lookup_stage_completed",
            "stage": "dictionary",
            "monotonic_ns": 350,
            "duration_ns": 10,
            "found": True,
        },
        {
            "event": "lookup_stage_completed",
            "stage": "token_selection",
            "monotonic_ns": 360,
            "duration_ns": 5,
        },
        {
            "event": "lookup_stage_completed",
            "stage": "morphology",
            "monotonic_ns": 370,
            "duration_ns": 7,
        },
        {
            "event": "popup_visible",
            "monotonic_ns": 400,
            "hover_to_visible_popup_ns": 300,
        },
        {"event": "executor_pending_replaced", "monotonic_ns": 450},
        {"event": "lookup_stale_suppressed", "monotonic_ns": 460},
        {"event": "hover_cancellation", "monotonic_ns": 470},
        {"event": "lookup_cancelled_early", "monotonic_ns": 475},
        {"event": "lookup_cache_hit", "monotonic_ns": 476},
        {
            "event": "roi_observation",
            "monotonic_ns": 480,
            "repeated_frame": True,
            "repeated_region": True,
        },
        {"event": "session_finished", "monotonic_ns": 500},
    ]

    summary = LiveSummary.from_records(events, [])

    assert summary["hover_opportunities"] == 1
    assert summary["capture_count"] == 1
    assert summary["ocr_invocations"] == 1
    assert summary["ocr_invocations_per_hover_opportunity"] == 1.0
    assert summary["capture_latency_ns"]["p50"] == 20
    assert summary["ocr_latency_ns"]["p50"] == 50
    assert summary["first_ocr_inference_ns"] == 50
    assert summary["subsequent_ocr_latency_ns"] is None
    assert summary["dictionary_hits"] == 1
    assert summary["hangul_detections"] == 1
    assert summary["replaced_work"] == 1
    assert summary["stale_work"] == 1
    assert summary["cancelled_work"] == 1
    assert summary["hover_work_invalidations"] == 1
    assert summary["executor_pending_cancellations"] == 0
    assert summary["pipeline_early_cancellations"] == 1
    assert summary["repeated_frame_observations"] == 1
    assert summary["repeated_region_observations"] == 1
    assert summary["exact_input_cache_hits"] == 1
    assert summary["repeated_frame_suppressed"] == 1
    assert summary["stage_latency_ns"]["token_selection"]["p50"] == 5
    assert summary["stage_latency_ns"]["morphology"]["p50"] == 7
    assert summary["stage_latency_ns"]["dictionary"]["p50"] == 10
    assert summary["provider_worker_ready_count"] == 0


def test_summary_json_is_serializable() -> None:
    result = LiveSummary.from_records([{"event": "session_started", "monotonic_ns": 10}], [])
    json.dumps(result)
