"""The application version check that UpdateService deliberately does not do."""

from __future__ import annotations

import hashlib
import io
import os
import subprocess
import tarfile
import zipfile
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any, cast

import pytest
from hanly_app import app_update
from hanly_app.app_update import (
    APPLICATION_STEM,
    BUNDLE_IDENTIFIER,
    BUNDLE_NAME,
    PRODUCT_PACKAGE,
    ApplicationInstaller,
    ApplicationUpdate,
    ApplicationUpdateError,
    check_application_update,
    confirm_started,
    extract_application_bundle,
    extract_application_tar,
    installation_root,
    installed_version,
)

RELEASE_URL = "https://github.com/ThiagoRoss1/hanly/releases/tag/v0.2.0"


def _release(**overrides: Any) -> dict[str, Any]:
    payload = {"tag_name": "v0.2.0", "html_url": RELEASE_URL}
    payload.update(overrides)
    return payload


def test_a_newer_release_tag_is_reported_as_available() -> None:
    result = check_application_update(_release, current_version="0.1.0")

    assert result.available is True
    assert result.latest_version == "0.2.0"
    assert result.release_url == RELEASE_URL
    assert "0.2.0" in result.message and "0.1.0" in result.message


@pytest.mark.parametrize("tag", ["v0.1.0", "v0.0.9"])
def test_the_same_or_an_older_release_is_not_an_update(tag: str) -> None:
    result = check_application_update(lambda: _release(tag_name=tag), current_version="0.1.0")

    assert result.available is False
    assert result.message == "Hanly 0.1.0 is up to date."


def test_each_version_component_is_compared_numerically_not_lexically() -> None:
    """``v0.10.0`` is newer than ``0.9.0``; string ordering says the opposite."""

    result = check_application_update(lambda: _release(tag_name="v0.10.0"), current_version="0.9.0")

    assert result.available is True
    assert result.latest_version == "0.10.0"


@pytest.mark.parametrize("tag", ["0.2.0", "v0.2", "v0.2.0-rc1", "latest", ""])
def test_a_tag_that_is_not_a_stable_release_is_never_an_update(tag: str) -> None:
    result = check_application_update(lambda: _release(tag_name=tag), current_version="0.1.0")

    assert result.available is False
    assert result.latest_version is None


def test_a_non_https_release_url_is_not_offered() -> None:
    result = check_application_update(
        lambda: _release(html_url="javascript:alert(1)"), current_version="0.1.0"
    )

    assert result.release_url is None


def test_a_missing_release_url_leaves_nothing_to_open() -> None:
    result = check_application_update(lambda: {"tag_name": "v0.2.0"}, current_version="0.1.0")

    assert result.available is True
    assert result.release_url is None


def test_an_unparseable_installed_version_is_an_error_not_a_false_negative() -> None:
    with pytest.raises(ApplicationUpdateError):
        check_application_update(_release, current_version="0.1.0.dev1")


def test_release_metadata_that_is_not_an_object_is_rejected() -> None:
    with pytest.raises(ApplicationUpdateError):
        check_application_update(lambda: cast(Any, "v0.2.0"), current_version="0.1.0")


