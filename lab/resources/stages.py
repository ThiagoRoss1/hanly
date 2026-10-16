"""Run stage experiments in fresh processes and attribute what each stage cost.

The parent owns all measurement: it reads the child at each stage boundary,
while the child waits, and samples it continuously in between so a peak inside
a stage is seen even when the stage ends lower. Attribution is by difference
between boundaries, which is an estimate: shared libraries, native allocators
that keep freed pages, compression and initialization order all move it.
"""

from __future__ import annotations

import json
import statistics
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any

from .metrics import Snapshot, primary_memory, snapshot

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Measurement protocol for these experiments. A change to how a value is read
#: or derived bumps it, and comparison refuses to mix versions. v2: providers
#: on the worker thread, genuine OCR calls counted, OCR results recorded.
PROTOCOL = "resources-v2"

#: Fast enough to see a model load's transient; slow enough not to perturb it.
SAMPLE_INTERVAL_SECONDS = 0.02

#: Fewest repeated operations a growth slope is reported from.
MIN_GROWTH_OPERATIONS = 10

#: No stage of a healthy experiment is silent this long; a hung child is killed.
STAGE_TIMEOUT_SECONDS = 600.0


@dataclass
class StageRecord:
    """One stage as the parent observed it."""

    name: str
    duration_ns: int
    detail: dict[str, Any]
    after: dict[str, Any] | None
    sampled_peak: int | None
    sampled_peak_rss: int | None
    ticks: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ExperimentRecord:
    """One fresh child from start to exit."""

    label: str
    stages: list[StageRecord]
    exit_seconds: float | None
    returncode: int | None
    error: str | None = None


class _PeakSampler:
    """Track the highest reading of a process since the last reset."""

    def __init__(self, pid: int, interval: float) -> None:
        self._pid = pid
        self._interval = interval
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._peak: int | None = None
        self._peak_rss: int | None = None
        self._thread = threading.Thread(target=self._run, name="resource-peaks", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)

    def take(self) -> tuple[int | None, int | None]:
        """Return the window's peaks and start a new window."""

        with self._lock:
            peaks = (self._peak, self._peak_rss)
            self._peak = self._peak_rss = None
        return peaks

    def observe(self, reading: Snapshot | None) -> None:
        if reading is None:
            return
        value = primary_memory(reading)
        with self._lock:
            if value is not None and (self._peak is None or value > self._peak):
                self._peak = value
            if reading.rss is not None and (self._peak_rss is None or reading.rss > self._peak_rss):
                self._peak_rss = reading.rss

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            self.observe(snapshot(self._pid, full=False))


def run_child(
    plan: Mapping[str, Any],
    plan_path: Path,
    log_path: Path,
    *,
    label: str,
    interval: float = SAMPLE_INTERVAL_SECONDS,
    stage_timeout: float = STAGE_TIMEOUT_SECONDS,
) -> ExperimentRecord:
    """Run one plan in a fresh interpreter and record every stage boundary."""

    plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    stages: list[StageRecord] = []
    with log_path.open("ab") as log:
        spawned = time.monotonic()
        child = subprocess.Popen(
            [sys.executable, "-m", "lab.resources.child", str(plan_path)],
            cwd=str(REPO_ROOT),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=log,
        )
        assert child.stdin is not None and child.stdout is not None
        sampler = _PeakSampler(child.pid, interval)
        watchdog = _Watchdog(child, stage_timeout)
        sampler.start()
        watchdog.start()
        error: str | None = None
        released = spawned
        try:
            released = _drive(child.stdout, child.stdin, child.pid, sampler, watchdog, stages,
                              spawned=spawned)
        except (OSError, ValueError) as failure:
            error = f"{type(failure).__name__}: {failure}"
        finally:
            sampler.stop()

        try:
            returncode: int | None = child.wait(timeout=60)
            # From the last stage's release to the process being gone.
            exit_seconds: float | None = time.monotonic() - released
        except subprocess.TimeoutExpired:
            child.kill()
            returncode, exit_seconds = None, None
            error = error or "child did not exit within 60 s"
        watchdog.cancel()
    if watchdog.fired:
        error = f"a stage was silent for {stage_timeout:g} s; the child was killed"
    elif returncode not in (0, None) and error is None:
        error = f"child exited with {returncode}; see {log_path.name}"
    return ExperimentRecord(label, stages, exit_seconds, returncode, error)


