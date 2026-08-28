"""Stream and normalize the official KRDICT ZIP hierarchy."""

from __future__ import annotations

import io
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import IO
from xml.etree import ElementTree


class KRDICTSourceError(ValueError):
    """Raised when the official source cannot satisfy the production contract."""


@dataclass(frozen=True, slots=True)
class LemmaRecord:
    written_form: str
    variant: str | None
    is_primary: bool


@dataclass(frozen=True, slots=True)
class TranslationRecord:
    language: str
    lemma: str
    definition: str


@dataclass(frozen=True, slots=True)
class ExampleRecord:
    example_group: int
    example_order: int
    type: str | None
    text: str


@dataclass(frozen=True, slots=True)
class WordFormRecord:
    type: str
    written_form: str | None
    pronunciation: str | None


@dataclass(frozen=True, slots=True)
class CategoryRecord:
    type: str
    value: str


@dataclass(frozen=True, slots=True)
class RelatedFormRecord:
    type: str
    written_form: str
    target_source_id: int | None


@dataclass(frozen=True, slots=True)
class SyntacticPatternRecord:
    pattern_order: int
    pattern: str


@dataclass(frozen=True, slots=True)
class SenseRelationRecord:
    type: str
    target_lemma: str
    target_source_id: int | None
    target_homonym_number: int | None


@dataclass(frozen=True, slots=True)
class SenseRecord:
    source_sense_id: int
    sense_order: int
    korean_definition: str
    annotation: str | None
    syntactic_annotation: str | None
    translations: tuple[TranslationRecord, ...]
    examples: tuple[ExampleRecord, ...]
    syntactic_patterns: tuple[SyntacticPatternRecord, ...]
    sense_relations: tuple[SenseRelationRecord, ...]


@dataclass(frozen=True, slots=True)
class EntryRecord:
    source_id: int
    lexical_unit: str
    homonym_number: int | None
    part_of_speech: str | None
    vocabulary_level: str | None
    origin: str | None
    annotation: str | None
    lemmas: tuple[LemmaRecord, ...]
    senses: tuple[SenseRecord, ...]
    word_forms: tuple[WordFormRecord, ...]
    categories: tuple[CategoryRecord, ...]
    related_forms: tuple[RelatedFormRecord, ...]


class _SanitizingStream(io.RawIOBase):
    """Replace XML-illegal backspaces as bytes are read, never at rest."""

    def __init__(self, source: IO[bytes]) -> None:
        self._source = source
        self.replacements = 0

    def readable(self) -> bool:
        return True

    def read(self, size: int = -1) -> bytes:
        chunk = self._source.read(size)
        self.replacements += chunk.count(b"\x08")
        return chunk.replace(b"\x08", b" ")


def _name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold().replace("-", "_")


def _att_name(value: str) -> str:
    return value.casefold().replace("-", "").replace("_", "")


def _direct_features(node: ElementTree.Element, name: str) -> list[str]:
    wanted = _att_name(name)
    values: list[str] = []
    for child in node:
        if _name(child.tag) != "feat":
            continue
        actual = child.attrib.get("att", child.attrib.get("name", ""))
        if _att_name(actual) != wanted:
            continue
        value = child.attrib.get("val", child.attrib.get("value"))
        if value is None:
            value = "".join(child.itertext())
        if value != "":
            values.append(value)
    return values


def _feature(node: ElementTree.Element, name: str) -> str | None:
    values = _direct_features(node, name)
    return values[0] if values else None


def _source_id(node: ElementTree.Element) -> int | None:
    value: str | None = None
    if _att_name(node.attrib.get("att", "")) == "id":
        value = node.attrib.get("val", node.attrib.get("value"))
    if value is None:
        value = _feature(node, "id")
    return _integer(value, field="source id")


def _integer(value: str | None, *, field: str) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise KRDICTSourceError(f"{field} must be an integer, got {value!r}") from exc


