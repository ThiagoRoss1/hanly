"""Use the running desktop the way a person does, and write down what happened.

The driver presses the real capture shortcut, glides the real pointer onto each
target, and waits for the desktop's own trace to say how that hover ended. It
never calls into the application: every effect it observes went through the
same hotkey, mouse observer, capture, lookup child and popup a user's would.

Moving the mouse yourself during a tour stops it.
"""

from __future__ import annotations

import json
import multiprocessing
import os
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .ownership import owner_at
from .recorder import LabRecorder
from .scoring import RULE, classify

if TYPE_CHECKING:
    from .page import Placed, TourPage

#: The pointer drifting this far from where the driver put it means a person moved it.
_INTERVENTION_PX = 24
_GLIDE_STEPS = 8
_GLIDE_STEP_S = 0.006
#: Half the capture region the desktop takes around the pointer (its default 200x100).
_ROI_HALF = (100, 50)
#: Probe grid over that region, as fractions of its half-size from the centre.
_PROBES = tuple((fx, fy) for fx in (-1.0, -0.5, 0.0, 0.5, 1.0) for fy in (-1.0, 0.0, 1.0))
#: Hover events that carry an ID before it fires; they are not foreign work.
_PRE_FIRE = frozenset({"hover_mouse_opportunity", "hover_invalidation", "hover_cancellation"})


@dataclass
class _Lookup:
    """What the trace said about one lookup a bound hover submitted."""

    status: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    acquisition: str | None = None
    ocr_ms: float | None = None
    total_ms: float | None = None
    queries: list[tuple[str, bool]] = field(default_factory=list)
    recognized: list[str] = field(default_factory=list)
    confidence: float | None = None


@dataclass
class _Observation:
    """One target's hover, bound by ID so a stale or neighbouring lookup cannot answer it.

    A hover ID binds when it fires after the pointer arrived; a lookup ID binds
    when one of those hovers submits it. Everything else is counted and ignored.
    """

    hover_ids: set[int] = field(default_factory=set)
    lookups: dict[int, _Lookup] = field(default_factory=dict)
    roi: tuple[int, int] | None = None
    ignored: int = 0
    events: dict[str, int] = field(default_factory=dict)
    popup_status: str | None = None
    popup_ns: int | None = None
    delivered_ns: int | None = None
    done: threading.Event = field(default_factory=threading.Event)

    @property
    def latest(self) -> _Lookup | None:
        return self.lookups[max(self.lookups)] if self.lookups else None


