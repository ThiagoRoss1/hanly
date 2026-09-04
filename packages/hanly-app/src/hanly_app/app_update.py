"""Application build awareness and in-app installation.

:class:`~hanly_app.update_service.UpdateService` replaces *resources* declared
in the runtime manifest. It has no concept of the program executing it, so a
new desktop build is invisible to it. This module supplies that missing half.

It reuses the same delivery primitives rather than adding a second updater: the
release fetcher downloads the platform archive, :func:`verify_checksum` proves
it against the release's ``SHA256SUMS``, and :func:`extract_archive` unpacks it.
Only the last step differs. A resource is swapped in place while Hanly keeps
running; an application bundle contains the executable and the interpreter
currently running from it, so it is staged beside the installation and moved
into place by a small handoff script once this process has exited.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any, Protocol

from .update_service import (
    DownloadProgress,
    ProgressCallback,
    RemoteResource,
    UpdateServiceError,
    extract_archive,
    verify_checksum,
)

PRODUCT_PACKAGE = "hanly-app"

#: The onedir bundle directory name, and the executable inside it. Both come
#: from ``tools/build_package.py``; a release archive unpacks to exactly this.
APPLICATION_STEM = "hanly-desktop"

#: The release asset that lists a SHA-256 digest for every published asset.
CHECKSUM_ASSET = "SHA256SUMS"

#: Public releases are plain ``vMAJOR.MINOR.PATCH``; anything else is not a
#: build this check knows how to compare against.
_TAG_PATTERN = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
_VERSION_PATTERN = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")

_CHECKSUM_LINE = re.compile(r"^([0-9a-f]{64})\s+\*?(\S+)$")

#: Which release archive belongs to which platform, and how to unpack it.
_PLATFORM_ASSETS: Mapping[str, tuple[str, str]] = {
    "win32": ("hanly-desktop-windows.zip", "zip"),
    "darwin": ("hanly-desktop-macos.tar.gz", "gztar"),
    "linux": ("hanly-desktop-linux.tar.gz", "gztar"),
}

ReleaseSource = Callable[[], Mapping[str, Any]]
Spawn = Callable[[list[str], Path], None]


class ApplicationUpdateError(RuntimeError):
    """Raised when a new application build cannot be established or installed."""


class AssetDownloader(Protocol):
    """The one delivery operation an application install borrows."""

    def download(
        self,
        resource: RemoteResource,
        destination: Path,
        on_progress: ProgressCallback | None = None,
    ) -> None:
        """Write one release asset to the supplied staging destination."""


@dataclass(frozen=True)
class ApplicationUpdate:
    """Normalized answer to "is the running application out of date?"."""

    current_version: str
    latest_version: str | None
    release_url: str | None
    available: bool
    message: str
    #: Whether "Update now" can actually run. A source checkout has no bundle
    #: to replace, so it is offered the release notes and nothing else.
    installable: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON-compatible snapshot the Control Center renders."""

        return {
            "current_version": self.current_version,
            "latest_version": self.latest_version,
            "release_url": self.release_url,
            "available": self.available,
            "installable": self.installable,
            "message": self.message,
        }


@dataclass(frozen=True)
class StagedApplicationUpdate:
    """A verified new bundle waiting beside the installation it replaces."""

    version: str
    staged_path: Path
    install_root: Path


def installed_version() -> str:
    """Return the running product version from installed package metadata.

    The packaged build carries ``hanly-app``'s metadata for exactly this reason,
    so the frozen application and a source install answer identically.
    """

    try:
        return metadata.version(PRODUCT_PACKAGE)
    except metadata.PackageNotFoundError as error:
        raise ApplicationUpdateError(
            f"{PRODUCT_PACKAGE} version metadata is not available"
        ) from error


def installation_root(executable: str | Path | None = None) -> Path | None:
    """Return the onedir bundle this process runs from, or None outside one.

    A source checkout, a ``pip install``, and a test run all answer None: there
    is no self-contained directory whose replacement would be an application
    update.
    """

    if not getattr(sys, "frozen", False):
        return None
    return Path(sys.executable if executable is None else executable).resolve().parent


def _version_tuple(pattern: re.Pattern[str], value: str) -> tuple[int, int, int] | None:
    match = pattern.match(value.strip())
    if match is None:
        return None
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch)


def _release_url(payload: Mapping[str, Any]) -> str | None:
    """Return the release page only when the channel itself named a real one."""

    url = payload.get("html_url")
    return url if isinstance(url, str) and url.startswith("https://") else None


