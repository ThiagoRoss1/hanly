from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import hanly.resource_manager as resource_manager_module
import pytest
from hanly.resource_manager import (
    ResourceManager,
    ResourceManagerError,
    ResourceManifest,
    ResourceSpec,
    ResourceStatus,
    ResourceUnavailableError,
    SchemaSpec,
)

from tests.hanly_fixtures.krdict import build_fixture_krdict


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_valid_resource_exposes_metadata_path_and_configuration(tmp_path: Path) -> None:
    model = tmp_path / "model.bin"
    model.write_bytes(b"model")
    manager = ResourceManager(
        ResourceManifest(
            (
                ResourceSpec(
                    "ocr-model",
                    model,
                    version="1.2",
                    checksum=f"sha256:{_sha256(model)}",
                    configuration={"lang": "korean", "device": "cpu"},
                ),
            )
        )
    )

    metadata = manager.validate()

    assert metadata["ocr-model"].status is ResourceStatus.VALID
    assert metadata["ocr-model"].version == "1.2"
    assert metadata["ocr-model"].checksum == f"sha256:{_sha256(model)}"
    assert manager.validated_path("ocr-model") == model.resolve()
    assert manager.configuration("ocr-model") == {"lang": "korean", "device": "cpu"}
    validated = manager.validated_resource("ocr-model")
    assert validated.path == model.resolve()
    assert manager.validated_resources["ocr-model"] == validated


def test_missing_resource_is_reported_without_exposing_a_path(tmp_path: Path) -> None:
    missing = tmp_path / "missing.bin"
    manager = ResourceManager((ResourceSpec("ocr-model", missing, version="1.2"),))

    metadata = manager.validate()

    assert metadata["ocr-model"].status is ResourceStatus.MISSING
    assert metadata["ocr-model"].compatible is False
    with pytest.raises(ResourceUnavailableError):
        manager.validated_path("ocr-model")


def test_checksum_mismatch_is_incompatible(tmp_path: Path) -> None:
    model = tmp_path / "model.bin"
    model.write_bytes(b"model")
    manager = ResourceManager(
        (ResourceSpec("ocr-model", model, version="1.2", checksum="sha256:" + "0" * 64),)
    )

    metadata = manager.validate()

    assert metadata["ocr-model"].status is ResourceStatus.INCOMPATIBLE
    assert metadata["ocr-model"].checksum == f"sha256:{_sha256(model)}"


