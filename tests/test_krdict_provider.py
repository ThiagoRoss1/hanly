"""Focused tests for the read-only KRDICT provider."""

import sqlite3
import threading

import pytest
from hanly import DictionaryEntry, DictionaryProvider, ProviderError
from hanly.krdict_provider import KRDICTProvider, KRDICTProviderError

from tests.hanly_fixtures.krdict import build_fixture_krdict, build_krdict_database


def _database(tmp_path):
    return build_fixture_krdict(tmp_path)


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
        DictionaryEntry(
            headword="먹다",
            definitions=("to eat",),
            part_of_speech="동사",
            source="krdict",
        ),
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


def test_provider_exposes_real_hanja_without_relabeling_plain_origin_text(tmp_path) -> None:
    xml = """<?xml version="1.0" encoding="utf-8"?>
<LexicalResource><Lexicon>
  <LexicalEntry att="id" val="1">
    <feat att="lexicalUnit" val="단어" /><feat att="partOfSpeech" val="명사" />
    <feat att="origin" val="文化" /><feat att="vocabularyLevel" val="초급" />
    <Lemma><feat att="writtenForm" val="문화" /></Lemma>
    <Sense att="id" val="11"><feat att="definition" val="사회가 만든 생활 양식" />
      <Equivalent><feat att="language" val="영어" />
        <feat att="lemma" val="culture" />
        <feat att="definition" val="culture" /></Equivalent>
    </Sense>
  </LexicalEntry>
  <LexicalEntry att="id" val="2">
    <feat att="lexicalUnit" val="단어" /><feat att="partOfSpeech" val="명사" />
    <feat att="origin" val="robot" />
    <Lemma><feat att="writtenForm" val="로봇" /></Lemma>
    <Sense att="id" val="21"><feat att="definition" val="기계" />
      <Equivalent><feat att="language" val="영어" />
        <feat att="lemma" val="robot" />
        <feat att="definition" val="robot" /></Equivalent>
    </Sense>
  </LexicalEntry>
</Lexicon></LexicalResource>"""
    database = build_krdict_database(tmp_path, xml)

    with KRDICTProvider(database) as provider:
        culture = provider.lookup("문화")[0]
        robot = provider.lookup("로봇")[0]

    assert culture.hanja == "文化"
    assert culture.vocabulary_level == "초급"
    assert culture.source == "krdict"
    assert robot.hanja is None
