"""Focused worker-thread composition tests for the first app engine path."""

from __future__ import annotations

import threading
from collections.abc import Mapping, Sequence
from functools import partial
from pathlib import Path
from threading import Event
from typing import TypeVar

import hanly_app.composition as composition_module
from hanly import (
    BoundingBox,
    DictionaryEntry,
    LookupResult,
    LookupStatus,
    OCRResult,
    PixelFormat,
    Point,
    Quad,
    ROIImage,
    TargetResolution,
    TokenAnalysis,
)
from hanly.krdict_provider import KRDICTProvider
from hanly_app.composition import (
    LookupWorker,
    create_lookup_controller,
    create_lookup_worker_factory,
)
from hanly_app.diagnostics import DiagnosticLog, StartupTimeline
from hanly_app.job_executor import JobExecutor
from hanly_app.lookup_controller import LookupRequest

from tests.hanly_fixtures.krdict import build_fixture_krdict

_T = TypeVar("_T")

_IMAGE = ROIImage(1, 1, PixelFormat.GRAYSCALE_8, b"\x00")
_TARGET = Point(3, 4)
_OCR = OCRResult(
    text="책",
    confidence=0.99,
    quad=Quad.from_bounding_box(BoundingBox(0, 0, 10, 10)),
)


class _Provider:
    def __init__(self, kind: str, threads: dict[str, list[int]]) -> None:
        self.kind = kind
        self.threads = threads

    def close(self) -> None:
        self.threads.setdefault(f"close:{self.kind}", []).append(threading.get_ident())


class _OCRProvider(_Provider):
    def recognize(self, image: ROIImage):
        assert image is _IMAGE
        self.threads.setdefault("recognize", []).append(threading.get_ident())
        return (_OCR,)


class _MorphologyProvider(_Provider):
    def prewarm(self) -> None:
        self.threads.setdefault("prewarm:morphology", []).append(
            threading.get_ident()
        )

    def analyze(self, text: str):
        assert text == "책"
        return (TokenAnalysis(token="책", lemma="책"),)


class _DictionaryProvider(_Provider):
    def lookup(self, lemma: str):
        assert lemma == "책"
        return (DictionaryEntry(headword="책", definitions=("book",)),)


class _Resolver:
    def __init__(self, targets: list[Point]) -> None:
        self.targets = targets

    def resolve_target(
        self,
        ocr_results: Sequence[OCRResult] | None,
        target: Point | None,
    ) -> tuple[OCRResult, str] | None:
        assert ocr_results is not None and target is not None
        self.targets.append(target)
        return ocr_results[0], "책"


def test_provider_factories_and_close_run_on_executor_thread_and_point_is_exact() -> None:
    caller_thread = threading.get_ident()
    threads: dict[str, list[int]] = {}
    targets: list[Point] = []
    resolver = _Resolver(targets)

    def resolver_factory() -> _Resolver:
        return resolver

    def ocr_factory() -> _OCRProvider:
        threads.setdefault("factory:ocr", []).append(threading.get_ident())
        return _OCRProvider("ocr", threads)

    def morphology_factory() -> _MorphologyProvider:
        threads.setdefault("factory:morphology", []).append(threading.get_ident())
        return _MorphologyProvider("morphology", threads)

    def dictionary_factory() -> _DictionaryProvider:
        threads.setdefault("factory:dictionary", []).append(threading.get_ident())
        return _DictionaryProvider("dictionary", threads)

    results = []
    received = Event()
    worker_factory = create_lookup_worker_factory(
        ocr_factory,
        morphology_factory,
        dictionary_factory,
        word_resolver_factory=resolver_factory,
    )
    def receive(_request: LookupRequest, result) -> None:
        results.append(result)
        received.set()

    executor = JobExecutor(worker_factory, receive)
    executor.start()
    request = LookupRequest(1, _IMAGE, _TARGET)
    executor.submit(request)

    assert received.wait(timeout=2)
    executor.shutdown()

    worker_thread = executor.thread_ident
    assert worker_thread is not None
    assert worker_thread != caller_thread
    assert threads["factory:ocr"] == [worker_thread]
    assert threads["factory:morphology"] == [worker_thread]
    assert threads["factory:dictionary"] == [worker_thread]
    assert threads["prewarm:morphology"] == [worker_thread]
    assert threads["recognize"] == [worker_thread]
    assert threads["close:ocr"] == [worker_thread]
    assert threads["close:morphology"] == [worker_thread]
    assert threads["close:dictionary"] == [worker_thread]
    assert targets == [_TARGET]
    assert results[0].context is not None
    assert results[0].context.lemma == "책"


