"""Privacy-safe telemetry primitives for the live benchmark.

The real application can optionally send small JSON-safe mappings to a trace
sink.  This module intentionally has no imports from ``hanly_app``: it is a
developer-only recorder, sampler, and report builder used by the benchmark
driver.  The recorder's producer path is bounded and ``put_nowait`` only;
benchmark tracing must never add latency to the hover path.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import queue
import re
import secrets
import threading
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from statistics import median
from typing import Any, TextIO

LIVE_PHASES: tuple[str, ...] = (
    "idle",
    "empty",
    "non_korean_text",
    "repeated_same_korean",
    "korean_sequence",
    "stationary_changing_content",
    "fast_movement",
    "normal_game_browser",
)

_HANGUL_RE = re.compile(r"[\u1100-\u11ff\u3130-\u318f\ua960-\ua97f\uac00-\ud7ff]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_DIGIT_RE = re.compile(r"[0-9]")
_TEXT_KEYS = {"text", "ocr_text", "raw_text", "headword", "lemma"}
_WINDOW_KEYS = {"window", "window_name", "window_title", "process_name"}
_PIXEL_KEYS = {"pixels", "screenshot", "roi_bytes", "raw_roi", "image_bytes"}


def _json_safe(value: Any) -> Any:
    """Convert arbitrary optional fields to values accepted by JSON."""

    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, bytes):
        return {"byte_count": len(value)}
    return str(value)


class LiveTraceRecorder:
    """Best-effort bounded JSONL event recorder.

    ``record`` only timestamps, sanitizes simple JSON values, and calls
    ``put_nowait``.  It does not wait for a writer, flush a file, or propagate
    writer failures.  The daemon writer is started by default so a caller can
    inject this sink into a live composition without an additional lifecycle
    step; ``start=False`` is useful for deterministic tests.
    """

    def __init__(
        self,
        output: str | os.PathLike[str] | TextIO,
        *,
        queue_size: int = 4096,
        clock: Callable[[], int] = time.perf_counter_ns,
        start: bool = True,
    ) -> None:
        if queue_size < 1:
            raise ValueError("queue_size must be positive")
        self.output = output
        self.clock = clock
        self._queue: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=queue_size)
        self._thread: threading.Thread | None = None
        self._closed = False
        self._started = False
        self._lock = threading.Lock()
        self._dropped_events = 0
        self._write_errors = 0
        self._last_write_error: str | None = None
        if start:
            self.start()

    @property
    def dropped_events(self) -> int:
        return self._dropped_events

    @property
    def write_errors(self) -> int:
        return self._write_errors

    @property
    def last_write_error(self) -> str | None:
        return self._last_write_error

    def start(self) -> None:
        """Start the daemon writer; repeated calls are harmless."""

        with self._lock:
            if self._started or self._closed:
                return
            self._started = True
            self._thread = threading.Thread(
                target=self._write_loop,
                name="benchmark-trace-writer",
                daemon=True,
            )
            self._thread.start()

    def record(self, event: str, **fields: Any) -> bool:
        """Queue one event without waiting for the writer.

        Returns ``False`` if the recorder is closed or its bounded queue is
        full.  A monotonic nanosecond timestamp is always generated at the
        producer boundary, before queuing.
        """

        if not isinstance(event, str) or not event.strip():
            raise ValueError("event must be a non-empty string")
        if self._closed:
            return False
        payload: dict[str, Any] = {
            "schema_version": 1,
            "event": event,
            "monotonic_ns": int(self.clock()),
        }
        payload.update({str(key): _json_safe(value) for key, value in fields.items()})
        return self._enqueue(payload)

    def record_at(self, event: str, monotonic_ns: int, **fields: Any) -> bool:
        """Queue an event carrying an already-observed monotonic timestamp."""

        if not isinstance(event, str) or not event.strip():
            raise ValueError("event must be a non-empty string")
        if isinstance(monotonic_ns, bool) or not isinstance(monotonic_ns, int):
            raise TypeError("monotonic_ns must be an integer")
        payload: dict[str, Any] = {
            "schema_version": 1,
            "event": event,
            "monotonic_ns": monotonic_ns,
        }
        payload.update({str(key): _json_safe(value) for key, value in fields.items()})
        return self._enqueue(payload)

    def _enqueue(self, payload: dict[str, Any]) -> bool:
        if self._closed:
            return False
        try:
            self._queue.put_nowait(payload)
        except queue.Full:
            self._dropped_events += 1
            return False
        return True

    def emit(self, fields: Mapping[str, Any]) -> bool:
        """Record an event mapping, retaining the recorder-owned timestamp."""

        event = fields.get("event", fields.get("event_kind"))
        if not isinstance(event, str):
            raise ValueError("event mapping must contain a string event or event_kind")
        payload = {
            key: value
            for key, value in fields.items()
            if key not in {"event", "event_kind", "monotonic_ns", "timestamp_ns"}
        }
        observed_ns = fields.get("monotonic_ns", fields.get("timestamp_ns"))
        if isinstance(observed_ns, int) and not isinstance(observed_ns, bool):
            return self.record_at(event, observed_ns, **payload)
        return self.record(event, **payload)

    def close(self, timeout: float = 2.0) -> None:
        """Drain queued events and close the output best-effort."""

        if self._closed:
            return
        self._closed = True
        if not self._started:
            return
        # This is lifecycle code, not a production event path.  If the queue
        # is full, the writer will drain it before accepting the sentinel.
        while True:
            try:
                self._queue.put(None, timeout=0.01)
                break
            except queue.Full:
                if self._thread is None or not self._thread.is_alive():
                    break
        if self._thread is not None:
            self._thread.join(timeout=max(0.0, timeout))

    def __enter__(self) -> LiveTraceRecorder:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _write_loop(self) -> None:
        stream: TextIO | None = None
        close_stream = False
        try:
            if hasattr(self.output, "write"):
                stream = self.output  # type: ignore[assignment]
            else:
                stream = Path(self.output).open("a", encoding="utf-8", newline="\n")
                close_stream = True
        except Exception as exc:  # pragma: no cover - platform/file-system dependent
            self._record_write_error(exc)
            return

        if stream is None:
            return
        try:
            while True:
                item = self._queue.get()
                if item is None:
                    break
                try:
                    stream.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")
                    stream.flush()
                except Exception as exc:  # pragma: no cover - platform/file-system dependent
                    self._record_write_error(exc)
        finally:
            if close_stream and stream is not None:
                try:
                    stream.close()
                except Exception as exc:  # pragma: no cover - platform/file-system dependent
                    self._record_write_error(exc)

    def _record_write_error(self, error: BaseException) -> None:
        self._write_errors += 1
        self._last_write_error = type(error).__name__


class LiveResourceSampler:
    """Background CPU/RSS sampler with injectable time/process dependencies."""

    def __init__(
        self,
        output: str | os.PathLike[str] | TextIO,
        *,
        interval_seconds: float = 0.25,
        process: Any | None = None,
        process_factory: Callable[[], Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
        clock_ns: Callable[[], int] | None = None,
        wall_clock_ns: Callable[[], int] = time.time_ns,
        sleep: Callable[[float], Any] = time.sleep,
        phase: Callable[[], str] | None = None,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self.output = output
        self.interval_seconds = interval_seconds
        self.process = process
        self.process_factory = process_factory
        self._process_resolution_attempted = process is not None
        self.clock = clock
        self.clock_ns = clock_ns
        self.wall_clock_ns = wall_clock_ns
        self.sleep = sleep
        self.phase = phase or (lambda: "unknown")
        self._stream: TextIO | None = None
        self._close_stream = False
        self._writer: csv.DictWriter[str] | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._open()
        self._stop.clear()
        self.sample_once()
        self._thread = threading.Thread(
            target=self._run,
            name="benchmark-resource-sampler",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(0.0, timeout))
            self._thread = None
        if self._stream is not None:
            try:
                self._stream.flush()
            finally:
                if self._close_stream:
                    self._stream.close()
                self._stream = None
                self._writer = None

    def sample_once(self) -> bool:
        """Append one sample; return false only when process metrics fail."""

        if self._stream is None:
            self._open()
        process = self._resolve_process()
        cpu: float | None = None
        rss: int | None = None
        threads: int | None = None
        if process is not None:
            try:
                cpu_value = process.cpu_percent(interval=None)
                cpu = float(cpu_value) if math.isfinite(float(cpu_value)) else None
            except Exception:
                pass
            try:
                rss = int(process.memory_info().rss)
            except Exception:
                pass
            try:
                threads = int(process.num_threads())
            except Exception:
                pass
        if self._writer is None or self._stream is None:
            return False
        stream = self._stream
        writer = self._writer
        row = {
            "timestamp": self.wall_clock_ns(),
            "monotonic_ns": (
                int(self.clock_ns())
                if self.clock_ns is not None
                else int(self.clock() * 1_000_000_000)
            ),
            "phase": self.phase(),
            "cpu_percent": "" if cpu is None else cpu,
            "rss_bytes": "" if rss is None else rss,
            "thread_count": "" if threads is None else threads,
        }
        with self._lock:
            writer.writerow(row)
            stream.flush()
        return True

    def _run(self) -> None:
        while not self._stop.is_set():
            self.sleep(self.interval_seconds)
            if not self._stop.is_set():
                self.sample_once()

    def _open(self) -> None:
        if self._stream is not None:
            return
        if hasattr(self.output, "write"):
            self._stream = self.output  # type: ignore[assignment]
        else:
            path = Path(self.output)
            path.parent.mkdir(parents=True, exist_ok=True)
            self._stream = path.open("w", encoding="utf-8", newline="")
            self._close_stream = True
        stream = self._stream
        if stream is None:
            raise OSError("could not open resource sampler output")
        self._writer = csv.DictWriter(
            stream,
            fieldnames=(
                "timestamp",
                "monotonic_ns",
                "phase",
                "cpu_percent",
                "rss_bytes",
                "thread_count",
            ),
            lineterminator="\n",
        )
        self._writer.writeheader()
        stream.flush()

    def _resolve_process(self) -> Any | None:
        if self.process is not None:
            return self.process
        if self._process_resolution_attempted:
            return None
        self._process_resolution_attempted = True
        try:
            if self.process_factory is not None:
                self.process = self.process_factory()
                return self.process
            import psutil  # type: ignore[import-untyped]

            self.process = psutil.Process(os.getpid())
            return self.process
        except Exception:
            return None


class PhaseTransition:
    """One deterministic marker transition."""

    def __init__(self, previous: str, phase: str, marker_index: int) -> None:
        self.previous = previous
        self.phase = phase
        self.marker_index = marker_index

    def as_dict(self) -> dict[str, Any]:
        return {
            "previous_phase": self.previous,
            "phase": self.phase,
            "marker_index": self.marker_index,
        }


class ScenarioPhaseController:
    """Cycle through the approved live-run scenarios from a marker hotkey."""

    def __init__(self, phases: Sequence[str] = LIVE_PHASES) -> None:
        normalized = tuple(str(phase) for phase in phases)
        if not normalized or any(not phase for phase in normalized):
            raise ValueError("phases must contain at least one non-empty name")
        self.phases = normalized
        self.index = 0
        self._lock = threading.Lock()

    @property
    def current(self) -> str:
        with self._lock:
            return self.phases[self.index]

    def set(self, phase: str) -> PhaseTransition:
        if phase not in self.phases:
            raise ValueError(f"unknown phase: {phase}")
        with self._lock:
            previous = self.phases[self.index]
            self.index = self.phases.index(phase)
            return PhaseTransition(previous, self.phases[self.index], self.index)

    def advance(self) -> PhaseTransition:
        with self._lock:
            previous = self.phases[self.index]
            self.index = (self.index + 1) % len(self.phases)
            return PhaseTransition(previous, self.phases[self.index], self.index)


class SessionPrivacy:
    """Redact screen-derived values while retaining useful classifications."""

    def __init__(self, *, key: bytes | None = None) -> None:
        self.key = key if key is not None else secrets.token_bytes(32)
        if not self.key:
            raise ValueError("privacy key must not be empty")

    def roi_digest(self, roi: bytes | bytearray | memoryview, width: int, height: int) -> str:
        payload = width.to_bytes(8, "big", signed=False) + height.to_bytes(8, "big", signed=False)
        digest = hashlib.blake2b(payload + bytes(roi), key=self.key, digest_size=16).hexdigest()
        return digest

    def classify_text(self, text: str) -> dict[str, Any]:
        if not isinstance(text, str):
            text = str(text)
        hangul = sum(1 for char in text if _HANGUL_RE.fullmatch(char))
        latin = sum(1 for char in text if _LATIN_RE.fullmatch(char))
        digits = sum(1 for char in text if _DIGIT_RE.fullmatch(char))
        whitespace = sum(1 for char in text if char.isspace())
        punctuation = sum(1 for char in text if not char.isalnum() and not char.isspace())
        return {
            "char_count": len(text),
            "hangul_char_count": hangul,
            "has_hangul": hangul > 0,
            "latin_char_count": latin,
            "digit_char_count": digits,
            "whitespace_char_count": whitespace,
            "punctuation_char_count": punctuation,
        }

    def redact(self, fields: Mapping[str, Any], *, retain_text: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in fields.items():
            name = str(key)
            lowered = name.casefold()
            if lowered in _WINDOW_KEYS:
                continue
            if lowered in _TEXT_KEYS:
                if isinstance(value, str):
                    result.update(self.classify_text(value))
                    if retain_text:
                        result[name] = value
                continue
            if lowered in _PIXEL_KEYS:
                if isinstance(value, (bytes, bytearray, memoryview)):
                    width = int(fields.get("roi_width", 0) or 0)
                    height = int(fields.get("roi_height", 0) or 0)
                    result["roi_digest"] = self.roi_digest(value, width, height)
                    result["roi_byte_count"] = len(value)
                continue
            result[name] = _json_safe(value)
        return result


def _percentile(values: Iterable[int | float]) -> dict[str, Any] | None:
    ordered = sorted(values)
    if not ordered:
        return None
    rank = max(1, math.ceil(len(ordered) * 0.95))
    return {
        "count": len(ordered),
        "min": ordered[0],
        "max": ordered[-1],
        "mean": sum(ordered) / len(ordered),
        "p50": median(ordered),
        "p95": ordered[rank - 1],
        "duration_unit": "ns",
    }


def _event_values(
    records: Sequence[Mapping[str, Any]], event_names: set[str], key: str
) -> list[int | float]:
    values: list[int | float] = []
    for record in records:
        if record.get("event") in event_names and isinstance(record.get(key), (int, float)):
            value = record[key]
            if not isinstance(value, bool) and math.isfinite(float(value)) and value >= 0:
                values.append(value)
    return values


def _preferred_count(
    events: Sequence[str],
    primary: Sequence[str],
    fallback: Sequence[str],
) -> int:
    primary_count = sum(event in set(primary) for event in events)
    return primary_count if primary_count else sum(event in set(fallback) for event in events)


class LiveSummary:
    """Build the JSON-safe live report from trace and resource observations."""

    @staticmethod
    def from_records(
        events: Iterable[Mapping[str, Any]],
        process_samples: Iterable[Mapping[str, Any]],
    ) -> dict[str, Any]:
        records = [dict(record) for record in events]
        samples = [dict(sample) for sample in process_samples]
        monotonic = [
            int(record["monotonic_ns"])
            for record in records
            if isinstance(record.get("monotonic_ns"), (int, float))
        ]
        session_starts = [
            int(record["monotonic_ns"])
            for record in records
            if record.get("event") == "session_started"
            and isinstance(record.get("monotonic_ns"), (int, float))
        ]
        session_finishes = [
            int(record["monotonic_ns"])
            for record in records
            if record.get("event") == "session_finished"
            and isinstance(record.get("monotonic_ns"), (int, float))
        ]
        if session_starts and session_finishes:
            duration_ns = max(0, session_finishes[-1] - session_starts[0])
        else:
            duration_ns = max(monotonic) - min(monotonic) if monotonic else 0
        event_names = [str(record.get("event", "")) for record in records]

        def count(*names: str) -> int:
            return sum(event in set(names) for event in event_names)

        opportunity_count = _preferred_count(
            event_names,
            ("hover_opportunity", "hover_move", "hover_mouse_opportunity"),
            ("dwell_started",),
        )
        ocr_count = _preferred_count(
            event_names,
            ("ocr_started", "ocr_invoked"),
            ("ocr_completed", "ocr_result"),
        )
        if ocr_count == 0:
            ocr_count = sum(record.get("stage") == "ocr" for record in records)
        hangul = count("hangul_detected") or sum(
            record.get("has_hangul") is True for record in records
        )
        non_hangul = sum(
            record.get("has_hangul") is False
            for record in records
            if record.get("event") in {"ocr_completed", "ocr_result"} or "has_hangul" in record
        )
        dictionary_hits = sum(
            record.get("status") in {"hit", "found", "success"}
            for record in records
            if record.get("event") in {"dictionary_result", "dictionary_lookup"}
        )
        dictionary_misses = sum(
            record.get("status") in {"miss", "missing", "not_found"}
            for record in records
            if record.get("event") in {"dictionary_result", "dictionary_lookup"}
        )

        duration_seconds = duration_ns / 1_000_000_000 if duration_ns else 0.0
        summary: dict[str, Any] = {
            "session_duration_ns": duration_ns,
            "session_duration_seconds": duration_seconds,
            "hover_opportunities": opportunity_count,
            "capture_count": _preferred_count(
                event_names,
                ("capture_started", "hover_capture_attempted"),
                ("capture_completed", "capture_finished", "hover_capture_completed"),
            ),
            "ocr_invocations": ocr_count,
            "ocr_invocations_per_hover_opportunity": (
                ocr_count / opportunity_count if opportunity_count else 0.0
            ),
            "ocr_invocation_rate_per_second": (
                ocr_count / duration_seconds if duration_seconds else 0.0
            ),
            "ocr_invocation_rate_per_minute": (
                ocr_count * 60 / duration_seconds if duration_seconds else 0.0
            ),
            "capture_latency_ns": _percentile(
                _event_values(
                    records, {"capture_completed", "capture_finished"}, "capture_latency_ns"
                )
                + _event_values(records, {"hover_capture_completed"}, "duration_ns")
            ),
            "ocr_latency_ns": _percentile(
                _event_values(records, {"ocr_completed", "ocr_result"}, "ocr_latency_ns")
                + [
                    value
                    for record in records
                    if record.get("event") == "lookup_stage_completed"
                    and record.get("stage") == "ocr"
                    for value in _event_values([record], {"lookup_stage_completed"}, "duration_ns")
                ]
            ),
            "hover_to_popup_latency_ns": _percentile(
                _event_values(records, {"popup_visible"}, "hover_to_popup_ns")
                + _event_values(records, {"popup_visible"}, "hover_to_visible_popup_ns")
            ),
            "repeated_frame_suppressed": sum(
                record.get("event") in {"ocr_suppressed", "work_suppressed"}
                and record.get("reason", record.get("suppression_reason")) == "repeated_frame"
                for record in records
            )
            + count("lookup_cache_hit"),
            "repeated_region_suppressed": sum(
                record.get("event") in {"ocr_suppressed", "work_suppressed"}
                and record.get("reason", record.get("suppression_reason")) == "repeated_region"
                for record in records
            ),
            "repeated_frame_observations": sum(
                record.get("event") == "roi_observation"
                and record.get("repeated_frame") is True
                for record in records
            ),
            "repeated_region_observations": sum(
                record.get("event") == "roi_observation"
                and record.get("repeated_region") is True
                for record in records
            ),
            "stale_work": count(
                "work_stale",
                "lookup_stale",
                "stale_result",
                "lookup_stale_suppressed",
                "hover_stale_after_capture",
                "hover_stale_after_submission",
            ),
            "cancelled_work": count(
                "work_cancelled",
                "lookup_cancelled",
                "cancelled",
                "executor_pending_cancelled",
                "lookup_cancelled_early",
            ),
            "hover_work_invalidations": count("hover_cancellation"),
            "executor_pending_cancellations": count("executor_pending_cancelled"),
            "pipeline_early_cancellations": count("lookup_cancelled_early"),
            "replaced_work": count(
                "work_replaced",
                "lookup_replaced",
                "replaced",
                "executor_pending_replaced",
            ),
            "hangul_detections": hangul,
            "non_hangul_results": non_hangul,
            "dictionary_hits": dictionary_hits,
            "dictionary_misses": dictionary_misses,
            "idle_resource_use": _resource_summary(samples, "idle"),
            "phase_duration_ns": _phase_durations(records),
            "popup_visible_count": count("popup_visible"),
            "popup_suppressed_count": count("popup_suppressed"),
            "popup_results_by_status": _field_counts(
                records, event="popup_visible", field="result_status"
            ),
            "popup_suppressed_by_status": _field_counts(
                records, event="popup_suppressed", field="result_status"
            ),
            "provider_worker_ready_count": count("executor_worker_ready"),
            "exact_input_cache_hits": count("lookup_cache_hit"),
            "work_queued": count("executor_submission_accepted"),
            "work_started": count("executor_work_started"),
            "work_completed": count("executor_work_completed"),
            "results_delivered": count("lookup_current_delivered"),
        }
        stage_records = [
            record for record in records if record.get("event") == "lookup_stage_completed"
        ]
        summary["hangul_detections"] = max(
            int(summary["hangul_detections"]),
            sum(
                int(record.get("hangul_region_count", 0) or 0)
                for record in stage_records
                if record.get("stage") == "ocr"
            ),
        )
        summary["non_hangul_results"] = max(
            int(summary["non_hangul_results"]),
            sum(
                int(record.get("region_count", 0) or 0) > 0
                and int(record.get("hangul_region_count", 0) or 0) == 0
                for record in stage_records
                if record.get("stage") == "ocr"
            ),
        )
        dictionary_records = [
            record
            for record in stage_records
            if record.get("stage") == "dictionary"
        ]
        summary["dictionary_hits"] = max(
            int(summary["dictionary_hits"]),
            sum(record.get("found") is True for record in dictionary_records),
        )
        summary["dictionary_misses"] = max(
            int(summary["dictionary_misses"]),
            sum(record.get("found") is False for record in dictionary_records),
        )
        ocr_durations = [
            int(record["duration_ns"])
            for record in stage_records
            if record.get("stage") == "ocr"
            and isinstance(record.get("duration_ns"), (int, float))
            and not isinstance(record.get("duration_ns"), bool)
        ]
        summary["first_ocr_inference_ns"] = (
            ocr_durations[0] if ocr_durations else None
        )
        summary["subsequent_ocr_latency_ns"] = _percentile(ocr_durations[1:])
        summary["non_hangul_ocr_regions"] = sum(
            max(
                0,
                int(record.get("region_count", 0) or 0)
                - int(record.get("hangul_region_count", 0) or 0),
            )
            for record in stage_records
            if record.get("stage") == "ocr"
        )
        summary["provider_initialization_latency_ns"] = _paired_latency(
            records,
            "executor_worker_construction_started",
            "executor_worker_ready",
        )
        summary["provider_prewarm_latency_ns"] = _percentile(
            _event_values(
                records,
                {"provider_prewarm_completed"},
                "duration_ns",
            )
        )
        summary["stage_latency_ns"] = {
            "dwell": _percentile(
                _event_values(records, {"hover_stable_fire"}, "dwell_duration_ns")
            ),
            "capture": summary["capture_latency_ns"],
            **{
                stage: _percentile(
                    [
                        record["duration_ns"]
                        for record in stage_records
                        if record.get("stage") == stage
                        and isinstance(record.get("duration_ns"), (int, float))
                        and not isinstance(record.get("duration_ns"), bool)
                    ]
                )
                for stage in (
                    "ocr",
                    "token_selection",
                    "morphology",
                    "dictionary",
                    "total_pipeline",
                )
            },
            "ui_dispatch_to_popup": _percentile(
                _event_values(records, {"popup_visible"}, "ui_dispatch_to_popup_ns")
            ),
            "hover_to_visible_popup": summary["hover_to_popup_latency_ns"],
        }
        return summary

    @staticmethod
    def from_files(
        events_path: str | os.PathLike[str], process_path: str | os.PathLike[str]
    ) -> dict[str, Any]:
        with Path(events_path).open(encoding="utf-8") as stream:
            events = [json.loads(line) for line in stream if line.strip()]
        with Path(process_path).open(encoding="utf-8", newline="") as stream:
            samples = list(csv.DictReader(stream))
        return LiveSummary.from_records(events, samples)


def _resource_summary(samples: Sequence[Mapping[str, Any]], phase: str) -> dict[str, Any]:
    selected = [sample for sample in samples if sample.get("phase") == phase]

    def values(key: str) -> list[float]:
        result: list[float] = []
        for sample in selected:
            try:
                value = float(sample[key])
            except (KeyError, TypeError, ValueError):
                continue
            if math.isfinite(value):
                result.append(value)
        return result

    def numeric_summary(items: list[float]) -> dict[str, Any] | None:
        result = _percentile(items)
        if result is not None:
            result["duration_unit"] = "value"
        return result

    return {
        "sample_count": len(selected),
        "cpu_percent": numeric_summary(values("cpu_percent")),
        "rss_bytes": numeric_summary(values("rss_bytes")),
        "thread_count": numeric_summary(values("thread_count")),
    }


def _field_counts(
    records: Sequence[Mapping[str, Any]], *, event: str, field: str
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        if record.get("event") != event:
            continue
        value = record.get(field)
        if value is None:
            continue
        key = str(value)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _paired_latency(
    records: Sequence[Mapping[str, Any]], start_event: str, end_event: str
) -> int | None:
    started: int | None = None
    for record in sorted(
        records,
        key=lambda item: int(item.get("monotonic_ns", 0) or 0),
    ):
        observed = record.get("monotonic_ns")
        if not isinstance(observed, (int, float)):
            continue
        if record.get("event") == start_event:
            started = int(observed)
        elif record.get("event") == end_event and started is not None:
            return max(0, int(observed) - started)
    return None


def _phase_durations(records: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    timed = sorted(
        (
            int(record["monotonic_ns"]),
            str(record.get("event", "")),
            str(record.get("phase", "unknown")),
        )
        for record in records
        if isinstance(record.get("monotonic_ns"), (int, float))
    )
    start = next((item for item in timed if item[1] == "session_started"), None)
    finish = next(
        (item for item in reversed(timed) if item[1] == "session_finished"), None
    )
    if start is None or finish is None or finish[0] < start[0]:
        return {}
    durations: dict[str, int] = {}
    current_phase = start[2]
    previous_ns = start[0]
    for observed_ns, event, phase in timed:
        if observed_ns <= previous_ns or event != "phase_marker":
            continue
        durations[current_phase] = durations.get(current_phase, 0) + (
            observed_ns - previous_ns
        )
        current_phase = phase
        previous_ns = observed_ns
    durations[current_phase] = durations.get(current_phase, 0) + (
        finish[0] - previous_ns
    )
    return durations


__all__ = [
    "LIVE_PHASES",
    "LiveResourceSampler",
    "LiveSummary",
    "LiveTraceRecorder",
    "PhaseTransition",
    "ScenarioPhaseController",
    "SessionPrivacy",
]
