"""Focused tests for the local developer-alpha resource preparation seam."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import tools.dev_resources as dev_resources
from tools.dev_alpha import run_dev_alpha
from tools.dev_resources import DevResourceError, prepare_dev_resources


def _write_config(directory: Path, *, database: str = "krdict/krdict.sqlite3") -> Path:
    (directory / "models" / "det").mkdir(parents=True)
    (directory / "models" / "rec").mkdir(parents=True)
    (directory / "models" / "det" / "inference.pdiparams").write_bytes(b"model")
    (directory / "models" / "rec" / "inference.pdiparams").write_bytes(b"model")
    config = directory / "runtime.json"
    config.write_text(
        json.dumps(
            {
                "resources": {
                    "paddle_detection_model": {"path": "models/det"},
                    "paddle_recognition_model": {"path": "models/rec"},
                    "krdict": {"path": database},
                },
                "paddle": {
                    "text_detection_model_name": "PP-OCRv5_mobile_det",
                    "text_recognition_model_name": "korean_PP-OCRv5_mobile_rec",
                },
            }
        ),
        encoding="utf-8",
    )
    return config


def _write_source(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """<dictionary>
  <entry><headword>책</headword><definition lang="en">book</definition></entry>
</dictionary>""",
        encoding="utf-8",
    )


def test_prepare_dev_resources_builds_missing_local_database(tmp_path: Path) -> None:
    config = _write_config(tmp_path)
    source = tmp_path / "krdict-mini.xml"
    _write_source(source)
    calls: list[tuple[Path, Path]] = []

    def builder(source_path: Path, database_path: Path) -> Path:
        calls.append((source_path, database_path))
        database_path.parent.mkdir(parents=True, exist_ok=True)
        database_path.write_bytes(b"prepared")
        return database_path

    preparation = prepare_dev_resources(
        config,
        source_path=source,
        database_builder=builder,
    )

    assert preparation.krdict_built is True
    assert preparation.krdict_database == (tmp_path / "krdict/krdict.sqlite3").resolve()
    assert calls == [(source.resolve(), preparation.krdict_database)]


def test_prepare_dev_resources_does_not_rebuild_existing_database(tmp_path: Path) -> None:
    config = _write_config(tmp_path)
    database = tmp_path / "krdict/krdict.sqlite3"
    database.parent.mkdir()
    database.write_bytes(b"existing")
    called = False

    def builder(_source: Path, _database: Path) -> Path:
        nonlocal called
        called = True
        return database

    preparation = prepare_dev_resources(config, database_builder=builder)

    assert preparation.krdict_built is False
    assert called is False
    assert database.read_bytes() == b"existing"


def test_prepare_dev_resources_discovers_standard_cache_without_editing_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _write_config(tmp_path)
    database = tmp_path / "krdict/krdict.sqlite3"
    database.parent.mkdir()
    database.write_bytes(b"existing")
    cache = tmp_path / "official_models"
    detection = cache / "PP-OCRv5_mobile_det"
    recognition = cache / "korean_PP-OCRv5_mobile_rec"
    detection.mkdir(parents=True)
    recognition.mkdir(parents=True)
    (detection / "model.pdmodel").write_bytes(b"det")
    (recognition / "model.pdmodel").write_bytes(b"rec")
    (tmp_path / "models" / "det" / "inference.pdiparams").unlink()
    (tmp_path / "models" / "rec" / "inference.pdiparams").unlink()
    monkeypatch.setattr(
        dev_resources,
        "_standard_model_directories",
        lambda name: (cache / name,),
    )
    original = config.read_text(encoding="utf-8")

    preparation = prepare_dev_resources(config)

    assert preparation.config_path != config.resolve()
    effective = json.loads(preparation.config_path.read_text(encoding="utf-8"))
    assert effective["resources"]["paddle_detection_model"]["path"] == str(
        detection.resolve()
    )
    assert effective["resources"]["krdict"]["path"] == str(database.resolve())
    assert config.read_text(encoding="utf-8") == original
    preparation.cleanup()
    assert not preparation.config_path.exists()


def test_prepare_dev_resources_reports_missing_ocr_model_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _write_config(tmp_path)
    database = tmp_path / "krdict/krdict.sqlite3"
    database.parent.mkdir()
    database.write_bytes(b"existing")
    (tmp_path / "models" / "det" / "inference.pdiparams").unlink()
    (tmp_path / "models" / "det").rmdir()
    monkeypatch.setattr(dev_resources, "_standard_model_directories", lambda _name: ())

    with pytest.raises(
        DevResourceError, match="PaddleOCR detection model directory is unavailable"
    ):
        prepare_dev_resources(config)


def test_prepare_dev_resources_reports_missing_in_repo_source(tmp_path: Path) -> None:
    config = _write_config(tmp_path)

    with pytest.raises(DevResourceError, match="in-repository XML source was not found"):
        prepare_dev_resources(config, source_path=tmp_path / "missing.xml")


def test_run_dev_alpha_sets_offline_flag_and_cleans_preparation(
    tmp_path: Path,
) -> None:
    events: list[str] = []

    class Prepared:
        config_path = tmp_path / "effective-runtime.json"

        def cleanup(self) -> None:
            events.append("cleanup")

    environment: dict[str, str] = {}

    def prepare(config_path: str | Path | None) -> Prepared:
        assert config_path == tmp_path / "requested-runtime.json"
        events.append("prepare")
        return Prepared()

    def run(*, config_path: Path) -> int:
        assert config_path == Prepared.config_path
        assert environment["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] == "True"
        events.append("run")
        return 7

    result = run_dev_alpha(
        tmp_path / "requested-runtime.json",
        resource_preparer=prepare,
        alpha_runner=run,
        environment=environment,
    )

    assert result == 7
    assert events == ["prepare", "run", "cleanup"]
