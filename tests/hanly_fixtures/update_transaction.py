"""A disposable installation, a real transaction, and the real helper over it.

The helper is a PowerShell program that moves files inside a directory Windows
is holding open. Nothing about that is provable from the rendered text, so every
case here builds two compiled programs, stages a transaction through the
production journal, and runs the shipped script over the result.

The installation under test is built from scratch in ``tmp_path``. Nothing
outside it is read or written, and the user's own installation is never a
subject: the point is a Hanly-shaped tree, not this machine's Hanly.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from time import monotonic, sleep

from hanly_app.app_inventory import file_digest, write_installed_manifest
from hanly_app.app_manifest import (
    BuildIdentity,
    FileEntry,
    InstallManifest,
    content_fingerprint,
)
from hanly_app.app_update_helper import (
    EXIT_WAIT_SECONDS,
    HELPER_SCRIPT_NAME,
    READY_WAIT_SECONDS,
    render_helper_script,
)
from hanly_app.app_update_journal import (
    JournalOperation,
    TransactionPlan,
    UpdateJournal,
)

from .update_handoff import PROGRAM_SUFFIX, _compile, c_string  # noqa: F401

OLD_VERSION = "0.5.0"
NEW_VERSION = "0.5.1"

PROGRAM_NAME = f"hanly-desktop{PROGRAM_SUFFIX}"

#: Shortened from the shipped bounds so a case that never settles fails rather
#: than holding the suite for ten minutes. The shipped values are asserted by
#: the portable suite instead.
TEST_EXIT_WAIT = 20
TEST_READY_WAIT = 25

#: How long a case waits for the detached helper to reach an outcome.
SETTLE_WAIT_SECONDS = 120.0


@dataclass
class Installation:
    """One built installation, and the transaction waiting to change it."""

    root: Path
    journal: UpdateJournal
    script: Path
    log: Path

    @property
    def program(self) -> Path:
        return self.root / PROGRAM_NAME

    def read(self, relative: str) -> str | None:
        path = self.root.joinpath(*relative.split("/"))
        return path.read_text(encoding="utf-8") if path.is_file() else None

    def digest(self, relative: str) -> str | None:
        path = self.root.joinpath(*relative.split("/"))
        return file_digest(path)[0] if path.is_file() else None

    @property
    def launched(self) -> list[str]:
        return self.log.read_text(encoding="utf-8").split() if self.log.exists() else []

    def await_outcome(self, timeout: float = SETTLE_WAIT_SECONDS) -> dict[str, object]:
        """Wait for the detached helper to write its settled result."""

        deadline = monotonic() + timeout
        while monotonic() < deadline:
            result = self.journal.read_result()
            if result is not None:
                sleep(0.5)
                return result
            sleep(0.25)
        raise AssertionError(
            "the update helper never settled; progress was "
            f"{self.journal.records()!r}"
        )


def build_installation(
    tmp_path: Path,
    probe_root: Path,
    *,
    new_version: str = NEW_VERSION,
    reported_version: str | None = None,
    linger: int = 0,
) -> Installation:
    """Build an old installation and stage a real transaction over it.

    ``reported_version`` is what the replacement claims through
    ``--update-ready``. Making it differ from the version being installed is how
    a case gets a build that starts and is still rejected.
    """

    probe_root.mkdir(parents=True, exist_ok=True)
    source = probe_root / "probe.c"
    source.write_text(_PROBE_SOURCE, encoding="ascii")
    log = probe_root / "launched.txt"

    root = tmp_path / "install" / "hanly-desktop"
    _compile(source, root / PROGRAM_NAME, identity="old", version=OLD_VERSION, log=log)
    (root / "_internal").mkdir(parents=True, exist_ok=True)
    (root / "_internal" / "unchanged.txt").write_text("stays\n", encoding="utf-8")
    (root / "_internal" / "dropped.txt").write_text("goes\n", encoding="utf-8")

    base = _manifest(root, OLD_VERSION)
    write_installed_manifest(root, base)

    staging = tmp_path / "staged"
    _compile(
        source,
        staging / PROGRAM_NAME,
        identity="new",
        version=reported_version or new_version,
        log=log,
        linger=linger,
    )
    added = staging / "added.txt"
    added.write_text("new file\n", encoding="utf-8")

    journal = _stage(tmp_path, root, base, new_version, staging, added)
    return Installation(root=root, journal=journal, script=_script(journal), log=log)


def run_helper(installation: Installation, *, recover: bool = False) -> None:
    """Start the shipped helper over a staged transaction, detached."""

    command = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(installation.script),
        "-Transaction",
        str(installation.journal.directory),
        "-Quiet",
    ]
    if recover:
        command.append("-Recover")
    subprocess.Popen(command, cwd=installation.script.parent, close_fds=True)


def _stage(
    tmp_path: Path,
    root: Path,
    base: InstallManifest,
    new_version: str,
    staging: Path,
    added: Path,
) -> UpdateJournal:
    """Write the journal and payload the helper will act on.

    The production journal writes all of it: a fixture that laid out its own
    directory would keep passing after the real layout changed.
    """

    program_digest, program_size = file_digest(staging / PROGRAM_NAME)
    added_digest, added_size = file_digest(added)
    operations = (
        JournalOperation(
            index=1,
            kind="add",
            path="_internal/added.txt",
            target_sha256=added_digest,
            target_size=added_size,
        ),
        JournalOperation(
            index=2,
            kind="replace",
            path=PROGRAM_NAME,
            target_sha256=program_digest,
            target_size=program_size,
            current_sha256=base.entries[PROGRAM_NAME].sha256,
        ),
        JournalOperation(index=3, kind="delete", path="_internal/dropped.txt"),
    )

    journal = UpdateJournal(root / ".hanly-update" / "t-probe")
    journal.prepare(
        TransactionPlan(
            transaction_id="t-probe",
            install_root=root,
            executable=PROGRAM_NAME,
            target=_identity(new_version, "1" * 16),
            base=base.identity,
            operations=operations,
            recovery_root=tmp_path / "recovery",
            created=0.0,
        )
    )
    (staging / PROGRAM_NAME).replace(journal.payload_for(operations[1]))
    added.replace(journal.payload_for(operations[0]))
    return journal


def _manifest(root: Path, version: str) -> InstallManifest:
    entries = [
        FileEntry(path=relative, sha256=digest, size=size)
        for relative, digest, size in (
            (name, *file_digest(root.joinpath(*name.split("/"))))
            for name in (PROGRAM_NAME, "_internal/unchanged.txt", "_internal/dropped.txt")
        )
    ]
    return InstallManifest.from_entries(_identity(version, content_fingerprint(entries)), entries)


def _identity(version: str, build_id: str) -> BuildIdentity:
    return BuildIdentity(
        product="hanly-desktop",
        platform="windows",
        architecture="x86_64",
        version=version,
        build_id=build_id,
    )


def _script(journal: UpdateJournal) -> Path:
    """Write the shipped helper with only its two waits shortened."""

    body = render_helper_script()
    for shipped, shortened in (
        (EXIT_WAIT_SECONDS, TEST_EXIT_WAIT),
        (READY_WAIT_SECONDS, TEST_READY_WAIT),
    ):
        assert body.count(f"AddSeconds({shipped})") == 1, body
        body = body.replace(f"AddSeconds({shipped})", f"AddSeconds({shortened})")

    script = journal.directory / HELPER_SCRIPT_NAME
    script.write_text(body, encoding="utf-8-sig", newline="\r\n")
    return script


#: The replacement has to be a real program: the helper starts it with
#: ``Start-Process`` and waits for it to write a readiness file, which a text
#: file cannot do. ``LINGER_SECONDS`` keeps a rejected build holding the
#: installation open, which is the state a rollback has to cope with.
_PROBE_SOURCE = """
#include <stdio.h>
#include <string.h>
#include <windows.h>

