"""Whether two runs can be compared, and what the comparison says, from measured facts only.

Nothing here measures. It takes two runs' identities and the outcomes their
reports already scored, decides what a comparison may claim, and derives a few
fixed explanations beside the raw numbers: correctness, the failure set, the
process roles, and performance against one named heuristic policy. The raw
values, deltas and sample counts always travel with any explanation, and an
incompatible pair is labelled raw-only rather than explained.

Different commits are the point of a comparison, never a reason to refuse one.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .identity import NOT_APPLICABLE, UNKNOWN, RunIdentity

COMPARABLE = "comparable"
NOT_COMPARABLE = "not_comparable"
INSUFFICIENT = "insufficient_evidence"


@dataclass(frozen=True)
class Band:
    """How far a value may move before a comparison calls it lower or higher."""

    fraction: float
    floor: float
    unit: str

    def width(self, baseline: float) -> float:
        return max(abs(baseline) * self.fraction, self.floor)


@dataclass(frozen=True)
class PerformancePolicy:
    """Indicative bands, not calibrated against Hanly's variance.

    They are neither significance thresholds nor release gates. A value inside
    its band is reported as within it, not as unchanged; the raw numbers stay
    primary, and repeatability evidence may justify different bands later.
    """

    name: str
    popup_p50: Band
    sampled_rss: Band


POLICY = PerformancePolicy(
    name="indicative-bands-v1",
    popup_p50=Band(0.05, 5.0, "ms"),
    sampled_rss=Band(0.05, 32.0, "MiB"),
)


# -- compatibility ------------------------------------------------------------------------


def compatibility(before: RunIdentity, after: RunIdentity) -> dict[str, Any]:
    """What a comparison of ``after`` against ``before`` may claim.

    Correctness needs the same kind, platform, backend, options and rendered
    plan. Latency and memory additionally need both runs finished under one
    known measurement protocol on an equivalent host, which the platform name
    alone does not establish.
    """

    blocking: list[str] = []
    missing: list[str] = []
    warnings: list[str] = []

    def same(label: str, one: Any, other: Any) -> None:
        if UNKNOWN in (one, other):
            missing.append(f"{label} unknown ({one} / {other})")
        elif one != other:
            blocking.append(f"{label} differs ({one} / {other})")

    if before.kind not in {"tour", "stress"} or after.kind not in {"tour", "stress"}:
        blocking.append(
            f"only tours and stress campaigns are compared ({before.kind} / {after.kind})"
        )
    same("kind", before.kind, after.kind)
    same("platform", f"{before.system}-{before.machine}", f"{after.system}-{after.machine}")
    same("observed OCR backend", before.backend, after.backend)
    for key in sorted(set(before.options) | set(after.options)):
        same(f"option {key}", before.options.get(key), after.options.get(key))
    if UNKNOWN in (before.fingerprint, after.fingerprint):
        warnings.append(
            "rendered plan identity is not on record for both; occurrences are matched one by one"
        )
    elif before.fingerprint != after.fingerprint:
        blocking.append("rendered plan differs (faces, sizes, themes or targets)")
    for identity in (before, after):
        if identity.conflicts:
            missing.append(f"{identity.name}: {'; '.join(identity.conflicts)}")
        if identity.source_state != "clean":
            warnings.append(f"{identity.name} was recorded from a {identity.source_state} checkout")
        if not identity.complete:
            warnings.append(
                f"{identity.name} did not finish ({identity.completion}); "
                "only matched occurrences count"
            )
    if set(before.rules) != set(after.rules):
        warnings.append(
            f"recorded under {', '.join(before.rules) or 'no rule'} and "
            f"{', '.join(after.rules) or 'no rule'}; "
            "both are re-scored under the current rule"
        )

    status = NOT_COMPARABLE if blocking else INSUFFICIENT if missing else COMPARABLE
    performance = _performance_blockers(before, after)
    correctness = status == COMPARABLE
    return {
        "status": status,
        "reasons": blocking + missing,
        "warnings": warnings,
        "eligible": {
            "correctness": correctness,
            "latency": correctness and not performance,
            "memory": correctness and not performance,
        },
        "performance_reasons": performance,
    }


def _performance_blockers(before: RunIdentity, after: RunIdentity) -> list[str]:
    reasons = []
    for identity in (before, after):
        if not identity.complete:
            reasons.append(f"{identity.name} did not finish")
        if identity.measurement_protocol in {UNKNOWN, NOT_APPLICABLE}:
            reasons.append(f"{identity.name} records no measurement protocol")
        if not identity.host:
            reasons.append(f"{identity.name} records no host description")
    if before.measurement_protocol != after.measurement_protocol:
        reasons.append("measurement protocols differ")
    if before.host and after.host and before.host != after.host:
        reasons.append("hosts differ (OS release, CPU count or memory)")
    return sorted(set(reasons))


# -- occurrences ---------------------------------------------------------------------------


def tour_occurrence(row: Mapping[str, Any]) -> str:
    """One rendered occurrence: the target as painted in one face, size and theme.

    Word IDs follow sampling order, so a word is named by its surface; story
    targets keep their hand-set IDs. The variant keeps two renderings of one
    word apart, which matching by surface alone collapsed.
    """

    name = f"words:{row.get('surface')}" if row.get("source") == "words" else str(row.get("target"))
    return f"{name}@{_variant(row)}"


def stress_occurrence(row: Mapping[str, Any]) -> str:
    """Stress targets are unique per plan; the variant still has to match."""

    return f"{row.get('target')}@{_variant(row)}"


def _variant(row: Mapping[str, Any]) -> str:
    return f"{row.get('font')}/{row.get('font_px')}/{row.get('theme')}"


def occurrences(
    rows: Iterable[Mapping[str, Any]], key: Callable[[Mapping[str, Any]], str]
) -> dict[str, Mapping[str, Any]]:
    """Every row under its own key; a repeated key gets an ordinal, never a merge."""

    seen: Counter[str] = Counter()
    out: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        base = key(row)
        seen[base] += 1
        out[base if seen[base] == 1 else f"{base}#{seen[base]}"] = row
    return out


# -- explanations --------------------------------------------------------------------------


def compare_outcomes(
    before: Sequence[Mapping[str, Any]],
    after: Sequence[Mapping[str, Any]],
    *,
    key: Callable[[Mapping[str, Any]], str],
    passes: frozenset[str],
    unscored: frozenset[str],
    informational: frozenset[str] = frozenset(),
    eligible: bool,
) -> dict[str, Any]:
    """Match occurrences and explain correctness without changing any verdict."""

    old, new = occurrences(before, key), occurrences(after, key)
    matched = sorted(set(old) & set(new))
    counted: Counter[str] = Counter()
    changed, retained, introduced, resolved = [], [], [], []
    for name in matched:
        was, now = str(old[name].get("verdict")), str(new[name].get("verdict"))
        if was in informational or now in informational:
            counted["informational"] += 1
            continue
        if was in unscored or now in unscored:
            counted["unscored_in_either"] += 1
            continue
        counted["scored_in_both"] += 1
        if was != now:
            changed.append({"occurrence": name, "before": was, "after": now})
        if was not in passes and now not in passes:
            retained.append(name)
        elif now not in passes:
            introduced.append(name)
        elif was not in passes:
            resolved.append(name)
    return {
        "matched": len(matched),
        "only_before": len(set(old) - set(new)),
        "only_after": len(set(new) - set(old)),
        "counts": dict(counted),
        "changed": changed,
        "correctness": _correctness(eligible, counted["scored_in_both"], introduced, resolved),
        "failure_set": {
            "retained": retained,
            "introduced": introduced,
            "resolved": resolved,
        },
    }


def _correctness(eligible: bool, scored: int, introduced: list[str], resolved: list[str]) -> str:
    if not eligible or scored == 0:
        return "unavailable"
    if introduced and resolved:
        return "mixed"
    if introduced:
        return "regressed"
    if resolved:
        return "improved"
    return "unchanged"


def process_roles(before: Iterable[str] | None, after: Iterable[str] | None) -> dict[str, Any]:
    if before is None or after is None:
        return {"status": "unavailable"}
    old, new = set(before), set(after)
    if not old or not new:
        return {"status": "unavailable"}
    return {
        "status": "same" if old == new else "changed",
        "only_before": sorted(old - new),
        "only_after": sorted(new - old),
    }


def performance(
    name: str,
    before: float | None,
    after: float | None,
    band: Band,
    *,
    eligible: bool,
    samples: tuple[int | None, int | None] = (None, None),
) -> dict[str, Any]:
    """One measured value against its indicative band, with the raw numbers kept."""

    row: dict[str, Any] = {
        "measure": name,
        "before": before,
        "after": after,
        "unit": band.unit,
        "samples": list(samples),
        "policy": POLICY.name,
    }
    if before is None or after is None:
        return {**row, "verdict": "unavailable"}
    delta = after - before
    width = band.width(before)
    row.update(delta=round(delta, 3), band=round(width, 3))
    if not eligible:
        return {**row, "verdict": "unavailable"}
    if abs(delta) <= width:
        verdict = "within indicative band"
    else:
        verdict = "lower" if delta < 0 else "higher"
    return {**row, "verdict": verdict}


def headline(comparison: Mapping[str, Any]) -> list[str]:
    """The fixed explanation lines a compact report shows first."""

    compat = comparison["compatibility"]
    if compat["status"] != COMPARABLE:
        return [f"raw comparison only: {compat['status']} ({'; '.join(compat['reasons'])})"]
    outcome = comparison["outcomes"]
    failures = outcome["failure_set"]
    lines = [
        f"correctness: {outcome['correctness']}",
        f"failure set: {len(failures['retained'])} retained / {len(failures['introduced'])} "
        f"introduced / {len(failures['resolved'])} resolved",
        f"process roles: {comparison['process_roles']['status']}",
    ]
    for row in comparison["performance"]:
        if row["verdict"] == "unavailable":
            lines.append(f"{row['measure']}: unavailable")
        else:
            lines.append(
                f"{row['measure']}: {row['verdict']} ({row['before']} -> {row['after']} "
                f"{row['unit']}, band ±{row['band']} under {row['policy']})"
            )
    return lines


__all__ = [
    "COMPARABLE",
    "INSUFFICIENT",
    "NOT_COMPARABLE",
    "POLICY",
    "Band",
    "PerformancePolicy",
    "compare_outcomes",
    "compatibility",
    "headline",
    "occurrences",
    "performance",
    "process_roles",
    "stress_occurrence",
    "tour_occurrence",
]
