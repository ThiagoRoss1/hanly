"""Application composition for the first Hanly engine worker.

Concrete provider construction intentionally happens in the executor worker
thread.  In particular, ``KRDICTProvider`` opens its SQLite connection there
and is closed there, preserving SQLite's thread affinity without changing the
engine adapter.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from hashlib import blake2b
from re import compile as re_compile
from typing import Protocol, cast

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
    TargetResolution,
    TokenAnalysis,
)
from hanly.errors import LookupCancelled
from hanly.word_resolver import ResolutionEvidence, TargetResolver, WordResolver

from .diagnostics import StartupTimeline
from .lookup_controller import LookupController, LookupRequest, ResultDispatcher
from .lookup_evidence import (
    encode_dictionary_evidence,
    encode_morphology_evidence,
    encode_ocr_evidence,
    encode_resolution_evidence,
)
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
#: A captured ROI keys on its pixels and target; direct text keys on the word
#: itself, so the two can never collide.
LookupCacheKey = tuple[bool, int, int, str, float, float, bytes] | tuple[bool, str, int]
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
        timeline: StartupTimeline | None = None,
        ocr_backend: str | None = None,
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
        # Construction and warming are the bulk of the wait between an opened
        # window and a ready runtime, so each one is timed by role.
        startup = timeline or StartupTimeline()
        try:
            # These calls are intentionally in worker construction, not in the
            # composition root. JobExecutor invokes its worker factory on its
            # own thread.
            with startup.phase("ocr provider"):
                ocr_provider = ocr_provider_factory()
            providers.append(ocr_provider)
            with startup.phase("morphology provider"):
                morphology_provider = morphology_provider_factory()
            providers.append(morphology_provider)
            with startup.phase("dictionary provider"):
                dictionary_provider = dictionary_provider_factory()
            providers.append(dictionary_provider)
            # Warming happens here, inside worker construction, so a provider
            # with lazy first-inference cost pays it before the executor
            # reports ready and hover starts capturing.
            _prewarm_provider(ocr_provider, "ocr", trace_sink, startup)
            _prewarm_provider(morphology_provider, "morphology", trace_sink, startup)
            resolver = (
                word_resolver_factory() if word_resolver_factory is not None else WordResolver()
            )
            # Caching sits under tracing so a hit reports as a real OCR stage
            # with a near-zero duration, which is what the developer overlay
            # shows.
            gate = _TextPresenceGate(ocr_provider) if skip_flat_rois else None
            cached_ocr = _CachingOCRProvider(
                gate if gate is not None else ocr_provider
            )
            self._ocr_path = _OCRPathObserver(cached_ocr, gate)
            traced_ocr = (
                _TracingOCRProvider(
                    cached_ocr,
                    trace_sink,
                    ocr_path="full",
                    observer=self._ocr_path,
                    backend=ocr_backend,
                )
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
                _traced_resolver(resolver, trace_sink)
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
        # Every downstream decision is re-observed from scratch, so a stage this
        # lookup never reached reports nothing rather than the previous answer.
        self._ocr_path.forget()
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
                lookup_cache_fingerprint=_cache_key_fingerprint(cache_key),
                ocr_stage_skipped=True,
                provider_executed=False,
                provider_skipped_reason="lookup_cache_hit",
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
            lookup_cache_fingerprint=_cache_key_fingerprint(cache_key),
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
        if item.selection is not None:
            # The desktop already read this word, so there is nothing to
            # recognize. The OCR provider is not consulted at all, and a
            # dictionary miss here stays a miss rather than falling into OCR.
            emit_trace(
                self._trace_sink,
                "lookup_acquisition",
                lookup_request_id=item.request_id,
                hover_request_id=item.hover_request_id,
                acquisition_source=_acquisition_label(item.selection.source),
                ocr_stage_skipped=True,
            )
            return self._pipeline.lookup_selection(
                item.selection, cancelled=item.is_cancelled
            )

        assert item.image is not None
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
    timeline: StartupTimeline | None = None,
    ocr_backend: str | None = None,
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
        timeline=timeline,
        ocr_backend=ocr_backend,
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
    on_initialization_error: Callable[[BaseException], None] | None = None,
    result_dispatcher: ResultDispatcher | None = None,
    thread_name: str | None = None,
    trace_sink: RuntimeTraceSink | None = None,
    timeline: StartupTimeline | None = None,
) -> LookupController:
    """Compose a controller whose providers are deferred to its worker thread."""

    worker_factory = create_lookup_worker_factory(
        ocr_provider_factory,
        morphology_provider_factory,
        dictionary_provider_factory,
        word_resolver_factory=word_resolver_factory,
        confidence_threshold=confidence_threshold,
        trace_sink=trace_sink,
        timeline=timeline,
    )
    return LookupController(
        worker_factory,
        on_result,
        on_error=on_error,
        on_initialization_error=on_initialization_error,
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
    timeline: StartupTimeline | None = None,
) -> None:
    """Run an optional provider warm hook during worker construction."""

    prewarm = getattr(provider, "prewarm", None)
    if not callable(prewarm):
        return
    startup = timeline or StartupTimeline()
    started_ns = _trace_clock()
    emit_trace(trace_sink, "provider_prewarm_started", stage=stage)
    try:
        with startup.phase(f"{stage} prewarm"):
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


#: An acquisition label names a route, not content. Anything else is reported
#: as unknown rather than copied into a trace, so a caller cannot make the
#: trace carry recognized text or grow without bound through this field.
_LABEL_PATTERN = re_compile(r"\A[A-Za-z0-9_-]{1,32}\Z")


def _acquisition_label(source: str | None) -> str | None:
    """The route a selection came from, bounded and free of content."""

    if source is None:
        return None
    return source if _LABEL_PATTERN.match(source) else "unknown"


def _cache_key_fingerprint(key: LookupCacheKey) -> str:
    """Identify a cache key without carrying what it holds.

    A captured key holds pixels and a direct key holds the word that was read.
    Both are private, so a trace only ever receives this digest of them.
    """

    if len(key) == 3:
        hover, text, cursor_index = key
        digest = blake2b(str(text).encode("utf-8"), digest_size=16)
        digest.update(f"|direct|{hover}|{cursor_index}".encode())
        return digest.hexdigest()

    hover, width, height, pixel_format, target_x, target_y, data = key
    digest = blake2b(data, digest_size=16)
    digest.update(
        f"|{hover}|{width}|{height}|{pixel_format}|{target_x!r}|{target_y!r}".encode()
    )
    return digest.hexdigest()


def _lookup_cache_key(request: LookupRequest) -> LookupCacheKey:
    if request.selection is not None:
        # Direct text is its own cache identity: the same word read the same
        # way answers the same, and no pixels were involved to key on.
        return (
            request.hover_request_id is not None,
            request.selection.text,
            request.selection.cursor_index,
        )

    image = request.image
    assert image is not None
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


@dataclass(frozen=True, slots=True)
class _GateMeasurement:
    """One text-presence decision together with every input that produced it.

    The decision and its inputs are one immutable value so a diagnostic cannot
    report a threshold, a sample count, and a verdict that were never part of
    the same calculation.
    """

    pixel_format: str
    sampled_channel: int
    method: str
    row_step: int
    column_step: int
    sampled_rows: int
    sampled_columns: int
    delta_threshold: int
    transition_target: int
    observed_transitions: int
    passed: bool
    malformed: bool

    @property
    def early_exit(self) -> bool:
        """Whether sampling stopped as soon as the target was reached."""

        return self.passed and not self.malformed


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
        self.last_measurement: _GateMeasurement | None = None

    def forget(self) -> None:
        """Drop the previous decision so a bypassed gate reports nothing.

        Without this a lookup served from the OCR cache would report whichever
        ROI the gate last actually measured, which is a different request's
        answer to a question this one never asked.
        """

        self.last_measurement = None

    def recognize(self, image: ROIImage) -> tuple[OCRResult, ...]:
        measurement = _measure_text_presence(image)
        self.last_measurement = measurement
        if not measurement.passed:
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


def _measure_text_presence(image: ROIImage) -> _GateMeasurement:
    """Sample a coarse grid for sharp luminance transitions and report both.

    The algorithm is unchanged: the first byte of each sampled pixel stands in
    for luminance, and an ROI too small or too short to sample is passed rather
    than refused.
    """

    stride = image.bytes_per_pixel
    row_bytes = image.width * stride
    data = image.data
    malformed = image.width < 2 or image.height < 1 or len(data) < row_bytes
    column_step = max(1, image.width // _GATE_SAMPLES_PER_ROW)
    row_step = max(1, image.height // _GATE_SAMPLE_ROWS)

    def measured(
        transitions: int, rows: int, columns: int, passed: bool
    ) -> _GateMeasurement:
        return _GateMeasurement(
            pixel_format=image.pixel_format.value,
            sampled_channel=0,
            method="first_channel_row_delta",
            row_step=row_step,
            column_step=column_step,
            sampled_rows=rows,
            sampled_columns=columns,
            delta_threshold=_GATE_EDGE_DELTA,
            transition_target=_GATE_MIN_TRANSITIONS,
            observed_transitions=transitions,
            passed=passed,
            malformed=malformed,
        )

    if malformed:
        return measured(0, 0, 0, True)

    transitions = 0
    sampled_rows = 0
    sampled_columns = 0
    for y in range(0, image.height, row_step):
        row_start = y * row_bytes
        previous = data[row_start]
        sampled_rows += 1
        for x in range(column_step, image.width, column_step):
            value = data[row_start + x * stride]
            sampled_columns += 1
            if abs(value - previous) >= _GATE_EDGE_DELTA:
                transitions += 1
                if transitions >= _GATE_MIN_TRANSITIONS:
                    return measured(transitions, sampled_rows, sampled_columns, True)
            previous = value
    return measured(transitions, sampled_rows, sampled_columns, False)


def _has_text_like_structure(image: ROIImage) -> bool:
    """Return whether a sampled grid shows enough sharp luminance transitions."""

    return _measure_text_presence(image).passed


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
        self.last_image_fingerprint: str | None = None

    def forget(self) -> None:
        """Drop the previous decision so an unreached cache reports nothing."""

        self.last_recognition_was_cached = False
        self.last_image_fingerprint = None

    def recognize(self, image: ROIImage) -> tuple[OCRResult, ...]:
        # Digest rather than the pixels themselves: a retained ROI is 60 KB of
        # whatever was on screen, and the cache has no reason to hold a copy of
        # it once the results are known.
        digest = blake2b(image.data, digest_size=16).digest()
        key = (
            image.width,
            image.height,
            image.pixel_format.value,
            digest,
        )
        self.last_image_fingerprint = digest.hex()
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


class _OCRPathObserver:
    """Report which of the gate, the OCR cache, and the provider actually ran.

    An empty OCR result has three very different causes -- a rejected flat ROI,
    a reused earlier answer, and a provider that genuinely read nothing -- and
    they are indistinguishable from the result alone.
    """

    def __init__(
        self, cache: _CachingOCRProvider, gate: _TextPresenceGate | None
    ) -> None:
        self._cache = cache
        self._gate = gate

    def forget(self) -> None:
        """Clear every recorded decision before a lookup begins."""

        self._cache.forget()
        if self._gate is not None:
            self._gate.forget()

    def describe(self) -> dict[str, JSONPrimitive]:
        """Summarize this lookup's OCR-path decisions as trace primitives."""

        cached = self._cache.last_recognition_was_cached
        fields: dict[str, JSONPrimitive] = {
            "ocr_cache_consulted": self._cache.last_image_fingerprint is not None,
            "ocr_cache_hit": cached,
            "ocr_image_fingerprint": self._cache.last_image_fingerprint,
            "gate_enabled": self._gate is not None,
        }
        measurement = self._gate.last_measurement if self._gate is not None else None
        fields["gate_ran"] = measurement is not None
        if measurement is not None:
            fields.update(
                {
                    "gate_pixel_format": measurement.pixel_format,
                    "gate_sampled_channel": measurement.sampled_channel,
                    "gate_method": measurement.method,
                    "gate_row_step": measurement.row_step,
                    "gate_column_step": measurement.column_step,
                    "gate_sampled_rows": measurement.sampled_rows,
                    "gate_sampled_columns": measurement.sampled_columns,
                    "gate_delta_threshold": measurement.delta_threshold,
                    "gate_transition_target": measurement.transition_target,
                    "gate_observed_transitions": measurement.observed_transitions,
                    "gate_passed": measurement.passed,
                    "gate_malformed_safe_pass": measurement.malformed,
                    "gate_early_exit": measurement.early_exit,
                }
            )
        fields["provider_executed"] = (
            not cached and (measurement is None or measurement.passed)
        )
        fields["provider_skipped_reason"] = _provider_skipped_reason(cached, measurement)
        return fields


