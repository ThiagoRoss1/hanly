from __future__ import annotations

import json
from pathlib import Path

import pytest
from hanly_app.config import AppConfig, CaptureMode, ConfigManager, Theme


def test_default_config_is_valid_and_contains_only_desktop_preferences() -> None:
    config = AppConfig()

    assert config.hotkey
    assert config.hover_delay_ms > 0
    assert config.capture_mode is CaptureMode.FULL_MONITOR
    assert config.theme is Theme.SYSTEM
    assert config.popup_enabled is True
    assert config.update_checks_enabled is True
    assert "confidence_threshold" not in config.to_dict()


def test_config_manager_uses_defaults_when_file_is_missing(tmp_path: Path) -> None:
    manager = ConfigManager(tmp_path / "settings.json")

    loaded = manager.load()

    assert loaded == AppConfig()


def test_config_manager_round_trips_typed_json(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    expected = AppConfig(
        hotkey="alt+shift+h",
        hover_delay_ms=200,
        capture_mode=CaptureMode.REGION,
        theme=Theme.DARK,
        popup_enabled=False,
        update_checks_enabled=False,
    )
    manager = ConfigManager(path)

    manager.save(expected)
    loaded = ConfigManager(path).load()

    assert loaded == expected
    assert path.read_text(encoding="utf-8") == (
        json.dumps(expected.to_dict(), indent=2, sort_keys=True) + "\n"
    )


def test_update_validates_and_persists_a_new_config(tmp_path: Path) -> None:
    manager = ConfigManager(tmp_path / "settings.json")

    updated = manager.update(hover_delay_ms=220, theme="light")

    assert updated.hover_delay_ms == 220
    assert updated.theme is Theme.LIGHT
    assert manager.load() == updated


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("hotkey", "  "),
        ("hover_delay_ms", 0),
        ("hover_delay_ms", -1),
        ("capture_mode", "continuous_ocr"),
        ("theme", "neon"),
    ],
)
def test_invalid_preferences_are_rejected(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        AppConfig(**{field: value})  # type: ignore[arg-type]


def test_save_replaces_existing_file_without_leaving_a_temp_file(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    manager = ConfigManager(path)
    manager.save(AppConfig(hotkey="ctrl+h"))

    manager.save(AppConfig(hotkey="ctrl+j"))

    assert '"hotkey": "ctrl+j"' in path.read_text(encoding="utf-8")
    assert list(tmp_path.glob(".settings.json.*.tmp")) == []