def _children(node: ElementTree.Element, name: str) -> list[ElementTree.Element]:
    wanted = _name(name)
    return [child for child in node if _name(child.tag) == wanted]


def _word_form_rows(
    node: ElementTree.Element, inherited_type: str | None = None
) -> list[WordFormRecord]:
    form_type = _feature(node, "type") or inherited_type
    if form_type is None:
        return []
    written = _direct_features(node, "writtenForm")
    pronunciations = _direct_features(node, "pronunciation")
    count = max(len(written), len(pronunciations), 1)
    rows: list[WordFormRecord] = []
    for index in range(count):
        written_form = (
            written[index]
            if index < len(written)
            else (written[0] if len(written) == 1 else None)
        )
        pronunciation = (
            pronunciations[index]
            if index < len(pronunciations)
            else (pronunciations[0] if len(pronunciations) == 1 else None)
        )
        if written_form is not None or pronunciation is not None:
            rows.append(WordFormRecord(form_type, written_form, pronunciation))
    return rows


def _parse_sense(node: ElementTree.Element, order: int) -> SenseRecord:
    source_id = _source_id(node)
    definition = _feature(node, "definition")
    if source_id is None or definition is None:
        raise KRDICTSourceError("every Sense requires an integer id and Korean definition")

    translations: list[TranslationRecord] = []
    for equivalent in _children(node, "Equivalent"):
        if _feature(equivalent, "language") != "영어":
            continue
        lemma = _feature(equivalent, "lemma")
        translated_definition = _feature(equivalent, "definition")
        if lemma is not None and translated_definition is not None:
            translations.append(TranslationRecord("en", lemma, translated_definition))

    examples: list[ExampleRecord] = []
    for group_order, group in enumerate(_children(node, "SenseExample"), start=1):
        example_type = _feature(group, "type")
        for line_order, text in enumerate(_direct_features(group, "example"), start=1):
            examples.append(ExampleRecord(group_order, line_order, example_type, text))

    patterns = list(_direct_features(node, "syntacticPattern"))
    for pattern_node in _children(node, "syntacticPattern"):
        value = _feature(pattern_node, "pattern") or _feature(pattern_node, "syntacticPattern")
        if value is not None:
            patterns.append(value)

    relations: list[SenseRelationRecord] = []
    for relation in _children(node, "SenseRelation"):
        relation_type = _feature(relation, "type")
        target_lemma = _feature(relation, "lemma") or _feature(relation, "writtenForm")
        if relation_type is None or target_lemma is None:
            continue
        relations.append(
            SenseRelationRecord(
                relation_type,
                target_lemma,
                _source_id(relation),
                _integer(_feature(relation, "homonym_number"), field="target homonym number"),
            )
        )

    return SenseRecord(
        source_sense_id=source_id,
        sense_order=order,
        korean_definition=definition,
        annotation=_feature(node, "annotation"),
        syntactic_annotation=_feature(node, "syntacticAnnotation"),
        translations=tuple(translations),
        examples=tuple(examples),
        syntactic_patterns=tuple(
            SyntacticPatternRecord(pattern_order, pattern)
            for pattern_order, pattern in enumerate(patterns, start=1)
        ),
        sense_relations=tuple(relations),
    )


