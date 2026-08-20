"""Focused tests for the normalized provider protocols."""

from collections.abc import Sequence
from inspect import signature
from typing import get_type_hints

from hanly import (
    BoundingBox,
    DictionaryEntry,
    DictionaryProvider,
    MorphologyProvider,
    OCRProvider,
    OCRResult,
    PixelFormat,
    Quad,
    ROIImage,
    TokenAnalysis,
)

_ROI = ROIImage(
    width=2,
    height=1,
    pixel_format=PixelFormat.GRAYSCALE_8,
    data=bytes([0, 255]),
)


class _StructuralOCRProvider:
    def recognize(self, image: ROIImage) -> Sequence[OCRResult]:
        del image
        # Reading order is the adapter's responsibility; two regions are
        # returned in the order a caller may rely on.
        return (
            OCRResult(
                text="책을",
                confidence=0.9,
                quad=Quad.from_bounding_box(
                    BoundingBox(left=0, top=0, right=10, bottom=10)
                ),
            ),
            OCRResult(
                text="읽습니다.",
                confidence=0.9,
                quad=Quad.from_bounding_box(
                    BoundingBox(left=12, top=0, right=30, bottom=10)
                ),
            ),
        )


class _StructuralMorphologyProvider:
    def analyze(self, text: str) -> Sequence[TokenAnalysis]:
        return (
            TokenAnalysis(
                token=text,
                lemma=text,
                part_of_speech="noun",
                morphology="base",
            ),
        )


class _StructuralDictionaryProvider:
    def lookup(self, lemma: str) -> Sequence[DictionaryEntry]:
        return (DictionaryEntry(headword=lemma, definitions=("a definition",)),)


def test_ocr_provider_protocol_is_structurally_conformant() -> None:
    assert isinstance(_StructuralOCRProvider(), OCRProvider)


def test_morphology_provider_protocol_is_structurally_conformant() -> None:
    assert isinstance(_StructuralMorphologyProvider(), MorphologyProvider)


def test_dictionary_provider_protocol_is_structurally_conformant() -> None:
    assert isinstance(_StructuralDictionaryProvider(), DictionaryProvider)


def test_provider_implementations_satisfy_the_protocols_statically() -> None:
    """`runtime_checkable` isinstance() checks method names only.

    These assignments are what actually verify the signatures: mypy rejects an
    implementation whose parameters or return type do not match the protocol,
    which `isinstance` above would happily accept.
    """

    ocr: OCRProvider = _StructuralOCRProvider()
    morphology: MorphologyProvider = _StructuralMorphologyProvider()
    dictionary: DictionaryProvider = _StructuralDictionaryProvider()

    assert ocr.recognize(_ROI)
    assert morphology.analyze("한국어")
    assert dictionary.lookup("한국어")


def test_ocr_results_are_returned_in_reading_order() -> None:
    """The provider contract states results arrive in reading order, so a
    caller may rely on sequence order instead of re-deriving it."""

    results = _StructuralOCRProvider().recognize(_ROI)

    assert [result.text for result in results] == ["책을", "읽습니다."]
    lefts = [result.bounding_box.left for result in results]
    assert lefts == sorted(lefts)


def test_provider_protocol_methods_have_the_published_names() -> None:
    ocr_method = OCRProvider.recognize
    morphology_method = MorphologyProvider.analyze
    dictionary_method = DictionaryProvider.lookup

    assert tuple(signature(ocr_method).parameters) == ("self", "image")
    assert tuple(signature(morphology_method).parameters) == ("self", "text")
    assert tuple(signature(dictionary_method).parameters) == ("self", "lemma")

    assert get_type_hints(ocr_method)["image"] is ROIImage
    assert get_type_hints(ocr_method)["return"] == Sequence[OCRResult]
    assert get_type_hints(morphology_method)["text"] is str
    assert get_type_hints(morphology_method)["return"] == Sequence[TokenAnalysis]
    assert get_type_hints(dictionary_method)["lemma"] is str
    assert get_type_hints(dictionary_method)["return"] == Sequence[DictionaryEntry]
