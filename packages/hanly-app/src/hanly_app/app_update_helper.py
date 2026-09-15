"""The Windows helper that applies an in-place update, and can undo it.

The installation holds the executable, the interpreter, and every native
library this process has loaded, so the moment files inside it start moving,
nothing written in Python may still be running. This module renders and starts
the program that takes over at that point.

What it renders is deliberately poor in dependencies: Windows PowerShell and
the .NET Framework that ships with Windows, and nothing else. It must run when
Hanly is stopped, when Hanly is half-replaced, and when Hanly cannot start at
all, so it may not load anything out of the installation it is repairing. A
verified copy is kept outside the installation for exactly the last case.

Correctness comes from the filesystem, not from the record. Every step is
decided by looking at what is actually there - is the backup present, is the
staged file still waiting - so a step interrupted after the move succeeded and
before the journal was appended reaches the same answer on the next run. The
journal bounds the work and drives the progress window; it is not the authority.
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable
from pathlib import Path

from .app_build_identity import PENDING_RECEIPT_NAME, PREVIOUS_RECEIPT_NAME
from .app_update_handoff import HandoffError, Spawn, spawn_detached
from .app_update_journal import EXPECTED_NAME, HELPER_NAME, UpdateJournal
from .owned_cleanup import _process_alive

#: The helper's own name wherever it is written.
HELPER_SCRIPT_NAME = "hanly-update-helper.ps1"

#: What a person can double-click to finish an interrupted update when Hanly
#: itself will not start. It sits beside the helper in the recovery location.
RECOVERY_LAUNCHER_NAME = "Finish Hanly update.cmd"

#: The file naming the transaction a recovery run should settle.
PENDING_NAME = "pending.json"

#: How long the helper waits for Hanly and its children to release the
#: installation, and how long it retries one rename Windows is still refusing.
EXIT_WAIT_SECONDS = 180
MOVE_ATTEMPTS = 30

#: How long the newly installed build has to report that it started. A cold
#: first launch pays for Qt initialization and model loading, and treating a
#: slow start as a failure would roll back a working update.
READY_WAIT_SECONDS = 600

#: How long the shell waits for the helper to acknowledge that it owns the
#: transaction. Quitting before that leaves nobody to apply the update.
CLAIM_WAIT_SECONDS = 30.0

Clock = Callable[[], float]


class HelperError(RuntimeError):
    """Raised when the helper cannot be written, started, or acknowledged."""


def render_helper_script() -> str:
    """Render the helper exactly as it is written to disk.

    Kept separate from writing it so a test can read the body, and so the copy
    in the recovery location and the copy beside a transaction are provably the
    same program.
    """

    return _HELPER.format(
        exit_wait=EXIT_WAIT_SECONDS,
        attempts=MOVE_ATTEMPTS,
        ready_wait=READY_WAIT_SECONDS,
        helper_name=HELPER_NAME,
        expected_name=EXPECTED_NAME,
        pending_receipt=PENDING_RECEIPT_NAME,
        previous_receipt=PREVIOUS_RECEIPT_NAME,
    )


def write_helper(directory: Path) -> Path:
    """Write the helper into a directory, with the encoding PowerShell needs.

    ``-File`` reads a script as UTF-8 only when it carries a byte-order mark,
    and expects ``cmd``-era line endings.
    """

    directory.mkdir(parents=True, exist_ok=True)
    script = directory / HELPER_SCRIPT_NAME
    try:
        script.write_text(render_helper_script(), encoding="utf-8-sig", newline="\r\n")
    except OSError as error:
        raise HelperError(f"could not write the update helper: {error}") from error
    return script


def install_recovery_copy(recovery_root: Path, journal: UpdateJournal) -> Path:
    """Keep a usable helper and a pointer to the transaction outside the app.

    This is what makes an interrupted update recoverable when the installation
    is mid-replacement: the helper here does not live in the tree being changed,
    and the launcher beside it needs no Hanly, no Python, and no network.
    """

    script = write_helper(recovery_root)
    pending = recovery_root / PENDING_NAME
    try:
        pending.write_text(
            json.dumps(
                {"transaction": str(journal.directory), "at": time.time()},
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        (recovery_root / RECOVERY_LAUNCHER_NAME).write_text(
            _RECOVERY_LAUNCHER.format(script=HELPER_SCRIPT_NAME, pending=PENDING_NAME),
            encoding="ascii",
            newline="\r\n",
        )
    except OSError as error:
        raise HelperError(f"could not prepare the recovery location: {error}") from error
    return script


def clear_recovery_copy(recovery_root: Path) -> None:
    """Drop the pointer once the transaction it named is settled."""

    try:
        (recovery_root / PENDING_NAME).unlink(missing_ok=True)
        (recovery_root / RECOVERY_LAUNCHER_NAME).unlink(missing_ok=True)
    except OSError:
        pass


def pending_transaction(recovery_root: Path) -> Path | None:
    """The transaction a recovery run would settle, if one is outstanding."""

    try:
        payload = json.loads((recovery_root / PENDING_NAME).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    value = payload.get("transaction") if isinstance(payload, dict) else None
    return Path(value) if isinstance(value, str) and value else None


def start_helper(
    journal: UpdateJournal,
    recovery_root: Path,
    *,
    spawn: Spawn | None = None,
    recover: bool = False,
) -> None:
    """Write the helper, keep a recovery copy, and start it detached."""

    if sys.platform != "win32" and spawn is None:
        raise HelperError("the in-place update helper is a Windows program")

    script = write_helper(journal.directory)
    install_recovery_copy(recovery_root, journal)

    arguments = [*_launcher(script), "-Transaction", str(journal.directory)]
    if recover:
        arguments.append("-Recover")
    runner = spawn if spawn is not None else spawn_detached
    try:
        runner(arguments, script.parent)
    except (OSError, HandoffError) as error:
        raise HelperError(f"could not start the update helper: {error}") from error


def await_claim(
    journal: UpdateJournal,
    *,
    timeout: float = CLAIM_WAIT_SECONDS,
    clock: Clock = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Block until the helper says it owns the transaction, and return its pid.

    Quitting before this succeeds would leave the staged update with nobody to
    apply it, and the user with an application that closed for no reason.
    """

    deadline = clock() + timeout
    while clock() < deadline:
        claim = journal.helper_claim()
        pid = claim.get("pid") if isinstance(claim, dict) else None
        if isinstance(pid, int) and pid > 0:
            return pid
        sleep(0.2)
    raise HelperError("the update helper did not start; nothing has been changed")


