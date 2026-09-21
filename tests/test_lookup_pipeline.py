"""Focused tests for the normalized engine lookup pipeline."""

from collections.abc import Sequence

import pytest
from hanly import (
    BoundingBox,
    DictionaryEntry,
    HanlyError,
    LexicalCandidate,
    LookupStatus,
    MorphologyAnalysis,
    MorphologyProvider,
    OCRResult,
    PixelFormat,
    Point,
    Quad,
    ROIImage,
    TargetResolution,
    TokenAnalysis,
)
from hanly.providers import DictionaryProvider, OCRProvider
from hanly.word_resolver import WordResolver

_IMAGE = ROIImage(
    width=2,
    height=1,
    pixel_format=PixelFormat.GRAYSCALE_8,
    data=b"\x00\xff",
)
_TARGET = Point(x=5, y=5)
_OCR_RESULT = OCRResult(
    text="읽습니다.",
    confidence=0.95,
    quad=Quad.from_bounding_box(
        BoundingBox(left=0, top=0, right=10, bottom=10)
    ),
)
_ENTRY = DictionaryEntry(
    headword="읽다",
    definitions=("to read",),
    part_of_speech="동사",
)
_BOOK_ENTRY = DictionaryEntry(
    headword="책",
    definitions=("book",),
    part_of_speech="명사",
)


class _OCR:
    def __init__(self, events: list[str], results: Sequence[OCRResult] = (_OCR_RESULT,)) -> None:
        self.events = events
        self.results = results

    def recognize(self, image: ROIImage) -> Sequence[OCRResult]:
        assert image is _IMAGE
        self.events.append("ocr")
        return self.results


class _Resolver:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def resolve_target(
        self,
        ocr_results: Sequence[OCRResult] | None,
        target: Point | None,
    ) -> tuple[OCRResult, str] | None:
        self.events.append("resolver")
        return WordResolver.resolve_target(ocr_results, target)


class _Morphology:
    def __init__(self, events: list[str], analyses: Sequence[TokenAnalysis]) -> None:
        self.events = events
        self.analyses = analyses

    def analyze(self, text: str) -> Sequence[TokenAnalysis]:
        assert text == "읽습니다."
        self.events.append("morphology")
        return self.analyses


class _Dictionary:
    def __init__(self, events: list[str], entries: Sequence[DictionaryEntry]) -> None:
        self.events = events
        self.entries = entries
        self.lemmas: list[str] = []

    def lookup(self, lemma: str) -> Sequence[DictionaryEntry]:
        self.events.append("dictionary")
        self.lemmas.append(lemma)
        # Only the forms it actually holds, so the surface and whole-form
        # probes see a real miss rather than a universal hit.
        if any(entry.headword == lemma for entry in self.entries):
            return self.entries
        return ()


def _morphology(events: list[str], analyses: Sequence[TokenAnalysis] | None = None) -> _Morphology:
    return _Morphology(
        events,
        analyses
        if analyses is not None
        else (TokenAnalysis(token="읽습니다", lemma="읽다", part_of_speech="동사"),),
    )


def _pipeline(
    events: list[str],
    *,
    ocr_results: Sequence[OCRResult] = (_OCR_RESULT,),
    analyses: Sequence[TokenAnalysis] | None = None,
    entries: Sequence[DictionaryEntry] = (_ENTRY,),
    confidence_threshold: float | None = None,
):
    from hanly.lookup_pipeline import LookupPipeline

    return LookupPipeline(
        ocr_provider=_OCR(events, ocr_results),
        morphology_provider=_morphology(events, analyses),
        dictionary_provider=_Dictionary(events, entries),
        word_resolver=_Resolver(events),
        confidence_threshold=confidence_threshold,
    )


def test_a_provider_without_spans_keeps_the_first_usable_lemma() -> None:
    """A morphology provider written against the older contract stays valid.

    Without spans nothing can be targeted, so the first usable lemma remains
    the answer and no reduction is claimed that the evidence cannot support.
    """

    line = OCRResult(
        text="책을 읽습니다.",
        confidence=0.95,
        quad=Quad.from_bounding_box(BoundingBox(left=0, top=0, right=192, bottom=48)),
    )

    class _AnyTextMorphology:
        def __init__(self, analyses: Sequence[TokenAnalysis]) -> None:
            self.analyses = analyses

        def analyze(self, text: str) -> Sequence[TokenAnalysis]:
            assert text == line.text
            return self.analyses

    class _WholeRegionResolver:
        def resolve_target(
            self,
            ocr_results: Sequence[OCRResult] | None,
            target: Point | None,
        ) -> tuple[OCRResult, str] | None:
            del ocr_results, target
            return line, line.text

    from hanly.lookup_pipeline import LookupPipeline

    events: list[str] = []
    pipeline = LookupPipeline(
        ocr_provider=_OCR(events, (line,)),
        morphology_provider=_AnyTextMorphology(
            (
                TokenAnalysis(token="책", lemma="책", part_of_speech="명사"),
                TokenAnalysis(token="을", lemma="을", part_of_speech="조사"),
                TokenAnalysis(token="읽습니다", lemma="읽다", part_of_speech="동사"),
            )
        ),
        dictionary_provider=_Dictionary(events, (_BOOK_ENTRY,)),
        word_resolver=_WholeRegionResolver(),
    )

    result = pipeline.lookup(_IMAGE, Point(x=24, y=24))

    assert result.status is LookupStatus.SUCCESS
    assert result.context is not None
    assert result.context.lemma == "책"
    assert result.diagnostics == ()


