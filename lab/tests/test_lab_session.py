"""The lab session: what it records, what it refuses to record, and what it reports."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from lab.cli import _parser, with_default_verb
from lab.report.build import build_report
from lab.report.model import build_model
from lab.session.corpus import TourTarget, story_targets, word_targets
from lab.session.driver import _judge, _Observation
from lab.session.recorder import LabDiagnosticLog, LabRecorder


def _events(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# -- recorder ---------------------------------------------------------------------------


def test_evidence_reaches_disk_only_inside_a_verified_hover(tmp_path: Path) -> None:
    recorder = LabRecorder(tmp_path / "events.jsonl", retain_evidence=True, retain_geometry=True)
    stage = {
        "event_kind": "lookup_stage_completed",
        "timestamp_ns": 1,
        "stage": "ocr",
        "ocr_evidence": '{"text":"secret"}',
        "region_count": 1,
    }

    recorder.emit(stage)
    recorder.evidence_open = True
    recorder.emit(stage)
    recorder.close()

    first, second = _events(tmp_path / "events.jsonl")
    assert "ocr_evidence" not in first and first["region_count"] == 1
    assert second["ocr_evidence"] == '{"text":"secret"}'


def test_a_failing_listener_never_reaches_the_app(tmp_path: Path) -> None:
    recorder = LabRecorder(tmp_path / "events.jsonl", retain_evidence=False, retain_geometry=False)
    seen: list[str] = []

    def broken(name: str, *_: object) -> None:
        raise RuntimeError("lab bug")

    recorder.subscribe(broken)
    recorder.subscribe(lambda name, *_: seen.append(name))
    recorder.emit({"event_kind": "hover_stable_fire", "timestamp_ns": 5})
    recorder.lab("tour_page", page=0)
    recorder.close()

    assert seen == ["hover_stable_fire", "tour_page"]
    assert recorder.counts == {"hover_stable_fire": 1, "tour_page": 1}


def test_startup_lines_become_structured_phases(tmp_path: Path) -> None:
    recorder = LabRecorder(tmp_path / "events.jsonl", retain_evidence=False, retain_geometry=False)
    log = LabDiagnosticLog(recorder, tmp_path / "logs" / "hanly.log")

    log.record("Startup", "resources: 232 ms (ok, attempt 1)")
    log.record("Startup", "runtime ready at 675 ms")
    log.record("Capture", f"saved under {Path.home()}/secret")
    recorder.close()

    phase, milestone, other = _events(tmp_path / "events.jsonl")
    assert (phase["event"], phase["name"], phase["duration_ms"]) == (
        "startup_phase",
        "resources",
        232,
    )
    assert (milestone["name"], milestone["at_ms"]) == ("runtime ready", 675)
    assert str(Path.home()) not in other["message"]


# -- scoring a hover ---------------------------------------------------------------------


def _placed(**target: Any) -> Any:
    fields: dict[str, Any] = {
        "id": "t1",
        "source": "words",
        "line": "가다",
        "start": 0,
        "surface": "가다",
        "cursor": 1,
        "lemma": "가다",
        "headword": "가다",
    }
    fields.update(target)
    return SimpleNamespace(target=TourTarget(**fields), font_family="F", font_px=22, theme="light")


def _seen(**result: Any) -> _Observation:
    observation = _Observation()
    observation.lookup_ids.add(1)
    observation.result = result or None
    return observation


@pytest.mark.parametrize(
    ("result", "recognized", "verdict"),
    [
        (
            {"status": "SUCCESS", "selected": "가다", "lemma": "가다", "headword": "가다"},
            ["가다"],
            "correct",
        ),
        (
            {"status": "SUCCESS", "selected": "기다", "lemma": "기다", "headword": "기다"},
            ["기다"],
            "misread",
        ),
        (
            {"status": "SUCCESS", "selected": "오다", "lemma": "오다", "headword": "오다"},
            ["가다 오다"],
            "wrong_word",
        ),
        (
            {"status": "SUCCESS", "selected": "가다", "lemma": "갈다", "headword": "갈다"},
            ["가다"],
            "wrong_lemma",
        ),
        ({"status": "EMPTY", "selected": None, "lemma": None, "headword": None}, [], "no_text"),
        (
            {"status": "UNUSABLE", "selected": None, "lemma": None, "headword": None},
            ["천천히 가다 오다"],
            "unresolved",
        ),
        (
            {"status": "NOT_FOUND", "selected": "가다", "lemma": None, "headword": None},
            ["가다"],
            "not_found",
        ),
    ],
)
def test_a_hover_is_judged_by_the_first_stage_that_went_wrong(
    result: dict[str, Any], recognized: list[str], verdict: str
) -> None:
    seen = _seen(**result)
    seen.recognized = recognized
    assert _judge(_placed(), seen, 0, timed_out=False)["verdict"] == verdict


def test_a_refuse_target_passes_only_without_an_answer() -> None:
    refuse = _placed(surface="Hanly", refuse=True, lemma=None, headword=None)
    assert _judge(refuse, _seen(status="UNUSABLE"), 0, timed_out=False)["verdict"] == "refused"
    answered = _seen(status="SUCCESS", selected="x", lemma="x", headword="x")
    assert _judge(refuse, answered, 0, timed_out=False)["verdict"] == "false_answer"


def test_silence_is_never_a_pass() -> None:
    nothing = _Observation()
    assert _judge(_placed(), nothing, 0, timed_out=True)["verdict"] == "no_hover"
    started = _seen()
    assert _judge(_placed(), started, 0, timed_out=True)["verdict"] == "no_result"


# -- corpus --------------------------------------------------------------------------------


def test_the_story_carries_every_minibook_target() -> None:
    targets = story_targets()
    assert len(targets) > 100
    assert all(t.line[t.start : t.start + len(t.surface)] == t.surface for t in targets)
    assert any(t.refuse for t in targets)


def test_words_are_sampled_deterministically_and_plain_hangul(tmp_path: Path) -> None:
    database = tmp_path / "krdict.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE entries (id INTEGER PRIMARY KEY, vocabulary_level TEXT,
                                  part_of_speech TEXT);
            CREATE TABLE lemmas (id INTEGER PRIMARY KEY, entry_id INTEGER, written_form TEXT,
                                 is_primary INTEGER);
            """
        )
        forms = ["가다", "오다", "먹다", "abc", "가", "책상", "학교", "친구", "사랑-하다"]
        for index, form in enumerate(forms, 1):
            connection.execute("INSERT INTO entries VALUES (?, '초급', '동사')", (index,))
            connection.execute("INSERT INTO lemmas VALUES (?, ?, ?, 1)", (index, index, form))

    first = word_targets(database, 4, seed=3)
    assert [t.surface for t in first] == [t.surface for t in word_targets(database, 4, seed=3)]
    assert len(first) == 4
    assert all(t.surface == t.headword and all("가" <= c <= "힣" for c in t.surface) for t in first)


