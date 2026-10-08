"""Turn a stress campaign's recording into ``campaign.json``, ``.md`` and ``.html``.

Rebuilt from ``events.jsonl``, ``metadata.json`` and ``processes.jsonl`` alone,
so a campaign can be re-scored under a later rule without re-running it. Read
text appears only for a run that retained fixture text, and only lab-authored
text ever can.
"""

from __future__ import annotations

import html
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from ..comparison import (
    POLICY,
    compare_outcomes,
    compatibility,
    performance,
    process_roles,
    stress_occurrence,
)
from ..identity import run_identity
from ..session.scoring import UNSCORED
from ..session.stress import NEGATIVE
from ..session.stress_scoring import (
    CORPUS_RULE,
    INFORMATION,
    PASS,
    RULE,
    failing_stage,
    stress_verdict,
    summarize,
)
from ..stage_evidence import FALSE, TRUE, UNAVAILABLE, stability

_ORDER = (
    "word", "story", "cursor", "dense", "mixed_korean", "image_text", "repeat", "rapid",
    "uia_korean", "leave_early", "blank", "number", "punctuation", "latin", "mixed_latin",
    "icon", "image_none", "after_popup", "uia_latin", "changing", "covered",
)


def build_campaign(run_dir: Path, *, baseline: Path | str | None = None) -> dict[str, Any]:
    """Score every recorded hover under the current rule and write all three files.

    ``baseline`` adds a comparison with an earlier campaign, re-scored under
    the same rule; nothing is written beside it.
    """

    from .build import provenance_model, resolve_baseline

    metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    rows = _scored(run_dir)
    recorded = Counter(str(row.get("recorded_verdict")) for row in rows)
    identity = run_identity(run_dir)
    chosen, note = resolve_baseline(identity, baseline)
    model: dict[str, Any] = {
        "run": run_dir.name,
        "rule": _rules(rows),
        "commit": metadata.get("commit"),
        "dirty": metadata.get("dirty"),
        "platform": metadata.get("platform"),
        "options": metadata.get("options"),
        "planned": metadata.get("plan") or {},
        "planned_total": sum((metadata.get("plan") or {}).values()),
        "ended": _ended(run_dir),
        "summary": summarize(rows),
        "changed_since_recording": sum(
            1 for row in rows if row["recorded_verdict"] != row["verdict"]
        ),
        "recorded_verdicts": dict(recorded),
        "latency": _latency(rows),
        "processes": _processes(run_dir),
        "failures": _failures(rows, bool(metadata.get("fixture_text_retained"))),
        "acquisition": _acquisition(rows),
        "informational": _informational(rows),
        "provenance": provenance_model(identity, metadata, current_rule=_rules(rows)),
        "comparison_note": note,
        "corpus": corpus_summary(rows),
    }
    model["comparison"] = (
        None if chosen is None else compare_campaigns(chosen, model, rows, run_dir)
    )
    (run_dir / "campaign.json").write_text(
        json.dumps(model, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (run_dir / "campaign.md").write_text(_markdown(model), encoding="utf-8")
    (run_dir / "campaign.html").write_text(_html(model), encoding="utf-8")
    return model


def compare_campaigns(
    baseline_dir: Path, current: dict[str, Any], rows: list[dict[str, Any]], run_dir: Path
) -> dict[str, Any]:
    """The current campaign against an earlier one, occurrence by occurrence."""

    before_rows = _scored(baseline_dir)
    compat = compatibility(run_identity(baseline_dir), run_identity(run_dir))
    eligible = compat["eligible"]
    outcomes = compare_outcomes(
        before_rows,
        rows,
        key=stress_occurrence,
        passes=PASS,
        unscored=UNSCORED,
        informational=INFORMATION | {"observed"},
        eligible=eligible["correctness"],
    )
    before_latency = _latency(before_rows)["all"]
    after_latency = current["latency"]["all"]
    before_processes = _processes(baseline_dir)
    before_rss = before_processes.get("peak_rss_mib", {})
    after_rss = current["processes"].get("peak_rss_mib", {})
    rss_samples = (before_processes.get("samples"), current["processes"].get("samples"))
    return {
        "baseline": baseline_dir.name,
        "rule": current["rule"],
        "compatibility": compat,
        "before": summarize(before_rows),
        "after": current["summary"],
        "outcomes": outcomes,
        "process_roles": process_roles(before_rss or None, after_rss or None),
        "performance": [
            performance(
                "popup p50",
                before_latency["p50"],
                after_latency["p50"],
                POLICY.popup_p50,
                eligible=eligible["latency"],
                samples=(before_latency["n"], after_latency["n"]),
            ),
            *(
                performance(
                    f"{role} peak sampled RSS",
                    before_rss.get(role),
                    after_rss.get(role),
                    POLICY.sampled_rss,
                    eligible=eligible["memory"],
                    samples=rss_samples,
                )
                for role in ("lookup", "shell")
            ),
        ],
    }


def corpus_summary(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Controlled-image hovers: desktop stage facts and per-case stability over rounds."""

    corpus = [row for row in rows if row.get("family") == "corpus"]
    if not corpus:
        return None
    surface = [row for row in corpus if row.get("truth_target") == "surface"]
    quiet = [row for row in corpus if row.get("truth_target") == "no_korean"]
    by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in corpus:
        verdict = str(row.get("verdict"))
        # A cached answer repeats an earlier recognition; it is not a fresh one.
        judged = verdict not in UNSCORED and verdict not in INFORMATION and not _cached(row)
        ok = verdict in PASS if judged else None
        by_case[str(row.get("case"))].append(
            {"output": verdict, "ok": ok, "error": verdict == "error"}
        )
    cases = {case: stability(observations) for case, observations in sorted(by_case.items())}
    selected = [row for row in surface if row.get("verdict") == "target_selected"]
    unjudged = UNSCORED | {"timed_out", "error", "no_hover", "no_result"}
    return {
        "rule": CORPUS_RULE,
        "hovers": len(corpus),
        "cached_hovers": sum(1 for row in corpus if _cached(row)),
        "verdicts": dict(Counter(str(row.get("verdict")) for row in corpus).most_common()),
        "facts": {
            "target_surface_correct": _fact(surface, "target_selected", _SURFACE_FAILURES),
            "false_presentation": _fact(quiet, "false_answer", {"quiet"}),
            "stale_presentation": _fact(corpus, "stale_popup", _PRESENTED_OR_QUIET),
        },
        # A selected target the dictionary then missed is a language outcome only.
        "language_after_selection": dict(Counter(str(row.get("status")) for row in selected)),
        "not_judged": dict(
            Counter(str(row.get("verdict")) for row in corpus if row.get("verdict") in unjudged)
        ),
        "first_bad_stage": dict(Counter(str(row["stage"]) for row in corpus if row.get("stage"))),
        "stability": {
            "classes": dict(Counter(row["classification"] for row in cases.values())),
            "cases": cases,
        },
    }


_SURFACE_FAILURES = frozenset({"no_text", "unresolved", "misread", "wrong_word"})
_PRESENTED_OR_QUIET = frozenset({"target_selected", "quiet", "false_answer"}) | _SURFACE_FAILURES


def _fact(
    rows: list[dict[str, Any]], true: str, false: frozenset[str] | set[str]
) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        verdict = row.get("verdict")
        counts[TRUE if verdict == true else FALSE if verdict in false else UNAVAILABLE] += 1
    return dict(counts)


def _rules(rows: list[dict[str, Any]]) -> str:
    """The rules this campaign's hovers are judged under, now."""

    rules = {CORPUS_RULE if row.get("family") == "corpus" else RULE for row in rows}
    return ", ".join(sorted(rules)) or RULE


def _scored(run_dir: Path) -> list[dict[str, Any]]:
    """Every recorded hover re-scored under the current rule; the recording is untouched."""

    rows = [event for event in _events(run_dir) if event.get("event") == "stress_result"]
    for row in rows:
        row["recorded_verdict"] = row.get("verdict")
        row["verdict"] = stress_verdict(row)
        row["stage"] = failing_stage(row)
    return rows


def _events(run_dir: Path) -> list[dict[str, Any]]:
    with (run_dir / "events.jsonl").open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _ended(run_dir: Path) -> str:
    names = {event.get("event") for event in _events(run_dir)}
    for name, label in (
        ("tour_finished", "finished"),
        ("tour_stopped_by_user", "stopped_by_user"),
        ("tour_aborted", "aborted"),
    ):
        if name in names:
            return label
    # The driver never recorded an end: the session stopped under it.
    return "interrupted"


def _latency(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Popup latency of fresh answers; answers from the lookup cache are kept apart."""

    by_family: dict[str, list[float]] = defaultdict(list)
    cached: list[float] = []
    for row in rows:
        value = row.get("hover_to_popup_ms")
        if isinstance(value, (int, float)) and row.get("popup"):
            if _cached(row):
                cached.append(float(value))
            else:
                by_family[str(row.get("family"))].append(float(value))
    every = sorted(value for values in by_family.values() for value in values)
    return {
        "all": _percentiles(every),
        "cached": _percentiles(sorted(cached)),
        "families": {name: _percentiles(sorted(values)) for name, values in by_family.items()},
    }


def _cached(row: dict[str, Any]) -> bool:
    hits = row.get("cache_hits")
    return isinstance(hits, int) and not isinstance(hits, bool) and hits > 0


def _percentiles(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"n": 0, "p50": None, "p90": None, "max": None}

    def rank(fraction: float) -> float:
        return round(values[min(len(values) - 1, int(fraction * len(values)))], 1)

    return {"n": len(values), "p50": rank(0.5), "p90": rank(0.9), "max": round(values[-1], 1)}


def _processes(run_dir: Path) -> dict[str, Any]:
    peaks: dict[str, float] = {}
    samples = 0
    path = run_dir / "processes.jsonl"
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            samples += 1
            for row in json.loads(line).get("processes", []):
                if isinstance(row.get("rss"), int):
                    role = str(row.get("role"))
                    peaks[role] = max(peaks.get(role, 0.0), row["rss"] / 2**20)
    return {
        "peak_rss_mib": {role: round(value, 1) for role, value in sorted(peaks.items())},
        "samples": samples,
        "note": "sampled resident memory every 250 ms; not private memory, not a precise peak",
    }


def _failures(rows: list[dict[str, Any]], retained: bool) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        if row["verdict"] in PASS or row.get("stage") is None:
            continue
        entry = {
            key: row.get(key)
            for key in (
                "target", "family", "behavior", "surface", "expected", "verdict", "stage",
                "font", "font_px", "theme", "raster", "graphic", "acquisition", "direct_text",
                "gate", "cache_hits", "status", "hover_to_popup_ms", "replay_image",
            )
        }
        if retained:
            entry.update({key: row.get(key) for key in ("selected", "headword", "recognized")})
        out.append(entry)
    return out


def _acquisition(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    table: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        table[str(row.get("family"))][str(row.get("acquisition") or "none")] += 1
    return {family: dict(counts) for family, counts in sorted(table.items())}


def _informational(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "target": row.get("target"),
            "family": row.get("family"),
            "popup": row.get("popup"),
            "observed": row.get("observed"),
            "unscored": row.get("unscored"),
        }
        for row in rows
        if row.get("family") in {"changing", "covered"}
    ]


# -- rendering ----------------------------------------------------------------------


def _markdown(model: dict[str, Any]) -> str:
    from .build import comparison_lines, provenance_lines

    summary = model["summary"]
    lines = [
        f"# Stress campaign - {model['run']}",
        "",
        *provenance_lines(model["provenance"]),
        *comparison_lines(model.get("comparison"), model.get("comparison_note")),
        "",
        "## Campaign",
        "",
        f"- rule {model['rule']}; ended: {model['ended']}",
        f"- planned {model['planned_total']}, executed {summary['executed']}, "
        f"scored {summary['scored']}, unscored {summary['unscored']}",
        f"- passed {summary['passed']} of {summary['scored']}"
        + (f" ({summary['accuracy']:.1%})" if summary["accuracy"] is not None else ""),
        f"- false presentations {summary['false_positives']} of {summary['negatives_scored']} "
        f"negatives ({summary['negatives_failed_otherwise']} more timed out or errored); "
        f"missing or wrong answers {summary['missing_answers']} of "
        f"{summary['positives_scored']} positives",
        "",
        "## Families",
        "",
        "| family | planned | verdicts |",
        "|---|---|---|",
    ]
    for family in _families(model):
        verdicts = ", ".join(
            f"{name} {count}" for name, count in sorted(summary["families"].get(family, {}).items())
        )
        lines.append(f"| {family} | {model['planned'].get(family, '')} | {verdicts} |")
    corpus = model.get("corpus")
    if corpus:
        lines += [
            "",
            f"## Controlled images ({corpus['rule']})",
            "",
            f"- hovers {corpus['hovers']}; verdicts {corpus['verdicts']}",
            *(f"- {name}: {counts}" for name, counts in corpus["facts"].items()),
            "- after a selected target the dictionary answered: "
            f"{corpus['language_after_selection']}",
            f"- not judged: {corpus['not_judged'] or 'none'}",
            f"- stability over rounds: {corpus['stability']['classes']}",
        ]
    lines += ["", "## Failing stages", ""]
    lines += [f"- {stage}: {count}" for stage, count in summary["stages"].items()] or ["- none"]
    latency = model["latency"]["all"]
    lines += [
        "",
        f"Hover to popup (fresh answers): n={latency['n']} p50={latency['p50']} ms "
        f"p90={latency['p90']} ms; answered from the cache: n={model['latency']['cached']['n']}",
        "",
        "Peak sampled RSS (MiB): "
        + ", ".join(f"{k} {v}" for k, v in model["processes"].get("peak_rss_mib", {}).items()),
        "",
    ]
    return "\n".join(lines)


def _families(model: dict[str, Any]) -> list[str]:
    present = set(model["planned"]) | set(model["summary"]["families"])
    return [name for name in _ORDER if name in present] + sorted(present - set(_ORDER))


_CSS = """
:root { --bg:#fbfbf9; --fg:#1d1f23; --muted:#6a6f78; --ok:#2f8f5b; --bad:#c2453b;
  --info:#9aa3ad; --line:#e3e3df; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#17191c; --fg:#e8e8e6; --muted:#9aa0a8; --line:#2c3036; } }
body { margin:0; padding:24px 16px; background:var(--bg); color:var(--fg);
  font:14px/1.5 system-ui, sans-serif; }
main { max-width:1180px; margin:0 auto; }
h1 { font-size:22px; margin:0 0 4px; } h2 { font-size:16px; margin:28px 0 8px; }
.muted { color:var(--muted); }
.kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:10px;
  margin:16px 0; }
.kpi { border:1px solid var(--line); border-radius:8px; padding:10px 12px; }
.kpi b { display:block; font-size:22px; }
table { width:100%; border-collapse:collapse; font-size:13px; }
td, th { border-bottom:1px solid var(--line); padding:5px 6px; text-align:left;
  vertical-align:top; }
.scroll { overflow-x:auto; }
td.bars { width:30%; } .bar { display:inline-block; height:12px; }
.ok { background:var(--ok); } .bad { background:var(--bad); } .info { background:var(--info); }
"""

#: Verdicts drawn grey: evidence or unscored, neither pass nor fail.
_GREY = frozenset(
    {
        "observed", "answered_before_leaving", "not_submitted", "obscured",
        "obscured_during_capture", "unverifiable_region",
    }
)
_FAILURE_COLUMNS = (
    "target", "family", "expected", "verdict", "stage", "font", "font_px", "theme",
    "raster", "selected", "headword",
)


def _cell(value: object) -> str:
    return f"<td>{html.escape('' if value is None else str(value))}</td>"


def _row(values: list[object]) -> str:
    return "<tr>" + "".join(_cell(value) for value in values) + "</tr>"


def _header(names: list[str]) -> str:
    return "<tr>" + "".join(f"<th>{html.escape(name)}</th>" for name in names) + "</tr>"


def _bars(verdicts: dict[str, int]) -> str:
    total = sum(verdicts.values()) or 1
    parts = []
    for name, count in sorted(verdicts.items(), key=lambda item: item[0] not in PASS):
        tone = "ok" if name in PASS else "info" if name in _GREY else "bad"
        width = 100 * count / total
        parts.append(
            f'<span class="bar {tone}" style="width:{width:.1f}%" '
            f'title="{html.escape(name)} {count}"></span>'
        )
    return "".join(parts)


def _kpi(label: str, value: str) -> str:
    return f'<div class="kpi"><span class="muted">{html.escape(label)}</span><b>{value}</b></div>'


def _html(model: dict[str, Any]) -> str:
    summary = model["summary"]
    family_rows = []
    for family in _families(model):
        verdicts = summary["families"].get(family, {})
        detail = ", ".join(f"{name} {count}" for name, count in sorted(verdicts.items()))
        family_rows.append(
            f"<tr><td>{html.escape(family)}</td>"
            f"<td>{'negative' if family in NEGATIVE else 'positive'}</td>"
            f"{_cell(model['planned'].get(family, ''))}{_cell(sum(verdicts.values()))}"
            f'<td class="bars">{_bars(verdicts)}</td>{_cell(detail)}</tr>'
        )
    stages = "".join(_row([stage, count]) for stage, count in summary["stages"].items())
    failures = "".join(
        _row([row.get(name) or (row.get("graphic") if name == "raster" else None)
              for name in _FAILURE_COLUMNS])
        for row in model["failures"]
    )
    latency = model["latency"]["all"]
    rss = ", ".join(f"{k} {v}" for k, v in model["processes"].get("peak_rss_mib", {}).items())
    accuracy = "" if summary["accuracy"] is None else f" ({summary['accuracy']:.1%})"
    meta = " · ".join(
        html.escape(str(part))
        for part in (
            model["run"],
            f"commit {str(model['commit'])[:12]} (dirty: {model['dirty']})",
            model["platform"],
            f"rule {model['rule']}",
            f"ended {model['ended']}",
        )
    )
    kpis = "".join(
        (
            _kpi("planned / executed", f"{model['planned_total']} / {summary['executed']}"),
            _kpi("scored / unscored", f"{summary['scored']} / {summary['unscored']}"),
            _kpi("passed", f"{summary['passed']}{accuracy}"),
            _kpi(
                "false presentations",
                f"{summary['false_positives']} / {summary['negatives_scored']}",
            ),
            _kpi("negatives timed out or errored", str(summary["negatives_failed_otherwise"])),
            _kpi(
                "missing or wrong answers",
                f"{summary['missing_answers']} / {summary['positives_scored']}",
            ),
            _kpi("hover → popup p50 / p90", f"{latency['p50']} / {latency['p90']} ms"),
        )
    )
    families_header = _header(["family", "kind", "planned", "executed", "verdicts", ""])
    failures_header = _header(
        ["target", "family", "expected", "verdict", "stage", "face", "px", "theme",
         "raster/graphic", "selected", "answered"]
    )
    note = html.escape(model["processes"].get("note", ""))
    return "\n".join(
        [
            '<!doctype html><html lang="en"><head><meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            f"<title>Stress campaign</title><style>{_CSS}</style></head><body><main>",
            "<h1>Text-acquisition stress campaign</h1>",
            f'<div class="muted">{meta}</div>',
            f'<div class="kpis">{kpis}</div>',
            "<h2>Families</h2>",
            f'<div class="scroll"><table>{families_header}{"".join(family_rows)}</table></div>',
            "<h2>Where failures point</h2>",
            f"<table>{_header(['stage', 'hovers'])}{stages}</table>",
            "<h2>Failures</h2>",
            f'<div class="scroll"><table>{failures_header}{failures}</table></div>',
            f"<h2>Resources</h2><p>Peak sampled RSS (MiB): {html.escape(rss)}. {note}</p>",
            f'<p class="muted">Scores are on lab-authored content under {model["rule"]}; '
            "they are not general OCR or translation accuracy.</p>",
            "</main></body></html>",
            "",
        ]
    )

__all__ = ["build_campaign"]
