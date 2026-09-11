# HAN-42 Updater Reliability Review Handoff

## Bundle

- Member issues: HAN-42 (Phase 1 of `docs/execution/post-v013-technical-wave.md`)
- Implementation ecosystem: Claude Opus, directly, under the human's
  **SIMPLIFICATION OVERRIDE** for this wave
- Date: 2026-09-09
- Host: macOS 25.6.0 (arm64), Python 3.13.11 in `.venv`
- Commit at start: `ed51a6a`, working tree clean. Nothing committed or pushed.

## Scope decision the override changed

The investigation enumerated failure modes broadly. Per the override, this
phase implements the smallest design that proves
**download → validate → stage → replace → relaunch → verify → cleanup**, with a
rollback that preserves the working application, and removes the broken handoff
rather than building an updater subsystem.

What the plan proposed and this phase **deliberately did not build**, because no
current failure mode or test required it:

| Proposed | Disposition |
|---|---|
| Durable transaction receipts / persisted progress | **Not built.** The only persisted state is one readiness file inside the transaction directory, required by the verify step itself. |
| Reboot-survival and next-launch recovery scanning | **Not built.** An interrupted swap leaves the transaction directory for manual recovery; `packaging/README.md` documents where the previous build is. |
| Legacy install-local data migration | **Not built.** Settings, diagnostics and KRDICT already live outside the installation, so the swap does not touch them. |
| `application-build.json` embedded build identity | **Not built.** It was conditional on existing metadata being insufficient. It is sufficient: `importlib.metadata.version("hanly-app")` gives the version, the macOS `Info.plist` gives identity, and the readiness handshake proves the new build *actually runs on this machine* — a stronger check than a static architecture string, since a wrong-architecture build fails to start and is rolled back. |
| Exclusive cross-process lock keyed by install root | **Not built.** Transaction directories are uniquely named, so two attempts cannot collide or delete each other's work. |
| Helper-ready acknowledgement before quitting | **Not built.** If the script never starts, Hanly quits with the installation untouched and reopening works — annoying, not destructive. Revisit trigger below. |

## Defects reproduced before fixing

Every one of these is a current, evidenced failure, not a speculative hardening.

| Platform | Defect | Evidence |
|---|---|---|
| macOS | **Every real release archive was refused.** `_require_bundle_member` rejected any member outside `Hanly.app/`, but `tools/build_package.py` archives with `ditto --sequesterRsrc`, which always emits a `__MACOSX/` sidecar tree. | `_preflight_bundle_members(dist/hanly-desktop-macos.zip, "Hanly.app")` raised `the downloaded application has an unsafe path`; the real archive holds 8,780 `__MACOSX` members. Reproduced minimally with a 4-file `ditto -c -k --sequesterRsrc` archive. |
| Windows | **The relaunch resolved `hanly-desktop.exe.exe`.** `_PLATFORM_LAYOUTS["win32"].executable_path` already ends in `.exe` and `_WINDOWS_HANDOFF` appended another, in both the success and rollback branches. The swap would succeed and leave the user with no running Hanly and no error. | Rendering with the production layout. The old tests missed it because they rendered the template default instead of the real layout. |
| Linux | **Extraction refused the archive.** `extract_archive` → `_extract_gztar` rejects every link, and `shutil.make_archive(..., "gztar")` preserves the PyInstaller onedir symlinks. | The POSIX onedir tree in `dist/macos/hanly-desktop` — the same shape `build_package.py` tars for Linux — holds **442 symlinks**. Not executed on Linux; the contract mismatch is concrete. |
| All | **The previous build was deleted before anything proved the new one runs.** `apply()` only started a script; neither helper obtained any acknowledgement, and both removed the backup right after the rename. | Source. |
| All | **Fixed sibling names and scripts that never cleaned up.** `.hanly-update.download`, `<name>.staged`, `<name>.previous` and `hanly-update.sh`/`.cmd` persisted, and `_reserve()`/`_place()` deleted prior names without checking ownership. | Source. |
| All | **A resource-manifest failure hid the application check.** `_collect_updates` called `check_for_updates()` first and let it propagate, so the update that would fix a broken manifest was never offered. | Source; now covered by a test. |
| All | **Update ownership had a callback race.** `_active_locked()` went false when a future completed, before its daemon callback finalized state, so a second click could start work an older callback then overwrote. | Source; now reproduced deterministically by `_DeferredExecutor`. |

## Implemented

