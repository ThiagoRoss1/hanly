"""Reading an installed tree into the inventory the manifest describes.

The producer hashes a freshly frozen build to publish its manifest; the client
hashes the installation it is about to change to find out what actually differs
from it. Both are the same walk, so both are here.

The walk is deliberately one sequential worker. Hashing a gigabyte across a
thread pool turns a disk into the bottleneck for everything else on the machine
and finishes no sooner, and this runs while the user is waiting with the
application still open.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .app_manifest import (
    INSTALLED_MANIFEST_NAME,
    RESERVED_NAMES,
    BuildIdentity,
    FileEntry,
    InstallManifest,
    ManifestError,
    require_safe_relative_path,
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


__all__ = [
    "CancelHook",
    "InstalledTree",
    "InventoryCancelled",
    "InventoryError",
    "InventoryProgress",
    "ProgressHook",
    "build_manifest",
    "component_for",
    "file_digest",
    "read_installation",
    "read_installed_manifest",
    "walk_installation",
    "write_installed_manifest",
]
