"""Whole-form preference and generic homograph ordering in the language stage.

The rules under test are generic: the dictionary decides whether a joined form
is a word, and homograph order comes from signals the lookup already computed.
No case here encodes a mapping for a particular word.
"""

from __future__ import annotations

import pytest
from hanly import (
    DictionaryEntry,
    DictionarySense,
    LexicalCandidate,
    LookupStatus,
    MorphologyAnalysis,
    TextSelection,
    TokenAnalysis,
)
from hanly.language_pipeline import LanguagePipeline


class _Morphology:
    """Returns a scripted analysis, and records what it was asked."""

    def __init__(self, analysis: MorphologyAnalysis) -> None:
        self._analysis = analysis
        self.analyzed: list[str] = []

    def analyze(self, text: str) -> MorphologyAnalysis:
        self.analyzed.append(text)
        return self._analysis


class _Dictionary:
    def __init__(self, known: dict[str, DictionaryEntry | tuple[DictionaryEntry, ...]]):
        self._known = known
        self.queries: list[str] = []

    def lookup(self, lemma: str) -> tuple[DictionaryEntry, ...]:
        self.queries.append(lemma)
        found = self._known.get(lemma, ())
        return found if isinstance(found, tuple) else (found,)


def _entry(headword: str, gloss: str, **kwargs: object) -> DictionaryEntry:
    return DictionaryEntry(
        headword=headword,
        senses=(DictionarySense(definition=f"{gloss} definition", gloss=gloss),),
        **kwargs,  # type: ignore[arg-type]
    )


#: `초대받았어요`: two units, the way Kiwi really reports it.
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


def test_a_complete_form_the_dictionary_has_becomes_the_primary_result() -> None:
    dictionary = _Dictionary({"초대받다": _entry("초대받다", "be invited")})
    language = LanguagePipeline(_Morphology(_SPLIT), dictionary)

    result = language.lookup(TextSelection(_SURFACE, 0))

    assert result.status is LookupStatus.SUCCESS
    assert result.entries[0].headword == "초대받다"
    # The exact surface first, then the reconstructed form, then the components
    # the panel explains.
    assert dictionary.queries == ["초대받았어요", "초대받다", "초대", "받다"]


@pytest.mark.parametrize("cursor_index", range(len(_SURFACE)))
def test_a_complete_form_stays_stable_at_every_position_inside_it(
    cursor_index: int,
) -> None:
    """Moving inside one resolved form must not swap the answer for a part."""

    dictionary = _Dictionary({"초대받다": _entry("초대받다", "be invited")})
    language = LanguagePipeline(_Morphology(_SPLIT), dictionary)

    result = language.lookup(TextSelection(_SURFACE, cursor_index))

    assert result.entries[0].headword == "초대받다"
    assert result.context is not None
    candidate = result.context.candidate
    assert candidate is not None and candidate.lemma == "초대받다"
    # It spans the whole surface, which is what makes it stable.
    assert (candidate.start, candidate.end) == (0, len(_SURFACE))


@pytest.mark.parametrize(
    ("cursor_index", "lemma"), [(0, "초대"), (1, "초대"), (2, "받다"), (5, "받다")]
)
def test_without_a_complete_form_the_cursor_component_is_the_answer(
    cursor_index: int, lemma: str
) -> None:
    """KRDICT genuinely has no `초대받다`; the approved fallback governs."""

    dictionary = _Dictionary(
        {"초대": _entry("초대", "invitation"), "받다": _entry("받다", "receive")}
    )
    language = LanguagePipeline(_Morphology(_SPLIT), dictionary)

    result = language.lookup(TextSelection(_SURFACE, cursor_index))

    assert result.status is LookupStatus.SUCCESS
    assert result.entries[0].headword == lemma
    # Bounded and ordered: exact surface, whole form, then the component the
    # cursor is on before the rest.
    assert dictionary.queries[:3] == ["초대받았어요", "초대받다", lemma]
    assert len(dictionary.queries) <= 5


def test_a_simple_word_probes_no_complete_form() -> None:
    analysis = MorphologyAnalysis(
        tokens=(
            TokenAnalysis(
                token="학교", lemma="학교", part_of_speech="NNG", start=0, length=2
            ),
        ),
        candidates=(LexicalCandidate(lemma="학교", start=0, end=2, part_of_speech="NNG"),),
    )
    dictionary = _Dictionary({"학교": _entry("학교", "school")})
    language = LanguagePipeline(_Morphology(analysis), dictionary)

    result = language.lookup(TextSelection("학교", 0))

    assert result.entries[0].headword == "학교"
    assert dictionary.queries == ["학교"]


