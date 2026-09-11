"""An in-process stand-in for Hanly's spawned lookup child.

The child's own code runs unchanged, on a thread and over a real pipe, so the
tests that use this exercise the real transport, the real reader/processing
split, and the real cancellation plumbing. What it leaves out is the process
boundary itself and the OCR preload, which is what lets these tests stay
deterministic and free of a hundred-megabyte download.
"""

from __future__ import annotations

import multiprocessing
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from hanly import DictionaryEntry, OCRResult, PixelFormat, Point, Quad, ROIImage, TokenAnalysis
from hanly.easyocr_provider import EasyOCRConfig
from hanly_app.lookup_process import LookupSettings, _LookupChild
from hanly_app.process_transport import Transport

#: A one-pixel ROI is enough: the fake OCR provider ignores the pixels.
PIXEL = ROIImage(width=1, height=1, pixel_format=PixelFormat.RGB_888, data=b"\x00\x00\x00")
TARGET = Point(0.5, 0.5)

#: The word every fake provider in this harness agrees on.
WORD = "책"


class WatchedTransport(Transport):
    """The child's end, recording which message kinds the parent sent.

    Cancellation travels as a message, so a test can wait for the child to
    have taken it rather than guessing how long forwarding needs.
    """

    def __init__(self, connection: Any) -> None:
        super().__init__(connection)
        self.received: list[str] = []

    def receive(self) -> Any:
        message = super().receive()
        self.received.append(str(message.get("kind")))
        return message

    def saw(self, kind: str) -> bool:
        return kind in self.received


class FakeProcess:
    """Enough of a child process for the engine's lifecycle decisions."""

    def __init__(self, thread: threading.Thread) -> None:
        self._thread = thread
        self.terminated = False

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def join(self, timeout: float | None = None) -> None:
        self._thread.join(timeout)

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.terminated = True


class ThreadChildSpawner:
    """Run the real child body on a thread and hand back its pipe."""

    def __init__(
        self,
        *,
        on_start: Callable[[LookupSettings], None] | None = None,
        fail_with: str | None = None,
    ) -> None:
        self.spawns = 0
        self.children: list[FakeProcess] = []
        #: The child's own end, so a test can close it the way a crash does.
        self.child_transports: list[WatchedTransport] = []
        self._on_start = on_start
        self._fail_with = fail_with

    def __call__(
        self,
        _target: Any,
        settings: LookupSettings,
        *,
        name: str = "",
        max_bytes: int | None = None,
    ) -> tuple[Any, Transport]:
        del name, max_bytes
        parent_end, child_end = multiprocessing.Pipe(duplex=True)
        transport = WatchedTransport(child_end)
        self.child_transports.append(transport)

        def body() -> None:
            if self._on_start is not None:
                self._on_start(settings)
            if self._fail_with is not None:
                transport.send({"kind": "failed", "message": self._fail_with})
                transport.close()
                return
            _LookupChild(transport, settings).run()

        thread = threading.Thread(target=body, name="fake-lookup-child", daemon=True)
        self.spawns += 1
        process = FakeProcess(thread)
        self.children.append(process)
        thread.start()
        return process, Transport(parent_end)


class RecordingProviders:
    """Fake OCR, morphology, and dictionary adapters that record their thread."""

    def __init__(self) -> None:
        self.threads: dict[str, int] = {}
        self.databases: list[Path] = []
        self.lookups = 0
        #: Set to block inside recognition, which is where a supersession lands.
        self.hold: threading.Event | None = None
        self.entered = threading.Semaphore(0)

    def install(self, monkeypatch: Any) -> None:
        monkeypatch.setattr("hanly.easyocr_provider.EasyOCRProvider", self._ocr())
        monkeypatch.setattr("hanly.kiwi_provider.KiwiProvider", self._morphology())
        monkeypatch.setattr("hanly.krdict_provider.KRDICTProvider", self._dictionary())

    def _ocr(self) -> type:
        recorder = self

        class FakeOCR:
            def __init__(self, *, config: EasyOCRConfig) -> None:
                recorder.threads["ocr"] = threading.get_ident()
                self.config = config

            def prewarm(self) -> None:
                recorder.threads["ocr_prewarm"] = threading.get_ident()

            def recognize(self, image: ROIImage) -> tuple[OCRResult, ...]:
                del image
                recorder.threads["ocr_recognize"] = threading.get_ident()
                recorder.entered.release()
                hold = recorder.hold
                if hold is not None:
                    hold.wait(5.0)
                return (
                    OCRResult(
                        text=WORD,
                        confidence=0.9,
                        quad=Quad.from_bounding_box(_unit_box()),
                    ),
                )

        return FakeOCR

    def _morphology(self) -> type:
        recorder = self

        class FakeKiwi:
            def __init__(self) -> None:
                recorder.threads["morphology"] = threading.get_ident()

            def analyze(self, text: str) -> Sequence[TokenAnalysis]:
                return (TokenAnalysis(token=text, lemma=WORD),)

        return FakeKiwi

    def _dictionary(self) -> type:
        recorder = self

        class FakeKRDICT:
            def __init__(self, database_path: Path) -> None:
                recorder.threads["dictionary"] = threading.get_ident()
                recorder.databases.append(database_path)

            def lookup(self, lemma: str) -> Sequence[DictionaryEntry]:
                del lemma
                recorder.threads["dictionary_lookup"] = threading.get_ident()
                recorder.lookups += 1
                return (DictionaryEntry(headword=WORD, definitions=("book",)),)

            def close(self) -> None:
                recorder.threads["dictionary_close"] = threading.get_ident()

        return FakeKRDICT


def settings(krdict_path: Path | None = None) -> LookupSettings:
    """Build provider settings that need no real model or database."""

    return LookupSettings(
        krdict_path=krdict_path or Path("krdict.sqlite3"),
        easyocr=EasyOCRConfig(languages=("ko",), download_enabled=False),
    )


def _unit_box() -> Any:
    from hanly import BoundingBox

    return BoundingBox(0, 0, 1, 1)


__all__ = [
    "PIXEL",
    "TARGET",
    "WORD",
    "FakeProcess",
    "RecordingProviders",
    "ThreadChildSpawner",
    "WatchedTransport",
    "settings",
]
