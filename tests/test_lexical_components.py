"""The component decomposition carried with a lookup outcome.

Components explain how a surface is built. They are produced by the one shared
language stage, so both acquisitions describe a word the same way.
"""

from __future__ import annotations

import pickle

import pytest
from hanly import (
    DictionaryEntry,
    DictionarySense,
    LexicalCandidate,
    LexicalComponent,
    LookupContext,
    MorphologyAnalysis,
    TextSelection,
    TokenAnalysis,
)
from hanly.language_pipeline import LanguagePipeline


class _Morphology:
    def __init__(self, analysis: MorphologyAnalysis) -> None:
        self._analysis = analysis

    def analyze(self, text: str) -> MorphologyAnalysis:
        del text
        return self._analysis


class _Dictionary:
    def __init__(self, known: dict[str, str]) -> None:
        self._known = known
        self.queries: list[str] = []

    def lookup(self, lemma: str) -> tuple[DictionaryEntry, ...]:
        self.queries.append(lemma)
        gloss = self._known.get(lemma)
        if gloss is None:
            return ()
        return (
            DictionaryEntry(
                headword=lemma,
                senses=(DictionarySense(definition=f"{gloss} definition", gloss=gloss),),
            ),
        )


#: `초대받았어요`, exactly as Kiwi reports it.
_SPLIT = MorphologyAnalysis(
    tokens=(
        TokenAnalysis(token="초대", lemma="초대", part_of_speech="NNG", start=0, length=2),
        TokenAnalysis(token="받", lemma="받다", part_of_speech="VV-R", start=2, length=1),
        TokenAnalysis(token="었", lemma="었", part_of_speech="EP", start=3, length=1),
        TokenAnalysis(token="어요", lemma="어요", part_of_speech="EF", start=4, length=2),
    ),
    candidates=(
        LexicalCandidate(lemma="초대", start=0, end=2, part_of_speech="NNG"),
        LexicalCandidate(lemma="받다", start=2, end=6, part_of_speech="VV"),
    ),
)
_SURFACE = "초대받았어요"
_KNOWN = {"초대": "invitation", "받다": "receive"}


# --- the contract itself ----------------------------------------------------


def test_the_component_is_exported_and_constructible() -> None:
    import hanly

    assert "LexicalComponent" in hanly.__all__
    component = hanly.LexicalComponent(lemma="초대", start=0, end=2)
    assert (component.gloss, component.part_of_speech, component.grammatical) == (
        None,
        None,
        False,
    )


def test_a_context_without_components_is_still_constructible() -> None:
    """The field is additive, so every existing caller keeps working."""

    assert LookupContext(text="책").components == ()


@pytest.mark.parametrize(
    ("start", "end"), [(-1, 2), (2, 2), (3, 1), (0, 0)]
)
def test_a_component_rejects_a_span_that_cannot_index_text(start: int, end: int) -> None:
    with pytest.raises(ValueError):
        LexicalComponent(lemma="x", start=start, end=end)


def test_a_component_requires_a_lemma_and_typed_fields() -> None:
    with pytest.raises(ValueError):
        LexicalComponent(lemma="", start=0, end=1)
    with pytest.raises(TypeError):
        LexicalComponent(lemma="x", start=0, end=1, gloss=3)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        LexicalComponent(lemma="x", start=True, end=2)


def test_components_survive_the_worker_transport() -> None:
    """The result is pickled between processes, so the field must travel."""

    language = LanguagePipeline(_Morphology(_SPLIT), _Dictionary(_KNOWN))
    result = language.lookup(TextSelection(_SURFACE, 0))

    restored = pickle.loads(pickle.dumps(result))

    assert restored.context is not None and result.context is not None
    assert restored.context.components == result.context.components
    assert restored.context.components[0].gloss == "invitation"


# --- what the decomposition says --------------------------------------------


def _components(cursor_index: int = 0, known: dict[str, str] | None = None):
    dictionary = _Dictionary(_KNOWN if known is None else known)
    language = LanguagePipeline(_Morphology(_SPLIT), dictionary)
    result = language.lookup(TextSelection(_SURFACE, cursor_index))
    assert result.context is not None
    return result, result.context.components, dictionary


