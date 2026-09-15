"""Produce the manifest, delta, and update metadata a release publishes.

The frozen application is built first; this runs against that finished tree and
never modifies it beyond writing the inventory into it. Three products come out:

``hanly-desktop-windows.manifest.json``
    every managed file in the build, with digest, size, and component.
``hanly-desktop-windows-from-<base>-to-<target>.delta.zip``
    only the files that differ from one named previous published build.
``hanly-desktop-windows.update.json``
    what a client downloads, and which build the delta starts from.

Schema 2 adds the same three products for macOS and Linux, and one more step
before any of them: the build stamp. A macOS bundle is sealed by its signature,
so its manifest cannot live inside it and cannot be a hash of its own contents
either. The identifier goes in as package data before the freeze, the manifest
is produced from the finished, signed tree afterwards, and the two meet in the
update package.

The delta is assembled against the *published* previous manifest, verified
against that release's ``SHA256SUMS``. Rebuilding an old tag and diffing
against the result would produce a delta whose base is a build nobody has
installed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import sys
import uuid
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from hanly_app.app_build_identity import BUILD_STAMP_NAME, BuildStamp
from hanly_app.app_hup import (
    DELTA_FORMAT,
    BundleDescriptor,
    HupError,
    HupIndex,
    ManifestMember,
    PlatformEntry,
    ReleaseAsset,
    ReleaseIdentity,
    delta_payload_name,
    manifest_member_name,
    read_package,
    write_package,
)
from hanly_app.app_hup import DeltaDescriptor as HupDelta
from hanly_app.app_inventory import build_manifest, read_tree, write_installed_manifest
from hanly_app.app_manifest import (
    MANIFEST_ASSET,
    PLATFORM_MACOS,
    PLATFORM_WINDOWS,
    UPDATE_METADATA_ASSET,
    AssetReference,
    BuildIdentity,
    DeltaDescriptor,
    InstallManifest,
    ManifestError,
    TreeDifference,
    TreeLayout,
    TreeManifest,
    UpdateMetadata,
    content_fingerprint,
    delta_asset_name,
    tree_difference,
)
from hanly_app.app_update import BUNDLE_IDENTIFIER
from hanly_app.app_update_plan import delta_contents

PRODUCT = "hanly-desktop"
PLATFORM = PLATFORM_WINDOWS

#: A delta carries a handful of files on the ordinary path, so compressing it
#: costs little and the saving is real for the Python archive and metadata that
#: dominate a patch release.
_COMPRESSION = zipfile.ZIP_DEFLATED

_CHECKSUM_LINE = re.compile(r"^([0-9a-f]{64})\s+\*?(\S+)$")


class ArtifactError(RuntimeError):
    """Raised when a release product cannot be produced from its inputs."""


@dataclass(frozen=True, slots=True)
class ReleaseProducts:
    """What one run wrote, and why a delta is missing when it is."""

    manifest_path: Path
    metadata_path: Path
    delta_path: Path | None = None
    delta_omitted_reason: str = ""

    def paths(self) -> tuple[Path, ...]:
        if self.delta_path is None:
            return (self.manifest_path, self.metadata_path)
        return (self.manifest_path, self.delta_path, self.metadata_path)


def host_architecture(machine: str | None = None) -> str:
    """Normalize the machine name into the label a manifest carries."""

    value = (machine if machine is not None else platform.machine()).strip().lower()
    if value in {"amd64", "x86_64", "x64"}:
        return "x86_64"
    if value in {"arm64", "aarch64"}:
        return "arm64"
    if value in {"x86", "i386", "i686"}:
        return "x86"
    raise ArtifactError(f"unsupported machine architecture {value!r}")


def generate_manifest(
    application: Path,
    version: str,
    *,
    architecture: str | None = None,
    write_into_build: bool = True,
) -> InstallManifest:
    """Inventory a finished build, and leave that inventory inside it.

    The build id is derived from the contents themselves, so two builds of one
    version are distinguishable and one build is reproducibly named.
    """

    architecture = architecture or host_architecture()
    provisional = _identity(version, architecture, "0" * 16)
    inventory = build_manifest(application, provisional)
    identity = _identity(version, architecture, content_fingerprint(inventory))
    manifest = InstallManifest.from_entries(identity, inventory)

    if write_into_build:
        write_installed_manifest(application, manifest)
    return manifest


def assemble_delta(
    application: Path,
    target: InstallManifest,
    base: InstallManifest,
    destination: Path,
) -> DeltaDescriptor:
    """Write the payload carrying every file that differs from ``base``."""

    changed = sorted(delta_contents(target, base))
    deletions = tuple(sorted(entry.path for entry in base if entry.path not in target))

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.unlink(missing_ok=True)
    with zipfile.ZipFile(destination, "w", compression=_COMPRESSION) as payload:
        for relative in changed:
            source = application.joinpath(*relative.split("/"))
            if not source.is_file():
                raise ArtifactError(f"the build is missing {relative}, which the delta needs")
            payload.write(source, arcname=relative)

    return DeltaDescriptor(
        base_version=base.identity.version,
        base_build_id=base.identity.build_id,
        base_manifest_digest=base.digest(),
        payload=_asset(destination),
        deletions=deletions,
    )


def load_base_manifest(manifest_path: Path, checksums_path: Path | None) -> InstallManifest:
    """Read a previously published manifest, proving it is that release's.

    Without the checksums the file is taken on trust, which is right for a
    local experiment and wrong for a release; the release lane always passes
    them.
    """

    try:
        text = manifest_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ArtifactError(f"could not read {manifest_path}: {error}") from error

    if checksums_path is not None:
        expected = _published_digests(checksums_path).get(MANIFEST_ASSET)
        if expected is None:
            raise ArtifactError(f"{checksums_path} lists no digest for {MANIFEST_ASSET}")
        actual = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if actual != expected:
            raise ArtifactError(
                f"{manifest_path} is not the manifest {checksums_path.name} published"
            )

    try:
        return InstallManifest.from_json(text)
    except ManifestError as error:
        raise ArtifactError(f"{manifest_path} is not a usable manifest: {error}") from error


def build_release_products(
    application: Path,
    archive: Path,
    version: str,
    output_directory: Path,
    *,
    architecture: str | None = None,
    base_manifest_path: Path | None = None,
    base_checksums_path: Path | None = None,
    delta_reason: str = "",
) -> ReleaseProducts:
    """Produce every update artifact one Windows release publishes.

    From the HUP era on this is a compatibility export: it is what a client
    from before cross-platform updates reads, and it is deliberately
    full-only. Publishing a second, legacy-only delta would save one
    bootstrap download and add a second thing to keep correct.
    """

    if not application.is_dir():
        raise ArtifactError(f"{application} is not a built application directory")
    if not archive.is_file():
        raise ArtifactError(f"{archive} is not a built application archive")

    manifest = generate_manifest(application, version, architecture=architecture)
    output_directory.mkdir(parents=True, exist_ok=True)
    manifest_path = output_directory / MANIFEST_ASSET
    manifest_path.write_text(manifest.to_json(), encoding="utf-8")

    delta_path, delta, reason = _optional_delta(
        application, manifest, output_directory, base_manifest_path, base_checksums_path
    )
    reason = reason if base_manifest_path is not None else (delta_reason or reason)

    metadata = UpdateMetadata(
        identity=manifest.identity,
        manifest_digest=manifest.digest(),
        manifest=_asset(manifest_path),
        full=_asset(archive),
        delta=delta,
        delta_omitted_reason=reason,
    )
    metadata_path = output_directory / UPDATE_METADATA_ASSET
    metadata_path.write_text(metadata.to_json(), encoding="utf-8")

    return ReleaseProducts(
        manifest_path=manifest_path,
        metadata_path=metadata_path,
        delta_path=delta_path,
        delta_omitted_reason=reason,
    )


def _optional_delta(
    application: Path,
    manifest: InstallManifest,
    output_directory: Path,
    base_manifest_path: Path | None,
    base_checksums_path: Path | None,
) -> tuple[Path | None, DeltaDescriptor | None, str]:
    """Produce the delta when a usable base exists, and say why when not.

    A missing or unusable predecessor never fails a release. The first
    manifest-aware build has none by definition, and a release that stops
    because it cannot diff is worse than one that ships the full archive.
    """

    if base_manifest_path is None:
        return None, None, "no previous published manifest was supplied"

    try:
        base = load_base_manifest(base_manifest_path, base_checksums_path)
    except ArtifactError as error:
        return None, None, str(error)

    if base.identity.version == manifest.identity.version:
        return None, None, "the previous published build carries this same version"
    if base.identity.architecture != manifest.identity.architecture:
        return None, None, "the previous published build is for a different architecture"
    if base.digest() == manifest.digest():
        return None, None, "the previous published build is identical to this one"

    destination = output_directory / delta_asset_name(
        base.identity.version, manifest.identity.version
    )
    return destination, assemble_delta(application, manifest, base, destination), ""


def _identity(version: str, architecture: str, build_id: str) -> BuildIdentity:
    return BuildIdentity(
        product=PRODUCT,
        platform=PLATFORM,
        architecture=architecture,
        version=version,
        build_id=build_id,
    )


def _asset(path: Path) -> AssetReference:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return AssetReference(name=path.name, size=path.stat().st_size, sha256=digest.hexdigest())


def _published_digests(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ArtifactError(f"could not read {path}: {error}") from error
    digests: dict[str, str] = {}
    for line in text.splitlines():
        match = _CHECKSUM_LINE.match(line.strip())
        if match is not None:
            digests[match.group(2)] = match.group(1)
    return digests


# --------------------------------------------------------------------------
# Schema 2: the stamp, the tree manifest, and the one delta per platform
# --------------------------------------------------------------------------


def allocate_build_id() -> str:
    """A fresh identifier for one freeze.

    A new one per build, even for the same tag: two builds of one version are
    two builds, and a release that could not tell them apart would offer a
    delta against bytes nobody has.
    """

    return str(uuid.uuid4())


def write_build_stamp(
    package_root: Path,
    *,
    platform_name: str,
    architecture: str,
    version: str,
    source_commit: str,
    build_id: str | None = None,
    built_at: str | None = None,
) -> BuildStamp:
    """Put this build's identity into the package, before it is frozen.

    Written as ordinary package data so the frozen application reads it the way
    it reads any other resource, and so nothing has to be appended to a signed
    bundle afterwards.
    """

    stamp = BuildStamp(
        product=PRODUCT,
        platform=platform_name,
        architecture=architecture,
        version=version,
        build_id=build_id or allocate_build_id(),
        source_commit=source_commit,
        built_at=built_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    destination = package_root / "assets" / BUILD_STAMP_NAME
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(stamp.to_json(), encoding="utf-8")
    return stamp


def read_build_stamp_file(package_root: Path) -> BuildStamp:
    """Read back the stamp a build was frozen with."""

    path = package_root / "assets" / BUILD_STAMP_NAME
    try:
        return BuildStamp.from_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as error:
        raise ArtifactError(f"could not read {path}: {error}") from error


def generate_tree_manifest(
    application: Path, stamp: BuildStamp, layout: TreeLayout
) -> TreeManifest:
    """Describe a finished, signed build exactly as its release publishes it.

    Run after signing and after every other change to the tree. Nothing is
    written into the application: the manifest is a release asset, and writing
    it inside a bundle would change the seal it claims to describe.
    """

    if not application.is_dir():
        raise ArtifactError(f"{application} is not a built application directory")
    inventory = read_tree(application, stamp.platform)
    if inventory.unsupported:
        raise ArtifactError(
            f"{application} carries {len(inventory.unsupported)} entries a manifest cannot "
            f"describe, starting with {inventory.unsupported[0]}"
        )
    manifest = inventory.manifest(stamp.identity, layout)
    if stamp.platform == PLATFORM_WINDOWS:
        _require_windows_installable(manifest)
    return manifest


def _require_windows_installable(manifest: TreeManifest) -> None:
    """Refuse a Windows build an in-place update could not put in place.

    Windows changes an installation file by file, so nothing creates a link or
    an empty directory. Publishing one would produce a release that installs
    correctly from the full product and never from a delta, which is a defect
    to catch at build time rather than on somebody's machine.
    """

    parents = {
        "/".join(entry.path.split("/")[:depth])
        for entry in manifest
        for depth in range(1, entry.path.count("/") + 1)
    }
    refused = sorted(
        entry.path
        for entry in manifest
        if entry.is_symlink or (entry.is_directory and entry.path not in parents)
    )
    if refused:
        raise ArtifactError(
            f"this Windows build contains {len(refused)} link(s) or empty directories an "
            f"in-place update cannot install, starting with {refused[0]}"
        )


def assemble_tree_delta(
    application: Path, target: TreeManifest, base: TreeManifest, destination: Path
) -> TreeDifference:
    """Write the one payload carrying every changed file's bytes, and nothing else.

    Modes, directories, links, and the allowed macOS attributes all come from
    the manifests, so the payload is plain regular-file content. A file whose
    only change is its permission bits contributes no member.
    """

    difference = tree_difference(base, target)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.unlink(missing_ok=True)
    with zipfile.ZipFile(destination, "w", compression=_COMPRESSION) as payload:
        for relative in difference.payload_paths:
            source = application.joinpath(*relative.split("/"))
            if source.is_symlink() or not source.is_file():
                raise ArtifactError(f"the build is missing {relative}, which the delta needs")
            payload.write(source, arcname=relative)
    return difference


def tree_delta_path(output_directory: Path, base: TreeManifest, target: TreeManifest) -> Path:
    """Where one platform's delta is written, under the name it publishes."""

    return output_directory / delta_payload_name(
        target.platform,
        target.identity.architecture,
        base.identity.version,
        target.identity.version,
    )


