"""The real POSIX swap, run against directories that can be thrown away.

Everything else about a POSIX update is checked with doubles. This is not: the
helper is compiled from its own source and run as a program, against a real
installation, a real candidate, and a real acknowledgement. What it proves is
the only thing a double cannot - that two directories actually exchange, that a
build which does not answer is actually put back, and that neither happens
twice.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from hanly_app.app_update_handoff import (
    LAUNCH_EXEC,
    NativeTransaction,
    read_descriptor,
    write_descriptor,
)

from tools.build_package import build_native_helper

pytestmark = pytest.mark.skipif(
    sys.platform.startswith("win32"), reason="the native POSIX helper is not a Windows program"
)

#: Short enough that a case that is going to fail fails quickly, long enough
#: that starting a shell script is not mistaken for a build that never came up.
EXIT_TIMEOUT = 5
READY_TIMEOUT = 10

EXPECTED = "HANLY-READY-2\ntransaction\nnonce\nhanly-desktop\nlinux\nx86_64\n0.5.3\nbuild\ndigest\n"


@pytest.fixture(scope="module")
def helper(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The helper, compiled from source exactly as a release builds it."""

    root = Path(__file__).resolve().parents[3]
    return build_native_helper(root, tmp_path_factory.mktemp("helper") / "hanly-update-posix")


class _Transaction:
    """One disposable installation, and the swap that would replace it."""

    def __init__(
        self, tmp_path: Path, *, answers: bool = True, keeps_running: bool = False
    ) -> None:
        self.root = tmp_path
        self.install = tmp_path / "apps" / "hanly-desktop"
        self.staging = tmp_path / "apps" / ".hanly-update-t1"
        self.state = tmp_path / "state"
        self.candidate = self.staging / "candidate"
        for directory in (self.install, self.candidate, self.state):
            directory.mkdir(parents=True)

        (self.install / "marker").write_text("old", encoding="utf-8")
        (self.candidate / "marker").write_text("new", encoding="utf-8")
        _write_program(self.install / "hanly-desktop", answers=False, expected="")
        _write_program(
            self.candidate / "hanly-desktop",
            answers=answers,
            expected=EXPECTED,
            keeps_running=keeps_running,
        )

        self.descriptor_path = self.staging / "descriptor"
        write_descriptor(self.descriptor_path, self.transaction())

    def transaction(self) -> NativeTransaction:
        install = os.stat(self.install)
        candidate = os.stat(self.candidate)
        return NativeTransaction(
            transaction_id="t1",
            lock_path=self.state / "native-lock",
            install_path=self.install,
            staging_path=self.staging,
            candidate_path=self.candidate,
            backup_path=self.staging / "previous",
            rejected_path=self.staging / "rejected",
            result_path=self.staging / "result",
            ack_path=self.state / "challenge-t1.ack",
            challenge_path=self.state / "challenge-t1.json",
            expected=EXPECTED,
            executable="hanly-desktop",
            launch=LAUNCH_EXEC,
            parent_pid=0,
            exit_timeout=EXIT_TIMEOUT,
            ready_timeout=READY_TIMEOUT,
            install_device=install.st_dev,
            install_inode=install.st_ino,
            candidate_device=candidate.st_dev,
            candidate_inode=candidate.st_ino,
        )

    def result(self) -> tuple[str, str]:
        lines = (self.staging / "result").read_text(encoding="utf-8").splitlines()
        return lines[0], lines[1] if len(lines) > 1 else ""

    def marker(self) -> str:
        return (self.install / "marker").read_text(encoding="utf-8")


def _write_program(
    path: Path, *, answers: bool, expected: str, keeps_running: bool = False
) -> None:
    """A stand-in for Hanly that either answers its challenge or does not.

    ``keeps_running`` is what a real build does: it answers and then goes on
    running for as long as the user keeps it open.
    """

    body = "#!/bin/sh\n"
    if answers:
        # ``$2`` is the challenge path the helper passes; the answer goes
        # beside it, exactly where a real build would write it.
        body += 'printf %s "$EXPECTED" > "${2%.json}.ack"\n'.replace(
            "$EXPECTED", expected.replace("\n", "\\n")
        )
        body = body.replace("printf %s", "printf '%b'")
    body += "sleep 120\n" if keeps_running else "exit 0\n"
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _run(helper: Path, descriptor: Path, *, recover: bool = False) -> int:
    command = [str(helper)]
    if recover:
        command.append("--recover")
    command.append(str(descriptor))
    return subprocess.run(command, check=False, capture_output=True, timeout=120).returncode


def test_a_candidate_that_answers_is_installed_and_the_old_build_is_kept(
    helper: Path, tmp_path: Path
) -> None:
    transaction = _Transaction(tmp_path)

    status = _run(helper, transaction.descriptor_path)

    assert status == 0
    assert transaction.result()[0] == "committed"
    assert transaction.marker() == "new"
    assert (transaction.staging / "previous" / "marker").read_text(encoding="utf-8") == "old"


def test_a_candidate_that_never_answers_is_rejected_and_the_old_build_returns(
    helper: Path, tmp_path: Path
) -> None:
    transaction = _Transaction(tmp_path, answers=False)

    status = _run(helper, transaction.descriptor_path)

    assert status == 1
    assert transaction.result()[0] == "restored"
    assert transaction.marker() == "old"
    assert (transaction.staging / "rejected" / "marker").read_text(encoding="utf-8") == "new"