def test_every_component_indexes_the_text_and_is_ordered_by_start() -> None:
    result, components, _d = _components()

    text = result.context.text or ""
    assert len(components) == 4
    for component in components:
        assert 0 <= component.start < component.end <= len(text)
    assert [c.start for c in components] == sorted(c.start for c in components)


def test_lexical_and_grammatical_components_are_distinguished() -> None:
    _result, components, _d = _components()

    lexical = [c for c in components if not c.grammatical]
    grammatical = [c for c in components if c.grammatical]
    assert [c.lemma for c in lexical] == ["초대", "받다"]
    assert [c.lemma for c in grammatical] == ["었", "어요"]
    assert all(c.gloss for c in grammatical)


@pytest.mark.parametrize(
    ("cursor_index", "headword"), [(0, "초대"), (1, "초대"), (2, "받다"), (5, "받다")]
)
def test_the_primary_stays_cursor_sensitive_while_the_panel_stays_whole(
    cursor_index: int, headword: str
) -> None:
    """KRDICT has no `초대받다`, so the component the cursor is on answers, and
    the decomposition is retained as context either way."""

    result, components, _d = _components(cursor_index)

    assert result.entries[0].headword == headword
    assert [c.lemma for c in components] == ["초대", "받다", "었", "어요"]


def test_the_cursor_component_is_glossed_first_when_the_budget_is_tight() -> None:
    _result, _components_, dictionary = _components(cursor_index=2)

    lexical = [q for q in dictionary.queries if q in {"초대", "받다"}]
    assert lexical[0] == "받다"


def test_a_component_the_dictionary_lacks_reports_no_gloss() -> None:
    _result, components, _d = _components(known={"초대": "invitation"})

    missing = next(c for c in components if c.lemma == "받다")
    assert missing.gloss is None
    assert missing.grammatical is False


def test_a_simple_word_carries_no_components() -> None:
    analysis = MorphologyAnalysis(
        tokens=(
            TokenAnalysis(
                token="학교", lemma="학교", part_of_speech="NNG", start=0, length=2
            ),
        ),
        candidates=(LexicalCandidate(lemma="학교", start=0, end=2, part_of_speech="NNG"),),
    )
    language = LanguagePipeline(_Morphology(analysis), _Dictionary({"학교": "school"}))

    result = language.lookup(TextSelection("학교", 0))

    assert result.context is not None
    assert result.context.components == ()


def test_overlapping_spans_are_preserved_and_ordered() -> None:
    """`예뻤어요` fuses its stem and its past marker into the same syllable."""

    analysis = MorphologyAnalysis(
        tokens=(
            TokenAnalysis(token="예쁘", lemma="예쁘다", part_of_speech="VA", start=0, length=2),
            TokenAnalysis(token="었", lemma="었", part_of_speech="EP", start=1, length=1),
            TokenAnalysis(token="어요", lemma="어요", part_of_speech="EF", start=2, length=2),
        ),
        candidates=(LexicalCandidate(lemma="예쁘다", start=0, end=4, part_of_speech="VA"),),
    )
    language = LanguagePipeline(_Morphology(analysis), _Dictionary({"예쁘다": "pretty"}))

    result = language.lookup(TextSelection("예뻤어요", 0))

    assert result.context is not None
    components = result.context.components
    assert [(c.lemma, c.start, c.end) for c in components] == [
        ("예쁘다", 0, 4),
        ("었", 1, 2),
        ("어요", 2, 4),
    ]
    # The lexical component spans the grammatical one; both are real.
    lexical = components[0]
    assert not lexical.grammatical and components[1].grammatical
    assert lexical.start <= components[1].start < lexical.end


