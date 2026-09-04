"""Package a validated KRDICT SQLite seed as a release-ready Zstandard asset."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

if __package__ in (None, ""):
    # Run as a plain script rather than ``python -m``, so the repository root
    # is not on the path and ``tools.krdict`` cannot be imported without it.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from collections.abc import Sequence
from dataclasses import asdict, dataclass

import zstandard
from hanly.krdict_schema import KRDICTSchemaError, validate_krdict_connection

from tools.krdict import configure_utf8_output


class PackageError(RuntimeError):
    """Raised when a seed cannot be packaged without metadata drift."""


@dataclass(frozen=True, slots=True)
class PackageResult:
    asset_path: Path
    manifest_path: Path
    sha256: str
    uncompressed_size: int
    compressed_size: int
    compression_ratio: float
    resource_version: str
    source_date: str
    schema_version: int
    expected_entry_count: int


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _temporary_file(destination: Path, suffix: str) -> Path:
    descriptor, name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=suffix, dir=destination.parent
    )
    os.close(descriptor)
    return Path(name)


def package_database(
    database_path: str | Path,
    output_path: str | Path,
    *,
    resource_version: str,
    source_date: str,
    manifest_path: str | Path,
) -> PackageResult:
    """Validate, compress, hash, and describe one deterministic resource."""

    database = Path(database_path)
    output = Path(output_path)
    manifest = Path(manifest_path)
    expected_name = f"krdict-{resource_version}.sqlite3.zst"
    if output.name != expected_name:
        raise PackageError(f"asset name must be {expected_name}")
    if not database.is_file():
        raise PackageError(f"database does not exist: {database}")

    connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
    try:
        try:
            metadata = validate_krdict_connection(
                connection, expected_resource_version=resource_version
            )
        except (sqlite3.Error, KRDICTSchemaError) as exc:
            raise PackageError(f"database validation failed: {exc}") from exc
    finally:
        connection.close()
    if metadata["source_date"] != source_date:
        raise PackageError("source_date does not match database metadata")

    output.parent.mkdir(parents=True, exist_ok=True)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    temporary_asset = _temporary_file(output, ".zst.tmp")
    temporary_manifest = _temporary_file(manifest, ".json.tmp")
    uncompressed_size = database.stat().st_size
    try:
        compressor = zstandard.ZstdCompressor(
            level=19,
            threads=0,
            write_checksum=True,
            write_content_size=True,
        )
        with database.open("rb") as source, temporary_asset.open("wb") as target:
            compressor.copy_stream(source, target, size=uncompressed_size)
        compressed_size = temporary_asset.stat().st_size
        digest = _sha256(temporary_asset)
        payload = {
            "manifest_version": 1,
            "resources": {
                "krdict": {
                    "asset_name": output.name,
                    "checksum": f"sha256:{digest}",
                    "expected_entry_count": int(metadata["entry_count"]),
                    "kind": "krdict",
                    "schema_version": int(metadata["schema_version"]),
                    "size": compressed_size,
                    "source_date": source_date,
                    "version": resource_version,
                }
            },
        }
        temporary_manifest.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary_asset, output)
        os.replace(temporary_manifest, manifest)
    except (OSError, ValueError, zstandard.ZstdError) as exc:
        raise PackageError(f"resource packaging failed: {exc}") from exc
    finally:
        temporary_asset.unlink(missing_ok=True)
        temporary_manifest.unlink(missing_ok=True)

    return PackageResult(
        asset_path=output.resolve(),
        manifest_path=manifest.resolve(),
        sha256=digest,
        uncompressed_size=uncompressed_size,
        compressed_size=compressed_size,
        compression_ratio=compressed_size / uncompressed_size,
        resource_version=resource_version,
        source_date=source_date,
        schema_version=int(metadata["schema_version"]),
        expected_entry_count=int(metadata["entry_count"]),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--resource-version", required=True)
    parser.add_argument("--source-date", required=True)
    parser.add_argument("--manifest", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    configure_utf8_output()
    args = _parser().parse_args(argv)
    try:
        result = package_database(
            args.database,
            args.output,
            resource_version=args.resource_version,
            source_date=args.source_date,
            manifest_path=args.manifest,
        )
    except PackageError as exc:
        raise SystemExit(f"error: {exc}") from exc
    print(
        json.dumps(
            {
                **asdict(result),
                "asset_path": str(result.asset_path),
                "manifest_path": str(result.manifest_path),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
