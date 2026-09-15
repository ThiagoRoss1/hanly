"""What one installed Hanly build is made of, and what a release offers.

An application update used to need nothing but an archive name: the whole
bundle was downloaded and the whole directory replaced. Replacing only the
files that differ needs the release to say which files there are, so this
module defines that inventory and the release metadata pointing at it.

Three documents, one schema version, all produced from the final frozen tree:

``InstallManifest``
    every managed file in a build, with its digest, size, and component label.
``UpdateMetadata``
    what a client should download - the full archive always, and a delta from
    one named previous build when one was produced.
``FileEntry``
    the unit both are made of.

Schema 2 adds the vocabulary the other two platforms need. A macOS bundle and
a Linux onedir are trees rather than lists of regular files, so ``TreeManifest``
names every directory, permission bit, and relative link as well, and
``TreeLayout`` says what the root is called. V1 is frozen exactly as it is: old
Windows clients still read documents in that shape, and this module keeps
producing them.

Nothing here reads a release or touches an installation. It is the vocabulary
the producer in ``tools/`` and the installer in :mod:`hanly_app.app_update`
both speak, and the only place their agreement is defined.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Any

#: Incremented when a field's meaning changes. A client refuses a document it
#: does not recognize rather than guessing at the difference.
SCHEMA_VERSION = 1

#: Excluded from the inventory by name: an installation updated once carries
#: this, and a manifest generated from it would adopt the leftovers as product.
WORKING_DIRECTORY_NAME = ".hanly-update"

#: The installed manifest, written into the build so a client can read what it
#: currently has without asking the network.
INSTALLED_MANIFEST_NAME = ".hanly-manifest.json"

#: Names inside an installation that are the updater's, never the product's.
RESERVED_NAMES = frozenset({WORKING_DIRECTORY_NAME, INSTALLED_MANIFEST_NAME})

#: Release asset names. The full archive keeps the name older clients already
#: look for; everything else is new and additive.
MANIFEST_ASSET = "hanly-desktop-windows.manifest.json"
UPDATE_METADATA_ASSET = "hanly-desktop-windows.update.json"

#: A manifest entry map with nothing in it, usable as a frozen default.
_EMPTY_XATTRS: Mapping[str, str] = MappingProxyType({})

#: The most entries either schema reads out of one document. A build is a few
#: thousand files; anything past this is not one to hold in memory and index.
MAX_MANIFEST_ENTRIES = 100_000

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_VERSION = re.compile(r"^\d+\.\d+\.\d+$")
_BUILD_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_LABEL = re.compile(r"^[A-Za-z0-9._+-]{1,64}$")
_CHECKSUM_LINE = re.compile(r"^([0-9a-f]{64})\s+\*?(\S+)$")

#: Device names MS-DOS still reserves, with or without an extension.
_RESERVED_STEMS = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{digit}" for digit in "123456789"}
    | {f"lpt{digit}" for digit in "123456789"}
)


class ManifestError(ValueError):
    """Raised when an inventory or its release metadata is not usable."""


def parse_checksums(text: str) -> dict[str, str]:
    """Return ``asset name -> sha256`` from a ``sha256sum`` output file."""

    digests: dict[str, str] = {}
    for line in text.splitlines():
        match = _CHECKSUM_LINE.match(line.strip())
        if match is not None:
            digests[match.group(2)] = match.group(1)
    return digests


def content_fingerprint(entries: Iterable[FileEntry]) -> str:
    """A short, stable name for exactly this set of file contents.

    This is what becomes a build id, so it is taken over paths and digests
    alone: including the identity that carries it would be circular, and
    including sizes would add nothing a digest does not already fix.
    """

    hasher = hashlib.sha256()
    for entry in sorted(entries, key=lambda item: item.path):
        hasher.update(entry.path.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(entry.sha256.encode("ascii"))
        hasher.update(b"\n")
    return hasher.hexdigest()[:16]


def delta_asset_name(base_version: str, target_version: str) -> str:
    """Name the one delta a release publishes, from its two endpoints."""

    return f"hanly-desktop-windows-from-{base_version}-to-{target_version}.delta.zip"


@dataclass(frozen=True, slots=True)
class BuildIdentity:
    """Which build a document describes.

    Version alone is not identity. Two builds of one tag differ in content, and
    a delta assembled against the wrong one produces a tree that passes every
    per-file digest check and is still not the published build, so every
    document carries the build fingerprint the release was cut from.
    """

    product: str
    platform: str
    architecture: str
    version: str
    build_id: str

    def __post_init__(self) -> None:
        for field_name in ("product", "platform", "architecture"):
            value = getattr(self, field_name)
            if not _LABEL.match(value):
                raise ManifestError(f"build {field_name} {value!r} is not a plain label")
        if not _VERSION.match(self.version):
            raise ManifestError(f"build version {self.version!r} is not MAJOR.MINOR.PATCH")
        if not _BUILD_ID.match(self.build_id):
            raise ManifestError(f"build id {self.build_id!r} is not a plain identifier")

    def to_dict(self) -> dict[str, str]:
        return {
            "product": self.product,
            "platform": self.platform,
            "architecture": self.architecture,
            "version": self.version,
            "build_id": self.build_id,
        }

    @classmethod
    def from_payload(cls, payload: Any) -> BuildIdentity:
        mapping = _require_mapping(payload, "build identity")
        return cls(
            product=_require_text(mapping, "product"),
            platform=_require_text(mapping, "platform"),
            architecture=_require_text(mapping, "architecture"),
            version=_require_text(mapping, "version"),
            build_id=_require_text(mapping, "build_id"),
        )


@dataclass(frozen=True, slots=True)
class FileEntry:
    """One managed file: where it goes, what it must contain, how big it is."""

    path: str
    sha256: str
    size: int
    component: str = "application"

    def __post_init__(self) -> None:
        require_safe_relative_path(self.path)
        if not _SHA256.match(self.sha256):
            raise ManifestError(f"{self.path} has no SHA-256 digest")
        if isinstance(self.size, bool) or not isinstance(self.size, int) or self.size < 0:
            raise ManifestError(f"{self.path} has no usable size")
        if not _LABEL.match(self.component):
            raise ManifestError(f"{self.path} has no usable component label")

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "size": self.size,
            "component": self.component,
        }

    @classmethod
    def from_payload(cls, payload: Any) -> FileEntry:
        mapping = _require_mapping(payload, "file entry")
        size = mapping.get("size")
        if isinstance(size, bool) or not isinstance(size, int):
            raise ManifestError("file entry size must be an integer")
        return cls(
            path=_require_text(mapping, "path"),
            sha256=_require_text(mapping, "sha256").lower(),
            size=size,
            component=str(mapping.get("component") or "application"),
        )


@dataclass(frozen=True, slots=True)
class InstallManifest:
    """Every managed file in one build, indexed by its installed path."""

    identity: BuildIdentity
    entries: Mapping[str, FileEntry]

    def __post_init__(self) -> None:
        _require_no_case_collision(self.entries)
        _require_no_path_shadowing(self.entries)
        object.__setattr__(self, "entries", dict(sorted(self.entries.items())))

    def __iter__(self) -> Iterator[FileEntry]:
        return iter(self.entries.values())

    def __len__(self) -> int:
        return len(self.entries)

    def __contains__(self, path: object) -> bool:
        return path in self.entries

    def get(self, path: str) -> FileEntry | None:
        return self.entries.get(path)

    @property
    def total_size(self) -> int:
        return sum(entry.size for entry in self.entries.values())

    def digest(self) -> str:
        """A stable digest over the whole inventory, identity included.

        This is what binds a delta to the exact tree it was computed from. It
        is taken over the canonical serialization so producer and consumer
        cannot disagree about key order or spacing.
        """

        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "identity": self.identity.to_dict(),
            "files": [entry.to_dict() for entry in self.entries.values()],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_payload(cls, payload: Any) -> InstallManifest:
        mapping = _require_mapping(payload, "manifest")
        _require_schema_version(mapping, "manifest")
        files = mapping.get("files")
        if not isinstance(files, (list, tuple)):
            raise ManifestError("manifest files must be a list")
        entries: dict[str, FileEntry] = {}
        for item in files:
            entry = FileEntry.from_payload(item)
            if entry.path in entries:
                raise ManifestError(f"manifest lists {entry.path} twice")
            entries[entry.path] = entry
        if not entries:
            raise ManifestError("manifest lists no files")
        return cls(identity=BuildIdentity.from_payload(mapping.get("identity")), entries=entries)

    @classmethod
    def from_json(cls, text: str) -> InstallManifest:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as error:
            raise ManifestError(f"manifest is not readable JSON: {error}") from error
        return cls.from_payload(payload)

    @classmethod
    def from_entries(cls, identity: BuildIdentity, entries: Iterable[FileEntry]) -> InstallManifest:
        indexed: dict[str, FileEntry] = {}
        for entry in entries:
            if entry.path in indexed:
                raise ManifestError(f"manifest lists {entry.path} twice")
            indexed[entry.path] = entry
        return cls(identity=identity, entries=indexed)


@dataclass(frozen=True, slots=True)
class AssetReference:
    """One release asset a client may download, and how to know it is intact."""

    name: str
    size: int
    sha256: str

    def __post_init__(self) -> None:
        if not self.name or "/" in self.name or "\\" in self.name:
            raise ManifestError(f"asset name {self.name!r} is not a plain release asset")
        if isinstance(self.size, bool) or not isinstance(self.size, int) or self.size <= 0:
            raise ManifestError(f"asset {self.name} has no usable size")
        if not _SHA256.match(self.sha256):
            raise ManifestError(f"asset {self.name} has no SHA-256 digest")

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "size": self.size, "sha256": self.sha256}

    @classmethod
    def from_payload(cls, payload: Any) -> AssetReference:
        mapping = _require_mapping(payload, "asset reference")
        size = mapping.get("size")
        if isinstance(size, bool) or not isinstance(size, int):
            raise ManifestError("asset size must be an integer")
        return cls(
            name=_require_text(mapping, "name"),
            size=size,
            sha256=_require_text(mapping, "sha256").lower(),
        )


@dataclass(frozen=True, slots=True)
class DeltaDescriptor:
    """The one differential payload a release offers, and what it assumes.

    ``deletions`` is explicit rather than derived. A client that inferred it
    from "every installed path missing from the target" would delete files it
    does not own the moment an installation carries anything the manifest never
    described.
    """

    base_version: str
    base_build_id: str
    base_manifest_digest: str
    payload: AssetReference
    deletions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not _VERSION.match(self.base_version):
            raise ManifestError(f"delta base version {self.base_version!r} is not a version")
        if not _BUILD_ID.match(self.base_build_id):
            raise ManifestError("delta base build id is not a plain identifier")
        if not _SHA256.match(self.base_manifest_digest):
            raise ManifestError("delta base manifest digest is not a SHA-256 digest")
        for path in self.deletions:
            require_safe_relative_path(path)
        object.__setattr__(self, "deletions", tuple(sorted(set(self.deletions))))

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_version": self.base_version,
            "base_build_id": self.base_build_id,
            "base_manifest_digest": self.base_manifest_digest,
            "payload": self.payload.to_dict(),
            "deletions": list(self.deletions),
        }

    @classmethod
    def from_payload(cls, payload: Any) -> DeltaDescriptor:
        mapping = _require_mapping(payload, "delta")
        deletions = mapping.get("deletions", [])
        if not isinstance(deletions, (list, tuple)):
            raise ManifestError("delta deletions must be a list")
        return cls(
            base_version=_require_text(mapping, "base_version"),
            base_build_id=_require_text(mapping, "base_build_id"),
            base_manifest_digest=_require_text(mapping, "base_manifest_digest").lower(),
            payload=AssetReference.from_payload(mapping.get("payload")),
            deletions=tuple(str(item) for item in deletions),
        )


@dataclass(frozen=True, slots=True)
class UpdateMetadata:
    """What one release offers a client that can install differentially.

    The full archive is always present. The delta is optional, because the
    first manifest-aware release has no predecessor to diff against and a
    rebuilt or missing previous artifact is a reason to publish without one,
    never a reason to hold up the release.
    """

    identity: BuildIdentity
    manifest_digest: str
    manifest: AssetReference
    full: AssetReference
    delta: DeltaDescriptor | None = None
    #: Why no delta was produced. Display and diagnostics only.
    delta_omitted_reason: str = ""

    def __post_init__(self) -> None:
        if not _SHA256.match(self.manifest_digest):
            raise ManifestError("manifest digest is not a SHA-256 digest")

    def delta_for(self, base: BuildIdentity, base_manifest_digest: str) -> DeltaDescriptor | None:
        """Return the delta only when it was computed from exactly this build."""

        delta = self.delta
        if delta is None:
            return None
        matches = (
            delta.base_version == base.version
            and delta.base_build_id == base.build_id
            and delta.base_manifest_digest == base_manifest_digest
        )
        return delta if matches else None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "identity": self.identity.to_dict(),
            "manifest_digest": self.manifest_digest,
            "manifest": self.manifest.to_dict(),
            "full": self.full.to_dict(),
        }
        if self.delta is not None:
            payload["delta"] = self.delta.to_dict()
        elif self.delta_omitted_reason:
            payload["delta_omitted_reason"] = self.delta_omitted_reason
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, indent=2) + "\n"

    @classmethod
    def from_payload(cls, payload: Any) -> UpdateMetadata:
        mapping = _require_mapping(payload, "update metadata")
        _require_schema_version(mapping, "update metadata")
        raw_delta = mapping.get("delta")
        return cls(
            identity=BuildIdentity.from_payload(mapping.get("identity")),
            manifest_digest=_require_text(mapping, "manifest_digest").lower(),
            manifest=AssetReference.from_payload(mapping.get("manifest")),
            full=AssetReference.from_payload(mapping.get("full")),
            delta=None if raw_delta is None else DeltaDescriptor.from_payload(raw_delta),
            delta_omitted_reason=str(mapping.get("delta_omitted_reason") or ""),
        )

    @classmethod
    def from_json(cls, text: str) -> UpdateMetadata:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as error:
            raise ManifestError(f"update metadata is not readable JSON: {error}") from error
        return cls.from_payload(payload)


def require_safe_relative_path(path: str) -> PurePosixPath:
    """Accept only a path that can be joined to an installation root safely.

    Everything refused here is refused before any file is opened. The write
    boundary checks containment again against the resolved root, because a
    textual check cannot see a reparse point that appeared in between.
    """

    if not path or path != path.strip():
        raise ManifestError(f"{path!r} is not a usable relative path")
    if "\\" in path or ":" in path:
        raise ManifestError(f"{path!r} is not a plain forward-slash relative path")
    if path.startswith("/"):
        raise ManifestError(f"{path!r} is absolute")

    parts = PurePosixPath(path).parts
    if not parts:
        raise ManifestError(f"{path!r} names nothing")
    for part in parts:
        if part in ("", ".", ".."):
            raise ManifestError(f"{path!r} does not stay inside the installation")
        if part != part.strip() or part.endswith("."):
            # Windows silently strips these, so two distinct manifest paths
            # would land on one file.
            raise ManifestError(f"{path!r} has a segment Windows would rewrite")
        if part.split(".")[0].lower() in _RESERVED_STEMS:
            raise ManifestError(f"{path!r} uses a reserved device name")
    if parts[0] in RESERVED_NAMES:
        raise ManifestError(f"{path!r} is inside the updater's own working area")
    return PurePosixPath(path)


def _require_mapping(payload: Any, what: str) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise ManifestError(f"{what} must be a JSON object")
    return payload


def _require_text(mapping: Mapping[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{key} must be a non-empty string")
    return value


def _require_schema_version(mapping: Mapping[str, Any], what: str) -> None:
    version = mapping.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ManifestError(
            f"{what} declares schema version {version!r}; this build reads {SCHEMA_VERSION}"
        )


def _require_no_case_collision(entries: Mapping[str, FileEntry]) -> None:
    """Two paths differing only in case are one file on Windows."""

    seen: dict[str, str] = {}
    for path in entries:
        folded = path.casefold()
        if folded in seen:
            raise ManifestError(f"{path} and {seen[folded]} differ only in case")
        seen[folded] = path


def _require_no_path_shadowing(entries: Mapping[str, FileEntry]) -> None:
    """A file cannot also be some other file's parent directory."""

    directories = {
        str(parent).casefold()
        for path in entries
        for parent in PurePosixPath(path).parents
        if str(parent) != "."
    }
    for path in entries:
        if path.casefold() in directories:
            raise ManifestError(f"{path} is listed as both a file and a directory")


