"""Real installation trees, and the release documents that describe them.

Every schema-2 case needs the same two things: a directory shaped like one of
the three products, and the manifest a release would publish for it. Building
them on disk rather than by hand is deliberate - the point of these cases is
that the producer and the client read one tree the same way, which a manifest
written out literally would not prove.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from hanly_app.app_build_identity import BuildStamp
from hanly_app.app_hup import (
    DELTA_FORMAT,
    BundleDescriptor,
    DeltaDescriptor,
    HupIndex,
    ManifestMember,
    PlatformEntry,
    ReleaseAsset,
    ReleaseIdentity,
    manifest_member_name,
    write_package,
)
from hanly_app.app_inventory import read_tree, write_xattr
from hanly_app.app_manifest import BuildIdentity, TreeEntry, TreeLayout, TreeManifest

BUNDLE_IDENTIFIER = "io.github.thiagoross1.hanly"

#: A commit hash shaped like a real one, for documents that must carry one.
SOURCE_COMMIT = "0123456789abcdef0123456789abcdef01234567"


@dataclass(frozen=True, slots=True)
class Link:
    """A relative symlink in a tree specification."""

    target: str


@dataclass(frozen=True, slots=True)
class Product:
    """One platform's layout, and the tree a fresh build of it looks like."""

    platform: str
    architecture: str
    root: str
    executable: str
    files: Mapping[str, object]

    @property
    def layout(self) -> TreeLayout:
        mode = None if self.platform == "windows" else 0o755
        return TreeLayout(root=self.root, executable=self.executable, mode=mode)

    def identity(self, version: str, build_id: str) -> BuildIdentity:
        return BuildIdentity(
            product="hanly-desktop",
            platform=self.platform,
            architecture=self.architecture,
            version=version,
            build_id=build_id,
        )

    def stamp(self, version: str, build_id: str) -> BuildStamp:
        return BuildStamp(
            product="hanly-desktop",
            platform=self.platform,
            architecture=self.architecture,
            version=version,
            build_id=build_id,
            source_commit=SOURCE_COMMIT,
        )


WINDOWS = Product(
    platform="windows",
    architecture="x86_64",
    root="hanly-desktop",
    executable="hanly-desktop.exe",
    files={
        "hanly-desktop.exe": b"windows program",
        "_internal": None,
        "_internal/base_library.zip": b"library bytes",
        "_internal/PyQt6": None,
        "_internal/PyQt6/QtCore.pyd": b"qt core",
    },
)

MACOS = Product(
    platform="macos",
    architecture="arm64",
    root="Hanly.app",
    executable="Contents/MacOS/hanly-desktop",
    files={
        "Contents": None,
        "Contents/Info.plist": b"<plist/>",
        "Contents/MacOS": None,
        "Contents/MacOS/hanly-desktop": b"mac program",
        "Contents/Frameworks": None,
        "Contents/Frameworks/Qt.framework": None,
        "Contents/Frameworks/Qt.framework/Versions": None,
        "Contents/Frameworks/Qt.framework/Versions/A": None,
        "Contents/Frameworks/Qt.framework/Versions/A/Qt": b"qt binary",
        "Contents/Frameworks/Qt.framework/Versions/Current": Link("A"),
        "Contents/Frameworks/Qt.framework/Qt": Link("Versions/Current/Qt"),
        "Contents/_CodeSignature": None,
        "Contents/_CodeSignature/CodeResources": b"<seal/>",
    },
)

LINUX = Product(
    platform="linux",
    architecture="x86_64",
    root="hanly-desktop",
    executable="hanly-desktop",
    files={
        "hanly-desktop": b"linux program",
        "_internal": None,
        "_internal/libpython.so.1.0": b"interpreter",
        "_internal/libpython.so": Link("libpython.so.1.0"),
    },
)

PRODUCTS = {product.platform: product for product in (WINDOWS, MACOS, LINUX)}

#: Which entries a build marks executable. Everything else keeps 0o644.
_EXECUTABLE_SUFFIXES = ("hanly-desktop", "hanly-desktop.exe", "/Qt")


def write_tree(
    parent: Path, product: Product, *, changes: Mapping[str, object] | None = None
) -> Path:
    """Create one product's directory under ``parent`` and return its root.

    ``changes`` overrides or adds entries, which is how a second build of the
    same product is made to differ from the first.
    """

    root = parent / product.root
    entries = {**product.files, **(changes or {})}
    root.mkdir(parents=True, exist_ok=True)
    for relative in sorted(entries, key=lambda value: value.count("/")):
        _write_entry(root, relative, entries[relative], product.platform)
    return root


