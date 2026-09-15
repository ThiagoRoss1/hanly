"""The one metadata package a release publishes for every platform at once.

``Hanly-vX.Y.Z.hup`` is a small ZIP holding an index and one tree manifest per
built platform, and no application bytes at all. A client downloads it, finds
the one entry that matches the build it is actually running, and learns from
that entry which release assets it may fetch and what the result has to look
like. Everything large stays a separate release asset, so nobody downloads
another platform's payload to read their own metadata.

Reading is deliberately hostile-input work: the file is fetched over the
network before anything about it is known, so every bound here is checked while
reading rather than after a decompression has already finished. Nothing in a
HUP is ever written to the filesystem - it is parsed in memory, within limits,
and the paths it contains are data the installer validates again.
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .app_manifest import (
    ARCHITECTURES,
    PLATFORMS,
    BuildIdentity,
    ManifestError,
    TreeManifest,
    require_tree_path,
)

#: The wire version of the whole container. A client refuses one it does not
#: recognize rather than reading the parts it happens to understand.
HUP_VERSION = 1

PRODUCT = "hanly-desktop"

INDEX_MEMBER = "index.json"
MANIFEST_DIRECTORY = "manifests"

#: What a full product is packaged as, per platform, and the one delta format.
FORMAT_ZIP = "zip"
FORMAT_DMG = "dmg"
FORMAT_TAR_GZ = "tar.gz"
FULL_FORMATS = frozenset({FORMAT_ZIP, FORMAT_DMG, FORMAT_TAR_GZ})
DELTA_FORMAT = "files-zip-v1"

#: macOS signing policy this wave publishes. Ad-hoc signatures are reproduced
#: byte for byte and never regenerated locally; the label exists so a later
#: policy is a value a client can refuse rather than a silent difference.
SIGNATURE_POLICY_ADHOC = "adhoc-v1"

#: Hard limits, shared by the producer and every client. They bound what is
#: read, not what a decompressor has already produced. Raising one needs
#: measured evidence from a real release, not a bigger build.
MAX_PACKAGE_BYTES = 16 * 1024 * 1024
MAX_EXPANDED_BYTES = 64 * 1024 * 1024
MAX_MEMBERS = 9
MAX_PLATFORMS = 8
MAX_INDEX_BYTES = 256 * 1024
MAX_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_JSON_DEPTH = 32
MAX_ASSET_NAME_BYTES = 256
MAX_PATH_BYTES = 4096

#: The compression a member may use. Anything else is a format this reader
#: would have to hand to another library to expand.
_ALLOWED_COMPRESSION = frozenset({zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED})

#: The end-of-central-directory record a ZIP64 archive carries. Nothing this
#: small needs one, so its presence means the file is not what it claims.
_ZIP64_SIGNATURE = b"PK\x06\x06"

_HEX = "0123456789abcdef"
_READ_BYTES = 256 * 1024


class HupError(RuntimeError):
    """Raised when an update package cannot be read or trusted."""


def package_asset_name(version: str) -> str:
    """The one name a release publishes its update package under."""

    return f"Hanly-v{version}.hup"


def manifest_member_name(platform: str, architecture: str) -> str:
    """Where one platform's tree manifest sits inside the package."""

    return f"{MANIFEST_DIRECTORY}/{platform}-{architecture}.json"


def delta_payload_name(
    platform: str, architecture: str, base_version: str, version: str
) -> str:
    """Name the one delta a release publishes for one platform tuple."""

    return (
        f"{PRODUCT}-{platform}-{architecture}"
        f"-from-{base_version}-to-{version}.delta.zip"
    )


@dataclass(frozen=True, slots=True)
class ReleaseIdentity:
    """Which release this package describes, in the three ways it is named."""

    tag: str
    version: str
    source_commit: str

    def __post_init__(self) -> None:
        if self.tag != f"v{self.version}":
            raise HupError(f"release tag {self.tag!r} does not name version {self.version!r}")
        if len(self.source_commit) != 40 or any(
            character not in _HEX for character in self.source_commit
        ):
            raise HupError("a release records the full commit it was built from")

    def to_dict(self) -> dict[str, Any]:
        return {"tag": self.tag, "version": self.version, "source_commit": self.source_commit}

    @classmethod
    def from_payload(cls, payload: Any) -> ReleaseIdentity:
        mapping = _mapping(payload, "release")
        return cls(
            tag=_text(mapping, "tag"),
            version=_text(mapping, "version"),
            source_commit=_text(mapping, "source_commit").lower(),
        )


