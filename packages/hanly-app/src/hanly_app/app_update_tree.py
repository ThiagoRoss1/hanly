"""Building the new installation beside the old one, on macOS and Linux.

Windows changes an installation file by file. POSIX does not: a whole candidate
is reconstructed in a private directory on the same volume, proved to be
exactly the published build, and only then swapped in. Two renames are cheaper
to undo than forty, a rejected candidate is one directory to throw away, and
macOS gets the one thing it cannot do any other way - a bundle whose signature
material is reproduced rather than regenerated.

Most of a candidate is not downloaded. Every file the installation already
holds with the right content is copied across from it, which is what makes an
update the size of what changed. "Reused" means copied here, not left alone:
the candidate is a real second copy, and saying otherwise would misdescribe
both the disk it needs and the time it takes.

Nothing in this module touches the installation. It reads from it and writes
into a directory it created, and the swap belongs to the native helper.
"""

from __future__ import annotations

import base64
import hashlib
import os
import shutil
import stat
import tarfile
import zipfile
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from .app_inventory import (
    InventoryError,
    TreeComparison,
    compare_tree,
    read_tree,
    write_xattr,
)
from .app_manifest import (
    MAX_MANIFEST_ENTRIES,
    POSIX_PLATFORMS,
    ManifestError,
    TreeEntry,
    TreeManifest,
    require_tree_path,
)

#: What the private transaction directory holds while an update is in flight.
CANDIDATE_NAME = "candidate"
PREVIOUS_NAME = "previous"
REJECTED_NAME = "rejected"

#: The largest product this build will extract, and the most entries it will
#: read out of one archive. Both are checked while reading.
MAX_PRODUCT_BYTES = 8 * 1024 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = MAX_MANIFEST_ENTRIES

#: One read while copying or extracting, which is also the hashing block size.
_READ_BYTES = 1024 * 1024

#: Permissions a directory is created with before its manifest mode is applied.
#: Restrictive on the way in: nothing else may read a half-built candidate.
_WORKING_MODE = 0o700

ProgressHook = Callable[[str, int, int], None]
CancelHook = Callable[[], bool]


class CandidateError(RuntimeError):
    """Raised when a candidate installation cannot be built or trusted."""


class CandidateCancelled(CandidateError):
    """Raised when the caller asked to stop before the candidate was finished."""


@dataclass(frozen=True, slots=True)
class BuiltCandidate:
    """One finished candidate, and what building it actually cost."""

    root: Path
    manifest: TreeManifest
    preserved: tuple[str, ...] = ()
    reused_bytes: int = 0
    payload_bytes: int = 0
    preserved_bytes: int = 0

    @property
    def total_bytes(self) -> int:
        return self.reused_bytes + self.payload_bytes + self.preserved_bytes


def assemble_candidate(
    destination: Path,
    manifest: TreeManifest,
    *,
    source_root: Path,
    reusable: Iterable[str],
    payload: Path | None = None,
    on_progress: ProgressHook | None = None,
    should_cancel: CancelHook | None = None,
) -> BuiltCandidate:
    """Reconstruct one published build from local content plus changed bytes.

    Entries are created in manifest order with directories first and links
    last, because a link can only be made once what it points at exists. Every
    file is hashed as it is written, whether it came from the payload or from
    the installation: a file that was correct when the plan was made and has
    changed since is not one to copy into the new build.
    """

    _require_posix(manifest)
    root = _open_candidate(destination)
    reuse = set(reusable)
    members = _delta_members(payload) if payload is not None else {}

    directories = [entry for entry in manifest if entry.is_directory]
    files = [entry for entry in manifest if entry.is_file]
    links = [entry for entry in manifest if entry.is_symlink]

    for entry in sorted(directories, key=lambda item: item.path):
        _create_directory(root, entry)

    reused_bytes = 0
    payload_bytes = 0
    for done, entry in enumerate(sorted(files, key=lambda item: item.path), start=1):
        _require_active(should_cancel)
        if entry.path in reuse:
            _copy_from_installation(source_root, root, entry)
            reused_bytes += entry.byte_size
        else:
            _write_from_payload(payload, members, root, entry)
            payload_bytes += entry.byte_size
        _report(on_progress, "reconstructing", done, len(files))

    for entry in sorted(links, key=lambda item: item.path):
        _create_link(root, entry)

    return BuiltCandidate(
        root=root,
        manifest=manifest,
        reused_bytes=reused_bytes,
        payload_bytes=payload_bytes,
    )


