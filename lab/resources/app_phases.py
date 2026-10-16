"""Attribute a recorded desktop session's process samples to its phases.

Reads ``processes.jsonl`` and ``events.jsonl`` from an existing session run;
nothing is launched. Phases come from the session's own events, so a phase
the session never reached is absent rather than empty. Samples are RSS every
250 ms, which shares pages between processes and misses short spikes.
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

#: A gap this long without lookup activity counts as idle.
IDLE_GAP_MS = 10_000.0

#: Events that mark lookup activity.
_ACTIVITY = frozenset({"lookup_submit", "lookup_current_delivered", "lookup_stage_completed"})


def analyze_session(run_dir: Path) -> dict[str, Any]:
    """Per-phase, per-role peaks, sustained levels, growth, duplicates and leftovers."""

    samples = list(_read_jsonl(run_dir / "processes.jsonl"))
    events = list(_read_jsonl(run_dir / "events.jsonl"))
    if not samples:
        raise ValueError(f"{run_dir.name} holds no process samples")
    phases = phase_windows(events, end_ms=float(samples[-1]["t_ms"]))
    return {
        "run": run_dir.name,
        "metric": "rss",
        "phases": {
            name: _phase(samples, start, end)
            for name, windows in phases.items()
            for start, end in windows[:1]
        } | {
            "idle": _merged(samples, phases.get("idle", [])),
        },
        "duplicates": duplicates(samples),
        "after_stop": _after_stop(samples, events),
        "growth": _growth(samples, phases),
    }


def phase_windows(
    events: Sequence[Mapping[str, Any]], *, end_ms: float
) -> dict[str, list[tuple[float, float]]]:
    """Windows in session milliseconds, taken from the session's own events."""

    first: dict[str, float] = {}
    activity: list[float] = []
    for event in events:
        name = event.get("event")
        moment = event.get("t_ms")
        if not isinstance(name, str) or not isinstance(moment, (int, float)):
            continue
        first.setdefault(name, float(moment))
        if name in _ACTIVITY:
            activity.append(float(moment))

    windows: dict[str, list[tuple[float, float]]] = {}
    ready = first.get("runtime_preparation_completed", first.get("executor_worker_ready"))
    if ready is not None:
        windows["startup"] = [(0.0, ready)]
    if "provider_prewarm_started" in first and "provider_prewarm_completed" in first:
        windows["engine_warm"] = [(first["provider_prewarm_started"],
                                   first["provider_prewarm_completed"])]
    stop = first.get("desktop_stop_requested", end_ms)
    if activity:
        windows["active"] = [(min(activity), max(activity))]
    windows["idle"] = _idle_gaps(sorted(activity), ready or 0.0, stop)
    if "desktop_stop_requested" in first:
        windows["shutdown"] = [(stop, first.get("desktop_stopped", end_ms))]
    return windows


def _idle_gaps(activity: Sequence[float], start: float, stop: float) -> list[tuple[float, float]]:
    marks = [start, *[moment for moment in activity if start <= moment <= stop], stop]
    return [(left, right) for left, right in zip(marks, marks[1:]) if right - left >= IDLE_GAP_MS]


def _phase(samples: Sequence[Mapping[str, Any]], start: float, end: float) -> dict[str, Any]:
    return _roles([sample for sample in samples if start <= sample["t_ms"] <= end], start, end)


def _merged(
    samples: Sequence[Mapping[str, Any]], windows: Sequence[tuple[float, float]]
) -> dict[str, Any]:
    chosen = [
        sample for sample in samples
        if any(start <= sample["t_ms"] <= end for start, end in windows)
    ]
    total = sum(end - start for start, end in windows)
    return _roles(chosen, None, None) | {"windows": len(windows), "duration_ms": total}


def _roles(
    samples: Sequence[Mapping[str, Any]], start: float | None, end: float | None
) -> dict[str, Any]:
    # A role can be several processes at once (webview helpers), so each
    # sample is totalled per role before peaks and medians are taken.
    per_role: dict[str, list[int]] = defaultdict(list)
    totals: list[int] = []
    for sample in samples:
        in_sample: dict[str, int] = defaultdict(int)
        for process in sample["processes"]:
            rss = process.get("rss")
            if isinstance(rss, int):
                in_sample[process["role"]] += rss
        for role, rss in in_sample.items():
            per_role[role].append(rss)
        totals.append(sum(in_sample.values()))
    return {
        "start_ms": start,
        "end_ms": end,
        "samples": len(samples),
        "roles": {
            role: {
                "peak": max(values),
                "sustained_median": statistics.median(values),
                "last": values[-1],
            }
            for role, values in sorted(per_role.items())
        },
        # Summing RSS double-counts pages processes share; an upper bound.
        "family_peak_upper_bound": max(totals) if totals else None,
        "family_median_upper_bound": statistics.median(totals) if totals else None,
    }


