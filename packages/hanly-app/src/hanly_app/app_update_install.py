"""Preparing a Windows update that changes only the files that differ.

The whole-bundle installer in :mod:`hanly_app.app_update` downloads one archive
and hands a directory swap to a script. This is the other strategy: read what is
installed, work out what has to change, fetch only that, and leave a transaction
the helper can apply file by file.

It runs in two halves on purpose. :meth:`DifferentialInstaller.prepare` answers
"what would this update do, and how much would it download" without fetching a
payload, because that answer is what the user is shown before they commit to a
download whose size they were not told. :meth:`DifferentialInstaller.stage` then
fetches exactly what the prepared plan named.

Nothing here writes into the installation. Staged files land in the transaction
directory and stay there until the native helper moves them, which is the only
step that cannot happen while Hanly is running.
"""

from __future__ import annotations

import hashlib
import shutil
import tempfile
import time
import zipfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from .app_inventory import (
    InstalledTree,
    InventoryCancelled,
    InventoryError,
    InventoryProgress,
    read_installation,
    read_installed_manifest,
)
from .app_manifest import (
    MANIFEST_ASSET,
    UPDATE_METADATA_ASSET,
    AssetReference,
    InstallManifest,
    ManifestError,
    UpdateMetadata,
    parse_checksums,
    require_safe_relative_path,
)
from .app_update_journal import (
    JournalError,
    TransactionPlan,
    UpdateJournal,
    operations_for,
    working_root,
)
from .app_update_plan import (
    FROM_FULL,
    PlanError,
    UpdatePlan,
    plan_update,
)
from .update_service import (
    DownloadProgress,
    ProgressCallback,
    RemoteResource,
    UpdateServiceError,
    verify_checksum,
)

#: The release asset listing a digest for every other asset.
CHECKSUM_ASSET = "SHA256SUMS"

#: What the full archive unpacks to, and therefore the prefix every one of its
#: members carries. A delta carries bare installed paths and no prefix.
ARCHIVE_ROOT = "hanly-desktop"

#: One read while extracting, which is also the hashing block size.
_READ_BYTES = 1024 * 1024

#: Metadata is small by construction. A release that answers with something
#: else is not one to read into memory and parse.
MAX_METADATA_BYTES = 8 * 1024 * 1024

#: Room left over after the payload, the staged files, and the backups, so a
#: successful update does not leave the volume with nothing on it.
DISK_MARGIN_BYTES = 256 * 1024 * 1024

CancelHook = Callable[[], bool]
ReleaseSource = Callable[[], Mapping[str, Any]]


class DifferentialUpdateError(RuntimeError):
    """Raised when a differential update cannot be prepared or staged."""


class UpdateCancelled(DifferentialUpdateError):
    """Raised when the user stopped the update before anything was changed."""

    #: Read by the coordinator, which knows this installer only by its
    #: protocol and must not recognize a cancellation by class name.
    cancelled = True


class AssetDownloader(Protocol):
    """The one delivery operation this installer borrows from the fetcher."""

    def download(
        self,
        resource: RemoteResource,
        destination: Path,
        on_progress: ProgressCallback | None = None,
    ) -> None:
        """Write one release asset to the supplied staging destination."""


@dataclass(frozen=True, slots=True)
class PreparedUpdate:
    """What an update would do, decided before its payload was fetched."""

    metadata: UpdateMetadata
    target: InstallManifest
    installed: InstalledTree
    base_manifest: InstallManifest | None
    plan: UpdatePlan

    @property
    def requires_confirmation(self) -> bool:
        """Whether the user is about to be given a download they never chose.

        Discovery costs no payload and reports no size, so nothing about a full
        archive has been authorized by the time the plan exists.
        """

        return self.plan.source == FROM_FULL

    @property
    def is_blocked(self) -> bool:
        return bool(self.plan.collisions)

    def summary(self) -> dict[str, Any]:
        return self.plan.summary()


@dataclass(frozen=True, slots=True)
class StagedUpdate:
    """A verified payload, unpacked into a transaction and ready to apply."""

    journal: UpdateJournal
    transaction: TransactionPlan
    plan: UpdatePlan


