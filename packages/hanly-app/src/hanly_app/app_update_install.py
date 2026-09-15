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

Schema 2 keeps that two-step shape and makes it the shared one. Preparing is
identical on every platform - pin the release, read the one metadata package,
read the installation, establish what it is, plan - and only what a platform
then does with the plan differs.

Nothing here writes into the installation. Staged files land in the transaction
directory and stay there until the native helper moves them, which is the only
step that cannot happen while Hanly is running.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import time
import zipfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from .app_build_identity import BuildStamp, ReceiptStore, receipt_for
from .app_hup import (
    FORMAT_DMG,
    HupError,
    PlatformEntry,
    ReleaseAsset,
    UpdatePackage,
    package_asset_name,
    package_digest,
    read_package,
)
from .app_inventory import (
    InstalledTree,
    InventoryCancelled,
    InventoryError,
    InventoryProgress,
    TreeInventory,
    compare_tree,
    read_installation,
    read_installed_manifest,
    read_tree,
)
from .app_manifest import (
    MANIFEST_ASSET,
    MAX_MANIFEST_ENTRIES,
    PLATFORM_MACOS,
    UPDATE_METADATA_ASSET,
    AssetReference,
    InstallManifest,
    ManifestError,
    TreeManifest,
    UpdateMetadata,
    parse_checksums,
    require_safe_relative_path,
)
from .app_update_journal import (
    RECORD_POSIX_TREE,
    RECORD_WINDOWS_FILES,
    JournalError,
    JournalOperation,
    TransactionPlan,
    UpdateChallenge,
    UpdateJournal,
    new_challenge,
    operations_for,
    tree_operations_for,
    working_root,
    write_challenge,
)
from .app_update_macos import (
    BundleError,
    acquire_disk_image,
    require_bundle_identity,
    require_valid_signature,
)
from .app_update_plan import (
    FROM_DELTA,
    FROM_FULL,
    OWNERSHIP_BOOTSTRAP,
    OWNERSHIP_RECEIPT,
    OwnershipUnknown,
    PlanError,
    TreePlan,
    UpdatePlan,
    plan_tree_update,
    plan_update,
)
from .app_update_tree import (
    CANDIDATE_NAME,
    PREVIOUS_NAME,
    REJECTED_NAME,
    BuiltCandidate,
    CandidateCancelled,
    CandidateError,
    assemble_candidate,
    copy_preserved,
    extract_full_product,
    verify_candidate,
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

#: How the metadata of a release other than the pinned one is read. Used once,
#: to find out what an installation carrying no receipt actually is.
TaggedReleaseSource = Callable[[str], Mapping[str, Any]]


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


# --------------------------------------------------------------------------
# Schema 2: one preparation for all three platforms
#
# Preparing an update is the same work everywhere: pin the release so nothing
# can move under it, read the one metadata package, find this machine's entry,
# read the installation, establish what it is, and plan. Only what happens to
# the plan afterwards differs, which is what a staging strategy is.
# --------------------------------------------------------------------------

#: The largest checksum listing this build reads. A release lists a dozen
#: assets; anything past this is not a document to parse.
MAX_CHECKSUM_BYTES = 1024 * 1024

#: The most assets one release may declare. GitHub allows far more; a Hanly
#: release publishes about a dozen.
MAX_RELEASE_ASSETS = 256


class UnsupportedPlatform(DifferentialUpdateError):
    """Raised when this release publishes nothing for this machine.

    A near miss is still a miss: installing another architecture's build would
    produce an installation that cannot start.
    """


class UpdateBlocked(DifferentialUpdateError):
    """Raised when an update could run but must not, and a person must act."""


@dataclass(frozen=True, slots=True)
class ReleaseAssetRecord:
    """One asset as the release API described it at the moment of pinning."""

    name: str
    url: str
    asset_id: int | None = None
    size: int | None = None
    digest: str | None = None

    def matches(self, expected: ReleaseAsset) -> bool:
        """Whether the release still describes the asset the index named."""

        if self.size is not None and self.size != expected.size:
            return False
        return self.digest is None or self.digest == expected.sha256


@dataclass(frozen=True, slots=True)
class ReleaseSnapshot:
    """One release, frozen at the moment an update was planned from it.

    Every later download resolves through this rather than through the shared
    release cache: a resource refresh reads the channel again, and an approved
    plan must not quietly start pointing at a different build's assets.
    """

    tag: str
    version: str
    assets: Mapping[str, ReleaseAssetRecord]
    release_id: int | None = None
    release_url: str | None = None

    def get(self, name: str) -> ReleaseAssetRecord | None:
        return self.assets.get(name)

    def require(self, name: str) -> ReleaseAssetRecord:
        asset = self.assets.get(name)
        if asset is None:
            raise DifferentialUpdateError(f"the release for Hanly {self.version} has no {name}")
        return asset


def snapshot_release(payload: Any, version: str) -> ReleaseSnapshot:
    """Pin one release payload into the immutable form an update is bound to."""

    if not isinstance(payload, Mapping):
        raise DifferentialUpdateError("release metadata must be a JSON object")
    tag = payload.get("tag_name")
    if tag != f"v{version}":
        raise DifferentialUpdateError(
            f"the release channel no longer offers Hanly {version}; check for updates again"
        )

    raw = payload.get("assets")
    if not isinstance(raw, (list, tuple)):
        raise DifferentialUpdateError("the release lists no assets")
    if len(raw) > MAX_RELEASE_ASSETS:
        raise DifferentialUpdateError("the release lists more assets than this build reads")

    assets: dict[str, ReleaseAssetRecord] = {}
    for item in raw:
        record = _asset_record(item)
        if record is not None:
            assets[record.name] = record

    return ReleaseSnapshot(
        tag=str(tag),
        version=version,
        assets=assets,
        release_id=_optional_integer(payload.get("id")),
        release_url=payload.get("html_url") if isinstance(payload.get("html_url"), str) else None,
    )


@dataclass(frozen=True, slots=True)
class PreparedTreeUpdate:
    """What an update would do, decided before its payload was fetched."""

    snapshot: ReleaseSnapshot
    entry: PlatformEntry
    target: TreeManifest
    inventory: TreeInventory
    base: TreeManifest
    plan: TreePlan

    @property
    def version(self) -> str:
        return self.plan.version

    @property
    def requires_confirmation(self) -> bool:
        """Whether the user is about to be given a download they never chose.

        Discovery costs no payload and reports no size, so nothing about a full
        product has been authorized by the time the plan exists.
        """

        return self.plan.source == FROM_FULL

    @property
    def is_blocked(self) -> bool:
        return self.plan.is_blocked

    def payload_asset(self) -> ReleaseAsset:
        return (
            self.entry.delta.payload
            if self.plan.source == FROM_DELTA and self.entry.delta is not None
            else self.entry.full
        )

    def summary(self) -> dict[str, Any]:
        return self.plan.summary()


class StagingStrategy(Protocol):
    """What one platform does with a plan the shared core has decided."""

    @property
    def label(self) -> str:
        """How this strategy names itself in a progress snapshot."""

    def precheck(self, prepared: PreparedTreeUpdate) -> None:
        """Refuse a plan this platform cannot apply, before anything is fetched."""

    def required_bytes(self, plan: TreePlan) -> int:
        """Free space this strategy needs on the installation's volume."""

    def assemble(
        self,
        prepared: PreparedTreeUpdate,
        payload: Path,
        *,
        on_progress: ProgressCallback | None = None,
        should_cancel: CancelHook | None = None,
    ) -> Any:
        """Turn a verified payload into something ready to apply, and return it."""


@dataclass(frozen=True, slots=True)
class StagedTreeUpdate:
    """A verified payload, laid out by one strategy and ready to apply."""

    plan: TreePlan
    transaction: Any


class TreeUpdateInstaller:
    """Prepare and stage one update of one installation, on any platform."""

    def __init__(
        self,
        downloader: AssetDownloader,
        release_source: ReleaseSource,
        *,
        stamp: BuildStamp,
        install_root: Path,
        store: ReceiptStore,
        strategy: StagingStrategy,
        tagged_release_source: TaggedReleaseSource | None = None,
    ) -> None:
        self._downloader = downloader
        self._release_source = release_source
        self._tagged_release_source = tagged_release_source
        self._stamp = stamp
        self._install_root = Path(install_root).resolve()
        self._store = store
        self._strategy = strategy

    @property
    def install_root(self) -> Path:
        return self._install_root

    def prepare(
        self,
        version: str,
        *,
        on_progress: ProgressCallback | None = None,
        should_cancel: CancelHook | None = None,
    ) -> PreparedTreeUpdate:
        """Decide the whole update without fetching a byte of its payload."""

        _emit(on_progress, "inspecting")
        snapshot = snapshot_release(self._release_source(), version)
        package = self._read_package(snapshot, version)
        entry = self._entry_for(package, version)
        self._require_assets(snapshot, entry)

        target = package.manifest_for(entry)
        inventory = self._read_installation(on_progress, should_cancel)
        base, ownership = self._established_base(inventory)

        try:
            plan = plan_tree_update(
                target,
                inventory,
                base,
                ownership=ownership,
                full=entry.full,
                delta=entry.delta,
            )
        except PlanError as error:
            raise DifferentialUpdateError(str(error)) from error

        prepared = PreparedTreeUpdate(
            snapshot=snapshot,
            entry=entry,
            target=target,
            inventory=inventory,
            base=base,
            plan=plan,
        )
        self._strategy.precheck(prepared)
        return prepared

    def stage(
        self,
        prepared: PreparedTreeUpdate,
        *,
        on_progress: ProgressCallback | None = None,
        should_cancel: CancelHook | None = None,
    ) -> StagedTreeUpdate:
        """Fetch the payload the plan named and lay out the transaction."""

        plan = prepared.plan
        if plan.collisions:
            raise UpdateBlocked(
                "files this installation does not own occupy paths the update needs: "
                + ", ".join(plan.collisions[:5])
            )
        if plan.is_empty:
            raise DifferentialUpdateError("this installation already matches the new build")

        self._strategy.precheck(prepared)
        self._require_room(plan)

        scratch = Path(tempfile.mkdtemp(prefix="hanly-update-payload."))
        try:
            payload = self._fetch_payload(prepared, scratch, on_progress, should_cancel)
            transaction = self._strategy.assemble(
                prepared, payload, on_progress=on_progress, should_cancel=should_cancel
            )
        finally:
            _remove(scratch)

        _emit(on_progress, "staged", 1, 1)
        return StagedTreeUpdate(plan=plan, transaction=transaction)

    def _fetch_payload(
        self,
        prepared: PreparedTreeUpdate,
        scratch: Path,
        on_progress: ProgressCallback | None,
        should_cancel: CancelHook | None,
    ) -> Path:
        asset = prepared.payload_asset()
        destination = scratch / asset.name
        _emit(on_progress, "downloading", 0, asset.size)
        self._download(prepared.snapshot, asset, destination, on_progress)
        _require_cancel(should_cancel)

        _emit(on_progress, "verifying")
        _verify_asset(destination, asset)
        return destination

    def _read_package(self, snapshot: ReleaseSnapshot, version: str) -> UpdatePackage:
        """Fetch and prove the one metadata package, and nothing else."""

        name = package_asset_name(version)
        directory = Path(tempfile.mkdtemp(prefix="hanly-update-metadata."))
        try:
            digests = self._checksums(snapshot, directory)
            expected = digests.get(name)
            if expected is None:
                raise DifferentialUpdateError(
                    f"{CHECKSUM_ASSET} lists no digest for {name}; this release predates "
                    "cross-platform updates"
                )
            path = directory / name
            self._download(snapshot, _metadata_asset(name, expected), path, None)
            if package_digest(path) != expected:
                raise DifferentialUpdateError(f"{name} is not the file the release published")
            return read_package(path)
        except HupError as error:
            raise DifferentialUpdateError(f"the release metadata is not usable: {error}") from error
        finally:
            _remove(directory)

    def _checksums(self, snapshot: ReleaseSnapshot, directory: Path) -> Mapping[str, str]:
        path = directory / CHECKSUM_ASSET
        self._download(snapshot, _metadata_asset(CHECKSUM_ASSET), path, None)
        try:
            if path.stat().st_size > MAX_CHECKSUM_BYTES:
                raise DifferentialUpdateError(f"{CHECKSUM_ASSET} is larger than this build reads")
            return parse_checksums(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError) as error:
            raise DifferentialUpdateError(f"could not read {CHECKSUM_ASSET}: {error}") from error

    def _entry_for(self, package: UpdatePackage, version: str) -> PlatformEntry:
        entry = package.index.entry_for(self._stamp.platform, self._stamp.architecture)
        if entry is None:
            raise UnsupportedPlatform(
                f"Hanly {version} publishes no build for {self._stamp.platform} "
                f"{self._stamp.architecture}. Download it from the release page instead."
            )
        return entry

    def _require_assets(self, snapshot: ReleaseSnapshot, entry: PlatformEntry) -> None:
        """Every asset this entry names is in the pinned release, unchanged."""

        wanted = [entry.full]
        if entry.delta is not None:
            wanted.append(entry.delta.payload)
        for asset in wanted:
            record = snapshot.get(asset.name)
            if record is None:
                raise DifferentialUpdateError(
                    f"the release for Hanly {snapshot.version} does not publish {asset.name}"
                )
            if not record.matches(asset):
                raise DifferentialUpdateError(
                    f"{asset.name} is not the file this release's update package describes"
                )

    def _read_installation(
        self, on_progress: ProgressCallback | None, should_cancel: CancelHook | None
    ) -> TreeInventory:
        def relay(progress: InventoryProgress) -> None:
            _emit(on_progress, "inspecting", progress.bytes_completed, progress.bytes_total)

        try:
            return read_tree(
                self._install_root,
                self._stamp.platform,
                on_progress=relay,
                should_cancel=should_cancel,
            )
        except InventoryCancelled as error:
            raise UpdateCancelled(str(error)) from error
        except InventoryError as error:
            raise DifferentialUpdateError(f"could not read this installation: {error}") from error

    def _established_base(self, inventory: TreeInventory) -> tuple[TreeManifest, str]:
        """Find out what this installation actually is, or refuse to guess.

        A receipt this updater wrote is the ordinary answer. A fresh manual
        installation has none, so the build it claims to be is fetched and the
        tree is checked against it - every managed entry, by hash. Anything
        less is not ownership, and an update without ownership would be
        guessing about what it may delete.
        """

        receipt = self._store.read_receipt()
        if receipt is not None and receipt.describes(self._stamp):
            stored = self._store.read_manifest(receipt.manifest_sha256)
            if stored is not None:
                return stored, OWNERSHIP_RECEIPT
        return self._bootstrap(inventory), OWNERSHIP_BOOTSTRAP

    def _bootstrap(self, inventory: TreeInventory) -> TreeManifest:
        """Adopt an installation only when it is exactly a published build."""

        published = self._installed_tag_manifest()
        if published is None:
            raise OwnershipUnknown(
                f"Hanly cannot confirm that this installation is the published "
                f"{self._stamp.version} build, so it will not update it automatically. "
                "Install the new version by hand, keeping this folder until it works."
            )
        comparison = compare_tree(inventory, published)
        if comparison.missing or comparison.differing:
            raise OwnershipUnknown(
                f"this installation differs from the published Hanly {self._stamp.version} "
                f"in {len(comparison.missing) + len(comparison.differing)} file(s), so an "
                "update cannot tell its files from yours. Install by hand instead."
            )
        self._store.store_manifest(published)
        return published

    def _installed_tag_manifest(self) -> TreeManifest | None:
        """Read the metadata of the tag this installation already runs.

        A different release from the one being installed, which is why it is
        fetched separately and never allowed to replace the pinned snapshot.
        """

        if self._tagged_release_source is None:
            return None
        try:
            snapshot = snapshot_release(
                self._tagged_release_source(self._stamp.release_tag), self._stamp.version
            )
            package = self._read_package(snapshot, self._stamp.version)
        except (DifferentialUpdateError, UpdateServiceError):
            return None
        entry = package.index.entry_for(self._stamp.platform, self._stamp.architecture)
        if entry is None or entry.identity.to_dict() != self._stamp.identity.to_dict():
            return None
        return package.manifest_for(entry)

    def _download(
        self,
        snapshot: ReleaseSnapshot,
        asset: ReleaseAsset,
        destination: Path,
        on_progress: ProgressCallback | None,
    ) -> None:
        """Fetch one asset through the pinned snapshot, never the live channel."""

        record = snapshot.require(asset.name)
        resource = RemoteResource(
            resource_id=ARCHIVE_ROOT,
            version=snapshot.version,
            url=record.url,
            asset_name=asset.name,
            size=asset.size,
        )
        try:
            self._downloader.download(resource, destination, on_progress)
        except UpdateServiceError as error:
            raise DifferentialUpdateError(f"could not download {asset.name}: {error}") from error

    def _require_room(self, plan: TreePlan) -> None:
        needed = self._strategy.required_bytes(plan)
        try:
            free = shutil.disk_usage(self._install_root).free
        except OSError as error:
            raise DifferentialUpdateError(f"could not measure available disk: {error}") from error
        if free < needed:
            raise DifferentialUpdateError(
                f"this update needs about {_megabytes(needed)} free on the drive holding "
                f"Hanly, and {_megabytes(free)} is available"
            )


def _asset_record(payload: Any) -> ReleaseAssetRecord | None:
    """Read one release asset, or None for an entry that is not usable."""

    if not isinstance(payload, Mapping):
        return None
    name = payload.get("name")
    url = payload.get("browser_download_url", payload.get("url"))
    if not isinstance(name, str) or not name or not isinstance(url, str) or not url:
        return None
    return ReleaseAssetRecord(
        name=name,
        url=url,
        asset_id=_optional_integer(payload.get("id")),
        size=_optional_integer(payload.get("size")),
        digest=_api_digest(payload.get("digest")),
    )


def _api_digest(value: Any) -> str | None:
    """The SHA-256 GitHub reports for an asset, when it reports one."""

    if isinstance(value, str) and value.startswith("sha256:") and len(value) == 71:
        return value[len("sha256:") :].lower()
    return None


def _optional_integer(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _metadata_asset(name: str, digest: str | None = None) -> ReleaseAsset:
    """Describe a small release document as the asset the downloader fetches."""

    return ReleaseAsset(name=name, size=MAX_METADATA_BYTES, sha256=digest or "0" * 64)


def _verify_asset(path: Path, asset: ReleaseAsset) -> None:
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


def _require_cancel(should_cancel: CancelHook | None) -> None:
    if should_cancel is not None and should_cancel():
        raise UpdateCancelled("the update was cancelled before anything changed")


# --------------------------------------------------------------------------
# Windows: adapt the working in-place transaction, do not rewrite it
# --------------------------------------------------------------------------

#: Room for the journal, the staged control file, and the helper's own log.
METADATA_MARGIN_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class StagedWindowsTransaction:
    """A Windows transaction laid out and waiting for the native helper."""

    journal: UpdateJournal
    transaction: TransactionPlan
    challenge: UpdateChallenge


class WindowsFileStaging:
    """Stage exactly the files that differ, into the existing transaction.

    Windows keeps changing an installation file by file rather than swapping a
    whole tree: the PowerShell helper, its backups, its long-path handling and
    its external recovery copy already do that and are proven against real
    frozen builds. What changed in schema 2 is where the plan comes from and
    what the new build has to prove before the update is committed.
    """

    label = "windows-files"

    def __init__(
        self,
        *,
        install_root: Path,
        executable: str,
        recovery_root: Path,
        store: ReceiptStore,
        source_commit: str,
    ) -> None:
        self._install_root = Path(install_root).resolve()
        self._executable = executable
        self._recovery_root = Path(recovery_root)
        self._store = store
        self._source_commit = source_commit

    def precheck(self, prepared: PreparedTreeUpdate) -> None:
        """Refuse a target this strategy cannot put in place file by file."""

        unstageable = _unstageable_entries(prepared.target)
        if unstageable:
            raise UpdateBlocked(
                "this build contains entries an in-place update cannot install "
                f"({', '.join(unstageable[:3])}). Install it by hand instead."
            )
        if prepared.plan.transitions:
            raise UpdateBlocked(
                "this update changes what "
                f"{', '.join(prepared.plan.transitions[:3])} is, which an in-place update "
                "cannot do safely. Install it by hand instead."
            )

    def required_bytes(self, plan: TreePlan) -> int:
        """Payload, newly staged files, records, and headroom.

        A replaced file is renamed to its backup rather than copied, so it is
        already allocated and is deliberately not counted a second time.
        """

        return (
            plan.download_bytes + plan.write_bytes + METADATA_MARGIN_BYTES + DISK_MARGIN_BYTES
        )

    def assemble(
        self,
        prepared: PreparedTreeUpdate,
        payload: Path,
        *,
        on_progress: ProgressCallback | None = None,
        should_cancel: CancelHook | None = None,
    ) -> StagedWindowsTransaction:
        """Lay out one transaction the helper can apply, or undo, on its own."""

        journal = self._open_transaction()
        try:
            return self._stage_into(journal, prepared, payload, on_progress, should_cancel)
        except BaseException:
            _remove(journal.directory)
            raise

    def _stage_into(
        self,
        journal: UpdateJournal,
        prepared: PreparedTreeUpdate,
        payload: Path,
        on_progress: ProgressCallback | None,
        should_cancel: CancelHook | None,
    ) -> StagedWindowsTransaction:
        plan = prepared.plan
        operations = tree_operations_for(plan)
        challenge = new_challenge(
            journal.directory.name,
            plan.identity,
            prepared.target.digest(),
            self._install_root,
        )
        challenge_path = write_challenge(
            self._store.directory / f"challenge-{challenge.transaction_id}.json", challenge
        )

        transaction = TransactionPlan(
            transaction_id=challenge.transaction_id,
            install_root=self._install_root,
            executable=self._executable,
            target=plan.identity,
            base=plan.base_identity,
            operations=operations,
            recovery_root=self._recovery_root,
            created=time.time(),
            record=RECORD_WINDOWS_FILES,
            manifest_sha256=prepared.target.digest(),
            challenge_path=challenge_path,
            receipt_path=self._store.receipt_path,
        )
        journal.prepare(transaction)
        journal.expected_path.write_text(challenge.expected(), encoding="utf-8", newline="\n")

        _emit(on_progress, "unpacking", 0, len(operations))
        _unpack_payload(payload, journal, operations, on_progress, should_cancel)
        self._stage_receipt(prepared)
        return StagedWindowsTransaction(
            journal=journal, transaction=transaction, challenge=challenge
        )

    def _stage_receipt(self, prepared: PreparedTreeUpdate) -> None:
        """Keep the manifest and the receipt the new build will be entitled to.

        Neither is adopted here. The receipt becomes this installation's only
        once the new build has answered its challenge, and the previous one is
        kept beside it until then.
        """

        self._store.store_manifest(prepared.target)
        self._store.stage_receipt(
            receipt_for(
                self._install_root,
                prepared.target,
                release_tag=prepared.snapshot.tag,
                source_commit=self._source_commit,
                preserved_paths=prepared.plan.preserved,
            )
        )

    def _open_transaction(self) -> UpdateJournal:
        root = working_root(self._install_root)
        try:
            root.mkdir(parents=True, exist_ok=True)
            return UpdateJournal(Path(tempfile.mkdtemp(prefix="t", dir=root)))
        except (OSError, JournalError) as error:
            raise DifferentialUpdateError(
                f"could not prepare an update inside {self._install_root}: {error}"
            ) from error


def _unstageable_entries(target: TreeManifest) -> tuple[str, ...]:
    """Target entries a file-by-file Windows apply has no operation for.

    A link or an empty directory would have to be created by something, and
    nothing in this strategy creates one. The producer refuses to publish a
    Windows build containing either, so reaching this is a release defect - it
    is checked again here because a client must not act on one.
    """

    parents = {
        "/".join(entry.path.split("/")[:depth])
        for entry in target
        for depth in range(1, entry.path.count("/") + 1)
    }
    return tuple(
        sorted(
            entry.path
            for entry in target
            if entry.is_symlink or (entry.is_directory and entry.path not in parents)
        )
    )


def _unpack_payload(
    archive: Path,
    journal: UpdateJournal,
    operations: tuple[JournalOperation, ...],
    on_progress: ProgressCallback | None,
    should_cancel: CancelHook | None,
) -> None:
    """Extract only the members this update needs, one at a time.

    A member is written to a name of this module's choosing rather than to the
    path it claims, so a hostile archive has no say in where anything lands.
    The claimed path still has to be one the plan asked for, which is what
    stops an unwanted extra member being written at all.
    """

    wanted = {item.path: item for item in operations if item.writes_a_file}
    with zipfile.ZipFile(archive) as payload:
        members = _payload_members(payload, set(wanted))
        missing = sorted(set(wanted) - set(members))
        if missing:
            raise DifferentialUpdateError(
                f"the downloaded payload is missing {len(missing)} file(s) this update "
                "needs: " + ", ".join(missing[:5])
            )
        for done, (relative, member) in enumerate(sorted(members.items()), start=1):
            _require_cancel(should_cancel)
            operation = wanted[relative]
            _extract_member(payload, member, journal.payload_for(operation), operation)
            _emit(on_progress, "unpacking", done, len(wanted))


def _payload_members(
    payload: zipfile.ZipFile, wanted: set[str]
) -> dict[str, zipfile.ZipInfo]:
    """Index the archive by installed path, refusing anything unsafe.

    A full product nests everything under its root directory and a delta does
    not, so the prefix is stripped when it is there. Members the plan did not
    ask for are ignored rather than rejected: a full archive legitimately
    carries the whole build.
    """

    found: dict[str, zipfile.ZipInfo] = {}
    entries = 0
    for member in payload.infolist():
        entries += 1
        if entries > MAX_MANIFEST_ENTRIES:
            raise DifferentialUpdateError(
                "the downloaded payload lists more files than a build has"
            )
        if member.is_dir():
            continue
        relative = _installed_path(member.filename)
        if relative is None or relative not in wanted:
            continue
        if relative in found:
            raise DifferentialUpdateError(f"the downloaded payload carries {relative} twice")
        if (member.external_attr >> 16) & 0o170000 == 0o120000:
            raise DifferentialUpdateError("the downloaded payload contains a link")
        found[relative] = member
    return found


# --------------------------------------------------------------------------
# macOS and Linux: build the whole new installation, then swap it
# --------------------------------------------------------------------------

#: The private directory one POSIX update owns, beside the installation so the
#: swap that follows is a rename on one filesystem.
TRANSACTION_PREFIX = ".hanly-update-"

#: A macOS install that lives here is a copy the system made to run it from a
#: quarantined location. Replacing that copy would change nothing a user sees.
_TRANSLOCATED = "/AppTranslocation/"


@dataclass(frozen=True, slots=True)
class StagedPosixTransaction:
    """A whole new installation, built and proved, waiting to be swapped in."""

    directory: Path
    candidate: BuiltCandidate
    challenge: UpdateChallenge
    install_root: Path

    @property
    def previous_path(self) -> Path:
        return self.directory / PREVIOUS_NAME

    @property
    def rejected_path(self) -> Path:
        return self.directory / REJECTED_NAME


class PosixTreeStaging:
    """Reconstruct the published build beside the installation, then prove it.

    macOS and Linux share this because they share the reason for it: a bundle
    is signed as a whole and a onedir's libraries are opened long after start,
    so an installation caught between two builds is worse than one replaced in
    a single step. What differs is only what each platform allows to be in an
    installation that is not the product.
    """

    label = "posix-tree"

    def __init__(
        self,
        *,
        install_root: Path,
        platform: str,
        store: ReceiptStore,
        source_commit: str,
        runner: Any = None,
    ) -> None:
        self._install_root = Path(install_root).resolve()
        self._platform = platform
        self._store = store
        self._source_commit = source_commit
        self._runner = runner

    def precheck(self, prepared: PreparedTreeUpdate) -> None:
        """Refuse before anything is fetched what cannot be installed at all."""

        self._require_writable_location()
        if self._platform == PLATFORM_MACOS and prepared.plan.preserved:
            raise UpdateBlocked(
                "this application contains files Hanly did not install "
                f"({', '.join(prepared.plan.preserved[:3])}). Move them out, or install the "
                "new version by hand and keep this one until you have."
            )

    def required_bytes(self, plan: TreePlan) -> int:
        """Payload, the whole new copy, the extras kept, records, and headroom.

        The old installation is renamed aside rather than copied, so it is
        already allocated and is deliberately not counted again.
        """

        return (
            plan.download_bytes
            + plan.candidate_bytes
            + _preserved_bytes(self._install_root, plan.preserved)
            + METADATA_MARGIN_BYTES
            + DISK_MARGIN_BYTES
        )

    def assemble(
        self,
        prepared: PreparedTreeUpdate,
        payload: Path,
        *,
        on_progress: ProgressCallback | None = None,
        should_cancel: CancelHook | None = None,
    ) -> StagedPosixTransaction:
        """Build the whole candidate, prove it, and leave it ready to swap."""

        directory = self._open_transaction()
        try:
            return self._build(directory, prepared, payload, on_progress, should_cancel)
        except BaseException:
            _remove(directory)
            raise

    def _build(
        self,
        directory: Path,
        prepared: PreparedTreeUpdate,
        payload: Path,
        on_progress: ProgressCallback | None,
        should_cancel: CancelHook | None,
    ) -> StagedPosixTransaction:
        plan = prepared.plan
        root = directory / CANDIDATE_NAME
        candidate = self._reconstruct(root, prepared, payload, on_progress, should_cancel)

        if plan.preserved:
            candidate = copy_preserved(candidate, self._install_root, plan.preserved)

        _emit(on_progress, "validating-bundle")
        verify_candidate(candidate)
        self._require_launchable(candidate)

        challenge = new_challenge(
            directory.name.removeprefix(TRANSACTION_PREFIX),
            plan.identity,
            prepared.target.digest(),
            self._install_root,
        )
        self._record(directory, prepared, challenge)
        return StagedPosixTransaction(
            directory=directory,
            candidate=candidate,
            challenge=challenge,
            install_root=self._install_root,
        )

    def _reconstruct(
        self,
        root: Path,
        prepared: PreparedTreeUpdate,
        payload: Path,
        on_progress: ProgressCallback | None,
        should_cancel: CancelHook | None,
    ) -> BuiltCandidate:
        """Produce the candidate, from changed bytes or from a whole product."""

        def relay(phase: str, completed: int, total: int) -> None:
            _emit(on_progress, phase, completed, total)

        _emit(on_progress, "reconstructing")
        try:
            if prepared.plan.source == FROM_DELTA:
                return assemble_candidate(
                    root,
                    prepared.target,
                    source_root=self._install_root,
                    reusable=prepared.plan.reusable_paths,
                    payload=payload,
                    on_progress=relay,
                    should_cancel=should_cancel,
                )
            if prepared.entry.full.format == FORMAT_DMG:
                return acquire_disk_image(
                    root, payload, prepared.target, **self._native()
                )
            return extract_full_product(
                root, payload, prepared.target, on_progress=relay, should_cancel=should_cancel
            )
        except CandidateCancelled as error:
            raise UpdateCancelled(str(error)) from error
        except CandidateError as error:
            raise DifferentialUpdateError(str(error)) from error

    def _require_launchable(self, candidate: BuiltCandidate) -> None:
        """Hold the finished candidate to what macOS needs before it will run."""

        if self._platform != PLATFORM_MACOS:
            return
        try:
            require_bundle_identity(
                candidate.root,
                version=candidate.manifest.identity.version,
                executable=candidate.manifest.layout.executable,
            )
            require_valid_signature(candidate.root, **self._native())
        except BundleError as error:
            raise DifferentialUpdateError(str(error)) from error

    def _record(
        self, directory: Path, prepared: PreparedTreeUpdate, challenge: UpdateChallenge
    ) -> None:
        """Write what a helper and a later recovery run read, before either exists."""

        transaction = TransactionPlan(
            transaction_id=challenge.transaction_id,
            install_root=self._install_root,
            executable=prepared.target.layout.executable,
            target=prepared.plan.identity,
            base=prepared.plan.base_identity,
            operations=(),
            recovery_root=self._store.directory,
            created=time.time(),
            record=RECORD_POSIX_TREE,
            manifest_sha256=prepared.target.digest(),
            challenge_path=write_challenge(
                self._store.directory / f"challenge-{challenge.transaction_id}.json", challenge
            ),
            receipt_path=self._store.receipt_path,
        )
        journal = UpdateJournal(directory)
        journal.prepare(transaction)
        journal.expected_path.write_text(challenge.expected(), encoding="utf-8", newline="\n")

        self._store.store_manifest(prepared.target)
        self._store.stage_receipt(
            receipt_for(
                self._install_root,
                prepared.target,
                release_tag=prepared.snapshot.tag,
                source_commit=self._source_commit,
                preserved_paths=prepared.plan.preserved,
            )
        )

    def _open_transaction(self) -> Path:
        """Claim a private directory on the installation's own volume."""

        try:
            return Path(
                tempfile.mkdtemp(prefix=TRANSACTION_PREFIX, dir=self._install_root.parent)
            )
        except OSError as error:
            raise DifferentialUpdateError(
                f"could not prepare an update beside {self._install_root}: {error}"
            ) from error

    def _require_writable_location(self) -> None:
        """Refuse a place an update could not put a new installation into."""

        parent = self._install_root.parent
        if _TRANSLOCATED in str(self._install_root):
            raise UpdateBlocked(
                "Hanly is running from a copy macOS made to open it safely. Move Hanly into "
                "your Applications folder and open it from there, then update."
            )
        if not os.access(parent, os.W_OK | os.X_OK) or _is_read_only(parent):
            raise UpdateBlocked(
                f"Hanly cannot update itself where it is installed ({parent} cannot be "
                "written to). Move it somewhere you own, then update."
            )

    def _native(self) -> dict[str, Any]:
        """The command runner, passed only when a caller supplied one."""

        return {} if self._runner is None else {"runner": self._runner}


def _preserved_bytes(install_root: Path, paths: tuple[str, ...]) -> int:
    total = 0
    for relative in paths:
        try:
            total += os.lstat(install_root.joinpath(*relative.split("/"))).st_size
        except OSError:
            continue
    return total


def _is_read_only(path: Path) -> bool:
    try:
        return bool(os.statvfs(path).f_flag & os.ST_RDONLY)
    except (OSError, AttributeError):
        return False

__all__ = [
    "ARCHIVE_ROOT",
    "CHECKSUM_ASSET",
    "DISK_MARGIN_BYTES",
    "MAX_CHECKSUM_BYTES",
    "MAX_RELEASE_ASSETS",
    "AssetDownloader",
    "METADATA_MARGIN_BYTES",
    "DifferentialInstaller",
    "DifferentialUpdateError",
    "PreparedTreeUpdate",
    "PreparedUpdate",
    "ReleaseAssetRecord",
    "ReleaseSnapshot",
    "TRANSACTION_PREFIX",
    "PosixTreeStaging",
    "StagedPosixTransaction",
    "StagedTreeUpdate",
    "StagedUpdate",
    "StagedWindowsTransaction",
    "StagingStrategy",
    "TaggedReleaseSource",
    "TreeUpdateInstaller",
    "UnsupportedPlatform",
    "UpdateBlocked",
    "WindowsFileStaging",
    "UpdateCancelled",
    "snapshot_release",
]
