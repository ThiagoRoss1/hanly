"""Turn one selected surface word into a normalized lookup outcome.

Everything from here on is about language, not about where the words came from.
The stage takes a :class:`~hanly.contracts.TextSelection` -- surface text plus a
cursor offset -- applies Hanly's Korean-only policy, asks the morphology
provider what lexical units the surface holds, picks the one the cursor is on,
and looks that lemma up.

It never sees an image, a screen rectangle, a window, or a desktop object, and
it must not learn to. Pixels reach it through
:class:`~hanly.lookup_pipeline.LookupPipeline`, which does OCR and target
resolution first; a reader that already knows the word can construct the
selection directly and skip all of that. Both then run this one implementation,
which is what makes the two paths answer identically.

A caller that has pixel evidence to preserve passes it as ``evidence``. The
stage fills in the language fields and leaves the rest of that context alone, so
a pixel lookup keeps its OCR regions and geometry without this module knowing
what any of it means.
"""

from collections.abc import Callable, Sequence
from dataclasses import replace
from unicodedata import category

from .contracts import (
    LexicalCandidate,
    LookupContext,
    LookupResult,
    LookupStatus,
    MorphologyAnalysis,
    TextSelection,
    TokenAnalysis,
)
from .errors import HanlyError, LookupCancelled
from .providers import DictionaryProvider, MorphologyProvider


class LanguagePipeline:
    """Run the Korean language stage for one already-selected surface word.

    Constructed with only the two providers it actually uses, so a client with
    no pixel path -- a future accessibility reader, a test, a replay tool --
    never has to build an OCR provider to look a word up.
    """

    def __init__(
        self,
        morphology_provider: MorphologyProvider,
        dictionary_provider: DictionaryProvider,
    ) -> None:
        self._morphology_provider = morphology_provider
        self._dictionary_provider = dictionary_provider

    def lookup(
        self,
        selection: TextSelection,
        *,
        cancelled: Callable[[], bool] | None = None,
        evidence: LookupContext | None = None,
    ) -> LookupResult:
        """Return a normalized result for one selected surface word.

        Unusable text and an absent dictionary entry are ordinary results, not
        exceptions. A provider that raises becomes an ``ERROR`` result carrying
        a :class:`~hanly.errors.HanlyError`.
        """

        if not isinstance(selection, TextSelection):
            raise TypeError("selection must be a TextSelection")

        # The stage owns the language fields and clears whatever a caller left
        # in them. Passing a previous result's context back as evidence is a
        # natural thing to do, and without this an early return would carry a
        # lemma that contradicts its own text.
        base = (
            LookupContext()
            if evidence is None
            else replace(evidence, text=None, lemma=None, analyses=(), candidate=None)
        )
        text = selection.text.strip()
        if not text:
            return LookupResult(
                status=LookupStatus.UNUSABLE,
                diagnostics=("The selection carried no text",),
                context=base,
            )

        context = replace(base, text=text)
        # Hanly's downstream language services are Korean-only. Latin text,
        # numbers, and punctuation must not wake the morphology provider or the
        # dictionary, whichever acquisition produced them.
        if not _is_korean_segment(text):
            return LookupResult(
                status=LookupStatus.UNUSABLE,
                diagnostics=(
                    "Resolved target must contain Hangul and may otherwise "
                    "contain only whitespace or punctuation",
                ),
                context=context,
            )

        try:
            analysis = _as_morphology_analysis(self._morphology_provider.analyze(text))
        except Exception as exc:
            return error_result("morphology", exc, context)

        abort_if_cancelled(cancelled)
        try:
            analyses = analysis.tokens
            selected = _select_candidate(analysis, selection.cursor_index)
        except Exception as exc:
            return error_result("morphology processing", exc, context)

        context = replace(context, analyses=analyses)
        if selected is None:
            return LookupResult(
                status=LookupStatus.UNUSABLE,
                diagnostics=("Morphology returned no usable lemma",),
                context=context,
            )

        lemma = selected.lemma
        diagnostics = _selection_diagnostics(analysis, selected, text)

        abort_if_cancelled(cancelled)
        context = replace(context, lemma=lemma, candidate=selected)
        try:
            entries = tuple(self._dictionary_provider.lookup(lemma))
        except Exception as exc:
            return error_result("dictionary", exc, context)

        if not entries:
            return LookupResult(
                status=LookupStatus.NOT_FOUND,
                diagnostics=diagnostics
                + (f"Dictionary returned no entries for lemma {lemma!r}",),
                context=context,
            )

        return LookupResult(
            status=LookupStatus.SUCCESS,
            entries=entries,
            diagnostics=diagnostics,
            context=context,
        )