class DifferentialInstaller:
    """Prepare and stage one in-place update of a Windows installation."""

    def __init__(
        self,
        downloader: AssetDownloader,
        release_source: ReleaseSource,
        *,
        install_root: Path,
        executable: str,
        recovery_root: Path,
    ) -> None:
        self._downloader = downloader
        self._release_source = release_source
        self._install_root = Path(install_root).resolve()
        self._executable = executable
        self._recovery_root = Path(recovery_root)

    @property
    def install_root(self) -> Path:
        return self._install_root

    def prepare(
        self,
        version: str,
        *,
        on_progress: ProgressCallback | None = None,
        should_cancel: CancelHook | None = None,
    ) -> PreparedUpdate:
        """Read the release and the installation, and decide what must change."""

        metadata, target = self._metadata(version)
        _emit(on_progress, "inspecting")

        base_manifest = read_installed_manifest(self._install_root)
        installed = self._inspect(on_progress, should_cancel)

        try:
            plan = plan_update(metadata, target, installed, base_manifest=base_manifest)
        except PlanError as error:
            raise DifferentialUpdateError(str(error)) from error

        return PreparedUpdate(
            metadata=metadata,
            target=target,
            installed=installed,
            base_manifest=base_manifest,
            plan=plan,
        )

    def stage(
        self,
        prepared: PreparedUpdate,
        *,
        on_progress: ProgressCallback | None = None,
        should_cancel: CancelHook | None = None,
    ) -> StagedUpdate:
        """Fetch the payload the plan named and lay out the transaction."""

        plan = prepared.plan
        if plan.collisions:
            raise DifferentialUpdateError(
                "files this installation does not own occupy paths the update needs: "
                + ", ".join(plan.collisions[:5])
            )
        if plan.is_empty:
            raise DifferentialUpdateError("this installation already matches the new build")

        self._require_room(plan)
        journal = self._open_transaction()
        try:
            transaction = self._stage_into(journal, plan, on_progress, should_cancel)
        except BaseException:
            _remove(journal.directory)
            raise
        _emit(on_progress, "staged", 1, 1)
        return StagedUpdate(journal=journal, transaction=transaction, plan=plan)

    def _stage_into(
        self,
        journal: UpdateJournal,
        plan: UpdatePlan,
        on_progress: ProgressCallback | None,
        should_cancel: CancelHook | None,
    ) -> TransactionPlan:
        operations = operations_for(plan)
        transaction = TransactionPlan(
            transaction_id=journal.directory.name,
            install_root=self._install_root,
            executable=self._executable,
            target=plan.identity,
            base=plan.base_identity,
            operations=operations,
            recovery_root=self._recovery_root,
            created=time.time(),
        )
        journal.prepare(transaction)

        download = journal.directory / "payload.archive"
        _emit(on_progress, "downloading", 0, plan.payload.size)
        self._fetch(
            plan.payload.name, plan.payload.size, plan.identity.version, download, on_progress
        )

        _emit(on_progress, "verifying")
        _verify(download, plan.payload)

        _emit(on_progress, "unpacking", 0, len(operations))
        self._unpack(download, journal, operations, on_progress, should_cancel)
        _remove(download)
        return transaction

    def _unpack(
        self,
        archive: Path,
        journal: UpdateJournal,
        operations: tuple[Any, ...],
        on_progress: ProgressCallback | None,
        should_cancel: CancelHook | None,
    ) -> None:
        """Extract only the members this update needs, one at a time.

        A member is written to a name of this module's choosing rather than to
        the path it claims, so a hostile archive has no say in where anything
        lands. The claimed path still has to be one the plan asked for, which
        is what stops an unwanted extra member being written at all.
        """

        wanted = {item.path: item for item in operations if item.writes_a_file}
        with zipfile.ZipFile(archive) as payload:
            members = self._members(payload, set(wanted))
            missing = sorted(set(wanted) - set(members))
            if missing:
                raise DifferentialUpdateError(
                    f"the downloaded payload is missing {len(missing)} file(s) this update "
                    "needs: " + ", ".join(missing[:5])
                )
            for done, (relative, member) in enumerate(sorted(members.items()), start=1):
                if should_cancel is not None and should_cancel():
                    raise UpdateCancelled("the update was cancelled before anything changed")
                operation = wanted[relative]
                _extract_member(payload, member, journal.payload_for(operation), operation)
                _emit(on_progress, "unpacking", done, len(wanted))

    def _members(
        self, payload: zipfile.ZipFile, wanted: set[str]
    ) -> dict[str, zipfile.ZipInfo]:
        """Index the archive by installed path, refusing anything unsafe.

        The full archive nests everything under the bundle directory and the
        delta does not, so the prefix is stripped when it is there. Members the
        plan did not ask for are ignored rather than rejected: a full archive
        legitimately carries the whole build.
        """

        found: dict[str, zipfile.ZipInfo] = {}
        for member in payload.infolist():
            if member.is_dir():
                continue
            relative = _installed_path(member.filename)
            if relative is None or relative not in wanted:
                continue
            if relative in found:
                raise DifferentialUpdateError(
                    f"the downloaded payload carries {relative} twice"
                )
            if (member.external_attr >> 16) & 0o170000 == 0o120000:
                raise DifferentialUpdateError("the downloaded payload contains a link")
            found[relative] = member
        return found

    def _metadata(self, version: str) -> tuple[UpdateMetadata, InstallManifest]:
        """Fetch and prove the two small documents, and nothing else."""

        payload = self._release_source()
        tag = payload.get("tag_name") if isinstance(payload, Mapping) else None
        if tag != f"v{version}":
            raise DifferentialUpdateError(
                f"the release channel no longer offers Hanly {version}; check for updates again"
            )

        # The system temporary directory rather than the installation: these
        # are three small files read before the user has committed to anything,
        # and an installation under Program Files is not ours to write to yet.
        directory = Path(tempfile.mkdtemp(prefix="hanly-update-metadata."))
        try:
            digests = self._checksums(version, directory)
            metadata = UpdateMetadata.from_json(
                self._text(UPDATE_METADATA_ASSET, version, directory, digests)
            )
            manifest = InstallManifest.from_json(
                self._text(MANIFEST_ASSET, version, directory, digests)
            )
        except ManifestError as error:
            raise DifferentialUpdateError(f"the release metadata is not usable: {error}") from error
        except UpdateServiceError as error:
            raise DifferentialUpdateError(f"could not read the release: {error}") from error
        finally:
            _remove(directory)

        if manifest.digest() != metadata.manifest_digest:
            raise DifferentialUpdateError(
                "the release manifest is not the one its update metadata describes"
            )
        if metadata.identity.version != version:
            raise DifferentialUpdateError("the release metadata describes a different version")
        return metadata, manifest

    def _checksums(self, version: str, directory: Path) -> Mapping[str, str]:
        path = directory / CHECKSUM_ASSET
        self._fetch(CHECKSUM_ASSET, MAX_METADATA_BYTES, version, path, None)
        try:
            return parse_checksums(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError) as error:
            raise DifferentialUpdateError(f"could not read {CHECKSUM_ASSET}: {error}") from error

    def _text(self, name: str, version: str, directory: Path, digests: Mapping[str, str]) -> str:
        """Fetch one small document and prove it against the release's sums."""

        expected = digests.get(name)
        if expected is None:
            raise DifferentialUpdateError(f"{CHECKSUM_ASSET} lists no digest for {name}")
        path = directory / name
        self._fetch(name, MAX_METADATA_BYTES, version, path, None)
        try:
            verify_checksum(path, expected)
        except UpdateServiceError as error:
            raise DifferentialUpdateError(
                f"{name} is not the file the release published"
            ) from error
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise DifferentialUpdateError(f"could not read {name}: {error}") from error

    def _fetch(
        self,
        name: str,
        size: int,
        version: str,
        destination: Path,
        on_progress: ProgressCallback | None,
    ) -> None:
        resource = RemoteResource(
            resource_id=ARCHIVE_ROOT, version=version, asset_name=name, size=size
        )
        try:
            self._downloader.download(resource, destination, on_progress)
        except UpdateServiceError as error:
            raise DifferentialUpdateError(f"could not download {name}: {error}") from error

    def _inspect(
        self, on_progress: ProgressCallback | None, should_cancel: CancelHook | None
    ) -> InstalledTree:
        def relay(progress: InventoryProgress) -> None:
            _emit(on_progress, "inspecting", progress.bytes_completed, progress.bytes_total)

        try:
            return read_installation(
                self._install_root, on_progress=relay, should_cancel=should_cancel
            )
        except InventoryCancelled as error:
            raise UpdateCancelled(str(error)) from error
        except InventoryError as error:
            raise DifferentialUpdateError(f"could not read this installation: {error}") from error

    def _open_transaction(self) -> UpdateJournal:
        root = working_root(self._install_root)
        try:
            root.mkdir(parents=True, exist_ok=True)
            return UpdateJournal(Path(tempfile.mkdtemp(prefix="t", dir=root)))
        except (OSError, JournalError) as error:
            raise DifferentialUpdateError(
                f"could not prepare an update inside {self._install_root}: {error}"
            ) from error

    def _require_room(self, plan: UpdatePlan) -> None:
        """Refuse to start an update the volume cannot hold.

        The payload, the files unpacked from it, and the originals moved aside
        are all present at once, so the requirement is their sum and not the
        download alone.
        """

        needed = plan.download_bytes + plan.write_bytes + _replaced_bytes(plan) + DISK_MARGIN_BYTES
        try:
            free = shutil.disk_usage(self._install_root).free
        except OSError as error:
            raise DifferentialUpdateError(f"could not measure available disk: {error}") from error
        if free < needed:
            raise DifferentialUpdateError(
                f"this update needs about {_megabytes(needed)} free on the drive holding "
                f"Hanly, and {_megabytes(free)} is available"
            )


