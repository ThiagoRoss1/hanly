"""Stage facts for controlled images: what was observed at each stage, and nothing more.

Each fact is ``observed_true``, ``observed_false`` or ``unavailable``. A fact is
available only when the case states the truth it needs and the mode actually
produced the evidence: a detector response exists only where a detector ran on
its own (EasyOCR's ``detection-only``), never from normalized results, and
presentation exists only on the desktop. The first stage observed to go wrong
is named; that is where a failure became visible, not a proven root cause.

Stability is kept apart from correctness. A case answered the same wrong way
every time is stable and wrong, never reliably correct.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .corpus import CorpusCase
from .ocr_metrics import is_hangul, normalize

TRUE = "observed_true"
FALSE = "observed_false"
UNAVAILABLE = "unavailable"

#: Modes whose regions are the detector's own. ``recognition-only`` returns
#: normalized results, which can drop detector boxes, so it is not one of them.
DETECTOR_MODES = frozenset({"detection-only"})
FACTS = (
    "target_surface_correct",
    "detector_response_on_empty",
    "false_hangul",
    "false_korean_selection",
    "presentation",
)


def ocr_facts(
    case: CorpusCase,
    *,
    mode: str,
    texts: Sequence[str],
    region_count: int,
    transcribes: bool,
    resolved: str | None,
    resolved_ran: bool,
    error: bool,
) -> tuple[dict[str, str], str | None]:
    """The facts one OCR pass establishes for one case, and the first bad stage."""

    truth = case.truth
    facts = dict.fromkeys(FACTS, UNAVAILABLE)
    if truth is None or error:
        return facts, "processing_error" if error else None

    joined = " ".join(texts)
    has_hangul = any(is_hangul(character) for character in joined)
    if truth.target == "surface" and transcribes and resolved_ran and case.expected_surface:
        correct = resolved is not None and normalize(resolved) == normalize(case.expected_surface)
        facts["target_surface_correct"] = TRUE if correct else FALSE
    if mode in DETECTOR_MODES and not truth.text_present:
        facts["detector_response_on_empty"] = TRUE if region_count else FALSE
    if transcribes and not truth.korean_present:
        facts["false_hangul"] = TRUE if has_hangul else FALSE
    if truth.target == "no_korean" and transcribes and resolved_ran:
        selected = resolved or ""
        facts["false_korean_selection"] = (
            TRUE if any(is_hangul(character) for character in selected) else FALSE
        )
    return facts, _first_bad_stage(case, facts, joined, has_hangul, region_count)


def _first_bad_stage(
    case: CorpusCase,
    facts: Mapping[str, str],
    joined: str,
    has_hangul: bool,
    region_count: int,
) -> str | None:
    if facts["detector_response_on_empty"] == TRUE:
        return "detector_region_on_empty"
    if facts["false_hangul"] == TRUE:
        return "ocr_false_hangul"
    if facts["false_korean_selection"] == TRUE:
        return "target_selection"
    if facts["target_surface_correct"] == FALSE:
        if not region_count:
            return "ocr_no_text"
        if not has_hangul:
            return "ocr_no_hangul"
        surface = normalize(case.expected_surface or "")
        return "target_selection" if surface and surface in normalize(joined) else "ocr_misread"
    return None


def evaluable(facts: Mapping[str, str]) -> bool:
    return any(value != UNAVAILABLE for key, value in facts.items() if key != "presentation")


def fact_counts(rows: Iterable[Mapping[str, str]]) -> dict[str, dict[str, int]]:
    counts: dict[str, Counter[str]] = {name: Counter() for name in FACTS}
    for facts in rows:
        for name in FACTS:
            counts[name][facts.get(name, UNAVAILABLE)] += 1
    return {name: dict(counter) for name, counter in counts.items()}


def stability(observations: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """How one case behaved over its repetitions, apart from whether it was right.

    Each observation carries ``output`` (what was produced), ``ok`` (True,
    False or None when it could not be judged) and ``error``.
    """

    errors = sum(1 for item in observations if item.get("error"))
    judged = [
        item["ok"] for item in observations if not item.get("error") and item["ok"] is not None
    ]
    outputs = Counter(str(item.get("output")) for item in observations if not item.get("error"))
    modal = outputs.most_common(1)[0][1] if outputs else 0
    completed = len(observations) - errors
    if not observations or not judged:
        classification = "unavailable"
    elif errors:
        classification = "incomplete"
    elif all(judged):
        classification = "stable_correct" if len(outputs) == 1 else "correct_with_varying_output"
    elif not any(judged):
        classification = "stable_wrong" if len(outputs) == 1 else "wrong_with_varying_output"
    else:
        classification = "variable"
    return {
        "repetitions": len(observations),
        "completed": completed,
        "errors": errors,
        "judged": len(judged),
        "correct": sum(1 for ok in judged if ok),
        "distinct_outputs": len(outputs),
        "modal_share": round(modal / completed, 3) if completed else None,
        "classification": classification,
    }


__all__ = [
    "DETECTOR_MODES",
    "FACTS",
    "FALSE",
    "TRUE",
    "UNAVAILABLE",
    "evaluable",
    "fact_counts",
    "ocr_facts",
    "stability",
]
