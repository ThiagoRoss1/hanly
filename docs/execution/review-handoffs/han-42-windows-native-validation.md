# HAN-42 Windows Native Validation Review Handoff

## Bundle

- Member issues: HAN-42 (native Windows validation of the post-v0.1.3
  technical wave; follows `han-42-updater-reliability.md`)
- Implementation ecosystem: Claude Opus, directly
- Date: 2026-09-10
- Branch: `codex/post-v013-technical-wave`, HEAD `ca2a403`, working tree clean
  at start. Nothing committed, pushed, merged, or changed in Linear.

This run closes remaining risk 1 of `post-v013-technical-wave-final.md` — "no
native Windows execution happened in this wave" — and answers its open
`debug.pak` question with a measurement.

## Environment

**Host.** Windows 10 Enterprise 10.0.19045, x64. System locale **pt-BR**, which
is not incidental: two of the defects below only appear when Windows formats
its own error strings in a non-English code page.

**Release environment.** A fresh venv at `D:\hanly-release\venv` on
**Python 3.10.11**, the exact interpreter `build.yml` pins, installed in the
workflow's order:

```
python -m pip install --upgrade pip                                  # 26.2.1
python -m pip install --group dev -c packaging/release-constraints.txt
python -m pip install --editable packages/hanly
python -m pip install --editable "packages/hanly-app[runtime]" -c packaging/release-constraints.txt
python -m pip install "pyinstaller>=6,<7" pyinstaller-hooks-contrib -c packaging/release-constraints.txt
```

Resolved runtime, as reported by the frozen build's own self-check: PyQt6
6.11.0, PyQt6-WebEngine 6.11.0, pywebview 6.2.1, pystray 0.19.5, easyocr 1.7.2,
torch 2.14.0, kiwipiepy 0.23.2, pyinstaller 6.22.2.

**Development environment.** The repository `.venv` on Python 3.13.11. Every
gate below was run in both.

## Root causes found

| # | Where | Root cause |
|---|---|---|
| 1 | `tests/test_app_update_handoff.py` | `Path.chmod(0o700)` on Windows carries only the read-only flag — there is no execute bit — so `st_mode & 0o700 == 0o700` can never hold on a Windows host. The assertion tested the operating system, not the writer. |
| 2 | `tests/test_app_update_handoff.py` | binutils' `ld.exe` takes `argv` through the Windows ANSI code page. The probe's `-o` path went straight into the Hangul installation directory, reached `ld` as `?? ????`, and failed with `Invalid argument`. |
| 3 | Local host only | `C:\msys64\mingw64\bin\cc.exe` is the first `cc` on this machine's PATH and is broken — its `cc1.exe` cannot load its own libraries, so it exits 1 with an empty stderr. Being on PATH is not the same as building programs, and every native test failed here with nothing to go on. |
| 4 | `tools/krdict/__init__.py`, `tools/dev_lookup.py` | `stream.reconfigure(encoding="utf-8")` resets the error handler to `strict` unless `errors` is named too. Under pytest that stream *is* the capture file, created with `errors="replace"`. From `tests/krdict/…` onward the session decoded captured output strictly, and the first non-UTF-8 byte a native library wrote — Qt's `qt.qpa.windowclass: … ( "Esta classe já existe." )`, a Windows error string in the console code page — raised `UnicodeDecodeError` in every subsequent setup and teardown. |
| 5 | `packages/hanly-app/src/hanly_app/app_update_handoff.py` | **Production rollback bug.** On the reject path the new build is still running from `$Install`, and Windows refuses `[System.IO.Directory]::Move` on a directory a running program was started from. The rename threw, `catch { exit 1 }` fired, and the handoff exited having restored nothing. |

Cause 4 is invisible on an English CI runner. Cause 5 is invisible to the
existing test suite, whose probes exit the instant they report.

## Exact fixes

**`tests/test_app_update_handoff.py`**

