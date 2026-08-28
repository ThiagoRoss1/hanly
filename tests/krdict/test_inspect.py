"""Focused tests for the human-facing production KRDICT archive inspector."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

from tools.krdict.inspect import inspect, main


def _archive(path: Path, *sources: bytes) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for index, source in enumerate(sources, start=1):
            archive.writestr(f"{index}_sample.xml", source)
    return path


def _source(*entries: str) -> bytes:
    return (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<LexicalResource><Lexicon>"
        + "".join(entries)
        + "</Lexicon></LexicalResource>"
    ).encode()


def _entry(entry_id: str, headword: str, *, language: str = "영어") -> str:
    return f"""
<LexicalEntry att="id" val="{entry_id}">
  <feat att="homonym_number" val="1" />
  <feat att="partOfSpeech" val="명사" />
  <Lemma><feat att="writtenForm" val="{headword}" /></Lemma>
  <Sense att="id" val="1">
    <feat att="definition" val="한국어 뜻" />
    <Equivalent>
      <feat att="language" val="{language}" />
      <feat att="lemma" val="book" />
      <feat att="definition" val="A written work." />
    </Equivalent>
  </Sense>
</LexicalEntry>
"""


def test_cli_accepts_a_zip_and_prints_compact_json(tmp_path, capsys) -> None:
    archive = _archive(tmp_path / "krdict.zip", _source(_entry("10", "책")))

    status = main([str(archive), "--compact", "--language", "영어", "--samples", "1"])

    assert status == 0
    report = json.loads(capsys.readouterr().out)
    assert report["language"] == "영어"
    assert report["samples"][0]["entry_id"] == "10"
    assert report["samples"][0]["headword"] == "책"
    assert report["validation"]["files_scanned"] == 1
    assert report["validation"]["entries_scanned"] == 1


def test_cli_uses_utf8_output_on_a_legacy_windows_console() -> None:
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "cp1252"

    result = subprocess.run(
        [sys.executable, "tools/krdict/inspect.py", "--help"],
        cwd=Path(__file__).parents[2],
        env=environment,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert b"--language" in result.stdout


def test_illegal_backspace_is_sanitized_in_memory(tmp_path, capsys) -> None:
    source = _source(_entry("10", "책")).replace(b"written work", b"written\x08work")
    archive = _archive(tmp_path / "krdict.zip", source)

    status = inspect(archive, compact=True, language="영어", samples=1)

    assert status == 0
    report = json.loads(capsys.readouterr().out)
    assert report["samples"][0]["senses"][0]["translation"] == {
        "language": "영어",
        "lemma": "book",
        "definition": "A written work.",
    }
    assert report["validation"]["sanitized_0x08_bytes"] == 1


def test_compact_mode_selects_the_requested_translation_language(tmp_path, capsys) -> None:
    entry = _entry("10", "책").replace(
        "</Sense>",
        """
    <Equivalent>
      <feat att="language" val="일본어" />
      <feat att="lemma" val="本" />
      <feat att="definition" val="文章を記録したもの。" />
    </Equivalent>
  </Sense>""",
    )
    archive = _archive(tmp_path / "krdict.zip", _source(entry))

    status = inspect(archive, compact=True, language="일본어", samples=1)

    assert status == 0
    report = json.loads(capsys.readouterr().out)
    assert report["samples"][0]["senses"][0]["translation"] == {
        "language": "일본어",
        "lemma": "本",
        "definition": "文章を記録したもの。",
    }


def test_compact_mode_keeps_missing_optional_fields_explicit(tmp_path, capsys) -> None:
    entry = """
<LexicalEntry att="id" val="11">
  <Lemma><feat att="writtenForm" val="없다" /></Lemma>
  <Sense att="id" val="1"><feat att="definition" val="존재하지 않다." /></Sense>
</LexicalEntry>
"""
    archive = _archive(tmp_path / "krdict.zip", _source(entry))

    status = inspect(archive, compact=True, language="영어", samples=1)

    assert status == 0
    sample = json.loads(capsys.readouterr().out)["samples"][0]
    assert sample == {
        "entry_id": "11",
        "headword": "없다",
        "homonym": None,
        "part_of_speech": None,
        "pronunciation": None,
        "level": None,
        "category": None,
        "senses": [
            {
                "sense_id": "1",
                "korean_definition": "존재하지 않다.",
                "examples": [],
                "translation": None,
            }
        ],
    }


def test_translation_lemma_is_not_used_as_a_missing_korean_headword(tmp_path, capsys) -> None:
    entry = """
<LexicalEntry att="id" val="13">
  <Sense att="id" val="1">
    <feat att="definition" val="한국어 뜻" />
    <Equivalent>
      <feat att="language" val="영어" />
      <feat att="lemma" val="not a Korean headword" />
      <feat att="definition" val="An English definition." />
    </Equivalent>
  </Sense>
</LexicalEntry>
"""
    archive = _archive(tmp_path / "krdict.zip", _source(entry))

    status = inspect(archive, compact=True, language="영어", samples=1)

    assert status == 0
    sample = json.loads(capsys.readouterr().out)["samples"][0]
    assert sample["headword"] is None


def test_compact_mode_preserves_multiple_senses_and_examples(tmp_path, capsys) -> None:
    entry = """
<LexicalEntry att="id" val="12">
  <Lemma><feat att="writtenForm" val="가" /></Lemma>
  <Sense att="id" val="1">
    <feat att="definition" val="끝부분." />
    <SenseExample><feat att="example" val="길가." /></SenseExample>
    <Equivalent><feat att="language" val="영어" /><feat att="lemma" val="edge" />
      <feat att="definition" val="An outer limit." /></Equivalent>
  </Sense>
  <Sense att="id" val="2">
    <feat att="definition" val="주변." />
    <SenseExample>
      <feat att="example" val="강가." />
      <feat att="example" val="냇가." />
    </SenseExample>
  </Sense>
</LexicalEntry>
"""
    archive = _archive(tmp_path / "krdict.zip", _source(entry))

    status = inspect(archive, compact=True, language="영어", samples=1)

    assert status == 0
    senses = json.loads(capsys.readouterr().out)["samples"][0]["senses"]
    assert [sense["sense_id"] for sense in senses] == ["1", "2"]
    assert senses[0]["examples"] == ["길가."]
    assert senses[1]["examples"] == ["강가.", "냇가."]
    assert senses[1]["translation"] is None


def test_sample_limit_does_not_stop_full_archive_iteration(tmp_path, capsys) -> None:
    archive = _archive(
        tmp_path / "krdict.zip",
        _source(_entry("1", "하나")),
        _source(_entry("2", "둘"), _entry("3", "셋")),
    )

    status = inspect(archive, compact=True, language="영어", samples=1)

    assert status == 0
    report = json.loads(capsys.readouterr().out)
    assert len(report["samples"]) == 1
    assert report["validation"] == {
        "files_scanned": 2,
        "entries_scanned": 3,
        "senses_scanned": 3,
        "sanitized_0x08_bytes": 0,
    }
