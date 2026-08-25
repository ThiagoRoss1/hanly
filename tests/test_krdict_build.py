"""Focused HAN-8 tests for deterministic KRDICT source processing."""

import sqlite3
import tracemalloc

import pytest
from hanly.krdict_build import (
    KRDICT_SCHEMA_MARKER,
    KRDICT_SCHEMA_VERSION,
    build_krdict_database,
    build_krdict_report,
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


def test_an_entry_without_an_english_definition_is_skipped_not_fatal(tmp_path) -> None:
    """The published dump contains Korean-only entries. Aborting on the first
    one would fail a long build over normal data."""

    source = tmp_path / "krdict.xml"
    source.write_text(
        "<dictionary>"
        "<entry><headword>책</headword><translation><language>English</language>"
        "<trans_dfn>book</trans_dfn></translation></entry>"
        "<entry><headword>바다</headword><definition lang='ko'>바다</definition></entry>"
        "<entry><headword>읽다</headword><translation><language>English</language>"
        "<trans_dfn>to read</trans_dfn></translation></entry>"
        "</dictionary>",
        encoding="utf-8",
    )

    result = build_krdict_report(source, tmp_path / "krdict.sqlite3")

    assert result.entry_count == 2
    assert result.definition_count == 2
    assert result.skipped_without_english == 1


def test_a_source_with_no_usable_entry_still_fails_loudly(tmp_path) -> None:
    """Zero usable entries means the wrong file or the wrong element names,
    which must not be mistaken for a successful build."""

    source = tmp_path / "krdict.xml"
    source.write_text(
        "<dictionary>"
        "<entry><headword>책</headword><definition lang='ko'>책</definition></entry>"
        "<entry><headword>바다</headword><definition lang='ko'>바다</definition></entry>"
        "</dictionary>",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="English definition"):
        build_krdict_report(source, tmp_path / "krdict.sqlite3")


def test_records_are_streamed_rather_than_held_as_one_document(tmp_path) -> None:
    """A whole parsed KRDICT dump does not fit comfortably in memory, so the
    parser must not retain records it has finished with."""

    source = tmp_path / "krdict.xml"
    entries = "".join(
        f"<entry><headword>단어{index}</headword><translation>"
        f"<language>English</language><trans_dfn>word {index}</trans_dfn>"
        "</translation></entry>"
        for index in range(2000)
    )
    source.write_text(f"<dictionary>{entries}</dictionary>", encoding="utf-8")

    tracemalloc.start()
    try:
        result = build_krdict_report(source, tmp_path / "krdict.sqlite3")
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert result.entry_count == 2000
    # Generous, but far below what retaining 2000 parsed subtrees would cost.
    assert peak < 8_000_000
