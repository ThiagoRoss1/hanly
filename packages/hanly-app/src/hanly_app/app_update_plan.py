"""Deciding what an update has to change, before anything is downloaded.

A plan is produced from three things: the target manifest the release
publishes, the inventory of what is actually installed, and the delta the
release offers if it offers one. It says which files are added, replaced, and
deleted, which payload can supply them, and what it refuses to touch.

Planning is separate from downloading and from applying so that the answer can
be shown to the user - a real size, a real file count - before the first byte
of payload is fetched, and so the same answer can be re-checked against disk
after the application has stopped and before anything is written.

Schema 2 keeps that shape and widens it to every platform. There is one
planning algorithm; what differs between Windows, macOS, and Linux is only what
each does with the plan it is given.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .app_hup import DeltaDescriptor as HupDelta
from .app_hup import ReleaseAsset
from .app_inventory import InstalledTree, TreeInventory
from .app_manifest import (
    AssetReference,
    BuildIdentity,
    DeltaDescriptor,
    FileEntry,
    InstallManifest,
    TreeEntry,
    TreeManifest,
    UpdateMetadata,
    tree_difference,
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


# --------------------------------------------------------------------------
# Schema 2: one planner for all three platforms
#
# The three strategies differ in how they apply a plan, never in how they
# decide one. Windows moves individual files into a live installation; macOS
# and Linux assemble a whole candidate and swap it. Both need the same three
# answers first - what differs, which of it the payload has to carry, and what
# this updater is not allowed to touch - so those answers are computed once
# here and handed to whichever strategy runs.
# --------------------------------------------------------------------------

#: How this installation's ownership of its own files was established.
OWNERSHIP_RECEIPT = "receipt"
OWNERSHIP_BOOTSTRAP = "bootstrap"


class OwnershipUnknown(PlanError):
    """Raised when nothing establishes what this installation is made of.

    An update that proceeded from here would be guessing which files it owns,
    and the first thing it would guess about is what it may delete.
    """


@dataclass(frozen=True, slots=True)
class TreeOperation:
    """One difference between the target build and what is on disk now."""

    kind: str
    path: str
    target: TreeEntry | None = None
    current: TreeEntry | None = None

    @property
    def needs_bytes(self) -> bool:
        """Whether a payload has to supply this operation's content.

        Directories, links, permission bits and macOS signature attributes all
        come from the manifest, so a file whose bytes are already right on disk
        needs nothing sent even though it is changing.
        """

        target = self.target
        if self.kind not in (ADD, REPLACE) or target is None or not target.is_file:
            return False
        current = self.current
        return current is None or not current.is_file or current.sha256 != target.sha256

    @property
    def size(self) -> int:
        return 0 if self.target is None else self.target.byte_size

    @property
    def component(self) -> str:
        entry = self.target if self.target is not None else self.current
        return "application" if entry is None else entry.component


@dataclass(frozen=True, slots=True)
class TreePlan:
    """Everything one update will do, decided before its payload is fetched."""

    target: TreeManifest
    base_identity: BuildIdentity
    ownership: str
    source: str
    payload: ReleaseAsset
    operations: tuple[TreeOperation, ...]
    #: Target files already byte-correct on disk. On POSIX these are copied
    #: into the candidate rather than downloaded; on Windows they are left.
    reusable_paths: tuple[str, ...] = ()
    #: Target paths occupied by something the previous build never owned.
    #: Reported and never overwritten - equal bytes are not ownership.
    collisions: tuple[str, ...] = ()
    #: Paths whose kind changes between the two builds. Windows refuses these
    #: rather than guessing a destructive order; a whole candidate does not
    #: care, because it never rewrites the old tree in place.
    transitions: tuple[str, ...] = ()
    #: What is in the installation that no build described. Kept as it is.
    preserved: tuple[str, ...] = ()
    fallback_reason: str = ""

    @property
    def identity(self) -> BuildIdentity:
        return self.target.identity

    @property
    def version(self) -> str:
        return self.target.identity.version

    @property
    def platform(self) -> str:
        return self.target.platform

    @property
    def additions(self) -> tuple[TreeOperation, ...]:
        return tuple(item for item in self.operations if item.kind == ADD)

    @property
    def replacements(self) -> tuple[TreeOperation, ...]:
        return tuple(item for item in self.operations if item.kind == REPLACE)

    @property
    def deletions(self) -> tuple[TreeOperation, ...]:
        return tuple(item for item in self.operations if item.kind == DELETE)

    @property
    def required_paths(self) -> tuple[str, ...]:
        """Exactly the paths whose bytes the payload has to carry."""

        return tuple(sorted(item.path for item in self.operations if item.needs_bytes))

    @property
    def download_bytes(self) -> int:
        return self.payload.size

    @property
    def write_bytes(self) -> int:
        """What lands inside the installation itself, file by file."""

        return sum(item.size for item in self.operations)

    @property
    def candidate_bytes(self) -> int:
        """What a whole reconstructed copy of the target build occupies."""

        return self.target.total_size

    @property
    def reused_bytes(self) -> int:
        """Bytes a candidate copies from this installation rather than fetches."""

        return sum(
            entry.byte_size
            for path in self.reusable_paths
            if (entry := self.target.get(path)) is not None
        )

    @property
    def is_empty(self) -> bool:
        return not self.operations

    @property
    def is_blocked(self) -> bool:
        return bool(self.collisions)

    def summary(self) -> dict[str, object]:
        """The JSON-compatible shape the Control Center renders."""

        return {
            "source": self.source,
            "platform": self.platform,
            "architecture": self.identity.architecture,
            "version": self.version,
            "base_version": self.base_identity.version,
            "download_bytes": self.download_bytes,
            "write_bytes": self.write_bytes,
            "candidate_bytes": self.candidate_bytes,
            "reused_bytes": self.reused_bytes,
            "add_count": len(self.additions),
            "replace_count": len(self.replacements),
            "delete_count": len(self.deletions),
            "ownership": self.ownership,
            "collisions": list(self.collisions),
            "transitions": list(self.transitions),
            "preserved": list(self.preserved),
            "fallback_reason": self.fallback_reason,
        }


def plan_tree_update(
    target: TreeManifest,
    inventory: TreeInventory,
    base: TreeManifest | None,
    *,
    ownership: str,
    full: ReleaseAsset,
    delta: HupDelta | None = None,
) -> TreePlan:
    """Decide the whole update, before a byte of payload is fetched.

    ``base`` is what this installation is known to be - from a receipt this
    updater wrote, or from a published manifest the tree was proved to match
    exactly. Without one there is no plan to make: what an update may delete,
    and which occupied paths are its own, are both read from it.
    """

    if base is None:
        raise OwnershipUnknown(
            "this installation does not match any build Hanly published, so an update "
            "cannot tell its files from yours"
        )
    _require_same_build(target, base)

    operations, collisions = _tree_changes(target, inventory, base)
    required = {item.path for item in operations if item.needs_bytes}
    usable, reason = _usable_tree_delta(delta, base, target, required)

    return TreePlan(
        target=target,
        base_identity=base.identity,
        ownership=ownership,
        source=FROM_DELTA if usable is not None else FROM_FULL,
        payload=usable.payload if usable is not None else full,
        operations=operations,
        reusable_paths=_reusable(target, inventory, required),
        collisions=collisions,
        transitions=_transitions(target, base),
        preserved=_preserved(target, inventory, base),
        fallback_reason="" if usable is not None else reason,
    )


def _tree_changes(
    target: TreeManifest, inventory: TreeInventory, base: TreeManifest
) -> tuple[tuple[TreeOperation, ...], tuple[str, ...]]:
    """Diff the target against the actual tree, with ownership in mind.

    The comparison is against what is on disk, not against the base manifest: a
    file corrupted since installation differs here and not there, and an update
    that ignored the difference would leave it corrupted.
    """

    operations: list[TreeOperation] = []
    collisions: list[str] = []

    for entry in target:
        current = inventory.get(entry.path)
        if current is None:
            operations.append(TreeOperation(kind=ADD, path=entry.path, target=entry))
            continue
        if entry.path not in base:
            # Occupied by something the previous build never had. Equal bytes
            # are not ownership: somebody else put it there.
            collisions.append(entry.path)
            continue
        if not current.same_content(entry):
            operations.append(
                TreeOperation(kind=REPLACE, path=entry.path, target=entry, current=current)
            )

    operations.extend(_tree_removals(target, inventory, base))
    operations.sort(key=lambda item: (_ORDER[item.kind], item.path))
    return tuple(operations), tuple(sorted(collisions))


def _tree_removals(
    target: TreeManifest, inventory: TreeInventory, base: TreeManifest
) -> list[TreeOperation]:
    """Remove only what the previous build owned and the new one dropped.

    Deepest first, so a directory is emptied before it is taken away.
    """

    removals = [
        TreeOperation(kind=DELETE, path=entry.path, current=current)
        for entry in base
        if entry.path not in target and (current := inventory.get(entry.path)) is not None
    ]
    removals.sort(key=lambda item: item.path.count("/"), reverse=True)
    return removals


def _preserved(
    target: TreeManifest, inventory: TreeInventory, base: TreeManifest
) -> tuple[str, ...]:
    """What is in the installation that no build of Hanly ever described.

    A path the previous build owned and this one drops is not somebody's file:
    it is this update's deletion, and the plan already accounts for it. Counting
    it as an extra would make every release that removes a file look like an
    installation somebody had been editing.
    """

    return tuple(
        path
        for path in sorted(inventory.entries)
        if path not in target and path not in base
    )


def _reusable(
    target: TreeManifest, inventory: TreeInventory, required: set[str]
) -> tuple[str, ...]:
    """Target files this installation already holds, byte for byte.

    On POSIX these are what a candidate is mostly built from; saying so is also
    what keeps "reusing content" from being read as "writing nothing".
    """

    return tuple(
        sorted(
            entry.path
            for entry in target.files
            if entry.path not in required
            and (current := inventory.get(entry.path)) is not None
            and current.is_file
            and current.sha256 == entry.sha256
        )
    )


def _transitions(target: TreeManifest, base: TreeManifest) -> tuple[str, ...]:
    """Paths that stop being a file and start being a directory, or the reverse."""

    return tuple(
        sorted(
            entry.path
            for entry in target
            if (previous := base.get(entry.path)) is not None and previous.kind != entry.kind
        )
    )


def _usable_tree_delta(
    delta: HupDelta | None,
    base: TreeManifest,
    target: TreeManifest,
    required: set[str],
) -> tuple[HupDelta | None, str]:
    """Return the delta only when it can supply everything this plan needs.

    The release's advertised lists are checked against the diff both sides can
    compute rather than believed, and coverage is checked against what *this*
    installation actually needs, which is not the same set.
    """

    if delta is None:
        return None, "this release publishes no differential update for this installation"
    if delta.base_identity.to_dict() != base.identity.to_dict():
        return None, (
            f"the differential update starts from Hanly {delta.base_identity.version}, "
            f"and a different build of {base.identity.version} is installed"
        )
    if delta.base_manifest_sha256 != base.digest():
        return None, "the installed build's file inventory no longer matches its build"

    difference = tree_difference(base, target)
    if delta.changed_paths != difference.changed_paths:
        return None, "the differential update does not describe the change it publishes"
    if delta.deleted_paths != difference.deleted_paths:
        return None, "the differential update does not describe the files it removes"
    if not required <= set(difference.payload_paths):
        return None, (
            "some installed files need repairing, which the differential update does not carry"
        )
    return delta, ""


def _require_same_build(target: TreeManifest, base: TreeManifest) -> None:
    current = base.identity
    updated = target.identity
    if (current.product, current.platform, current.architecture) != (
        updated.product,
        updated.platform,
        updated.architecture,
    ):
        raise PlanError("the installed build and the published build are for different machines")
    if current.build_id == updated.build_id:
        raise PlanError("the published build is the one already installed")


__all__ = [
    "ADD",
    "DELETE",
    "FROM_DELTA",
    "FROM_FULL",
    "OWNERSHIP_BOOTSTRAP",
    "OWNERSHIP_RECEIPT",
    "OWNERSHIP_UNVERIFIED",
    "OWNERSHIP_VERIFIED",
    "REPLACE",
    "FileOperation",
    "OwnershipUnknown",
    "PlanError",
    "TreeOperation",
    "TreePlan",
    "UpdatePlan",
    "delta_contents",
    "plan_tree_update",
    "plan_update",
]