def test_the_pointer_chooses_among_several_lexical_units() -> None:
    """Korean writes compounds without spaces, so counting words cannot find
    the ambiguous cases. Spans can, and the unselected units stay visible."""

    from hanly.lookup_pipeline import LookupPipeline

    line = OCRResult(
        text="책읽는",
        confidence=0.95,
        quad=Quad.from_bounding_box(BoundingBox(left=0, top=0, right=192, bottom=48)),
    )
    analysis = MorphologyAnalysis(
        tokens=(
            TokenAnalysis(token="책", lemma="책", part_of_speech="NNG", start=0, length=1),
            TokenAnalysis(token="읽", lemma="읽다", part_of_speech="VV", start=1, length=1),
        ),
        candidates=(
            LexicalCandidate(lemma="책", start=0, end=1, part_of_speech="NNG"),
            LexicalCandidate(lemma="읽다", start=1, end=3, part_of_speech="VV"),
        ),
    )

    class _Analysis:
        def analyze(self, text: str) -> MorphologyAnalysis:
            del text
            return analysis

    class _PointingResolver:
        def __init__(self, index: int) -> None:
            self.index = index

        def resolve_target(
            self,
            ocr_results: Sequence[OCRResult] | None,
            target: Point | None,
        ) -> tuple[OCRResult, str] | None:
            del ocr_results, target
            return line, line.text

        def resolve_target_detail(
            self,
            ocr_results: Sequence[OCRResult] | None,
            target: Point | None,
        ) -> TargetResolution:
            del ocr_results, target
            return TargetResolution(
                region=line, text=line.text, cursor_index=self.index, region_start=0
            )

    class _UnitsOnlyDictionary(_Dictionary):
        """Neither `책읽는` nor `책읽다` is a word; only the units are."""

        def lookup(self, lemma: str) -> Sequence[DictionaryEntry]:
            found = super().lookup(lemma)
            return found if lemma in {"책", "읽다"} else ()

    for index, expected in ((0, "책"), (1, "읽다"), (2, "읽다")):
        events: list[str] = []
        pipeline = LookupPipeline(
            ocr_provider=_OCR(events, (line,)),
            morphology_provider=_Analysis(),
            dictionary_provider=_UnitsOnlyDictionary(events, (_ENTRY,)),
            word_resolver=_PointingResolver(index),
        )

        result = pipeline.lookup(_IMAGE, Point(x=24, y=24))

        assert result.context is not None
        assert result.context.lemma == expected, index
        assert any("2 lexical units" in note for note in result.diagnostics)


def test_narrowed_word_with_several_lemmas_reports_no_reduction_diagnostic() -> None:
    """Korean morphology routinely splits one resolved word into several
    lemmas. That is not a reduction and must not produce a diagnostic."""

    events: list[str] = []
    pipeline = _pipeline(
        events,
        analyses=(
            TokenAnalysis(token="읽", lemma="읽다", part_of_speech="동사"),
            TokenAnalysis(token="습니다", lemma="습니다", part_of_speech="어미"),
        ),
    )

    result = pipeline.lookup(_IMAGE, _TARGET)

    assert result.status is LookupStatus.SUCCESS
    assert result.diagnostics == ()


def test_pipeline_narrows_a_line_region_before_morphology() -> None:
    events: list[str] = []
    line = OCRResult(
        text="책을 읽습니다.",
        confidence=0.95,
        quad=Quad.from_bounding_box(
            BoundingBox(left=0, top=0, right=192, bottom=48)
        ),
    )
    from hanly.lookup_pipeline import LookupPipeline

    pipeline = LookupPipeline(
        ocr_provider=_OCR(events, (line,)),
        morphology_provider=_morphology(events),
        dictionary_provider=_Dictionary(events, (_ENTRY,)),
    )

    result = pipeline.lookup(_IMAGE, Point(x=120, y=24))

    assert result.status is LookupStatus.SUCCESS
    assert result.context is not None
    assert result.context.text == "읽습니다."
    assert result.context.lemma == "읽다"
    assert result.diagnostics == ()


