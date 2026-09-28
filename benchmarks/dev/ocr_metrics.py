"""Score OCR output, and say plainly when there is nothing to score against.

Two rules run through everything here.

**A missing ground truth is not a zero.** An unannotated case would otherwise
be indistinguishable from a case the recognizer got completely wrong, and the
corpus is mostly unannotated by design. Every metric returns
``not_applicable`` instead.

**Reading the right word matters separately from reading the right string.**
A recognizer that transcribes a line perfectly but whose geometry puts it
somewhere else has not helped: the pointer still selects the wrong word. Region
order and geometry are therefore kept, and a correct string in the wrong place
never becomes a target-word success.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

#: The Unicode normal forms a comparison may fold to.
NormalForm = Literal["NFC", "NFD", "NFKC", "NFKD"]

#: How a string is folded before a character-level comparison. Korean composes
#: the same syllable several ways, so an unnormalized comparison measures the
#: encoding rather than the recognition.
DEFAULT_NORMALIZATION: NormalForm = "NFC"

MEASURED = "measured"
NOT_APPLICABLE = "not_applicable"

_HANGUL_RANGES = (
    ("\u1100", "\u11ff"),
    ("\u3130", "\u318f"),
    ("\ua960", "\ua97f"),
    ("\uac00", "\ud7a3"),
    ("\ud7b0", "\ud7ff"),
)


@dataclass(frozen=True)
class Metric:
    """One scored value, or an explicit statement that it cannot be scored."""

    name: str
    status: str
    value: float | bool | None = None
    detail: dict[str, Any] | None = None

    @property
    def measured(self) -> bool:
        return self.status == MEASURED

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "value": self.value,
            "detail": self.detail or {},
        }


@dataclass(frozen=True)
class Region:
    """One text region with axis-aligned bounds, from either side of a score."""

    text: str
    left: float
    top: float
    right: float
    bottom: float

    @property
    def area(self) -> float:
        return max(0.0, self.right - self.left) * max(0.0, self.bottom - self.top)

    def contains(self, x: float, y: float) -> bool:
        return self.left <= x <= self.right and self.top <= y <= self.bottom


def normalize(text: str, form: NormalForm = DEFAULT_NORMALIZATION) -> str:
    return unicodedata.normalize(form, text)


def is_hangul(character: str) -> bool:
    return any(low <= character <= high for low, high in _HANGUL_RANGES)


def exact_match(
    expected: str | None, actual: str, *, form: NormalForm = DEFAULT_NORMALIZATION
) -> Metric:
    """Whether the complete recognized string is exactly the expected one."""

    if expected is None:
        return Metric("exact_match", NOT_APPLICABLE, detail={"reason": "no expected text"})
    return Metric(
        "exact_match",
        MEASURED,
        normalize(expected, form) == normalize(actual, form),
        {"normalization": form},
    )


def character_error_rate(
    expected: str | None, actual: str, *, form: NormalForm = DEFAULT_NORMALIZATION
) -> Metric:
    """Levenshtein distance over normalized characters, per expected character."""

    if expected is None:
        return Metric(
            "character_error_rate", NOT_APPLICABLE, detail={"reason": "no expected text"}
        )
    reference = normalize(expected, form)
    hypothesis = normalize(actual, form)
    if not reference:
        return Metric(
            "character_error_rate",
            NOT_APPLICABLE,
            detail={"reason": "expected text is empty", "normalization": form},
        )
    distance = _edit_distance(reference, hypothesis)
    return Metric(
        "character_error_rate",
        MEASURED,
        distance / len(reference),
        {
            "normalization": form,
            "edits": distance,
            "reference_length": len(reference),
            "reference": reference,
            "hypothesis": hypothesis,
        },
    )


def hangul_syllable_error_rate(
    expected: str | None, actual: str, *, form: NormalForm = DEFAULT_NORMALIZATION
) -> Metric:
    """Character error rate over the Hangul syllables alone.

    Latin, digits, and punctuation ride along in real Korean UI text and would
    otherwise dilute exactly the errors this project cares about.
    """

    if expected is None:
        return Metric(
            "hangul_syllable_error_rate",
            NOT_APPLICABLE,
            detail={"reason": "no expected text"},
        )
    reference = "".join(c for c in normalize(expected, form) if is_hangul(c))
    hypothesis = "".join(c for c in normalize(actual, form) if is_hangul(c))
    if not reference:
        return Metric(
            "hangul_syllable_error_rate",
            NOT_APPLICABLE,
            detail={"reason": "expected text carries no Hangul", "normalization": form},
        )
    distance = _edit_distance(reference, hypothesis)
    return Metric(
        "hangul_syllable_error_rate",
        MEASURED,
        distance / len(reference),
        {"normalization": form, "edits": distance, "reference_length": len(reference)},
    )


def false_empty(expected: str | None, regions: Sequence[Any]) -> Metric:
    """Whether the recognizer returned nothing where text was known to be."""

    if expected is None or not expected.strip():
        return Metric("false_empty", NOT_APPLICABLE, detail={"reason": "no expected text"})
    return Metric("false_empty", MEASURED, len(regions) == 0)


def detection_scores(
    expected: Sequence[Region], actual: Sequence[Region], *, iou_threshold: float = 0.5
) -> tuple[Metric, Metric]:
    """Precision and recall over region geometry at a declared IoU threshold.

    Matching is greedy over descending overlap and one-to-one, so a single
    sprawling detection cannot claim several expected regions at once.
    """

    if not expected:
        reason = {"reason": "no annotated regions"}
        return (
            Metric("detection_precision", NOT_APPLICABLE, detail=reason),
            Metric("detection_recall", NOT_APPLICABLE, detail=reason),
        )

    pairs = sorted(
        (
            (_iou(one, other), expected_index, actual_index)
            for expected_index, one in enumerate(expected)
            for actual_index, other in enumerate(actual)
        ),
        key=lambda pair: (-pair[0], pair[1], pair[2]),
    )
    matched_expected: set[int] = set()
    matched_actual: set[int] = set()
    for overlap, expected_index, actual_index in pairs:
        if overlap < iou_threshold:
            break
        if expected_index in matched_expected or actual_index in matched_actual:
            continue
        matched_expected.add(expected_index)
        matched_actual.add(actual_index)

    detail = {
        "iou_threshold": iou_threshold,
        "expected": len(expected),
        "actual": len(actual),
        "matched": len(matched_expected),
    }
    precision = (
        Metric("detection_precision", MEASURED, len(matched_actual) / len(actual), detail)
        if actual
        else Metric(
            "detection_precision",
            MEASURED,
            0.0,
            {**detail, "note": "nothing was detected"},
        )
    )
    recall = Metric(
        "detection_recall", MEASURED, len(matched_expected) / len(expected), detail
    )
    return precision, recall


def target_region_recall(
    target: tuple[float, float] | None, actual: Sequence[Region]
) -> Metric:
    """Whether any detected region actually contains the annotated pointer."""

    if target is None:
        return Metric(
            "target_region_recall", NOT_APPLICABLE, detail={"reason": "no annotated target"}
        )
    x, y = target
    containing = [index for index, region in enumerate(actual) if region.contains(x, y)]
    return Metric(
        "target_region_recall",
        MEASURED,
        bool(containing),
        {"containing_indices": containing},
    )


def target_surface_correct(
    expected_surface: str | None,
    resolved_surface: str | None,
    *,
    form: NormalForm = DEFAULT_NORMALIZATION,
) -> Metric:
    """Whether the word under the pointer is the word that was expected."""

    if expected_surface is None:
        return Metric(
            "target_surface_correct",
            NOT_APPLICABLE,
            detail={"reason": "no annotated surface"},
        )
    if resolved_surface is None:
        return Metric(
            "target_surface_correct", MEASURED, False, {"reason": "nothing resolved"}
        )
    return Metric(
        "target_surface_correct",
        MEASURED,
        normalize(expected_surface, form) == normalize(resolved_surface, form),
        {"normalization": form, "resolved": resolved_surface},
    )


def output_variance(outputs: Sequence[str], *, form: NormalForm = DEFAULT_NORMALIZATION) -> Metric:
    """How often repeating an identical input changed the answer."""

    if len(outputs) < 2:
        return Metric(
            "repeated_input_variance",
            NOT_APPLICABLE,
            detail={"reason": "fewer than two repeats"},
        )
    distinct = {normalize(output, form) for output in outputs}
    return Metric(
        "repeated_input_variance",
        MEASURED,
        len(distinct) > 1,
        {"repeats": len(outputs), "distinct_outputs": len(distinct)},
    )


def gate_false_negative_rate(observations: Sequence[dict[str, Any]]) -> Metric:
    """How often the text-presence gate refused an ROI known to hold text.

    A gate false negative makes the popup silently stop working, so it is the
    gate error worth counting; a gate that lets a photograph through only costs
    an OCR call.
    """

    scored = [
        observation
        for observation in observations
        if isinstance(observation.get("gate_passed"), bool)
        and isinstance(observation.get("has_expected_text"), bool)
        and observation["has_expected_text"]
    ]
    if not scored:
        return Metric(
            "gate_false_negative_rate",
            NOT_APPLICABLE,
            detail={"reason": "no gate observations with known text"},
        )
    refused = sum(1 for observation in scored if not observation["gate_passed"])
    return Metric(
        "gate_false_negative_rate",
        MEASURED,
        refused / len(scored),
        {"refused": refused, "scored": len(scored)},
    )


def score_case(
    *,
    expected_text: str | None,
    expected_surface: str | None,
    expected_target: tuple[float, float] | None,
    expected_regions: Sequence[Region],
    actual_regions: Sequence[Region],
    resolved_surface: str | None = None,
    repeats: Sequence[str] = (),
    iou_threshold: float = 0.5,
    form: NormalForm = DEFAULT_NORMALIZATION,
) -> tuple[Metric, ...]:
    """Score one case, preserving provider order when joining its regions.

    The recognized string is rebuilt in the order the provider reported, which
    is what keeps a correctly transcribed but misplaced line from scoring as a
    success.
    """

    actual_text = " ".join(region.text for region in actual_regions)
    precision, recall = detection_scores(
        expected_regions, actual_regions, iou_threshold=iou_threshold
    )
    return (
        exact_match(expected_text, actual_text, form=form),
        character_error_rate(expected_text, actual_text, form=form),
        hangul_syllable_error_rate(expected_text, actual_text, form=form),
        false_empty(expected_text, actual_regions),
        precision,
        recall,
        target_region_recall(expected_target, actual_regions),
        target_surface_correct(expected_surface, resolved_surface, form=form),
        output_variance(repeats, form=form),
    )


def aggregate(metrics: Sequence[Metric]) -> dict[str, Any]:
    """Aggregate like-named metrics, counting what could not be scored.

    ``not_applicable`` cases are counted and excluded from the mean rather than
    folded in as zeroes, so a mostly unannotated corpus cannot look like a
    perfectly scoring one.
    """

    grouped: dict[str, list[Metric]] = {}
    for metric in metrics:
        grouped.setdefault(metric.name, []).append(metric)

    summary: dict[str, Any] = {}
    for name, entries in sorted(grouped.items()):
        measured = [entry for entry in entries if entry.measured and entry.value is not None]
        values = [float(entry.value) for entry in measured if entry.value is not None]
        summary[name] = {
            "evidence_class": "derived",
            "cases": len(entries),
            "measured": len(measured),
            "not_applicable": len(entries) - len(measured),
            "mean": sum(values) / len(values) if values else None,
        }
    return summary


def _iou(one: Region, other: Region) -> float:
    left = max(one.left, other.left)
    top = max(one.top, other.top)
    right = min(one.right, other.right)
    bottom = min(one.bottom, other.bottom)
    if left >= right or top >= bottom:
        return 0.0
    intersection = (right - left) * (bottom - top)
    union = one.area + other.area - intersection
    return intersection / union if union > 0 else 0.0


def _edit_distance(reference: str, hypothesis: str) -> int:
    """Levenshtein distance, kept to one row of working memory."""

    if reference == hypothesis:
        return 0
    if not hypothesis:
        return len(reference)

    previous = list(range(len(hypothesis) + 1))
    for row, reference_character in enumerate(reference, start=1):
        current = [row]
        for column, hypothesis_character in enumerate(hypothesis, start=1):
            substitution = previous[column - 1] + (
                reference_character != hypothesis_character
            )
            current.append(min(previous[column] + 1, current[column - 1] + 1, substitution))
        previous = current
    return previous[-1]


__all__ = [
    "DEFAULT_NORMALIZATION",
    "NormalForm",
    "MEASURED",
    "NOT_APPLICABLE",
    "Metric",
    "Region",
    "aggregate",
    "character_error_rate",
    "detection_scores",
    "exact_match",
    "false_empty",
    "gate_false_negative_rate",
    "hangul_syllable_error_rate",
    "is_hangul",
    "normalize",
    "output_variance",
    "score_case",
    "target_region_recall",
    "target_surface_correct",
]
