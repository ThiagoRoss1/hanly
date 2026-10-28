"""Focused validation for the native Tauri product and Python service bundle."""

from __future__ import annotations

import json
import signal
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from hanly_app.service import self_check as service_self_check

from tools import build_package, prepare_easyocr_models, smoke_packaged_runtime
from tools.build_package import (
    APPLICATION_STEM,
    BUNDLE_NAME,
    NATIVE_HELPER_FLAGS,
    NATIVE_HELPER_SOURCE,
    RESOURCE_DIRECTORY,
    PackageLayout,
    PackagingError,
    archive_application,
    build_command,
    create_disk_image,
    host_platform,
    stage_native_application,
    write_tauri_build_config,
)
from tools.prepare_easyocr_models import (
    WEIGHTS,
    ModelPreparationError,
    Weight,
    file_md5,
    prepare_models,
)
from tools.smoke_packaged_runtime import (
    BUNDLE_NAME as SMOKE_BUNDLE_NAME,
)
from tools.smoke_packaged_runtime import (
    BUNDLE_SIGNATURE,
    EASYOCR_MODEL_SUBDIRECTORY,
    EASYOCR_PATH_VARIABLES,
    HEADLESS_SELF_CHECK_MODES,
    HOME_VARIABLES,
    LOCAL_KRDICT_VARIABLE,
    REQUIRED_DATA_FILES,
    REQUIRED_MODEL_FILES,
    _executable_in,
    _iter_failures,
    _ProfileContext,
    _self_check_command,
    compare_to_manifest,
    inspect_bundle,
    isolated_environment,
    reconstruct_application,
    reconstruct_from_disk_image,
    run_packaged_self_check,
    verify_disk_image,
)
from tools.smoke_packaged_runtime import main as smoke_main

ROOT = Path(__file__).parents[1]
SPEC = ROOT / "packaging" / "hanly-service.spec"
RUNTIME_HOOK = ROOT / "packaging" / "runtime_hook.py"
RELEASE_CONSTRAINTS = ROOT / "packaging" / "release-constraints.txt"


def test_host_platform_normalizes_supported_system_names() -> None:
    assert host_platform("win32") == "windows"
    assert host_platform("darwin") == "macos"
    assert host_platform("linux") == "linux"


def test_package_layout_exposes_handoff_artifact_conventions(tmp_path: Path) -> None:
    layout = PackageLayout.for_platform(tmp_path, "windows")

    assert APPLICATION_STEM == "hanly-desktop"
    assert RESOURCE_DIRECTORY == "resources"
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
    assert command[command.index("--distpath") + 1] == str(tmp_path / "dist")
    assert command[-1] == str(tmp_path / "packaging" / "hanly-service.spec")


def test_a_windows_build_neither_builds_nor_collects_the_posix_helper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = PackageLayout.for_platform(tmp_path, "windows")
    monkeypatch.setenv("HANLY_UPDATE_HELPER", str(tmp_path / "unexpected-helper"))
    monkeypatch.setattr(build_package, "_stamp_build", lambda *_args: object())
    monkeypatch.setattr(build_package, "build_command", lambda *_args, **_kwargs: ["freeze"])
    monkeypatch.setattr(
        build_package,
        "build_native_helper",
        lambda *_args, **_kwargs: pytest.fail("Windows tried to build the POSIX helper"),
    )

    def run(command: list[str], **kwargs: object) -> SimpleNamespace:
        assert command == ["freeze"]
        environment = cast(dict[str, str], kwargs["env"])
        assert "HANLY_UPDATE_HELPER" not in environment
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr(build_package.subprocess, "run", run)

    assert build_package.run_build(layout) == 7


def _unguarded_fault_hooks(source: str) -> list[str]:
    """Every line naming a fault hook from outside the block that compiles it."""

    guarded = False
    unguarded: list[str] = []
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("#ifdef HANLY_UPDATER_TEST_HOOKS"):
            guarded = True
        elif stripped.startswith("#endif"):
            guarded = False
        elif "HANLY_TEST_" in line and not guarded:
            unguarded.append(stripped)
    return unguarded


def test_a_released_helper_carries_none_of_its_fault_injection() -> None:
    """The failures the native cases inject are a compile-time opt-in.

    A hook reachable in a shipped helper would be a way to make a real update
    fail, so the release flags never define it and no hook is read outside the
    block it is compiled in.
    """

    assert not any("HANLY_UPDATER_TEST_HOOKS" in flag for flag in NATIVE_HELPER_FLAGS)
    assert _unguarded_fault_hooks((ROOT / NATIVE_HELPER_SOURCE).read_text(encoding="utf-8")) == []


def test_service_spec_collects_python_runtime_and_excludes_old_desktop_frameworks() -> None:
    source = SPEC.read_text(encoding="utf-8")

    for package_name in ("hanly", "hanly_app.service", "hanly_app.lookup", "easyocr", "torch"):
        assert package_name in source
    assert "collect_submodules" in source
    assert "exclude_binaries=True" in source
    assert "console=True" in source
    assert "PyQt6" in source and "PySide6" in source
    assert "pywebview" in source and "pystray" in source
    assert "pynput.mouse._darwin" in source
    assert "resources/dev" not in source
    assert "paddle" not in source


def test_packaging_spec_keeps_pkg_resources_out_of_the_bundle() -> None:
    """A setuptools upgrade can leave an empty ``pkg_resources`` directory
    behind. PyInstaller collects it as a namespace package and its runtime hook
    then fails on ``pkg_resources.NullProvider`` before the app starts."""

    source = SPEC.read_text(encoding="utf-8")

    assert '"pkg_resources"' in source
    assert "excludes=list(EXCLUDED_MODULES)" in source


def test_macos_bundle_signing_stays_ad_hoc_without_hardened_runtime_options() -> None:
    """The local unsigned release keeps the ad-hoc, cdhash-bound designated requirement."""

    commands: list[list[str]] = []

    def run(command: list[str], **_options: object) -> SimpleNamespace:
        commands.append(command)
        return SimpleNamespace(returncode=0)

    build_package.sign_macos_bundle(ROOT / "dist/Hanly.app", runner=run)

    assert commands[0][1:6] == ["--force", "--deep", "--sign", "-", "--timestamp=none"]
    assert commands[1][1:4] == ["--verify", "--deep", "--strict"]
    assert len(commands) == 2
    # An explicit requirement such as `identifier "…"` would let any ad-hoc
    # code naming that identifier inherit Hanly's privacy grants.
    assert not any(argument.startswith(("-r", "--requirements")) for argument in commands[0])
    assert not any(
        "runtime" in argument or "entitlements" in argument
        for command in commands
        for argument in command
    )


def test_the_runtime_hook_loads_no_role_specific_library() -> None:
    """It runs in every process, the Control Center and lookup children
    included, so importing Qt WebEngine or the OCR stack here would put back
    exactly the memory the process split exists to release."""

    source = RUNTIME_HOOK.read_text(encoding="utf-8")

    assert "preload_ocr_runtime" not in source
    assert "PyQt6" not in source
    assert "silence_runtime_warnings" in source


def test_the_entry_point_diverts_spawned_children_before_anything_else() -> None:
    """A frozen child re-enters through this same executable. Without this
    first, it would parse arguments and start a second desktop."""

    source = (ROOT / "packaging" / "service_entrypoint.py").read_text(encoding="utf-8")
    body = source.split("def run(", 1)[1]
    assert "multiprocessing.freeze_support()" in body
    assert body.index("multiprocessing.freeze_support()") < body.index(
        "from hanly_app.service.server import main"
    )


