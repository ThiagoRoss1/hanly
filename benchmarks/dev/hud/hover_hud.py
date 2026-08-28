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
from PyQt6.QtCore import QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter, QPaintEvent, QPen
from PyQt6.QtWidgets import QWidget

from .capture_exclusion import exclude_from_capture

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
_MARGIN = 16
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


class HoverHUD(QWidget):
    """Always-on-top panel showing the live and recent hover timelines.

    Trace events arrive on the mouse listener, worker, and UI threads, so they
    are only queued here. A timer drains the queue on the UI thread, which
    keeps every Qt call on the thread Qt requires without adding a second
    cross-thread signalling path to the application.
    """

    #: Opts this sink into the region geometry the OCR trace can carry, which
    #: the ROI schematic draws. It stays off by default because it describes
    #: where text sits on someone's screen.
    retain_geometry = True

    def __init__(self, *, dwell_ms: int, backend: str) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        # Deliberately opaque: Windows refuses to exclude a layered window
        # from screen capture, and an overlay that is captured feeds its own
        # pixels back into the OCR it is supposed to be reporting on.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(_WIDTH, _HEIGHT)

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

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._drain)
        self._timer.start(_REFRESH_MS)

    def emit(self, event: Any) -> object:
        """Queue one trace event from whichever thread produced it."""

        with self._lock:
            self._pending.append(dict(event))
        return None

    def place_top_right(self, screen_width: int, screen_height: int) -> None:
        """Park the overlay clear of the cursor's usual working area."""

        del screen_height
        self.move(max(0, screen_width - _WIDTH - _MARGIN), _MARGIN)

    def hide_from_capture(self) -> bool:
        """Ask the compositor to keep this window out of screen captures."""

        return exclude_from_capture(int(self.winId()))

    def _drain(self) -> None:
        with self._lock:
            events = list(self._pending)
            self._pending.clear()
        if not events:
            return
        for event in events:
            self._apply(event)
        self.update()

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

    def paintEvent(self, a0: QPaintEvent | None) -> None:
        del a0
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(17, 19, 24))

        self._paint_header(painter)
        self._paint_timeline(painter)
        self._paint_outcome(painter)
        self._paint_summary(painter)
        self._paint_roi_map(painter)
        painter.end()

    def _paint_header(self, painter: QPainter) -> None:
        painter.setFont(_font(11, bold=True))
        painter.setPen(QColor("#e5e7eb"))
        painter.drawText(14, 24, "HANLY HOVER")

        painter.setFont(_font(9))
        painter.setPen(QColor("#9ca3af"))
        state = "ready" if self._worker_ready else "warming"
        painter.drawText(14, 42, f"{self._backend} · dwell {self._dwell_ms} ms · {state}")

        if self._ocr_running:
            painter.setPen(QColor("#eb6834"))
            painter.setFont(_font(9, bold=True))
            painter.drawText(_WIDTH - 96, 24, "● OCR RUNNING")

    def _paint_timeline(self, painter: QPainter) -> None:
        attempt = self._current or self._last
        top = 58.0
        if attempt is None:
            painter.setFont(_font(9))
            painter.setPen(QColor("#6b7280"))
            painter.drawText(14, int(top) + 14, "waiting for a hover…")
            return

        # Scale against the busiest recent hover so bars stay comparable with
        # each other while still filling the width. A fixed ceiling left a
        # cached lookup drawn as a sliver against mostly empty space.
        busiest = max(
            [item.measured_ms for item in self._history] + [attempt.measured_ms]
        )
        scale = (_WIDTH - 28) / max(_MIN_TIMELINE_MS, busiest)
        left = 14.0
        for stage, color in _STAGES:
            duration = attempt.stages.get(stage)
            if duration is None:
                continue
            width = max(2.0, duration * scale)
            painter.fillRect(
                QRectF(left, top, width, 18.0),
                QColor(color if stage != "ocr" or not attempt.ocr_cached else "#22c55e"),
            )
            left += width

        painter.setFont(_font(8))
        row = int(top) + 34
        for stage, color in _STAGES:
            duration = attempt.stages.get(stage)
            if duration is None or duration < 0.05:
                continue
            painter.setPen(QColor(color))
            label = f"{stage} {duration:.1f}"
            if stage == "ocr" and attempt.ocr_cached:
                label = f"{stage} cached"
            painter.drawText(14, row, label)
            row += 13

    def _paint_outcome(self, painter: QPainter) -> None:
        attempt = self._last
        if attempt is None:
            return
        painter.setFont(_font(10, bold=True))
        painter.setPen(QColor(_status_color(attempt.status)))
        painter.drawText(180, 106, attempt.status or "—")

        painter.setFont(_font(9))
        painter.setPen(QColor("#9ca3af"))
        if attempt.note:
            painter.drawText(180, 124, attempt.note)
        if attempt.total_ms is not None:
            total = f"total {attempt.total_ms:.1f} ms"
            if attempt.retried:
                total += "  (keener retry)"
            painter.drawText(180, 142, total)

    def _paint_roi_map(self, painter: QPainter) -> None:
        """Draw the last ROI to scale, with the regions found inside it.

        This lives in the panel rather than over the screen because anything
        painted on the captured area is composited into the next capture of it.
        """

        attempt = self._last
        if attempt is None:
            return

        roi_width, roi_height = attempt.roi
        scale = min(_MAP_WIDTH / roi_width, _MAP_HEIGHT / roi_height)
        width, height = int(roi_width * scale), int(roi_height * scale)
        painter.setPen(QColor("#4b5563"))
        painter.drawRect(_MAP_X, _MAP_Y, width, height)

        painter.setFont(_font(7))
        for order, (left, top, right, bottom) in enumerate(attempt.boxes, start=1):
            painter.setPen(QColor(_REGION_COLOR))
            box_x = _MAP_X + int(left * scale)
            box_y = _MAP_Y + int(top * scale)
            painter.drawRect(
                box_x,
                box_y,
                max(1, int((right - left) * scale)),
                max(1, int((bottom - top) * scale)),
            )
            painter.drawText(box_x + 1, box_y - 1, str(order))

        if attempt.cursor is not None:
            painter.setPen(QPen(QColor(_CURSOR_COLOR), 2))
            x = _MAP_X + int(attempt.cursor[0] * scale)
            y = _MAP_Y + int(attempt.cursor[1] * scale)
            painter.drawLine(x - 4, y, x + 4, y)
            painter.drawLine(x, y - 4, x, y + 4)

        painter.setFont(_font(8))
        painter.setPen(QColor("#6b7280"))
        painter.drawText(
            _MAP_X + width + 12,
            _MAP_Y + 12,
            f"roi {roi_width}x{roi_height}",
        )
        painter.drawText(
            _MAP_X + width + 12,
            _MAP_Y + 26,
            f"{len(attempt.boxes)} region(s) read",
        )

    def _paint_summary(self, painter: QPainter) -> None:
        painter.setPen(QColor("#374151"))
        painter.drawLine(14, 176, _WIDTH - 14, 176)

        totals = [item.total_ms for item in self._history if item.total_ms is not None]
        painter.setFont(_font(9))
        painter.setPen(QColor("#9ca3af"))
        summary = f"last {len(self._history)}"
        if totals:
            summary += f" · p50 {median(totals):.0f} ms"
        if self._ocr_calls:
            summary += f" · ocr cache {self._ocr_hits}/{self._ocr_calls}"
        painter.drawText(14, 196, summary)

        # One glyph per recent attempt: the shape of a run is readable at a
        # glance in a way a column of status words is not.
        history = [item for item in self._history if item.status]
        if history:
            painter.drawText(14, 214, "recent")
            left = 68
            for item in history[-24:]:
                painter.setPen(QColor(_status_color(item.status)))
                painter.drawText(left, 214, _status_glyph(item.status))
                left += 13

        painter.setPen(QColor("#6b7280"))
        painter.drawText(14, 236, self._resources.summary())


class _ProcessResources:
    """Report this process's own CPU and memory, when psutil is installed.

    CPU is expressed in whole cores rather than as a percentage of the machine,
    because that is what predicts behavior on a weaker one: a lookup that keeps
    2.0 cores busy has no headroom left on a dual-core laptop. The backend runs
    CPU-only by construction, so there is no GPU figure to report.
    """

    def __init__(self) -> None:
        self._process: Any | None = None
        try:
            import psutil

            self._process = psutil.Process()
            self._process.cpu_percent(None)
        except Exception:
            self._process = None

    def summary(self) -> str:
        process = self._process
        if process is None:
            return "cpu n/a (psutil)"
        try:
            cores = process.cpu_percent(None) / 100.0
            rss_mb = process.memory_info().rss / 1e6
            threads = process.num_threads()
        except Exception:
            return "cpu n/a"
        return f"{cores:.1f} cores · {rss_mb:.0f} MB · {threads} thr"


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


def _font(size: int, *, bold: bool = False) -> QFont:
    font = QFont("Consolas", size)
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setBold(bold)
    return font


__all__ = ["HoverHUD"]