int main(int argc, char **argv) {
    FILE *log = fopen(LOG, "a");
    if (log) { fprintf(log, "%s\\n", IDENTITY); fclose(log); }
    for (int index = 1; index + 1 < argc; index++) {
        if (strcmp(argv[index], "--update-ready") == 0) {
            FILE *ready = fopen(argv[index + 1], "w");
            if (ready) { fputs(VERSION, ready); fclose(ready); }
        }
    }
    if (LINGER_SECONDS > 0) { Sleep(LINGER_SECONDS * 1000); }
    return 0;
}
"""


__all__ = [
    "NEW_VERSION",
    "OLD_VERSION",
    "PROGRAM_NAME",
    "SETTLE_WAIT_SECONDS",
    "TEST_EXIT_WAIT",
    "TEST_READY_WAIT",
    "Installation",
    "append_operation",
    "build_installation",
    "run_helper",
]


def append_operation(
    installation: Installation, relative: str, payload: Path
) -> None:
    """Add one replacement to a staged transaction, through the real plan.

    The journal is written once and read by the helper, so a case that needs a
    fourth operation rewrites the plan rather than reaching past it.
    """

    plan = installation.journal.read_plan()
    digest, size = file_digest(payload)
    operation = JournalOperation(
        index=len(plan.operations) + 1,
        kind="replace",
        path=relative,
        target_sha256=digest,
        target_size=size,
    )
    payload.replace(installation.journal.payload_for(operation))
    installation.journal.prepare(
        TransactionPlan(
            transaction_id=plan.transaction_id,
            install_root=plan.install_root,
            executable=plan.executable,
            target=plan.target,
            base=plan.base,
            operations=(*plan.operations, operation),
            recovery_root=plan.recovery_root,
            created=plan.created,
        )
    )