class TourDriver:
    """Drive a whole tour on its own thread; ``run`` blocks until it finishes."""

    def __init__(
        self,
        recorder: LabRecorder,
        page: TourPage,
        *,
        capture_hotkey: str,
        settle_timeout: float = 4.0,
        first_timeout: float = 90.0,
    ) -> None:
        self._recorder = recorder
        self._page = page
        self._capture_hotkey = capture_hotkey
        self._settle_timeout = settle_timeout
        self._first_timeout = first_timeout
        self._lock = threading.Lock()
        self._active: _Observation | None = None
        self._ready = threading.Event()
        self._popup_hidden = threading.Event()
        self._expected: tuple[int, int] | None = None
        #: Captured images are in device pixels; the probe grid is in points.
        self._scale = float(page.devicePixelRatioF() or 1.0)
        self.stopped_by_user = False
        self.completed = 0
        recorder.subscribe(self._observe)

        from pynput import keyboard, mouse

        self._mouse = mouse.Controller()
        self._keyboard = keyboard.Controller()
        self._keys = keyboard.Key

    # -- the tour ---------------------------------------------------------------

    def run(self) -> None:
        self._recorder.lab("tour_waiting_for_runtime")
        if not self._ready.wait(180):
            self._recorder.lab("tour_aborted", reason="runtime_never_ready")
            return
        self._page.show_page(0)
        time.sleep(0.4)
        self._press_capture_hotkey()
        self._recorder.lab("tour_capture_requested", hotkey=self._capture_hotkey)
        first = True
        for index, page in enumerate(self._page.pages):
            if not self._page.show_page(index):
                self._recorder.lab("tour_aborted", reason="page_not_painted", page=index)
                return
            time.sleep(0.25)
            self._recorder.lab("tour_page", page=index, theme=page.theme, targets=len(page.placed))
            self._move_to(self._page.to_global(page.rest))
            for placed in page.placed:
                if self._user_moved():
                    self.stopped_by_user = True
                    self._recorder.lab("tour_stopped_by_user", completed=self.completed)
                    return
                self._hover(placed, index, first)
                first = False
                self._move_to(self._page.to_global(page.rest))
                self._popup_hidden.clear()
                self._popup_hidden.wait(0.8)
        self._recorder.lab("tour_finished", completed=self.completed)

    def _hover(self, placed: Placed, page: int, first: bool) -> None:
        x, y = self._page.to_global(placed.point)
        foreign = self._foreign_windows(x, y)
        if foreign:
            # Another application covers the page here: reading it would retain
            # somebody else's text. Re-raise the page and skip this target.
            self._page.show_page(page)
            self._finish(placed, _Observation(), 0, unscored="obscured", foreign=foreign)
            return
        self._glide(x, y)
        arrived = time.perf_counter_ns()
        observation = _Observation()
        with self._lock:
            self._active = observation
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
        timeout = self._first_timeout if first else self._settle_timeout
        observation.done.wait(timeout)
        # A popup is only part of the answer; give a late popup event a moment.
        if observation.popup_status is None and observation.delivered_ns is not None:
            time.sleep(0.15)
        with self._lock:
            self._active = None

        # Ownership is sampled again after the answer. The probes cover a grid
        # of the region at two moments, not every pixel or the time between.
        unscored = None
        foreign = self._foreign_windows(x, y)
        if foreign:
            unscored = "obscured_during_capture"
        elif observation.roi is not None and _exceeds_probe(observation.roi, self._scale):
            unscored = "unverifiable_region"
        self._finish(
            placed,
            observation,
            arrived,
            unscored=unscored,
            foreign=foreign,
            timed_out=not observation.done.is_set(),
        )

    def _finish(
        self,
        placed: Placed,
        seen: _Observation,
        arrived_ns: int,
        *,
        unscored: str | None,
        foreign: list[str],
        timed_out: bool = False,
    ) -> None:
        self.completed += 1
        record = outcome_record(
            placed, seen, arrived_ns, timed_out=timed_out, keep_text=unscored is None
        )
        if unscored is not None:
            record["unscored"] = unscored
            record["foreign_points"] = foreign
        record["verdict"] = classify(record)
        record["rule"] = RULE
        self._recorder.lab("tour_result", **record)

    # -- observing the desktop's own trace ---------------------------------------

    def _observe(self, name: str, observed_ns: int, fields: Mapping[str, Any]) -> None:
        if name == "startup_milestone" and fields.get("name") == "runtime ready":
            self._ready.set()
        if name in {"retained_target_cleared", "popup_suppressed"}:
            self._popup_hidden.set()
        with self._lock:
            observation = self._active
        if observation is not None:
            observe(observation, name, observed_ns, fields)

    @staticmethod
    def _foreign_windows(x: int, y: int) -> list[str]:
        """Probe points of the capture region not owned by this process, and by whom.

        An unknown owner counts as foreign: the check fails closed.
        """

        own = os.getpid()
        children = {child.pid: child.name for child in multiprocessing.active_children()}
        half_w, half_h = _ROI_HALF
        foreign = []
        for fx, fy in _PROBES:
            px = min(x + fx * half_w, x + half_w - 1)
            py = min(y + fy * half_h, y + half_h - 1)
            owner = owner_at(px, py)
            if owner == own:
                continue
            # The owner's identity stays coarse: which Hanly child, or simply "other".
            who = "none" if owner is None else children.get(owner, "other")
            foreign.append(f"{fx:+.1f},{fy:+.1f}:{who}")
        return foreign

    # -- the real input devices ---------------------------------------------------

    def _press_capture_hotkey(self) -> None:
        parts = [part.strip().lower() for part in self._capture_hotkey.split("+")]
        aliases = {"control": "ctrl", "option": "alt", "command": "cmd"}
        keys: list[Any] = []
        for part in parts:
            named = aliases.get(part, part)
            keys.append(getattr(self._keys, named, None) or named)
        for key in keys:
            self._keyboard.press(key)
            time.sleep(0.02)
        for key in reversed(keys):
            self._keyboard.release(key)
            time.sleep(0.02)

    def _glide(self, x: int, y: int) -> None:
        start_x, start_y = self._mouse.position
        for step in range(1, _GLIDE_STEPS + 1):
            fraction = step / _GLIDE_STEPS
            self._set(
                round(start_x + (x - start_x) * fraction), round(start_y + (y - start_y) * fraction)
            )
            time.sleep(_GLIDE_STEP_S)

    def _move_to(self, point: tuple[int, int]) -> None:
        self._glide(*point)

    def _set(self, x: int, y: int) -> None:
        self._mouse.position = (x, y)
        self._expected = (x, y)

    def _user_moved(self) -> bool:
        if self._expected is None:
            return False
        x, y = self._mouse.position
        return abs(x - self._expected[0]) + abs(y - self._expected[1]) > _INTERVENTION_PX


