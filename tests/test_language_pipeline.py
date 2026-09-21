"""The acquisition-neutral language stage, and its parity with the pixel path.

The load-bearing test in this file is the parity one. Two acquisitions that
arrive at the same surface word and the same cursor offset must produce the same
answer, because there is one implementation underneath. If they ever diverge,
the seam has failed at the only thing it exists to do.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from hanly import (
    BoundingBox,
    DictionaryEntry,
    LanguagePipeline,
    LexicalCandidate,
    LookupContext,
    LookupPipeline,
    LookupResult,
    LookupStatus,
    MorphologyAnalysis,
    OCRResult,
    PixelFormat,
    Point,
    Quad,
    ROIImage,
    TextSelection,
    TokenAnalysis,
)
from hanly.errors import LookupCancelled

_IMAGE = ROIImage(1, 1, PixelFormat.GRAYSCALE_8, b"\x00")
#: One line of OCR text with the pointer inside the second word.
_LINE = "나는 초대받았어요"
_SURFACE = "초대받았어요"
#: Far enough along the quad to land inside `초대받았어요`.
_TARGET = Point(58, 5)


def _region(text: str = _LINE) -> OCRResult:
    return OCRResult(
        text=text,
        confidence=0.95,
        quad=Quad.from_bounding_box(BoundingBox(0, 0, 90, 10)),
    )


class _OCR:
    """Returns one line; the resolver picks the word under the target."""

    def __init__(self, text: str = _LINE) -> None:
        self.text = text
        self.calls = 0

    def recognize(self, _image: ROIImage) -> tuple[OCRResult, ...]:
        self.calls += 1
        return (_region(self.text),)


class _Morphology:
    """Kiwi-shaped: `초대받았어요` holds `초대` and `받다`."""

    def __init__(self) -> None:
        self.analyzed: list[str] = []

    def analyze(self, text: str) -> MorphologyAnalysis:
        self.analyzed.append(text)
        return MorphologyAnalysis(
            tokens=(
                TokenAnalysis(
                    token="초대", lemma="초대", part_of_speech="NNG", start=0, length=2
                ),
                TokenAnalysis(
                    token="받", lemma="받다", part_of_speech="VV", start=2, length=1
                ),
                TokenAnalysis(
                    token="았어요", lemma="었어요", part_of_speech="EF", start=3, length=3
                ),
            ),
            candidates=(
                LexicalCandidate(lemma="초대", start=0, end=2, part_of_speech="NNG"),
                LexicalCandidate(lemma="받다", start=2, end=6, part_of_speech="VV"),
            ),
        )


class _Dictionary:
    """Holds `초대` and `받다`; deliberately has no `초대받다`, like KRDICT."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    def lookup(self, lemma: str) -> tuple[DictionaryEntry, ...]:
        self.queries.append(lemma)
        if lemma in {"초대", "받다"}:
            return (DictionaryEntry(headword=lemma, definitions=(f"meaning of {lemma}",)),)
        return ()


def _language(
    morphology: _Morphology | None = None, dictionary: _Dictionary | None = None
) -> tuple[LanguagePipeline, _Morphology, _Dictionary]:
    m = morphology or _Morphology()
    d = dictionary or _Dictionary()
    return LanguagePipeline(m, d), m, d


def _pixel(
    ocr: _OCR | None = None,
    morphology: _Morphology | None = None,
    dictionary: _Dictionary | None = None,
    **options: object,
) -> tuple[LookupPipeline, _OCR, _Morphology, _Dictionary]:
    o = ocr or _OCR()
    m = morphology or _Morphology()
    d = dictionary or _Dictionary()
    return LookupPipeline(o, m, d, **options), o, m, d  # type: ignore[arg-type]


# --- Parity: the whole point of the seam ------------------------------------


