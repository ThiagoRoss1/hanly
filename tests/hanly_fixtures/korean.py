"""Deliberately small Korean examples for provider and resolver tests."""

from hanly import BoundingBox, DictionaryEntry, OCRResult, Quad, TokenAnalysis

KOREAN_TEXT = "책을 읽습니다."

KOREAN_OCR_RESULTS: tuple[OCRResult, ...] = (
    OCRResult(
        text="책을",
        confidence=0.95,
        quad=Quad.from_bounding_box(BoundingBox(left=0, top=0, right=48, bottom=48)),
    ),
    OCRResult(
        text="읽습니다.",
        confidence=0.95,
        quad=Quad.from_bounding_box(BoundingBox(left=52, top=0, right=192, bottom=48)),
    ),
)

KOREAN_TOKEN_ANALYSES: tuple[TokenAnalysis, ...] = (
    TokenAnalysis(
        token="책",
        lemma="책",
        part_of_speech="명사",
        morphology="일반",
    ),
    TokenAnalysis(
        token="을",
        lemma="을",
        part_of_speech="조사",
        morphology="목적격",
    ),
    TokenAnalysis(
        token="읽습니다",
        lemma="읽다",
        part_of_speech="동사",
        morphology="현재·격식체",
    ),
)

KOREAN_DICTIONARY_ENTRIES: tuple[DictionaryEntry, ...] = (
    DictionaryEntry(
        headword="책",
        definitions=("book",),
        part_of_speech="명사",
    ),
    DictionaryEntry(
        headword="읽다",
        definitions=("to read",),
        part_of_speech="동사",
    ),
)

__all__ = [
    "KOREAN_DICTIONARY_ENTRIES",
    "KOREAN_OCR_RESULTS",
    "KOREAN_TEXT",
    "KOREAN_TOKEN_ANALYSES",
]
