"""What the update handoff script says, before any shell is asked to run it.

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
    EXIT_WAIT_SECONDS,
    READY_ARGUMENT,
    READY_WAIT_SECONDS,
    _write_handoff_script,
    handoff_arguments,
    render_handoff_script,
    start_handoff,
)

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
    assert directory == script.parent
    assert command[-7:] == handoff_arguments(transaction)
