"""Focused validation for the release manifest consumed by ``UpdateService``."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from hanly_app.update_service import RemoteManifest

from tools.build_release_manifest import ResourceArtifact, build_manifest, main


def test_build_manifest_hashes_each_artifact_and_emits_release_asset_urls(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "krdict.sqlite3"
    payload = b"dictionary artifact"
    archive.write_bytes(payload)

    manifest = build_manifest(
        release="v1.2.3",
        release_base_url="https://github.com/acme/hanly/releases/download/v1.2.3",
        resources=(
            ResourceArtifact(
                resource_id="krdict",
                kind="krdict",
                version="2026.08",
                path=archive,
            ),
        ),
    )

    resource = manifest["resources"]["krdict"]
    assert resource == {
        "asset_name": "krdict.sqlite3",
        "checksum": f"sha256:{hashlib.sha256(payload).hexdigest()}",
        "kind": "krdict",
        "url": "https://github.com/acme/hanly/releases/download/v1.2.3/krdict.sqlite3",
        "version": "2026.08",
    }


def test_build_manifest_requires_https_and_existing_file_artifacts(tmp_path: Path) -> None:
    missing = tmp_path / "missing.zip"
    resource = ResourceArtifact("models", "directory", "v1", missing)

    with pytest.raises(ValueError, match="HTTPS"):
        build_manifest("v1", "http://github.example/release", (resource,))

    with pytest.raises(ValueError, match="artifact does not exist"):
        build_manifest("v1", "https://github.example/release", (resource,))

    with pytest.raises(ValueError, match="at least one resource"):
        build_manifest("v1", "https://github.example/release", ())


def test_resource_artifact_rejects_kinds_the_local_resource_manager_cannot_validate(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "resource.zip"
    artifact.write_bytes(b"resource")

    with pytest.raises(ValueError, match="resource kind must be one of"):
        ResourceArtifact("resource", "opaque", "v1", artifact)


def test_cli_accepts_explicit_resource_specs_and_writes_update_service_manifest(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "model.zip"
    archive.write_bytes(b"model")
    output = tmp_path / "hanly-resources.json"

    exit_code = main(
        [
            "--release",
            "v2.0.0",
            "--release-base-url",
            "https://github.example/releases/download/v2.0.0",
            "--output",
            str(output),
            "--resource",
            f"model|directory|v2.0.0|{archive}",
        ]
    )

    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["manifest_version"] == 1
    assert payload["release"] == "v2.0.0"
    assert payload["resources"]["model"]["asset_name"] == "model.zip"


def test_directory_resources_must_be_delivered_as_a_zip_archive(tmp_path: Path) -> None:
    """``UpdateService`` unpacks a directory resource with ``zipfile`` alone."""

    tarball = tmp_path / "models.tar.gz"
    tarball.write_bytes(b"models")

    with pytest.raises(ValueError, match="must be delivered as a .zip archive"):
        ResourceArtifact("models", "directory", "v1", tarball)

    assert ResourceArtifact("models", "directory", "v1", tmp_path / "models.zip")
    assert ResourceArtifact("models", "sqlite", "v1", tarball)


def test_resource_fields_are_stored_normalized(tmp_path: Path) -> None:
    artifact = tmp_path / "model.zip"
    artifact.write_bytes(b"model")

    resource = ResourceArtifact("  krdict ", " sqlite ", " 2026.08 ", artifact, "  named.zip ")

    assert (resource.resource_id, resource.kind, resource.version) == (
        "krdict",
        "sqlite",
        "2026.08",
    )
    assert resource.published_asset_name == "named.zip"


def test_asset_names_are_rejected_before_a_manifest_is_built(tmp_path: Path) -> None:
    artifact = tmp_path / "model.zip"
    artifact.write_bytes(b"model")

    with pytest.raises(ValueError, match="must not contain path separators"):
        ResourceArtifact("models", "directory", "v1", artifact, "nested/model.zip")


def test_base_url_whitespace_and_trailing_slashes_never_reach_asset_urls(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "model.zip"
    artifact.write_bytes(b"model")
    resource = ResourceArtifact("models", "directory", "v1", artifact)

    manifest = build_manifest(
        "  v1  ", "  https://github.example/releases/download/v1//  ", (resource,)
    )

    assert manifest["release"] == "v1"
    assert manifest["resources"]["models"]["url"] == (
        "https://github.example/releases/download/v1/model.zip"
    )


def test_generated_manifest_is_accepted_by_the_update_service_contract(tmp_path: Path) -> None:
    """The release tool and ``UpdateService`` must not drift apart silently."""

    models = tmp_path / "hanly-resources-paddle_detection_model-v1.zip"
    models.write_bytes(b"detection model archive")
    dictionary = tmp_path / "hanly-resources-krdict-v1.sqlite3"
    dictionary.write_bytes(b"dictionary")

    payload = build_manifest(
        "v1.0.0",
        "https://github.com/acme/hanly/releases/download/v1.0.0",
        (
            ResourceArtifact("paddle_detection_model", "directory", "v1.0.0", models),
            ResourceArtifact("krdict", "krdict", "v1.0.0", dictionary),
        ),
    )

    manifest = RemoteManifest.from_payload(payload)

    assert manifest.release == "v1.0.0"
    assert {resource.resource_id for resource in manifest} == {
        "paddle_detection_model",
        "krdict",
    }
    detection = manifest["paddle_detection_model"]
    assert detection.kind == "directory"
    assert detection.checksum is not None and detection.checksum.startswith("sha256:")
    assert detection.url == (
        "https://github.com/acme/hanly/releases/download/v1.0.0/"
        "hanly-resources-paddle_detection_model-v1.zip"
    )
