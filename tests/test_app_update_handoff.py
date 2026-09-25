"""What the update handoff script says, before any shell is asked to run it.

Schema 2 adds the descriptor the native POSIX helper reads instead of a
script. It is a fixed binary record, so its round trip and its refusals are
checked here; running the real helper against it is native behavior.

These are the decisions the renderer makes -- which program each platform
relaunches, how the previous build outlives the swap, which waits are bounded,
how paths travel -- and every one of them is checked by reading the rendered
body. Running that body against real builds is native behavior and lives in
the native suite.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from hanly_app.app_update import APPLICATION_STEM
from hanly_app.app_update_handoff import (
    DESCRIPTOR_MAGIC,
    EXIT_WAIT_SECONDS,
    LAUNCH_EXEC,
    MAX_FIELD_BYTES,
    READY_ARGUMENT,
    READY_WAIT_SECONDS,
    HandoffError,
    NativeTransaction,
    _write_handoff_script,
    await_native_claim,
    clear_native_pending,
    handoff_arguments,
    install_native_helper,
    native_helper_is_running,
    native_pending,
    read_descriptor,
    read_native_result,
    record_native_pending,
    render_handoff_script,
    start_handoff,
    write_descriptor,
)

from tests.hanly_fixtures.capabilities import requires_posix_modes
from tests.hanly_fixtures.update_handoff import (
    MACOS_PROGRAM,
    c_string,
    transaction_for,
)

#: What a Windows installation calls the program inside it.
_WINDOWS_PROGRAM = f"{APPLICATION_STEM}.exe"


# --- what the rendered body has to say ---------------------------------------


def test_the_windows_relaunch_uses_the_program_path_exactly_as_it_was_given() -> None:
    """The layout's executable already carries ``.exe``. A template that appends
    one resolves ``hanly-desktop.exe.exe``, which exists nowhere: the swap then
    succeeds and the user is left with no running Hanly and no error."""

    script = render_handoff_script(executable=_WINDOWS_PROGRAM, platform="win32")

    assert f"'{_WINDOWS_PROGRAM}'" in script
    assert f"{_WINDOWS_PROGRAM}.exe" not in script
    assert script.count(_WINDOWS_PROGRAM) == 1


def test_the_windows_relaunch_quotes_the_path_it_hands_the_new_build() -> None:
    """``Start-Process -ArgumentList`` joins an array with spaces and quotes
    nothing. Most Windows installation paths contain a space, so an unquoted
    readiness path would reach the new build in pieces, never be written, and
    roll back an update that had in fact installed correctly."""

    script = render_handoff_script(executable=_WINDOWS_PROGRAM, platform="win32")

    assert f'Start-Hanly (\'{READY_ARGUMENT} \"\' + $Ready + \'\"\')' in script


def test_a_rejected_build_is_renamed_aside_rather_than_deleted() -> None:
    """A recursive delete can fail part way through, which would leave the
    installation path in pieces with the previous build not yet restored. A
    rename either happens or does not."""

    for platform, rename, delete in (
        (
            "win32",
            "[System.IO.Directory]::Move($Install, (Join-Path $Transaction 'rejected'))",
            "Remove-Item -LiteralPath $Install",
        ),
        ("linux", 'mv "$install" "$transaction/rejected"', 'rm -rf "$install"'),
    ):
        script = render_handoff_script(executable=APPLICATION_STEM, platform=platform)
        assert rename in script
        assert delete not in script


def test_macos_relaunches_the_application_and_never_the_program_inside_it() -> None:
    """``open`` is what registers the relaunched build with the window server;
    executing the program directly produces a process with no Dock entry."""

    script = render_handoff_script(executable=MACOS_PROGRAM, platform="darwin")

    assert '/usr/bin/open "$install" --args' in script
    assert MACOS_PROGRAM not in script


@pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
def test_the_previous_build_outlives_the_swap_that_replaced_it(platform: str) -> None:
    """Every step is ordered around one rule: the build known to work is still
    on disk until the build replacing it has said that it started."""

    script = render_handoff_script(executable=APPLICATION_STEM, platform=platform)
    aside, swap_in, answered, discard = (
        (
            "[System.IO.Directory]::Move($Install, $Backup)",
            "[System.IO.Directory]::Move($Staged, $Install)",
            "-ceq $Version",
            "Complete-Handoff",
        )
        if platform == "win32"
        else (
            'mv "$install" "$backup"',
            'mv "$staged" "$install"',
            '= "x$version"',
            'finish',
        )
    )

    assert script.index(aside) < script.index(swap_in) < script.index(READY_ARGUMENT)
    # The backup lives in the transaction directory, so discarding that
    # directory is what ends the update's ability to undo itself. On the path
    # where the swap worked, nothing discards it before the new build answered.
    verified = script[script.index(READY_ARGUMENT) :]
    assert verified.index(answered) < verified.index(discard)


@pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
def test_every_wait_is_bounded_so_a_stuck_handoff_cannot_spin_forever(
    platform: str,
) -> None:
    script = render_handoff_script(executable=APPLICATION_STEM, platform=platform)

    assert str(EXIT_WAIT_SECONDS) in script
    assert str(READY_WAIT_SECONDS) in script
    if platform == "win32":
        # ``timeout`` needs console input a detached process does not have, and
        # Start-Sleep is what a PowerShell handoff has instead.
        assert "timeout /t" not in script
        assert "Start-Sleep" in script


@pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
def test_the_paths_travel_as_arguments_and_never_as_generated_script_text(
    platform: str,
) -> None:
    """Generated text is where a shell picks up injection, and where a Windows
    console code page corrupts a non-ASCII installation path."""

    script = render_handoff_script(executable=APPLICATION_STEM, platform=platform)

    assert "hanly-update-" not in script
    assert script.isascii()


def test_a_windows_path_survives_being_compiled_into_the_probe() -> None:
    """``-DLOG="C:\\Users\\..."`` is a string of escape sequences, not a path,
    and ``\\U`` is not a valid one. This is what failed on the Windows runner
    before the probe's paths were escaped."""

    literal = c_string(r"C:\Users\runneradmin\AppData\Local\Temp\launched.txt")

    assert literal == r'"C:\\Users\\runneradmin\\AppData\\Local\\Temp\\launched.txt"'
    assert c_string('a "quoted" name') == r'"a \"quoted\" name"'


