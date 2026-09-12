from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from hanly_app.config import (
    DEFAULT_CAPTURE_HOTKEY,
    DEFAULT_HOVER_HOTKEY,
    HOVER_HOTKEY_FALLBACKS,
    AppConfig,
    CaptureMode,
    CaptureRegion,
    ConfigManager,
    HoverActivation,
    LookupPreload,
    Theme,
)


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


def test_a_profile_written_before_the_hover_toggle_keeps_its_lookup_key(
    tmp_path: Path,
) -> None:
    """Reinterpreting the key the user has been pressing for months would be
    the worst possible migration."""

    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"hotkey": "ctrl+alt+k", "hover_delay_ms": 140}), encoding="utf-8"
    )
    manager = ConfigManager(path)

    config = manager.load()

    assert config.hotkey == "ctrl+alt+k"
    assert config.hover_delay_ms == 140
    assert config.hover_hotkey == DEFAULT_HOVER_HOTKEY
    assert config.hover_activation is HoverActivation.PUSH_TO_HOVER
    assert config.lookup_preload is LookupPreload.WHEN_CAPTURE_STARTS
    assert manager.migrations == ()


def test_a_lookup_key_sitting_on_the_toggle_default_moves_the_toggle(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"hotkey": DEFAULT_HOVER_HOTKEY}), encoding="utf-8")
    manager = ConfigManager(path)

    config = manager.load()

    assert config.hotkey == DEFAULT_HOVER_HOTKEY
    assert config.hover_hotkey == HOVER_HOTKEY_FALLBACKS[1]
    assert manager.migrations
    assert DEFAULT_HOVER_HOTKEY in manager.migrations[0]


def test_a_stored_toggle_binding_is_the_users_choice_and_is_kept(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"hover_hotkey": "ctrl+alt+j"}), encoding="utf-8")

    config = ConfigManager(path).load()

    assert config.hover_hotkey == "ctrl+alt+j"


def test_two_actions_may_not_ask_for_the_same_key() -> None:
    with pytest.raises(ValueError, match="different key combinations"):
        AppConfig(hotkey="ctrl+shift+k", hover_hotkey="Ctrl+Shift+K")
    with pytest.raises(ValueError, match="different key combinations"):
        AppConfig(hotkey="ctrl+shift+k", capture_hotkey="Ctrl+Shift+K")


def test_the_new_preferences_round_trip_through_stored_json(tmp_path: Path) -> None:
    manager = ConfigManager(tmp_path / "config.json")

    manager.update(
        lookup_preload="always",
        hover_activation="always_active",
        hover_hotkey="ctrl+alt+j",
    )

    reloaded = ConfigManager(tmp_path / "config.json").load()
    assert reloaded.lookup_preload is LookupPreload.ALWAYS
    assert reloaded.hover_activation is HoverActivation.ALWAYS_ACTIVE
    assert reloaded.hover_hotkey == "ctrl+alt+j"


def test_an_invented_preload_choice_is_refused(tmp_path: Path) -> None:
    manager = ConfigManager(tmp_path / "config.json")

    with pytest.raises(ValueError, match="lookup_preload"):
        manager.update(lookup_preload="whenever")


def test_a_candidate_is_validated_without_being_stored(tmp_path: Path) -> None:
    """A shortcut has to be tried with the operating system before it is saved."""

    path = tmp_path / "config.json"
    manager = ConfigManager(path)

    candidate = manager.candidate(hover_hotkey="ctrl+alt+j")

    assert candidate.hover_hotkey == "ctrl+alt+j"
    assert manager.config.hover_hotkey == DEFAULT_HOVER_HOTKEY
    assert not path.exists()


def test_start_stop_capture_gets_its_own_shortcut_without_moving_the_others(
    tmp_path: Path,
) -> None:
    """The third action is new, so it is the one that has to find a position."""

    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"hotkey": "ctrl+shift+space", "hover_hotkey": "ctrl+shift+f9"}),
        encoding="utf-8",
    )
    manager = ConfigManager(path)

    config = manager.load()

    assert config.hotkey == "ctrl+shift+space"
    assert config.hover_hotkey == "ctrl+shift+f9"
    assert config.capture_hotkey == DEFAULT_CAPTURE_HOTKEY
    assert manager.migrations == ()


def test_a_profile_occupying_every_candidate_leaves_start_stop_unbound(
    tmp_path: Path,
) -> None:
    """Losing one shortcut beats resetting preferences to make room for it."""

    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"hotkey": "ctrl+shift+f10", "hover_hotkey": "ctrl+shift+f11"}),
        encoding="utf-8",
    )
    manager = ConfigManager(path)

    config = manager.load()

    assert config.hotkey == "ctrl+shift+f10"
    assert config.hover_hotkey == "ctrl+shift+f11"
    assert config.capture_hotkey == "ctrl+shift+f12"
    assert any("f12" in note for note in manager.migrations)


def test_migration_is_idempotent_across_a_save_and_reload(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"hotkey": "ctrl+alt+k"}), encoding="utf-8")
    manager = ConfigManager(path)

    first = manager.load()
    manager.save(first)
    second = ConfigManager(path)

    assert second.load() == first
    assert second.migrations == ()
