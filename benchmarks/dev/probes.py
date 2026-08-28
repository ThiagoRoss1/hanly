"""Dependency-free observational probes for the benchmark campaign.

The helpers in this module wrap existing production callables.  They do not
replace a provider or alter its inputs, return value, or exception behavior.
"""

from __future__ import annotations

import csv
import dataclasses
import functools
import json
import math
import os
import time
from collections.abc import Callable, Mapping, MutableSequence, Sequence
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter_ns
from typing import Any, TextIO, TypeVar, cast

_resource: Any
try:
    import resource as _resource
except ImportError:  # pragma: no cover - Windows has no resource module.
    _resource = None


JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
Record = dict[str, JsonValue]
Sink = MutableSequence[Any] | Callable[[Mapping[str, Any]], Any] | TextIO
T = TypeVar("T")


def _json_safe(value: Any, *, depth: int = 0) -> JsonValue:
    """Convert an observation value without allowing raw objects into JSON."""
    if value is None or isinstance(value, (bool, int, str)):
        return value

    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)

    if depth >= 5:
        return {"type": type(value).__name__, "truncated": True}

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, bytes):
        return {"type": "bytes", "length": len(value)}

    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        try:
            return _json_safe(dataclasses.asdict(value), depth=depth + 1)
        except BaseException:
            return {"type": type(value).__name__}

    if isinstance(value, Mapping):
        return {
            str(key): _json_safe(item, depth=depth + 1)
            for key, item in value.items()
        }

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_safe(item, depth=depth + 1) for item in value]

    if isinstance(value, (set, frozenset)):
        return sorted((_json_safe(item, depth=depth + 1) for item in value), key=repr)

    return {"type": type(value).__name__}


def _append_record(sink: Sink, record: Record) -> None:
    """Append a record while keeping instrumentation observational.

    A failing telemetry sink must never replace a production result or
    exception.  The record has already been reduced to JSON-safe primitives.
    """
    try:
        if hasattr(sink, "append"):
            cast(MutableSequence[Any], sink).append(record)
        elif hasattr(sink, "write"):
            stream = cast(TextIO, sink)
            stream.write(f"{json.dumps(record, sort_keys=True)}\n")
            stream.flush()
        else:
            cast(Callable[[Mapping[str, JsonValue]], Any], sink)(record)
    except BaseException:
        return


def _correctness_facts(
    value: Any,
    correctness: Mapping[str, Any] | Callable[[Any], Mapping[str, Any]] | None,
) -> tuple[str, JsonValue]:
    if correctness is None:
        return "unknown", {}

    try:
        facts: Any = correctness(value) if callable(correctness) else correctness
        safe_facts = _json_safe(facts)
    except BaseException as error:
        return "unavailable", {"error": type(error).__name__}

    if not isinstance(safe_facts, dict):
        return "unavailable", {"value": safe_facts}

    status = safe_facts.get("status")
    if status is None:
        status = safe_facts.get("correctness_status")
    if status is None and "ok" in safe_facts:
        status = "pass" if safe_facts["ok"] is True else "fail"
    return str(status) if status is not None else "unknown", safe_facts


def _observe_stage(
    stage: str,
    operation: Callable[..., T],
    sink: Sink,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    *,
    run_id: str | None = None,
    scenario: str | None = None,
    iteration: int = 0,
    condition: str = "warm",
    evidence_class: str = "measured",
    correctness: Mapping[str, Any] | Callable[[Any], Mapping[str, Any]] | None = None,
    correctness_facts: Mapping[str, Any] | Callable[[Any], Mapping[str, Any]] | None = None,
) -> T:
    started = perf_counter_ns()
    base: Record = {
        "schema_version": 1,
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "evidence_class": evidence_class,
        "scenario": scenario,
        "stage": stage,
        "iteration": iteration,
        "condition": condition,
    }

    try:
        result = operation(*args, **kwargs)
    except BaseException as error:
        base.update(
            {
                "duration_ns": perf_counter_ns() - started,
                "correctness_status": "error",
                "correctness": {},
                "exception_type": type(error).__name__,
                "exception_message": _exception_message(error),
            }
        )
        _append_record(sink, cast(Record, _json_safe(base)))
        raise

    status, facts = _correctness_facts(result, correctness or correctness_facts)
    base.update(
        {
            "duration_ns": perf_counter_ns() - started,
            "correctness_status": status,
            "correctness": facts,
            "result": _json_safe(result),
        }
    )
    _append_record(sink, cast(Record, _json_safe(base)))
    return result


