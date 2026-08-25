"""Kiwi-backed morphology provider for the Hanly engine.

The optional ``kiwipiepy`` dependency is deliberately loaded lazily.  This
keeps the normalized engine contracts importable in environments that do not
install the concrete provider, while still reporting a provider-owned error
when the adapter is used without Kiwi available.
"""

from collections.abc import Iterable, Mapping, Sequence
from importlib import import_module
from typing import Any, cast

from .contracts import TokenAnalysis
from .errors import ProviderError


class KiwiProvider:
    """Adapt a Kiwi tokenizer to the normalized morphology contract.

    ``analyzer`` is injectable so callers and tests can provide a compatible
    tokenizer without constructing Kiwi.  A real ``kiwipiepy.Kiwi`` instance
    is created lazily when no analyzer is supplied.
    """

    def __init__(self, analyzer: object | None = None) -> None:
        self._analyzer = analyzer
        self._prewarmed = False

    def prewarm(self) -> None:
        """Initialize Kiwi and exercise its tokenizer once on the caller thread."""

        if self._prewarmed:
            return
        self.analyze("한")
        self._prewarmed = True

    def analyze(self, text: str) -> Sequence[TokenAnalysis]:
        """Return normalized token analyses for ``text``.

        Empty or whitespace-only input is a normal empty result and does not
        invoke the analyzer.  Analyzer failures and malformed token values are
        normalized to :class:`ProviderError` so external exceptions do not
        cross the provider seam.
        """

        if not isinstance(text, str):
            raise TypeError("morphology input must be a string")
        if not text.strip():
            return ()

        try:
            tokens = self._tokenize(text)
            return tuple(self._normalize_token(token) for token in tokens)
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError("Kiwi morphology analysis failed") from exc

    def _tokenize(self, text: str) -> Iterable[object]:
        analyzer = self._get_analyzer()

        tokenize = getattr(analyzer, "tokenize", None)
        if callable(tokenize):
            return cast(Iterable[object], tokenize(text))

        # A narrow fallback makes injected test doubles convenient while the
        # real Kiwi adapter continues to use its stable ``tokenize`` method.
        analyze = getattr(analyzer, "analyze", None)
        if callable(analyze):
            return cast(Iterable[object], analyze(text))

        if callable(analyzer):
            return cast(Iterable[object], analyzer(text))

        raise ProviderError("Kiwi analyzer must provide tokenize(text)")

    def _get_analyzer(self) -> object:
        if self._analyzer is not None:
            return self._analyzer

        try:
            kiwi_module = import_module("kiwipiepy")
            kiwi_type = getattr(kiwi_module, "Kiwi")
            self._analyzer = kiwi_type()
        except Exception as exc:
            raise ProviderError("kiwipiepy is unavailable") from exc
        return self._analyzer

    @classmethod
    def _normalize_token(cls, token: object) -> TokenAnalysis:
        surface = cls._required_string(token, ("form", "surface", "token"), "surface")
        lemma = cls._optional_string(
            token,
            ("lemma", "dictionary_form", "base_form"),
        ) or surface
        part_of_speech = cls._optional_string(
            token,
            ("tag", "part_of_speech", "pos"),
        )
        morphology = cls._optional_string(token, ("morphology", "morph"))

        return TokenAnalysis(
            token=surface,
            lemma=lemma,
            part_of_speech=part_of_speech,
            morphology=morphology,
        )

    @classmethod
    def _required_string(
        cls,
        token: object,
        names: tuple[str, ...],
        label: str,
    ) -> str:
        value = cls._value(token, names)
        if not isinstance(value, str) or not value:
            raise ProviderError(f"Kiwi token is missing a non-empty {label}")
        return value

    @classmethod
    def _optional_string(
        cls,
        token: object,
        names: tuple[str, ...],
    ) -> str | None:
        value = cls._value(token, names)
        if value is None:
            return None
        if not isinstance(value, str):
            raise ProviderError(f"Kiwi token field {names[0]!r} must be a string")
        return value or None

    @staticmethod
    def _value(token: object, names: tuple[str, ...]) -> Any:
        if isinstance(token, Mapping):
            for name in names:
                if name in token:
                    return token[name]
            return None

        for name in names:
            value = getattr(token, name, None)
            if value is not None:
                return value
        return None


__all__ = ["KiwiProvider"]