def _provider_skipped_reason(
    cached: bool, measurement: _GateMeasurement | None
) -> str | None:
    if cached:
        return "ocr_cache_hit"
    if measurement is not None and not measurement.passed:
        return "gate_rejected"
    return None


class _TracingOCRProvider:
    def __init__(
        self,
        provider: OCRProvider,
        sink: RuntimeTraceSink,
        *,
        ocr_path: str,
        observer: _OCRPathObserver | None = None,
        backend: str | None = None,
    ) -> None:
        self._provider = provider
        self._sink = sink
        self._ocr_path = ocr_path
        self._observer = observer
        # Which recognizer actually read these pixels. It travels with the
        # result rather than being inferred later from configuration, which on
        # an ``auto`` runtime resolves differently per machine.
        self._backend = backend
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
            "ocr_backend": self._backend,
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
        if _wants_evidence(self._sink) and isinstance(result, Sequence):
            trace_fields["ocr_evidence"] = encode_ocr_evidence(
                [item for item in result if isinstance(item, OCRResult)]
            )
        if self._observer is not None:
            trace_fields.update(self._observer.describe())
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

    def word_bounds(self, region: OCRResult, target: Point) -> object:
        """Forward the resolver's optional geometry; tracing must not hide it."""

        bounds = getattr(self._resolver, "word_bounds", None)
        return bounds(region, target) if callable(bounds) else None

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


