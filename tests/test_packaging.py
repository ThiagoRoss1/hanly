"""Focused validation for the local PyInstaller packaging contract."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import prepare_easyocr_models
from tools.build_package import (
    APPLICATION_STEM,
    BUNDLE_NAME,
    RESOURCE_ARCHIVE_STEM,
    PackageLayout,
    PackagingError,
    archive_application,
    build_command,
    create_disk_image,
    host_platform,
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
    HOME_VARIABLES,
    LOCAL_KRDICT_VARIABLE,
    REQUIRED_DATA_FILES,
    REQUIRED_MODEL_FILES,
    _executable_in,
    _ProfileContext,
    inspect_bundle,
    isolated_environment,
    reconstruct_application,
    verify_disk_image,
)

ROOT = Path(__file__).parents[1]
SPEC = ROOT / "packaging" / "hanly-desktop.spec"
RUNTIME_HOOK = ROOT / "packaging" / "runtime_hook.py"
RELEASE_CONSTRAINTS = ROOT / "packaging" / "release-constraints.txt"


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
    assert "collect_submodules" in source
    assert "exclude_binaries=True" in source
    for backend in ("_win32", "_darwin", "_xorg"):
        assert backend in source
    assert "pynput.mouse._darwin" in source
    assert "pynput.keyboard._darwin" not in source
    assert "resources/dev" not in source
    assert "paddle" not in source


def test_packaging_spec_keeps_pkg_resources_out_of_the_bundle() -> None:
    """A setuptools upgrade can leave an empty ``pkg_resources`` directory
    behind. PyInstaller collects it as a namespace package and its runtime hook
    then fails on ``pkg_resources.NullProvider`` before the app starts."""

    source = SPEC.read_text(encoding="utf-8")

    assert 'EXCLUDED_MODULES = ("tests", "test", "pkg_resources")' in source
    assert "excludes=list(EXCLUDED_MODULES)" in source


def test_the_macos_spec_does_not_force_the_hardened_runtime() -> None:
    """PyInstaller adds ``--options=runtime`` for any named identity, the ad hoc
    ``"-"`` included, and a hardened process then refuses to map the bundle's
    own ad hoc signed libraries. Naming no identity keeps the ad hoc signature
    without that restriction, which is why no entitlements file is needed."""

    source = SPEC.read_text(encoding="utf-8")

    assert "codesign_identity=" not in source
    assert "entitlements_file=" not in source
    assert not (ROOT / "packaging" / "entitlements.plist").exists()


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

    source = (
        ROOT / "packages" / "hanly-app" / "src" / "hanly_app" / "cli.py"
    ).read_text(encoding="utf-8")
    body = source.split("def main(", 1)[1]

    assert "multiprocessing.freeze_support()" in body
    assert body.index("multiprocessing.freeze_support()") < body.index("parse_args")


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


def _write_bundle(
    root: Path,
    *,
    with_morphology: bool,
    internal_parts: tuple[str, ...] = ("_internal",),
) -> Path:
    """Build a frozen-layout directory, optionally with the v0.1.0 defect."""

    internal = root.joinpath(*internal_parts)
    (internal / "easyocr").mkdir(parents=True)
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
        # Archiving names the file it writes; unpacking names a directory that
        # already exists, and what lands in it is the caller's business.
        if self.returncode == 0 and not target.is_dir():
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


def test_the_spec_builds_a_named_app_bundle_on_macos() -> None:
    source = SPEC.read_text(encoding="utf-8")

    assert 'BUNDLE_NAME = "Hanly.app"' in source
    assert 'BUNDLE_IDENTIFIER = "io.github.thiagoross1.hanly"' in source
    assert "BUNDLE(" in source
    assert 'name=APPLICATION_STEM' in source
    # The plist version is the packaged product's own metadata, never a literal.
    assert 'APPLICATION_VERSION = version("hanly-app")' in source
    assert '"CFBundleShortVersionString": APPLICATION_VERSION' in source


def test_the_spec_collects_the_inputs_a_frozen_build_cannot_fetch() -> None:
    """Verified TLS and OCR both fail in a bundle that has to download."""

    source = SPEC.read_text(encoding="utf-8")

    assert 'collect_data_files("certifi")' in source
    assert "assets/easyocr_models/*.pth" in source
    assert 'MODEL_FILES = ("craft_mlt_25k.pth", "korean_g2.pth")' in source
    assert "prepare_easyocr_models.py" in source


def test_the_spec_uses_targeted_easyocr_hook_and_keeps_other_collections() -> None:
    source = SPEC.read_text(encoding="utf-8")

    assert 'for package_name in ("torchvision",):' in source
    assert 'collect_all("easyocr")' not in source
    # Korean recognition decodes against both character sets, and ``easyocr``
    # configuration may legally name either, so neither may be dropped.
    assert 'hooksconfig={"easyocr": {"lang_codes": ["ko", "en"]}}' in source
    assert 'for distribution in ("hanly-app", "hanly", "easyocr"):' in source
    assert "collect_dynamic_libs" not in source
    # The uncertain surfaces stay collected; only duplication was removed.
    assert 'collect_all(package_name)' in source
    assert "kiwipiepy" in source


def test_the_spec_keeps_only_the_webengine_locales_hanly_can_present() -> None:
    """The filter has to run on the analysis result and before the bundle is
    built: the locales arrive from QtWebEngine's hook during analysis, and a
    macOS bundle is signed as it is assembled, so nothing may be removed after.
    """

    source = SPEC.read_text(encoding="utf-8")

    assert 'KEPT_WEBENGINE_LOCALES = ("en-US.pak", "ko.pak")' in source
    assert "a.datas = _without_unused_webengine_locales(a.datas)" in source
    assert source.index("a.datas = _without_unused_webengine_locales") < source.index(
        "pyz = PYZ("
    )


def test_the_spec_drops_qt_catalogues_without_touching_webengine_locales() -> None:
    """Windows and Linux keep ``qtwebengine_locales`` inside the same
    ``translations`` directory, so the rule matches the file suffix rather than
    the directory the catalogues happen to share with them."""

    source = SPEC.read_text(encoding="utf-8")

    assert 'entry for entry in collected if not entry[0].endswith(".qm")' in source
    assert "a.datas = _without_qt_translation_catalogues(a.datas)" in source
    assert source.index("a.datas = _without_qt_translation_catalogues") < source.index(
        "pyz = PYZ("
    )


def test_release_inputs_are_pinned_without_touching_package_ranges() -> None:
    pins = RELEASE_CONSTRAINTS.read_text(encoding="utf-8")

    assert "easyocr==1.7.2" in pins
    assert "pyinstaller==6.22.2" in pins
    assert "pyinstaller-hooks-contrib==2026.7" in pins


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

    from hanly_app import app_update

    from tools.release_build import FIXED_RELEASE_ASSETS

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
    # The release publishes exactly those four, plus the manifest and the sums.
    assert produced < FIXED_RELEASE_ASSETS
    assert FIXED_RELEASE_ASSETS - produced == {"hanly-resources.json", "SHA256SUMS"}

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
        bundle.joinpath("_internal", *relative.split("/")).unlink()

    assert missing.ok
    assert set(REQUIRED_DATA_FILES) <= set(missing.present)
    assert set(inspect_bundle(bundle).missing) == set(REQUIRED_DATA_FILES)


def test_the_inventory_reads_a_macos_bundles_split_collection(tmp_path: Path) -> None:
    """A .app keeps the same tree under Contents, not beside the executable."""

    application = tmp_path / SMOKE_BUNDLE_NAME
    _write_bundle(
        application,
        with_morphology=True,
        internal_parts=("Contents", "Frameworks", "_internal"),
    )
    program = application / "Contents" / "MacOS" / APPLICATION_STEM
    program.parent.mkdir(parents=True)
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
