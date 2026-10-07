"""How a stress hover is judged, and which stage a failure points at.

Positives keep the tour's rule (``strict-headword-v3``): the bound lookup
finished and answered with the expected dictionary form. A negative passes only
when no answer was presented for it; whether the app read nothing, declined, or
never fired is all ``quiet``. A popup from another hover appearing while this
one is measured is a presentation failure, whatever this hover's own outcome.

``leave_early`` is judged on presentation alone: an answer that arrives after
the pointer left must not be shown. ``changing`` and ``covered`` are evidence,
not scored.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any

from .scoring import UNSCORED, classify
from .stress import INFORMATIONAL, NEGATIVE

RULE = "stress-v1"

PASS = frozenset({"correct", "refused", "quiet", "withheld"})
#: An answer was presented where none should have been.
FALSE_PRESENTATION = frozenset({"false_answer", "stale_popup"})
INFORMATION = frozenset({"answered_before_leaving", "observed", "not_submitted"})


def stress_verdict(record: Mapping[str, Any]) -> str:
    """The verdict for one ``stress_result`` record under ``stress-v1``."""

    unscored = record.get("unscored")
    if isinstance(unscored, str) and unscored in UNSCORED:
        return unscored
    family = str(record.get("family") or "word")
    if family in INFORMATIONAL:
        return "observed"
    if record.get("foreign_popups"):
        return "stale_popup"
    if family == "leave_early":
        return _late(record)
    if family in NEGATIVE:
        return _negative(record)
    return classify(record)


def _negative(record: Mapping[str, Any]) -> str:
    if record.get("error"):
        return "error"
    if record.get("popup") == "SUCCESS":
        return "false_answer"
    if record.get("timed_out") and record.get("lookup_ids"):
        # Still working when the driver gave up: an answer could yet appear.
        return "timed_out"
    return "quiet"


def _late(record: Mapping[str, Any]) -> str:
    observed = record.get("observed") or {}
    if not observed.get("submitted"):
        return "not_submitted"
    if observed.get("answered_before_leaving"):
        return "answered_before_leaving"
    return "late_popup" if record.get("late_popups") else "withheld"


def failing_stage(record: Mapping[str, Any]) -> str | None:
    """The first stage a failed or false outcome points at, from text-free facts."""

    verdict = record.get("verdict") or stress_verdict(record)
    if verdict in PASS or verdict in INFORMATION or verdict in UNSCORED:
        return None
    facts = record.get("facts") or {}
    direct = record.get("direct_text")
    if verdict in {"stale_popup", "late_popup"}:
        return "currency_presentation"
    if verdict in {"no_hover", "no_result", "timed_out"}:
        return "hover_or_scheduling" if verdict == "no_hover" else "pipeline_unfinished"
    if verdict == "error":
        return "processing_error"
    if record.get("acquisition") == "accessibility" or direct == "direct":
        return "uia"
    if verdict == "false_answer":
        if record.get("gate") == "rejected":
            return "presence_gate"
        return "ocr_false_text" if facts.get("has_recognized_text") else "resolver"
    if verdict == "no_text":
        return "presence_gate" if record.get("gate") == "rejected" else "ocr_no_text"
    if verdict == "misread":
        return "ocr_misread"
    if verdict in {"unresolved", "wrong_word"}:
        return "resolver"
    if verdict in {"wrong_lemma", "ambiguous_surface", "not_found"}:
        return "morphology_dictionary"
    return "unknown"


def summarize(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Counts per family, verdict and stage; accuracy over scored hovers only."""

    rows = list(records)
    families: dict[str, Counter[str]] = {}
    stages: Counter[str] = Counter()
    for row in rows:
        verdict = str(row.get("verdict"))
        families.setdefault(str(row.get("family")), Counter())[verdict] += 1
        if row.get("stage"):
            stages[str(row["stage"])] += 1
    scored = [
        row for row in rows
        if row.get("verdict") not in UNSCORED and row.get("verdict") not in INFORMATION
        and row.get("verdict") != "observed"
    ]
    passed = sum(1 for row in scored if row.get("verdict") in PASS)
    positives = [row for row in scored if str(row.get("family")) not in NEGATIVE]
    negatives = [row for row in scored if str(row.get("family")) in NEGATIVE]
    return {
        "rule": RULE,
        "executed": len(rows),
        "scored": len(scored),
        "unscored": len(rows) - len(scored),
        "passed": passed,
        "accuracy": passed / len(scored) if scored else None,
        # Only a presented answer is a false positive; a negative that timed out
        # or errored failed differently and is counted on its own.
        "false_positives": sum(
            1 for row in negatives if row.get("verdict") in FALSE_PRESENTATION
        ),
        "negatives_failed_otherwise": sum(
            1
            for row in negatives
            if row.get("verdict") not in PASS and row.get("verdict") not in FALSE_PRESENTATION
        ),
        "negatives_scored": len(negatives),
        "missing_answers": sum(1 for row in positives if row.get("verdict") not in PASS),
        "positives_scored": len(positives),
        "families": {name: dict(counts) for name, counts in sorted(families.items())},
        "stages": dict(stages.most_common()),
    }


__all__ = [
    "FALSE_PRESENTATION",
    "INFORMATION",
    "PASS",
    "RULE",
    "failing_stage",
    "stress_verdict",
    "summarize",
]