def test_the_running_version_comes_from_installed_package_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The frozen build and a source install both answer from ``hanly-app``'s
    metadata, and an installation without it is an error rather than a guess."""

    assert installed_version() == metadata.version(PRODUCT_PACKAGE)

    def uninstalled(name: str) -> str:
        raise metadata.PackageNotFoundError(name)

    monkeypatch.setattr(app_update.metadata, "version", uninstalled)
    with pytest.raises(ApplicationUpdateError, match="metadata is not available"):
        installed_version()


def test_the_snapshot_is_json_compatible_primitives() -> None:
    payload = check_application_update(_release, current_version="0.1.0").to_dict()

    assert payload == {
        "current_version": "0.1.0",
        "latest_version": "0.2.0",
        "release_url": RELEASE_URL,
        "available": True,
        "installable": False,
        "message": (
            "Hanly 0.2.0 is available. You are running 0.1.0; "
            "this installation updates itself outside Hanly."
        ),
    }
    assert all(
        isinstance(value, (str, bool, type(None))) for value in payload.values()
    )


class _FakeDownloader:
    """Serve release assets from a prepared name -> bytes mapping."""

    def __init__(self, assets: dict[str, bytes]) -> None:
        self.assets = assets
        self.requested: list[str] = []
        self.sizes: list[tuple[str, int | None]] = []

    def download(self, resource: Any, destination: Path, on_progress: Any = None) -> None:
        self.requested.append(resource.asset_name)
        self.sizes.append((resource.asset_name, resource.size))
        destination.write_bytes(self.assets[resource.asset_name])


#: A PyInstaller directory build reaches a POSIX release with hundreds of
#: relative links between its bundled libraries; the tar fixture carries one.
_INTERNAL_LINK = "hanly-desktop/libhanly.so"


def _bundle_archive(archive_format: str, executable: str) -> bytes:
    """Build the archive shape ``tools/build_package.py`` publishes."""

    buffer = io.BytesIO()
    members = (
        (f"hanly-desktop/{executable}", b"new build"),
        ("hanly-desktop/_internal/libhanly.so", b"library"),
    )
    if archive_format == "zip":
        with zipfile.ZipFile(buffer, "w") as bundle:
            for name, payload in members:
                bundle.writestr(name, payload)
        return buffer.getvalue()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, payload in members:
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            info.mode = 0o755
            archive.addfile(info, io.BytesIO(payload))
        link = tarfile.TarInfo(_INTERNAL_LINK)
        link.type = tarfile.SYMTYPE
        link.linkname = "_internal/libhanly.so"
        archive.addfile(link)
    return buffer.getvalue()


@dataclass
class _Channel:
    """One release, and the installation the installer would replace."""

    payload: dict[str, Any]
    downloader: _FakeDownloader
    install_root: Path
    executable: str


def _channel(tmp_path: Path, platform: str, *, corrupt: bool = False) -> _Channel:
    asset_name, archive_format = (
        ("hanly-desktop-windows.zip", "zip")
        if platform == "win32"
        else ("hanly-desktop-linux.tar.gz", "gztar")
    )
    executable = "hanly-desktop.exe" if platform == "win32" else "hanly-desktop"
    archive = _bundle_archive(archive_format, executable)
    digest = hashlib.sha256(b"tampered" if corrupt else archive).hexdigest()
    zeros = "0" * 64
    sums = f"{digest}  {asset_name}\n{zeros}  hanly-resources.json\n"

    install_root = tmp_path / "install" / "hanly-desktop"
    install_root.mkdir(parents=True)
    (install_root / executable).write_bytes(b"old build")

    payload = {
        "tag_name": "v0.2.0",
        "html_url": RELEASE_URL,
        "assets": [{"name": asset_name, "size": len(archive)}, {"name": "SHA256SUMS"}],
    }
    downloader = _FakeDownloader({asset_name: archive, "SHA256SUMS": sums.encode()})
    return _Channel(payload, downloader, install_root, executable)


def _check(channel: _Channel, platform: str, *, frozen: bool = True) -> ApplicationUpdate:
    return check_application_update(
        lambda: channel.payload,
        current_version="0.1.0",
        install_root=channel.install_root if frozen else None,
        platform=platform,
    )


def _installer(channel: _Channel, platform: str, spawned: list[Any] | None = None):
    return ApplicationInstaller(
        channel.downloader,
        lambda: channel.payload,
        install_root=channel.install_root,
        platform=platform,
        spawn=lambda command, directory: (
            spawned.append((command, directory)) if spawned is not None else None
        ),
    )


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_a_frozen_build_with_a_published_archive_is_installable(
    tmp_path: Path, platform: str
) -> None:
    result = _check(_channel(tmp_path, platform), platform)

    assert result.available is True
    assert result.installable is True


def test_a_source_checkout_is_told_about_the_build_but_cannot_install_it(tmp_path: Path) -> None:
    """There is no bundle to replace, so only the release notes are offered."""

    result = _check(_channel(tmp_path, "linux"), "linux", frozen=False)

    assert result.available is True
    assert result.installable is False
    assert result.release_url == RELEASE_URL


def test_a_release_missing_this_platforms_archive_is_not_installable(tmp_path: Path) -> None:
    channel = _channel(tmp_path, "linux")
    channel.payload["assets"] = [{"name": "SHA256SUMS"}]

    assert _check(channel, "linux").installable is False


def _siblings(install_root: Path) -> list[str]:
    """What the updater left beside the installation it was working on."""

    return sorted(item.name for item in install_root.parent.iterdir())


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_staging_verifies_and_unpacks_a_build_without_touching_the_running_one(
    tmp_path: Path, platform: str
) -> None:
    channel = _channel(tmp_path, platform)
    installer = _installer(channel, platform)
    phases: list[str] = []

    transaction = installer.stage(
        _check(channel, platform), on_progress=lambda progress: phases.append(progress.phase)
    )

    assert transaction.version == "0.2.0"
    assert (transaction.staged_path / channel.executable).read_bytes() == b"new build"
    assert (channel.install_root / channel.executable).read_bytes() == b"old build"
    assert phases == ["downloading", "verifying", "installing", "complete"]
    assert "SHA256SUMS" in channel.downloader.requested


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_everything_staging_writes_lives_in_one_directory_it_owns(
    tmp_path: Path, platform: str
) -> None:
    """The swap, the rollback, and the cleanup all address one directory, so a
    finished or abandoned update is a single removal rather than a set of fixed
    sibling names an interrupted attempt can leave behind."""

    channel = _channel(tmp_path, platform)
    transaction = _installer(channel, platform).stage(_check(channel, platform))

    assert _siblings(channel.install_root) == sorted(
        (channel.install_root.name, transaction.directory.name)
    )
    for path in (transaction.staged_path, transaction.backup_path, transaction.ready_path):
        assert transaction.directory in path.parents
    # Nothing about the name is fixed, so a second attempt cannot collide with,
    # or delete, what an earlier one is still working in.
    assert transaction.directory.name.startswith(".hanly-update-")


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_a_failed_download_leaves_no_trace_beside_the_installation(
    tmp_path: Path, platform: str
) -> None:
    channel = _channel(tmp_path, platform, corrupt=True)

    with pytest.raises(ApplicationUpdateError, match="checksum does not match"):
        _installer(channel, platform).stage(_check(channel, platform))

    assert _siblings(channel.install_root) == [channel.install_root.name]
    assert (channel.install_root / channel.executable).read_bytes() == b"old build"


def test_a_linux_build_keeps_the_internal_links_its_layout_is_made_of(
    tmp_path: Path,
) -> None:
    """The resource extractor refuses every link, which is right for a resource
    and wrong for a directory build: the archive is mostly links between its own
    bundled libraries, and a copy without them does not run."""

    channel = _channel(tmp_path, "linux")
    transaction = _installer(channel, "linux").stage(_check(channel, "linux"))

    link = transaction.staged_path / "libhanly.so"
    assert link.is_symlink()
    assert os.readlink(link) == "_internal/libhanly.so"
    assert os.access(transaction.staged_path / channel.executable, os.X_OK)


def test_a_tar_link_that_leaves_the_payload_is_refused_before_extraction(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "escape.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        escape = tarfile.TarInfo("hanly-desktop/passwd")
        escape.type = tarfile.SYMTYPE
        escape.linkname = "../../../etc/passwd"
        bundle.addfile(escape)

    with pytest.raises(ApplicationUpdateError, match="links outside itself"):
        extract_application_tar(archive, tmp_path, APPLICATION_STEM)

    assert sorted(item.name for item in tmp_path.iterdir()) == ["escape.tar.gz"]


def test_the_declared_asset_size_bounds_the_application_download(tmp_path: Path) -> None:
    """The release says how large its archive is, and the downloader enforces
    that as a ceiling; a body that keeps arriving is stopped before the disk is."""

    channel = _channel(tmp_path, "linux")
    installer = _installer(channel, "linux")
    installer.stage(_check(channel, "linux"))

    sizes = {name: size for name, size in channel.downloader.sizes}
    assert sizes["hanly-desktop-linux.tar.gz"] == len(
        channel.downloader.assets["hanly-desktop-linux.tar.gz"]
    )


def test_a_build_that_is_not_installable_is_refused_before_any_download(tmp_path: Path) -> None:
    channel = _channel(tmp_path, "linux")

    with pytest.raises(ApplicationUpdateError, match="no installable application build"):
        _installer(channel, "linux").stage(_check(channel, "linux", frozen=False))

    assert channel.downloader.requested == []


def test_staging_is_refused_when_the_release_no_longer_offers_the_checked_build(
    tmp_path: Path,
) -> None:
    """The assets come out of one cached release payload. If that payload has
    moved on, its assets belong to a different build than the user agreed to."""

    channel = _channel(tmp_path, "linux")
    update = _check(channel, "linux")
    channel.payload["tag_name"] = "v0.3.0"

    with pytest.raises(ApplicationUpdateError, match="check for updates again"):
        _installer(channel, "linux").stage(update)

    assert channel.downloader.requested == []
    assert _siblings(channel.install_root) == [channel.install_root.name]


# --- the macOS update unit is the application bundle ------------------------

_BUNDLE_PROGRAM = f"{BUNDLE_NAME}/Contents/MacOS/{APPLICATION_STEM}"


def _macos_bundle_members(identifier: str = BUNDLE_IDENTIFIER) -> dict[str, bytes]:
    """The files an .app must have for an update to be allowed to install it."""

    import plistlib

    return {
        _BUNDLE_PROGRAM: b"new build",
        f"{BUNDLE_NAME}/Contents/Info.plist": plistlib.dumps(
            {"CFBundleIdentifier": identifier, "CFBundleName": "Hanly"}
        ),
        f"{BUNDLE_NAME}/Contents/_CodeSignature/CodeResources": b"<signature>",
        f"{BUNDLE_NAME}/Contents/Resources/hanly.icns": b"icon",
    }


def _macos_archive(members: dict[str, bytes], links: dict[str, str] | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        for name, payload in members.items():
            bundle.writestr(name, payload)
        for name, target in (links or {}).items():
            info = zipfile.ZipInfo(name)
            # The high bits are the POSIX mode; 0o120000 is what marks a symlink.
            info.external_attr = (0o120777 << 16) | 0o200000
            bundle.writestr(info, target)
    return buffer.getvalue()


class _Ditto:
    """Stands in for /usr/bin/ditto, which exists only on macOS."""

    def __init__(self, returncode: int = 0) -> None:
        self.returncode = returncode
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str], **_options: Any) -> Any:
        self.commands.append(command)
        if self.returncode == 0:
            archive, destination = Path(command[-2]), Path(command[-1])
            with zipfile.ZipFile(archive) as bundle:
                # ``ditto -x -k`` consumes the ``__MACOSX`` sidecar rather than
                # writing it, folding its attributes back into the files it
                # creates. A plain extractor writes it out as a directory, which
                # is the difference this double exists to keep.
                bundle.extractall(
                    destination,
                    members=[
                        name for name in bundle.namelist() if not name.startswith("__MACOSX/")
                    ],
                )
        return subprocess.CompletedProcess(command, self.returncode, b"", b"")


def _macos_channel(
    tmp_path: Path,
    *,
    members: dict[str, bytes] | None = None,
    links: dict[str, str] | None = None,
) -> _Channel:
    archive = _macos_archive(members or _macos_bundle_members(), links)
    asset_name = "hanly-desktop-macos.zip"
    sums = f"{hashlib.sha256(archive).hexdigest()}  {asset_name}\n"

    install_root = tmp_path / "Applications" / BUNDLE_NAME
    program = install_root / "Contents" / "MacOS" / APPLICATION_STEM
    program.parent.mkdir(parents=True)
    program.write_bytes(b"old build")

    payload = {
        "tag_name": "v0.2.0",
        "html_url": RELEASE_URL,
        "assets": [{"name": asset_name}, {"name": "SHA256SUMS"}],
    }
    downloader = _FakeDownloader({asset_name: archive, "SHA256SUMS": sums.encode()})
    return _Channel(payload, downloader, install_root, APPLICATION_STEM)


def _macos_installer(channel: _Channel, spawned: list[Any] | None = None) -> ApplicationInstaller:
    installer = _installer(channel, "darwin", spawned)
    # ditto is macOS's own tool; the shape of the call is what is asserted here.
    installer._extract_bundle = lambda archive, parent, payload: extract_application_bundle(
        archive, parent, payload, runner=_Ditto()
    )
    return installer


def test_a_macos_installation_is_the_app_not_the_directory_holding_the_program(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Replacing Contents/MacOS would leave a broken bundle behind."""

    program = tmp_path / "Applications" / BUNDLE_NAME / "Contents" / "MacOS" / APPLICATION_STEM
    program.parent.mkdir(parents=True)
    program.write_bytes(b"frozen")
    monkeypatch.setattr(app_update.sys, "frozen", True, raising=False)

    assert installation_root(program) == tmp_path / "Applications" / BUNDLE_NAME
    # A onedir installation is unchanged.
    assert installation_root(tmp_path / "dist" / "hanly-desktop" / APPLICATION_STEM) == (
        tmp_path / "dist" / "hanly-desktop"
    )