def manifest_for(
    root: Path, product: Product, *, version: str = "0.5.3", build_id: str = "build-one"
) -> TreeManifest:
    """Read a built tree into the manifest its release would publish."""

    inventory = read_tree(root, product.platform)
    return inventory.manifest(product.identity(version, build_id), product.layout)


def entry_at(manifest: TreeManifest, path: str) -> TreeEntry:
    """One entry a case is about, failing the case when it is not there."""

    entry = manifest.get(path)
    if entry is None:
        raise AssertionError(f"{path} is not in the manifest")
    return entry


def asset_for(path: Path, format_name: str) -> ReleaseAsset:
    """Describe one real file as the release asset a client would fetch."""

    raw = path.read_bytes()
    return ReleaseAsset(
        name=path.name,
        size=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
        format=format_name,
    )


def manifest_member(manifest: TreeManifest) -> ManifestMember:
    raw = manifest.to_json().encode("utf-8")
    return ManifestMember(
        member=manifest_member_name(manifest.platform, manifest.identity.architecture),
        size=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
    )


def platform_entry(
    manifest: TreeManifest,
    full: ReleaseAsset,
    *,
    delta: DeltaDescriptor | None = None,
    delta_omitted_reason: str = "",
) -> PlatformEntry:
    """Assemble one index entry from a manifest and its published assets."""

    macos = (
        BundleDescriptor(bundle_identifier=BUNDLE_IDENTIFIER)
        if manifest.platform == "macos"
        else None
    )
    return PlatformEntry(
        identity=manifest.identity,
        manifest=manifest_member(manifest),
        full=full,
        layout_root=manifest.layout.root,
        layout_executable=manifest.layout.executable,
        delta=delta,
        delta_omitted_reason=delta_omitted_reason,
        macos=macos,
    )


def delta_descriptor(
    base: TreeManifest, payload: Path, changed: tuple[str, ...], deleted: tuple[str, ...] = ()
) -> DeltaDescriptor:
    return DeltaDescriptor(
        base_identity=base.identity,
        base_manifest_sha256=base.digest(),
        payload=asset_for(payload, DELTA_FORMAT),
        changed_paths=tuple(sorted(changed)),
        deleted_paths=tuple(sorted(deleted)),
    )


def write_hup(
    destination: Path,
    entries: tuple[PlatformEntry, ...],
    manifests: tuple[TreeManifest, ...],
    *,
    version: str = "0.5.3",
) -> Path:
    """Write a real update package from real manifests."""

    index = HupIndex(
        release=ReleaseIdentity(tag=f"v{version}", version=version, source_commit=SOURCE_COMMIT),
        platforms=entries,
    )
    return write_package(
        destination,
        index,
        {manifest_member(manifest).member: manifest for manifest in manifests},
    )


def _write_entry(root: Path, relative: str, value: object, platform: str) -> None:
    path = root.joinpath(*relative.split("/"))
    if isinstance(value, Link):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.unlink(missing_ok=True)
        path.symlink_to(value.target)
        return
    if value is None:
        path.mkdir(parents=True, exist_ok=True)
        _set_mode(path, 0o755, platform)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value if isinstance(value, bytes) else str(value).encode("utf-8"))
    _set_mode(path, 0o755 if relative.endswith(_EXECUTABLE_SUFFIXES) else 0o644, platform)


def _set_mode(path: Path, mode: int, platform: str) -> None:
    if platform != "windows":
        path.chmod(mode)


def sign_entry(path: Path, value: bytes = b"\x00\x01detached-signature") -> None:
    """Attach the kind of material attribute a signed bundle really carries."""

    write_xattr(path, "com.apple.cs.CodeDirectory", value)


__all__ = [
    "BUNDLE_IDENTIFIER",
    "LINUX",
    "MACOS",
    "PRODUCTS",
    "SOURCE_COMMIT",
    "WINDOWS",
    "Link",
    "Product",
    "asset_for",
    "delta_descriptor",
    "entry_at",
    "manifest_for",
    "manifest_member",
    "platform_entry",
    "sign_entry",
    "write_hup",
    "write_tree",
]
