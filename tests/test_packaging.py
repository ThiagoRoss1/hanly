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
from tools.smoke_packaged_runtime import (
    EASYOCR_MODEL_SUBDIRECTORY,
    EASYOCR_PATH_VARIABLES,
    HOME_VARIABLES,
    REQUIRED_MODEL_FILES,
    _ProfileContext,
    inspect_bundle,
    isolated_environment,
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

    for package_name in ("hanly", "hanly_app", "easyocr", "torch"):
        assert package_name in source
    assert "assets/control_center" in source
    assert "collect_dynamic_libs" in source
    assert "collect_submodules" in source
    assert "exclude_binaries=True" in source
    for backend in ("_win32", "_darwin", "_xorg"):
        assert backend in source
    assert "resources/dev" not in source
    assert "paddle" not in source


def test_packaging_spec_keeps_pkg_resources_out_of_the_bundle() -> None:
    """A setuptools upgrade can leave an empty ``pkg_resources`` directory
    behind. PyInstaller collects it as a namespace package and its runtime hook
    then fails on ``pkg_resources.NullProvider`` before the app starts."""

    source = SPEC.read_text(encoding="utf-8")

    assert 'EXCLUDED_MODULES = ("tests", "test", "spikes", "pkg_resources")' in source
    assert "excludes=list(EXCLUDED_MODULES)" in source


def test_runtime_hook_preloads_the_ocr_runtime_without_importing_qt() -> None:
    source = RUNTIME_HOOK.read_text(encoding="utf-8")

    assert "preload_ocr_runtime" in source
    assert "PyQt6" not in source


def test_there_is_exactly_one_way_to_start_hanly() -> None:
    """One command, one entry function. The packaged executable,
    `python -m hanly_app`, and the installed script all reach
    `hanly_app.cli:main`, and no launcher script is shipped beside the
    executable."""

    app_project = (ROOT / "packages" / "hanly-app" / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    entrypoint = (ROOT / "packaging" / "entrypoint.py").read_text(encoding="utf-8")
    module_main = (
        ROOT / "packages" / "hanly-app" / "src" / "hanly_app" / "__main__.py"
    ).read_text(encoding="utf-8")
    spec = (ROOT / "packaging" / "hanly-desktop.spec").read_text(encoding="utf-8")

    scripts = app_project.split("[project.scripts]", 1)[1].split("[", 1)[0]
    assert scripts.strip() == 'hanly = "hanly_app.cli:main"'

    assert "from hanly_app.cli import main" in entrypoint
    assert "from .cli import main" in module_main
    assert "hanly.cmd" not in spec
    assert not (ROOT / "packaging" / "hanly.cmd").exists()


def test_host_platform_rejects_an_unsupported_system_by_name() -> None:
    with pytest.raises(ValueError, match="freebsd"):
        host_platform("freebsd")


def test_build_command_defaults_to_current_interpreter_and_platform(tmp_path: Path) -> None:
    command = build_command(PackageLayout.for_platform(tmp_path))

    assert command[0] == sys.executable
    assert command[command.index("--distpath") + 1] == str(
        tmp_path / "dist" / host_platform()
    )


def test_packaging_spec_collects_morphology_as_a_mandatory_dependency() -> None:
    """The v0.1.0 Windows bundle shipped without Kiwi and never became ready.

    Collection must therefore sit outside the tolerant loop that is allowed to
    skip an absent optional package, and it must apply on every platform.
    """

    source = SPEC.read_text(encoding="utf-8")

    for package_name in ("kiwipiepy", "kiwipiepy_model", "_kiwipiepy"):
        assert package_name in source
    mandatory_block = source.split("for package_name in MANDATORY_PACKAGES:", 1)[1]
    assert "except Exception" not in mandatory_block.split("\n\n", 1)[0]
    assert "sys.platform" not in mandatory_block.split("\n\n", 1)[0]


def _write_bundle(root: Path, *, with_morphology: bool) -> Path:
    """Build a frozen-layout directory, optionally with the v0.1.0 defect."""

    internal = root / "_internal"
    (internal / "easyocr").mkdir(parents=True)
    if not with_morphology:
        return root

    (internal / "kiwipiepy").mkdir()
    (internal / "_kiwipiepy.pyd").write_bytes(b"native extension")
    model = internal / "kiwipiepy_model"
    model.mkdir()
    for name in REQUIRED_MODEL_FILES:
        (model / name).write_bytes(b"model data")
    return root


def test_bundle_inventory_reports_the_released_windows_defect(tmp_path: Path) -> None:
    inventory = inspect_bundle(_write_bundle(tmp_path / "app", with_morphology=False))

    assert not inventory.ok
    assert "kiwipiepy" in inventory.missing
    assert "kiwipiepy_model" in inventory.missing
    assert any("_kiwipiepy" in item for item in inventory.missing)
    assert "easyocr" in inventory.present


def test_bundle_inventory_accepts_a_complete_morphology_collection(tmp_path: Path) -> None:
    inventory = inspect_bundle(_write_bundle(tmp_path / "app", with_morphology=True))

    assert inventory.ok
    assert inventory.missing == ()
    assert "_kiwipiepy.pyd" in inventory.present


def test_the_frozen_smoke_cannot_fall_back_to_a_developer_model_cache(
    tmp_path: Path,
) -> None:
    """EasyOCR resolves models through three inherited paths, not one."""

    developer = tmp_path / "developer"
    profile, home, models = (tmp_path / name for name in ("profile", "home", "models"))

    environment = isolated_environment(
        {
            "EASYOCR_MODULE_PATH": str(developer / ".EasyOCR"),
            "MODULE_PATH": str(developer / "models"),
            "HOME": str(developer),
            "USERPROFILE": str(developer),
            "XDG_CACHE_HOME": str(developer / "cache"),
            "LOCALAPPDATA": str(developer / "AppData"),
            "HANLY_KRDICT_DB": str(developer / "krdict.sqlite3"),
        },
        profile,
        home,
        models,
    )

    assert all(environment[name] == str(models) for name in EASYOCR_PATH_VARIABLES)
    assert all(environment[name] == str(home) for name in HOME_VARIABLES)
    assert environment["LOCALAPPDATA"] == str(profile)
    assert "HANLY_KRDICT_DB" not in environment
    # Nothing left points anywhere the developer's own resources could be.
    assert str(developer) not in "".join(environment.values())


def test_a_named_model_cache_makes_the_isolated_run_deterministic(
    tmp_path: Path,
) -> None:
    """Offline determinism is opt-in and explicit, never an inherited accident."""

    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "korean_g2.pth").write_bytes(b"recognition model")

    with _ProfileContext(tmp_path / "profile", model_cache=cache) as (environment, _work):
        # EasyOCR appends "model" to whichever module path it resolved.
        seeded = Path(environment[EASYOCR_PATH_VARIABLES[0]]) / EASYOCR_MODEL_SUBDIRECTORY

        assert (seeded / "korean_g2.pth").read_bytes() == b"recognition model"


def test_a_missing_model_cache_is_named_rather_than_silently_ignored(
    tmp_path: Path,
) -> None:
    with pytest.raises(FileNotFoundError, match="EasyOCR model directory"):
        with _ProfileContext(tmp_path / "profile", model_cache=tmp_path / "absent"):
            pass