@dataclass(frozen=True, slots=True)
class ReleaseAsset:
    """One file this release publishes, and how to know it is intact."""

    name: str
    size: int
    sha256: str
    format: str = ""

    def __post_init__(self) -> None:
        _require_asset_name(self.name)
        _require_size(self.size, self.name)
        _require_digest(self.sha256, self.name)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"name": self.name, "size": self.size, "sha256": self.sha256}
        if self.format:
            payload["format"] = self.format
        return payload

    @classmethod
    def from_payload(cls, payload: Any, what: str) -> ReleaseAsset:
        mapping = _mapping(payload, what)
        return cls(
            name=_text(mapping, "name"),
            size=_integer(mapping, "size"),
            sha256=_text(mapping, "sha256").lower(),
            format=str(mapping.get("format") or ""),
        )


@dataclass(frozen=True, slots=True)
class ManifestMember:
    """Where one platform's manifest sits in the package, and what it is."""

    member: str
    size: int
    sha256: str

    def __post_init__(self) -> None:
        _require_size(self.size, self.member)
        _require_digest(self.sha256, self.member)
        if self.size > MAX_MANIFEST_BYTES:
            raise HupError(f"{self.member} is larger than a manifest this build reads")

    def to_dict(self) -> dict[str, Any]:
        return {"member": self.member, "size": self.size, "sha256": self.sha256}

    @classmethod
    def from_payload(cls, payload: Any) -> ManifestMember:
        mapping = _mapping(payload, "manifest member")
        return cls(
            member=_text(mapping, "member"),
            size=_integer(mapping, "size"),
            sha256=_text(mapping, "sha256").lower(),
        )


@dataclass(frozen=True, slots=True)
class DeltaDescriptor:
    """The one direct delta a platform offers, and the build it starts from.

    ``changed_paths`` and ``deleted_paths`` are explicit coverage, checked
    against the diff of the two manifests rather than believed. They say what
    the payload accounts for; they are never authority to delete anything in a
    live installation.
    """

    base_identity: BuildIdentity
    base_manifest_sha256: str
    payload: ReleaseAsset
    changed_paths: tuple[str, ...] = ()
    deleted_paths: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_digest(self.base_manifest_sha256, "the delta base manifest")
        if self.payload.format != DELTA_FORMAT:
            raise HupError(f"{self.payload.name} is not a {DELTA_FORMAT} payload")
        for name, paths in (("changed", self.changed_paths), ("deleted", self.deleted_paths)):
            _require_sorted_paths(paths, self.base_identity.platform, name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_identity": self.base_identity.to_dict(),
            "base_manifest_sha256": self.base_manifest_sha256,
            "payload": self.payload.to_dict(),
            "changed_paths": list(self.changed_paths),
            "deleted_paths": list(self.deleted_paths),
        }

    @classmethod
    def from_payload(cls, payload: Any) -> DeltaDescriptor:
        mapping = _mapping(payload, "delta")
        return cls(
            base_identity=_identity(mapping.get("base_identity")),
            base_manifest_sha256=_text(mapping, "base_manifest_sha256").lower(),
            payload=ReleaseAsset.from_payload(mapping.get("payload"), "delta payload"),
            changed_paths=_paths(mapping.get("changed_paths"), "changed_paths"),
            deleted_paths=_paths(mapping.get("deleted_paths"), "deleted_paths"),
        )


@dataclass(frozen=True, slots=True)
class BundleDescriptor:
    """What a macOS client checks about the bundle it is about to assemble."""

    bundle_identifier: str
    signature_policy: str = SIGNATURE_POLICY_ADHOC

    def __post_init__(self) -> None:
        if not self.bundle_identifier:
            raise HupError("a macOS entry names the bundle identifier it publishes")
        if self.signature_policy != SIGNATURE_POLICY_ADHOC:
            raise HupError(
                f"signature policy {self.signature_policy!r} is not one this build installs"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle_identifier": self.bundle_identifier,
            "signature_policy": self.signature_policy,
        }

    @classmethod
    def from_payload(cls, payload: Any) -> BundleDescriptor:
        mapping = _mapping(payload, "macos entry")
        return cls(
            bundle_identifier=_text(mapping, "bundle_identifier"),
            signature_policy=str(mapping.get("signature_policy") or SIGNATURE_POLICY_ADHOC),
        )