def test_a_surface_the_dictionary_lists_whole_keeps_no_misleading_split() -> None:
    """`고소득층` is one word; naming its first syllable would explain it wrongly."""

    analysis = MorphologyAnalysis(
        tokens=(
            TokenAnalysis(token="고", lemma="고", part_of_speech="XPN", start=0, length=1),
            TokenAnalysis(token="소득", lemma="소득", part_of_speech="NNG", start=1, length=2),
            TokenAnalysis(token="층", lemma="층", part_of_speech="XSN", start=3, length=1),
        ),
        candidates=(
            LexicalCandidate(lemma="고", start=0, end=1, part_of_speech="XPN"),
            LexicalCandidate(lemma="소득", start=1, end=4, part_of_speech="NNG"),
        ),
    )
    dictionary = _Dictionary(
        {"고소득층": "high-income bracket", "고": "the late", "소득": "income"}
    )
    language = LanguagePipeline(_Morphology(analysis), dictionary)

    result = language.lookup(TextSelection("고소득층", 0))

    assert result.entries[0].headword == "고소득층"
    assert result.context is not None
    assert [c.lemma for c in result.context.components if not c.grammatical] == []
    # The parts are asked about in order to judge them, and then not shown.
    assert len(dictionary.queries) <= 5


# --- the dictionary budget --------------------------------------------------


def test_the_exact_surface_is_probed_before_anything_is_reconstructed() -> None:
    dictionary = _Dictionary({_SURFACE: "a real entry"})
    language = LanguagePipeline(_Morphology(_SPLIT), dictionary)

    result = language.lookup(TextSelection(_SURFACE, 0))

    assert result.entries[0].headword == _SURFACE
    assert dictionary.queries[0] == _SURFACE
    assert len(dictionary.queries) <= 5


def test_a_repeated_lemma_is_asked_for_only_once() -> None:
    analysis = MorphologyAnalysis(
        tokens=(
            TokenAnalysis(token="꿀", lemma="꿀", part_of_speech="NNG", start=0, length=1),
            TokenAnalysis(token="꿀", lemma="꿀", part_of_speech="NNG", start=1, length=1),
        ),
        candidates=(
            LexicalCandidate(lemma="꿀", start=0, end=1, part_of_speech="NNG"),
            LexicalCandidate(lemma="꿀", start=1, end=2, part_of_speech="NNG"),
        ),
    )
    dictionary = _Dictionary({"꿀": "honey"})
    language = LanguagePipeline(_Morphology(analysis), dictionary)

    language.lookup(TextSelection("꿀꿀", 0))

    assert dictionary.queries.count("꿀") == 1


def test_no_lookup_exceeds_five_dictionary_queries() -> None:
    """A surface with many parts must not multiply into many queries."""

    candidates = tuple(
        LexicalCandidate(lemma=f"단어{index}", start=index, end=index + 1, part_of_speech="NNG")
        for index in range(8)
    )
    tokens = tuple(
        TokenAnalysis(
            token=f"단어{index}", lemma=f"단어{index}", part_of_speech="NNG",
            start=index, length=1,
        )
        for index in range(8)
    )
    dictionary = _Dictionary({})
    language = LanguagePipeline(
        _Morphology(MorphologyAnalysis(tokens=tokens, candidates=candidates)), dictionary
    )

    language.lookup(TextSelection("가나다라마바사아", 0))

    assert len(dictionary.queries) <= 5
    assert len(set(dictionary.queries)) == len(dictionary.queries)


# --- a decomposition has to explain the characters it covers -----------------


def _split(parts: list[tuple[str, int, int, str]], text: str) -> MorphologyAnalysis:
    """An analysis whose candidates are (lemma, start, end, pos)."""

    return MorphologyAnalysis(
        tokens=tuple(
            TokenAnalysis(
                token=text[start:end], lemma=lemma, part_of_speech=pos,
                start=start, length=end - start,
            )
            for lemma, start, end, pos in parts
        ),
        candidates=tuple(
            LexicalCandidate(lemma=lemma, start=start, end=end, part_of_speech=pos)
            for lemma, start, end, pos in parts
        ),
    )


