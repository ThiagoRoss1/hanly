"""Hand updates to a helper that outlives Hanly and waits for its exit.

Keep the old install until the swapped-in build reports readiness. Schema-2 POSIX
helpers provide durability, exact process identity, and locking; Python writes a
fixed descriptor and an external helper copy confirms ownership. Transaction
paths beside the install remain under owned cleanup.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: The internal argument the relaunched build answers with its own version.
READY_ARGUMENT = "--update-ready"

#: How long the handoff waits for Hanly to exit, and how long it then retries a
#: Windows directory rename a lingering lock is still refusing.
EXIT_WAIT_SECONDS = 120
SWAP_ATTEMPTS = 30

#: Match the packaged UI smoke's cold-start allowance; a shorter deadline
#: could roll back a working build during model and Qt initialization.
READY_WAIT_SECONDS = 600

Spawn = Callable[[list[str], Path], None]


class HandoffError(RuntimeError):
    """Raised when the native swap cannot be started."""


@dataclass(frozen=True, slots=True)
class UpdateTransaction:
    """One staged replacement, and every path the swap is allowed to touch.

    ``directory`` is owned by this transaction alone; the handoff removes it
    whole once the outcome is settled, which is the only cleanup there is.
    """

    directory: Path
    install_root: Path
    staged_path: Path
    backup_path: Path
    ready_path: Path
    version: str


def start_handoff(
    transaction: UpdateTransaction,
    *,
    executable: str,
    platform: str = sys.platform,
    spawn: Spawn | None = None,
) -> None:
    """Write the swap script somewhere disposable and start it detached.

    The script lives outside the transaction directory it deletes, so removing
    that directory is never a script removing the ground it stands on.
    """

    script = _write_script(executable=executable, platform=platform)
    runner = spawn if spawn is not None else spawn_detached
    try:
# Launch from the temp root, not the script directory; inherited working
# directories remain held open and would prevent cleanup.
        runner(
            [*_launcher(platform, script), *handoff_arguments(transaction)],
            script.parent.parent,
        )
    except OSError as error:
        raise HandoffError(f"could not start the update handoff: {error}") from error


def handoff_arguments(transaction: UpdateTransaction) -> list[str]:
    """Return the values the script reads, in the order it reads them.

    Paths cross as arguments rather than as text rendered into the script: a
    generated body is where a shell picks up both injection and code-page
    corruption of a non-ASCII installation path.
    """

    return [
        str(os.getpid()),
        str(transaction.install_root),
        str(transaction.staged_path),
        str(transaction.backup_path),
        str(transaction.ready_path),
        transaction.version,
        str(transaction.directory),
    ]


def render_handoff_script(*, executable: str, platform: str = sys.platform) -> str:
    """Render the swap script, kept separate from spawning so it can be read."""

    if platform.startswith("win32"):
        return _WINDOWS_HANDOFF.format(
            executable=executable,
            exit_wait=EXIT_WAIT_SECONDS,
            attempts=SWAP_ATTEMPTS,
            ready_wait=READY_WAIT_SECONDS,
            ready_argument=READY_ARGUMENT,
        )
    return _POSIX_HANDOFF.format(
        launch=_posix_launch(platform, executable),
        stop=_posix_stop(platform),
        exit_wait=EXIT_WAIT_SECONDS,
        ready_wait=READY_WAIT_SECONDS,
        ready_argument=READY_ARGUMENT,
    )


def spawn_detached(command: list[str], directory: Path) -> None:
    """Start a helper that outlives the parent process it is waiting for.

    On Windows, use NEW_PROCESS_GROUP to isolate console signals and CREATE_NO_WINDOW.
    Avoid DETACHED_PROCESS: PowerShell can exit successfully without running its
    script. Windows children outlive their parent without console detachment.
    """

    if sys.platform.startswith("win32"):
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
            subprocess, "CREATE_NO_WINDOW", 0
        )
        subprocess.Popen(command, cwd=directory, close_fds=True, creationflags=flags)
        return
    subprocess.Popen(command, cwd=directory, close_fds=True, start_new_session=True)


def _write_handoff_script(body: str, *, platform: str, directory: Path) -> Path:
    """Write one rendered body with the encoding and mode its shell requires.

    PowerShell reads a ``-File`` script as UTF-8 only with a BOM and expects
    ``cmd``-era line endings; a POSIX shell needs the executable bit instead.
    Taking the body as an argument is what lets the tests that execute a real
    swap write their shortened one through this same boundary, rather than
    restating these rules and leaving them unexercised.
    """

    windows = platform.startswith("win32")
    script = directory / ("hanly-update.ps1" if windows else "hanly-update.sh")
    try:
        script.write_text(
            body,
            encoding="utf-8-sig" if windows else "utf-8",
            newline="\r\n" if windows else "\n",
        )
        if not windows:
            script.chmod(0o700)
    except OSError as error:
        raise HandoffError(f"could not write the update handoff: {error}") from error
    return script


def _write_script(*, executable: str, platform: str) -> Path:
    directory = Path(tempfile.mkdtemp(prefix="hanly-update."))
    body = render_handoff_script(executable=executable, platform=platform)
    return _write_handoff_script(body, platform=platform, directory=directory)


def _launcher(platform: str, script: Path) -> list[str]:
    if platform.startswith("win32"):
        return [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-WindowStyle",
            "Hidden",
            "-File",
            str(script),
        ]
    return ["/bin/sh", str(script)]


def _posix_launch(platform: str, executable: str) -> str:
    """Return how one POSIX platform starts an installed Hanly.

    macOS goes through ``open`` so the relaunched build is a registered
    application with a Dock entry and menu bar, which running the program
    inside the bundle directly does not produce. The cost is that no pid comes
    back from it, which is why stopping a rejected build differs by platform
    as well.
    """

    if platform.startswith("darwin"):
        return '/usr/bin/open "$install" --args "$@"'
    return _indented([f'"$install/{executable}" "$@" >/dev/null 2>&1 &', "candidate=$!"])


def _posix_stop(platform: str) -> str:
    """Return how one POSIX platform stops a candidate it is about to reject.

    A backgrounded program is this script's own job, so its pid is exact.
    ``open`` hands back no pid at all - it returns once LaunchServices has been
    asked, and the application it starts is reparented to launchd - so macOS
    has to find the candidate among the running processes instead.
    """

    if platform.startswith("darwin"):
        return _indented([*_macos_candidate_pids(), *_posix_terminate("$candidate")])
    return _indented(_posix_terminate('"$candidate"'))


def _macos_candidate_pids() -> list[str]:
    """Render shell lines collecting macOS PIDs by literal executable path from ps.

    Quoted case patterns avoid pkill regex mismatches for brackets or C++ paths.
    The leading ``(`` is required by bash 3.2's /bin/sh parser; otherwise the pattern's
    ``)`` can terminate its surrounding command substitution.
    """

    return [
        "candidate=$(/bin/ps -axo pid=,comm= | while read -r pid program; do",
        '  case "$program" in ("$install"/*) printf \'%s \' "$pid" ;; esac',
        "done)",
    ]


def _posix_terminate(pids: str) -> list[str]:
    """Return the ask-then-insist stop both POSIX platforms end with.

    macOS passes an unquoted expansion because a bundle answers with every
    process started out of it, which on Hanly is the shell and its two
    children; Linux backgrounds one program and knows its single pid.
    """

    return [
        '[ -n "$candidate" ] || return 0',
        f"kill {pids} 2>/dev/null || return 0",
        "sleep 1",
        f"kill -9 {pids} 2>/dev/null || true",
    ]


def _indented(lines: list[str]) -> str:
    """Join shell lines for a slot that sits one level inside a function."""

    return "\n  ".join(lines)


_POSIX_HANDOFF = """#!/bin/sh
# Hanly update handoff. Started detached by the build it replaces.
set -u

