"""The dictionary that keeps the packaged runtime smoke off the network."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from hanly.krdict_provider import KRDICTProvider
from hanly.krdict_schema import KRDICT_SCHEMA_VERSION, validate_krdict_connection
from hanly_app.self_check import DICTIONARY_PROBE

from tools.build_smoke_krdict import (
    PROBE_LEMMAS,
    SMOKE_RESOURCE_VERSION,
    build_smoke_krdict,
    main,
)


@pytest.fixture(name="database")
def _database(tmp_path: Path) -> Path:
    return build_smoke_krdict(tmp_path / "krdict.sqlite3")


def test_the_smoke_dictionary_satisfies_the_runtime_resource_contract(
    database: Path,
) -> None:
    """It travels the same install path a released asset does, so a database
    the runtime would reject is no cheaper here than it is on a user's machine."""

    connection = sqlite3.connect(database)
    try:
        metadata = validate_krdict_connection(connection)
    finally:
        connection.close()

    assert metadata["schema_version"] == str(KRDICT_SCHEMA_VERSION)
    assert metadata["resource_version"] == SMOKE_RESOURCE_VERSION
    assert int(metadata["entry_count"]) == len(PROBE_LEMMAS)


def test_the_smoke_dictionary_answers_what_the_packaged_self_check_asks(
    database: Path,
) -> None:
    """The frozen check looks one fixed word up. A corpus without it turns a
    working bundle into a failing release for no reason at all."""

    assert DICTIONARY_PROBE in PROBE_LEMMAS
    with KRDICTProvider(database) as dictionary:
        assert all(dictionary.lookup(lemma) for lemma in PROBE_LEMMAS)


def test_two_builds_of_the_same_source_produce_the_same_database(
    tmp_path: Path, database: Path
) -> None:
    rebuilt = build_smoke_krdict(tmp_path / "again" / "krdict.sqlite3")

    assert rebuilt.read_bytes() == database.read_bytes()


def test_the_command_writes_where_it_was_told_and_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    destination = tmp_path / "runner-temp" / "krdict.sqlite3"

    assert main([str(destination)]) == 0
    assert capsys.readouterr().out.strip() == str(destination.resolve())
    assert destination.is_file()
