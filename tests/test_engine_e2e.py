"""UI-free image-to-LookupResult validation for the Hanly engine."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest
from hanly import (
    BoundingBox,
    DictionaryEntry,
    HanlyError,
    LookupPipeline,
    LookupStatus,
    OCRResult,
    PixelFormat,
    Point,
    Quad,
    ROIImage,
)
from hanly.kiwi_provider import KiwiProvider
from hanly.krdict_build import build_krdict_database
from hanly.krdict_provider import KRDICTProvider
from hanly.providers import OCRProvider
from hanly.word_resolver import WordResolver
from hanly_fixtures.korean import KOREAN_OCR_RESULTS

_IMAGE = ROIImage(
    # These dimensions match the committed Korean ROI fixture.  The real
    # PaddleOCR path has already been verified against its PNG; this ordinary
    # E2E test keeps OCR deterministic by injecting the provider seam.
    width=192,
    height=48,
    pixel_format=PixelFormat.RGB_888,
    data=bytes(192 * 48 * 3),
)
_READING_TARGET = Point(x=100, y=24)
_NOUN_TARGET = Point(x=24, y=24)
_LINE_OCR_RESULT = OCRResult(
    text="책을 읽습니다.",
    confidence=0.95,
    quad=Quad.from_bounding_box(
        BoundingBox(left=0, top=0, right=192, bottom=48)
    ),
)


class _DeterministicOCR:
    """Inject normalized OCR evidence without loading a model."""

    def __init__(self, results: Sequence[OCRResult] = KOREAN_OCR_RESULTS) -> None:
        self.results = tuple(results)
        self.received_image: ROIImage | None = None

    def recognize(self, image: ROIImage) -> Sequence[OCRResult]:
        assert image is _IMAGE
        self.received_image = image
        return self.results


def _write_deterministic_krdict_source(path: Path) -> None:
    path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<dictionary>
  <entry>
    <headword>읽다</headword>
    <part_of_speech>동사</part_of_speech>
    <sense>
      <translation><language>English</language><trans_dfn>to read</trans_dfn></translation>
    </sense>
  </entry>
</dictionary>
""",
        encoding="utf-8",
    )


@pytest.fixture
def krdict_database(tmp_path: Path) -> Path:
    source = tmp_path / "krdict.xml"
    database = tmp_path / "krdict.sqlite3"
    _write_deterministic_krdict_source(source)
    return build_krdict_database(source, database)


@pytest.fixture(scope="module")
def real_kiwi() -> KiwiProvider:
    pytest.importorskip("kiwipiepy")
    return KiwiProvider()


def _pipeline(
    ocr: OCRProvider, kiwi: KiwiProvider, database: Path
) -> tuple[LookupPipeline, KRDICTProvider]:
    dictionary = KRDICTProvider(database)
    # The caller owns the provider lifecycle and closes it on the same thread.
    pipeline = LookupPipeline(
        ocr_provider=ocr,
        morphology_provider=kiwi,
        dictionary_provider=dictionary,
        word_resolver=WordResolver(),
    )
    return pipeline, dictionary


def test_engine_e2e_returns_success_from_roi_to_dictionary_entry(
    krdict_database: Path, real_kiwi: KiwiProvider
) -> None:
    ocr = _DeterministicOCR()
    pipeline, dictionary = _pipeline(ocr, real_kiwi, krdict_database)
    try:
        result = pipeline.lookup(_IMAGE, _READING_TARGET)
    finally:
        dictionary.close()

    assert ocr.received_image is _IMAGE
    assert result.status is LookupStatus.SUCCESS
    assert result.entries == (
        DictionaryEntry(headword="읽다", definitions=("to read",), part_of_speech="동사"),
    )
    assert result.diagnostics == ()
    assert result.error is None
    assert result.context is not None
    assert result.context.text == "읽습니다."
    assert result.context.lemma == "읽다"
    assert result.context.ocr_results == KOREAN_OCR_RESULTS


def test_engine_e2e_real_kiwi_looks_up_the_word_targeted_inside_a_line_region(
    krdict_database: Path, real_kiwi: KiwiProvider
) -> None:
    ocr = _DeterministicOCR((_LINE_OCR_RESULT,))
    pipeline, dictionary = _pipeline(ocr, real_kiwi, krdict_database)
    try:
        result = pipeline.lookup(_IMAGE, Point(x=120, y=24))
    finally:
        dictionary.close()

    assert result.status is LookupStatus.SUCCESS
    assert result.entries == (
        DictionaryEntry(headword="읽다", definitions=("to read",), part_of_speech="동사"),
    )
    assert result.context is not None
    assert result.context.text == "읽습니다."
    assert result.context.lemma == "읽다"


def test_engine_e2e_returns_normal_not_found_without_an_exception(
    krdict_database: Path, real_kiwi: KiwiProvider
) -> None:
    ocr = _DeterministicOCR()
    pipeline, dictionary = _pipeline(ocr, real_kiwi, krdict_database)
    try:
        result = pipeline.lookup(_IMAGE, _NOUN_TARGET)
    finally:
        dictionary.close()

    assert result.status is LookupStatus.NOT_FOUND
    assert result.entries == ()
    assert result.error is None
    assert result.context is not None
    assert result.context.text == "책을"
    assert result.context.lemma == "책"
    assert result.context.ocr_results == KOREAN_OCR_RESULTS


def test_engine_e2e_returns_error_result_for_dictionary_processing_failure(
    krdict_database: Path, real_kiwi: KiwiProvider
) -> None:
    ocr = _DeterministicOCR()
    pipeline, dictionary = _pipeline(ocr, real_kiwi, krdict_database)
    dictionary.close()

    result = pipeline.lookup(_IMAGE, _READING_TARGET)

    assert result.status is LookupStatus.ERROR
    assert isinstance(result.error, HanlyError)
    assert result.error is not None
    assert "closed" in str(result.error)
    assert any("dictionary" in diagnostic.lower() for diagnostic in result.diagnostics)
    assert result.context is not None
    assert result.context.text == "읽습니다."
    assert result.context.lemma == "읽다"
    assert result.context.ocr_results == KOREAN_OCR_RESULTS
