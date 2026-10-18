"""Real Kiwi context and construction analysis, with a bounded dictionary fixture."""

from __future__ import annotations

import pytest
from hanly import DictionaryEntry, LanguagePipeline, LookupStatus, TextSelection

from tests.hanly_fixtures.capabilities import require_modules

pytestmark = pytest.mark.native


@pytest.fixture(autouse=True)
def require_kiwi() -> None:
    require_modules("kiwipiepy")


class _Listed:
    """A dictionary holding exactly the given headwords, each with its senses."""

    def __init__(self, senses: dict[str, tuple[str, ...]]) -> None:
        self.senses = senses
        self.queries: list[str] = []

    def lookup(self, lemma: str) -> tuple[DictionaryEntry, ...]:
        self.queries.append(lemma)
        return tuple(
            DictionaryEntry(headword=lemma, definitions=(f"{lemma} {pos}",), part_of_speech=pos)
            for pos in self.senses.get(lemma, ())
        )


def _kiwi_language(senses: dict[str, tuple[str, ...]]) -> LanguagePipeline:
    from hanly.kiwi_provider import KiwiProvider

    return LanguagePipeline(KiwiProvider(), _Listed(senses))


def test_a_pointer_on_the_copula_answers_for_its_noun() -> None:
    language = _kiwi_language({"학생": ("명사",), "이다": ("조사",)})

    for cursor in range(len("학생입니다")):
        result = language.lookup(TextSelection(text="학생입니다", cursor_index=cursor))
        assert result.entries[0].headword == "학생", cursor


def test_a_neighbouring_word_decides_an_ambiguous_analysis() -> None:
    language = _kiwi_language({"나": ("대명사",), "나다": ("동사",)})

    before_verb = language.lookup(
        TextSelection(text="나는", cursor_index=0, context_after="가요")
    )

    assert before_verb.entries[0].headword == "나"
    assert before_verb.context is not None and before_verb.context.text == "나는"


def test_a_noun_spelled_like_an_inflection_does_not_replace_the_verb() -> None:
    language = _kiwi_language({"먹지": ("명사",), "먹다": ("동사",)})

    result = language.lookup(TextSelection(text="먹지", cursor_index=0, context_after="않아요"))

    assert result.entries[0].headword == "먹다"


def test_a_listed_construction_is_named_from_either_word() -> None:
    language = _kiwi_language({
        "먹다": ("동사",), "있다": ("형용사", "보조 동사"), "-고 있다": ("품사 없음",),
    })

    stem = language.lookup(TextSelection(text="먹고", cursor_index=0, context_after="있어요"))
    auxiliary = language.lookup(
        TextSelection(text="있어요", cursor_index=0, context_before="먹고")
    )

    for result in (stem, auxiliary):
        assert result.context is not None and result.context.construction is not None
        assert result.context.construction.headword == "-고 있다"
    assert stem.entries[0].headword == "먹다"
    assert auxiliary.entries[0].part_of_speech == "보조 동사"


def test_a_construction_is_never_invented_without_its_dictionary_entry() -> None:
    language = _kiwi_language({"먹다": ("동사",), "가다": ("동사",)})

    result = language.lookup(TextSelection(text="먹고", cursor_index=0, context_after="가요"))

    assert result.status is LookupStatus.SUCCESS
    assert result.context is not None and result.context.construction is None


def test_constructions_share_the_existing_dictionary_query_budget() -> None:
    from hanly.kiwi_provider import KiwiProvider

    dictionary = _Listed({})
    language = LanguagePipeline(KiwiProvider(), dictionary)

    result = language.lookup(TextSelection("컴퓨터공학공부하고", context_after="있어요"))

    assert result.status is not LookupStatus.ERROR
    assert 0 < len(dictionary.queries) <= 5


def test_a_construction_entirely_inside_a_neighbour_does_not_describe_the_target() -> None:
    language = _kiwi_language({
        "학교": ("명사",), "-ㄹ 수 있다": ("품사 없음",),
    })

    result = language.lookup(TextSelection("학교", context_before="할수있다"))

    assert result.status is LookupStatus.SUCCESS
    assert result.context is not None and result.context.construction is None
