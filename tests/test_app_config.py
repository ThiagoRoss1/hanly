from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from hanly_app.config import AppConfig, CaptureMode, CaptureRegion, ConfigManager, Theme


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


def test_capture_target_and_region_persist_as_preferences(tmp_path: Path) -> None:
    """Where Hanly looks is a setting now, not a launch-time prompt."""

    manager = ConfigManager(tmp_path / "settings.json")
    manager.load()

    saved = manager.update(
        capture_mode=CaptureMode.REGION,
        capture_monitor=2,
        capture_region={"left": 10, "top": 20, "width": 300, "height": 200},
    )

    assert saved.capture_monitor == 2
    assert saved.capture_region == CaptureRegion(10, 20, 300, 200)
    assert ConfigManager(manager.path).load() == saved


def test_settings_written_before_capture_preferences_still_load(tmp_path: Path) -> None:
    """An existing profile must keep working after this release."""

    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"hotkey": "ctrl+alt+k", "hover_delay_ms": 120}),
        encoding="utf-8",
    )

    loaded = ConfigManager(path).load()

    assert loaded.hotkey == "ctrl+alt+k"
    assert loaded.capture_monitor is None
    assert loaded.capture_region is None


def test_region_mode_without_a_region_stays_loadable(tmp_path: Path) -> None:
    """A monitor can disappear between sessions; settings must survive it."""

    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"capture_mode": "region"}), encoding="utf-8")

    loaded = ConfigManager(path).load()

    assert loaded.capture_mode is CaptureMode.REGION
    assert loaded.capture_region is None


@pytest.mark.parametrize(
    "region",
    [
        {"left": 0, "top": 0, "width": 0, "height": 10},
        {"left": 0, "top": 0, "width": 10},
        {"left": 0.5, "top": 0, "width": 10, "height": 10},
    ],
)
def test_an_unusable_capture_region_is_rejected(region: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        AppConfig(capture_region=cast(Any, region))


def test_a_monitor_index_must_be_one_of_the_capture_service_indices() -> None:
    with pytest.raises(ValueError, match="capture_monitor"):
        AppConfig(capture_monitor=0)