# --------------------------------------------------------------------------
# Schema 2: the whole tree, on every platform
#
# V1 describes a Windows list of regular files. A macOS bundle and a Linux
# onedir are not that: they carry empty directories, permission bits that
# decide whether the program can be executed at all, and hundreds of relative
# links between bundled libraries. A manifest that dropped any of those would
# describe a tree that cannot be reconstructed, so V2 names every entry and
# what makes it that entry.
# --------------------------------------------------------------------------

#: Incremented separately from V1: a build publishes both, and a client reads
#: whichever it understands.
TREE_SCHEMA_VERSION = 2

KIND_FILE = "file"
KIND_DIRECTORY = "directory"
KIND_SYMLINK = "symlink"
KINDS = frozenset({KIND_FILE, KIND_DIRECTORY, KIND_SYMLINK})

PLATFORM_WINDOWS = "windows"
PLATFORM_MACOS = "macos"
PLATFORM_LINUX = "linux"
PLATFORMS = frozenset({PLATFORM_WINDOWS, PLATFORM_MACOS, PLATFORM_LINUX})

#: Nothing is added here in this wave. An installation whose tuple is absent
#: from a release is told to download by hand rather than offered a payload
#: built for a different machine.
ARCHITECTURES = frozenset({"x86_64", "arm64"})

