"""Application build awareness and in-app installation.

:class:`~hanly_app.update_service.UpdateService` replaces *resources* declared
in the runtime manifest. It has no concept of the program executing it, so a
new desktop build is invisible to it. This module supplies that missing half.

It reuses the same delivery primitives rather than adding a second updater: the
release fetcher downloads the platform archive, :func:`verify_checksum` proves
it against the release's ``SHA256SUMS``, and :func:`extract_archive` unpacks it.
Only the last step differs. A resource is swapped in place while Hanly keeps
running; an application bundle contains the executable and the interpreter
currently running from it, so it is staged in a directory this module owns and
moved into place by :mod:`~hanly_app.app_update_handoff` once this process has
exited.
"""

from __future__ import annotations

import os
import plistlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from .app_update_handoff import (
    HandoffError,
    Spawn,
    UpdateTransaction,
    start_handoff,
)
from .paths import macos_bundle_root
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

#: The macOS product, and the identity its Info.plist must carry. Both come
#: from ``packaging/hanly-desktop.spec``.
BUNDLE_NAME = "Hanly.app"
BUNDLE_IDENTIFIER = "io.github.thiagoross1.hanly"

#: The release asset that lists a SHA-256 digest for every published asset.
CHECKSUM_ASSET = "SHA256SUMS"

#: Public releases are plain ``vMAJOR.MINOR.PATCH``; anything else is not a
#: build this check knows how to compare against.
_TAG_PATTERN = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
_VERSION_PATTERN = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")

_CHECKSUM_LINE = re.compile(r"^([0-9a-f]{64})\s+\*?(\S+)$")


@dataclass(frozen=True, slots=True)
class _InstallLayout:
    """What one platform publishes, and what an installation of it looks like.

    Everything that differs between platforms is here, so the installer reads
    an installation's shape instead of testing for macOS at each step.
    """

    asset_name: str
    #: ``zip``/``gztar`` unpack through the shared extractor; ``bundle`` is the
    #: macOS application, which only ``ditto`` reproduces intact.
    archive_format: str
    #: What the archive unpacks to, and what is moved into place.
    payload_name: str
    #: The program inside that payload, relative to it.
    executable_parts: tuple[str, ...]

    @property
    def executable_path(self) -> str:
        """The program's location as the handoff script reads it."""

        return "/".join(self.executable_parts)


#: Which release archive belongs to which platform, and what it installs.
_PLATFORM_LAYOUTS: Mapping[str, _InstallLayout] = {
    "win32": _InstallLayout(
        "hanly-desktop-windows.zip", "zip", APPLICATION_STEM, (f"{APPLICATION_STEM}.exe",)
    ),
    # A DMG is what a person downloads; the updater takes the ZIP, which is
    # what carries an .app's links and permissions through a release.
    "darwin": _InstallLayout(
        "hanly-desktop-macos.zip",
        "bundle",
        BUNDLE_NAME,
        ("Contents", "MacOS", APPLICATION_STEM),
    ),
    "linux": _InstallLayout(
        "hanly-desktop-linux.tar.gz", "gztar", APPLICATION_STEM, (APPLICATION_STEM,)
    ),
}

ReleaseSource = Callable[[], Mapping[str, Any]]

#: The one archive member ``ditto --sequesterRsrc`` adds beside the bundle. It
#: carries the extended attributes ``ditto -x`` folds back into the files it
#: writes, and nothing by that name is ever created on disk.
_APPLE_DOUBLE_ROOT = "__MACOSX"


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
    """Return the installation this process runs from, or None outside one.

    On macOS that is the ``.app`` containing the program, not the directory the
    program sits in: the bundle is what is installed, signed, and replaced. A
    source checkout, a ``pip install``, and a test run all answer None - there
    is no self-contained directory whose replacement would be an update.
    """

    if not getattr(sys, "frozen", False):
        return None
    bundle = macos_bundle_root(executable)
    if bundle is not None:
        return bundle
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


