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
from lab.session.driver import _Observation, observe, outcome_record
from lab.session.recorder import LabDiagnosticLog, LabRecorder
from lab.session.scoring import classify, summarize


def _events(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# -- recorder ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field",
    ["ocr_evidence", "result_evidence", "dictionary_evidence", "future_evidence", "ocr_boxes"],
)
def test_no_content_field_ever_reaches_disk(tmp_path: Path, field: str) -> None:
    recorder = LabRecorder(tmp_path / "events.jsonl", retain_evidence=True, retain_geometry=True)
    seen: list[Any] = []
    recorder.subscribe(lambda name, ns, fields: seen.append(fields.get(field)))
    sentinel = "SENTINEL-보이면-안됨"

    recorder.emit({"event_kind": "lookup_stage_completed", "timestamp_ns": 1, field: sentinel})
    recorder.lab("tour_target", **{field: sentinel})
    recorder.close()

    assert sentinel not in (tmp_path / "events.jsonl").read_text(encoding="utf-8")
    # The in-memory listener (the tour driver) still receives it.
    assert seen == [sentinel, sentinel]


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


# -- binding and scoring a hover -----------------------------------------------------------


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


def _result(selected: str | None, headword: str | None, status: str = "SUCCESS") -> str:
    return json.dumps(
        {"status": status, "selected": selected, "lemma": headword, "headword": headword}
    )


def _hovered(*events: tuple[str, dict[str, Any]]) -> _Observation:
    observation = _Observation()
    for name, fields in events:
        observe(observation, name, 0, fields)
    return observation


def _answered(hover: int, lookup: int, selected: str, headword: str) -> list[Any]:
    return [
        ("hover_stable_fire", {"hover_request_id": hover}),
        ("hover_submission", {"hover_request_id": hover, "lookup_request_id": lookup}),
        (
            "lookup_stage_completed",
            {
                "hover_request_id": hover,
                "lookup_request_id": lookup,
                "stage": "total_pipeline",
                "outcome": "SUCCESS",
                "duration_ns": 1,
                "result_evidence": _result(selected, headword),
            },
        ),
        ("popup_visible", {"lookup_request_id": lookup, "result_status": "SUCCESS"}),
    ]


def test_a_stale_lookup_from_another_hover_cannot_answer_this_one() -> None:
    stale = (
        "lookup_stage_completed",
        {
            "hover_request_id": 3,
            "lookup_request_id": 9,
            "stage": "total_pipeline",
            "outcome": "SUCCESS",
            "duration_ns": 1,
            "result_evidence": _result("오다", "오다"),
        },
    )
    stale_popup = ("popup_visible", {"lookup_request_id": 9, "result_status": "SUCCESS"})
    seen = _hovered(stale, stale_popup, *_answered(4, 10, "가다", "가다"))

    record = outcome_record(_placed(), seen, 0, timed_out=False, keep_text=True)
    assert (record["lookup_ids"], record["headword"]) == ([10], "가다")
    assert record["ignored_foreign_events"] == 2
    assert classify(record) == "correct"


def test_only_a_stale_answer_leaves_this_hover_without_a_result() -> None:
    stale = ("popup_visible", {"lookup_request_id": 9, "result_status": "SUCCESS"})
    seen = _hovered(("hover_stable_fire", {"hover_request_id": 4}), stale)

    record = outcome_record(_placed(), seen, 0, timed_out=True, keep_text=True)
    assert seen.done.is_set() is False
    assert classify(record) == "no_hover"


def test_a_discarded_hover_keeps_no_recognized_text() -> None:
    seen = _hovered(*_answered(4, 10, "가다", "가다"))
    record = outcome_record(_placed(), seen, 0, timed_out=False, keep_text=False)
    assert not {"selected", "lemma", "headword", "recognized", "queries"} & set(record)
    record["unscored"] = "obscured_during_capture"
    assert classify(record) == "obscured_during_capture"


