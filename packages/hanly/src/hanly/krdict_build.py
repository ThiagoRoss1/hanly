"""Build the small, runtime-oriented KRDICT SQLite artifact.

The source-side processing intentionally lives outside ``KRDICTProvider``.  A
build may be run when resources are installed or updated; the provider only
opens the resulting artifact in read-only mode at runtime.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unicodedata
from collections import OrderedDict
from pathlib import Path
from xml.etree import ElementTree

KRDICT_SCHEMA_NAME = "hanly.krdict"
KRDICT_SCHEMA_VERSION = 1
KRDICT_SCHEMA_MARKER = f"{KRDICT_SCHEMA_NAME}-sqlite-v{KRDICT_SCHEMA_VERSION}"


class KRDICTBuildError(ValueError):
    """Raised when a KRDICT source cannot produce a valid build artifact."""


_HEADWORD_TAGS = {
    "headword",
    "head_word",
    "lemma",
    "lexicalform",
    "lexical_form",
    "writtenform",
    "written_form",
    "word",
    "targetword",
    "target_word",
}
_PART_OF_SPEECH_TAGS = {
    "partofspeech",
    "part_of_speech",
    "pos",
}
_DEFINITION_TAGS = {
    "definition",
    "def",
    "gloss",
    "meaning",
    "transdfn",
    "trans_dfn",
    "englishdefinition",
    "english_definition",
    "translationdefinition",
    "translation_definition",
    "transword",
    "trans_word",
}
_ENGLISH_TAGS = {
    "english",
    "englishdefinition",
    "english_definition",
    "gloss",
    "transdfn",
    "trans_dfn",
    "translationdefinition",
    "translation_definition",
    "transword",
    "trans_word",
}
_RECORD_TAGS = {"entry", "item", "record", "lexicalentry", "lexical_entry"}
_TRANSLATION_CONTAINER_TAGS = {"translation", "translations", "sense"}


def _local_name(tag: str) -> str:
    """Return a namespace-independent, comparison-friendly XML tag name."""

    return tag.rsplit("}", 1)[-1].lower().replace("-", "_")


def _normalise(value: str | None) -> str:
    if value is None:
        return ""
    value = unicodedata.normalize("NFC", value)
    return " ".join(value.split())


def _language(element: ElementTree.Element) -> str | None:
    for name, value in element.attrib.items():
        if _local_name(name) in {"lang", "language"}:
            return _normalise(value).lower()
    return None


def _is_english(language: str | None) -> bool:
    if language is None:
        return False
    return language in {"en", "eng", "english", "영어"} or language.startswith("en-")


def _element_text(element: ElementTree.Element) -> str:
    return _normalise("".join(element.itertext()))


def _attribute_value(element: ElementTree.Element, names: set[str]) -> str:
    """Read KRDICT/OpenAPI ``feat att=... val=...`` style values."""

    for name, value in element.attrib.items():
        if _local_name(name) in names:
            return _normalise(value)
    attribute_name = element.attrib.get("att") or element.attrib.get("name")
    if attribute_name and _local_name(attribute_name) in names:
        return _normalise(element.attrib.get("val") or element.attrib.get("value"))
    return ""


def _find_field(node: ElementTree.Element, names: set[str]) -> str:
    for element in node.iter():
        tag_name = _local_name(element.tag)
        if tag_name in names:
            value = _element_text(element)
            if value:
                return value
            value = _attribute_value(element, names)
            if value:
                return value
        value = _attribute_value(element, names)
        if value:
            return value
    return ""


def _translation_language(container: ElementTree.Element) -> str | None:
    language = _language(container)
    if language:
        return language
    for element in container.iter():
        if _local_name(element.tag) in {"language", "lang", "targetlanguage", "target_language"}:
            value = _element_text(element)
            if value:
                return value.lower()
    return None


def _effective_translation_language(
    element: ElementTree.Element,
    parents: dict[ElementTree.Element, ElementTree.Element],
) -> str | None:
    """Resolve the language declared on a containing translation element."""

    language = _language(element)
    if language:
        return language
    parent = parents.get(element)
    while parent is not None:
        if _local_name(parent.tag) in {"translation", "translations"}:
            return _translation_language(parent)
        parent = parents.get(parent)
    return None


def _english_definitions(node: ElementTree.Element) -> tuple[str, ...]:
    """Extract English definitions from both dump-style and API-style XML."""

    explicit_definitions: list[str] = []
    fallback_definitions: list[str] = []
    parents = {
        child: parent
        for parent in node.iter()
        for child in parent
    }
    has_non_english_translation = False

    def add(target: list[str], value: str) -> None:
        value = _normalise(value)
        if value and value not in target:
            target.append(value)

    # ``definition lang="en"`` and ``definition`` (the compact fixture/dump
    # form) are handled directly.  A language other than English is excluded.
    for element in node.iter():
        tag_name = _local_name(element.tag)
        language = _effective_translation_language(element, parents)
        if (
            tag_name in {"translation", "translations"}
            and language is not None
            and not _is_english(language)
        ):
            has_non_english_translation = True
        if tag_name in _DEFINITION_TAGS:
            if _is_english(language) or (
                language is None and tag_name in _ENGLISH_TAGS
            ):
                add(explicit_definitions, _element_text(element))
            elif language is None:
                add(fallback_definitions, _element_text(element))

        # A common KRDICT dump representation uses ``<feat att="definition"
        # val="..."/>`` rather than a named element.
        attribute_name = element.attrib.get("att") or element.attrib.get("name")
        if attribute_name and _local_name(attribute_name) in _DEFINITION_TAGS:
            value = element.attrib.get("val") or element.attrib.get("value") or ""
            if _is_english(language) or (
                language is None and _local_name(attribute_name) in _ENGLISH_TAGS
            ):
                add(explicit_definitions, value)
            elif language is None:
                add(fallback_definitions, value)

    # API-style records put ``trans_dfn`` / ``trans_word`` below a translation
    # container and identify the target language in a sibling ``language``.
    for container in node.iter():
        if _local_name(container.tag) not in _TRANSLATION_CONTAINER_TAGS:
            continue
        language = _translation_language(container)
        if language is not None and not _is_english(language):
            continue
        for element in container.iter():
            if _local_name(element.tag) in _ENGLISH_TAGS:
                add(explicit_definitions, _element_text(element))

    if explicit_definitions:
        return tuple(explicit_definitions)
    if has_non_english_translation:
        return ()
    return tuple(fallback_definitions)


def _record_nodes(root: ElementTree.Element) -> list[ElementTree.Element]:
    nodes = [element for element in root.iter() if _local_name(element.tag) in _RECORD_TAGS]
    if nodes:
        return nodes
    return [root]


def _parse_source(source_path: Path) -> OrderedDict[tuple[str, str | None], list[str]]:
    try:
        root = ElementTree.parse(source_path).getroot()
    except (ElementTree.ParseError, OSError) as exc:
        raise KRDICTBuildError(f"unable to read KRDICT XML source: {source_path}") from exc

    records: OrderedDict[tuple[str, str | None], list[str]] = OrderedDict()
    for node in _record_nodes(root):
        headword = _find_field(node, _HEADWORD_TAGS)
        if not headword:
            continue
        part_of_speech = _find_field(node, _PART_OF_SPEECH_TAGS) or None
        definitions = _english_definitions(node)
        if not definitions:
            raise KRDICTBuildError(
                f"entry {headword!r} has no English definition"
            )
        key = (headword, part_of_speech)
        target = records.setdefault(key, [])
        for definition in definitions:
            if definition not in target:
                target.append(definition)

    if not records:
        raise KRDICTBuildError("KRDICT XML source contains no dictionary entries")
    return records


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA foreign_keys = ON;
        PRAGMA user_version = 1;
        CREATE TABLE metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE entries (
            id INTEGER PRIMARY KEY,
            headword TEXT NOT NULL,
            part_of_speech TEXT
        );
        CREATE TABLE definitions (
            entry_id INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
            ordinal INTEGER NOT NULL,
            definition TEXT NOT NULL,
            PRIMARY KEY (entry_id, ordinal)
        );
        CREATE INDEX idx_entries_headword ON entries(headword);
        INSERT INTO metadata(key, value) VALUES
            ('schema_name', 'hanly.krdict'),
            ('schema_marker', 'hanly.krdict-sqlite-v1'),
            ('schema_version', '1'),
            ('source_language', 'ko'),
            ('target_language', 'en');
        """
    )


