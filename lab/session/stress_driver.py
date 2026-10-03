"""Drive a stress campaign: the tour's hover, plus the behaviours that break it.

Beyond a plain dwell the driver can cross other words quickly before settling
(``rapid``), leave right after the lookup was submitted so its answer arrives
late (``leave_early``), change the word under a pointer that stays put
(``changing``), rest on the spot where the previous answer was shown
(``after_popup``), hover a page another window covers (``covered``), and hover
real accessible text in a separate lab-owned window (``uia_*``).

Ownership is the tour's: the lab's own windows, plus the UIA helper window the
lab started, may be read; anything else makes the hover unscored.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QPoint, QRect

from .browser_text import BrowserText
from .driver import TourDriver, _Observation, outcome_record
from .ownership import owner_at
from .recorder import LabRecorder
from .stress import StressItem
from .stress_page import StressPage, StressPlaced
from .stress_scoring import RULE, failing_stage, stress_verdict

#: How long a ``leave_early`` hover waits for its lookup to be submitted.
_SUBMIT_WAIT = 2.0
#: How long the driver keeps listening after leaving, for an answer that is late.
_LATE_WINDOW = 1.5
_RAPID_STEP_S = 0.004
#: Lines per browser window: every capture region around them stays inside it.
_UIA_LINES = 6


class StressDriver(TourDriver):
    """Run every page of a stress plan, then the UIA segment, on one thread."""

    def __init__(
        self,
        recorder: LabRecorder,
        page: StressPage,
        uia_items: list[StressItem],
        *,
        capture_hotkey: str,
        run_dir: Path,
        retain_fixture_text: bool,
        retain_fixture_images: bool,
    ) -> None:
        super().__init__(
            recorder,
            page,
            capture_hotkey=capture_hotkey,
            retain_fixture_text=retain_fixture_text,
        )
        self._stress_page = page
        self._uia_items = uia_items
        self._run_dir = run_dir
        self._retain_images = retain_fixture_images
        self._allowed: set[int] = set()
        self._last_popup: QRect | None = None
        self._page_index = 0
        #: Where the pointer rests while the tour page is hidden; ``None`` uses the page.
        self._rest_override: tuple[int, int] | None = None
        # Read once on the Qt thread that built the page.
        self._page_handle = int(page.winId())

    # -- the run ------------------------------------------------------------------

    def run(self) -> None:
        from .driver import ensure_capture

        self._recorder.lab("tour_waiting_for_runtime")
        if not self._ready.wait(180):
            self._recorder.lab("tour_aborted", reason="runtime_never_ready")
            return
        self._page.show_page(0)
        time.sleep(0.4)
        how = ensure_capture(self._observing, self._press_capture_hotkey)
        self._recorder.lab("tour_capture", how=how, hotkey=self._capture_hotkey)
        if how == "never_started":
            self._recorder.lab("tour_aborted", reason="capture_never_started")
            return
        first = True
        for index, page in enumerate(self._page.pages):
            self._page_index = index
            if not self._page.show_page(index):
                self._recorder.lab("tour_aborted", reason="page_not_painted", page=index)
                return
            cover = self._start_cover() if index == self._stress_page.covered_page else None
            try:
                time.sleep(0.25)
                self._recorder.lab(
                    "tour_page", page=index, theme=page.theme, targets=len(page.placed)
                )
                self._move_to(self._page.to_global(page.rest))
                for placed in page.placed:
                    if self._user_moved() or not self._one(placed, index, first):
                        self._stopped()
                        return
                    first = False
            finally:
                if cover is not None:
                    _stop(cover)
        if not self._uia_segment():
            self._stopped()
            return
        self._recorder.lab("tour_finished", completed=self.completed)

    def _stopped(self) -> None:
        self.stopped_by_user = True
        self._recorder.lab("tour_stopped_by_user", completed=self.completed)

    def _one(self, placed: Any, page: int, first: bool) -> bool:
        item: StressItem | None = getattr(placed, "item", None)
        behavior = item.behavior if item is not None else "dwell"
        if item is not None and item.family == "after_popup":
            placed = self._at_previous_popup(placed)
        if behavior == "rapid":
            self._cross(placed)
        if behavior in {"leave_early", "changing"}:
            done = self._special(placed, page, behavior)
        else:
            done = self._hover(placed, page, first)
        if not done:
            return False
        self._last_popup = _own_popup_rect(self._page_handle)
        self._move_to(self._page.to_global(self._page.pages[page].rest))
        self._popup_hidden.clear()
        self._popup_hidden.wait(0.8)
        return True

    # -- behaviours ---------------------------------------------------------------

    def _cross(self, placed: StressPlaced) -> None:
        """Sweep over earlier cells faster than the dwell, then let the hover settle."""

        for point in placed.approach:
            x, y = self._page.to_global(point)
            self._set(x, y)
            time.sleep(_RAPID_STEP_S)

    def _at_previous_popup(self, placed: StressPlaced) -> StressPlaced:
        """Rest where the last answer was shown, if that spot is still on blank page."""

        rect = self._last_popup
        if rect is None:
            return placed
        origin = self._page.geometry().topLeft()
        centre = rect.center() - origin
        if not self._page.rect().contains(centre) or self._over_text(centre):
            return placed
        return replace(placed, point=centre, word=QRect(centre.x() - 1, centre.y() - 1, 2, 2))

    def _restore_page(self, page: int) -> None:
        # While the browser is read the page stays out of its way.
        if self._rest_override is None:
            super()._restore_page(page)

    def _over_text(self, point: QPoint) -> bool:
        placed = self._page.pages[self._page_index].placed
        return any(item.word.adjusted(-30, -20, 30, 20).contains(point) for item in placed)

    def _special(self, placed: StressPlaced, page: int, behavior: str) -> bool:
        x, y = self._page.to_global(placed.point)
        foreign = self._foreign_windows(x, y)
        if foreign:
            self._page.show_page(page)
            self._finish(placed, _Observation(), 0, unscored="obscured", foreign=foreign)
            return True
        observation = _Observation()
        with self._lock:
            self._active = observation
        self._glide(x, y)
        arrived = time.perf_counter_ns()
        self._target_event(placed, page, x, y)
        observed: dict[str, Any] = {}
        if behavior == "leave_early":
            deadline = time.monotonic() + _SUBMIT_WAIT
            while not observation.lookups and time.monotonic() < deadline:
                time.sleep(0.005)
            submitted = bool(observation.lookups)
            answered_first = observation.popup_status is not None
            rest = self._page.to_global(self._page.pages[page].rest)
            self._glide(*rest)
            observation.departed_ns = time.perf_counter_ns()
            time.sleep(_LATE_WINDOW)
            observed = {"submitted": submitted, "answered_before_leaving": answered_first}
        else:
            observation.done.wait(self._settle_timeout)
            before = observation.popup_status
            run = getattr(placed, "run_index", None)
            item = placed.item
            if run is not None and item is not None and item.replacement:
                self._stress_page.swap(page, run, item.replacement)
                swapped = time.perf_counter_ns()
                time.sleep(_LATE_WINDOW)
                fired_after = observation.fired_after(swapped)
                observed = {
                    "answer_before_change": before,
                    "hovers_after_change": fired_after,
                }
                self._stress_page.swap(page, run, item.target.line or item.target.surface)
        with self._lock:
            self._active = None
        if self._user_moved() and behavior != "leave_early":
            return False
        foreign = self._foreign_windows(x, y) if behavior != "leave_early" else []
        self._finish(
            placed,
            observation,
            arrived,
            unscored="obscured_during_capture" if foreign else None,
            foreign=foreign,
            timed_out=behavior != "leave_early" and not observation.done.is_set(),
            observed=observed,
        )
        return True

    # -- the UIA segment ----------------------------------------------------------

    def _uia_segment(self) -> bool:
        """Hover real accessible text in an isolated browser window the lab owns."""

        if not self._uia_items or sys.platform != "win32":
            return True
        geometry = self._page.geometry()
        window = (geometry.left() + 200, geometry.top() + 80, 900, 820)
        # Blank page inside the browser, below its last line: never anyone else's screen.
        rest = (window[0] + window[2] - 90, window[1] + window[3] - 60)
        # The tour page is always on top; it steps aside while the browser is read.
        self._stress_page.set_shown(False)
        self._rest_override = rest
        try:
            for offset in range(0, len(self._uia_items), _UIA_LINES):
                chunk = self._uia_items[offset : offset + _UIA_LINES]
                lines = [item.target.surface for item in chunk]
                with BrowserText(lines, self._run_dir / "browser", window) as text:
                    if not text.points or text.window_pid is None:
                        self._recorder.lab(
                            "uia_segment_unavailable",
                            reason="no_browser_text",
                            classes=sorted(set(text.refusal)),
                        )
                        return True
                    self._allowed.add(text.window_pid)
                    painted_ms = self._await_painted(text.points, text.window_pid)
                    self._recorder.lab(
                        "uia_segment", targets=len(text.points), painted_ms=painted_ms
                    )
                    try:
                        if not self._hover_points(chunk, text.points, rest):
                            return False
                    finally:
                        self._allowed.discard(text.window_pid)
            return True
        finally:
            self._rest_override = None
            self._stress_page.set_shown(True)

    def _await_painted(
        self, points: list[tuple[int, int]], owner: int, *, deadline_s: float = 10.0
    ) -> float | None:
        """Milliseconds until the browser has drawn its lines, or None if it never did.

        DevTools can measure text that a fresh window has not presented yet; a
        hover then captures a blank frame. Pixels are read in memory only.
        """

        import mss

        started = time.monotonic()
        with mss.mss() as screen:
            while time.monotonic() - started < deadline_s:
                boxes = [
                    {"left": x - 30, "top": y - 12, "width": 60, "height": 24}
                    for x, y in points
                    if owner_at(x, y) == owner
                ]
                if boxes and all(is_drawn(screen.grab(box).rgb) for box in boxes):
                    return round((time.monotonic() - started) * 1000, 1)
                time.sleep(0.1)
        return None

    def _hover_points(
        self, items: list[StressItem], points: list[tuple[int, int]], rest: tuple[int, int]
    ) -> bool:
        origin = self._page.geometry().topLeft()
        self._move_to(rest)
        for item, (x, y) in zip(items, points, strict=False):
            local = QPoint(x, y) - origin
            placed = StressPlaced(
                item.target,
                QRect(local.x() - 2, local.y() - 2, 4, 4),
                local,
                "Malgun Gothic",
                30,
                "light",
                item=item,
            )
            if self._user_moved() or not self._hover(placed, self._page_index, False):
                return False
            self._move_to(rest)
            self._popup_hidden.clear()
            self._popup_hidden.wait(0.8)
        return True
    # -- recording ----------------------------------------------------------------

    def _target_event(self, placed: Any, page: int, x: int, y: int) -> None:
        target = placed.target
        self._recorder.lab(
            "tour_target",
            target=target.id,
            source=target.source,
            page=page,
            x=x,
            y=y,
            font=placed.font_family,
            font_px=placed.font_px,
            theme=placed.theme,
        )

    def _finish(
        self,
        placed: Any,
        seen: _Observation,
        arrived_ns: int,
        *,
        unscored: str | None,
        foreign: list[str],
        timed_out: bool = False,
        observed: dict[str, Any] | None = None,
    ) -> None:
        self.completed += 1
        item: StressItem | None = getattr(placed, "item", None)
        record = outcome_record(
            placed,
            seen,
            arrived_ns,
            timed_out=timed_out,
            verified=unscored is None,
            retain_text=self._retain_fixture_text,
        )
        if unscored is not None:
            record["unscored"] = unscored
            record["foreign_points"] = foreign
        record.update(
            family=item.family if item else "word",
            behavior=item.behavior if item else "dwell",
            raster=item.raster if item else None,
            graphic=item.graphic if item else None,
            repeat_of=item.repeat_of if item else None,
            late_popups=seen.late_popups,
            foreign_popups=seen.foreign_popups,
            direct_text=seen.direct_text,
            gate=seen.latest.gate if seen.latest else None,
            cache_hits=seen.cache_hits,
            region=list(seen.region) if seen.region else None,
            observed=observed or {},
        )
        record["verdict"] = stress_verdict(record)
        record["stage"] = failing_stage(record)
        record["rule"] = RULE
        if self._retain_images and unscored is None and record["stage"] in _REPLAYED:
            record["replay_image"] = self._recapture(record)
        self._recorder.lab("stress_result", **record)

    def _recapture(self, record: dict[str, Any]) -> str | None:
        """Grab the region the app captured, once its popup is gone, for an offline replay.

        The page is the lab's own and static, so these are the pixels the app
        read unless the page changed in between; it is labelled as a lab
        re-capture, never as the app's own frame.
        """

        region = record.get("region")
        if not region:
            return None
        rest = self._page.to_global(self._page.pages[self._page_index].rest)
        self._move_to(self._rest_override or rest)
        self._popup_hidden.clear()
        self._popup_hidden.wait(1.0)
        left, top, width, height = region
        foreign = [
            (px, py)
            for px in (left, left + width - 1)
            for py in (top, top + height - 1)
            if owner_at(px, py) not in {os.getpid(), *self._allowed}
        ]
        if foreign:
            return None
        import mss
        import mss.tools

        folder = self._run_dir / "replay"
        folder.mkdir(exist_ok=True)
        path = folder / f"{record['target']}.png"
        with mss.mss() as screen:
            shot = screen.grab({"left": left, "top": top, "width": width, "height": height})
            mss.tools.to_png(shot.rgb, shot.size, output=str(path))
        return path.name

    def _foreign_windows(self, x: int, y: int) -> list[str]:
        found = super()._foreign_windows(x, y)
        if not self._allowed:
            return found
        allowed = []
        for point in found:
            # The helper's own window counts as the lab's, nothing else does.
            if point.endswith(":other") and self._owner_allowed(point, x, y):
                continue
            allowed.append(point)
        return allowed

    def _owner_allowed(self, point: str, x: int, y: int) -> bool:
        fx, fy = (float(part) for part in point.split(":")[0].split(","))
        from .driver import _ROI_HALF

        px = min(x + fx * _ROI_HALF[0], x + _ROI_HALF[0] - 1)
        py = min(y + fy * _ROI_HALF[1], y + _ROI_HALF[1] - 1)
        return owner_at(px, py) in self._allowed

    def _start_cover(self) -> subprocess.Popen[bytes]:
        geometry = self._page.geometry()
        cover = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "lab.session.cover",
                str(geometry.left() + 420),
                str(geometry.top() + 180),
                "640",
                "380",
            ],
            cwd=str(Path(__file__).resolve().parents[2]),
        )
        time.sleep(1.5)
        self._recorder.lab("cover_started")
        return cover


#: Failures whose cause may be OCR, which an offline replay can separate from capture.
_REPLAYED = frozenset({"ocr_no_text", "ocr_misread", "resolver", "ocr_false_text"})


def is_drawn(rgb: bytes) -> bool:
    """Whether a captured box shows anything but one flat colour."""

    return any(rgb[index : index + 3] != rgb[:3] for index in range(3, len(rgb), 3))


def _stop(process: subprocess.Popen[Any]) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(5)
        except subprocess.TimeoutExpired:
            process.kill()


def _own_popup_rect(page_handle: int) -> QRect | None:
    """Where this process's popup is: its visible top-level window that is not the page.

    Asked of the window manager rather than of Qt, so it is safe off the Qt thread.
    """

    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    own = os.getpid()
    found: list[QRect] = []

    def visit(handle: int, _parameter: int) -> bool:
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(handle, ctypes.byref(pid))
        if pid.value != own or handle == page_handle or not user32.IsWindowVisible(handle):
            return True
        rect = wintypes.RECT()
        user32.GetWindowRect(handle, ctypes.byref(rect))
        width, height = rect.right - rect.left, rect.bottom - rect.top
        # The popup is a small window; the page and Qt's helper windows are not.
        if 40 < width < 900 and 30 < height < 900:
            found.append(QRect(rect.left, rect.top, width, height))
        return True

    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(visit)
    user32.EnumWindows(callback, 0)
    return found[0] if found else None

__all__ = ["StressDriver"]
