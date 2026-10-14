"""On-screen panel showing what one hover actually did.

A :class:`~hanly_app.runtime_trace.RuntimeTraceSink` that draws events instead
of recording them, so "why did nothing appear when I hovered that word" has a
visible answer.

Transparent to mouse input so it cannot change the behavior it reports.
"""

from __future__ import annotations

from collections import deque
from statistics import median
from threading import Lock
from typing import Any, Final

from hanly_app.runtime_trace import JSONPrimitive
from PIL import Image, ImageDraw

from ..session.raster_fonts import available_fonts, load_font
from ..session.raster_ui import ImageWindow, Rect, UIHost

# Stage order is the order work actually happens in, which is also the order
# the timeline bar is drawn in.
_STAGES: Final[tuple[tuple[str, str], ...]] = (
    ("dwell", "#8b93a1"),
    ("capture", "#3b82f6"),
    ("ocr", "#eb6834"),
    ("token_selection", "#a855f7"),
    ("morphology", "#22c55e"),
    ("dictionary", "#eab308"),
)
_STAGE_COLORS: Final[dict[str, str]] = dict(_STAGES)
_HISTORY = 20
_REFRESH_MS = 50
_WIDTH = 430
_HEIGHT = 344
# Floor for the timeline scale, so one very fast hover cannot magnify
# sub-millisecond stages into a full-width bar.
_MIN_TIMELINE_MS = 40.0
_REGION_COLOR = "#4ade80"
_CURSOR_COLOR = "#facc15"
# The ROI schematic: the captured region to scale, inside the panel.
_MAP_X = 14
_MAP_Y = 252
_MAP_WIDTH = 150
_MAP_HEIGHT = 76


class _Attempt:
    """One hover attempt, accumulated as its trace events arrive."""

    def __init__(self, hover_request_id: int | None) -> None:
        self.hover_request_id = hover_request_id
        self.stages: dict[str, float] = {}
        self.status: str | None = None
        self.word: str | None = None
        self.note: str | None = None
        self.ocr_cached = False
        self.lookup_cached = False
        self.total_ms: float | None = None
        self.region_count: int | None = None
        self.candidate_count: int | None = None
        self.hangul_regions: int | None = None
        self.resolved: bool | None = None
        self.retried = False
        self.boxes: tuple[tuple[int, int, int, int], ...] = ()
        self.roi: tuple[int, int] = (200, 100)
        self.cursor: tuple[float, float] | None = None

    @property
    def measured_ms(self) -> float:
        return sum(self.stages.values())


