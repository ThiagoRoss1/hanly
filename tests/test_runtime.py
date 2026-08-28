from __future__ import annotations

import json
import threading
from pathlib import Path
from threading import Event

import hanly_app.runtime as runtime_module
import pytest
from hanly import (
    BoundingBox,
    DictionaryEntry,
    OCRResult,
    PixelFormat,
    Point,
    Quad,
    ROIImage,
    TokenAnalysis,
)
from hanly_app.runtime import (
    RuntimeConfigError,
    load_runtime,
)

from tests.hanly_fixtures.krdict import build_fixture_krdict

_IMAGE = ROIImage(
    width=1,
    height=1,
    pixel_format=PixelFormat.RGB_888,
    data=b"\x00\x00\x00",
)
_TARGET = Point(0.5, 0.5)


def _krdict_database(path: Path) -> Path:
    return build_fixture_krdict(path.parent, path.name)


def _runtime_config(
    directory: Path,
    *,
    resources: dict[str, object] | None = None,
) -> Path:
    payload = {
        "resources": resources
        or {"krdict": {"path": "data/krdict.sqlite3", "kind": "krdict"}},
    }
    path = directory / "runtime.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _valid_config(tmp_path: Path) -> Path:
    (tmp_path / "data").mkdir()
    _krdict_database(tmp_path / "data" / "krdict.sqlite3")
    return _runtime_config(tmp_path)


def test_invalid_resource_status_is_reported_with_resource_diagnostics(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    config = _runtime_config(tmp_path)

    with pytest.raises(RuntimeConfigError, match="krdict.*does not exist"):
        load_runtime(config)


def test_invalid_declared_optional_resource_also_blocks_runtime_startup(
    tmp_path: Path,
) -> None:
    valid = _valid_config(tmp_path)
    payload = json.loads(valid.read_text(encoding="utf-8"))
    payload["resources"]["unused_asset"] = {"path": "missing.asset", "kind": "file"}
    valid.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RuntimeConfigError, match="unused_asset.*does not exist"):
        load_runtime(valid)


def test_concrete_provider_factories_are_deferred_and_krdict_lifecycle_stays_on_worker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _valid_config(tmp_path)
    runtime = load_runtime(config)
    construction_threads: dict[str, int] = {}
    lookup_threads: dict[str, int] = {}
    close_threads: dict[str, int] = {}
    constructed = Event()
    delivered = Event()

    class FakeOCR:
        def __init__(self, *, config: object) -> None:
            del config
            construction_threads["ocr"] = threading.get_ident()
            constructed.set()

        def recognize(self, image: ROIImage) -> tuple[OCRResult, ...]:
            del image
            return (
                OCRResult(
                    text="책",
                    confidence=0.99,
                    quad=Quad.from_bounding_box(BoundingBox(0, 0, 1, 1)),
                ),
            )

    class FakeKiwi:
        def __init__(self) -> None:
            construction_threads["kiwi"] = threading.get_ident()

        def analyze(self, text: str) -> tuple[TokenAnalysis, ...]:
            assert text == "책"
            return (TokenAnalysis(token="책", lemma="책"),)

    class FakeKRDICT:
        def __init__(self, database_path: Path) -> None:
            assert database_path == (tmp_path / "data" / "krdict.sqlite3").resolve()
            construction_threads["krdict"] = threading.get_ident()

        def lookup(self, lemma: str) -> tuple[DictionaryEntry, ...]:
            assert lemma == "책"
            lookup_threads["krdict"] = threading.get_ident()
            return (DictionaryEntry(headword="책", definitions=("book",)),)

        def close(self) -> None:
            close_threads["krdict"] = threading.get_ident()

    monkeypatch.setattr(runtime_module, "EasyOCRProvider", FakeOCR)
    monkeypatch.setattr(runtime_module, "KiwiProvider", FakeKiwi)
    monkeypatch.setattr(runtime_module, "KRDICTProvider", FakeKRDICT)

    controller = runtime.create_lookup_controller(lambda _result: delivered.set())
    assert not constructed.is_set()
    controller.start()
    assert controller.wait_until_ready(timeout=2)
    controller.submit(_IMAGE, _TARGET)
    assert constructed.wait(timeout=2)
    assert delivered.wait(timeout=2)
    controller.stop()

    worker_thread = controller._executor.thread_ident
    assert worker_thread is not None
    assert set(construction_threads.values()) == {worker_thread}
    assert lookup_threads == {"krdict": worker_thread}
    assert close_threads == {"krdict": worker_thread}