# --------------------------------------------------------------------------
# Schema 2: one platform's release products, and the package that indexes them
#
# Each build job produces its own products and a private descriptor naming
# them. One later job reads every descriptor and assembles the single update
# package. No job writes a fragment of that package, and no release rebuilds
# an application to produce one.
# --------------------------------------------------------------------------

MANIFEST_NAME = "manifest.json"
DESCRIPTOR_NAME = "descriptor.json"

#: Machine codes each executable format records for the two architectures
#: Hanly publishes. Read from the file rather than taken from the runner: a
#: label from the machine that built it says nothing about what it built.
_ELF_MACHINES = {0x3E: "x86_64", 0xB7: "arm64"}
_PE_MACHINES = {0x8664: "x86_64", 0xAA64: "arm64"}
_MACHO_CPUS = {0x01000007: "x86_64", 0x0100000C: "arm64"}


@dataclass(frozen=True, slots=True)
class PlatformRelease:
    """Everything one platform contributes to a release, and where it is."""

    directory: Path
    manifest: TreeManifest
    full: ReleaseAsset
    delta: HupDelta | None = None
    delta_omitted_reason: str = ""

    @property
    def manifest_path(self) -> Path:
        return self.directory / MANIFEST_NAME

    @property
    def descriptor_path(self) -> Path:
        return self.directory / DESCRIPTOR_NAME

    def entry(self) -> PlatformEntry:
        """This platform's entry in the release's one update package."""

        raw = self.manifest.to_json().encode("utf-8")
        return PlatformEntry(
            identity=self.manifest.identity,
            manifest=ManifestMember(
                member=manifest_member_name(
                    self.manifest.platform, self.manifest.identity.architecture
                ),
                size=len(raw),
                sha256=hashlib.sha256(raw).hexdigest(),
            ),
            full=self.full,
            layout_root=self.manifest.layout.root,
            layout_executable=self.manifest.layout.executable,
            delta=self.delta,
            delta_omitted_reason=self.delta_omitted_reason,
            macos=(
                BundleDescriptor(bundle_identifier=BUNDLE_IDENTIFIER)
                if self.manifest.platform == PLATFORM_MACOS
                else None
            ),
        )

    def write(self) -> PlatformRelease:
        """Write the manifest and the descriptor one aggregation job reads."""

        self.directory.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(self.manifest.to_json(), encoding="utf-8")
        self.descriptor_path.write_text(
            json.dumps(self.entry().to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return self

    @classmethod
    def read(cls, directory: Path) -> PlatformRelease:
        """Read back one platform's contribution, proving the two agree."""

        try:
            manifest = TreeManifest.from_json(
                (directory / MANIFEST_NAME).read_text(encoding="utf-8")
            )
            entry = PlatformEntry.from_payload(
                json.loads((directory / DESCRIPTOR_NAME).read_text(encoding="utf-8"))
            )
        except (OSError, UnicodeError, json.JSONDecodeError, ManifestError, HupError) as error:
            raise ArtifactError(f"{directory} is not a usable platform release: {error}") from error

        release = cls(
            directory=directory,
            manifest=manifest,
            full=entry.full,
            delta=entry.delta,
            delta_omitted_reason=entry.delta_omitted_reason,
        )
        if release.entry().to_dict() != entry.to_dict():
            raise ArtifactError(f"{directory} describes a build its manifest does not")
        return release


def executable_architecture(path: Path) -> str | None:
    """Read what machine an executable is actually built for, or None.

    The runner's own label is not evidence: a job can build for a different
    architecture than the one it runs on, and a hosted runner's default is not
    a promise. This reads the header the loader reads.
    """

    try:
        with path.open("rb") as stream:
            header = stream.read(64)
    except OSError:
        return None
    if len(header) < 20:
        return None

    if header[:4] == b"\x7fELF":
        return _ELF_MACHINES.get(int.from_bytes(header[18:20], "little"))
    if header[:2] == b"MZ":
        return _pe_architecture(path, header)
    if header[:4] in (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe"):
        return _MACHO_CPUS.get(int.from_bytes(header[4:8], "little"))
    return None


def _pe_architecture(path: Path, header: bytes) -> str | None:
    offset = int.from_bytes(header[0x3C:0x40], "little")
    try:
        with path.open("rb") as stream:
            stream.seek(offset)
            signature = stream.read(6)
    except OSError:
        return None
    if len(signature) < 6 or signature[:4] != b"PE\0\0":
        return None
    return _PE_MACHINES.get(int.from_bytes(signature[4:6], "little"))


def require_architecture(executable: Path, expected: str) -> None:
    """Refuse a build whose program is not for the machine it claims."""

    actual = executable_architecture(executable)
    if actual is None:
        raise ArtifactError(f"could not read what machine {executable} is built for")
    if actual != expected:
        raise ArtifactError(
            f"{executable} is built for {actual}, and this build claims {expected}"
        )


def build_platform_release(
    application: Path,
    stamp: BuildStamp,
    layout: TreeLayout,
    full_product: Path,
    output_directory: Path,
    *,
    full_format: str,
    base: TreeManifest | None = None,
    base_reason: str = "",
) -> PlatformRelease:
    """Produce one platform's manifest, optional delta, and descriptor.

    Run against the finished, signed tree. The delta is diffed against the
    *published* previous manifest, never a rebuilt tag: a rebuild is a
    different tree, and a delta whose base nobody has installed applies to
    nothing.
    """

    require_architecture(
        application.joinpath(*layout.executable.split("/")), stamp.architecture
    )
    manifest = generate_tree_manifest(application, stamp, layout)
    output_directory.mkdir(parents=True, exist_ok=True)

    delta, reason = _optional_tree_delta(
        application, manifest, base, output_directory, base_reason
    )
    return PlatformRelease(
        directory=output_directory,
        manifest=manifest,
        full=_release_asset(full_product, full_format),
        delta=delta,
        delta_omitted_reason=reason,
    ).write()


def _optional_tree_delta(
    application: Path,
    manifest: TreeManifest,
    base: TreeManifest | None,
    output_directory: Path,
    base_reason: str,
) -> tuple[HupDelta | None, str]:
    """Produce the delta when a usable predecessor exists, and say why when not.

    A missing or unusable predecessor never fails a release: the first
    HUP-aware build has none by definition. A delta no smaller than the whole
    product is dropped for the same reason a client would refuse it - there is
    nothing to gain and a second thing to go wrong.
    """

    if base is None:
        return None, base_reason or "no previous published manifest was supplied"
    if base.identity.to_dict() == manifest.identity.to_dict():
        return None, "the previous published build is this same build"
    if base.identity.version == manifest.identity.version:
        return None, "the previous published build carries this same version"
    if base.identity.architecture != manifest.identity.architecture:
        return None, "the previous published build is for a different architecture"

    destination = tree_delta_path(output_directory, base, manifest)
    difference = assemble_tree_delta(application, manifest, base, destination)
    payload = _release_asset(destination, DELTA_FORMAT)
    return (
        HupDelta(
            base_identity=base.identity,
            base_manifest_sha256=base.digest(),
            payload=payload,
            changed_paths=difference.changed_paths,
            deleted_paths=difference.deleted_paths,
        ),
        "",
    )


def load_base_package_manifest(
    package_path: Path,
    checksums_path: Path | None,
    *,
    platform_name: str,
    architecture: str,
) -> TreeManifest:
    """Read one platform's manifest out of a previously published package.

    Proved against that release's own checksums before it is opened. Without
    them the file is taken on trust, which is right for a local experiment and
    wrong for a release; the release lane always passes them.
    """

    if checksums_path is not None:
        expected = _published_digests(checksums_path).get(package_path.name)
        if expected is None:
            raise ArtifactError(
                f"{checksums_path} lists no digest for {package_path.name}"
            )
        if _file_digest(package_path) != expected:
            raise ArtifactError(
                f"{package_path} is not the package {checksums_path.name} published"
            )

    try:
        package = read_package(package_path)
    except HupError as error:
        raise ArtifactError(f"{package_path} is not a usable update package: {error}") from error
    entry = package.index.entry_for(platform_name, architecture)
    if entry is None:
        raise ArtifactError(
            f"{package_path} publishes no build for {platform_name} {architecture}"
        )
    return package.manifest_for(entry)


def assemble_update_package(
    directories: Sequence[Path],
    destination: Path,
    *,
    source_commit: str,
    products: Path | None = None,
) -> Path:
    """Build the one update package from every platform that succeeded.

    Assembled once, from the descriptors of one run. Every platform has to
    agree about the version and the commit, and no tuple may appear twice: a
    package mixing two runs would describe builds that were never published
    together.

    ``products`` is where the assets those descriptors name actually are. Given
    one, every size and digest is taken from the file rather than believed,
    which is the only place a descriptor and the thing it describes can be
    compared at all.
    """

    releases = [PlatformRelease.read(directory) for directory in directories]
    if products is not None:
        for release in releases:
            _require_published(products, release)
    if not releases:
        raise ArtifactError("no platform produced a release to index")

    versions = {release.manifest.identity.version for release in releases}
    if len(versions) != 1:
        raise ArtifactError(f"these builds carry {len(versions)} different versions")
    version = versions.pop()

    index = HupIndex(
        release=ReleaseIdentity(
            tag=f"v{version}", version=version, source_commit=source_commit
        ),
        platforms=tuple(release.entry() for release in releases),
    )
    try:
        return write_package(
            destination,
            index,
            {release.entry().manifest.member: release.manifest for release in releases},
        )
    except HupError as error:
        raise ArtifactError(f"the update package could not be assembled: {error}") from error


def _require_published(products: Path, release: PlatformRelease) -> None:
    """Prove every asset one platform advertises is the file it describes."""

    advertised = [release.full]
    if release.delta is not None:
        advertised.append(release.delta.payload)
    for asset in advertised:
        path = products / asset.name
        if not path.is_file():
            raise ArtifactError(f"{release.manifest.platform} advertises {asset.name}, which "
                                f"this run did not produce")
        if path.stat().st_size != asset.size or _file_digest(path) != asset.sha256:
            raise ArtifactError(f"{asset.name} is not the file its descriptor describes")


def _release_asset(path: Path, format_name: str) -> ReleaseAsset:
    return ReleaseAsset(
        name=path.name,
        size=path.stat().st_size,
        sha256=_file_digest(path),
        format=format_name,
    )


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    stamp = commands.add_parser("stamp", help="write this build's identity before it is frozen")
    stamp.add_argument("--package-root", type=Path, required=True)
    stamp.add_argument("--platform", dest="platform_name", required=True)
    stamp.add_argument("--architecture", required=True)
    stamp.add_argument("--version", required=True)
    stamp.add_argument("--source-commit", required=True)
    stamp.add_argument("--build-id", help="reuse an identifier instead of allocating one")

    package = commands.add_parser(
        "package", help="assemble one release's update package from every platform"
    )
    package.add_argument(
        "--descriptor",
        dest="descriptors",
        type=Path,
        action="append",
        required=True,
        help="a directory one build job wrote its manifest and descriptor into",
    )
    package.add_argument("--output", type=Path, required=True)
    package.add_argument("--source-commit", required=True)
    package.add_argument(
        "--products",
        type=Path,
        help="where the assets those descriptors name are, so each one is proved",
    )

    manifest = commands.add_parser(
        "manifest", help="write the schema-1 inventory into a Windows build"
    )
    manifest.add_argument("--application", type=Path, required=True)
    manifest.add_argument("--version", required=True)
    manifest.add_argument("--architecture")

    legacy = commands.add_parser(
        "legacy", help="write the schema-1 Windows compatibility documents"
    )
    legacy.add_argument("--application", type=Path, required=True)
    legacy.add_argument("--version", required=True)
    legacy.add_argument("--archive", type=Path, required=True)
    legacy.add_argument("--output-directory", type=Path, required=True)
    legacy.add_argument("--architecture")
    legacy.add_argument("--base-manifest", type=Path)
    legacy.add_argument("--base-checksums", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for ``python tools/update_artifacts.py``."""

    args = _build_parser().parse_args(argv)
    try:
        return _run(args)
    except (ArtifactError, ManifestError, OSError) as error:
        print(f"Hanly update artifacts: {error}", file=sys.stderr)
        return 1


def _run(args: argparse.Namespace) -> int:
    if args.command == "stamp":
        stamp = write_build_stamp(
            args.package_root,
            platform_name=args.platform_name,
            architecture=args.architecture,
            version=args.version,
            source_commit=args.source_commit,
            build_id=args.build_id,
        )
        print(json.dumps(stamp.to_dict()))
        return 0

    if args.command == "package":
        written = assemble_update_package(
            args.descriptors,
            args.output,
            source_commit=args.source_commit,
            products=args.products,
        )
        print(f"Hanly update artifacts: wrote {written}")
        return 0

    if args.command == "manifest":
        manifest = generate_manifest(
            args.application, args.version, architecture=args.architecture
        )
        print(json.dumps({"build_id": manifest.identity.build_id, "files": len(manifest)}))
        return 0

    products = build_release_products(
        args.application,
        args.archive,
        args.version,
        args.output_directory,
        architecture=args.architecture,
        base_manifest_path=args.base_manifest,
        base_checksums_path=args.base_checksums,
    )
    for path in products.paths():
        print(f"Hanly update artifacts: wrote {path}")
    if products.delta_path is None:
        print(f"Hanly update artifacts: no delta published ({products.delta_omitted_reason})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