def duplicates(samples: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """Roles seen with more than one live process in the same sample."""

    found: dict[str, int] = {}
    for sample in samples:
        counts: dict[str, int] = defaultdict(int)
        for process in sample["processes"]:
            counts[process["role"]] += 1
        for role, count in counts.items():
            # Webview helpers are several processes by design.
            if count > 1 and not role.endswith("helper"):
                found[role] = max(found.get(role, 0), count)
    return found


def _after_stop(
    samples: Sequence[Mapping[str, Any]], events: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    stopped = next(
        (float(event["t_ms"]) for event in events if event.get("event") == "desktop_stopped"),
        None,
    )
    if stopped is None:
        return {"observed": False}
    late = [sample for sample in samples if sample["t_ms"] > stopped]
    survivors = sorted({
        process["role"] for sample in late for process in sample["processes"]
    })
    return {"observed": True, "samples_after_stop": len(late), "surviving_roles": survivors}


def _growth(
    samples: Sequence[Mapping[str, Any]],
    phases: Mapping[str, Sequence[tuple[float, float]]],
) -> dict[str, Any]:
    """Bytes per minute per role from the end of startup to the stop request."""

    start = phases.get("startup", [(0.0, 0.0)])[0][1]
    stop = phases.get("shutdown", [(float("inf"), 0.0)])[0][0]
    series: dict[str, list[tuple[float, int]]] = defaultdict(list)
    for sample in samples:
        if start <= sample["t_ms"] < stop:
            in_sample: dict[str, int] = defaultdict(int)
            for process in sample["processes"]:
                if isinstance(process.get("rss"), int):
                    in_sample[process["role"]] += process["rss"]
            for role, rss in in_sample.items():
                series[role].append((sample["t_ms"], rss))
    return {
        role: {"bytes_per_minute": _slope(points), "samples": len(points)}
        for role, points in sorted(series.items())
        if len(points) >= 8
    }


def _slope(points: Sequence[tuple[float, int]]) -> float:
    mean_x = statistics.fmean(x for x, _ in points)
    mean_y = statistics.fmean(y for _, y in points)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in points)
    denominator = sum((x - mean_x) ** 2 for x, _ in points) or 1.0
    return numerator / denominator * 60_000.0


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    try:
        stream = path.open(encoding="utf-8")
    except OSError:
        return
    with stream:
        for line in stream:
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict):
                yield value


def write_session_summary(run_dir: Path, analysis: Mapping[str, Any], destination: Path) -> Path:
    lines = [
        f"# Session resources `{analysis['run']}`", "",
        "RSS sampled every 250 ms by the session's external sampler. Family totals sum",
        "RSS across processes and double-count shared pages: an upper bound, not a total.",
        "RSS also falls when macOS compresses idle pages, so idle figures understate what",
        "a process holds; `lab resources stages` measures physical footprint instead.", "",
        "Each role is totalled per sample; a role may be several processes.", "",
        "| phase | samples | role | peak | sustained (median) | last |",
        "|---|---|---|---|---|---|",
    ]
    for phase, data in analysis["phases"].items():
        for role, values in data["roles"].items():
            lines.append(
                f"| {phase} | {data['samples']} | {role} | {_mib(values['peak'])} "
                f"| {_mib(values['sustained_median'])} | {_mib(values['last'])} |"
            )
    lines += ["", "| role | growth from ready to stop |", "|---|---|"]
    for role, growth in analysis["growth"].items():
        rate = growth["bytes_per_minute"] / 2**20
        lines.append(f"| {role} | {rate:+.2f} MiB/min ({growth['samples']} samples) |")
    duplicates_found = analysis["duplicates"]
    listed = ", ".join(f"{role} ×{count}" for role, count in duplicates_found.items())
    lines += ["", "- Duplicate processes in one role: " + (listed or "none")]
    after = analysis["after_stop"]
    if after.get("observed"):
        lines.append("- Still running after `desktop_stopped`: "
                     + (", ".join(after["surviving_roles"]) or "nothing"))
    else:
        lines.append(
            "- The session never recorded `desktop_stopped`; release at exit is unobserved."
        )
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return destination


def _mib(value: float | None) -> str:
    return "n/a" if value is None else f"{value / 2**20:.1f} MiB"
