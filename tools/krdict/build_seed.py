"""Build the normalized production KRDICT SQLite seed."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

if __package__ in (None, ""):
    # Run as a plain script rather than ``python -m``, so the repository root
    # is not on the path and ``tools.krdict`` cannot be imported without it.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass

from tools.krdict.source import EntryRecord, KRDICTSource, KRDICTSourceError

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

INDEX_SQL = """
CREATE INDEX idx_entries_source_source_id ON entries(source, source_id);
CREATE INDEX idx_lemmas_written_form_entry ON lemmas(written_form, entry_id);
CREATE INDEX idx_lemmas_entry_id ON lemmas(entry_id);
CREATE INDEX idx_word_forms_written_form_entry ON word_forms(written_form, entry_id);
CREATE INDEX idx_word_forms_entry_id ON word_forms(entry_id);
CREATE INDEX idx_translations_sense_language ON translations(sense_id, language);
CREATE INDEX idx_categories_entry_id ON categories(entry_id);
CREATE INDEX idx_related_forms_entry_id ON related_forms(entry_id);
CREATE INDEX idx_sense_relations_sense_id ON sense_relations(sense_id);
"""


class BuildError(RuntimeError):
    """Raised when a source cannot produce a complete seed."""


@dataclass(frozen=True, slots=True)
class BuildResult:
    database_path: Path
    entry_count: int
    sense_count: int
    sanitized_byte_count: int
    xml_member_count: int
    row_counts: Mapping[str, int]
    duration_seconds: float


_ENTRY_SQL = """INSERT INTO entries(
       id, source, source_id, lexical_unit, homonym_number,
       part_of_speech, vocabulary_level, origin, annotation
   ) VALUES (?, 'krdict', ?, ?, ?, ?, ?, ?, ?)"""

_SENSE_SQL = """INSERT INTO senses(
       id, entry_id, source_sense_id, sense_order,
       korean_definition, annotation, syntactic_annotation
   ) VALUES (?, ?, ?, ?, ?, ?, ?)"""

# Every child row is written through one statement per table, so the tables a
# build touches and the columns it fills stay visible in one place.
_CHILD_SQL = {
    "lemmas": "INSERT INTO lemmas(id, entry_id, written_form, variant, is_primary) "
    "VALUES (?, ?, ?, ?, ?)",
    "word_forms": "INSERT INTO word_forms(id, entry_id, type, written_form, pronunciation) "
    "VALUES (?, ?, ?, ?, ?)",
    "categories": "INSERT INTO categories(id, entry_id, type, value) VALUES (?, ?, ?, ?)",
    "related_forms": "INSERT INTO related_forms(id, entry_id, type, written_form, "
    "target_source_id) VALUES (?, ?, ?, ?, ?)",
    "translations": "INSERT INTO translations(id, sense_id, language, lemma, definition) "
    "VALUES (?, ?, ?, ?, ?)",
    "examples": "INSERT INTO examples(id, sense_id, example_group, example_order, type, text) "
    "VALUES (?, ?, ?, ?, ?, ?)",
    "syntactic_patterns": "INSERT INTO syntactic_patterns(id, sense_id, pattern_order, pattern) "
    "VALUES (?, ?, ?, ?)",
    "sense_relations": "INSERT INTO sense_relations(id, sense_id, type, target_lemma, "
    "target_source_id, target_homonym_number) VALUES (?, ?, ?, ?, ?, ?)",
}

_TABLES = ("entries", "senses", *_CHILD_SQL)


def _insert_children(
    connection: sqlite3.Connection,
    counters: dict[str, int],
    table: str,
    rows: Iterable[tuple[object, ...]],
) -> None:
    """Insert one table's rows under deterministic sequential primary keys."""

    def numbered() -> Iterator[tuple[object, ...]]:
        for row in rows:
            counters[table] += 1
            yield (counters[table], *row)

    connection.executemany(_CHILD_SQL[table], numbered())


