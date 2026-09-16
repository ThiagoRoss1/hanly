"""Reading an installed tree into the inventory the manifest describes.

The producer hashes a freshly frozen build to publish its manifest; the client
hashes the installation it is about to change to find out what actually differs
from it. Both are the same walk, so both are here.

Schema 2 reads the same tree as a tree: directories, permission bits, relative
links, and the extended attributes a macOS signature lives in. Nothing is
followed - a link is recorded as a link, and a directory link is never
descended - so what comes back describes the installation rather than whatever
it happens to point at.

The walk is deliberately one sequential worker. Hashing a gigabyte across a
thread pool turns a disk into the bottleneck for everything else on the machine
and finishes no sooner, and this runs while the user is waiting with the
application still open.
"""

from __future__ import annotations

import base64
import hashlib
import os
import stat
import sys
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath

from .app_manifest import (
    INSTALLED_MANIFEST_NAME,
    KIND_DIRECTORY,
    KIND_FILE,
    KIND_SYMLINK,
    MATERIAL,
    POSIX_PLATFORMS,
    PROVENANCE,
    RESERVED_NAMES,
    WORKING_DIRECTORY_NAME,
    BuildIdentity,
    FileEntry,
    InstallManifest,
    ManifestError,
    TreeEntry,
    TreeLayout,
    TreeManifest,
    classify_xattr,
    require_safe_relative_path,
    require_tree_path,
)

#: One read of a file being hashed. Large enough that the syscall is not the
#: cost, small enough that a hostile size cannot be buffered.
_READ_BYTES = 1024 * 1024

#: Paths whose leading segment marks them as something other than product
#: content: per-user settings a build must never adopt, and Python's own
#: caches, which a frozen tree does not ship and a run can create.
_UNMANAGED_SEGMENTS = frozenset({"__pycache__"})

#: How a component label is read out of an installed path. A PyInstaller
#: onedir puts every dependency under ``_internal``; the label is the package
#: directory there, which is what a person recognizes in a progress list.
_INTERNAL_ROOT = "_internal"

ProgressHook = Callable[["InventoryProgress"], None]
CancelHook = Callable[[], bool]


class InventoryError(RuntimeError):
    """Raised when an installation cannot be read as a managed tree."""


class InventoryCancelled(InventoryError):
    """Raised when the caller asked to stop before the walk finished."""


@dataclass(frozen=True, slots=True)
class InventoryProgress:
    """How far a walk has got, in the units a person is shown."""

    files_completed: int
    files_total: int
    bytes_completed: int
    bytes_total: int

    @property
    def fraction(self) -> float | None:
        if self.bytes_total <= 0:
            return None
        return min(1.0, self.bytes_completed / self.bytes_total)


@dataclass(frozen=True, slots=True)
class InstalledTree:
    """What one installation holds right now.

    ``unmanaged`` is kept separate and never rewritten or deleted: a runtime
    cache, a log somebody dropped in, or a file from a build older than
    manifests is not the updater's to remove.
    """

    root: Path
    entries: Mapping[str, FileEntry]
    unmanaged: tuple[str, ...] = ()

    def get(self, path: str) -> FileEntry | None:
        return self.entries.get(path)

    def manifest(self, identity: BuildIdentity) -> InstallManifest:
        return InstallManifest.from_entries(identity, self.entries.values())


def file_digest(path: Path) -> tuple[str, int]:
    """Return one file's SHA-256 and size from a single streamed pass."""

    hasher = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(_READ_BYTES)
            if not chunk:
                break
            size += len(chunk)
            hasher.update(chunk)
    return hasher.hexdigest(), size


def component_for(relative: str) -> str:
    """Label a file by the package a person would recognize it as part of."""

    parts = PurePosixPath(relative).parts
    if len(parts) >= 3 and parts[0] == _INTERNAL_ROOT:
        return _label(parts[1])
    if len(parts) >= 2 and parts[0] == _INTERNAL_ROOT:
        return _label(PurePosixPath(parts[1]).stem)
    return "application"


def walk_installation(root: Path) -> Iterator[tuple[str, Path]]:
    """Yield every regular file under ``root`` as a manifest-shaped path.

    Directory links are not descended and file links are not followed: a
    PyInstaller Windows build contains neither, and one that appeared is not
    something to hash through.
    """

    base = Path(root)
    if not base.is_dir():
        raise InventoryError(f"{root} is not an installation directory")

    for directory, subdirectories, files in os.walk(base, followlinks=False):
        current = Path(directory)
        subdirectories[:] = sorted(
            name
            for name in subdirectories
            if not _is_excluded(current / name, base, name)
        )
        for name in sorted(files):
            candidate = current / name
            if candidate.is_symlink():
                continue
            relative = candidate.relative_to(base).as_posix()
            if _is_reserved(relative) or name == INSTALLED_MANIFEST_NAME:
                continue
            yield relative, candidate


