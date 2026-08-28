"""Deterministic OCR-invocation-rate scenarios over Hanly's hover decision seam."""

from __future__ import annotations

import heapq
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from hanly import Point
from hanly_app.hover_controller import HoverController


@dataclass
class _Handle:
    callback: Callable[[], None]
    cancelled: bool = False

    def cancel(self) -> None:
        self.cancelled = True


class _VirtualScheduler:
    def __init__(self) -> None:
        self.now_ms = 0.0
        self._next_id = 0
        self._queue: list[tuple[float, int, _Handle]] = []

    def __call__(self, delay_ms: float, callback: Callable[[], None]) -> _Handle:
        handle = _Handle(callback)
        self._next_id += 1
        heapq.heappush(
            self._queue,
            (self.now_ms + delay_ms, self._next_id, handle),
        )
        return handle

    def advance_to(self, target_ms: float) -> None:
        while self._queue and self._queue[0][0] <= target_ms:
            due, _sequence, handle = heapq.heappop(self._queue)
            self.now_ms = due
            if not handle.cancelled:
                handle.callback()
        self.now_ms = target_ms


def simulate_ocr_invocations(
    events: Sequence[tuple[float, Point]],
    *,
    duration_ms: float,
    dwell_ms: float = 150.0,
) -> dict[str, Any]:
    """Count calls at the exact stable-handler boundary that triggers OCR."""

    scheduler = _VirtualScheduler()
    invocations = 0

    def invoke_ocr(_request: Any) -> None:
        nonlocal invocations
        invocations += 1

    hover = HoverController(
        invoke_ocr,
        delay_ms=dwell_ms,
        scheduler=scheduler,
        dispatcher=lambda callback: callback(),
    )
    for timestamp_ms, point in events:
        if timestamp_ms < scheduler.now_ms or timestamp_ms > duration_ms:
            raise ValueError("event timestamps must be ordered inside the observation window")
        scheduler.advance_to(timestamp_ms)
        hover.on_position(point)
    scheduler.advance_to(duration_ms)
    hover.shutdown()

    return {
        "events": len(events),
        "duration_ms": duration_ms,
        "configured_dwell_ms": dwell_ms,
        "ocr_invocations": invocations,
        "invocations_per_second": invocations / (duration_ms / 1000),
    }


def hover_invocation_matrix(*, dwell_ms: float = 150.0) -> dict[str, dict[str, Any]]:
    """Return the required idle/jitter/text/repeat/non-text campaign matrix."""

    return {
        "idle": simulate_ocr_invocations((), duration_ms=1_000, dwell_ms=dwell_ms),
        "small_mouse_jitter": simulate_ocr_invocations(
            tuple((index * 30.0, Point(100 + index % 2, 100)) for index in range(8)),
            duration_ms=500,
            dwell_ms=dwell_ms,
        ),
        "movement_across_text": simulate_ocr_invocations(
            tuple((index * 30.0, Point(20 + index * 12, 100)) for index in range(12)),
            duration_ms=700,
            dwell_ms=dwell_ms,
        ),
        "repeated_hover_same_word": simulate_ocr_invocations(
            tuple((index * 250.0, Point(100, 100)) for index in range(5)),
            duration_ms=1_250,
            dwell_ms=dwell_ms,
        ),
        "movement_across_non_text": simulate_ocr_invocations(
            tuple((index * 250.0, Point(20 + index * 25, 300)) for index in range(5)),
            duration_ms=1_250,
            dwell_ms=dwell_ms,
        ),
    }


__all__ = ["hover_invocation_matrix", "simulate_ocr_invocations"]
