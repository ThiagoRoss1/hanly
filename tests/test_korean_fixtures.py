"""Focused tests for the small shared Korean fixture set."""

import json
import struct
from pathlib import Path

from hanly import BoundingBox, DictionaryEntry, OCRResult, TokenAnalysis
from hanly_fixtures.korean import (
    KOREAN_DICTIONARY_ENTRIES,
    KOREAN_OCR_RESULTS,
    KOREAN_TEXT,
    KOREAN_TOKEN_ANALYSES,
)

ASSET_DIRECTORY = Path(__file__).parent / "hanly_fixtures" / "assets"
KOREAN_ROI_PNG = ASSET_DIRECTORY / "korean_reading_roi.png"
KOREAN_ROI_METADATA = ASSET_DIRECTORY / "korean_reading_roi.json"


def test_korean_text_fixture_is_deterministic_and_human_readable() -> None:
    assert KOREAN_TEXT == "책을 읽습니다."


def test_korean_ocr_fixture_uses_normalized_contracts() -> None:
    assert len(KOREAN_OCR_RESULTS) == 2
    assert all(isinstance(result, OCRResult) for result in KOREAN_OCR_RESULTS)
    assert [result.text for result in KOREAN_OCR_RESULTS] == ["책을", "읽습니다."]
    assert KOREAN_OCR_RESULTS[0].bounding_box == BoundingBox(
        left=0, top=0, right=48, bottom=48
    )
    assert KOREAN_OCR_RESULTS[1].bounding_box == BoundingBox(
        left=52, top=0, right=192, bottom=48
    )
    assert [result.confidence for result in KOREAN_OCR_RESULTS] == [0.95, 0.95]


def test_korean_morphology_fixture_covers_a_short_sentence() -> None:
    assert len(KOREAN_TOKEN_ANALYSES) == 3
    assert all(isinstance(analysis, TokenAnalysis) for analysis in KOREAN_TOKEN_ANALYSES)
    assert [(analysis.token, analysis.lemma) for analysis in KOREAN_TOKEN_ANALYSES] == [
        ("책", "책"),
        ("을", "을"),
        ("읽습니다", "읽다"),
    ]


def test_korean_dictionary_fixture_covers_the_sentence_lemmas() -> None:
    assert len(KOREAN_DICTIONARY_ENTRIES) == 2
    assert all(isinstance(entry, DictionaryEntry) for entry in KOREAN_DICTIONARY_ENTRIES)
    assert [entry.headword for entry in KOREAN_DICTIONARY_ENTRIES] == ["책", "읽다"]
    assert KOREAN_DICTIONARY_ENTRIES[0].definitions == ("book",)
    assert KOREAN_DICTIONARY_ENTRIES[1].definitions == ("to read",)


def test_korean_raster_roi_has_png_dimensions_and_matching_metadata() -> None:
    metadata = json.loads(KOREAN_ROI_METADATA.read_text(encoding="utf-8"))
    png_data = KOREAN_ROI_PNG.read_bytes()

    assert png_data[:8] == b"\x89PNG\r\n\x1a\n"
    assert png_data[12:16] == b"IHDR"
    width, height = struct.unpack(">II", png_data[16:24])

    assert metadata["fixture_id"] == "korean_reading_roi"
    assert metadata["expected_text"] == KOREAN_TEXT
    assert metadata["purpose"] == "test-only Korean OCR ROI; non-benchmark fixture"
    assert metadata["benchmark"] is False
    assert metadata["format"] == "PNG"
    assert (width, height) == (metadata["width"], metadata["height"]) == (192, 48)
