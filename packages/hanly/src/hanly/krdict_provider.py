"""Read-only runtime adapter for the built KRDICT SQLite artifact."""

from __future__ import annotations

import os
import sqlite3
import unicodedata
from collections import OrderedDict
from pathlib import Path

from .contracts import DictionaryEntry
from .errors import ProviderError
from .krdict_build import (
    KRDICT_SCHEMA_MARKER,
    KRDICT_SCHEMA_NAME,
    KRDICT_SCHEMA_VERSION,
)


class KRDICTProviderError(ProviderError):
    """Raised when the KRDICT database is unreadable or incompatible."""


def _normalise(value: str | None) -> str:
    if value is None:
        return ""
    value = unicodedata.normalize("NFC", value)
    return " ".join(value.split())


class KRDICTProvider:
    """Look up normalized dictionary entries from an explicit database path.

    The connection uses SQLite's ``mode=ro`` URI flag.  No source processing,
    ResourceManager interaction, or SQLite row objects cross the provider seam;
    callers receive only ``DictionaryEntry`` instances.
    """

    def __init__(self, database_path: str | os.PathLike[str]) -> None:
        self.database_path = Path(database_path).expanduser()
        self._connection: sqlite3.Connection | None = None
        if not self.database_path.is_file():
            raise KRDICTProviderError(
                f"KRDICT database is unreadable: {self.database_path}"
            )

        try:
            connection = sqlite3.connect(
                f"{self.database_path.resolve().as_uri()}?mode=ro",
                uri=True,
            )
            connection.row_factory = sqlite3.Row
            self._validate_schema(connection)
        except KRDICTProviderError:
            if "connection" in locals():
                connection.close()
            raise
        except (OSError, sqlite3.Error) as exc:
            if "connection" in locals():
                connection.close()
            raise KRDICTProviderError(
                f"KRDICT database is unreadable: {self.database_path}"
            ) from exc
        self._connection = connection

    @staticmethod
    def _validate_schema(connection: sqlite3.Connection) -> None:
        try:
            table_names = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        except sqlite3.Error as exc:
            raise KRDICTProviderError("KRDICT database is unreadable") from exc

        required_tables = {"metadata", "entries", "definitions"}
        if not required_tables.issubset(table_names):
            raise KRDICTProviderError(
                "KRDICT database is incompatible: required tables are missing"
            )

        try:
            metadata = dict(
                connection.execute("SELECT key, value FROM metadata").fetchall()
            )
            user_version = connection.execute("PRAGMA user_version").fetchone()[0]
            entry_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(entries)")
            }
            definition_columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(definitions)")
            }
            index_names = {
                row[1] for row in connection.execute("PRAGMA index_list('entries')")
            }
        except sqlite3.Error as exc:
            raise KRDICTProviderError(
                "KRDICT database is unreadable while checking its schema"
            ) from exc

        if (
            metadata.get("schema_name") != KRDICT_SCHEMA_NAME
            or metadata.get("schema_marker") != KRDICT_SCHEMA_MARKER
            or metadata.get("schema_version") != str(KRDICT_SCHEMA_VERSION)
            or metadata.get("source_language") != "ko"
            or metadata.get("target_language") != "en"
            or user_version != KRDICT_SCHEMA_VERSION
            or not {"id", "headword", "part_of_speech"}.issubset(entry_columns)
            or not {"entry_id", "ordinal", "definition"}.issubset(definition_columns)
            or "idx_entries_headword" not in index_names
        ):
            raise KRDICTProviderError(
                "KRDICT database is incompatible with the Hanly KRDICT schema"
            )

    def _require_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise KRDICTProviderError("KRDICT provider is closed")
        return self._connection

    def lookup(self, lemma: str) -> tuple[DictionaryEntry, ...]:
        """Return all entries for ``lemma`` or an empty tuple when absent."""

        if not isinstance(lemma, str):
            raise TypeError("KRDICT lookup lemma must be a string")
        normalized_lemma = _normalise(lemma)
        if not normalized_lemma:
            return ()

        connection = self._require_connection()
        try:
            rows = connection.execute(
                """
                SELECT e.id AS entry_id, e.headword, e.part_of_speech,
                       d.ordinal, d.definition
                FROM entries AS e
                JOIN definitions AS d ON d.entry_id = e.id
                WHERE e.headword = ?
                ORDER BY e.id, d.ordinal
                """,
                (normalized_lemma,),
            ).fetchall()
        except sqlite3.ProgrammingError as exc:
            # A SQLite connection belongs to the thread that opened it. Without
            # this branch the violation is reported as an unreadable database,
            # which points a debugger at the file instead of the caller.
            raise KRDICTProviderError(
                "KRDICT lookup was called from a different thread than the one "
                "that opened the database; open a connection per thread"
            ) from exc
        except sqlite3.Error as exc:
            raise KRDICTProviderError(
                "KRDICT database became unreadable during lookup"
            ) from exc

        grouped: OrderedDict[int, tuple[str, str | None, list[str]]] = OrderedDict()
        for row in rows:
            entry_id = int(row["entry_id"])
            if entry_id not in grouped:
                grouped[entry_id] = (
                    _normalise(row["headword"]),
                    _normalise(row["part_of_speech"]) or None,
                    [],
                )
            definitions = grouped[entry_id][2]
            definition = _normalise(row["definition"])
            if definition and definition not in definitions:
                definitions.append(definition)

        entries: list[DictionaryEntry] = []
        try:
            for headword, part_of_speech, definitions in grouped.values():
                if not headword or not definitions:
                    raise ValueError("an entry has no normalized headword or definition")
                entries.append(
                    DictionaryEntry(
                        headword=headword,
                        definitions=tuple(definitions),
                        part_of_speech=part_of_speech,
                    )
                )
        except ValueError as exc:
            raise KRDICTProviderError(
                "KRDICT database is incompatible: entry data is invalid"
            ) from exc
        return tuple(entries)

    def close(self) -> None:
        """Close the read-only connection; safe to call more than once."""

        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def __enter__(self) -> KRDICTProvider:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        # Nothing here inspects the exception, and returning None keeps any
        # error raised inside the with-block propagating.
        self.close()


__all__ = ["KRDICTProvider", "KRDICTProviderError"]