old_pid="$1"
install="$2"
staged="$3"
backup="$4"
ready="$5"
version="$6"
transaction="$7"

candidate=""

launch() {{
  {launch}
}}

# Stop a rejected candidate before restoring the previous build. POSIX would
# otherwise rename its live directory and leave two Hanly processes running.
stop_candidate() {{
  {stop}
}}

# The transaction directory holds the staged build, the previous build, and
# the readiness file, so one removal is the whole cleanup. The script deletes
# itself last; it lives outside that directory for exactly this reason.
finish() {{
  rm -rf "$transaction"
  rm -f "$0"
}}

waited=0
while kill -0 "$old_pid" 2>/dev/null; do
  if [ "$waited" -ge {exit_wait} ]; then
    finish
    exit 1
  fi
  waited=$((waited + 1))
  sleep 1
done

mv "$install" "$backup" || {{ finish; exit 1; }}
if ! mv "$staged" "$install"; then
  mv "$backup" "$install" || exit 1
  launch
  finish
  exit 1
fi

launch {ready_argument} "$ready"

waited=0
while [ "$waited" -lt {ready_wait} ]; do
  if [ -f "$ready" ] && [ "x$(cat "$ready" 2>/dev/null)" = "x$version" ]; then
    finish
    exit 0
  fi
  waited=$((waited + 1))
  sleep 1
