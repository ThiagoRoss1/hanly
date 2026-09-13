"""Two compiled builds, a real script, and the swap that replaces one with the other.

The rendered body of an update script proves nothing about what a shell does
with it, so every executing case builds a throwaway old and new program, runs
the production script over them, and reads back which one was started. The
scaffolding lives here because the Windows-only and macOS-only rollbacks need
exactly the same two builds as the shared cases.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from time import monotonic, sleep

from hanly_app.app_update import APPLICATION_STEM, BUNDLE_NAME
from hanly_app.app_update_handoff import (
    EXIT_WAIT_SECONDS,
    READY_WAIT_SECONDS,
    UpdateTransaction,
    _write_handoff_script,
    handoff_arguments,
    render_handoff_script,
)

from .capabilities import unavailable

NEW_VERSION = "0.2.0"

#: Bounded so an unlaunched build fails the test instead of hanging it.
LAUNCH_WAIT_SECONDS = 60.0

#: What each platform's installation is called, and the program inside it.
MACOS_PROGRAM = f"Contents/MacOS/{APPLICATION_STEM}"

#: What the host's own compiler driver calls the program it produces.
PROGRAM_SUFFIX = ".exe" if sys.platform == "win32" else ""


#: ``LINGER_SECONDS`` is how long the build stays alive after reporting, which
#: is what makes it a build the handoff has to stop rather than one that has
#: already let go of the directory it was started from.
PROBE_SOURCE = """
#include <stdio.h>
#include <string.h>
#ifdef _WIN32
#include <windows.h>
#else
#include <unistd.h>
#endif

