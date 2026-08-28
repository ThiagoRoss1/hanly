"""Exact hierarchy tests for the official KRDICT XML shape."""
# ruff: noqa: E501 -- literal byte XML is intentionally kept on source lines.

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

from tools.krdict.source import KRDICTSource


def _archive(path: Path, source: bytes) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("02.xml", source)
    return path


def test_official_hierarchy_is_preserved_without_cross_scope_flattening(tmp_path: Path) -> None:
    source = b"""<?xml version="1.0" encoding="UTF-8"?>
<LexicalResource><Lexicon>
<LexicalEntry att="id" val="101">
  <feat att="lexicalUnit" val="\xeb\x8b\xa8\xec\x96\xb4" />
  <feat att="homonym_number" val="0" />
  <feat att="partOfSpeech" val="\xeb\x8f\x99\xec\x82\xac" />
  <feat att="vocabularyLevel" val="\xec\x97\x86\xec\x9d\x8c" />
  <feat att="origin" val="\xe5\x8e\x9f" />
  <feat att="annotation" val="entry note" />
  <Lemma><feat att="writtenForm" val="\xea\xb0\x80\xeb\x8b\xa4" /><feat att="variant" val="main" /></Lemma>
  <Lemma><feat att="writtenForm" val="\xea\xb0\x80\xea\xb0\x80" /><feat att="variant" val="dialect" /></Lemma>
  <WordForm><feat att="type" val="\xed\x99\x9c\xec\x9a\xa9" /><feat att="writtenForm" val="\xea\xb0\x84" /><feat att="pronunciation" val="\xea\xb0\x84" /></WordForm>
  <WordForm><feat att="type" val="\xeb\xb0\x9c\xec\x9d\x8c" /><feat att="pronunciation" val="\xea\xb0\x88\xeb\x8b\xa4" /><feat att="pronunciation" val="\xea\xb0\x88\xeb\x94\xb0" /></WordForm>
  <FormRepresentation><feat att="type" val="\xec\xa4\x80\xeb\xa7\x90" /><feat att="writtenForm" val="\xea\xb0\x80" /></FormRepresentation>
  <feat att="semanticCategory" val="\xec\x9d\xb4\xeb\x8f\x99" />
  <feat att="subjectCategiory" val="\xec\x82\xac\xed\x9a\x8c" />
  <RelatedForm><feat att="type" val="\xec\xb0\xb8\xea\xb3\xa0" /><feat att="writtenForm" val="\xec\x98\xa4\xeb\x8b\xa4" /><feat att="id" val="202" /></RelatedForm>
  <Sense att="id" val="301">
    <feat att="definition" val="first Korean definition" />
    <feat att="annotation" val="sense note" />
    <feat att="syntacticAnnotation" val="syntax note" />
    <syntacticPattern><feat att="pattern" val="N\xec\x97\x90 \xea\xb0\x80\xeb\x8b\xa4" /></syntacticPattern>
    <SenseExample><feat att="type" val="\xeb\x8c\x80\xed\x99\x94" /><feat att="example" val="A line" /><feat att="example" val="B line" /></SenseExample>
    <Equivalent><feat att="language" val="\xec\x98\x81\xec\x96\xb4" /><feat att="lemma" val="go" /><feat att="definition" val="To move." /></Equivalent>
    <Equivalent><feat att="language" val="\xec\x98\x81\xec\x96\xb4" /><feat att="lemma" val="leave" /><feat att="definition" val="To depart." /></Equivalent>
    <Equivalent><feat att="language" val="\xec\x9d\xbc\xeb\xb3\xb8\xec\x96\xb4" /><feat att="lemma" val="ignore" /><feat att="definition" val="ignore" /></Equivalent>
    <SenseRelation><feat att="type" val="\xec\x9c\xa0\xec\x9d\x98\xec\x96\xb4" /><feat att="lemma" val="\xec\x98\xa4\xeb\x8b\xa4" /><feat att="id" val="202" /><feat att="homonymNumber" val="0" /></SenseRelation>
  </Sense>
  <Sense att="id" val="302"><feat att="definition" val="second Korean definition" /></Sense>
</LexicalEntry>
</Lexicon></LexicalResource>"""
    archive = _archive(tmp_path / "source.zip", source)

    scanned = KRDICTSource(archive)
    records = tuple(scanned.iter_entries())

    assert len(records) == 1
    entry = records[0]
    assert (
        entry.source_id,
        entry.lexical_unit,
        entry.homonym_number,
        entry.part_of_speech,
        entry.vocabulary_level,
        entry.origin,
        entry.annotation,
    ) == (101, "\ub2e8\uc5b4", 0, "\ub3d9\uc0ac", "\uc5c6\uc74c", "\u539f", "entry note")
    assert [(item.written_form, item.variant, item.is_primary) for item in entry.lemmas] == [
        ("\uac00\ub2e4", "main", True),
        ("\uac00\uac00", "dialect", False),
    ]
    assert [(item.type, item.written_form, item.pronunciation) for item in entry.word_forms] == [
        ("\ud65c\uc6a9", "\uac04", "\uac04"),
        ("\ubc1c\uc74c", None, "\uac08\ub2e4"),
        ("\ubc1c\uc74c", None, "\uac08\ub530"),
        ("\uc900\ub9d0", "\uac00", None),
    ]
    assert [(item.type, item.value) for item in entry.categories] == [
        ("semantic", "\uc774\ub3d9"),
        ("subject", "\uc0ac\ud68c"),
    ]
    assert entry.related_forms[0].target_source_id == 202
    assert [sense.source_sense_id for sense in entry.senses] == [301, 302]
    first = entry.senses[0]
    assert first.korean_definition == "first Korean definition"
    assert (first.annotation, first.syntactic_annotation) == ("sense note", "syntax note")
    assert [(item.language, item.lemma, item.definition) for item in first.translations] == [
        ("en", "go", "To move."),
        ("en", "leave", "To depart."),
    ]
    assert [(item.example_group, item.example_order, item.type, item.text) for item in first.examples] == [
        (1, 1, "\ub300\ud654", "A line"),
        (1, 2, "\ub300\ud654", "B line"),
    ]
    assert [item.pattern for item in first.syntactic_patterns] == ["N\uc5d0 \uac00\ub2e4"]
    assert (
        first.sense_relations[0].type,
        first.sense_relations[0].target_lemma,
        first.sense_relations[0].target_source_id,
        first.sense_relations[0].target_homonym_number,
    ) == ("\uc720\uc758\uc5b4", "\uc624\ub2e4", 202, 0)
    assert (scanned.xml_member_count, scanned.entry_count, scanned.sense_count) == (1, 1, 2)


def test_illegal_backspaces_are_replaced_only_in_memory(tmp_path: Path) -> None:
    source = (
        b'<LexicalResource><Lexicon><LexicalEntry att="id" val="1">'
        b'<feat att="lexicalUnit" val="word"/><Lemma><feat att="writtenForm" val="a"/></Lemma>'
        b'<Sense att="id" val="2"><feat att="definition" val="bad\x08byte"/></Sense>'
        b"</LexicalEntry></Lexicon></LexicalResource>"
    )
    archive = _archive(tmp_path / "source.zip", source)
    before = hashlib.sha256(archive.read_bytes()).hexdigest()

    scanned = KRDICTSource(archive)
    record = next(scanned.iter_entries())

    assert record.senses[0].korean_definition == "bad byte"
    assert scanned.sanitized_byte_count == 1
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == before