done

# Move the failed candidate aside before restoring the known-good build.
# If restore fails, preserve the transaction and its only working backup.
stop_candidate
mv "$install" "$transaction/rejected" || exit 1
mv "$backup" "$install" || exit 1
launch
finish
exit 1
"""


_WINDOWS_HANDOFF = """param(
  [Parameter(Mandatory = $true)][int]$OldProcessId,
  [Parameter(Mandatory = $true)][string]$Install,
  [Parameter(Mandatory = $true)][string]$Staged,
  [Parameter(Mandatory = $true)][string]$Backup,
  [Parameter(Mandatory = $true)][string]$Ready,
  [Parameter(Mandatory = $true)][string]$Version,
  [Parameter(Mandatory = $true)][string]$Transaction
)

$ErrorActionPreference = 'Stop'
$program = Join-Path $Install '{executable}'

# PowerShell's -ArgumentList does not quote paths containing spaces, so quote
# the relaunch path explicitly; later rollback handles a failed relaunch.
function Start-Hanly {{
  param([string]$Arguments = '')

  $options = @{{ FilePath = $program; WorkingDirectory = $Install; PassThru = $true }}
  if ($Arguments -ne '') {{ $options['ArgumentList'] = $Arguments }}
  try {{
    return Start-Process @options
  }} catch {{
    return $null
  }}
}}

# Windows cannot rename a running build's directory. Stop the rejected
# candidate before restoring the previous installation.
function Stop-Hanly {{
  param($Started)

  if ($null -eq $Started) {{ return }}
  try {{
    Stop-Process -InputObject $Started -Force -ErrorAction SilentlyContinue
  }} catch {{
  }}
}}

# The transaction directory holds the staged build, the previous build, and the
# readiness file, so one removal is the whole cleanup. This script lives in the
# temporary directory instead, and goes with it.
function Complete-Handoff {{
  Remove-Item -LiteralPath $Transaction -Recurse -Force -ErrorAction SilentlyContinue
  Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
}}

$deadline = (Get-Date).AddSeconds({exit_wait})
while (Get-Process -Id $OldProcessId -ErrorAction SilentlyContinue) {{
  if ((Get-Date) -ge $deadline) {{ Complete-Handoff; exit 1 }}
  Start-Sleep -Seconds 1
}}

# Windows keeps a directory locked for a moment after the process holding its
# executable exits, so the first rename is retried rather than trusted once.
$moved = $false
for ($attempt = 0; $attempt -lt {attempts}; $attempt++) {{
  try {{
    [System.IO.Directory]::Move($Install, $Backup)
    $moved = $true
    break
  }} catch {{
    Start-Sleep -Seconds 1
  }}
}}
if (-not $moved) {{ Complete-Handoff; exit 1 }}

try {{
  [System.IO.Directory]::Move($Staged, $Install)
}} catch {{
  try {{ [System.IO.Directory]::Move($Backup, $Install) }} catch {{ exit 1 }}
  Start-Hanly | Out-Null
  Complete-Handoff
  exit 1
}}

$candidate = Start-Hanly ('{ready_argument} \"' + $Ready + '\"')

