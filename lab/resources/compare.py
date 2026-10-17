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

#: How far recognition may move and still count as the same reading: corners
#: in ROI pixels, confidence absolute. Text and region order have no tolerance.
QUAD_TOLERANCE = 1.0
CONFIDENCE_TOLERANCE = 0.02

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
    # The OCR variant may differ: that difference is what a comparison measures.
    plan_keys = (
        "ocr_backend", "lookups", "idle_seconds", "inputs", "warmup_runs", "sequence",
        "components",
    )
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
    for name, summary in (("baseline", base), ("candidate", cand)):
        calibration = _calibration(summary)
        if calibration != "passed":
            reasons.append(f"{name} calibration {calibration}")
        for label, experiment in summary["experiments"].items():
            for run in experiment.get("repeats", []):
                if run.get("error") or run.get("returncode") != 0:
                    reasons.append(f"{name} {label} contains a failed or unfinished repeat")
                    break
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
        "ocr": compare_ocr(base.get("ocr"), cand.get("ocr")),
        "variants": [base["plan"].get("ocr_variant", "product"),
                     cand["plan"].get("ocr_variant", "product")],
        "experiments": experiments,
        "calibration": _calibration(cand),
        "baseline_calibration": _calibration(base),
        "decision": "not made here: accepting a change needs reproducible evidence, "
                    "documented trade-offs and regression coverage",
    }


def compare_ocr(
    base: Mapping[str, Any] | None, cand: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Compare two recognizers' readings of the same inputs, input by input.

    ``identical`` needs every digest equal; ``within_tolerance`` allows corner
    and confidence movement inside the stated tolerances; anything else is
    ``changed`` and names the inputs and what moved. Unstable readings within
    either run make the result ``unstable`` rather than hiding the noise.
    """

    if not base or not cand:
        return {"label": "unavailable"}
    if not (base.get("stable_within_runs") and cand.get("stable_within_runs")
            and base.get("stable_across_repeats") and cand.get("stable_across_repeats")):
        return {"label": "unstable", "baseline_unstable": base.get("unstable_inputs"),
                "candidate_unstable": cand.get("unstable_inputs")}
    changed: dict[str, list[str]] = {}
    worst_quad = 0.0
    worst_confidence = 0.0
    left, right = base["records"], cand["records"]
    for index in sorted(set(left) | set(right), key=int):
        one, other = left.get(index), right.get(index)
        if one is None or other is None:
            changed[index] = ["missing"]
            continue
        if one["digest"] == other["digest"]:
            continue
        reasons: list[str] = []
        if len(one["regions"]) != len(other["regions"]):
            reasons.append("region count")
        for a, b in zip(one["regions"], other["regions"]):
            if a["text"] != b["text"]:
                reasons.append("text or order")
            quad = max(abs(x - y) for x, y in zip(a["quad"], b["quad"]))
            confidence = abs(a["confidence"] - b["confidence"])
            worst_quad = max(worst_quad, quad)
            worst_confidence = max(worst_confidence, confidence)
            if quad > QUAD_TOLERANCE:
                reasons.append("geometry")
            if confidence > CONFIDENCE_TOLERANCE:
                reasons.append("confidence")
        if reasons:
            changed[index] = sorted(set(reasons))
    identical = all(
        left.get(index, {}).get("digest") == right.get(index, {}).get("digest")
        for index in set(left) | set(right)
    )
    return {
        "label": "identical" if identical else "changed" if changed else "within_tolerance",
        "inputs": len(set(left) | set(right)),
        "changed": changed,
        "worst_quad_px": round(worst_quad, 3),
        "worst_confidence": round(worst_confidence, 4),
        "tolerances": {"quad_px": QUAD_TOLERANCE, "confidence": CONFIDENCE_TOLERANCE},
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
        f"- Recognizer: `{result['variants'][0]}` → `{result['variants'][1]}`; readings "
        f"**{result['ocr']['label']}**"
        + (f" (worst corner {result['ocr']['worst_quad_px']} px, worst confidence "
           f"{result['ocr']['worst_confidence']}; changed inputs: "
           f"{sorted(result['ocr']['changed']) or 'none'})"
           if "worst_quad_px" in result["ocr"] else ""),
        f"- Baseline calibration: {result['baseline_calibration']}",
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
