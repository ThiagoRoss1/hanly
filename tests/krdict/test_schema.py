"""Contract tests for the exact production KRDICT schema."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from tools.krdict.build_seed import create_indexes, create_schema

EXPECTED_TABLES = {
    "entries",
    "lemmas",
    "senses",
    "translations",
    "examples",
    "word_forms",
    "categories",
    "related_forms",
    "syntactic_patterns",
    "sense_relations",
    "resource_metadata",
}

EXPECTED_INDEXES = {
    "idx_entries_source_source_id",
    "idx_lemmas_written_form_entry",
    "idx_lemmas_entry_id",
    "idx_word_forms_written_form_entry",
    "idx_word_forms_entry_id",
    "idx_translations_sense_language",
    "idx_categories_entry_id",
    "idx_related_forms_entry_id",
    "idx_sense_relations_sense_id",
}


def test_schema_has_exact_tables_constraints_and_post_load_indexes(tmp_path: Path) -> None:
    database = tmp_path / "krdict.sqlite3"
    with sqlite3.connect(database) as connection:
        create_schema(connection)
        create_indexes(connection)
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        indexes = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
            )
        }
        entry_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='entries'"
        ).fetchone()[0]

    assert tables == EXPECTED_TABLES
    assert indexes == EXPECTED_INDEXES
    assert "AUTOINCREMENT" not in entry_sql.upper()


def test_source_id_index_is_non_unique_and_preserves_reused_ids(tmp_path: Path) -> None:
    database = tmp_path / "krdict.sqlite3"
    with sqlite3.connect(database) as connection:
        create_schema(connection)
        create_indexes(connection)
        connection.execute(
            "INSERT INTO entries(id, source, source_id, lexical_unit) "
            "VALUES (1, 'krdict', 77610, '단어')"
        )
        connection.execute(
            "INSERT INTO entries(id, source, source_id, lexical_unit) "
            "VALUES (2, 'krdict', 77610, '관용구')"
        )
        index = connection.execute(
            "SELECT \"unique\" FROM pragma_index_list('entries') "
            "WHERE name = 'idx_entries_source_source_id'"
        ).fetchone()
        count = connection.execute(
            "SELECT COUNT(*) FROM entries WHERE source = 'krdict' AND source_id = 77610"
        ).fetchone()[0]

    assert index == (0,)
    assert count == 2
