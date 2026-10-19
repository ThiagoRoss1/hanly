from __future__ import annotations

from pathlib import Path

from hanly_app.paths import (
    RUNTIME_CONFIG_NAME,
    default_app_config_path,
    default_runtime_config_path,
    discover_runtime_config,
)


def test_default_app_config_prefers_local_app_data(tmp_path: Path) -> None:
    assert default_app_config_path({"LOCALAPPDATA": str(tmp_path)}) == (
        tmp_path / "Hanly" / "config.json"
    ).resolve()


def test_runtime_configuration_sits_beside_the_settings_file(tmp_path: Path) -> None:
    environment = {"LOCALAPPDATA": str(tmp_path)}

    runtime = default_runtime_config_path(environment)

    assert runtime.name == RUNTIME_CONFIG_NAME
    assert runtime.parent == default_app_config_path(environment).parent


def test_packaged_launch_prefers_configuration_beside_the_executable(
    tmp_path: Path,
) -> None:
    application_dir = tmp_path / "hanly-desktop"
    application_dir.mkdir()
    executable = application_dir / "hanly-desktop.exe"
    executable.write_bytes(b"frozen")
    beside = application_dir / RUNTIME_CONFIG_NAME
    beside.write_text("{}", encoding="utf-8")

    environment = {"LOCALAPPDATA": str(tmp_path / "settings")}
    per_user = default_runtime_config_path(environment)
    per_user.parent.mkdir(parents=True)
    per_user.write_text("{}", encoding="utf-8")

    assert discover_runtime_config(environment, executable) == beside


def test_per_user_config_is_used_when_none_ships_with_the_build(tmp_path: Path) -> None:
    executable = tmp_path / "bin" / "hanly-desktop.exe"
    executable.parent.mkdir()
    executable.write_bytes(b"frozen")

    environment = {"LOCALAPPDATA": str(tmp_path / "settings")}
    per_user = default_runtime_config_path(environment)
    per_user.parent.mkdir(parents=True)
    per_user.write_text("{}", encoding="utf-8")

    assert discover_runtime_config(environment, executable) == per_user


def test_macos_bundle_uses_per_user_config_instead_of_the_replaceable_bundle(
    tmp_path: Path,
) -> None:
    executable = (
        tmp_path
        / "Hanly.app"
        / "Contents"
        / "MacOS"
        / "hanly-desktop"
    )
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"frozen")

    environment = {"LOCALAPPDATA": str(tmp_path / "settings")}
    per_user = default_runtime_config_path(environment)
    per_user.parent.mkdir(parents=True)
    per_user.write_text("{}", encoding="utf-8")
    (executable.parent / RUNTIME_CONFIG_NAME).write_text("{}", encoding="utf-8")

    assert discover_runtime_config(environment, executable) == per_user


def test_runtime_config_discovery_returns_none_without_a_candidate(tmp_path: Path) -> None:
    executable = tmp_path / "bin" / "hanly-desktop.exe"
    executable.parent.mkdir()
    executable.write_bytes(b"frozen")

    assert discover_runtime_config({"LOCALAPPDATA": str(tmp_path / "empty")}, executable) is None
