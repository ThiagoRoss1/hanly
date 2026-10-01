"""How a tour hover is judged. One rule, used live and when rebuilding a report.

The metric is deliberately narrow: **a hover is correct when the lookup bound to
that hover succeeded and the dictionary form it answered with (its leading
entry's headword, or the lemma it queried) equals the hand-set expected form.**
It says nothing about whether every definition shown is right, and it is a
score on the lab's controlled corpus, not general OCR or translation accuracy.

A verdict belongs to one of three groups. ``PASS`` and ``FAIL`` are scored;
``UNSCORED`` hovers were never read (or their reading was discarded) and are
reported separately, never folded into either.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

#: Bumped whenever a verdict could change for the same recorded outcome.
#: v3: a hover the app never finished (no presentation decision before the
#: driver's deadline) is ``timed_out``, whatever partial result it carried.
RULE = "strict-headword-v3"

PASS = frozenset({"correct", "refused"})
FAIL = frozenset(
    {
        "false_answer",
        "ambiguous_surface",
        "wrong_lemma",
        "not_found",
        "unresolved",
        "misread",
        "wrong_word",
        "no_text",
        "error",
        "timed_out",
        "no_result",
        "no_hover",
    }
)
#: Not read, or read and then discarded because ownership could not be shown.
UNSCORED = frozenset({"obscured", "obscured_during_capture", "unverifiable_region"})

#: Statuses that mean the lookup ran and deliberately produced no answer.
_DECLINED = frozenset({"EMPTY", "UNUSABLE", "NOT_FOUND"})


#: The text-free facts a verdict depends on. A tour persists these instead of
#: what was read, so a later rule can still re-score a run that kept no text.
FACT_KEYS = (
    "answer_matches_expected",
    "has_selection",
    "has_recognized_text",
    "surface_was_read",
    "selection_is_target",
    "answer_is_selection",
)


def derive_facts(record: Mapping[str, Any]) -> dict[str, bool]:
    """Compute the facts from in-memory text: the selected word, answer and reading."""

    status = record.get("status")
    selected = str(record.get("selected") or "")
    raw_headword = record.get("headword")
    headword = None if raw_headword is None else str(raw_headword)
    lemma = record.get("lemma")
    surface = str(record.get("surface") or "")
    expected = record.get("expected")
    expected_lemma = record.get("expected_lemma", expected)
    recognized = " ".join(str(text) for text in record.get("recognized") or ())
    succeeded = status == "SUCCESS"
    return {
        "answer_matches_expected": succeeded
        and (
            expected in (headword, lemma)
            or (expected_lemma is not None and lemma == expected_lemma)
        ),
        "has_selection": bool(selected),
        "has_recognized_text": bool(recognized.strip()),
        "surface_was_read": bool(surface) and surface in recognized,
        "selection_is_target": bool(selected)
        and _core(selected) in (_core(surface), _hangul_run(surface, record.get("cursor"))),
        "answer_is_selection": bool(selected)
        and headword is not None
        and _core(headword) == _core(selected),
    }


def classify(record: Mapping[str, Any]) -> str:
    """The verdict for one tour result record, by the first stage that went wrong.

    ``record`` is a ``tour_result`` from any schema since the first tour: a
    current one carries ``facts``; older ones carry the text they were derived
    from. Missing facts count against the hover, never for it.
    """

    unscored = record.get("unscored")
    if isinstance(unscored, str) and unscored in UNSCORED:
        return unscored
    if record.get("verdict") in UNSCORED:
        return str(record["verdict"])

    status = record.get("status")
    has_result = status is not None
    stored = record.get("facts")
    facts = stored if isinstance(stored, Mapping) else derive_facts(record)

    def fact(name: str) -> bool:
        return facts.get(name) is True

    if record.get("error"):
        return "error"
    if not has_result and not record.get("lookup_ids"):
        return "no_hover"
    if record.get("timed_out"):
        # Completion is the app's own popup decision for the bound lookup; a
        # pipeline result that never reached it is partial, not an answer.
        return "timed_out"
    if not has_result:
        return "no_result"
    if record.get("refuse"):
        if status in _DECLINED:
            return "refused"
        return "false_answer" if status == "SUCCESS" else "error"
    if fact("answer_matches_expected"):
        return "correct"
    if status not in _DECLINED and status != "SUCCESS":
        return "error"
    if not fact("has_selection"):
        if not fact("has_recognized_text"):
            return "no_text"
        # Text was read, but no word under the pointer was chosen from it.
        return "unresolved" if fact("surface_was_read") else "misread"
    if not fact("selection_is_target"):
        return "wrong_word" if fact("surface_was_read") else "misread"
    if status == "SUCCESS" and fact("answer_is_selection"):
        # The exact surface is itself a dictionary word, and Hanly has no
        # sentence context to prefer the reading the story intends (드릴).
        return "ambiguous_surface"
    if status == "SUCCESS":
        return "wrong_lemma"
    return "not_found"


def summarize(verdicts: Sequence[str]) -> dict[str, Any]:
    """Counts under the current rule; accuracy is over scored hovers only."""

    scored = [verdict for verdict in verdicts if verdict not in UNSCORED]
    passed = sum(verdict in PASS for verdict in scored)
    return {
        "rule": RULE,
        "total": len(verdicts),
        "scored": len(scored),
        "unscored": len(verdicts) - len(scored),
        "passed": passed,
        "accuracy": passed / len(scored) if scored else None,
    }


def _core(text: str) -> str:
    return str(text).strip().strip("\"'“”‘’.,!?()[]")


def _hangul_run(text: str, index: object) -> str:
    if not text:
        return ""
    cursor = index if isinstance(index, int) and 0 <= index < len(text) else len(text) // 2
    start, end = cursor, cursor + 1
    while start > 0 and "가" <= text[start - 1] <= "힣":
        start -= 1
    while end < len(text) and "가" <= text[end] <= "힣":
        end += 1
    return text[start:end]


__all__ = ["FACT_KEYS", "FAIL", "PASS", "RULE", "UNSCORED", "classify", "derive_facts", "summarize"]
