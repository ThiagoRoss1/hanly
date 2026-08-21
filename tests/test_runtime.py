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
from hanly.krdict_build import build_krdict_database
from hanly_app.runtime import (
    RuntimeConfigError,
    load_runtime,
)

_IMAGE = ROIImage(
    width=1,
    height=1,
    pixel_format=PixelFormat.RGB_888,
    data=b"\x00\x00\x00",
)
_TARGET = Point(0.5, 0.5)


def _krdict_database(path: Path) -> Path:
    source = path.with_suffix(".xml")
    source.write_text(
        """<dictionary>
  <entry><headword>책</headword><part_of_speech>명사</part_of_speech>
    <definition lang=\"en\">book</definition></entry>
</dictionary>""",
        encoding="utf-8",
    )
    build_krdict_database(source, path)
    return path


def _runtime_config(
    directory: Path,
    *,
    paddle: dict[str, object] | None = None,
    resources: dict[str, object] | None = None,
) -> Path:
    payload = {
        "resources": resources
        or {
            "paddle_detection_model": {"path": "models/det", "kind": "directory"},
            "paddle_recognition_model": {"path": "models/rec", "kind": "directory"},
            "krdict": {"path": "data/krdict.sqlite3", "kind": "krdict"},
        },
        "paddle": paddle
        or {
            "text_detection_model_name": "PP-OCRv5_mobile_det",
            "text_detection_model_dir": "models/det",
            "text_recognition_model_name": "korean_PP-OCRv5_mobile_rec",
            "text_recognition_model_dir": "models/rec",
            "enable_mkldnn": False,
        },
    }
    path = directory / "runtime.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _valid_config(tmp_path: Path) -> Path:
    (tmp_path / "models" / "det").mkdir(parents=True)
    (tmp_path / "models" / "rec").mkdir(parents=True)
    (tmp_path / "data").mkdir()
    _krdict_database(tmp_path / "data" / "krdict.sqlite3")
    return _runtime_config(tmp_path)


def test_runtime_config_is_rooted_and_passes_explicit_paths_and_options_to_paddle(
    tmp_path: Path,
) -> None:
    config = _valid_config(tmp_path)

    runtime = load_runtime(config)

    assert runtime.resource_manager.validated_path("paddle_detection_model") == (
        tmp_path / "models" / "det"
    ).resolve()
    assert runtime.resource_manager.base_path == tmp_path.resolve()
    assert runtime.resource_manager.configuration("paddle_detection_model")["model_name"] == (
        "PP-OCRv5_mobile_det"
    )
    assert runtime.resource_manager.configuration("paddle_recognition_model")["model_name"] == (
        "korean_PP-OCRv5_mobile_rec"
    )
    options = runtime.paddle_config.to_engine_kwargs()
    assert options["text_detection_model_name"] == "PP-OCRv5_mobile_det"
    assert options["text_detection_model_dir"] == str(
        (tmp_path / "models" / "det").resolve()
    )
    assert options["text_recognition_model_name"] == "korean_PP-OCRv5_mobile_rec"
    assert options["text_recognition_model_dir"] == str(
        (tmp_path / "models" / "rec").resolve()
    )
    assert options["enable_mkldnn"] is False


def test_enable_mkldnn_is_omitted_when_runtime_config_does_not_set_it(
    tmp_path: Path,
) -> None:
    config = _valid_config(tmp_path)
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["paddle"].pop("enable_mkldnn")
    config.write_text(json.dumps(payload), encoding="utf-8")

    runtime = load_runtime(config)

    assert "enable_mkldnn" not in runtime.paddle_config.to_engine_kwargs()


@pytest.mark.parametrize(
    ("paddle", "message"),
    [
        (
            {"text_recognition_model_name": "rec"},
            "text_detection_model_name",
        ),
        (
            {
                "text_detection_model_name": "det",
                "text_detection_model_dir": "models/det",
                "text_recognition_model_dir": "models/rec",
            },
            "text_recognition_model_name",
        ),
    ],
)
def test_runtime_config_requires_explicit_detection_and_recognition_name_dir_pairs(
    tmp_path: Path,
    paddle: dict[str, object],
    message: str,
) -> None:
    (tmp_path / "models" / "det").mkdir(parents=True)
    (tmp_path / "models" / "rec").mkdir(parents=True)
    (tmp_path / "data").mkdir()
    _krdict_database(tmp_path / "data" / "krdict.sqlite3")
    config = _runtime_config(tmp_path, paddle=paddle)

    with pytest.raises(RuntimeConfigError, match=message):
        load_runtime(config)


def test_extra_options_cannot_override_a_validated_model_path(tmp_path: Path) -> None:
    config = _valid_config(tmp_path)
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["paddle"]["extra_options"] = {"text_detection_model_dir": "C:/unvalidated"}
    config.write_text(json.dumps(payload), encoding="utf-8")

    # to_engine_kwargs applies extra_options last, so without this guard the
    # unvalidated path would reach PaddleOCR instead of the ResourceManager
    # one this composition root exists to enforce.
    with pytest.raises(RuntimeConfigError, match="text_detection_model_dir"):
        load_runtime(config)


def test_unknown_paddle_keys_still_pass_through_to_the_library(tmp_path: Path) -> None:
    config = _valid_config(tmp_path)
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["paddle"]["cpu_threads"] = 4
    config.write_text(json.dumps(payload), encoding="utf-8")

    options = load_runtime(config).paddle_config.to_engine_kwargs()

    assert options["cpu_threads"] == 4


def test_invalid_resource_status_is_reported_with_resource_diagnostics(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    config = _runtime_config(tmp_path)

    with pytest.raises(RuntimeConfigError, match="paddle_detection_model.*does not exist"):
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

    monkeypatch.setattr(runtime_module, "PaddleOCRProvider", FakeOCR)
    monkeypatch.setattr(runtime_module, "KiwiProvider", FakeKiwi)
    monkeypatch.setattr(runtime_module, "KRDICTProvider", FakeKRDICT)

    controller = runtime.create_lookup_controller(lambda _result: delivered.set())
    assert not constructed.is_set()
    controller.start()
    controller.submit(_IMAGE, _TARGET)
    assert constructed.wait(timeout=2)
    assert delivered.wait(timeout=2)
    controller.stop()

    worker_thread = controller._executor.thread_ident
    assert worker_thread is not None
    assert set(construction_threads.values()) == {worker_thread}
    assert lookup_threads == {"krdict": worker_thread}
    assert close_threads == {"krdict": worker_thread}