def _exception_message(error: BaseException) -> str:
    try:
        return str(error)
    except BaseException:
        return f"<{type(error).__name__}>"


def observe_stage(
    stage: str,
    operation: Callable[..., T],
    sink: Sink,
    *args: Any,
    run_id: str | None = None,
    scenario: str | None = None,
    iteration: int = 0,
    condition: str = "warm",
    evidence_class: str = "measured",
    correctness: Mapping[str, Any] | Callable[[Any], Mapping[str, Any]] | None = None,
    correctness_facts: Mapping[str, Any] | Callable[[Any], Mapping[str, Any]] | None = None,
    **kwargs: Any,
) -> T:
    """Time one existing callable and append one JSON-safe measurement."""
    return _observe_stage(
        stage,
        operation,
        sink,
        args,
        kwargs,
        run_id=run_id,
        scenario=scenario,
        iteration=iteration,
        condition=condition,
        evidence_class=evidence_class,
        correctness=correctness,
        correctness_facts=correctness_facts,
    )


probe_stage = observe_stage


def _stage_wrapper(
    stage: str,
    operation: Callable[..., T],
    sink: Sink,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    metadata: dict[str, Any],
) -> T:
    return _observe_stage(stage, operation, sink, args, kwargs, **metadata)


_METADATA_KEYS = {
    "run_id",
    "scenario",
    "iteration",
    "condition",
    "evidence_class",
    "correctness",
    "correctness_facts",
}


def _split_metadata(kwargs: dict[str, Any]) -> dict[str, Any]:
    metadata = {key: kwargs.pop(key) for key in tuple(kwargs) if key in _METADATA_KEYS}
    return metadata


def probe_capture(operation: Callable[..., T], sink: Sink, *args: Any, **kwargs: Any) -> T:
    """Observe a capture callable without changing its result or errors."""
    return _stage_wrapper("capture", operation, sink, args, kwargs, _split_metadata(kwargs))


def probe_ocr(operation: Callable[..., T], sink: Sink, *args: Any, **kwargs: Any) -> T:
    """Observe an OCR callable without changing its result or errors."""
    return _stage_wrapper("ocr", operation, sink, args, kwargs, _split_metadata(kwargs))


def probe_morphology(operation: Callable[..., T], sink: Sink, *args: Any, **kwargs: Any) -> T:
    """Observe a morphology callable without changing its result or errors."""
    return _stage_wrapper("morphology", operation, sink, args, kwargs, _split_metadata(kwargs))


def probe_dictionary(operation: Callable[..., T], sink: Sink, *args: Any, **kwargs: Any) -> T:
    """Observe a dictionary callable without changing its result or errors."""
    return _stage_wrapper("dictionary", operation, sink, args, kwargs, _split_metadata(kwargs))


def probe_result_dispatch(operation: Callable[..., T], sink: Sink, *args: Any, **kwargs: Any) -> T:
    """Observe the result-dispatch callable without changing its result or errors."""
    return _stage_wrapper("result_dispatch", operation, sink, args, kwargs, _split_metadata(kwargs))


capture_probe = probe_capture
ocr_probe = probe_ocr
morphology_probe = probe_morphology
dictionary_probe = probe_dictionary
result_dispatch_probe = probe_result_dispatch


