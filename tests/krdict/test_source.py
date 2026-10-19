"""Exact hierarchy tests for the official KRDICT XML shape."""
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
    source = (
        b'<?xml version="1.0" encoding="UTF-8"?>\n<LexicalResource><Lexicon'
        b'>\n<LexicalEntry att="id" val="101">\n  <feat att="lexicalUnit" v'
        b'al="\xeb\x8b\xa8\xec\x96\xb4" />\n  <feat att="homonym_number" va'
        b'l="0" />\n  <feat att="partOfSpeech" val="\xeb\x8f\x99\xec\x82'
        b'\xac" />\n  <feat att="vocabularyLevel" val="\xec\x97\x86\xec\x9d'
        b'\x8c" />\n  <feat att="origin" val="\xe5\x8e\x9f" />\n  <feat att'
        b'="annotation" val="entry note" />\n  <Lemma><feat att="writtenFor'
        b'm" val="\xea\xb0\x80\xeb\x8b\xa4" /><feat att="variant" val="main'
        b'" /></Lemma>\n  <Lemma><feat att="writtenForm" val="\xea\xb0\x80'
        b'\xea\xb0\x80" /><feat att="variant" val="dialect" /></Lemma>\n  <'
        b'WordForm><feat att="type" val="\xed\x99\x9c\xec\x9a\xa9" /><feat '
        b'att="writtenForm" val="\xea\xb0\x84" /><feat att="pronunciation" '
        b'val="\xea\xb0\x84" /></WordForm>\n  <WordForm><feat att="type" va'
        b'l="\xeb\xb0\x9c\xec\x9d\x8c" /><feat att="pronunciation" val="'
        b'\xea\xb0\x88\xeb\x8b\xa4" /><feat att="pronunciation" val="\xea'
        b'\xb0\x88\xeb\x94\xb0" /></WordForm>\n  <FormRepresentation><feat '
        b'att="type" val="\xec\xa4\x80\xeb\xa7\x90" /><feat att="writtenFor'
        b'm" val="\xea\xb0\x80" /></FormRepresentation>\n  <feat att="seman'
        b'ticCategory" val="\xec\x9d\xb4\xeb\x8f\x99" />\n  <feat att="subj'
        b'ectCategiory" val="\xec\x82\xac\xed\x9a\x8c" />\n  <RelatedForm><'
        b'feat att="type" val="\xec\xb0\xb8\xea\xb3\xa0" /><feat att="writt'
        b'enForm" val="\xec\x98\xa4\xeb\x8b\xa4" /><feat att="id" val="202"'
        b' /></RelatedForm>\n  <Sense att="id" val="301">\n    <feat att="d'
        b'efinition" val="first Korean definition" />\n    <feat att="annot'
        b'ation" val="sense note" />\n    <feat att="syntacticAnnotation" v'
        b'al="syntax note" />\n    <syntacticPattern><feat att="pattern" va'
        b'l="N\xec\x97\x90 \xea\xb0\x80\xeb\x8b\xa4" /></syntacticPattern>'
        b'\n    <SenseExample><feat att="type" val="\xeb\x8c\x80\xed\x99'
        b'\x94" /><feat att="example" val="A line" /><feat att="example" va'
        b'l="B line" /></SenseExample>\n    <Equivalent><feat att="language'
        b'" val="\xec\x98\x81\xec\x96\xb4" /><feat att="lemma" val="go" /><'
        b'feat att="definition" val="To move." /></Equivalent>\n    <Equiva'
        b'lent><feat att="language" val="\xec\x98\x81\xec\x96\xb4" /><feat '
        b'att="lemma" val="leave" /><feat att="definition" val="To depart."'
        b' /></Equivalent>\n    <Equivalent><feat att="language" val="\xec'
        b'\x9d\xbc\xeb\xb3\xb8\xec\x96\xb4" /><feat att="lemma" val="ignore'
        b'" /><feat att="definition" val="ignore" /></Equivalent>\n    <Sen'
        b'seRelation><feat att="type" val="\xec\x9c\xa0\xec\x9d\x98\xec\x96'
        b'\xb4" /><feat att="lemma" val="\xec\x98\xa4\xeb\x8b\xa4" /><feat '
        b'att="id" val="202" /><feat att="homonymNumber" val="0" /></SenseR'
        b'elation>\n  </Sense>\n  <Sense att="id" val="302"><feat att="defi'
        b'nition" val="second Korean definition" /></Sense>\n</LexicalEntry'
        b'>\n</Lexicon></LexicalResource>'
    )
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
    assert [
        (item.example_group, item.example_order, item.type, item.text)
        for item in first.examples
    ] == [
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