- **`app_update_handoff.py` (new).** One `UpdateTransaction` record and the
  native swap script per platform. The script waits for Hanly to exit, renames
  the installation into the transaction directory, renames the staged build
  into place, relaunches it with `--update-ready <path>`, and waits for that
  path to hold the version it installed. Success removes the transaction
  directory and the script; a timeout puts the previous build back and
  relaunches that; a failed restore launches nothing and keeps the backup.
- **Windows helper rewritten from `cmd` to PowerShell 5.1**, using
  `[System.IO.Directory]::Move`, `Get-Process`, `Start-Process` and literal
  paths. This removes the `_CMD_UNSAFE` refusal entirely — an installation path
  containing `&`, `%`, `!` and friends is no longer rejected — and removes the
  doubled-extension relaunch.
- **macOS relaunches through `/usr/bin/open`** on the `.app`, so the new build
  is a registered application with a Dock entry, instead of the inner program
  being exec'd directly.
- **Staging is transaction-scoped.** `stage()` claims one uniquely named
  `.hanly-update-*` directory beside the installation and puts the download,
  checksums, extraction, staged build, backup and readiness file inside it.
  Any failure removes that one directory.
- **`extract_application_tar` (new)** is the application's own Linux extractor:
  it admits directories, regular files and symlinks that resolve inside the
  payload, and refuses everything else. The resource extractor is unchanged.
- **The `__MACOSX` sidecar is admitted into the table of contents and never
  onto disk.** `_require_extracted_roots` checks what the unpacker actually
  produced, so an extractor that writes the sidecar out is still caught.
- **Draft and prerelease payloads are refused**, and the release's declared
  asset size is passed to the downloader as a byte bound.
- **Coordinator ownership** now ends when the matching callback finalizes, not
  when the future completes; stale callbacks are dropped by future identity;
  and no further update starts once the swap is waiting for this process.
- **Resource and application checks are collected independently.**
- **`--update-ready` reaches `run_desktop` through the one entry point**, and is
  answered from the Control Center window's own post-start hook — Qt, WebEngine
  and the interpreter inside the new build have all started by then. It does
  not wait on capture permission, Start Capture, or a network check. A failed
  write is reported to diagnostics and never blocks the launch.

## Architecture / seams touched

- `hanly-app → hanly` direction unchanged; nothing was added to the engine.
- `ResourceManager` (understands local resources) vs `UpdateService`/app updater
  (obtains remote ones) unchanged. `update_service.py` was **not modified**.
- **One entry point preserved.** `--update-ready` is a suppressed argument to
  `cli.main`, not a second program; `tests/test_packaging.py` still passes.
- `_ControlCenter.run` and `DesktopApplication.run` gained pywebview's existing
  optional `on_started` hook, which `ControlCenterHost.run` already accepted.
- No architecture invariant changes are required by this work.

## Relevant files / diff areas

- `packages/hanly-app/src/hanly_app/app_update_handoff.py` (new)
- `packages/hanly-app/src/hanly_app/app_update.py`
- `packages/hanly-app/src/hanly_app/update_coordinator.py`
- `packages/hanly-app/src/hanly_app/application.py`, `cli.py`
- `tests/test_app_update_handoff.py` (new), `tests/test_app_update.py`,
  `tests/test_update_coordinator.py`, `tests/test_application.py`,
  `tests/test_capture_selector.py`
- `docs/CODE-MAP.md` (§6a, the update index the plan called incomplete),
  `packaging/README.md`

## Implementation-side validation already run

Project gates, on this host:

```text
.venv/bin/python -B -m pytest                     1025 passed, 2 skipped (86s)
.venv/bin/python -m ruff check packages packaging tests tools benchmarks   passed
.venv/bin/python -m mypy  packages packaging tests tools benchmarks        no issues, 177 files
```

**The macOS handoff was executed for real, not rendered.**
`tests/test_app_update_handoff.py` compiles two tiny Mach-O programs with `cc`,
builds them into real `.app` bundles, and runs the actual script:

- a verified update swaps the installation, relaunches through `open`, gets the
  expected version back, and leaves nothing behind — no staged build, no
  backup, no script;
- a build that reports the wrong version is rolled back and the previous build
  relaunched;
- a staged build that cannot be moved into place relaunches the previous one;
- a rollback that itself fails launches nothing and keeps the backup;
- an installation path with spaces and Hangul survives the whole handoff.

(LaunchServices refuses to `open` a bundle whose executable is a shell script,
which is why the test compiles real binaries; the tests skip where `cc` is
absent.)

