"""Production validator tests over source-independent literal fixtures."""
# ruff: noqa: E501 -- literal official-shape XML is intentionally unwrapped.

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from tools.krdict.build_seed import build_database
from tools.krdict.validate_seed import ValidationError, validate_database


def _built_pair(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "source.zip"
    xml = """<LexicalResource><Lexicon>
<LexicalEntry att="id" val="77610">
 <feat att="lexicalUnit" val="단어"/><feat att="homonym_number" val="0"/>
 <feat att="vocabularyLevel" val="없음"/><Lemma><feat att="writtenForm" val="첫"/></Lemma>
 <Sense att="id" val="1"><feat att="definition" val="맨 처음의."/>
  <Equivalent><feat att="language" val="영어"/><feat att="lemma" val="first"/><feat att="definition" val="Of the very first."/></Equivalent>
 </Sense>
</LexicalEntry>
<LexicalEntry att="id" val="77610">
 <feat att="lexicalUnit" val="관용구"/><Lemma><feat att="writtenForm" val="첫 단추를 끼우다"/></Lemma>
 <Sense att="id" val="1"><feat att="definition" val="일을 시작하다."/></Sense>
</LexicalEntry>
<LexicalEntry att="id" val="9">
 <feat att="lexicalUnit" val="단어"/><Lemma><feat att="writtenForm" val="가다"/></Lemma>
 <WordForm><feat att="type" val="활용"/><feat att="writtenForm" val="가요"/></WordForm>
 <Sense att="id" val="2"><feat att="definition" val="이동하다."/></Sense>
</LexicalEntry>
</Lexicon></LexicalResource>"""
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("fixture.xml", xml)
    database = tmp_path / "krdict.sqlite3"
    build_database(
        source,
        database,
        source_date="2026-08-19",
        resource_version="20260819-v1",
        build_date="2026-08-25",
    )
    return source, database


def test_validator_reports_reused_source_ids_without_rejecting_them(tmp_path: Path) -> None:
    source, database = _built_pair(tmp_path)

    report = validate_database(
        database,
        source_path=source,
        expected_entries=3,
        expected_senses=3,
        expected_sanitized_bytes=0,
    )

    assert (
        report.source_entry_count,
        report.distinct_source_id_count,
        report.reused_source_id_count,
        report.maximum_source_id_reuse,
    ) == (3, 2, 1, 2)
    assert report.source_sense_count == 3
    assert report.row_counts["translations"] == 1
    assert report.integrity_check == "ok"
    assert report.foreign_key_violations == 0
    assert "idx_entries_source_source_id" in report.indexes
    assert "idx_lemmas_written_form_entry" in report.query_plans["lemma"]
    assert "idx_word_forms_written_form_entry" in report.query_plans["word_form"]


def test_validator_rejects_metadata_source_count_drift(tmp_path: Path) -> None:
    source, database = _built_pair(tmp_path)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE resource_metadata SET value = '2' WHERE key = 'entry_count'"
        )

    with pytest.raises(ValidationError, match="entry_count"):
        validate_database(database, source_path=source)


def test_validator_cli_emits_utf8_on_a_legacy_windows_console(tmp_path: Path) -> None:
    source, database = _built_pair(tmp_path)
    korean_source = tmp_path / "사전.zip"
    source.replace(korean_source)
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "cp1252"

    result = subprocess.run(
        [
            sys.executable,
            "tools/krdict/validate_seed.py",
            str(database),
            "--source",
            str(korean_source),
        ],
        cwd=Path(__file__).parents[2],
        env=environment,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert "사전.zip" in result.stdout.decode("utf-8")
