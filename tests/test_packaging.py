"""Focused validation for the local PyInstaller packaging contract."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tools.build_package import (
    APPLICATION_STEM,
    RESOURCE_ARCHIVE_STEM,
    PackageLayout,
    archive_application,
    build_command,
    host_platform,
)

ROOT = Path(__file__).parents[1]
SPEC = ROOT / "packaging" / "hanly-desktop.spec"
RUNTIME_HOOK = ROOT / "packaging" / "runtime_hook.py"


def test_host_platform_normalizes_supported_system_names() -> None:
    assert host_platform("win32") == "windows"
    assert host_platform("darwin") == "macos"
    assert host_platform("linux") == "linux"


def test_package_layout_exposes_handoff_artifact_conventions(tmp_path: Path) -> None:
    layout = PackageLayout.for_platform(tmp_path, "windows")

    assert APPLICATION_STEM == "hanly-desktop"
    assert RESOURCE_ARCHIVE_STEM == "hanly-resources"
    assert layout.application_directory == tmp_path / "dist" / "windows" / APPLICATION_STEM
    assert layout.executable == layout.application_directory / "hanly-desktop.exe"
    assert layout.application_archive == tmp_path / "dist" / "hanly-desktop-windows.zip"


def test_for_platform_normalizes_the_host_when_no_platform_is_given(tmp_path: Path) -> None:
    layout = PackageLayout.for_platform(tmp_path)

    assert layout.platform_name == host_platform()
    assert layout.repo_root == tmp_path.resolve()


def test_archive_application_creates_the_release_handoff_archive(tmp_path: Path) -> None:
    layout = PackageLayout.for_platform(tmp_path, "windows")
    executable = layout.application_directory / "hanly-desktop.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"frozen executable")

    archive = archive_application(layout)

    assert archive == layout.application_archive
    assert archive.is_file()


def test_build_command_uses_spec_and_platform_scoped_dist(tmp_path: Path) -> None:
    command = build_command(
        PackageLayout.for_platform(tmp_path, "linux"),
        python_executable=Path("python"),
    )

    assert command[:4] == ["python", "-m", "PyInstaller", "--noconfirm"]
    assert "--onedir" not in command
    assert "--windowed" not in command
    assert "--name" not in command
    assert "--specpath" not in command
    assert command[command.index("--distpath") + 1] == str(
        tmp_path / "dist" / "linux"
    )
    assert command[-1] == str(tmp_path / "packaging" / "hanly-desktop.spec")


def test_packaging_spec_collects_app_engine_native_runtime_and_assets() -> None:
    source = SPEC.read_text(encoding="utf-8")

    for package_name in ("hanly", "hanly_app", "paddle", "paddleocr", "paddlex"):
        assert package_name in source
    assert "assets/control_center" in source
    assert "collect_dynamic_libs" in source
    assert "collect_submodules" in source
    assert "exclude_binaries=True" in source
    for backend in ("_win32", "_darwin", "_xorg"):
        assert backend in source
    assert "resources/dev" not in source
    assert ".paddlex" not in source


def test_runtime_hook_preloads_paddleocr_without_importing_qt() -> None:
    source = RUNTIME_HOOK.read_text(encoding="utf-8")

    assert "paddleocr" in source
    assert "PyQt6" not in source
    assert "preload_ocr_runtime" in source
    # Hanly has no torch dependency; stale search paths hide real gaps.
    assert "torch" not in source


def test_host_platform_rejects_an_unsupported_system_by_name() -> None:
    with pytest.raises(ValueError, match="freebsd"):
        host_platform("freebsd")


def test_build_command_defaults_to_current_interpreter_and_platform(tmp_path: Path) -> None:
    command = build_command(PackageLayout.for_platform(tmp_path))

    assert command[0] == sys.executable
    assert command[command.index("--distpath") + 1] == str(
        tmp_path / "dist" / host_platform()
    )
