"""The staged EasyOCR runner, driven through a reader double.

The runner reproduces ``Reader.readtext``'s body, so the two things worth
pinning are that it fails loudly when those internals move and that its retained
crops really are the images its reported text came from.

``easyocr.utils`` pulls in Torch and OpenCV, so every test that needs the real
cropping helpers skips rather than importing them on a machine without the OCR
runtime.
"""

from __future__ import annotations

from typing import Any

import pytest
from hanly import PixelFormat, ROIImage

from benchmarks.dev.easyocr_stages import (
    COMPARISON_REPLAY,
    PINNED_EASYOCR_VERSION,
    RECOGNIZER_HEIGHT,
    STAGED_DIAGNOSTIC,
    StagedEasyOCRError,
    compare_to_live,
    run_staged_easyocr,
    verify_easyocr_api,
)


def _roi(width: int = 96, height: int = 32) -> ROIImage:
    """A plain light ROI; the reader double decides what is 'found' in it."""

    return ROIImage(width, height, PixelFormat.RGB_888, bytes([220]) * (width * height * 3))


class _Reader:
    """A reader with EasyOCR's call shape and a scripted set of detections."""

    def __init__(
        self,
        horizontal: list[Any] | None = None,
        free: list[Any] | None = None,
        texts: list[tuple[str, float]] | None = None,
    ) -> None:
        self.horizontal = horizontal if horizontal is not None else [[8, 80, 4, 28]]
        self.free = free if free is not None else []
        self.texts = texts if texts is not None else [("책을", 0.91)]
        self.detect_calls: list[dict[str, Any]] = []
        self.recognize_calls: list[tuple[list[Any], list[Any]]] = []

    def detect(self, _image: Any, **kwargs: Any) -> tuple[list[Any], list[Any]]:
        self.detect_calls.append(kwargs)
        return [self.horizontal], [self.free]

    def recognize(
        self,
        _grey: Any,
        horizontal_list: list[Any] | None = None,
        free_list: list[Any] | None = None,
        **_kwargs: Any,
    ) -> list[tuple[list[list[float]], str, float]]:
        self.recognize_calls.append((list(horizontal_list or []), list(free_list or [])))
        index = len(self.recognize_calls) - 1
        if index >= len(self.texts):
            return []
        box = (horizontal_list or free_list or [[0, 1, 0, 1]])[0]
        text, confidence = self.texts[index]
        return [(_corners(box), text, confidence)]


def _corners(box: Any) -> list[list[float]]:
    if len(box) == 4 and not isinstance(box[0], (list, tuple)):
        left, right, top, bottom = (float(value) for value in box)
        return [[left, top], [right, top], [right, bottom], [left, bottom]]
    return [[float(point[0]), float(point[1])] for point in box]


def _requires_easyocr() -> None:
    pytest.importorskip("easyocr.utils", reason="the staged runner needs EasyOCR")


# --- API-shape failure ------------------------------------------------------


class _WithoutDetect:
    def recognize(self, *_args: Any, **_kwargs: Any) -> list[Any]:
        return []


def test_a_reader_without_the_expected_stages_fails_by_name() -> None:
    with pytest.raises(StagedEasyOCRError, match="missing detect"):
        verify_easyocr_api(_WithoutDetect())


def test_verification_reports_the_version_it_checked() -> None:
    _requires_easyocr()

    assert verify_easyocr_api(_Reader()) == PINNED_EASYOCR_VERSION


def test_an_unknown_evidence_class_is_refused_before_anything_runs() -> None:
    reader = _Reader()

    with pytest.raises(ValueError, match="unknown evidence class"):
        run_staged_easyocr(reader, _roi(), evidence_class="whatever")

    assert reader.detect_calls == []


# --- Staged evidence --------------------------------------------------------


def test_a_horizontal_region_keeps_the_crop_its_text_came_from() -> None:
    _requires_easyocr()
    reader = _Reader()

    run = run_staged_easyocr(reader, _roi(), evidence_class=STAGED_DIAGNOSTIC)

    (region,) = run.regions
    assert region.kind == "horizontal"
    assert region.text == "책을"
    assert region.crop is not None
    assert region.crop.height == RECOGNIZER_HEIGHT
    assert region.crop.mode == "L"
    assert region.crop.byte_count == region.crop.width * region.crop.height
    assert region.recognizer_input is region.crop
    assert region.unavailable_reason is None
    # The box that was cropped is the box that was recognized.
    assert reader.recognize_calls == [([reader.horizontal[0]], [])]


def test_a_free_form_region_is_recognized_through_the_free_list() -> None:
    _requires_easyocr()
    quad = [[10.0, 6.0], [70.0, 2.0], [72.0, 26.0], [12.0, 30.0]]
    reader = _Reader(horizontal=[], free=[quad], texts=[("읽다", 0.8)])

    run = run_staged_easyocr(reader, _roi())

    (region,) = run.regions
    assert region.kind == "free"
    assert region.raw_box == tuple(tuple(point) for point in quad)
    assert region.crop is not None
    assert reader.recognize_calls == [([], [quad])]