def test_single_token_segment_reports_no_reduction_diagnostic() -> None:
    events: list[str] = []

    result = _pipeline(events).lookup(_IMAGE, _TARGET)

    assert result.status is LookupStatus.SUCCESS
    assert result.diagnostics == ()


@pytest.mark.parametrize("text", ["hello", "hello책", "책2"])
def test_non_korean_target_stops_before_morphology_and_dictionary(text: str) -> None:
    events: list[str] = []
    target_segment = OCRResult(
        text=text,
        confidence=0.99,
        quad=Quad.from_bounding_box(
            BoundingBox(left=0, top=0, right=10, bottom=10)
        ),
    )

    result = _pipeline(events, ocr_results=(target_segment,)).lookup(_IMAGE, _TARGET)

    assert result.status is LookupStatus.UNUSABLE
    assert result.context is not None
    assert result.context.text == text
    assert events == ["ocr", "resolver"]
    assert any("Hangul" in diagnostic for diagnostic in result.diagnostics)


def test_korean_target_with_spaces_and_punctuation_reaches_morphology_and_dictionary() -> None:
    events: list[str] = []
    line = OCRResult(
        text="책을 읽습니다.",
        confidence=0.99,
        quad=Quad.from_bounding_box(BoundingBox(left=0, top=0, right=192, bottom=48)),
    )

    class _WholeRegionResolver:
        def resolve_target(
            self,
            ocr_results: Sequence[OCRResult] | None,
            target: Point | None,
        ) -> tuple[OCRResult, str] | None:
            del ocr_results, target
            events.append("resolver")
            return line, line.text

    class _AnyTextMorphology:
        def analyze(self, text: str) -> Sequence[TokenAnalysis]:
            assert text == line.text
            events.append("morphology")
            return (TokenAnalysis(token="책", lemma="책", part_of_speech="명사"),)

    from hanly.lookup_pipeline import LookupPipeline

    pipeline = LookupPipeline(
        ocr_provider=_OCR(events, (line,)),
        morphology_provider=_AnyTextMorphology(),
        dictionary_provider=_Dictionary(events, (_BOOK_ENTRY,)),
        word_resolver=_WholeRegionResolver(),
    )

    result = pipeline.lookup(_IMAGE, _TARGET)

    assert result.status is LookupStatus.SUCCESS
    assert events == ["ocr", "resolver", "morphology", "dictionary", "dictionary"]


def test_error_diagnostic_does_not_repeat_the_stage_prefix() -> None:
    events: list[str] = []
    pipeline = _pipeline(events)
    pipeline._ocr_provider = _RaisingOCR()

    result = pipeline.lookup(_IMAGE, _TARGET)

    assert result.status is LookupStatus.ERROR
    assert result.diagnostics[0].count("OCR failed:") == 1


def test_pipeline_runs_stages_in_order_and_returns_success() -> None:
    events: list[str] = []
    pipeline = _pipeline(events)

    result = pipeline.lookup(_IMAGE, _TARGET)

    # The surface is probed before the lemma, so the stage appears twice.
    assert events == ["ocr", "resolver", "morphology", "dictionary", "dictionary"]
    assert result.status is LookupStatus.SUCCESS
    assert result.entries == (_ENTRY,)
    assert result.context is not None
    assert result.context.text == "읽습니다."
    assert result.context.lemma == "읽다"
    assert result.context.ocr_results == (_OCR_RESULT,)
    assert result.context.selected_ocr is _OCR_RESULT
    assert result.context.analyses == (
        TokenAnalysis(token="읽습니다", lemma="읽다", part_of_speech="동사"),
    )
    assert result.error is None


def test_pipeline_returns_empty_when_ocr_finds_no_regions() -> None:
    events: list[str] = []
    pipeline = _pipeline(events, ocr_results=())

    result = pipeline.lookup(_IMAGE, _TARGET)

    assert result.status is LookupStatus.EMPTY
    assert events == ["ocr"]
    assert result.context is not None
    assert result.context.ocr_results == ()
    assert any("OCR" in diagnostic for diagnostic in result.diagnostics)