#: Platforms whose filesystems carry permission bits worth reproducing.
POSIX_PLATFORMS = frozenset({PLATFORM_MACOS, PLATFORM_LINUX})

#: Extended attributes that are part of what a file *is*: macOS keeps a
#: detached code signature in these, and a bundle reassembled without them no
#: longer verifies.
MATERIAL_XATTR_PREFIXES = ("com.apple.cs.",)

#: Extended attributes the machine attaches to a copy rather than the product:
#: where it was downloaded from, what Finder was told about it. They are
#: deliberately not part of identity, and never reproduced from a manifest.
PROVENANCE_XATTR_NAMES = frozenset(
    {
        "com.apple.quarantine",
        "com.apple.macl",
        "com.apple.provenance",
        "com.apple.lastuseddate#PS",
        "com.apple.TextEncoding",
    }
)
PROVENANCE_XATTR_PREFIXES = ("com.apple.metadata:",)

MATERIAL = "material"
PROVENANCE = "provenance"
UNSUPPORTED = "unsupported"

#: One attribute value, and every material attribute in one manifest. A
#: detached signature is a few kilobytes; anything past this is not something
#: to carry through an update.
MAX_XATTR_VALUE_BYTES = 64 * 1024
MAX_XATTR_MANIFEST_BYTES = 1024 * 1024