def read_installation(
    root: Path,
    *,
    on_progress: ProgressHook | None = None,
    should_cancel: CancelHook | None = None,
) -> InstalledTree:
    """Hash every managed file in an installation, reporting as it goes."""

    candidates = list(walk_installation(root))
    managed: list[tuple[str, Path]] = []
    unmanaged: list[str] = []
    for relative, path in candidates:
        try:
            require_safe_relative_path(relative)
        except ManifestError:
            unmanaged.append(relative)
            continue
        if _is_unmanaged(relative):
            unmanaged.append(relative)
            continue
        managed.append((relative, path))

    total_bytes = sum(_size_of(path) for _relative, path in managed)
    entries: dict[str, FileEntry] = {}
    completed_bytes = 0

    _report(on_progress, 0, len(managed), 0, total_bytes)
    for index, (relative, path) in enumerate(managed, start=1):
        if should_cancel is not None and should_cancel():
            raise InventoryCancelled("reading the installation was cancelled")
        try:
            digest, size = file_digest(path)
        except OSError as error:
            raise InventoryError(f"could not read {relative}: {error}") from error
        entries[relative] = FileEntry(
            path=relative, sha256=digest, size=size, component=component_for(relative)
        )
        completed_bytes += size
        _report(on_progress, index, len(managed), completed_bytes, total_bytes)

    return InstalledTree(root=Path(root), entries=entries, unmanaged=tuple(sorted(unmanaged)))


def build_manifest(
    root: Path,
    identity: BuildIdentity,
    *,
    on_progress: ProgressHook | None = None,
) -> InstallManifest:
    """Read a freshly built tree into the manifest its release publishes."""

    tree = read_installation(root, on_progress=on_progress)
    if not tree.entries:
        raise InventoryError(f"{root} holds no files to describe")
    return tree.manifest(identity)


def read_installed_manifest(root: Path) -> InstallManifest | None:
    """Return the manifest a build carries, or None for one that carries none.

    A build predating manifests answers None, which is what sends a client to
    the full archive instead of a delta.
    """

    path = Path(root) / INSTALLED_MANIFEST_NAME
    if path.is_symlink() or not path.is_file():
        return None
    try:
        return InstallManifest.from_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ManifestError):
        return None


def write_installed_manifest(root: Path, manifest: InstallManifest) -> Path:
    """Write the inventory into the build, where the next update reads it."""

    path = Path(root) / INSTALLED_MANIFEST_NAME
    path.write_text(manifest.to_json(), encoding="utf-8")
    return path


def _report(
    hook: ProgressHook | None,
    files_completed: int,
    files_total: int,
    bytes_completed: int,
    bytes_total: int,
) -> None:
    if hook is not None:
        hook(InventoryProgress(files_completed, files_total, bytes_completed, bytes_total))


def _is_excluded(path: Path, base: Path, name: str) -> bool:
    if path.is_symlink():
        return True
    if name in _UNMANAGED_SEGMENTS:
        return True
    return path.relative_to(base).as_posix() in RESERVED_NAMES


def _is_reserved(relative: str) -> bool:
    return PurePosixPath(relative).parts[0] in RESERVED_NAMES


def _is_unmanaged(relative: str) -> bool:
    return any(part in _UNMANAGED_SEGMENTS for part in PurePosixPath(relative).parts)