$deadline = (Get-Date).AddSeconds({ready_wait})
while ((Get-Date) -lt $deadline) {{
  if (Test-Path -LiteralPath $Ready) {{
    $reported = (Get-Content -LiteralPath $Ready -Raw -ErrorAction SilentlyContinue)
    if ($null -ne $reported -and $reported.Trim() -ceq $Version) {{
      Complete-Handoff
      exit 0
    }}
  }}
  Start-Sleep -Seconds 1
}}

        # Restore the known-good build. Rename instead of deleting so a partial
        # removal cannot strand the installation; retry until Windows releases it.
Stop-Hanly $candidate

$aside = $false
for ($attempt = 0; $attempt -lt {attempts}; $attempt++) {{
  try {{
    [System.IO.Directory]::Move($Install, (Join-Path $Transaction 'rejected'))
    $aside = $true
    break
  }} catch {{
    Start-Sleep -Seconds 1
  }}
}}
if (-not $aside) {{ exit 1 }}

try {{
  [System.IO.Directory]::Move($Backup, $Install)
}} catch {{
  exit 1
}}
Start-Hanly | Out-Null
Complete-Handoff
exit 1
"""


# Schema 2 uses a native helper for durable renames, process identity, and a
# persistent lock. It reads only the fixed descriptor below.

#: The helper's own name, wherever it is built, shipped, or copied to.
NATIVE_HELPER_NAME = "hanly-update-posix"

#: The descriptor's wire format. Both sides carry the same field list in the
#: same order; a descriptor with any other count is refused rather than read as
#: far as the two happen to agree.
DESCRIPTOR_MAGIC = b"HANLYUPD"
DESCRIPTOR_VERSION = 1
MAX_DESCRIPTOR_BYTES = 64 * 1024
MAX_FIELD_BYTES = 4096

DESCRIPTOR_FIELDS = (
    "transaction_id",
    "lock_path",
    "install_path",
    "staging_path",
    "candidate_path",
    "backup_path",
    "rejected_path",
    "result_path",
    "ack_path",
    "challenge_path",
    "expected",
    "executable",
    "launch",
    "parent_pid",
    "exit_timeout",
    "ready_timeout",
    "install_device",
    "install_inode",
    "candidate_device",
    "candidate_inode",
)

#: How the relaunched build is started. macOS goes through LaunchServices so
#: the new Hanly is a registered application; Linux runs the program directly.
LAUNCH_OPEN = "open"
LAUNCH_EXEC = "exec"

#: How long the shell waits for the helper to take the installation's lock.
#: Quitting before it has leaves the candidate with nobody to install it.
NATIVE_CLAIM_SECONDS = 30.0

#: Outcomes the helper writes, in the vocabulary the desktop already reads.
NATIVE_RESULTS = frozenset({"committed", "restored", "recovery-required", "abandoned"})


@dataclass(frozen=True, slots=True)
class NativeTransaction:
    """Everything the native helper is told, and nothing it could infer wrong.

    Device and inode numbers are recorded for both roots because a path is not
    an identity: between this being written and the helper acting, a path is
    exactly the thing that can be made to point somewhere else.
    """

    transaction_id: str
    lock_path: Path
    install_path: Path
    staging_path: Path
    candidate_path: Path
    backup_path: Path
    rejected_path: Path
    result_path: Path
    ack_path: Path
    challenge_path: Path
    expected: str
    executable: str
    launch: str
    parent_pid: int
    exit_timeout: int
    ready_timeout: int
    install_device: int
    install_inode: int
    candidate_device: int
    candidate_inode: int

    def to_bytes(self) -> bytes:
        """Render the descriptor exactly as the native reader parses it."""

        payload = bytearray(DESCRIPTOR_MAGIC)
        payload += DESCRIPTOR_VERSION.to_bytes(4, "big")
        payload += len(DESCRIPTOR_FIELDS).to_bytes(4, "big")
        for name in DESCRIPTOR_FIELDS:
            raw = str(getattr(self, name)).encode("utf-8")
            if b"\0" in raw:
                raise HandoffError(f"{name} cannot appear in an update descriptor")
            if len(raw) > MAX_FIELD_BYTES:
                raise HandoffError(f"{name} is longer than an update descriptor carries")
            payload += len(raw).to_bytes(4, "big")
            payload += raw
        if len(payload) > MAX_DESCRIPTOR_BYTES:
            raise HandoffError("the update descriptor is larger than the helper reads")
        return bytes(payload)

    @classmethod
    def from_bytes(cls, data: bytes) -> NativeTransaction:
        """Read a descriptor back, under the same rules the helper applies."""

        if len(data) > MAX_DESCRIPTOR_BYTES:
            raise HandoffError("the update descriptor is larger than the helper reads")
        if not data.startswith(DESCRIPTOR_MAGIC):
            raise HandoffError("the update descriptor is not one of ours")

        offset = len(DESCRIPTOR_MAGIC)
        version, offset = _read_u32(data, offset)
        count, offset = _read_u32(data, offset)
        if version != DESCRIPTOR_VERSION or count != len(DESCRIPTOR_FIELDS):
            raise HandoffError("the update descriptor was written by a different Hanly")

        values: dict[str, Any] = {}
        for name in DESCRIPTOR_FIELDS:
            length, offset = _read_u32(data, offset)
            if length > MAX_FIELD_BYTES or offset + length > len(data):
                raise HandoffError("the update descriptor ends inside a field")
            values[name] = data[offset : offset + length].decode("utf-8")
            offset += length
        if offset != len(data):
            raise HandoffError("the update descriptor has trailing data")

        return cls(
            transaction_id=values["transaction_id"],
            lock_path=Path(values["lock_path"]),
            install_path=Path(values["install_path"]),
            staging_path=Path(values["staging_path"]),
            candidate_path=Path(values["candidate_path"]),
            backup_path=Path(values["backup_path"]),
            rejected_path=Path(values["rejected_path"]),
            result_path=Path(values["result_path"]),
            ack_path=Path(values["ack_path"]),
            challenge_path=Path(values["challenge_path"]),
            expected=values["expected"],
            executable=values["executable"],
            launch=values["launch"],
            parent_pid=int(values["parent_pid"]),
            exit_timeout=int(values["exit_timeout"]),
            ready_timeout=int(values["ready_timeout"]),
            install_device=int(values["install_device"]),
            install_inode=int(values["install_inode"]),
            candidate_device=int(values["candidate_device"]),
            candidate_inode=int(values["candidate_inode"]),
        )


def launch_mode(platform: str = sys.platform) -> str:
    return LAUNCH_OPEN if platform.startswith("darwin") else LAUNCH_EXEC


def write_descriptor(path: Path, transaction: NativeTransaction) -> Path:
    """Write the descriptor privately, and make it durable before it is used."""

    payload = transaction.to_bytes()
    try:
        handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as error:
        raise HandoffError(f"could not write the update descriptor: {error}") from error
    return path


def read_descriptor(path: Path) -> NativeTransaction:
    """Read a descriptor back, which is how its round trip is held to account."""

    try:
        if path.is_symlink() or not path.is_file():
            raise HandoffError(f"{path} is not an update descriptor")
        return NativeTransaction.from_bytes(path.read_bytes())
    except OSError as error:
        raise HandoffError(f"could not read the update descriptor: {error}") from error


def install_native_helper(source: Path, destination: Path) -> Path:
    """Copy the helper somewhere outside the installation, and prove the copy.

    The installation is briefly absent between the two renames, so the program
    doing the renaming cannot live inside it. The copy is compared against the
    original byte for byte before anything is handed to it.
    """

    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = source.read_bytes()
        destination.write_bytes(payload)
        os.chmod(destination, 0o700)
        if destination.read_bytes() != payload:
            raise HandoffError("the update helper did not copy correctly")
    except OSError as error:
        raise HandoffError(f"could not prepare the update helper: {error}") from error
    return destination


def start_native_helper(
    helper: Path,
    descriptor: Path,
    *,
    recover: bool = False,
    spawn: Spawn | None = None,
) -> None:
    """Start the helper detached, with the descriptor as its only input.

    Arguments, never a rendered script and never a shell: a generated body is
    where an installation path picks up both injection and code-page damage.
    """

    command = [str(helper)]
    if recover:
        command.append("--recover")
    command.append(str(descriptor))
    runner = spawn if spawn is not None else spawn_detached
    try:
        runner(command, descriptor.parent)
    except OSError as error:
        raise HandoffError(f"could not start the update helper: {error}") from error


def await_native_claim(
    lock_path: Path,
    *,
    timeout: float = NATIVE_CLAIM_SECONDS,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Block until the helper holds the installation's lock, then return.

    Ownership is transferred by observation rather than by a file the helper
    writes: the lock is held on an open handle, so a helper that dies releases
    it, and one that has it is genuinely the owner. Nothing has been mutated
    yet - the helper does not touch the installation until this process exits -
    so waiting here is what closes the window, not what opens one.
    """

    deadline = clock() + timeout
    while clock() < deadline:
        if not _lock_is_free(lock_path):
            return
        sleep(0.2)
    raise HandoffError("the update helper did not start; nothing has been changed")


