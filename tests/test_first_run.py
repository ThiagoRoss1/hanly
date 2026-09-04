from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path

import hanly_app.first_run as first_run
import pytest
from hanly.resource_manager import ResourceManager
from hanly_app.first_run import (
    LOCAL_KRDICT_VARIABLE,
    PUBLIC_REPOSITORY_NAME,
    PUBLIC_REPOSITORY_OWNER,
    FirstRunError,
    provision_runtime_config,
)
from hanly_app.runtime import load_runtime
from hanly_app.update_service import (
    DownloadProgress,
    RemoteManifest,
    RemoteResource,
    UpdateService,
    UpdateServiceError,
)

from tests.hanly_fixtures.krdict import build_fixture_krdict


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _krdict_database() -> bytes:
    with tempfile.TemporaryDirectory(prefix="hanly-bootstrap-fixture-") as directory:
        path = build_fixture_krdict(Path(directory))
        return path.read_bytes()


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
    payloads = {"krdict": _krdict_database()} if include_krdict else {}
    resources = [
        RemoteResource(
            resource_id,
            "fixture-v1",
            url=f"https://example.test/{resource_id}",
            checksum=f"sha256:{_sha256(payload)}",
            kind="krdict",
            asset_name=f"{resource_id}.artifact",
        )
        for resource_id, payload in payloads.items()
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

    result = provision_runtime_config(config, fetcher=fetcher)

    assert result == config.resolve()
    payload = json.loads(config.read_text(encoding="utf-8"))
    assert payload["updates"]["github"] == {
        "owner": PUBLIC_REPOSITORY_OWNER,
        "repository": PUBLIC_REPOSITORY_NAME,
        "tag": "latest",
        "manifest_asset": "hanly-resources.json",
    }
    # EasyOCR resolves its own models, so a first run provisions only KRDICT.
    assert set(payload["resources"]) == {"krdict"}
    assert fetcher.downloads == ["krdict"]
    payload_versions = {
        resource_id: value["installed_version"]
        for resource_id, value in payload["resources"].items()
    }
    assert payload_versions == {"krdict": "fixture-v1"}
    runtime = load_runtime(config)
    assert runtime.resource_manager.all_valid
    assert all(
        not update.available
        for update in UpdateService(runtime.resource_manager, fetcher).check_for_updates()
    )


def test_invalid_extra_resource_blocks_required_first_run_repair(
    tmp_path: Path,
) -> None:
    config = tmp_path / "runtime.json"
    config.write_text(
        json.dumps(
            {
                "resources": {
                    "krdict": {"kind": "krdict", "path": "krdict.sqlite3"},
                    "extra": {"kind": "file", "path": "missing-extra.bin"},
                }
            }
        ),
        encoding="utf-8",
    )
    fetcher = _fetcher()

    with pytest.raises(FirstRunError, match="extra"):
        provision_runtime_config(config, fetcher=fetcher)

    assert fetcher.downloads == []


def test_repeat_launch_starts_without_contacting_the_release_channel(
    tmp_path: Path,
) -> None:
    """Healthy resources are enough to start. Optional update availability is
    the update coordinator's asynchronous job, not a startup network wait."""

    config = tmp_path / "runtime.json"
    provision_runtime_config(config, fetcher=_fetcher())

    second_fetcher = _fetcher()
    provision_runtime_config(config, fetcher=second_fetcher)

    assert second_fetcher.fetch_count == 0
    assert second_fetcher.downloads == []


def test_a_healthy_launch_never_constructs_a_fetcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An offline user whose dictionary is already installed must start. With
    every resource valid there is nothing to obtain, so no fetcher is built and
    no name is resolved -- not even to be told the network is unavailable."""

    config = tmp_path / "runtime.json"
    provision_runtime_config(config, fetcher=_fetcher())

    def offline(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("a healthy launch must not reach for the network")

    monkeypatch.setattr(first_run, "_public_release_fetcher", offline)
    monkeypatch.setattr(first_run, "_local_seed_fetcher", offline)

    assert provision_runtime_config(config) == config.resolve()


def test_first_run_reports_user_facing_resource_phases(tmp_path: Path) -> None:
    statuses: list[str] = []

    provision_runtime_config(
        tmp_path / "runtime.json",
        fetcher=_fetcher(),
        on_status=statuses.append,
    )

    assert statuses == [
        "Preparing Hanly...",
        "Checking resources...",
        "Downloading Korean dictionary...",
        "Verifying...",
        "Installing...",
        "Ready",
    ]


def test_missing_release_resource_reports_repository_and_resource(tmp_path: Path) -> None:
    config = tmp_path / "runtime.json"

    with pytest.raises(
        FirstRunError,
        match=f"{PUBLIC_REPOSITORY_OWNER}/{PUBLIC_REPOSITORY_NAME}.*krdict",
    ):
        provision_runtime_config(config, fetcher=_fetcher(include_krdict=False))

    assert config.is_file()
    assert not (tmp_path / "krdict" / "krdict.sqlite3").exists()


def test_existing_invalid_config_is_provisioned_without_rewriting_user_settings(
    tmp_path: Path,
) -> None:
    config = tmp_path / "runtime.json"
    provision_runtime_config(config, fetcher=_fetcher())
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["resources"]["krdict"]["path"] = "custom/dictionary.sqlite3"
    payload["operator_note"] = "keep this setting"
    payload["resources"]["krdict"]["version"] = "fixture-v1"
    payload["resources"]["krdict"].pop("installed_version")
    config.write_text(json.dumps(payload), encoding="utf-8")

    fetcher = _fetcher()
    provision_runtime_config(config, fetcher=fetcher)

    saved = json.loads(config.read_text(encoding="utf-8"))
    assert saved["resources"]["krdict"]["path"] == "custom/dictionary.sqlite3"
    assert saved["operator_note"] == "keep this setting"
    assert saved["resources"]["krdict"]["version"] == "fixture-v1"
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

    with pytest.raises(FirstRunError, match="incompatible resource kind.*krdict"):
        provision_runtime_config(config, fetcher=fetcher)

    assert fetcher.downloads == []


def test_an_invalid_extra_resource_fails_bootstrap_rather_than_startup(
    tmp_path: Path,
) -> None:
    """``load_runtime`` applies the same all-valid rule, so passing here only
    moves the same failure past the point where bootstrap could repair it."""

    config = tmp_path / "runtime.json"
    provision_runtime_config(config, fetcher=_fetcher())
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["resources"]["operator_asset"] = {"path": "missing.asset", "kind": "file"}
    config.write_text(json.dumps(payload), encoding="utf-8")

    offline = _fetcher()
    with pytest.raises(FirstRunError, match="resources are invalid.*operator_asset"):
        provision_runtime_config(config, fetcher=offline)

    assert offline.fetch_count == 0


def test_an_unreachable_release_channel_points_at_the_local_alternative(
    tmp_path: Path,
) -> None:
    """A first run with no dictionary and no reachable channel cannot start.
    The message an offline user sees must say what to do, and must say the
    problem is one-time rather than reading as a broken application."""

    class _Unreachable:
        def fetch_manifest(self) -> RemoteManifest:
            raise UpdateServiceError("could not read remote metadata: HTTP Error 404")

        def download(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("nothing should be downloaded")

    with pytest.raises(FirstRunError) as failure:
        provision_runtime_config(tmp_path / "runtime.json", fetcher=_Unreachable())

    message = str(failure.value)

    assert LOCAL_KRDICT_VARIABLE in message
    assert "network" in message
    assert "later launches start offline" in message


def test_a_local_database_provisions_a_first_run_without_the_release_channel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A built database is installed through the same staging, checksum, and
    activation path a download takes, so no release has to exist yet."""

    seed_directory = tmp_path / "seed"
    seed_directory.mkdir()
    seed = build_fixture_krdict(seed_directory)
    monkeypatch.setenv(LOCAL_KRDICT_VARIABLE, str(seed))
    config = tmp_path / "runtime.json"

    provision_runtime_config(config)

    payload = json.loads(config.read_text(encoding="utf-8"))
    assert payload["resources"]["krdict"]["installed_version"] == "fixture-v1"
    installed = config.parent / payload["resources"]["krdict"]["path"]
    assert installed.read_bytes() == seed.read_bytes()
    assert load_runtime(config).resource_manager.all_valid


def test_a_named_local_database_that_does_not_exist_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(LOCAL_KRDICT_VARIABLE, str(tmp_path / "absent.sqlite3"))

    with pytest.raises(FirstRunError, match=LOCAL_KRDICT_VARIABLE):
        provision_runtime_config(tmp_path / "runtime.json")


def test_an_install_records_its_version_and_identity_in_one_atomic_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both facts describe the same installed bytes. No intermediate manifest
    may name a version whose identity has not been recorded alongside it."""

    config = tmp_path / "runtime.json"
    snapshots: list[dict[str, object]] = []
    original = first_run._write_json_atomically

    def record(path: Path, payload: object) -> None:
        assert isinstance(payload, Mapping)
        entry = payload["resources"]["krdict"]
        if isinstance(entry, Mapping) and "installed_version" in entry:
            snapshots.append(dict(entry))
        original(path, payload)

    monkeypatch.setattr(first_run, "_write_json_atomically", record)

    provision_runtime_config(config, fetcher=_fetcher())

    assert snapshots, "the activation was never recorded"
    assert all(entry.get("verified_identity") for entry in snapshots)
    payload = json.loads(config.read_text(encoding="utf-8"))
    krdict = payload["resources"]["krdict"]
    installed = config.parent / krdict["path"]
    status = installed.stat()
    assert krdict["installed_version"] == "fixture-v1"
    assert krdict["verified_identity"] == f"{status.st_size}:{status.st_mtime_ns}"


def test_the_launch_after_an_install_skips_the_sqlite_integrity_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The installer already scanned these exact bytes, and the recorded
    identity still describes them, so startup pays for no second full-file read."""

    config = tmp_path / "runtime.json"
    provision_runtime_config(config, fetcher=_fetcher())

    scans: list[Path] = []
    monkeypatch.setattr(
        ResourceManager, "_validate_integrity", staticmethod(lambda path: scans.append(path))
    )

    assert load_runtime(config).resource_manager.all_valid
    assert scans == []


def test_a_replaced_database_re_earns_the_integrity_scan_on_the_next_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The recorded identity is a claim about specific bytes, not a permanent
    exemption: anything that changes the file spends the check again."""

    config = tmp_path / "runtime.json"
    provision_runtime_config(config, fetcher=_fetcher())
    payload = json.loads(config.read_text(encoding="utf-8"))
    installed = config.parent / payload["resources"]["krdict"]["path"]
    os.utime(installed, ns=(0, 0))

    scans: list[Path] = []
    monkeypatch.setattr(
        ResourceManager, "_validate_integrity", staticmethod(lambda path: scans.append(path))
    )

    load_runtime(config)

    assert scans == [installed.resolve()]