def recover_pending(recovery_root: Path, *, spawn: Spawn | None = None) -> Path | None:
    """Start a recovery run for an outstanding transaction, if there is one."""

    transaction = pending_transaction(recovery_root)
    if transaction is None or not (transaction / "plan.json").is_file():
        clear_recovery_copy(recovery_root)
        return None
    journal = UpdateJournal(transaction)
    if journal.is_settled():
        clear_recovery_copy(recovery_root)
        return None
    start_helper(journal, recovery_root, spawn=spawn, recover=True)
    return transaction


def _launcher(script: Path) -> list[str]:
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


def helper_is_running(pid: int) -> bool:
    """Whether a claimed helper process is still there."""

    if pid <= 0:
        return False
    return _process_alive(pid)


_RECOVERY_LAUNCHER = """@echo off
rem Finish or undo an interrupted Hanly update. Needs nothing but Windows.
setlocal
set "HERE=%~dp0"
for /f "usebackq tokens=* delims=" %%A in (`
  powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
    "(Get-Content -LiteralPath '%HERE%{pending}' -Raw | ConvertFrom-Json).transaction"
`) do set "TRANSACTION=%%A"
if not defined TRANSACTION (
  echo There is no interrupted Hanly update to finish.
  pause
  exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%HERE%{script}" ^
  -Transaction "%TRANSACTION%" -Recover
pause
"""


