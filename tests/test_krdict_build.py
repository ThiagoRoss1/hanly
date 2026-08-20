"""Focused HAN-8 tests for deterministic KRDICT source processing."""

import sqlite3

import pytest
from hanly.krdict_build import (
    KRDICT_SCHEMA_MARKER,
    KRDICT_SCHEMA_VERSION,
    build_krdict_database,
)


def _write_source(path) -> None:
    path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<dictionary>
  <entry>
    <headword> 먹다 </headword>
    <part_of_speech>동사</part_of_speech>
    <sense>
      <translation><language>English</language><trans_dfn>to eat</trans_dfn></translation>
    </sense>
  </entry>
  <entry>
    <word>책</word>
    <pos>명사</pos>
    <sense><translation><language>en</language><trans_dfn>a book</trans_dfn></translation></sense>
  </entry>
</dictionary>
""",
        encoding="utf-8",
    )


def test_build_creates_versioned_indexed_sqlite_artifact(tmp_path) -> None:
    source = tmp_path / "krdict.xml"
    database = tmp_path / "krdict.sqlite3"
    _write_source(source)

    result = build_krdict_database(source, database)

    assert result == database
    with sqlite3.connect(database) as connection:
        metadata = dict(connection.execute("SELECT key, value FROM metadata"))
        assert metadata["schema_marker"] == KRDICT_SCHEMA_MARKER
        assert metadata["schema_version"] == str(KRDICT_SCHEMA_VERSION)
        assert metadata["source_language"] == "ko"
        assert metadata["target_language"] == "en"
        assert connection.execute(
            "SELECT headword, part_of_speech FROM entries ORDER BY headword"
        ).fetchall() == [("먹다", "동사"), ("책", "명사")]
        assert connection.execute(
            "SELECT definition FROM definitions ORDER BY entry_id, ordinal"
        ).fetchall() == [("to eat",), ("a book",)]

        indexes = {
            row[1]
            for row in connection.execute("PRAGMA index_list('entries')")
        }
        assert "idx_entries_headword" in indexes


def test_build_replaces_existing_artifact_deterministically(tmp_path) -> None:
    source = tmp_path / "krdict.xml"
    database = tmp_path / "krdict.sqlite3"
    _write_source(source)

    build_krdict_database(source, database)
    first = database.read_bytes()
    build_krdict_database(source, database)

    assert database.read_bytes() == first


def test_build_rejects_xml_without_english_definitions(tmp_path) -> None:
    source = tmp_path / "krdict.xml"
    source.write_text(
        "<dictionary><entry><headword>책</headword>"
        "<definition lang='ko'>책</definition></entry></dictionary>",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="English definition"):
        build_krdict_database(source, tmp_path / "krdict.sqlite3")
