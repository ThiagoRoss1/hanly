"""Runtime composition tests for the EasyOCR backend selection."""

from __future__ import annotations

import json
import threading
from collections.abc import Sequence
from pathlib import Path

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
from hanly.easyocr_provider import EasyOCRConfig
from hanly_app.lookup_controller import LookupRequest
from hanly_app.runtime import (
    RuntimeConfigError,
    load_runtime,
)

from tests.hanly_fixtures.krdict import build_fixture_krdict

_IMAGE = ROIImage(width=1, height=1, pixel_format=PixelFormat.RGB_888, data=b"\x00\x00\x00")
_TARGET = Point(0.5, 0.5)


def _krdict_database(path: Path) -> Path:
    return build_fixture_krdict(path.parent, path.name)


def _easyocr_config(tmp_path: Path, **easyocr: object) -> Path:
    """Write a runtime config that selects EasyOCR and declares only KRDICT."""

    (tmp_path / "data").mkdir(exist_ok=True)
    _krdict_database(tmp_path / "data" / "krdict.sqlite3")
    payload: dict[str, object] = {
        "ocr_backend": "easyocr",
        "resources": {"krdict": {"path": "data/krdict.sqlite3", "kind": "krdict"}},
    }
    if easyocr:
        payload["easyocr"] = easyocr
    path = tmp_path / "runtime-easyocr.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class _FakeEasyOCR:
    """Records construction and answers with one Korean region."""

    constructions: list[EasyOCRConfig] = []
    prewarms: list[int] = []

    def __init__(self, *, config: EasyOCRConfig) -> None:
        type(self).constructions.append(config)

    def prewarm(self) -> None:
        type(self).prewarms.append(threading.get_ident())

    def recognize(self, image: ROIImage) -> tuple[OCRResult, ...]:
        del image
        return (
            OCRResult(
                text="책",
                confidence=0.9,
                quad=Quad.from_bounding_box(BoundingBox(0, 0, 1, 1)),
            ),
        )


class _FakeKiwi:
    def analyze(self, text: str) -> Sequence[TokenAnalysis]:
        assert text == "책"
        return (TokenAnalysis(token="책", lemma="책"),)


class _FakeKRDICT:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def lookup(self, lemma: str) -> Sequence[DictionaryEntry]:
        assert lemma == "책"
        return (DictionaryEntry(headword="책", definitions=("book",)),)

    def close(self) -> None:
        return None


@pytest.fixture
def easyocr_providers(monkeypatch: pytest.MonkeyPatch) -> type[_FakeEasyOCR]:
    """Substitute every provider the EasyOCR runtime is allowed to construct."""

    _FakeEasyOCR.constructions = []
    _FakeEasyOCR.prewarms = []
    monkeypatch.setattr(runtime_module, "EasyOCRProvider", _FakeEasyOCR)
    monkeypatch.setattr(runtime_module, "KiwiProvider", _FakeKiwi)
    monkeypatch.setattr(runtime_module, "KRDICTProvider", _FakeKRDICT)
    return _FakeEasyOCR


def test_an_easyocr_runtime_declares_only_the_krdict_resource(tmp_path: Path) -> None:
    runtime = load_runtime(_easyocr_config(tmp_path))

    assert runtime.easyocr_config == EasyOCRConfig()
    assert set(runtime.resource_manager.validate()) == {"krdict"}
    assert runtime.krdict_path == (tmp_path / "data" / "krdict.sqlite3").resolve()


def test_easyocr_options_are_validated_and_rooted_at_the_config_file(
    tmp_path: Path,
) -> None:
    config = _easyocr_config(
        tmp_path,
        languages=["ko"],
        model_storage_directory="models/easyocr",
        download_enabled=False,
        cpu_threads=4,
        detect_network="craft",
    )

    easyocr_config = load_runtime(config).easyocr_config

    assert easyocr_config is not None
    assert easyocr_config.languages == ("ko",)
    assert easyocr_config.model_storage_directory == (
        tmp_path / "models" / "easyocr"
    ).resolve()
    assert easyocr_config.download_enabled is False
    assert easyocr_config.cpu_threads == 4
    assert easyocr_config.extra_options == {"detect_network": "craft"}


def test_invalid_easyocr_options_are_reported_as_a_runtime_config_error(
    tmp_path: Path,
) -> None:
    config = _easyocr_config(tmp_path, cpu_threads=0)

    with pytest.raises(RuntimeConfigError):
        load_runtime(config)


def test_the_worker_composes_easyocr_kiwi_and_krdict(
    tmp_path: Path, easyocr_providers: type[_FakeEasyOCR]
) -> None:
    runtime = load_runtime(_easyocr_config(tmp_path, cpu_threads=2))

    worker = runtime.create_worker_factory()()
    try:
        result = worker(LookupRequest(request_id=1, image=_IMAGE, target=_TARGET))
    finally:
        worker.close()

    assert len(easyocr_providers.constructions) == 1
    assert easyocr_providers.constructions[0].cpu_threads == 2
    assert result.entries[0].headword == "책"


def test_easyocr_is_warmed_during_worker_construction_before_ready(
    tmp_path: Path, easyocr_providers: type[_FakeEasyOCR]
) -> None:
    runtime = load_runtime(_easyocr_config(tmp_path))

    worker = runtime.create_worker_factory()()
    worker.close()

    assert easyocr_providers.prewarms == [threading.get_ident()]


def test_a_hover_request_takes_the_ordinary_provider_path(
    tmp_path: Path, easyocr_providers: type[_FakeEasyOCR]
) -> None:
    """Hover and manual lookups share one OCR seam."""

    runtime = load_runtime(_easyocr_config(tmp_path))

    worker = runtime.create_worker_factory()()
    try:
        result = worker(
            LookupRequest(
                request_id=1,
                image=_IMAGE,
                target=_TARGET,
                hover_request_id=7,
            )
        )
    finally:
        worker.close()

    assert result.entries[0].headword == "책"
    assert len(easyocr_providers.constructions) == 1


def test_the_flat_roi_gate_is_off_unless_a_configuration_asks_for_it(
    tmp_path: Path,
) -> None:
    assert load_runtime(_easyocr_config(tmp_path)).skip_flat_rois is False

    path = _easyocr_config(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["skip_flat_rois"] = True
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert load_runtime(path).skip_flat_rois is True


def test_a_non_boolean_flat_roi_gate_is_rejected(tmp_path: Path) -> None:
    path = _easyocr_config(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["skip_flat_rois"] = "yes"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RuntimeConfigError, match="skip_flat_rois"):
        load_runtime(path)