def test_real_krdict_connection_is_owned_by_the_lookup_worker(tmp_path: Path) -> None:
    database = build_fixture_krdict(tmp_path)
    results = []
    received = Event()

    def receive(result) -> None:
        results.append(result)
        received.set()

    controller = create_lookup_controller(
        lambda: _OCRProvider("ocr", {}),
        lambda: _MorphologyProvider("morphology", {}),
        lambda: KRDICTProvider(database),
        receive,
        word_resolver_factory=lambda: _Resolver([]),
    )
    controller.start()
    controller.submit(_IMAGE, _TARGET)

    assert received.wait(timeout=2)
    controller.stop()

    assert results[0].status is LookupStatus.SUCCESS
    assert results[0].entries[0].definitions == ("a book", "book")


def test_lookup_worker_reuses_exact_success_but_changed_pixels_rerun_ocr() -> None:
    calls: list[ROIImage] = []

    class OCR:
        def recognize(self, image: ROIImage) -> tuple[OCRResult, ...]:
            calls.append(image)
            return (_OCR,)

    worker = LookupWorker(
        OCR,
        lambda: _MorphologyProvider("morphology", {}),
        lambda: _DictionaryProvider("dictionary", {}),
        word_resolver_factory=lambda: _Resolver([]),
    )
    changed = ROIImage(1, 1, PixelFormat.GRAYSCALE_8, b"\xff")

    first = worker(LookupRequest(1, _IMAGE, _TARGET))
    repeated = worker(LookupRequest(2, _IMAGE, _TARGET))
    changed_result = worker(LookupRequest(3, changed, _TARGET))
    worker.close()

    assert first.status is LookupStatus.SUCCESS
    assert repeated == first
    assert changed_result.status is LookupStatus.SUCCESS
    assert calls == [_IMAGE, changed]


def test_lookup_worker_caches_exact_negative_ocr_result() -> None:
    calls = 0

    class EmptyOCR:
        def recognize(self, _image: ROIImage) -> tuple[OCRResult, ...]:
            nonlocal calls
            calls += 1
            return ()

    worker = LookupWorker(
        EmptyOCR,
        lambda: _MorphologyProvider("morphology", {}),
        lambda: _DictionaryProvider("dictionary", {}),
    )

    first = worker(LookupRequest(1, _IMAGE, _TARGET))
    repeated = worker(LookupRequest(2, _IMAGE, _TARGET))
    worker.close()

    assert first.status is LookupStatus.EMPTY
    assert repeated == first
    assert calls == 1


def _large_roi(width: int = 200, height: int = 100) -> ROIImage:
    return ROIImage(
        width,
        height,
        PixelFormat.GRAYSCALE_8,
        bytes(index % 256 for index in range(width * height)),
    )


def test_ocr_cache_serves_an_identical_roi_and_still_resolves_the_new_target() -> None:
    """The ROI is the expensive input, the target is not: moving the cursor to
    another word inside pixels already recognized must skip OCR and still
    resolve that other word."""

    calls: list[ROIImage] = []

    class TwoWordOCR:
        def recognize(self, image: ROIImage) -> tuple[OCRResult, ...]:
            calls.append(image)
            return (
                OCRResult("책", 0.99, Quad.from_bounding_box(BoundingBox(0, 0, 90, 100))),
                OCRResult("물", 0.99, Quad.from_bounding_box(BoundingBox(110, 0, 200, 100))),
            )

    class Morphology:
        def analyze(self, text: str) -> tuple[TokenAnalysis, ...]:
            return (TokenAnalysis(text, text),)

    class Dictionary:
        def lookup(self, lemma: str) -> tuple[DictionaryEntry, ...]:
            return (DictionaryEntry(headword=lemma, definitions=("x",)),)

    roi = _large_roi()
    worker = LookupWorker(TwoWordOCR, Morphology, Dictionary)
    first = worker(LookupRequest(1, roi, Point(40, 50)))
    second = worker(LookupRequest(2, roi, Point(160, 50)))
    worker.close()

    assert len(calls) == 1
    assert first.status is LookupStatus.SUCCESS
    assert second.status is LookupStatus.SUCCESS
    assert first.context is not None and first.context.lemma == "책"
    assert second.context is not None and second.context.lemma == "물"