# -- report --------------------------------------------------------------------------------


def _write_session(run: Path) -> None:
    def event(t: float, kind: str, /, **fields: Any) -> dict[str, Any]:
        return {"event": kind, "t_ms": t, **fields}

    ns = 1_000_000
    events = [
        event(0, "startup_phase", name="resources", duration_ms=200, outcome="ok"),
        event(10, "hover_mouse_opportunity", hover_request_id=1),
        event(20, "hover_invalidation", hover_request_id=1),
        event(20, "hover_mouse_opportunity", hover_request_id=2),
        event(100, "hover_stable_fire", hover_request_id=2),
        event(
            101,
            "hover_direct_text",
            hover_request_id=2,
            outcome="unsupported",
            duration_ns=1 * ns,
            used_direct_text=False,
        ),
        event(130, "hover_capture_completed", hover_request_id=2, duration_ns=28 * ns),
        event(130, "lookup_submit", hover_request_id=2, lookup_request_id=7),
        event(131, "lookup_cache_miss", hover_request_id=2, lookup_request_id=7),
        event(
            161,
            "lookup_stage_completed",
            lookup_request_id=7,
            hover_request_id=2,
            stage="ocr",
            duration_ns=30 * ns,
            region_count=1,
            hangul_region_count=1,
            ocr_backend="vision",
            gate_passed=True,
        ),
        event(
            162,
            "lookup_stage_completed",
            lookup_request_id=7,
            hover_request_id=2,
            stage="token_selection",
            duration_ns=ns // 10,
            resolved=True,
        ),
        event(
            164,
            "lookup_stage_completed",
            lookup_request_id=7,
            hover_request_id=2,
            stage="dictionary",
            duration_ns=2 * ns,
            found=True,
        ),
        event(
            164,
            "lookup_stage_completed",
            lookup_request_id=7,
            hover_request_id=2,
            stage="total_pipeline",
            duration_ns=33 * ns,
            outcome="SUCCESS",
            cached=False,
        ),
        event(167, "popup_visible", lookup_request_id=7, result_status="SUCCESS"),
        event(
            168,
            "tour_result",
            target="t1",
            verdict="correct",
            expected="가다",
            headword="가다",
            confidence=0.9,
            font_px=22,
            theme="light",
            font="F",
            source="words",
            hover_to_popup_ms=147.0,
            lookup_ids=[7],
            recognized=["</script>"],
        ),
    ]
    run.mkdir()
    (run / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
    (run / "processes.jsonl").write_text(
        json.dumps(
            {
                "t_ms": 50,
                "processes": [
                    {"pid": 1, "role": "shell", "rss": 100 * 2**20, "cpu": 5.0, "threads": 9},
                    {"pid": 2, "role": "lookup", "rss": 600 * 2**20, "cpu": 40.0, "threads": 12},
                    {"pid": 3, "role": "lookup.helper", "rss": 2**20, "cpu": 0.0, "threads": 1},
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run / "metadata.json").write_text(json.dumps({"mode": "tour"}), encoding="utf-8")


def test_a_hover_is_rebuilt_across_both_processes(tmp_path: Path) -> None:
    _write_session(tmp_path / "run")
    model = build_model(tmp_path / "run")

    (episode,) = model["episodes"]
    assert episode["outcome"] == "answered" and episode["total"] == pytest.approx(147)
    names = [name for name, _, _ in episode["segments"]]
    assert names == ["dwell", "direct_text", "capture", "to_engine", "ocr", "language", "to_popup"]
    assert model["moved_on"] == 1
    steps = {row["step"]: row["count"] for row in model["funnel"]}
    assert steps["Pointer settled (hover opportunity)"] == 2
    assert steps["Popup shown with an answer"] == 1
    assert model["processes"]["summary"]["lookup"]["rss_mib"] == 600
    assert "lookup helpers" in model["processes"]["summary"]
    assert model["tour"]["accuracy"] == 1.0
    assert any("OCR" in finding["title"] for finding in model["findings"])


def test_the_report_cannot_be_broken_out_of_by_recorded_text(tmp_path: Path) -> None:
    _write_session(tmp_path / "run")
    report = build_report(tmp_path / "run")

    html = report.read_text(encoding="utf-8")
    assert "/*__MODEL__*/" not in html
    assert html.count("</script>") == 1
    assert (tmp_path / "run" / "summary.md").read_text(encoding="utf-8").startswith("# Hanly Lab")
    assert (
        json.loads((tmp_path / "run" / "report.json").read_text(encoding="utf-8"))["run"] == "run"
    )


# -- command line ----------------------------------------------------------------------------


def test_the_lab_runs_the_app_when_given_no_verb() -> None:
    assert with_default_verb([]) == ["run"]
    assert with_default_verb(["--hud"]) == ["run", "--hud"]
    assert with_default_verb(["tour"]) == ["tour"]
    assert with_default_verb(["--help"]) == ["--help"]
    assert _parser().parse_args(with_default_verb([])).mode == "run"


def test_tour_options_parse() -> None:
    args = _parser().parse_args(
        ["tour", "--words", "500", "--story-sizes", "0", "--word-sizes", "14,18"]
    )
    assert (args.mode, args.words, args.story_sizes, args.word_sizes) == ("tour", 500, (), (14, 18))