def test_there_is_exactly_one_way_to_start_hanly() -> None:
    """The native root is the product entry; Python is only its service child."""

    cargo = (ROOT / "apps" / "desktop" / "src-tauri" / "Cargo.toml").read_text(
        encoding="utf-8"
    )
    native_main = (ROOT / "apps" / "desktop" / "src-tauri" / "src" / "main.rs").read_text(
        encoding="utf-8"
    )
    assert 'name = "hanly-desktop"' in cargo
    assert "hanly_desktop::run" in native_main
    assert "console=True" in SPEC.read_text(encoding="utf-8")


def test_service_inventory_self_check_does_not_construct_runtime_providers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime_root = tmp_path / "_internal"
    for relative in service_self_check._REQUIRED_DATA_FILES:
        required = runtime_root / relative
        required.parent.mkdir(parents=True, exist_ok=True)
        required.write_bytes(b"present")

    stamp = SimpleNamespace(
        build_id="build-id",
        source_commit="a" * 40,
        version="1.1.0",
    )
    monkeypatch.setattr(service_self_check.sys, "frozen", True, raising=False)
    monkeypatch.setattr(service_self_check.sys, "_MEIPASS", str(runtime_root), raising=False)
    monkeypatch.setattr(service_self_check, "read_build_stamp", lambda: stamp)
    monkeypatch.setattr(
        service_self_check,
        "_load_runtime",
        lambda _path: pytest.fail("inventory must not load the runtime"),
    )

    report = service_self_check.run_service_self_check("inventory")
    versions = cast(dict[str, str], report["versions"])
    stages = cast(list[dict[str, object]], report["stages"])

    assert report["ok"] is True
    assert report["mode"] == "inventory"
    assert versions["build_id"] == "build-id"
    assert [stage["name"] for stage in stages] == ["inventory"]


def test_source_inventory_resolves_easyocr_data_from_its_distribution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from importlib.machinery import ModuleSpec

    site_packages = tmp_path / "site-packages"
    package_specs: dict[str, ModuleSpec] = {}
    for name in ("certifi", "easyocr", "torch", "kiwipiepy", "kiwipiepy_model"):
        package_root = site_packages / name
        package_root.mkdir(parents=True, exist_ok=True)
        spec = ModuleSpec(
            name, loader=None, origin=str(package_root / "__init__.py"), is_package=True
        )
        spec.submodule_search_locations = [str(package_root)]
        package_specs[name] = spec

    easyocr_characters = site_packages / "easyocr" / "character"
    easyocr_characters.mkdir(parents=True)
    (easyocr_characters / "ko_char.txt").write_text("ko", encoding="utf-8")

    app_root = tmp_path / "source" / "hanly_app"
    app_root.mkdir(parents=True)
    for relative in service_self_check._REQUIRED_DATA_FILES[1:]:
        if relative.startswith("hanly_app/"):
            resource = app_root / relative.removeprefix("hanly_app/")
            resource.parent.mkdir(parents=True, exist_ok=True)
            resource.write_bytes(b"present")

    def fake_find_spec(name: str) -> ModuleSpec | None:
        return package_specs.get(name)

    monkeypatch.setattr(service_self_check, "__file__", str(app_root / "service" / "self_check.py"))
    monkeypatch.setattr(service_self_check.sys, "frozen", False, raising=False)
    monkeypatch.setattr("importlib.util.find_spec", fake_find_spec)

    assert service_self_check._inventory() == (
        "build identity and required service data are present"
    )


def test_service_worker_self_check_closes_providers_and_omits_lookup_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Worker:
        def __init__(self) -> None:
            self.closed = False

        def __call__(self, _request: object) -> SimpleNamespace:
            entry = SimpleNamespace(word="한국어")
            context = SimpleNamespace(analyses=(object(),), ocr_results=())
            return SimpleNamespace(entries=(entry,), context=context)

        def close(self) -> None:
            self.closed = True

    worker = Worker()
    runtime = SimpleNamespace(
        create_worker_factory=lambda: lambda: worker,
    )
    config = tmp_path / "runtime.json"
    config.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(service_self_check, "_inventory", lambda: "inventory ok")
    monkeypatch.setattr(service_self_check, "_load_runtime", lambda _path: runtime)
    monkeypatch.setattr(
        service_self_check, "_versions", lambda: {"hanly-app": "1.1.0"}
    )

    report = service_self_check.run_service_self_check(
        "worker", runtime_config=config
    )
    stages = cast(list[dict[str, object]], report["stages"])

    assert report["ok"] is True
    assert worker.closed is True
    assert "한국어" not in str(report)
    assert {stage["name"] for stage in stages} == {
        "inventory",
        "runtime configuration",
        "runtime",
        "lookup worker",
        "dictionary",
        "morphology",
        "worker close",
    }


def test_host_platform_rejects_an_unsupported_system_by_name() -> None:
    with pytest.raises(ValueError, match="freebsd"):
        host_platform("freebsd")


def test_build_command_defaults_to_current_interpreter_and_platform(tmp_path: Path) -> None:
    command = build_command(PackageLayout.for_platform(tmp_path))

    assert command[0] == sys.executable
    assert command[command.index("--distpath") + 1] == str(
        tmp_path / "dist"
    )


def test_tauri_resources_are_mapped_only_after_the_frozen_inputs_exist(
    tmp_path: Path,
) -> None:
    layout = PackageLayout.for_platform(tmp_path, "macos")
    layout.service_executable.parent.mkdir(parents=True)
    layout.service_executable.write_bytes(b"service")
    layout.native_helper_input.write_bytes(b"helper")

    overlay = write_tauri_build_config(layout)
    config = json.loads(overlay.read_text(encoding="utf-8"))

    assert config["bundle"]["active"] is True
    assert config["bundle"]["resources"][str(layout.service_root.resolve())] == "hanly-service"
    assert (
        config["bundle"]["resources"][str(layout.native_helper_input.resolve())]
        == "hanly-update-posix"
    )


def test_portable_native_product_stages_service_under_resources(tmp_path: Path) -> None:
    layout = PackageLayout.for_platform(tmp_path, "linux")
    layout.tauri_release_executable.parent.mkdir(parents=True)
    layout.tauri_release_executable.write_bytes(b"native root")
    layout.service_executable.parent.mkdir(parents=True)
    layout.service_executable.write_bytes(b"service")
    layout.native_helper_input.write_bytes(b"helper")

    stage_native_application(layout)

    assert layout.executable.read_bytes() == b"native root"
    assert (
        layout.resource_directory / "hanly-service" / "hanly-service"
    ).read_bytes() == b"service"
    assert (layout.resource_directory / "hanly-update-posix").read_bytes() == b"helper"


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


def _write_bundle(
    root: Path,
    *,
    with_morphology: bool,
    internal_parts: tuple[str, ...] | None = None,
) -> Path:
    """Build a native-root/service layout, optionally missing morphology."""

    resources = (
        root / "Contents" / "Resources"
        if root.suffix == ".app"
        else root / "resources"
    )
    service_root = resources / "hanly-service"
    internal = service_root.joinpath(
        *(internal_parts if internal_parts is not None else ("_internal",))
    )
    (internal / "easyocr").mkdir(parents=True)
    service_executable = service_root / (
        "hanly-service.exe" if sys.platform == "win32" else "hanly-service"
    )
    service_executable.parent.mkdir(parents=True, exist_ok=True)
    service_executable.write_bytes(b"service")
    native_executable = (
        root / "Contents" / "MacOS" / APPLICATION_STEM
        if root.suffix == ".app"
        else root / f"{APPLICATION_STEM}{'.exe' if sys.platform == 'win32' else ''}"
    )
    native_executable.parent.mkdir(parents=True, exist_ok=True)
    native_executable.write_bytes(b"native root")
    for relative in REQUIRED_DATA_FILES:
        data_file = internal.joinpath(*relative.split("/"))
        data_file.parent.mkdir(parents=True, exist_ok=True)
        data_file.write_bytes(b"build input")
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


