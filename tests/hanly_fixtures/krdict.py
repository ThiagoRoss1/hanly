"""Small official-shape KRDICT artifacts shared by runtime tests."""
# ruff: noqa: E501 -- literal XML is clearer when source elements stay intact.

from __future__ import annotations

import zipfile
from pathlib import Path

from tools.krdict.build_seed import build_database


def build_krdict_database(directory: Path, xml: str, database_name: str = "krdict.sqlite3") -> Path:
    """Build one normalized database from official-shape XML through the real
    production pipeline, so fixtures cannot drift from the shipped schema."""

    source = directory / "krdict-source.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("fixture.xml", xml)
    database = directory / database_name
    build_database(
        source,
        database,
        source_date="fixture",
        resource_version="fixture-v1",
        build_date="1970-01-01",
    )
    return database


FIXTURE_XML = """<?xml version="1.0" encoding="utf-8"?>
<LexicalResource><Lexicon>
  <LexicalEntry att="id" val="10">
    <feat att="lexicalUnit" val="단어" />
    <feat att="homonym_number" val="0" />
    <feat att="partOfSpeech" val="동사" />
    <Lemma><feat att="writtenForm" val="먹다" /></Lemma>
    <WordForm><feat att="type" val="활용" /><feat att="writtenForm" val="먹어요" /></WordForm>
    <Sense att="id" val="100">
      <feat att="definition" val="음식을 입을 통하여 배 속에 들여보내다." />
      <Equivalent><feat att="language" val="영어" /><feat att="lemma" val="eat" /><feat att="definition" val="to eat" /></Equivalent>
    </Sense>
  </LexicalEntry>
  <LexicalEntry att="id" val="20">
    <feat att="lexicalUnit" val="단어" />
    <feat att="homonym_number" val="0" />
    <feat att="partOfSpeech" val="명사" />
    <Lemma><feat att="writtenForm" val="책" /></Lemma>
    <Sense att="id" val="200">
      <feat att="definition" val="글이나 그림을 인쇄하여 묶은 것." />
      <Equivalent><feat att="language" val="영어" /><feat att="lemma" val="book" /><feat att="definition" val="a book" /></Equivalent>
      <Equivalent><feat att="language" val="영어" /><feat att="lemma" val="volume" /><feat att="definition" val="book" /></Equivalent>
    </Sense>
  </LexicalEntry>
  <LexicalEntry att="id" val="30">
    <feat att="lexicalUnit" val="단어" />
    <feat att="homonym_number" val="0" />
    <feat att="partOfSpeech" val="동사" />
    <Lemma><feat att="writtenForm" val="읽다" /></Lemma>
    <Sense att="id" val="300">
      <feat att="definition" val="글을 보고 뜻을 이해하다." />
      <Equivalent><feat att="language" val="영어" /><feat att="lemma" val="read" /><feat att="definition" val="to read" /></Equivalent>
    </Sense>
  </LexicalEntry>
</Lexicon></LexicalResource>
"""


def build_fixture_krdict(directory: Path, database_name: str = "krdict.sqlite3") -> Path:
    return build_krdict_database(directory, FIXTURE_XML, database_name)
