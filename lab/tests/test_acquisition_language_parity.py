"""Compare normalized OCR targeting with production direct-text acquisition."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from hanly import (
    BoundingBox,
    LookupStatus,
    OCRResult,
    PixelFormat,
    Point,
    Quad,
    ROIImage,
)
from hanly.kiwi_provider import KiwiProvider
from hanly.krdict_provider import KRDICTProvider
from hanly.lookup_pipeline import LookupPipeline
from hanly.word_resolver import WordResolver
from hanly_app.acquisition.direct_text import DirectText, DirectTextCoordinator
from hanly_app.config import TechnicalDetailLevel
from hanly_app.popup.presentation import format_lookup_result

DATABASE = Path(__file__).parents[2] / "data" / "generated" / "krdict.sqlite3"
IMAGE = ROIImage(1000, 24, PixelFormat.RGB_888, bytes(1000 * 24 * 3))


def _database() -> Path:
    if DATABASE.is_file():
        return DATABASE
    if os.environ.get("HANLY_REQUIRE_REAL_KRDICT") == "1":
        pytest.fail(f"required production KRDICT database is missing: {DATABASE}")
    pytest.skip("production KRDICT database is a local generated artifact")


class _OCR:
    def __init__(self, reading: OCRResult) -> None:
        self.reading = reading
        self.calls = 0

    def recognize(self, _image: ROIImage) -> tuple[OCRResult, ...]:
        self.calls += 1
        return (self.reading,)


class _Reader:
    def __init__(self, text: str, cursor_index: int) -> None:
        self.text = text
        self.cursor_index = cursor_index

    def read_at(self, _point: Point, *, timeout_ms: int) -> DirectText:
        assert timeout_ms > 0
        return DirectText(self.text, self.cursor_index, BoundingBox(0, 0, 1000, 24))

    def refine_bounds(
        self,
        _point: Point,
        _start: int,
        _end: int,
        *,
        line: str,
        timeout_ms: int,
    ) -> BoundingBox:
        assert line == self.text
        assert timeout_ms > 0
        return BoundingBox(0, 0, 1000, 24)


class _RecordingKiwi:
    def __init__(self) -> None:
        self.provider = KiwiProvider()
        self.inputs: list[str] = []

    def analyze(self, text: str):
        self.inputs.append(text)
        return self.provider.analyze(text)


@pytest.mark.parametrize(
    ("line", "target", "cursor", "lemma", "construction"),
    [
        ("한국어를 할 수 있어요.", "할", 0, "하다", "-ㄹ 수 있다"),
        ("(학교)에 가요.", "(학교)에", 4, "학교", None),
    ],
    ids=("g092-bounded-construction", "parenthetical-particle"),
)
def test_ocr_and_direct_acquisition_feed_equivalent_bounded_language_input(
    line: str,
    target: str,
    cursor: int,
    lemma: str,
    construction: str | None,
) -> None:
    pytest.importorskip("kiwipiepy")
    database = _database()
    start = line.index(target)
    selected_cursor = start + cursor
    reading = OCRResult(
        line,
        0.99,
        Quad.from_bounding_box(BoundingBox(0, 0, 1000, 24)),
    )
    pointer = next(
        Point(x, 12)
        for x in range(1000)
        if (
            detail := WordResolver.resolve_target_detail((reading,), Point(x, 12))
        ) is not None
        and detail.text == target
        and detail.cursor_index == cursor
    )

    dictionary = KRDICTProvider(database)
    try:
        ocr_morphology = _RecordingKiwi()
        direct_morphology = _RecordingKiwi()
        ocr = _OCR(reading)
        unused_ocr = _OCR(reading)
        ocr_pipeline = LookupPipeline(ocr, ocr_morphology, dictionary)
        direct_pipeline = LookupPipeline(unused_ocr, direct_morphology, dictionary)
        direct = DirectTextCoordinator(
            _Reader(line, selected_cursor)
        ).acquire(pointer)
        assert direct.used_direct_text
        assert direct.selection is not None
        assert (
            direct.selection.text,
            direct.selection.cursor_index,
            direct.selection.context_before,
            direct.selection.context_after,
        ) == (
            target,
            cursor,
            "한국어를" if target == "할" else "",
            "수 있어요." if target == "할" else "가요.",
        )

        ocr_result = ocr_pipeline.lookup(IMAGE, pointer)
        direct_result = direct_pipeline.lookup_selection(direct.selection)
        ocr_content = format_lookup_result(ocr_result, TechnicalDetailLevel.OFF)
        direct_content = format_lookup_result(direct_result, TechnicalDetailLevel.OFF)
    finally:
        dictionary.close()

    assert ocr_result.status is direct_result.status is LookupStatus.SUCCESS
    assert ocr_result.context is not None and direct_result.context is not None
    assert (ocr_result.context.text, ocr_result.context.lemma) == (target, lemma)
    assert (direct_result.context.text, direct_result.context.lemma) == (target, lemma)
    assert ocr_result.context.construction == direct_result.context.construction
    actual_construction = (
        None
        if ocr_result.context.construction is None
        else ocr_result.context.construction.headword
    )
    assert actual_construction == construction
    assert ocr_content.entry == direct_content.entry
    assert ocr.calls == 1
    assert unused_ocr.calls == 0
    assert ocr_morphology.inputs == direct_morphology.inputs == [line]