def test_flat_roi_skips_ocr_only_when_the_gate_is_enabled() -> None:
    calls: list[ROIImage] = []

    class CountingOCR:
        def recognize(self, image: ROIImage) -> tuple[OCRResult, ...]:
            calls.append(image)
            return ()

    class Morphology:
        def analyze(self, text: str) -> tuple[TokenAnalysis, ...]:
            return ()

    class Dictionary:
        def lookup(self, _lemma: str) -> tuple[DictionaryEntry, ...]:
            return ()

    flat = ROIImage(200, 100, PixelFormat.GRAYSCALE_8, bytes(200 * 100))

    ungated = LookupWorker(CountingOCR, Morphology, Dictionary)
    assert ungated(LookupRequest(1, flat, Point(100, 50))).status is LookupStatus.EMPTY
    ungated.close()
    assert len(calls) == 1

    gated = LookupWorker(CountingOCR, Morphology, Dictionary, skip_flat_rois=True)
    assert gated(LookupRequest(2, flat, Point(100, 50))).status is LookupStatus.EMPTY
    gated.close()
    assert len(calls) == 1


def test_text_presence_gate_accepts_ordinary_and_low_contrast_text() -> None:
    """A wrong "nothing here" makes the popup silently stop working, so the gate
    must keep faint text on the OCR path."""

    def rendered(background: int, ink: int) -> ROIImage:
        pixels = bytearray([background] * (200 * 100))
        for row in range(40, 60):
            for column in range(20, 180, 4):
                pixels[row * 200 + column] = ink
        return ROIImage(200, 100, PixelFormat.GRAYSCALE_8, bytes(pixels))

    assert composition_module._has_text_like_structure(rendered(255, 0))
    assert composition_module._has_text_like_structure(rendered(0, 255))
    assert composition_module._has_text_like_structure(rendered(120, 170))
    assert not composition_module._has_text_like_structure(
        ROIImage(200, 100, PixelFormat.GRAYSCALE_8, bytes([200] * (200 * 100)))
    )


def test_a_cursor_on_undetected_text_gets_one_keener_retry() -> None:
    """A lone Hangul syllable at a normal UI size is below what the detector
    reports, so the first pass sees nothing where the cursor is. The retry is
    worth its cost only because the alternative is showing the user nothing."""

    class TwoPassOCR:
        def __init__(self) -> None:
            self.calls = 0
            self.sensitive_calls = 0

        def recognize(self, image: ROIImage) -> tuple[OCRResult, ...]:
            self.calls += 1
            return ()

        def sensitive_variant(self) -> TwoPassOCR._Sensitive:
            return TwoPassOCR._Sensitive(self)

        class _Sensitive:
            def __init__(self, owner: TwoPassOCR) -> None:
                self._owner = owner

            def recognize(self, image: ROIImage) -> tuple[OCRResult, ...]:
                self._owner.sensitive_calls += 1
                return (
                    OCRResult(
                        "책",
                        0.99,
                        Quad.from_bounding_box(
                            BoundingBox(0, 0, image.width, image.height)
                        ),
                    ),
                )

    ocr = TwoPassOCR()

    class Morphology:
        def analyze(self, text: str) -> tuple[TokenAnalysis, ...]:
            return (TokenAnalysis(text, "책"),)

    class Dictionary:
        def lookup(self, lemma: str) -> tuple[DictionaryEntry, ...]:
            return (DictionaryEntry(headword=lemma, definitions=("book",)),)

    worker = LookupWorker(lambda: ocr, Morphology, Dictionary)
    result = worker(LookupRequest(1, _large_roi(), Point(100, 50)))
    worker.close()

    assert result.status is LookupStatus.SUCCESS
    assert result.context is not None and result.context.lemma == "책"
    assert ocr.calls == 1
    assert ocr.sensitive_calls == 1


