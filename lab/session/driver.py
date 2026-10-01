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

if TYPE_CHECKING:
    from .page import Placed, TourPage

#: The pointer drifting this far from where the driver put it means a person moved it.
_INTERVENTION_PX = 24
_GLIDE_STEPS = 8
_GLIDE_STEP_S = 0.006
#: Half the capture region the desktop takes around the pointer, checked at its corners.
_ROI_HALF = (100, 50)


@dataclass
class _Observation:
    """What the trace said about one target while the pointer rested on it."""

    hover_ids: set[int] = field(default_factory=set)
    lookup_ids: set[int] = field(default_factory=set)
    events: dict[str, int] = field(default_factory=dict)
    result: dict[str, Any] | None = None
    popup_status: str | None = None
    popup_ns: int | None = None
    delivered_ns: int | None = None
    acquisition: str | None = None
    ocr_ms: float | None = None
    total_ms: float | None = None
    queries: list[tuple[str, bool]] = field(default_factory=list)
    recognized: list[str] = field(default_factory=list)
    confidence: float | None = None
    done: threading.Event = field(default_factory=threading.Event)


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
        self._engine_ready = threading.Event()
        self._popup_hidden = threading.Event()
        self._expected: tuple[int, int] | None = None
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
        target = placed.target
        observation = _Observation()
        x, y = self._page.to_global(placed.point)
        foreign = self._foreign_windows(x, y)
        if foreign:
            # Another application covers the page here: reading it would retain
            # somebody else's text. Re-raise the page and skip this target.
            self._page.show_page(page)
            self.completed += 1
            self._recorder.lab(
                "tour_result",
                target=target.id,
                source=target.source,
                verdict="obscured",
                surface=target.surface,
                expected=target.headword,
                refuse=target.refuse,
                font=placed.font_family,
                font_px=placed.font_px,
                theme=placed.theme,
                foreign_points=foreign,
            )
            return
        self._glide(x, y)
        arrived = time.perf_counter_ns()
        with self._lock:
            self._active = observation
        self._recorder.evidence_open = self._recorder.retain_evidence
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
        self._recorder.evidence_open = False
        with self._lock:
            self._active = None
        self.completed += 1
        self._recorder.lab(
            "tour_result",
            **_judge(placed, observation, arrived, timed_out=not observation.done.is_set()),
        )

    # -- observing the desktop's own trace ---------------------------------------

    def _observe(self, name: str, observed_ns: int, fields: Mapping[str, Any]) -> None:
        if name == "startup_milestone" and fields.get("name") == "runtime ready":
            self._ready.set()
        if name in {"retained_target_cleared", "popup_suppressed"}:
            self._popup_hidden.set()
        with self._lock:
            observation = self._active
        if observation is None:
            return
        observation.events[name] = observation.events.get(name, 0) + 1
        hover_id = fields.get("hover_request_id")
        lookup_id = fields.get("lookup_request_id")
        if isinstance(hover_id, int):
            observation.hover_ids.add(hover_id)
        if isinstance(lookup_id, int):
            observation.lookup_ids.add(lookup_id)
        if name == "lookup_acquisition":
            observation.acquisition = str(fields.get("acquisition_source"))
        elif name == "lookup_stage_completed":
            self._stage(observation, fields)
        elif name == "lookup_current_delivered":
            observation.delivered_ns = observed_ns
        elif name in {"popup_visible", "popup_suppressed"}:
            observation.popup_status = str(fields.get("result_status") or name)
            observation.popup_ns = observed_ns
            observation.done.set()
        elif name in {"lookup_error", "lookup_stage_error", "hover_capture_error"}:
            observation.done.set()

    @staticmethod
    def _stage(observation: _Observation, fields: Mapping[str, Any]) -> None:
        stage = fields.get("stage")
        duration = fields.get("duration_ns")
        if stage == "ocr" and isinstance(duration, int):
            observation.ocr_ms = duration / 1e6
            observation.acquisition = observation.acquisition or "ocr"
            observation.confidence = _float(fields.get("confidence_mean"))
            evidence = _decode(fields.get("ocr_evidence"))
            if evidence:
                observation.recognized = [str(r.get("text")) for r in evidence.get("regions", [])]
        elif stage == "dictionary":
            evidence = _decode(fields.get("dictionary_evidence"))
            if evidence:
                observation.queries.append(
                    (str(evidence.get("query")), bool(evidence.get("found")))
                )
        elif stage == "total_pipeline":
            if isinstance(duration, int):
                observation.total_ms = duration / 1e6
            observation.result = _decode(fields.get("result_evidence"))

    @staticmethod
    def _foreign_windows(x: int, y: int) -> list[str]:
        """Probe points of the capture region another process covers, and by whom."""

        own = os.getpid()
        children = {child.pid: child.name for child in multiprocessing.active_children()}
        half_w, half_h = _ROI_HALF
        probes = {
            "center": (x, y),
            "top_left": (x - half_w, y - half_h),
            "top_right": (x + half_w - 1, y - half_h),
            "bottom_left": (x - half_w, y + half_h - 1),
            "bottom_right": (x + half_w - 1, y + half_h - 1),
        }
        foreign = []
        for name, (px, py) in probes.items():
            owner = owner_at(px, py)
            if owner == own:
                continue
            # The owner's identity stays coarse: which Hanly child, or simply "other".
            who = "none" if owner is None else children.get(owner, "other")
            foreign.append(f"{name}:{who}")
        return foreign

    # -- the real input devices ---------------------------------------------------

    def _press_capture_hotkey(self) -> None:
        parts = [part.strip().lower() for part in self._capture_hotkey.split("+")]
        keys: list[Any] = []
        for part in parts:
            named = {
                "ctrl": "ctrl",
                "control": "ctrl",
                "shift": "shift",
                "alt": "alt",
                "option": "alt",
                "cmd": "cmd",
                "command": "cmd",
            }.get(part, part)
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