#: Only the permission bits. setuid, setgid, and the sticky bit are refused
#: rather than reproduced: a published desktop application needs none of them,
#: and an updater that could set them is a privilege escalation waiting to be
#: pointed at a hostile manifest.
_ALL_MODE_BITS = 0o7777
_FORBIDDEN_MODE_BITS = 0o7000

#: How many links one path may traverse before the graph is called a cycle.
_LINK_DEPTH = 40

_LINK_TARGET = 4096


def classify_xattr(name: str) -> str:
    """Say whether one extended attribute is product content, or the machine's.

    Anything in neither category is refused where it is found rather than
    dropped: silently discarding an attribute would publish a manifest that
    cannot reproduce the tree it claims to describe.
    """

    if name.startswith(MATERIAL_XATTR_PREFIXES):
        return MATERIAL
    if name in PROVENANCE_XATTR_NAMES or name.startswith(PROVENANCE_XATTR_PREFIXES):
        return PROVENANCE
    return UNSUPPORTED


@dataclass(frozen=True, slots=True)
class TreeLayout:
    """What the installation root is called, and what runs from inside it.

    The root is described here rather than as an entry so a manifest has no
    ambiguous ``.``: every entry path is unambiguously something beneath it.
    """

    root: str
    executable: str
    mode: int | None = None

    def __post_init__(self) -> None:
        if not self.root or "/" in self.root or self.root in (".", ".."):
            raise ManifestError(f"layout root {self.root!r} is not one directory name")
        if self.mode is not None:
            _require_mode(self.mode, "the installation root")

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"root": self.root, "executable": self.executable}
        if self.mode is not None:
            payload["mode"] = self.mode
        return payload

    @classmethod
    def from_payload(cls, payload: Any) -> TreeLayout:
        mapping = _require_mapping(payload, "layout")
        return cls(
            root=_require_text(mapping, "root"),
            executable=_require_text(mapping, "executable"),
            mode=_optional_mode(mapping.get("mode"), "the installation root"),
        )


