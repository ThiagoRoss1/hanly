"""Runtime validation and lookup tests for the normalized KRDICT seed."""

from __future__ import annotations

import sqlite3

import pytest
from hanly import DictionaryEntry
from hanly.krdict_provider import KRDICTProvider, KRDICTProviderError
from hanly.krdict_schema import KRDICT_REQUIRED_INDEXES, validate_krdict_connection

from tests.hanly_fixtures.krdict import build_fixture_krdict


def test_shared_schema_validator_checks_metadata_counts_and_indexes(tmp_path) -> None:
    database = build_fixture_krdict(tmp_path)

    with sqlite3.connect(database) as connection:
        metadata = validate_krdict_connection(connection)
        indexes = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' AND name NOT LIKE 'sqlite_%'"
            )
        }

    assert metadata["resource_version"] == "fixture-v1"
    assert set(KRDICT_REQUIRED_INDEXES) == indexes


def test_provider_looks_up_primary_lemmas_and_inflected_word_forms(tmp_path) -> None:
    database = build_fixture_krdict(tmp_path)

    with KRDICTProvider(database) as provider:
        assert provider.lookup(" 먹다 ") == (
            DictionaryEntry("먹다", ("to eat",), "동사"),
        )
        assert provider.lookup("먹어요") == (
            DictionaryEntry("먹다", ("to eat",), "동사"),
        )


def test_provider_rejects_a_seed_with_inconsistent_metadata_count(tmp_path) -> None:
    database = build_fixture_krdict(tmp_path)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE resource_metadata SET value = '999' WHERE key = 'entry_count'"
        )

    with pytest.raises(KRDICTProviderError, match="incompatible"):
        KRDICTProvider(database)