def _platform_asset(platform: str) -> tuple[str, str] | None:
    for prefix, asset in _PLATFORM_ASSETS.items():
        if platform.startswith(prefix):
            return asset
    return None


def _release_advertises(payload: Mapping[str, Any], name: str) -> bool:
    assets = payload.get("assets")
    if not isinstance(assets, (list, tuple)):
        return False
    return any(isinstance(asset, Mapping) and asset.get("name") == name for asset in assets)


def check_application_update(
    release_source: ReleaseSource,
    *,
    current_version: str | None = None,
    install_root: Path | None = None,
    platform: str = sys.platform,
) -> ApplicationUpdate:
    """Compare the running version with the latest public release tag."""

    current = current_version if current_version is not None else installed_version()
    running = _version_tuple(_VERSION_PATTERN, current)
    if running is None:
        raise ApplicationUpdateError(f"installed version {current!r} is not MAJOR.MINOR.PATCH")

    payload = release_source()
    if not isinstance(payload, Mapping):
        raise ApplicationUpdateError("release metadata must be a JSON object")

    release_url = _release_url(payload)
    tag = payload.get("tag_name")
    released = _version_tuple(_TAG_PATTERN, tag) if isinstance(tag, str) else None
    if released is None:
        return ApplicationUpdate(
            current_version=current,
            latest_version=None,
            release_url=release_url,
            available=False,
            message=f"Hanly {current} is installed. The release channel has no comparable version.",
        )

    latest = ".".join(str(part) for part in released)
    if released <= running:
        return ApplicationUpdate(
            current_version=current,
            latest_version=latest,
            release_url=release_url,
            available=False,
            message=f"Hanly {current} is up to date.",
        )

    asset = _platform_asset(platform)
    installable = (
        install_root is not None
        and asset is not None
        and _release_advertises(payload, asset[0])
        and _release_advertises(payload, CHECKSUM_ASSET)
    )
    if installable:
        message = f"Hanly {latest} is available. You are running {current}."
    else:
        message = (
            f"Hanly {latest} is available. You are running {current}; "
            "this installation updates itself outside Hanly."
        )
    return ApplicationUpdate(
        current_version=current,
        latest_version=latest,
        release_url=release_url,
        available=True,
        message=message,
        installable=installable,
    )


