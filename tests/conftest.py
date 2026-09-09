"""Suite-wide isolation for Hanly-owned profile and cache paths."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

if sys.platform.startswith("linux") and not (
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
):
    # Qt must choose its platform before any test imports QApplication.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def isolate_hanly_user_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep tests away from real configuration, resources, logs, and caches."""

    profile = tmp_path / "profile"
    cache = tmp_path / "cache"
    models = cache / "easyocr"
    if sys.platform == "win32":
        monkeypatch.setenv("LOCALAPPDATA", str(profile))
    else:
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(profile))
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    monkeypatch.setenv("EASYOCR_MODULE_PATH", str(models))
    monkeypatch.setenv("MODULE_PATH", str(models))

    if os.environ.get("HANLY_REQUIRE_REAL_KRDICT") != "1":
        monkeypatch.delenv("HANLY_KRDICT_DB", raising=False)
