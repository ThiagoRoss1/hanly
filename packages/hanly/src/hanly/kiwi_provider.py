"""Kiwi-backed morphology provider for the Hanly engine.

The optional ``kiwipiepy`` dependency is deliberately loaded lazily.  This
keeps the normalized engine contracts importable in environments that do not
install the concrete provider, while still reporting a provider-owned error
when the adapter is used without Kiwi available.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from importlib import import_module
from typing import Any, cast

from .contracts import LexicalCandidate, MorphologyAnalysis, TokenAnalysis
from .errors import ProviderError

_PUNCTUATION_TAGS = frozenset(
    {"SF", "SP", "SS", "SSO", "SSC", "SE", "SO", "SW", "SB"}
)
#: Endings, particles, and derivational suffixes attach to the unit before them
#: rather than opening one of their own.
_ATTACHED_PREFIXES = ("E", "J", "XS")


def _tag_family(tag: str | None) -> str:
    """The tag without Kiwi's irregular-conjugation suffix, e.g. ``VA-I``."""

    return (tag or "").split("-", 1)[0].upper()


def _join_verb_suffix_options() -> int | None:
    """Kiwi's ``Match.ALL | Match.JOIN_V_SUFFIX`` value, when kiwipiepy is present."""

    try:
        match = getattr(import_module("kiwipiepy"), "Match")
        return int(match.ALL | match.JOIN_V_SUFFIX)
    except Exception:
        return None


@dataclass
class _CandidateBuilder:
    """Accumulates one lexical unit and the affixes attached to it."""

    lemma: str
    start: int
    end: int
    part_of_speech: str | None
    token_indices: list[int]

    def extend(self, index: int, end: int) -> None:
        # Contracted syllables make Kiwi spans overlap, so the unit's extent is
        # the furthest edge reached rather than the last token's edge.
        self.end = max(self.end, end)
        self.token_indices.append(index)

    def build(self) -> LexicalCandidate:
        return LexicalCandidate(
            lemma=self.lemma,
            start=self.start,
            end=self.end,
            part_of_speech=self.part_of_speech,
            token_indices=tuple(self.token_indices),
        )


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

    def analyze(self, text: str) -> MorphologyAnalysis:
        """Return raw morphemes and the lexical units a lookup may address.

        Empty or whitespace-only input is a normal empty result and does not
        invoke the analyzer.  Analyzer failures and malformed token values are
        normalized to :class:`ProviderError` so external exceptions do not
        cross the provider seam.
        """

        if not isinstance(text, str):
            raise TypeError("morphology input must be a string")
        if not text.strip():
            return MorphologyAnalysis()

        try:
            tokens = tuple(
                self._normalize_token(token) for token in self._tokenize(text)
            )
            candidates = self._candidates(text)
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError("Kiwi morphology analysis failed") from exc

        return MorphologyAnalysis(tokens=tokens, candidates=candidates)

    def _candidates(self, text: str) -> tuple[LexicalCandidate, ...]:
        """Group the affix-joined token stream into addressable lexical units.

        Kiwi's ``JOIN_V_SUFFIX`` option is what turns ``사과 + 하`` into the
        single predicate ``사과하다``. Deriving the lemma any other way would
        mean appending ``다`` to a stem, which produces wrong forms for
        irregulars and is rejected by the plan.
        """

        joined = self._tokenize_joined(text)
        if joined is None:
            return ()

        grouped: list[_CandidateBuilder] = []
        for index, token in enumerate(joined):
            tag = _tag_family(self._optional_string(token, ("tag", "part_of_speech", "pos")))
            start, length = self._span(token)
            if start is None or length is None or length <= 0:
                continue

            if tag in _PUNCTUATION_TAGS:
                continue

            if grouped and tag.startswith(_ATTACHED_PREFIXES):
                grouped[-1].extend(index, start + length)
                continue

            if tag.startswith(_ATTACHED_PREFIXES):
                # A particle or ending with nothing before it cannot open a unit.
                continue

            lemma = self._optional_string(token, ("lemma", "dictionary_form", "base_form"))
            surface = self._optional_string(token, ("form", "surface", "token"))
            grouped.append(
                _CandidateBuilder(
                    lemma=lemma or surface or "",
                    start=start,
                    end=start + length,
                    part_of_speech=tag or None,
                    token_indices=[index],
                )
            )

        return tuple(builder.build() for builder in grouped if builder.lemma)

    def _tokenize_joined(self, text: str) -> Iterable[object] | None:
        """Tokenize with verb suffixes joined, or ``None`` when unsupported.

        An injected test double normally has a plain ``tokenize(text)``, so an
        unsupported keyword is a normal absence of candidates rather than an
        error: the pipeline then falls back to token-derived candidates.
        """

        analyzer = self._get_analyzer()
        tokenize = getattr(analyzer, "tokenize", None)
        if not callable(tokenize):
            return None

        options = _join_verb_suffix_options()
        if options is None:
            return None
        try:
            return cast(Iterable[object], tokenize(text, match_options=options))
        except TypeError:
            return None

    @classmethod
    def _span(cls, token: object) -> tuple[int | None, int | None]:
        start = cls._value(token, ("start",))
        length = cls._value(token, ("len", "length"))
        if isinstance(start, bool) or isinstance(length, bool):
            return None, None
        if not isinstance(start, int) or not isinstance(length, int):
            return None, None
        return start, length

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

        start, length = cls._span(token)

        return TokenAnalysis(
            token=surface,
            lemma=lemma,
            part_of_speech=part_of_speech,
            morphology=morphology,
            start=start,
            length=length,
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