class StageProbe:
    """Reusable stage wrapper carrying common measurement metadata."""

    def __init__(
        self,
        stage: str,
        sink: Sink,
        *,
        run_id: str | None = None,
        scenario: str | None = None,
        condition: str = "warm",
        evidence_class: str = "measured",
    ) -> None:
        self.stage = stage
        self.sink = sink
        self.run_id = run_id
        self.scenario = scenario
        self.condition = condition
        self.evidence_class = evidence_class
        self._iteration = 0

    def __call__(self, operation: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        result = observe_stage(
            self.stage,
            operation,
            self.sink,
            *args,
            run_id=self.run_id,
            scenario=self.scenario,
            iteration=self._iteration,
            condition=self.condition,
            evidence_class=self.evidence_class,
            **kwargs,
        )
        self._iteration += 1
        return result

    def wrap(self, operation: Callable[..., T]) -> Callable[..., T]:
        """Return a callable that measures each invocation of ``operation``."""
        @functools.wraps(operation)
        def wrapped(*args: Any, **kwargs: Any) -> T:
            return self(operation, *args, **kwargs)

        return wrapped

    measure = __call__
    run = __call__


class ProcessSampler:
    """Write bounded process CPU/RSS observations to a CSV stream or path."""

    def __init__(
        self,
        output: str | os.PathLike[str] | TextIO,
        *,
        interval_seconds: float = 0.25,
        max_window_seconds: float = 60.0,
        process: Any | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Any] = time.sleep,
    ) -> None:
        if interval_seconds < 0:
            raise ValueError("interval_seconds must be non-negative")
        if max_window_seconds <= 0:
            raise ValueError("max_window_seconds must be positive")
        self.output = output
        self.interval_seconds = interval_seconds
        self.max_window_seconds = max_window_seconds
        self.process = process
        self.clock = clock
        self.sleep = sleep

    def _resolve_process(self) -> Any | None:
        if self.process is not None:
            return self.process
        try:
            import psutil  # type: ignore[import-untyped]

            return psutil.Process(os.getpid())
        except Exception:
            return None

    def _read_sample(self, process: Any | None) -> tuple[float | None, int | None]:
        if process is not None:
            try:
                cpu = process.cpu_percent(interval=None)
            except Exception:
                cpu = None
            try:
                rss = process.memory_info().rss
            except Exception:
                rss = None
            return _number_or_none(cpu), _integer_or_none(rss)

        try:
            if _resource is None:
                return None, None
            usage = _resource.getrusage(_resource.RUSAGE_SELF)
            # Unix reports KiB; keep the field name honest for the fallback.
            return None, int(usage.ru_maxrss) * 1024
        except Exception:
            return None, None

    def _open_output(self) -> tuple[TextIO, bool]:
        if hasattr(self.output, "write"):
            return cast(TextIO, self.output), False
        return Path(self.output).open("w", encoding="utf-8", newline=""), True

    def run(self, duration_seconds: float) -> int:
        """Sample immediately and continue no longer than the configured cap."""
        if duration_seconds < 0:
            raise ValueError("duration_seconds must be non-negative")

        duration = min(float(duration_seconds), self.max_window_seconds)
        stream, close_stream = self._open_output()
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(("timestamp", "cpu_percent", "rss_bytes"))
        stream.flush()

        process = self._resolve_process()
        deadline = self.clock() + duration
        count = 0
        max_samples = 100_000
        try:
            while True:
                cpu, rss = self._read_sample(process)
                writer.writerow(
                    (time.time_ns(), cpu if cpu is not None else "", rss if rss is not None else "")
                )
                stream.flush()
                count += 1

                now = self.clock()
                if now >= deadline or count >= max_samples:
                    break

                remaining = deadline - now
                self.sleep(min(self.interval_seconds, remaining))
        finally:
            if close_stream:
                stream.close()
        return count


def _number_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _integer_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def sample_process(
    output: str | os.PathLike[str] | TextIO,
    duration_seconds: float,
    **kwargs: Any,
) -> int:
    """Convenience function for one bounded process-observation window."""
    return ProcessSampler(output, **kwargs).run(duration_seconds)


__all__ = [
    "ProcessSampler",
    "StageProbe",
    "capture_probe",
    "dictionary_probe",
    "morphology_probe",
    "observe_stage",
    "ocr_probe",
    "probe_capture",
    "probe_dictionary",
    "probe_morphology",
    "probe_ocr",
    "probe_result_dispatch",
    "probe_stage",
    "result_dispatch_probe",
    "sample_process",
]
