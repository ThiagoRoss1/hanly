"""Scoring rules, and the cases where there is nothing to score.

Every metric here is checked against a hand-calculable example, because a
scoring bug produces plausible numbers rather than an error.
"""

from __future__ import annotations

import unicodedata

import pytest

from benchmarks.dev.ocr_metrics import (
    MEASURED,
    NOT_APPLICABLE,
    Metric,
    Region,
    aggregate,
    character_error_rate,
    detection_scores,
    exact_match,
    false_empty,
    gate_false_negative_rate,
    hangul_syllable_error_rate,
    is_hangul,
    output_variance,
    score_case,
    target_region_recall,
    target_surface_correct,
)


def _region(text: str, left: float, top: float, right: float, bottom: float) -> Region:
    return Region(text, left, top, right, bottom)


# --- Character error rate ---------------------------------------------------


def test_one_substitution_in_eight_characters_is_one_eighth() -> None:
    """The real EasyOCR failure on the reading fixture: 을 read as 올."""

    metric = character_error_rate("책을 읽습니다.", "책올 읽습니다.")

    assert metric.status == MEASURED
    assert metric.value == pytest.approx(1 / 8)
    assert metric.detail is not None and metric.detail["edits"] == 1


@pytest.mark.parametrize(
    ("expected", "actual", "edits"),
    [
        ("한국어", "한국어", 0),
        ("한국어", "한국", 1),
        ("한국", "한국어", 1),
        ("한국어", "중국어", 1),
        ("한국어", "", 3),
        ("abc", "cba", 2),
    ],
)
def test_edit_distance_matches_hand_calculation(
    expected: str, actual: str, edits: int
) -> None:
    metric = character_error_rate(expected, actual)

    assert metric.detail is not None and metric.detail["edits"] == edits
    assert metric.value == pytest.approx(edits / len(expected))


def test_a_decomposed_syllable_is_not_counted_as_an_error() -> None:
    """Korean composes the same syllable several ways; NFC folds them."""

    composed = "책"
    decomposed = unicodedata.normalize("NFD", composed)

    assert composed != decomposed
    assert character_error_rate(composed, decomposed).value == 0.0
    assert exact_match(composed, decomposed).value is True


def test_an_absent_reference_is_not_applicable_rather_than_perfect() -> None:
    for metric in (
        exact_match(None, "무엇"),
        character_error_rate(None, "무엇"),
        hangul_syllable_error_rate(None, "무엇"),
        false_empty(None, []),
    ):
        assert metric.status == NOT_APPLICABLE
        assert metric.value is None


def test_an_empty_reference_cannot_be_divided_by() -> None:
    metric = character_error_rate("", "무엇")

    assert metric.status == NOT_APPLICABLE
    assert metric.detail is not None and "empty" in metric.detail["reason"]


# --- Hangul syllable error rate ---------------------------------------------


def test_the_hangul_rate_ignores_latin_digits_and_punctuation() -> None:
    """Latin noise around Korean must not dilute a Korean error."""

    full = character_error_rate("Hanly 버전 2.0", "Hanly 버젼 2.0")
    hangul = hangul_syllable_error_rate("Hanly 버전 2.0", "Hanly 버젼 2.0")

    assert hangul.value == pytest.approx(1 / 2)
    assert isinstance(full.value, float) and isinstance(hangul.value, float)
    assert full.value < hangul.value


def test_a_reference_with_no_hangul_is_not_applicable() -> None:
    metric = hangul_syllable_error_rate("Hanly 2.0", "Hanly 2.0")

    assert metric.status == NOT_APPLICABLE


def test_hangul_detection_covers_jamo_and_syllables() -> None:
    assert is_hangul("책") and is_hangul("ᄀ") and is_hangul("ㄱ")
    assert not is_hangul("a") and not is_hangul("2") and not is_hangul("。")


# --- False empty ------------------------------------------------------------


def test_reading_nothing_where_text_was_known_to_be_is_a_false_empty() -> None:
    assert false_empty("책", []).value is True
    assert false_empty("책", [object()]).value is False


# --- Detection --------------------------------------------------------------


def test_detection_matches_one_to_one_at_the_declared_threshold() -> None:
    expected = [_region("a", 0, 0, 10, 10), _region("b", 20, 0, 30, 10)]
    actual = [_region("a", 1, 1, 11, 11), _region("b", 21, 0, 31, 10)]

    precision, recall = detection_scores(expected, actual, iou_threshold=0.5)

    assert precision.value == 1.0
    assert recall.value == 1.0


def test_one_sprawling_detection_cannot_claim_two_expected_regions() -> None:
    expected = [_region("a", 0, 0, 10, 10), _region("b", 12, 0, 22, 10)]
    actual = [_region("ab", 0, 0, 22, 10)]

    precision, recall = detection_scores(expected, actual, iou_threshold=0.3)

    assert recall.value == pytest.approx(0.5)
    assert precision.value == 1.0


