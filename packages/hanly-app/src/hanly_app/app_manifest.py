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

Nothing here reads a release or touches an installation. It is the vocabulary
the producer in ``tools/`` and the installer in :mod:`hanly_app.app_update`
both speak, and the only place their agreement is defined.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
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


__all__ = [
    "INSTALLED_MANIFEST_NAME",
    "MANIFEST_ASSET",
    "RESERVED_NAMES",
    "SCHEMA_VERSION",
    "UPDATE_METADATA_ASSET",
    "WORKING_DIRECTORY_NAME",
    "AssetReference",
    "BuildIdentity",
    "DeltaDescriptor",
    "FileEntry",
    "InstallManifest",
    "ManifestError",
    "UpdateMetadata",
    "content_fingerprint",
    "delta_asset_name",
    "parse_checksums",
    "require_safe_relative_path",
]
