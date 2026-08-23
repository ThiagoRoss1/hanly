from __future__ import annotations

import hashlib
import io
import sqlite3
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from hanly.resource_manager import ResourceManager, ResourceManifest, ResourceSpec
from hanly_app.update_service import (
    DownloadProgress,
    GitHubReleaseFetcher,
    RemoteManifest,
    RemoteManifestError,
    RemoteResource,
    ResourceUpdateError,
    UpdateService,
)


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
        _create_krdict_database(updated, "new")
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

    connection = sqlite3.connect(destination)
    try:
        assert connection.execute("SELECT headword FROM entries").fetchone()[0] == "new"
    finally:
        connection.close()
    assert result.path == destination.resolve()
    assert result.backup_path == tmp_path / "krdict.sqlite.last-known-good"
    connection = sqlite3.connect(result.backup_path)
    try:
        assert connection.execute("SELECT headword FROM entries").fetchone()[0] == "known good"
    finally:
        connection.close()
    assert any(event.phase == "validating" for event in events)
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


class _Response(io.BytesIO):
    def __init__(self, payload: bytes, headers: dict[str, str] | None = None) -> None:
        super().__init__(payload)
        self.headers = headers or {}


def _create_krdict_database(path: Path, headword: str) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        PRAGMA user_version = 1;
        CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE entries (
            id INTEGER PRIMARY KEY,
            headword TEXT NOT NULL,
            part_of_speech TEXT
        );
        CREATE TABLE definitions (
            entry_id INTEGER NOT NULL,
            ordinal INTEGER NOT NULL,
            definition TEXT NOT NULL,
            PRIMARY KEY (entry_id, ordinal)
        );
        CREATE INDEX idx_entries_headword ON entries(headword);
        INSERT INTO metadata(key, value) VALUES
            ('schema_name', 'hanly.krdict'),
            ('schema_version', '1'),
            ('schema_marker', 'hanly.krdict-sqlite-v1'),
            ('source_language', 'ko'),
            ('target_language', 'en');
        """
    )
    connection.execute("INSERT INTO entries(id, headword) VALUES (1, ?)", (headword,))
    connection.execute("INSERT INTO definitions VALUES (1, 1, 'definition')")
    connection.commit()
    connection.close()


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
        return str(connection.execute("SELECT headword FROM entries").fetchone()[0])
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

    from hanly_app.update_service import _verify_checksum

    artifact = tmp_path / "artifact.bin"
    payload = b"\xa1\x9c" * (1024 * 1024)
    artifact.write_bytes(payload)

    _verify_checksum(artifact, f"sha256:{_sha256(payload)}")
    _verify_checksum(artifact, _sha256(payload).upper())
    _verify_checksum(artifact, f"sha512:{hashlib.sha512(payload).hexdigest()}")

    with pytest.raises(ResourceUpdateError, match="checksum does not match"):
        _verify_checksum(artifact, f"sha256:{'0' * 64}")


def test_checksum_verification_reports_unusable_algorithms_and_paths(tmp_path: Path) -> None:
    from hanly_app.update_service import _verify_checksum

    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"payload")

    with pytest.raises(ResourceUpdateError, match="unsupported artifact checksum algorithm"):
        _verify_checksum(artifact, "crc32:00000000")

    with pytest.raises(ResourceUpdateError, match="could not hash staged artifact"):
        _verify_checksum(tmp_path / "missing.bin", f"sha256:{'0' * 64}")
