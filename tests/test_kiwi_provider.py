"""Focused tests for the normalized Kiwi morphology adapter."""

from dataclasses import dataclass

import pytest
from hanly import (
    MorphologyAnalysis,
    MorphologyProvider,
    ProviderError,
    TokenAnalysis,
)
from hanly.kiwi_provider import KiwiProvider

from tests.hanly_fixtures.unchecked import unchecked


@dataclass(frozen=True)
class _FakeToken:
    form: str
    tag: str
    lemma: str
    morphology: str | None = None


class _FakeAnalyzer:
    def __init__(self, tokens: tuple[_FakeToken, ...]) -> None:
        self.tokens = tokens
        self.inputs: list[str] = []

    def tokenize(self, text: str) -> tuple[_FakeToken, ...]:
        self.inputs.append(text)
        return self.tokens


def test_kiwi_provider_normalizes_fake_tokens_without_leaking_them() -> None:
    analyzer = _FakeAnalyzer(
        (
            _FakeToken("책", "NNG", "책", "일반"),
            _FakeToken("을", "JKO", "을", "목적격"),
            _FakeToken("읽습니다", "EF", "읽다"),
        )
    )

    provider = KiwiProvider(analyzer=analyzer)
    analyses = provider.analyze("책을 읽습니다")

    assert isinstance(provider, MorphologyProvider)
    assert tuple(analyses) == (
        TokenAnalysis(token="책", lemma="책", part_of_speech="NNG", morphology="일반"),
        TokenAnalysis(token="을", lemma="을", part_of_speech="JKO", morphology="목적격"),
        TokenAnalysis(token="읽습니다", lemma="읽다", part_of_speech="EF"),
    )
    assert all(isinstance(analysis, TokenAnalysis) for analysis in analyses)
    assert not any(analysis is analyzer.tokens[0] for analysis in analyses)
    assert analyzer.inputs == ["책을 읽습니다"]


def test_kiwi_provider_uses_surface_and_base_form_fallbacks() -> None:
    analyzer = _FakeAnalyzer(())
    provider = KiwiProvider(
        analyzer=lambda text: [{"form": "먹", "tag": "VV", "base_form": "먹다"}]
    )

    analyses = provider.analyze("먹")

    assert tuple(analyses) == (TokenAnalysis(token="먹", lemma="먹다", part_of_speech="VV"),)
    assert analyzer.inputs == []


def test_kiwi_provider_preserves_a_multi_token_conjugation() -> None:
    provider = KiwiProvider(
        analyzer=lambda _text: (
            {"form": "깨뜨리", "tag": "VV", "lemma": "깨뜨리다"},
            {"form": "었", "tag": "EP", "lemma": "었"},
            {"form": "습니다", "tag": "EF", "lemma": "습니다"},
        )
    )

    assert tuple(provider.analyze("깨뜨렸습니다")) == (
        TokenAnalysis("깨뜨리", "깨뜨리다", "VV"),
        TokenAnalysis("었", "었", "EP"),
        TokenAnalysis("습니다", "습니다", "EF"),
    )


def test_kiwi_provider_returns_empty_for_empty_input_without_calling_analyzer() -> None:
    analyzer = _FakeAnalyzer(
        (_FakeToken("절대 호출되면 안 됨", "NNG", "절대 호출되면 안 됨"),)
    )

    assert tuple(KiwiProvider(analyzer=analyzer).analyze("")) == ()
    assert tuple(KiwiProvider(analyzer=analyzer).analyze("   \n\t")) == ()
    assert analyzer.inputs == []


def test_kiwi_provider_prewarm_runs_one_small_analysis_and_reuses_analyzer() -> None:
    analyzer = _FakeAnalyzer((_FakeToken("한", "NNG", "한"),))
    provider = KiwiProvider(analyzer=analyzer)

    provider.prewarm()
    provider.prewarm()
    provider.analyze("한국어")

    assert analyzer.inputs == ["한", "한국어"]


class _FailingAnalyzer:
    def tokenize(self, text: str) -> tuple[object, ...]:
        del text
        raise RuntimeError("kiwi exploded")


