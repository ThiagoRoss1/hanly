"""A whole published release on disk, and the client that reads one.

Every case about preparing an update needs the same thing: two builds, the
products and the update package a release publishes for them, and a fetcher
that answers for that release and nothing else. Building it for real - real
trees, real archives, real digests - is what makes the cases about the updater
rather than about the doubles.
"""

from __future__ import annotations

import hashlib
import shutil
import tarfile
import zipfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hanly_app.app_build_identity import BuildStamp
from hanly_app.app_hup import package_asset_name
from hanly_app.app_manifest import TreeManifest
from hanly_app.update_service import DownloadProgress, ProgressCallback, RemoteResource

from tests.hanly_fixtures.capabilities import MATERIAL_XATTRS
from tests.hanly_fixtures.update_tree import (
    Product,
    asset_for,
    delta_descriptor,
    info_plist,
    manifest_for,
    platform_entry,
    sign_entry,
    write_hup,
    write_tree,
)
from tools.update_artifacts import assemble_tree_delta, tree_delta_path

CHECKSUM_ASSET = "SHA256SUMS"

#: Where the fetcher double claims its assets live. Nothing is fetched over the
#: network; the URL exists because a release asset is required to have one.
ASSET_ORIGIN = "https://example.invalid/hanly"

#: What each platform publishes its whole product as.
FULL_FORMATS = {"windows": "zip", "macos": "dmg", "linux": "tar.gz"}
FULL_SUFFIXES = {"windows": ".zip", "macos": ".dmg", "linux": ".tar.gz"}


class PublishedRelease:
    """One release: its build, its products, and the package describing them."""

    def __init__(
        self,
        root: Path,
        product: Product,
        *,
        version: str,
        build_id: str,
        changes: Mapping[str, object] | None = None,
        previous: PublishedRelease | None = None,
    ) -> None:
        self.root = root
        self.product = product
        self.version = version
        self.tag = f"v{version}"
        self.assets = root / "assets"
        self.assets.mkdir(parents=True, exist_ok=True)

        self.build = write_tree(root / "build", product, changes=self._contents(changes))
        self._sign()
        self.manifest = manifest_for(self.build, product, version=version, build_id=build_id)
        self.stamp = product.stamp(version, build_id)
        self.full = self._archive_product()
        self.delta = self._delta(previous)
        self.package = self._package(previous)
        self.checksums = self._checksums()

    def _sign(self) -> None:
        """Give a macOS build the signature material a published one carries.

        Per version, so the attribute really changes between two releases: an
        update that dropped it would produce a bundle that no longer verifies,
        and a case built on an unsigned tree would never notice.

        Only macOS can carry it. Elsewhere the build is published unsigned and
        the cases whose subject is that material declare they need a host that
        can hold it.
        """

        if self.product.platform != "macos" or not MATERIAL_XATTRS:
            return
        sign_entry(
            self.build.joinpath(*self.product.executable.split("/")),
            f"signature for {self.version}".encode(),
        )

    def _contents(self, changes: Mapping[str, object] | None) -> dict[str, object]:
        """A macOS bundle's plist names its own version, so it is built per release."""

        contents: dict[str, object] = dict(changes or {})
        if self.product.platform == "macos":
            contents.setdefault("Contents/Info.plist", info_plist(self.version))
        return contents

    def payload(self) -> dict[str, Any]:
        """The release payload a GitHub adapter would hand the updater."""

        return {
            "tag_name": self.tag,
            "id": 5001,
            "html_url": f"{ASSET_ORIGIN}/releases/{self.tag}",
            "draft": False,
            "prerelease": False,
            "assets": [
                {
                    "name": path.name,
                    "id": index,
                    "size": path.stat().st_size,
                    "browser_download_url": f"{ASSET_ORIGIN}/{self.tag}/{path.name}",
                }
                for index, path in enumerate(sorted(self.assets.iterdir()), start=1)
            ],
        }

    def asset_path(self, name: str) -> Path:
        return self.assets / name

    def corrupt(self, name: str) -> None:
        """Change one published asset without changing what the release says."""

        path = self.assets / name
        path.write_bytes(path.read_bytes() + b"tampered")

    def install(self, destination: Path) -> Path:
        """Lay this build down as an installation, exactly as published."""

        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(self.build, destination, symlinks=True)
        return destination

    def _archive_product(self) -> Path:
        """Write the whole product this platform publishes.

        macOS publishes a disk image, which only macOS can make; for a portable
        case the file stands in for one, and the macOS lane proves the real
        thing against the same manifest.
        """

        name = f"hanly-desktop-{self.product.platform}{FULL_SUFFIXES[self.product.platform]}"
        destination = self.assets / name
        if self.product.platform == "linux":
            with tarfile.open(destination, "w:gz") as archive:
                archive.add(self.build, arcname=self.product.root)
            return destination
        if self.product.platform == "windows":
            with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for path in sorted(self.build.rglob("*")):
                    if path.is_file() and not path.is_symlink():
                        arcname = f"{self.product.root}/{path.relative_to(self.build).as_posix()}"
                        archive.write(path, arcname=arcname)
            return destination
        destination.write_bytes(b"a disk image the macOS lane produces for real")
        return destination

    def _delta(self, previous: PublishedRelease | None) -> Path | None:
        if previous is None:
            return None
        destination = tree_delta_path(self.assets, previous.manifest, self.manifest)
        assemble_tree_delta(self.build, self.manifest, previous.manifest, destination)
        return destination

    def _package(self, previous: PublishedRelease | None) -> Path:
        descriptor = (
            None
            if previous is None or self.delta is None
            else delta_descriptor(
                previous.manifest,
                self.delta,
                *_difference(previous.manifest, self.manifest),
            )
        )
        entry = platform_entry(
            self.manifest,
            asset_for(self.full, FULL_FORMATS[self.product.platform]),
            delta=descriptor,
            delta_omitted_reason="" if descriptor else "no verified predecessor was published",
        )
        return write_hup(
            self.assets / package_asset_name(self.version),
            (entry,),
            (self.manifest,),
            version=self.version,
        )

    def _checksums(self) -> Path:
        destination = self.assets / CHECKSUM_ASSET
        lines = [
            f"{_digest(path)}  {path.name}"
            for path in sorted(self.assets.iterdir())
            if path.name != CHECKSUM_ASSET
        ]
        destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return destination


