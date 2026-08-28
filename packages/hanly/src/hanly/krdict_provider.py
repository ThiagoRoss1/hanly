"""Read-only runtime adapter for the built KRDICT SQLite artifact."""

from __future__ import annotations

import os
import sqlite3
import unicodedata
from collections import OrderedDict
from pathlib import Path

from .contracts import DictionaryEntry
from .errors import ProviderError
from .krdict_schema import validate_krdict_connection


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
            validate_krdict_connection(connection)
        except sqlite3.Error as exc:
            raise KRDICTProviderError("KRDICT database is unreadable") from exc
        except ValueError as exc:
            raise KRDICTProviderError(
                "KRDICT database is incompatible with the Hanly KRDICT schema"
            ) from exc

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
                WITH candidates(entry_id) AS (
                    SELECT entry_id FROM lemmas WHERE written_form = ?
                    UNION
                    SELECT entry_id FROM word_forms WHERE written_form = ?
                )
                SELECT e.id AS entry_id, l.written_form AS headword,
                       e.part_of_speech, s.sense_order, t.id AS translation_id,
                       t.definition
                FROM candidates AS c
                JOIN entries AS e ON e.id = c.entry_id
                JOIN lemmas AS l ON l.entry_id = e.id AND l.is_primary = 1
                JOIN senses AS s ON s.entry_id = e.id
                JOIN translations AS t ON t.sense_id = s.id AND t.language = 'en'
                ORDER BY e.id, s.sense_order, t.id
                """,
                (normalized_lemma, normalized_lemma),
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