class _TracingDetailResolver(_TracingResolver):
    """Tracing for a resolver that answers the richer pointer-offset contract.

    :meth:`LookupPipeline._resolve_target` probes for ``resolve_target_detail``
    and falls back to the pair contract with ``cursor_index=0`` when it is
    absent. A wrapper that dropped the method therefore moved the pointer to the
    start of the resolved word, which is exactly the divergence instrumentation
    must not introduce.

    When the resolver can also explain itself, the explanation comes from the
    same call that produced the answer rather than from a second pass.
    """

    def resolve_target_detail(
        self,
        ocr_results: Sequence[OCRResult] | None,
        target: Point | None,
    ) -> TargetResolution | None:
        request = self._request
        started_ns = _trace_clock()
        try:
            resolution, evidence = self._resolve(ocr_results, target)
        except BaseException as error:
            _trace_stage_error(self._sink, "token_selection", request, started_ns, error)
            raise

        fields: dict[str, JSONPrimitive] = {
            "resolved": resolution is not None,
            "candidate_count": (
                len(ocr_results) if isinstance(ocr_results, Sequence) else None
            ),
            "cursor_index": resolution.cursor_index if resolution is not None else None,
            "region_start": resolution.region_start if resolution is not None else None,
        }
        if evidence is not None:
            fields["resolution_reason"] = evidence.reason
            fields["selected_region_index"] = evidence.selected_index
            fields["horizontal_fraction"] = evidence.horizontal_fraction
            fields["character_index"] = evidence.character_index
            if _wants_evidence(self._sink):
                fields["resolution_evidence"] = encode_resolution_evidence(evidence)
        _trace_stage_completed(
            self._sink, "token_selection", request, started_ns, **fields
        )
        return resolution

    def _resolve(
        self,
        ocr_results: Sequence[OCRResult] | None,
        target: Point | None,
    ) -> tuple[TargetResolution | None, ResolutionEvidence | None]:
        """Resolve once, preferring the form that also explains the answer."""

        explain = getattr(self._resolver, "resolve_target_evidence", None)
        if callable(explain):
            evidence = cast(ResolutionEvidence, explain(ocr_results, target))
            return evidence.resolution, evidence

        detail = getattr(self._resolver, "resolve_target_detail")
        return cast(TargetResolution | None, detail(ocr_results, target)), None


