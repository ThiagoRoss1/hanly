"""Provider-only orchestration for normalized Hanly lookups."""

from collections.abc import Sequence
from math import isfinite

from .contracts import (
    LookupContext,
    LookupResult,
    LookupStatus,
    OCRResult,
    Point,
    ROIImage,
    TokenAnalysis,
)
from .errors import HanlyError
from .providers import DictionaryProvider, MorphologyProvider, OCRProvider
from .word_resolver import TargetResolver, WordResolver


class LookupPipeline:
    """Run OCR, target resolution, morphology, and dictionary lookup.

    The pipeline deliberately knows only normalized contracts, provider
    protocols, and the :class:`TargetResolver` seam.  It does not select or
    construct a concrete provider.  A confidence threshold is optional: when omitted,
    OCR confidence is retained as evidence but does not reject a lookup.
    When configured, it applies to the OCR region resolved at the target and a
    below-threshold region produces the normal ``UNUSABLE`` outcome.
    """

    def __init__(
        self,
        ocr_provider: OCRProvider,
        morphology_provider: MorphologyProvider,
        dictionary_provider: DictionaryProvider,
        word_resolver: TargetResolver | None = None,
        *,
        confidence_threshold: float | None = None,
    ) -> None:
        if confidence_threshold is not None and (
            not isinstance(confidence_threshold, (int, float))
            or isinstance(confidence_threshold, bool)
            or not isfinite(float(confidence_threshold))
            or not 0 <= confidence_threshold <= 1
        ):
            raise ValueError("confidence_threshold must be between 0 and 1")

        self._ocr_provider = ocr_provider
        self._morphology_provider = morphology_provider
        self._dictionary_provider = dictionary_provider
        self._word_resolver = word_resolver or WordResolver()
        self._confidence_threshold = confidence_threshold

    @property
    def confidence_threshold(self) -> float | None:
        """The configured lower bound for resolved OCR confidence."""

        return self._confidence_threshold

    def lookup(self, image: ROIImage, target: Point) -> LookupResult:
        """Return a normalized result for ``image`` at ``target``.

        Empty, unresolved, low-confidence, and not-found outcomes are ordinary
        results.  Exceptions from a provider or processing stage are converted
        into an ``ERROR`` result carrying a ``HanlyError`` so callers do not
        need exception handling for normal lookup execution.
        """

        try:
            ocr_results = tuple(self._ocr_provider.recognize(image))
        except Exception as exc:
            return self._error_result("OCR", exc)

        context = LookupContext(ocr_results=ocr_results)
        if not ocr_results:
            return LookupResult(
                status=LookupStatus.EMPTY,
                diagnostics=("OCR returned no text regions",),
                context=context,
            )

        try:
            resolution = self._word_resolver.resolve_target(ocr_results, target)
            # A resolver that returns a malformed pair fails here and becomes
            # an ordinary word-resolution error rather than a shape ladder.
            region, text = resolution if resolution is not None else (None, "")
        except Exception as exc:
            return self._error_result("word resolution", exc, context)

        if region is None or not text.strip():
            return LookupResult(
                status=LookupStatus.UNUSABLE,
                diagnostics=("OCR target did not resolve to one usable text region",),
                context=context,
            )

        text = text.strip()
        context = LookupContext(text=text, ocr_results=ocr_results)

        try:
            low_confidence = self._is_low_confidence(region)
        except Exception as exc:
            return self._error_result("confidence processing", exc, context)
        if low_confidence:
            threshold = self._confidence_threshold
            assert threshold is not None
            return LookupResult(
                status=LookupStatus.UNUSABLE,
                diagnostics=(
                    f"OCR confidence for {text!r} is below the configured "
                    f"threshold {threshold:g}",
                ),
                context=context,
            )

        try:
            analyses = tuple(self._morphology_provider.analyze(text))
        except Exception as exc:
            return self._error_result("morphology", exc, context)

        try:
            lemmas = _usable_lemmas(analyses)
        except Exception as exc:
            return self._error_result("morphology processing", exc, context)
        if not lemmas:
            return LookupResult(
                status=LookupStatus.UNUSABLE,
                diagnostics=("Morphology returned no usable lemma",),
                context=context,
            )

        lemma = lemmas[0]
        diagnostics: tuple[str, ...] = ()
        if len(lemmas) > 1 and len(text.split()) > 1:
            # One resolved word analyzing into several lemmas is ordinary
            # Korean morphology. A segment still holding several words is not:
            # the answer may be for a word the user is not pointing at, so that
            # reduction stays visible instead of silent.
            diagnostics = (
                f"Resolved segment {text!r} holds several words and "
                f"{len(lemmas)} usable lemmas; looked up the first ({lemma!r}) "
                f"because the pipeline does not re-target inside a segment",
            )

        context = LookupContext(text=text, lemma=lemma, ocr_results=ocr_results)
        try:
            entries = tuple(self._dictionary_provider.lookup(lemma))
        except Exception as exc:
            return self._error_result("dictionary", exc, context)

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

    def _is_low_confidence(self, region: OCRResult) -> bool:
        """Apply confidence policy to the OCR region that contains the target."""

        threshold = self._confidence_threshold
        return threshold is not None and region.confidence < threshold

    @staticmethod
    def _error_result(
        stage: str,
        exception: Exception,
        context: LookupContext | None = None,
    ) -> LookupResult:
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


def _usable_lemmas(analyses: Sequence[TokenAnalysis]) -> tuple[str, ...]:
    """Return the provider-ordered non-empty lemmas.

    The pipeline uses the first one; the rest are counted so a multi-token
    segment can be reported rather than silently reduced.
    """

    lemmas: list[str] = []
    for analysis in analyses:
        if not isinstance(analysis, TokenAnalysis):
            continue
        if not isinstance(analysis.lemma, str):
            continue
        lemma = analysis.lemma.strip()
        if lemma:
            lemmas.append(lemma)
    return tuple(lemmas)


__all__ = ["LookupPipeline"]