def test_the_frozen_smoke_names_a_signal_when_no_stage_survived() -> None:
    """A process killed during startup reports nothing of its own."""

    failures = list(
        _iter_failures(
            {
                "ok": False,
                "stages": [],
                "stdout": "",
                "exit_code": -int(signal.SIGABRT),
                "exit_timeout": False,
                "stderr": "native runtime could not load a required platform library\n",
            }
        )
    )

    assert "SIGABRT" in failures[0]
    assert "required platform library" in failures[1]


def test_the_frozen_smoke_names_a_fatal_windows_exception() -> None:
    """Windows reports a fatal fault as the raw NTSTATUS, not as a signal, and
    "exited with status 3221225501" is not a diagnosis anyone can act on."""

    failures = list(
        _iter_failures(
            {
                "ok": False,
                "stages": [],
                "stdout": "",
                "exit_code": 0xC000001D,
                "exit_timeout": False,
                "stderr": "Windows fatal exception: code 0xc000001d",
            }
        )
    )

    assert "ILLEGAL_INSTRUCTION" in failures[0]
    assert "0xC000001D" in failures[0]


def test_an_ordinary_windows_exit_status_is_not_read_as_a_fault() -> None:
    """The fault range starts at 0xC0000000; a small status is a program's own
    chosen exit code and naming it an exception would invent a crash."""

    failures = list(_iter_failures({"stages": [], "exit_code": 2, "stderr": ""}))

    assert failures[0].endswith("exit: status 2")


def test_the_frozen_smoke_reports_a_failed_stage_rather_than_the_exit() -> None:
    """A stage that failed is the diagnosis; the status adds nothing to it."""

    failures = list(
        _iter_failures(
            {
                "stages": [
                    {"name": "runtime", "ok": True, "detail": ""},
                    {"name": "dictionary", "ok": False, "detail": "no entry"},
                ],
                "exit_code": 1,
            }
        )
    )

    assert failures == ["dictionary: no entry"]


def test_the_self_check_traces_a_native_crash_before_it_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Torch and Kiwi end the process rather than raise. Without the fault
    handler a crashed frozen bundle reports an exit status and nothing else."""

    enabled: list[str] = []
    monkeypatch.setattr(
        service_self_check.faulthandler, "enable", lambda *_, **__: enabled.append("on")
    )

    with pytest.raises(ValueError):
        service_self_check.run_service_self_check("unsupported")

    assert enabled == ["on"]


@pytest.mark.parametrize("mode", service_self_check.SELF_CHECK_MODES)
def test_native_service_checks_preserve_the_callers_display_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    """Only the native UI check needs a display; service checks dispatch headlessly."""

    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.setenv("QT_QPA_PLATFORM", "xcb")
    launched: dict[str, object] = {}

    def popen(*args: object, **kwargs: object) -> SimpleNamespace:
        launched["command"] = args[0]
        launched["environment"] = kwargs["env"]
        return SimpleNamespace(pid=0, wait=lambda timeout=None: 0)

    monkeypatch.setattr(smoke_packaged_runtime.subprocess, "Popen", popen)

    run_packaged_self_check(tmp_path / "hanly-desktop", mode=mode)

    environment = cast(dict[str, str], launched["environment"])
    command = cast(list[str], launched["command"])
    assert environment["DISPLAY"] == ":99"
    assert environment["QT_QPA_PLATFORM"] == "xcb"
    assert command[-2:] == ["--self-check", mode]


def test_inventory_ocr_and_worker_checks_dispatch_without_the_native_window() -> None:
    """The Rust launcher routes service-only modes without constructing Tauri."""

    assert HEADLESS_SELF_CHECK_MODES == ("inventory", "ocr", "worker")
    assert set(HEADLESS_SELF_CHECK_MODES) == set(service_self_check.SELF_CHECK_MODES) - {
        "ui"
    }


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


def test_a_named_dictionary_is_the_only_one_the_frozen_run_may_install(
    tmp_path: Path,
) -> None:
    """Without one the frozen bundle provisions itself from the release channel,
    and the check depends on an unauthenticated GitHub API call."""

    dictionary = tmp_path / "krdict.sqlite3"
    dictionary.write_bytes(b"dictionary")

    with _ProfileContext(tmp_path / "profile", krdict=dictionary) as (environment, _work):
        assert environment[LOCAL_KRDICT_VARIABLE] == str(dictionary)


def test_a_missing_dictionary_is_named_rather_than_quietly_downloaded(
    tmp_path: Path,
) -> None:
    with pytest.raises(FileNotFoundError, match="no KRDICT database"):
        with _ProfileContext(tmp_path / "profile", krdict=tmp_path / "absent.sqlite3"):
            pass


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


def test_the_macos_product_is_an_app_bundle_with_the_shared_executable(
    tmp_path: Path,
) -> None:
    """macOS installs, signs, and updates an .app, not a loose directory."""

    layout = PackageLayout.for_platform(tmp_path, "macos")

    assert BUNDLE_NAME == "Hanly.app"
    assert layout.application_directory == tmp_path / "dist" / "macos" / BUNDLE_NAME
    assert layout.executable == (
        layout.application_directory / "Contents" / "MacOS" / APPLICATION_STEM
    )
    assert layout.application_archive == tmp_path / "dist" / "hanly-desktop-macos.zip"
    assert layout.application_dmg == tmp_path / "dist" / "hanly-desktop-macos.dmg"


def test_only_linux_still_hands_off_a_tarball(tmp_path: Path) -> None:
    linux = PackageLayout.for_platform(tmp_path, "linux")

    assert linux.application_directory == tmp_path / "dist" / "linux" / APPLICATION_STEM
    assert linux.application_archive == tmp_path / "dist" / "hanly-desktop-linux.tar.gz"
    with pytest.raises(ValueError, match="macOS"):
        linux.application_dmg


class _NativeTool:
    """Records the macOS packaging commands and writes what they would."""

    def __init__(self, returncode: int = 0) -> None:
        self.returncode = returncode
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str], **_options: object) -> object:
        self.commands.append(command)
        target = Path(command[-1])
    # Only archive commands name an output file; unpacking names a directory,
    # and detach may end in a flag such as ``-force``.
        writes_a_file = (
            self.returncode == 0 and not command[-1].startswith("-") and not target.is_dir()
        )
        if writes_a_file:
            target.write_bytes(b"native artifact")
        return SimpleNamespace(returncode=self.returncode, stderr=b"tool failed")


def _built_bundle(tmp_path: Path) -> PackageLayout:
    layout = PackageLayout.for_platform(tmp_path, "macos")
    executable = layout.executable
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"frozen executable")
    return layout


def test_the_macos_products_are_made_by_macos_own_tools(tmp_path: Path) -> None:
    """A Python-written ZIP loses the links and bits that make it an app."""

    layout = _built_bundle(tmp_path)
    ditto, hdiutil = _NativeTool(), _NativeTool()

    archive = archive_application(layout, runner=ditto)
    image = create_disk_image(layout, runner=hdiutil)

    assert archive == layout.application_archive
    assert image == layout.application_dmg
    assert ditto.commands[0][:5] == [
        "/usr/bin/ditto",
        "-c",
        "-k",
        "--sequesterRsrc",
        "--keepParent",
    ]
    assert ditto.commands[0][5:] == [str(layout.application_directory), str(archive)]
    assert hdiutil.commands[0][0] == "/usr/bin/hdiutil"
    assert "-srcfolder" in hdiutil.commands[0]
    assert hdiutil.commands[0][-1] == str(image)
    # Both products are read from the same application, which neither modifies.
    assert layout.executable.read_bytes() == b"frozen executable"


def test_a_failing_native_packaging_tool_is_reported_not_ignored(tmp_path: Path) -> None:
    layout = _built_bundle(tmp_path)

    with pytest.raises(PackagingError, match="tool failed"):
        archive_application(layout, runner=_NativeTool(returncode=1))


def test_archiving_a_onedir_build_still_needs_no_native_tool(tmp_path: Path) -> None:
    layout = PackageLayout.for_platform(tmp_path, "linux")
    executable = layout.executable
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"frozen executable")

    archive = archive_application(layout)

    assert archive == layout.application_archive
    assert archive.is_file()


def test_the_tauri_bundle_preserves_product_identity_and_version() -> None:
    source = (
        ROOT / "apps" / "desktop" / "src-tauri" / "tauri.conf.json"
    ).read_text(encoding="utf-8")

    assert '"identifier": "io.github.thiagoross1.hanly"' in source
    assert '"productName": "Hanly"' in source
    assert '"version": "1.1.0"' in source


def test_the_spec_collects_the_inputs_a_frozen_build_cannot_fetch() -> None:
    """Verified TLS and OCR both fail in a bundle that has to download."""

    source = SPEC.read_text(encoding="utf-8")

    assert 'collect_data_files("certifi")' in source
    assert "assets/easyocr_models/*.pth" in source
    assert 'MODEL_FILES = ("craft_mlt_25k.pth", "korean_g2.pth")' in source
    assert "prepare_easyocr_models.py" in source


def test_the_spec_uses_targeted_easyocr_hook_and_keeps_other_collections() -> None:
    source = SPEC.read_text(encoding="utf-8")

    assert 'for package_name in ("easyocr", "torchvision"):' in source
    # Korean recognition decodes against both character sets, and ``easyocr``
    # configuration may legally name either, so neither may be dropped.
    assert 'hooksconfig={"easyocr": {"lang_codes": ["ko", "en"]}}' in source
    assert 'for distribution in ("hanly-app", "hanly", "easyocr"):' in source
    assert 'collect_all(package_name)' in source
    assert "MANDATORY_PACKAGES" in source


def test_release_inputs_pin_freezer_without_a_gui_runtime() -> None:
    pins = RELEASE_CONSTRAINTS.read_text(encoding="utf-8")

    assert "easyocr==1.7.2" in pins
    assert "pyinstaller==6.22.2" in pins
    assert "pyinstaller-hooks-contrib==2026.7" in pins
    assert "PyQt" not in pins and "Qt" not in pins


def test_the_bundled_weights_are_the_two_easyocr_actually_loads() -> None:
    assert tuple(weight.name for weight in WEIGHTS) == (
        "craft_mlt_25k.pth",
        "korean_g2.pth",
    )
    for weight in WEIGHTS:
        assert weight.url.startswith("https://")
        assert len(weight.md5) == 32


def _archive_containing(path: Path, members: dict[str, bytes]) -> bytes:
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    path.write_bytes(buffer.getvalue())
    return buffer.getvalue()


class _Opener:
    """Serves prepared archive bytes instead of reaching the network."""

    def __init__(self, payloads: dict[str, bytes]) -> None:
        self.payloads = payloads
        self.calls: list[tuple[str, float | None]] = []

    def __call__(self, url: str, timeout: float | None = None) -> object:
        import io

        self.calls.append((url, timeout))
        return io.BytesIO(self.payloads[url])


def _synthetic_weight(tmp_path: Path, payload: bytes, **members: bytes) -> tuple[Weight, bytes]:
    """Build one weight whose published digest is the payload's own."""

    import hashlib

    entries = {"weights.pth": payload}
    entries.update(members)
    archive = _archive_containing(tmp_path / "upstream.zip", entries)
    weight = Weight(
        "weights.pth",
        "https://example.invalid/weights.zip",
        hashlib.md5(payload).hexdigest(),
    )
    return weight, archive