class HoverHUD:
    """Always-on-top panel showing the live and recent hover timelines.

    Trace events arrive on the mouse listener, worker, and UI threads, so they
    are queued and rendered on Lab's native window thread.
    """

    #: Opts this sink into the region geometry the OCR trace can carry, which
    #: the ROI schematic draws. It stays off by default because it describes
    #: where text sits on someone's screen.
    retain_geometry = True

    def __init__(self, ui: UIHost, *, dwell_ms: int, backend: str) -> None:
        self._ui = ui
        self._scale = ui.geometry.display_scale
        desktop = ui.geometry.bounds
        local_bounds = Rect(
            desktop.width - _WIDTH - 18,
            18,
            _WIDTH,
            _HEIGHT,
        )
        self._window: ImageWindow = ui.create_window(
            ui.geometry.to_window(local_bounds), ignore_mouse=True
        )
        self._fonts = available_fonts(
            ("Menlo", "Consolas", "Noto Sans Mono", "Apple SD Gothic Neo", "Malgun Gothic")
        )
        self._dwell_ms = dwell_ms
        self._backend = backend
        self._lock = Lock()
        self._pending: deque[dict[str, JSONPrimitive]] = deque(maxlen=512)
        self._current: _Attempt | None = None
        self._last: _Attempt | None = None
        self._history: deque[_Attempt] = deque(maxlen=_HISTORY)
        self._ocr_running = False
        self._ocr_hits = 0
        self._ocr_calls = 0
        self._worker_ready = False
        self._resources = _ProcessResources()
        self._closed = False
        self._refresh()
        self._schedule_drain()

    def emit(self, event: Any) -> object:
        """Queue one trace event from whichever thread produced it."""

        with self._lock:
            self._pending.append(dict(event))
        return None

    def _drain(self) -> None:
        if self._closed:
            return
        with self._lock:
            events = list(self._pending)
            self._pending.clear()
        for event in events:
            self._apply(event)
        if events:
            self._refresh()
        self._schedule_drain()

    def _apply(self, event: dict[str, JSONPrimitive]) -> None:
        kind = event.get("event_kind")
        if kind == "hover_stable_fire":
            hover_id = event.get("hover_request_id")
            self._current = _Attempt(hover_id if isinstance(hover_id, int) else None)
            self._current.stages["dwell"] = float(self._dwell_ms)
            return
        if kind == "executor_work_started":
            self._ocr_running = self._current is not None
            return
        if kind == "provider_prewarm_completed":
            self._worker_ready = True
            return
        if kind == "ocr_sensitive_retry":
            if self._current is not None:
                self._current.retried = True
            return

        attempt = self._current
        if attempt is None:
            return

        if kind == "hover_capture_completed":
            attempt.stages["capture"] = _milliseconds(event)
            width = _count(event.get("roi_width"))
            height = _count(event.get("roi_height"))
            if width and height:
                attempt.roi = (width, height)
            target_x = event.get("target_x")
            target_y = event.get("target_y")
            if isinstance(target_x, (int, float)) and isinstance(target_y, (int, float)):
                attempt.cursor = (float(target_x), float(target_y))
        elif kind == "lookup_cache_hit":
            attempt.lookup_cached = True
            attempt.status = _text(event.get("result_status"))
        elif kind == "lookup_stage_completed":
            stage = _text(event.get("stage"))
            if stage in _STAGE_COLORS:
                attempt.stages[stage] = _milliseconds(event)
            if stage == "ocr":
                self._ocr_running = False
                attempt.ocr_cached = event.get("ocr_cached") is True
                attempt.region_count = _count(event.get("region_count"))
                attempt.hangul_regions = _count(event.get("hangul_region_count"))
                attempt.boxes = _decode_boxes(event.get("ocr_boxes"))
                self._ocr_calls += 1
                self._ocr_hits += int(attempt.ocr_cached)
            elif stage == "token_selection":
                attempt.resolved = event.get("resolved") is True
                attempt.candidate_count = _count(event.get("candidate_count"))
        elif kind == "lookup_stage_error":
            self._ocr_running = False
            attempt.note = f"{_text(event.get('stage'))} error"
        elif kind == "hover_capture_error":
            attempt.note = "capture failed"
            self._finish(attempt)
        elif kind == "hover_stale_after_capture":
            attempt.note = "superseded by movement"
            self._finish(attempt)
        elif kind == "total_pipeline":
            attempt.total_ms = _milliseconds(event)
            attempt.status = _text(event.get("outcome")) or attempt.status
        elif kind in {"popup_visible", "popup_suppressed"}:
            attempt.status = _text(event.get("result_status")) or attempt.status
            if kind == "popup_suppressed" and attempt.note is None:
                attempt.note = _suppression_note(attempt)
            self._finish(attempt)

    def _finish(self, attempt: _Attempt) -> None:
        self._ocr_running = False
        self._last = attempt
        self._history.append(attempt)
        self._current = None

    def _schedule_drain(self) -> None:
        if not self._closed:
            self._ui.call_later(_REFRESH_MS, self._drain)

    def _refresh(self) -> None:
        scale = self._scale
        image = Image.new("RGB", (round(_WIDTH * scale), round(_HEIGHT * scale)), "#111318")
        draw = ImageDraw.Draw(image)

        def text(
            x: float, y: float, value: str, size: int, color: str, *, bold: bool = False
        ) -> None:
            font = load_font(self._fonts[0], round(size * scale))
            draw.text(
                (round(x * scale), round(y * scale)),
                value,
                font=font,
                fill=color,
                anchor="ls",
                stroke_width=1 if bold else 0,
            )

        text(14, 24, "HANLY HOVER", 11, "#e5e7eb", bold=True)
        state = "ready" if self._worker_ready else "warming"
        text(14, 42, f"{self._backend} · dwell {self._dwell_ms} ms · {state}", 9, "#9ca3af")
        if self._ocr_running:
            text(_WIDTH - 96, 24, "● OCR RUNNING", 9, "#eb6834", bold=True)

        attempt = self._current or self._last
        top = 58.0
        if attempt is None:
            text(14, top + 14, "waiting for a hover…", 9, "#6b7280")
        else:
            busiest = max([item.measured_ms for item in self._history] + [attempt.measured_ms])
            timeline_scale = (_WIDTH - 28) / max(_MIN_TIMELINE_MS, busiest)
            left = 14.0
            for stage, color in _STAGES:
                duration = attempt.stages.get(stage)
                if duration is None:
                    continue
                width = max(2.0, duration * timeline_scale)
                fill = color if stage != "ocr" or not attempt.ocr_cached else "#22c55e"
                draw.rectangle(
                    (
                        round(left * scale),
                        round(top * scale),
                        round((left + width) * scale),
                        round((top + 18) * scale),
                    ),
                    fill=fill,
                )
                left += width
            row = int(top) + 46
            for stage, color in _STAGES:
                duration = attempt.stages.get(stage)
                if duration is None or duration < 0.05:
                    continue
                label = (
                    f"{stage} cached"
                    if stage == "ocr" and attempt.ocr_cached
                    else f"{stage} {duration:.1f}"
                )
                text(14, row, label, 8, color)
                row += 13

        last = self._last
        if last is not None:
            text(180, 106, last.status or "—", 10, _status_color(last.status), bold=True)
            if last.note:
                text(180, 124, last.note, 9, "#9ca3af")
            if last.total_ms is not None:
                total = f"total {last.total_ms:.1f} ms"
                if last.retried:
                    total += "  (keener retry)"
                text(180, 142, total, 9, "#9ca3af")
            self._draw_roi(draw, text, last, scale)

        draw.line((14 * scale, 176 * scale, (_WIDTH - 14) * scale, 176 * scale), fill="#374151")
        totals = [item.total_ms for item in self._history if item.total_ms is not None]
        summary = f"last {len(self._history)}"
        if totals:
            summary += f" · p50 {median(totals):.0f} ms"
        if self._ocr_calls:
            summary += f" · ocr cache {self._ocr_hits}/{self._ocr_calls}"
        text(14, 196, summary, 9, "#9ca3af")
        history = [item for item in self._history if item.status]
        if history:
            text(14, 214, "recent", 8, "#9ca3af")
            left = 68
            for item in history[-24:]:
                text(left, 214, _status_glyph(item.status), 8, _status_color(item.status))
                left += 13
        text(14, 236, self._resources.summary(), 8, "#6b7280")
        self._window.set_image(image)

    def _draw_roi(
        self, draw: ImageDraw.ImageDraw, text: Any, attempt: _Attempt, scale: float
    ) -> None:
        roi_width, roi_height = attempt.roi
        ratio = min(_MAP_WIDTH / roi_width, _MAP_HEIGHT / roi_height)
        width, height = int(roi_width * ratio), int(roi_height * ratio)
        draw.rectangle(
            (_MAP_X * scale, _MAP_Y * scale, (_MAP_X + width) * scale, (_MAP_Y + height) * scale),
            outline="#4b5563",
            width=max(1, round(scale)),
        )
        for order, (left, top, right, bottom) in enumerate(attempt.boxes, start=1):
            box_x = _MAP_X + int(left * ratio)
            box_y = _MAP_Y + int(top * ratio)
            draw.rectangle(
                (
                    box_x * scale,
                    box_y * scale,
                    (_MAP_X + int(right * ratio)) * scale,
                    (_MAP_Y + int(bottom * ratio)) * scale,
                ),
                outline=_REGION_COLOR,
                width=max(1, round(scale)),
            )
            text(box_x + 1, box_y - 1, str(order), 7, _REGION_COLOR)
        if attempt.cursor is not None:
            x = _MAP_X + int(attempt.cursor[0] * ratio)
            y = _MAP_Y + int(attempt.cursor[1] * ratio)
            draw.line(
                ((x - 4) * scale, y * scale, (x + 4) * scale, y * scale),
                fill=_CURSOR_COLOR,
                width=max(1, round(scale * 2)),
            )
            draw.line(
                (x * scale, (y - 4) * scale, x * scale, (y + 4) * scale),
                fill=_CURSOR_COLOR,
                width=max(1, round(scale * 2)),
            )
        text(_MAP_X + width + 12, _MAP_Y + 12, f"roi {roi_width}x{roi_height}", 8, "#6b7280")
        text(_MAP_X + width + 12, _MAP_Y + 26, f"{len(attempt.boxes)} region(s) read", 8, "#6b7280")

    def show(self) -> None:
        self._window.show()

    def close(self) -> None:
        self._closed = True
        self._window.close()