def _platform_layout(platform: str) -> _InstallLayout | None:
    for prefix, layout in _PLATFORM_LAYOUTS.items():
        if platform.startswith(prefix):
            return layout
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
    if payload.get("draft") or payload.get("prerelease"):
        return ApplicationUpdate(
            current_version=current,
            latest_version=None,
            release_url=release_url,
            available=False,
            message=f"Hanly {current} is installed. The release channel has no stable build.",
        )

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

    layout = _platform_layout(platform)
    installable = (
        install_root is not None
        and layout is not None
        and _release_advertises(payload, layout.asset_name)
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

    Staging is complete and reversible on its own: everything it writes lives
    in one transaction directory, nothing about the running installation
    changes until :meth:`apply` runs, and :meth:`apply` validates nothing.
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
        layout = _platform_layout(platform)
        if layout is None:
            raise ApplicationUpdateError(f"no published application archive for {platform}")
        self._downloader = downloader
        self._release_source = release_source
        self._install_root = install_root.resolve()
        self._layout = layout
        self._asset_name = layout.asset_name
        self._platform = platform
        self._spawn = spawn
        self._extract_bundle = extract_application_bundle

    def stage(
        self,
        update: ApplicationUpdate,
        *,
        on_progress: ProgressCallback | None = None,
    ) -> UpdateTransaction:
        """Return a verified new build waiting in a directory this owns.

        The directory sits beside the installation so the swap that follows is
        a rename on one filesystem rather than a copy that can half-finish.
        """

        version = update.latest_version
        if version is None or not update.installable:
            raise ApplicationUpdateError("there is no installable application build")
        payload = self._confirm_release(version)

        directory = self._open_transaction()
        try:
            _emit(on_progress, "downloading")
            download = directory / "download"
            self._fetch(
                self._asset_name,
                version,
                download,
                on_progress,
                size=_asset_size(payload, self._asset_name),
            )

            _emit(on_progress, "verifying")
            verify_checksum(download, self._expected_digest(version, directory))

            _emit(on_progress, "installing")
            staged = self._place(self._unpack(download, directory), directory)
            _remove(download)
        except UpdateServiceError as error:
            _remove(directory)
            raise ApplicationUpdateError(f"could not stage Hanly {version}: {error}") from error
        except BaseException:
            _remove(directory)
            raise

        _emit(on_progress, "complete", 1, 1)
        return UpdateTransaction(
            directory=directory,
            install_root=self._install_root,
            staged_path=staged,
            backup_path=directory / "previous",
            ready_path=directory / "ready",
            version=version,
        )

    def apply(self, transaction: UpdateTransaction) -> None:
        """Hand the swap to a detached script and leave; the caller then quits.

        The installation holds the executable and the interpreter running this
        code, so the replacement cannot happen in-process.
        """

        try:
            start_handoff(
                transaction,
                executable=self._layout.executable_path,
                platform=self._platform,
                spawn=self._spawn,
            )
        except HandoffError as error:
            _remove(transaction.directory)
            raise ApplicationUpdateError(str(error)) from error

    def _open_transaction(self) -> Path:
        """Claim a private directory beside the installation to work in."""

        try:
            return Path(
                tempfile.mkdtemp(prefix=".hanly-update-", dir=self._install_root.parent)
            )
        except OSError as error:
            raise ApplicationUpdateError(
                f"could not prepare an update beside {self._install_root}: {error}"
            ) from error

    def _confirm_release(self, version: str) -> Mapping[str, Any]:
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
        return payload

    def _fetch(
        self,
        asset_name: str,
        version: str,
        destination: Path,
        on_progress: ProgressCallback | None,
        *,
        size: int | None = None,
    ) -> None:
        resource = RemoteResource(
            resource_id=APPLICATION_STEM,
            version=version,
            asset_name=asset_name,
            size=size,
        )
        self._downloader.download(resource, destination, on_progress)

    def _expected_digest(self, version: str, directory: Path) -> str:
        """Read this platform's digest out of the release's ``SHA256SUMS``."""

        sums = directory / CHECKSUM_ASSET
        self._fetch(CHECKSUM_ASSET, version, sums, None)
        digests = _parse_checksums(sums.read_text(encoding="utf-8"))
        _remove(sums)

        digest = digests.get(self._asset_name)
        if digest is None:
            raise ApplicationUpdateError(f"{CHECKSUM_ASSET} has no digest for {self._asset_name}")
        return digest

    def _unpack(self, download: Path, directory: Path) -> Path:
        """Unpack the verified download the way its own format requires."""

        if self._layout.archive_format == "bundle":
            return self._extract_bundle(download, directory, self._layout.payload_name)
        if self._layout.archive_format == "gztar":
            return extract_application_tar(download, directory, self._layout.payload_name)
        return extract_archive(download, directory, "hanly-update", archive_format="zip")

    def _place(self, extracted: Path, directory: Path) -> Path:
        """Move the unpacked build to where the handoff will rename it from."""

        payload = extracted / self._layout.payload_name
        if not payload.joinpath(*self._layout.executable_parts).is_file():
            raise ApplicationUpdateError("the downloaded archive is not a Hanly bundle")
        if self._layout.archive_format == "bundle":
            _require_signed_hanly_bundle(payload)

        staged = directory / self._layout.payload_name
        os.replace(payload, staged)
        _remove(extracted)
        return staged


def confirm_started(path: Path) -> None:
    """Report this build's version to the handoff that installed it.

    This file is the whole acknowledgement an update waits for: until the
    version written here is the one it installed, the handoff keeps the
    previous installation and can still put it back.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(installed_version(), encoding="utf-8")


def _emit(
    callback: ProgressCallback | None, phase: str, completed: int = 0, total: int | None = None
) -> None:
    if callback is not None:
        callback(DownloadProgress(APPLICATION_STEM, phase, completed, total))


def _asset_size(payload: Mapping[str, Any], name: str) -> int | None:
    """Return the byte count the release declares for one asset, if it does."""

    assets = payload.get("assets")
    if not isinstance(assets, (list, tuple)):
        return None
    for asset in assets:
        if isinstance(asset, Mapping) and asset.get("name") == name:
            size = asset.get("size")
            return size if isinstance(size, int) and size > 0 else None
    return None


def _parse_checksums(text: str) -> dict[str, str]:
    """Return ``name -> sha256`` from a ``sha256sum`` output file."""

    digests: dict[str, str] = {}
    for line in text.splitlines():
        match = _CHECKSUM_LINE.match(line.strip())
        if match is not None:
            digests[match.group(2)] = match.group(1)
    return digests


def _remove(path: Path) -> None:
    try:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)
    except OSError:
        pass


#: ``ditto`` reproduces an application's symlinks and permissions from a ZIP.
#: ``zipfile`` writes a symlink out as a regular file, producing a bundle that
#: no longer launches or verifies.
_DITTO = "/usr/bin/ditto"

CommandRunner = Callable[..., Any]


def extract_application_bundle(
    archive: Path,
    parent: Path,
    payload_name: str,
    *,
    runner: CommandRunner = subprocess.run,
) -> Path:
    """Unpack one macOS application ZIP into a fresh directory under ``parent``.

    The archive is already proved against ``SHA256SUMS``; what is checked here
    is shape. Every member belongs to the expected bundle, no member or link
    escapes it, and nothing written reaches outside the extraction root.
    """

    target = Path(tempfile.mkdtemp(prefix=".hanly-update.", dir=parent))
    try:
        _preflight_bundle_members(archive, payload_name)
        completed = runner(
            [_DITTO, "-x", "-k", str(archive), str(target)],
            check=False,
            capture_output=True,
        )
        if getattr(completed, "returncode", 1) != 0:
            raise ApplicationUpdateError("could not unpack the downloaded application")
        _require_extracted_roots(target, payload_name)
        _require_contained_tree(target)
    except Exception:
        _remove(target)
        raise
    return target


def extract_application_tar(archive: Path, parent: Path, payload_name: str) -> Path:
    """Unpack one Linux application tarball into a fresh directory.

    This is the application's own extractor rather than the resource one:
    a PyInstaller directory build reaches a release with hundreds of relative
    symlinks between its bundled libraries, and the resource extractor rejects
    every link outright because a resource never legitimately contains one.
    Links are admitted here only when they resolve inside the payload.
    """

    target = Path(tempfile.mkdtemp(prefix=".hanly-update.", dir=parent))
    try:
        with tarfile.open(archive, "r:gz") as bundle:
            members = bundle.getmembers()
            for member in members:
                _require_tar_member(member, payload_name)
            if not members:
                raise ApplicationUpdateError("the downloaded application archive is empty")
            # ``data_filter`` marks the interpreters that accept ``filter``; the
            # members are already proved above, so its absence is not a gap.
            if hasattr(tarfile, "data_filter"):
                bundle.extractall(target, filter="data")
            else:
                bundle.extractall(target)
        _require_extracted_roots(target, payload_name)
        _require_contained_tree(target)
    except tarfile.TarError as error:
        _remove(target)
        raise ApplicationUpdateError(
            f"the downloaded application is unreadable: {error}"
        ) from error
    except Exception:
        _remove(target)
        raise
    return target


def _require_tar_member(member: tarfile.TarInfo, payload_name: str) -> None:
    """Admit the directories, files, and internal links a build is made of."""

    _require_bundle_member(member.name, payload_name)
    if member.issym():
        _require_link_inside(member.name, member.linkname, payload_name)
    elif not (member.isfile() or member.isdir()):
        raise ApplicationUpdateError("the downloaded application has an unsupported entry")


def _preflight_bundle_members(archive: Path, payload_name: str) -> None:
    """Read the archive's own table of contents before anything is written."""

    try:
        with zipfile.ZipFile(archive) as bundle:
            members = bundle.infolist()
            for member in members:
                _require_bundle_member(member.filename, payload_name, sidecar=True)
                if _is_symlink(member):
                    _require_link_inside(
                        member.filename,
                        bundle.read(member).decode("utf-8", "replace"),
                        payload_name,
                    )
    except zipfile.BadZipFile as error:
        raise ApplicationUpdateError(
            f"the downloaded application is unreadable: {error}"
        ) from error
    if not members:
        raise ApplicationUpdateError("the downloaded application archive is empty")


def _require_bundle_member(name: str, payload_name: str, *, sidecar: bool = False) -> None:
    """Every path in the archive is relative, and inside a root it may use.

    ``sidecar`` admits the ``__MACOSX`` tree ``ditto --sequesterRsrc`` writes
    beside the bundle. Its entries carry extended attributes rather than files:
    ``ditto -x`` folds them back into what it writes and creates nothing under
    that name, which is why it is allowed to be read and never to be extracted.
    """

    if not name or name.startswith("/") or "\\" in name or ":" in name:
        raise ApplicationUpdateError("the downloaded application has an unsafe path")
    roots = (payload_name, _APPLE_DOUBLE_ROOT) if sidecar else (payload_name,)
    parts = PurePosixPath(name).parts
    if ".." in parts or parts[0] not in roots:
        raise ApplicationUpdateError("the downloaded application has an unsafe path")


def _require_link_inside(name: str, target: str, payload_name: str) -> None:
    """A link may point within its own bundle, and nowhere else.

    The link is not followed: its target is resolved textually against the
    location it will be written to, because nothing has been written yet.
    """

    if not target or target.startswith("/"):
        raise ApplicationUpdateError("the downloaded application links outside itself")

    resolved: list[str] = list(PurePosixPath(name).parent.parts)
    for part in PurePosixPath(target).parts:
        if part == "..":
            if not resolved:
                raise ApplicationUpdateError("the downloaded application links outside itself")
            resolved.pop()
        elif part not in ("", "."):
            resolved.append(part)
    if not resolved or resolved[0] != payload_name:
        raise ApplicationUpdateError("the downloaded application links outside itself")


def _is_symlink(member: zipfile.ZipInfo) -> bool:
    return (member.external_attr >> 16) & 0o170000 == 0o120000


def _require_extracted_roots(target: Path, payload_name: str) -> None:
    """Prove the payload is what was written, and that it is all that was."""

    written = sorted(item.name for item in target.iterdir())
    if written != [payload_name]:
        raise ApplicationUpdateError("the downloaded application unpacked to an unexpected shape")


def _require_contained_tree(target: Path) -> None:
    """Prove that nothing written under ``target`` leads out of it.

    Subdirectories are resolved as well as files: ``os.walk`` reports a link to
    a directory as a subdirectory and does not descend it, so checking only
    what it calls files would never look at one.
    """

    root = target.resolve()
    for directory, subdirectories, files in os.walk(target, followlinks=False):
        entries = (*subdirectories, *files)
        for name in (directory, *(os.path.join(directory, item) for item in entries)):
            resolved = Path(name).resolve()
            if resolved != root and root not in resolved.parents:
                raise ApplicationUpdateError("the unpacked application escapes its directory")


def _require_signed_hanly_bundle(bundle: Path) -> None:
    """Refuse a staged bundle that is not this application, intact.

    Identity and a structural signature are both read from the staged copy
    before anything is moved: the swap itself has no way to undo a wrong build.
    """

    if not (bundle / "Contents" / "_CodeSignature" / "CodeResources").is_file():
        raise ApplicationUpdateError("the downloaded application carries no signature")
    try:
        information = plistlib.loads((bundle / "Contents" / "Info.plist").read_bytes())
    except (OSError, ValueError, plistlib.InvalidFileException) as error:
        raise ApplicationUpdateError(
            f"the downloaded application has no readable Info.plist: {error}"
        ) from error
    if information.get("CFBundleIdentifier") != BUNDLE_IDENTIFIER:
        raise ApplicationUpdateError("the downloaded application is not Hanly")


__all__ = [
    "APPLICATION_STEM",
    "BUNDLE_IDENTIFIER",
    "BUNDLE_NAME",
    "PRODUCT_PACKAGE",
    "ApplicationInstaller",
    "ApplicationUpdate",
    "ApplicationUpdateError",
    "check_application_update",
    "confirm_started",
    "extract_application_bundle",
    "extract_application_tar",
    "installation_root",
    "installed_version",
]
