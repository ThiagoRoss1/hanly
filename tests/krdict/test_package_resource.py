"""Zstandard resource packaging contract tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import zstandard
from hanly_app.update_service import RemoteManifest

from tests.hanly_fixtures.krdict import build_fixture_krdict
from tools.krdict.package_resource import PackageError, package_database


def test_packager_creates_deterministic_zstd_and_manifest_metadata(tmp_path: Path) -> None:
    database = build_fixture_krdict(tmp_path)
    first_directory = tmp_path / "first"
    second_directory = tmp_path / "second"
    first_directory.mkdir()
    second_directory.mkdir()
    asset_name = "krdict-fixture-v1.sqlite3.zst"

    first = package_database(
        database,
        first_directory / asset_name,
        resource_version="fixture-v1",
        source_date="fixture",
        manifest_path=first_directory / "resource.json",
    )
    second = package_database(
        database,
        second_directory / asset_name,
        resource_version="fixture-v1",
        source_date="fixture",
        manifest_path=second_directory / "resource.json",
    )

    assert first.asset_path.read_bytes() == second.asset_path.read_bytes()
    assert first.sha256 == hashlib.sha256(first.asset_path.read_bytes()).hexdigest()
    assert first.compressed_size == first.asset_path.stat().st_size
    assert first.uncompressed_size == database.stat().st_size
    assert first.compression_ratio == pytest.approx(
        first.compressed_size / first.uncompressed_size
    )
    payload = json.loads(first.manifest_path.read_text(encoding="utf-8"))
    assert payload == {
        "manifest_version": 1,
        "resources": {
            "krdict": {
                "asset_name": asset_name,
                "checksum": f"sha256:{first.sha256}",
                "expected_entry_count": 3,
                "kind": "krdict",
                "schema_version": 1,
                "size": first.compressed_size,
                "source_date": "fixture",
                "version": "fixture-v1",
            }
        },
    }
    restored = zstandard.ZstdDecompressor().decompress(
        first.asset_path.read_bytes(), max_output_size=first.uncompressed_size
    )
    assert restored == database.read_bytes()


def test_packager_rejects_metadata_that_disagrees_with_requested_asset(tmp_path: Path) -> None:
    database = build_fixture_krdict(tmp_path)

    with pytest.raises(PackageError, match="resource_version"):
        package_database(
            database,
            tmp_path / "krdict-wrong.sqlite3.zst",
            resource_version="wrong",
            source_date="fixture",
            manifest_path=tmp_path / "resource.json",
        )


def test_producer_manifest_is_accepted_by_remote_manifest_contract(tmp_path: Path) -> None:
    database = build_fixture_krdict(tmp_path)
    result = package_database(
        database,
        tmp_path / "krdict-fixture-v1.sqlite3.zst",
        resource_version="fixture-v1",
        source_date="fixture",
        manifest_path=tmp_path / "resource.json",
    )

    payload = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    manifest = RemoteManifest.from_payload(payload)
    resource = manifest["krdict"]

    assert resource.asset_name == result.asset_path.name
    assert resource.checksum == f"sha256:{result.sha256}"
    assert resource.kind == "krdict"
    assert resource.version == "fixture-v1"
    assert resource.schema_version == 1
    assert resource.expected_entry_count == 3