@dataclass(frozen=True, slots=True)
class TreeEntry:
    """One thing inside an installation, and everything that makes it itself.

    Which fields carry meaning depends on ``kind``; the rest must be absent
    rather than null, so two manifests describing one tree serialize to one
    sequence of bytes.
    """

    path: str
    kind: str
    component: str = "application"
    sha256: str | None = None
    size: int | None = None
    mode: int | None = None
    link_target: str | None = None
    xattrs: Mapping[str, str] = _EMPTY_XATTRS

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ManifestError(f"{self.path}: {self.kind!r} is not a kind a manifest records")
        if not _LABEL.match(self.component):
            raise ManifestError(f"{self.path} has no usable component label")
        _require_kind_fields(self)
        if self.mode is not None:
            _require_mode(self.mode, self.path)
        object.__setattr__(self, "xattrs", dict(sorted(_checked_xattrs(self).items())))

    @property
    def is_file(self) -> bool:
        return self.kind == KIND_FILE

    @property
    def is_directory(self) -> bool:
        return self.kind == KIND_DIRECTORY

    @property
    def is_symlink(self) -> bool:
        return self.kind == KIND_SYMLINK

    @property
    def byte_size(self) -> int:
        return self.size or 0

    def same_content(self, other: TreeEntry) -> bool:
        """Whether two entries would produce the same thing on disk.

        Component labels are display, so they are left out: relabelling a file
        is not a reason to send its bytes again.
        """

        return (
            self.kind == other.kind
            and self.sha256 == other.sha256
            and self.size == other.size
            and self.mode == other.mode
            and self.link_target == other.link_target
            and dict(self.xattrs) == dict(other.xattrs)
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "path": self.path,
            "kind": self.kind,
            "component": self.component,
        }
        if self.sha256 is not None:
            payload["sha256"] = self.sha256
        if self.size is not None:
            payload["size"] = self.size
        if self.mode is not None:
            payload["mode"] = self.mode
        if self.link_target is not None:
            payload["link_target"] = self.link_target
        if self.xattrs:
            payload["xattrs"] = dict(self.xattrs)
        return payload

    @classmethod
    def from_payload(cls, payload: Any) -> TreeEntry:
        mapping = _require_mapping(payload, "tree entry")
        path = _require_text(mapping, "path")
        raw = mapping.get("xattrs")
        if raw is not None and not isinstance(raw, Mapping):
            raise ManifestError(f"{path} lists extended attributes that are not an object")
        return cls(
            path=path,
            kind=_require_text(mapping, "kind"),
            component=str(mapping.get("component") or "application"),
            sha256=_optional_digest(mapping.get("sha256"), path),
            size=_optional_size(mapping.get("size"), path),
            mode=_optional_mode(mapping.get("mode"), path),
            link_target=_optional_link_target(mapping.get("link_target"), path),
            xattrs={} if raw is None else {str(key): str(value) for key, value in raw.items()},
        )


