"""Focused worker-thread composition tests for the first app engine path."""

from __future__ import annotations

import threading
from collections.abc import Sequence
from pathlib import Path
from threading import Event

import hanly_app.composition as composition_module
from hanly import (
    BoundingBox,
    DictionaryEntry,
    LookupStatus,
    OCRResult,
    PixelFormat,
    Point,
    Quad,
    ROIImage,
    TokenAnalysis,
)
from hanly.krdict_provider import KRDICTProvider
from hanly_app.composition import (
    LookupWorker,
    create_lookup_controller,
    create_lookup_worker_factory,
)
from hanly_app.job_executor import JobExecutor
from hanly_app.lookup_controller import LookupRequest

from tests.hanly_fixtures.krdict import build_fixture_krdict

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
