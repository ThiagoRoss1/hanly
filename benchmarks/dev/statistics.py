"""Warm-success latency summaries for benchmark measurement records."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from statistics import median
from typing import Any


class StatisticsError(ValueError):
    """Raised when measurements cannot produce a valid summary."""


def summarize(
    samples: Iterable[Mapping[str, Any]],
    *,
    condition: str = "warm",
    success_statuses: Iterable[str] = ("success",),
    duration_key: str = "duration_ns",
) -> dict[str, Any]:
    """Summarize only successful samples for the requested condition.

    ``p95`` uses nearest-rank selection: rank ``ceil(0.95 * n)`` in the
    ascending values, with no interpolation.
    """

    if condition not in {"cold", "warmup", "warm"}:
        raise StatisticsError("condition must be cold, warmup, or warm")
    statuses = {status.casefold() for status in success_statuses}
    if not statuses:
        raise StatisticsError("at least one successful correctness status is required")

    durations: list[int | float] = []
    for index, sample in enumerate(samples):
        if not isinstance(sample, Mapping):
            raise StatisticsError(f"sample {index} must be a mapping")
        if sample.get("condition") != condition:
            continue
        if "correctness_status" not in sample:
            raise StatisticsError(f"sample {index} is missing correctness_status")
        status = sample["correctness_status"]
        if not isinstance(status, str):
            raise StatisticsError(f"sample {index} correctness_status must be a string")
        if status.casefold() not in statuses:
            continue
        if duration_key not in sample:
            raise StatisticsError(f"sample {index} is missing {duration_key}")
        duration = sample[duration_key]
        if isinstance(duration, bool) or not isinstance(duration, (int, float)):
            raise StatisticsError(f"sample {index} {duration_key} must be numeric")
        if not math.isfinite(duration) or duration < 0:
            raise StatisticsError(f"sample {index} {duration_key} must be finite and non-negative")
        durations.append(duration)

    if not durations:
        raise StatisticsError(
            f"no {condition} successful samples are available for summary"
        )

    ordered = sorted(durations)
    nearest_rank = max(1, math.ceil(0.95 * len(ordered)))
    return {
        "evidence_class": "derived",
        "count": len(ordered),
        "min": min(ordered),
        "max": max(ordered),
        "mean": sum(ordered) / len(ordered),
        "p50": median(ordered),
        "p95": ordered[nearest_rank - 1],
        "duration_unit": "ns",
    }
