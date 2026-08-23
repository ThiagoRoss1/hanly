from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import zipfile
from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from hanly_app.resource_bootstrap import (
    PUBLIC_REPOSITORY_NAME,
    PUBLIC_REPOSITORY_OWNER,
    RuntimeBootstrapError,
    bootstrap_runtime_config,
)
from hanly_app.runtime import load_runtime
from hanly_app.update_service import (
    DownloadProgress,
    RemoteManifest,
    RemoteResource,
    UpdateService,
)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _model_archive(name: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("inference.pdiparams", f"{name} model")
    return buffer.getvalue()


def _krdict_database() -> bytes:
    path = Path(__file__).with_name("_bootstrap-fixture.sqlite3")
    connection = sqlite3.connect(path)
    try:
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
            INSERT INTO entries(id, headword) VALUES (1, '책');
            INSERT INTO definitions VALUES (1, 1, 'book');
            """
        )
        connection.commit()
        return path.read_bytes()
    finally:
        connection.close()
        path.unlink(missing_ok=True)


@dataclass
class _Fetcher:
    manifest: RemoteManifest
    payloads: dict[str, bytes]
    fail_resource: str | None = None
    fetch_count: int = 0
    downloads: list[str] | None = None

    def __post_init__(self) -> None:
        self.downloads = []

    def fetch_manifest(self) -> RemoteManifest:
        self.fetch_count += 1
        return self.manifest

    def download(
        self,
        resource: RemoteResource,
        destination: Path,
        on_progress: object = None,
    ) -> None:
        assert self.downloads is not None
        self.downloads.append(resource.resource_id)
        destination.write_bytes(self.payloads[resource.resource_id])
        if resource.resource_id == self.fail_resource:
            raise OSError("controlled interruption")
        if callable(on_progress):
            on_progress(DownloadProgress(resource.resource_id, "complete", 1, 1))


def _fetcher(*, include_krdict: bool = True, fail_resource: str | None = None) -> _Fetcher:
    payloads = {
        "paddle_detection_model": _model_archive("detection"),
        "paddle_recognition_model": _model_archive("recognition"),
        "krdict": _krdict_database(),
    }
    versions = {
        "paddle_detection_model": "2026.08",
        "paddle_recognition_model": "v3.2.1",
        "krdict": "2025-12",
    }
    resources = [
        RemoteResource(
            resource_id,
            versions[resource_id],
            url=f"https://example.test/{resource_id}",
            checksum=f"sha256:{_sha256(payload)}",
            kind="directory" if resource_id != "krdict" else "krdict",
            asset_name=f"{resource_id}.artifact",
        )
        for resource_id, payload in payloads.items()
        if include_krdict or resource_id != "krdict"
    ]
    return _Fetcher(
        RemoteManifest(tuple(resources), release="2026.08"),
        payloads,
        fail_resource=fail_resource,
    )


def test_first_run_writes_production_config_and_installs_required_resources(
    tmp_path: Path,
) -> None:
    config = tmp_path / "Hanly" / "runtime.json"
    fetcher = _fetcher()

    result = bootstrap_runtime_config(config, fetcher=fetcher)

    assert result == config.resolve()
    payload = json.loads(config.read_text(encoding="utf-8"))
    assert payload["updates"]["github"] == {
        "owner": PUBLIC_REPOSITORY_OWNER,
        "repository": PUBLIC_REPOSITORY_NAME,
        "tag": "latest",
        "manifest_asset": "hanly-resources.json",
    }
    assert set(payload["resources"]) == {
        "paddle_detection_model",
        "paddle_recognition_model",
        "krdict",
    }
    assert fetcher.downloads == [
        "paddle_detection_model",
        "paddle_recognition_model",
        "krdict",
    ]
    payload_versions = {
        resource_id: value["installed_version"]
        for resource_id, value in payload["resources"].items()
    }
    assert payload_versions == {
        "paddle_detection_model": "2026.08",
        "paddle_recognition_model": "v3.2.1",
        "krdict": "2025-12",
    }
    runtime = load_runtime(config)
    assert runtime.resource_manager.all_valid
    assert all(
        not update.available
        for update in UpdateService(runtime.resource_manager, fetcher).check_for_updates()
    )


def test_repeat_launch_skips_remote_provisioning_after_resources_are_valid(
    tmp_path: Path,
) -> None:
    config = tmp_path / "runtime.json"
    first_fetcher = _fetcher()
    bootstrap_runtime_config(config, fetcher=first_fetcher)

    second_fetcher = _fetcher()
    bootstrap_runtime_config(config, fetcher=second_fetcher)

    assert second_fetcher.fetch_count == 0
    assert second_fetcher.downloads == []


def test_missing_release_resource_reports_repository_and_resource(tmp_path: Path) -> None:
    config = tmp_path / "runtime.json"

    with pytest.raises(
        RuntimeBootstrapError,
        match=f"{PUBLIC_REPOSITORY_OWNER}/{PUBLIC_REPOSITORY_NAME}.*krdict",
    ):
        bootstrap_runtime_config(config, fetcher=_fetcher(include_krdict=False))

    assert config.is_file()
    assert not (tmp_path / "krdict" / "krdict.sqlite3").exists()


def test_partial_provisioning_records_each_prior_activation_for_retry(tmp_path: Path) -> None:
    config = tmp_path / "runtime.json"
    interrupted = _fetcher(fail_resource="krdict")

    with pytest.raises(RuntimeBootstrapError, match="krdict"):
        bootstrap_runtime_config(config, fetcher=interrupted)

    partial = json.loads(config.read_text(encoding="utf-8"))
    assert partial["resources"]["paddle_detection_model"]["installed_version"] == "2026.08"
    assert partial["resources"]["paddle_recognition_model"]["installed_version"] == "v3.2.1"
    assert "installed_version" not in partial["resources"]["krdict"]

    retry = _fetcher()
    bootstrap_runtime_config(config, fetcher=retry)

    assert retry.downloads == ["krdict"]


def test_existing_invalid_config_is_provisioned_without_rewriting_user_settings(
    tmp_path: Path,
) -> None:
    config = tmp_path / "runtime.json"
    bootstrap_runtime_config(config, fetcher=_fetcher())
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["resources"]["krdict"]["path"] = "custom/dictionary.sqlite3"
    payload["operator_note"] = "keep this setting"
    payload["resources"]["krdict"]["version"] = "1"
    payload["resources"]["krdict"].pop("installed_version")
    config.write_text(json.dumps(payload), encoding="utf-8")

    fetcher = _fetcher()
    bootstrap_runtime_config(config, fetcher=fetcher)

    saved = json.loads(config.read_text(encoding="utf-8"))
    assert saved["resources"]["krdict"]["path"] == "custom/dictionary.sqlite3"
    assert saved["operator_note"] == "keep this setting"
    assert saved["resources"]["krdict"]["version"] == "1"
    assert "installed_version" not in saved["resources"]["krdict"]
    assert (tmp_path / "custom" / "dictionary.sqlite3").is_file()


def test_a_manifest_advertising_the_wrong_kind_is_refused_before_any_download(
    tmp_path: Path,
) -> None:
    config = tmp_path / "runtime.json"
    fetcher = _fetcher()
    krdict = next(item for item in fetcher.manifest if item.resource_id == "krdict")
    fetcher.manifest = RemoteManifest(
        tuple(item for item in fetcher.manifest if item.resource_id != "krdict")
        + (replace(krdict, kind="file"),),
        release="2026.08",
    )

    with pytest.raises(RuntimeBootstrapError, match="incompatible resource kind.*krdict"):
        bootstrap_runtime_config(config, fetcher=fetcher)

    assert fetcher.downloads == []


def test_an_invalid_extra_resource_fails_bootstrap_rather_than_startup(
    tmp_path: Path,
) -> None:
    """``load_runtime`` applies the same all-valid rule, so passing here only
    moves the same failure past the point where bootstrap could repair it."""

    config = tmp_path / "runtime.json"
    bootstrap_runtime_config(config, fetcher=_fetcher())
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["resources"]["operator_asset"] = {"path": "missing.asset", "kind": "file"}
    config.write_text(json.dumps(payload), encoding="utf-8")

    offline = _fetcher()
    with pytest.raises(RuntimeBootstrapError, match="resources are invalid.*operator_asset"):
        bootstrap_runtime_config(config, fetcher=offline)

    assert offline.fetch_count == 0