def native_helper_is_running(lock_path: Path) -> bool:
    """Whether a POSIX helper currently owns this installation's update lock.

    The candidate launched by that helper enters normal startup before it
    writes its acknowledgement. Settlement must leave the live owner alone;
    starting a recovery helper in that window creates a second contender for
    the same transaction and reports an interruption that did not happen.
    """

    return not _lock_is_free(lock_path)


def read_native_result(path: Path) -> tuple[str, str] | None:
    """What the helper settled on, if it has settled on anything yet."""

    try:
        if path.is_symlink() or not path.is_file():
            return None
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return None
    if not lines or lines[0] not in NATIVE_RESULTS:
        return None
    return lines[0], lines[1] if len(lines) > 1 else ""


#: The pointer a recovery run follows when Hanly itself will not start.
NATIVE_PENDING_NAME = "pending.json"


def record_native_pending(directory: Path, descriptor: Path) -> Path:
    """Name the transaction a recovery run would settle, outside the installation."""

    path = Path(directory) / NATIVE_PENDING_NAME
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"descriptor": str(descriptor), "at": time.time()}, sort_keys=True),
            encoding="utf-8",
        )
    except OSError as error:
        raise HandoffError(f"could not record the pending update: {error}") from error
    return path


def native_pending(directory: Path) -> Path | None:
    """The descriptor an outstanding transaction left behind, if there is one."""

    try:
        payload = json.loads(
            (Path(directory) / NATIVE_PENDING_NAME).read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    value = payload.get("descriptor") if isinstance(payload, dict) else None
    return Path(value) if isinstance(value, str) and value else None


def clear_native_pending(directory: Path) -> None:
    """Drop the pointer once the transaction it named has settled."""

    try:
        (Path(directory) / NATIVE_PENDING_NAME).unlink(missing_ok=True)
    except OSError:
        pass


def _lock_is_free(path: Path) -> bool:
    """Whether nothing currently holds the installation's advisory lock.

    Imported here rather than at module scope: this module is loaded on Windows
    too, where the Windows helper is what holds a transaction and ``fcntl``
    does not exist.
    """

    import fcntl

    try:
        handle = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError:
        return False
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    else:
        fcntl.flock(handle, fcntl.LOCK_UN)
        return True
    finally:
        os.close(handle)


def _read_u32(data: bytes, offset: int) -> tuple[int, int]:
    if offset + 4 > len(data):
        raise HandoffError("the update descriptor is too short")
    return int.from_bytes(data[offset : offset + 4], "big"), offset + 4


__all__ = [
    "DESCRIPTOR_FIELDS",
    "DESCRIPTOR_MAGIC",
    "DESCRIPTOR_VERSION",
    "EXIT_WAIT_SECONDS",
    "LAUNCH_EXEC",
    "LAUNCH_OPEN",
    "MAX_DESCRIPTOR_BYTES",
    "MAX_FIELD_BYTES",
    "NATIVE_CLAIM_SECONDS",
    "NATIVE_HELPER_NAME",
    "NATIVE_PENDING_NAME",
    "NATIVE_RESULTS",
    "READY_ARGUMENT",
    "READY_WAIT_SECONDS",
    "HandoffError",
    "NativeTransaction",
    "UpdateTransaction",
    "await_native_claim",
    "clear_native_pending",
    "handoff_arguments",
    "native_pending",
    "install_native_helper",
    "launch_mode",
    "native_helper_is_running",
    "read_descriptor",
    "read_native_result",
    "record_native_pending",
    "render_handoff_script",
    "spawn_detached",
    "start_handoff",
    "start_native_helper",
    "write_descriptor",
]