def test_a_weight_is_fetched_verified_and_then_reused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    weight, archive = _synthetic_weight(tmp_path, b"recognition weights")
    monkeypatch.setattr(prepare_easyocr_models, "WEIGHTS", (weight,))
    opener = _Opener({weight.url: archive})
    destination = tmp_path / "models"

    (prepared,) = prepare_models(destination, opener=opener)

    assert prepared == destination / "weights.pth"
    assert file_md5(prepared) == weight.md5
    assert opener.calls == [(weight.url, prepare_easyocr_models.REQUEST_TIMEOUT_SECONDS)]

    prepare_models(destination, opener=opener)

    # An already-correct file is not downloaded again.
    assert len(opener.calls) == 1


def test_content_that_is_not_the_published_weight_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    weight, _ = _synthetic_weight(tmp_path, b"recognition weights")
    tampered = _archive_containing(tmp_path / "tampered.zip", {"weights.pth": b"something else"})
    monkeypatch.setattr(prepare_easyocr_models, "WEIGHTS", (weight,))
    destination = tmp_path / "models"

    with pytest.raises(ModelPreparationError, match="does not match"):
        prepare_models(destination, opener=_Opener({weight.url: tampered}))

    assert not (destination / "weights.pth").exists()


def test_nothing_but_the_named_weight_leaves_the_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A release archive is not a directory tree to unpack wherever it says."""

    weight, archive = _synthetic_weight(
        tmp_path,
        b"recognition weights",
        **{"../escaped.txt": b"nope", "extra/notes.txt": b"nope"},
    )
    monkeypatch.setattr(prepare_easyocr_models, "WEIGHTS", (weight,))
    destination = tmp_path / "models"

    prepare_models(destination, opener=_Opener({weight.url: archive}))

    assert sorted(item.name for item in destination.iterdir()) == ["weights.pth"]
    assert not (tmp_path / "escaped.txt").exists()


def test_an_archive_without_the_weight_is_reported_by_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    empty = _archive_containing(tmp_path / "empty.zip", {"readme.txt": b"nothing here"})
    weight = Weight("weights.pth", "https://example.invalid/weights.zip", "0" * 32)
    monkeypatch.setattr(prepare_easyocr_models, "WEIGHTS", (weight,))

    with pytest.raises(ModelPreparationError, match="weights.pth"):
        prepare_models(tmp_path / "models", opener=_Opener({weight.url: empty}))


def test_a_weight_is_never_fetched_over_plain_http(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    weight = Weight("weights.pth", "http://example.invalid/weights.zip", "0" * 32)
    monkeypatch.setattr(prepare_easyocr_models, "WEIGHTS", (weight,))
    opener = _Opener({})

    with pytest.raises(ModelPreparationError, match="HTTPS"):
        prepare_models(tmp_path / "models", opener=opener)

    assert opener.calls == []


def test_every_producer_and_consumer_names_the_same_release_products() -> None:
    """The builder, the release contract, and the updater must not drift apart."""

    from hanly_app.updates import desktop_update as app_update
    from hanly_app.updates.manifest import (
        MANIFEST_ASSET,
        UPDATE_METADATA_ASSET,
        delta_asset_name,
    )

    from tools.release_build import DELTA_ASSET, FIXED_RELEASE_ASSETS

    root = Path("/repo")
    produced = set()
    for platform_name in ("windows", "macos", "linux"):
        layout = PackageLayout.for_platform(root, platform_name)
        produced.add(layout.application_archive.name)
        if platform_name == "macos":
            produced.add(layout.application_dmg.name)

    assert produced == {
        "hanly-desktop-windows.zip",
        "hanly-desktop-macos.zip",
        "hanly-desktop-macos.dmg",
        "hanly-desktop-linux.tar.gz",
    }
    # Derive metadata names from producer constants so a release rename fails
    # this test instead of surfacing only during publication.
    assert produced < FIXED_RELEASE_ASSETS
    assert FIXED_RELEASE_ASSETS - produced == {
        MANIFEST_ASSET,
        UPDATE_METADATA_ASSET,
        "hanly-resources.json",
        "SHA256SUMS",
    }
    # The delta is the one asset named by shape rather than spelled out, so the
    # release contract's pattern has to match what the builder actually writes.
    assert DELTA_ASSET.fullmatch(delta_asset_name("0.5.1", "0.5.2")) is not None
    assert not any(DELTA_ASSET.fullmatch(name) for name in FIXED_RELEASE_ASSETS)

    installed = {
        layout.asset_name for layout in app_update._PLATFORM_LAYOUTS.values()
    }
    # Every asset the updater downloads is one the build publishes, and the
    # disk image is never one of them.
    assert installed < produced
    assert "hanly-desktop-macos.dmg" not in installed


# --- the packaged smoke, pointed at what is actually published ---------------


def test_the_inventory_names_the_inputs_a_frozen_build_cannot_fetch(
    tmp_path: Path,
) -> None:
    """Verified TLS and offline OCR both fail on a bundle missing these."""

    bundle = _write_bundle(tmp_path / "app", with_morphology=True)
    missing = inspect_bundle(bundle)
    for relative in REQUIRED_DATA_FILES:
        bundle.joinpath(
            "resources", "hanly-service", "_internal", *relative.split("/")
        ).unlink()

    assert missing.ok
    assert set(REQUIRED_DATA_FILES) <= set(missing.present)
    assert set(inspect_bundle(bundle).missing) == set(REQUIRED_DATA_FILES)


def test_the_inventory_reads_a_macos_bundles_split_collection(tmp_path: Path) -> None:
    """A .app keeps the same tree under Contents, not beside the executable."""

    application = tmp_path / SMOKE_BUNDLE_NAME
    _write_bundle(
        application,
        with_morphology=True,
        internal_parts=("_internal",),
    )
    program = application / "Contents" / "MacOS" / APPLICATION_STEM
    program.parent.mkdir(parents=True, exist_ok=True)
    program.write_bytes(b"frozen executable")
    signature = application.joinpath(*BUNDLE_SIGNATURE.split("/"))
    signature.parent.mkdir(parents=True)
    signature.write_bytes(b"<signature>")

    inventory = inspect_bundle(application)

    assert inventory.ok
    assert _executable_in(application) == program

    # PyInstaller only warns when signing fails, and Hanly's updater refuses an
    # application that carries no signature.
    signature.unlink()
    assert inspect_bundle(application).missing == (BUNDLE_SIGNATURE,)


def _published_zip(path: Path) -> Path:
    """Stand in for the ditto archive the release publishes."""

    import zipfile

    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{SMOKE_BUNDLE_NAME}/Contents/MacOS/{APPLICATION_STEM}", b"program")
        archive.writestr(f"{SMOKE_BUNDLE_NAME}/Contents/Info.plist", b"<plist/>")
    return path


def test_the_published_zip_is_unpacked_back_into_an_application(tmp_path: Path) -> None:
    archive = _published_zip(tmp_path / "hanly-desktop-macos.zip")
    ditto = _NativeTool()

    def unpack(command: list[str], **options: object) -> object:
        import zipfile

        with zipfile.ZipFile(command[-2]) as bundle:
            bundle.extractall(command[-1])
        return ditto(command, **options)

    application = reconstruct_application(archive, tmp_path / "out", runner=unpack)

    assert application == (tmp_path / "out" / SMOKE_BUNDLE_NAME)
    assert ditto.commands[0][:3] == ["/usr/bin/ditto", "-x", "-k"]
    assert _executable_in(application).is_file()


def test_an_archive_without_the_application_is_reported(tmp_path: Path) -> None:
    archive = tmp_path / "hanly-desktop-macos.zip"
    archive.write_bytes(b"not a bundle")

    with pytest.raises(FileNotFoundError, match=SMOKE_BUNDLE_NAME):
        reconstruct_application(archive, tmp_path / "out", runner=_NativeTool())


def test_the_disk_image_is_mounted_read_only_and_always_unmounted(
    tmp_path: Path,
) -> None:
    """The DMG is what a person opens; nothing here may leave it attached."""

    image = tmp_path / "hanly-desktop-macos.dmg"
    image.write_bytes(b"disk image")
    hdiutil = _NativeTool()

    def mount(command: list[str], **options: object) -> object:
        hdiutil.commands.append(command)
        if command[1] == "attach":
            program = Path(command[-1]) / SMOKE_BUNDLE_NAME / "Contents" / "MacOS"
            program.mkdir(parents=True)
            (program / APPLICATION_STEM).write_bytes(b"program")
        return SimpleNamespace(returncode=0, stderr=b"")

    report = verify_disk_image(image, runner=mount)

    assert report["ok"] is True
    assert report["contents"] == [SMOKE_BUNDLE_NAME]
    assert hdiutil.commands[0][:2] == ["/usr/bin/hdiutil", "attach"]
    assert "-readonly" in hdiutil.commands[0]
    assert hdiutil.commands[-1][:2] == ["/usr/bin/hdiutil", "detach"]


def test_a_disk_image_that_cannot_be_read_fails_without_leaving_a_mount(
    tmp_path: Path,
) -> None:
    image = tmp_path / "hanly-desktop-macos.dmg"
    image.write_bytes(b"corrupt")

    with pytest.raises(RuntimeError, match="could not mount"):
        verify_disk_image(image, runner=_NativeTool(returncode=1))


def test_lookup_child_does_not_own_desktop_lifecycle() -> None:
    """The lookup child only builds providers; the service provisions resources
    and the native root owns windows, shortcuts and update acknowledgement."""

    forbidden = (
        "provision_runtime_config",
        "confirm_started",
        "run_desktop",
        "hanly_app.hotkeys",
    )
    app = ROOT / "packages" / "hanly-app" / "src" / "hanly_app"
    assert not (app / "control_center" / "process.py").exists()
    children = (app / "lookup" / "process.py",)
    for path in children:
        source = path.read_text(encoding="utf-8")
        for name in forbidden:
            assert name not in source, f"{path.name} reaches {name}"


# --- progress markers, which are all a killed frozen run leaves behind -------

#: A run that reaches the report. Two stages complete, and the JSON the harness
#: parses is printed last, exactly as the real check prints it.
_COMPLETED_PROGRAM = """
import json