@dataclass(frozen=True, slots=True)
class PlatformEntry:
    """Everything one OS and architecture is offered, and nothing else's."""

    identity: BuildIdentity
    manifest: ManifestMember
    full: ReleaseAsset
    layout_root: str
    layout_executable: str
    delta: DeltaDescriptor | None = None
    delta_omitted_reason: str = ""
    macos: BundleDescriptor | None = None

    def __post_init__(self) -> None:
        if self.platform not in PLATFORMS:
            raise HupError(f"{self.platform!r} is not a platform this build installs")
        if self.architecture not in ARCHITECTURES:
            raise HupError(f"{self.architecture!r} is not an architecture this build installs")
        if self.manifest.member != manifest_member_name(self.platform, self.architecture):
            raise HupError(f"{self.manifest.member} is not where this platform's manifest belongs")
        if self.full.format not in FULL_FORMATS:
            raise HupError(f"{self.full.name} is not a full product format this build reads")
        if (self.platform == "macos") != (self.macos is not None):
            raise HupError("only a macOS entry carries bundle information")
        if self.delta is not None:
            self._require_delta_matches()

    def _require_delta_matches(self) -> None:
        delta = self.delta
        assert delta is not None
        base = delta.base_identity
        if (base.product, base.platform, base.architecture) != (
            self.identity.product,
            self.platform,
            self.architecture,
        ):
            raise HupError("the delta starts from a build for a different product or machine")
        if base.version == self.identity.version:
            raise HupError("the delta starts from a build carrying this same version")

    @property
    def platform(self) -> str:
        return self.identity.platform

    @property
    def architecture(self) -> str:
        return self.identity.architecture

    @property
    def version(self) -> str:
        return self.identity.version

    @property
    def tuple_name(self) -> str:
        return f"{self.platform}-{self.architecture}"

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "platform": self.platform,
            "architecture": self.architecture,
            "identity": self.identity.to_dict(),
            "manifest": self.manifest.to_dict(),
            "full": self.full.to_dict(),
            "layout": {"root": self.layout_root, "executable": self.layout_executable},
            "delta": None if self.delta is None else self.delta.to_dict(),
        }
        if self.delta is None and self.delta_omitted_reason:
            payload["delta_omitted_reason"] = self.delta_omitted_reason
        if self.macos is not None:
            payload["macos"] = self.macos.to_dict()
        return payload

    @classmethod
    def from_payload(cls, payload: Any) -> PlatformEntry:
        mapping = _mapping(payload, "platform entry")
        layout = _mapping(mapping.get("layout"), "layout")
        raw_delta = mapping.get("delta")
        raw_macos = mapping.get("macos")
        entry = cls(
            identity=_identity(mapping.get("identity")),
            manifest=ManifestMember.from_payload(mapping.get("manifest")),
            full=ReleaseAsset.from_payload(mapping.get("full"), "full product"),
            layout_root=_text(layout, "root"),
            layout_executable=_text(layout, "executable"),
            delta=None if raw_delta is None else DeltaDescriptor.from_payload(raw_delta),
            delta_omitted_reason=_reason(mapping.get("delta_omitted_reason")),
            macos=None if raw_macos is None else BundleDescriptor.from_payload(raw_macos),
        )
        _require_declared_tuple(mapping, entry)
        return entry


