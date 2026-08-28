"""Literal regressions transcribed manually from the 2026-08-19 raw XML."""
# ruff: noqa: E501 -- exact source values must remain easy to compare verbatim.

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

import pytest

DATABASE = Path(__file__).parents[2] / "data" / "generated" / "krdict.sqlite3"


def _database() -> Path:
    if DATABASE.is_file():
        return DATABASE
    if os.environ.get("HANLY_REQUIRE_REAL_KRDICT") == "1":
        pytest.fail(f"required production KRDICT database is missing: {DATABASE}")
    pytest.skip("production KRDICT database is a local generated artifact")


def _rows(
    connection: sqlite3.Connection, sql: str, key: int
) -> list[tuple[Any, ...]]:
    return [tuple(row) for row in connection.execute(sql, (key,))]


def _entry_record(source_id: int, written_form: str) -> dict[str, Any]:
    with sqlite3.connect(_database()) as connection:
        connection.row_factory = sqlite3.Row
        entry = connection.execute(
            """SELECT e.*, l.written_form AS primary_lemma
               FROM entries AS e
               JOIN lemmas AS l ON l.entry_id = e.id AND l.is_primary = 1
               WHERE e.source = 'krdict' AND e.source_id = ? AND l.written_form = ?""",
            (source_id, written_form),
        ).fetchone()
        assert entry is not None
        entry_id = int(entry["id"])
        senses = []
        for sense in connection.execute(
            "SELECT * FROM senses WHERE entry_id = ? ORDER BY sense_order", (entry_id,)
        ):
            sense_id = int(sense["id"])
            senses.append(
                {
                    "source_sense_id": sense["source_sense_id"],
                    "sense_order": sense["sense_order"],
                    "korean_definition": sense["korean_definition"],
                    "annotation": sense["annotation"],
                    "syntactic_annotation": sense["syntactic_annotation"],
                    "translations": _rows(
                        connection,
                        """SELECT language, lemma, definition FROM translations
                           WHERE sense_id = ? ORDER BY id""",
                        sense_id,
                    ),
                    "examples": _rows(
                        connection,
                        """SELECT example_group, example_order, type, text FROM examples
                           WHERE sense_id = ? ORDER BY example_group, example_order""",
                        sense_id,
                    ),
                    "patterns": _rows(
                        connection,
                        """SELECT pattern_order, pattern FROM syntactic_patterns
                           WHERE sense_id = ? ORDER BY pattern_order""",
                        sense_id,
                    ),
                    "relations": _rows(
                        connection,
                        """SELECT type, target_lemma, target_source_id, target_homonym_number
                           FROM sense_relations WHERE sense_id = ? ORDER BY id""",
                        sense_id,
                    ),
                }
            )
        return {
            "entry": (
                entry["source"],
                entry["source_id"],
                entry["lexical_unit"],
                entry["homonym_number"],
                entry["part_of_speech"],
                entry["vocabulary_level"],
                entry["origin"],
                entry["annotation"],
                entry["primary_lemma"],
            ),
            "lemmas": _rows(
                connection,
                """SELECT written_form, variant, is_primary FROM lemmas
                   WHERE entry_id = ? ORDER BY id""",
                entry_id,
            ),
            "word_forms": _rows(
                connection,
                """SELECT type, written_form, pronunciation FROM word_forms
                   WHERE entry_id = ? ORDER BY id""",
                entry_id,
            ),
            "categories": _rows(
                connection,
                "SELECT type, value FROM categories WHERE entry_id = ? ORDER BY id",
                entry_id,
            ),
            "related_forms": _rows(
                connection,
                """SELECT type, written_form, target_source_id FROM related_forms
                   WHERE entry_id = ? ORDER BY id""",
                entry_id,
            ),
            "senses": senses,
        }


def test_ga_27733_preserves_the_complete_two_sense_record() -> None:
    record = _entry_record(27733, "가")

    assert record == {
        "entry": ("krdict", 27733, "단어", 1, "명사", "고급", None, None, "가"),
        "lemmas": [("가", None, 1)],
        "word_forms": [("발음", None, "가ː")],
        "categories": [("semantic", "자연 > 지형")],
        "related_forms": [],
        "senses": [
            {
                "source_sense_id": 1,
                "sense_order": 1,
                "korean_definition": "어떤 장소나 물건의 둘레나 끝부분.",
                "annotation": None,
                "syntactic_annotation": None,
                "translations": [
                    ("en", "edge; verge", "The perimeter or outer limits of a place or a thing.")
                ],
                "examples": [
                    (1, 1, "구", "가를 꾸미다."),
                    (2, 1, "구", "가를 장식하다."),
                    (3, 1, "구", "가에 걸치다."),
                    (4, 1, "구", "가에 달다."),
                    (5, 1, "구", "가에 달라붙다."),
                    (6, 1, "구", "가에 세우다."),
                    (7, 1, "구", "가에 앉다."),
                    (8, 1, "문장", "공원의 중앙에는 잔디밭이 있고 가에는 울타리가 둘러쳐져 있었다."),
                    (9, 1, "문장", "민준이는 금방이라도 일어날 듯이 의자 가에 엉덩이만 살짝 걸치고 앉았다."),
                    (10, 1, "대화", "차는 어디에 주차했어요?"),
                    (10, 2, "대화", "저기 운동장 가에 세워 뒀어요."),
                ],
                "patterns": [],
                "relations": [],
            },
            {
                "source_sense_id": 2,
                "sense_order": 2,
                "korean_definition": "‘주변’의 뜻을 나타내는 말.",
                "annotation": "일부 명사 뒤에 붙여 쓴다.",
                "syntactic_annotation": None,
                "translations": [("en", "by; fringe", "The surrounding area of a place.")],
                "examples": [
                    (1, 1, "구", "강가."),
                    (2, 1, "구", "길가."),
                    (3, 1, "구", "냇가."),
                    (4, 1, "구", "문가."),
                    (5, 1, "구", "시냇가."),
                    (6, 1, "구", "우물가."),
                    (7, 1, "구", "창가."),
                    (8, 1, "구", "창문가."),
                    (9, 1, "구", "호숫가."),
                ],
                "patterns": [],
                "relations": [],
            },
        ],
    }