from hanly_app.service import self_check

stages = []
self_check._stage(stages, "runtime", lambda: "loaded", success_detail="loaded")
self_check._stage(stages, "dictionary", lambda: "1 entry", success_detail="1 entry")
print(json.dumps({"mode": "worker", "ok": True, "stages": stages}, indent=2), flush=True)
"""

#: A run killed inside a stage. ``os._exit`` rather than a real fault: the
#: point is that no report and no completion marker is written, which is what a
#: native abort looks like from outside, without a crash report to collect.
_KILLED_PROGRAM = """
import os

from hanly_app.service import self_check

stages = []
self_check._stage(stages, "runtime", lambda: "loaded", success_detail="loaded")
self_check._stage(stages, "ocr", lambda: os._exit(134))
"""

#: A run that starts a stage and never leaves it.
_HANGING_PROGRAM = """
import time

from hanly_app.service import self_check

self_check._emit_marker(self_check.STAGE_STARTED, "main window")
time.sleep(120)
"""


def _self_check_program(directory: Path, program: str) -> Path:
    """Write a stand-in the harness launches the way it launches a bundle.

    A launcher rather than the program itself, because the harness runs one
    executable path and Windows does not run a ``.py`` file as one.
    """

    directory.mkdir(parents=True, exist_ok=True)
    script = directory / "self_check_program.py"
    script.write_text(program, encoding="utf-8")

    if sys.platform == "win32":
        launcher = directory / "hanly-desktop.bat"
        launcher.write_text(
            f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n', encoding="utf-8"
        )
        return launcher

    launcher = directory / "hanly-desktop"
    launcher.write_text(
        f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8"
    )
    launcher.chmod(0o755)
    return launcher


def test_a_completed_run_still_parses_and_keeps_its_stage_timings(
    tmp_path: Path,
) -> None:
    """Markers travel on stderr, so the report on stdout is untouched by them."""

    report = run_packaged_self_check(
        _self_check_program(tmp_path / "bundle", _COMPLETED_PROGRAM), timeout=60
    )

    assert report["ok"] is True
    assert report["exit_code"] == 0
    stages = cast(list[dict[str, object]], report["stages"])
    assert [stage["name"] for stage in stages] == ["runtime", "dictionary"]
    assert all(isinstance(stage["duration_ms"], float) for stage in stages)

    progress = cast(dict[str, object], report["progress"])
    assert progress["started"] == ["runtime", "dictionary"]
    assert [stage["stage"] for stage in cast(list[dict], progress["completed"])] == [
        "runtime",
        "dictionary",
    ]
    # Nothing is still open, so nothing is blamed.
    assert progress["current_stage"] is None


def test_macos_ui_self_check_enters_through_the_application_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(smoke_packaged_runtime.sys, "platform", "darwin")
    executable = tmp_path / "Hanly.app" / "Contents" / "MacOS" / "hanly-desktop"
    output = tmp_path / "self-check.out"
    errors = tmp_path / "self-check.err"

    command, bundle = _self_check_command(
        executable,
        ["--self-check", "ui"],
        mode="ui",
        stdout_path=output,
        stderr_path=errors,
    )

    assert bundle == tmp_path / "Hanly.app"
    assert command == [
        "/usr/bin/open",
        "-n",
        "-W",
        "--stdout",
        str(output),
        "--stderr",
        str(errors),
        str(bundle),
        "--args",
        "--self-check",
        "ui",
    ]


def test_a_killed_run_names_the_stage_it_was_inside(tmp_path: Path) -> None:
    """The stage that never completed is the only suspect a crash leaves."""

    report = run_packaged_self_check(
        _self_check_program(tmp_path / "bundle", _KILLED_PROGRAM), timeout=60
    )

    progress = cast(dict[str, object], report["progress"])
    assert progress["current_stage"] == "ocr"
    assert progress["started"] == ["runtime", "ocr"]
    # The stage that did finish keeps its evidence; the crash is not its fault.
    assert [stage["stage"] for stage in cast(list[dict], progress["completed"])] == [
        "runtime"
    ]

    failure = next(_iter_failures(report))
    assert "current_stage: ocr" in failure
    assert "status 134" in failure


def test_a_hanging_run_names_its_stage_and_the_deadline(tmp_path: Path) -> None:
    report = run_packaged_self_check(
        _self_check_program(tmp_path / "bundle", _HANGING_PROGRAM), timeout=5
    )

    assert report["exit_timeout"] is True
    failure = next(_iter_failures(report))
    assert failure == "current_stage: main window; exit: did not exit before the deadline"


def test_a_timed_out_run_takes_the_processes_it_started_with_it(tmp_path: Path) -> None:
    """Killing only the launched process leaves its children holding the run's
    own output files, so the working directory cannot be removed and an
    abandoned bundle keeps running. The frozen desktop always has children, and
    on Windows the launcher itself is one more."""

    profile = tmp_path / "profile"
    report = run_packaged_self_check(
        _self_check_program(tmp_path / "bundle", _HANGING_PROGRAM),
        profile=profile,
        timeout=5,
    )

    assert report["exit_timeout"] is True
    # Deleting the file is the assertion: a surviving child still holds the
    # handle it inherited, and Windows refuses the unlink while it does.
    (profile / "work" / "self-check.err").unlink()


_SPAWNING_PROGRAM = """
import subprocess
import sys
import time
from pathlib import Path