@dataclass(frozen=True, slots=True)
class HupIndex:
    """The package's own table of contents, and the release it describes."""

    release: ReleaseIdentity
    platforms: tuple[PlatformEntry, ...]
    product: str = PRODUCT

    def __post_init__(self) -> None:
        if self.product != PRODUCT:
            raise HupError(f"{self.product!r} is not the product this build updates")
        if not self.platforms:
            raise HupError("the update package describes no platforms")
        if len(self.platforms) > MAX_PLATFORMS:
            raise HupError("the update package describes more platforms than it may")
        seen: set[str] = set()
        for entry in self.platforms:
            if entry.tuple_name in seen:
                raise HupError(f"the update package describes {entry.tuple_name} twice")
            seen.add(entry.tuple_name)
            if entry.identity.version != self.release.version:
                raise HupError(f"{entry.tuple_name} carries a version the release does not")
            if entry.identity.product != self.product:
                raise HupError(f"{entry.tuple_name} is not this product")

    def __iter__(self) -> Iterator[PlatformEntry]:
        return iter(self.platforms)

    @property
    def version(self) -> str:
        return self.release.version

    @property
    def members(self) -> tuple[str, ...]:
        return tuple(sorted(entry.manifest.member for entry in self.platforms))

    def entry_for(self, platform: str, architecture: str) -> PlatformEntry | None:
        """The one entry a machine may install, or None when there is none.

        A tuple that is absent is absent. Offering the nearest architecture
        instead would install a build that cannot run.
        """

        for entry in self.platforms:
            if entry.platform == platform and entry.architecture == architecture:
                return entry
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "hup_version": HUP_VERSION,
            "product": self.product,
            "release": self.release.to_dict(),
            "platforms": [entry.to_dict() for entry in self.platforms],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_payload(cls, payload: Any) -> HupIndex:
        mapping = _mapping(payload, "index")
        version = mapping.get("hup_version")
        if version != HUP_VERSION:
            raise HupError(
                f"the update package declares version {version!r}; this build reads {HUP_VERSION}"
            )
        raw = mapping.get("platforms")
        if not isinstance(raw, (list, tuple)):
            raise HupError("the index must list its platforms")
        if len(raw) > MAX_PLATFORMS:
            raise HupError("the update package describes more platforms than it may")
        return cls(
            release=ReleaseIdentity.from_payload(mapping.get("release")),
            platforms=tuple(PlatformEntry.from_payload(item) for item in raw),
            product=_text(mapping, "product"),
        )

    @classmethod
    def from_json(cls, text: str) -> HupIndex:
        return cls.from_payload(_load_json(text, "index"))


@dataclass(frozen=True, slots=True)
class UpdatePackage:
    """One read update package: its index, and every manifest it carries."""

    index: HupIndex
    manifests: Mapping[str, TreeManifest]

    def manifest_for(self, entry: PlatformEntry) -> TreeManifest:
        manifest = self.manifests.get(entry.manifest.member)
        if manifest is None:
            raise HupError(f"the update package has no manifest for {entry.tuple_name}")
        return manifest

    @property
    def version(self) -> str:
        return self.index.version

    def asset_names(self) -> tuple[str, ...]:
        """Every release asset this package refers to, deduplicated."""

        names = {entry.full.name for entry in self.index}
        names.update(
            entry.delta.payload.name for entry in self.index if entry.delta is not None
        )
        return tuple(sorted(names))


def read_package(path: Path) -> UpdatePackage:
    """Read one update package from disk, within every bound above.

    The file has already been proved against the release's published digest by
    the time this runs; what is checked here is that its contents are the shape
    this build knows how to read, member by member, before any of it is used.
    """

    _require_readable_container(path)
    with zipfile.ZipFile(path) as package:
        members = _checked_members(package)
        index = HupIndex.from_json(
            _member_text(package, members[INDEX_MEMBER], MAX_INDEX_BYTES, INDEX_MEMBER)
        )
        manifests = _read_manifests(package, members, index)
    return UpdatePackage(index=index, manifests=manifests)


def write_package(path: Path, index: HupIndex, manifests: Mapping[str, TreeManifest]) -> Path:
    """Write the package a release publishes, and prove it reads back.

    The producer and every client share one reader, so a package that cannot be
    read here is a build failure rather than something a user discovers.
    """

    declared = set(index.members)
    if set(manifests) != declared:
        raise HupError("the index and the supplied manifests describe different platforms")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr(INDEX_MEMBER, index.to_json())
        for member in sorted(declared):
            package.writestr(member, manifests[member].to_json())

    read_package(path)
    return path


def package_digest(path: Path) -> str:
    """The digest a release's ``SHA256SUMS`` carries for this package."""

    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(_READ_BYTES), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _require_readable_container(path: Path) -> None:
    """Refuse the whole-file shapes this reader will not open at all."""

    try:
        size = path.stat().st_size
    except OSError as error:
        raise HupError(f"could not read the update package: {error}") from error
    if size > MAX_PACKAGE_BYTES:
        raise HupError("the update package is larger than this build reads")
    try:
        data = path.read_bytes()
    except OSError as error:
        raise HupError(f"could not read the update package: {error}") from error
    if _ZIP64_SIGNATURE in data:
        raise HupError("the update package is a ZIP64 archive")


