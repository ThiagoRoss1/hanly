"""Storage inventory and the conservative clean-up, on disposable fixtures only."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

import pytest

from lab import pins, storage
from lab.metadata import provenance

CLEAN = {"commit": "a" * 40, "dirty": False, "state": "clean"}
LATER = time.time() + 3600
DECLARED = ["install", "release", "profile", "temp"]


def _update_run(root: Path, name: str = "20261007-100000-windows-update", **block: Any) -> Path:
    run = root / name
    for sub in DECLARED:
        (run / sub / "nested").mkdir(parents=True)
        (run / sub / "nested" / "payload.bin").write_bytes(b"x" * 2048)
    (run / "logs").mkdir()
    (run / "logs" / "profile__app.log").write_text("kept", "utf-8")
    summary = {
        "mode": "install",
        "source_tag": "v0.9.0",
        "remnants": {},
        "events": [],
        "passed": True,
        "lab_provenance": provenance(
            "update_check", CLEAN, disposable=block.pop("disposable", DECLARED), **block
        ),
    }
    (run / "summary.json").write_text(json.dumps(summary), "utf-8")
    return run


def _tree(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): (
            hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "dir"
        )
        for path in sorted(root.rglob("*"))
    }


def _registry(tmp_path: Path) -> pins.Registry:
    return pins.load(tmp_path / "pins.json", tmp_path / "runs")


@pytest.fixture
def runs(tmp_path: Path) -> Path:
    root = tmp_path / "runs"
    root.mkdir()
    return root


def test_a_preview_changes_nothing_and_apply_keeps_every_evidence_file(
    tmp_path: Path, runs: Path
) -> None:
    run = _update_run(runs)
    before = _tree(tmp_path)

    plan = storage.preview(runs, _registry(tmp_path), now=LATER)

    assert _tree(tmp_path) == before
    assert sorted(target["subtree"] for target in plan["targets"]) == sorted(DECLARED)
    assert plan["reclaimable_bytes"] == 4 * 2048
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan), "utf-8")

    result = storage.apply(path, runs, _registry(tmp_path), now=LATER)

    assert result["status"] == "complete" and len(result["deleted"]) == 4
    assert sorted(item.name for item in run.iterdir()) == ["logs", "summary.json"]
    assert (run / "logs" / "profile__app.log").read_text("utf-8") == "kept"


@pytest.mark.parametrize(
    "setup",
    ["pinned", "recent", "legacy", "unknown", "preserved_names"],
)
def test_protected_material_is_never_proposed(tmp_path: Path, runs: Path, setup: str) -> None:
    now = LATER
    registry = _registry(tmp_path)
    if setup == "pinned":
        _update_run(runs)
        registry = pins.keep(registry, "20261007-100000-windows-update", "evidence")
    elif setup == "recent":
        _update_run(runs)
        now = time.time()
    elif setup == "legacy":
        run = _update_run(runs)
        summary = json.loads((run / "summary.json").read_text("utf-8"))
        del summary["lab_provenance"]
        (run / "summary.json").write_text(json.dumps(summary), "utf-8")
    elif setup == "unknown":
        manual = runs / "20261005-mac-update" / "install-1"
        _update_run(manual.parent, "install-1")
        (manual.parent / "install-1.log").write_text("manual", "utf-8")
    else:
        run = _update_run(runs, disposable=["replay", "summary.json", "../x", "frozen-2", "logs"])
        (run / "replay").mkdir()

    plan = storage.preview(runs, registry, now=now)

    assert plan["targets"] == []
    if setup in {"pinned", "recent"}:
        assert {kept["subtree"] for kept in plan["kept"]} == set(DECLARED)


def test_an_unfinished_session_keeps_its_browser_folder(tmp_path: Path, runs: Path) -> None:
    run = runs / "20261007-100000-stress"
    (run / "browser").mkdir(parents=True)
    (run / "browser" / "lines.html").write_text("x", "utf-8")
    block = provenance("stress", CLEAN, disposable=["browser"])
    (run / "metadata.json").write_text(json.dumps({"mode": "stress", "lab_provenance": block}))
    (run / "events.jsonl").write_text(json.dumps({"event": "tour_planned"}) + "\n", "utf-8")

    unfinished = storage.preview(runs, _registry(tmp_path), now=LATER)
    with (run / "events.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"event": "tour_finished"}) + "\n")
    finished = storage.preview(runs, _registry(tmp_path), now=LATER)

    assert unfinished["targets"] == [] and "unfinished" in unfinished["kept"][0]["reason"]
    assert [target["subtree"] for target in finished["targets"]] == ["browser"]


def test_links_are_never_followed_or_collected(tmp_path: Path, runs: Path) -> None:
    run = _update_run(runs)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "precious.txt").write_text("keep", "utf-8")
    (run / "temp" / "nested" / "escape").symlink_to(outside)
    for sub in ("install", "release", "profile"):
        os.rename(run / sub, tmp_path / f"moved-{sub}")
    (run / "profile").symlink_to(tmp_path / "moved-profile")

    plan = storage.preview(runs, _registry(tmp_path), now=LATER)

    reasons = {kept["subtree"]: kept["reason"] for kept in plan["kept"]}
    assert "link" in reasons["temp"] and "link" in reasons["profile"]
    assert plan["targets"] == []
    assert (outside / "precious.txt").exists()


def test_a_stale_or_edited_plan_deletes_nothing(tmp_path: Path, runs: Path) -> None:
    run = _update_run(runs)
    plan = storage.preview(runs, _registry(tmp_path), now=LATER)
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan), "utf-8")
    (run / "temp" / "nested" / "late.txt").write_text("written after the preview", "utf-8")
    before = _tree(run)

    with pytest.raises(storage.StorageError, match="contents changed"):
        storage.apply(path, runs, _registry(tmp_path), now=LATER)
    assert _tree(run) == before

    edited = {**plan, "targets": plan["targets"][:1]}
    path.write_text(json.dumps(edited), "utf-8")
    with pytest.raises(storage.StorageError, match="edited after the preview"):
        storage.apply(path, runs, _registry(tmp_path), now=LATER)


def test_a_run_pinned_after_the_preview_is_refused(tmp_path: Path, runs: Path) -> None:
    run = _update_run(runs)
    plan = storage.preview(runs, _registry(tmp_path), now=LATER)
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan), "utf-8")
    registry = pins.keep(_registry(tmp_path), run.name, "changed my mind")

    with pytest.raises(storage.StorageError, match="pinned"):
        storage.apply(path, runs, registry, now=LATER)
    assert (run / "install").is_dir()


def test_a_replaced_directory_is_refused(tmp_path: Path, runs: Path) -> None:
    run = _update_run(runs)
    plan = storage.preview(runs, _registry(tmp_path), now=LATER)
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan), "utf-8")
    os.rename(run / "install", tmp_path / "old-install")
    os.rename(tmp_path / "old-install", run / "install-aside")
    (run / "install" / "nested").mkdir(parents=True)
    (run / "install" / "nested" / "payload.bin").write_bytes(b"x" * 2048)

    with pytest.raises(storage.StorageError, match="different directory|contents changed"):
        storage.apply(path, runs, _registry(tmp_path), now=LATER)


@pytest.mark.parametrize("failure", [PermissionError, KeyboardInterrupt])
def test_a_deletion_that_stops_midway_says_exactly_where(
    tmp_path: Path, runs: Path, monkeypatch: pytest.MonkeyPatch, failure: type[BaseException]
) -> None:
    _update_run(runs)
    plan = storage.preview(runs, _registry(tmp_path), now=LATER)
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan), "utf-8")
    real_unlink = os.unlink
    calls = []

    def unlink(target: Any) -> None:
        calls.append(target)
        if len(calls) == 2:
            raise failure("stop")
        real_unlink(target)

    monkeypatch.setattr(storage.os, "unlink", unlink)

    result = storage.apply(path, runs, _registry(tmp_path), now=LATER)

    order = [f"{t['run']}/{t['subtree']}" for t in plan["targets"]]
    assert result["status"] == ("partial" if failure is PermissionError else "interrupted")
    assert result["deleted"] == order[:1]
    assert result["partial"] == order[1]
    assert result["not_attempted"] == order[2:]


def test_plans_cannot_name_anything_outside_a_run(tmp_path: Path, runs: Path) -> None:
    body = {"schema_version": 1, "targets": [{"run": "..", "subtree": "x"}]}
    plan = {**body, "plan_id": storage._plan_id(body)}
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan), "utf-8")

    with pytest.raises(storage.StorageError, match="outside a run root"):
        storage.apply(path, runs, _registry(tmp_path), now=LATER)


def test_a_redirected_runs_root_is_refused(tmp_path: Path, runs: Path) -> None:
    link = tmp_path / "redirected"
    link.symlink_to(runs)

    with pytest.raises(storage.StorageError, match="redirected"):
        storage.preview(link, _registry(tmp_path), now=LATER)


def test_the_inventory_separates_lab_packaging_and_unknown_material(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    runs = repo / "artifacts" / "lab" / "runs"
    runs.mkdir(parents=True)
    _update_run(runs)
    (runs / "20261005-mac-update").mkdir()
    (repo / "artifacts" / "benchmarks").mkdir()
    for name in ("macos", "hanly-desktop-macos.zip", "archive-bd7527b"):
        target = repo / "dist" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"1") if "." in name else target.mkdir()
    registry = pins.load(tmp_path / "pins.json", runs)

    report = storage.inventory(repo, registry, now=LATER)

    owners = {entry["path"]: entry["ownership"] for entry in report["entries"]}
    assert owners["artifacts/lab/runs/20261007-100000-windows-update"] == "lab"
    assert owners["artifacts/lab/runs/20261005-mac-update"] == "unknown"
    assert owners["artifacts/benchmarks"] == "unknown"
    assert owners["dist/macos"] == "packaging"
    assert owners["dist/hanly-desktop-macos.zip"] == "packaging"
    assert owners["dist/archive-bd7527b"] == "unknown"
    update = next(e for e in report["entries"] if e["kind"] == "update_check")
    assert update["disposable_bytes"] == 4 * 2048


def test_an_update_check_keeps_its_logs_before_offering_the_working_copies(
    tmp_path: Path,
) -> None:
    from lab.checks import windows_update

    root = tmp_path / "run"
    (root / "profile" / "Hanly" / "logs").mkdir(parents=True)
    (root / "profile" / "Hanly" / "logs" / "hanly.log").write_text("app", "utf-8")
    (root / "temp").mkdir()
    (root / "temp" / "updater.log").write_text("helper", "utf-8")

    kept = windows_update._retain_logs(root)

    assert kept == ["profile/Hanly/logs/hanly.log", "temp/updater.log"]
    assert (root / "logs" / "profile__Hanly__logs__hanly.log").read_text("utf-8") == "app"
    assert (root / "logs" / "temp__updater.log").read_text("utf-8") == "helper"