@dataclass(frozen=True, slots=True)
class TreeManifest:
    """Every entry in one published build, on one platform.

    Construction is where a manifest is proved usable: paths that platform
    could not represent, links that leave the root, a case collision that would
    be one file after installation, all fail here rather than during an apply.
    """

    identity: BuildIdentity
    layout: TreeLayout
    entries: Mapping[str, TreeEntry]

    def __post_init__(self) -> None:
        platform = self.identity.platform
        if platform not in PLATFORMS:
            raise ManifestError(f"{platform!r} is not a platform this manifest describes")
        if self.identity.architecture not in ARCHITECTURES:
            raise ManifestError(
                f"{self.identity.architecture!r} is not an architecture this build knows"
            )
        if not self.entries:
            raise ManifestError("a tree manifest describes no entries")
        for path in self.entries:
            require_tree_path(path, platform)
        _require_declared_parents(self.entries)
        _require_no_alias(self.entries, platform)
        _require_links_contained(self.entries)
        _require_control_entries(self.entries, platform)
        _require_executable_present(self.entries, self.layout)
        _require_xattr_budget(self.entries)
        object.__setattr__(self, "entries", dict(sorted(self.entries.items())))

    def __iter__(self) -> Iterator[TreeEntry]:
        return iter(self.entries.values())

    def __len__(self) -> int:
        return len(self.entries)

    def __contains__(self, path: object) -> bool:
        return path in self.entries

    def get(self, path: str) -> TreeEntry | None:
        return self.entries.get(path)

    @property
    def platform(self) -> str:
        return self.identity.platform

    @property
    def files(self) -> tuple[TreeEntry, ...]:
        return tuple(item for item in self.entries.values() if item.is_file)

    @property
    def total_size(self) -> int:
        return sum(item.byte_size for item in self.entries.values())

    def digest(self) -> str:
        """The digest that, with the identity, names this exact build.

        Taken over the canonical bytes below so a producer and a client cannot
        disagree about key order, spacing, or which optional field was absent.
        """

        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": TREE_SCHEMA_VERSION,
            "identity": self.identity.to_dict(),
            "layout": self.layout.to_dict(),
            "entries": [self.entries[path].to_dict() for path in sorted(self.entries)],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_payload(cls, payload: Any) -> TreeManifest:
        mapping = _require_mapping(payload, "tree manifest")
        version = mapping.get("schema_version")
        if version != TREE_SCHEMA_VERSION:
            raise ManifestError(
                f"tree manifest declares schema version {version!r}; "
                f"this build reads {TREE_SCHEMA_VERSION}"
            )
        raw = mapping.get("entries")
        if not isinstance(raw, (list, tuple)):
            raise ManifestError("a tree manifest must list its entries")
        if len(raw) > MAX_MANIFEST_ENTRIES:
            raise ManifestError("the tree manifest lists more entries than a build may have")
        entries: dict[str, TreeEntry] = {}
        for item in raw:
            entry = TreeEntry.from_payload(item)
            if entry.path in entries:
                raise ManifestError(f"the tree manifest lists {entry.path} twice")
            entries[entry.path] = entry
        return cls(
            identity=BuildIdentity.from_payload(mapping.get("identity")),
            layout=TreeLayout.from_payload(mapping.get("layout")),
            entries=entries,
        )

    @classmethod
    def from_json(cls, text: str) -> TreeManifest:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as error:
            raise ManifestError(f"tree manifest is not readable JSON: {error}") from error
        return cls.from_payload(payload)

    @classmethod
    def from_entries(
        cls, identity: BuildIdentity, layout: TreeLayout, entries: Iterable[TreeEntry]
    ) -> TreeManifest:
        indexed: dict[str, TreeEntry] = {}
        for entry in entries:
            if entry.path in indexed:
                raise ManifestError(f"the tree manifest lists {entry.path} twice")
            indexed[entry.path] = entry
        return cls(identity=identity, layout=layout, entries=indexed)


@dataclass(frozen=True, slots=True)
class TreeDifference:
    """What changed between two published builds of one platform.

    ``payload_paths`` is the subset whose *bytes* have to travel. A file whose
    only change is its permission bits is in ``changed`` and not here: the
    manifest already says what the mode must become.
    """

    changed_paths: tuple[str, ...]
    deleted_paths: tuple[str, ...]
    payload_paths: tuple[str, ...]

    @property
    def is_empty(self) -> bool:
        return not (self.changed_paths or self.deleted_paths)


def tree_difference(base: TreeManifest, target: TreeManifest) -> TreeDifference:
    """Diff two manifests the one way producer and client both compute it.

    Both sides derive this rather than trusting a published list, so the lists
    a release advertises can be checked against it instead of believed.
    """

    changed: list[str] = []
    payload: list[str] = []
    for entry in target:
        previous = base.get(entry.path)
        if previous is not None and previous.same_content(entry):
            continue
        changed.append(entry.path)
        if entry.is_file and _needs_bytes(previous, entry):
            payload.append(entry.path)
    deleted = [entry.path for entry in base if entry.path not in target]
    return TreeDifference(
        changed_paths=tuple(sorted(changed)),
        deleted_paths=tuple(sorted(deleted)),
        payload_paths=tuple(sorted(payload)),
    )


def require_tree_path(path: str, platform: str) -> tuple[str, ...]:
    """Accept only a path that names something inside an installation root.

    Segments are split textually rather than through ``PurePosixPath``, which
    silently folds ``a//b`` and ``a/./b`` into ``a/b``: the two spellings would
    then be two manifest entries landing on one file.
    """

    if not path:
        raise ManifestError("an entry path must not be empty")
    if len(path.encode("utf-8")) > _LINK_TARGET:
        raise ManifestError(f"{path!r} is longer than a path this updater carries")
    if path.startswith("/") or "\\" in path:
        raise ManifestError(f"{path!r} is not a plain forward-slash relative path")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in path):
        raise ManifestError(f"{path!r} contains a control character")

    segments = tuple(path.split("/"))
    for segment in segments:
        if segment in ("", ".", ".."):
            raise ManifestError(f"{path!r} does not stay inside the installation")
    if segments[0] == WORKING_DIRECTORY_NAME:
        raise ManifestError(f"{path!r} is inside the updater's own working area")
    if platform == PLATFORM_WINDOWS:
        _require_windows_segments(path, segments)
    return segments


