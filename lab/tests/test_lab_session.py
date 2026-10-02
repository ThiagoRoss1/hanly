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

    record = outcome_record(_placed(), seen, 0, timed_out=False, verified=True, retain_text=True)
    assert (record["lookup_ids"], record["headword"]) == ([10], "가다")
    assert record["ignored_foreign_events"] == 2
    assert classify(record) == "correct"


def test_only_a_stale_answer_leaves_this_hover_without_a_result() -> None:
    stale = ("popup_visible", {"lookup_request_id": 9, "result_status": "SUCCESS"})
    seen = _hovered(("hover_stable_fire", {"hover_request_id": 4}), stale)

    record = outcome_record(_placed(), seen, 0, timed_out=True, verified=True)
    assert seen.done.is_set() is False
    assert classify(record) == "no_hover"


_READ = {"selected", "lemma", "headword", "recognized", "queries"}
_SENTINEL = "센티널읽음"


def _answered_with(text: str) -> _Observation:
    events = _answered(4, 10, text, text)
    ocr = (
        "lookup_stage_completed",
        {
            "hover_request_id": 4,
            "lookup_request_id": 10,
            "stage": "ocr",
            "duration_ns": 1,
            "ocr_evidence": json.dumps({"regions": [{"text": text}]}),
        },
    )
    return _hovered(events[0], events[1], ocr, *events[2:])


def test_a_verified_hover_keeps_facts_but_no_text_by_default() -> None:
    record = outcome_record(
        _placed(surface=_SENTINEL, line=_SENTINEL, headword=_SENTINEL, lemma=_SENTINEL),
        _answered_with(_SENTINEL),
        0,
        timed_out=False,
        verified=True,
    )
    assert not _READ & set(record)
    assert record["facts"]["answer_matches_expected"] is True
    assert (record["recognized_regions"], record["queries_tried"]) == (1, 0)
    assert classify(record) == "correct"


def test_fixture_text_is_kept_only_on_request() -> None:
    record = outcome_record(
        _placed(), _answered_with("가다"), 0, timed_out=False, verified=True, retain_text=True
    )
    assert record["recognized"] == ["가다"] and record["headword"] == "가다"


def test_an_unverified_hover_keeps_neither_text_nor_facts() -> None:
    seen = _answered_with(_SENTINEL)
    record = outcome_record(_placed(), seen, 0, timed_out=False, verified=False, retain_text=True)
    assert not _READ & set(record) and "facts" not in record
    assert _SENTINEL not in json.dumps(record, ensure_ascii=False)
    record["unscored"] = "obscured_during_capture"
    assert classify(record) == "obscured_during_capture"


def test_a_late_result_from_another_hover_leaves_no_trace() -> None:
    late = (
        "lookup_stage_completed",
        {
            "hover_request_id": 3,
            "lookup_request_id": 9,
            "stage": "total_pipeline",
            "outcome": "SUCCESS",
            "duration_ns": 1,
            "result_evidence": _result(_SENTINEL, _SENTINEL),
        },
    )
    seen = _hovered(late, *_answered(4, 10, "가다", "가다"))
    record = outcome_record(_placed(), seen, 0, timed_out=False, verified=True, retain_text=True)
    assert _SENTINEL not in json.dumps(record, ensure_ascii=False)


def test_an_error_line_reaches_the_timeline_without_its_message(tmp_path: Path) -> None:
    recorder = LabRecorder(tmp_path / "events.jsonl", retain_evidence=False, retain_geometry=False)
    log = LabDiagnosticLog(recorder, tmp_path / "logs" / "hanly.log")
    log.record("Lookup", f"failed on {_SENTINEL}", level="error")
    log.record("Lookup engine", "ready")
    recorder.close()

    text = (tmp_path / "events.jsonl").read_text(encoding="utf-8")
    assert _SENTINEL not in text and '"message_withheld":true' in text
    assert '"message":"ready"' in text


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


