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
    DictionaryEntry,
    LexicalCandidate,
    LexicalComponent,
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

        abort_if_cancelled(cancelled)
        # A dictionary failure still has to explain which unit was being looked
        # up, and the whole form is not known until the probe has answered.
        attempted = replace(context, lemma=selected.lemma, candidate=selected)
        probes = _DictionaryProbes(self._dictionary_provider)
        try:
            selected, entries = self._resolve_entries(probes, analysis, selected, text)
            listed_whole = bool(entries) and selected.lemma == text
            components = _components(
                probes, analysis, text, selection.cursor_index, listed_whole
            )
        except Exception as exc:
            return error_result("dictionary", exc, attempted)

        lemma = selected.lemma
        diagnostics = _selection_diagnostics(analysis, selected, text)
        context = replace(
            context, lemma=lemma, candidate=selected, components=components
        )

        if not entries:
            return LookupResult(
                status=LookupStatus.NOT_FOUND,
                diagnostics=diagnostics
                + (f"Dictionary returned no entries for lemma {lemma!r}",),
                context=context,
            )

        return LookupResult(
            status=LookupStatus.SUCCESS,
            entries=_rank_entries(entries, selected.part_of_speech),
            diagnostics=diagnostics,
            context=context,
        )

    def _resolve_entries(
        self,
        probes: "_DictionaryProbes",
        analysis: MorphologyAnalysis,
        selected: LexicalCandidate,
        text: str,
    ) -> tuple[LexicalCandidate, tuple[DictionaryEntry, ...]]:
        """Answer with the largest real dictionary form covering the surface.

        The exact surface comes first because a dictionary lists many forms
        verbatim -- ``깜짝이야`` and ``고소득층`` are entries in their own right,
        and reconstructing them from morphology would answer a different word.
        Only then is the whole form reconstructed, and only then the component
        the cursor is on.
        """

        entries = probes.lookup(text)
        if entries:
            surface = LexicalCandidate(
                lemma=text,
                start=0,
                end=len(text),
                part_of_speech=selected.part_of_speech,
            )
            return surface, entries

        whole = _complete_form(analysis, text)
        if whole is not None:
            entries = probes.lookup(whole.lemma)
            if entries:
                return whole, entries

        return selected, probes.lookup(selected.lemma)


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


#: KRDICT grades every entry. The common sense of a homograph is the one a
#: reader hovering ordinary text almost always means, and this grading is the
#: dictionary's own answer to which that is.
_LEVEL_ORDER = {"초급": 0, "중급": 1, "고급": 2}

#: Kiwi tag family -> the KRDICT part-of-speech naming the same class. Only the
#: families that actually open a lexical unit appear; anything absent simply
#: contributes no ordering signal.
_POS_EQUIVALENTS = {
    "NNG": "명사",
    "NNP": "명사",
    "NNB": "의존 명사",
    "NP": "대명사",
    "NR": "수사",
    "VV": "동사",
    "VA": "형용사",
    "MAG": "부사",
    "MAJ": "부사",
    "MM": "관형사",
    "IC": "감탄사",
}


#: Kiwi tag families that attach to a lexical unit instead of naming one. They
#: explain the form of the word, so they are annotations rather than entries.
_GRAMMATICAL_PREFIXES = ("E", "J", "XS")

#: What each grammatical family contributes, in the reader's terms. An absent
#: family simply has no label, which is honest rather than invented.
_GRAMMATICAL_LABELS = {
    "EP": "tense or honorific",
    "EF": "sentence ending",
    "EC": "connective ending",
    "ETN": "nominalizing ending",
    "ETM": "modifier ending",
    "JKS": "subject particle",
    "JKC": "complement particle",
    "JKO": "object particle",
    "JKG": "possessive particle",
    "JKB": "adverbial particle",
    "JKV": "vocative particle",
    "JKQ": "quotative particle",
    "JX": "auxiliary particle",
    "JC": "connective particle",
    "XSN": "noun-forming suffix",
    "XSV": "verb-forming suffix",
    "XSA": "adjective-forming suffix",
}

#: The dictionary budget for one lookup: the exact surface, the reconstructed
#: whole form, and up to three lexical components.
_MAX_DICTIONARY_QUERIES = 5
_MAX_COMPONENT_QUERIES = 3