_HELPER = r"""param(
  [Parameter(Mandatory = $true)][string]$Transaction,
  [switch]$Recover,
  [switch]$Quiet
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

# Everything this script needs is in the transaction directory, which is not
# the directory it is about to change. Reading the plan first is also what
# proves the transaction is one this helper understands.
$planPath = Join-Path $Transaction 'plan.json'
if (-not (Test-Path -LiteralPath $planPath)) {{ exit 2 }}
$plan = Get-Content -LiteralPath $planPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($plan.journal_version -ne 1) {{ exit 2 }}

$install = $plan.install_root
$program = Join-Path $install $plan.executable
$readyPath = Join-Path $Transaction 'ready.txt'
$expectedPath = Join-Path $Transaction '{expected_name}'
$progressPath = Join-Path $Transaction 'progress.jsonl'
$resultPath = Join-Path $Transaction 'result.json'
$payloadRoot = Join-Path $Transaction 'payload'
$backupRoot = Join-Path $Transaction 'backup'
$version = $plan.target.version
$operations = @($plan.operations)

# A schema-2 transaction names a private challenge the new build answers with
# its own identity. A transaction staged by an older Hanly names none, and is
# still committed by the version text it already knows to write.
function Get-PlanValue {{
  param([string]$Name)

  $property = $plan.PSObject.Properties[$Name]
  if ($null -eq $property) {{ return $null }}
  return $property.Value
}}

$challengePath = Get-PlanValue 'challenge'
$receiptPath = Get-PlanValue 'receipt'
$ackPath = $null
if ($challengePath) {{
  $ackPath = [System.IO.Path]::ChangeExtension($challengePath, '.ack')
}}

# .NET's own UTF8 encoding emits a byte-order mark, which every document here
# is read back by something that treats one as content.
$utf8 = New-Object System.Text.UTF8Encoding($false)

# ---------------------------------------------------------------- journal ---

function Write-Record {{
  param([string]$Phase, $Operation = $null, [string]$Detail = '')

  $entry = [ordered]@{{ at = [double]([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() / 1000) }}
  $entry['phase'] = $Phase
  if ($null -ne $Operation) {{ $entry['operation'] = $Operation }}
  if ($Detail) {{ $entry['detail'] = $Detail }}
  $line = ($entry | ConvertTo-Json -Compress)
  $stream = [System.IO.StreamWriter]::new($progressPath, $true, $utf8)
  try {{
    $stream.WriteLine($line)
    $stream.Flush()
  }} finally {{
    $stream.Dispose()
  }}
}}

function Write-Result {{
  param([string]$Outcome, [string]$Detail = '')

  $payload = [ordered]@{{ outcome = $Outcome; detail = $Detail }}
  $payload['at'] = [double]([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() / 1000)
  $text = $payload | ConvertTo-Json
  [System.IO.File]::WriteAllText($resultPath, $text, $utf8)
}}

# ------------------------------------------------------------------ paths ---

# A PyInstaller tree reaches past 260 characters inside its own packages. The
# extended prefix lifts that limit without a machine-wide setting, and disables
# normalization, so only already-absolute paths may be given it.
function Get-ExtendedPath {{
  param([string]$Path)

  if ([string]::IsNullOrEmpty($Path)) {{ return $Path }}
  if ($Path.StartsWith('\\?\')) {{ return $Path }}
  if ($Path.StartsWith('\\')) {{ return '\\?\UNC\' + $Path.Substring(2) }}
  return '\\?\' + $Path
}}

# A manifest path is always forward-slashed, and an extended-length path is
# always backslashed and never normalized, so the two are joined a segment at a
# time rather than by rewriting separators.
function Join-Relative {{
  param([string]$Root, $Relative)

  $path = $Root
  foreach ($part in ([string]$Relative).Split('/')) {{
    if (-not $part) {{ continue }}
    # A recovery run reads a plan off disk; nothing joined here may climb out.
    $unsafe = [System.IO.Path]::GetInvalidFileNameChars()
    if ($part -eq '.' -or $part -eq '..' -or $part.IndexOfAny($unsafe) -ge 0) {{
      throw "unsafe path in the update plan: $Relative"
    }}
    $path = Join-Path $path $part
  }}
  return $path
}}

function Resolve-TransactionPath {{
  param($Relative)

  if (-not $Relative) {{ return $null }}
  return Join-Relative $Transaction $Relative
}}

function Test-FilePresent {{
  param([string]$Path)

  return [System.IO.File]::Exists((Get-ExtendedPath $Path))
}}

function Move-FileWithRetry {{
  param([string]$From, [string]$To)

  $source = Get-ExtendedPath $From
  $target = Get-ExtendedPath $To
  $parent = [System.IO.Path]::GetDirectoryName($target)
  if ($parent -and -not [System.IO.Directory]::Exists($parent)) {{
    [System.IO.Directory]::CreateDirectory($parent) | Out-Null
  }}
  for ($attempt = 0; $attempt -lt {attempts}; $attempt++) {{
    try {{
      if ([System.IO.File]::Exists($target)) {{ [System.IO.File]::Delete($target) }}
      [System.IO.File]::Move($source, $target)
      return $true
    }} catch {{
      Start-Sleep -Milliseconds 500
    }}
  }}
  return $false
}}

function Remove-EmptyParents {{
  param([string]$Path)

  $separator = [System.IO.Path]::DirectorySeparatorChar
  $root = $install.TrimEnd($separator) + $separator
  $directory = [System.IO.Path]::GetDirectoryName($Path)
  while ($directory -and $directory.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) {{
    $extended = Get-ExtendedPath $directory
    if (-not [System.IO.Directory]::Exists($extended)) {{ break }}
    if ([System.IO.Directory]::EnumerateFileSystemEntries($extended).GetEnumerator().MoveNext()) {{
      break
    }}
    try {{ [System.IO.Directory]::Delete($extended) }} catch {{ break }}
    $directory = [System.IO.Path]::GetDirectoryName($directory)
  }}
}}

# --------------------------------------------------------------- progress ---

$script:form = $null
$script:closing = $false
$script:bar = $null
$script:label = $null
$script:detail = $null

# A courtesy, not part of the transaction: every step here is guarded, and a
# machine with no desktop session runs the whole update with no window and the
# same outcome.
function Open-Progress {{
  if ($Quiet) {{ return }}
  try {{
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    $script:form = New-Object System.Windows.Forms.Form
    $script:form.Text = 'Updating Hanly'
    $script:form.ClientSize = New-Object System.Drawing.Size(460, 130)
    $script:form.FormBorderStyle = 'FixedDialog'
    $script:form.StartPosition = 'CenterScreen'
    $script:form.MaximizeBox = $false
    $script:form.MinimizeBox = $false
    $script:form.TopMost = $true

    $script:label = New-Object System.Windows.Forms.Label
    $script:label.SetBounds(18, 18, 424, 22)
    $script:label.Text = "Updating Hanly to $version"
    $script:form.Controls.Add($script:label)

    $script:bar = New-Object System.Windows.Forms.ProgressBar
    $script:bar.SetBounds(18, 50, 424, 20)
    $script:bar.Minimum = 0
    $script:bar.Maximum = [Math]::Max(1, $operations.Count)
    $script:form.Controls.Add($script:bar)

    $script:detail = New-Object System.Windows.Forms.Label
    $script:detail.SetBounds(18, 80, 424, 34)
    $script:detail.ForeColor = [System.Drawing.Color]::DimGray
    $script:form.Controls.Add($script:detail)

    $script:closing = $false
    $script:form.Add_FormClosing({{
      param($formSender, $formEvent)
      if (-not $script:closing) {{
        $formEvent.Cancel = $true
        $formSender.Hide()
      }}
    }}.GetNewClosure())
    $script:form.Show()
    [System.Windows.Forms.Application]::DoEvents()
  }} catch {{
    $script:form = $null
  }}
}}

function Update-Progress {{
  param([string]$Text, [int]$Value = -1, [string]$Detail = '')

  if ($null -eq $script:form) {{ return }}
  try {{
    $script:label.Text = $Text
    if ($Value -ge 0) {{ $script:bar.Value = [Math]::Min($Value, $script:bar.Maximum) }}
    $script:detail.Text = $Detail
    [System.Windows.Forms.Application]::DoEvents()
  }} catch {{
  }}
}}

function Close-Progress {{
  if ($null -eq $script:form) {{ return }}
  try {{
    $script:closing = $true
    $script:form.Close()
    $script:form.Dispose()
  }} catch {{
  }}
  $script:form = $null
}}

# -------------------------------------------------------------- processes ---

# By the program they are running, never by name: the shell, the Control Center
# and the lookup child all run this installation's executable, and anything else
# called hanly-desktop is none of this script's business.
function Get-InstallProcesses {{
  $prefix = $install.TrimEnd('\') + '\'
  $found = @()
  foreach ($process in (Get-Process -ErrorAction SilentlyContinue)) {{
    try {{
      $path = $process.Path
    }} catch {{
      continue
    }}
    if ($path -and $path.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {{
      $found += $process
    }}
  }}
  return $found
}}

function Wait-ForInstallToBeFree {{
  $deadline = (Get-Date).AddSeconds({exit_wait})
  while ((Get-Date) -lt $deadline) {{
    if (@(Get-InstallProcesses).Count -eq 0) {{ return $true }}
    Update-Progress "Waiting for Hanly to close…" -Detail 'The update starts once it has stopped.'
    # Once a second: every poll walks the whole process table reading paths.
    Start-Sleep -Seconds 1
  }}
  return (@(Get-InstallProcesses).Count -eq 0)
}}

function Stop-InstallProcesses {{
  foreach ($process in @(Get-InstallProcesses)) {{
    try {{ $process.CloseMainWindow() | Out-Null }} catch {{ }}
  }}
  Start-Sleep -Seconds 2
  foreach ($process in @(Get-InstallProcesses)) {{
    try {{ Stop-Process -InputObject $process -Force -ErrorAction SilentlyContinue }} catch {{ }}
  }}
  Start-Sleep -Seconds 1
}}

# ----------------------------------------------------------------- apply ----

function Invoke-Apply {{
  Write-Record 'applying'
  $done = 0
  foreach ($operation in $operations) {{
    $done++
    $target = Join-Relative $install $operation.path
    $payload = Resolve-TransactionPath $operation.payload
    $backup = Resolve-TransactionPath $operation.backup

    Update-Progress "Replacing files $done / $($operations.Count)" $done $operation.path
    Write-Record 'operation' $operation.index $operation.kind

    # Every branch reads the filesystem before acting, so an operation
    # interrupted after its move and before its record replays to the same
    # place instead of moving something twice.
    switch ($operation.kind) {{
      'add' {{
        if (Test-FilePresent $payload) {{
          # Still staged and the path is occupied: something appeared since the
          # plan was made. It has no backup, so it is not ours to overwrite.
          if (Test-FilePresent $target) {{ return $false }}
          if (-not (Move-FileWithRetry $payload $target)) {{ return $false }}
        }} elseif (-not (Test-FilePresent $target)) {{
          return $false
        }}
      }}
      'replace' {{
        if ((Test-FilePresent $target) -and -not (Test-FilePresent $backup)) {{
          if (-not (Move-FileWithRetry $target $backup)) {{ return $false }}
        }}
        if (Test-FilePresent $payload) {{
          if (-not (Move-FileWithRetry $payload $target)) {{ return $false }}
        }} elseif (-not (Test-FilePresent $target)) {{
          return $false
        }}
      }}
      'delete' {{
        if (Test-FilePresent $target) {{
          if (-not (Move-FileWithRetry $target $backup)) {{ return $false }}
        }}
        Remove-EmptyParents $target
      }}
      default {{ return $false }}
    }}
    Write-Record 'applied' $operation.index
  }}
  return $true
}}

function Invoke-Rollback {{
  Write-Record 'rolling-back'
  Update-Progress 'Restoring the previous version…' 0
  $intact = $true
  $ordered = @($operations)
  [array]::Reverse($ordered)
  foreach ($operation in $ordered) {{
    $target = Join-Relative $install $operation.path
    $payload = Resolve-TransactionPath $operation.payload
    $backup = Resolve-TransactionPath $operation.backup

    Update-Progress 'Restoring the previous version…' -Detail $operation.path
    switch ($operation.kind) {{
      'add' {{
        # A payload still staged means this addition was never made, so a file
        # at that path belongs to whatever put it there.
        if ((Test-FilePresent $target) -and -not (Test-FilePresent $payload)) {{
          try {{
            [System.IO.File]::Delete((Get-ExtendedPath $target))
          }} catch {{
            $intact = $false
          }}
          Remove-EmptyParents $target
        }}
      }}
      default {{
        # A missing backup means the original was never moved aside, which is
        # the same state a rollback is trying to reach.
        if (Test-FilePresent $backup) {{
          if (-not (Move-FileWithRetry $backup $target)) {{ $intact = $false }}
        }}
      }}
    }}
  }}
  return $intact
}}

function Start-Candidate {{
  param([string]$Arguments = '')

  $options = @{{ FilePath = $program; WorkingDirectory = $install; PassThru = $true }}
  if ($Arguments -ne '') {{ $options['ArgumentList'] = $Arguments }}
  try {{
    return Start-Process @options
  }} catch {{
    return $null
  }}
}}

# A schema-2 answer is compared as whole bytes against the file staging wrote,
# so this script never reassembles the record and never has to agree with the
# installer about field order. A schema-1 transaction still answers by version,
# which is all a helper of that generation ever asked for.
function Test-Started {{
  if ($ackPath) {{
    if (-not (Test-Path -LiteralPath $ackPath)) {{ return $false }}
    if (-not (Test-Path -LiteralPath $expectedPath)) {{ return $false }}
    try {{
      $answered = [System.IO.File]::ReadAllText($ackPath)
      $expected = [System.IO.File]::ReadAllText($expectedPath)
    }} catch {{
      return $false
    }}
    return $answered -ceq $expected
  }}
  if (-not (Test-Path -LiteralPath $readyPath)) {{ return $false }}
  try {{
    $reported = (Get-Content -LiteralPath $readyPath -Raw -ErrorAction SilentlyContinue)
  }} catch {{
    return $false
  }}
  return ($null -ne $reported -and $reported.Trim() -ceq $version)
}}

function Get-ReadyArguments {{
  if ($ackPath) {{ return '--update-ready-v2 "' + $challengePath + '"' }}
  return '--update-ready "' + $readyPath + '"'
}}

# A stale answer from an earlier attempt would commit this transaction without
# the new build having started at all.
function Clear-Acknowledgement {{
  foreach ($path in @($ackPath, $readyPath)) {{
    if ($path) {{
      Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
    }}
  }}
}}

# The new build adopts the staged receipt when it answers. A rollback has to put
# back the one describing the build going back into place, and drop the one that
# was never earned.
function Restore-Receipt {{
  if (-not $receiptPath) {{ return }}
  $directory = [System.IO.Path]::GetDirectoryName($receiptPath)
  if (-not $directory) {{ return }}
  $previous = Join-Path $directory '{previous_receipt}'
  $pending = Join-Path $directory '{pending_receipt}'
  try {{
    if (Test-Path -LiteralPath $previous) {{
      Copy-Item -LiteralPath $previous -Destination $receiptPath -Force
      Remove-Item -LiteralPath $previous -Force -ErrorAction SilentlyContinue
    }} else {{
      Remove-Item -LiteralPath $receiptPath -Force -ErrorAction SilentlyContinue
    }}
    Remove-Item -LiteralPath $pending -Force -ErrorAction SilentlyContinue
  }} catch {{
  }}
}}

function Wait-ForStartup {{
  $deadline = (Get-Date).AddSeconds({ready_wait})
  while ((Get-Date) -lt $deadline) {{
    if (Test-Started) {{ return $true }}
    Start-Sleep -Seconds 1
  }}
  return $false
}}

# ------------------------------------------------------------------- run ----

$claim = [ordered]@{{ pid = $PID; recover = [bool]$Recover }}
$claim['at'] = [double]([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() / 1000)
[System.IO.File]::WriteAllText(
  (Join-Path $Transaction '{helper_name}'),
  ($claim | ConvertTo-Json),
  $utf8
)

Open-Progress
$status = 1
try {{
  if (-not (Wait-ForInstallToBeFree)) {{
    if ($Recover) {{
      Stop-InstallProcesses
    }}
    if (@(Get-InstallProcesses).Count -ne 0) {{
      Write-Record 'recovery-required' -Detail 'Hanly is still running'
      Write-Result 'recovery-required' 'Hanly did not close, so nothing was changed.'
      Close-Progress
      exit 1
    }}
  }}

  if (Invoke-Apply) {{
    Write-Record 'awaiting-startup'
    Update-Progress "Starting Hanly $version…" $operations.Count
    Clear-Acknowledgement
    $candidate = Start-Candidate (Get-ReadyArguments)
    if (Wait-ForStartup) {{
      Write-Record 'committed'
      Write-Result 'committed' "Hanly $version started."
      $status = 0
    }} else {{
      if ($null -ne $candidate) {{ Stop-InstallProcesses }}
      if (Invoke-Rollback) {{
        Restore-Receipt
        Write-Record 'restored'
        Write-Result 'restored' (
          "Hanly $version did not start, so the previous version is back."
        )
        Start-Candidate | Out-Null
      }} else {{
        Write-Record 'recovery-required' -Detail 'rollback incomplete'
        Write-Result 'recovery-required' 'The previous version could not be fully restored.'
      }}
    }}
  }} else {{
    if (Invoke-Rollback) {{
      Restore-Receipt
      Write-Record 'restored'
      Write-Result 'restored' 'The update could not be applied, so nothing was changed.'
      Start-Candidate | Out-Null
    }} else {{
      Write-Record 'recovery-required' -Detail 'apply and rollback both incomplete'
      Write-Result 'recovery-required' 'The update stopped part way and could not be undone.'
    }}
  }}
}} catch {{
  Write-Record 'recovery-required' -Detail $_.Exception.Message
  Write-Result 'recovery-required' $_.Exception.Message
}} finally {{
  Close-Progress
}}

exit $status
"""


__all__ = [
    "CLAIM_WAIT_SECONDS",
    "EXIT_WAIT_SECONDS",
    "HELPER_SCRIPT_NAME",
    "MOVE_ATTEMPTS",
    "PENDING_NAME",
    "READY_WAIT_SECONDS",
    "RECOVERY_LAUNCHER_NAME",
    "HelperError",
    "await_claim",
    "clear_recovery_copy",
    "helper_is_running",
    "install_recovery_copy",
    "pending_transaction",
    "recover_pending",
    "render_helper_script",
    "start_helper",
    "write_helper",
]