class ReleaseChannel:
    """The two things a client needs from a release: its payload and its bytes."""

    def __init__(self, *releases: PublishedRelease) -> None:
        self._releases = {release.tag: release for release in releases}
        self.latest = releases[-1]
        self.requested: list[str] = []

    def release_source(self) -> Mapping[str, Any]:
        return self.latest.payload()

    def tagged_release_source(self, tag: str) -> Mapping[str, Any]:
        release = self._releases.get(tag)
        if release is None:
            raise KeyError(f"no release published for {tag}")
        return release.payload()

    def download(
        self,
        resource: RemoteResource,
        destination: Path,
        on_progress: ProgressCallback | None = None,
    ) -> None:
        """Serve one asset out of the release its own URL names.

        Resolved by URL rather than by name on purpose: two releases publish a
        ``SHA256SUMS``, and an updater that reached the wrong one would be
        proving this release's package against another release's digests.
        """

        name = resource.asset_name or ""
        tag = str(resource.url or "").removeprefix(f"{ASSET_ORIGIN}/").split("/")[0]
        self.requested.append(f"{tag}/{name}")
        release = self._releases.get(tag)
        if release is None:
            raise FileNotFoundError(f"no release published for {tag}")
        path = release.asset_path(name)
        if not path.is_file():
            raise FileNotFoundError(f"{release.tag} does not publish {name}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(path.read_bytes())
        if on_progress is not None:
            size = destination.stat().st_size
            on_progress(DownloadProgress(name, "downloading", size, size))


def stamp_for(release: PublishedRelease) -> BuildStamp:
    return release.stamp


def _difference(base: TreeManifest, target: TreeManifest) -> tuple[tuple[str, ...], ...]:
    from hanly_app.app_manifest import tree_difference

    computed = tree_difference(base, target)
    return computed.changed_paths, computed.deleted_paths


def _digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


__all__ = [
    "ASSET_ORIGIN",
    "CHECKSUM_ASSET",
    "PublishedRelease",
    "ReleaseChannel",
    "stamp_for",
]
