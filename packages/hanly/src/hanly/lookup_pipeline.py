"""Provider-only orchestration for normalized Hanly lookups."""

from collections.abc import Callable, Sequence
from dataclasses import replace
from math import isfinite

from .contracts import (
    BoundingBox,
    LookupContext,
    LookupResult,
    LookupStatus,
    OCRResult,
    Point,
    ROIImage,
    TextSelection,
)
from .language_pipeline import LanguagePipeline, abort_if_cancelled, error_result
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
        self._word_resolver = word_resolver or WordResolver()
        self._confidence_threshold = confidence_threshold
        # One language implementation, shared with every non-pixel caller.
        self._language = LanguagePipeline(morphology_provider, dictionary_provider)

    def _resolve_target(
        self,
        ocr_results: Sequence[OCRResult],
        target: Point,
    ) -> tuple[OCRResult | None, str, int]:
        """Resolve the pointer through the richest API the resolver offers.

        A resolver that only implements the pair contract still works; its
        answer simply carries no pointer offset, so selection falls back to the
        start of the resolved word.
        """

        detailed = getattr(self._word_resolver, "resolve_target_detail", None)
        if callable(detailed):
            resolution = detailed(ocr_results, target)
            if resolution is None:
                return None, "", 0
            return resolution.region, resolution.text, resolution.cursor_index

        pair = self._word_resolver.resolve_target(ocr_results, target)
        # A resolver that returns a malformed pair fails here and becomes an
        # ordinary word-resolution error rather than a shape ladder.
        region, text = pair if pair is not None else (None, "")
        return region, text, 0

    @property
    def confidence_threshold(self) -> float | None:
        """The configured lower bound for resolved OCR confidence."""

        return self._confidence_threshold

    def lookup(
        self,
        image: ROIImage,
        target: Point,
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> LookupResult:
        """Return a normalized result for ``image`` at ``target``.

        The compatible pixel facade, unchanged for every existing caller. It
        owns what only pixels can decide -- recognition, which region the
        pointer is in, and OCR confidence -- and then hands the resulting
        selection to the same language stage a non-pixel caller would use.

        Empty, unresolved, low-confidence, and not-found outcomes are ordinary
        results.  Exceptions from a provider or processing stage are converted
        into an ``ERROR`` result carrying a ``HanlyError`` so callers do not
        need exception handling for normal lookup execution.
        """

        abort_if_cancelled(cancelled)
        try:
            ocr_results = tuple(self._ocr_provider.recognize(image))
        except Exception as exc:
            return error_result("OCR", exc)

        abort_if_cancelled(cancelled)
        context = LookupContext(ocr_results=ocr_results)
        if not ocr_results:
            return LookupResult(
                status=LookupStatus.EMPTY,
                diagnostics=("OCR returned no text regions",),
                context=context,
            )

        try:
            region, text, cursor_index = self._resolve_target(ocr_results, target)
        except Exception as exc:
            return error_result("word resolution", exc, context)

        abort_if_cancelled(cancelled)
        if region is None or not text.strip():
            return LookupResult(
                status=LookupStatus.UNUSABLE,
                diagnostics=("OCR target did not resolve to one usable text region",),
                context=context,
            )

        evidence = LookupContext(
            ocr_results=ocr_results,
            selected_ocr=region,
            word_region=_word_region(self._word_resolver, region, target),
        )

        try:
            low_confidence = self._is_low_confidence(region)
        except Exception as exc:
            return error_result(
                "confidence processing", exc, replace(evidence, text=text.strip())
            )
        if low_confidence:
            threshold = self._confidence_threshold
            assert threshold is not None
            return LookupResult(
                status=LookupStatus.UNUSABLE,
                diagnostics=(
                    f"OCR confidence for {text.strip()!r} is below the configured "
                    f"threshold {threshold:g}",
                ),
                context=replace(evidence, text=text.strip()),
            )

        return self._language.lookup(
            TextSelection(text=text, cursor_index=cursor_index, source="ocr"),
            cancelled=cancelled,
            evidence=evidence,
        )

    def lookup_selection(
        self,
        selection: TextSelection,
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> LookupResult:
        """Look one already-selected surface word up, without an image.

        The same language stage :meth:`lookup` reaches after OCR. A caller that
        obtained the word some other way needs no pixels, no target point, and
        no OCR provider -- though one built through this class still had to
        supply one, which is why :class:`~hanly.language_pipeline.LanguagePipeline`
        is separately constructible.
        """

        return self._language.lookup(selection, cancelled=cancelled)

    def _is_low_confidence(self, region: OCRResult) -> bool:
        """Apply confidence policy to the OCR region that contains the target."""

        threshold = self._confidence_threshold
        return threshold is not None and region.confidence < threshold


def _word_region(
    resolver: TargetResolver, region: OCRResult, target: Point
) -> BoundingBox | None:
    """Ask the resolver where the word is, if this one can say.

    Geometry is an addition to the resolver seam rather than a requirement of
    it: a substituted resolver that only answers "which word" stays valid, and
    its results simply carry no geometry for a client to use.
    """

    bounds = getattr(resolver, "word_bounds", None)
    if not callable(bounds):
        return None
    try:
        found = bounds(region, target)
    except Exception:
        # Geometry is an optimisation for the client's popup. Losing it must
        # never turn a successful lookup into an error.
        return None
    return found if isinstance(found, BoundingBox) else None


__all__ = ["LookupPipeline"]