def test_a_stale_answer_from_an_earlier_attempt_does_not_commit(
    helper: Path, tmp_path: Path
) -> None:
    transaction = _Transaction(tmp_path, answers=False)
    transaction.transaction().ack_path.write_text("0.5.3\n", encoding="utf-8")

    assert _run(helper, transaction.descriptor_path) == 1
    assert transaction.result()[0] == "restored"
    assert transaction.marker() == "old"


def test_an_interruption_between_the_two_renames_is_undone(
    helper: Path, tmp_path: Path
) -> None:
    transaction = _Transaction(tmp_path)
    # Exactly what a crash after the first rename leaves behind: the
    # installation path empty, the old build beside it, the candidate waiting.
    os.rename(transaction.install, transaction.staging / "previous")

    status = _run(helper, transaction.descriptor_path, recover=True)

    assert status == 1
    assert transaction.result()[0] == "restored"
    assert transaction.marker() == "old"


def test_an_interruption_after_both_renames_rolls_the_new_build_back(
    helper: Path, tmp_path: Path
) -> None:
    transaction = _Transaction(tmp_path, answers=False)
    os.rename(transaction.install, transaction.staging / "previous")
    os.rename(transaction.candidate, transaction.install)

    status = _run(helper, transaction.descriptor_path, recover=True)

    assert status == 1
    assert transaction.result()[0] == "restored"
    assert transaction.marker() == "old"
    assert (transaction.staging / "rejected" / "marker").read_text(encoding="utf-8") == "new"


def test_recovery_keeps_an_exactly_acknowledged_candidate_when_result_was_not_written(
    helper: Path, tmp_path: Path
) -> None:
    transaction = _Transaction(tmp_path)
    plan = transaction.transaction()
    os.rename(transaction.install, transaction.staging / "previous")
    os.rename(transaction.candidate, transaction.install)
    plan.ack_path.write_bytes(EXPECTED.encode("utf-8"))

    status = _run(helper, transaction.descriptor_path, recover=True)

    assert status == 0
    assert transaction.result()[0] == "committed"
    assert transaction.marker() == "new"
    assert (transaction.staging / "previous" / "marker").read_text(encoding="utf-8") == "old"


def test_recovery_works_with_no_installation_to_run_it_from(
    helper: Path, tmp_path: Path
) -> None:
    """The whole reason the helper is a separate program: it runs when Hanly
    cannot, out of a copy that is not inside the tree being replaced."""

    transaction = _Transaction(tmp_path)
    os.rename(transaction.install, transaction.staging / "previous")
    assert not transaction.install.exists()

    assert _run(helper, transaction.descriptor_path, recover=True) == 1
    assert transaction.install.is_dir()
    assert transaction.marker() == "old"


def test_an_installation_that_is_no_longer_the_one_recorded_is_not_touched(
    helper: Path, tmp_path: Path
) -> None:
    transaction = _Transaction(tmp_path)
    replacement = tmp_path / "apps" / "substitute"
    replacement.mkdir()
    (replacement / "marker").write_text("somebody else's", encoding="utf-8")
    os.rename(transaction.install, tmp_path / "moved-away")
    os.rename(replacement, transaction.install)

    assert _run(helper, transaction.descriptor_path) == 1
    assert transaction.result()[0] == "abandoned"
    assert transaction.marker() == "somebody else's"


def test_one_installation_admits_one_helper_at_a_time(
    helper: Path, tmp_path: Path
) -> None:
    transaction = _Transaction(tmp_path)
    lock = transaction.transaction().lock_path
    lock.parent.mkdir(parents=True, exist_ok=True)
    handle = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        import fcntl

        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert _run(helper, transaction.descriptor_path) == 2
    finally:
        os.close(handle)

    assert transaction.marker() == "old"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data[:-1],
        lambda data: data + b"trailing",
        lambda data: b"OTHERPKG" + data[8:],
        lambda data: data[:8] + (99).to_bytes(4, "big") + data[12:],
    ],
    ids=["truncated", "trailing", "wrong-magic", "wrong-version"],
)
def test_a_descriptor_this_helper_does_not_understand_changes_nothing(
    helper: Path, tmp_path: Path, mutate: Callable[[bytes], bytes]
) -> None:
    transaction = _Transaction(tmp_path)
    original = transaction.descriptor_path.read_bytes()
    transaction.descriptor_path.write_bytes(mutate(original))

    assert _run(helper, transaction.descriptor_path) == 2
    assert transaction.marker() == "old"
    assert not (transaction.staging / "result").exists()


def test_the_descriptor_round_trips_between_the_two_readers(tmp_path: Path) -> None:
    """Python writes it and the helper reads it; this holds Python to its own."""

    transaction = _Transaction(tmp_path)

    assert read_descriptor(transaction.descriptor_path) == transaction.transaction()


def test_the_helper_waits_for_the_answer_and_not_for_hanly_to_be_closed(
    helper: Path, tmp_path: Path
) -> None:
    """A real build answers and then keeps running for as long as the user
    keeps it open. A helper that waited on the program it started would hold
    the backup - and the whole update - open for the rest of the session."""

    transaction = _Transaction(tmp_path, keeps_running=True)

    started = time.monotonic()
    status = _run(helper, transaction.descriptor_path)
    elapsed = time.monotonic() - started

    assert status == 0
    assert transaction.result()[0] == "committed"
    assert transaction.marker() == "new"
    # The stand-in stays up for two minutes; committing must not wait for it.
    assert elapsed < 60