**The real release artifact was staged end to end.** Driving
`ApplicationInstaller.stage()` against `dist/hanly-desktop-macos.zip`
(570,688,335 bytes) with the real SHA-256 and real `ditto`:

```text
phases downloading → verifying → installing → complete   8.3 s
size bound passed to the downloader   570688335
staged payload           Hanly.app, program present
symlinks preserved       1537
running installation     untouched (b'old build')
transaction contents     ['Hanly.app']
codesign --verify --deep --strict   PASS
```

Before this change that same archive was refused outright.

## Known limitations / intentionally unvalidated areas

- **Windows was not executed.** The PowerShell helper is rendered and asserted
  here, and `tests/test_app_update_handoff.py` executes it on `win32`, but that
  lane has only ever run in CI. **This is the largest open risk in the phase**:
  argument quoting at the `Start-Process` boundary, execution policy under
  machine GPO, and the locked-directory retry are unproven on real Windows.
- **Linux was not executed on a Linux kernel.** `extract_application_tar` and
  the Linux handoff variant were exercised on macOS, including a release-shaped
  tar built from the real PyInstaller onedir tree. A real frozen Linux build and
  native-kernel swap remain outstanding.
- **No two-version frozen build was produced.** Staging is proved against the
  real archive; the *frozen old → new* swap is not. The plan's
  `tools/smoke_application_update.py` and
  `tests/integration/test_application_update.py` are **not written** — they need
  two genuine builds in disposable checkouts, which is a separate run.
- **v0.1.3 cannot self-update to a build carrying this fix.** The defects are in
  the installed 0.1.3 code, and code that is not yet installed cannot repair
  them. On macOS 0.1.3 refuses the archive; on Windows it swaps and then fails
  to relaunch. **Migration off 0.1.3 is manual** (download the DMG / ZIP and
  replace the installation). Do not claim backward self-update works.
- **The reported macOS `.cmd` incident is still unattributed.** Current source
  cannot produce that filename on Darwin — confirmed again here — and it now
  cannot produce any `.cmd` at all. Original-machine evidence is still needed.
- **Explicit CLI arguments are not carried across an update relaunch.** Same as
  before this change; now documented in `packaging/README.md`.
- **The readiness timeout is 600 s**, taken from
  `tools/smoke_packaged_runtime.UI_TIMEOUT_SECONDS` — the bound the packaged UI
  smoke already allows a frozen build for the same milestone. It is a derived
  bound, not a measured one; a real cold frozen start was not timed here.
- `build.yml`'s `continue-on-error` on the macOS/Linux Control Center smoke was
  **not** removed. It is a release-gate change the plan places in this phase,
  but it belongs with the CI work in §5.2 and would go untested until a build
  runs. Flagged, not done.
- Nothing was committed, pushed, published, or mutated in Linear.

## Deferred, with revisit triggers

| Item | Revisit when |
|---|---|
| Helper-ready acknowledgement before Qt quit | A Windows lane shows the helper failing to start after `Popen` succeeded (execution policy, AV interception). |
| Reboot-survival / next-launch recovery | A real interrupted swap is observed leaving a user without a usable installation. |
| Cross-process update lock | Two Hanly processes on one installation are shown to overlap. Unique transaction names already stop them destroying each other's work. |
| Killing an unresponsive new build before rollback | A hung — not crashed — new build is observed. Today a rollback whose restore fails aborts and keeps the backup, which is safe but leaves the hung process running. |
| `application-build.json` | Existing metadata is shown insufficient to prove version, platform or architecture. |

## Suggested review targets

1. **The PowerShell helper**, line by line — it is the least-proven artifact
   here. Especially `Start-Process -ArgumentList` quoting, the
   `[System.IO.Directory]::Move` retry loop, and `Complete-Handoff` deleting
   `$PSCommandPath` while PowerShell is running it.
2. **The rollback branches in both scripts**, against the rule that the previous
   build is discarded only after the new one answered.
3. **`_require_bundle_member(..., sidecar=True)`** — whether admitting
   `__MACOSX` into the table of contents while `_require_extracted_roots`
   guards what lands on disk is the right split.
4. **`extract_application_tar`'s link policy** against a real Linux release tar.
5. **The readiness milestone**: is "the window opened" the right proof, versus
   `RuntimeStatus.ready` (which would make a missing KRDICT roll back a working
   update)?
6. **`UpdateCoordinator._deliver`** and the `_handed_off` flag.

