from __future__ import annotations

import hashlib
import io
import json
import os
import sqlite3
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import zstandard
from hanly.resource_manager import ResourceManager, ResourceManifest, ResourceSpec
from hanly_app import update_service
from hanly_app.update_service import (
    DownloadProgress,
    GitHubReleaseFetcher,
    RemoteManifest,
    RemoteManifestError,
    RemoteResource,
    ResourceUpdateError,
    UpdateService,
)

from tools.krdict.build_seed import build_database


@dataclass
class FakeFetcher:
    manifest: RemoteManifest
    payloads: dict[str, bytes]
    fail_after_write: bool = False

    def fetch_manifest(self) -> RemoteManifest:
        return self.manifest

    def download(
        self, resource: RemoteResource, destination: Path, on_progress: Any = None
    ) -> None:
        payload = self.payloads[resource.resource_id]
        written = payload[: max(1, len(payload) // 2)] if self.fail_after_write else payload
        destination.write_bytes(written)
        if on_progress is not None:
            on_progress(
                DownloadProgress(resource.resource_id, "downloading", len(written), len(payload))
            )
        if self.fail_after_write:
            raise OSError("controlled interruption")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _service(
    tmp_path: Path, payload: bytes | None = None
) -> tuple[UpdateService, ResourceManager, FakeFetcher]:
    destination = tmp_path / "krdict.sqlite"
    _create_krdict_database(destination, "known good")
    if payload is None:
        updated = tmp_path / "updated.sqlite"
        _create_krdict_database(updated, "new", version="2")
        payload = updated.read_bytes()
    spec = ResourceSpec("krdict", destination, version="1", kind="krdict")
    resource = RemoteResource(
        "krdict",
        "2",
        url="https://example.test/krdict",
        checksum=f"sha256:{_sha256(payload)}",
        kind="krdict",
    )
    fetcher = FakeFetcher(RemoteManifest((resource,)), {"krdict": payload})
    manager = ResourceManager(ResourceManifest((spec,)))
    return UpdateService(manager, fetcher), manager, fetcher


def test_manifest_normalizes_mapping_and_array_forms() -> None:
    manifest = RemoteManifest.from_payload(
        {
            "release": "v1",
            "resources": {
                "ocr-model": {"version": "2", "asset_name": "ocr.zip", "kind": "directory"}
            },
        }
    )

    assert manifest.release == "v1"
    assert manifest["ocr-model"].asset_name == "ocr.zip"
    assert manifest["ocr-model"].kind == "directory"


def test_manifest_preserves_optional_krdict_artifact_validation_fields() -> None:
    manifest = RemoteManifest.from_payload(
        {
            "resources": {
                "krdict": {
                    "version": "20260819-v1",
                    "asset_name": "krdict-20260819-v1.sqlite3.zst",
                    "checksum": f"sha256:{'1' * 64}",
                    "kind": "krdict",
                    "size": 123,
                    "schema_version": 1,
                    "expected_entry_count": 56555,
                    "source_date": "2026-08-19",
                }
            }
        }
    )

    resource = manifest["krdict"]
    assert (
        resource.size,
        resource.schema_version,
        resource.expected_entry_count,
        resource.source_date,
    ) == (123, 1, 56555, "2026-08-19")


def test_manifest_rejects_missing_resources() -> None:
    with pytest.raises(RemoteManifestError, match="resources"):
        RemoteManifest.from_payload({})


def test_check_for_updates_reports_remote_version_without_local_policy(tmp_path: Path) -> None:
    service, _manager, _fetcher = _service(tmp_path)

    updates = service.check_for_updates()

    assert len(updates) == 1
    assert updates[0].available is True
    assert updates[0].current_version == "1"
    assert updates[0].resource.version == "2"


def test_install_validates_staged_artifact_before_atomic_activation_and_keeps_backup(
    tmp_path: Path,
) -> None:
    service, _manager, _fetcher = _service(tmp_path)
    events: list[DownloadProgress] = []
    destination = tmp_path / "krdict.sqlite"

    result = service.install("krdict", on_progress=events.append)

    assert _headword(destination) == "new"
    assert result.path == destination.resolve()
    assert result.backup_path == tmp_path / "krdict.sqlite.last-known-good"
    assert _headword(result.backup_path) == "known good"
    assert any(event.phase == "installing" for event in events)
    assert events[-1].phase == "complete"
    assert list(tmp_path.glob("*.download")) == []


def test_failed_sqlite_validation_is_non_destructive(tmp_path: Path) -> None:
    service, _manager, _fetcher = _service(tmp_path, b"truncated sqlite")

    with pytest.raises(ResourceUpdateError, match="not valid|validation"):
        service.install("krdict")

    connection = sqlite3.connect(tmp_path / "krdict.sqlite")
    try:
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    finally:
        connection.close()
    assert list(tmp_path.glob("*.download")) == []


def test_zstd_krdict_is_verified_decompressed_validated_and_activated(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "krdict.sqlite3"
    _create_krdict_database(destination, "known good")
    updated = tmp_path / "updated.sqlite3"
    _create_krdict_database(updated, "new", version="2")
    payload = zstandard.ZstdCompressor(write_checksum=True).compress(updated.read_bytes())
    resource = RemoteResource(
        "krdict",
        "2",
        url="https://example.test/krdict-2.sqlite3.zst",
        checksum=f"sha256:{_sha256(payload)}",
        kind="krdict",
        size=len(payload),
        schema_version=1,
        expected_entry_count=1,
        source_date="fixture",
    )
    fetcher = FakeFetcher(RemoteManifest((resource,)), {"krdict": payload})
    manager = ResourceManager(
        ResourceManifest((ResourceSpec("krdict", destination, version="1", kind="krdict"),))
    )
    progress: list[DownloadProgress] = []

    result = UpdateService(manager, fetcher).install("krdict", on_progress=progress.append)

    assert _headword(result.path) == "new"
    assert _headword(destination.with_name(destination.name + ".last-known-good")) == (
        "known good"
    )
    assert [event.phase for event in progress if event.phase != "downloading"] == [
        "verifying",
        "installing",
        "complete",
    ]


@pytest.mark.parametrize(
    ("size", "schema_version", "entry_count", "source_date", "message"),
    [
        (1, 1, 1, "fixture", "size does not match"),
        (None, 2, 1, "fixture", "schema_version does not match"),
        (None, 1, 2, "fixture", "entry_count does not match"),
        (None, 1, 1, "2099-01-01", "source_date does not match"),
    ],
)
def test_zstd_manifest_mismatches_preserve_the_active_database_and_clean_staging(
    tmp_path: Path,
    size: int | None,
    schema_version: int,
    entry_count: int,
    source_date: str,
    message: str,
) -> None:
    destination = tmp_path / "krdict.sqlite3"
    _create_krdict_database(destination, "known good")
    updated = tmp_path / "updated.sqlite3"
    _create_krdict_database(updated, "new", version="2")
    payload = zstandard.ZstdCompressor(write_checksum=True).compress(updated.read_bytes())
    resource = RemoteResource(
        "krdict",
        "2",
        url="https://example.test/krdict-2.sqlite3.zst",
        checksum=f"sha256:{_sha256(payload)}",
        kind="krdict",
        size=len(payload) if size is None else size,
        schema_version=schema_version,
        expected_entry_count=entry_count,
        source_date=source_date,
    )
    fetcher = FakeFetcher(RemoteManifest((resource,)), {"krdict": payload})
    manager = ResourceManager(
        ResourceManifest((ResourceSpec("krdict", destination, version="1", kind="krdict"),))
    )

    with pytest.raises(ResourceUpdateError, match=message):
        UpdateService(manager, fetcher).install("krdict")

    assert _headword(destination) == "known good"
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "krdict.sqlite3",
        "krdict.sqlite3.zip",
        "updated.sqlite3",
        "updated.sqlite3.zip",
    ]


def test_valid_zstd_wrapping_corrupt_sqlite_is_non_destructive_and_cleans_staging(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "krdict.sqlite3"
    _create_krdict_database(destination, "known good")
    payload = zstandard.ZstdCompressor(write_checksum=True).compress(b"not sqlite")
    resource = RemoteResource(
        "krdict",
        "2",
        url="https://example.test/krdict-2.sqlite3.zst",
        checksum=f"sha256:{_sha256(payload)}",
        kind="krdict",
        size=len(payload),
        schema_version=1,
        expected_entry_count=1,
        source_date="fixture",
    )
    fetcher = FakeFetcher(RemoteManifest((resource,)), {"krdict": payload})
    manager = ResourceManager(
        ResourceManifest((ResourceSpec("krdict", destination, version="1", kind="krdict"),))
    )

    with pytest.raises(ResourceUpdateError, match="validation|not valid"):
        UpdateService(manager, fetcher).install("krdict")

    assert _headword(destination) == "known good"
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "krdict.sqlite3",
        "krdict.sqlite3.zip",
    ]


def test_corrupt_zstd_is_rejected_without_replacing_active_database(tmp_path: Path) -> None:
    destination = tmp_path / "krdict.sqlite3"
    _create_krdict_database(destination, "known good")
    payload = b"not a zstandard frame"
    resource = RemoteResource(
        "krdict",
        "2",
        url="https://example.test/krdict-2.sqlite3.zst",
        checksum=f"sha256:{_sha256(payload)}",
        kind="krdict",
        size=len(payload),
        schema_version=1,
        expected_entry_count=1,
        source_date="fixture",
    )
    fetcher = FakeFetcher(RemoteManifest((resource,)), {"krdict": payload})
    manager = ResourceManager(
        ResourceManifest((ResourceSpec("krdict", destination, version="1", kind="krdict"),))
    )

    with pytest.raises(ResourceUpdateError, match="decompress|Zstandard"):
        UpdateService(manager, fetcher).install("krdict")

    assert _headword(destination) == "known good"
    assert not tuple(tmp_path.glob(".*.install"))


def test_an_empty_zstd_frame_is_rejected_and_leaves_no_staged_output(tmp_path: Path) -> None:
    """A valid frame that decompresses to nothing is a rejection like any other,
    and must not leave its partially written install file behind."""

    destination = tmp_path / "krdict.sqlite3"
    _create_krdict_database(destination, "known good")
    payload = zstandard.ZstdCompressor().compress(b"")
    resource = RemoteResource(
        "krdict",
        "2",
        url="https://example.test/krdict-2.sqlite3.zst",
        checksum=f"sha256:{_sha256(payload)}",
        kind="krdict",
        size=len(payload),
        schema_version=1,
        expected_entry_count=1,
        source_date="fixture",
    )
    fetcher = FakeFetcher(RemoteManifest((resource,)), {"krdict": payload})
    manager = ResourceManager(
        ResourceManifest((ResourceSpec("krdict", destination, version="1", kind="krdict"),))
    )

    with pytest.raises(ResourceUpdateError, match="empty"):
        UpdateService(manager, fetcher).install("krdict")

    assert _headword(destination) == "known good"
    assert not tuple(tmp_path.glob(".*.install"))


def test_sqlite_install_requires_an_expected_remote_checksum(tmp_path: Path) -> None:
    destination = tmp_path / "krdict.sqlite"
    _create_krdict_database(destination, "known good")
    resource = RemoteResource(
        "krdict",
        "2",
        url="https://example.test/krdict",
        kind="krdict",
    )
    fetcher = FakeFetcher(RemoteManifest((resource,)), {"krdict": b"unused"})
    manager = ResourceManager(
        ResourceManifest((ResourceSpec("krdict", destination, version="1", kind="krdict"),))
    )

    with pytest.raises(ResourceUpdateError, match="must provide a checksum"):
        UpdateService(manager, fetcher).install("krdict")

    connection = sqlite3.connect(destination)
    try:
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    finally:
        connection.close()


def test_interrupted_download_is_reported_and_leaves_no_partial_stage(tmp_path: Path) -> None:
    service, _manager, fetcher = _service(tmp_path)
    fetcher.fail_after_write = True

    with pytest.raises(ResourceUpdateError, match="interruption"):
        service.install("krdict")

    connection = sqlite3.connect(tmp_path / "krdict.sqlite")
    try:
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    finally:
        connection.close()
    assert list(tmp_path.glob("*.download")) == []


def test_directory_resource_is_unpacked_to_staging_directory(tmp_path: Path) -> None:
    destination = tmp_path / "ocr-model"
    destination.mkdir()
    (destination / "old.bin").write_bytes(b"old")
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("model.bin", b"model")
    spec = ResourceSpec("ocr-model", destination, version="1", kind="directory")
    resource = RemoteResource(
        "ocr-model",
        "2",
        url="https://example.test/model.zip",
        checksum=f"sha256:{_sha256(archive.getvalue())}",
        kind="directory",
    )
    manager = ResourceManager(ResourceManifest((spec,)))
    fetcher = FakeFetcher(RemoteManifest((resource,)), {"ocr-model": archive.getvalue()})

    result = UpdateService(manager, fetcher).install("ocr-model")

    assert (result.path / "model.bin").read_bytes() == b"model"
    assert (result.path / "old.bin").exists() is False


def test_github_release_fetcher_reads_inline_manifest_and_streams_download(
    tmp_path: Path,
) -> None:
    payload = b"artifact"
    responses = {
        "https://api.github.com/repos/acme/hanly/releases/latest": _Response(
            b'{"tag_name":"v2","manifest":{"resources":[{"id":"krdict","version":"2","url":"https://download/krdict"}]}}'
        ),
        "https://download/krdict": _Response(payload, {"Content-Length": str(len(payload))}),
    }

    def opener(url: str, **_kwargs: Any) -> _Response:
        return responses[url]

    fetcher = GitHubReleaseFetcher("acme", "hanly", opener=opener)
    manifest = fetcher.fetch_manifest()
    destination = tmp_path / "artifact.bin"
    progress: list[DownloadProgress] = []
    fetcher.download(manifest["krdict"], destination, progress.append)

    assert destination.read_bytes() == payload
    assert progress[-1].completed == len(payload)


def test_github_release_fetcher_resolves_producer_asset_name(tmp_path: Path) -> None:
    payload = b"producer artifact"
    asset_name = "krdict-20260819-v1.sqlite3.zst"
    manifest = {
        "manifest_version": 1,
        "resources": {
            "krdict": {
                "asset_name": asset_name,
                "checksum": f"sha256:{_sha256(payload)}",
                "expected_entry_count": 1,
                "kind": "krdict",
                "schema_version": 1,
                "size": len(payload),
                "source_date": "2026-08-19",
                "version": "20260819-v1",
            }
        },
    }
    responses = {
        "https://api.github.com/repos/acme/hanly/releases/latest": _Response(
            json.dumps(
                {
                    "tag_name": "v1.0.0",
                    "assets": [
                        {
                            "name": "hanly-resources.json",
                            "browser_download_url": "https://download/manifest",
                        },
                        {
                            "name": asset_name,
                            "browser_download_url": "https://download/krdict",
                        },
                    ],
                }
            ).encode()
        ),
        "https://download/manifest": _Response(json.dumps(manifest).encode()),
        "https://download/krdict": _Response(payload, {"Content-Length": str(len(payload))}),
    }

    def opener(url: str, **_kwargs: Any) -> _Response:
        return responses[url]

    fetcher = GitHubReleaseFetcher("acme", "hanly", opener=opener)
    remote_manifest = fetcher.fetch_manifest()
    resource = remote_manifest["krdict"]
    destination = tmp_path / asset_name

    fetcher.download(resource, destination)

    assert resource.url is None
    assert resource.asset_name == asset_name
    assert destination.read_bytes() == payload


class _Response(io.BytesIO):
    def __init__(self, payload: bytes, headers: dict[str, str] | None = None) -> None:
        super().__init__(payload)
        self.headers = headers or {}


def _create_krdict_database(path: Path, headword: str, *, version: str = "1") -> None:
    source = path.with_suffix(path.suffix + ".zip")
    xml = f"""<LexicalResource><Lexicon>
<LexicalEntry att="id" val="1">
 <feat att="lexicalUnit" val="단어"/><Lemma><feat att="writtenForm" val="{headword}"/></Lemma>
 <Sense att="id" val="1"><feat att="definition" val="definition"/>
  <Equivalent><feat att="language" val="영어"/>
   <feat att="lemma" val="definition"/><feat att="definition" val="definition"/>
  </Equivalent>
 </Sense>
</LexicalEntry></Lexicon></LexicalResource>"""
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("fixture.xml", xml)
    build_database(
        source,
        path,
        source_date="fixture",
        resource_version=version,
        build_date="1970-01-01",
    )


def _directory_service(
    tmp_path: Path, *, checksum: str | None, archive: bytes | None = None
) -> tuple[UpdateService, Path]:
    destination = tmp_path / "models"
    destination.mkdir()
    (destination / "inference.pdiparams").write_bytes(b"active model")
    if archive is None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as bundle:
            bundle.writestr("inference.pdiparams", "replacement model")
        archive = buffer.getvalue()
    resource = RemoteResource(
        "models",
        "2",
        url="https://example.test/models.zip",
        checksum=checksum,
        kind="directory",
    )
    fetcher = FakeFetcher(RemoteManifest((resource,)), {"models": archive})
    manager = ResourceManager(
        ResourceManifest((ResourceSpec("models", destination, version="1", kind="directory"),))
    )
    return UpdateService(manager, fetcher), destination


def test_directory_resource_requires_a_checksum_before_activation(tmp_path: Path) -> None:
    """Directory deliveries carry the OCR models the engine loads and executes,
    so transport integrity alone must not activate them."""

    service, destination = _directory_service(tmp_path, checksum=None)

    with pytest.raises(ResourceUpdateError, match="must provide a checksum"):
        service.install("models")

    assert (destination / "inference.pdiparams").read_bytes() == b"active model"


def test_directory_resource_with_a_wrong_checksum_is_rejected(tmp_path: Path) -> None:
    service, destination = _directory_service(tmp_path, checksum=f"sha256:{'0' * 64}")

    with pytest.raises(ResourceUpdateError, match="checksum does not match"):
        service.install("models")

    assert (destination / "inference.pdiparams").read_bytes() == b"active model"
    assert sorted(p.name for p in destination.parent.iterdir()) == ["models"]


def test_directory_resource_with_a_valid_checksum_installs(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr("inference.pdiparams", "replacement model")
    archive = buffer.getvalue()
    service, destination = _directory_service(
        tmp_path, checksum=f"sha256:{_sha256(archive)}", archive=archive
    )

    result = service.install("models")

    assert result.path == destination.resolve()
    assert (destination / "inference.pdiparams").read_bytes() == b"replacement model"


def test_remote_resources_must_use_https(tmp_path: Path) -> None:
    del tmp_path
    RemoteResource("krdict", "2", url="https://example.test/db", kind="krdict")
    for rejected in (
        "http://example.test/db",
        "file:///etc/passwd",
        "ftp://example.test/db",
        "example.test/db",
    ):
        with pytest.raises(ResourceUpdateError, match="must be delivered over https"):
            RemoteResource("krdict", "2", url=rejected, kind="krdict")


def test_release_asset_urls_are_also_restricted_to_https() -> None:
    fetcher = GitHubReleaseFetcher("owner", "repository")

    with pytest.raises(ResourceUpdateError, match="must be delivered over https"):
        fetcher._open("http://example.test/asset")


def test_rollback_restores_the_known_good_copy_and_stays_idempotent(tmp_path: Path) -> None:
    """Rollback must restore, not swap: a rejected artifact never becomes the
    new last-known-good, and rolling back twice must not reinstall it."""

    service, manager, _fetcher = _service(tmp_path)
    destination = tmp_path / "krdict.sqlite"
    backup = destination.with_name(destination.name + ".last-known-good")

    service.install("krdict")
    assert _headword(destination) == "new"
    assert _headword(backup) == "known good"

    assert service.rollback("krdict") == destination.resolve()
    assert _headword(destination) == "known good"
    assert _headword(backup) == "known good"

    service.rollback("krdict")
    assert _headword(destination) == "known good"
    assert _headword(backup) == "known good"
    assert manager.validate()["krdict"].status.value == "VALID"


def _headword(path: Path) -> str:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return str(connection.execute("SELECT written_form FROM lemmas").fetchone()[0])
    finally:
        connection.close()


def test_a_redirect_cannot_downgrade_the_https_transport() -> None:
    """urllib blocks a redirect to file: but still follows http: and ftp:, so
    the policy has to be re-applied on every hop, not just the first URL."""

    from hanly_app.update_service import _HTTPSOnlyRedirectHandler

    handler = _HTTPSOnlyRedirectHandler()
    request = urllib.request.Request("https://example.test/asset")

    for rejected in ("http://example.test/asset", "ftp://example.test/asset"):
        with pytest.raises(ResourceUpdateError, match="must be delivered over https"):
            handler.redirect_request(request, None, 302, "Found", {}, rejected)


def test_checksum_verification_streams_multi_chunk_artifacts(tmp_path: Path) -> None:
    """The verifier must hash incrementally on every supported interpreter, so
    it is pinned against a payload larger than one read chunk rather than a
    stdlib helper that only exists from Python 3.11 onward."""

    from hanly_app.update_service import verify_checksum

    artifact = tmp_path / "artifact.bin"
    payload = b"\xa1\x9c" * (1024 * 1024)
    artifact.write_bytes(payload)

    verify_checksum(artifact, f"sha256:{_sha256(payload)}")
    verify_checksum(artifact, _sha256(payload).upper())
    verify_checksum(artifact, f"sha512:{hashlib.sha512(payload).hexdigest()}")

    with pytest.raises(ResourceUpdateError, match="checksum does not match"):
        verify_checksum(artifact, f"sha256:{'0' * 64}")


def test_checksum_verification_reports_unusable_algorithms_and_paths(tmp_path: Path) -> None:
    from hanly_app.update_service import verify_checksum

    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"payload")

    with pytest.raises(ResourceUpdateError, match="unsupported artifact checksum algorithm"):
        verify_checksum(artifact, "crc32:00000000")

    with pytest.raises(ResourceUpdateError, match="could not hash staged artifact"):
        verify_checksum(tmp_path / "missing.bin", f"sha256:{'0' * 64}")


def test_updates_are_not_offered_for_resources_this_install_never_declared(
    tmp_path: Path,
) -> None:
    """A release serves every backend, so its manifest can advertise PaddleOCR
    models to an EasyOCR install. Offering them would offer something ``install``
    then refuses, because it resolves destinations from the local manifest."""

    service, _manager, fetcher = _service(tmp_path)
    fetcher.manifest = RemoteManifest(
        (
            *fetcher.manifest,
            RemoteResource(
                "paddle_detection_model",
                "9",
                url="https://example.test/detection",
                kind="directory",
            ),
        )
    )

    availability = service.check_for_updates()

    assert [item.resource.resource_id for item in availability] == ["krdict"]


def _zstd_zeros_declaring_no_size(size: int) -> bytes:
    """Compress ``size`` zero bytes into a frame that declares no content size.

    Zeros compress to a few kilobytes, which is the shape of a decompression
    bomb; streaming keeps the uncompressed fixture out of the test's memory.
    """

    buffer = io.BytesIO()
    block = b"\0" * (4 * 1024 * 1024)
    with zstandard.ZstdCompressor(write_content_size=False).stream_writer(
        buffer, closefd=False
    ) as writer:
        remaining = size
        while remaining > 0:
            writer.write(block[:remaining])
            remaining -= min(remaining, len(block))
    return buffer.getvalue()


def test_a_zstd_bomb_is_refused_at_the_shipped_ceiling_without_writing_it_out(
    tmp_path: Path,
) -> None:
    """A frame that declares no size and keeps producing bytes past the ceiling
    is stopped mid-stream, so a compromised manifest cannot fill a user's disk.

    Nothing here is monkeypatched: the bound under test is the shipped one.
    """

    destination = tmp_path / "krdict.sqlite3"
    _create_krdict_database(destination, "known good")
    payload = _zstd_zeros_declaring_no_size(
        update_service._ZSTD_MAX_OUTPUT_BYTES + 8 * 1024 * 1024
    )
    resource = RemoteResource(
        "krdict",
        "2",
        url="https://example.test/krdict-2.sqlite3.zst",
        checksum=f"sha256:{_sha256(payload)}",
        kind="krdict",
        size=len(payload),
        schema_version=1,
        expected_entry_count=1,
        source_date="fixture",
    )
    fetcher = FakeFetcher(RemoteManifest((resource,)), {"krdict": payload})
    manager = ResourceManager(
        ResourceManifest((ResourceSpec("krdict", destination, version="1", kind="krdict"),))
    )

    with pytest.raises(ResourceUpdateError, match="decompression bound"):
        UpdateService(manager, fetcher).install("krdict")

    assert _headword(destination) == "known good"
    assert not tuple(tmp_path.glob(".*.install"))


def test_a_declared_size_beyond_the_ceiling_is_capped_rather_than_trusted(
    tmp_path: Path,
) -> None:
    """A frame header is attacker-controlled, so a declaration larger than
    anything Hanly ships buys no extra room."""

    # A hand-built header: magic, a descriptor selecting an 8-byte content size
    # with no window descriptor, then the declared size itself.
    header = b"\x28\xb5\x2f\xfd\xe0" + (8 * 1024**3).to_bytes(8, "little")
    archive = tmp_path / "resource.zst"
    archive.write_bytes(header)

    assert update_service._zstd_output_limit(archive) == update_service._ZSTD_MAX_OUTPUT_BYTES


def test_the_decompression_bound_comes_from_the_declared_frame_content_size(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "resource.zst"
    archive.write_bytes(zstandard.ZstdCompressor().compress(b"x" * 5000))

    assert update_service._zstd_output_limit(archive) == 5000


def test_a_frame_declaring_no_content_size_falls_back_to_the_fixed_ceiling(
    tmp_path: Path,
) -> None:
    """An undeclared size is the attacker-controlled case, so it is capped
    rather than trusted."""

    archive = tmp_path / "resource.zst"
    compressor = zstandard.ZstdCompressor(write_content_size=False)
    archive.write_bytes(compressor.compress(b"x" * 5000))

    assert update_service._zstd_output_limit(archive) == update_service._ZSTD_MAX_OUTPUT_BYTES


def test_an_unreadable_zstd_header_is_a_resource_error_not_a_crash(tmp_path: Path) -> None:
    archive = tmp_path / "resource.zst"
    archive.write_bytes(b"not a frame")

    with pytest.raises(ResourceUpdateError, match="frame header"):
        update_service._zstd_output_limit(archive)


def test_an_object_form_manifest_entry_that_is_not_an_object_is_refused() -> None:
    """A remote manifest is the least trusted input here, so a malformed value
    must fail closed as a manifest error, not as an incidental TypeError."""

    with pytest.raises(RemoteManifestError, match="must be an object"):
        RemoteManifest.from_payload({"resources": {"krdict": 123}})


def test_a_directory_activation_survives_a_failed_cleanup_of_the_displaced_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Once the new tree is live, leftover data that will not delete is litter
    on disk, not a failed activation the caller should roll back."""

    from hanly_app import update_service as module

    destination = tmp_path / "models"
    destination.mkdir()
    (destination / "weights.bin").write_bytes(b"old")
    stage = tmp_path / "staged"
    stage.mkdir()
    (stage / "weights.bin").write_bytes(b"new")

    real_remove = module._remove_path
    calls: list[Path] = []

    def flaky_remove(path: Path) -> None:
        calls.append(path)
        # Only the post-swap discard of the displaced copy is made to fail.
        swapped = (destination / "weights.bin").read_bytes() == b"new"
        if swapped and path.name.startswith(".models."):
            raise PermissionError("directory is in use")
        real_remove(path)

    monkeypatch.setattr(module, "_remove_path", flaky_remove)

    backup = module.activate_path(stage, destination)

    assert (destination / "weights.bin").read_bytes() == b"new"
    assert backup is not None and (backup / "weights.bin").read_bytes() == b"old"


def test_a_failed_directory_swap_puts_the_previous_tree_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hanly_app import update_service as module

    destination = tmp_path / "models"
    destination.mkdir()
    (destination / "weights.bin").write_bytes(b"old")
    stage = tmp_path / "staged"
    stage.mkdir()
    (stage / "weights.bin").write_bytes(b"new")

    real_replace = os.replace
    seen: list[int] = []

    def failing_replace(source: Any, target: Any, **kwargs: Any) -> None:
        seen.append(1)
        # The first replace moves the live tree aside; the second is the swap.
        if len(seen) == 2:
            raise OSError("cannot move staged tree into place")
        real_replace(source, target, **kwargs)

    monkeypatch.setattr(module.os, "replace", failing_replace)

    with pytest.raises(OSError, match="cannot move staged tree"):
        module.activate_path(stage, destination)

    assert (destination / "weights.bin").read_bytes() == b"old"


def test_a_download_that_outgrows_its_declared_size_is_abandoned_mid_stream(
    tmp_path: Path,
) -> None:
    """The manifest size is an exact bound, so an oversized response is already
    wrong and is not written out in full before being rejected."""

    served = b"x" * (4 * 1024 * 1024)

    def opener(url: str, timeout: float | None = None) -> Any:
        return _StreamedResponse(served)

    fetcher = GitHubReleaseFetcher("owner", "repo", opener=opener)
    resource = RemoteResource(
        "krdict", "2", url="https://example.test/krdict.zst", size=1024, kind="krdict"
    )
    destination = tmp_path / "artifact.bin"

    with pytest.raises(ResourceUpdateError, match="exceeds its declared 1024 byte size"):
        fetcher.download(resource, destination)

    assert destination.stat().st_size <= 1024


def test_a_download_within_its_declared_size_is_written_in_full(tmp_path: Path) -> None:
    served = b"y" * 2048

    fetcher = GitHubReleaseFetcher(
        "owner", "repo", opener=lambda url, timeout=None: _StreamedResponse(served)
    )
    resource = RemoteResource(
        "krdict", "2", url="https://example.test/krdict.zst", size=len(served), kind="krdict"
    )
    destination = tmp_path / "artifact.bin"

    fetcher.download(resource, destination)

    assert destination.read_bytes() == served


class _StreamedResponse:
    """The tiny slice of an HTTP response the downloader reads."""

    def __init__(self, payload: bytes) -> None:
        self._stream = io.BytesIO(payload)
        self.headers = {"Content-Length": str(len(payload))}

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)

    def close(self) -> None:
        self._stream.close()