def test_the_macos_updater_takes_the_zip_and_relaunches_the_bundles_program(
    tmp_path: Path,
) -> None:
    channel = _macos_channel(tmp_path)
    spawned: list[Any] = []
    installer = _macos_installer(channel, spawned)

    transaction = installer.stage(_check(channel, "darwin"))
    installer.apply(transaction)

    assert channel.downloader.requested[0] == "hanly-desktop-macos.zip"
    # The staged copy keeps the bundle's own name: macOS reads an application
    # from its ``.app`` suffix, and a renamed one is a directory.
    assert transaction.staged_path.name == BUNDLE_NAME
    assert (transaction.staged_path / "Contents" / "MacOS" / APPLICATION_STEM).is_file()
    # The running installation is untouched until the handoff runs.
    assert (channel.install_root / "Contents" / "MacOS" / APPLICATION_STEM).read_bytes() == (
        b"old build"
    )
    script = Path(spawned[0][0][1]).read_text(encoding="utf-8")
    assert "/usr/bin/open" in script


def test_a_downloaded_application_that_is_not_hanly_is_never_staged(tmp_path: Path) -> None:
    channel = _macos_channel(
        tmp_path, members=_macos_bundle_members(identifier="com.example.other")
    )

    with pytest.raises(ApplicationUpdateError, match="not Hanly"):
        _macos_installer(channel).stage(_check(channel, "darwin"))

    assert _siblings(channel.install_root) == [channel.install_root.name]