def test_pipeline_returns_unusable_for_low_confidence_when_configured() -> None:
    events: list[str] = []
    pipeline = _pipeline(events, confidence_threshold=0.99)

    result = pipeline.lookup(_IMAGE, _TARGET)

    assert result.status is LookupStatus.UNUSABLE
    assert events == ["ocr", "resolver"]
    assert result.context is not None
    assert result.context.text == "읽습니다."
    assert result.context.selected_ocr is _OCR_RESULT
    assert any("confidence" in diagnostic.lower() for diagnostic in result.diagnostics)


def test_pipeline_allows_low_confidence_when_no_threshold_is_configured() -> None:
    events: list[str] = []
    pipeline = _pipeline(events, confidence_threshold=None)

    result = pipeline.lookup(_IMAGE, _TARGET)

    assert result.status is LookupStatus.SUCCESS


def test_pipeline_returns_unusable_when_target_does_not_resolve() -> None:
    events: list[str] = []
    pipeline = _pipeline(events)

    result = pipeline.lookup(_IMAGE, Point(x=50, y=50))

    assert result.status is LookupStatus.UNUSABLE
    assert events == ["ocr", "resolver"]
    assert result.context is not None
    assert result.context.text is None
    assert result.context.ocr_results == (_OCR_RESULT,)


def test_pipeline_returns_unusable_when_morphology_has_no_tokens() -> None:
    events: list[str] = []
    pipeline = _pipeline(events, analyses=())

    result = pipeline.lookup(_IMAGE, _TARGET)

    assert result.status is LookupStatus.UNUSABLE
    assert events == ["ocr", "resolver", "morphology"]
    assert result.context is not None
    assert result.context.text == "읽습니다."
    assert result.context.lemma is None


def test_pipeline_looks_up_only_the_first_usable_lemma_and_reports_not_found() -> None:
    events: list[str] = []
    analyses = (
        TokenAnalysis(token="읽습니다", lemma="읽다"),
        TokenAnalysis(token=".", lemma="문장부호"),
    )
    pipeline = _pipeline(events, analyses=analyses, entries=())

    result = pipeline.lookup(_IMAGE, _TARGET)

    assert result.status is LookupStatus.NOT_FOUND
    assert events == ["ocr", "resolver", "morphology", "dictionary", "dictionary"]
    assert result.context is not None
    assert result.context.lemma == "읽다"
    assert result.context.analyses == analyses
    assert any("읽다" in diagnostic for diagnostic in result.diagnostics)


def test_pipeline_converts_word_resolution_exceptions_to_error_results() -> None:
    from hanly.lookup_pipeline import LookupPipeline

    class _RaisingResolver:
        def resolve_target(
            self,
            ocr_results: Sequence[OCRResult] | None,
            target: Point | None,
        ) -> tuple[OCRResult, str] | None:
            del ocr_results, target
            raise RuntimeError("resolution exploded")

    result = LookupPipeline(
        _OCR([]),
        _morphology([]),
        _Dictionary([], (_ENTRY,)),
        word_resolver=_RaisingResolver(),
    ).lookup(_IMAGE, _TARGET)

    assert result.status is LookupStatus.ERROR
    assert isinstance(result.error, HanlyError)
    assert result.error is not None
    assert "word resolution" in str(result.error).lower()
    assert result.context is not None
    assert result.context.ocr_results == (_OCR_RESULT,)


@pytest.mark.parametrize(
    "stage",
    [
        "OCR",
        "morphology",
        "dictionary",
    ],
)
def test_pipeline_converts_provider_exceptions_to_error_results(stage: str) -> None:
    from hanly.lookup_pipeline import LookupPipeline

    events: list[str] = []
    ocr: OCRProvider = _OCR(events)
    morphology: MorphologyProvider = _morphology(events)
    dictionary: DictionaryProvider = _Dictionary(events, (_ENTRY,))
    if stage == "OCR":
        ocr = _RaisingOCR()
    elif stage == "morphology":
        morphology = _RaisingMorphology()
    else:
        dictionary = _RaisingDictionary()
    result = LookupPipeline(ocr, morphology, dictionary).lookup(_IMAGE, _TARGET)

    assert result.status is LookupStatus.ERROR
    assert isinstance(result.error, HanlyError)
    assert result.error is not None
    assert stage.lower() in str(result.error).lower()
    assert any(stage.lower() in diagnostic.lower() for diagnostic in result.diagnostics)


class _RaisingOCR:
    def recognize(self, image: ROIImage) -> Sequence[OCRResult]:
        del image
        raise RuntimeError("recognition exploded")


class _RaisingMorphology:
    def analyze(self, text: str) -> Sequence[TokenAnalysis]:
        del text
        raise RuntimeError("analysis exploded")


class _RaisingDictionary:
    def lookup(self, lemma: str) -> Sequence[DictionaryEntry]:
        del lemma
        raise RuntimeError("lookup exploded")
