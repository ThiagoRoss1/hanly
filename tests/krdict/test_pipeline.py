"""Production-database pipeline regressions with real Korean providers."""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

import pytest
from hanly import (
    BoundingBox,
    DictionaryEntry,
    LookupPipeline,
    LookupResult,
    LookupStatus,
    OCRResult,
    PixelFormat,
    Point,
    Quad,
    ROIImage,
)
from hanly.easyocr_provider import EasyOCRConfig, EasyOCRProvider
from hanly.kiwi_provider import KiwiProvider
from hanly.krdict_provider import KRDICTProvider
from hanly.providers import OCRProvider

DATABASE = Path(__file__).parents[2] / "data" / "generated" / "krdict.sqlite3"
IMAGE_PATH = Path(__file__).parents[1] / "hanly_fixtures" / "assets" / "korean_reading_roi.png"
IMAGE = ROIImage(192, 48, PixelFormat.RGB_888, bytes(192 * 48 * 3))
TARGET = Point(110, 24)
READ_ENTRY = DictionaryEntry(
    headword="읽다",
    definitions=(
        "To see written words or letters, and utter them as they are pronounced.",
        "To read written words and know their meaning.",
        "To read a work of a writer.",
        "To understand what a picture, sign, or sound indicates.",
        "To understand the nature or characteristic of a certain object or situation.",
        "To look at someone's facial expression or acts and then know how he/she feels.",
        "In the game of go or janggi, Korean chess, to think about a move or guess "
        "the move of the other party.",
        "To grasp the data of a computer.",
        "To interpret a certain writing or remark in a particular way.",
    ),
    part_of_speech="동사",
)


def _database() -> Path:
    if DATABASE.is_file():
        return DATABASE
    if os.environ.get("HANLY_REQUIRE_REAL_KRDICT") == "1":
        pytest.fail(f"required production KRDICT database is missing: {DATABASE}")
    pytest.skip("production KRDICT database is a local generated artifact")


class _OCRResultFixture:
    def recognize(self, _image: ROIImage) -> Sequence[OCRResult]:
        return (
            OCRResult(
                text="책을 읽습니다.",
                confidence=0.95,
                quad=Quad.from_bounding_box(BoundingBox(0, 0, 192, 48)),
            ),
        )


def _lookup(ocr: OCRProvider, image: ROIImage) -> LookupResult:
    pytest.importorskip("kiwipiepy")
    dictionary = KRDICTProvider(_database())
    pipeline = LookupPipeline(ocr, KiwiProvider(), dictionary)
    try:
        return pipeline.lookup(image, TARGET)
    finally:
        dictionary.close()


def test_deterministic_ocr_result_flows_through_real_kiwi_and_production_krdict() -> None:
    result = _lookup(_OCRResultFixture(), IMAGE)

    assert result.status is LookupStatus.SUCCESS
    assert result.context is not None
    assert (result.context.text, result.context.lemma) == ("읽습니다.", "읽다")
    assert result.entries == (READ_ENTRY,)


def test_real_easyocr_fixture_flows_through_real_kiwi_and_production_krdict() -> None:
    if os.environ.get("HANLY_RUN_REAL_EASYOCR") != "1":
        pytest.skip("real EasyOCR model inference is an opt-in supported-environment test")
    pillow = pytest.importorskip("PIL.Image")
    pytest.importorskip("easyocr")
    image = pillow.open(IMAGE_PATH).convert("RGB")
    roi = ROIImage(image.width, image.height, PixelFormat.RGB_888, image.tobytes())

    result = _lookup(EasyOCRProvider(EasyOCRConfig(download_enabled=False)), roi)

    assert result.status is LookupStatus.SUCCESS
    assert result.context is not None
    assert result.context.text == "읽습니다."
    assert result.context.lemma == "읽다"
    assert result.entries == (READ_ENTRY,)