def test_an_unsigned_application_is_refused_before_the_swap(tmp_path: Path) -> None:
    members = _macos_bundle_members()
    del members[f"{BUNDLE_NAME}/Contents/_CodeSignature/CodeResources"]
    channel = _macos_channel(tmp_path, members=members)

    with pytest.raises(ApplicationUpdateError, match="no signature"):
        _macos_installer(channel).stage(_check(channel, "darwin"))


def test_an_internal_relative_link_survives_the_preflight(tmp_path: Path) -> None:
    """Qt frameworks are full of them; rejecting those would reject every build."""

    channel = _macos_channel(
        tmp_path,
        links={f"{BUNDLE_NAME}/Contents/Frameworks/Qt.framework/Current": "../Versions/A"},
    )

    staged = _macos_installer(channel).stage(_check(channel, "darwin"))

    assert (staged.staged_path / "Contents" / "MacOS" / APPLICATION_STEM).is_file()


@pytest.mark.parametrize(
    "target",
    ["/etc/passwd", "../../../elsewhere", "../../../Other.app/Contents/MacOS/program"],
)
def test_a_link_out_of_the_bundle_is_refused_before_anything_is_written(
    tmp_path: Path, target: str
) -> None:
    channel = _macos_channel(
        tmp_path, links={f"{BUNDLE_NAME}/Contents/Resources/link": target}
    )

    with pytest.raises(ApplicationUpdateError, match="links outside itself"):
        _macos_installer(channel).stage(_check(channel, "darwin"))


