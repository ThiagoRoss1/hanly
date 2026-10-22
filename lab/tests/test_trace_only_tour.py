"""Packaged smoke evidence must never become a linguistic accuracy result."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from hanly_app.config import AppConfig

from lab.cli import _parser
from lab.identity import reproduction, run_identity
from lab.report.build import build_report
from lab.session.corpus import TourTarget
from lab.session.driver import _Lookup, _Observation, smoke_record
from lab.session.page import Placed
from lab.session.raster_ui import Point, Rect
from lab.session.runner import SessionOptions, _desktop_environment, _driven_exit_code, run_session


def _placed(*, refuse: bool = False) -> Placed:
    return Placed(
        TourTarget("owned-1", "story", "학교", 0, "학교", 0, "학교", "학교", refuse),
        Rect(100, 100, 40, 30),
        Point(110, 110),
        "fixture-font",
        30,
        "light",
    )


def test_successful_smoke_does_not_copy_content_or_assert_semantic_accuracy() -> None:
    sentinel = "PRIVATE-SENTINEL"
    seen = _Observation(
        hover_ids={1},
        lookups={
            2: _Lookup(status="SUCCESS", result={"headword": sentinel}, recognized=[sentinel])
        },
        popup_status="SUCCESS",
    )

    record = smoke_record(_placed(), seen, timed_out=False, unscored=None)

    assert record["passed"] is True
    assert sentinel not in json.dumps(record)
    assert not {"accuracy", "facts", "headword", "surface", "recognized"} & record.keys()


@pytest.mark.parametrize("status", [None, "UNUSABLE", "NOT_FOUND", "ERROR"])
def test_missing_or_refused_positive_popup_fails(status: str | None) -> None:
    seen = _Observation(hover_ids={1}, lookups={2: _Lookup(status=status)}, popup_status=status)

    assert smoke_record(_placed(), seen, timed_out=False, unscored=None)["passed"] is False


@pytest.mark.parametrize("condition", ["timeout", "obscured", "late", "foreign", "unbound"])
def test_incomplete_or_unbound_success_cannot_pass(condition: str) -> None:
    seen = _Observation(
        hover_ids=set() if condition == "unbound" else {1},
        lookups={2: _Lookup(status="SUCCESS")},
        popup_status="SUCCESS",
        late_popups=int(condition == "late"),
        foreign_popups=int(condition == "foreign"),
    )

    record = smoke_record(
        _placed(),
        seen,
        timed_out=condition == "timeout",
        unscored="obscured" if condition == "obscured" else None,
    )

    assert record["passed"] is False


def test_direct_non_korean_refusal_needs_no_lookup() -> None:
    seen = _Observation(hover_ids={1}, popup_status="NOT_KOREAN")

    assert (
        smoke_record(_placed(refuse=True), seen, timed_out=False, unscored=None)["passed"] is True
    )


@pytest.mark.parametrize(
    "options",
    [
        SessionOptions(mode="run", trace_only=True),
        SessionOptions(mode="tour", trace_only=True, retain_fixture_text=True),
        SessionOptions(mode="tour", trace_only=True, baseline="registered"),
    ],
)
def test_trace_only_rejects_content_retention_and_scored_baselines(options: SessionOptions) -> None:
    with pytest.raises(SystemExit, match="without text retention or baseline"):
        run_session(options)


def test_inspection_cannot_keep_a_scored_tour_open() -> None:
    with pytest.raises(SystemExit, match="--inspect-last requires --trace-only"):
        run_session(SessionOptions(mode="tour", inspect_last=True))


def test_trace_only_uses_no_private_observer_even_for_debug(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("lab.session.runner.is_debug_executable", lambda *_: True)
    monkeypatch.setenv("HANLY_DESKTOP_SERVICE_MODULE", "unsafe")
    monkeypatch.setenv("HANLY_LAB_RETAIN_EVIDENCE", "1")
    monkeypatch.setenv("HANLY_LAB_RETAIN_GEOMETRY", "1")

    environment = _desktop_environment(
        tmp_path,
        SessionOptions(mode="tour", trace_only=True),
        tmp_path / "hanly-desktop",
    )

    assert (
        not {
            "HANLY_DESKTOP_SERVICE_MODULE",
            "HANLY_LAB_RETAIN_EVIDENCE",
            "HANLY_LAB_RETAIN_GEOMETRY",
        }
        & environment.keys()
    )


def test_smoke_failure_is_not_a_successful_app_exit() -> None:
    assert _driven_exit_code("tour", 0, {"tour_finished": 1, "tour_smoke_failed": 1}) == 2


def test_trace_only_cli_and_reports_have_no_semantic_tour_score(tmp_path: Path) -> None:
    args = _parser().parse_args(["tour", "--quick", "--trace-only", "--no-open"])
    assert args.trace_only is True
    events = [
        {"event": "tour_planned", "t_ms": 0, "targets": 1},
        {
            "event": "tour_smoke_result",
            "t_ms": 1,
            "target": "owned-1",
            "passed": True,
            "rule": "native-lifecycle-v1",
            "status": "SUCCESS",
        },
        {"event": "tour_finished", "t_ms": 2, "completed": 1},
        {"event": "session_ended", "t_ms": 3, "exit_code": 0},
    ]
    (tmp_path / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events))
    (tmp_path / "processes.jsonl").write_text("")
    (tmp_path / "metadata.json").write_text(
        json.dumps(
            {
                "mode": "tour",
                "options": {"trace_only": True},
                "settings": AppConfig().to_dict(),
            }
        )
    )

    build_report(tmp_path)
    report = json.loads((tmp_path / "report.json").read_text())

    assert report["tour"] is None
    assert report["smoke"]["semantic_accuracy"] is None
    assert report["smoke"]["passed"] == 1
    assert report["provenance"]["recorded_rules"] == ["native-lifecycle-v1"]
    assert "semantic accuracy is unmeasured" in (tmp_path / "summary.md").read_text()
    command = reproduction(run_identity(tmp_path), report["metadata"])
    assert "--trace-only" in command["command"]
    assert command["exact"] is False


def test_scored_packaged_tour_still_requires_private_debug_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("lab.session.runner._runtime_config", lambda *_: tmp_path / "runtime.json")
    monkeypatch.setattr("lab.session.runner._read_user_settings", lambda *_: AppConfig())
    monkeypatch.setattr("lab.session.runner._require_tour_prerequisites", lambda *_: None)
    monkeypatch.setattr("lab.session.runner.desktop_executable", lambda *_: tmp_path / "packaged")
    monkeypatch.setattr("lab.session.runner.is_debug_executable", lambda *_: False)

    with pytest.raises(SystemExit, match="driven tours require this checkout's debug"):
        run_session(SessionOptions(mode="tour", words=1))