def _drive(
    stdout: IO[bytes],
    stdin: IO[bytes],
    pid: int,
    sampler: _PeakSampler,
    watchdog: _Watchdog,
    stages: list[StageRecord],
    *,
    spawned: float,
) -> float:
    """Answer every report; return when the last one was released."""

    ticks: list[dict[str, Any]] = []
    released = spawned
    for raw in stdout:
        watchdog.reset()
        record = json.loads(raw)
        # The child is blocked until "go", so this reading is a quiet boundary.
        if "tick" in record:
            reading = snapshot(pid, full=False)
            sampler.observe(reading)
            ticks.append({
                "index": record["tick"],
                "latency_ns": record["latency_ns"],
                "memory": primary_memory(reading),
                "rss": reading.rss if reading else None,
                **{k: v for k, v in record.items() if k not in {"stage", "tick", "latency_ns"}},
            })
        else:
            reading = snapshot(pid, full=True)
            sampler.observe(reading)
            peak, peak_rss = sampler.take()
            name = record.pop("stage")
            duration_ns = int(record.pop("duration_ns"))
            if not stages:
                # The interpreter cannot time its own start; the parent can.
                duration_ns = int((time.monotonic() - spawned) * 1e9)
            stages.append(StageRecord(
                name=name,
                duration_ns=duration_ns,
                detail=record,
                after=reading.as_dict() if reading else None,
                sampled_peak=peak,
                sampled_peak_rss=peak_rss,
                ticks=ticks,
            ))
            ticks = []
            # The next stage starts at this level; seeding its window keeps a
            # stage shorter than the sampling interval from reporting a peak
            # below where it began.
            sampler.observe(reading)
        stdin.write(b"go\n")
        stdin.flush()
        released = time.monotonic()
    stdin.close()
    return released


