from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import hanly.resource_manager as resource_manager_module
import pytest
from hanly.resource_manager import (
    ResourceManager,
    ResourceManifest,
    ResourceSpec,
    ResourceStatus,
    ResourceUnavailableError,
    SchemaSpec,
)


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


def test_krdict_schema_is_validated_locally(tmp_path: Path) -> None:
    database = tmp_path / "krdict.sqlite"
    _create_krdict_database(database)
    manager = ResourceManager(
        (ResourceSpec("krdict", database, version="1", kind="krdict"),)
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
    connection.commit()
    connection.close()