class _DictionaryProbes:
    """One lookup's dictionary budget, deduplicated and capped.

    A hover must not multiply into an unbounded number of queries just because
    a surface decomposes into many parts, so a repeated lemma is free and the
    budget simply runs out rather than growing.
    """

    def __init__(self, provider: DictionaryProvider) -> None:
        self._provider = provider
        self._answers: dict[str, tuple[DictionaryEntry, ...]] = {}

    def lookup(self, lemma: str) -> tuple[DictionaryEntry, ...]:
        cached = self._answers.get(lemma)
        if cached is not None:
            return cached
        if len(self._answers) >= _MAX_DICTIONARY_QUERIES:
            return ()
        entries = tuple(self._provider.lookup(lemma))
        self._answers[lemma] = entries
        return entries

    @property
    def query_count(self) -> int:
        return len(self._answers)


def _components(
    probes: _DictionaryProbes,
    analysis: MorphologyAnalysis,
    text: str,
    cursor_index: int,
    listed_whole: bool = False,
) -> tuple[LexicalComponent, ...]:
    """Describe how ``text`` is built, with a gloss for each part.

    A surface that does not decompose has nothing to explain, so it returns
    nothing and a client has no panel to show.

    When the dictionary lists the surface itself, the word is already settled
    and its morphological split is only worth showing if every part genuinely
    explains the characters it covers. ``두통거리`` is ``두통`` and ``거리``,
    which is worth knowing; ``고소득층`` is not ``고 · the late``. The endings
    are kept either way, because they describe the form rather than rename it.
    """

    lexical = (
        _lexical_components(probes, analysis, text, cursor_index)
        if not listed_whole or _decomposition_is_faithful(probes, analysis, text)
        else []
    )
    grammatical = _grammatical_components(analysis, text)
    if len(lexical) + len(grammatical) < 2:
        return ()

    # Stable in morphology order for equal offsets, which keeps a stem ahead of
    # the ending that fuses into the same characters.
    return tuple(sorted(lexical + grammatical, key=lambda item: item.start))


def _decomposition_is_faithful(
    probes: _DictionaryProbes, analysis: MorphologyAnalysis, text: str
) -> bool:
    """Whether every part explains exactly the characters it covers.

    A part earns its place when the dictionary holds its lemma *and* that lemma
    is what the span actually reads. Both halves are needed: a lemma the
    dictionary lacks explains nothing, and a lemma that differs from its own
    surface is the morphology having substituted a different word -- ``가다``
    for the ``가`` of ``여행가``, ``이다`` for the ``이야`` of ``깜짝이야``, or a
    bare ``소득`` for the ``소득층`` of ``고소득층``.

    Running out of dictionary budget answers no as well, since an unglossed
    part cannot be shown to explain anything.
    """

    candidates = analysis.candidates
    if len(candidates) < 2:
        return False

    for candidate in candidates:
        span = _clamp_span(candidate.start, candidate.end, text)
        if span is None or text[span[0] : span[1]] != candidate.lemma:
            return False
        if not probes.lookup(candidate.lemma):
            return False
    return True


def _lexical_components(
    probes: _DictionaryProbes,
    analysis: MorphologyAnalysis,
    text: str,
    cursor_index: int,
) -> list[LexicalComponent]:
    """The dictionary-addressable parts, glossed while the budget allows."""

    selected = _select_candidate(analysis, cursor_index)
    ordered = list(analysis.candidates)
    if selected is not None:
        # The part the reader is pointing at is the one worth spending the
        # budget on first.
        ordered.sort(key=lambda candidate: candidate.lemma != selected.lemma)

    glossed: dict[str, str | None] = {}
    for candidate in ordered:
        if len(glossed) >= _MAX_COMPONENT_QUERIES:
            break
        if candidate.lemma in glossed:
            continue
        entries = probes.lookup(candidate.lemma)
        glossed[candidate.lemma] = _first_gloss(entries, candidate.part_of_speech)

    components: list[LexicalComponent] = []
    for candidate in analysis.candidates:
        span = _clamp_span(candidate.start, candidate.end, text)
        if span is None:
            continue
        components.append(
            LexicalComponent(
                lemma=candidate.lemma,
                start=span[0],
                end=span[1],
                gloss=glossed.get(candidate.lemma),
                part_of_speech=candidate.part_of_speech,
            )
        )
    return components