def extract_full_product(
    destination: Path,
    archive: Path,
    manifest: TreeManifest,
    *,
    on_progress: ProgressHook | None = None,
    should_cancel: CancelHook | None = None,
) -> BuiltCandidate:
    """Unpack a whole published product straight into the candidate.

    Directly, rather than into a staging tree that is then copied: a second
    full copy of the product is a cost with nothing to show for it. What comes
    out is checked against the same manifest a reconstructed candidate is, by
    the same function, so the two paths cannot diverge.
    """

    _require_posix(manifest)
    root = _open_candidate(destination)
    prefix = manifest.layout.root
    if archive.name.endswith((".tar.gz", ".tgz")):
        _extract_tar(root, archive, prefix, on_progress, should_cancel)
    else:
        _extract_zip(root, archive, prefix, on_progress, should_cancel)
    _apply_manifest_metadata(root, manifest)
    return BuiltCandidate(root=root, manifest=manifest, payload_bytes=manifest.total_size)


def _apply_manifest_metadata(root: Path, manifest: TreeManifest) -> None:
    """Make an extracted tree carry the metadata the manifest describes.

    An archive records some of this and a candidate's own working directories
    record none of it, so both paths end by taking permissions and material
    attributes from the one place that is authoritative. That is also what lets
    a reconstructed candidate and an extracted one be checked by one function.
    """

    for entry in sorted(manifest.files, key=lambda item: item.path):
        _apply_metadata(_inside(root, entry.path), entry)
    directories = [entry for entry in manifest if entry.is_directory]
    # Deepest first: a directory made read-only before its children are set
    # would refuse the change to them.
    for entry in sorted(directories, key=lambda item: item.path.count("/"), reverse=True):
        _apply_metadata(_inside(root, entry.path), entry)


def verify_candidate(candidate: BuiltCandidate) -> TreeComparison:
    """Prove a candidate is exactly the build its manifest describes.

    Every entry, its kind, its mode, its link target, its material attributes
    and its bytes. Anything the manifest does not describe is an extra, and an
    extra is either something this update deliberately preserved or a reason
    not to install.
    """

    try:
        inventory = read_tree(candidate.root, candidate.manifest.platform)
    except InventoryError as error:
        raise CandidateError(f"could not read the new installation: {error}") from error
    if inventory.unsupported:
        raise CandidateError(
            f"the new installation carries {len(inventory.unsupported)} entries this update "
            f"cannot account for, starting with {inventory.unsupported[0]}"
        )

    comparison = compare_tree(inventory, candidate.manifest)
    unexpected = tuple(path for path in comparison.extra if path not in candidate.preserved)
    if comparison.missing or comparison.differing or unexpected:
        raise CandidateError(_mismatch(comparison, unexpected))
    return comparison


def copy_preserved(
    candidate: BuiltCandidate, source_root: Path, paths: Iterable[str]
) -> BuiltCandidate:
    """Carry a person's own files across into the new installation.

    They never become product content by surviving a swap: they are recorded
    separately, so the next update still reads them as somebody else's.
    """

    manifest = candidate.manifest
    copied: list[str] = []
    total = 0
    for relative in sorted(paths):
        if relative in manifest:
            raise CandidateError(f"{relative} is part of the new build, not an extra to keep")
        total += _copy_extra(source_root, candidate.root, relative)
        copied.append(relative)
    return BuiltCandidate(
        root=candidate.root,
        manifest=manifest,
        preserved=tuple(copied),
        reused_bytes=candidate.reused_bytes,
        payload_bytes=candidate.payload_bytes,
        preserved_bytes=total,
    )


def discard_candidate(root: Path) -> None:
    """Remove a candidate that will not be installed, whatever state it is in."""

    try:
        if root.is_dir() and not root.is_symlink():
            shutil.rmtree(root)
    except OSError:
        pass


def _open_candidate(destination: Path) -> Path:
    """Create the one directory this build is assembled in, and own it."""

    root = Path(destination)
    try:
        root.mkdir(parents=True, mode=_WORKING_MODE)
    except FileExistsError as error:
        raise CandidateError(f"{root} already exists") from error
    except OSError as error:
        raise CandidateError(f"could not create {root}: {error}") from error
    return root