@pytest.mark.parametrize(
    ("fields", "verdict"),
    [
        ({"timed_out": True}, "timed_out"),
        ({"timed_out": False}, "correct"),
        ({"refuse": True, "expected": None, "status": "UNUSABLE", "timed_out": True}, "timed_out"),
        ({"refuse": True, "expected": None, "status": "UNUSABLE", "timed_out": False}, "refused"),
        ({"status": None, "timed_out": True}, "timed_out"),
        ({"error": "OSError", "timed_out": True}, "error"),
    ],
)
def test_a_hover_the_app_never_finished_cannot_pass(fields: dict[str, Any], verdict: str) -> None:
    """A result without the app's own presentation decision is partial, not an answer."""

    assert classify(_record(**fields)) == verdict


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


def _with_older_recording(run: Path, sentinel: str) -> None:
    """Make the session look like a tour recorded before text stopped being stored."""

    events = run / "events.jsonl"
    rows = [json.loads(line) for line in events.read_text(encoding="utf-8").splitlines()]
    rows[-1].update(
        selected=sentinel,
        headword=sentinel,
        lemma=sentinel,
        recognized=[sentinel],
        queries=[[sentinel, True]],
    )
    rows.insert(
        5,
        {
            "event": "lookup_stage_completed",
            "t_ms": 150,
            "hover_request_id": 2,
            "lookup_request_id": 7,
            "stage": "ocr",
            "duration_ns": 1,
            "ocr_evidence": sentinel,
            "ocr_boxes": sentinel,
        },
    )
    rows.append(
        {
            "event": "diagnostic",
            "t_ms": 170,
            "subsystem": "Lookup",
            "level": "error",
            "message": f"failed on {sentinel}",
        }
    )
    events.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")


@pytest.mark.parametrize("retained", [False, True])
def test_reports_show_read_text_only_for_a_run_that_retained_it(
    tmp_path: Path, retained: bool
) -> None:
    sentinel = "센티널리포트"
    run = tmp_path / "run"
    _write_session(run)
    _with_older_recording(run, sentinel)
    (run / "metadata.json").write_text(
        json.dumps({"mode": "tour", "fixture_text_retained": retained}), encoding="utf-8"
    )

    build_report(run)

    outputs = {
        name: (run / name).read_text(encoding="utf-8")
        for name in ("report.json", "report.html", "summary.md")
    }
    for name, text in outputs.items():
        # Evidence, geometry and error text never appear; read text only on request.
        assert "ocr_boxes" not in text and f"failed on {sentinel}" not in text, name
    assert (sentinel in outputs["report.json"]) is retained
    assert (sentinel in outputs["summary.md"]) is retained
    tour = json.loads(outputs["report.json"])["tour"]
    # Scored from the recorded text in memory either way: the selection is not the word.
    assert tour["verdicts"] == {"misread": 1}


@pytest.mark.parametrize(
    ("last_event", "ended"),
    [
        ("tour_finished", "finished"),
        ("tour_stopped_by_user", "stopped_by_user"),
        (None, "interrupted"),
    ],
)
def test_a_tour_says_whether_it_finished(
    tmp_path: Path, last_event: str | None, ended: str
) -> None:
    run = tmp_path / "run"
    _write_session(run)
    events = run / "events.jsonl"
    rows = [json.loads(line) for line in events.read_text(encoding="utf-8").splitlines()]
    rows.insert(0, {"event": "tour_planned", "t_ms": 0, "targets": 24})
    if last_event:
        rows.append({"event": last_event, "t_ms": 200})
    events.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    model = build_model(run)

    assert model["tour"]["completion"] == {"ended": ended, "planned": 24, "hovered": 1}
    warned = any("did not finish" in finding["title"] for finding in model["findings"])
    assert warned is (ended != "finished")


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


