"""Focused tests for the human-facing production KRDICT archive inspector."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

from tools.krdict.inspect_archive import inspect, main


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


def test_cli_uses_utf8_output_on_a_legacy_windows_console(tmp_path: Path) -> None:
    """The report is the Korean the console has to survive. ``--help`` is ASCII
    and would pass on a console that cannot encode a single headword."""

    archive = _archive(tmp_path / "krdict.zip", _source(_entry("10", "책")))
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "cp1252"

    result = subprocess.run(
        [sys.executable, "tools/krdict/inspect_archive.py", str(archive), "--compact"],
        cwd=Path(__file__).parents[2],
        env=environment,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr.decode(errors="replace")
    report = json.loads(result.stdout.decode("utf-8"))
    assert report["samples"][0]["headword"] == "책"
    assert report["language"] == "영어"


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
        "semantic_categories": [],
        "subject_categories": [],
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


#: One real 가1 entry, trimmed to the shapes this inspector reads. The
#: pronunciation sits directly on the WordForm, the categories are entry-level
#: features, and "subjectCategiory" is the official misspelling.
_REAL_ENTRY = """
<LexicalEntry att="id" val="30">
  <feat att="homonym_number" val="1" />
  <feat att="lexicalUnit" val="단어" />
  <feat att="partOfSpeech" val="감탄사" />
  <feat att="vocabularyLevel" val="없음" />
  <feat att="semanticCategory" val="인간 &gt; 의사소통" />
  <feat att="subjectCategiory" val="사회 생활 &gt; 인간관계" />
  <Lemma><feat att="writtenForm" val="가" /></Lemma>
  <WordForm>
    <feat att="type" val="발음" />
    <feat att="pronunciation" val="가ː" />
  </WordForm>
  <Sense att="id" val="1"><feat att="definition" val="말을 시작할 때 내는 소리." /></Sense>
</LexicalEntry>
"""

#: The nested shape the inspector previously required, kept so the fallback is
#: exercised rather than assumed.
_NESTED_PRONUNCIATION_ENTRY = """
<LexicalEntry att="id" val="31">
  <Lemma><feat att="writtenForm" val="값" /></Lemma>
  <WordForm>
    <feat att="type" val="발음" />
    <FormRepresentation><feat att="pronunciation" val="갑" /></FormRepresentation>
  </WordForm>
  <Sense att="id" val="1"><feat att="definition" val="물건의 가치." /></Sense>
</LexicalEntry>
"""


def _sample(tmp_path, entry: str, capsys) -> dict:
    archive = _archive(tmp_path / "krdict.zip", _source(entry))

    assert inspect(archive, compact=True, language="영어", samples=1) == 0

    return json.loads(capsys.readouterr().out)["samples"][0]


def test_pronunciation_is_read_from_the_word_form_the_archive_actually_uses(
    tmp_path, capsys
) -> None:
    """The official source records it on the WordForm, not below it."""

    sample = _sample(tmp_path, _REAL_ENTRY, capsys)

    assert sample["pronunciation"] == "가ː"


def test_a_nested_form_representation_pronunciation_is_still_found(
    tmp_path, capsys
) -> None:
    sample = _sample(tmp_path, _NESTED_PRONUNCIATION_ENTRY, capsys)

    assert sample["pronunciation"] == "갑"


def test_categories_come_from_the_entry_level_features_including_the_misspelling(
    tmp_path, capsys
) -> None:
    """``SubjectField``/``subject`` do not exist in the archive; these do."""

    sample = _sample(tmp_path, _REAL_ENTRY, capsys)

    assert sample["semantic_categories"] == ["인간 > 의사소통"]
    assert sample["subject_categories"] == ["사회 생활 > 인간관계"]


def test_an_entry_without_categories_reports_empty_lists(tmp_path, capsys) -> None:
    sample = _sample(tmp_path, _NESTED_PRONUNCIATION_ENTRY, capsys)

    assert sample["semantic_categories"] == []
    assert sample["subject_categories"] == []


def test_the_inspector_reads_the_same_shapes_the_builder_reads(tmp_path, capsys) -> None:
    """The inspector exists to preview what the build will store, so the two
    must not disagree about where pronunciation and categories live."""

    from tools.krdict.source import KRDICTSource

    sample = _sample(tmp_path, _REAL_ENTRY, capsys)
    (record,) = list(KRDICTSource(tmp_path / "krdict.zip").iter_entries())

    assert sample["pronunciation"] in {form.pronunciation for form in record.word_forms}
    assert sample["semantic_categories"] == [
        category.value for category in record.categories if category.type == "semantic"
    ]
    assert sample["subject_categories"] == [
        category.value for category in record.categories if category.type == "subject"
    ]