@pytest.mark.parametrize(
    ("cursor_index", "lemma"),
    [(0, "초대"), (1, "초대"), (2, "받다"), (3, "받다"), (5, "받다")],
)
def test_pixel_and_direct_selections_agree_at_every_cursor_offset(
    cursor_index: int, lemma: str
) -> None:
    """Identical text and index, two acquisitions, one answer."""

    language, _m, direct_dictionary = _language()
    direct = language.lookup(TextSelection(_SURFACE, cursor_index))

    pipeline, _o, _pm, pixel_dictionary = _pixel()
    via_facade = pipeline.lookup_selection(TextSelection(_SURFACE, cursor_index))

    assert direct.status is via_facade.status is LookupStatus.SUCCESS
    assert direct.entries == via_facade.entries
    assert direct.diagnostics == via_facade.diagnostics
    assert direct.context is not None and via_facade.context is not None
    assert direct.context.lemma == via_facade.context.lemma == lemma
    assert direct.context.candidate == via_facade.context.candidate
    assert direct_dictionary.queries == pixel_dictionary.queries == [lemma]


def test_a_real_pixel_lookup_and_an_equivalent_direct_selection_agree() -> None:
    """The pixel path resolves a selection; handing the engine that same
    selection directly must reach the same answer."""

    pipeline, _o, morphology, dictionary = _pixel()
    from_pixels = pipeline.lookup(_IMAGE, _TARGET)

    assert from_pixels.context is not None
    surface = from_pixels.context.text
    assert surface == _SURFACE
    # Recover the offset the resolver chose, then replay it without an image.
    from hanly.word_resolver import WordResolver

    resolution = WordResolver.resolve_target_detail([_region()], _TARGET)
    assert resolution is not None

    language, _m2, direct_dictionary = _language()
    direct = language.lookup(TextSelection(surface, resolution.cursor_index))

    assert direct.status is from_pixels.status
    assert direct.entries == from_pixels.entries
    assert direct.diagnostics == from_pixels.diagnostics
    assert direct.context is not None
    assert direct.context.lemma == from_pixels.context.lemma
    assert direct.context.candidate == from_pixels.context.candidate
    assert direct.context.analyses == from_pixels.context.analyses
    assert dictionary.queries == direct_dictionary.queries


def test_the_two_paths_run_one_implementation_not_two() -> None:
    """A pixel lookup analyzes exactly the text a direct selection would."""

    pipeline, _o, morphology, _d = _pixel()
    pipeline.lookup(_IMAGE, _TARGET)

    assert morphology.analyzed == [_SURFACE]


# --- The pixel facade stays compatible --------------------------------------


def test_the_pixel_facade_still_reports_its_ocr_evidence() -> None:
    pipeline, _o, _m, _d = _pixel()

    result = pipeline.lookup(_IMAGE, _TARGET)

    assert result.status is LookupStatus.SUCCESS
    context = result.context
    assert context is not None
    assert context.ocr_results == (_region(),)
    assert context.selected_ocr == _region()
    assert context.word_region is not None
    assert context.text == _SURFACE


def test_a_direct_selection_carries_no_pixel_evidence_it_never_had() -> None:
    language, _m, _d = _language()

    result = language.lookup(TextSelection(_SURFACE, 2))

    context = result.context
    assert context is not None
    assert context.ocr_results == ()
    assert context.selected_ocr is None
    assert context.word_region is None
    assert context.text == _SURFACE


def test_empty_ocr_is_still_an_empty_pixel_result() -> None:
    class Blank:
        def recognize(self, _image: ROIImage) -> tuple[OCRResult, ...]:
            return ()

    pipeline, _o, _m, _d = _pixel(ocr=Blank())  # type: ignore[arg-type]

    result = pipeline.lookup(_IMAGE, _TARGET)

    assert result.status is LookupStatus.EMPTY
    assert result.context is not None and result.context.ocr_results == ()


def test_low_confidence_remains_a_pixel_only_decision() -> None:
    """The language stage has no confidence to judge; the facade keeps it."""

    class Faint:
        def recognize(self, _image: ROIImage) -> tuple[OCRResult, ...]:
            return (_region_with_confidence(0.10),)

    def _region_with_confidence(value: float) -> OCRResult:
        return OCRResult(_LINE, value, Quad.from_bounding_box(BoundingBox(0, 0, 90, 10)))

    pipeline, _o, morphology, _d = _pixel(
        ocr=Faint(), confidence_threshold=0.5  # type: ignore[arg-type]
    )

    result = pipeline.lookup(_IMAGE, _TARGET)

    assert result.status is LookupStatus.UNUSABLE
    assert "confidence" in result.diagnostics[0]
    assert morphology.analyzed == [], "a rejected region must not reach the language stage"
    assert result.context is not None and result.context.selected_ocr is not None