def _grammatical_components(
    analysis: MorphologyAnalysis, text: str
) -> list[LexicalComponent]:
    """The endings and particles, which explain the form rather than name it."""

    components: list[LexicalComponent] = []
    for token in analysis.tokens:
        family = _tag_family(token.part_of_speech)
        if not family.startswith(_GRAMMATICAL_PREFIXES):
            continue
        if token.start is None or token.length is None:
            continue
        span = _clamp_span(token.start, token.start + token.length, text)
        if span is None or not token.lemma:
            continue
        components.append(
            LexicalComponent(
                lemma=token.lemma,
                start=span[0],
                end=span[1],
                gloss=_GRAMMATICAL_LABELS.get(family),
                part_of_speech=token.part_of_speech,
                grammatical=True,
            )
        )
    return components


def _clamp_span(start: int, end: int, text: str) -> tuple[int, int] | None:
    """Keep a provider's span inside the text it describes, or drop it.

    A candidate's span covers the endings attached to its unit, and a provider
    may report one reaching past the analyzed text. The contract requires
    offsets that index ``text``, so an unusable span is omitted rather than
    repaired into a different claim.
    """

    if not isinstance(start, int) or not isinstance(end, int):
        return None
    bounded_end = min(end, len(text))
    if start < 0 or bounded_end <= start:
        return None
    return start, bounded_end


def _first_gloss(
    entries: tuple[DictionaryEntry, ...], part_of_speech: str | None
) -> str | None:
    """The gloss a reader would see for this part, under the same ordering."""

    if not entries:
        return None
    senses = _rank_entries(entries, part_of_speech)[0].senses
    return senses[0].gloss if senses else None


def _complete_form(
    analysis: MorphologyAnalysis, text: str
) -> LexicalCandidate | None:
    """The whole form the units spell out, when they spell out one word.

    Kiwi lexicalizes some compounds itself and splits others, so ``인정받다``
    arrives whole while ``초대받다`` arrives as two units. Joining the leading
    surface to the final unit's lemma reconstructs the dictionary form without
    appending an ending to a stem, which would be wrong for every irregular.
    Whether the result is a word is decided by the dictionary, not here.
    """

    candidates = analysis.candidates
    if len(candidates) < 2:
        return None

    first, last = candidates[0], candidates[-1]
    if last.start <= first.start or last.end > len(text):
        return None

    span = text[first.start : last.end]
    # Whitespace means these are separate words that happen to share a
    # selection, and they must keep selecting independently.
    if any(character.isspace() for character in span):
        return None

    # Substituting the final lemma for its surface is only right when that
    # lemma is the dictionary form of an inflected predicate. A noun whose span
    # swallowed a derivational suffix keeps its bare lemma, so the same
    # substitution would silently drop characters -- `고소득층` would be asked
    # for as `고소득`, which is a different word the dictionary also has.
    swallowed_suffix = last.end > last.start + len(last.lemma)
    predicate = (last.part_of_speech or "").upper().startswith("V")
    if swallowed_suffix and not predicate:
        return None

    lemma = text[first.start : last.start] + last.lemma
    if not lemma:
        return None

    return LexicalCandidate(
        lemma=lemma,
        start=first.start,
        end=last.end,
        part_of_speech=last.part_of_speech,
        token_indices=tuple(
            index for candidate in candidates for index in candidate.token_indices
        ),
    )


def _rank_entries(
    entries: tuple[DictionaryEntry, ...], part_of_speech: str | None
) -> tuple[DictionaryEntry, ...]:
    """Order one lemma's homographs by signals the lookup already computed.

    Provider order is insertion order, which put ``초대 · 初代`` ahead of
    ``초대 · 招待``. Matching the morphology's part of speech first, then the
    dictionary's own difficulty grading, replaces that with the reading a
    hovering reader means, without inspecting any definition text.
    """

    if len(entries) < 2:
        return entries

    wanted = _POS_EQUIVALENTS.get(_tag_family(part_of_speech))

    def rank(item: tuple[int, DictionaryEntry]) -> tuple[int, int, int]:
        index, entry = item
        matched = 0 if wanted is not None and entry.part_of_speech == wanted else 1
        level = _LEVEL_ORDER.get(entry.vocabulary_level or "", len(_LEVEL_ORDER))
        return (matched, level, index)

    return tuple(entry for _index, entry in sorted(enumerate(entries), key=rank))


def _tag_family(tag: str | None) -> str:
    """The tag without Kiwi's irregular-conjugation suffix, e.g. ``VV-R``."""

    return (tag or "").split("-", 1)[0].upper()


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