def _judge(
    placed: Placed, seen: _Observation, arrived_ns: int, *, timed_out: bool
) -> dict[str, Any]:
    """Classify one hover by the first stage that went wrong."""

    target = placed.target
    result = seen.result or {}
    status = result.get("status")
    selected = result.get("selected")
    headword = result.get("headword")
    lemma = result.get("lemma")
    recognized = " ".join(seen.recognized)

    if target.refuse:
        verdict = "refused" if status != "SUCCESS" else "false_answer"
    elif not seen.lookup_ids and not seen.hover_ids:
        verdict = "no_hover"
    elif not result:
        verdict = "no_result" if timed_out else "no_lookup"
    elif status == "SUCCESS" and target.headword in (headword, lemma):
        verdict = "correct"
    elif not selected and not recognized.strip():
        verdict = "no_text"
    elif not selected:
        # Text was recognized, but no word under the pointer was chosen from it.
        verdict = "unresolved" if target.surface in recognized else "misread"
    elif selected and _core(selected) not in (_core(target.surface), _hangul_run(target)):
        # Recognition misread the word, or resolution picked a neighbour.
        verdict = "misread" if target.surface not in recognized else "wrong_word"
    elif lemma != target.lemma and headword != target.headword:
        verdict = "wrong_lemma" if status == "SUCCESS" else "not_found"
    else:
        verdict = "not_found"

    return {
        "target": target.id,
        "source": target.source,
        "surface": target.surface,
        "expected": target.headword,
        "refuse": target.refuse,
        "kinds": list(target.kinds),
        "level": target.level,
        "font": placed.font_family,
        "font_px": placed.font_px,
        "theme": placed.theme,
        "verdict": verdict,
        "status": status,
        "selected": selected,
        "lemma": lemma,
        "headword": headword,
        "recognized": seen.recognized,
        "queries": seen.queries,
        "confidence": seen.confidence,
        "acquisition": seen.acquisition,
        "ocr_ms": seen.ocr_ms,
        "pipeline_ms": seen.total_ms,
        "popup": seen.popup_status,
        "hover_to_popup_ms": None if seen.popup_ns is None else (seen.popup_ns - arrived_ns) / 1e6,
        "timed_out": timed_out,
        "hover_ids": sorted(seen.hover_ids),
        "lookup_ids": sorted(seen.lookup_ids),
        "events": seen.events,
    }


def _core(text: str) -> str:
    return text.strip().strip("\"'“”‘’.,!?()[]")


def _hangul_run(target: Any) -> str:
    text, index = target.surface, target.cursor
    start = index
    while start > 0 and "가" <= text[start - 1] <= "힣":
        start -= 1
    end = index + 1
    while end < len(text) and "가" <= text[end] <= "힣":
        end += 1
    return text[start:end]


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


__all__ = ["TourDriver"]