def test_the_iou_threshold_is_a_boundary_not_a_suggestion() -> None:
    expected = [_region("a", 0, 0, 10, 10)]
    # Half-overlapping boxes: intersection 50, union 150, IoU exactly 1/3.
    actual = [_region("a", 5, 0, 15, 10)]

    assert detection_scores(expected, actual, iou_threshold=0.33)[1].value == 1.0
    assert detection_scores(expected, actual, iou_threshold=0.34)[1].value == 0.0


def test_detecting_nothing_scores_zero_recall_rather_than_failing() -> None:
    precision, recall = detection_scores([_region("a", 0, 0, 10, 10)], [])

    assert recall.value == 0.0
    assert precision.value == 0.0
    assert precision.detail is not None and "nothing was detected" in precision.detail["note"]


def test_unannotated_regions_are_not_applicable() -> None:
    precision, recall = detection_scores([], [_region("a", 0, 0, 10, 10)])

    assert precision.status == recall.status == NOT_APPLICABLE


# --- The target -------------------------------------------------------------


def test_the_target_must_actually_be_inside_a_detected_region() -> None:
    regions = [_region("a", 0, 0, 10, 10), _region("b", 20, 0, 30, 10)]

    assert target_region_recall((5, 5), regions).value is True
    assert target_region_recall((15, 5), regions).value is False
    assert target_region_recall(None, regions).status == NOT_APPLICABLE


def test_a_boundary_pixel_counts_as_inside() -> None:
    assert target_region_recall((10, 10), [_region("a", 0, 0, 10, 10)]).value is True


def test_resolving_nothing_is_a_failure_not_an_absence() -> None:
    """The annotation exists, so an unresolved pointer is a wrong answer."""

    metric = target_surface_correct("읽습니다.", None)

    assert metric.status == MEASURED
    assert metric.value is False


def test_the_surface_comparison_is_normalized() -> None:
    assert target_surface_correct("책", unicodedata.normalize("NFD", "책")).value is True
    assert target_surface_correct("책", "상").value is False


# --- Variance ---------------------------------------------------------------


def test_repeating_an_identical_input_should_not_change_the_answer() -> None:
    assert output_variance(["책", "책", "책"]).value is False
    assert output_variance(["책", "책", "잭"]).value is True


def test_fewer_than_two_repeats_cannot_show_variance() -> None:
    assert output_variance([]).status == NOT_APPLICABLE
    assert output_variance(["책"]).status == NOT_APPLICABLE


# --- The gate ---------------------------------------------------------------


def test_the_gate_rate_counts_only_rois_known_to_hold_text() -> None:
    observations = [
        {"gate_passed": False, "has_expected_text": True},
        {"gate_passed": True, "has_expected_text": True},
        {"gate_passed": False, "has_expected_text": False},
    ]

    metric = gate_false_negative_rate(observations)

    assert metric.value == pytest.approx(0.5)
    assert metric.detail is not None and metric.detail["scored"] == 2


def test_no_gate_observations_is_not_applicable() -> None:
    assert gate_false_negative_rate([]).status == NOT_APPLICABLE


# --- Scoring a whole case ---------------------------------------------------


def test_a_correct_string_in_the_wrong_place_is_not_a_target_success() -> None:
    """Transcription and target selection are scored separately on purpose."""

    metrics = {
        metric.name: metric
        for metric in score_case(
            expected_text="책을 읽습니다.",
            expected_surface="읽습니다.",
            expected_target=(5.0, 5.0),
            expected_regions=(),
            actual_regions=(_region("책을 읽습니다.", 100, 100, 200, 130),),
            resolved_surface=None,
        )
    }

    assert metrics["exact_match"].value is True
    assert metrics["target_region_recall"].value is False
    assert metrics["target_surface_correct"].value is False


def test_regions_are_joined_in_the_order_the_provider_reported() -> None:
    metrics = {
        metric.name: metric
        for metric in score_case(
            expected_text="책을 읽습니다.",
            expected_surface=None,
            expected_target=None,
            expected_regions=(),
            actual_regions=(
                _region("책을", 0, 0, 40, 20),
                _region("읽습니다.", 45, 0, 140, 20),
            ),
        )
    }

    assert metrics["exact_match"].value is True


# --- Aggregation ------------------------------------------------------------


def test_unscoreable_cases_are_counted_and_excluded_from_the_mean() -> None:
    """A mostly unannotated corpus must not look like a perfect one."""

    summary = aggregate(
        [
            Metric("cer", MEASURED, 0.5),
            Metric("cer", MEASURED, 0.1),
            Metric("cer", NOT_APPLICABLE),
        ]
    )

    assert summary["cer"]["cases"] == 3
    assert summary["cer"]["measured"] == 2
    assert summary["cer"]["not_applicable"] == 1
    assert summary["cer"]["mean"] == pytest.approx(0.3)


def test_a_metric_nothing_could_score_has_no_mean_at_all() -> None:
    summary = aggregate([Metric("cer", NOT_APPLICABLE), Metric("cer", NOT_APPLICABLE)])

    assert summary["cer"]["mean"] is None
    assert summary["cer"]["measured"] == 0