def test_words_separated_by_whitespace_are_never_joined() -> None:
    """Two ordinary words in one selection must keep selecting independently."""

    analysis = MorphologyAnalysis(
        tokens=(),
        candidates=(
            LexicalCandidate(lemma="책", start=0, end=2, part_of_speech="NNG"),
            LexicalCandidate(lemma="읽다", start=3, end=5, part_of_speech="VV"),
        ),
    )
    dictionary = _Dictionary({"책": _entry("책", "book"), "읽다": _entry("읽다", "read")})
    language = LanguagePipeline(_Morphology(analysis), dictionary)

    assert language.lookup(TextSelection("책을 읽는", 0)).entries[0].headword == "책"
    assert language.lookup(TextSelection("책을 읽는", 4)).entries[0].headword == "읽다"
    assert "책을 읽다" not in dictionary.queries


def test_homographs_are_ordered_by_the_dictionarys_own_grading() -> None:
    """Provider order is insertion order; the common reading must come first."""

    rare = _entry("초대", "first", vocabulary_level="고급", part_of_speech="명사")
    common = _entry("초대", "invitation", vocabulary_level="초급", part_of_speech="명사")
    analysis = MorphologyAnalysis(
        candidates=(LexicalCandidate(lemma="초대", start=0, end=2, part_of_speech="NNG"),)
    )
    language = LanguagePipeline(_Morphology(analysis), _Dictionary({"초대": (rare, common)}))

    result = language.lookup(TextSelection("초대", 0))

    assert [entry.senses[0].gloss for entry in result.entries] == ["invitation", "first"]


def test_a_matching_part_of_speech_outranks_the_grading() -> None:
    """The morphology says which class the reader is pointing at."""

    noun = _entry("차", "tea", vocabulary_level="초급", part_of_speech="명사")
    verb = _entry("차", "kick", vocabulary_level="중급", part_of_speech="동사")
    analysis = MorphologyAnalysis(
        candidates=(LexicalCandidate(lemma="차", start=0, end=1, part_of_speech="VV"),)
    )
    language = LanguagePipeline(_Morphology(analysis), _Dictionary({"차": (noun, verb)}))

    result = language.lookup(TextSelection("차", 0))

    assert [entry.senses[0].gloss for entry in result.entries] == ["kick", "tea"]


def test_ordering_is_stable_when_no_signal_separates_two_entries() -> None:
    first = _entry("말", "speech", vocabulary_level="초급", part_of_speech="명사")
    second = _entry("말", "horse", vocabulary_level="초급", part_of_speech="명사")
    analysis = MorphologyAnalysis(
        candidates=(LexicalCandidate(lemma="말", start=0, end=1, part_of_speech="NNG"),)
    )
    language = LanguagePipeline(_Morphology(analysis), _Dictionary({"말": (first, second)}))

    result = language.lookup(TextSelection("말", 0))

    assert [entry.senses[0].gloss for entry in result.entries] == ["speech", "horse"]


def test_a_missing_complete_form_and_missing_component_is_still_not_found() -> None:
    dictionary = _Dictionary({})
    language = LanguagePipeline(_Morphology(_SPLIT), dictionary)

    result = language.lookup(TextSelection(_SURFACE, 0))

    assert result.status is LookupStatus.NOT_FOUND
    assert result.entries == ()
    assert dictionary.queries == ["초대받았어요", "초대받다", "초대", "받다"]


def test_a_dictionary_failure_during_the_probe_is_an_error_result() -> None:
    class _Failing:
        def lookup(self, lemma: str) -> tuple[DictionaryEntry, ...]:
            raise RuntimeError("database gone")

    language = LanguagePipeline(_Morphology(_SPLIT), _Failing())

    result = language.lookup(TextSelection(_SURFACE, 0))

    assert result.status is LookupStatus.ERROR
    assert result.error is not None
    assert "dictionary" in result.diagnostics[0]


def test_a_join_that_would_drop_surface_characters_is_refused() -> None:
    """`고소득층` splits into `고` + `소득`, whose span swallowed the suffix `층`.

    Substituting the bare lemma would ask for `고소득`, a different word the
    dictionary also holds, and answer it while pointing at `고소득층`.
    """

    analysis = MorphologyAnalysis(
        candidates=(
            LexicalCandidate(lemma="고", start=0, end=1, part_of_speech="XPN"),
            LexicalCandidate(lemma="소득", start=1, end=4, part_of_speech="NNG"),
        )
    )
    dictionary = _Dictionary({"고소득": _entry("고소득", "high income")})
    language = LanguagePipeline(_Morphology(analysis), dictionary)

    result = language.lookup(TextSelection("고소득층", 0))

    assert "고소득" not in dictionary.queries
    assert result.status is LookupStatus.NOT_FOUND


def test_an_inflected_predicate_may_still_replace_its_surface() -> None:
    """The same span test must not block the case the rule exists for."""

    dictionary = _Dictionary({"초대받다": _entry("초대받다", "be invited")})
    language = LanguagePipeline(_Morphology(_SPLIT), dictionary)

    assert language.lookup(TextSelection(_SURFACE, 0)).entries[0].headword == "초대받다"


# --- a surface without its trailing particles --------------------------------

