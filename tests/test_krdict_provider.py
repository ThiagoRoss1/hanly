"""Focused HAN-9 tests for the read-only KRDICT provider."""

import sqlite3
import threading

import pytest
from hanly import DictionaryEntry, DictionaryProvider, ProviderError
from hanly.krdict_build import build_krdict_database
from hanly.krdict_provider import KRDICTProvider, KRDICTProviderError


def _database(tmp_path):
    source = tmp_path / "krdict.xml"
    source.write_text(
        """<dictionary>
  <entry><headword>먹다</headword><part_of_speech>동사</part_of_speech>
    <definition lang="en">to eat</definition></entry>
  <entry><headword>책</headword><part_of_speech>명사</part_of_speech>
    <definition lang="en">a book</definition><definition lang="en">book</definition></entry>
</dictionary>""",
        encoding="utf-8",
    )
    database = tmp_path / "krdict.sqlite3"
    build_krdict_database(source, database)
    return database


def test_cross_thread_lookup_reports_thread_affinity_not_an_unreadable_file(
    tmp_path,
) -> None:
    """A SQLite connection belongs to the thread that opened it.

    The misleading "unreadable database" message would send a debugger after
    the file instead of the caller, so the thread violation is named directly.
    """

    database = _database(tmp_path)
    failures: list[str] = []

    with KRDICTProvider(database) as provider:
        assert provider.lookup("책")

        def worker() -> None:
            try:
                provider.lookup("책")
            except KRDICTProviderError as exc:
                failures.append(str(exc))

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()

    assert failures, "expected the cross-thread lookup to fail"
    assert "thread" in failures[0]
    assert "unreadable" not in failures[0]


def test_provider_is_protocol_conformant_and_normalizes_entries(tmp_path) -> None:
    database = _database(tmp_path)

    with KRDICTProvider(database) as provider:
        assert isinstance(provider, DictionaryProvider)
        entries = provider.lookup("  먹다 ")

    assert entries == (
        DictionaryEntry(headword="먹다", definitions=("to eat",), part_of_speech="동사"),
    )
    assert all(isinstance(entry, DictionaryEntry) for entry in entries)


def test_provider_returns_all_definitions_and_empty_for_not_found(tmp_path) -> None:
    database = _database(tmp_path)

    provider = KRDICTProvider(database)
    try:
        assert provider.lookup("책")[0].definitions == ("a book", "book")
        assert provider.lookup("없는 단어") == ()
    finally:
        provider.close()


def test_provider_fails_clearly_for_unreadable_or_incompatible_database(tmp_path) -> None:
    with pytest.raises(KRDICTProviderError, match="unreadable"):
        KRDICTProvider(tmp_path / "missing.sqlite3")

    incompatible = tmp_path / "incompatible.sqlite3"
    with sqlite3.connect(incompatible) as connection:
        connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)")
        connection.execute(
            "INSERT INTO metadata(key, value) VALUES ('schema_marker', 'wrong')"
        )

    with pytest.raises(KRDICTProviderError, match="incompatible"):
        KRDICTProvider(incompatible)


def test_provider_opens_database_read_only_and_does_not_expose_rows(tmp_path) -> None:
    database = _database(tmp_path)
    provider = KRDICTProvider(database)
    try:
        entries = provider.lookup("책")
        assert isinstance(entries[0], DictionaryEntry)
        assert not isinstance(entries[0], sqlite3.Row)
        connection = provider._connection
        assert connection is not None
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("CREATE TABLE should_not_exist (id INTEGER)")
    finally:
        provider.close()


def test_provider_error_is_a_hanly_provider_error() -> None:
    assert issubclass(KRDICTProviderError, ProviderError)
