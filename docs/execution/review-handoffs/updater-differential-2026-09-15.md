# Updater: differential installation and visible progress — Review Handoff

## Bundle

- Plan: `docs/execution/updater-differential-execution-plan-2026-09-15.md`
  (Gate-tier, Phase A only), from
  `docs/execution/reports/updater-in-place-differential-2026-09-15.md`
- Implementation ecosystem: Claude Opus 5, directly, one session
- Date: 2026-09-15
- Host: Windows 10 Enterprise 19045 (x86_64), Python 3.13 in `.venv`
- Commit at start: `52f1325`, working tree clean apart from the two planning
  documents. **Nothing committed, pushed, merged, tagged, or published.**

## What changed, in one sentence

Windows now installs an update by replacing only the files that differ, in
place, at the same installation path; the crash that made the previous updater
fail is fixed for every platform; and the Control Center shows real sizes,
counts, and activity instead of a phase label.

---

## 1. The defect that stopped the reported update

`packages/hanly-app/src/hanly_app/cli.py:145` — `_leave` flushed
`sys.stdout`/`sys.stderr` without allowing for their being `None`, which is what
PyInstaller leaves them as in a `console=False` build
([PyInstaller docs](https://pyinstaller.org/en/latest/common-issues-and-pitfalls.html#sys-stdin-sys-stdout-and-sys-stderr-in-noconsole-windowed-applications-windows-only)).
The `AttributeError` escaped `main`, so `_terminate_without_unloading` and
`os._exit` never ran and the bootloader held a modal crash dialog. The update
handoff was meanwhile waiting on `Get-Process -Id $OldProcessId` with a
120-second bound, so it timed out and swapped nothing.

Fixed by skipping absent streams and widening the caught tuple to
`AttributeError`. Regression: `tests/test_capture_selector.py::
test_a_windowed_build_without_streams_still_ends_its_process`, parametrized over
both streams absent and one absent, asserting that both termination steps still
ran. Proved against the real frozen windowed build in §6.

**This fires on every quit of a windowed build**, not only during an update. The
update is where it did visible damage, because it is the one path with something
waiting on the exit.

---

## 2. Delivery and installation design as built

### Release artifacts (Windows only)

`tools/update_artifacts.py` produces three documents from the finished frozen
tree, and `tools/build_package.py` runs it as part of a Windows build:

| Asset | Contents |
|---|---|
| `hanly-desktop-windows.manifest.json` | every managed file: path, SHA-256, size, component label |
| `hanly-desktop-windows.update.json` | target identity, manifest digest, full-archive reference, optional delta descriptor |
| `hanly-desktop-windows-from-<base>-to-<target>.delta.zip` | only the files differing from one named previous **published** build |

The same inventory is written into the build as `.hanly-manifest.json` before
archiving, so a fresh installation knows what it is made of without asking the
network.

Identity is `product/platform/architecture/version/build_id`, where `build_id`
is a 16-hex fingerprint over the sorted `(path, sha256)` pairs. Version alone is
not identity: two builds of one tag differ, and a delta assembled against the
wrong one produces a tree that passes every per-file digest check and is still
not the published build.

The delta's base is the previous release's **published** manifest, proved
against that release's `SHA256SUMS` before use
(`update_artifacts.load_base_manifest`). A missing or unusable predecessor
records a reason and publishes without a delta; it never fails a release.

### Client selection

`DifferentialInstaller.prepare` pins the checked release, downloads
`SHA256SUMS`, `update.json`, and `manifest.json` — **and no payload** — verifies
each against the release's checksums, then hashes the installation in one
sequential worker and produces an `UpdatePlan`.

The delta is used only when its payload covers every changed-or-missing target
file this installation actually needs. That coverage check is what catches the
case the investigation got wrong: a delta is the diff between two *published*
builds, so a file corrupted or removed since install is missing here and
unchanged there, and the delta does not carry it. Anything uncovered falls back
to the full archive **as a source of files** — inspected, and only the needed
members extracted. There is no return to unpacking a replacement tree.

- Unmanaged files are preserved. A target path occupied by a file the previous
  manifest did not own is reported as a collision and the update stops.
- Deletions come only from paths the verified previous manifest owned and the
  target does not have. An installation with no inventory deletes nothing.
- Disk preflight covers payload + staged files + backups + a 256 MB margin.

### Durable apply and recovery

`app_update_journal.py` writes one immutable `plan.json` and an append-only
`progress.jsonl` (flushed and `fsync`ed before each mutation) inside
`<installation>/.hanly-update/<transaction>/`, with `payload/NNNN` and
`backup/NNNN` beside them. Staged files are named by operation index rather than
mirroring the tree, so a payload path is always short and ASCII whatever the
installation is called.

`app_update_helper.py` renders the PowerShell program that applies it. It uses
Windows PowerShell and the .NET Framework and nothing else — no Python, no
Hanly, no Qt, no Torch, no DLL from the installation — which is asserted by
`tests/test_app_update_helper.py` and by a case in the native suite.

**Correctness comes from the filesystem, not the journal.** Every apply and
rollback step reads what is there before acting, so a step interrupted between
the move succeeding and the record of it replays to the same result. The journal
bounds the work, drives the progress window, and tells a person what happened.

```
prepared → helper-ready → waiting-for-exit → applying → awaiting-startup
                                                   → committed → cleanup
                                  failure → rolling-back → restored
                                          → recovery-required
```

- Additions and replacements are applied before deletions, so an interruption
  leaves more of a working installation rather than less.
- Processes are identified by the executable they are running being inside the
  installation, not by name, so the shell, the Control Center, and the lookup
  child are all waited for and nothing unrelated is ever touched.
- All moves use `\\?\`-prefixed .NET calls with bounded retries, so long paths
  inside `_internal` do not depend on a machine-wide setting.
- `InstallLock` is a per-installation, cross-process lock; a lock whose owner is
  gone is taken over, so one crash is not permanent.
- `await_claim` blocks the quit until the helper has written its ownership
  claim, so the application never closes leaving a staged update with nobody to
  apply it.

**Power-loss limit, stated plainly:** this is not an atomic whole-tree update. A
verified copy of the helper, a pointer to the transaction, and a
`Finish Hanly update.cmd` are written to `%LOCALAPPDATA%\Hanly\recovery\` —
outside the installation — before the first file moves. That launcher finishes
or undoes the transaction with nothing but Windows, which is the route when the
installation itself will not start. When Hanly *can* start,
`application.settle_pending_update` runs before Qt, before settings, before
anything is opened.

`owned_cleanup` was extended to know about `<installation>/.hanly-update` and to
report rather than reclaim any transaction holding a `backup/` or a `plan.json`.
Disk is never a reason to delete somebody's only copy of a working file.

---

## 3. UX

The Updates panel keeps the existing Control Center styling; only Updates
changed. `update_coordinator` now exposes `plan`, `awaiting_confirmation`,
`cancellable`, and a bounded `activity` tail.

| Stage | What the page shows |
|---|---|
| Available | installed → target version, notes, **Update now** |
| Preparing | "Checking installed files…", with byte counters; Cancel |
| Confirm | **Download full update — \<size\>** and the reason, when the small download cannot be used here |
| Downloading | `42% downloaded · 18.4 MB / 43.8 MB · 25.4 MB remaining`; Cancel |
| Unpacking | "Preparing files…" with file counts |
| Installing | the helper's own window: `Replacing files 12 / 37` and the current path |
| Starting | `Starting Hanly <version>…` — no success mark yet |
| Failure | the reason, restoring progress, and the final restored/recovery result |

Two deliberate decisions:

- **A full download always asks first.** Discovery costs no payload and reports
  no size, so the only click that has authorized a size is the one for a
  differential update. A full archive is hundreds of megabytes nobody was shown,
  whether the release published no delta or this installation cannot use the one
  it did. Declining releases the plan and the lock without installing.
- **Progress is coalesced** to at most five snapshots a second
  (`PROGRESS_INTERVAL_SECONDS`), a change of phase always lands, and the
  activity tail is bounded at 120 entries and rebuilt rather than appended to —
  the snapshot crosses a pipe on every poll.

The helper's progress window is a courtesy, not part of the transaction: it is
created inside a `try`, every update to it is guarded, closing it hides it, and
a session with no desktop runs the whole update with no window and no difference
in outcome.

---

## 4. Bounded scope, kept

- **Windows only** for the differential path. macOS and Linux keep the
  whole-bundle swap in `app_update.py` / `app_update_handoff.py`, untouched
  except by the shared `_leave` fix; their published sizes are labelled as the
  full archive in `packaging/README.md`. macOS bundle identity, signature
  checks, links, and `open`-based launch are unchanged.
- **One direct delta**, from the immediately preceding published release. No
  chains.
- **File-level replacement.** No bsdiff, no chunk hosting, no per-file release
  assets, no runtime pip, no new update service.
- No OCR tuning, no dependency pruning, no background updater, no cache sweeping.
  KRDICT resource updates keep their existing independent path and messages.

Engine boundaries are intact: everything added is in `hanly_app` or `tools`, and
`tests/test_package_boundary.py` still passes. There is still exactly one
desktop entry point; `tests/test_packaging.py` still passes.

---

## 5. Files

| File | Change |
|---|---|
| `packages/hanly-app/src/hanly_app/cli.py` | the `_leave` fix |
| `app_manifest.py` | **new** — manifest, update metadata, delta descriptor, path rules |
| `app_inventory.py` | **new** — hashing a tree into that inventory |
| `app_update_plan.py` | **new** — the add/replace/delete diff and payload selection |
| `app_update_install.py` | **new** — metadata, plan, download, selective extraction, preflight |
| `app_update_journal.py` | **new** — the durable record, the paths, the install lock |
| `app_update_helper.py` | **new** — the native apply/rollback program and recovery copy |
| `app_update_runner.py` | **new** — the desktop seam: lock, claim, settle |
| `update_coordinator.py` | two-stage install, confirmation, cancel, activity, coalescing |
| `control_center.py`, `control_center_process.py` | `cancel_update`, `confirm_full` |
| `assets/control_center/*` | the stage table, byte counters, details |
| `application.py` | Windows installer wiring; settle before anything opens |
| `owned_cleanup.py`, `paths.py` | the in-place working root; the recovery directory |
| `tools/update_artifacts.py` | **new** — the release producer |
| `tools/build_package.py` | runs it on Windows, before archiving |
| `.github/workflows/build.yml` | fetches the previous manifest, uploads the new assets |
| `.github/workflows/release.yml` | validates, checksums, and publishes them |
| `docs/CODE-MAP.md`, `packaging/README.md` | describe what is actually there |

---

## 6. Validation

All commands from `.venv/Scripts/python.exe` on the host named above.

### Gates

| Gate | Result |
|---|---|
| `-m pytest` (everything) | **1379 passed, 11 skipped, 1 failed** — the one failure is the packaged worker below |
| `-m pytest` (portable only) | **1278 passed, 6 skipped** |
| `-m ruff check packages packaging tests tools benchmarks` | **All checks passed** |
| `-m mypy packages packaging tests tools benchmarks` | **no issues in 229 source files** |
| `tools/build_package.py --platform windows` | **exit 0**; produced the archive, the manifest, and the update metadata |
| `tests/native --suite native` | **37 passed, 3 skipped**; the Windows set alone is 11 passed |
| `tests/packaged --suite packaged` | **2 passed, 1 failed** — see *Unresolved* |

### The real frozen Windows update

A 0.5.1 build was produced by the real build command, copied to a disposable
installation, and updated to 0.5.2 through the production path:
`InPlaceUpdateRunner.prepare` → `.install` → the shipped helper → the real
frozen build answering `--update-ready`. Only the Control Center button was
replaced, by calling the same runner the bridge calls.

The 0.5.2 release was derived from the 0.5.1 build with controlled changes —
the two `dist-info` directories renamed for the version bump, one asset edited,
one added — and its delta assembled by the production `assemble_delta`. A
second PyInstaller run needs 1.4 GB the host did not have free. Every large
dependency is byte-identical between the two, which is the shape of a patch
release. None of it is committed.

The probe was run twice: once against the first implementation, and again
against the hardened one described under *Findings*, with the same result and
the same figures.

**Outcome: committed.** `result.json` reads
`{"outcome": "committed", "detail": "Hanly 0.5.2 started."}`, the installation
now carries `hanly_app-0.5.2.dist-info`, and the relaunched build was observed
running with its Control Center and QtWebEngine children.

### Measured, same target content, same machine

| | Whole-bundle delivery | This bundle's differential path |
|---|---|---|
| Downloaded | **648,557,160 B** (the archive this build produced) | **1,062,979 B** — delta 8,187 + manifest 1,052,496 + update.json 1,880 + SHA256SUMS 416 |
| Application payload fetched before the user clicked | the whole archive | **none** |
| Files written into the installation | 6,118 extracted, then a directory swap | **17 written, 15 removed** |
| Bytes written | ~1.47 GB | **15,845 B** |
| Peak scratch in the transaction | ~648 MB archive + 1.47 GB staged tree | **43,756 B** |
| Unchanged files rewritten | all of them | **zero** |

Timings, from the transaction journal and a direct measurement:

| Stage | Elapsed |
|---|---|
| Inspect the installation (6,118 files, 1.47 GB hashed, one sequential worker) | **9.53 s** (154 MB/s) |
| Download, verify, unpack, journal | **3.70 s** |
| Apply 32 operations | **0.26 s** |
| Relaunch and receive the startup acknowledgement | **1.32 s** |

The 609 MB in the investigation is context, not a controlled baseline: it was
not remeasured, and the row above compares the two ways of delivering *this*
build's content on *this* machine.

**Where the remaining download goes:** 99% of it is the manifest, which is
1.05 MB of uncompressed JSON for 6,118 files. Compressing it or serving a
compact form is the obvious next reduction and is deliberately not in this
bundle — three orders of magnitude were already the point.

One earlier full run showed eight transient failures in
`test_app_update_differential.py`; it overlapped a native-suite background run
on a host with under 2 GB free disk, and the module passes in isolation and in
two consecutive clean full runs since. Recorded here rather than left out, but
treated as resource contention rather than an ordering defect.

### Native cases added

`tests/native/windows/test_update_helper_windows.py` runs the shipped
PowerShell over throwaway installations built from two compiled programs:

- only the changed files move, the new build starts, and everything else is
  byte-identical afterwards;
- a build that starts and reports the wrong version is rolled back *while it is
  still holding the executable Windows will not let go of*;
- a transaction interrupted between a filesystem move and its journal record
  settles to the same installation on a second run;
- the helper's body loads nothing from the tree it is changing;
- a file **past 260 characters** inside `_internal` is replaced;
- every move survives an installation path with spaces and Hangul. That case
  ends in a rollback rather than a commit, and the docstring says why: the
  replacement is a C program receiving `--update-ready` through an ANSI
  `argv`, which is the fixture's limit, not the helper's.

`tests/native/windows/test_update_spawn_windows.py` proves the helper is
actually started and outlives the process that started it — see the second
defect below.

---

## 7. Migration

`0.5.0` and `0.5.1` carry no inventory, and their own `_leave` cannot exit a
windowed build, so publishing a fixed target does not make their updater work.
**The first update from either is a manual replacement**, documented in
`packaging/README.md`: close Hanly, unpack `hanly-desktop-windows.zip` over the
existing `hanly-desktop` directory, keep the path. Settings, diagnostics, and
KRDICT are in the per-user profile and are unaffected.

That build carries `.hanly-manifest.json`, and every update after it is an
ordinary differential one. The first manifest-aware release publishes no delta
(there is no published predecessor with a manifest); the one after it does.

The evidence from the reported failure —
`C:\Users\Thiago\Downloads\hanly050\.hanly-update-efqyhaae`, a complete verified
0.5.1 build — was **not** touched by this work.

---

## 8. Findings

### Fixed now

**A second, independent defect would have stopped the update even with `_leave`
fixed.** `app_update_handoff.spawn_detached` started the helper with
`DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW`. A PowerShell
started with **no console at all** exits zero having run none of its script, so
the swap never happened and nothing anywhere said why. Measured directly on this
host, one flag at a time:

| Creation flags | Child ran its script |
|---|---|
| none | yes |
| `CREATE_NEW_PROCESS_GROUP` | yes |
| `CREATE_NO_WINDOW` | yes |
| `CREATE_NEW_PROCESS_GROUP \| CREATE_NO_WINDOW` | yes |
| **`DETACHED_PROCESS`** | **no** |
| `DETACHED_PROCESS \| CREATE_NEW_PROCESS_GROUP \| CREATE_NO_WINDOW` | **no** |

`DETACHED_PROCESS` is gone. A process outlives its parent on Windows regardless;
detaching the console is not what makes that true, and both properties are now
asserted by real spawns in `tests/native/windows/test_update_spawn_windows.py`.

This was found by running the probe, not by reading the code, and it is the
reason the plan's insistence on a real frozen update was right.

**The relaunched build would have started a second helper over the live
transaction.** `settle_pending_update` runs before Qt on every launch, including
the launch the helper just performed while it waits for `--update-ready`. The
transaction is legitimately unsettled at that moment, so the first version of
`_hand_back` would have called `recover_pending` and put two programs on the same
files. A live helper now keeps its own transaction; covered by
`test_the_build_a_helper_just_launched_does_not_start_a_second_one`.

**A full download is always confirmed first.** The first version asked only when
a delta had been advertised and could not be used. Discovery costs no payload and
reports no size, so a release that simply publishes no delta would have started
hundreds of megabytes nobody was shown — the behaviour this whole bundle exists
to remove.

**Metadata is fetched to the system temporary directory,** not into the
installation. Preparing happens before the user has committed to anything, and an
installation under `Program Files` is not ours to write to at that point.

### Unresolved

**The packaged worker check fails on this host, and I could not attribute it to
this bundle.**

```
EasyOCRProviderError: EasyOCR is unavailable: [WinError 1114] ...
Error loading "…\_internal\torch\lib\c10.dll" or one of its dependencies.
```

It fails in about four seconds, deterministically, across three runs. What is
known: the other two packaged cases pass, including the dependency inventory and
the Control Center window; the same frozen build launched fully during the probe
with its Control Center and QtWebEngine children; `import torch` (2.13.0+cpu)
succeeds in the venv the build was made from; and **nothing in this diff touches
`packaging/hanly-desktop.spec`, `packaging/release-constraints.txt`, the runtime
hook, or any import torch depends on** — `git status packaging/` shows only
`README.md`. The host was also at 1.5 GB free RAM and under 2 GB free disk
throughout.

I am not claiming this gate passes, and I am not claiming it is environmental.
It needs a separate look on a machine with room, ideally against a build from
before this branch.

### Found and fixed in the review pass

A second pass over the new modules, after the first probe, turned up five more:

**A member could decompress past its declared size.** `_extract_member` copied
a whole member and checked its digest afterwards, so a payload whose entry
expanded far beyond the manifest's size would fill the disk before anything
noticed. The manifest states each file's exact size, so extraction now streams
with a running hash and abandons the member the moment it exceeds it. The same
change removes the second full read the digest check used to cost — on a
full-archive fallback that halves the I/O.

**An addition could destroy a file it did not own.** If something appeared at a
target path between planning and applying, the `add` branch moved the payload
over it, deleting a file that has no backup — the one genuinely unrecoverable
outcome in the whole design. An addition whose payload is still staged now
refuses a path that is already occupied, and the rollback only removes a file
it can prove it wrote (the payload is gone). Covered by
`test_an_addition_never_overwrites_a_file_that_appeared_since_planning`.

**Two guards were silently disabled by lost backslashes.** The path-segment
check rendered as `Contains('')`, which matches everything, and
`Remove-EmptyParents` compared against a root with no separator. Both now use
`[System.IO.Path]` APIs so no backslash literal appears in the template at all.
The first version of these guards failed six native cases immediately, which is
how they were caught.

**The install lock was a read followed by a write.** Two processes arriving
together could both find it free. It is now created with `O_EXCL`, falling back
to a takeover only when the recorded owner is provably gone.

**The coordinator recognized a cancellation by class name.** Renaming
`UpdateCancelled` would have silently turned "the update was stopped" into
"update failed". It now reads a `cancelled` marker off the exception, which is
consistent with knowing the installer only by its protocol.

Also removed: `resolve_within`, `free_space`, `same_volume`, and `summarize`,
none of which any product code called.

### Deferred, with a revisit trigger

| Deferred | Revisit when |
|---|---|
| Compressing the 1.05 MB manifest, or serving a compact form | it is 99% of the remaining download; revisit if the bundle's file count grows or slow connections are reported |
| Chains of deltas across skipped releases | a user reports a large fallback download after skipping releases |
| Binary (bsdiff) deltas within a file | a release bumps a large dependency, where one 371 MB file dominates the delta |
| macOS and Linux differential updates | Windows has proven the shape; macOS needs the signature question answered properly |
| A helper that dies between launching the candidate and reading the acknowledgement leaves an unsettled transaction the next launch recovers by stopping the running app | a real occurrence; the state is genuinely unsettled, so finishing it is correct, but the user loses their session |

### Dismissed

- *Removing the orphaned 1.4 GB in the user's Downloads.* The plan names it as
  evidence. Untouched.
- *A supervisor for the helper.* `await_claim` already refuses to quit until the
  helper owns the transaction, which covers the failure that mattered.

---

## 9. Status

Phase A is complete and stops here. **Nothing is committed, pushed, merged,
tagged, or published**, and no publishing workflow was triggered. HAN-42 is
moved to In Review, not Done.

Waiting for Thiago's review.
