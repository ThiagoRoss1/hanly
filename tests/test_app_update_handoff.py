"""The native swap, run for real on the platform it is written for.

A rendered script proves nothing about what a shell does with it. Every test
below that can execute drives the actual handoff against two tiny programs
standing in for the old and new builds, and reads back which one was started.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from time import monotonic, sleep

import pytest
from hanly_app.app_update import APPLICATION_STEM, BUNDLE_NAME
from hanly_app.app_update_handoff import (
    EXIT_WAIT_SECONDS,
    READY_ARGUMENT,
    READY_WAIT_SECONDS,
    UpdateTransaction,
    handoff_arguments,
    render_handoff_script,
    start_handoff,
)

NEW_VERSION = "0.2.0"

#: Bounded so an unlaunched build fails the test instead of hanging it.
_LAUNCH_WAIT_SECONDS = 60.0

#: What each platform's installation is called, and the program inside it.
_WINDOWS_PROGRAM = f"{APPLICATION_STEM}.exe"
_MACOS_PROGRAM = f"Contents/MacOS/{APPLICATION_STEM}"


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

    script = render_handoff_script(executable=_MACOS_PROGRAM, platform="darwin")

    assert '/usr/bin/open "$install" --args' in script
    assert _MACOS_PROGRAM not in script


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


def test_the_script_is_written_outside_the_directory_it_removes(tmp_path: Path) -> None:
    transaction = _transaction(tmp_path / "install")
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


# --- and what a shell actually does with it ----------------------------------


_PROBE_SOURCE = """
#include <stdio.h>
#include <string.h>