class _Watchdog:
    """Kill a child whose stages stop arriving."""

    def __init__(self, child: subprocess.Popen[bytes], timeout: float) -> None:
        self._child = child
        self._timeout = timeout
        self._timer: threading.Timer | None = None
        self.fired = False

    def start(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.cancel()
        self._timer = threading.Timer(self._timeout, self._fire)
        self._timer.daemon = True
        self._timer.start()

    def cancel(self) -> None:
        if self._timer is not None:
            self._timer.cancel()

    def _fire(self) -> None:
        self.fired = True
        self._child.kill()


# -- attribution ---------------------------------------------------------------------------


def attribute(record: ExperimentRecord) -> dict[str, Any]:
    """Per-stage deltas, transients and derived quantities for one experiment."""

    rows: list[dict[str, Any]] = []
    previous: int | None = None
    for stage in record.stages:
        memory = primary_memory(stage.after)
        delta = memory - previous if memory is not None and previous is not None else None
        floor = max(v for v in (memory, previous) if v is not None) if (
            memory is not None or previous is not None
        ) else None
        transient = (
            max(0, stage.sampled_peak - floor)
            if stage.sampled_peak is not None and floor is not None
            else None
        )
        rows.append({
            "stage": stage.name,
            "duration_ms": stage.duration_ns / 1e6,
            "memory_after": memory,
            "delta": delta,
            "sampled_peak": stage.sampled_peak,
            "sampled_peak_rss": stage.sampled_peak_rss,
            # Calls that reached the recognizer, beneath every cache.
            "ocr_calls": stage.detail.get("ocr_calls"),
            "transient_above_boundary": transient,
            "rss_after": (stage.after or {}).get("rss"),
            "uss_after": (stage.after or {}).get("uss"),
            "threads_after": (stage.after or {}).get("threads"),
            "detail": stage.detail,
            **_repeated(stage.ticks),
        })
        if memory is not None:
            previous = memory
    _add_resource_deltas(rows, record.stages)
    return {
        "label": record.label,
        "available": _available(record.stages),
        "stages": rows,
        "derived": _derived(rows, record),
        "exit_seconds": record.exit_seconds,
        "returncode": record.returncode,
        "error": record.error,
        "lifetime_peak_footprint": _last(record.stages, "lifetime_peak_footprint"),
    }


def _repeated(ticks: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not ticks:
        return {}
    latencies = sorted(tick["latency_ns"] / 1e6 for tick in ticks)
    memory = [tick["memory"] for tick in ticks if tick.get("memory") is not None]
    return {
        "operations": len(ticks),
        "latency_ms": {
            "p50": _nearest_rank(latencies, 0.5),
            "p90": _nearest_rank(latencies, 0.9),
            "p95": _nearest_rank(latencies, 0.95),
            "max": latencies[-1],
        },
        # A slope through a handful of readings is noise, not growth.
        "growth_per_operation": _slope(memory) if len(memory) >= MIN_GROWTH_OPERATIONS else None,
        "growth_first_to_last": memory[-1] - memory[0] if len(memory) > 1 else None,
        "statuses": sorted({str(tick.get("status")) for tick in ticks if "status" in tick}),
        "digests": [tick.get("digest") for tick in ticks if "digest" in tick],
        "cache": sorted({str(tick.get("cache")) for tick in ticks if "cache" in tick}),
    }


def _add_resource_deltas(rows: list[dict[str, Any]], stages: Sequence[StageRecord]) -> None:
    previous: Mapping[str, Any] = {}
    for row, stage in zip(rows, stages, strict=True):
        after = stage.after or {}
        user = _difference(after.get("cpu_user"), previous.get("cpu_user"))
        system = _difference(after.get("cpu_system"), previous.get("cpu_system"))
        row["cpu_seconds"] = user + system if user is not None and system is not None else None
        row["read_bytes"] = _difference(after.get("read_bytes"), previous.get("read_bytes"))
        row["write_bytes"] = _difference(after.get("write_bytes"), previous.get("write_bytes"))
        if after:
            previous = after


def _difference(after: Any, before: Any) -> Any:
    if after is None or before is None:
        return None
    return after - before


def _derived(rows: Sequence[Mapping[str, Any]], record: ExperimentRecord) -> dict[str, Any]:
    by_name = {row["stage"]: row for row in rows}

    def memory(name: str) -> int | None:
        row = by_name.get(name)
        return row["memory_after"] if row else None

    ready = "assemble_worker" if "assemble_worker" in by_name else "load"
    # Providers may defer their model until first use, so "loaded" alone can
    # miss it; ready_cost runs through the first real operation.
    first = "first_lookup" if "first_lookup" in by_name else "first_use"
    base = memory("runtime_validation")
    loaded = memory(ready)
    sustained = memory("idle")
    unloaded = memory("unload")
    settled = memory("after_unload_idle")
    # Startup runs to the first answer: a deferred load belongs to it.
    names = [row["stage"] for row in rows]
    startup_rows = rows[: names.index(first) + 1] if first in by_name else []
    peaks = [row["sampled_peak"] for row in startup_rows if row["sampled_peak"] is not None]
    return {
        "loaded": _difference(loaded, base),
        "ready_cost": _difference(memory(first), base),
        "startup_ms": sum(row["duration_ms"] for row in startup_rows) or None,
        "startup_sampled_peak": max(peaks) if peaks else None,
        "sustained_after_idle": sustained,
        "released_by_unload": _difference(sustained, unloaded),
        "retained_after_unload": _difference(settled, base),
        "released_at_exit_only": settled,
        "exit_seconds": record.exit_seconds,
    }


def _available(stages: Sequence[StageRecord]) -> dict[str, bool]:
    """Which metrics this child actually produced at any boundary."""

    keys = ("rss", "footprint", "lifetime_peak_footprint", "uss", "read_bytes", "write_bytes",
            "gpu")
    return {
        key: any(stage.after is not None and stage.after.get(key) is not None for stage in stages)
        for key in keys
    }


def _last(stages: Sequence[StageRecord], key: str) -> Any:
    for stage in reversed(stages):
        if stage.after and stage.after.get(key) is not None:
            return stage.after[key]
    return None


def _nearest_rank(values: Sequence[float], quantile: float) -> float:
    index = max(0, min(len(values) - 1, int(round(quantile * len(values) + 0.5)) - 1))
    return values[index]


def _slope(values: Sequence[int]) -> float | None:
    """Least-squares bytes per operation; ``None`` below three readings."""

    if len(values) < 3:
        return None
    count = len(values)
    mean_x = (count - 1) / 2
    mean_y = statistics.fmean(values)
    numerator = sum((index - mean_x) * (value - mean_y) for index, value in enumerate(values))
    denominator = sum((index - mean_x) ** 2 for index in range(count))
    return numerator / denominator


# -- repeats -------------------------------------------------------------------------------


def aggregate(experiments: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Median, minimum and maximum of each stage value across repeats."""

    keys = (
        "memory_after", "delta", "sampled_peak", "transient_above_boundary",
        "duration_ms", "cpu_seconds", "threads_after", "read_bytes",
        "growth_per_operation", "rss_after", "sampled_peak_rss", "ocr_calls",
    )
    stages: dict[str, dict[str, Any]] = {}
    for experiment in experiments:
        for row in experiment["stages"]:
            slot = stages.setdefault(
                row["stage"], {key: [] for key in (*keys, "latency_p50", "latency_p95")}
            )
            for key in keys:
                if row.get(key) is not None:
                    slot[key].append(row[key])
            if row.get("latency_ms"):
                slot["latency_p50"].append(row["latency_ms"]["p50"])
                slot["latency_p95"].append(row["latency_ms"]["p95"])
    derived_keys = {key for experiment in experiments for key in experiment["derived"]}
    derived = {
        key: _spread([
            experiment["derived"][key]
            for experiment in experiments
            if experiment["derived"].get(key) is not None
        ])
        for key in sorted(derived_keys)
    }
    return {
        "repeats": len(experiments),
        "stages": {
            name: {key: _spread(values) for key, values in slot.items()}
            for name, slot in stages.items()
        },
        "derived": derived,
    }


def _spread(values: Sequence[float]) -> dict[str, float] | None:
    if not values:
        return None
    return {
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
        "n": len(values),
    }


ProgressReporter = Callable[[str], None]