def test_a_listed_word_keeps_parts_that_read_as_themselves() -> None:
    """`두통거리` is `두통` and `거리`, which is worth knowing."""

    text = "두통거리"
    analysis = _split([("두통", 0, 2, "NNG"), ("거리", 2, 4, "NNG")], text)
    dictionary = _Dictionary(
        {"두통거리": "a source of headaches", "두통": "headache", "거리": "material"}
    )
    language = LanguagePipeline(_Morphology(analysis), dictionary)

    result = language.lookup(TextSelection(text, 0))

    assert result.entries[0].headword == text
    assert [c.lemma for c in result.context.components] == ["두통", "거리"]  # type: ignore[union-attr]


def test_a_listed_word_drops_a_part_that_names_a_different_word() -> None:
    """`여행가` is not `여행` and `가다`; the span reads `가`, not `가다`."""

    text = "여행가"
    analysis = _split([("여행", 0, 2, "NNG"), ("가다", 2, 3, "VV")], text)
    dictionary = _Dictionary({"여행가": "traveller", "여행": "travel", "가다": "go"})
    language = LanguagePipeline(_Morphology(analysis), dictionary)

    result = language.lookup(TextSelection(text, 0))

    assert result.entries[0].headword == text
    assert [c for c in result.context.components if not c.grammatical] == []  # type: ignore[union-attr]


def test_a_listed_word_drops_a_part_whose_span_swallowed_a_suffix() -> None:
    """`고소득층` is one word; its span reads `소득층`, not `소득`."""

    text = "고소득층"
    analysis = _split([("고", 0, 1, "XPN"), ("소득", 1, 4, "NNG")], text)
    dictionary = _Dictionary(
        {"고소득층": "high-income bracket", "고": "the late", "소득": "income"}
    )
    language = LanguagePipeline(_Morphology(analysis), dictionary)

    result = language.lookup(TextSelection(text, 0))

    assert result.entries[0].headword == text
    assert [c for c in result.context.components if not c.grammatical] == []  # type: ignore[union-attr]


def test_a_listed_word_drops_a_part_the_dictionary_does_not_hold() -> None:
    """A part with no entry explains nothing, however well its span reads."""

    text = "맏사위"
    analysis = _split([("맏", 0, 1, "XPN"), ("사위", 1, 3, "NNG")], text)
    dictionary = _Dictionary({"맏사위": "oldest son-in-law", "사위": "son-in-law"})
    language = LanguagePipeline(_Morphology(analysis), dictionary)

    result = language.lookup(TextSelection(text, 0))

    assert [c for c in result.context.components if not c.grammatical] == []  # type: ignore[union-attr]


def test_a_surface_the_dictionary_lacks_still_decomposes() -> None:
    """`초대받았어요` has no entry of its own, so its parts are the answer."""

    dictionary = _Dictionary(_KNOWN)
    language = LanguagePipeline(_Morphology(_SPLIT), dictionary)

    result = language.lookup(TextSelection(_SURFACE, 0))

    assert [c.lemma for c in result.context.components] == [  # type: ignore[union-attr]
        "초대",
        "받다",
        "었",
        "어요",
    ]


def test_cursor_movement_inside_a_listed_word_keeps_the_same_entry() -> None:
    text = "두통거리"
    analysis = _split([("두통", 0, 2, "NNG"), ("거리", 2, 4, "NNG")], text)
    dictionary = _Dictionary(
        {"두통거리": "a source of headaches", "두통": "headache", "거리": "material"}
    )
    language = LanguagePipeline(_Morphology(analysis), dictionary)

    headwords = {
        language.lookup(TextSelection(text, index)).entries[0].headword
        for index in range(len(text))
    }

    assert headwords == {text}


def test_an_exhausted_budget_shows_only_the_complete_form() -> None:
    """An unglossed part cannot be shown to explain anything."""

    text = "가나다라마바"
    parts = [(text[i], i, i + 1, "NNG") for i in range(len(text))]
    analysis = _split(parts, text)
    dictionary = _Dictionary({text: "a listed word"})
    language = LanguagePipeline(_Morphology(analysis), dictionary)

    result = language.lookup(TextSelection(text, 0))

    assert result.entries[0].headword == text
    assert [c for c in result.context.components if not c.grammatical] == []  # type: ignore[union-attr]
    assert len(dictionary.queries) <= 5