class ApplicationInstaller:
    """Download, verify, and stage one application build, then hand it off.

    Staging is complete and reversible on its own: nothing about the running
    installation changes until :meth:`apply` runs, and :meth:`apply` performs no
    validation of its own.
    """

    def __init__(
        self,
        downloader: AssetDownloader,
        release_source: ReleaseSource,
        *,
        install_root: Path,
        platform: str = sys.platform,
        spawn: Spawn | None = None,
    ) -> None:
        asset = _platform_asset(platform)
        if asset is None:
            raise ApplicationUpdateError(f"no published application archive for {platform}")
        self._downloader = downloader
        self._release_source = release_source
        self._install_root = install_root.resolve()
        self._asset_name, self._archive_format = asset
        self._windows = platform.startswith("win32")
        self._spawn = spawn if spawn is not None else _spawn_detached

    def stage(
        self,
        update: ApplicationUpdate,
        *,
        on_progress: ProgressCallback | None = None,
    ) -> StagedApplicationUpdate:
        """Return a verified new bundle placed beside the current installation."""

        version = update.latest_version
        if version is None or not update.installable:
            raise ApplicationUpdateError("there is no installable application build")
        self._confirm_release(version)

        parent = self._install_root.parent
        download = _reserve(parent, ".download")
        extracted: Path | None = None
        try:
            _emit(on_progress, "downloading")
            self._fetch(self._asset_name, version, download, on_progress)

            _emit(on_progress, "verifying")
            verify_checksum(download, self._expected_digest(version, parent))

            _emit(on_progress, "installing")
            extracted = extract_archive(
                download, parent, "hanly-update", archive_format=self._archive_format
            )
            staged = self._place(extracted, parent)
        except UpdateServiceError as error:
            raise ApplicationUpdateError(f"could not stage Hanly {version}: {error}") from error
        except OSError as error:
            raise ApplicationUpdateError(f"could not stage Hanly {version}: {error}") from error
        finally:
            _remove(download)
            if extracted is not None:
                _remove(extracted)

        _emit(on_progress, "complete", 1, 1)
        return StagedApplicationUpdate(version, staged, self._install_root)

    def apply(self, staged: StagedApplicationUpdate) -> None:
        """Hand the swap to a detached script and leave; the caller then quits.

        The bundle holds the executable and the interpreter running this code,
        so the replacement cannot happen in-process. The script waits for this
        process to exit, moves the staged bundle into place, restores the old
        one if that fails, and relaunches Hanly.
        """

        script = _write_handoff_script(staged, windows=self._windows)
        launcher = ["cmd.exe", "/c"] if self._windows else ["/bin/sh"]
        try:
            self._spawn([*launcher, str(script), *handoff_arguments(staged)], script.parent)
        except OSError as error:
            raise ApplicationUpdateError(f"could not start the update handoff: {error}") from error

    def _confirm_release(self, version: str) -> None:
        """Refuse to stage assets from a release other than the checked one.

        The fetcher serves every asset out of one cached release payload. If
        that payload has moved on since the check, its assets belong to a
        different build than the one the user agreed to install.
        """

        payload = self._release_source()
        tag = payload.get("tag_name") if isinstance(payload, Mapping) else None
        if tag != f"v{version}":
            raise ApplicationUpdateError(
                f"the release channel no longer offers Hanly {version}; check for updates again"
            )

    def _fetch(
        self,
        asset_name: str,
        version: str,
        destination: Path,
        on_progress: ProgressCallback | None,
    ) -> None:
        resource = RemoteResource(
            resource_id=APPLICATION_STEM, version=version, asset_name=asset_name
        )
        self._downloader.download(resource, destination, on_progress)

    def _expected_digest(self, version: str, parent: Path) -> str:
        """Read this platform's digest out of the release's ``SHA256SUMS``."""

        sums = _reserve(parent, ".sums")
        try:
            self._fetch(CHECKSUM_ASSET, version, sums, None)
            digests = _parse_checksums(sums.read_text(encoding="utf-8"))
        finally:
            _remove(sums)

        digest = digests.get(self._asset_name)
        if digest is None:
            raise ApplicationUpdateError(f"{CHECKSUM_ASSET} has no digest for {self._asset_name}")
        return digest

    def _place(self, extracted: Path, parent: Path) -> Path:
        """Move the unpacked bundle to the fixed name the handoff script reads."""

        bundle = extracted / APPLICATION_STEM
        if not (bundle / self._executable_name()).is_file():
            raise ApplicationUpdateError("the downloaded archive is not a Hanly bundle")

        staged = parent / f"{self._install_root.name}.staged"
        _remove(staged)
        os.replace(bundle, staged)
        return staged

    def _executable_name(self) -> str:
        return f"{APPLICATION_STEM}.exe" if self._windows else APPLICATION_STEM


def _emit(
    callback: ProgressCallback | None, phase: str, completed: int = 0, total: int | None = None
) -> None:
    if callback is not None:
        callback(DownloadProgress(APPLICATION_STEM, phase, completed, total))


def _parse_checksums(text: str) -> dict[str, str]:
    """Return ``name -> sha256`` from a ``sha256sum`` output file."""

    digests: dict[str, str] = {}
    for line in text.splitlines():
        match = _CHECKSUM_LINE.match(line.strip())
        if match is not None:
            digests[match.group(2)] = match.group(1)
    return digests


def _reserve(parent: Path, suffix: str) -> Path:
    path = parent / f".hanly-update{suffix}"
    _remove(path)
    return path


def _remove(path: Path) -> None:
    try:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)
    except OSError:
        pass


#: How long the handoff waits for this process to exit, and how long it then
#: retries a Windows directory move that a lingering lock is still refusing.
#: Both are bounded so a stuck handoff exits instead of spinning forever.
_HANDOFF_WAIT_SECONDS = 120
_HANDOFF_SWAP_ATTEMPTS = 30

#: Characters ``cmd.exe`` acts on even inside a quoted argument. An install
#: path containing one cannot be handed to a batch script safely, so the update
#: is refused rather than run against a path the script would misread.
_CMD_UNSAFE = set('&|<>^"%!')


def backup_path(install_root: Path) -> Path:
    """Where the replaced bundle is kept until the new one is in place."""

    return install_root.with_name(install_root.name + ".previous")


def handoff_arguments(staged: StagedApplicationUpdate) -> list[str]:
    """Return the values the handoff script reads, in the order it reads them.

    The paths are arguments rather than text baked into the script: a batch file
    is parsed in the console code page, which would corrupt a non-ASCII install
    path, and generated text is where a script picks up injection. Arguments
    cross the process boundary as they are.
    """

    return [
        str(os.getpid()),
        str(staged.install_root),
        str(staged.staged_path),
        str(backup_path(staged.install_root)),
    ]


