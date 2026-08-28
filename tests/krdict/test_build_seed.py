"""Production seed builder tests over literal official-shape XML."""
# ruff: noqa: E501 -- literal official-shape XML is intentionally unwrapped.

from __future__ import annotations

import sqlite3
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from tools.krdict.build_seed import BuildError, build_database


def _source(path: Path) -> Path:
    xml = """<LexicalResource><Lexicon>
<LexicalEntry att="id" val="10">
 <feat att="lexicalUnit" val="단어"/><feat att="homonym_number" val="0"/>
 <feat att="partOfSpeech" val="명사"/><feat att="vocabularyLevel" val="없음"/>
 <Lemma><feat att="writtenForm" val="책"/></Lemma>
 <WordForm><feat att="type" val="발음"/><feat att="pronunciation" val="책"/></WordForm>
 <feat att="semanticCategory" val="교육"/>
 <Sense att="id" val="100"><feat att="definition" val="글을 묶은 물건."/>
  <SenseExample><feat att="type" val="문장"/><feat att="example" val="책을 읽다."/></SenseExample>
  <Equivalent><feat att="language" val="영어"/><feat att="lemma" val="book"/><feat att="definition" val="A written work."/></Equivalent>
 </Sense>
</LexicalEntry>
</Lexicon></LexicalResource>""".encode()
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("one.xml", xml)
    return path


def test_builder_populates_every_scope_metadata_indexes_and_analyze(tmp_path: Path) -> None:
    database = tmp_path / "krdict.sqlite3"

    result = build_database(
        _source(tmp_path / "source.zip"),
        database,
        source_date="2026-08-19",
        resource_version="20260819-v1",
        build_date="2026-08-25",
    )

    assert result.entry_count == 1
    assert result.sense_count == 1
    assert result.sanitized_byte_count == 0
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT source, source_id, lexical_unit, homonym_number, vocabulary_level FROM entries"
        ).fetchone() == ("krdict", 10, "단어", 0, "없음")
        assert connection.execute(
            "SELECT written_form, variant, is_primary FROM lemmas"
        ).fetchone() == ("책", None, 1)
        assert connection.execute(
            "SELECT source_sense_id, sense_order, korean_definition FROM senses"
        ).fetchone() == (100, 1, "글을 묶은 물건.")
        assert connection.execute(
            "SELECT language, lemma, definition FROM translations"
        ).fetchone() == ("en", "book", "A written work.")
        assert connection.execute(
            "SELECT example_group, example_order, type, text FROM examples"
        ).fetchone() == (1, 1, "문장", "책을 읽다.")
        assert connection.execute(
            "SELECT type, written_form, pronunciation FROM word_forms"
        ).fetchone() == ("발음", None, "책")
        assert connection.execute("SELECT type, value FROM categories").fetchone() == (
            "semantic",
            "교육",
        )
        metadata = dict(connection.execute("SELECT key, value FROM resource_metadata"))
        assert metadata == {
            "build_date": "2026-08-25",
            "entry_count": "1",
            "resource_version": "20260819-v1",
            "schema_version": "1",
            "sense_count": "1",
            "source": "krdict",
            "source_date": "2026-08-19",
        }
        assert connection.execute(
            "SELECT count(*) FROM sqlite_stat1"
        ).fetchone()[0] > 0


def test_builder_is_byte_deterministic_and_preserves_previous_output_on_failure(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path / "source.zip")
    database = tmp_path / "krdict.sqlite3"
    arguments = dict(
        source_date="2026-08-19",
        resource_version="20260819-v1",
        build_date="2026-08-25",
    )
    build_database(source, database, **arguments)
    first = database.read_bytes()

    build_database(source, database, **arguments)
    assert database.read_bytes() == first

    broken = tmp_path / "broken.zip"
    with zipfile.ZipFile(broken, "w") as archive:
        archive.writestr("bad.xml", b"<broken>")
    with pytest.raises(BuildError):
        build_database(broken, database, **arguments)
    assert database.read_bytes() == first
    assert not tuple(tmp_path.glob(".krdict.sqlite3.*.tmp"))


def test_builder_preserves_distinct_entries_that_reuse_raw_source_id(tmp_path: Path) -> None:
    """Removing either row would lose official base-word/idiom source data."""

    xml = """<LexicalResource><Lexicon>
<LexicalEntry att="id" val="77610">
 <feat att="lexicalUnit" val="단어"/><Lemma><feat att="writtenForm" val="첫"/></Lemma>
 <Sense att="id" val="1"><feat att="definition" val="맨 처음의."/></Sense>
</LexicalEntry>
<LexicalEntry att="id" val="77610">
 <feat att="lexicalUnit" val="관용구"/><Lemma><feat att="writtenForm" val="첫 단추를 끼우다"/></Lemma>
 <Sense att="id" val="1"><feat att="definition" val="일을 시작하다."/></Sense>
</LexicalEntry>
</Lexicon></LexicalResource>"""
    source = tmp_path / "reused-id.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("reused.xml", xml)

    database = tmp_path / "krdict.sqlite3"
    build_database(
        source,
        database,
        source_date="2026-08-19",
        resource_version="20260819-v1",
        build_date="2026-08-25",
    )

    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            """SELECT e.id, e.source_id, e.lexical_unit, l.written_form
               FROM entries AS e JOIN lemmas AS l ON l.entry_id = e.id
               ORDER BY e.id"""
        ).fetchall()
    assert rows == [
        (1, 77610, "단어", "첫"),
        (2, 77610, "관용구", "첫 단추를 끼우다"),
    ]


def test_builder_direct_script_entry_point_does_not_shadow_stdlib_inspect() -> None:
    result = subprocess.run(
        [sys.executable, "tools/krdict/build_seed.py", "--help"],
        cwd=Path(__file__).parents[2],
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert b"--resource-version" in result.stdout
