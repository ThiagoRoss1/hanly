"""The in-place apply, over a real installation, by the shipped helper.

Everything here runs the production PowerShell against two compiled programs in
a throwaway tree. A rendered script proves nothing about what Windows does with
an executable it is holding open, which is the only part of this update that
cannot be checked any other way.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hanly_app.app_update_journal import COMMITTED, RESTORED

from tests.hanly_fixtures.update_handoff import COMPILER
from tests.hanly_fixtures.update_transaction import (
    PROGRAM_NAME,
    Installation,
    append_operation,
    build_installation,
    run_helper,
)

pytestmark = pytest.mark.skipif(
    COMPILER is None,
    reason="the apply cases compile the builds they install; no cc, clang, or gcc on PATH",
)


def _install(
    tmp_path: Path, *, reported_version: str | None = None, linger: int = 0
) -> Installation:
    return build_installation(
        tmp_path / "tree",
        tmp_path / "probe",
        reported_version=reported_version,
        linger=linger,
    )


def test_only_the_changed_files_move_and_the_new_build_starts(tmp_path: Path) -> None:
    """The whole contract in one run: one file added, one replaced, one
    removed, everything else untouched, and the installation still at the path
    it was always at."""

    installation = _install(tmp_path)
    unchanged = installation.digest("_internal/unchanged.txt")

    run_helper(installation)
    result = installation.await_outcome()

    assert result["outcome"] == COMMITTED
    assert installation.read("_internal/added.txt") == "new file\n"
    assert installation.read("_internal/dropped.txt") is None
    assert installation.digest("_internal/unchanged.txt") == unchanged
    assert installation.launched == ["new"]
    assert installation.program.is_file()


def test_a_build_that_reports_the_wrong_version_is_rolled_back(tmp_path: Path) -> None:
    """Startup acknowledgement is the gate, not extraction. A replacement that
    runs but is not the build that was installed has to be undone, while it is
    still holding the executable Windows will not let go of."""

    installation = _install(tmp_path, reported_version="9.9.9", linger=30)
    before = installation.digest(PROGRAM_NAME)

    run_helper(installation)
    result = installation.await_outcome()

    assert result["outcome"] == RESTORED
    assert installation.digest(PROGRAM_NAME) == before
    assert installation.read("_internal/dropped.txt") == "goes\n"
    assert installation.read("_internal/added.txt") is None
    assert installation.launched == ["new", "old"]


def test_an_interrupted_apply_settles_when_the_helper_runs_again(tmp_path: Path) -> None:
    """Every step reads the filesystem before acting, so a transaction stopped
    part way through reaches the same installation on a second run rather than
    moving something twice or restoring over the new file."""

    installation = _install(tmp_path)
    operations = installation.journal.read_plan().operations

    # Exactly the state an interruption between the filesystem and the journal
    # leaves: the addition is in place and nothing recorded it.
    payload = installation.journal.payload_for(operations[0])
    destination = installation.root / "_internal" / "added.txt"
    payload.replace(destination)

    run_helper(installation, recover=True)
    result = installation.await_outcome()

    assert result["outcome"] == COMMITTED
    assert installation.read("_internal/added.txt") == "new file\n"
    assert installation.read("_internal/dropped.txt") is None
    assert installation.launched == ["new"]


def test_the_helper_needs_nothing_out_of_the_tree_it_is_changing(tmp_path: Path) -> None:
    """A helper that loaded anything from the installation could not repair one
    that is half-replaced, which is the case it exists for."""

    installation = _install(tmp_path)
    body = installation.script.read_text(encoding="utf-8-sig")

    assert "python" not in body.lower()
    assert "hanly_app" not in body
    for assembly in ("System.Windows.Forms", "System.Drawing"):
        assert f"Add-Type -AssemblyName {assembly}" in body


def test_every_file_move_survives_spaces_and_hangul_in_the_install_path(
    tmp_path: Path,
) -> None:
    """Every path reaching the helper is an argument or a journal field, never
    text rendered into a command, and every move goes through an
    extended-length path. A person's own Downloads folder is where this breaks
    if either of those is wrong.

    The outcome here is a rollback rather than a commit, and that is the
    fixture's limit rather than the helper's: the replacement is a C program
    receiving ``--update-ready`` through an ANSI ``argv``, so a Hangul path
    reaches it as ``?? ????`` and it cannot write the readiness file. What the
    case proves is the part that is in doubt — every add, replace, delete, and
    then every restore, over a path like this. Startup acknowledgement is
    proved by the cases above, and the shipped build reads a wide ``argv``.
    """

    installation = build_installation(tmp_path / "한국어 프로그램 (beta)", tmp_path / "probe")
    before = installation.digest(PROGRAM_NAME)

    run_helper(installation)
    installation.await_outcome()

    applied = [
        record.get("operation")
        for record in installation.journal.records()
        if record.get("phase") == "applied"
    ]
    assert applied == [1, 2, 3]
    assert installation.digest(PROGRAM_NAME) == before
    assert installation.read("_internal/dropped.txt") == "goes\n"
    assert installation.read("_internal/added.txt") is None


def test_a_deeply_nested_file_past_the_old_path_limit_is_still_replaced(
    tmp_path: Path,
) -> None:
    """A PyInstaller tree reaches past 260 characters inside its own bundled
    packages, and a helper that used the ordinary APIs would fail there
    without a machine-wide setting nobody can rely on."""

    installation = _install(tmp_path)
    deep = "/".join(
        ["_internal", *(f"a_long_package_directory_name_{index}" for index in range(8))]
    )
    target = installation.root.joinpath(*deep.split("/"))
    target.mkdir(parents=True)
    (target / "buried.txt").write_text("old\n", encoding="utf-8")
    assert len(str(target)) > 260

    payload = installation.root.parent / "buried-payload.txt"
    payload.write_text("replaced\n", encoding="utf-8")
    append_operation(installation, f"{deep}/buried.txt", payload)

    run_helper(installation)
    result = installation.await_outcome()

    assert result["outcome"] == COMMITTED
    assert (target / "buried.txt").read_text(encoding="utf-8") == "replaced\n"


def test_an_addition_never_overwrites_a_file_that_appeared_since_planning(
    tmp_path: Path,
) -> None:
    """An addition has no backup, so a file at that path which the plan did not
    see is the one thing an apply can destroy outright. It stops instead, and
    the rollback puts back everything it had already moved."""

    installation = _install(tmp_path)
    intruder = installation.root / "_internal" / "added.txt"
    intruder.write_text("someone else's file\n", encoding="utf-8")
    before = installation.digest(PROGRAM_NAME)

    run_helper(installation)
    result = installation.await_outcome()

    assert result["outcome"] == RESTORED
    assert intruder.read_text(encoding="utf-8") == "someone else's file\n"
    assert installation.digest(PROGRAM_NAME) == before
    assert installation.read("_internal/dropped.txt") == "goes\n"
