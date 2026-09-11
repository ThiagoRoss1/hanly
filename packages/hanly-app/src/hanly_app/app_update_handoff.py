"""The one step of an application update that cannot happen in-process.

A new build has to replace the directory holding the executable and the
interpreter currently running from it, so the last stretch belongs to a small
script that outlives this process: it waits for Hanly to exit, swaps the staged
build in, starts it, and waits for the new build to say it came up. Only then
is the previous build discarded.

Everything the swap touches lives inside one :class:`UpdateTransaction`
directory beside the installation, so finishing - successfully or not - is a
single directory removal rather than a set of fixed names to clean up.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

#: The internal argument the relaunched build answers with its own version.
READY_ARGUMENT = "--update-ready"

#: How long the handoff waits for Hanly to exit, and how long it then retries a
#: Windows directory rename a lingering lock is still refusing.
EXIT_WAIT_SECONDS = 120
SWAP_ATTEMPTS = 30

#: How long the new build has to report that it started. This is the bound the
#: packaged UI smoke already allows a frozen build for the same milestone
#: (``tools/smoke_packaged_runtime.UI_TIMEOUT_SECONDS``): a cold first launch
#: pays for model loading and Qt initialization, and treating a slow start as a
#: failure would roll back a working update.
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
        runner(
            [*_launcher(platform, script), *handoff_arguments(transaction)],
            script.parent,
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
        exit_wait=EXIT_WAIT_SECONDS,
        ready_wait=READY_WAIT_SECONDS,
        ready_argument=READY_ARGUMENT,
    )


def spawn_detached(command: list[str], directory: Path) -> None:
    """Start the handoff so it outlives the process it is waiting for."""

    if sys.platform.startswith("win32"):
        flags = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
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
    inside the bundle directly does not produce.
    """

    if platform.startswith("darwin"):
        return '/usr/bin/open "$install" --args "$@"'
    return f'"$install/{executable}" "$@" >/dev/null 2>&1 &'


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

launch() {{
  {launch}
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

# The new build never reported starting. The previous one is known to work, so
# it goes back. It is moved aside rather than deleted: a removal that fails
# part way through would leave the installation path in pieces with nothing
# yet restored. A restore that itself fails launches nothing and keeps the
# transaction, because its backup is then the only copy of a working Hanly.
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

# ``-ArgumentList`` joins an array with spaces and quotes nothing, so a path
# containing one - which most Windows installation paths do - would reach the
# new build split across several arguments. The line is quoted here instead.
# A relaunch that cannot start never throws: what follows it already handles a
# build that did not come up, and losing the cleanup on the way out does not.
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

# Windows refuses to rename a directory a running program was started from, so
# a build that came up but is being rejected has to be stopped before the
# previous one can go back. Without this the restore fails outright and leaves
# the rejected build installed.
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

# The new build never reported starting. The previous one is known to work, so
# it goes back. It is renamed aside rather than removed: a recursive delete
# that fails part way through would leave the installation path in pieces with
# nothing yet restored, and a rename either happens or does not. The rename is
# retried for the same reason the first one is: stopping a process returns
# before Windows has released the files it held.
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


__all__ = [
    "EXIT_WAIT_SECONDS",
    "READY_ARGUMENT",
    "READY_WAIT_SECONDS",
    "HandoffError",
    "UpdateTransaction",
    "handoff_arguments",
    "render_handoff_script",
    "spawn_detached",
    "start_handoff",
]