def test_cheomseongdae_600265_preserves_the_complete_v1_record() -> None:
    record = _entry_record(600265, "첨성대")

    assert record == {
        "entry": (
            "krdict",
            600265,
            "단어",
            0,
            "명사",
            "없음",
            "瞻星臺",
            None,
            "첨성대",
        ),
        "lemmas": [("첨성대", None, 1)],
        "word_forms": [("발음", None, "첨성대")],
        "categories": [("semantic", "문화 > 전통 문화")],
        "related_forms": [],
        "senses": [
            {
                "source_sense_id": 1,
                "sense_order": 1,
                "korean_definition": "경주시에 있는 신라 선덕 여왕 때 만들어진 천문 기상 관측 시설. ",
                "annotation": None,
                "syntactic_annotation": None,
                "translations": [
                    (
                        "en",
                        "Cheomseongdae",
                        "An astronomical and meteorological observation facility that was built during the reign of Queen Seondeok of Silla, located in Gyeongju.",
                    )
                ],
                "examples": [],
                "patterns": [],
                "relations": [],
            }
        ],
    }


def test_cheomyeohada_77500_preserves_conjugations_short_form_and_dialogue() -> None:
    record = _entry_record(77500, "첨예하다")

    assert record["entry"] == (
        "krdict",
        77500,
        "단어",
        0,
        "형용사",
        "고급",
        "尖銳하다",
        None,
        "첨예하다",
    )
    assert record["lemmas"] == [("첨예하다", None, 1)]
    assert record["word_forms"] == [
        ("발음", None, "처몌하다"),
        ("활용", "첨예한", "처몌한"),
        ("활용", "첨예하여", "처몌하여"),
        ("준말", "첨예해", "처몌해"),
        ("활용", "첨예하니", "처몌하니"),
        ("활용", "첨예합니다", "처몌함니다"),
    ]
    assert record["categories"] == [
        ("semantic", "인간 > 태도"),
        ("subject", "사회 문제"),
    ]
    assert record["related_forms"] == []
    assert record["senses"] == [
        {
            "source_sense_id": 1,
            "sense_order": 1,
            "korean_definition": "상황이나 사태가 날카롭고 거세다.",
            "annotation": None,
            "syntactic_annotation": None,
            "translations": [
                ("en", "acute; intense", "A situation or matter being acute and violent.")
            ],
            "examples": [
                (1, 1, "구", "첨예한 갈등."),
                (2, 1, "구", "첨예한 대조."),
                (3, 1, "구", "첨예하게 그리다."),
                (4, 1, "구", "첨예하게 나타나다."),
                (5, 1, "구", "첨예하게 대립하다."),
                (6, 1, "문장", "여야가 첨예한 갈등을 풀지 못한 채 국회는 파행을 맞고 있다."),
                (7, 1, "문장", "양국이 영토 문제를 둘러싸고 첨예하게 대립하고 있다."),
                (8, 1, "문장", "김 감독의 이번 영화는 계급 간의 갈등을 첨예하게 그리고 있다."),
                (9, 1, "대화", "여론 조사 결과는 어떻습니까?"),
                (9, 2, "대화", "문제에 대해 찬반 입장이 첨예하게 다르게 나타나고 있습니다."),
            ],
            "patterns": [(1, "1이 첨예하다")],
            "relations": [],
        }
    ]


def test_related_form_and_sense_relation_remain_distinct_external_references() -> None:
    related = _entry_record(77504, "첨예화")
    relation = _entry_record(77519, "첩")

    assert related["related_forms"] == [
        ("파생어", "첨예화되다", 77505),
        ("파생어", "첨예화하다", 77508),
    ]
    assert relation["entry"] == (
        "krdict",
        77519,
        "단어",
        1,
        "명사",
        "고급",
        "妾",
        None,
        "첩",
    )
    assert relation["word_forms"] == [
        ("발음", None, "첩"),
        ("활용", "첩이", "처비"),
        ("활용", "첩도", "첩또"),
        ("활용", "첩만", "첨만"),
    ]
    assert relation["senses"][0]["relations"] == [
        ("유의어", "작은마누라", 76097, 0)
    ]


def test_reused_source_id_77610_preserves_every_distinct_raw_entry() -> None:
    with sqlite3.connect(_database()) as connection:
        rows = connection.execute(
            """SELECT e.id, l.written_form FROM entries AS e
               JOIN lemmas AS l ON l.entry_id = e.id AND l.is_primary = 1
               WHERE e.source = 'krdict' AND e.source_id = 77610 ORDER BY e.id"""
        ).fetchall()

    assert len({row[0] for row in rows}) == 4
    assert [row[1] for row in rows] == [
        "첫",
        "첫 단추를 끼우다",
        "첫 단추를 잘못 끼우다",
        "첫 삽을 뜨다",
    ]