def _installed_path(name: str) -> str | None:
    """Turn one archive member name into the installed path it belongs at."""

    if not name or name.startswith("/") or "\\" in name or ":" in name:
        return None
    parts = PurePosixPath(name).parts
    if parts and parts[0] == ARCHIVE_ROOT:
        parts = parts[1:]
    if not parts:
        return None
    relative = "/".join(parts)
    try:
        require_safe_relative_path(relative)
    except ManifestError:
        return None
    return relative


def _extract_member(
    payload: zipfile.ZipFile,
    member: zipfile.ZipInfo,
    destination: Path,
    operation: Any,
) -> None:
    """Write one member, hashing it and stopping the moment it grows too big.

    The manifest says exactly how large the file must be, so a member that
    decompresses past it is abandoned mid-stream rather than filling the disk
    and failing a digest check afterwards.
    """

    destination.parent.mkdir(parents=True, exist_ok=True)
    hasher = hashlib.sha256()
    written = 0
    try:
        with payload.open(member) as source, destination.open("wb") as output:
            while True:
                chunk = source.read(_READ_BYTES)
                if not chunk:
                    break
                written += len(chunk)
                if written > operation.target_size:
                    raise DifferentialUpdateError(
                        f"{operation.path} is larger than the release describes"
                    )
                hasher.update(chunk)
                output.write(chunk)
    except (OSError, zipfile.BadZipFile, RuntimeError) as error:
        raise DifferentialUpdateError(f"could not unpack {member.filename}: {error}") from error

    if written != operation.target_size or hasher.hexdigest() != operation.target_sha256:
        raise DifferentialUpdateError(
            f"the downloaded {operation.path} is not the file the release describes"
        )