def _write_handoff_script(staged: StagedApplicationUpdate, *, windows: bool) -> Path:
    if windows:
        offending = _CMD_UNSAFE.intersection(str(staged.install_root))
        if offending:
            raise ApplicationUpdateError(
                "the installation path contains characters the update handoff "
                f"cannot quote safely: {''.join(sorted(offending))}"
            )
    directory = staged.install_root.parent
    script = directory / ("hanly-update.cmd" if windows else "hanly-update.sh")
    # Line endings are pinned rather than left to the platform: ``cmd.exe``
    # mis-parses a batch file with bare newlines.
    script.write_text(
        render_handoff_script(windows=windows),
        encoding="ascii",
        newline="\r\n" if windows else "\n",
    )
    if not windows:
        script.chmod(0o700)
    return script


def render_handoff_script(*, windows: bool) -> str:
    """Render the swap script, kept separate from spawning so it can be read.

    The body is fixed ASCII and takes its paths from :func:`handoff_arguments`.
    It waits for the old process, moves the live bundle aside, moves the staged
    bundle in, and relaunches. If the second move fails the previous bundle goes
    straight back and *that* bundle is relaunched, so a failed update costs the
    user nothing but the update. The new build is never launched unless it is
    actually in place, and a rollback that itself fails launches nothing at all
    rather than starting whatever happens to be at the install path.
    """

    if windows:
        return _WINDOWS_HANDOFF.format(
            wait=_HANDOFF_WAIT_SECONDS,
            attempts=_HANDOFF_SWAP_ATTEMPTS,
            executable=APPLICATION_STEM,
        )
    return _POSIX_HANDOFF.format(wait=_HANDOFF_WAIT_SECONDS, executable=APPLICATION_STEM)


_POSIX_HANDOFF = """#!/bin/sh
set -u
pid="$1"
install="$2"
staged="$3"
backup="$4"

waited=0
while kill -0 "$pid" 2>/dev/null; do
  if [ "$waited" -ge {wait} ]; then
    exit 1
  fi
  waited=$((waited + 1))
  sleep 1
done

rm -rf "$backup"
mv "$install" "$backup" || exit 1
if ! mv "$staged" "$install"; then
  mv "$backup" "$install" || exit 1
  rm -rf "$staged"
  exec "$install/{executable}"
fi
rm -rf "$backup"
exec "$install/{executable}"
"""

# ``ping`` is the sleep: ``timeout`` fails outright when a detached process has
# no console input. The move is retried because Windows keeps a directory
# locked for a moment after the process holding its executable exits.
_WINDOWS_HANDOFF = """@echo off
setlocal
set "PID=%~1"
set "INSTALL=%~2"
set "STAGED=%~3"
set "BACKUP=%~4"

set /a WAITED=0
:wait
tasklist /nh /fi "PID eq %PID%" 2>nul | find "%PID%" >nul || goto gone
if %WAITED% geq {wait} exit /b 1
set /a WAITED+=1
ping -n 2 127.0.0.1 >nul
goto wait

:gone
if exist "%BACKUP%" rmdir /s /q "%BACKUP%"
set /a TRIES=0
:swap
move "%INSTALL%" "%BACKUP%" >nul 2>&1 && goto replace
if %TRIES% geq {attempts} exit /b 1
set /a TRIES+=1
ping -n 2 127.0.0.1 >nul
goto swap

:replace
move "%STAGED%" "%INSTALL%" >nul 2>&1 || goto rollback
rmdir /s /q "%BACKUP%" 2>nul
start "" "%INSTALL%\\{executable}.exe"
exit /b 0

:rollback
move "%BACKUP%" "%INSTALL%" >nul 2>&1 || exit /b 1
rmdir /s /q "%STAGED%" 2>nul
start "" "%INSTALL%\\{executable}.exe"
exit /b 1
"""


def _spawn_detached(command: list[str], directory: Path) -> None:
    """Start the handoff so it outlives the process it is waiting for."""

    if sys.platform.startswith("win32"):
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
        subprocess.Popen(command, cwd=directory, close_fds=True, creationflags=flags)
        return
    subprocess.Popen(command, cwd=directory, close_fds=True, start_new_session=True)


__all__ = [
    "APPLICATION_STEM",
    "CHECKSUM_ASSET",
    "PRODUCT_PACKAGE",
    "ApplicationInstaller",
    "ApplicationUpdate",
    "ApplicationUpdateError",
    "StagedApplicationUpdate",
    "backup_path",
    "check_application_update",
    "handoff_arguments",
    "installation_root",
    "installed_version",
    "render_handoff_script",
]
