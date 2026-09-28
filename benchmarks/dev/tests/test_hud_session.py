"""The HUD's provider label, which must name the recognizer actually selected.

Importing the session module constructs no Qt object and loads no OCR runtime;
only :func:`run_hud_session` reaches for those, and nothing here calls it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from hanly_app.config import OCRBackend

from benchmarks.dev.hud.session import _resolved_backend
from tests.hanly_fixtures.krdict import build_fixture_krdict


def _runtime_config(directory: Path, *, ocr_backend: str | None = None) -> Path:
    (directory / "data").mkdir()
    build_fixture_krdict(directory / "data", "krdict.sqlite3")
    payload: dict[str, object] = {
        "resources": {"krdict": {"path": "data/krdict.sqlite3", "kind": "krdict"}},
    }
    if ocr_backend is not None:
        payload["ocr_backend"] = ocr_backend
    path = directory / "runtime.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_the_label_names_the_pinned_recognizer(tmp_path: Path) -> None:
    assert _resolved_backend(_runtime_config(tmp_path, ocr_backend="easyocr")) == "easyocr"


def test_auto_reports_the_backend_this_machine_resolves_to(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``auto`` differs per machine, which is why the label cannot be fixed."""

    from hanly.vision_provider import VisionProvider

    config = _runtime_config(tmp_path, ocr_backend="auto")

    monkeypatch.setattr(VisionProvider, "is_available", staticmethod(lambda: True))
    assert _resolved_backend(config) == OCRBackend.VISION.value

    monkeypatch.setattr(VisionProvider, "is_available", staticmethod(lambda: False))
    assert _resolved_backend(config) == OCRBackend.EASYOCR.value


def test_an_unloadable_configuration_claims_no_backend(tmp_path: Path) -> None:
    """The desktop launch reports the real failure; the HUD must not guess."""

    assert _resolved_backend(tmp_path / "missing.json") == "unresolved"
