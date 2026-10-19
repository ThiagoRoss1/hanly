"""Private controlled-image text stays out of durable Lab outcomes."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from lab.session.corpus import TourTarget
from lab.session.driver import _Observation
from lab.session.stress import StressItem
from lab.session.stress_driver import StressDriver


class _Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def lab(self, name: str, **fields: Any) -> None:
        self.events.append((name, fields))


def test_private_corpus_result_keeps_verdict_but_drops_expected_content() -> None:
    recorder = _Recorder()
    driver = StressDriver.__new__(StressDriver)
    driver.completed = 0
    driver._retain_fixture_text = False
    driver._retain_images = False
    driver._recorder = cast(Any, recorder)
    target = TourTarget(
        id="private-case#1",
        source="corpus",
        line="민감한 예문",
        start=0,
        surface="민감한",
        cursor=0,
        lemma=None,
        headword=None,
        refuse=False,
    )
    item = StressItem(
        target,
        "corpus",
        truth_target="surface",
        case="private-case",
        private=True,
    )
    placed = SimpleNamespace(
        target=target,
        font_family="fixture",
        font_px=16,
        theme="light",
        item=item,
    )

    driver._finish(
        placed,
        _Observation(),
        1,
        unscored="obscured",
        foreign=["foreign"],
    )

    name, result = recorder.events[0]
    assert name == "stress_result"
    assert result["family"] == "corpus"
    assert result["truth_target"] == "surface"
    assert "verdict" in result
    assert not {"surface", "expected", "expected_lemma", "cursor", "region"} & result.keys()
    assert "민감한" not in repr(result)