def test_text_that_was_read_but_rejected_is_not_retried() -> None:
    """Latin text and unreducible tokens were detected fine. Reading them again
    more slowly cannot change the answer."""

    class CountingOCR:
        def __init__(self) -> None:
            self.sensitive_calls = 0

        def recognize(self, image: ROIImage) -> tuple[OCRResult, ...]:
            return (
                OCRResult(
                    "hello",
                    0.99,
                    Quad.from_bounding_box(BoundingBox(0, 0, image.width, image.height)),
                ),
            )

        def sensitive_variant(self) -> CountingOCR:
            self.sensitive_calls += 1
            return self

    class Morphology:
        def analyze(self, text: str) -> tuple[TokenAnalysis, ...]:
            return (TokenAnalysis(text, text),)

    class Dictionary:
        def lookup(self, _lemma: str) -> tuple[DictionaryEntry, ...]:
            return ()

    ocr = CountingOCR()
    worker = LookupWorker(lambda: ocr, Morphology, Dictionary)
    result = worker(LookupRequest(1, _large_roi(), Point(100, 50)))
    worker.close()

    assert result.status is LookupStatus.UNUSABLE
    # Built once during construction, never invoked for this lookup.
    assert ocr.sensitive_calls == 1


def test_an_adapter_without_a_sensitive_variant_still_composes() -> None:
    class PlainOCR:
        def recognize(self, _image: ROIImage) -> tuple[OCRResult, ...]:
            return ()

    class Morphology:
        def analyze(self, text: str) -> tuple[TokenAnalysis, ...]:
            return ()

    class Dictionary:
        def lookup(self, _lemma: str) -> tuple[DictionaryEntry, ...]:
            return ()

    worker = LookupWorker(PlainOCR, Morphology, Dictionary)
    assert worker(LookupRequest(1, _large_roi(), Point(100, 50))).status is LookupStatus.EMPTY
    worker.close()