# --- Normal non-success semantics are unchanged -----------------------------


def test_not_found_is_a_language_result_from_either_acquisition() -> None:
    """A dictionary miss stays NOT_FOUND, with the analysis retained."""

    class OnlyUnknown:
        def analyze(self, text: str) -> MorphologyAnalysis:
            return MorphologyAnalysis(
                tokens=(TokenAnalysis(token=text, lemma="없는말", start=0, length=len(text)),),
                candidates=(LexicalCandidate(lemma="없는말", start=0, end=len(text)),),
            )

    language, _m, dictionary = _language(morphology=OnlyUnknown())  # type: ignore[arg-type]
    direct = language.lookup(TextSelection(_SURFACE, 0))

    pipeline, _o, _pm, _pd = _pixel(morphology=OnlyUnknown())  # type: ignore[arg-type]
    from_pixels = pipeline.lookup(_IMAGE, _TARGET)

    for result in (direct, from_pixels):
        assert result.status is LookupStatus.NOT_FOUND
        assert result.entries == ()
        assert result.context is not None
        assert result.context.lemma == "없는말"
        assert result.context.analyses
    assert dictionary.queries == ["없는말"]


@pytest.mark.parametrize("text", ["Hanly 2.0", "12345", "   ", "", "!!!"])
def test_non_korean_selections_are_unusable_without_waking_a_provider(text: str) -> None:
    language, morphology, dictionary = _language()

    result = language.lookup(TextSelection(text))

    assert result.status is LookupStatus.UNUSABLE
    assert morphology.analyzed == []
    assert dictionary.queries == []


def test_a_morphology_provider_with_no_lemma_is_unusable_not_an_error() -> None:
    class Silent:
        def analyze(self, _text: str) -> MorphologyAnalysis:
            return MorphologyAnalysis()

    language, _m, dictionary = _language(morphology=Silent())  # type: ignore[arg-type]

    result = language.lookup(TextSelection(_SURFACE, 0))

    assert result.status is LookupStatus.UNUSABLE
    assert dictionary.queries == []
    assert result.context is not None and result.context.text == _SURFACE


def test_a_sequence_only_morphology_provider_still_works() -> None:
    """The older `Sequence[TokenAnalysis]` contract stays valid."""

    class Older:
        def analyze(self, text: str) -> Sequence[TokenAnalysis]:
            return (TokenAnalysis(token=text, lemma="받다", start=0, length=len(text)),)

    language, _m, dictionary = _language(morphology=Older())  # type: ignore[arg-type]

    result = language.lookup(TextSelection(_SURFACE, 0))

    assert result.status is LookupStatus.SUCCESS
    assert dictionary.queries == ["받다"]


# --- Errors and cancellation ------------------------------------------------


@pytest.mark.parametrize(
    ("failing", "stage"),
    [("morphology", "morphology"), ("dictionary", "dictionary")],
)
def test_a_provider_failure_is_an_error_result_naming_its_stage(
    failing: str, stage: str
) -> None:
    class Exploding:
        def analyze(self, _text: str) -> MorphologyAnalysis:
            raise RuntimeError("boom")

        def lookup(self, _lemma: str) -> tuple[DictionaryEntry, ...]:
            raise RuntimeError("boom")

    kwargs = {failing: Exploding()}
    language, _m, _d = _language(**kwargs)  # type: ignore[arg-type]

    result = language.lookup(TextSelection(_SURFACE, 0))

    assert result.status is LookupStatus.ERROR
    assert result.error is not None
    assert result.diagnostics[0].startswith(f"{stage} failed:")


def test_cancellation_still_aborts_the_language_stage() -> None:
    language, _m, dictionary = _language()

    with pytest.raises(LookupCancelled):
        language.lookup(TextSelection(_SURFACE, 0), cancelled=lambda: True)

    assert dictionary.queries == []


def test_a_non_selection_argument_is_a_type_error() -> None:
    language, _m, _d = _language()

    with pytest.raises(TypeError, match="TextSelection"):
        language.lookup("초대받았어요")  # type: ignore[arg-type]