def _record(**fields: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "surface": "가다",
        "cursor": 1,
        "expected": "가다",
        "expected_lemma": "가다",
        "refuse": False,
        "lookup_ids": [1],
        "status": "SUCCESS",
        "selected": "가다",
        "lemma": "가다",
        "headword": "가다",
        "recognized": ["가다"],
    }
    base.update(fields)
    return base


@pytest.mark.parametrize(
    ("fields", "verdict"),
    [
        ({}, "correct"),
        (
            {"headword": "기다", "lemma": "기다", "selected": "기다", "recognized": ["기다"]},
            "misread",
        ),
        (
            {"headword": "오다", "lemma": "오다", "selected": "오다", "recognized": ["가다 오다"]},
            "wrong_word",
        ),
        (
            {"surface": "가다가", "selected": "가다가", "headword": "가", "lemma": "가"},
            "wrong_lemma",
        ),
        (
            {
                "surface": "드릴",
                "selected": "드릴",
                "headword": "드릴",
                "lemma": "드릴",
                "expected": "드리다",
                "expected_lemma": "드리다",
            },
            "ambiguous_surface",
        ),
        ({"status": "NOT_FOUND", "headword": None, "lemma": None}, "not_found"),
        ({"status": "EMPTY", "selected": None, "recognized": []}, "no_text"),
        ({"status": "UNUSABLE", "selected": None, "recognized": ["천천히 가다"]}, "unresolved"),
        ({"status": "ERROR"}, "error"),
        ({"error": "OSError"}, "error"),
        ({"status": None}, "no_result"),
        ({"status": None, "lookup_ids": []}, "no_hover"),
    ],
)
def test_a_hover_is_judged_by_the_first_stage_that_went_wrong(
    fields: dict[str, Any], verdict: str
) -> None:
    assert classify(_record(**fields)) == verdict


@pytest.mark.parametrize(
    ("fields", "verdict"),
    [
        ({"status": "UNUSABLE"}, "refused"),
        ({"status": "SUCCESS"}, "false_answer"),
        ({"status": None}, "no_result"),
        ({"status": None, "timed_out": True, "lookup_ids": []}, "no_hover"),
        ({"status": "ERROR"}, "error"),
        ({"error": "TransportClosed"}, "error"),
    ],
)
def test_only_a_deliberate_non_answer_counts_as_a_refusal(
    fields: dict[str, Any], verdict: str
) -> None:
    assert classify(_record(refuse=True, expected=None, expected_lemma=None, **fields)) == verdict


def test_unscored_hovers_stay_out_of_the_accuracy() -> None:
    summary = summarize(["correct", "refused", "wrong_lemma", "obscured", "unverifiable_region"])
    assert (summary["scored"], summary["unscored"], summary["passed"]) == (3, 2, 2)
    assert summary["accuracy"] == pytest.approx(2 / 3)


# -- corpus --------------------------------------------------------------------------------


def test_the_story_carries_every_minibook_target() -> None:
    targets = story_targets()
    assert len(targets) > 100
    assert all(t.line[t.start : t.start + len(t.surface)] == t.surface for t in targets)
    assert any(t.refuse for t in targets)


