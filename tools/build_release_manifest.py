"""Build the GitHub resource manifest consumed by ``UpdateService``.

The release workflow supplies already-built application and resource artifacts.
This tool only inventories explicitly named resource artifacts, hashes their
bytes, and emits metadata whose asset URLs point at the tagged GitHub release.
It does not contact GitHub or publish anything.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

SUPPORTED_RESOURCE_KINDS = frozenset({"file", "directory", "sqlite", "krdict"})

# ``UpdateService`` unpacks a directory resource with ``zipfile`` and installs
# every other kind as the downloaded file itself, so a directory delivered in
# any other container cannot be activated by a client.
DIRECTORY_ARCHIVE_SUFFIX = ".zip"


@dataclass(frozen=True, slots=True)
class ResourceArtifact:
    """One staged resource archive and the metadata advertised for it."""

    resource_id: str
    kind: str
    version: str
    path: Path
    asset_name: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("resource_id", "kind", "version"):
            value = getattr(self, field_name).strip()
            if not value:
                raise ValueError(f"resource {field_name} must not be empty")
            object.__setattr__(self, field_name, value)

        if self.kind not in SUPPORTED_RESOURCE_KINDS:
            supported = ", ".join(sorted(SUPPORTED_RESOURCE_KINDS))
            raise ValueError(f"resource kind must be one of: {supported}")

        object.__setattr__(self, "path", Path(self.path))
        object.__setattr__(
            self, "asset_name", None if self.asset_name is None else self.asset_name.strip()
        )
        _validate_asset_name(self.published_asset_name)

        if self.kind == "directory" and not self.published_asset_name.lower().endswith(
            DIRECTORY_ARCHIVE_SUFFIX
        ):
            raise ValueError(
                f"directory resource {self.resource_id} must be delivered as a "
                f"{DIRECTORY_ARCHIVE_SUFFIX} archive"
            )

    @property
    def published_asset_name(self) -> str:
        """The release asset name advertised for this artifact."""

        return self.asset_name or self.path.name


def build_manifest(
    release: str,
    release_base_url: str,
    resources: Sequence[ResourceArtifact],
) -> dict[str, Any]:
    """Return deterministic ``hanly-resources.json`` payload data.

    Every resource is represented by its release asset name, an HTTPS asset
    URL, version, kind, and a SHA-256 checksum over the staged artifact bytes.
    """

    tag = release.strip()
    if not tag:
        raise ValueError("release must not be empty")
    if not resources:
        raise ValueError("at least one resource artifact is required")
    base_url = _https_base_url(release_base_url)

    entries: dict[str, dict[str, str]] = {}
    for resource in resources:
        if resource.resource_id in entries:
            raise ValueError(f"duplicate resource id: {resource.resource_id}")

        asset_name = resource.published_asset_name
        entries[resource.resource_id] = {
            "asset_name": asset_name,
            "checksum": f"sha256:{_sha256(resource.path)}",
            "kind": resource.kind,
            "url": f"{base_url}/{quote(asset_name, safe='-._~')}",
            "version": resource.version,
        }

    return {
        "manifest_version": 1,
        "release": tag,
        "resources": entries,
    }


def _https_base_url(value: str) -> str:
    """Return the normalized prefix that asset URLs are appended to."""

    normalized = value.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        raise ValueError("release base URL must be an HTTPS URL")
    if parsed.query or parsed.fragment:
        raise ValueError("release base URL must not contain a query or fragment")
    return normalized


def _validate_asset_name(asset_name: str) -> None:
    if not asset_name or asset_name in {".", ".."}:
        raise ValueError("resource asset_name must be a file name")
    if "/" in asset_name or "\\" in asset_name:
        raise ValueError("resource asset_name must not contain path separators")


def _sha256(path: Path) -> str:
    if not path.is_file():
        raise ValueError(f"resource artifact does not exist as a file: {path}")

    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ValueError(f"could not read resource artifact {path}: {exc}") from exc
    return digest.hexdigest()


def _resource_spec(value: str) -> ResourceArtifact:
    """Parse ``id|kind|version|path[|asset_name]`` CLI syntax."""

    fields = value.split("|", 4)
    if len(fields) not in {4, 5} or any(not field.strip() for field in fields[:4]):
        raise ValueError(
            "resource must use id|kind|version|path or "
            "id|kind|version|path|asset_name"
        )
    resource_id, kind, version, path = fields[:4]
    asset_name = fields[4] if len(fields) == 5 else None
    return ResourceArtifact(resource_id, kind, version, Path(path), asset_name)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", required=True, help="release tag/version")
    parser.add_argument(
        "--release-base-url",
        required=True,
        help="HTTPS URL prefix for release assets, without a trailing slash",
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--resource",
        action="append",
        required=True,
        metavar="ID|KIND|VERSION|PATH[|ASSET_NAME]",
        help="explicit staged resource artifact (repeat for each resource)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the manifest generator CLI."""

    args = _parser().parse_args(argv)
    try:
        resources = tuple(_resource_spec(value) for value in args.resource)
        payload = build_manifest(args.release, args.release_base_url, resources)
    except ValueError as exc:
        raise SystemExit(f"error: {exc}") from exc

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
