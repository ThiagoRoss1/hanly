"""Write a run's report: ``report.html`` for people, ``report.json`` and
``summary.md`` for tools and agents. All three come from the same model."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..comparison import headline
from ..identity import REPO_ROOT, RunIdentity, reproduction, run_identity
from ..metadata import source_identity
from ..session.scoring import RULE
from .model import SEGMENTS, build_model, compare_tours

_TEMPLATE = Path(__file__).with_name("template.html")
#: ``--baseline`` given without a run: the registered baseline for this run's key.
REGISTERED = "registered"


def build_report(run_dir: Path, *, baseline: Path | str | None = None) -> Path:
    """Write the run's reports; ``baseline`` adds a same-rule before/after comparison.

    ``REGISTERED`` picks the baseline the local registry holds for this run's
    compatibility key. Nothing is written beside the baseline.
    """

    run_dir = Path(run_dir)
    model = build_model(run_dir)
    identity = run_identity(run_dir)
    model["provenance"] = provenance_model(identity, model["metadata"])
    chosen, note = resolve_baseline(identity, baseline)
    model["comparison"] = None if chosen is None else compare_tours(chosen, model, run_dir)
    model["comparison_note"] = note
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


def resolve_baseline(
    identity: RunIdentity, baseline: Path | str | None
) -> tuple[Path | None, str | None]:
    """The baseline directory to compare with, or why there is none."""

    if baseline is None:
        return None, None
    if str(baseline) != REGISTERED:
        return Path(baseline), None
    from ..pins import PinError, load

    try:
        found = load().baseline_for(identity)
    except PinError as error:
        return None, f"no registered baseline was used: {error}"
    if found is None:
        return None, f"no registered baseline for {identity.compatibility_key}"
    return found.path, None


def provenance_model(
    identity: RunIdentity, metadata: dict[str, Any], current_rule: str = RULE
) -> dict[str, Any]:
    """Who recorded the run, from what, and with which code this report was rebuilt."""

    return {
        "identity": identity.as_dict(),
        "recorded_rules": list(identity.rules),
        "current_rule": current_rule,
        "rebuilt_with": source_identity(REPO_ROOT),
        "reproduce": reproduction(identity, metadata),
    }


def provenance_lines(provenance: dict[str, Any]) -> list[str]:
    """The compact report's provenance block, shared by sessions and campaigns."""

    identity = provenance["identity"]
    rebuilt = provenance["rebuilt_with"]
    reproduce = provenance["reproduce"]
    lines = [
        "## Provenance",
        "",
        f"- recorded from commit {identity['commit'][:12]}, checkout {identity['source_state']}"
        f" (changed during the run: {identity['source_changed']})",
        f"- platform {identity['system']} {identity['machine']}; OCR backend configured "
        f"{identity['configured_backend']}, observed "
        f"{', '.join(identity['observed_backends']) or 'none'}",
        f"- rule recorded {', '.join(provenance['recorded_rules']) or 'none'}; "
        f"shown under {provenance['current_rule']}",
        f"- ended: {identity['completion']}; measurement protocol "
        f"{identity['measurement_protocol']}",
        f"- this report was rebuilt with commit {rebuilt['commit'][:12]} ({rebuilt['state']})",
    ]
    for conflict in identity["conflicts"]:
        lines.append(f"- conflict: {conflict}")
    if reproduce["command"]:
        label = "exact" if reproduce["exact"] else "not exact"
        lines.append(f"- reproduce ({label}): `{reproduce['command']}`")
    for item in reproduce["missing"]:
        lines.append(f"  - unresolved: {item}")
    for item in reproduce["prerequisites"]:
        lines.append(f"  - needs: {item}")
    return lines


def comparison_lines(comparison: dict[str, Any] | None, note: str | None) -> list[str]:
    """Compatibility and the derived explanation lines, before any raw table."""

    if comparison is None:
        return [] if note is None else ["", "## Baseline", "", f"- {note}"]
    compat = comparison["compatibility"]
    lines = [
        "",
        f"## Compared with {comparison['baseline']} (both under {comparison['rule']})",
        "",
        f"- compatibility: {compat['status']}",
    ]
    lines += [f"  - reason: {reason}" for reason in compat["reasons"]]
    lines += [f"  - warning: {warning}" for warning in compat["warnings"]]
    lines += [f"  - performance not compared: {reason}" for reason in compat["performance_reasons"]]
    lines += [f"- {line}" for line in headline(comparison)]
    outcome = comparison["outcomes"]
    lines.append(
        f"- coverage: {outcome['matched']} matched occurrences, {outcome['only_before']} only "
        f"before, {outcome['only_after']} only after; {outcome['counts']}"
    )
    failures = outcome["failure_set"]
    for label in ("introduced", "resolved"):
        if failures[label]:
            lines.append(f"- {label}: {', '.join(failures[label][:40])}")
    return lines


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


def _read(tour: dict[str, Any], row: dict[str, Any]) -> str:
    """What was read, or only its counts when the run retained no text."""

    if tour.get("text_included"):
        return f"{row.get('headword')} | {' / '.join(row.get('recognized') or [])}"
    return (
        f"(not retained) | {row.get('recognized_regions') or 0} region(s), "
        f"{row.get('queries_found') or 0}/{row.get('queries_tried') or 0} queries found"
    )


def _ended(tour: dict[str, Any]) -> str:
    completion = tour.get("completion") or {}
    ended = completion.get("ended", "unknown")
    if ended == "finished":
        return "finished"
    hovered, planned = completion.get("hovered"), completion.get("planned")
    return f"{ended} after {hovered} of {planned} planned hovers"


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
        f"- mode: {meta.get('mode')}"
        f"  duration: {model['duration_ms'] / 1000:.1f} s"
        f"  events: {sum(model['event_counts'].values())}"
        f"  dropped: {meta.get('dropped_events', 0)}",
        "",
        *provenance_lines(model["provenance"]),
        *comparison_lines(model.get("comparison"), model.get("comparison_note")),
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
        raw = "" if comparison["compatibility"]["status"] == "comparable" else " (raw only)"
        lines += [
            "",
            f"## Raw comparison with {comparison['baseline']}{raw}",
            "",
            f"- before: {before['passed']}/{before['scored']} scored "
            f"({_pct(before['accuracy'])}), {before['unscored']} unscored",
            f"- after: {after['passed']}/{after['scored']} scored "
            f"({_pct(after['accuracy'])}), {after['unscored']} unscored",
            f"- matched occurrences: {comparison['matched']}  only before: "
            f"{comparison['only_before']}  only after: {comparison['only_after']}",
            f"- popup median: {comparison['before_popup_ms'].get('p50')} -> "
            f"{comparison['after_popup_ms'].get('p50')} ms",
            "",
            "| occurrence | expected | before | after | answer before | answer after |",
            "|---|---|---|---|---|---|",
        ]
        for row in comparison["changed"]:
            lines.append(
                f"| {row['occurrence']} | {row['expected']} | {row['before']} | {row['after']} | "
                f"{row['before_answer'] or '–'} | {row['after_answer'] or '–'} |"
            )
    tour = model.get("tour")
    if tour:
        accuracy = f"{_pct(tour['accuracy'])} under {tour['rule']}"
        lines += [
            "",
            "## Tour",
            "",
            f"- accuracy: {accuracy} over {tour['scored']} scored",
            f"- ended: {_ended(tour)}",
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
                    f"{_read(tour, row)} | {row['confidence']} | {row['font_px']} |"
                )
    return "\n".join(lines) + "\n"


__all__ = ["build_report", "summary_markdown", "system_map"]