def test_regions_carry_the_detector_geometry_before_normalization() -> None:
    _requires_easyocr()
    reader = _Reader(horizontal=[[8, 80, 4, 28]])

    run = run_staged_easyocr(reader, _roi())

    (region,) = run.regions
    assert region.raw_box == (8.0, 80.0, 4.0, 28.0)
    assert region.quad == ((8.0, 4.0), (80.0, 4.0), (80.0, 28.0), (8.0, 28.0))


def test_every_region_joins_to_its_own_crop_and_text() -> None:
    _requires_easyocr()
    reader = _Reader(
        horizontal=[[4, 40, 2, 26], [44, 90, 2, 26]],
        texts=[("첫째", 0.9), ("둘째", 0.7)],
    )

    run = run_staged_easyocr(reader, _roi())

    assert [region.index for region in run.regions] == [0, 1]
    assert [region.text for region in run.regions] == ["첫째", "둘째"]
    assert len({region.crop for region in run.regions}) == 2
    assert [region.confidence for region in run.regions] == [0.9, 0.7]


def test_a_region_the_recognizer_read_nothing_from_says_why() -> None:
    _requires_easyocr()
    reader = _Reader(horizontal=[[4, 40, 2, 26]], texts=[])

    run = run_staged_easyocr(reader, _roi())

    (region,) = run.regions
    assert region.text is None
    assert region.unavailable_reason == "recognition_empty"
    assert run.normalized == ()


def test_staged_output_is_normalized_by_the_adapter_not_by_this_module() -> None:
    _requires_easyocr()
    # A blank recognition is dropped by the adapter's own normalization, and a
    # confidence above one is clamped there; both must hold here unchanged.
    reader = _Reader(
        horizontal=[[4, 40, 2, 26], [44, 90, 2, 26]],
        texts=[("", 0.9), ("책", 1.4)],
    )

    run = run_staged_easyocr(reader, _roi())

    assert [result.text for result in run.normalized] == ["책"]
    assert run.normalized[0].confidence == 1.0


def test_a_staged_run_records_its_timings_and_the_version_it_used() -> None:
    _requires_easyocr()

    run = run_staged_easyocr(_Reader(), _roi())

    assert run.easyocr_version == PINNED_EASYOCR_VERSION
    assert run.notes == ()
    assert run.detection_ns > 0
    assert run.total_ns >= run.detection_ns
    assert run.source.width == 96 and run.grayscale.mode == "L"


# --- The two evidence classes stay apart ------------------------------------


def test_a_diagnostic_run_owns_its_internals_and_a_replay_says_it_is_one() -> None:
    _requires_easyocr()

    diagnostic = run_staged_easyocr(_Reader(), _roi(), evidence_class=STAGED_DIAGNOSTIC)
    replay = run_staged_easyocr(_Reader(), _roi(), evidence_class=COMPARISON_REPLAY)

    assert diagnostic.is_replay is False
    assert replay.is_replay is True
    assert replay.evidence_class == COMPARISON_REPLAY


def test_an_agreeing_replay_is_reported_as_agreement() -> None:
    _requires_easyocr()
    reader = _Reader(texts=[("책을", 0.91)])
    staged = run_staged_easyocr(reader, _roi(), evidence_class=COMPARISON_REPLAY)

    comparison = compare_to_live(staged.normalized, staged)

    assert comparison.matches is True
    assert comparison.differences == ()


def test_a_diverging_replay_is_surfaced_and_leaves_the_live_result_alone() -> None:
    """A replay that disagrees is a finding, never a correction."""

    _requires_easyocr()
    live_run = run_staged_easyocr(_Reader(texts=[("책을", 0.91)]), _roi())
    replay = run_staged_easyocr(
        _Reader(texts=[("책울", 0.44)]), _roi(), evidence_class=COMPARISON_REPLAY
    )

    comparison = compare_to_live(live_run.normalized, replay)

    assert comparison.matches is False
    assert comparison.differences == ("region 0 text: '책을' vs '책울'",)
    assert comparison.live == live_run.normalized
    assert comparison.staged == replay.normalized


def test_a_replay_that_found_a_different_number_of_regions_says_so() -> None:
    _requires_easyocr()
    live_run = run_staged_easyocr(_Reader(texts=[("책을", 0.91)]), _roi())
    replay = run_staged_easyocr(
        _Reader(horizontal=[], free=[], texts=[]), _roi(), evidence_class=COMPARISON_REPLAY
    )

    comparison = compare_to_live(live_run.normalized, replay)

    assert comparison.matches is False
    assert comparison.differences == ("region count: live 1 vs staged 0",)
