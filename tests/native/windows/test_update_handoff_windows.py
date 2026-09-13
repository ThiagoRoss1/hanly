"""The rollback only Windows needs: a directory it will not rename."""

from __future__ import annotations

from pathlib import Path

from tests.hanly_fixtures.update_handoff import assert_identity, prepare_handoff, run_handoff


def test_a_rejected_build_that_is_still_running_is_stopped_before_the_restore(
    tmp_path: Path,
) -> None:
    """A build that comes up and then reports the wrong version is the case the
    swap has to undo while the new build is still holding the installation
    directory. Windows refuses to rename that directory until the program
    started from it is gone, so a rollback that does not stop it first restores
    nothing and leaves the rejected build installed."""

    handoff = run_handoff(
        prepare_handoff(tmp_path, "win32", new_version="9.9.9", linger=60), expect_status=1
    )

    assert handoff.await_launched(["new", "old"]) == ["new", "old"]
    assert not handoff.transaction.directory.exists()
    assert [item.name for item in handoff.transaction.install_root.parent.iterdir()] == [
        handoff.transaction.install_root.name
    ]
    assert_identity(handoff, "old")
