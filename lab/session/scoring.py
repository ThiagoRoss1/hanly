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


def classify(record: Mapping[str, Any]) -> str:
    """The verdict for one tour result record, by the first stage that went wrong.

    ``record`` is a ``tour_result`` as written by the driver (any schema since
    the first tour). Missing fields count against the hover, never for it.
    """

    unscored = record.get("unscored")
    if isinstance(unscored, str) and unscored in UNSCORED:
        return unscored
    if record.get("verdict") in UNSCORED:
        return str(record["verdict"])

    status = record.get("status")
    selected = record.get("selected")
    headword = record.get("headword")
    lemma = record.get("lemma")
    surface = str(record.get("surface") or "")
    expected = record.get("expected")
    expected_lemma = record.get("expected_lemma", expected)
    recognized = " ".join(str(text) for text in record.get("recognized") or ())
    has_result = status is not None

    if record.get("error"):
        return "error"
    if not has_result and not record.get("lookup_ids"):
        return "no_hover"
    if record.get("timed_out"):
        # Completion is the app's own popup decision for the bound lookup; a
        # pipeline result that never reached it is partial, not an answer.
        return "timed_out"
    if not has_result:
        # A timeout or a missing answer is never a refusal or a pass.
        return "no_result" if record.get("lookup_ids") else "no_hover"
    if record.get("refuse"):
        if status in _DECLINED:
            return "refused"
        return "false_answer" if status == "SUCCESS" else "error"
    if status == "SUCCESS" and expected in (headword, lemma):
        return "correct"
    if status == "SUCCESS" and expected_lemma is not None and lemma == expected_lemma:
        return "correct"
    if status not in _DECLINED and status != "SUCCESS":
        return "error"
    if not selected:
        if not recognized.strip():
            return "no_text"
        # Text was read, but no word under the pointer was chosen from it.
        return "unresolved" if surface and surface in recognized else "misread"
    if _core(selected) not in (_core(surface), _hangul_run(surface, record.get("cursor"))):
        return "misread" if surface not in recognized else "wrong_word"
    if status == "SUCCESS" and headword is not None and _core(headword) == _core(selected):
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


__all__ = ["FAIL", "PASS", "RULE", "UNSCORED", "classify", "summarize"]
