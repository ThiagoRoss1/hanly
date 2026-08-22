"""Focused worker-thread composition tests for the first app engine path."""

from __future__ import annotations

import threading
from collections.abc import Sequence
from pathlib import Path
from threading import Event

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
from hanly.krdict_build import build_krdict_database
from hanly.krdict_provider import KRDICTProvider
from hanly_app.composition import create_lookup_controller, create_lookup_worker_factory
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
