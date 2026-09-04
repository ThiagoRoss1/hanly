"""The application version check that UpdateService deliberately does not do."""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pytest
from hanly_app.app_update import (
    APPLICATION_STEM,
    ApplicationInstaller,
    ApplicationUpdate,
    ApplicationUpdateError,
    StagedApplicationUpdate,
    check_application_update,
    installed_version,
    render_handoff_script,
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


def test_the_running_version_comes_from_installed_package_metadata() -> None:
    assert installed_version() == "0.1.0"


def test_the_snapshot_is_json_compatible_primitives() -> None:
    payload = check_application_update(_release, current_version="0.1.0").to_dict()

    assert payload == {
        "current_version": "0.1.0",
        "latest_version": "0.2.0",
        "release_url": RELEASE_URL,
        "available": True,
        "installable": False,
        "message": ApplicationUpdate(
            current_version="0.1.0",
            latest_version="0.2.0",
            release_url=RELEASE_URL,
            available=True,
            message=payload["message"],
        ).message,
    }
    assert all(
        isinstance(value, (str, bool, type(None))) for value in payload.values()
    )


class _FakeDownloader:
    """Serve release assets from a prepared name -> bytes mapping."""

    def __init__(self, assets: dict[str, bytes]) -> None:
        self.assets = assets
        self.requested: list[str] = []

    def download(self, resource: Any, destination: Path, on_progress: Any = None) -> None:
        self.requested.append(resource.asset_name)
        destination.write_bytes(self.assets[resource.asset_name])


def _bundle_archive(archive_format: str, executable: str) -> bytes:
    """Build the archive shape ``tools/build_package.py`` publishes."""

    buffer = io.BytesIO()
    members = ((f"hanly-desktop/{executable}", b"new build"), ("hanly-desktop/runtime.json", b"{}"))
    if archive_format == "zip":
        with zipfile.ZipFile(buffer, "w") as bundle:
            for name, payload in members:
                bundle.writestr(name, payload)
        return buffer.getvalue()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, payload in members:
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
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
        "assets": [{"name": asset_name}, {"name": "SHA256SUMS"}],
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


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_staging_verifies_and_unpacks_a_build_without_touching_the_running_one(
    tmp_path: Path, platform: str
) -> None:
    channel = _channel(tmp_path, platform)
    installer = _installer(channel, platform)
    phases: list[str] = []

    staged = installer.stage(
        _check(channel, platform), on_progress=lambda progress: phases.append(progress.phase)
    )

    assert staged.version == "0.2.0"
    assert (staged.staged_path / channel.executable).read_bytes() == b"new build"
    assert (channel.install_root / channel.executable).read_bytes() == b"old build"
    assert phases == ["downloading", "verifying", "installing", "complete"]
    assert "SHA256SUMS" in channel.downloader.requested


def test_an_archive_that_does_not_match_sha256sums_is_never_unpacked(tmp_path: Path) -> None:
    channel = _channel(tmp_path, "linux", corrupt=True)

    with pytest.raises(ApplicationUpdateError, match="checksum does not match"):
        _installer(channel, "linux").stage(_check(channel, "linux"))

    assert not (channel.install_root.parent / "hanly-desktop.staged").exists()
    assert (channel.install_root / channel.executable).read_bytes() == b"old build"


def test_a_build_that_is_not_installable_is_refused_before_any_download(tmp_path: Path) -> None:
    channel = _channel(tmp_path, "linux")

    with pytest.raises(ApplicationUpdateError, match="no installable application build"):
        _installer(channel, "linux").stage(_check(channel, "linux", frozen=False))

    assert channel.downloader.requested == []


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_applying_hands_the_swap_to_a_detached_script(tmp_path: Path, platform: str) -> None:
    """The bundle holds the running executable, so the swap cannot be in-process."""

    channel = _channel(tmp_path, platform)
    spawned: list[Any] = []
    installer = _installer(channel, platform, spawned)
    staged = installer.stage(_check(channel, platform))

    installer.apply(staged)

    command, directory = spawned[0]
    launcher = ["cmd.exe", "/c"] if platform == "win32" else ["/bin/sh"]
    script, pid, install, new_bundle, backup = command[len(launcher) :]

    assert command[: len(launcher)] == launcher
    assert directory == channel.install_root.parent
    assert Path(script).exists()
    assert [pid, install, new_bundle, backup] == [
        str(os.getpid()),
        str(channel.install_root),
        str(staged.staged_path),
        f"{channel.install_root}.previous",
    ]


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_the_paths_travel_as_arguments_and_never_as_generated_script_text(
    tmp_path: Path, platform: str
) -> None:
    """A batch file is parsed in the console code page, which would corrupt a
    non-ASCII install path, and generated text is where a script would pick up
    injection. Neither applies to a body that contains no paths at all."""

    channel = _channel(tmp_path, platform)
    spawned: list[Any] = []
    installer = _installer(channel, platform, spawned)

    installer.apply(installer.stage(_check(channel, platform)))

    script = spawned[0][0][2 if platform == "win32" else 1]
    body = Path(script).read_text(encoding="ascii")

    assert str(channel.install_root) not in body
    assert body.isascii()


def test_a_windows_path_cmd_cannot_quote_is_refused_rather_than_mishandled(
    tmp_path: Path,
) -> None:
    install = tmp_path / "Hanly & Co" / "hanly-desktop"
    staged = StagedApplicationUpdate("0.2.0", install.with_suffix(".staged"), install)
    installer = ApplicationInstaller(
        _FakeDownloader({}),
        dict,
        install_root=install,
        platform="win32",
        spawn=lambda command, directory: None,
    )

    with pytest.raises(ApplicationUpdateError, match="cannot quote safely"):
        installer.apply(staged)


@pytest.mark.parametrize("windows", [True, False])
def test_the_handoff_waits_then_swaps_then_relaunches_and_rolls_back_on_failure(
    windows: bool,
) -> None:
    script = render_handoff_script(windows=windows)

    wait, aside, swap_in, relaunch = (
        ("tasklist", 'move "%INSTALL%" "%BACKUP%"', 'move "%STAGED%" "%INSTALL%"', "start ")
        if windows
        else ("kill -0", 'mv "$install" "$backup"', 'mv "$staged" "$install"', "exec ")
    )
    rollback = 'move "%BACKUP%" "%INSTALL%"' if windows else 'mv "$backup" "$install"'

    # Wait for the old process, move the live bundle aside, move the new one
    # in, and only then relaunch. The rollback is after the failing swap.
    assert script.index(wait) < script.index(aside) < script.index(swap_in)
    assert script.index(swap_in) < script.index(relaunch)
    assert script.index(swap_in) < script.index(rollback)
    assert script.count(rollback) == 1


@pytest.mark.parametrize("windows", [True, False])
def test_every_handoff_wait_is_bounded_so_a_stuck_swap_cannot_spin_forever(
    windows: bool,
) -> None:
    script = render_handoff_script(windows=windows)

    assert "120" in script
    assert ("geq 120" in script) if windows else ("-ge 120" in script)
    if windows:
        # Windows keeps a directory locked briefly after the process using it
        # exits, so the first move is retried rather than failed outright.
        assert "geq 30" in script
        # ``timeout`` needs console input a detached process does not have.
        assert "timeout /t" not in script
        assert "ping -n" in script


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
    assert not (channel.install_root.parent / "hanly-desktop.staged").exists()


def _dead_pid() -> str:
    """Return a pid that has already exited, so the handoff stops waiting."""

    finished = subprocess.Popen([sys.executable, "-c", ""])
    finished.wait()
    return str(finished.pid)


def _bundle(root: Path, name: str, launched: Path) -> Path:
    """Create a stub bundle whose executable records that it was launched."""

    root.mkdir(parents=True)
    executable = root / APPLICATION_STEM
    executable.write_text(
        f'#!/bin/sh\nprintf %s {name} >> "{launched}"\n', encoding="ascii", newline="\n"
    )
    executable.chmod(0o755)
    return root


def _run_posix_handoff(tmp_path: Path, *, break_staged: bool, break_rollback: bool) -> str:
    """Run the real handoff script and report which bundle it relaunched."""

    launched = tmp_path / "launched"
    launched.write_text("", encoding="ascii")
    install = _bundle(tmp_path / "hanly-desktop", "old", launched)
    staged = _bundle(tmp_path / "hanly-desktop.staged", "new", launched)
    backup = tmp_path / "hanly-desktop.previous"
    if break_staged:
        shutil.rmtree(staged)

    environment = dict(os.environ)
    if break_rollback:
        # Fail only the rollback move, so the branch under test is the one that
        # cannot put the previous bundle back.
        shim = tmp_path / "bin"
        shim.mkdir()
        (shim / "mv").write_text(
            f'#!/bin/sh\ncase "$1" in "{backup}") exit 1 ;; esac\nexec /bin/mv "$@"\n',
            encoding="ascii",
            newline="\n",
        )
        (shim / "mv").chmod(0o755)
        environment["PATH"] = f"{shim}{os.pathsep}{environment['PATH']}"

    script = tmp_path / "hanly-update.sh"
    script.write_text(render_handoff_script(windows=False), encoding="ascii", newline="\n")
    subprocess.run(
        ["bash", str(script), _dead_pid(), str(install), str(staged), str(backup)],
        check=False,
        capture_output=True,
        timeout=60,
        env=environment,
    )
    return launched.read_text(encoding="ascii")


@pytest.mark.skipif(shutil.which("bash") is None, reason="the POSIX handoff needs a shell")
def test_a_successful_update_relaunches_the_new_bundle(tmp_path: Path) -> None:
    launched = _run_posix_handoff(tmp_path, break_staged=False, break_rollback=False)

    assert launched == "new"
    assert "printf %s new" in (tmp_path / "hanly-desktop" / APPLICATION_STEM).read_text(
        encoding="ascii"
    )


@pytest.mark.skipif(shutil.which("bash") is None, reason="the POSIX handoff needs a shell")
def test_a_failed_replacement_relaunches_the_bundle_the_rollback_restored(
    tmp_path: Path,
) -> None:
    """A failed update costs the user the update, not their running Hanly."""

    launched = _run_posix_handoff(tmp_path, break_staged=True, break_rollback=False)

    assert launched == "old"
    assert "printf %s old" in (tmp_path / "hanly-desktop" / APPLICATION_STEM).read_text(
        encoding="ascii"
    )


@pytest.mark.skipif(shutil.which("bash") is None, reason="the POSIX handoff needs a shell")
def test_a_failed_rollback_launches_nothing(tmp_path: Path) -> None:
    """Neither bundle is at the install path, so nothing there is safe to start."""

    launched = _run_posix_handoff(tmp_path, break_staged=True, break_rollback=True)

    assert launched == ""
    assert not (tmp_path / "hanly-desktop").exists()
    # The previous bundle is intact under its backup name, so a person can
    # still put it back by hand.
    assert (tmp_path / "hanly-desktop.previous" / APPLICATION_STEM).is_file()


@pytest.mark.parametrize("windows", [True, False])
def test_the_rollback_relaunch_is_gated_on_the_rollback_actually_succeeding(
    windows: bool,
) -> None:
    script = render_handoff_script(windows=windows)

    if windows:
        rollback = script.split(":rollback", 1)[1]
        # The guard is on the same line as the restoring move, so no ordering
        # mistake can let the relaunch run after a failed restore.
        assert 'move "%BACKUP%" "%INSTALL%" >nul 2>&1 || exit /b 1' in rollback
        assert rollback.index("exit /b 1") < rollback.index("start ")
        assert script.count("start ") == 2
    else:
        assert 'mv "$backup" "$install" || exit 1' in script
        rollback = script.split('mv "$backup" "$install"', 1)[1]
        assert rollback.index("exit 1") < rollback.index("exec ")
        assert script.count("exec ") == 2
