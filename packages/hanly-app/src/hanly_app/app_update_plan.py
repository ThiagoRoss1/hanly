"""Deciding what an update has to change, before anything is downloaded.

A plan is produced from three things: the target manifest the release
publishes, the inventory of what is actually installed, and the delta the
release offers if it offers one. It says which files are added, replaced, and
deleted, which payload can supply them, and what it refuses to touch.

Planning is separate from downloading and from applying so that the answer can
be shown to the user - a real size, a real file count - before the first byte
of payload is fetched, and so the same answer can be re-checked against disk
after the application has stopped and before anything is written.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .app_inventory import InstalledTree
from .app_manifest import (
    AssetReference,
    BuildIdentity,
    DeltaDescriptor,
    FileEntry,
    InstallManifest,
    UpdateMetadata,
)

#: Where the files a plan needs will come from.
FROM_DELTA = "delta"
FROM_FULL = "full"

#: What a plan knows about the installation it is changing.
OWNERSHIP_VERIFIED = "verified"
OWNERSHIP_UNVERIFIED = "unverified"

ADD = "add"
REPLACE = "replace"
DELETE = "delete"


class PlanError(RuntimeError):
    """Raised when no safe plan exists for an installation."""


@dataclass(frozen=True, slots=True)
class FileOperation:
    """One change the apply step will make, and what it expects to find."""

    kind: str
    path: str
    #: What the file must contain afterwards. Absent for a deletion.
    target: FileEntry | None = None
    #: What it contains now, when the plan read it. Absent for an addition.
    current_sha256: str | None = None
    component: str = "application"

    @property
    def size(self) -> int:
        return 0 if self.target is None else self.target.size


@dataclass(frozen=True, slots=True)
class UpdatePlan:
    """Everything one update will do, decided before any payload is fetched."""

    identity: BuildIdentity
    base_identity: BuildIdentity | None
    source: str
    payload: AssetReference
    operations: tuple[FileOperation, ...]
    ownership: str
    #: Target paths occupied by files this installation does not own. Reported,
    #: never overwritten - the update stops rather than destroying them.
    collisions: tuple[str, ...] = ()
    #: Files left exactly as they are because nothing owns them.
    preserved: tuple[str, ...] = ()
    #: Why the delta could not be used, when a delta was advertised.
    fallback_reason: str = ""

    @property
    def additions(self) -> tuple[FileOperation, ...]:
        return tuple(item for item in self.operations if item.kind == ADD)

    @property
    def replacements(self) -> tuple[FileOperation, ...]:
        return tuple(item for item in self.operations if item.kind == REPLACE)

    @property
    def deletions(self) -> tuple[FileOperation, ...]:
        return tuple(item for item in self.operations if item.kind == DELETE)

    @property
    def required_paths(self) -> tuple[str, ...]:
        """Target paths the payload has to supply."""

        return tuple(item.path for item in self.operations if item.kind in (ADD, REPLACE))

    @property
    def write_bytes(self) -> int:
        """How much will actually be written into the installation."""

        return sum(item.size for item in self.operations)

    @property
    def download_bytes(self) -> int:
        return self.payload.size

    @property
    def is_empty(self) -> bool:
        return not self.operations

    def summary(self) -> dict[str, object]:
        """The JSON-compatible shape the Control Center renders."""

        return {
            "source": self.source,
            "version": self.identity.version,
            "base_version": None if self.base_identity is None else self.base_identity.version,
            "download_bytes": self.download_bytes,
            "write_bytes": self.write_bytes,
            "add_count": len(self.additions),
            "replace_count": len(self.replacements),
            "delete_count": len(self.deletions),
            "ownership": self.ownership,
            "collisions": list(self.collisions),
            "fallback_reason": self.fallback_reason,
        }


def plan_update(
    metadata: UpdateMetadata,
    target: InstallManifest,
    installed: InstalledTree,
    *,
    base_manifest: InstallManifest | None,
) -> UpdatePlan:
    """Decide the whole update: what changes, and which payload supplies it.

    ``base_manifest`` is what the installed build claims to be. It is used for
    ownership - which files this updater may delete - and to match a delta's
    declared base. An installation that carries none still updates; it just
    updates from the full archive and deletes nothing.
    """

    _require_same_product(metadata.identity, target.identity)

    operations, collisions = _changes(target, installed, base_manifest)
    delta = _usable_delta(metadata, target, base_manifest, operations)
    fallback_reason = "" if delta is not None else _fallback_reason(metadata, base_manifest)

    return UpdatePlan(
        identity=target.identity,
        base_identity=None if base_manifest is None else base_manifest.identity,
        source=FROM_DELTA if delta is not None else FROM_FULL,
        payload=delta.payload if delta is not None else metadata.full,
        operations=operations,
        ownership=OWNERSHIP_VERIFIED if base_manifest is not None else OWNERSHIP_UNVERIFIED,
        collisions=collisions,
        preserved=installed.unmanaged,
        fallback_reason=fallback_reason,
    )


def _changes(
    target: InstallManifest,
    installed: InstalledTree,
    base_manifest: InstallManifest | None,
) -> tuple[tuple[FileOperation, ...], tuple[str, ...]]:
    """Diff the target against what is on disk, keeping ownership in mind."""

    operations: list[FileOperation] = []
    collisions: list[str] = []

    for entry in target:
        current = installed.get(entry.path)
        if current is None:
            operations.append(
                FileOperation(kind=ADD, path=entry.path, target=entry, component=entry.component)
            )
            continue
        if current.sha256 == entry.sha256:
            continue
        if base_manifest is not None and entry.path not in base_manifest:
            # Something occupies a path the previous build never owned. It is
            # not this updater's file to overwrite.
            collisions.append(entry.path)
            continue
        operations.append(
            FileOperation(
                kind=REPLACE,
                path=entry.path,
                target=entry,
                current_sha256=current.sha256,
                component=entry.component,
            )
        )

    operations.extend(_removals(target, installed, base_manifest))
    operations.sort(key=lambda item: (_ORDER[item.kind], item.path))
    return tuple(operations), tuple(sorted(collisions))


def _removals(
    target: InstallManifest,
    installed: InstalledTree,
    base_manifest: InstallManifest | None,
) -> list[FileOperation]:
    """Delete only what the previous build owned and the new one dropped.

    With no verified previous inventory there is no ownership to reason from,
    so nothing is deleted. A stale file left behind is harmless; deleting
    somebody's file because a manifest did not mention it is not.
    """

    if base_manifest is None:
        return []
    removals: list[FileOperation] = []
    for entry in base_manifest:
        if entry.path in target:
            continue
        current = installed.get(entry.path)
        if current is None:
            continue
        removals.append(
            FileOperation(
                kind=DELETE,
                path=entry.path,
                current_sha256=current.sha256,
                component=entry.component,
            )
        )
    return removals


def _usable_delta(
    metadata: UpdateMetadata,
    target: InstallManifest,
    base_manifest: InstallManifest | None,
    operations: tuple[FileOperation, ...],
) -> DeltaDescriptor | None:
    """Return the delta only if it can supply everything this plan needs.

    A delta carries what changed between two *published* builds, which is not
    the set that differs from *this* installation: a file corrupted since
    install is missing here and unchanged there, so the delta lacks it.
    """

    if base_manifest is None:
        return None
    delta = metadata.delta_for(base_manifest.identity, base_manifest.digest())
    if delta is None:
        return None
    required = {item.path for item in operations if item.kind in (ADD, REPLACE)}
    return delta if required <= delta_contents(target, base_manifest) else None


def delta_contents(target: InstallManifest, base_manifest: InstallManifest) -> set[str]:
    """Which target paths a delta between these two builds carries.

    The descriptor does not list its own members, so both sides derive them the
    same way: every target file the base build did not have, or had with
    different content. Producer and consumer compute this from the same two
    manifests, so they agree by construction rather than by agreement.
    """

    return {
        entry.path
        for entry in target
        if (previous := base_manifest.get(entry.path)) is None
        or previous.sha256 != entry.sha256
    }


def _fallback_reason(metadata: UpdateMetadata, base_manifest: InstallManifest | None) -> str:
    if metadata.delta is None:
        return metadata.delta_omitted_reason or "this release publishes no differential update"
    if base_manifest is None:
        return "this installation has no file inventory to update from"
    delta = metadata.delta
    if delta.base_version != base_manifest.identity.version:
        return (
            f"the differential update starts from Hanly {delta.base_version}, "
            f"and Hanly {base_manifest.identity.version} is installed"
        )
    if delta.base_build_id != base_manifest.identity.build_id:
        return "the installed build is not the published build this update starts from"
    if delta.base_manifest_digest != base_manifest.digest():
        return "the installed file inventory no longer matches its build"
    return "some installed files need repairing, which the differential update does not carry"


def _require_same_product(metadata: BuildIdentity, target: BuildIdentity) -> None:
    if metadata.to_dict() != target.to_dict():
        raise PlanError("the release metadata and its manifest describe different builds")


_ORDER: Mapping[str, int] = {ADD: 0, REPLACE: 1, DELETE: 2}


__all__ = [
    "ADD",
    "DELETE",
    "FROM_DELTA",
    "FROM_FULL",
    "OWNERSHIP_UNVERIFIED",
    "OWNERSHIP_VERIFIED",
    "REPLACE",
    "FileOperation",
    "PlanError",
    "UpdatePlan",
    "delta_contents",
    "plan_update",
]
