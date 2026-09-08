"""Runtime configuration and resource-validation ownership.

Provider construction and lifecycle live in ``test_easyocr_runtime.py``, beside
the fakes the EasyOCR runtime already substitutes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from hanly_app import runtime as runtime_module
from hanly_app.runtime import (
    PACKAGED_MODEL_FILES,
    RuntimeConfigError,
    load_runtime,
)

from tests.hanly_fixtures.krdict import build_fixture_krdict


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


def _packaged_build(
    monkeypatch: pytest.MonkeyPatch,
    directory: Path,
    *,
    weights: tuple[str, ...] = PACKAGED_MODEL_FILES,
) -> None:
    """Stand in for a frozen build carrying the given weight files."""

    directory.mkdir(parents=True, exist_ok=True)
    for name in weights:
        (directory / name).write_bytes(b"weights")
    monkeypatch.setattr(runtime_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(runtime_module, "PACKAGED_MODEL_DIRECTORY", directory)


def _config_with_old_easyocr_settings(tmp_path: Path) -> Path:
    """A runtime.json written by an older Hanly that downloaded its models."""

    config = _valid_config(tmp_path)
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["easyocr"] = {
        "languages": ["ko"],
        "model_storage_directory": "models",
        "download_enabled": True,
    }
    config.write_text(json.dumps(payload), encoding="utf-8")
    return config


def test_a_packaged_build_uses_its_own_weights_and_cannot_download(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Old persisted download settings do not survive into a packaged launch."""

    config = _config_with_old_easyocr_settings(tmp_path)
    models = tmp_path / "bundled"
    _packaged_build(monkeypatch, models)

    easyocr_config = load_runtime(config).easyocr_config

    assert easyocr_config is not None
    assert easyocr_config.model_storage_directory == models
    assert easyocr_config.download_enabled is False
    assert easyocr_config.user_network_directory is None


def test_a_packaged_build_missing_a_weight_fails_instead_of_downloading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _valid_config(tmp_path)
    models = tmp_path / "bundled"
    _packaged_build(monkeypatch, models, weights=("craft_mlt_25k.pth",))

    with pytest.raises(RuntimeConfigError, match="korean_g2.pth"):
        load_runtime(config)


def test_a_source_checkout_keeps_its_configured_easyocr_behaviour(
    tmp_path: Path,
) -> None:
    """Development is unchanged: EasyOCR still resolves and fetches its own."""

    config = _config_with_old_easyocr_settings(tmp_path)

    easyocr_config = load_runtime(config).easyocr_config

    assert easyocr_config is not None
    assert easyocr_config.model_storage_directory == tmp_path / "models"
    assert easyocr_config.download_enabled is True