def _create_directory(root: Path, entry: TreeEntry) -> None:
    path = _inside(root, entry.path)
    try:
        path.mkdir(parents=True, mode=_WORKING_MODE, exist_ok=True)
        _apply_metadata(path, entry)
    except OSError as error:
        raise CandidateError(f"could not create {entry.path}: {error}") from error


def _copy_from_installation(source_root: Path, root: Path, entry: TreeEntry) -> None:
    """Copy one file the installation already holds, hashing it on the way.

    The plan said this content was correct when it was read. Hashing it again
    while copying is what catches a file that changed in between, rather than
    building a candidate around it and failing the whole-tree check later with
    nothing to say about why.
    """

    source = _inside(Path(source_root), entry.path)
    if source.is_symlink() or not source.is_file():
        raise CandidateError(f"{entry.path} is no longer a file in this installation")
    try:
        digest, size = _copy_file(source, _inside(root, entry.path), entry)
    except CandidateError as error:
        # A local file that outgrew its entry did not arrive wrong; it changed.
        raise CandidateError(
            f"{entry.path} changed while the update was being prepared"
        ) from error
    if digest != entry.sha256 or size != entry.byte_size:
        raise CandidateError(f"{entry.path} changed while the update was being prepared")
    _apply_metadata(_inside(root, entry.path), entry)


def _write_from_payload(
    payload: Path | None,
    members: Mapping[str, zipfile.ZipInfo],
    root: Path,
    entry: TreeEntry,
) -> None:
    """Write one file the payload carries, refusing anything else it claims."""

    member = members.get(entry.path)
    if payload is None or member is None:
        raise CandidateError(f"the downloaded payload does not carry {entry.path}")
    destination = _inside(root, entry.path)
    try:
        with zipfile.ZipFile(payload) as archive, archive.open(member) as source:
            digest, size = _write_stream(source, destination, entry)
    except (OSError, zipfile.BadZipFile, RuntimeError) as error:
        raise CandidateError(f"could not unpack {entry.path}: {error}") from error
    if digest != entry.sha256 or size != entry.byte_size:
        raise CandidateError(f"the downloaded {entry.path} is not what the release describes")
    _apply_metadata(destination, entry)


def _create_link(root: Path, entry: TreeEntry) -> None:
    """Make one relative link, after everything it could point at exists."""

    path = _inside(root, entry.path)
    try:
        path.symlink_to(entry.link_target or "")
    except OSError as error:
        raise CandidateError(f"could not create the link {entry.path}: {error}") from error


def _apply_metadata(path: Path, entry: TreeEntry) -> None:
    """Set one entry's permission bits and its material attributes.

    Never through a link: a link has no mode of its own, and following one
    would change something outside the candidate.
    """

    if path.is_symlink():
        return
    try:
        if entry.mode is not None:
            os.chmod(path, entry.mode, follow_symlinks=False)
        for name, value in entry.xattrs.items():
            write_xattr(path, name, base64.b64decode(value))
    except OSError as error:
        raise CandidateError(f"could not set what {entry.path} is: {error}") from error


def _copy_file(source: Path, destination: Path, entry: TreeEntry) -> tuple[str, int]:
    try:
        with source.open("rb") as stream:
            return _write_stream(stream, destination, entry)
    except OSError as error:
        raise CandidateError(f"could not copy {entry.path}: {error}") from error


def _write_stream(source: IO[bytes], destination: Path, entry: TreeEntry) -> tuple[str, int]:
    """Write one file, abandoning it the moment it outgrows what it may be."""

    hasher = hashlib.sha256()
    written = 0
    destination.parent.mkdir(parents=True, mode=_WORKING_MODE, exist_ok=True)
    with destination.open("wb") as output:
        while True:
            chunk = source.read(_READ_BYTES)
            if not chunk:
                break
            written += len(chunk)
            if written > entry.byte_size:
                raise CandidateError(f"{entry.path} is larger than the release describes")
            hasher.update(chunk)
            output.write(chunk)
    return hasher.hexdigest(), written