def test_the_lab_quits_through_the_shells_interrupt_handler() -> None:
    # A child process, because the old route killed the caller outright on Windows.
    import subprocess
    import sys

    script = (
        "import signal\n"
        "from lab.session import runner\n"
        "signal.signal(signal.SIGINT, lambda *_: print('handled', flush=True))\n"
        "runner._request_quit()\n"
        "print('alive', flush=True)\n"
    )
    child = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert (child.returncode, child.stdout.split()) == (0, ["handled", "alive"])


def test_a_tour_never_toggles_off_capture_the_app_already_started() -> None:
    import threading

    from lab.session.driver import ensure_capture

    presses: list[str] = []
    watching = threading.Event()
    watching.set()
    assert ensure_capture(watching, lambda: presses.append("key"), launch_grace=0) == (
        "already_watching"
    )
    assert presses == []

    idle = threading.Event()

    def press() -> None:
        presses.append("key")
        idle.set()

    assert ensure_capture(idle, press, launch_grace=0) == "shortcut"
    assert presses == ["key"]

    stuck = threading.Event()
    assert (
        ensure_capture(stuck, lambda: None, launch_grace=0, after_press=0) == "never_started"
    )


def test_a_hover_that_fires_as_the_pointer_lands_is_this_targets(tmp_path: Path) -> None:
    """With a 20 ms hover delay the app's hover can fire before the glide returns."""

    import threading

    from lab.session.driver import TourDriver

    recorder = LabRecorder(tmp_path / "events.jsonl", retain_evidence=True, retain_geometry=True)
    driver = TourDriver.__new__(TourDriver)
    driver._recorder = recorder
    driver._lock = threading.Lock()
    driver._active = None
    driver._settle_timeout = 0.2
    driver._first_timeout = 0.2
    driver._retain_fixture_text = False
    driver._scale = 1.0
    driver._expected = None
    driver.completed = 0
    setattr(driver, "_page", SimpleNamespace(to_global=lambda point: (point.x, point.y)))
    driver._foreign_windows = lambda x, y: []  # type: ignore[method-assign]
    mouse = SimpleNamespace(position=(0, 0))
    setattr(driver, "_mouse", mouse)

    def glide(x: int, y: int) -> None:
        driver._expected = (x, y)
        mouse.position = (x, y)
        fields = {"hover_request_id": 9}
        driver._observe("hover_stable_fire", 1, fields)
        driver._observe("popup_visible", 2, {"lookup_request_id": 4, "result_status": "SUCCESS"})

    driver._glide = glide  # type: ignore[method-assign]
    target = TourTarget("w1", "words", "학교", 0, "학교", 1, "학교", "학교")
    placed = SimpleNamespace(
        target=target, point=SimpleNamespace(x=5, y=5), font_family="F", font_px=22, theme="light"
    )

    assert driver._hover(placed, 0, False)  # type: ignore[arg-type]
    recorder.close()

    lines = (tmp_path / "events.jsonl").read_text("utf-8").splitlines()
    rows = [json.loads(line) for line in lines]
    result = next(row for row in rows if row.get("event") == "tour_result")
    assert result["hover_ids"] == [9]


def test_a_helper_belongs_to_its_nearest_sampled_ancestor() -> None:
    from lab.session.sampler import nearest_owner

    shell, window = SimpleNamespace(pid=1), SimpleNamespace(pid=2)
    webengine = SimpleNamespace(pid=3, parents=lambda: [window, shell])
    stray = SimpleNamespace(pid=4, parents=lambda: [SimpleNamespace(pid=9)])
    owned = {1: "shell", 2: "control_center"}

    assert nearest_owner(webengine, owned) == 2
    assert nearest_owner(stray, owned) is None


def test_tour_options_parse() -> None:
    args = _parser().parse_args(
        ["tour", "--words", "500", "--story-sizes", "0", "--word-sizes", "14,18"]
    )
    assert (args.mode, args.words, args.story_sizes, args.word_sizes) == ("tour", 500, (), (14, 18))