## Phase B review — findings

Reviewed 2026-09-09, scoped by the human to the HAN-42 implementation only:
transaction ownership/cleanup, rollback correctness, the readiness handshake,
PowerShell safety and quoting, `__MACOSX` handling versus traversal protection,
Linux symlink validation, the stale-callback fix, and resource-check
independence. No redesign; no reboot recovery or durable machinery added.

### Fixed now

**1. The PowerShell relaunch would lose the readiness path on any installation
path containing a space.** `Start-Process -ArgumentList` given an array joins it
with spaces and quotes nothing, so `@('--update-ready', 'C:\Users\John
Smith\...\ready')` reaches the new build as four arguments. The new build would
never write the readiness file, and **every such update would roll back despite
having installed correctly**. Windows installation paths contain a space more
often than not (`C:\Program Files\…`, any `C:\Users\First Last\…`). The
helper now builds a single explicitly quoted argument line. Pinned by
`test_the_windows_relaunch_quotes_the_path_it_hands_the_new_build`.
*Severity: high. This is exactly the boundary the plan warned about — "`Start-Process
-ArgumentList` alone does not prove correct quoting" — and the first handoff
flagged it as unproven instead of fixing it.*

**2. A failed resource check was reported to the user as "all current".** The
independence fix swallowed the resource exception and left `resources: []`, so
`_check_message` produced *"Hanly and all local resources are current."* for a
manifest that could not be read at all. That is worse than the original bug it
replaced: the original at least showed an error. Both halves now report their
own failure; the check reaches `failed` when only the resource half broke, and
names the cause when an application update is available alongside it. Pinned by
`test_a_resource_check_that_could_not_run_is_never_reported_as_up_to_date`.
*Severity: high, and introduced by this phase.*

**3. Rolling back deleted the rejected build before restoring the previous
one.** Both scripts did `rm -rf $install` / `Remove-Item -Recurse` and then
restored. A recursive delete can fail part way through — on Windows routinely,
if the new build is still holding a file — leaving the installation path in
pieces with nothing yet restored. Both now rename the rejected build into the
transaction directory instead, which either happens or does not, and which the
existing cleanup removes anyway. Pinned by
`test_a_rejected_build_is_renamed_aside_rather_than_deleted`.
*Severity: medium. Also one primitive instead of two.*

**4. A relaunch that threw skipped the cleanup after it.** With
`$ErrorActionPreference = 'Stop'`, a failing `Start-Process` terminated the
script before `Complete-Handoff`, leaking the transaction directory. `Start-Hanly`
now never throws: every caller is already followed by something that handles a
build which did not come up — the readiness wait rolls back, and a rollback has
nothing further to try. *Severity: low. Also simpler.*

**5. The post-extraction containment check never looked at symlinked
directories.** `os.walk` reports a link to a directory as a subdirectory and
does not descend it, so resolving only `files` skipped them entirely; a
`Contents/escape -> /etc` link passed the check. Reproduced directly. The
archive preflight already rejects such a link textually, so this was
defence-in-depth that did not defend rather than a reachable hole — fixed as
cheap hardening at a public boundary. Verified against the real release archive
afterwards: it still stages cleanly, with **299 symlinked directories now
required to resolve inside the payload**. Pinned by
`test_a_link_to_a_directory_that_escapes_is_caught_after_extraction`.
*Severity: low (defence in depth).*

### Reviewed and found correct

- **Transaction ownership and cleanup.** One `mkdtemp` directory per attempt, so
  two attempts cannot collide or delete each other's work; every failure path in
  `stage()` removes exactly that directory; `apply()` removes it if the handoff
  cannot start. The script lives outside the directory it deletes and removes
  itself last.
- **`__MACOSX` handling does not weaken traversal protection.** `sidecar=True`
  widens only the permitted *first path component*, and only for the ZIP
  preflight. Absolute paths, drive letters, backslashes and `..` are still
  refused for every member, links are still resolved textually against
  `payload_name` (so a link under `__MACOSX` is refused), and
  `_require_extracted_roots` independently proves the sidecar never reached
  disk. The tar path does not pass `sidecar`.
- **Linux symlink validation.** `_require_link_inside` resolves textually,
  pops on `..`, and requires the result's first component to be the payload —
  absolute, escaping and empty targets are all refused before extraction, and
  `filter="data"` plus the containment walk sit behind it. Hard links and device
  nodes still fall to the "unsupported entry" branch.
- **The stale-callback fix.** `_deliver` compares future identity under the
  lock; `_active_locked` holds ownership until a callback finalizes;
  `_handed_off` is one-way and set only after a successful stage. A stale
  callback arriving after `_handed_off` finds `_future is None` and is dropped.
- **The readiness handshake.** The file cannot pre-exist (fresh `mkdtemp`), the
  version is compared rather than mere existence, `confirm_started` writes
  without a trailing newline and `cat`/`Get-Content -Raw` handle either, and a
  failed write is reported to diagnostics without blocking startup.

### Dismissed

- **PID reuse during the exit wait** (`kill -0` / `Get-Process`) could make the
  handoff wait out its bound and abandon the update. Pre-existing, unchanged by
  this phase, low probability, and it fails safe: the installation is untouched.
- **A hung new build being rolled back around** leaves two processes on POSIX.
  Documented in `packaging/README.md`; killing it needs process identity the
  override rules out for now, and it is already in the deferred table.
- **A trailing backslash in an installation path** would break the quoted
  PowerShell argument. `mkdtemp` never produces one, and Windows paths from
  `Join-Path` do not end in a separator.

### Not re-run after the fixes

The gates were re-run in full (below). The **real-artifact staging probe was
re-run** and still passes. The **native macOS handoff tests were re-run** and
cover the changed rollback path. Windows and Linux remain unexecuted, as before.

## Native gate attempt — 2026-09-09

Ordered by the human: complete the Windows and Linux native validation, then
transition automatically to HAN-40 only if both pass.

### Windows — NOT EXECUTED. Blocker.

This host has no way to run the PowerShell handoff at all:

```text
uname                        Darwin 25.6.0 arm64
docker/podman/colima/lima    absent
vagrant/qemu/UTM             absent
pwsh / powershell            absent
wine / wine64                absent
gh                           absent
```

Windows PowerShell 5.1 exists only on Windows. `pwsh` could be installed on
macOS, but it would prove nothing that matters here: the defect class this gate
exists to catch is `Start-Process` **Win32 argv quoting**, NTFS **executable
locking** during the rename retry, execution policy, and launching from a
frozen GUI process with no console — none of which a POSIX build of PowerShell
Core reproduces. Running it would produce a green result with no bearing on
Windows, which is worse than no result.

The CI Windows lane cannot be reached either: `gh` is absent, and this run is
forbidden from committing, pushing, or creating branches, which is what would
trigger it.

**Nothing about the Windows handoff has been executed. It remains rendered-only,
including the argument-quoting fix made during the focused review — the fix is
reasoned and pinned by a render assertion, but unproven at runtime.**

### Linux — executed, with one stated limitation

The Linux script body and the Linux extraction path were both run for real. The
kernel underneath was macOS, not Linux; the script is plain POSIX shell that
execs the program at the final path, and tar symlink/mode semantics are POSIX,
so the behaviour exercised is the shipped behaviour. A real Linux kernel and a
real frozen Linux Hanly build are still outstanding.

**Real release-shaped tar.** Built from the actual PyInstaller onedir tree in
`dist/macos/hanly-desktop` exactly the way `tools/build_package.py` archives the
Linux product (`shutil.make_archive(..., "gztar", base_dir="hanly-desktop")`):

```text
archive          hanly-desktop-linux.tar.gz, 562,546,015 bytes
members          6378   symlinks 442   hardlinks 0   executable files 519
roots            ['hanly-desktop']
sample link      _internal/PyQt6/Qt6/lib/QtConcurrent.framework/QtConcurrent
                   -> Versions/Current/QtConcurrent
