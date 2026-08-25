"""Focused tests for the normalized Kiwi morphology adapter."""

from dataclasses import dataclass

import pytest
from hanly import MorphologyProvider, ProviderError, TokenAnalysis
from hanly.kiwi_provider import KiwiProvider


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
    assert analyses == (
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

    assert analyses == (TokenAnalysis(token="먹", lemma="먹다", part_of_speech="VV"),)
    assert analyzer.inputs == []


def test_kiwi_provider_returns_empty_for_empty_input_without_calling_analyzer() -> None:
    analyzer = _FakeAnalyzer(
        (_FakeToken("절대 호출되면 안 됨", "NNG", "절대 호출되면 안 됨"),)
    )

    assert KiwiProvider(analyzer=analyzer).analyze("") == ()
    assert KiwiProvider(analyzer=analyzer).analyze("   \n\t") == ()
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
        KiwiProvider(analyzer=_FakeAnalyzer(())).analyze(None)  # type: ignore[arg-type]


def test_kiwi_provider_can_use_installed_kiwi_for_a_cheap_smoke() -> None:
    pytest.importorskip("kiwipiepy")

    analyses = KiwiProvider().analyze("먹었어요")

    assert analyses
    assert analyses[0].token == "먹"
    assert analyses[0].lemma == "먹다"
    assert analyses[0].part_of_speech == "VV"
    assert all(isinstance(analysis, TokenAnalysis) for analysis in analyses)