def _checked_members(package: zipfile.ZipFile) -> Mapping[str, zipfile.ZipInfo]:
    """Index the archive by name, refusing every member shape but two."""

    try:
        infos = package.infolist()
    except zipfile.BadZipFile as error:
        raise HupError(f"the update package is unreadable: {error}") from error
    if len(infos) > MAX_MEMBERS:
        raise HupError("the update package carries more members than it may")

    members: dict[str, zipfile.ZipInfo] = {}
    expanded = 0
    for info in infos:
        _require_member_shape(info)
        if info.filename in members:
            raise HupError(f"the update package carries {info.filename} twice")
        expanded += info.file_size
        if expanded > MAX_EXPANDED_BYTES:
            raise HupError("the update package expands past what this build reads")
        members[info.filename] = info

    if INDEX_MEMBER not in members:
        raise HupError("the update package carries no index")
    return members


def _require_member_shape(info: zipfile.ZipInfo) -> None:
    """One member is a plain stored or deflated file at a name we expect."""

    name = info.filename
    if info.is_dir():
        raise HupError("the update package carries a directory member")
    if name != INDEX_MEMBER and not _is_manifest_member(name):
        raise HupError(f"{name} is not a member an update package carries")
    if info.compress_type not in _ALLOWED_COMPRESSION:
        raise HupError(f"{name} uses a compression this build does not read")
    if info.flag_bits & 0x1:
        raise HupError(f"{name} is encrypted")
    if (info.external_attr >> 16) & 0o170000 == 0o120000:
        raise HupError(f"{name} is a link")


def _is_manifest_member(name: str) -> bool:
    prefix = f"{MANIFEST_DIRECTORY}/"
    if not name.startswith(prefix) or not name.endswith(".json"):
        return False
    stem = name[len(prefix) : -len(".json")]
    return bool(stem) and "/" not in stem and ".." not in stem


def _read_manifests(
    package: zipfile.ZipFile,
    members: Mapping[str, zipfile.ZipInfo],
    index: HupIndex,
) -> Mapping[str, TreeManifest]:
    """Read exactly the manifests the index names, and prove each is its own."""

    declared = set(index.members)
    extra = set(members) - declared - {INDEX_MEMBER}
    if extra:
        raise HupError(f"the update package carries {sorted(extra)[0]}, which its index omits")

    manifests: dict[str, TreeManifest] = {}
    for entry in index:
        member = members.get(entry.manifest.member)
        if member is None:
            raise HupError(f"the update package is missing {entry.manifest.member}")
        text = _member_text(package, member, MAX_MANIFEST_BYTES, entry.manifest.member)
        _require_member_identity(text, entry.manifest)
        try:
            manifest = TreeManifest.from_json(text)
        except ManifestError as error:
            raise HupError(f"{entry.manifest.member} is not a usable manifest: {error}") from error
        _require_manifest_matches(manifest, entry)
        manifests[entry.manifest.member] = manifest
    return manifests


def _require_member_identity(text: str, member: ManifestMember) -> None:
    raw = text.encode("utf-8")
    if len(raw) != member.size:
        raise HupError(f"{member.member} is not the size the index declares")
    if hashlib.sha256(raw).hexdigest() != member.sha256:
        raise HupError(f"{member.member} is not the manifest the index describes")


def _require_manifest_matches(manifest: TreeManifest, entry: PlatformEntry) -> None:
    if manifest.identity.to_dict() != entry.identity.to_dict():
        raise HupError(f"{entry.manifest.member} describes a different build than the index")
    if manifest.layout.root != entry.layout_root:
        raise HupError(f"{entry.manifest.member} installs to a different root than the index")
    if manifest.layout.executable != entry.layout_executable:
        raise HupError(f"{entry.manifest.member} names a different executable than the index")


def _member_text(
    package: zipfile.ZipFile, info: zipfile.ZipInfo, limit: int, what: str
) -> str:
    """Read one member, stopping the moment it expands past its own limit."""

    if info.file_size > limit:
        raise HupError(f"{what} is larger than this build reads")
    chunks: list[bytes] = []
    read = 0
    try:
        with package.open(info) as stream:
            while True:
                chunk = stream.read(_READ_BYTES)
                if not chunk:
                    break
                read += len(chunk)
                if read > limit:
                    raise HupError(f"{what} is larger than this build reads")
                chunks.append(chunk)
    except (zipfile.BadZipFile, OSError, RuntimeError) as error:
        raise HupError(f"could not read {what}: {error}") from error
    try:
        return b"".join(chunks).decode("utf-8")
    except UnicodeError as error:
        raise HupError(f"{what} is not valid UTF-8: {error}") from error