class _FakeStartupClock:
    """Advanced by the test, so no provider is ever really constructed here."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_worker_construction_reports_what_each_provider_cost() -> None:
    """The wait between an open window and a ready runtime is broken down."""

    clock = _FakeStartupClock()

    class WarmingOCR:
        def recognize(self, _image: ROIImage) -> tuple[OCRResult, ...]:
            return ()

        def prewarm(self) -> None:
            clock.advance(3.0)

    def ocr_factory() -> WarmingOCR:
        clock.advance(2.0)
        return WarmingOCR()

    log = DiagnosticLog()
    threads: dict[str, list[int]] = {}
    LookupWorker(
        ocr_factory,
        lambda: _MorphologyProvider("morphology", threads),
        lambda: _DictionaryProvider("dictionary", threads),
        timeline=StartupTimeline(log, clock=clock),
    )

    assert log.snapshot() == (
        "Startup: ocr provider: 2000 ms (ok)",
        "Startup: morphology provider: 0 ms (ok)",
        "Startup: dictionary provider: 0 ms (ok)",
        "Startup: ocr prewarm: 3000 ms (ok)",
        "Startup: morphology prewarm: 0 ms (ok)",
    )


# --- Traced/untraced parity -------------------------------------------------
#
# ``LookupPipeline`` probes the resolver for ``resolve_target_detail`` and falls
# back to the pair contract with ``cursor_index=0``. A tracing wrapper that does
# not forward the richer method therefore moves the pointer to the start of the
# resolved word, and the lookup selects a different lexical candidate with
# tracing on than with it off. These fixtures are the guard for that.

_COMPOUND = OCRResult(
    text="책상",
    confidence=0.95,
    quad=Quad.from_bounding_box(BoundingBox(0, 0, 20, 10)),
)
#: Inside the second syllable of ``책상``, so the pointer selects ``상``.
_SECOND_SYLLABLE = Point(15, 5)


class _CompoundOCR:
    def recognize(self, _image: ROIImage) -> tuple[OCRResult, ...]:
        return (_COMPOUND,)


class _SpannedMorphology:
    """Report the spans that make a pointer offset select a lexical unit."""

    def analyze(self, text: str) -> tuple[TokenAnalysis, ...]:
        assert text == "책상"
        return (
            TokenAnalysis(token="책", lemma="책", start=0, length=1),
            TokenAnalysis(token="상", lemma="상", start=1, length=1),
        )


class _RecordingDictionary:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def lookup(self, lemma: str) -> tuple[DictionaryEntry, ...]:
        self.queries.append(lemma)
        return (DictionaryEntry(headword=lemma, definitions=("a definition",)),)


class _RecordingSink:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def emit(self, event: Mapping[str, object]) -> None:
        self.events.append(dict(event))


def _identity(value: _T) -> _T:
    """Bind a fixture into a zero-argument factory without a late-bound lambda."""

    return value


class _PairOnlyResolver:
    """A substituted resolver that answers only the pair contract."""

    def __init__(self) -> None:
        self.calls = 0

    def resolve_target(
        self,
        ocr_results: Sequence[OCRResult] | None,
        target: Point | None,
    ) -> tuple[OCRResult, str] | None:
        self.calls += 1
        assert ocr_results is not None
        return ocr_results[0], ocr_results[0].text


def _compound_lookup(
    trace_sink: _RecordingSink | None,
) -> tuple[LookupResult, _RecordingDictionary]:
    dictionary = _RecordingDictionary()
    worker = LookupWorker(
        _CompoundOCR,
        _SpannedMorphology,
        lambda: dictionary,
        trace_sink=trace_sink,
    )
    try:
        return worker(LookupRequest(1, _IMAGE, _SECOND_SYLLABLE)), dictionary
    finally:
        worker.close()


def test_tracing_does_not_change_the_selected_candidate_or_queried_lemma() -> None:
    untraced, untraced_dictionary = _compound_lookup(None)
    traced, traced_dictionary = _compound_lookup(_RecordingSink())

    assert untraced_dictionary.queries == ["상"]
    assert traced_dictionary.queries == untraced_dictionary.queries
    assert traced.status is untraced.status is LookupStatus.SUCCESS
    assert traced.context is not None and untraced.context is not None
    assert traced.context.text == untraced.context.text == "책상"
    assert traced.context.lemma == untraced.context.lemma == "상"
    assert traced.context.candidate == untraced.context.candidate
    assert traced.context.selected_ocr == untraced.context.selected_ocr
    assert traced.context.word_region == untraced.context.word_region
    assert traced.entries == untraced.entries
    assert traced.diagnostics == untraced.diagnostics


def test_traced_token_selection_reports_the_resolved_pointer_offset() -> None:
    sink = _RecordingSink()
    _compound_lookup(sink)

    selection = [
        event
        for event in sink.events
        if event.get("stage") == "token_selection"
        and event.get("event_kind") == "lookup_stage_completed"
    ]
    assert len(selection) == 1
    assert selection[0]["resolved"] is True
    assert selection[0]["cursor_index"] == 1
    assert selection[0]["region_start"] == 0


def test_tracing_resolves_the_target_exactly_once() -> None:
    calls: list[Point | None] = []

    class CountingResolver:
        def resolve_target_detail(
            self,
            ocr_results: Sequence[OCRResult] | None,
            target: Point | None,
        ) -> TargetResolution | None:
            from hanly.word_resolver import WordResolver

            calls.append(target)
            return WordResolver.resolve_target_detail(ocr_results, target)

        def resolve_target(
            self,
            ocr_results: Sequence[OCRResult] | None,
            target: Point | None,
        ) -> tuple[OCRResult, str] | None:
            raise AssertionError("the richer contract must be preferred")

    worker = LookupWorker(
        _CompoundOCR,
        _SpannedMorphology,
        _RecordingDictionary,
        word_resolver_factory=CountingResolver,
        trace_sink=_RecordingSink(),
    )
    worker(LookupRequest(1, _IMAGE, _SECOND_SYLLABLE))
    worker.close()

    assert calls == [_SECOND_SYLLABLE]


def test_tracing_does_not_upgrade_a_pair_only_resolver() -> None:
    """A substituted resolver keeps its own contract under instrumentation."""

    untraced_resolver = _PairOnlyResolver()
    traced_resolver = _PairOnlyResolver()
    results: list[tuple[LookupResult, _RecordingDictionary]] = []
    sinks: tuple[_RecordingSink | None, ...] = (None, _RecordingSink())
    for resolver, sink in zip((untraced_resolver, traced_resolver), sinks):
        dictionary = _RecordingDictionary()
        worker = LookupWorker(
            _CompoundOCR,
            _SpannedMorphology,
            partial(_identity, dictionary),
            word_resolver_factory=partial(_identity, resolver),
            trace_sink=sink,
        )
        results.append((worker(LookupRequest(1, _IMAGE, _SECOND_SYLLABLE)), dictionary))
        worker.close()

    (untraced, untraced_dictionary), (traced, traced_dictionary) = results
    # The pair contract carries no pointer offset, so both paths fall back to
    # the start of the resolved word rather than one of them gaining an offset.
    assert untraced_dictionary.queries == ["책"]
    assert traced_dictionary.queries == ["책"]
    assert traced.context is not None and untraced.context is not None
    assert traced.context.candidate == untraced.context.candidate
    assert untraced_resolver.calls == traced_resolver.calls == 1


# --- Gate and cache decision evidence ---------------------------------------


def _ocr_stage_events(sink: _RecordingSink) -> list[dict[str, object]]:
    return [
        event
        for event in sink.events
        if event.get("event_kind") == "lookup_stage_completed"
        and event.get("stage") == "ocr"
    ]


def _events(sink: _RecordingSink, kind: str) -> list[dict[str, object]]:
    return [event for event in sink.events if event.get("event_kind") == kind]


def _flat_roi() -> ROIImage:
    return ROIImage(200, 100, PixelFormat.GRAYSCALE_8, bytes([200] * (200 * 100)))


def _text_roi(marker: int = 0) -> ROIImage:
    pixels = bytearray([255] * (200 * 100))
    for row in range(40, 60):
        for column in range(20, 180, 4):
            pixels[row * 200 + column] = 0
    pixels[0] = marker
    return ROIImage(200, 100, PixelFormat.GRAYSCALE_8, bytes(pixels))


class _EmptyMorphology:
    def analyze(self, _text: str) -> tuple[TokenAnalysis, ...]:
        return ()


class _EmptyDictionary:
    def lookup(self, _lemma: str) -> tuple[DictionaryEntry, ...]:
        return ()


class _CountingOCR:
    def __init__(self) -> None:
        self.calls: list[ROIImage] = []

    def recognize(self, image: ROIImage) -> tuple[OCRResult, ...]:
        self.calls.append(image)
        return ()


def test_a_rejected_flat_roi_is_reported_as_a_gate_decision_not_empty_ocr() -> None:
    sink = _RecordingSink()
    ocr = _CountingOCR()
    worker = LookupWorker(
        lambda: ocr,
        _EmptyMorphology,
        _EmptyDictionary,
        skip_flat_rois=True,
        trace_sink=sink,
    )
    assert worker(LookupRequest(1, _flat_roi(), Point(100, 50))).status is LookupStatus.EMPTY
    worker.close()

    assert ocr.calls == []
    (event,) = _ocr_stage_events(sink)
    assert event["gate_enabled"] is True
    assert event["gate_ran"] is True
    assert event["gate_passed"] is False
    assert event["provider_executed"] is False
    assert event["provider_skipped_reason"] == "gate_rejected"
    assert event["gate_method"] == "first_channel_row_delta"
    assert event["gate_sampled_channel"] == 0
    assert event["gate_pixel_format"] == PixelFormat.GRAYSCALE_8.value
    assert event["gate_delta_threshold"] == 32
    assert event["gate_transition_target"] == 8
    assert event["gate_observed_transitions"] == 0
    assert event["gate_malformed_safe_pass"] is False


def test_a_passing_gate_reports_its_early_exit_and_that_the_provider_ran() -> None:
    sink = _RecordingSink()
    ocr = _CountingOCR()
    worker = LookupWorker(
        lambda: ocr,
        _EmptyMorphology,
        _EmptyDictionary,
        skip_flat_rois=True,
        trace_sink=sink,
    )
    worker(LookupRequest(1, _text_roi(), Point(100, 50)))
    worker.close()

    assert len(ocr.calls) == 1
    (event,) = _ocr_stage_events(sink)
    assert event["gate_passed"] is True
    assert event["gate_early_exit"] is True
    assert event["gate_observed_transitions"] == 8
    assert event["provider_executed"] is True
    assert event["provider_skipped_reason"] is None


def test_a_gate_too_small_to_sample_passes_and_says_so() -> None:
    sink = _RecordingSink()
    ocr = _CountingOCR()
    worker = LookupWorker(
        lambda: ocr,
        _EmptyMorphology,
        _EmptyDictionary,
        skip_flat_rois=True,
        trace_sink=sink,
    )
    worker(LookupRequest(1, ROIImage(1, 1, PixelFormat.GRAYSCALE_8, b"\x10"), Point(0, 0)))
    worker.close()

    assert len(ocr.calls) == 1
    (event,) = _ocr_stage_events(sink)
    assert event["gate_malformed_safe_pass"] is True
    assert event["gate_passed"] is True
    assert event["gate_sampled_rows"] == 0
    assert event["provider_executed"] is True


def test_an_ocr_cache_hit_reports_no_gate_rather_than_the_previous_decision() -> None:
    """A bypassed gate must not answer with the last ROI it actually measured."""

    sink = _RecordingSink()
    ocr = _CountingOCR()
    worker = LookupWorker(
        lambda: ocr,
        _EmptyMorphology,
        _EmptyDictionary,
        skip_flat_rois=True,
        trace_sink=sink,
    )
    roi = _text_roi()
    # Different targets keep the full-result cache out of the way, so the second
    # lookup reaches the OCR cache rather than stopping before it.
    worker(LookupRequest(1, roi, Point(100, 50)))
    worker(LookupRequest(2, roi, Point(101, 50)))
    worker.close()

    assert len(ocr.calls) == 1
    first, second = _ocr_stage_events(sink)
    assert first["gate_ran"] is True and first["ocr_cache_hit"] is False
    assert second["gate_ran"] is False
    assert "gate_passed" not in second
    assert second["ocr_cache_hit"] is True
    assert second["provider_executed"] is False
    assert second["provider_skipped_reason"] == "ocr_cache_hit"
    assert second["ocr_image_fingerprint"] == first["ocr_image_fingerprint"]


def test_changed_pixels_produce_a_different_ocr_fingerprint_and_a_real_call() -> None:
    sink = _RecordingSink()
    ocr = _CountingOCR()
    worker = LookupWorker(
        lambda: ocr,
        _EmptyMorphology,
        _EmptyDictionary,
        trace_sink=sink,
    )
    worker(LookupRequest(1, _text_roi(marker=0), Point(100, 50)))
    worker(LookupRequest(2, _text_roi(marker=17), Point(100, 50)))
    worker.close()

    assert len(ocr.calls) == 2
    first, second = _ocr_stage_events(sink)
    assert first["ocr_image_fingerprint"] != second["ocr_image_fingerprint"]
    assert first["gate_enabled"] is second["gate_enabled"] is False
    assert first["gate_ran"] is second["gate_ran"] is False
    assert first["provider_executed"] is second["provider_executed"] is True


def test_a_full_result_cache_hit_reports_every_downstream_stage_skipped() -> None:
    sink = _RecordingSink()
    ocr = _CountingOCR()
    worker = LookupWorker(
        lambda: ocr,
        _EmptyMorphology,
        _EmptyDictionary,
        skip_flat_rois=True,
        trace_sink=sink,
    )
    roi = _text_roi()
    worker(LookupRequest(1, roi, Point(100, 50)))
    worker(LookupRequest(2, roi, Point(100, 50)))
    worker.close()

    assert len(ocr.calls) == 1
    # The repeat never reached OCR at all, so it emitted no OCR stage event.
    assert len(_ocr_stage_events(sink)) == 1
    (hit,) = _events(sink, "lookup_cache_hit")
    (miss,) = _events(sink, "lookup_cache_miss")
    assert hit["ocr_stage_skipped"] is True
    assert hit["provider_executed"] is False
    assert hit["provider_skipped_reason"] == "lookup_cache_hit"
    assert hit["lookup_cache_fingerprint"] == miss["lookup_cache_fingerprint"]


def test_a_cache_fingerprint_carries_no_pixels() -> None:
    roi = _text_roi()
    key = composition_module._lookup_cache_key(LookupRequest(1, roi, Point(100, 50)))
    fingerprint = composition_module._cache_key_fingerprint(key)

    assert isinstance(fingerprint, str)
    assert len(fingerprint) == 32
    assert roi.data.hex() not in fingerprint


def test_tracing_adds_no_persistence_and_no_result_change_to_the_gate_path() -> None:
    def run(sink: _RecordingSink | None) -> LookupResult:
        ocr = _CountingOCR()
        worker = LookupWorker(
            lambda: ocr,
            _EmptyMorphology,
            _EmptyDictionary,
            skip_flat_rois=True,
            trace_sink=sink,
        )
        try:
            return worker(LookupRequest(1, _flat_roi(), Point(100, 50)))
        finally:
            worker.close()

    assert run(None) == run(_RecordingSink())