def _copy_extra(source_root: Path, root: Path, relative: str) -> int:
    """Copy one unmanaged entry across, keeping what it is and nothing more."""

    try:
        require_tree_path(relative, "linux")
    except ManifestError as error:
        raise CandidateError(f"{relative} is not a path this update can keep: {error}") from error

    source = _inside(Path(source_root), relative)
    destination = _inside(root, relative)
    try:
        status = os.lstat(source)
        destination.parent.mkdir(parents=True, mode=_WORKING_MODE, exist_ok=True)
        if stat.S_ISLNK(status.st_mode):
            destination.symlink_to(os.readlink(source))
            return 0
        if stat.S_ISDIR(status.st_mode):
            destination.mkdir(mode=stat.S_IMODE(status.st_mode), exist_ok=True)
            return 0
        if not stat.S_ISREG(status.st_mode):
            raise CandidateError(f"{relative} is not a file this update can keep")
        shutil.copyfile(source, destination)
        os.chmod(destination, stat.S_IMODE(status.st_mode), follow_symlinks=False)
    except OSError as error:
        raise CandidateError(f"could not keep {relative}: {error}") from error
    return status.st_size


def _delta_members(payload: Path) -> Mapping[str, zipfile.ZipInfo]:
    """Index a payload by the installed path each member belongs at."""

    found: dict[str, zipfile.ZipInfo] = {}
    expanded = 0
    try:
        with zipfile.ZipFile(payload) as archive:
            infos = archive.infolist()
    except (OSError, zipfile.BadZipFile) as error:
        raise CandidateError(f"the downloaded payload is unreadable: {error}") from error
    if len(infos) > MAX_ARCHIVE_ENTRIES:
        raise CandidateError("the downloaded payload carries more files than a build has")

    for member in infos:
        if member.is_dir():
            continue
        if (member.external_attr >> 16) & 0o170000 == 0o120000:
            raise CandidateError("the downloaded payload contains a link")
        expanded += member.file_size
        if expanded > MAX_PRODUCT_BYTES:
            raise CandidateError("the downloaded payload expands past what this build installs")
        relative = _member_path(member.filename, prefix=None)
        if relative is None:
            raise CandidateError(f"the downloaded payload names {member.filename!r}")
        if relative in found:
            raise CandidateError(f"the downloaded payload carries {relative} twice")
        found[relative] = member
    return found


def _extract_zip(
    root: Path,
    archive: Path,
    prefix: str,
    on_progress: ProgressHook | None,
    should_cancel: CancelHook | None,
) -> None:
    """Stream one product ZIP into the candidate, member by member."""

    try:
        with zipfile.ZipFile(archive) as payload:
            infos = payload.infolist()
            _require_archive_bounds(len(infos), sum(item.file_size for item in infos))
            for done, member in enumerate(infos, start=1):
                _require_active(should_cancel)
                relative = _member_path(member.filename, prefix=prefix)
                if relative is None:
                    continue
                if member.is_dir():
                    _inside(root, relative).mkdir(parents=True, mode=_WORKING_MODE, exist_ok=True)
                    continue
                _extract_zip_member(payload, member, root, relative)
                _report(on_progress, "reconstructing", done, len(infos))
    except (OSError, zipfile.BadZipFile, RuntimeError) as error:
        raise CandidateError(f"the downloaded product is unreadable: {error}") from error