grandchild = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
Path(sys.argv[-1]).write_text(str(grandchild.pid), encoding="utf-8")
time.sleep(120)
"""


@pytest.mark.skipif(sys.platform == "win32", reason="taskkill /T covers Windows")
def test_a_timed_out_run_kills_the_grandchildren_it_left_behind(tmp_path: Path) -> None:
    import os
    import time

    record = tmp_path / "grandchild.pid"
    report = run_packaged_self_check(
        _self_check_program(tmp_path / "bundle", _SPAWNING_PROGRAM),
        mode=str(record),
        timeout=5,
    )

    assert report["exit_timeout"] is True
    pid = int(record.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 5
    # Not this process's child, so only a signal probe can see it; its orphan
    # is reaped by init once killed.
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        os.kill(pid, 9)
        pytest.fail("the grandchild outlived the timed-out run")


def test_a_detach_failure_does_not_hide_the_error_that_caused_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    image = tmp_path / "hanly-desktop-macos.dmg"
    image.write_bytes(b"disk image")

    def refuse_detach(command: list[str], **_options: object) -> object:
        return SimpleNamespace(returncode=int(command[1] == "detach"), stderr=b"busy")

    with pytest.raises(FileNotFoundError, match=SMOKE_BUNDLE_NAME):
        reconstruct_from_disk_image(image, tmp_path / "out", runner=refuse_detach)
    assert "could not unmount" in capsys.readouterr().err


def test_a_crash_before_any_marker_stays_explicitly_unknown() -> None:
    """Naming the last stage that passed would invent a diagnosis."""

    failures = list(
        _iter_failures(
            {
                "ok": False,
                "stages": [],
                "progress": {"started": [], "completed": [], "current_stage": None},
                "exit_code": 0xC000001D,
                "stderr": "",
            }
        )
    )

    assert failures[0] == "current_stage: unknown; exit: ILLEGAL_INSTRUCTION (0xC000001D)"


def test_progress_is_read_before_the_stderr_tail_is_cut() -> None:
    """A long run's first markers are exactly what a bounded tail would lose."""

    markers = "\n".join(
        f'{smoke_packaged_runtime.STAGE_MARKER_PREFIX} '
        f'{{"event": "stage_started", "stage": "runtime"}}'
        for _ in range(1)
    )
    stderr = markers + "\n" + "x" * 8000

    progress = smoke_packaged_runtime.read_progress(stderr)

    assert progress["current_stage"] == "runtime"
    assert len(stderr[-4000:]) == 4000