def observe(
    observation: _Observation, name: str, observed_ns: int, fields: Mapping[str, Any]
) -> None:
    """Fold one trace event into the hover it belongs to, or count it as foreign."""

    hover_id = fields.get("hover_request_id")
    lookup_id = fields.get("lookup_request_id")
    if isinstance(hover_id, int):
        if name == "hover_stable_fire":
            observation.hover_ids.add(hover_id)
        if hover_id not in observation.hover_ids:
            if name not in _PRE_FIRE:
                observation.ignored += 1
            return
        if isinstance(lookup_id, int):
            observation.lookups.setdefault(lookup_id, _Lookup())
    lookup = observation.lookups.get(lookup_id) if isinstance(lookup_id, int) else None
    if isinstance(lookup_id, int) and lookup is None:
        # A lookup none of this target's hovers submitted: stale earlier work.
        observation.ignored += 1
        return
    if lookup_id is None and hover_id is None:
        return
    observation.events[name] = observation.events.get(name, 0) + 1

    if name == "hover_capture_completed":
        width, height = fields.get("roi_width"), fields.get("roi_height")
        if isinstance(width, int) and isinstance(height, int):
            observation.roi = (width, height)
    elif name == "popup_visible" or name == "popup_suppressed":
        observation.popup_status = str(fields.get("result_status") or name)
        observation.popup_ns = observed_ns
        observation.done.set()
    elif name == "lookup_current_delivered":
        observation.delivered_ns = observed_ns
    if lookup is None:
        return
    if name == "lookup_acquisition":
        lookup.acquisition = str(fields.get("acquisition_source"))
    elif name == "lookup_stage_completed":
        _stage(lookup, fields)
    elif name in {"lookup_stage_error", "lookup_error"}:
        lookup.error = str(fields.get("error_type") or name)
        observation.done.set()


def _stage(lookup: _Lookup, fields: Mapping[str, Any]) -> None:
    stage = fields.get("stage")
    duration = fields.get("duration_ns")
    if stage == "ocr" and isinstance(duration, int):
        lookup.ocr_ms = duration / 1e6
        lookup.acquisition = lookup.acquisition or "ocr"
        lookup.confidence = _float(fields.get("confidence_mean"))
        evidence = _decode(fields.get("ocr_evidence"))
        if evidence:
            lookup.recognized = [str(r.get("text")) for r in evidence.get("regions", [])]
    elif stage == "dictionary":
        evidence = _decode(fields.get("dictionary_evidence"))
        if evidence:
            lookup.queries.append((str(evidence.get("query")), bool(evidence.get("found"))))
    elif stage == "total_pipeline":
        if isinstance(duration, int):
            lookup.total_ms = duration / 1e6
        outcome = fields.get("outcome")
        lookup.status = str(outcome) if outcome else None
        lookup.result = _decode(fields.get("result_evidence"))


def outcome_record(
    placed: Placed, seen: _Observation, arrived_ns: int, *, timed_out: bool, keep_text: bool
) -> dict[str, Any]:
    """The durable outcome of one hover; recognized text only when ``keep_text``."""

    target = placed.target
    lookup = seen.latest
    result = (lookup.result if lookup is not None else None) or {}
    record: dict[str, Any] = {
        "target": target.id,
        "source": target.source,
        "surface": target.surface,
        "cursor": target.cursor,
        "expected": target.headword,
        "expected_lemma": target.lemma,
        "refuse": target.refuse,
        "kinds": list(target.kinds),
        "level": target.level,
        "font": placed.font_family,
        "font_px": placed.font_px,
        "theme": placed.theme,
        "status": None if lookup is None else lookup.status,
        "error": None if lookup is None else lookup.error,
        "acquisition": None if lookup is None else lookup.acquisition,
        "ocr_ms": None if lookup is None else lookup.ocr_ms,
        "pipeline_ms": None if lookup is None else lookup.total_ms,
        "confidence": None if lookup is None else lookup.confidence,
        "popup": seen.popup_status,
        "hover_to_popup_ms": None if seen.popup_ns is None else (seen.popup_ns - arrived_ns) / 1e6,
        "timed_out": timed_out,
        "hover_ids": sorted(seen.hover_ids),
        "lookup_ids": sorted(seen.lookups),
        "ignored_foreign_events": seen.ignored,
        "events": seen.events,
    }
    if keep_text and lookup is not None:
        # Lab-authored text, read from pixels the lab sampled as its own.
        record.update(
            selected=result.get("selected"),
            lemma=result.get("lemma"),
            headword=result.get("headword"),
            recognized=lookup.recognized,
            queries=lookup.queries,
        )
    return record


def _exceeds_probe(roi: tuple[int, int], scale: float = 1.0) -> bool:
    """A captured region larger than the probed one cannot be attributed."""

    width, height = roi[0] / scale, roi[1] / scale
    return width > 2 * _ROI_HALF[0] or height > 2 * _ROI_HALF[1]


def _decode(value: object) -> dict[str, Any] | None:
    if not isinstance(value, str):
        return None
    try:
        decoded = json.loads(value)
    except ValueError:
        return None
    return decoded if isinstance(decoded, dict) else None


def _float(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


__all__ = ["TourDriver", "observe", "outcome_record"]