- The POSIX-mode test records the mode the writer *requests* — assertable on
  every host — and additionally asserts the mode the file lands with where the
  platform has one.
- `_compile` builds into the probe directory, which is always ASCII, and copies
  the finished program to its installation path in Python, which has no code
  page limit. The path under test still carries a space and Hangul.
- `_COMPILER` selects the first compiler on PATH that actually produces a
  program (`_builds_programs`), so a broken toolchain skips with a reason
  instead of failing every native test.
- The win32 probe is now named `hanly-desktop.exe`, the name production hands
  the handoff, so the executed test relaunches exactly what a shipped update
  would.
- The probe accepts `LINGER_SECONDS`, which is what makes a rejected build one
  the handoff has to stop rather than one that has already let go.
- New `test_a_rejected_build_that_is_still_running_is_stopped_before_the_restore`.

**`tools/krdict/__init__.py`, `tools/dev_lookup.py`** — name `errors` on
`reconfigure`, keeping the handler the stream already had. New regression test
`tests/krdict/test_console_output.py`.

**`packages/hanly-app/src/hanly_app/app_update_handoff.py`** — `Start-Hanly`
returns the started process; a new `Stop-Hanly` stops the rejected build before
the restore; the rename-aside is retried the way the first swap already is,
because stopping a process returns before Windows releases the files it held.

## Focused updater test results

`tests/test_app_update_handoff.py`: **22 passed, 1 skipped** on Python 3.13.11
and on Python 3.10.11. The skip is the POSIX `mv`-shim rollback test, which
does not apply to a Windows host.

These now execute for real on Windows rather than being rendered-only: a
verified update, a rollback when the new build never answers, a staged build
that cannot be moved into place, an installation path with spaces and Hangul,
and the new still-running-rejection case.

The new test was checked red before green. With the production fix stashed it
fails on exactly the defect:

```
E  AssertionError: assert ['new'] == ['new', 'old']
   Right contains one more item: 'old'
```

— the previous build is never relaunched. With the fix it passes.

## Full test suite

| Environment | Result |
|---|---|
| Python 3.13.11 (`.venv`) | **1035 passed, 6 skipped, 2 failed** |
| Python 3.10.11 (release venv) | **1022 passed, 8 skipped, 2 failed** |

The same two failures in both, and **they are an environment limitation, not a
product failure**:

- `tests/test_app_update.py::test_a_linux_build_keeps_the_internal_links_its_layout_is_made_of`
- `tests/test_app_update.py::test_a_link_to_a_directory_that_escapes_is_caught_after_extraction`

Both need real symlink creation. This account holds no
`SeCreateSymbolicLinkPrivilege` — `whoami /priv` lists none, and the failure is
`OSError: [WinError 1314] O cliente não tem o privilégio necessário`. The first
fails the same way indirectly: `tarfile` silently extracts a link as a regular
file when it cannot create one. Both pass on the GitHub Windows runner, which
runs elevated. Neither was skipped, xfailed, or weakened.

For scale, the release environment before the `reconfigure` fix reported
**2 failed, 741 passed, 9 skipped, 554 errors**.

## Lint, types, dependencies

| Gate | Python 3.13.11 | Python 3.10.11 |
|---|---|---|
| `ruff check packages packaging tests tools benchmarks` | clean | clean |
| `mypy packages packaging tests tools benchmarks` | clean, 178 files | clean, 178 files |
| `pip check` | no broken requirements | no broken requirements |

## Real frozen Windows build

`tools/prepare_easyocr_models.py`, then
`tools/build_package.py --platform windows` with
`PYINSTALLER_STRICT_BUNDLE_CODESIGN_ERROR=1` — the `build.yml` path, run from
the Python 3.10 release environment. Exit 0. Built twice: once to validate the
artifact, then again after the rollback fix so the frozen build carries it.

| Product | Size |
|---|---|
| `dist/hanly-desktop-windows.zip` | **604,526,871 bytes** (576.5 MiB), 5,296 entries, single `hanly-desktop/` root |
| `dist/windows/hanly-desktop` (onedir) | **1.29 GB** |

