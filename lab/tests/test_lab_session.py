"""The lab session: what it records, what it refuses to record, and what it reports."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from lab.cli import _parser, with_default_verb
from lab.report.build import build_report
from lab.report.model import build_model, lifecycle, startup
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


def test_native_runtime_readiness_drives_timeline_and_startup_report() -> None:
    events = [
        {"event": "desktop_started", "t_ms": 10.0},
        {
            "event": "runtime_preparation_completed",
            "phase": "runtime",
            "t_ms": 47.0,
        },
        {"event": "lab_runtime_ready", "t_ms": 47.0},
        {
            "event": "lab_driver_input_preflight",
            "t_ms": 48.0,
            "preflight_available": True,
            "post_event_access": False,
            "listen_event_access": True,
            "accessibility_trusted": False,
        },
    ]

    marks = lifecycle(events)
    report = startup(events)

    assert [mark["label"] for mark in marks] == ["Desktop runtime ready"]
    assert report["milestones"] == [{"name": "desktop service ready", "at_ms": 37.0, "t": 47.0}]
    assert report["lab_driver_input_preflight"] == {
        "preflight_available": True,
        "post_event_access": False,
        "listen_event_access": True,
        "accessibility_trusted": False,
    }


def test_tour_hotkey_synthesis_marks_each_press_and_release_without_key_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lab.session.driver import TourDriver

    class Recorder:
        def __init__(self) -> None:
            self.events: list[tuple[str, dict[str, object]]] = []

        def lab(self, name: str, /, **fields: object) -> None:
            self.events.append((name, fields))

    class Keys:
        ctrl = object()
        shift = object()
        f10 = object()

    class Keyboard:
        def __init__(self) -> None:
            self.events: list[str] = []

        def press(self, _key: object) -> None:
            self.events.append("press")

        def release(self, _key: object) -> None:
            self.events.append("release")

    driver: Any = object.__new__(TourDriver)
    driver._capture_hotkey = "ctrl+shift+f10"
    driver._keys = Keys
    driver._keyboard = Keyboard()
    driver._recorder = Recorder()
    monkeypatch.setattr("lab.session.mac_function_keys.sys.platform", "linux")
    monkeypatch.setattr("lab.session.driver.time.sleep", lambda _duration: None)

    driver._press_capture_hotkey()

    names = [name for name, _fields in driver._recorder.events]
    assert names[0] == "tour_capture_input_started"
    assert names[-1] == "tour_capture_input_completed"
    assert names.count("tour_capture_key_dispatch_started") == 6
    assert names.count("tour_capture_key_dispatch_completed") == 6
    edges = [
        fields["edge"]
        for name, fields in driver._recorder.events
        if name.endswith("started") and name != "tour_capture_input_started"
    ]
    assert edges == [
        "press",
        "press",
        "press",
        "release",
        "release",
        "release",
    ]
    assert all("key" not in fields for _name, fields in driver._recorder.events)
    assert driver._keyboard.events == ["press"] * 3 + ["release"] * 3


@pytest.mark.parametrize("number", range(1, 21))
def test_macos_function_key_range_uses_public_pynput_virtual_codes(
    monkeypatch: pytest.MonkeyPatch, number: int
) -> None:
    from lab.session.mac_function_keys import dispatch_key_edge

    class KeyCode:
        vk = 100 + number

    class Key:
        value = KeyCode()

    class Quartz:
        kCGEventFlagMaskSecondaryFn = 1 << 8
        kCGHIDEventTap = 12
        kCGEventFlagMaskControl = 1 << 0
        kCGEventFlagMaskShift = 1 << 1
        kCGEventFlagMaskAlternate = 1 << 2
        kCGEventFlagMaskCommand = 1 << 3

        def __init__(self) -> None:
            self.events: list[tuple[object, ...]] = []

        def CGEventCreateKeyboardEvent(
            self, source: None, virtual_key: int, key_down: bool
        ) -> object:
            event = object()
            self.events.append(("create", source, virtual_key, key_down, event))
            return event

        def CGEventSetFlags(self, event: object, flags: int) -> None:
            self.events.append(("flags", event, flags))

        def CGEventPost(self, tap: int, event: object) -> None:
            self.events.append(("post", tap, event))

    quartz = Quartz()
    monkeypatch.setattr("lab.session.mac_function_keys.sys.platform", "darwin")

    dispatch_key_edge(
        object(),
        Key(),
        f"f{number}",
        pressed=True,
        modifier_names=("ctrl", "shift", "alt", "cmd"),
        quartz_loader=lambda: quartz,
    )

    create = quartz.events[0]
    flags = quartz.events[1]
    post = quartz.events[2]
    assert create[:4] == ("create", None, 100 + number, True)
    assert flags[0] == "flags"
    assert flags[1] is create[4]
    assert flags[2] == 1 << 8 | 1 << 0 | 1 << 1 | 1 << 2 | 1 << 3
    assert post == ("post", quartz.kCGHIDEventTap, create[4])


def test_macos_function_key_chord_posts_balanced_edges_and_keeps_trace_private(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lab.session.driver import TourDriver

    timeline: list[tuple[object, ...]] = []

    class Recorder:
        def __init__(self) -> None:
            self.events: list[tuple[str, dict[str, object]]] = []

        def lab(self, name: str, /, **fields: object) -> None:
            self.events.append((name, fields))

    class Keys:
        ctrl = object()
        shift = object()

        class F10:
            class Value:
                vk = 109

            value = Value()

        f10 = F10()

    class Keyboard:
        def press(self, key: object) -> None:
            timeline.append(("pynput", "press", _key_name(key)))

        def release(self, key: object) -> None:
            timeline.append(("pynput", "release", _key_name(key)))

    class Quartz:
        kCGEventFlagMaskSecondaryFn = 1 << 8
        kCGEventFlagMaskControl = 1 << 0
        kCGEventFlagMaskShift = 1 << 1
        kCGEventFlagMaskAlternate = 1 << 2
        kCGEventFlagMaskCommand = 1 << 3
        kCGHIDEventTap = 12

        def CGEventCreateKeyboardEvent(
            self, _source: None, virtual_key: int, key_down: bool
        ) -> tuple[int, bool]:
            event = (virtual_key, key_down)
            timeline.append(("create", *event))
            return event

        def CGEventSetFlags(self, event: object, flags: int) -> None:
            timeline.append(("flags", event, flags))

        def CGEventPost(self, tap: int, event: object) -> None:
            timeline.append(("post", tap, event))

    def _key_name(key: object) -> str:
        if key is Keys.ctrl:
            return "ctrl"
        if key is Keys.shift:
            return "shift"
        raise AssertionError("function key should use Quartz")

    driver: Any = object.__new__(TourDriver)
    driver._capture_hotkey = "ctrl+shift+f10"
    driver._keys = Keys
    driver._keyboard = Keyboard()
    driver._recorder = Recorder()
    monkeypatch.setattr("lab.session.mac_function_keys.sys.platform", "darwin")
    monkeypatch.setattr("lab.session.mac_function_keys._load_quartz", Quartz)
    monkeypatch.setattr("lab.session.driver.time.sleep", lambda _duration: None)

    driver._press_capture_hotkey()

    expected_flags = 1 << 8 | 1 << 0 | 1 << 1
    assert timeline == [
        ("pynput", "press", "ctrl"),
        ("pynput", "press", "shift"),
        ("create", 109, True),
        ("flags", (109, True), expected_flags),
        ("post", 12, (109, True)),
        ("create", 109, False),
        ("flags", (109, False), expected_flags),
        ("post", 12, (109, False)),
        ("pynput", "release", "shift"),
        ("pynput", "release", "ctrl"),
    ]
    assert all("key" not in fields for _name, fields in driver._recorder.events)


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


def test_accessibility_worker_trace_preserves_the_direct_text_funnel(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run.mkdir()
    rows = [
        {"event": "hover_mouse_opportunity", "t_ms": 0, "hover_request_id": 1},
        {"event": "hover_stable_fire", "t_ms": 10, "hover_request_id": 1},
        {
            "event": "hover_direct_text",
            "t_ms": 20,
            "hover_request_id": 1,
            "outcome": "direct",
            "used_direct_text": True,
            "duration_ns": 10_000_000,
        },
        {"event": "lookup_submit", "t_ms": 21, "hover_request_id": 1, "lookup_request_id": 7},
        {
            "event": "lookup_acquisition",
            "t_ms": 22,
            "hover_request_id": 1,
            "lookup_request_id": 7,
            "acquisition_source": "accessibility",
            "ocr_stage_skipped": True,
        },
        {"event": "popup_visible", "t_ms": 30, "lookup_request_id": 7, "result_status": "SUCCESS"},
    ]
    (run / "events.jsonl").write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    model = build_model(run)

    steps = {row["step"]: row["count"] for row in model["funnel"]}
    assert steps["Read without pixels (direct text)"] == 1
    assert steps["Screen region captured"] == 0
    assert steps["OCR ran"] == 0
    assert steps["Popup shown with an answer"] == 1


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


def test_the_lab_stops_the_native_child_with_its_platform_interrupt(tmp_path: Path) -> None:
    import signal

    from lab.session.desktop_process import DesktopProcess

    recorder = LabRecorder(tmp_path / "events.jsonl", retain_evidence=False, retain_geometry=False)
    process = SimpleNamespace(poll=lambda: None)
    sent: list[int] = []
    process.send_signal = sent.append
    desktop = DesktopProcess(
        tmp_path / "hanly-desktop",
        runtime_config=tmp_path / "runtime.json",
        app_config=tmp_path / "app.json",
        environment={},
        recorder=recorder,
        sampler=SimpleNamespace(unregister_process=lambda _pid: None),
        repo_root=tmp_path,
    )
    desktop.process = cast(Any, process)

    desktop.request_stop()
    desktop.request_stop()
    recorder.close()

    expected = (
        getattr(signal, "CTRL_BREAK_EVENT", signal.SIGINT)
        if sys.platform == "win32"
        else signal.SIGINT
    )
    assert sent == [expected]


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
    assert ensure_capture(stuck, lambda: None, launch_grace=0, after_press=0) == "never_started"


def test_capture_start_requires_a_native_hotkey_acknowledgement() -> None:
    import threading

    from lab.session.driver import ensure_capture

    observing = threading.Event()
    acknowledged = threading.Event()
    rejected = threading.Event()
    assert (
        ensure_capture(
            observing,
            lambda: None,
            launch_grace=0,
            after_press=1,
            delivery_ack=acknowledged,
            delivery_rejected=rejected,
            acknowledgement_timeout=0.01,
        )
        == "input_unconfirmed"
    )

    def reject() -> None:
        acknowledged.set()
        rejected.set()

    assert (
        ensure_capture(
            observing,
            reject,
            launch_grace=0,
            after_press=1,
            delivery_ack=acknowledged,
            delivery_rejected=rejected,
        )
        == "input_rejected"
    )


def test_native_input_ack_is_not_mistaken_for_capture_observation() -> None:
    import threading

    from lab.session.driver import ensure_capture

    observing = threading.Event()
    acknowledged = threading.Event()

    def delivered() -> None:
        acknowledged.set()

    assert (
        ensure_capture(
            observing,
            delivered,
            launch_grace=0,
            after_press=0.02,
            delivery_ack=acknowledged,
        )
        == "never_started"
    )


def test_tour_consumes_common_runtime_and_native_input_trace_events() -> None:
    import threading

    from lab.session.driver import TourDriver

    driver = TourDriver.__new__(TourDriver)
    driver._ready = threading.Event()
    driver._runtime_failed = False
    driver._native_context_seen = threading.Event()
    driver._registered_hotkey_count = None
    driver._capture_input_ack = threading.Event()
    driver._capture_input_rejected = threading.Event()
    driver._observing = threading.Event()
    driver._popup_hidden = threading.Event()
    driver._lock = threading.Lock()
    driver._active = None

    driver._observe("runtime_preparation_completed", 1, {"phase": "runtime"})
    driver._observe("native_context", 2, {"registered_hotkey_count": 3})
    driver._observe(
        "native_input",
        3,
        {"action": "toggle_capture", "edge": "pressed", "accepted": False},
    )

    assert driver._ready.is_set()
    assert driver._native_context_seen.is_set()
    assert driver._registered_hotkey_count == 3
    assert driver._capture_input_ack.is_set()
    assert driver._capture_input_rejected.is_set()

    driver._ready.clear()
    driver._observe("runtime_preparation_failed", 4, {"phase": "runtime"})
    assert driver._ready.is_set()
    assert driver._runtime_failed


def test_tour_rejects_unregistered_native_capture_hotkey(tmp_path: Path) -> None:
    import threading

    from lab.session.driver import TourDriver

    recorder = LabRecorder(tmp_path / "events.jsonl", retain_evidence=False, retain_geometry=False)
    driver = TourDriver.__new__(TourDriver)
    driver._recorder = recorder
    driver._native_context_seen = threading.Event()
    driver._native_context_seen.set()
    driver._registered_hotkey_count = 0

    assert not driver._ensure_capture()
    recorder.close()

    events = _events(tmp_path / "events.jsonl")
    assert [(event["event"], event["reason"]) for event in events] == [
        ("tour_aborted", "capture_hotkey_unregistered")
    ]


def test_tour_reports_lab_driver_event_post_access_and_fails_fast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import threading

    from lab.session import driver as tour_driver

    class Recorder:
        def __init__(self) -> None:
            self.events: list[tuple[str, dict[str, object]]] = []

        def lab(self, name: str, /, **fields: object) -> None:
            self.events.append((name, fields))

    recorder = Recorder()
    instance: Any = tour_driver.TourDriver.__new__(tour_driver.TourDriver)
    instance._recorder = recorder
    instance._native_context_seen = threading.Event()
    instance._native_context_seen.set()
    instance._registered_hotkey_count = 3
    monkeypatch.setattr(
        tour_driver,
        "_macos_input_preflight",
        lambda: {
            "preflight_available": True,
            "post_event_access": False,
            "listen_event_access": False,
            "accessibility_trusted": False,
        },
    )

    assert not instance._ensure_capture()
    assert [event for event, _fields in recorder.events] == [
        "lab_driver_input_preflight",
        "tour_aborted",
    ]
    assert recorder.events[-1][1]["reason"] == "lab_driver_post_event_access_unavailable"


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS permissions are platform-specific")
def test_macos_driver_preflight_reads_permissions_without_prompting() -> None:
    from lab.session.driver import _macos_input_preflight

    result = _macos_input_preflight()

    assert result is not None
    assert set(result) == {
        "preflight_available",
        "post_event_access",
        "listen_event_access",
        "accessibility_trusted",
    }
    assert result["preflight_available"] is True
    assert all(
        isinstance(result[name], bool)
        for name in ("post_event_access", "listen_event_access", "accessibility_trusted")
    )


@pytest.mark.parametrize(
    ("exit_code", "counts", "expected"),
    [
        (0, {"tour_aborted": 1}, 2),
        (0, {}, 2),
        (0, {"tour_stopped_by_user": 1}, 0),
        (0, {"tour_finished": 1}, 0),
        (1, {"tour_finished": 1}, 1),
    ],
)
def test_failed_driven_session_cannot_exit_as_a_pass(
    exit_code: int, counts: dict[str, int], expected: int
) -> None:
    from lab.session.runner import _driven_exit_code

    assert _driven_exit_code("tour", exit_code, counts) == expected


def test_empty_tour_is_rejected_before_creating_a_session() -> None:
    from lab.session.runner import SessionOptions, run_session

    with pytest.raises(SystemExit, match="at least one story target or dictionary word"):
        run_session(SessionOptions(mode="tour", words=0, story_sizes=()))


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
    driver._trace_only = False
    driver._scale = 1.0
    driver._expected = None
    driver.completed = 0
    setattr(driver, "_page", SimpleNamespace(to_global=lambda point: (point.x, point.y)))
    setattr(driver, "_foreign_windows", lambda x, y: [])
    mouse = SimpleNamespace(position=(0, 0))
    setattr(driver, "_mouse", mouse)

    def glide(x: int, y: int) -> None:
        driver._expected = (x, y)
        mouse.position = (x, y)
        fields = {"hover_request_id": 9}
        driver._observe("hover_stable_fire", 1, fields)
        driver._observe("popup_visible", 2, {"lookup_request_id": 4, "result_status": "SUCCESS"})

    setattr(driver, "_glide", glide)
    target = TourTarget("w1", "words", "학교", 0, "학교", 1, "학교", "학교")
    placed: Any = SimpleNamespace(
        target=target, point=SimpleNamespace(x=5, y=5), font_family="F", font_px=22, theme="light"
    )

    assert driver._hover(placed, 0, False)
    recorder.close()

    lines = (tmp_path / "events.jsonl").read_text("utf-8").splitlines()
    rows = [json.loads(line) for line in lines]
    result = next(row for row in rows if row.get("event") == "tour_result")
    assert result["hover_ids"] == [9]


def test_a_helper_belongs_to_its_nearest_sampled_ancestor(monkeypatch: Any) -> None:
    import psutil

    from lab.session.sampler import nearest_owner

    parent_map = {
        2: SimpleNamespace(ppid=lambda: 1),
        3: SimpleNamespace(ppid=lambda: 2),
        4: SimpleNamespace(ppid=lambda: 9),
        9: SimpleNamespace(ppid=lambda: 0),
    }
    monkeypatch.setattr(psutil, "Process", lambda pid: parent_map[pid])
    webengine = SimpleNamespace(ppid=lambda: 2)
    stray = SimpleNamespace(ppid=lambda: 9)
    owned = {1: "shell", 2: "control_center"}

    assert nearest_owner(webengine, owned) == 2
    assert nearest_owner(stray, owned) is None


def test_tour_options_parse() -> None:
    args = _parser().parse_args(
        ["tour", "--words", "500", "--story-sizes", "0", "--word-sizes", "14,18"]
    )
    assert (args.mode, args.words, args.story_sizes, args.word_sizes) == ("tour", 500, (), (14, 18))


def test_the_sampler_measures_the_shell_from_outside_it(tmp_path: Path) -> None:
    """Sampling runs in its own process, so it cannot hold the shell's interpreter lock."""

    import os
    import time

    from lab.session.sampler import ProcessSampler

    path = tmp_path / "processes.jsonl"
    sampler = ProcessSampler(path, time.perf_counter_ns(), interval=0.05)
    sampler.start()
    deadline = time.monotonic() + 30
    while (
        time.monotonic() < deadline
        and len(path.read_text("utf-8").splitlines() if path.exists() else []) < 3
    ):
        time.sleep(0.05)
    sampler.stop()

    rows = [json.loads(line) for line in path.read_text("utf-8").splitlines()]
    assert sampler.samples == len(rows) >= 3
    shell = rows[-1]["processes"][0]
    assert (shell["pid"], shell["role"]) == (os.getpid(), "shell") and shell["rss"] > 0
    # Neither the sampler nor a launcher in front of it is measured as the shell's helper.
    assert all(row["role"] == "shell" for sample in rows for row in sample["processes"])
    assert sorted(item.name for item in tmp_path.iterdir()) == ["processes.jsonl"]


@pytest.mark.skipif(sys.platform == "win32", reason="a terminal's Ctrl+C reaches a POSIX group")
def test_the_sampler_outlives_a_terminal_interrupt(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    """Ctrl+C reaches the whole foreground group; ending the run stays the shell's job."""

    import os
    import signal
    import time

    from lab.session.sampler import ProcessSampler

    path = tmp_path / "processes.jsonl"
    sampler = ProcessSampler(path, time.perf_counter_ns(), interval=0.05)
    sampler.start()
    deadline = time.monotonic() + 30
    while (
        time.monotonic() < deadline
        and len(path.read_text("utf-8").splitlines() if path.exists() else []) < 3
    ):
        time.sleep(0.05)
    assert sampler._process is not None
    os.kill(sampler._process.pid, signal.SIGINT)
    time.sleep(0.5)
    sampler.stop()

    rows = path.read_text("utf-8").splitlines()
    assert sampler.samples == len(rows) >= 3
    assert "KeyboardInterrupt" not in capfd.readouterr().err
