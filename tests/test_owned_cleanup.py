"""Removing what Hanly left behind, and refusing everything else.

Every rule here is chosen so the failure mode is leaving something behind
rather than deleting something that mattered, so most of these assert that a
directory survived.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from hanly_app.owned_cleanup import (
    MARKER_NAME,
    MIN_AGE_SECONDS,
    RECOVERY_REQUIRED,
    CleanupError,
    OwnedWorkspace,
    StagingLocation,
    sweep_staging,
    update_staging_locations,
)

from tests.hanly_fixtures.capabilities import requires_symlinks


class _Clock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _workspace(tmp_path: Path, clock: _Clock) -> OwnedWorkspace:
    return OwnedWorkspace(tmp_path / "work", clock=clock)


def test_an_opened_directory_carries_a_marker_naming_its_owner(tmp_path: Path) -> None:
    clock = _Clock()
    owned = _workspace(tmp_path, clock).open("resource-staging")

    marker = json.loads((owned.path / MARKER_NAME).read_text(encoding="utf-8"))

    assert owned.path.is_dir()
    assert marker["operation"] == "resource-staging"
    assert marker["owner_pid"] == os.getpid()
    assert marker["version"] == 1


def test_two_operations_opened_together_never_share_a_directory(tmp_path: Path) -> None:
    """One process, one kind of work, one clock tick: a name built from those
    three collides, and the first to finish would delete the other's work."""

    workspace = _workspace(tmp_path, _Clock())

    first = workspace.open("update")
    second = workspace.open("update")

    assert first.path != second.path
    workspace.complete(first)
    assert second.path.is_dir()


def test_this_process_is_alive_and_an_unused_id_is_not() -> None:
    """The liveness check itself, on the platform actually running the tests."""

    from hanly_app.owned_cleanup import _process_alive

    assert _process_alive(os.getpid())
    assert not _process_alive(999_999)
    assert not _process_alive(0)


def test_a_completed_operation_removes_its_directory_at_once(tmp_path: Path) -> None:
    clock = _Clock()
    workspace = _workspace(tmp_path, clock)
    owned = workspace.open("update")

    workspace.complete(owned)

    assert not owned.path.exists()


def test_a_live_owner_keeps_its_directory_however_old_it_is(tmp_path: Path) -> None:
    """A recycled process id can only make Hanly keep a directory."""

    clock = _Clock()
    workspace = _workspace(tmp_path, clock)
    owned = workspace.open("update")
    clock.advance(MIN_AGE_SECONDS * 10)

    report = workspace.sweep()

    assert owned.path in report.preserved
    assert owned.path.is_dir()


def test_an_abandoned_directory_is_reaped_once_it_has_aged(tmp_path: Path) -> None:
    clock = _Clock()
    workspace = _workspace(tmp_path, clock)
    owned = workspace.open("update")
    _reassign_owner(owned.path, pid=999_999)
    clock.advance(MIN_AGE_SECONDS + 1)

    report = workspace.sweep()

    assert owned.path in report.removed
    assert not owned.path.exists()


def test_a_young_abandoned_directory_is_left_alone(tmp_path: Path) -> None:
    """An operation that is merely slow must not be mistaken for a dead one."""

    clock = _Clock()
    workspace = _workspace(tmp_path, clock)
    owned = workspace.open("update")
    _reassign_owner(owned.path, pid=999_999)
    clock.advance(MIN_AGE_SECONDS / 2)

    report = workspace.sweep()

    assert owned.path in report.preserved
    assert owned.path.is_dir()


def test_a_directory_needing_recovery_is_reported_and_never_removed(
    tmp_path: Path,
) -> None:
    clock = _Clock()
    workspace = _workspace(tmp_path, clock)
    owned = workspace.open("update")
    workspace.require_recovery(owned, "the previous build is the only working copy")
    _reassign_owner(owned.path, pid=999_999, status=RECOVERY_REQUIRED)
    clock.advance(MIN_AGE_SECONDS * 5)

    report = workspace.sweep()

    assert owned.path in report.recovery_required
    assert owned.path.is_dir()
    assert any("kept rather than removed" in line for line in report.messages())


