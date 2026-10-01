"""Rebuild what happened in a session from its recorded events.

Everything here is derived from ``events.jsonl`` and ``processes.jsonl``; the
report can be regenerated at any time and never needs the app again. Timestamps
from the lookup child share the shell's monotonic clock (``perf_counter`` is
system-wide on macOS, Windows and Linux), so stages from both processes sit on
one timeline.
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Waterfall segments in pipeline order. Colors follow this order in the report.
SEGMENTS: tuple[tuple[str, str], ...] = (
    ("dwell", "Dwell (debounce)"),
    ("direct_text", "Direct text (AX/UIA)"),
    ("capture", "Screen capture"),
    ("to_engine", "Handoff to engine"),
    ("ocr", "OCR"),
    ("language", "Resolve + morphology + dictionary"),
    ("to_popup", "Back to shell + popup"),
)

#: Terminal events, the outcome they mean, and whether work was thrown away.
_TERMINALS = {
    "popup_visible": "answered",
    "popup_suppressed": "no_answer",
    "lookup_stale_suppressed": "stale",
    "lookup_cancelled_early": "cancelled",
    "hover_stale_after_capture": "stale",
    "hover_stale_after_submission": "stale",
    "hover_capture_error": "error",
    "hover_submission_error": "error",
    "lookup_error": "error",
}


@dataclass
class Episode:
    """One hover: from the pointer settling to whatever ended it."""

    hover_id: int
    start: float
    events: list[tuple[float, str, dict[str, Any]]] = field(default_factory=list)
    lookup_id: int | None = None
    fired: float | None = None
    outcome: str = "moved_on"
    status: str | None = None
    segments: list[tuple[str, float, float]] = field(default_factory=list)
    facts: dict[str, Any] = field(default_factory=dict)

    @property
    def end(self) -> float:
        return self.events[-1][0] if self.events else self.start

    @property
    def total(self) -> float | None:
        popup = self.facts.get("popup_at")
        return None if popup is None else popup - self.start


def load(run_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    events = _jsonl(run_dir / "events.jsonl")
    processes = _jsonl(run_dir / "processes.jsonl")
    metadata_path = run_dir / "metadata.json"
    metadata = json.loads(metadata_path.read_text("utf-8")) if metadata_path.is_file() else {}
    events.sort(key=lambda event: event.get("t_ms", 0))
    return events, processes, metadata


def build_model(run_dir: Path) -> dict[str, Any]:
    events, processes, metadata = load(run_dir)
    episodes = episodes_from(events)
    fired = [episode for episode in episodes if episode.fired is not None]
    tour = [event for event in events if event["event"] == "tour_result"]
    model: dict[str, Any] = {
        "metadata": metadata,
        "duration_ms": events[-1]["t_ms"] if events else 0,
        "event_counts": dict(Counter(event["event"] for event in events).most_common()),
        "startup": startup(events),
        "funnel": funnel(events, episodes),
        "stages": stage_stats(events, fired),
        "breakdown": breakdown(fired),
        "processes": process_profile(processes, events),
        "episodes": [_episode_row(episode) for episode in fired],
        "moved_on": len(episodes) - len(fired),
        "lifecycle": lifecycle(events),
        "tour": tour_summary(tour) if tour else None,
        "diagnostics": [
            {k: e.get(k) for k in ("t_ms", "subsystem", "level", "message")}
            for e in events
            if e["event"] == "diagnostic"
        ][-200:],
    }
    model["findings"] = findings(model)
    return model


# -- episodes ----------------------------------------------------------------------


def episodes_from(events: Sequence[Mapping[str, Any]]) -> list[Episode]:
    by_hover: dict[int, Episode] = {}
    lookup_to_hover: dict[int, int] = {}
    for event in events:
        name, t = event["event"], float(event.get("t_ms", 0))
        hover_id = event.get("hover_request_id")
        lookup_id = event.get("lookup_request_id")
        if isinstance(hover_id, int) and isinstance(lookup_id, int):
            lookup_to_hover.setdefault(lookup_id, hover_id)
        if not isinstance(hover_id, int) and isinstance(lookup_id, int):
            hover_id = lookup_to_hover.get(lookup_id)
        if not isinstance(hover_id, int):
            continue
        episode = by_hover.get(hover_id)
        if episode is None:
            episode = by_hover[hover_id] = Episode(hover_id, t)
        fields = {k: v for k, v in event.items() if k not in _NOISE}
        episode.events.append((t, name, fields))
    for episode in by_hover.values():
        _interpret(episode)
    return sorted(by_hover.values(), key=lambda episode: episode.start)


_NOISE = {"schema_version", "event", "monotonic_ns", "t_ms", "by", "source", "thread_id"}


def _interpret(episode: Episode) -> None:
    facts = episode.facts
    stages: dict[str, list[tuple[float, float, Mapping[str, Any]]]] = defaultdict(list)
    for t, name, fields in episode.events:
        lookup_id = fields.get("lookup_request_id")
        if isinstance(lookup_id, int) and episode.lookup_id is None:
            episode.lookup_id = lookup_id
        duration = _ms(fields.get("duration_ns"))
        if name == "hover_stable_fire":
            episode.fired = t
        elif name == "hover_direct_text":
            facts["direct_text"] = fields.get("outcome")
            facts["direct_text_ms"] = duration
            if fields.get("used_direct_text"):
                facts["acquisition"] = "direct_text"
        elif name == "hover_capture_completed":
            facts["capture_ms"] = duration
            facts["capture_end"] = t
            facts["roi"] = f"{fields.get('roi_width')}x{fields.get('roi_height')}"
            facts["roi_clipped"] = fields.get("roi_clipped")
            facts["acquisition"] = facts.get("acquisition") or "capture"
        elif name in {"lookup_cache_hit", "lookup_cache_miss"}:
            facts.setdefault("engine_at", t)
            facts["lookup_cache"] = "hit" if name == "lookup_cache_hit" else "miss"
        elif name == "lookup_acquisition":
            facts["acquisition"] = fields.get("acquisition_source") or facts.get("acquisition")
        elif name == "ocr_sensitive_retry":
            facts["sensitive_retry"] = True
        elif name == "lookup_stage_completed" and duration is not None:
            stage = str(fields.get("stage"))
            stages[stage].append((t - duration, t, fields))
            if stage == "ocr":
                facts["ocr_backend"] = fields.get("ocr_backend")
                facts["ocr_regions"] = fields.get("region_count")
                facts["ocr_hangul_regions"] = fields.get("hangul_region_count")
                facts["ocr_confidence"] = fields.get("confidence_mean")
                facts["ocr_cached"] = bool(fields.get("ocr_cached") or fields.get("ocr_cache_hit"))
                facts["gate"] = (
                    "rejected"
                    if fields.get("provider_skipped_reason") == "gate_rejected"
                    else "passed"
                    if fields.get("gate_passed")
                    else None
                )
            elif stage == "token_selection":
                facts["resolved"] = fields.get("resolved")
                facts["resolution_reason"] = fields.get("resolution_reason")
            elif stage == "dictionary":
                facts["dictionary_queries"] = facts.get("dictionary_queries", 0) + 1
                facts["dictionary_found"] = facts.get("dictionary_found") or bool(
                    fields.get("found")
                )
            elif stage == "total_pipeline":
                facts["pipeline_ms"] = duration
                facts["pipeline_end"] = t
                facts["result"] = fields.get("outcome")
                facts["cached"] = fields.get("cached")
        elif name == "lookup_dispatch_queued":
            facts["dispatched_at"] = t
        if name in _TERMINALS and "terminal" not in facts:
            facts["terminal"] = name
            episode.outcome = _TERMINALS[name]
            episode.status = fields.get("result_status") or episode.status
            if name in {"popup_visible", "popup_suppressed"}:
                facts["popup_at"] = t
    if episode.fired is not None and episode.outcome == "moved_on":
        episode.outcome = "abandoned" if facts.get("capture_end") else "left_before_capture"
    episode.segments = _segments(episode, stages)
    facts["stages"] = {
        stage: round(sum(end - start for start, end, _ in spans), 3)
        for stage, spans in stages.items()
    }


def _segments(
    episode: Episode, stages: Mapping[str, list[tuple[float, float, Mapping[str, Any]]]]
) -> list[tuple[str, float, float]]:
    facts, origin, out = episode.facts, episode.start, []

    def add(name: str, start: float | None, end: float | None) -> None:
        if start is not None and end is not None and end >= start:
            out.append((name, round(start - origin, 3), round(end - origin, 3)))

    fired = episode.fired
    add("dwell", origin, fired)
    if fired is not None and facts.get("direct_text_ms") is not None:
        add("direct_text", fired, fired + facts["direct_text_ms"])
    capture_end = facts.get("capture_end")
    if capture_end is not None and facts.get("capture_ms") is not None:
        add("capture", capture_end - facts["capture_ms"], capture_end)
    handed = capture_end if capture_end is not None else fired
    first_stage = min((s for spans in stages.values() for s, _, _ in spans), default=None)
    engine_at = facts.get("engine_at")
    add("to_engine", handed, first_stage if first_stage is not None else engine_at)
    for start, end, _ in stages.get("ocr", ()):
        add("ocr", start, end)
    language = [
        span
        for stage in ("token_selection", "morphology", "dictionary")
        for span in stages.get(stage, ())
    ]
    if language:
        add("language", min(s for s, _, _ in language), max(e for _, e, _ in language))
    add("to_popup", facts.get("pipeline_end"), facts.get("popup_at"))
    return out


def _episode_row(episode: Episode) -> dict[str, Any]:
    facts = {k: v for k, v in episode.facts.items() if not k.endswith(("_at", "_end"))}
    return {
        "hover": episode.hover_id,
        "lookup": episode.lookup_id,
        "t": round(episode.start, 1),
        "outcome": episode.outcome,
        "status": episode.status,
        "total": None if episode.total is None else round(episode.total, 2),
        "segments": episode.segments,
        "facts": facts,
        "trail": [
            [
                round(t - episode.start, 3),
                name,
                {k: v for k, v in f.items() if not k.endswith("_evidence")},
            ]
            for t, name, f in episode.events
        ],
    }


# -- aggregates --------------------------------------------------------------------------


def funnel(
    events: Sequence[Mapping[str, Any]], episodes: Sequence[Episode]
) -> list[dict[str, Any]]:
    """How many hovers reached each step, and what stopped the rest."""

    fired = [e for e in episodes if e.fired is not None]
    captured = [e for e in fired if e.facts.get("acquisition") in {"capture", "ocr"}]
    direct = [e for e in fired if e.facts.get("acquisition") == "direct_text"]
    engine = [e for e in fired if e.facts.get("lookup_cache")]
    cache_hits = [e for e in engine if e.facts.get("lookup_cache") == "hit"]
    ocr = [e for e in engine if "ocr" in e.facts.get("stages", {})]
    hangul = [e for e in ocr if (e.facts.get("ocr_hangul_regions") or 0) > 0]
    resolved = [e for e in fired if e.facts.get("resolved")]
    found = [e for e in fired if e.facts.get("dictionary_found")]
    answered = [e for e in fired if e.outcome == "answered"]
    inside = sum(1 for e in events if e["event"] == "hover_inside_retained_target")
    return [
        {
            "step": "Pointer settled (hover opportunity)",
            "count": len(episodes),
            "note": f"{len(episodes) - len(fired)} moved on before the dwell elapsed",
        },
        {
            "step": "Dwell elapsed (stable fire)",
            "count": len(fired),
            "note": f"{inside} pointer moves stayed inside a shown answer and started nothing",
        },
        {"step": "Read without pixels (direct text)", "count": len(direct), "branch": True},
        {"step": "Screen region captured", "count": len(captured)},
        {
            "step": "Reached the lookup engine",
            "count": len(engine),
            "note": f"{len(cache_hits)} answered from the lookup cache",
        },
        {
            "step": "OCR ran",
            "count": len(ocr),
            "note": f"{sum(1 for e in ocr if e.facts.get('gate') == 'rejected')} "
            "flat regions skipped by the gate",
        },
        {"step": "OCR found Hangul", "count": len(hangul)},
        {"step": "Word under pointer resolved", "count": len(resolved)},
        {"step": "Dictionary entry found", "count": len(found)},
        {"step": "Popup shown with an answer", "count": len(answered)},
    ]


def stage_stats(
    events: Sequence[Mapping[str, Any]], episodes: Sequence[Episode]
) -> list[dict[str, Any]]:
    samples: dict[str, list[float]] = defaultdict(list)
    for event in events:
        if event["event"] == "lookup_stage_completed":
            value = _ms(event.get("duration_ns"))
            if value is not None:
                samples[f"engine.{event.get('stage')}"].append(value)
    for episode in episodes:
        for name, start, end in episode.segments:
            # OCR already has its engine-side row; the hover segment is the same span.
            if name != "ocr":
                samples[f"hover.{name}"].append(end - start)
        if episode.total is not None and episode.outcome == "answered":
            samples["hover.total_to_answer"].append(episode.total)
    return [
        {"name": name, **describe(values)} for name, values in sorted(samples.items()) if values
    ]


def breakdown(episodes: Sequence[Episode]) -> dict[str, Any]:
    """Median time per segment of answered hovers: where the wait goes."""

    answered = [e for e in episodes if e.outcome == "answered" and e.facts.get("cached") is False]
    per: dict[str, list[float]] = defaultdict(list)
    for episode in answered:
        spent: dict[str, float] = defaultdict(float)
        for name, start, end in episode.segments:
            spent[name] += end - start
        for name, _ in SEGMENTS:
            per[name].append(spent.get(name, 0.0))
    medians = {name: _percentile(values, 50) for name, values in per.items()}
    return {"answered_uncached": len(answered), "median_ms": medians}


def process_profile(
    samples: Sequence[Mapping[str, Any]], events: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    series: dict[str, list[tuple[float, float, float]]] = defaultdict(list)
    peaks: dict[str, dict[str, Any]] = {}
    pids: dict[str, set[int]] = defaultdict(set)
    for sample in samples:
        totals: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
        for row in sample.get("processes", ()):
            if "rss" not in row:
                continue
            role = _role_group(str(row["role"]))
            pids[role].add(int(row["pid"]))
            totals[role][0] += row["rss"] / 2**20
            totals[role][1] += row.get("cpu", 0.0)
            totals[role][2] += row.get("threads", 0)
        for role, (rss, cpu, threads) in totals.items():
            series[role].append((round(sample["t_ms"], 1), round(rss, 1), round(cpu, 1)))
            peak = peaks.setdefault(role, {"rss_mib": 0.0, "cpu": 0.0, "threads": 0})
            peak["rss_mib"] = max(peak["rss_mib"], round(rss, 1))
            peak["cpu"] = max(peak["cpu"], round(cpu, 1))
            peak["threads"] = max(peak["threads"], int(threads))
    for role, values in series.items():
        peaks[role]["mean_cpu"] = round(sum(v[2] for v in values) / len(values), 1)
        peaks[role]["final_rss_mib"] = values[-1][1]
        peaks[role]["processes"] = len(pids[role])
        peaks[role]["alive_ms"] = [values[0][0], values[-1][0]]
    return {"series": series, "summary": peaks, "samples": len(samples)}


def _role_group(role: str) -> str:
    if role.endswith(".helper"):
        return role.split(".")[0] + " helpers"
    return role


def lifecycle(events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Milestones worth a marker on every timeline."""

    marks = {
        "session_started": "Session started",
        "startup_milestone": None,
        "hover_observation_started": "Watching the screen",
        "executor_worker_construction_started": "Lookup engine loading",
        "executor_worker_ready": "Lookup engine ready",
        "tour_capture_requested": "Capture shortcut pressed",
        "tour_page": "Tour page",
        "tour_finished": "Tour finished",
        "tour_stopped_by_user": "Stopped by user",
        "tour_aborted": "Tour aborted",
        "executor_shutdown": "Lookup engine shut down",
        "session_ended": "Session ended",
    }
    out = []
    for event in events:
        name = event["event"]
        if name not in marks:
            continue
        label = marks[name] or str(event.get("name"))
        if name == "tour_page":
            label = f"Page {int(event.get('page', 0)) + 1} ({event.get('theme')})"
        out.append({"t": round(event["t_ms"], 1), "label": label, "kind": name})
    first_answer = next((e for e in events if e["event"] == "popup_visible"), None)
    if first_answer is not None:
        out.append(
            {
                "t": round(first_answer["t_ms"], 1),
                "label": "First answer shown",
                "kind": "first_answer",
            }
        )
    return sorted(out, key=lambda mark: mark["t"])


