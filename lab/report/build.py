"""Write a run's report: ``report.html`` for people, ``report.json`` and
``summary.md`` for tools and agents. All three come from the same model."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .model import SEGMENTS, build_model, compare_tours

_TEMPLATE = Path(__file__).with_name("template.html")


def build_report(run_dir: Path, *, baseline: Path | None = None) -> Path:
    """Write the run's reports; ``baseline`` adds a same-rule before/after comparison."""

    run_dir = Path(run_dir)
    model = build_model(run_dir)
    model["comparison"] = None if baseline is None else compare_tours(Path(baseline), model)
    model["run"] = run_dir.name
    model["segments"] = [list(pair) for pair in SEGMENTS]
    model["map"] = system_map(model)
    (run_dir / "report.json").write_text(
        json.dumps(model, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )
    (run_dir / "summary.md").write_text(summary_markdown(model), encoding="utf-8")
    payload = json.dumps(model, ensure_ascii=False, default=str).replace("</", "<\\/")
    html = _TEMPLATE.read_text(encoding="utf-8").replace("/*__MODEL__*/null", payload)
    path = run_dir / "report.html"
    path.write_text(html, encoding="utf-8")
    return path


def system_map(model: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Every component the report draws, with what this run measured at it."""

    counts = model["event_counts"]
    stages = {row["name"]: row for row in model["stages"]}
    procs = model["processes"]["summary"]
    episodes = model["episodes"]

    def p50(name: str) -> float | None:
        row = stages.get(name)
        return None if row is None else row["p50"]

    def n(name: str) -> int:
        return int(counts.get(name, 0))

    backend = next(
        (e["facts"].get("ocr_backend") for e in episodes if e["facts"].get("ocr_backend")), None
    )
    used_direct = sum(1 for e in episodes if e["facts"].get("acquisition") == "direct_text")
    gate_rejected = sum(1 for e in episodes if e["facts"].get("gate") == "rejected")
    return {
        "mouse": {
            "count": n("hover_mouse_opportunity"),
            "detail": f"{n('hover_invalidation')} invalidated by further movement",
        },
        "hover": {
            "count": n("hover_stable_fire"),
            "p50": p50("hover.dwell"),
            "detail": f"{n('hover_cancellation')} cancelled",
        },
        "retained": {
            "count": n("hover_inside_retained_target"),
            "detail": f"{n('retained_target')} answers retained under the pointer",
        },
        "direct": {
            "count": n("hover_direct_text"),
            "p50": p50("hover.direct_text"),
            "detail": f"{used_direct} read without pixels",
        },
        "capture": {
            "count": n("hover_capture_completed"),
            "p50": p50("hover.capture"),
            "detail": f"{n('hover_capture_error')} errors",
        },
        "controller": {
            "count": n("lookup_submit"),
            "detail": f"{n('lookup_invalidate')} invalidations",
        },
        "executor": {
            "count": n("executor_work_started"),
            "p50": p50("hover.to_engine"),
            "detail": f"{n('executor_pending_replaced')} pending replaced (latest wins)",
        },
        "cache": {
            "count": n("lookup_cache_hit") + n("lookup_cache_miss"),
            "detail": f"{n('lookup_cache_hit')} hits, {n('lookup_cache_miss')} misses",
        },
        "gate": {
            "count": n("lookup_cache_miss"),
            "detail": f"{gate_rejected} flat regions rejected",
        },
        "ocr": {
            "count": _stage_n(stages, "engine.ocr"),
            "p50": p50("engine.ocr"),
            "label": f"OCR ({backend})" if backend else "OCR",
            "detail": f"{n('ocr_sensitive_retry')} sensitive retries",
        },
        "resolver": {
            "count": _stage_n(stages, "engine.token_selection"),
            "p50": p50("engine.token_selection"),
        },
        "morphology": {
            "count": _stage_n(stages, "engine.morphology"),
            "p50": p50("engine.morphology"),
        },
        "dictionary": {
            "count": _stage_n(stages, "engine.dictionary"),
            "p50": p50("engine.dictionary"),
        },
        "currency": {
            "count": n("lookup_current_delivered"),
            "detail": f"{n('lookup_stale_suppressed')} stale answers discarded",
        },
        "popup": {
            "count": n("popup_visible"),
            "p50": p50("hover.to_popup"),
            "detail": f"{n('popup_suppressed')} non-answers not shown",
        },
        "process.shell": procs.get("shell", {}),
        "process.lookup": procs.get("lookup", {}),
        "process.control_center": procs.get("control_center", {}),
    }


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def _stage_n(stages: dict[str, Any], name: str) -> int:
    row = stages.get(name)
    return 0 if row is None else int(row["n"])


def summary_markdown(model: dict[str, Any]) -> str:
    meta = model["metadata"]
    lines = [
        f"# Hanly Lab - {model['run']}",
        "",
        f"- mode: {meta.get('mode')}  commit: {str(meta.get('commit', ''))[:12]}"
        f"{' (dirty)' if meta.get('dirty') else ''}  platform: {meta.get('platform')}",
        f"- duration: {model['duration_ms'] / 1000:.1f} s"
        f"  events: {sum(model['event_counts'].values())}"
        f"  dropped: {meta.get('dropped_events', 0)}",
        "",
        "## Findings",
        "",
    ]
    for finding in model["findings"]:
        where = f" - `{finding['where']}`" if finding["where"] else ""
        lines.append(f"- **{finding['level']}** {finding['title']}{where}")
        lines.append(f"  {finding['detail']}")
    lines += ["", "## Funnel", ""]
    lines += [
        f"- {row['step']}: {row['count']}" + (f" ({row['note']})" if row.get("note") else "")
        for row in model["funnel"]
    ]
    lines += ["", "## Median segment of an uncached answer (ms)", ""]
    for name, label in SEGMENTS:
        lines.append(f"- {label}: {model['breakdown']['median_ms'].get(name, 0):.1f}")
    lines += [
        "",
        "## Stage latency (ms)",
        "",
        "| stage | n | p50 | p90 | p99 | max |",
        "|---|---|---|---|---|---|",
    ]
    for row in model["stages"]:
        lines.append(
            f"| {row['name']} | {row['n']} | {row['p50']:.1f} | {row['p90']:.1f} | "
            f"{row['p99']:.1f} | {row['max']:.1f} |"
        )
    lines += [
        "",
        "## Processes",
        "",
        "| role | peak MiB | final MiB | mean CPU % | peak threads |",
        "|---|---|---|---|---|",
    ]
    for role, row in model["processes"]["summary"].items():
        lines.append(
            f"| {role} | {row['rss_mib']} | {row['final_rss_mib']} | "
            f"{row['mean_cpu']} | {row['threads']} |"
        )
    comparison = model.get("comparison")
    if comparison:
        before, after = comparison["before"], comparison["after"]
        lines += [
            "",
            f"## Compared with {comparison['baseline']} (both under {comparison['rule']})",
            "",
            f"- before: {before['passed']}/{before['scored']} scored "
            f"({_pct(before['accuracy'])}), {before['unscored']} unscored",
            f"- after: {after['passed']}/{after['scored']} scored "
            f"({_pct(after['accuracy'])}), {after['unscored']} unscored",
            f"- matched targets: {comparison['matched']}  only before: "
            f"{comparison['only_before']}  only after: {comparison['only_after']}",
            f"- popup median: {comparison['before_popup_ms'].get('p50')} -> "
            f"{comparison['after_popup_ms'].get('p50')} ms",
            "",
            "| target | expected | before | after | answer before | answer after |",
            "|---|---|---|---|---|---|",
        ]
        for row in comparison["changed"]:
            lines.append(
                f"| {row['target']} | {row['expected']} | {row['before']} | {row['after']} | "
                f"{row['before_answer']} | {row['after_answer']} |"
            )
    tour = model.get("tour")
    if tour:
        accuracy = f"{_pct(tour['accuracy'])} under {tour['rule']}"
        lines += [
            "",
            "## Tour",
            "",
            f"- accuracy: {accuracy} over {tour['scored']} scored",
            f"- verdicts: {tour['verdicts']}",
            "",
        ]
        for key in ("by_font_px", "by_theme", "by_font", "by_source"):
            lines.append(
                f"- {key}: "
                + ", ".join(
                    f"{row['group']} {row['accuracy']:.0%} (n={row['n']})" for row in tour[key]
                )
            )
        if tour["failures"]:
            lines += [
                "",
                "### Failures",
                "",
                "| target | expected | verdict | answer | recognized | conf | px |",
                "|---|---|---|---|---|---|---|",
            ]
            for row in tour["failures"][:80]:
                lines.append(
                    f"| {row['target']} | {row['expected']} | {row['verdict']} | "
                    f"{row['headword']} | {' / '.join(row['recognized'] or [])} | "
                    f"{row['confidence']} | {row['font_px']} |"
                )
    return "\n".join(lines) + "\n"


__all__ = ["build_report", "summary_markdown", "system_map"]