def _dictionary(path: Path, forms: list[str], *, untranslated: tuple[str, ...] = ()) -> Path:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE entries (id INTEGER PRIMARY KEY, vocabulary_level TEXT,
                                  part_of_speech TEXT);
            CREATE TABLE lemmas (id INTEGER PRIMARY KEY, entry_id INTEGER, written_form TEXT,
                                 is_primary INTEGER);
            CREATE TABLE senses (id INTEGER PRIMARY KEY, entry_id INTEGER);
            CREATE TABLE translations (id INTEGER PRIMARY KEY, sense_id INTEGER, language TEXT);
            """
        )
        for index, form in enumerate(forms, 1):
            connection.execute("INSERT INTO entries VALUES (?, '초급', '동사')", (index,))
            connection.execute("INSERT INTO lemmas VALUES (?, ?, ?, 1)", (index, index, form))
            connection.execute("INSERT INTO senses VALUES (?, ?)", (index, index))
            language = "ko" if form in untranslated else "en"
            connection.execute(
                "INSERT INTO translations VALUES (?, ?, ?)", (index, index, language)
            )
    return path


def test_words_are_sampled_deterministically_and_plain_hangul(tmp_path: Path) -> None:
    forms = ["가다", "오다", "먹다", "abc", "가", "책상", "학교", "친구", "사랑-하다"]
    database = _dictionary(tmp_path / "krdict.sqlite3", forms)

    first = word_targets(database, 4, seed=3)
    assert [t.surface for t in first] == [t.surface for t in word_targets(database, 4, seed=3)]
    assert len(first) == 4
    assert all(t.surface == t.headword and all("가" <= c <= "힣" for c in t.surface) for t in first)


def test_a_headword_with_no_english_translation_is_not_a_target(tmp_path: Path) -> None:
    forms = ["가다", "오다", "먹다", "애기", "책상", "학교", "친구"]
    full = word_targets(_dictionary(tmp_path / "a.sqlite3", forms), 7, seed=3)
    without = word_targets(
        _dictionary(tmp_path / "b.sqlite3", forms, untranslated=("애기",)), 7, seed=3
    )

    assert "애기" in [t.surface for t in full]
    assert [t.surface for t in without] == [t.surface for t in full if t.surface != "애기"]


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
            rule="strict-headword-v2",
            expected="가다",
            expected_lemma="가다",
            surface="가다",
            cursor=1,
            status="SUCCESS",
            selected="가다",
            lemma="가다",
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


def test_a_comparison_rescores_both_runs_and_leaves_the_baseline_untouched(
    tmp_path: Path,
) -> None:
    _write_session(tmp_path / "before")
    _write_session(tmp_path / "after")
    events = tmp_path / "after" / "events.jsonl"
    rows = [json.loads(line) for line in events.read_text(encoding="utf-8").splitlines()]
    rows[-1].update(
        headword="갈다",
        lemma="갈다",
        selected="가다",
        surface="가다",
        status="SUCCESS",
        verdict="wrong_lemma",
    )
    events.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    before_files = sorted(path.name for path in (tmp_path / "before").iterdir())

    build_report(tmp_path / "after", baseline=tmp_path / "before")

    comparison = json.loads((tmp_path / "after" / "report.json").read_text(encoding="utf-8"))[
        "comparison"
    ]
    assert comparison["matched"] == 1
    assert [(c["before"], c["after"]) for c in comparison["changed"]] == [
        ("correct", "wrong_lemma")
    ]
    assert sorted(path.name for path in (tmp_path / "before").iterdir()) == before_files


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


def test_the_default_tour_is_the_standard_comparable_one() -> None:
    args = _parser().parse_args(["tour"])
    assert (args.words, args.story_sizes, args.seed, args.quick) == (300, (22,), 7, False)
    assert _parser().parse_args(["tour", "--quick"]).quick is True


def test_only_lab_sessions_are_discovered_by_start_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lab.session import runner

    for name in ("20261001-090000-tour", "20260930-230000-run", "w17-frozen-1", "20261001-1-x"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "events.jsonl").write_text("", encoding="utf-8")
    monkeypatch.setattr(runner, "RUNS_ROOT", tmp_path)

    assert [path.name for path in runner.recorded_runs()] == [
        "20260930-230000-run",
        "20261001-090000-tour",
    ]
    assert runner.resolve_run("20261001-090000-tour") == tmp_path / "20261001-090000-tour"
    with pytest.raises(SystemExit, match="not a recorded run"):
        runner.resolve_run("nothing-here")


def test_tour_options_parse() -> None:
    args = _parser().parse_args(
        ["tour", "--words", "500", "--story-sizes", "0", "--word-sizes", "14,18"]
    )
    assert (args.mode, args.words, args.story_sizes, args.word_sizes) == ("tour", 500, (), (14, 18))