def _load_json(text: str, what: str) -> Any:
    """Parse one bounded document, refusing the JSON a strict reader will not.

    Duplicate keys, ``NaN`` and the infinities, and a structure nested past the
    limit are all refused: each is a way for two readers of one document to
    reach two different answers.
    """

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise HupError(f"{what} names {key!r} twice")
            result[key] = value
        return result

    def constant(name: str) -> Any:
        raise HupError(f"{what} contains {name}, which is not a number")

    try:
        payload = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    except json.JSONDecodeError as error:
        raise HupError(f"{what} is not readable JSON: {error}") from error
    _require_depth(payload, what)
    return payload


def _require_depth(payload: Any, what: str, depth: int = 0) -> None:
    if depth > MAX_JSON_DEPTH:
        raise HupError(f"{what} is nested deeper than this build reads")
    if isinstance(payload, Mapping):
        for value in payload.values():
            _require_depth(value, what, depth + 1)
    elif isinstance(payload, (list, tuple)):
        for value in payload:
            _require_depth(value, what, depth + 1)


def _require_declared_tuple(mapping: Mapping[str, Any], entry: PlatformEntry) -> None:
    """The entry's own labels must agree with the identity it carries."""

    if mapping.get("platform") != entry.platform:
        raise HupError("a platform entry disagrees with its own identity about the platform")
    if mapping.get("architecture") != entry.architecture:
        raise HupError("a platform entry disagrees with its own identity about the architecture")


def _require_sorted_paths(paths: Sequence[str], platform: str, what: str) -> None:
    if len(set(paths)) != len(paths) or list(paths) != sorted(paths):
        raise HupError(f"the delta's {what} paths are not sorted and unique")
    for path in paths:
        try:
            require_tree_path(path, platform)
        except ManifestError as error:
            raise HupError(
                f"the delta names {path!r}, which is not a usable path: {error}"
            ) from error


def _paths(value: Any, what: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise HupError(f"{what} must be an array")
    return tuple(_require_path_text(item, what) for item in value)


def _require_path_text(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value:
        raise HupError(f"{what} must contain paths")
    if len(value.encode("utf-8")) > MAX_PATH_BYTES:
        raise HupError(f"{what} contains a path longer than this build reads")
    return value


def _identity(payload: Any) -> BuildIdentity:
    try:
        return BuildIdentity.from_payload(payload)
    except ManifestError as error:
        raise HupError(f"the update package has an unusable build identity: {error}") from error


def _mapping(payload: Any, what: str) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise HupError(f"{what} must be a JSON object")
    return payload


def _text(mapping: Mapping[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise HupError(f"{key} must be a non-empty string")
    return value


def _integer(mapping: Mapping[str, Any], key: str) -> int:
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise HupError(f"{key} must be an integer")
    return value


def _reason(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise HupError("a delta omission reason must be text")
    return value[:512]


def _require_asset_name(name: str) -> None:
    if not name or len(name.encode("utf-8")) > MAX_ASSET_NAME_BYTES:
        raise HupError(f"asset name {name!r} is not one a release publishes")
    if any(character in name for character in "/\\:") or name in (".", ".."):
        raise HupError(f"asset name {name!r} is not a plain release asset")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in name):
        raise HupError(f"asset name {name!r} contains a control character")


def _require_size(size: int, what: str) -> None:
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        raise HupError(f"{what} has no usable size")


def _require_digest(digest: str, what: str) -> None:
    if len(digest) != 64 or any(character not in _HEX for character in digest):
        raise HupError(f"{what} has no SHA-256 digest")


__all__ = [
    "DELTA_FORMAT",
    "FORMAT_DMG",
    "FORMAT_TAR_GZ",
    "FORMAT_ZIP",
    "FULL_FORMATS",
    "HUP_VERSION",
    "INDEX_MEMBER",
    "MAX_EXPANDED_BYTES",
    "MAX_INDEX_BYTES",
    "MAX_MANIFEST_BYTES",
    "MAX_MEMBERS",
    "MAX_PACKAGE_BYTES",
    "MAX_PLATFORMS",
    "PRODUCT",
    "SIGNATURE_POLICY_ADHOC",
    "BundleDescriptor",
    "DeltaDescriptor",
    "HupError",
    "HupIndex",
    "ManifestMember",
    "PlatformEntry",
    "ReleaseAsset",
    "ReleaseIdentity",
    "UpdatePackage",
    "delta_payload_name",
    "manifest_member_name",
    "package_asset_name",
    "package_digest",
    "read_package",
    "write_package",
]