def _size_of(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _label(value: str) -> str:
    cleaned = "".join(
        character if character.isalnum() or character in "._+-" else "-" for character in value
    )
    return cleaned[:64] or "application"


# --------------------------------------------------------------------------
# Schema 2: reading an installation as a tree
# --------------------------------------------------------------------------

#: Metadata a manifest cannot describe, and therefore cannot reproduce. Found
#: on a build, it fails the producer; found on an installation, it is what
#: stops an automatic update rather than something to quietly drop.
UNSUPPORTED_MODE_BITS = 0o7000


@dataclass(frozen=True, slots=True)
class TreeInventory:
    """Everything one installation actually contains, as it is right now.

    ``unsupported`` names entries this updater can read but not describe: a
    socket, a file with an immutable flag, an extended attribute in neither the
    material nor the provenance category. They are reported rather than
    ignored, because an installation containing one cannot be reconstructed.
    """

    root: Path
    platform: str
    entries: Mapping[str, TreeEntry]
    unsupported: tuple[str, ...] = ()

    def get(self, path: str) -> TreeEntry | None:
        return self.entries.get(path)

    def __contains__(self, path: object) -> bool:
        return path in self.entries

    @property
    def total_size(self) -> int:
        return sum(entry.byte_size for entry in self.entries.values())

    def manifest(self, identity: BuildIdentity, layout: TreeLayout) -> TreeManifest:
        """Describe this tree as the manifest its release would publish."""

        if self.unsupported:
            raise InventoryError(
                f"{self.root} contains {len(self.unsupported)} entries a manifest cannot "
                f"describe, starting with {self.unsupported[0]}"
            )
        return TreeManifest.from_entries(identity, layout, self.entries.values())


@dataclass(frozen=True, slots=True)
class TreeComparison:
    """How an installation differs from the build a manifest describes."""

    missing: tuple[str, ...]
    differing: tuple[str, ...]
    extra: tuple[str, ...]

    @property
    def matches(self) -> bool:
        return not (self.missing or self.differing or self.extra)


def read_tree(
    root: Path,
    platform: str,
    *,
    on_progress: ProgressHook | None = None,
    should_cancel: CancelHook | None = None,
) -> TreeInventory:
    """Read one installation into the vocabulary a schema-2 manifest speaks."""

    base = Path(root)
    if not base.is_dir() or base.is_symlink():
        raise InventoryError(f"{root} is not an installation directory")

    found = _scan_tree(base, platform)
    files = [item for item in found.entries if item.is_file]
    total_bytes = sum(_size_of(base.joinpath(*item.path.split("/"))) for item in files)

    entries: dict[str, TreeEntry] = {}
    completed = 0
    hashed = 0
    _report(on_progress, 0, len(files), 0, total_bytes)
    for entry in found.entries:
        if should_cancel is not None and should_cancel():
            raise InventoryCancelled("reading the installation was cancelled")
        if not entry.is_file:
            entries[entry.path] = entry
            continue
        path = base.joinpath(*entry.path.split("/"))
        try:
            digest, size = file_digest(path)
        except OSError as error:
            raise InventoryError(f"could not read {entry.path}: {error}") from error
        entries[entry.path] = replace(entry, sha256=digest, size=size)
        hashed += 1
        completed += size
        _report(on_progress, hashed, len(files), completed, total_bytes)

    return TreeInventory(
        root=base, platform=platform, entries=entries, unsupported=found.unsupported
    )


def compare_tree(inventory: TreeInventory, manifest: TreeManifest) -> TreeComparison:
    """Say exactly how an installation differs from one published build."""

    missing: list[str] = []
    differing: list[str] = []
    for entry in manifest:
        current = inventory.get(entry.path)
        if current is None:
            missing.append(entry.path)
        elif not current.same_content(entry):
            differing.append(entry.path)
    extra = [path for path in inventory.entries if path not in manifest]
    return TreeComparison(
        missing=tuple(sorted(missing)),
        differing=tuple(sorted(differing)),
        extra=tuple(sorted(extra)),
    )


def list_xattr_names(path: Path) -> tuple[str, ...]:
    """Every extended attribute on one entry, without following a link."""

    if sys.platform.startswith("darwin"):
        from . import app_xattr_darwin

        return app_xattr_darwin.list_names(path)
    if hasattr(os, "listxattr"):
        return tuple(os.listxattr(path, follow_symlinks=False))
    return ()


def read_xattr(path: Path, name: str) -> bytes:
    """One extended attribute's exact bytes."""

    if sys.platform.startswith("darwin"):
        from . import app_xattr_darwin

        return app_xattr_darwin.read_value(path, name)
    return os.getxattr(path, name, follow_symlinks=False)


def write_xattr(path: Path, name: str, value: bytes) -> None:
    """Set one extended attribute on an entry a candidate is assembling."""

    if sys.platform.startswith("darwin"):
        from . import app_xattr_darwin

        app_xattr_darwin.write_value(path, name, value)
        return
    os.setxattr(path, name, value, follow_symlinks=False)


def read_material_xattrs(path: Path, platform: str) -> tuple[Mapping[str, str], bool]:
    """Return the attributes that are content, and whether any were unreadable.

    Provenance attributes - where a download came from, what Finder recorded -
    are deliberately dropped: they belong to this machine's copy, not to the
    product. Anything in neither category is reported as unsupported rather
    than silently lost.
    """

    if platform not in POSIX_PLATFORMS:
        return {}, False

    material: dict[str, str] = {}
    unsupported = False
    try:
        names = list_xattr_names(path)
    except OSError:
        return {}, True
    for name in names:
        kind = classify_xattr(name)
        if kind == PROVENANCE:
            continue
        if kind != MATERIAL:
            unsupported = True
            continue
        try:
            value = read_xattr(path, name)
        except OSError:
            unsupported = True
            continue
        material[name] = base64.b64encode(value).decode("ascii")
    return material, unsupported


@dataclass(frozen=True, slots=True)
class _ScannedTree:
    """The shape of a tree before any of its files have been hashed."""

    entries: tuple[TreeEntry, ...]
    unsupported: tuple[str, ...]


def _scan_tree(base: Path, platform: str) -> _ScannedTree:
    """Walk the whole installation once, without following anything."""

    entries: list[TreeEntry] = []
    unsupported: list[str] = []
    pending: list[tuple[str, Path]] = [("", base)]

    while pending:
        relative, directory = pending.pop()
        for item in sorted(_scandir(directory), key=lambda value: value.name):
            child = f"{relative}/{item.name}" if relative else item.name
            if _is_updater_own(child):
                continue
            try:
                require_tree_path(child, platform)
            except ManifestError:
                unsupported.append(child)
                continue
            entry = _describe(child, Path(item.path), platform, unsupported)
            if entry is None:
                continue
            entries.append(entry)
            if entry.is_directory:
                pending.append((child, Path(item.path)))

    return _ScannedTree(
        entries=tuple(sorted(entries, key=lambda item: item.path)),
        unsupported=tuple(sorted(unsupported)),
    )


def _describe(
    relative: str, path: Path, platform: str, unsupported: list[str]
) -> TreeEntry | None:
    """Turn one filesystem entry into a manifest entry, or report it cannot be."""

    try:
        status = os.lstat(path)
    except OSError as error:
        raise InventoryError(f"could not read {relative}: {error}") from error

    if stat.S_ISLNK(status.st_mode):
        try:
            target = os.readlink(path)
        except OSError as error:
            raise InventoryError(f"could not read the link {relative}: {error}") from error
        return TreeEntry(path=relative, kind=KIND_SYMLINK, link_target=target,
                         component=component_for(relative))

    if getattr(status, "st_flags", 0):
        unsupported.append(relative)
        return None
    if stat.S_IMODE(status.st_mode) & UNSUPPORTED_MODE_BITS:
        unsupported.append(relative)
        return None

    mode = stat.S_IMODE(status.st_mode) if platform in POSIX_PLATFORMS else None
    xattrs, unreadable = read_material_xattrs(path, platform)
    if unreadable:
        unsupported.append(relative)
        return None

    if stat.S_ISDIR(status.st_mode):
        return TreeEntry(path=relative, kind=KIND_DIRECTORY, mode=mode, xattrs=xattrs,
                         component=component_for(relative))
    if stat.S_ISREG(status.st_mode):
        # Hashed by the caller, which is the step that reports progress.
        return TreeEntry(path=relative, kind=KIND_FILE, sha256=_UNREAD_DIGEST, size=0,
                         mode=mode, xattrs=xattrs, component=component_for(relative))

    unsupported.append(relative)
    return None


def _scandir(directory: Path) -> list[os.DirEntry[str]]:
    try:
        with os.scandir(directory) as scan:
            return list(scan)
    except OSError as error:
        raise InventoryError(f"could not read {directory}: {error}") from error


def _is_updater_own(relative: str) -> bool:
    """The one directory inside an installation that is never product."""

    return relative.split("/")[0] == WORKING_DIRECTORY_NAME


#: A placeholder digest for an entry the scan has found and not yet hashed. It
#: never reaches a manifest: the hashing pass replaces it for every file.
_UNREAD_DIGEST = "0" * 64


__all__ = [
    "UNSUPPORTED_MODE_BITS",
    "CancelHook",
    "InstalledTree",
    "InventoryCancelled",
    "InventoryError",
    "InventoryProgress",
    "ProgressHook",
    "TreeComparison",
    "TreeInventory",
    "build_manifest",
    "compare_tree",
    "component_for",
    "file_digest",
    "read_installation",
    "list_xattr_names",
    "read_installed_manifest",
    "read_material_xattrs",
    "read_tree",
    "read_xattr",
    "write_xattr",
    "walk_installation",
    "write_installed_manifest",
]