def _wants_evidence(sink: RuntimeTraceSink) -> bool:
    """Whether this sink asked for the full, private diagnostic structures."""

    return getattr(sink, "retain_evidence", False) is True


def _traced_resolver(resolver: TargetResolver, sink: RuntimeTraceSink) -> TargetResolver:
    """Wrap a resolver in exactly the contract it already implements.

    Defining ``resolve_target_detail`` unconditionally would silently upgrade a
    substituted pair-only resolver, which is the same class of semantic change
    in the opposite direction.
    """

    if callable(getattr(resolver, "resolve_target_detail", None)):
        return _TracingDetailResolver(resolver, sink)
    return _TracingResolver(resolver, sink)


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
        fields: dict[str, JSONPrimitive] = {
            "token_count": len(result) if isinstance(result, Sequence) else None,
            "hangul_token_count": (
                sum(
                    isinstance(item, TokenAnalysis) and _contains_hangul(item.token)
                    for item in result
                )
                if isinstance(result, Sequence)
                else None
            ),
        }
        if _wants_evidence(self._sink):
            fields["morphology_evidence"] = encode_morphology_evidence(text, result)
        _trace_stage_completed(
            self._sink, "morphology", request, started_ns, **fields
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
        entry_count = len(result) if isinstance(result, Sequence) else None
        fields: dict[str, JSONPrimitive] = {
            "entry_count": entry_count,
            "found": bool(result) if isinstance(result, Sequence) else None,
        }
        if _wants_evidence(self._sink):
            fields["dictionary_evidence"] = encode_dictionary_evidence(
                lemma, entry_count or 0
            )
        _trace_stage_completed(
            self._sink, "dictionary", request, started_ns, **fields
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
