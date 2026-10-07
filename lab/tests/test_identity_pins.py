"""Run identity across every recorded layout, and the local baseline registry."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from lab import metadata as metadata_module
from lab import pins
from lab.identity import resolve_name, run_identity
from lab.metadata import build_metadata, provenance, source_identity

CLEAN = {"commit": "a" * 40, "dirty": False, "state": "clean"}
DIRTY = {"commit": "a" * 40, "dirty": True, "state": "dirty"}


def _json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _session(
    run: Path,
    *,
    mode: str = "tour",
    source: dict[str, Any] | None = CLEAN,
    backends: tuple[str, ...] = ("vision",),
    configured: str = "vision",
    ended: str | None = "tour_finished",
    options: dict[str, Any] | None = None,
) -> Path:
    metadata: dict[str, Any] = {
        "schema_version": 1,
        "mode": mode,
        "started": "2026-10-07T10:00:00",
        "platform": "Darwin 25.6.0 arm64",
        "commit": "b" * 40,
        "dirty": False,
        "settings": {"ocr_backend": configured},
        "options": options or {"words": 300, "story_sizes": [22], "seed": 7},
    }
    if source is not None:
        metadata["lab_provenance"] = provenance(
            mode, source, measurement_protocol="p1", configured_backend=configured
        )
    _json(run / "metadata.json", metadata)
    events: list[dict[str, Any]] = [
        {"event": "tour_planned", "t_ms": 0, "targets": 1, "plan_fingerprint": "sha256:abc"}
    ]
    events += [
        {"event": "lookup_stage_completed", "stage": "ocr", "ocr_backend": backend}
        for backend in backends
    ]
    events.append({"event": "tour_result", "target": "t1", "rule": "strict-headword-v3"})
    if ended:
        events.append({"event": ended, "t_ms": 9})
    (run / "events.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8"
    )
    return run


def _registry(tmp_path: Path) -> pins.Registry:
    return pins.load(tmp_path / "pins.json", tmp_path / "runs")


# -- identity -----------------------------------------------------------------------------


def test_a_session_is_recognized_from_its_contents_with_start_time_provenance(
    tmp_path: Path,
) -> None:
    identity = run_identity(_session(tmp_path / "anything-at-all"))

    assert (identity.kind, identity.mode, identity.completion) == ("tour", "tour", "finished")
    # The start-time block wins over the legacy top-level fields.
    assert (identity.commit, identity.source_state) == ("a" * 40, "clean")
    assert (identity.system, identity.machine, identity.backend) == ("Darwin", "arm64", "vision")
    assert identity.fingerprint == "sha256:abc"
    assert identity.rules == ("strict-headword-v3",)
    assert identity.provenance_version == 1
    assert identity.conflicts == ()


def test_a_legacy_session_says_its_source_was_read_at_shutdown(tmp_path: Path) -> None:
    identity = run_identity(_session(tmp_path / "old", source=None))

    assert identity.commit == "b" * 40 and identity.source_state == "clean"
    assert identity.measurement_protocol == "unknown"
    assert identity.provenance_version is None
    assert any("shutdown" in note for note in identity.notes)


def test_conflicting_backend_observations_are_reported_not_resolved(tmp_path: Path) -> None:
    identity = run_identity(
        _session(tmp_path / "run", backends=("vision", "easyocr"), configured="vision")
    )

    assert identity.backend == "unknown"
    assert len(identity.conflicts) == 2


def test_an_auto_backend_is_known_only_from_what_was_observed(tmp_path: Path) -> None:
    observed = run_identity(_session(tmp_path / "a", backends=("easyocr",), configured="auto"))
    unseen = run_identity(_session(tmp_path / "b", backends=(), configured="auto"))

    assert observed.backend == "easyocr"
    assert unseen.backend == "unknown"


@pytest.mark.parametrize(
    ("ended", "completion"),
    [
        ("tour_stopped_by_user", "stopped_by_user"),
        ("tour_aborted", "aborted"),
        (None, "interrupted"),
    ],
)
def test_an_unfinished_tour_says_how_it_ended(
    tmp_path: Path, ended: str | None, completion: str
) -> None:
    assert run_identity(_session(tmp_path / "run", ended=ended)).completion == completion


def test_a_check_set_an_ocr_campaign_and_a_measurement_are_told_apart(tmp_path: Path) -> None:
    check = tmp_path / "c"
    _json(
        check / "metadata.json",
        build_metadata(scenario={"app_lab": ["B", "A"]}, kind="check", source=CLEAN),
    )
    _json(check / "summary.json", {"results": []})
    ocr = tmp_path / "o"
    _json(
        ocr / "metadata.json",
        build_metadata(
            config={"mode": "ocr-only", "backend": "vision", "samples": 3},
            scenario={"name": "ocr_ocr_only"},
            source=CLEAN,
        ),
    )
    _json(ocr / "corpus-inventory.json", {"case_count": 1})
    (ocr / "samples.jsonl").write_text(json.dumps({"backend": "vision"}) + "\n", encoding="utf-8")
    measure = tmp_path / "m"
    _json(
        measure / "metadata.json",
        build_metadata(scenario={"name": "real_lookup_roi_9x9"}, source=CLEAN),
    )

    identities = {path.name: run_identity(path) for path in (check, ocr, measure)}

    assert identities["c"].kind == "check" and identities["c"].mode == "A,B"
    assert identities["c"].completion == "finished"
    assert identities["o"].kind == "ocr_campaign" and identities["o"].backend == "vision"
    assert identities["o"].options == {"mode": "ocr-only", "samples": 3}
    assert identities["m"].kind == "real_lookup" and identities["m"].completion == "interrupted"
    # Measurement campaigns written without a kind still carry no provenance block.
    assert identities["m"].provenance_version is None


def test_an_update_check_is_recognized_from_its_summary(tmp_path: Path) -> None:
    run = tmp_path / "u"
    _json(
        run / "summary.json",
        {
            "mode": "rollback",
            "source_tag": "v0.9.0",
            "remnants": [],
            "events": [],
            "passed": True,
            "lab_provenance": provenance("update_check", CLEAN, started="2026-10-07T10:00:00"),
        },
    )

    identity = run_identity(run)

    assert (identity.kind, identity.mode, identity.completion) == (
        "update_check",
        "rollback",
        "finished",
    )
    assert identity.started == "2026-10-07T10:00:00"


@pytest.mark.parametrize("content", [None, "{not json", json.dumps({"something": "else"})])
def test_manual_corrupt_or_missing_material_stays_unknown(
    tmp_path: Path, content: str | None
) -> None:
    run = tmp_path / "manual"
    (run / "install-1").mkdir(parents=True)
    _json(run / "install-1" / "summary.json", {"mode": "install"})
    if content is not None:
        (run / "metadata.json").write_text(content, encoding="utf-8")

    identity = run_identity(run)

    assert identity.kind == "unknown" and identity.commit == "unknown"
    if content == "{not json":
        assert identity.notes == ("metadata.json unreadable (JSONDecodeError)",)


def test_a_failing_git_is_an_unknown_source_never_a_clean_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def broken(*_args: Any, **_kwargs: Any) -> Any:
        raise subprocess.CalledProcessError(128, "git")

    monkeypatch.setattr(metadata_module.subprocess, "run", broken)

    assert source_identity(tmp_path) == {"commit": "unknown", "dirty": None, "state": "unknown"}


def test_a_checkout_changed_during_the_run_is_recorded_beside_the_start(tmp_path: Path) -> None:
    moved = {"commit": "c" * 40, "dirty": False, "state": "clean"}
    block = provenance("tour", CLEAN, source_at_end=moved)

    assert block["source"] == CLEAN and block["source_at_end"] == moved
    assert block["source_changed"] is True
    assert provenance("tour", CLEAN, source_at_end=CLEAN)["source_changed"] is False
    # Two dirty readings at one commit cannot be told apart without a diff hash.
    assert provenance("tour", DIRTY, source_at_end=DIRTY)["source_changed"] is None


# -- names --------------------------------------------------------------------------------


def test_names_cannot_leave_the_runs_root(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    (root / "real").mkdir(parents=True)
    (tmp_path / "outside").mkdir()
    (root / "link").symlink_to(tmp_path / "outside")

    assert resolve_name("real", root) == (root / "real").resolve()
    for name in ("../outside", str(tmp_path / "outside"), "link", ".."):
        with pytest.raises(ValueError):
            resolve_name(name, root)


# -- registry -----------------------------------------------------------------------------


def test_a_baseline_is_registered_once_per_key_and_replaced_only_on_request(
    tmp_path: Path,
) -> None:
    first = _session(tmp_path / "runs" / "first")
    _session(tmp_path / "runs" / "second")

    registry, identity, replaced = pins.set_baseline(_registry(tmp_path), "first", "standard")
    assert replaced is None and identity.path == first
    with pytest.raises(pins.PinError, match="--replace"):
        pins.set_baseline(registry, "second", "newer")

    registry, _, replaced = pins.set_baseline(registry, "second", "newer", replace=True)

    assert replaced is not None and replaced.run == "first"
    assert [(pin.run, pin.role) for pin in _registry(tmp_path).pins] == [("second", "baseline")]
    assert first.is_dir()


def test_runs_with_different_options_hold_separate_baselines(tmp_path: Path) -> None:
    _session(tmp_path / "runs" / "standard")
    _session(tmp_path / "runs" / "quick", options={"words": 24, "story_sizes": [], "seed": 7})

    registry, _, _ = pins.set_baseline(_registry(tmp_path), "standard", "300 words")
    registry, _, replaced = pins.set_baseline(registry, "quick", "24 words")

    assert replaced is None and len(registry.baselines()) == 2


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"source": DIRTY}, "--allow-dirty"),
        ({"ended": None}, "did not finish"),
        ({"backends": (), "configured": "auto"}, "backend"),
        ({"source": {"commit": "unknown", "dirty": None, "state": "unknown"}}, "unknown"),
    ],
)
def test_an_untrustworthy_run_is_never_a_baseline(
    tmp_path: Path, kwargs: dict[str, Any], message: str
) -> None:
    _session(tmp_path / "runs" / "run", **kwargs)

    with pytest.raises(pins.PinError, match=message):
        pins.set_baseline(_registry(tmp_path), "run", "why")
    assert not (tmp_path / "pins.json").exists()


def test_a_dirty_run_is_a_baseline_only_when_allowed(tmp_path: Path) -> None:
    _session(tmp_path / "runs" / "run", source=DIRTY)

    registry, _, _ = pins.set_baseline(_registry(tmp_path), "run", "why", allow_dirty=True)

    assert registry.roles("run") == {"baseline"}


def test_an_incomplete_or_unknown_run_can_still_be_kept(tmp_path: Path) -> None:
    _session(tmp_path / "runs" / "partial", ended=None)
    (tmp_path / "runs" / "manual").mkdir()

    registry = pins.keep(_registry(tmp_path), "partial", "only evidence of the crash")
    registry = pins.keep(registry, "manual", "Mac update investigation")

    assert registry.protected() == {"partial", "manual"}


def test_unset_removes_only_that_runs_baseline_and_never_files(tmp_path: Path) -> None:
    run = _session(tmp_path / "runs" / "run")
    _session(tmp_path / "runs" / "other", options={"words": 1, "seed": 1})
    registry, _, _ = pins.set_baseline(_registry(tmp_path), "run", "baseline")
    registry, _, _ = pins.set_baseline(registry, "other", "baseline")
    registry = pins.keep(registry, "run", "keep it too")

    registry = pins.remove(registry, "run", "baseline")

    assert registry.roles("run") == {"keep"} and registry.roles("other") == {"baseline"}
    assert run.is_dir()


def test_a_dangling_entry_can_be_removed_and_an_absent_one_changes_nothing(
    tmp_path: Path,
) -> None:
    run = _session(tmp_path / "runs" / "gone")
    registry, _, _ = pins.set_baseline(_registry(tmp_path), "gone", "baseline")
    for path in sorted(run.rglob("*"), reverse=True):
        path.unlink() if path.is_file() else path.rmdir()
    run.rmdir()
    assert [pin.run for pin in _registry(tmp_path).dangling()] == ["gone"]
    before = (tmp_path / "pins.json").read_bytes()

    with pytest.raises(pins.PinError, match="no keep registration"):
        pins.remove(_registry(tmp_path), "gone", "keep")
    assert (tmp_path / "pins.json").read_bytes() == before

    registry = pins.remove(_registry(tmp_path), "gone", "baseline")
    assert registry.pins == ()


def test_the_registry_is_replaced_whole_and_rejects_foreign_names(tmp_path: Path) -> None:
    _session(tmp_path / "runs" / "run")
    pins.keep(_registry(tmp_path), "run", "why")

    assert [path.name for path in tmp_path.iterdir() if path.name.startswith(".")] == []
    stored = json.loads((tmp_path / "pins.json").read_text(encoding="utf-8"))
    assert stored == {
        "schema_version": 1,
        "pins": [{"run": "run", "role": "keep", "reason": "why"}],
    }

    stored["pins"].append({"run": "../elsewhere", "role": "keep", "reason": "x"})
    (tmp_path / "pins.json").write_text(json.dumps(stored), encoding="utf-8")
    with pytest.raises(pins.PinError, match="bare run name"):
        _registry(tmp_path)
    with pytest.raises(pins.PinError, match="not a run directory"):
        pins.keep(pins.Registry(tmp_path / "p2.json", tmp_path / "runs", ()), "../x", "why")


def test_a_registered_baseline_is_found_for_a_compatible_run(tmp_path: Path) -> None:
    _session(tmp_path / "runs" / "base")
    new = _session(tmp_path / "runs" / "new")
    registry, _, _ = pins.set_baseline(_registry(tmp_path), "base", "why")

    found = registry.baseline_for(run_identity(new))

    assert found is not None and found.name == "base"
    assert registry.baseline_for(run_identity(tmp_path / "runs" / "base")) is None


def test_the_cli_lists_every_kind_and_filters_by_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from lab import cli, identity

    _session(tmp_path / "runs" / "20261007-100000-tour")
    (tmp_path / "runs" / "manual").mkdir()
    monkeypatch.setattr(identity, "RUNS_ROOT", tmp_path / "runs")
    monkeypatch.setattr(pins, "PINS_PATH", tmp_path / "pins.json")
    monkeypatch.setattr(pins, "RUNS_ROOT", tmp_path / "runs")

    assert cli.main(["report", "--list"]) == 0
    listed = capsys.readouterr().out
    assert "20261007-100000-tour" in listed and "manual" in listed

    assert cli.main(["report", "--list", "--kind", "unknown"]) == 0
    assert capsys.readouterr().out.split()[0] == "manual"

    assert cli.main(["baseline", "unset", "20261007-100000-tour"]) == 2
    assert "no baseline registration" in capsys.readouterr().err
    assert not (tmp_path / "pins.json").exists()


def test_writers_add_provenance_without_touching_their_own_payload(tmp_path: Path) -> None:
    written = build_metadata(scenario={"name": "x"}, kind="real_hover", source=CLEAN)

    assert written["commit"] == "a" * 40
    assert written["lab_provenance"]["kind"] == "real_hover"
    assert written["lab_provenance"]["source"] == CLEAN
    assert "lab_provenance" not in build_metadata(scenario={"name": "x"}, source=CLEAN)
