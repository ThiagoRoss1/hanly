"""Runtime configuration and resource-validation ownership.

Provider construction and lifecycle live in ``test_easyocr_runtime.py``, beside
the fakes the EasyOCR runtime already substitutes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from hanly_app.runtime import (
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
