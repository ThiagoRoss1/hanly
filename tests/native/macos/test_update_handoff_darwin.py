"""The rollback only macOS needs: ``open`` returns no pid to stop."""

from __future__ import annotations

import subprocess
from pathlib import Path

from tests.hanly_fixtures.update_handoff import assert_identity, prepare_handoff, run_handoff


def test_a_rejected_macos_build_is_stopped_from_a_path_full_of_metacharacters(
    tmp_path: Path,
) -> None:
    """``open`` returns no pid, so macOS finds the candidate by the path it runs
    from -- and an installation path is text a person chose, not a pattern. Read
    as a regular expression, ``C++ apps`` does not compile and ``[beta]`` is a
    character class, so the candidate is silently never matched and survives the
    rollback that deletes the directory underneath it."""

    handoff = run_handoff(
        prepare_handoff(
            tmp_path / "C++ apps [beta]",
            "darwin",
            new_version="9.9.9",
            linger=60,
            probe_root=tmp_path / "probe",
        ),
        expect_status=1,
    )

    assert handoff.await_launched(["new", "old"]) == ["new", "old"]
    # Only the candidate is started with the readiness argument, so this sees
    # that one process and never the restored build launched beside it.
    assert not _running_with(str(handoff.transaction.ready_path))
    assert not handoff.transaction.directory.exists()
    assert_identity(handoff, "old")


def _running_with(argument: str) -> bool:
    """Whether any process still carries ``argument`` on its command line.

    Compared as literal text rather than handed to ``pgrep -f``: the paths this
    checks are exactly the ones a regular expression would misread.
    """

    listing = subprocess.run(
        ["/bin/ps", "-axww", "-o", "args="], capture_output=True, text=True
    ).stdout
    return any(argument in line for line in listing.splitlines())
