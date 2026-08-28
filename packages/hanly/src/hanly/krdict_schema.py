"""Single runtime contract for normalized KRDICT SQLite resources."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping

KRDICT_SCHEMA_NAME = "hanly.krdict"
KRDICT_SCHEMA_VERSION = 1

KRDICT_REQUIRED_COLUMNS: Mapping[str, tuple[str, ...]] = {
    "entries": (
        "id",
        "source",
        "source_id",
        "lexical_unit",
        "homonym_number",
        "part_of_speech",
        "vocabulary_level",
        "origin",
        "annotation",
    ),
    "lemmas": ("id", "entry_id", "written_form", "variant", "is_primary"),
    "senses": (
        "id",
        "entry_id",
        "source_sense_id",
        "sense_order",
        "korean_definition",
        "annotation",
        "syntactic_annotation",
    ),
    "translations": ("id", "sense_id", "language", "lemma", "definition"),
    "examples": (
        "id",
        "sense_id",
        "example_group",
        "example_order",
        "type",
        "text",
    ),
    "word_forms": ("id", "entry_id", "type", "written_form", "pronunciation"),
    "categories": ("id", "entry_id", "type", "value"),
    "related_forms": ("id", "entry_id", "type", "written_form", "target_source_id"),
    "syntactic_patterns": ("id", "sense_id", "pattern_order", "pattern"),
    "sense_relations": (
        "id",
        "sense_id",
        "type",
        "target_lemma",
        "target_source_id",
        "target_homonym_number",
    ),
    "resource_metadata": ("key", "value"),
}
KRDICT_REQUIRED_TABLES = tuple(KRDICT_REQUIRED_COLUMNS)
KRDICT_REQUIRED_INDEXES = (
    "idx_entries_source_source_id",
    "idx_lemmas_written_form_entry",
    "idx_lemmas_entry_id",
    "idx_word_forms_written_form_entry",
    "idx_word_forms_entry_id",
    "idx_translations_sense_language",
    "idx_categories_entry_id",
    "idx_related_forms_entry_id",
    "idx_sense_relations_sense_id",
)
KRDICT_REQUIRED_METADATA = (
    "schema_version",
    "resource_version",
    "source",
    "source_date",
    "build_date",
    "entry_count",
    "sense_count",
)


class KRDICTSchemaError(ValueError):
    """Raised when a database violates the normalized resource contract."""


def validate_krdict_connection(
    connection: sqlite3.Connection,
    *,
    expected_entry_count: int | None = None,
    expected_resource_version: str | None = None,
) -> dict[str, str]:
    """Validate schema, metadata, indexes, and cardinality invariants."""

    tables = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    missing_tables = set(KRDICT_REQUIRED_TABLES) - tables
    if missing_tables:
        raise KRDICTSchemaError(f"missing tables: {sorted(missing_tables)}")

    for table, required in KRDICT_REQUIRED_COLUMNS.items():
        actual = tuple(str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")'))
        if actual != required:
            raise KRDICTSchemaError(f"table {table} has incompatible columns")

    indexes = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND name NOT LIKE 'sqlite_%'"
        )
    }
    missing_indexes = set(KRDICT_REQUIRED_INDEXES) - indexes
    if missing_indexes:
        raise KRDICTSchemaError(f"missing indexes: {sorted(missing_indexes)}")

    metadata = {
        str(key): str(value)
        for key, value in connection.execute("SELECT key, value FROM resource_metadata")
    }
    missing_metadata = set(KRDICT_REQUIRED_METADATA) - metadata.keys()
    if missing_metadata:
        raise KRDICTSchemaError(f"missing metadata: {sorted(missing_metadata)}")
    if metadata["schema_version"] != str(KRDICT_SCHEMA_VERSION):
        raise KRDICTSchemaError("schema_version is incompatible")
    if metadata["source"] != "krdict":
        raise KRDICTSchemaError("source is not krdict")
    if (
        expected_resource_version is not None
        and metadata["resource_version"] != expected_resource_version
    ):
        raise KRDICTSchemaError("resource_version does not match the manifest")

    try:
        metadata_entry_count = int(metadata["entry_count"])
        metadata_sense_count = int(metadata["sense_count"])
    except ValueError as exc:
        raise KRDICTSchemaError("entry_count and sense_count must be integers") from exc
    actual_entry_count = int(connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0])
    actual_sense_count = int(connection.execute("SELECT COUNT(*) FROM senses").fetchone()[0])
    if metadata_entry_count != actual_entry_count:
        raise KRDICTSchemaError("entry_count does not match entries")
    if metadata_sense_count != actual_sense_count:
        raise KRDICTSchemaError("sense_count does not match senses")
    if expected_entry_count is not None and actual_entry_count != expected_entry_count:
        raise KRDICTSchemaError("entry_count does not match the remote manifest")

    missing_primary = int(
        connection.execute(
            """SELECT COUNT(*) FROM entries AS e
               WHERE NOT EXISTS (
                   SELECT 1 FROM lemmas AS l
                   WHERE l.entry_id = e.id AND l.is_primary = 1
               )"""
        ).fetchone()[0]
    )
    if missing_primary:
        raise KRDICTSchemaError(f"{missing_primary} entries have no primary lemma")
    return metadata


__all__ = [
    "KRDICT_REQUIRED_COLUMNS",
    "KRDICT_REQUIRED_INDEXES",
    "KRDICT_REQUIRED_METADATA",
    "KRDICT_REQUIRED_TABLES",
    "KRDICT_SCHEMA_NAME",
    "KRDICT_SCHEMA_VERSION",
    "KRDICTSchemaError",
    "validate_krdict_connection",
]
