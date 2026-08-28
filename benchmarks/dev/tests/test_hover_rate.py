"""Tests for deterministic hover invocation-rate measurements."""

from hanly import Point

from benchmarks.dev.hover_rate import hover_invocation_matrix, simulate_ocr_invocations


def test_movement_inside_dwell_collapses_to_one_ocr_invocation() -> None:
    result = simulate_ocr_invocations(
        ((0, Point(1, 1)), (50, Point(2, 1)), (100, Point(3, 1))),
        duration_ms=300,
        dwell_ms=150,
    )

    assert result["events"] == 3
    assert result["ocr_invocations"] == 1


def test_required_invocation_matrix_exposes_current_duplicate_behavior() -> None:
    matrix = hover_invocation_matrix(dwell_ms=150)

    assert matrix["idle"]["ocr_invocations"] == 0
    assert matrix["small_mouse_jitter"]["ocr_invocations"] == 1
    assert matrix["movement_across_text"]["ocr_invocations"] == 1
    assert matrix["repeated_hover_same_word"]["ocr_invocations"] == 5
    assert matrix["movement_across_non_text"]["ocr_invocations"] == 5