def startup(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    phases = [
        {"name": e["name"], "ms": e["duration_ms"], "outcome": e["outcome"], "end": e["t_ms"]}
        for e in events
        if e["event"] == "startup_phase"
    ]
    milestones = [
        {"name": e["name"], "at_ms": e["at_ms"], "t": e["t_ms"]}
        for e in events
        if e["event"] == "startup_milestone"
    ]
    prewarm = [
        {"stage": e.get("stage"), "ms": _ms(e.get("duration_ns")), "end": e["t_ms"]}
        for e in events
        if e["event"] == "provider_prewarm_completed"
    ]
    # The child is ready once every provider has prewarmed; the shell-side
    # executor events only bracket constructing a proxy to it.
    prewarm_started = [e["t_ms"] for e in events if e["event"] == "provider_prewarm_started"]
    prewarm_done = [e["t_ms"] for e in events if e["event"] == "provider_prewarm_completed"]
    engine = (
        round(max(prewarm_done) - min(prewarm_started), 1)
        if prewarm_started and prewarm_done
        else None
    )
    first_answer = next((e["t_ms"] for e in events if e["event"] == "popup_visible"), None)
    return {
        "phases": phases,
        "milestones": milestones,
        "prewarm": prewarm,
        "engine_load_ms": engine,
        "engine_ready_t": max(prewarm_done) if prewarm_done else None,
        "first_answer_t": first_answer,
    }


def tour_summary(results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    scored = [r for r in results if r.get("verdict") != "obscured"]
    verdicts = Counter(str(r.get("verdict")) for r in results)
    good = {"correct", "refused"}

    def by(key: str) -> list[dict[str, Any]]:
        groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for r in scored:
            value = r.get(key)
            groups[str(value) if value is not None else "-"].append(r)
        return sorted(
            (
                {
                    "group": group,
                    "n": len(items),
                    "accuracy": sum(r.get("verdict") in good for r in items) / len(items),
                    "median_popup_ms": _percentile(
                        [r["hover_to_popup_ms"] for r in items if r.get("hover_to_popup_ms")], 50
                    ),
                }
                for group, items in groups.items()
            ),
            key=lambda row: _sort_key(row["group"]),
        )

    calibration = []
    for low, high in ((0, 0.3), (0.3, 0.5), (0.5, 0.7), (0.7, 0.9), (0.9, 1.01)):
        bucket = [
            r
            for r in scored
            if isinstance(r.get("confidence"), (int, float)) and low <= r["confidence"] < high
        ]
        if bucket:
            calibration.append(
                {
                    "range": f"{low:.1f}-{min(high, 1):.1f}",
                    "n": len(bucket),
                    "accuracy": sum(r.get("verdict") in good for r in bucket) / len(bucket),
                }
            )
    failures = [
        {
            k: r.get(k)
            for k in (
                "target",
                "surface",
                "expected",
                "verdict",
                "status",
                "selected",
                "lemma",
                "headword",
                "recognized",
                "queries",
                "confidence",
                "font",
                "font_px",
                "theme",
                "hover_to_popup_ms",
                "kinds",
                "level",
                "source",
            )
        }
        for r in results
        if r.get("verdict") not in good
    ]
    return {
        "total": len(results),
        "scored": len(scored),
        "verdicts": dict(verdicts.most_common()),
        "accuracy": (sum(r.get("verdict") in good for r in scored) / len(scored))
        if scored
        else None,
        "popup_ms": describe(
            [r["hover_to_popup_ms"] for r in scored if r.get("hover_to_popup_ms")]
        ),
        "by_source": by("source"),
        "by_font_px": by("font_px"),
        "by_font": by("font"),
        "by_theme": by("theme"),
        "by_level": by("level"),
        "calibration": calibration,
        "failures": failures,
        "results": [
            {
                k: r.get(k)
                for k in (
                    "target",
                    "surface",
                    "expected",
                    "verdict",
                    "headword",
                    "selected",
                    "confidence",
                    "font_px",
                    "font",
                    "theme",
                    "hover_to_popup_ms",
                    "ocr_ms",
                    "pipeline_ms",
                    "source",
                    "recognized",
                    "queries",
                    "lookup_ids",
                )
            }
            for r in results
        ],
    }


# -- findings --------------------------------------------------------------------------------


def findings(model: Mapping[str, Any]) -> list[dict[str, str]]:
    """Plain-language observations, each with the numbers that support it."""

    out: list[dict[str, str]] = []

    def add(level: str, title: str, detail: str, where: str = "") -> None:
        out.append({"level": level, "title": title, "detail": detail, "where": where})

    medians = model["breakdown"]["median_ms"]
    # The dwell is a chosen wait, not work; rank only what the app spends.
    work = {name: value for name, value in medians.items() if name != "dwell"}
    total = sum(work.values())
    if total > 0:
        top = sorted(work.items(), key=lambda item: item[1], reverse=True)
        name, value = top[0]
        label = dict(SEGMENTS)[name]
        add(
            "insight",
            f"{label} is the largest share of processing ({value / total:.0%} of {total:.0f} ms)",
            "Median per segment of uncached answered hovers, after the dwell: "
            + ", ".join(f"{dict(SEGMENTS)[n]} {v:.1f} ms" for n, v in top if v > 0.05)
            + f". Plus the dwell of {medians.get('dwell', 0):.0f} ms before any of it starts.",
            _WHERE.get(name, ""),
        )
        capture, ocr = medians.get("capture", 0), medians.get("ocr", 0)
        if capture and ocr and capture > 0.6 * ocr:
            add(
                "opportunity",
                f"Screen capture costs {capture:.0f} ms, {capture / ocr:.1f}x the OCR it feeds",
                "Capture runs on the shell's main thread before anything is handed to the "
                "engine. A smaller grab, a persistent capture stream, or moving the grab off "
                "the UI thread would cut this directly.",
                _WHERE["capture"],
            )
        direct = medians.get("direct_text", 0)
        if direct >= 2:
            add(
                "opportunity",
                f"Direct-text probing adds {direct:.1f} ms to every captured hover",
                "When the app under the pointer exposes no text, the accessibility query is "
                "paid and then discarded. Remembering 'unsupported' per window/app would skip it.",
                _WHERE["direct_text"],
            )
    stages = {row["name"]: row for row in model["stages"]}
    dwell = stages.get("hover.dwell")
    if dwell:
        add(
            "insight",
            f"Dwell before a hover fires: median {dwell['p50']:.0f} ms",
            "This is the configured debounce plus scheduling. It is a deliberate wait, "
            "not processing; it trades accidental lookups against responsiveness.",
            _WHERE["dwell"],
        )

    start = model["startup"]
    if start.get("engine_load_ms"):
        loads = ", ".join(
            f"{row['stage']} {row['ms']:.0f} ms" for row in start["prewarm"] if row.get("ms")
        )
        add(
            "insight",
            f"Lookup engine took {start['engine_load_ms'] / 1000:.1f} s to prewarm its providers",
            f"Provider prewarm inside the hanly-lookup child: {loads}. The first hover waits "
            "for this; LookupPreload decides whether a launch pays it up front.",
            "hanly_app/composition.py (_prewarm_provider), lookup/process.py",
        )
    answered_total = stages.get("hover.total_to_answer")
    if (
        answered_total
        and answered_total["n"] >= 3
        and answered_total["max"] > 4 * answered_total["p50"]
    ):
        add(
            "warning",
            f"Slowest answer took {answered_total['max']:.0f} ms "
            f"vs median {answered_total['p50']:.0f} ms",
            "Usually the cold first lookup (engine still loading) or an OCR cache miss on a "
            "large region. Open the slowest hover in the explorer to see which segment grew.",
        )

    funnel_steps = {row["step"]: row["count"] for row in model["funnel"]}
    ocr_ran = funnel_steps.get("OCR ran", 0)
    hangul = funnel_steps.get("OCR found Hangul", 0)
    if ocr_ran >= 5 and hangul / ocr_ran < 0.6:
        add(
            "opportunity",
            f"{ocr_ran - hangul} of {ocr_ran} OCR runs found no Hangul",
            "Those runs cost full OCR to learn there was nothing to look up. A cheaper "
            "text-presence check before OCR, or a script-detection pass, would avoid them.",
            "hanly_app/composition.py (text-presence gate)",
        )
    episodes = model["episodes"]
    wasted = [
        e
        for e in episodes
        if e["outcome"] in {"stale", "cancelled", "abandoned"}
        and e["facts"].get("stages", {}).get("ocr")
    ]
    if wasted:
        spent = sum(e["facts"]["stages"].get("ocr", 0) for e in wasted)
        add(
            "insight",
            f"{len(wasted)} lookups ran OCR for an answer nobody saw ({spent:.0f} ms total)",
            "The pointer moved on before the answer arrived; the currency check correctly "
            "discarded it. Cancellation earlier in the engine would recover this time.",
            "hanly_app/lookup/controller.py",
        )
    retries = sum(1 for e in episodes if e["facts"].get("sensitive_retry"))
    if retries:
        add(
            "insight",
            f"OCR sensitive retry fired {retries} times",
            "A second, more sensitive recognition ran because the first read nothing at the "
            "pointer. Compare with tour accuracy to judge whether it earns its cost.",
            "hanly_app/composition.py",
        )

    procs = model["processes"]["summary"]
    lookup = procs.get("lookup")
    if lookup:
        add(
            "insight",
            f"Lookup engine peaked at {lookup['rss_mib']:.0f} MiB, "
            f"mean CPU {lookup['mean_cpu']:.0f}%",
            "Sampled RSS of the hanly-lookup child (its own helpers listed separately).",
            "hanly_app/lookup/process.py",
        )
    shell = procs.get("shell")
    if shell:
        add(
            "insight",
            f"Shell peaked at {shell['rss_mib']:.0f} MiB (includes the lab's own recorder)",
            "The lab hosts the shell in-process, so this includes recording overhead; "
            "compare with a plain `hanly` launch before treating it as product memory.",
            "hanly_app/application.py",
        )

    tour = model.get("tour")
    if tour and tour["scored"]:
        add(
            "insight" if tour["accuracy"] >= 0.9 else "warning",
            f"Tour accuracy {tour['accuracy']:.1%} over {tour['scored']} scored hovers",
            ", ".join(f"{k}: {v}" for k, v in tour["verdicts"].items()),
            "",
        )
        worst = [row for row in tour["by_font_px"] if row["n"] >= 5]
        if worst:
            low = min(worst, key=lambda row: row["accuracy"])
            if low["accuracy"] < tour["accuracy"] - 0.05:
                add(
                    "opportunity",
                    f"Accuracy drops to {low['accuracy']:.0%} at {low['group']} px text",
                    "Smaller glyphs give OCR fewer pixels per stroke; upscaling small ROIs before "
                    "recognition, or a larger capture scale, is the usual remedy.",
                    "hanly_app/acquisition/capture.py",
                )
        calibration = tour["calibration"]
        if len(calibration) >= 2:
            low_conf = calibration[0]
            if low_conf["accuracy"] < tour["accuracy"] - 0.1:
                add(
                    "opportunity",
                    f"Low OCR confidence ({low_conf['range']}) answers are right only "
                    f"{low_conf['accuracy']:.0%} of the time",
                    "Confidence separates good from bad reads, so a second check (re-recognize "
                    "at a higher scale, or ask the other backend) only when confidence is low "
                    "would target exactly the failures.",
                    "hanly/lookup_pipeline.py",
                )
            elif all(row["accuracy"] >= 0.95 for row in calibration):
                add(
                    "insight",
                    "OCR confidence does not predict errors in this run",
                    "Every confidence band answered correctly, so a confidence-triggered second "
                    "check would only add latency here. Re-check with smaller fonts or more words.",
                    "hanly/lookup_pipeline.py",
                )
        misread = sum(
            tour["verdicts"].get(kind, 0)
            for kind in ("misread", "wrong_word", "no_text", "unresolved")
        )
        lemma = tour["verdicts"].get("wrong_lemma", 0) + tour["verdicts"].get("not_found", 0)
        if misread or lemma:
            add(
                "warning",
                f"{misread} recognition/selection failures, {lemma} language/dictionary failures",
                "Recognition failures are fixed in OCR or the word resolver; language failures "
                "in morphology or dictionary querying even when the text was read correctly.",
                "",
            )
        obscured = tour["verdicts"].get("obscured", 0)
        if obscured:
            add(
                "warning",
                f"{obscured} hovers skipped: another window covered the page",
                "The lab refuses to read anything that is not its own page. These are not "
                "scored; close or move the covering window and rerun.",
                "",
            )
    if model["metadata"].get("dropped_events"):
        add(
            "warning",
            f"{model['metadata']['dropped_events']} trace events dropped",
            "The recorder's queue overflowed; counts in this report are lower bounds.",
            "",
        )
    return out


_WHERE = {
    "dwell": "hanly_app/hover/controller.py",
    "direct_text": "hanly_app/acquisition/direct_text.py",
    "capture": "hanly_app/acquisition/capture.py",
    "to_engine": "hanly_app/lookup/executor.py, lookup/transport.py",
    "ocr": "hanly/vision_provider.py, hanly/easyocr_provider.py",
    "language": "hanly/word_resolver.py, kiwi_provider.py, krdict_provider.py",
    "to_popup": "hanly_app/lookup/controller.py, popup/qt.py",
}


# -- small helpers ---------------------------------------------------------------------------


def describe(values: Iterable[float]) -> dict[str, Any]:
    items = sorted(float(v) for v in values)
    if not items:
        return {"n": 0}
    return {
        "n": len(items),
        "mean": round(sum(items) / len(items), 3),
        "p50": round(_percentile(items, 50), 3),
        "p90": round(_percentile(items, 90), 3),
        "p99": round(_percentile(items, 99), 3),
        "min": round(items[0], 3),
        "max": round(items[-1], 3),
    }


def _percentile(values: Sequence[float], percent: float) -> float:
    items = sorted(values)
    if not items:
        return 0.0
    rank = max(1, math.ceil(percent / 100 * len(items)))
    return items[rank - 1]


def _between(events: Sequence[Mapping[str, Any]], first: str, second: str) -> float | None:
    start = next((e["t_ms"] for e in events if e["event"] == first), None)
    end = next((e["t_ms"] for e in events if e["event"] == second), None)
    return None if start is None or end is None else round(end - start, 1)


def _ms(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value / 1e6


def _sort_key(group: str) -> tuple[int, Any]:
    try:
        return (0, float(group))
    except ValueError:
        return (1, group)


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


__all__ = ["SEGMENTS", "build_model", "describe", "episodes_from"]
