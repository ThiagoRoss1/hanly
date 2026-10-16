"""Compare a baseline and a candidate resource experiment, refusing unfair pairs.

Compatibility comes first: identical protocol, inputs, plan, recognizer,
library versions and host description. Then behaviour, then cost. A change is
only labelled; acceptance stays a human decision that needs this evidence, its
trade-offs and regression coverage.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

#: A memory difference inside this band is reported as unchanged. Not
#: calibrated against run-to-run variance; repeats and ranges decide trust.
MEMORY_BAND = (0.05, 16 * 2**20)
LATENCY_BAND = (0.05, 5.0)
#: Bytes retained per repeated operation; what decides unbounded growth.
GROWTH_BAND = (0.05, 4096.0)

#: Repeats per side before a timing difference may be called a change. Two
#: identical-code runs of three repeats each labelled six timings "improved" on
#: a busy Mac (2026-10-15); memory produced no such false label.
MIN_TIMING_REPEATS = 5

#: Library versions that may differ without changing what was measured.
_IGNORED_VERSIONS = frozenset({"hanly", "hanly-app"})


def load(run_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    return metadata, summary


def compatibility(
    baseline: tuple[Mapping[str, Any], Mapping[str, Any]],
    candidate: tuple[Mapping[str, Any], Mapping[str, Any]],
) -> list[str]:
    """Reasons the pair cannot be compared; empty when it can."""

    (base_meta, base), (cand_meta, cand) = baseline, candidate
    reasons: list[str] = []
    if base["protocol"] != cand["protocol"]:
        reasons.append(f"protocol {base['protocol']} against {cand['protocol']}")
    if base["primary_memory"] != cand["primary_memory"]:
        reasons.append("different primary memory metric")
    if base.get("input_digest") != cand.get("input_digest"):
        reasons.append("different inputs")
    plan_keys = ("ocr_backend", "lookups", "idle_seconds", "inputs", "warmup_runs")
    for key in plan_keys:
        if base["plan"].get(key) != cand["plan"].get(key):
            reasons.append(f"plan {key}: {base['plan'].get(key)} against {cand['plan'].get(key)}")
    for name, version in (base_meta.get("versions") or {}).items():
        other = (cand_meta.get("versions") or {}).get(name)
        if name not in _IGNORED_VERSIONS and version != other:
            reasons.append(f"{name} {version} against {other}")
    host = (base_meta.get("lab_provenance") or {}).get("host")
    if host != (cand_meta.get("lab_provenance") or {}).get("host"):
        reasons.append("different host description")
    if min(base["plan"]["repeats"], cand["plan"]["repeats"]) < 2:
        reasons.append("fewer than two repeats on one side; spread is unknown")
    return reasons


def compare(baseline_dir: Path, candidate_dir: Path) -> dict[str, Any]:
    baseline, candidate = load(baseline_dir), load(candidate_dir)
    reasons = compatibility(baseline, candidate)
    base, cand = baseline[1], candidate[1]
    behaviour = _behaviour(base, cand)
    experiments: dict[str, Any] = {}
    for label in sorted(set(base["experiments"]) & set(cand["experiments"])):
        experiments[label] = _experiment(
            base["experiments"][label]["aggregate"], cand["experiments"][label]["aggregate"]
        )
    return {
        "baseline": baseline_dir.name,
        "candidate": candidate_dir.name,
        "comparable": not reasons,
        "reasons": reasons,
        "behaviour": behaviour,
        "experiments": experiments,
        "calibration": _calibration(cand),
        "decision": "not made here: accepting a change needs reproducible evidence, "
                    "documented trade-offs and regression coverage",
    }


def _behaviour(base: Mapping[str, Any], cand: Mapping[str, Any]) -> str:
    left = (base.get("correctness") or {}).get("signature")
    right = (cand.get("correctness") or {}).get("signature")
    if left is None or right is None:
        return "unavailable"
    if not (base["correctness"].get("stable_across_repeats")
            and cand["correctness"].get("stable_across_repeats")):
        return "unstable"
    return "unchanged" if left == right else "changed"


def _experiment(base: Mapping[str, Any], cand: Mapping[str, Any]) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for name in sorted(set(base["derived"]) & set(cand["derived"])):
        rows[name] = _label(name, base["derived"][name], cand["derived"][name])
    stages: dict[str, Any] = {}
    for stage in base["stages"]:
        if stage not in cand["stages"]:
            continue
        stages[stage] = {
            key: _label(key, base["stages"][stage].get(key), cand["stages"][stage].get(key))
            for key in (
                "memory_after", "sampled_peak", "duration_ms", "latency_p50",
                "growth_per_operation",
            )
        }
    return {"derived": rows, "stages": stages}


def _label(
    name: str, base: Mapping[str, Any] | None, cand: Mapping[str, Any] | None
) -> dict[str, Any]:
    if not base or not cand:
        return {"label": "unavailable"}
    left, right = base["median"], cand["median"]
    timing = name.endswith("_ms") or name.startswith("latency") or name.endswith("seconds")
    growth = name.startswith("growth")
    relative, absolute = LATENCY_BAND if timing else GROWTH_BAND if growth else MEMORY_BAND
    band = max(abs(left) * relative, absolute)
    delta = right - left
    overlap = cand["min"] <= base["max"] and base["min"] <= cand["max"]
    few = min(base.get("n", 0), cand.get("n", 0)) < MIN_TIMING_REPEATS
    if abs(delta) <= band:
        label = "unchanged"
    elif overlap or (timing and few):
        # The medians moved, but some repeats of each side agree.
        label = "inconclusive"
    else:
        # For released memory more is better; for everything else less is.
        better = delta > 0 if name.startswith("released") else delta < 0
        label = "improved" if better else "regressed"
    return {"label": label, "baseline": left, "candidate": right, "delta": delta, "band": band}


def _calibration(summary: Mapping[str, Any]) -> str:
    calibration = summary["experiments"].get("calibration")
    if not calibration:
        return "absent"
    derived = calibration["aggregate"]["derived"]
    loaded = (derived.get("loaded") or {}).get("median")
    released = (derived.get("released_by_unload") or {}).get("median")
    expected = 64 * 2**20
    if loaded is None or released is None:
        return "unavailable"
    ok = abs(loaded - expected) < expected * 0.1 and abs(released - expected) < expected * 0.1
    return "passed" if ok else "failed"


def write_comparison(result: Mapping[str, Any], destination: Path) -> Path:
    lines = [
        f"# Resources: `{result['baseline']}` → `{result['candidate']}`", "",
        f"- Comparable: **{'yes' if result['comparable'] else 'no'}**",
    ]
    lines += [f"  - {reason}" for reason in result["reasons"]]
    lines += [
        f"- Behaviour: **{result['behaviour']}**",
        f"- Candidate calibration: {result['calibration']}",
        f"- Decision: {result['decision']}", "",
    ]
    if not result["comparable"]:
        lines += ["Raw differences follow for inspection only; they are not a comparison.", ""]
    for label, experiment in result["experiments"].items():
        lines += [f"## `{label}`", "", "| quantity | baseline | candidate | delta | label |",
                  "|---|---|---|---|---|"]
        for name, row in experiment["derived"].items():
            lines.append(_row(name, row))
        for stage, values in experiment["stages"].items():
            for key, row in values.items():
                if row["label"] != "unavailable":
                    lines.append(_row(f"{stage} · {key}", row))
        lines.append("")
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return destination


def _row(name: str, row: Mapping[str, Any]) -> str:
    if row["label"] == "unavailable":
        return f"| {name} | n/a | n/a | n/a | unavailable |"
    timing = "ms" in name or "latency" in name or "seconds" in name
    if "growth" in name:
        return (
            f"| {name} | {row['baseline'] / 1024:.1f} KiB/op "
            f"| {row['candidate'] / 1024:.1f} KiB/op "
            f"| {row['delta'] / 1024:+.1f} KiB/op | {row['label']} |"
        )
    if timing:
        scale, unit = 1.0, "ms" if "ms" in name or "latency" in name else "s"
    else:
        scale, unit = float(2**20), "MiB"
    return (
        f"| {name} | {row['baseline'] / scale:.1f} {unit} | {row['candidate'] / scale:.1f} {unit} "
        f"| {row['delta'] / scale:+.1f} {unit} | {row['label']} |"
    )