def test_unreadable_resource_is_incompatible_portably(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = tmp_path / "model.bin"
    model.write_bytes(b"model")
    monkeypatch.setattr(resource_manager_module.os, "access", lambda _path, _mode: False)
    manager = ResourceManager((ResourceSpec("ocr-model", model, version="1.2"),))

    metadata = manager.validate()

    assert metadata["ocr-model"].status is ResourceStatus.INCOMPATIBLE
    assert "unreadable" in manager.diagnostics("ocr-model")[0]


def test_version_file_mismatch_is_outdated(tmp_path: Path) -> None:
    model = tmp_path / "model.bin"
    version_file = tmp_path / "model.version"
    model.write_bytes(b"model")
    version_file.write_text("1.0\n", encoding="utf-8")
    manager = ResourceManager(
        (
            ResourceSpec(
                "ocr-model",
                model,
                version="2.0",
                version_file=version_file,
            ),
        )
    )

    metadata = manager.validate()

    assert metadata["ocr-model"].status is ResourceStatus.OUTDATED
    assert metadata["ocr-model"].version == "1.0"


def test_relative_paths_resolve_from_manager_base_not_process_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = tmp_path / "resource-bundle"
    base.mkdir()
    (base / "model.bin").write_bytes(b"base model")
    (base / "model.version").write_text("1.0\n", encoding="utf-8")

    cwd = tmp_path / "working-directory"
    cwd.mkdir()
    (cwd / "model.bin").write_bytes(b"wrong model")
    (cwd / "model.version").write_text("9.0\n", encoding="utf-8")
    monkeypatch.chdir(cwd)

    manager = ResourceManager(
        (
            ResourceSpec(
                "ocr-model",
                "model.bin",
                version="1.0",
                version_file="model.version",
            ),
        ),
        base_path=base,
    )

    metadata = manager.validate()

    assert manager.base_path == base.resolve()
    assert metadata["ocr-model"].status is ResourceStatus.VALID
    assert manager.validated_path("ocr-model") == (base / "model.bin").resolve()
    assert manager.validated_resource("ocr-model").path == manager.validated_path("ocr-model")


def test_relative_paths_without_a_base_are_refused_at_construction() -> None:
    # A malformed manifest is a configuration error, so it is refused before a
    # manager exists rather than part-way through a scan.
    with pytest.raises(ResourceManagerError, match="base_path") as excinfo:
        ResourceManager(
            (
                ResourceSpec(
                    "ocr-model",
                    "model.bin",
                    version_file="model.version",
                ),
                ResourceSpec("dictionary", "krdict.sqlite3"),
            )
        )

    message = str(excinfo.value)
    assert "ocr-model resource path" in message
    assert "ocr-model version_file" in message
    assert "dictionary resource path" in message


def test_validate_reports_resource_health_instead_of_raising(tmp_path: Path) -> None:
    # Resource health is normal operating state: one bad resource must not hide
    # the status of the others by aborting the scan.
    present = tmp_path / "model.bin"
    present.write_bytes(b"model")

    manager = ResourceManager(
        (
            ResourceSpec("present", present),
            ResourceSpec("absent", tmp_path / "missing.bin"),
            ResourceSpec("wrong-kind", present, kind="directory"),
            ResourceSpec("bad-checksum", present, checksum="sha256:" + "0" * 64),
        )
    )

    metadata = manager.validate()

    assert metadata["present"].status is ResourceStatus.VALID
    assert metadata["absent"].status is ResourceStatus.MISSING
    assert metadata["wrong-kind"].status is not ResourceStatus.VALID
    assert metadata["bad-checksum"].status is not ResourceStatus.VALID
    assert manager.diagnostics("wrong-kind") == ("resource is not a directory",)


def test_krdict_schema_is_validated_locally(tmp_path: Path) -> None:
    database = tmp_path / "krdict.sqlite"
    _create_krdict_database(database)
    manager = ResourceManager(
        (ResourceSpec("krdict", database, version="fixture-v1", kind="krdict"),)
    )

    metadata = manager.validate()

    assert metadata["krdict"].status is ResourceStatus.VALID
    assert manager.validated_path("krdict") == database.resolve()


def test_schema_mismatch_is_incompatible(tmp_path: Path) -> None:
    database = tmp_path / "krdict.sqlite"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    connection.commit()
    connection.close()
    manager = ResourceManager(
        (
            ResourceSpec(
                "krdict",
                database,
                version="1",
                schema=SchemaSpec(name="wrong.schema", version=1),
            ),
        )
    )

    metadata = manager.validate()

    assert metadata["krdict"].status is ResourceStatus.INCOMPATIBLE


def test_sqlite_integrity_failure_is_incompatible_with_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "krdict.sqlite"
    _create_krdict_database(database)

    def fail_integrity(_path: Path) -> None:
        raise ValueError(
            "PRAGMA quick_check returned malformed; "
            "PRAGMA integrity_check returned malformed"
        )

    monkeypatch.setattr(ResourceManager, "_validate_integrity", staticmethod(fail_integrity))
    manager = ResourceManager((ResourceSpec("krdict", database, kind="krdict"),))

    metadata = manager.validate()

    assert metadata["krdict"].status is ResourceStatus.INCOMPATIBLE
    assert "SQLite integrity check failed" in manager.diagnostics("krdict")[0]
    assert "PRAGMA quick_check" in manager.diagnostics("krdict")[0]


def test_valid_sqlite_resource_passes_integrity_check(tmp_path: Path) -> None:
    database = tmp_path / "resource.sqlite"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE values_table (value TEXT NOT NULL)")
    connection.commit()
    connection.close()

    manager = ResourceManager((ResourceSpec("resource", database, kind="sqlite"),))

    metadata = manager.validate()

    assert metadata["resource"].status is ResourceStatus.VALID


def test_resource_compatibility_requirements_are_normalized(tmp_path: Path) -> None:
    model = tmp_path / "model.bin"
    dictionary = tmp_path / "dictionary.bin"
    model.write_bytes(b"model")
    dictionary.write_bytes(b"dictionary")
    manager = ResourceManager(
        (
            ResourceSpec("ocr-model", model, version="1.0"),
            ResourceSpec(
                "dictionary",
                dictionary,
                version="1.0",
                compatible_with={"ocr-model": "2.0"},
            ),
        )
    )

    metadata = manager.validate()

    assert metadata["ocr-model"].status is ResourceStatus.VALID
    assert metadata["dictionary"].status is ResourceStatus.INCOMPATIBLE


def _create_krdict_database(path: Path) -> None:
    built = build_fixture_krdict(path.parent)
    built.replace(path)