# --- The engine stays acquisition-neutral -----------------------------------


def test_the_language_stage_needs_no_ocr_provider_at_all() -> None:
    """A native-text client must not have to construct a recognizer."""

    language = LanguagePipeline(_Morphology(), _Dictionary())

    assert language.lookup(TextSelection(_SURFACE, 2)).status is LookupStatus.SUCCESS


def test_the_selection_carries_no_screen_geometry() -> None:
    """Rectangles, windows and element handles stay in the client that owns
    them; an engine that knew about them could not be consumed without one."""

    fields = set(TextSelection.__dataclass_fields__)

    assert fields == {"text", "cursor_index", "source"}


def test_the_source_label_is_inert() -> None:
    """It is diagnostics only; no behaviour may come to depend on it."""

    language, _m, _d = _language()

    results = [
        language.lookup(TextSelection(_SURFACE, 2, source=source))
        for source in (None, "ocr", "accessibility", "anything at all")
    ]

    assert all(result == results[0] for result in results)


def test_evidence_from_a_caller_is_preserved_but_never_interpreted() -> None:
    language, _m, _d = _language()
    evidence = LookupContext(
        ocr_results=(_region(),),
        selected_ocr=_region(),
        word_region=BoundingBox(1, 2, 3, 4),
    )

    result = language.lookup(TextSelection(_SURFACE, 2), evidence=evidence)

    context = result.context
    assert context is not None
    assert context.ocr_results == evidence.ocr_results
    assert context.selected_ocr == evidence.selected_ocr
    assert context.word_region == evidence.word_region
    # And the language fields it does own were filled in.
    assert context.text == _SURFACE and context.lemma == "받다"


def test_stale_language_fields_in_caller_evidence_never_survive_an_early_return() -> None:
    """A result must never carry a lemma that contradicts its own text.

    Handing a previous result's context back as ``evidence`` is a natural thing
    for a non-pixel client to do, so the stage clears the fields it owns.
    """

    language, morphology, _d = _language()
    stale = LookupContext(
        text="stale",
        lemma="stale",
        analyses=(TokenAnalysis(token="stale", lemma="stale"),),
        candidate=LexicalCandidate(lemma="stale", start=0, end=5),
        ocr_results=(_region(),),
        word_region=BoundingBox(1, 2, 3, 4),
    )

    for selection in (TextSelection("Hanly 2.0"), TextSelection("   ")):
        context = language.lookup(selection, evidence=stale).context
        assert context is not None
        assert context.lemma is None
        assert context.candidate is None
        assert context.analyses == ()
        assert context.text != "stale"
        # The pixel evidence the stage does not own is still untouched.
        assert context.word_region == stale.word_region

    assert morphology.analyzed == []


def test_no_desktop_or_platform_module_reaches_the_language_stage() -> None:
    """Walk what the stage actually imports, transitively through ``hanly``.

    A scan of this one file would miss a platform dependency arriving through
    an engine module it imports, which is the way such a dependency would
    realistically appear.
    """

    import ast
    from pathlib import Path

    import hanly.language_pipeline as module

    engine = Path(module.__file__ or "").parent
    forbidden = {
        "hanly_app", "PyQt5", "PyQt6", "webview", "mss", "Quartz", "AppKit",
        "Vision", "objc", "easyocr", "torch", "kiwipiepy", "sqlite3",
    }

    seen: set[str] = set()
    reached: set[str] = set()
    pending = ["language_pipeline"]
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        source = engine / f"{name}.py"
        if not source.exists():
            continue
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                # A relative import names a sibling engine module to follow.
                if node.level:
                    pending.append(node.module or "")
                    continue
                names = [node.module or ""]
            else:
                continue
            reached.update(name.split(".")[0] for name in names)

    assert reached & forbidden == set(), sorted(reached & forbidden)
    # And the closure really was walked, not silently empty.
    assert {"contracts", "errors", "providers"} <= seen


def test_the_result_of_a_direct_selection_is_an_ordinary_lookup_result() -> None:
    language, _m, _d = _language()

    result = language.lookup(TextSelection(_SURFACE, 2))

    assert isinstance(result, LookupResult)
    assert result.status is LookupStatus.SUCCESS
    assert result.entries[0].headword == "받다"