class _ProcessResources:
    """Avoid presenting the Lab HUD process as Hanly resource usage."""

    def summary(self) -> str:
        return "native family samples · Lab report"


def _decode_boxes(value: JSONPrimitive) -> tuple[tuple[int, int, int, int], ...]:
    """Parse the ``l,t,r,b;l,t,r,b`` form the OCR trace carries."""

    if not isinstance(value, str) or not value:
        return ()
    boxes: list[tuple[int, int, int, int]] = []
    for group in value.split(";"):
        parts = group.split(",")
        if len(parts) != 4:
            continue
        try:
            left, top, right, bottom = (int(part) for part in parts)
        except ValueError:
            continue
        boxes.append((left, top, right, bottom))
    return tuple(boxes)


def _milliseconds(event: dict[str, JSONPrimitive]) -> float:
    duration = event.get("duration_ns")
    return float(duration) / 1e6 if isinstance(duration, (int, float)) else 0.0


def _text(value: JSONPrimitive) -> str | None:
    return value if isinstance(value, str) and value else None


def _count(value: JSONPrimitive) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _suppression_note(attempt: _Attempt) -> str:
    """Explain a suppressed popup in the terms the person hovering cares about.

    UNUSABLE covers three unrelated failures, and telling them apart is the
    whole reason this overlay exists. The distinction is reconstructed from
    trace fields rather than from the pipeline's diagnostics text, which can
    embed recognized characters.
    """

    status = attempt.status
    if status == "not_found":
        return "word read, not in the dictionary"
    if status == "empty":
        return "no text detected in the ROI"
    if status == "error":
        return "pipeline error"
    if status != "unusable":
        return "no popup"

    if attempt.resolved is False:
        candidates = attempt.candidate_count
        if candidates == 0:
            return "no region under the cursor"
        return f"cursor resolved to no word ({candidates} region(s))"
    if attempt.hangul_regions == 0:
        return "text found, but no Hangul"
    return "no usable lemma for that word"


def _status_glyph(status: str | None) -> str:
    if status == "success":
        return "●"
    if status in {"error", None}:
        return "✕"
    return "○"


def _status_color(status: str | None) -> str:
    if status == "success":
        return "#22c55e"
    if status in {"error", None}:
        return "#ef4444"
    return "#eab308"


__all__ = ["HoverHUD"]