Inventory `ok`, `missing: []` — checked on the built tree and again on the tree
extracted from the published ZIP.

## Frozen runtime smoke

All against the frozen executable on an isolated profile, with the dictionary
from `tools/build_smoke_krdict.py`.

| Stage | Result |
|---|---|
| runtime | ok |
| lookup worker | ok |
| **Korean OCR (EasyOCR)** | ok — read `책을 읽습니다.` from `korean_reading_roi.png` |
| **Morphology (Kiwi)** | ok — `한국어` |
| **Dictionary (KRDICT)** | ok — 1 entry for `한국어` |
| **Control Center** | ok — window opened and the loop exited cleanly; title `Hanly · Control Center`; 4 controls rendered; bridge `get_state` reported EasyOCR |

## Real updater handoff on the frozen application

The production script, started the way the application starts it, against two
full 1.29 GB copies of the frozen build, under
`…\한글 프로그램\Program Files\hanly-desktop` — a path with both a space and
Hangul. The installed build was started for real and then quit the way an
updating Hanly does, so the handoff waited on a live process.

**Accepted** — the staged build reports the version the transaction demands:

| Observation | Result |
|---|---|
| handoff exit status | 0 |
| install root and executable | present |
| transaction directory | removed |
| handoff script | removed |
| siblings of the installation | `hanly-desktop` only |

**Rejected / rollback** — the transaction demands `9.9.9`, the build reports
`0.1.3`:

| Observation | Result |
|---|---|
| handoff exit status | 1 |
| install root and executable | present, previous build restored and relaunched |
| version the new build reported | `0.1.3` |
| transaction directory | removed |
| handoff script | removed |
| siblings of the installation | `hanly-desktop` only |
| restored installation | passes inventory (`ok`, `missing: []`) |
| stray `hanly-desktop.exe` processes | 0 |

## The production rollback bug

The rejected run is what exposed root cause 5, and it is worth stating plainly
because the invariant it broke is the one the whole handoff exists to protect.

Before the fix, the same run left:

- the **rejected** build still installed at the installation path;
- the previous build stranded inside the transaction directory as `previous`,
  with no `rejected` directory ever created — proof the first rename never
  happened;
- the handoff script still on disk;
- **no Hanly relaunched at all**.

The backup survived, so nothing was destroyed and a person could recover by
hand. But the recovery path did not recover: a user whose update installed a
build that came up and then failed verification would have been left running
the bad build. The existing suite could not see this because its probes exit
immediately, so the directory was already free by the time the rollback ran.

The fix stops the build being rejected before restoring, and retries the rename
for the moment Windows keeps files locked after a process ends. Verified by the
new unit test (red then green) and by the rejected run above on the real frozen
application.

## `qtwebengine_devtools_resources.debug.pak`

**Present. Not removed. Nothing was changed about it.**

| File | Uncompressed | In the ZIP |
|---|---:|---:|
| `_internal/PyQt6/Qt6/resources/qtwebengine_devtools_resources.debug.pak` | 75,843,657 B (72.3 MiB) | 14,716,243 B (14.0 MiB) |
| `_internal/PyQt6/Qt6/resources/qtwebengine_devtools_resources.pak` | 11,609,413 B (11.1 MiB) | 11,594,127 B (11.1 MiB) |

This answers remaining risk 2 of `post-v013-technical-wave-final.md`, which
estimated "~15 MiB compressed, if it is still there". It is there, and 14.0 MiB
compressed is close to that estimate. No issue was observed that could be
attributed to it, and the standing rule for this wave is that a file is removed
only on measured evidence, so it stays. It remains the largest single known
Windows size item.

## Validated facts versus environment limitations

Kept separate deliberately.