def test_kiwi_provider_wraps_analyzer_failures() -> None:
    with pytest.raises(ProviderError, match="Kiwi morphology analysis failed") as caught:
        KiwiProvider(analyzer=_FailingAnalyzer()).analyze("한국어")

    assert isinstance(caught.value.__cause__, RuntimeError)


def test_kiwi_provider_wraps_malformed_tokens() -> None:
    with pytest.raises(ProviderError, match="surface"):
        KiwiProvider(analyzer=lambda text: [{"tag": "NNG"}]).analyze("한국어")


def test_kiwi_provider_rejects_non_string_input() -> None:
    with pytest.raises(TypeError, match="input must be a string"):
        KiwiProvider(analyzer=_FakeAnalyzer(())).analyze(unchecked(None))


def test_kiwi_provider_can_use_installed_kiwi_for_a_cheap_smoke() -> None:
    pytest.importorskip("kiwipiepy")

    analyses = KiwiProvider().analyze("먹었어요")

    assert analyses
    assert analyses[0].token == "먹"
    assert analyses[0].lemma == "먹다"
    assert analyses[0].part_of_speech == "VV"
    assert all(isinstance(analysis, TokenAnalysis) for analysis in analyses)


def _chosen(analysis: MorphologyAnalysis, index: int) -> str:
    candidate = analysis.candidate_at(index)
    assert candidate is not None, index
    return candidate.lemma


@pytest.fixture(scope="module")
def real_kiwi() -> KiwiProvider:
    """One real analyzer for the whole module; constructing Kiwi is expensive."""

    pytest.importorskip("kiwipiepy")
    return KiwiProvider()


_LEXICAL_UNIT_CASES = (
    ("사과했어요", "사과하다"),
    ("사과하다", "사과하다"),
    ("예뻤어요", "예쁘다"),
    ("떨어뜨렸어요", "떨어뜨리다"),
    ("깨뜨렸습니다", "깨뜨리다"),
    ("공부했어요", "공부하다"),
    ("행복했어요", "행복하다"),
    ("깨끗했어요", "깨끗하다"),
    ("먹었어요", "먹다"),
    ("아름다웠어요", "아름답다"),
    ("사과", "사과"),
    ("사과를", "사과"),
    ("예", "예"),
    ("책을", "책"),
)


@pytest.mark.parametrize(("surface", "lemma"), _LEXICAL_UNIT_CASES)
def test_real_kiwi_owns_the_whole_conjugation_at_every_syllable(
    real_kiwi: KiwiProvider, surface: str, lemma: str
) -> None:
    """Every syllable of one predicate must select the same lexical unit."""

    analysis = real_kiwi.analyze(surface)

    assert analysis.candidates, surface
    for index in range(len(surface)):
        chosen = analysis.candidate_at(index)
        assert chosen is not None
        assert chosen.lemma == lemma, f"{surface}[{index}]"


def test_real_kiwi_separates_adjacent_lexical_units_and_skips_punctuation(
    real_kiwi: KiwiProvider,
) -> None:
    provider = real_kiwi

    compound = provider.analyze("책읽는")
    assert [c.lemma for c in compound.candidates] == ["책", "읽다"]
    assert [_chosen(compound, index) for index in range(3)] == ["책", "읽다", "읽다"]

    quoted = provider.analyze("“예뻤어요”")
    assert [c.lemma for c in quoted.candidates] == ["예쁘다"]
    # The pointer resting on a quotation mark still answers with the word it
    # plainly sits beside rather than looking the punctuation up.
    assert _chosen(quoted, 0) == "예쁘다"


def test_real_kiwi_keeps_raw_derivational_morphemes_beside_the_candidate(
    real_kiwi: KiwiProvider,
) -> None:
    analysis = real_kiwi.analyze("사과했어요")

    assert [c.lemma for c in analysis.candidates] == ["사과하다"]
    assert [token.part_of_speech for token in analysis.tokens] == [
        "NNG",
        "XSV",
        "EP",
        "EF",
    ]
    assert [token.token for token in analysis.tokens] == ["사과", "하", "었", "어요"]
