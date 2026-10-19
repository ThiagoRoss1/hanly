"""Stress ownership includes its desktop without trusting unrelated windows."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from lab.session.recorder import LabRecorder
from lab.session.stress_driver import StressDriver


def test_stress_accepts_its_native_popup_but_rejects_foreign_windows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setitem(
        sys.modules,
        "pynput",
        SimpleNamespace(
            mouse=SimpleNamespace(Controller=lambda: None),
            keyboard=SimpleNamespace(Controller=lambda: None, Key=SimpleNamespace()),
        ),
    )
    recorder = LabRecorder(
        tmp_path / "events.jsonl", retain_evidence=False, retain_geometry=False
    )
    driver = StressDriver(
        recorder,
        cast(Any, SimpleNamespace(display_scale=2.0)),
        [],
        capture_hotkey="ctrl+shift+f10",
        run_dir=tmp_path,
        retain_fixture_text=False,
        retain_fixture_images=False,
        owned_pids={72345},
    )
    try:
        monkeypatch.setattr("lab.session.driver.owner_at", lambda _x, _y: 72345)
        assert driver._foreign_windows(200, 150) == []

        monkeypatch.setattr("lab.session.driver.owner_at", lambda _x, _y: 72346)
        assert driver._foreign_windows(200, 150)

        monkeypatch.setattr("lab.session.driver.owner_at", lambda _x, _y: None)
        assert driver._foreign_windows(200, 150)
    finally:
        recorder.close()