def test_a_powershell_handoff_is_written_with_the_bom_and_line_endings_it_needs(
    tmp_path: Path,
) -> None:
    """PowerShell reads a ``-File`` script as UTF-8 only when it starts with a
    BOM; without one a non-ASCII path inside it is decoded as the console code
    page. Asserted on the bytes, and on every host, because the platform that
    would notice is the one this suite usually cannot run on."""

    script = _write_handoff_script("Write-Output 'hi'\n", platform="win32", directory=tmp_path)
    raw = script.read_bytes()

    assert script.name == "hanly-update.ps1"
    assert raw.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" in raw


def test_a_posix_handoff_is_written_executable_without_a_bom(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows has no execute bit -- ``os.chmod`` there carries only the
    read-only flag -- so the mode the writer asks for is what every host can
    assert, and the mode the file lands with is asserted where one exists."""

    requested: list[int] = []
    chmod = Path.chmod

    def record(self: Path, mode: int) -> None:
        requested.append(mode)
        chmod(self, mode)

    monkeypatch.setattr(Path, "chmod", record)

    script = _write_handoff_script("#!/bin/sh\ntrue\n", platform="linux", directory=tmp_path)
    raw = script.read_bytes()

    assert script.name == "hanly-update.sh"
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" not in raw
    assert requested == [0o700]
    if os.name == "posix":
        assert script.stat().st_mode & 0o700 == 0o700


def test_the_script_is_written_outside_the_directory_it_removes(tmp_path: Path) -> None:
    transaction = transaction_for(tmp_path / "install")
    spawned: list[tuple[list[str], Path]] = []

    start_handoff(
        transaction,
        executable=APPLICATION_STEM,
        platform=sys.platform,
        spawn=lambda command, directory: spawned.append((command, directory)),
    )

    command, directory = spawned[0]
    script = Path(command[-8])
    assert script.is_file()
    assert transaction.directory not in script.parents
    # Never inside the script's own directory: a working directory stays in
    # use for the helper's life and the relaunched Hanly's, so cleanup of it
    # failed with "Access is denied" on Windows.
    assert directory == script.parent.parent
    assert script.parent not in (directory, *directory.parents)
    assert command[-7:] == handoff_arguments(transaction)


# --------------------------------------------------------------------------
# Schema 2: the descriptor the native helper reads
# --------------------------------------------------------------------------


def _native(tmp_path: Path, **overrides: object) -> NativeTransaction:
    values: dict[str, object] = {
        "transaction_id": "t1",
        "lock_path": tmp_path / "state" / "native-lock",
        "install_path": tmp_path / "apps" / "hanly-desktop",
        "staging_path": tmp_path / "apps" / ".hanly-update-t1",
        "candidate_path": tmp_path / "apps" / ".hanly-update-t1" / "candidate",
        "backup_path": tmp_path / "apps" / ".hanly-update-t1" / "previous",
        "rejected_path": tmp_path / "apps" / ".hanly-update-t1" / "rejected",
        "result_path": tmp_path / "apps" / ".hanly-update-t1" / "result",
        "ack_path": tmp_path / "state" / "challenge-t1.ack",
        "challenge_path": tmp_path / "state" / "challenge-t1.json",
        "expected": "HANLY-READY-2\nt1\ndeadbeef\n",
        "executable": "hanly-desktop",
        "launch": LAUNCH_EXEC,
        "parent_pid": 4321,
        "exit_timeout": 120,
        "ready_timeout": 600,
        "install_device": 16777232,
        "install_inode": 991122,
        "candidate_device": 16777232,
        "candidate_inode": 991123,
    }
    values.update(overrides)
    return NativeTransaction(**values)  # type: ignore[arg-type]


def test_a_descriptor_round_trips_through_the_bytes_the_helper_reads(
    tmp_path: Path,
) -> None:
    transaction = _native(tmp_path)

    payload = transaction.to_bytes()

    assert payload.startswith(DESCRIPTOR_MAGIC)
    assert NativeTransaction.from_bytes(payload) == transaction


def test_a_descriptor_that_is_not_exactly_this_format_is_refused(tmp_path: Path) -> None:
    payload = _native(tmp_path).to_bytes()

    for mutation, expected in (
        (payload[:-1], "ends inside a field"),
        (payload + b"extra", "trailing data"),
        (b"OTHERPKG" + payload[8:], "not one of ours"),
        (payload[:8] + (9).to_bytes(4, "big") + payload[12:], "different Hanly"),
    ):
        with pytest.raises(HandoffError, match=expected):
            NativeTransaction.from_bytes(mutation)


def test_a_field_too_long_for_the_helper_is_refused_before_it_is_written(
    tmp_path: Path,
) -> None:
    transaction = _native(tmp_path, executable="x" * (MAX_FIELD_BYTES + 1))

    with pytest.raises(HandoffError, match="longer than an update descriptor carries"):
        transaction.to_bytes()


@requires_posix_modes
def test_a_descriptor_is_written_privately_and_read_back(tmp_path: Path) -> None:
    transaction = _native(tmp_path)
    path = tmp_path / "descriptor"

    write_descriptor(path, transaction)

    assert read_descriptor(path) == transaction
    assert path.stat().st_mode & 0o777 == 0o600


@requires_posix_modes
def test_the_helper_is_copied_outside_the_installation_and_proved(tmp_path: Path) -> None:
    source = tmp_path / "install" / "hanly-update-posix"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"a native program")

    copy = install_native_helper(source, tmp_path / "state" / "hanly-update-posix")

    assert copy.read_bytes() == b"a native program"
    assert copy.stat().st_mode & 0o777 == 0o700
    assert copy.parent != source.parent


def test_the_pointer_a_recovery_run_follows_survives_the_installation(
    tmp_path: Path,
) -> None:
    state = tmp_path / "state"
    descriptor = tmp_path / "apps" / ".hanly-update-t1" / "descriptor"

    record_native_pending(state, descriptor)

    assert native_pending(state) == descriptor
    clear_native_pending(state)
    assert native_pending(state) is None


def test_a_result_the_helper_never_wrote_reads_as_no_result(tmp_path: Path) -> None:
    result = tmp_path / "result"

    assert read_native_result(result) is None

    result.write_text("something else\n", encoding="utf-8")
    assert read_native_result(result) is None

    result.write_text("committed\nHanly 0.5.3 started.\n", encoding="utf-8")
    assert read_native_result(result) == ("committed", "Hanly 0.5.3 started.")


@pytest.mark.skipif(sys.platform.startswith("win32"), reason="POSIX advisory locking")
def test_the_shell_waits_until_the_helper_genuinely_holds_the_lock(
    tmp_path: Path,
) -> None:
    import fcntl

    lock = tmp_path / "native-lock"
    handle = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        await_native_claim(lock, timeout=1.0)
    finally:
        os.close(handle)

    with pytest.raises(HandoffError, match="did not start"):
        await_native_claim(lock, timeout=0.5)


@pytest.mark.skipif(sys.platform.startswith("win32"), reason="POSIX advisory locking")
def test_a_live_helper_is_observed_through_the_lock_it_actually_holds(
    tmp_path: Path,
) -> None:
    """Settlement asks this before starting a recovery helper, so it has to
    answer from the lock itself rather than from anything a helper wrote."""

    import fcntl

    lock = tmp_path / "native-lock"

    assert not native_helper_is_running(lock)

    handle = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert native_helper_is_running(lock)
    finally:
        os.close(handle)

    assert not native_helper_is_running(lock)
