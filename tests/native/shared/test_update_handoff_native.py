"""The swap itself, run for real: two compiled builds and the production script.

What the rendered script says is a portable contract and is checked in the
portable suite. What a shell does with it is not: these cases execute the
handoff against builds this host compiled, and read back which one answered at
the installation path afterwards.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.hanly_fixtures.update_handoff import (
    HANDOFF_VARIANTS,
    assert_identity,
    prepare_handoff,
    run_handoff,
    with_dead_pid,
)


@pytest.mark.parametrize("platform", HANDOFF_VARIANTS)
def test_a_verified_update_replaces_the_installation_and_cleans_up_after_itself(
    tmp_path: Path, platform: str
) -> None:
    handoff = run_handoff(prepare_handoff(tmp_path, platform), expect_status=0)
    install_root = handoff.transaction.install_root

    assert handoff.await_launched(["new"]) == ["new"]
    assert install_root.is_dir()
    # Nothing of the update survives it: no staged build, no backup, no script.
    assert not handoff.transaction.directory.exists()
    assert not handoff.script.exists()
    assert [item.name for item in install_root.parent.iterdir()] == [install_root.name]


@pytest.mark.parametrize("platform", HANDOFF_VARIANTS)
def test_a_new_build_that_never_reports_starting_gives_the_old_one_back(
    tmp_path: Path, platform: str
) -> None:
    """The swap succeeding is not the update succeeding. A build that installs
    and then cannot run would otherwise leave the user with nothing, because the
    only working copy was deleted the moment the rename returned."""

    handoff = run_handoff(prepare_handoff(tmp_path, platform, new_version="9.9.9"), expect_status=1)
    install_root = handoff.transaction.install_root

    assert handoff.await_launched(["new", "old"]) == ["new", "old"]
    assert not handoff.transaction.directory.exists()
    assert [item.name for item in install_root.parent.iterdir()] == [install_root.name]
    assert_identity(handoff, "old")


@pytest.mark.parametrize("platform", HANDOFF_VARIANTS)
def test_a_replacement_that_cannot_be_moved_into_place_relaunches_the_old_build(
    tmp_path: Path, platform: str
) -> None:
    handoff = prepare_handoff(tmp_path, platform)
    shutil.rmtree(handoff.transaction.staged_path)

    run_handoff(handoff, expect_status=1)

    assert handoff.await_launched(["old"]) == ["old"]
    assert not handoff.transaction.directory.exists()
    assert_identity(handoff, "old")


@pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("pgrep") is None,
    reason="this is the POSIX rollback, and pgrep is how it is observed",
)
def test_a_rejected_build_that_is_still_running_is_stopped_before_the_posix_restore(
    tmp_path: Path,
) -> None:
    """POSIX renames a directory out from under a running program without
    complaint, so a rollback that does not stop the rejected build leaves it
    running out of a directory the handoff then deletes -- beside the restored
    build it just relaunched."""

    handoff = run_handoff(
        prepare_handoff(tmp_path, "linux", new_version="9.9.9", linger=60), expect_status=1
    )

    assert handoff.await_launched(["new", "old"]) == ["new", "old"]
    # Only the candidate is started with the readiness argument, so this sees
    # that one process and never the restored build launched beside it.
    assert not _running(f"update-ready {handoff.transaction.ready_path}")
    assert_identity(handoff, "old")


def _running(pattern: str) -> bool:
    """Whether any process's command line still matches ``pattern``."""

    return subprocess.run(["pgrep", "-f", pattern], capture_output=True).returncode == 0


@pytest.mark.skipif(sys.platform == "win32", reason="the shim replaces a POSIX mv")
def test_a_rollback_that_itself_fails_launches_nothing_and_keeps_the_backup(
    tmp_path: Path,
) -> None:
    """Neither build is at the installation path, so nothing there is safe to
    start; the previous one stays under the transaction for a person to restore."""

    handoff = prepare_handoff(tmp_path, sys.platform)
    shutil.rmtree(handoff.transaction.staged_path)
    shim = tmp_path / "bin"
    shim.mkdir()
    # Fail only the restoring move, so the branch under test is the one that
    # cannot put the previous build back.
    (shim / "mv").write_text(
        f'#!/bin/sh\ncase "$1" in "{handoff.transaction.backup_path}") exit 1 ;; esac\n'
        'exec /bin/mv "$@"\n',
        encoding="ascii",
        newline="\n",
    )
    (shim / "mv").chmod(0o755)

    environment = dict(os.environ)
    environment["PATH"] = f"{shim}{os.pathsep}{environment['PATH']}"
    finished = subprocess.run(
        ["/bin/sh", str(handoff.script), *with_dead_pid(handoff)],
        check=False,
        capture_output=True,
        timeout=180,
        env=environment,
    )

    assert finished.returncode == 1, finished.stderr.decode("utf-8", "replace")
    assert handoff.launched == []  # nothing was asked to start, so nothing can arrive
    assert not handoff.transaction.install_root.exists()
    assert handoff.transaction.backup_path.is_dir()


@pytest.mark.parametrize("platform", HANDOFF_VARIANTS)
def test_an_installation_path_with_spaces_and_non_ascii_survives_the_handoff(
    tmp_path: Path, platform: str
) -> None:
    handoff = run_handoff(
        prepare_handoff(tmp_path / "한글 프로그램", platform, probe_root=tmp_path / "probe"),
        expect_status=0,
    )

    assert "한글 프로그램" in str(handoff.transaction.install_root)
    assert handoff.await_launched(["new"]) == ["new"]
    assert_identity(handoff, "new")