def _require_windows_segments(path: str, segments: tuple[str, ...]) -> None:
    """The rules Windows enforces by rewriting a name rather than refusing it."""

    for segment in segments:
        if ":" in segment:
            raise ManifestError(f"{path!r} names a drive or an alternate data stream")
        if segment != segment.rstrip(" .") or segment != segment.strip():
            raise ManifestError(f"{path!r} has a segment Windows would rewrite")
        if segment.split(".")[0].lower() in _RESERVED_STEMS:
            raise ManifestError(f"{path!r} uses a reserved device name")


def _require_kind_fields(entry: TreeEntry) -> None:
    """Each kind carries exactly its own fields, and none of another's."""

    if entry.kind == KIND_FILE:
        if entry.sha256 is None or entry.size is None:
            raise ManifestError(f"{entry.path} is a file with no digest and size")
        if entry.link_target is not None:
            raise ManifestError(f"{entry.path} is a file with a link target")
        return
    if entry.sha256 is not None or entry.size is not None:
        raise ManifestError(f"{entry.path} is not a file and carries file content")
    if entry.kind == KIND_SYMLINK:
        if not entry.link_target:
            raise ManifestError(f"{entry.path} is a link with no target")
        if entry.mode is not None:
            # Permissions follow the link on every platform Hanly supports, so
            # recording one would describe a change no apply step can make.
            raise ManifestError(f"{entry.path} is a link with permission bits")
        if entry.xattrs:
            raise ManifestError(f"{entry.path} is a link with extended attributes")
    elif entry.link_target is not None:
        raise ManifestError(f"{entry.path} is a directory with a link target")


def _checked_xattrs(entry: TreeEntry) -> Mapping[str, str]:
    """Prove every recorded attribute is material, bounded, and real base64."""

    checked: dict[str, str] = {}
    for name, value in entry.xattrs.items():
        if classify_xattr(name) != MATERIAL:
            raise ManifestError(f"{entry.path} records {name}, which is not product content")
        try:
            decoded = base64.b64decode(value, validate=True)
        except (ValueError, binascii.Error) as error:
            raise ManifestError(f"{entry.path}: {name} is not base64: {error}") from error
        if len(decoded) > MAX_XATTR_VALUE_BYTES:
            raise ManifestError(f"{entry.path}: {name} is larger than a manifest carries")
        checked[name] = value
    return checked


def _require_xattr_budget(entries: Mapping[str, TreeEntry]) -> None:
    total = sum(
        len(value) for entry in entries.values() for value in entry.xattrs.values()
    )
    if total > MAX_XATTR_MANIFEST_BYTES:
        raise ManifestError("the manifest records more extended-attribute data than it may")


def _require_declared_parents(entries: Mapping[str, TreeEntry]) -> None:
    """Every entry's parents are declared directories, or it has none.

    This is also what keeps a material path from descending through a link:
    a parent that is a symlink is not a directory, and fails here.
    """

    for path in entries:
        segments = path.split("/")
        for depth in range(1, len(segments)):
            parent = "/".join(segments[:depth])
            declared = entries.get(parent)
            if declared is None:
                raise ManifestError(f"{path} sits under {parent}, which the manifest omits")
            if not declared.is_directory:
                raise ManifestError(f"{path} sits under {parent}, which is not a directory")


def _require_no_alias(entries: Mapping[str, TreeEntry], platform: str) -> None:
    """Refuse two paths one filesystem would treat as the same name.

    Linux keeps distinct case and distinct Unicode spellings, so only the
    platforms that fold them check. macOS folds both case and normalization,
    and is checked even for a case-sensitive volume: the published product has
    to install correctly on the default one.
    """

    if platform not in (PLATFORM_WINDOWS, PLATFORM_MACOS):
        return
    seen: dict[str, str] = {}
    for path in entries:
        folded = path.casefold()
        if platform == PLATFORM_MACOS:
            folded = unicodedata.normalize("NFC", folded)
        existing = seen.get(folded)
        if existing is not None:
            raise ManifestError(f"{path} and {existing} are one name on this platform")
        seen[folded] = path


def _require_links_contained(entries: Mapping[str, TreeEntry]) -> None:
    """Every link resolves to something this manifest describes, inside the root.

    Targets are resolved textually, because nothing exists on disk yet, and a
    segment that is itself a link is followed: a macOS framework reaches its
    binary through ``Versions/Current``, so a resolver that stopped at the
    first link would reject every bundle Hanly actually ships.
    """

    for entry in entries.values():
        if entry.is_symlink:
            _resolve_link(entries, entry)


