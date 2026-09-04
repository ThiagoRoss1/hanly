"""Validate a normalized KRDICT seed against its canonical source ZIP."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    # Run as a plain script rather than ``python -m``, so the repository root
    # is not on the path and ``tools.krdict`` cannot be imported without it.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass

from hanly.krdict_schema import (
    KRDICT_REQUIRED_INDEXES,
    KRDICTSchemaError,
    validate_krdict_connection,
)

from tools.krdict import configure_utf8_output
from tools.krdict.source import KRDICTSource, KRDICTSourceError

CONTENT_TABLES = (
    "entries",
    "lemmas",
    "senses",
    "translations",
    "examples",
    "word_forms",
    "categories",
    "related_forms",
    "syntactic_patterns",
    "sense_relations",
    "resource_metadata",
)


class ValidationError(RuntimeError):
    """Raised when a source/database pair violates the production contract."""


@dataclass(frozen=True, slots=True)
class ValidationReport:
    database: str
    source: str
    source_sha256: str
    source_xml_members: int
    source_entry_count: int
    source_sense_count: int
    source_english_translation_count: int
    sanitized_byte_count: int
    distinct_source_id_count: int
    reused_source_id_count: int
    maximum_source_id_reuse: int
    row_counts: Mapping[str, int]
    metadata: Mapping[str, str]
    indexes: tuple[str, ...]
    integrity_check: str
    foreign_key_violations: int
    analyze_rows: int
    query_plans: Mapping[str, str]
    benchmark_ms: Mapping[str, float]
    duration_seconds: float


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _query_plan(
    connection: sqlite3.Connection, sql: str, parameters: tuple[object, ...]
) -> str:
    return " | ".join(
        str(row[3])
        for row in connection.execute(f"EXPLAIN QUERY PLAN {sql}", parameters)
    )


def _benchmark(
    connection: sqlite3.Connection,
    sql: str,
    parameters: tuple[object, ...],
    *,
    iterations: int = 50,
) -> float:
    """Return the mean milliseconds one indexed lookup costs on this database."""

    started = time.perf_counter_ns()
    for _ in range(iterations):
        connection.execute(sql, parameters).fetchall()
    return (time.perf_counter_ns() - started) / iterations / 1_000_000


def _plans_and_benchmarks(
    connection: sqlite3.Connection,
) -> tuple[dict[str, str], dict[str, float]]:
    lemma_row = connection.execute(
        "SELECT written_form, entry_id FROM lemmas WHERE is_primary = 1 ORDER BY id LIMIT 1"
    ).fetchone()
    if lemma_row is None:
        raise ValidationError("database contains no primary lemma to benchmark")
    lemma, entry_id = str(lemma_row[0]), int(lemma_row[1])
    form_row = connection.execute(
        "SELECT written_form FROM word_forms WHERE written_form IS NOT NULL ORDER BY id LIMIT 1"
    ).fetchone()
    word_form = str(form_row[0]) if form_row is not None else lemma
    sense_row = connection.execute(
        "SELECT id FROM senses WHERE entry_id = ? ORDER BY sense_order LIMIT 1",
        (entry_id,),
    ).fetchone()
    if sense_row is None:
        raise ValidationError("database contains no sense to benchmark")
    sense_id = int(sense_row[0])
    source_id = int(
        connection.execute("SELECT source_id FROM entries WHERE id = ?", (entry_id,)).fetchone()[
            0
        ]
    )

    queries: dict[str, tuple[str, tuple[object, ...]]] = {
        "lemma": (
            "SELECT entry_id FROM lemmas WHERE written_form = ? ORDER BY entry_id",
            (lemma,),
        ),
        "word_form": (
            "SELECT entry_id FROM word_forms WHERE written_form = ? ORDER BY entry_id",
            (word_form,),
        ),
        "source_id_candidates": (
            "SELECT id FROM entries WHERE source = 'krdict' AND source_id = ? ORDER BY id",
            (source_id,),
        ),
        "entry_senses": (
            "SELECT id FROM senses WHERE entry_id = ? ORDER BY sense_order",
            (entry_id,),
        ),
        "sense_english": (
            "SELECT definition FROM translations "
            "WHERE sense_id = ? AND language = 'en' ORDER BY id",
            (sense_id,),
        ),
        "first_example": (
            "SELECT text FROM examples WHERE sense_id = ? "
            "ORDER BY example_group, example_order LIMIT 1",
            (sense_id,),
        ),
    }
    plans = {
        name: _query_plan(connection, sql, parameters)
        for name, (sql, parameters) in queries.items()
    }
    benchmarks = {
        name: _benchmark(connection, sql, parameters)
        for name, (sql, parameters) in queries.items()
    }
    return plans, benchmarks


def validate_database(
    database_path: str | Path,
    *,
    source_path: str | Path,
    expected_entries: int | None = None,
    expected_senses: int | None = None,
    expected_sanitized_bytes: int | None = None,
) -> ValidationReport:
    """Return validation evidence or raise before an invalid seed can ship."""

    database = Path(database_path)
    source = Path(source_path)
    if not database.is_file():
        raise ValidationError(f"database does not exist: {database}")
    if not source.is_file():
        raise ValidationError(f"source does not exist: {source}")
    started = time.perf_counter()
    source_hash_before = _sha256(source)
    source_ids: Counter[int] = Counter()
    english_translation_count = 0
    scanned = KRDICTSource(source)
    try:
        for entry in scanned.iter_entries():
            source_ids[entry.source_id] += 1
            english_translation_count += sum(
                len(sense.translations) for sense in entry.senses
            )
    except (KRDICTSourceError, OSError) as exc:
        raise ValidationError(f"source scan failed: {exc}") from exc
    if _sha256(source) != source_hash_before:
        raise ValidationError("source archive changed during validation")

    if expected_entries is not None and scanned.entry_count != expected_entries:
        raise ValidationError(
            f"source entry count {scanned.entry_count} != expected {expected_entries}"
        )
    if expected_senses is not None and scanned.sense_count != expected_senses:
        raise ValidationError(
            f"source sense count {scanned.sense_count} != expected {expected_senses}"
        )
    if (
        expected_sanitized_bytes is not None
        and scanned.sanitized_byte_count != expected_sanitized_bytes
    ):
        raise ValidationError(
            "sanitized byte count "
            f"{scanned.sanitized_byte_count} != expected {expected_sanitized_bytes}"
        )

    connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
    try:
        try:
            integrity_rows = tuple(
                str(row[0]) for row in connection.execute("PRAGMA integrity_check")
            )
            if integrity_rows != ("ok",):
                raise ValidationError(
                    f"PRAGMA integrity_check failed: {'; '.join(integrity_rows)}"
                )
            foreign_key_rows = tuple(connection.execute("PRAGMA foreign_key_check"))
            if foreign_key_rows:
                raise ValidationError(
                    f"PRAGMA foreign_key_check found {len(foreign_key_rows)} violation(s)"
                )
            metadata = validate_krdict_connection(connection)
        except (sqlite3.Error, KRDICTSchemaError) as exc:
            raise ValidationError(f"database schema validation failed: {exc}") from exc

        if int(metadata["entry_count"]) != scanned.entry_count:
            raise ValidationError("metadata entry_count does not match source entry count")
        if int(metadata["sense_count"]) != scanned.sense_count:
            raise ValidationError("metadata sense_count does not match source sense count")

        row_counts = {
            table: int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            for table in CONTENT_TABLES
        }
        if row_counts["translations"] != english_translation_count:
            raise ValidationError(
                "English translation row count does not match source Equivalent mapping"
            )

        database_reuse = {
            int(source_id): int(count)
            for source_id, count in connection.execute(
                """SELECT source_id, COUNT(*) FROM entries
                   WHERE source = 'krdict' GROUP BY source_id"""
            )
        }
        if database_reuse != dict(source_ids):
            raise ValidationError("database source_id multiplicities do not match source")

        indexes = tuple(
            sorted(
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'index' AND name NOT LIKE 'sqlite_%'"
                )
            )
        )
        if set(indexes) != set(KRDICT_REQUIRED_INDEXES):
            raise ValidationError("database explicit index set is incompatible")
        analyze_rows = int(connection.execute("SELECT COUNT(*) FROM sqlite_stat1").fetchone()[0])
        if analyze_rows == 0:
            raise ValidationError("ANALYZE statistics are missing")
        query_plans, benchmark_ms = _plans_and_benchmarks(connection)
    finally:
        connection.close()

    reused = tuple(count for count in source_ids.values() if count > 1)
    return ValidationReport(
        database=str(database.resolve()),
        source=str(source.resolve()),
        source_sha256=source_hash_before,
        source_xml_members=scanned.xml_member_count,
        source_entry_count=scanned.entry_count,
        source_sense_count=scanned.sense_count,
        source_english_translation_count=english_translation_count,
        sanitized_byte_count=scanned.sanitized_byte_count,
        distinct_source_id_count=len(source_ids),
        reused_source_id_count=len(reused),
        maximum_source_id_reuse=max(reused, default=1 if source_ids else 0),
        row_counts=row_counts,
        metadata=metadata,
        indexes=indexes,
        integrity_check="ok",
        foreign_key_violations=0,
        analyze_rows=analyze_rows,
        query_plans=query_plans,
        benchmark_ms=benchmark_ms,
        duration_seconds=time.perf_counter() - started,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--expect-entries", type=int)
    parser.add_argument("--expect-senses", type=int)
    parser.add_argument("--expect-sanitized-bytes", type=int)
    parser.add_argument("--report", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    configure_utf8_output()
    args = _parser().parse_args(argv)
    try:
        report = validate_database(
            args.database,
            source_path=args.source,
            expected_entries=args.expect_entries,
            expected_senses=args.expect_senses,
            expected_sanitized_bytes=args.expect_sanitized_bytes,
        )
    except ValidationError as exc:
        raise SystemExit(f"error: {exc}") from exc
    payload = json.dumps(asdict(report), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