def test_a_member_outside_the_expected_bundle_is_refused(tmp_path: Path) -> None:
    members = _macos_bundle_members()
    members["../escaped.txt"] = b"nope"
    channel = _macos_channel(tmp_path, members=members)

    with pytest.raises(ApplicationUpdateError, match="unsafe path"):
        _macos_installer(channel).stage(_check(channel, "darwin"))


def test_the_native_unpacker_is_invoked_as_ditto_and_cleans_up_when_it_fails(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "app.zip"
    archive.write_bytes(_macos_archive(_macos_bundle_members()))
    parent = tmp_path / "parent"
    parent.mkdir()

    working = _Ditto()
    extracted = extract_application_bundle(archive, parent, BUNDLE_NAME, runner=working)

    assert working.commands[0][:3] == ["/usr/bin/ditto", "-x", "-k"]
    assert (extracted / BUNDLE_NAME / "Contents" / "MacOS" / APPLICATION_STEM).is_file()

    with pytest.raises(ApplicationUpdateError, match="could not unpack"):
        extract_application_bundle(archive, parent, BUNDLE_NAME, runner=_Ditto(returncode=1))

    # Only the successful extraction is left behind.
    assert [item.name for item in parent.iterdir()] == [extracted.name]


def test_the_sidecar_ditto_writes_beside_the_bundle_is_read_and_never_extracted(
    tmp_path: Path,
) -> None:
    """``tools/build_package.py`` archives with ``ditto --sequesterRsrc``, which
    always emits a ``__MACOSX`` tree carrying the bundle's extended attributes.
    Refusing it refuses every release archive Hanly actually publishes; ``ditto
    -x`` folds it back into the files it writes and creates nothing by that name."""

    members = _macos_bundle_members()
    members[f"__MACOSX/{BUNDLE_NAME}/Contents/MacOS/._{APPLICATION_STEM}"] = b"\x00\x05\x16\x07"
    channel = _macos_channel(tmp_path, members=members)

    transaction = _macos_installer(channel).stage(_check(channel, "darwin"))

    assert (transaction.staged_path / "Contents" / "MacOS" / APPLICATION_STEM).is_file()
    assert sorted(item.name for item in transaction.directory.iterdir()) == [BUNDLE_NAME]


def test_an_archive_that_unpacks_to_more_than_the_bundle_is_refused(tmp_path: Path) -> None:
    """The sidecar is allowed into the table of contents, never onto disk.

    The unpacker is checked on what it produced rather than trusted, so an
    extractor that writes the sidecar out is caught even though the archive
    itself was admitted.
    """

    parent = tmp_path / "parent"
    parent.mkdir()
    archive = tmp_path / "app.zip"
    members = _macos_bundle_members()
    members[f"__MACOSX/{BUNDLE_NAME}/._Contents"] = b"attributes"
    archive.write_bytes(_macos_archive(members))

    def extract_everything(command: list[str], **_: Any) -> subprocess.CompletedProcess[bytes]:
        with zipfile.ZipFile(Path(command[-2])) as bundle:
            bundle.extractall(Path(command[-1]))
        return subprocess.CompletedProcess(command, 0, b"", b"")

    with pytest.raises(ApplicationUpdateError, match="unexpected shape"):
        extract_application_bundle(archive, parent, BUNDLE_NAME, runner=extract_everything)

    assert list(parent.iterdir()) == []


@pytest.mark.parametrize("marking", [{"draft": True}, {"prerelease": True}])
def test_a_draft_or_prerelease_is_not_offered_as_an_update(marking: dict[str, bool]) -> None:
    """Stable-only is the product policy, and neither payload is a stable build."""

    result = check_application_update(
        lambda: _release(**marking), current_version="0.1.0", platform="linux"
    )

    assert (result.available, result.installable, result.latest_version) == (False, False, None)
    assert "no stable build" in result.message


def test_a_relaunched_build_reports_the_version_that_actually_came_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """This file is the whole acknowledgement an update waits for: the handoff
    keeps the previous installation until it reads back the version it staged."""

    monkeypatch.setattr(metadata, "version", lambda name: "0.2.0")
    ready = tmp_path / "transaction" / "ready"

    confirm_started(ready)

    assert ready.read_text(encoding="utf-8") == "0.2.0"


def test_a_link_to_a_directory_that_escapes_is_caught_after_extraction(
    tmp_path: Path,
) -> None:
    """The preflight rejects such a link from the archive's own table of
    contents. This is the check behind it, on what was actually written -
    and ``os.walk`` reports a link to a directory as a subdirectory it does
    not descend, so a walk over files alone would never look at one."""

    from hanly_app.app_update import _require_contained_tree

    payload = tmp_path / BUNDLE_NAME / "Contents"
    payload.mkdir(parents=True)
    (payload / "escape").symlink_to("/etc", target_is_directory=True)

    with pytest.raises(ApplicationUpdateError, match="escapes its directory"):
        _require_contained_tree(tmp_path)
