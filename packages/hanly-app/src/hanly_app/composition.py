"""Application composition for the first Hanly engine worker.

Concrete provider construction intentionally happens in the executor worker
thread.  In particular, ``KRDICTProvider`` opens its SQLite connection there
and is closed there, preserving SQLite's thread affinity without changing the
engine adapter.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Sequence
from hashlib import blake2b
from typing import Protocol

from hanly import (
    DictionaryEntry,
    DictionaryProvider,
    LookupPipeline,
    LookupResult,
    LookupStatus,
    MorphologyProvider,
    OCRProvider,
    OCRResult,
    Point,
    ROIImage,
    TokenAnalysis,
)
from hanly.errors import LookupCancelled
from hanly.word_resolver import TargetResolver, WordResolver

from .lookup_controller import LookupController, LookupRequest, ResultDispatcher
from .runtime_trace import JSONPrimitive, RuntimeTraceSink, emit_trace

_LOOKUP_CACHE_SIZE = 32
# One entry holds a few OCR results and their geometry, on the order of a
# few hundred bytes, so a generous ring is cheap. It matters because live
# screen content changes under the cursor -- a blinking text caret inside
# the ROI is enough to miss -- and a small ring evicts a region the user
# is still moving around in.
_OCR_CACHE_SIZE = 96
# Text-presence gate sampling. Tuned to reject flat regions only; see
# :class:`_TextPresenceGate`.
_GATE_SAMPLES_PER_ROW = 64
_GATE_SAMPLE_ROWS = 32
_GATE_EDGE_DELTA = 32
_GATE_MIN_TRANSITIONS = 8
LookupCacheKey = tuple[bool, int, int, str, float, float, bytes]
_OCRCacheKey = tuple[int, int, str, bytes]  # dimensions, format, ROI digest


class Worker(Protocol):
    """Worker shape consumed by :class:`hanly_app.job_executor.JobExecutor`."""

    def __call__(self, item: LookupRequest) -> object:
        ...

    def close(self) -> None:
        ...


# Each factory names the protocol it must produce. Returning ``object`` was
# what forced the call site to suppress mypy; the provider protocols are
# structural, so any conforming adapter still satisfies these without
# inheriting anything.
OCRProviderFactory = Callable[[], OCRProvider]
MorphologyProviderFactory = Callable[[], MorphologyProvider]
DictionaryProviderFactory = Callable[[], DictionaryProvider]


# The engine exposes ``TargetResolver`` as a structural seam, so a substituted
# resolver satisfies this alias without inheriting anything and without a cast.
ResolverFactory = Callable[[], TargetResolver]

#: Retained for callers that describe any provider factory generically.
ProviderFactory = Callable[[], object]


class LookupWorker:
    """Own one pipeline and its provider instances for one executor thread."""

    def __init__(
        self,
        ocr_provider_factory: OCRProviderFactory,
        morphology_provider_factory: MorphologyProviderFactory,
        dictionary_provider_factory: DictionaryProviderFactory,
        *,
        word_resolver_factory: ResolverFactory | None = None,
        confidence_threshold: float | None = None,
        skip_flat_rois: bool = False,
        trace_sink: RuntimeTraceSink | None = None,
    ) -> None:
        for name, factory in (
            ("ocr_provider_factory", ocr_provider_factory),
            ("morphology_provider_factory", morphology_provider_factory),
            ("dictionary_provider_factory", dictionary_provider_factory),
        ):
            if not callable(factory):
                raise TypeError(f"{name} must be callable")
        if word_resolver_factory is not None and not callable(word_resolver_factory):
            raise TypeError("word_resolver_factory must be callable")
        providers: list[object] = []
        self._trace_wrappers: tuple[object, ...] = ()
        try:
            # These calls are intentionally in worker construction, not in the
            # composition root. JobExecutor invokes its worker factory on its
            # own thread.
            ocr_provider = ocr_provider_factory()
            providers.append(ocr_provider)
            morphology_provider = morphology_provider_factory()
            providers.append(morphology_provider)
            dictionary_provider = dictionary_provider_factory()
            providers.append(dictionary_provider)
            # Warming happens here, inside worker construction, so a provider
            # with lazy first-inference cost pays it before the executor
            # reports ready and hover starts capturing.
            _prewarm_provider(ocr_provider, "ocr", trace_sink)
            _prewarm_provider(morphology_provider, "morphology", trace_sink)
            resolver = (
                word_resolver_factory() if word_resolver_factory is not None else WordResolver()
            )
            # Caching sits under tracing so a hit reports as a real OCR stage
            # with a near-zero duration, which is what the developer overlay
            # shows.
            gated_ocr = (
                _TextPresenceGate(ocr_provider) if skip_flat_rois else ocr_provider
            )
            cached_ocr = _CachingOCRProvider(gated_ocr)
            traced_ocr = (
                _TracingOCRProvider(cached_ocr, trace_sink, ocr_path="full")
                if trace_sink is not None
                else cached_ocr
            )
            traced_morphology = (
                _TracingMorphologyProvider(morphology_provider, trace_sink)
                if trace_sink is not None
                else morphology_provider
            )
            traced_dictionary = (
                _TracingDictionaryProvider(dictionary_provider, trace_sink)
                if trace_sink is not None
                else dictionary_provider
            )
            traced_resolver = (
                _TracingResolver(resolver, trace_sink)
                if trace_sink is not None
                else resolver
            )
            self._pipeline = LookupPipeline(
                ocr_provider=traced_ocr,
                morphology_provider=traced_morphology,
                dictionary_provider=traced_dictionary,
                word_resolver=traced_resolver,
                confidence_threshold=confidence_threshold,
            )
            self._sensitive_pipeline = _sensitive_pipeline(
                ocr_provider,
                skip_flat_rois=skip_flat_rois,
                morphology_provider=traced_morphology,
                dictionary_provider=traced_dictionary,
                word_resolver=traced_resolver,
                confidence_threshold=confidence_threshold,
            )
            self._trace_wrappers = tuple(
                component
                for component in (
                    traced_ocr,
                    traced_resolver,
                    traced_morphology,
                    traced_dictionary,
                )
                if hasattr(component, "set_request")
            )
        except Exception:
            _close_providers(providers)
            raise
        self._providers = tuple(providers)
        self._closed = False
        self._trace_sink = trace_sink
        self._cache: OrderedDict[LookupCacheKey, LookupResult] = OrderedDict()

    @property
    def pipeline(self) -> LookupPipeline:
        """The pipeline owned by this worker (useful for focused diagnostics)."""

        return self._pipeline

    def __call__(self, item: LookupRequest) -> LookupResult:
        if not isinstance(item, LookupRequest):
            raise TypeError("lookup worker items must be LookupRequest values")
        if item.is_cancelled():
            raise LookupCancelled("lookup was superseded before worker execution")
        started_ns = _trace_clock()
        cache_key = _lookup_cache_key(item)
        cached = self._cache.get(cache_key)
        if cached is not None:
            self._cache.move_to_end(cache_key)
            emit_trace(
                self._trace_sink,
                "lookup_cache_hit",
                lookup_request_id=item.request_id,
                hover_request_id=item.hover_request_id,
                result_status=cached.status.value,
            )
            emit_trace(
                self._trace_sink,
                "lookup_stage_completed",
                stage="total_pipeline",
                lookup_request_id=item.request_id,
                hover_request_id=item.hover_request_id,
                duration_ns=_trace_clock() - started_ns,
                outcome=cached.status.value,
                cached=True,
            )
            return cached
        emit_trace(
            self._trace_sink,
            "lookup_cache_miss",
            lookup_request_id=item.request_id,
            hover_request_id=item.hover_request_id,
        )
        if self._trace_sink is None:
            result = self._lookup(item)
            self._remember(cache_key, result)
            return result

        for wrapper in self._trace_wrappers:
            set_request = getattr(wrapper, "set_request", None)
            if callable(set_request):
                set_request(item)

        try:
            result = self._lookup(item)
        except BaseException as error:
            emit_trace(
                self._trace_sink,
                "lookup_stage_error",
                stage="total_pipeline",
                lookup_request_id=item.request_id,
                hover_request_id=item.hover_request_id,
                duration_ns=_trace_clock() - started_ns,
                error_type=type(error).__name__,
            )
            raise
        emit_trace(
            self._trace_sink,
            "lookup_stage_completed",
            stage="total_pipeline",
            lookup_request_id=item.request_id,
            hover_request_id=item.hover_request_id,
            duration_ns=_trace_clock() - started_ns,
            outcome=result.status.value,
            cached=False,
        )
        self._remember(cache_key, result)
        return result

    def _lookup(self, item: LookupRequest) -> LookupResult:
        result = self._pipeline.lookup(
            item.image,
            item.target,
            cancelled=item.is_cancelled,
        )
        if self._sensitive_pipeline is None or not _nothing_was_read_at_target(result):
            return result

        # The cursor sits on something the ordinary detection pass did not
        # report as text at all, a lone Hangul syllable at a normal UI size is
        # the case that motivated this. One keener retry is worth its cost here
        # because it only runs when the alternative is showing the user nothing.
        emit_trace(
            self._trace_sink,
            "ocr_sensitive_retry",
            lookup_request_id=item.request_id,
            hover_request_id=item.hover_request_id,
        )
        retried = self._sensitive_pipeline.lookup(
            item.image,
            item.target,
            cancelled=item.is_cancelled,
        )
        return result if _nothing_was_read_at_target(retried) else retried

    def close(self) -> None:
        """Close all close-capable providers exactly once, in reverse order."""

        if self._closed:
            return
        self._closed = True
        self._cache.clear()
        _close_providers(self._providers)

    def _remember(self, key: LookupCacheKey, result: LookupResult) -> None:
        if result.status is LookupStatus.ERROR:
            return
        self._cache[key] = result
        self._cache.move_to_end(key)
        while len(self._cache) > _LOOKUP_CACHE_SIZE:
            self._cache.popitem(last=False)


def _nothing_was_read_at_target(result: LookupResult) -> bool:
    """Return whether detection reported nothing readable under the cursor.

    Two outcomes mean that. ``EMPTY`` is an ROI where detection found no text
    at all; ``UNUSABLE`` with no resolved text is an ROI where it found text
    elsewhere but none containing the cursor. ``UNUSABLE`` also covers text
    that carried no Hangul and text morphology could not reduce, those were
    read successfully and a keener pass would only read them again.
    """

    if result.status is LookupStatus.EMPTY:
        return True
    return (
        result.status is LookupStatus.UNUSABLE
        and result.context is not None
        and result.context.text is None
    )


def _sensitive_pipeline(
    ocr_provider: OCRProvider,
    *,
    skip_flat_rois: bool,
    morphology_provider: MorphologyProvider,
    dictionary_provider: DictionaryProvider,
    word_resolver: TargetResolver,
    confidence_threshold: float | None,
) -> LookupPipeline | None:
    """Build the retry pipeline, or ``None`` when the adapter offers no variant.

    Everything after OCR is shared with the primary pipeline; only the reading
    pass differs. The retry provider gets its own cache because it answers a
    different question about the same pixels.
    """

    variant = getattr(ocr_provider, "sensitive_variant", None)
    if not callable(variant):
        return None
    sensitive = variant()
    if sensitive is None:
        return None

    gated = _TextPresenceGate(sensitive) if skip_flat_rois else sensitive
    return LookupPipeline(
        ocr_provider=_CachingOCRProvider(gated),
        morphology_provider=morphology_provider,
        dictionary_provider=dictionary_provider,
        word_resolver=word_resolver,
        confidence_threshold=confidence_threshold,
    )


def create_lookup_worker_factory(
    ocr_provider_factory: OCRProviderFactory,
    morphology_provider_factory: MorphologyProviderFactory,
    dictionary_provider_factory: DictionaryProviderFactory,
    *,
    word_resolver_factory: ResolverFactory | None = None,
    confidence_threshold: float | None = None,
    skip_flat_rois: bool = False,
    trace_sink: RuntimeTraceSink | None = None,
) -> Callable[[], LookupWorker]:
    """Return a JobExecutor worker factory with deferred provider creation."""

    return lambda: LookupWorker(
        ocr_provider_factory=ocr_provider_factory,
        morphology_provider_factory=morphology_provider_factory,
        dictionary_provider_factory=dictionary_provider_factory,
        word_resolver_factory=word_resolver_factory,
        confidence_threshold=confidence_threshold,
        skip_flat_rois=skip_flat_rois,
        trace_sink=trace_sink,
    )


# ``build_*`` is the descriptive spelling used by composition roots; retain
# the create spelling above for callers that treat this as a factory function.
build_lookup_worker_factory = create_lookup_worker_factory


def create_lookup_controller(
    ocr_provider_factory: OCRProviderFactory,
    morphology_provider_factory: MorphologyProviderFactory,
    dictionary_provider_factory: DictionaryProviderFactory,
    on_result: Callable[[LookupResult], None] | None = None,
    *,
    word_resolver_factory: ResolverFactory | None = None,
    confidence_threshold: float | None = None,
    on_error: Callable[[LookupRequest, BaseException], None] | None = None,
    result_dispatcher: ResultDispatcher | None = None,
    thread_name: str | None = None,
    trace_sink: RuntimeTraceSink | None = None,
) -> LookupController:
    """Compose a controller whose providers are deferred to its worker thread."""

    worker_factory = create_lookup_worker_factory(
        ocr_provider_factory,
        morphology_provider_factory,
        dictionary_provider_factory,
        word_resolver_factory=word_resolver_factory,
        confidence_threshold=confidence_threshold,
        trace_sink=trace_sink,
    )
    return LookupController(
        worker_factory,
        on_result,
        on_error=on_error,
        result_dispatcher=result_dispatcher,
        thread_name=thread_name,
        trace_sink=trace_sink,
    )


build_lookup_controller = create_lookup_controller


def _trace_clock() -> int:
    from time import perf_counter_ns

    return perf_counter_ns()


def _prewarm_provider(
    provider: object,
    stage: str,
    trace_sink: RuntimeTraceSink | None,
) -> None:
    """Run an optional provider warm hook during worker construction."""

    prewarm = getattr(provider, "prewarm", None)
    if not callable(prewarm):
        return
    started_ns = _trace_clock()
    emit_trace(trace_sink, "provider_prewarm_started", stage=stage)
    try:
        prewarm()
    except BaseException as error:
        emit_trace(
            trace_sink,
            "provider_prewarm_error",
            stage=stage,
            duration_ns=_trace_clock() - started_ns,
            error_type=type(error).__name__,
        )
        raise
    emit_trace(
        trace_sink,
        "provider_prewarm_completed",
        stage=stage,
        duration_ns=_trace_clock() - started_ns,
    )


def _lookup_cache_key(request: LookupRequest) -> LookupCacheKey:
    image = request.image
    return (
        request.hover_request_id is not None,
        image.width,
        image.height,
        image.pixel_format.value,
        request.target.x,
        request.target.y,
        image.data,
    )


def _contains_hangul(value: str) -> bool:
    return any(
        "\u1100" <= character <= "\u11ff"
        or "\u3130" <= character <= "\u318f"
        or "\ua960" <= character <= "\ua97f"
        or "\uac00" <= character <= "\ud7ff"
        for character in value
    )


def _ocr_character_counts(results: Sequence[OCRResult]) -> dict[str, int]:
    counts = {
        "ocr_char_count": 0,
        "hangul_char_count": 0,
        "latin_char_count": 0,
        "digit_char_count": 0,
        "whitespace_char_count": 0,
        "punctuation_char_count": 0,
    }
    for result in results:
        if not isinstance(result, OCRResult):
            continue
        for character in result.text:
            counts["ocr_char_count"] += 1
            if _contains_hangul(character):
                counts["hangul_char_count"] += 1
            elif character.isascii() and character.isalpha():
                counts["latin_char_count"] += 1
            elif character.isdigit():
                counts["digit_char_count"] += 1
            elif character.isspace():
                counts["whitespace_char_count"] += 1
            elif not character.isalnum():
                counts["punctuation_char_count"] += 1
    return counts


class _TextPresenceGate:
    """Skip OCR for an ROI that holds no text-like structure at all.

    With a short hover delay most captures land on empty desktop, a flat window
    background, or an image with no writing, and each one otherwise costs a
    full OCR call. Sampling a coarse grid for sharp luminance transitions
    settles that in about a millisecond.

    The test is deliberately lopsided: it only refuses ROIs that are almost
    perfectly flat. Rejecting real text would make the popup silently stop
    working, which is far worse than occasionally running OCR over a busy
    photograph.
    """

    def __init__(self, provider: OCRProvider) -> None:
        self._provider = provider

    def recognize(self, image: ROIImage) -> tuple[OCRResult, ...]:
        if not _has_text_like_structure(image):
            return ()
        return tuple(self._provider.recognize(image))

    def prewarm(self) -> None:
        prewarm = getattr(self._provider, "prewarm", None)
        if callable(prewarm):
            prewarm()

    def close(self) -> None:
        close = getattr(self._provider, "close", None)
        if callable(close):
            close()


def _has_text_like_structure(image: ROIImage) -> bool:
    """Return whether a sampled grid shows enough sharp luminance transitions."""

    stride = image.bytes_per_pixel
    row_bytes = image.width * stride
    data = image.data
    if image.width < 2 or image.height < 1 or len(data) < row_bytes:
        return True

    column_step = max(1, image.width // _GATE_SAMPLES_PER_ROW)
    row_step = max(1, image.height // _GATE_SAMPLE_ROWS)

    transitions = 0
    for y in range(0, image.height, row_step):
        row_start = y * row_bytes
        previous = data[row_start]
        for x in range(column_step, image.width, column_step):
            value = data[row_start + x * stride]
            if abs(value - previous) >= _GATE_EDGE_DELTA:
                transitions += 1
                if transitions >= _GATE_MIN_TRANSITIONS:
                    return True
            previous = value
    return False


class _CachingOCRProvider:
    """Reuse a previous OCR result for a byte-identical ROI.

    OCR is ~99% of a lookup's cost, and capture snaps ROI origins to a grid
    (see :data:`~hanly_app.capture.DEFAULT_ROI_GRID`) precisely so that nearby
    cursor positions produce the same pixels. Caching here rather than around
    the whole lookup means a cursor moving to a different word inside an
    already-recognized ROI skips OCR while target resolution, morphology, and
    dictionary lookup still run — together under half a millisecond.

    The provider is confined to one worker thread, so no lock is needed.
    """

    def __init__(self, provider: OCRProvider) -> None:
        self._provider = provider
        self._cache: OrderedDict[_OCRCacheKey, tuple[OCRResult, ...]] = OrderedDict()
        self.last_recognition_was_cached = False

    def recognize(self, image: ROIImage) -> tuple[OCRResult, ...]:
        # Digest rather than the pixels themselves: a retained ROI is 60 KB of
        # whatever was on screen, and the cache has no reason to hold a copy of
        # it once the results are known.
        key = (
            image.width,
            image.height,
            image.pixel_format.value,
            blake2b(image.data, digest_size=16).digest(),
        )
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            self.last_recognition_was_cached = True
            return cached

        self.last_recognition_was_cached = False
        results = tuple(self._provider.recognize(image))
        self._cache[key] = results
        while len(self._cache) > _OCR_CACHE_SIZE:
            self._cache.popitem(last=False)
        return results

    def prewarm(self) -> None:
        prewarm = getattr(self._provider, "prewarm", None)
        if callable(prewarm):
            prewarm()

    def close(self) -> None:
        self._cache.clear()
        close = getattr(self._provider, "close", None)
        if callable(close):
            close()


class _TracingOCRProvider:
    def __init__(
        self,
        provider: OCRProvider,
        sink: RuntimeTraceSink,
        *,
        ocr_path: str,
    ) -> None:
        self._provider = provider
        self._sink = sink
        self._ocr_path = ocr_path
        self._request: LookupRequest | None = None

    def set_request(self, request: LookupRequest) -> None:
        self._request = request

    def recognize(self, image: ROIImage) -> Sequence[OCRResult]:
        request = self._request
        started_ns = _trace_clock()
        try:
            result = self._provider.recognize(image)
        except BaseException as error:
            _trace_stage_error(self._sink, "ocr", request, started_ns, error)
            raise
        regions = len(result) if isinstance(result, Sequence) else None
        hangul_regions = (
            sum(
                isinstance(item, OCRResult) and _contains_hangul(item.text)
                for item in result
            )
            if isinstance(result, Sequence)
            else None
        )
        character_counts = (
            _ocr_character_counts(result) if isinstance(result, Sequence) else {}
        )
        confidences = [
            item.confidence for item in result if isinstance(item, OCRResult)
        ]
        trace_fields: dict[str, JSONPrimitive] = {
            "ocr_path": self._ocr_path,
            "ocr_cached": getattr(
                self._provider, "last_recognition_was_cached", False
            ),
            "region_count": regions,
            "hangul_region_count": hangul_regions,
            "confidence_min": min(confidences) if confidences else None,
            "confidence_max": max(confidences) if confidences else None,
            "confidence_mean": (
                sum(confidences) / len(confidences) if confidences else None
            ),
            **character_counts,
        }
        if getattr(self._sink, "retain_text", False) is True:
            trace_fields["ocr_text"] = "\n".join(
                item.text for item in result if isinstance(item, OCRResult)
            )
        if getattr(self._sink, "retain_geometry", False) is True:
            trace_fields["ocr_boxes"] = _encoded_boxes(result)
        _trace_stage_completed(
            self._sink,
            "ocr",
            request,
            started_ns,
            **trace_fields,
        )
        return result


def _encoded_boxes(results: Sequence[object]) -> str:
    """Encode region boxes in provider reading order as ``l,t,r,b`` groups.

    Geometry carries no recognized characters, but it still describes where
    text sits on someone's screen, so it travels under its own opt-in beside
    ``retain_text`` rather than on every event.
    """

    return ";".join(
        f"{item.bounding_box.left},{item.bounding_box.top},"
        f"{item.bounding_box.right},{item.bounding_box.bottom}"
        for item in results
        if isinstance(item, OCRResult)
    )


class _TracingResolver:
    def __init__(self, resolver: TargetResolver, sink: RuntimeTraceSink) -> None:
        self._resolver = resolver
        self._sink = sink
        self._request: LookupRequest | None = None

    def set_request(self, request: LookupRequest) -> None:
        self._request = request

    def resolve_target(
        self,
        ocr_results: Sequence[OCRResult] | None,
        target: Point | None,
    ) -> tuple[OCRResult, str] | None:
        request = self._request
        started_ns = _trace_clock()
        try:
            result = self._resolver.resolve_target(ocr_results, target)
        except BaseException as error:
            _trace_stage_error(self._sink, "token_selection", request, started_ns, error)
            raise
        _trace_stage_completed(
            self._sink,
            "token_selection",
            request,
            started_ns,
            resolved=result is not None,
            candidate_count=len(ocr_results) if isinstance(ocr_results, Sequence) else None,
        )
        return result


class _TracingMorphologyProvider:
    def __init__(self, provider: MorphologyProvider, sink: RuntimeTraceSink) -> None:
        self._provider = provider
        self._sink = sink
        self._request: LookupRequest | None = None

    def set_request(self, request: LookupRequest) -> None:
        self._request = request

    def analyze(self, text: str) -> Sequence[TokenAnalysis]:
        request = self._request
        started_ns = _trace_clock()
        try:
            result = self._provider.analyze(text)
        except BaseException as error:
            _trace_stage_error(self._sink, "morphology", request, started_ns, error)
            raise
        _trace_stage_completed(
            self._sink,
            "morphology",
            request,
            started_ns,
            token_count=len(result) if isinstance(result, Sequence) else None,
            hangul_token_count=(
                sum(
                    isinstance(item, TokenAnalysis) and _contains_hangul(item.token)
                    for item in result
                )
                if isinstance(result, Sequence)
                else None
            ),
        )
        return result


class _TracingDictionaryProvider:
    def __init__(self, provider: DictionaryProvider, sink: RuntimeTraceSink) -> None:
        self._provider = provider
        self._sink = sink
        self._request: LookupRequest | None = None

    def set_request(self, request: LookupRequest) -> None:
        self._request = request

    def lookup(self, lemma: str) -> Sequence[DictionaryEntry]:
        request = self._request
        started_ns = _trace_clock()
        try:
            result = self._provider.lookup(lemma)
        except BaseException as error:
            _trace_stage_error(self._sink, "dictionary", request, started_ns, error)
            raise
        _trace_stage_completed(
            self._sink,
            "dictionary",
            request,
            started_ns,
            entry_count=len(result) if isinstance(result, Sequence) else None,
            found=bool(result) if isinstance(result, Sequence) else None,
        )
        return result


def _trace_stage_completed(
    sink: RuntimeTraceSink,
    stage: str,
    request: LookupRequest | None,
    started_ns: int,
    **fields: JSONPrimitive,
) -> None:
    emit_trace(
        sink,
        "lookup_stage_completed",
        stage=stage,
        lookup_request_id=request.request_id if request is not None else None,
        hover_request_id=request.hover_request_id if request is not None else None,
        duration_ns=_trace_clock() - started_ns,
        **fields,
    )


def _trace_stage_error(
    sink: RuntimeTraceSink,
    stage: str,
    request: LookupRequest | None,
    started_ns: int,
    error: BaseException,
) -> None:
    emit_trace(
        sink,
        "lookup_stage_error",
        stage=stage,
        lookup_request_id=request.request_id if request is not None else None,
        hover_request_id=request.hover_request_id if request is not None else None,
        duration_ns=_trace_clock() - started_ns,
        error_type=type(error).__name__,
    )


def _close_providers(providers: tuple[object, ...] | list[object]) -> None:
    first_error: Exception | None = None
    for provider in reversed(tuple(providers)):
        close = getattr(provider, "close", None)
        if not callable(close):
            continue
        try:
            close()
        except Exception as exc:
            # Make a best effort to close every provider.  Teardown failures
            # should not strand a SQLite connection because another provider
            # happened to fail its own cleanup.
            if first_error is None:
                first_error = exc
    if first_error is not None:
        raise first_error


__all__ = [
    "LookupWorker",
    "ProviderFactory",
    "ResolverFactory",
    "Worker",
    "build_lookup_worker_factory",
    "build_lookup_controller",
    "create_lookup_controller",
    "create_lookup_worker_factory",
]