int main(int argc, char **argv) {
    FILE *log = fopen(LOG, "a");
    if (log) { fprintf(log, "%s\\n", IDENTITY); fclose(log); }
    for (int index = 1; index + 1 < argc; index++) {
        if (strcmp(argv[index], "--update-ready") == 0) {
            FILE *ready = fopen(argv[index + 1], "w");
            if (ready) { fputs(VERSION, ready); fclose(ready); }
        }
    }
    return 0;
}
"""


#: Which handoff variants this host can actually execute. macOS runs its own
#: and Linux's: the Linux body is plain POSIX shell that execs the program at
#: the final path, which a macOS host runs identically. Only the ``open``
#: relaunch is Darwin-specific, and only Windows needs a Windows host.
_HANDOFF_VARIANTS = ["linux"] if sys.platform != "win32" else ["win32"]
if sys.platform == "darwin":
    _HANDOFF_VARIANTS.insert(0, "darwin")


@dataclass
class _Handoff:
    """One prepared swap, and where its two programs record what happened."""

    transaction: UpdateTransaction
    log: Path
    script: Path
    program: Path

    @property
    def launched(self) -> list[str]:
        text = self.log.read_text(encoding="utf-8") if self.log.exists() else ""
        return text.split()

    def await_launched(self, expected: list[str]) -> list[str]:
        """Wait out an asynchronous relaunch before reading the record.

        ``open`` returns as soon as it has asked for the application; the
        handoff does not wait for it either, so neither the script's exit nor
        its own cleanup means the relaunched build has run yet.
        """

        deadline = monotonic() + _LAUNCH_WAIT_SECONDS
        while self.launched != expected and monotonic() < deadline:
            sleep(0.1)
        return self.launched


def _transaction(install_root: Path, *, version: str = NEW_VERSION) -> UpdateTransaction:
    directory = install_root.parent / ".hanly-update-probe"
    directory.mkdir(parents=True, exist_ok=True)
    return UpdateTransaction(
        directory=directory,
        install_root=install_root,
        staged_path=directory / install_root.name,
        backup_path=directory / "previous",
        ready_path=directory / "ready",
        version=version,
    )


def _compile(source: Path, program: Path, *, identity: str, version: str, log: Path) -> None:
    program.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            str(_COMPILER),
            f'-DIDENTITY="{identity}"',
            f'-DVERSION="{version}"',
            f'-DLOG="{log}"',
            "-o",
            str(program),
            str(source),
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )


def _dead_pid() -> str:
    """Return a pid that has already exited, so the handoff stops waiting."""

    finished = subprocess.Popen([sys.executable, "-c", ""])
    finished.wait()
    return str(finished.pid)


def _macos_bundle(root: Path) -> None:
    """Give a bundle the Info.plist LaunchServices refuses to open without."""

    import plistlib

    (root / "Contents").mkdir(parents=True, exist_ok=True)
    (root / "Contents" / "Info.plist").write_bytes(
        plistlib.dumps(
            {
                "CFBundleExecutable": APPLICATION_STEM,
                "CFBundleIdentifier": f"io.github.thiagoross1.hanly.probe.{root.parent.name}",
                "CFBundleName": "Hanly",
                "CFBundlePackageType": "APPL",
            }
        )
    )


def _prepare(
    tmp_path: Path, platform: str, *, new_version: str = NEW_VERSION
) -> _Handoff:
    """Build an old installation, a staged replacement, and the real script."""

    tmp_path.mkdir(parents=True, exist_ok=True)
    source = tmp_path / "probe.c"
    source.write_text(_PROBE_SOURCE, encoding="ascii")
    log = tmp_path / "launched.txt"

    darwin = platform == "darwin"
    name = BUNDLE_NAME if darwin else APPLICATION_STEM
    inside = _MACOS_PROGRAM if darwin else APPLICATION_STEM

    install_root = tmp_path / "install" / name
    transaction = _transaction(install_root)
    for root, identity, version in (
        (install_root, "old", "0.1.0"),
        (transaction.staged_path, "new", new_version),
    ):
        _compile(source, root / inside, identity=identity, version=version, log=log)
        if darwin:
            _macos_bundle(root)

    return _Handoff(
        transaction,
        log,
        _script(tmp_path, executable=inside, platform=platform),
        install_root / inside,
    )


#: Ten minutes is the right bound for a frozen build on a cold start and the
#: wrong one for a test, so the two waits are shortened in the copy that runs
#: here. Their presence in the shipped body is asserted separately above.
def _script(tmp_path: Path, *, executable: str, platform: str) -> Path:
    body = render_handoff_script(executable=executable, platform=platform)
    for bound in (EXIT_WAIT_SECONDS, READY_WAIT_SECONDS):
        assert body.count(str(bound)) == 1, body
        body = body.replace(str(bound), "8")

    windows = platform == "win32"
    script = tmp_path / ("hanly-update.ps1" if windows else "hanly-update.sh")
    script.write_text(
        body,
        encoding="utf-8-sig" if windows else "utf-8",
        newline="\r\n" if windows else "\n",
    )
    if not windows:
        script.chmod(0o700)
    return script


def _run(handoff: _Handoff, *, expect_status: int) -> _Handoff:
    launcher = (
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
        ]
        if handoff.script.suffix == ".ps1"
        else ["/bin/sh"]
    )
    arguments = handoff_arguments(handoff.transaction)
    arguments[0] = _dead_pid()
    finished = subprocess.run(
        [*launcher, str(handoff.script), *arguments],
        check=False,
        capture_output=True,
        timeout=180,
        cwd=handoff.script.parent,
    )

    assert finished.returncode == expect_status, finished.stderr.decode("utf-8", "replace")
    return handoff


#: The two builds being swapped are compiled rather than scripted: macOS
#: refuses to ``open`` a bundle whose executable is a shell script, and Windows
#: needs a real executable to ``Start-Process``. Named explicitly so a host
#: without one skips with a reason instead of failing on a missing ``cc``.
_COMPILER = next(
    (found for name in ("cc", "clang", "gcc") if (found := shutil.which(name))), None
)

_native = pytest.mark.skipif(
    _COMPILER is None,
    reason="the handoff test compiles the builds it swaps; no cc, clang, or gcc on PATH",
)


@_native
@pytest.mark.parametrize("platform", _HANDOFF_VARIANTS)
def test_a_verified_update_replaces_the_installation_and_cleans_up_after_itself(
    tmp_path: Path, platform: str
) -> None:
    handoff = _run(_prepare(tmp_path, platform), expect_status=0)
    install_root = handoff.transaction.install_root

    assert handoff.await_launched(["new"]) == ["new"]
    assert install_root.is_dir()
    # Nothing of the update survives it: no staged build, no backup, no script.
    assert not handoff.transaction.directory.exists()
    assert not handoff.script.exists()
    assert [item.name for item in install_root.parent.iterdir()] == [install_root.name]


@_native
@pytest.mark.parametrize("platform", _HANDOFF_VARIANTS)
def test_a_new_build_that_never_reports_starting_gives_the_old_one_back(
    tmp_path: Path, platform: str
) -> None:
    """The swap succeeding is not the update succeeding. A build that installs
    and then cannot run would otherwise leave the user with nothing, because the
    only working copy was deleted the moment the rename returned."""

    handoff = _run(_prepare(tmp_path, platform, new_version="9.9.9"), expect_status=1)
    install_root = handoff.transaction.install_root

    assert handoff.await_launched(["new", "old"]) == ["new", "old"]
    assert not handoff.transaction.directory.exists()
    assert [item.name for item in install_root.parent.iterdir()] == [install_root.name]
    _assert_identity(handoff, "old")


@_native
@pytest.mark.parametrize("platform", _HANDOFF_VARIANTS)
def test_a_replacement_that_cannot_be_moved_into_place_relaunches_the_old_build(
    tmp_path: Path, platform: str
) -> None:
    handoff = _prepare(tmp_path, platform)
    shutil.rmtree(handoff.transaction.staged_path)

    _run(handoff, expect_status=1)

    assert handoff.await_launched(["old"]) == ["old"]
    assert not handoff.transaction.directory.exists()
    _assert_identity(handoff, "old")


@pytest.mark.skipif(sys.platform == "win32", reason="the shim replaces a POSIX mv")
@_native
def test_a_rollback_that_itself_fails_launches_nothing_and_keeps_the_backup(
    tmp_path: Path,
) -> None:
    """Neither build is at the installation path, so nothing there is safe to
    start; the previous one stays under the transaction for a person to restore."""

    handoff = _prepare(tmp_path, sys.platform)
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
        ["/bin/sh", str(handoff.script), *_with_dead_pid(handoff)],
        check=False,
        capture_output=True,
        timeout=180,
        env=environment,
    )

    assert finished.returncode == 1, finished.stderr.decode("utf-8", "replace")
    assert handoff.launched == []  # nothing was asked to start, so nothing can arrive
    assert not handoff.transaction.install_root.exists()
    assert handoff.transaction.backup_path.is_dir()


@_native
@pytest.mark.parametrize("platform", _HANDOFF_VARIANTS)
def test_an_installation_path_with_spaces_and_non_ascii_survives_the_handoff(
    tmp_path: Path, platform: str
) -> None:
    handoff = _run(_prepare(tmp_path / "한글 프로그램", platform), expect_status=0)

    assert handoff.await_launched(["new"]) == ["new"]
    _assert_identity(handoff, "new")


def _with_dead_pid(handoff: _Handoff) -> list[str]:
    arguments = handoff_arguments(handoff.transaction)
    arguments[0] = _dead_pid()
    return arguments


def _assert_identity(handoff: _Handoff, expected: str) -> None:
    """Run whatever is at the installation path and see which build answers."""

    before = len(handoff.launched)
    subprocess.run([str(handoff.program)], check=True, timeout=60)

    assert handoff.launched[before:] == [expected]