def test_marker_lines_are_kept_out_of_the_reported_output_tail() -> None:
    """Twenty lines of progress would push the fault traceback out of view."""

    marker = f'{smoke_packaged_runtime.STAGE_MARKER_PREFIX} {{"event": "x", "stage": "y"}}'
    stderr = "\n".join([marker] * 40 + ["Fatal Python error: Aborted"])

    tail = smoke_packaged_runtime._output_tail({"stderr": stderr})

    assert tail == "Fatal Python error: Aborted"


def test_both_sides_of_the_marker_seam_agree_on_what_a_marker_looks_like() -> None:
    """The harness deliberately does not import the package it checks, so the
    two copies of these constants are held apart by nothing but this. Renaming
    one side would cost every crashed run its stage without failing a test."""

    for name in ("STAGE_MARKER_PREFIX", "STAGE_STARTED", "STAGE_COMPLETED"):
        assert getattr(smoke_packaged_runtime, name) == getattr(service_self_check, name), name


def test_the_self_check_flushes_a_start_marker_before_the_work_it_names() -> None:
    """A marker written after the action would never survive the action."""

    source = (
        ROOT / "packages" / "hanly-app" / "src" / "hanly_app" / "service" / "self_check.py"
    ).read_text(encoding="utf-8")
    body = source.split("def _stage(", 1)[1]

    assert body.index("_emit_marker(STAGE_STARTED") < body.index("value = operation()")
    assert "flush=True" in source


def test_closing_the_worker_is_a_stage_of_its_own() -> None:
    """Releasing native handles can crash; blaming the dictionary for it is a
    diagnosis that sends the next person to the wrong provider."""

    source = (
        ROOT / "packages" / "hanly-app" / "src" / "hanly_app" / "service" / "self_check.py"
    ).read_text(encoding="utf-8")
    assert '_stage(stages, "worker close", worker.close' in source


# --- the products a run checks, each independently of the others -------------


def test_reconstructing_an_archive_can_stop_before_inspecting_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reconstruction and inspection are separate steps, so a bundle that
    cannot be inspected still says whether the published ZIP unpacked."""

    archive = tmp_path / "hanly-desktop-macos.zip"
    archive.write_bytes(b"archive")
    destination = tmp_path / "out"

    def unpack(source: Path, target: Path) -> Path:
        application = Path(target) / SMOKE_BUNDLE_NAME
        application.joinpath("Contents", "MacOS").mkdir(parents=True)
        application.joinpath("Contents", "MacOS", "hanly-desktop").write_bytes(b"")
        return application

    monkeypatch.setattr(smoke_packaged_runtime, "reconstruct_application", unpack)
    status = smoke_packaged_runtime.main(
        [
            "--from-archive",
            str(archive),
            "--reconstruct-into",
            str(destination),
            "--reconstruct-only",
        ]
    )

    assert status == 0
    report = json.loads(capsys.readouterr().out)
    assert report["reconstructed"]["archive"] == archive.name
    assert "inventory" not in report


def test_a_disk_image_is_checked_without_an_application_to_smoke(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ZIP that will not reconstruct says nothing about the disk image."""

    image = tmp_path / "hanly-desktop-macos.dmg"
    image.write_bytes(b"image")
    monkeypatch.setattr(
        smoke_packaged_runtime,
        "verify_disk_image",
        lambda path: {"image": Path(path).name, "application": SMOKE_BUNDLE_NAME, "ok": True},
    )

    assert smoke_packaged_runtime.main(["--disk-image", str(image)]) == 0
    assert json.loads(capsys.readouterr().out)["disk_image"]["ok"] is True


