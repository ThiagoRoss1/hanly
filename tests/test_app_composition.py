"""Focused worker-thread composition tests for the first app engine path."""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from threading import Event

import hanly_app.composition as composition_module
import pytest
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
from hanly.errors import LookupCancelled
from hanly.krdict_build import build_krdict_database
from hanly.krdict_provider import KRDICTProvider
from hanly.paddleocr_provider import TextRecognitionResult
from hanly_app.composition import (
    LookupWorker,
    _crop_hover_roi,
    create_lookup_controller,
    create_lookup_worker_factory,
)
from hanly_app.job_executor import JobExecutor
from hanly_app.lookup_controller import LookupRequest

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
    source = tmp_path / "krdict.xml"
    source.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<dictionary>
  <entry>
    <headword>책</headword>
    <part_of_speech>명사</part_of_speech>
    <sense>
      <translation><language>English</language><trans_dfn>book</trans_dfn></translation>
    </sense>
  </entry>
</dictionary>
""",
        encoding="utf-8",
    )
    database = build_krdict_database(source, tmp_path / "krdict.sqlite3")
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
    assert results[0].entries[0].definitions == ("book",)


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


def test_hover_crop_preserves_exact_pixels_and_marks_shifted_edges_unreliable() -> None:
    image = _large_roi()

    centered = _crop_hover_roi(image, Point(100.0, 50.0))
    left = _crop_hover_roi(image, Point(2.0, 50.0))
    top = _crop_hover_roi(image, Point(100.0, 2.0))
    right = _crop_hover_roi(image, Point(198.0, 50.0))
    bottom = _crop_hover_roi(image, Point(100.0, 98.0))

    assert (centered.image.width, centered.image.height) == (96, 32)
    assert centered.target == Point(48.0, 16.0)
    assert centered.cursor_centered is True
    expected = b"".join(
        image.data[row * image.width + 52 : row * image.width + 148]
        for row in range(34, 66)
    )
    assert centered.image.data == expected
    assert [crop.cursor_centered for crop in (left, top, right, bottom)] == [
        False,
        False,
        False,
        False,
    ]
    assert left.target.x == 2.0
    assert top.target.y == 2.0
    assert right.target.x == 94.0
    assert bottom.target.y == 30.0


class _FastTextProvider(_Provider):
    def __init__(
        self,
        result: TextRecognitionResult | None,
        calls: list[ROIImage],
        *,
        after_recognition: Callable[[], None] | None = None,
    ) -> None:
        super().__init__("fast", {})
        self._result = result
        self._calls = calls
        self._after_recognition = after_recognition

    def prewarm(self) -> None:
        return None

    def recognize_text(self, image: ROIImage) -> TextRecognitionResult | None:
        self._calls.append(image)
        if self._after_recognition is not None:
            self._after_recognition()
        return self._result


def _hover_worker(
    fast_provider_factory,
    *,
    full_calls: list[ROIImage],
    morphology_calls: list[str] | None = None,
    dictionary_calls: list[str] | None = None,
) -> LookupWorker:
    morphology_log = morphology_calls if morphology_calls is not None else []
    dictionary_log = dictionary_calls if dictionary_calls is not None else []

    class FullOCR:
        def recognize(self, image: ROIImage) -> tuple[OCRResult, ...]:
            full_calls.append(image)
            return (
                OCRResult(
                    "책",
                    0.99,
                    Quad.from_bounding_box(BoundingBox(0, 0, image.width, image.height)),
                ),
            )

    class Morphology:
        def analyze(self, text: str) -> tuple[TokenAnalysis, ...]:
            morphology_log.append(text)
            return (TokenAnalysis(text, "책"),)

    class Dictionary:
        def lookup(self, lemma: str) -> tuple[DictionaryEntry, ...]:
            dictionary_log.append(lemma)
            return (DictionaryEntry("책", ("book",)),)

    return LookupWorker(
        FullOCR,
        Morphology,
        Dictionary,
        hover_text_recognition_provider_factory=fast_provider_factory,
    )


def test_clear_hangul_hover_uses_fast_path_without_full_ocr() -> None:
    fast_calls: list[ROIImage] = []
    full_calls: list[ROIImage] = []
    worker = _hover_worker(
        lambda: _FastTextProvider(TextRecognitionResult("책", 0.99), fast_calls),
        full_calls=full_calls,
    )

    result = worker(LookupRequest(1, _large_roi(), Point(100, 50), hover_request_id=1))
    worker.close()

    assert result.status is LookupStatus.SUCCESS
    assert len(fast_calls) == 1
    assert (fast_calls[0].width, fast_calls[0].height) == (96, 32)
    assert full_calls == []


def test_non_hangul_fast_result_stops_before_full_ocr_and_downstream() -> None:
    fast_calls: list[ROIImage] = []
    full_calls: list[ROIImage] = []
    morphology_calls: list[str] = []
    dictionary_calls: list[str] = []
    worker = _hover_worker(
        lambda: _FastTextProvider(TextRecognitionResult("Settings", 0.99), fast_calls),
        full_calls=full_calls,
        morphology_calls=morphology_calls,
        dictionary_calls=dictionary_calls,
    )

    result = worker(LookupRequest(1, _large_roi(), Point(100, 50), hover_request_id=1))
    worker.close()

    assert result.status is LookupStatus.UNUSABLE
    assert full_calls == []
    assert morphology_calls == []
    assert dictionary_calls == []


@pytest.mark.parametrize(
    "fast_result",
    [
        TextRecognitionResult("책 학교", 0.99),
        TextRecognitionResult("책book", 0.99),
        TextRecognitionResult("책", 0.40),
    ],
)
def test_unreliable_fast_results_fallback_to_full_ocr_once(
    fast_result: TextRecognitionResult | None,
) -> None:
    fast_calls: list[ROIImage] = []
    full_calls: list[ROIImage] = []
    worker = _hover_worker(
        lambda: _FastTextProvider(fast_result, fast_calls),
        full_calls=full_calls,
    )

    result = worker(LookupRequest(1, _large_roi(), Point(100, 50), hover_request_id=1))
    worker.close()

    assert result.status is LookupStatus.SUCCESS
    assert len(fast_calls) == 1
    assert len(full_calls) == 1


@pytest.mark.parametrize(
    "fast_result",
    [None, TextRecognitionResult("", 0.0)],
)
def test_blank_fast_result_stops_without_fallback_or_downstream(
    fast_result: TextRecognitionResult | None,
) -> None:
    fast_calls: list[ROIImage] = []
    full_calls: list[ROIImage] = []
    morphology_calls: list[str] = []
    dictionary_calls: list[str] = []
    worker = _hover_worker(
        lambda: _FastTextProvider(fast_result, fast_calls),
        full_calls=full_calls,
        morphology_calls=morphology_calls,
        dictionary_calls=dictionary_calls,
    )

    result = worker(LookupRequest(1, _large_roi(), Point(100, 50), hover_request_id=1))
    worker.close()

    assert result.status is LookupStatus.EMPTY
    assert len(fast_calls) == 1
    assert full_calls == []
    assert morphology_calls == []
    assert dictionary_calls == []


def test_cursor_near_roi_edge_bypasses_fast_recognition_and_falls_back_once() -> None:
    fast_calls: list[ROIImage] = []
    full_calls: list[ROIImage] = []
    worker = _hover_worker(
        lambda: _FastTextProvider(TextRecognitionResult("책", 0.99), fast_calls),
        full_calls=full_calls,
    )

    result = worker(LookupRequest(1, _large_roi(), Point(2, 50), hover_request_id=1))
    worker.close()

    assert result.status is LookupStatus.SUCCESS
    assert fast_calls == []
    assert len(full_calls) == 1


def test_hover_cache_reuses_exact_pixels_but_changed_pixels_rerun_fast_ocr() -> None:
    fast_calls: list[ROIImage] = []
    full_calls: list[ROIImage] = []
    worker = _hover_worker(
        lambda: _FastTextProvider(
            TextRecognitionResult("Settings", 0.99), fast_calls
        ),
        full_calls=full_calls,
    )
    image = _large_roi()
    changed = ROIImage(
        image.width,
        image.height,
        image.pixel_format,
        image.data[:-1] + bytes([image.data[-1] ^ 0xFF]),
    )

    first = worker(LookupRequest(1, image, Point(100, 50), hover_request_id=1))
    repeated = worker(LookupRequest(2, image, Point(100, 50), hover_request_id=2))
    changed_result = worker(
        LookupRequest(3, changed, Point(100, 50), hover_request_id=3)
    )
    worker.close()

    assert first.status is LookupStatus.UNUSABLE
    assert repeated == first
    assert changed_result.status is LookupStatus.UNUSABLE
    assert len(fast_calls) == 2
    assert full_calls == []


def test_unsuccessful_hangul_lookup_falls_back_once_and_manual_bypasses_fast() -> None:
    fast_calls: list[ROIImage] = []
    full_calls: list[ROIImage] = []

    class EmptyDictionary:
        def lookup(self, _lemma: str) -> tuple[DictionaryEntry, ...]:
            return ()

    class FullOCR:
        def recognize(self, image: ROIImage) -> tuple[OCRResult, ...]:
            full_calls.append(image)
            return (
                OCRResult(
                    "책",
                    0.99,
                    Quad.from_bounding_box(
                        BoundingBox(0, 0, image.width, image.height)
                    ),
                ),
            )

    class Morphology:
        def analyze(self, text: str) -> tuple[TokenAnalysis, ...]:
            return (TokenAnalysis(text, "책"),)

    worker = LookupWorker(
        FullOCR,
        Morphology,
        EmptyDictionary,
        hover_text_recognition_provider_factory=lambda: _FastTextProvider(
            TextRecognitionResult("책", 0.99), fast_calls
        ),
    )

    hover = worker(LookupRequest(1, _large_roi(), Point(100, 50), hover_request_id=1))
    manual = worker(LookupRequest(2, _large_roi(), Point(100, 50)))
    worker.close()

    assert hover.status is LookupStatus.NOT_FOUND
    assert manual.status is LookupStatus.NOT_FOUND
    # The manual request bypasses the fast path, and both requests reach the
    # full provider's answer -- the second is served from the worker's OCR
    # cache because the ROI bytes are identical.
    assert len(fast_calls) == 1
    assert len(full_calls) == 1


def test_cancellation_before_fast_ocr_and_after_fast_result_prevents_more_work() -> None:
    first_fast_calls: list[ROIImage] = []
    first_full_calls: list[ROIImage] = []
    first = _hover_worker(
        lambda: _FastTextProvider(TextRecognitionResult("책", 0.99), first_fast_calls),
        full_calls=first_full_calls,
    )
    cancelled_before = LookupRequest(1, _large_roi(), Point(100, 50), hover_request_id=1)
    cancelled_before.cancel()

    with pytest.raises(LookupCancelled):
        first(cancelled_before)
    first.close()
    assert first_fast_calls == []
    assert first_full_calls == []

    second_fast_calls: list[ROIImage] = []
    second_full_calls: list[ROIImage] = []
    cancelled_after = LookupRequest(2, _large_roi(), Point(100, 50), hover_request_id=2)
    second = _hover_worker(
        lambda: _FastTextProvider(
            TextRecognitionResult("책 학교", 0.99),
            second_fast_calls,
            after_recognition=cancelled_after.cancel,
        ),
        full_calls=second_full_calls,
    )

    with pytest.raises(LookupCancelled):
        second(cancelled_after)
    second.close()
    assert len(second_fast_calls) == 1
    assert second_full_calls == []


def test_cancellation_during_crop_prevents_fast_recognition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fast_calls: list[ROIImage] = []
    full_calls: list[ROIImage] = []
    request = LookupRequest(1, _large_roi(), Point(100, 50), hover_request_id=1)
    original_crop = composition_module._crop_hover_roi

    def cancelling_crop(image: ROIImage, target: Point):
        request.cancel()
        return original_crop(image, target)

    monkeypatch.setattr(composition_module, "_crop_hover_roi", cancelling_crop)
    worker = _hover_worker(
        lambda: _FastTextProvider(TextRecognitionResult("책", 0.99), fast_calls),
        full_calls=full_calls,
    )

    with pytest.raises(LookupCancelled):
        worker(request)
    worker.close()

    assert fast_calls == []
    assert full_calls == []


def test_fast_inference_prewarm_finishes_before_worker_ready() -> None:
    prewarm_started = Event()
    release_prewarm = Event()

    class BlockingFastProvider:
        def prewarm(self) -> None:
            prewarm_started.set()
            assert release_prewarm.wait(timeout=2)

        def recognize_text(self, _image: ROIImage) -> TextRecognitionResult:
            return TextRecognitionResult("책", 0.99)

    worker_factory = create_lookup_worker_factory(
        lambda: _OCRProvider("ocr", {}),
        lambda: _MorphologyProvider("morphology", {}),
        lambda: _DictionaryProvider("dictionary", {}),
        hover_text_recognition_provider_factory=BlockingFastProvider,
    )
    executor = JobExecutor(worker_factory, lambda _item, _result: None)

    executor.start()
    assert prewarm_started.wait(timeout=2)
    assert executor.worker_ready is False
    release_prewarm.set()
    assert executor.wait_until_ready(timeout=2)
    executor.shutdown()


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