def test_an_unmarked_directory_is_never_touched(tmp_path: Path) -> None:
    """The marker is the whole permission; without one it is somebody else's."""

    clock = _Clock()
    workspace = _workspace(tmp_path, clock)
    workspace.open("update")
    stranger = workspace.root / "someone-elses-data"
    stranger.mkdir()
    (stranger / "keep.txt").write_text("mine", encoding="utf-8")
    clock.advance(MIN_AGE_SECONDS * 5)

    report = workspace.sweep()

    assert stranger in report.preserved
    assert (stranger / "keep.txt").is_file()


@requires_symlinks
def test_a_symlink_into_the_root_is_refused(tmp_path: Path) -> None:
    clock = _Clock()
    workspace = _workspace(tmp_path, clock)
    workspace.open("update")
    outside = tmp_path / "precious"
    outside.mkdir()
    (outside / "keep.txt").write_text("mine", encoding="utf-8")
    (workspace.root / "link").symlink_to(outside, target_is_directory=True)
    clock.advance(MIN_AGE_SECONDS * 5)

    workspace.sweep()

    assert (outside / "keep.txt").is_file()


def test_a_path_outside_the_root_cannot_be_completed(tmp_path: Path) -> None:
    from hanly_app.owned_cleanup import OwnedDirectory

    clock = _Clock()
    workspace = _workspace(tmp_path, clock)
    outside = tmp_path / "elsewhere"
    outside.mkdir()

    with pytest.raises(CleanupError, match="not inside"):
        workspace.complete(
            OwnedDirectory(outside, "update", os.getpid(), clock.now)
        )
    assert outside.is_dir()


def test_an_operation_name_must_be_one_path_segment(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, _Clock())

    with pytest.raises(CleanupError, match="path segment"):
        workspace.open("../escape")


def test_abandoned_update_staging_is_reaped_after_it_ages(tmp_path: Path) -> None:
    clock = _Clock()
    staging = tmp_path / ".hanly-update-abc"
    staging.mkdir()
    (staging / "download").write_bytes(b"partial")
    os.utime(staging, (clock.now - MIN_AGE_SECONDS - 1,) * 2)

    report = sweep_staging(
        [StagingLocation(root=tmp_path, prefix=".hanly-update-")], clock=clock
    )

    assert staging in report.removed
    assert not staging.exists()


def test_staging_that_still_holds_a_previous_build_is_kept(tmp_path: Path) -> None:
    """Its backup may be the only copy of a working Hanly, and disk is never a
    reason to delete that."""

    clock = _Clock()
    staging = tmp_path / ".hanly-update-abc"
    (staging / "previous").mkdir(parents=True)
    os.utime(staging, (clock.now - MIN_AGE_SECONDS * 10,) * 2)

    report = sweep_staging(
        update_staging_locations(tmp_path / "Hanly.app", tmp_path / "tmp"), clock=clock
    )

    assert staging in report.recovery_required
    assert (staging / "previous").is_dir()


def test_a_rejected_build_is_kept_for_the_same_reason(tmp_path: Path) -> None:
    clock = _Clock()
    staging = tmp_path / ".hanly-update-abc"
    (staging / "rejected").mkdir(parents=True)
    os.utime(staging, (clock.now - MIN_AGE_SECONDS * 10,) * 2)

    report = sweep_staging(
        update_staging_locations(tmp_path / "Hanly.app", tmp_path / "tmp"), clock=clock
    )

    assert staging in report.recovery_required


def test_the_audited_locations_cover_the_staging_and_the_handoff_script(
    tmp_path: Path,
) -> None:
    locations = update_staging_locations(tmp_path / "app" / "Hanly.app", tmp_path / "tmp")

    prefixes = {location.prefix for location in locations}
    assert prefixes == {"hanly-update.", ".hanly-update-"}
    assert (tmp_path / "app") in {location.root for location in locations}


def test_nothing_is_swept_when_hanly_is_not_installed(tmp_path: Path) -> None:
    locations = update_staging_locations(None, tmp_path / "tmp")

    assert [location.prefix for location in locations] == ["hanly-update."]


def _reassign_owner(path: Path, *, pid: int, status: str = "active") -> None:
    """Rewrite a marker as if another, now dead, process had written it."""

    marker = path / MARKER_NAME
    payload = json.loads(marker.read_text(encoding="utf-8"))
    payload["owner_pid"] = pid
    payload["status"] = status
    marker.write_text(json.dumps(payload), encoding="utf-8")