def test_a_disk_image_without_the_application_fails_the_step(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mounting is not the check: a DMG a person opens onto nothing is broken."""

    image = tmp_path / "hanly-desktop-macos.dmg"
    image.write_bytes(b"image")
    monkeypatch.setattr(
        smoke_packaged_runtime,
        "verify_disk_image",
        lambda path: {"image": Path(path).name, "application": SMOKE_BUNDLE_NAME, "ok": False},
    )

    assert smoke_packaged_runtime.main(["--disk-image", str(image)]) == 1
    assert "does not contain" in capsys.readouterr().err


def test_an_invocation_that_names_no_product_is_refused(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert smoke_packaged_runtime.main([]) == 2
    assert "name an application directory" in capsys.readouterr().err


# --- which source a frozen bundle says it came from --------------------------


def test_a_frozen_bundle_that_reports_another_version_is_not_this_build() -> None:
    """A stale artifact passes every check it ever passed. Only its own
    reported version says which source produced it, and one tested bundle
    reported 0.1.3 beside a 0.5.0 checkout with nothing in the run saying so."""

    identity = smoke_packaged_runtime.verify_frozen_identity(
        {"versions": {"hanly": "0.1.3", "hanly-app": "0.1.3"}}, "0.5.0"
    )

    assert identity["ok"] is False
    assert len(cast(list[str], identity["problems"])) == 2
    assert "expected '0.5.0'" in cast(list[str], identity["problems"])[0]


def test_a_report_that_names_no_version_is_a_failure_not_an_absence() -> None:
    """Missing identity proves nothing about the build, which is the same
    position a mismatch leaves the release in."""

    identity = smoke_packaged_runtime.verify_frozen_identity({}, "0.5.0")

    assert identity["ok"] is False
    assert cast(dict[str, object], identity["packages"]) == {
        "hanly": None,
        "hanly-app": None,
    }


def test_both_packages_agreeing_with_the_source_is_the_whole_check() -> None:
    identity = smoke_packaged_runtime.verify_frozen_identity(
        {"versions": {"hanly": "0.5.0", "hanly-app": "0.5.0", "torch": "2.4.1"}}, "0.5.0"
    )

    assert identity["ok"] is True
    assert identity["problems"] == []


_CURRENT = "9" * 40
_STALE = "cb2d437bbb7b856b0839c0a1907b0a3d96f54c27"


def _stamped_bundle(root: Path, **fields: object) -> Path:
    """A macOS-shaped bundle whose only content is its build stamp."""

    stamp: dict[str, object] = {
        "product": "hanly-desktop",
        "platform": "macos",
        "architecture": "arm64",
        "version": "0.5.3",
        "build_id": "d0a15bba-4da8-4cee-b65a-6dc363c6c0da",
        "source_commit": _CURRENT,
        "built_at": "2026-09-22T00:00:00+00:00",
    }
    stamp.update(fields)
    assets = root / "Hanly.app" / "Contents" / "Resources" / "hanly_app" / "assets"
    assets.mkdir(parents=True)
    (assets / "hanly-build.json").write_text(json.dumps(stamp), encoding="utf-8")
    return root / "Hanly.app"


def _source_identity(bundle: Path, **overrides: str) -> dict[str, object]:
    expected = {
        "expected_commit": _CURRENT,
        "expected_version": "0.5.3",
        "expected_platform": "macos",
        "expected_architecture": "arm64",
    }
    expected.update(overrides)
    return smoke_packaged_runtime.verify_source_identity(bundle, **expected)


def test_a_same_version_bundle_from_an_older_commit_fails_the_source_check(
    tmp_path: Path,
) -> None:
    """The stale bundle that passed the version-only gate at 0.5.3."""

    identity = _source_identity(_stamped_bundle(tmp_path, source_commit=_STALE))

    assert identity["ok"] is False
    assert _STALE in cast(list[str], identity["problems"])[0]


def test_a_bundle_from_the_expected_commit_passes_the_source_check(tmp_path: Path) -> None:
    identity = _source_identity(_stamped_bundle(tmp_path))

    assert identity["ok"] is True
    assert identity["problems"] == []


@pytest.mark.parametrize(
    ("fields", "overrides"),
    [
        ({"version": "0.5.2"}, {}),
        ({"architecture": "x86_64"}, {}),
        ({"platform": "windows"}, {}),
        ({"source_commit": None}, {}),
        ({}, {"expected_commit": "cb2d437"}),
    ],
    ids=["version", "architecture", "platform", "no-commit", "abbreviated-expectation"],
)
def test_any_other_identity_mismatch_fails_the_source_check(
    tmp_path: Path, fields: dict[str, object], overrides: dict[str, str]
) -> None:
    identity = _source_identity(_stamped_bundle(tmp_path, **fields), **overrides)

    assert identity["ok"] is False


def test_a_bundle_without_a_readable_stamp_fails_the_source_check(tmp_path: Path) -> None:
    empty = tmp_path / "empty" / "Hanly.app"
    empty.mkdir(parents=True)
    garbled = _stamped_bundle(tmp_path / "garbled")
    (garbled / "Contents" / "Resources" / "hanly_app" / "assets" / "hanly-build.json").write_text(
        "{not json", encoding="utf-8"
    )

    assert _source_identity(empty)["ok"] is False
    assert _source_identity(garbled)["ok"] is False


def test_an_identity_check_that_never_runs_the_executable_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An inventory reads files. The version comes from the bundle's own
    interpreter, so a check that does not start one has nothing to compare."""

    bundle = tmp_path / "bundle"
    bundle.mkdir()

    status = smoke_packaged_runtime.main(
        [str(bundle), "--inventory-only", "--expect-version", "0.5.0"]
    )

    assert status == 2
    assert "runs the executable" in capsys.readouterr().err


def test_the_disk_image_is_the_product_a_client_reconstructs_from(
    tmp_path: Path,
) -> None:
    """A HUP client downloads the disk image, so that is what gets smoked."""

    image = tmp_path / "hanly-desktop-macos.dmg"
    image.write_bytes(b"disk image")
    tools = _NativeTool()

    def native(command: list[str], **options: object) -> object:
        tools.commands.append(command)
        if command[0].endswith("hdiutil") and command[1] == "attach":
            program = Path(command[-1]) / SMOKE_BUNDLE_NAME / "Contents" / "MacOS"
            program.mkdir(parents=True)
            (program / APPLICATION_STEM).write_bytes(b"program")
        if command[0].endswith("ditto"):
            import shutil

            shutil.copytree(command[-2], command[-1])
        return SimpleNamespace(returncode=0, stderr=b"")

    application = reconstruct_from_disk_image(image, tmp_path / "out", runner=native)

    assert application == (tmp_path / "out" / SMOKE_BUNDLE_NAME)
    assert _executable_in(application).is_file()
    assert tools.commands[-1][:2] == ["/usr/bin/hdiutil", "detach"]


def test_a_disk_image_without_the_application_leaves_nothing_mounted(
    tmp_path: Path,
) -> None:
    image = tmp_path / "hanly-desktop-macos.dmg"
    image.write_bytes(b"disk image")
    tools = _NativeTool()

    with pytest.raises(FileNotFoundError, match=SMOKE_BUNDLE_NAME):
        reconstruct_from_disk_image(image, tmp_path / "out", runner=tools)

    assert tools.commands[-1][:2] == ["/usr/bin/hdiutil", "detach"]


def test_a_reconstructed_product_is_held_to_the_manifest_its_release_publishes(
    tmp_path: Path,
) -> None:
    from tests.hanly_fixtures.update_tree import LINUX, manifest_for, write_tree

    root = write_tree(tmp_path / "build", LINUX)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(manifest_for(root, LINUX).to_json(), encoding="utf-8")

    report = compare_to_manifest(root, manifest_path)
    assert report["ok"] is True
    assert report["entries"] == len(manifest_for(root, LINUX))

    (root / "hanly-desktop").write_bytes(b"a different program entirely")
    mismatched = compare_to_manifest(root, manifest_path)
    assert mismatched["ok"] is False
    assert mismatched["differing"] == ["hanly-desktop"]


def test_a_product_that_is_not_the_published_build_fails_the_smoke(
    tmp_path: Path,
) -> None:
    from tests.hanly_fixtures.update_tree import LINUX, manifest_for, write_tree

    root = write_tree(tmp_path / "build", LINUX)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(manifest_for(root, LINUX).to_json(), encoding="utf-8")
    (root / "stowaway").write_bytes(b"not in the release")

    status = smoke_main(
        [str(root), "--inventory-only", "--against-manifest", str(manifest_path)]
    )

    assert status == 1


def test_naming_two_subjects_to_reconstruct_is_refused() -> None:
    assert smoke_main(
        ["--from-archive", "a.zip", "--from-disk-image", "b.dmg", "--reconstruct-only"]
    ) == 2
    assert smoke_main(["--against-manifest", "m.json", "--disk-image", "b.dmg"]) == 2


@pytest.mark.parametrize("tampered", [False, True])
def test_reconstruction_only_preserves_the_manifest_comparison_exit_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tampered: bool,
) -> None:
    from tests.hanly_fixtures.update_tree import LINUX, manifest_for, write_tree

    root = write_tree(tmp_path / "build", LINUX)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(manifest_for(root, LINUX).to_json(), encoding="utf-8")
    if tampered:
        (root / "hanly-desktop").write_bytes(b"different executable")
    monkeypatch.setattr(smoke_packaged_runtime, "reconstruct_application", lambda *_args: root)

    status = smoke_main([
        "--from-archive", str(tmp_path / "release.zip"), "--reconstruct-only",
        "--against-manifest", str(manifest_path),
    ])

    assert status == int(tampered)


def test_a_packaging_tool_that_names_no_file_writes_none(tmp_path: Path) -> None:
    """`hdiutil detach <mount> -force` ends in a flag; a stub that took it for
    a path once left a file called `-force` in the repository root."""

    tool = _NativeTool()

    tool(["/usr/bin/hdiutil", "detach", str(tmp_path / "mount"), "-force"])

    assert not Path("-force").exists()
    assert sorted(item.name for item in tmp_path.iterdir()) == []


def test_the_windows_reader_needs_no_dependency_and_no_hidden_import() -> None:
    """UI Automation is bound through ``ctypes``, so nothing was added to ship it.

    ``collect_submodules("hanly_app")`` already carries the module into every
    artifact, exactly as it carries the macOS adapter; a COM binding such as
    ``comtypes`` would have been a runtime dependency on all three platforms.
    """

    manifest = (ROOT / "packages" / "hanly-app" / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    source = SPEC.read_text(encoding="utf-8")

    assert "comtypes" not in manifest
    assert "pywinauto" not in manifest
    assert "uiautomation" not in manifest
    assert "text_acquisition_uia" not in source
    assert 'collect_submodules("hanly_app.acquisition")' in source
    assert 'collect_submodules("hanly_app.lookup")' in source
    assert 'collect_submodules("hanly_app.service")' in source
    assert 'collect_submodules("hanly_app")' not in source