#: `손님이`: Kiwi splits off the suffix 님 and keeps 손 as the unit's lemma.
_PARTICLED = MorphologyAnalysis(
    tokens=(
        TokenAnalysis(token="손", lemma="손", part_of_speech="NNG", start=0, length=1),
        TokenAnalysis(token="님", lemma="님", part_of_speech="XSN", start=1, length=1),
        TokenAnalysis(token="이", lemma="이", part_of_speech="JKS", start=2, length=1),
    ),
    candidates=(LexicalCandidate(lemma="손", start=0, end=3, part_of_speech="NNG"),),
)


@pytest.mark.parametrize("cursor_index", range(3))
def test_a_word_is_found_without_its_particles_before_its_parts(cursor_index: int) -> None:
    dictionary = _Dictionary({"손님": _entry("손님", "guest"), "손": _entry("손", "hand")})
    language = LanguagePipeline(_Morphology(_PARTICLED), dictionary)

    result = language.lookup(TextSelection("손님이", cursor_index))

    assert result.entries[0].headword == "손님"
    assert dictionary.queries == ["손님이", "손님"]
    assert result.context is not None
    # The split's 손 ("hand") would explain a different word, so no lexical part is shown.
    assert [c.lemma for c in result.context.components if not c.grammatical] == []


def test_the_exact_surface_still_wins_over_the_particle_stripped_form() -> None:
    dictionary = _Dictionary(
        {"손님이": _entry("손님이", "listed"), "손님": _entry("손님", "guest")}
    )
    language = LanguagePipeline(_Morphology(_PARTICLED), dictionary)

    assert language.lookup(TextSelection("손님이", 0)).entries[0].headword == "손님이"
    assert dictionary.queries == ["손님이"]


def test_an_unlisted_stripped_form_falls_through_to_the_unit() -> None:
    dictionary = _Dictionary({"손": _entry("손", "hand")})
    language = LanguagePipeline(_Morphology(_PARTICLED), dictionary)

    assert language.lookup(TextSelection("손님이", 0)).entries[0].headword == "손"
    assert dictionary.queries[:3] == ["손님이", "손님", "손"]


def test_endings_are_never_stripped_from_a_predicate() -> None:
    dictionary = _Dictionary({"받다": _entry("받다", "receive")})
    LanguagePipeline(_Morphology(_SPLIT), dictionary).lookup(TextSelection(_SURFACE, 3))

    # 었/어요 are endings, not particles: nothing short of the surface is asked.
    assert not any(
        _SURFACE.startswith(query) and query != _SURFACE for query in dictionary.queries[:1]
    )
    assert "초대받았" not in dictionary.queries and "초대받" not in dictionary.queries


def test_a_particle_after_a_second_word_is_not_stripped_across_the_space() -> None:
    analysis = MorphologyAnalysis(
        tokens=(
            TokenAnalysis(token="책", lemma="책", part_of_speech="NNG", start=0, length=1),
            TokenAnalysis(token="학교", lemma="학교", part_of_speech="NNG", start=2, length=2),
            TokenAnalysis(token="에", lemma="에", part_of_speech="JKB", start=4, length=1),
        ),
        candidates=(
            LexicalCandidate(lemma="책", start=0, end=1, part_of_speech="NNG"),
            LexicalCandidate(lemma="학교", start=2, end=5, part_of_speech="NNG"),
        ),
    )
    dictionary = _Dictionary({"책": _entry("책", "book"), "학교": _entry("학교", "school")})
    LanguagePipeline(_Morphology(analysis), dictionary).lookup(TextSelection("책 학교에", 0))

    assert "책 학교" not in dictionary.queries


def test_overlapping_units_are_never_joined_into_a_whole_form() -> None:
    """`누군가는`: 누구 spans 누군, 이다 starts inside it; 누+이다 is a different word."""

    analysis = MorphologyAnalysis(
        tokens=(
            TokenAnalysis(token="누구", lemma="누구", part_of_speech="NP", start=0, length=2),
            TokenAnalysis(token="이", lemma="이다", part_of_speech="VCP", start=1, length=1),
            TokenAnalysis(token="ᆫ가", lemma="ᆫ가", part_of_speech="EF", start=1, length=2),
            TokenAnalysis(token="는", lemma="는", part_of_speech="JX", start=3, length=1),
        ),
        candidates=(
            LexicalCandidate(lemma="누구", start=0, end=2, part_of_speech="NP"),
            LexicalCandidate(lemma="이다", start=1, end=4, part_of_speech="VCP"),
        ),
    )
    dictionary = _Dictionary(
        {"누이다": _entry("누이다", "lay down"), "누구": _entry("누구", "who")}
    )

    result = LanguagePipeline(_Morphology(analysis), dictionary).lookup(
        TextSelection("누군가는", 0)
    )

    assert result.entries[0].headword == "누구"
    assert "누이다" not in dictionary.queries