```

Against that artifact:

```text
resource extractor (extract_archive, gztar)
  -> REFUSED: "archive contains a link or special file"
extract_application_tar
  -> ok in 5.3 s
     symlinks preserved  442      broken 0      escaping 0
     executable files    519      program mode 0o755, X_OK true
     extracted roots     ['hanly-desktop']
```

This upgrades the Linux defect from an inferred contract mismatch to a
**reproduction on a real release-shaped artifact**, and shows the replacement
extractor handling it losslessly.

**Real handoff execution.** `tests/test_app_update_handoff.py` now parameterises
its native tests over the handoff variants the host can execute, so the
**linux** variant — direct-exec relaunch of the program at the final path —
runs alongside the darwin one, and will run natively on the Linux CI lane:

```text
test_a_verified_update_replaces_the_installation_and_cleans_up_after_itself[linux]  PASSED
test_a_new_build_that_never_reports_starting_gives_the_old_one_back[linux]          PASSED
test_a_replacement_that_cannot_be_moved_into_place_relaunches_the_old_build[linux]  PASSED
test_an_installation_path_with_spaces_and_non_ascii_survives_the_handoff[linux]     PASSED
```

Between them these cover the canonical swap, final-path relaunch, the
`--update-ready` handshake, expected-version acknowledgement, cleanup of
transaction and script, rollback on a failed launch, and rollback on a wrong
version — with spaces and Hangul in the installation path.

| Linux requirement | Status |
|---|---|
| real PyInstaller onedir symlink structure | Done — 442 links from the real tree |
| legitimate internal symlinks preserved | Done — 442/442, none broken or escaping |
| escaping symlinks rejected | Done — unit test, refused before extraction |
| executable permissions preserved | Done — 519 files, program `0o755` |
| canonical installation swap | Done — linux variant executed |
| final-path relaunch | Done |
| `--update-ready` readiness handshake | Done |
| expected-version acknowledgement | Done |
| cleanup | Done |
| rollback | Done — failed launch and wrong version |
| **Linux kernel** | **Outstanding** |
| **real frozen Linux Hanly build** | **Outstanding** |

### Gates re-run after these changes

```text
pytest   1033 passed, 2 skipped
ruff     All checks passed
mypy     no issues in 177 source files
```

The pytest result requires normal LaunchServices access. In a restricted
sandbox the Darwin helper cases fail when `/usr/bin/open` is denied; rerunning
the same suite with native application-launch access produced the result above.

### Status change — native validation deferred (human decision, 2026-09-09)

The human has moved the Windows and Linux native updater execution out of this
phase and into the **final clean build / GitHub Actions / release-tag
validation**. It is an accepted deferred release risk, not a HAN-40 blocker.

**Neither platform may be recorded as PASS until that validation actually
runs.** What each still owes:

| Windows | Evidence today | Still pending on a real Windows lane |
|---|---|---|
| PowerShell helper | Source, unit/render assertions, focused review | Actual execution |
| `Start-Process` argument quoting | Reasoned fix + render assertion | **Exact native quoting behaviour** — the highest-value unproven item |
| GUI-process launch | Reasoned | Behaviour from a console-less frozen process |
| Executable locking | Retry loop written | NTFS lock during the rename retry |
| Frozen old → new swap | Not attempted | Required |

| Linux | Evidence today | Still pending on a real Linux lane |
|---|---|---|
| Archive/symlink logic | Real 562 MB release-shaped tar, 442 links preserved, 0 escaping | Same on a Linux kernel |
| Executable permissions | 519 files, `0o755`, verified | Native verification |
| Handoff body | `[linux]` variant executed on a macOS kernel | Execution on Linux |
| Final-path relaunch | Executed (POSIX) | Native |
| Frozen old → new swap | Not attempted | Required |

The macOS half of the gate is genuinely complete and is not deferred.

### Recommended final-validation action

HAN-40 may proceed under the human's explicit deferral above. Before release,
close the remaining native proof through one of:

1. **Run the CI Windows lane** — the cheapest path. It needs a commit and push,
   which this run is forbidden to do; the human can push the branch and the
   existing `ci.yml` Windows job plus `tests/test_app_update_handoff.py` will
   execute the PowerShell handoff, including the space-and-Hangul path that
   exercises the quoting fix.
2. **Run `pytest tests/test_app_update_handoff.py` on any Windows machine**
   with a C toolchain. The probe's compiler lookup was corrected during this
   attempt: it previously exempted Windows from the requirement and would have
   died on a missing `cc` with a `FileNotFoundError`; it now resolves `cc`,
   `clang` or `gcc` and skips with a stated reason when none is present, so a
   Windows run that cannot compile says so plainly instead of erroring. MSVC's
   `cl.exe` is not accepted — its flags differ — so a MinGW/Clang toolchain is
   what that lane needs.
3. **Provide a Windows VM or CI trigger access** to this environment.

A real Linux host would additionally close the two outstanding Linux rows,
though those are the weaker half of the remaining risk.

## Phase gate status

Ordinary project gates pass. macOS native execution is evidenced above.
**Windows and Linux native execution, and the frozen old → new swap, are
outstanding** and remain final clean-build / CI / release-tag validation items.
Per the human's 2026-09-09 decision, they do not block HAN-40 and may not be
reported as passed until those native lanes actually run. HAN-42 is reconciled
and Phase A ends here.
