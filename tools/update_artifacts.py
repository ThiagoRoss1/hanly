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
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from hanly_app.app_build_identity import BUILD_STAMP_NAME, BuildStamp
from hanly_app.app_hup import delta_payload_name
from hanly_app.app_inventory import build_manifest, read_tree, write_installed_manifest
from hanly_app.app_manifest import (
    MANIFEST_ASSET,
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
) -> ReleaseProducts:
    """Produce every update artifact one Windows release publishes."""

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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--application",
        type=Path,
        required=True,
        help="the finished onedir build to inventory",
    )
    parser.add_argument("--version", required=True, help="the release version being published")
    parser.add_argument(
        "--archive", type=Path, help="the full application archive this release publishes"
    )
    parser.add_argument(
        "--output-directory", type=Path, help="where the release products are written"
    )
    parser.add_argument("--architecture", help="override the detected machine architecture")
    parser.add_argument(
        "--base-manifest", type=Path, help="the previous release's published manifest asset"
    )
    parser.add_argument(
        "--base-checksums", type=Path, help="the previous release's SHA256SUMS, to prove it"
    )
    parser.add_argument(
        "--manifest-only",
        action="store_true",
        help="write the inventory into the build and stop",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for ``python tools/update_artifacts.py``."""

    args = _build_parser().parse_args(argv)
    try:
        if args.manifest_only:
            manifest = generate_manifest(
                args.application, args.version, architecture=args.architecture
            )
            print(json.dumps({"build_id": manifest.identity.build_id, "files": len(manifest)}))
            return 0

        if args.archive is None or args.output_directory is None:
            raise ArtifactError("--archive and --output-directory are required for a release")

        products = build_release_products(
            args.application,
            args.archive,
            args.version,
            args.output_directory,
            architecture=args.architecture,
            base_manifest_path=args.base_manifest,
            base_checksums_path=args.base_checksums,
        )
    except (ArtifactError, ManifestError, OSError) as error:
        print(f"Hanly update artifacts: {error}", file=sys.stderr)
        return 1

    for path in products.paths():
        print(f"Hanly update artifacts: wrote {path}")
    if products.delta_path is None:
        print(f"Hanly update artifacts: no delta published ({products.delta_omitted_reason})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