int main(int argc, char **argv) {
    FILE *log = fopen(LOG, "a");
    if (log) { fprintf(log, "%s\\n", IDENTITY); fclose(log); }
    for (int index = 1; index + 1 < argc; index++) {
        if (strcmp(argv[index], "--update-ready") == 0) {
            FILE *ready = fopen(argv[index + 1], "w");
            if (ready) { fputs(VERSION, ready); fclose(ready); }
        }
    }
#ifdef _WIN32
    if (LINGER_SECONDS > 0) { Sleep(LINGER_SECONDS * 1000); }
#else
    if (LINGER_SECONDS > 0) { sleep(LINGER_SECONDS); }
#endif
    return 0;
}
"""


#: Which handoff variants this host can actually execute. macOS runs its own
#: and Linux's: the Linux body is plain POSIX shell that execs the program at
#: the final path, which a macOS host runs identically. Only the ``open``
#: relaunch is Darwin-specific, and only Windows needs a Windows host.
HANDOFF_VARIANTS = ["linux"] if sys.platform != "win32" else ["win32"]
if sys.platform == "darwin":
    HANDOFF_VARIANTS.insert(0, "darwin")


@dataclass
class Handoff:
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

        deadline = monotonic() + LAUNCH_WAIT_SECONDS
        while self.launched != expected and monotonic() < deadline:
            sleep(0.1)
        return self.launched


def transaction_for(
    install_root: Path,
    *,
    version: str = NEW_VERSION,
    ready_root: Path | None = None,
) -> UpdateTransaction:
    directory = install_root.parent / ".hanly-update-probe"
    directory.mkdir(parents=True, exist_ok=True)
    return UpdateTransaction(
        directory=directory,
        install_root=install_root,
        staged_path=directory / install_root.name,
        backup_path=directory / "previous",
        ready_path=(ready_root or directory) / "ready",
        version=version,
    )


def c_string(value: object) -> str:
    """Quote a value as a C string literal.

    A Windows path is full of backslashes, so a macro expanding to
    ``"C:\\Users\\runneradmin\\..."`` is a string of escape sequences rather
    than a path -- and ``\\U`` is not even a valid one, which is how this
    first failed to compile on the Windows runner.
    """

    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def _compile(
    source: Path,
    program: Path,
    *,
    identity: str,
    version: str,
    log: Path,
    linger: int = 0,
) -> None:
    """Build one probe beside its source, then put it where it belongs.

    The compiler only ever sees the probe directory, which is ASCII: binutils
    takes ``argv`` through the Windows ANSI code page, so an output path
    containing Hangul reaches ``ld`` as ``?? ????`` and cannot be opened.
    Moving the finished program to an installation path the handoff is
    supposed to cope with is Python's job, and Python has no such limit.
    """

    built = source.parent / f"probe-{identity}{PROGRAM_SUFFIX}"
    command = [
        str(COMPILER),
        f"-DIDENTITY={c_string(identity)}",
        f"-DVERSION={c_string(version)}",
        f"-DLINGER_SECONDS={linger}",
        # Forward slashes: every Windows CRT accepts them, and they leave the
        # macro with nothing left to escape.
        f"-DLOG={c_string(log.as_posix())}",
        "-o",
        str(built),
        str(source),
    ]
    finished = subprocess.run(command, capture_output=True, timeout=120)
    if finished.returncode != 0:
        # Without this the failure is a bare CalledProcessError and the
        # compiler's own explanation is thrown away.
        raise AssertionError(
            "could not compile the update probe\n"
            f"command: {' '.join(command)}\n"
            f"stderr:\n{finished.stderr.decode('utf-8', 'replace')}"
        )

    program.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(built, program)


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


def prepare_handoff(
    tmp_path: Path,
    platform: str,
    *,
    new_version: str = NEW_VERSION,
    probe_root: Path | None = None,
    linger: int = 0,
) -> Handoff:
    """Build an old installation, a staged replacement, and the real script.

    ``probe_root`` is where the probe's own two files live: the program's log
    and the readiness file it writes. It is separate from ``tmp_path`` so the
    installation under test can carry spaces and Hangul while the C probe --
    which receives paths through a compile-time macro and an ANSI ``argv`` on
    Windows -- only ever handles ASCII. What the handoff renames, relaunches
    and cleans up is still the awkward path.
    """

    _require_a_compiler()
    tmp_path.mkdir(parents=True, exist_ok=True)
    probes = probe_root or tmp_path
    probes.mkdir(parents=True, exist_ok=True)
    source = probes / "probe.c"
    source.write_text(PROBE_SOURCE, encoding="ascii")
    log = probes / "launched.txt"

    darwin = platform == "darwin"
    name = BUNDLE_NAME if darwin else APPLICATION_STEM
    # The name the layout really carries on this platform, so the swap under
    # test relaunches exactly what a shipped update would.
    inside = MACOS_PROGRAM if darwin else f"{APPLICATION_STEM}{PROGRAM_SUFFIX}"

    install_root = tmp_path / "install" / name
    transaction = transaction_for(install_root, ready_root=probes)
    for root, identity, version, stays in (
        (install_root, "old", "0.1.0", 0),
        (transaction.staged_path, "new", new_version, linger),
    ):
        _compile(
            source, root / inside, identity=identity, version=version, log=log, linger=stays
        )
        if darwin:
            _macos_bundle(root)

    return Handoff(
        transaction,
        log,
        _script(tmp_path, executable=inside, platform=platform),
        install_root / inside,
    )


#: Ten minutes is the right bound for a frozen build on a cold start and the
#: wrong one for a test, so the two waits are shortened in the copy that runs
#: here. Their presence in the shipped body is asserted by the portable suite.
def _script(tmp_path: Path, *, executable: str, platform: str) -> Path:
    body = render_handoff_script(executable=executable, platform=platform)
    for bound in (EXIT_WAIT_SECONDS, READY_WAIT_SECONDS):
        assert body.count(str(bound)) == 1, body
        body = body.replace(str(bound), "8")

    # The production writer owns encoding, line endings and mode. Restating
    # them here would let this suite stay green while the real one regressed.
    return _write_handoff_script(body, platform=platform, directory=tmp_path)


def run_handoff(handoff: Handoff, *, expect_status: int) -> Handoff:
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


def _builds_programs(compiler: str) -> bool:
    """Answer whether a compiler on PATH can in fact produce a program.

    Being on PATH is not the same as working: an MSYS2 ``cc`` whose ``cc1``
    cannot load its own libraries exits non-zero with an empty stderr, which
    would otherwise fail every test below with nothing to go on.
    """

    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "usable.c"
        source.write_text("int main(void) { return 0; }\n", encoding="ascii")
        try:
            finished = subprocess.run(
                [compiler, "-o", str(source.with_suffix(PROGRAM_SUFFIX or ".out")), str(source)],
                capture_output=True,
                timeout=120,
            )
        except OSError:
            return False
    return finished.returncode == 0


#: The two builds being swapped are compiled rather than scripted: macOS
#: refuses to ``open`` a bundle whose executable is a shell script, and Windows
#: needs a real executable to ``Start-Process``. Named explicitly so a host
#: without a working one says so, rather than failing on a missing or broken
#: ``cc``.
COMPILER = next(
    (
        found
        for name in ("cc", "clang", "gcc")
        if (found := shutil.which(name)) and _builds_programs(found)
    ),
    None,
)


def _require_a_compiler() -> None:
    """Refuse to pretend a host without a compiler checked the swap.

    Called from :func:`prepare_handoff` rather than declared as a marker, so
    every case -- including the two platform-specific rollbacks -- inherits it
    without repeating it, and a required native job fails instead of skipping.
    """

    if COMPILER is None:
        unavailable(
            "the handoff cases compile the builds they swap; "
            "no cc, clang, or gcc on PATH"
        )


def with_dead_pid(handoff: Handoff) -> list[str]:
    """The handoff's own arguments, with a pid that has already exited."""

    arguments = handoff_arguments(handoff.transaction)
    arguments[0] = _dead_pid()
    return arguments


def assert_identity(handoff: Handoff, expected: str) -> None:
    """Run whatever is at the installation path and see which build answers."""

    before = len(handoff.launched)
    subprocess.run([str(handoff.program)], check=True, timeout=60)

    assert handoff.launched[before:] == [expected]


__all__ = [
    "HANDOFF_VARIANTS",
    "LAUNCH_WAIT_SECONDS",
    "MACOS_PROGRAM",
    "NEW_VERSION",
    "PROBE_SOURCE",
    "COMPILER",
    "PROGRAM_SUFFIX",
    "Handoff",
    "assert_identity",
    "c_string",
    "prepare_handoff",
    "run_handoff",
    "transaction_for",
    "with_dead_pid",
]