def _extract_zip_member(
    payload: zipfile.ZipFile, member: zipfile.ZipInfo, root: Path, relative: str
) -> None:
    destination = _inside(root, relative)
    destination.parent.mkdir(parents=True, mode=_WORKING_MODE, exist_ok=True)
    mode = (member.external_attr >> 16) & 0o170000
    if mode == 0o120000:
        payload_target = payload.read(member).decode("utf-8", "replace")
        destination.symlink_to(payload_target)
        return
    with payload.open(member) as source, destination.open("wb") as output:
        remaining = member.file_size
        while remaining > 0:
            chunk = source.read(min(_READ_BYTES, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            output.write(chunk)
    permissions = (member.external_attr >> 16) & 0o777
    if permissions:
        os.chmod(destination, permissions, follow_symlinks=False)


def _extract_tar(
    root: Path,
    archive: Path,
    prefix: str,
    on_progress: ProgressHook | None,
    should_cancel: CancelHook | None,
) -> None:
    """Stream one product tarball into the candidate, member by member.

    ``getmembers`` is deliberately not called: it reads the whole index of an
    archive of unknown size into memory before anything has been checked.
    """

    entries = 0
    expanded = 0
    try:
        with tarfile.open(archive, "r:gz") as payload:
            for member in payload:
                _require_active(should_cancel)
                entries += 1
                expanded += max(0, member.size)
                _require_archive_bounds(entries, expanded)
                relative = _member_path(member.name, prefix=prefix)
                if relative is None:
                    continue
                _extract_tar_member(payload, member, root, relative)
                _report(on_progress, "reconstructing", entries, 0)
    except tarfile.TarError as error:
        raise CandidateError(f"the downloaded product is unreadable: {error}") from error
    except OSError as error:
        raise CandidateError(f"could not unpack the downloaded product: {error}") from error


def _extract_tar_member(
    payload: tarfile.TarFile, member: tarfile.TarInfo, root: Path, relative: str
) -> None:
    destination = _inside(root, relative)
    if member.isdir():
        destination.mkdir(parents=True, mode=_WORKING_MODE, exist_ok=True)
        return
    destination.parent.mkdir(parents=True, mode=_WORKING_MODE, exist_ok=True)
    if member.issym():
        destination.symlink_to(member.linkname)
        return
    if not member.isfile():
        raise CandidateError(f"the downloaded product carries {relative}, which is not a file")
    source = payload.extractfile(member)
    if source is None:
        raise CandidateError(f"the downloaded product carries no content for {relative}")
    with source, destination.open("wb") as output:
        shutil.copyfileobj(source, output, _READ_BYTES)
    os.chmod(destination, member.mode & 0o777, follow_symlinks=False)


def _member_path(name: str, *, prefix: str | None) -> str | None:
    """Turn one archive member name into the path it belongs at, or refuse it.

    A product archive nests everything under its own root, which is stripped; a
    delta payload carries bare installed paths. A member outside the expected
    root is ignored rather than written, because a full archive legitimately
    carries things a candidate does not (a sidecar directory, a manifest a
    different generation reads).
    """

    cleaned = name.rstrip("/")
    if not cleaned:
        return None
    segments = cleaned.split("/")
    if prefix is not None:
        if segments[0] != prefix:
            return None
        segments = segments[1:]
        if not segments:
            return None
    relative = "/".join(segments)
    try:
        require_tree_path(relative, "linux")
    except ManifestError:
        return None
    return relative


def _inside(root: Path, relative: str) -> Path:
    """Join a manifest path to the candidate, refusing anything that leaves it.

    Checked again here rather than trusted from the manifest: between the
    manifest being read and this write, the only thing that has not changed is
    the text of the path.
    """

    path = Path(root)
    for segment in relative.split("/"):
        if segment in ("", ".", ".."):
            raise CandidateError(f"{relative} does not stay inside the new installation")
        path = path / segment
        if path.is_symlink():
            raise CandidateError(f"{relative} passes through a link")
    return path


def _require_archive_bounds(entries: int, expanded: int) -> None:
    if entries > MAX_ARCHIVE_ENTRIES:
        raise CandidateError("the downloaded product lists more files than a build has")
    if expanded > MAX_PRODUCT_BYTES:
        raise CandidateError("the downloaded product expands past what this build installs")


def _require_posix(manifest: TreeManifest) -> None:
    if manifest.platform not in POSIX_PLATFORMS:
        raise CandidateError(f"{manifest.platform} does not install by replacing a whole tree")


def _require_active(should_cancel: CancelHook | None) -> None:
    if should_cancel is not None and should_cancel():
        raise CandidateCancelled("the update was cancelled before anything was installed")


def _mismatch(comparison: TreeComparison, unexpected: tuple[str, ...]) -> str:
    for label, paths in (
        ("is missing", comparison.missing),
        ("does not match the release in", comparison.differing),
        ("carries an unexpected", unexpected),
    ):
        if paths:
            return f"the new installation {label} {paths[0]} and {len(paths) - 1} other entries"
    return "the new installation does not match the release"


def _report(hook: ProgressHook | None, phase: str, completed: int, total: int) -> None:
    if hook is not None:
        hook(phase, completed, total)


__all__ = [
    "CANDIDATE_NAME",
    "MAX_ARCHIVE_ENTRIES",
    "MAX_PRODUCT_BYTES",
    "PREVIOUS_NAME",
    "REJECTED_NAME",
    "BuiltCandidate",
    "CandidateCancelled",
    "CandidateError",
    "assemble_candidate",
    "copy_preserved",
    "discard_candidate",
    "extract_full_product",
    "verify_candidate",
]