def _resolve_link(entries: Mapping[str, TreeEntry], link: TreeEntry) -> str:
    """Follow one link to the real entry it names, or say why it does not."""

    resolved = link.path.split("/")[:-1]
    pending = _link_segments(link, link.link_target or "")
    budget = _LINK_DEPTH

    while pending:
        segment = pending.pop()
        if segment in ("", "."):
            continue
        if segment == "..":
            if not resolved:
                raise ManifestError(f"{link.path} points outside the installation")
            resolved.pop()
            continue

        resolved.append(segment)
        destination = entries.get("/".join(resolved))
        if destination is None:
            raise ManifestError(
                f"{link.path} points at {'/'.join(resolved)}, which is not in the build"
            )
        if destination.is_symlink:
            budget -= 1
            if budget < 0:
                raise ManifestError(f"{link.path} passes through too many links")
            resolved.pop()
            pending.extend(_link_segments(link, destination.link_target or ""))
        elif destination.is_file and pending:
            raise ManifestError(f"{link.path} points through {destination.path}, which is a file")

    if not resolved:
        raise ManifestError(f"{link.path} points at the installation root")
    return "/".join(resolved)


def _link_segments(link: TreeEntry, target: str) -> list[str]:
    """One link target as a stack of segments, innermost last."""

    if target.startswith("/") or "\\" in target:
        raise ManifestError(f"{link.path} points outside the installation")
    return list(reversed(target.split("/")))


def _require_control_entries(entries: Mapping[str, TreeEntry], platform: str) -> None:
    """The one updater-owned file a build may contain, and only where it belongs.

    Windows keeps writing the V1 inventory into the tree for the benefit of
    older clients, so V2 has to describe it. Admitting it as this one named
    control entry is not the same as relaxing the reserved-path rule.
    """

    entry = entries.get(INSTALLED_MANIFEST_NAME)
    if entry is not None and (platform != PLATFORM_WINDOWS or not entry.is_file):
        raise ManifestError(f"{INSTALLED_MANIFEST_NAME} is not a file this build publishes")
    for path in entries:
        if path.split("/")[-1] == INSTALLED_MANIFEST_NAME and path != INSTALLED_MANIFEST_NAME:
            raise ManifestError(f"{path} uses the updater's own control-file name")


def _require_executable_present(entries: Mapping[str, TreeEntry], layout: TreeLayout) -> None:
    entry = entries.get(layout.executable)
    if entry is None or not entry.is_file:
        raise ManifestError(f"the manifest has no executable at {layout.executable}")


def _require_mode(mode: int, what: str) -> None:
    if isinstance(mode, bool) or not isinstance(mode, int):
        raise ManifestError(f"{what} has permission bits that are not an integer")
    if mode < 0 or mode > _ALL_MODE_BITS:
        raise ManifestError(f"{what} has permission bits outside the range a manifest carries")
    if mode & _FORBIDDEN_MODE_BITS:
        raise ManifestError(f"{what} asks for setuid, setgid, or the sticky bit")


def _optional_mode(value: Any, what: str) -> int | None:
    if value is None:
        return None
    _require_mode(value, what)
    return int(value)


def _optional_size(value: Any, path: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ManifestError(f"{path} has no usable size")
    return value


def _optional_digest(value: Any, path: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not _SHA256.match(value.lower()):
        raise ManifestError(f"{path} has no SHA-256 digest")
    return value.lower()


def _optional_link_target(value: Any, path: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ManifestError(f"{path} has an unusable link target")
    if len(value.encode("utf-8")) > _LINK_TARGET:
        raise ManifestError(f"{path} has a link target longer than this updater carries")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        raise ManifestError(f"{path} has a link target containing a control character")
    return value


def _needs_bytes(previous: TreeEntry | None, entry: TreeEntry) -> bool:
    """Whether a changed file's content has to travel, rather than its mode."""

    return previous is None or not previous.is_file or previous.sha256 != entry.sha256


__all__ = [
    "ARCHITECTURES",
    "INSTALLED_MANIFEST_NAME",
    "KIND_DIRECTORY",
    "KIND_FILE",
    "KIND_SYMLINK",
    "KINDS",
    "MANIFEST_ASSET",
    "MATERIAL",
    "MAX_MANIFEST_ENTRIES",
    "MAX_XATTR_MANIFEST_BYTES",
    "MAX_XATTR_VALUE_BYTES",
    "PLATFORM_LINUX",
    "PLATFORM_MACOS",
    "PLATFORM_WINDOWS",
    "PLATFORMS",
    "POSIX_PLATFORMS",
    "PROVENANCE",
    "RESERVED_NAMES",
    "SCHEMA_VERSION",
    "TREE_SCHEMA_VERSION",
    "UNSUPPORTED",
    "UPDATE_METADATA_ASSET",
    "WORKING_DIRECTORY_NAME",
    "AssetReference",
    "BuildIdentity",
    "DeltaDescriptor",
    "FileEntry",
    "InstallManifest",
    "ManifestError",
    "TreeDifference",
    "TreeEntry",
    "TreeLayout",
    "TreeManifest",
    "UpdateMetadata",
    "classify_xattr",
    "content_fingerprint",
    "delta_asset_name",
    "parse_checksums",
    "require_safe_relative_path",
    "require_tree_path",
    "tree_difference",
]
