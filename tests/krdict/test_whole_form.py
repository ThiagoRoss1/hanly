"""Whole-form and homograph regressions against the real Kiwi and KRDICT.

These are the surfaces the reported defect and the approved product direction
name. They run only where the locally generated production database exists.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from hanly import LookupStatus, TextSelection
from hanly.kiwi_provider import KiwiProvider
from hanly.krdict_provider import KRDICTProvider
from hanly.language_pipeline import LanguagePipeline

DATABASE = Path(__file__).parents[2] / "data" / "generated" / "krdict.sqlite3"


def _database() -> Path:
    if DATABASE.is_file():
        return DATABASE
    if os.environ.get("HANLY_REQUIRE_REAL_KRDICT") == "1":
        pytest.fail(f"required production KRDICT database is missing: {DATABASE}")
    pytest.skip("production KRDICT database is a local generated artifact")


@pytest.fixture
def language() -> object:
    pytest.importorskip("kiwipiepy")
    dictionary = KRDICTProvider(_database())
    try:
        yield LanguagePipeline(KiwiProvider(), dictionary)
    finally:
        dictionary.close()


def _primary(language: LanguagePipeline, surface: str, index: int) -> tuple[str, str | None]:
    result = language.lookup(TextSelection(surface, index))
    assert result.status is LookupStatus.SUCCESS, result.diagnostics
    entry = result.entries[0]
    return entry.headword, entry.senses[0].gloss


@pytest.mark.parametrize("index", [0, 1])
def test_초대_resolves_to_invitation_not_the_first_generation_homograph(
    language: LanguagePipeline, index: int
) -> None:
    """The reported defect: `初代` was promoted over `招待` by row order alone."""

    headword, gloss = _primary(language, "초대받았어요", index)
    assert (headword, gloss) == ("초대", "invitation")


@pytest.mark.parametrize("index", [2, 3, 4, 5])
def test_받다_remains_the_answer_on_the_verbal_component(
    language: LanguagePipeline, index: int
) -> None:
    headword, gloss = _primary(language, "초대받았어요", index)
    assert headword == "받다"
    assert gloss is not None and gloss.startswith("receive")


def test_초대받다_is_genuinely_absent_so_the_component_fallback_governs(
    language: LanguagePipeline,
) -> None:
    """Guards the evidence this bundle rests on rather than assuming it."""

    dictionary = KRDICTProvider(_database())
    try:
        assert dictionary.lookup("초대받다") == ()
    finally:
        dictionary.close()


@pytest.mark.parametrize("index", range(6))
def test_a_real_complete_form_stays_stable_across_its_components(
    language: LanguagePipeline, index: int
) -> None:
    """`인정받다` is lexicalized and in KRDICT, so every position answers it."""

    headword, _gloss = _primary(language, "인정받았어요", index)
    assert headword == "인정받다"


@pytest.mark.parametrize(
    ("surface", "headword"),
    [
        ("가공식품", "가공식품"),
        ("가까워지다", "가까워지다"),
        ("가로놓이다", "가로놓이다"),
    ],
)
def test_a_split_compound_the_dictionary_holds_is_answered_whole(
    language: LanguagePipeline, surface: str, headword: str
) -> None:
    """Kiwi splits these; the joined form is a real entry and must win."""

    assert _primary(language, surface, 0)[0] == headword


@pytest.mark.parametrize(
    ("surface", "headword", "gloss"),
    [
        ("사과했어요", "사과하다", "apologize"),
        ("예뻤어요", "예쁘다", "pretty; beautiful; comely"),
        ("떨어뜨렸어요", "떨어뜨리다", "drop"),
        ("깨뜨렸습니다", "깨뜨리다", "break; smash"),
        ("학교", "학교", "school"),
    ],
)
def test_previously_correct_surfaces_do_not_regress(
    language: LanguagePipeline, surface: str, headword: str, gloss: str
) -> None:
    assert _primary(language, surface, 0) == (headword, gloss)


@pytest.mark.parametrize(
    ("index", "headword"), [(0, "책"), (1, "책"), (3, "읽다"), (4, "읽다")]
)
def test_two_space_separated_words_still_select_independently(
    language: LanguagePipeline, index: int, headword: str
) -> None:
    assert _primary(language, "책을 읽는", index)[0] == headword


def test_a_surface_with_no_entry_is_not_found_not_an_error(
    language: LanguagePipeline,
) -> None:
    result = language.lookup(TextSelection("쀍쀍쀍", 0))
    assert result.status in {LookupStatus.NOT_FOUND, LookupStatus.UNUSABLE}
    assert result.error is None