def _insert_entry(
    connection: sqlite3.Connection,
    entry: EntryRecord,
    entry_id: int,
    counters: dict[str, int],
) -> None:
    connection.execute(
        _ENTRY_SQL,
        (
            entry_id,
            entry.source_id,
            entry.lexical_unit,
            entry.homonym_number,
            entry.part_of_speech,
            entry.vocabulary_level,
            entry.origin,
            entry.annotation,
        ),
    )
    counters["entries"] += 1

    _insert_children(
        connection,
        counters,
        "lemmas",
        (
            (entry_id, lemma.written_form, lemma.variant, int(lemma.is_primary))
            for lemma in entry.lemmas
        ),
    )
    _insert_children(
        connection,
        counters,
        "word_forms",
        (
            (entry_id, form.type, form.written_form, form.pronunciation)
            for form in entry.word_forms
        ),
    )
    _insert_children(
        connection,
        counters,
        "categories",
        ((entry_id, category.type, category.value) for category in entry.categories),
    )
    _insert_children(
        connection,
        counters,
        "related_forms",
        (
            (entry_id, related.type, related.written_form, related.target_source_id)
            for related in entry.related_forms
        ),
    )

    for sense in entry.senses:
        counters["senses"] += 1
        sense_id = counters["senses"]
        connection.execute(
            _SENSE_SQL,
            (
                sense_id,
                entry_id,
                sense.source_sense_id,
                sense.sense_order,
                sense.korean_definition,
                sense.annotation,
                sense.syntactic_annotation,
            ),
        )
        _insert_children(
            connection,
            counters,
            "translations",
            (
                (sense_id, translation.language, translation.lemma, translation.definition)
                for translation in sense.translations
            ),
        )
        _insert_children(
            connection,
            counters,
            "examples",
            (
                (
                    sense_id,
                    example.example_group,
                    example.example_order,
                    example.type,
                    example.text,
                )
                for example in sense.examples
            ),
        )
        _insert_children(
            connection,
            counters,
            "syntactic_patterns",
            (
                (sense_id, pattern.pattern_order, pattern.pattern)
                for pattern in sense.syntactic_patterns
            ),
        )
        _insert_children(
            connection,
            counters,
            "sense_relations",
            (
                (
                    sense_id,
                    relation.type,
                    relation.target_lemma,
                    relation.target_source_id,
                    relation.target_homonym_number,
                )
                for relation in sense.sense_relations
            ),
        )


def build_database(
    source_path: str | os.PathLike[str],
    database_path: str | os.PathLike[str],
    *,
    source_date: str,
    resource_version: str,
    build_date: str,
) -> BuildResult:
    """Build and atomically activate one complete deterministic SQLite seed."""

    source = Path(source_path)
    destination = Path(database_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    started = time.perf_counter()
    counters = dict.fromkeys(_TABLES, 0)
    scanned = KRDICTSource(source)
    try:
        connection = sqlite3.connect(temporary)
        try:
            create_schema(connection)
            connection.execute("BEGIN")
            for entry_id, entry in enumerate(scanned.iter_entries(), start=1):
                _insert_entry(connection, entry, entry_id, counters)
            metadata = (
                ("schema_version", "1"),
                ("resource_version", resource_version),
                ("source", "krdict"),
                ("source_date", source_date),
                ("build_date", build_date),
                ("entry_count", str(scanned.entry_count)),
                ("sense_count", str(scanned.sense_count)),
            )
            connection.executemany(
                "INSERT INTO resource_metadata(key, value) VALUES (?, ?)", metadata
            )
            connection.commit()
            create_indexes(connection)
            connection.execute("ANALYZE")
            connection.commit()
        finally:
            connection.close()
        os.replace(temporary, destination)
    except (KRDICTSourceError, OSError, sqlite3.Error, ValueError) as exc:
        raise BuildError(f"unable to build KRDICT database: {exc}") from exc
    finally:
        temporary.unlink(missing_ok=True)

    return BuildResult(
        database_path=destination.resolve(),
        entry_count=scanned.entry_count,
        sense_count=scanned.sense_count,
        sanitized_byte_count=scanned.sanitized_byte_count,
        xml_member_count=scanned.xml_member_count,
        row_counts=dict(counters),
        duration_seconds=time.perf_counter() - started,
    )


def create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


def create_indexes(connection: sqlite3.Connection) -> None:
    connection.executescript(INDEX_SQL)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source-date", required=True)
    parser.add_argument("--resource-version", required=True)
    parser.add_argument("--build-date", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = build_database(
        args.source,
        args.output,
        source_date=args.source_date,
        resource_version=args.resource_version,
        build_date=args.build_date,
    )
    print(
        json.dumps(
            {
                "database": str(result.database_path),
                "duration_seconds": result.duration_seconds,
                "entries": result.entry_count,
                "senses": result.sense_count,
                "sanitized_0x08_bytes": result.sanitized_byte_count,
                "xml_members": result.xml_member_count,
                "row_counts": result.row_counts,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