def _verify(path: Path, asset: AssetReference) -> None:
    try:
        actual = path.stat().st_size
    except OSError as error:
        raise DifferentialUpdateError(f"could not read the download: {error}") from error
    if actual != asset.size:
        raise DifferentialUpdateError(f"{asset.name} is not the size the release declares")
    try:
        verify_checksum(path, asset.sha256)
    except UpdateServiceError as error:
        raise DifferentialUpdateError(f"{asset.name} did not verify: {error}") from error


def _replaced_bytes(plan: UpdatePlan) -> int:
    """How much the backups of replaced and deleted files will occupy.

    The current size is not known per file, so the target size stands in for a
    replacement and a deletion is counted at its recorded size. This over- and
    under-estimates individual files and is close enough for a preflight.
    """

    return sum(item.size for item in plan.replacements) + sum(
        item.size for item in plan.deletions
    )


def _emit(
    callback: ProgressCallback | None,
    phase: str,
    completed: int = 0,
    total: int | None = None,
) -> None:
    if callback is not None:
        callback(DownloadProgress(ARCHIVE_ROOT, phase, completed, total))


def _remove(path: Path) -> None:
    try:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)
    except OSError:
        pass


def _megabytes(value: int) -> str:
    return f"{value / (1000 * 1000):.0f} MB"


__all__ = [
    "ARCHIVE_ROOT",
    "CHECKSUM_ASSET",
    "DISK_MARGIN_BYTES",
    "AssetDownloader",
    "DifferentialInstaller",
    "DifferentialUpdateError",
    "PreparedUpdate",
    "StagedUpdate",
    "UpdateCancelled",
]