**Validated on this host, on the real artifact:** the frozen Windows build
produces from the `build.yml` path; its inventory is complete from both the
tree and the ZIP; Korean OCR, Kiwi, KRDICT and the Control Center all work in
the frozen process; the PowerShell handoff executes for real on a Hangul path
with spaces, in both the accepted and the rejected direction; the rollback
defect reproduces and the fix resolves it.

**Environment limitations, not product statements:** the two symlink tests
cannot run without `SeCreateSymbolicLinkPrivilege`; the broken MSYS2 `cc` is a
property of this machine; the pt-BR locale is what made the `reconfigure`
defect observable here rather than something Windows-specific in principle;
and the one 420 s startup timeout below is attributable to the host, not the
application.

## Remaining native Windows risks

1. **`Stop-Process` ends the parent only.** QtWebEngine helper processes
   normally exit with it, and the 30 × 1 s rename retry absorbs the gap. A
   helper holding files longer than 30 s would still fail the restore — exit 1
   with the backup intact, which is the pre-existing safe outcome, not a
   regression.
2. **The two symlink tests are unrunnable on a Windows account without
   Developer Mode or administrator rights.** They are covered only by CI.
3. **Popup, hover, hotkey, tray, capture and hide/restore remain unexercised in
   a frozen artifact on Windows.** The packaged self-check has only `worker`
   and `ui` modes; this is the pre-existing gap recorded as risk 3 of the wave
   handoff and it is unchanged.
4. **No Windows latency claim is made.** Nothing in this run measured hover or
   lookup timing on Windows.
5. **The rejected-build case was reproduced through a version mismatch**, which
   is the cheapest way to force it. The production trigger is a build that
   starts but never acknowledges within `READY_WAIT_SECONDS`; the code path is
   the same one, but that specific timing was not waited out on the frozen
   build.

## POSIX and macOS rollback — separate remaining risk, unchanged here

`mv` renames a directory whose program is running, so the POSIX and macOS
rollback still succeeds where the Windows one failed. The residual issue there
is different and milder: **nothing stops the rejected build**, so the user ends
with the restored build and the rejected one both running. On macOS the
relaunch goes through `/usr/bin/open`, which yields no pid, so there is no
process to stop without adding a lookup the script does not currently do.

This was deliberately **not changed in this run**: the mandate was Windows, the
defect is a different one, and it cannot be executed or verified on this host.
Recorded here so it is not lost.

## The Defender cold-start observation

On the very first full-suite run in the brand-new 5 GB release venv,
`tests/integration/test_desktop_startup.py::test_the_desktop_opens_and_reaches_ready_without_starting_capture`
timed out at its 420 s bound. Run alone immediately afterwards it passed in
**17.39 s**, and it passed in every subsequent full run.

The pattern — one very slow first touch of a freshly written multi-gigabyte
tree, then normal timing — is consistent with Windows Defender scanning newly
written files on first execution, not with the application hanging. Recorded
because a CI runner installing a fresh environment on every job could plausibly
hit the same bound, and because the alternative reading (a real startup hang)
would matter a great deal. Nothing was changed in response; if this recurs on
the runner, the first place to look is the timeout, not the desktop.

## Relevant files / diff areas

- `packages/hanly-app/src/hanly_app/app_update_handoff.py` — Windows rollback
- `tests/test_app_update_handoff.py` — probe, compiler selection, new test
- `tools/krdict/__init__.py`, `tools/dev_lookup.py` — stream reconfiguration
- `tests/krdict/test_console_output.py` — new

## Suggested review targets

- The `Stop-Hanly` boundary: whether stopping only the parent is sufficient for
  a frozen build with QtWebEngine helpers, and whether the retry bound is right.
- Whether the POSIX and macOS rollback should also stop the rejected build, and
  what identifies the process on macOS given `open` returns no pid.
- `_builds_programs` runs a compile at module import. Confirm the cost and the
  skip semantics are acceptable, and that a silently-skipping native suite is
  visible enough on CI.
- Whether any other tool reconfigures a stream without naming `errors`.

## Review assignment

Human-selected after implementation. Not started.
