"""What the Windows apply program must be, read from the script it ships.

The behaviour is proved by running it (``tests/native/windows``). These are the
properties that have to hold before it runs at all: what it may depend on, how
long it waits, and that the copy kept for a broken installation is the same
program as the copy beside the transaction.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from hanly_app.app_update_helper import (
    CLAIM_WAIT_SECONDS,
    EXIT_WAIT_SECONDS,
    HELPER_SCRIPT_NAME,
    MOVE_ATTEMPTS,
    PENDING_NAME,
    READY_WAIT_SECONDS,
    RECOVERY_LAUNCHER_NAME,
    HelperError,
    await_claim,
    clear_recovery_copy,
    install_recovery_copy,
    pending_transaction,
    recover_pending,
    render_helper_script,
    write_helper,
)
from hanly_app.app_update_journal import UpdateJournal


def _journal(tmp_path: Path) -> UpdateJournal:
    journal = UpdateJournal(tmp_path / "install" / ".hanly-update" / "t1")
    journal.directory.mkdir(parents=True)
    (journal.directory / "plan.json").write_text("{}", encoding="utf-8")
    return journal


def test_the_helper_depends_on_nothing_it_is_replacing() -> None:
    """It has to run when Hanly is stopped, when Hanly is half-replaced, and
    when Hanly cannot start at all. Anything loaded out of the installation
    would fail in exactly the case it exists for."""

    body = render_helper_script()

    for forbidden in ("python", "hanly_app", "invoke-webrequest"):
        assert forbidden not in body.lower(), forbidden
    # Windows PowerShell and the .NET Framework that ships with Windows.
    for allowed in ("System.Windows.Forms", "System.IO.File", "Start-Process"):
        assert allowed in body, allowed


def test_the_helper_never_reaches_the_network() -> None:
    """Everything it needs was downloaded and verified before it started."""

    body = render_helper_script().lower()

    for reach in ("http://", "https://", "webclient", "downloadfile"):
        assert reach not in body


def test_the_shipped_waits_are_the_ones_the_body_carries() -> None:
    """A test that shortens them has to know it shortened the shipped value."""

    body = render_helper_script()

    assert body.count(f"AddSeconds({EXIT_WAIT_SECONDS})") == 1
    assert body.count(f"AddSeconds({READY_WAIT_SECONDS})") == 1
    assert f"-lt {MOVE_ATTEMPTS}" in body
    # Long enough for a cold frozen start; short enough that a build that will
    # never come up is rolled back the same day.
    assert READY_WAIT_SECONDS == 600


def test_a_written_helper_is_readable_by_powershell_as_utf8(tmp_path: Path) -> None:
    """``-File`` reads a script as UTF-8 only with a byte-order mark, and
    expects cmd-era line endings."""

    script = write_helper(tmp_path)

    raw = script.read_bytes()
    assert script.name == HELPER_SCRIPT_NAME
    assert raw.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" in raw
    assert raw.decode("utf-8-sig").replace("\r\n", "\n") == render_helper_script()


def test_the_recovery_copy_is_the_same_program_kept_somewhere_safe(
    tmp_path: Path,
) -> None:
    """Outside the installation, because that is what may be unstartable."""

    journal = _journal(tmp_path)
    recovery = tmp_path / "profile" / "recovery"

    install_recovery_copy(recovery, journal)

    assert (recovery / HELPER_SCRIPT_NAME).read_bytes() == (
        write_helper(tmp_path / "beside").read_bytes()
    )
    assert pending_transaction(recovery) == journal.directory
    launcher = (recovery / RECOVERY_LAUNCHER_NAME).read_text(encoding="ascii")
    assert HELPER_SCRIPT_NAME in launcher
    assert PENDING_NAME in launcher
    # A person double-clicks it; nothing of Hanly's may be needed to run it.
    assert "python" not in launcher.lower()


def test_clearing_the_recovery_record_leaves_nothing_to_act_on(tmp_path: Path) -> None:
    recovery = tmp_path / "recovery"
    install_recovery_copy(recovery, _journal(tmp_path))

    clear_recovery_copy(recovery)

    assert pending_transaction(recovery) is None
    assert not (recovery / RECOVERY_LAUNCHER_NAME).exists()


def test_a_settled_transaction_is_not_recovered_again(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    recovery = tmp_path / "recovery"
    install_recovery_copy(recovery, journal)
    journal.record("committed")

    assert recover_pending(recovery) is None
    assert pending_transaction(recovery) is None


def test_quitting_before_the_helper_owns_the_transaction_is_refused(
    tmp_path: Path,
) -> None:
    """Otherwise the application closes for no reason and the staged update has
    nobody to apply it."""

    journal = _journal(tmp_path)
    elapsed = iter([0.0, 1.0, CLAIM_WAIT_SECONDS + 1.0])

    with pytest.raises(HelperError, match="nothing has been changed"):
        await_claim(
            journal,
            clock=lambda: next(elapsed),
            sleep=lambda _seconds: None,
        )


def test_a_helper_that_claimed_the_transaction_reports_its_process(
    tmp_path: Path,
) -> None:
    journal = _journal(tmp_path)
    journal.helper_path.write_text(json.dumps({"pid": 4242}), encoding="utf-8-sig")

    assert await_claim(journal, sleep=lambda _seconds: None) == 4242
