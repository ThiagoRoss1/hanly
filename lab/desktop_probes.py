"""Read-only monitor enumeration and ROI capture measurements."""

from __future__ import annotations

from collections.abc import Callable
from time import perf_counter_ns
from typing import Any

from hanly import Point

from .statistics import summarize


def measure_capture_service(
    service: Any,
    *,
    cursor: Point,
    enumeration_samples: int = 100,
    capture_samples: int = 30,
    clock: Callable[[], int] = perf_counter_ns,
) -> dict[str, Any]:
    """Measure existing capture calls without retaining captured pixels."""

    if enumeration_samples <= 0 or capture_samples <= 0:
        raise ValueError("capture probe sample counts must be positive")
    measurements: list[dict[str, Any]] = []
    monitor_count: int | None = None
    capture_shape: list[int] | None = None

    for iteration in range(enumeration_samples):
        started = clock()
        monitors = tuple(service.enumerate_monitors())
        duration = clock() - started
        monitor_count = len(monitors)
        measurements.append(
            {
                "stage": "monitor_enumeration",
                "iteration": iteration,
                "condition": "warm",
                "correctness_status": "success",
                "duration_ns": duration,
            }
        )

    for iteration in range(capture_samples):
        started = clock()
        result = service.capture_at_cursor(cursor)
        duration = clock() - started
        capture_shape = [result.image.width, result.image.height, len(result.image.data)]
        measurements.append(
            {
                "stage": "capture",
                "iteration": iteration,
                "condition": "warm",
                "correctness_status": "success",
                "duration_ns": duration,
            }
        )

    return {
        "schema_version": 1,
        "cursor": {"x": cursor.x, "y": cursor.y},
        "monitor_count": monitor_count,
        "capture_shape": capture_shape,
        "summaries": {
            stage: summarize(
                [sample for sample in measurements if sample["stage"] == stage]
            )
            for stage in ("monitor_enumeration", "capture")
        },
        "measurements": measurements,
    }


__all__ = ["measure_capture_service"]