def error_result(
    stage: str,
    exception: Exception,
    context: LookupContext | None = None,
) -> LookupResult:
    """Convert a stage failure into an ordinary ``ERROR`` result."""

    message = f"{stage} failed: {exception}"
    error = exception if isinstance(exception, HanlyError) else HanlyError(message)
    return LookupResult(
        status=LookupStatus.ERROR,
        # Built from the original exception so a synthesized error does not
        # repeat the stage prefix twice in the diagnostic.
        diagnostics=(message,),
        error=error,
        context=context,
    )


def abort_if_cancelled(cancelled: Callable[[], bool] | None) -> None:
    """Raise when a superseding request has made this one pointless."""

    if cancelled is not None and cancelled():
        raise LookupCancelled("lookup was superseded")


def _as_morphology_analysis(
    result: MorphologyAnalysis | Sequence[TokenAnalysis],
) -> MorphologyAnalysis:
    """Accept either contract shape from a morphology provider.

    ``hanly`` is consumed independently, so a provider written against the
    older ``Sequence[TokenAnalysis]`` contract stays valid. Its tokens become
    candidates only where the provider reported real spans; no joined or
    dictionary form is ever invented on its behalf.
    """

    if isinstance(result, MorphologyAnalysis):
        return result

    tokens = tuple(token for token in result if isinstance(token, TokenAnalysis))
    return MorphologyAnalysis(tokens=tokens, candidates=_candidates_from_tokens(tokens))


def _candidates_from_tokens(
    tokens: Sequence[TokenAnalysis],
) -> tuple[LexicalCandidate, ...]:
    candidates: list[LexicalCandidate] = []
    for index, token in enumerate(tokens):
        lemma = token.lemma.strip() if isinstance(token.lemma, str) else ""
        if not lemma or token.start is None or token.length is None:
            continue
        if token.start < 0 or token.length <= 0:
            continue
        candidates.append(
            LexicalCandidate(
                lemma=lemma,
                start=token.start,
                end=token.start + token.length,
                part_of_speech=token.part_of_speech,
                token_indices=(index,),
            )
        )
    return tuple(candidates)


def _select_candidate(
    analysis: MorphologyAnalysis, cursor_index: int
) -> LexicalCandidate | None:
    """Choose the lexical unit the pointer is on, or the only usable fallback.

    A provider that reports no spans cannot be targeted, so its first usable
    lemma remains the answer rather than a refusal.
    """

    candidate = analysis.candidate_at(cursor_index)
    if candidate is not None:
        return candidate

    for token in analysis.tokens:
        lemma = token.lemma.strip() if isinstance(token.lemma, str) else ""
        if lemma:
            return LexicalCandidate(lemma=lemma, start=0, end=max(1, len(lemma)))
    return None


def _selection_diagnostics(
    analysis: MorphologyAnalysis, selected: LexicalCandidate, text: str
) -> tuple[str, ...]:
    """Report a reduction the user cannot see in the answer itself.

    Several lexical units inside one resolved segment means the popup shows a
    word the reader may not be pointing at. Korean writes compounds without
    spaces, so counting whitespace would miss exactly the ambiguous cases.
    """

    if len(analysis.candidates) <= 1:
        return ()
    others = ", ".join(
        repr(candidate.lemma)
        for candidate in analysis.candidates
        if candidate is not selected
    )
    return (
        f"Resolved segment {text!r} holds {len(analysis.candidates)} lexical units; "
        f"selected {selected.lemma!r} at the pointer, with {others} also present",
    )


def _is_korean_segment(text: str) -> bool:
    """Accept Hangul text with whitespace/punctuation, rejecting other scripts."""

    return any(_is_hangul_character(character) for character in text) and all(
        _is_hangul_character(character)
        or character.isspace()
        or category(character).startswith("P")
        for character in text
    )


def _is_hangul_character(character: str) -> bool:
    """Return whether a character belongs to a supported Hangul codepoint range."""

    return (
        "ᄀ" <= character <= "ᇿ"
        or "㄰" <= character <= "㆏"
        or "ꥠ" <= character <= "꥿"
        or "가" <= character <= "힣"
        or "ힰ" <= character <= "퟿"
    )


__all__ = ["LanguagePipeline", "abort_if_cancelled", "error_result"]