def _parse_entry(node: ElementTree.Element) -> EntryRecord:
    source_id = _source_id(node)
    lexical_unit = _feature(node, "lexicalUnit")
    if source_id is None or lexical_unit is None:
        raise KRDICTSourceError("every LexicalEntry requires an integer id and lexicalUnit")

    lemmas: list[LemmaRecord] = []
    for index, lemma in enumerate(_children(node, "Lemma")):
        written_form = _feature(lemma, "writtenForm")
        if written_form is not None:
            lemmas.append(LemmaRecord(written_form, _feature(lemma, "variant"), index == 0))
    if not lemmas:
        raise KRDICTSourceError(f"LexicalEntry {source_id} has no Lemma writtenForm")

    word_forms: list[WordFormRecord] = []
    for form in _children(node, "WordForm"):
        word_forms.extend(_word_form_rows(form))
        inherited_type = _feature(form, "type")
        for representation in _children(form, "FormRepresentation"):
            word_forms.extend(_word_form_rows(representation, inherited_type))
    for representation in _children(node, "FormRepresentation"):
        word_forms.extend(_word_form_rows(representation))

    categories = [
        *(
            CategoryRecord("semantic", value)
            for value in _direct_features(node, "semanticCategory")
        ),
        # "subjectCategiory" is misspelled in the official source; matching the
        # correct spelling would silently drop every subject category.
        *(CategoryRecord("subject", value) for value in _direct_features(node, "subjectCategiory")),
    ]

    related_forms: list[RelatedFormRecord] = []
    for relation in _children(node, "RelatedForm"):
        relation_type = _feature(relation, "type")
        written_form = _feature(relation, "writtenForm") or _feature(relation, "lemma")
        if relation_type is not None and written_form is not None:
            related_forms.append(
                RelatedFormRecord(relation_type, written_form, _source_id(relation))
            )

    senses = tuple(
        _parse_sense(sense, order)
        for order, sense in enumerate(_children(node, "Sense"), start=1)
    )
    return EntryRecord(
        source_id=source_id,
        lexical_unit=lexical_unit,
        homonym_number=_integer(_feature(node, "homonym_number"), field="homonym number"),
        part_of_speech=_feature(node, "partOfSpeech"),
        vocabulary_level=_feature(node, "vocabularyLevel"),
        origin=_feature(node, "origin"),
        annotation=_feature(node, "annotation"),
        lemmas=tuple(lemmas),
        senses=senses,
        word_forms=tuple(word_forms),
        categories=tuple(categories),
        related_forms=tuple(related_forms),
    )


class KRDICTSource:
    """One repeatable streaming scan of an official KRDICT ZIP."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.xml_member_count = 0
        self.entry_count = 0
        self.sense_count = 0
        self.sanitized_byte_count = 0

    def iter_entries(self) -> Iterator[EntryRecord]:
        self.xml_member_count = 0
        self.entry_count = 0
        self.sense_count = 0
        self.sanitized_byte_count = 0
        try:
            with zipfile.ZipFile(self.path) as archive:
                names = sorted(
                    name for name in archive.namelist() if name.casefold().endswith(".xml")
                )
                if not names:
                    raise KRDICTSourceError("KRDICT ZIP contains no XML members")
                for name in names:
                    self.xml_member_count += 1
                    with archive.open(name) as raw:
                        stream = _SanitizingStream(raw)
                        # Counts stay accurate mid-iteration, so a caller that
                        # stops early still sees what has been read so far.
                        scanned_before = self.sanitized_byte_count
                        context = ElementTree.iterparse(stream, events=("start", "end"))
                        _event, root = next(context)
                        for event, element in context:
                            if event != "end" or _name(element.tag) != "lexicalentry":
                                continue
                            record = _parse_entry(element)
                            self.entry_count += 1
                            self.sense_count += len(record.senses)
                            self.sanitized_byte_count = scanned_before + stream.replacements
                            yield record
                            element.clear()
                            root.clear()
                        self.sanitized_byte_count = scanned_before + stream.replacements
                if self.entry_count == 0:
                    raise KRDICTSourceError(
                        "KRDICT source contains no LexicalEntry elements"
                    )
        except KRDICTSourceError:
            raise
        except (OSError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
            raise KRDICTSourceError(f"unable to read KRDICT source ZIP: {self.path}") from exc


__all__ = [
    "CategoryRecord",
    "EntryRecord",
    "ExampleRecord",
    "KRDICTSource",
    "KRDICTSourceError",
    "LemmaRecord",
    "RelatedFormRecord",
    "SenseRecord",
    "SenseRelationRecord",
    "SyntacticPatternRecord",
    "TranslationRecord",
    "WordFormRecord",
]