def build_krdict_database(
    source_path: str | os.PathLike[str],
    database_path: str | os.PathLike[str],
) -> Path:
    """Build a deterministic indexed SQLite artifact from a KRDICT XML dump.

    The destination is replaced only after a complete temporary database has
    been committed.  Rebuilding the same source therefore produces the same
    logical and byte-level artifact without requiring a production KRDICT
    download in tests or development.
    """

    source = Path(source_path)
    destination = Path(database_path)
    records = _parse_source(source)
    destination.parent.mkdir(parents=True, exist_ok=True)

    temporary_path: Path | None = None
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    os.close(file_descriptor)
    temporary_path = Path(temporary_name)
    try:
        connection = sqlite3.connect(temporary_path)
        try:
            with connection:
                _create_schema(connection)
                for entry_id, ((headword, part_of_speech), definitions) in enumerate(
                    records.items(), start=1
                ):
                    connection.execute(
                        "INSERT INTO entries(id, headword, part_of_speech) VALUES (?, ?, ?)",
                        (entry_id, headword, part_of_speech),
                    )
                    connection.executemany(
                        "INSERT INTO definitions(entry_id, ordinal, definition) VALUES (?, ?, ?)",
                        (
                            (entry_id, ordinal, definition)
                            for ordinal, definition in enumerate(definitions)
                        ),
                    )
        finally:
            connection.close()
        temporary_path.replace(destination)
        temporary_path = None
    except (OSError, sqlite3.Error) as exc:
        raise KRDICTBuildError(
            f"unable to write KRDICT SQLite database: {destination}"
        ) from exc
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return destination


# A descriptive alias helps callers that name the capability after its output
# format while keeping one implementation and one schema contract.
build_krdict_sqlite = build_krdict_database


__all__ = [
    "KRDICTBuildError",
    "KRDICT_SCHEMA_MARKER",
    "KRDICT_SCHEMA_NAME",
    "KRDICT_SCHEMA_VERSION",
    "build_krdict_database",
    "build_krdict_sqlite",
]
