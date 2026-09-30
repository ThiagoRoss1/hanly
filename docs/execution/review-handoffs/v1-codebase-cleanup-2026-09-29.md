# V1 codebase organization and cleanup — Review Handoff

Status: Phase A implementation complete. Phase B has not started.

## Scope and commits

Branch: `clean/arch-optimization`, starting at `5c510e5`. The existing eight
cleanup-wave commits remain untouched. Nothing in this session was pushed,
merged, tagged, or released. Each part has its own commit:

1. `139032d` — organize 39 desktop modules into six feature packages.
2. `e367d81` — remove the orphaned clipping-recovery module and its tests.
3. This handoff's commit — simplify comments and curate historical Markdown.

The root `hanly_app` symbol exports and `hanly_app.cli:main` remain unchanged.
The `hanly` engine still has no dependency on `hanly-app`. No backend, OCR
model, dictionary, provider contract, or runtime behavior was intentionally
changed. The third part contains no executable statement changes.

## What changed

- Desktop files now live under `acquisition/`, `hover/`, `lookup/`, `popup/`,
  `control_center/`, and `updates/`. Imports, lazy exports, tests, tools,
  packaging hook, release workflow import, and `docs/CODE-MAP.md` follow the
  move. Package initializers make PyInstaller discovery explicit.
- `capture_recovery.py` had no production caller after its one-shot recapture
  was rolled back; only its own test imported it. The module and that test were
  removed. Historical measurements remain in the September checkpoints.
- All authored Python comment blocks in source and tests are now at most three
  lines. Long implementation history was condensed to the invariant or
  external-library reason; a C fixture's `#include` directives were untouched.
- Twelve completed execution plans and reports moved from the execution root
  into `plans/` or `reports/`, with relative links repaired and stale status
  claims marked historical. The HAN-43/44 report keeps its review findings and
  commit table, but omits 7,540 lines of Git diff already in history. An
  obsolete, non-applying review patch was removed.
- Sixteen user-home prefixes in current Markdown were replaced with generic
  placeholders. No history rewrite was attempted; older Git commits still
  contain their original documentation.

README editorial work and the substantive AGENTS.md/CLAUDE.md rewrite remain
reserved for the separately planned session. Those two files received only
mechanical path repairs in Part 1.

## Validation and limits

- Entry portable baseline: 2,364 passed, 4 failed, 3 skipped. After Part 1,
  the result matched exactly. Final run: 2,356 passed, 4 failed, 3 skipped;
  the eight fewer passes are the removed orphan-module tests. The same four
  failures predate this session: two process-probe cases cannot call sandboxed
  `ps`, and two Vision fixtures return no regions on this host.
- Ruff and mypy are clean after Part 3 (305 checked files). Python 3.10
  compilation and the CLI help entry point passed after Part 1. Focused
  capture/microscope tests passed after Part 2 (103/103).
- The macOS frozen app and ZIP were built from `139032d`, confirmed by the
  embedded build stamp. ZIP reconstruction, inventory, and packaged worker
  runtime/OCR/morphology/dictionary/version checks passed. `hdiutil` refused
  DMG creation with “device not configured”; packaged Control Center window
  smoke aborted in the sandboxed Qt/WebEngine runtime. Neither is claimed as
  a passing final package check, and the ZIP is not stamped with the final
  comment/docs commit.
- Both capture-prompt shutdown cases pass on macOS with Qt offscreen. The
  native GUI aborts here, so the supplied Windows CI failures remain open:
  117 passed, 33 skipped, two shutdown-test failures (prompt took 9.843 s;
  region quit callback never ran). No unverified Windows fix was made.
- A Markdown link scan found 68 valid relative links outside code fences and
  zero unresolved. The current Markdown scan found no user-home prefixes,
  email addresses, or credential markers matching the documented patterns.

## Phase B review targets

1. Recheck relocated imports, spawn references, and PyInstaller discovery on
   Windows and Linux; remote CI is pending until the human pushes.
2. Confirm that no supported developer workflow still relies on the removed
   clipping-recovery helper. Do not revive its rolled-back recapture implicitly.
3. Review the Markdown moves and privacy scan against current tracked files;
   historical snapshots intentionally keep their original claims as evidence.
4. Diagnose the Windows Qt shutdown failures on a real Windows runner before
   selecting a selector or test correction. macOS offscreen passing is not
   evidence of a Windows fix.

Stop here for human review authorization. No Phase B review, push, merge, or
release is implied by this handoff.

## Post-Bundle Review Outcome — Phase B Part 1

Reviewer: Codex, authorized by the human on 2026-09-29. Scope: general
codebase and macOS only. Status: **conditionally accepted for Part 1**. No
confirmed executable regression was found in the three Phase A commits. This
is not a Windows verdict or a release approval.

### Fixed now

- `971a183` corrects the current `AGENTS.md` and `CLAUDE.md` spawn-module path
  to `control_center/process.py`. A package-walker regression test now checks
  that the relocated Control Center, lookup, transport, and updater modules are
  discoverable by name. The six package-import tests pass.

### Deferred considerations and revisit triggers

- **Windows Part 2:** The latest Windows CI run, as supplied by the human, had
  one failure: the prompt case in `test_capture_prompt_shutdown.py` took
  **3.344 s** against a **3 s** limit. An earlier run failed differently. Diagnose
  on a Windows PC before changing a selector, timeout, or shutdown path. No
  Windows fix or native validation was attempted here.
- **macOS GUI:** Native WebEngine cases fail with sandbox-denied Chromium Mach
  port registration, and the reconstructed frozen UI self-check aborts while
  creating `QWebEngineProfile`. The user's 16:42 crash report is the frozen
  test's `hanly-desktop` PID 35165, parented by Python, with `SIGABRT` on the
  Qt WebEngine/AppKit stack. Revisit on an unrestricted visible macOS session
  before claiming the Control Center works from this build.
- **macOS disk image:** The fresh build produced a ZIP, but `hdiutil create`
  returned “device not configured.” Revisit DMG creation and reconstruction on
  a host where disk-image devices are available. Do not treat the ZIP check as
  DMG validation.

### Dismissed with evidence

- The four portable failures are present at `5c510e5` as well as the reviewed
  branch: two `ps` probes receive sandbox `Operation not permitted`, and two
  Vision image fixtures return no regions. They are not Phase A regressions.
  The macOS handoff test's empty launch list also reproduces at `5c510e5`.
- The root package exports the same 109 names as `5c510e5`; every export
  resolves to its defining relocated module. The single CLI entry point still
  runs `multiprocessing.freeze_support()` first. Source searches found no
  executable references to removed module names or `capture_recovery`; the
  latter had no production caller and its removed tests covered only itself.
  Both child managers still use `lookup/transport.py` and `spawn`.
- Comment changes in the third commit have the same non-comment Python syntax
  trees. The three generated updater script constants differ only in comment
  lines; their non-comment lines are byte-identical. No executable behavior
  change was found there.
- A scan of 134 tracked Markdown files found 73 relative links outside code
  fences and no missing targets. Two privacy-pattern hits are illustrative
  `C:\\Users\\John Smith` and `C:\\Users\\First Last` paths in a historical
  PowerShell finding, not personal home paths. Historical reports retain old
  source filenames as dated evidence.

### Validation performed

| Check | Result |
| --- | --- |
| Focused imports, packaging, CI, capture, application, process tests | 365 passed |
| Package-import tests after the review test | 6 passed |
| Ruff; mypy | Clean; mypy checked 305 source files |
| Portable suite after the review test | 2,357 passed, 4 failed, 3 skipped in 93.36 s; all four failures reproduced directly from `5c510e5` |
| Native suite with Qt offscreen | Interrupted after 249.45 s: 43 passed, 6 failed, 2 skipped. Five failures involve denied `ps` or Qt WebEngine startup; the macOS handoff failure reproduces at `5c510e5` (69.35 s). The next native test did not complete. |
| Focused native capture-prompt shutdown and lookup spawn | 2 passed, 1 skipped |
| Fresh macOS freeze from `28dfd89` | PyInstaller bundle and 529 MiB ZIP built; embedded source stamp `28dfd890a360597ec9a892c2295246dc297fff41`. Initial attempt hit the sandboxed default cache; retry used `PYINSTALLER_CONFIG_DIR` under `/private/tmp`. DMG failed as above. The later review commit changes only docs and a test. |
| ZIP reconstruction; frozen inventory; signature; frozen CLI help | Passed on the reconstructed app |
| Packaged suite on reconstructed ZIP | Inventory, source identity, and isolated worker checks: 3 passed. Control Center UI check: 1 failed with `SIGABRT` in this sandbox. |

### Windows Part 2 checklist

1. On the Windows PC, inspect this branch and the prior Windows CI logs. Keep
   the 3.344 s prompt case and the earlier, different failure separate.
2. Run the portable, focused shutdown, and full native Windows suites; observe
   the prompt's elapsed time and quit callback under a real window server.
3. Verify relocated imports and spawn targets in a fresh frozen Windows build;
   run inventory, worker, Control Center UI, and packaged tests against that
   build. Check the release workflow's `updates.resource_service` import.
4. Classify any reproducible Windows defect, add a regression test, and make a
   Windows-only correction in Part 2. Do not infer a fix from macOS offscreen
   results.

Part 1 stops at this handoff. Nothing was pushed, merged, tagged, or released.

## Phase B Part 1 continuation — final macOS validation (2026-09-30)

**Verdict: macOS validation complete for this branch head.** The packaged
application reconstructed independently from the ZIP and DMG passed the
inventory, source-identity, worker, and Control Center UI gates. Both artifacts
match the published manifest and retain valid bundle signatures. This verdict
does not cover Windows, notarization, or a future release build.

The worktree was clean at `e461fcd3ca9cd4046c54f640e67c7c4b5f5d7267`
before this investigation. The fresh build's embedded source stamp names that
exact commit (version `0.9.0`, macOS arm64). No product, packaging, or test
defect was confirmed, so no code fix or regression-test commit was made.

### The two failures

- **DMG creation — environment restriction.** The production `hdiutil create`
  command failed with “device not configured” under the restricted shell. The
  same command on a one-file source folder succeeded with normal macOS disk
  access. Running `tools/build_package.py` with that access then created the
  full 631,715,759-byte DMG. The normal release check mounted it read-only,
  found `Hanly.app`, detached it, and reconstructed the app. Both reconstructed
  trees match all 7,339 manifest entries. This rules out the build's DMG
  contents or `hdiutil` arguments as the cause of the earlier failure.
- **Control Center abort — environment restriction.** The supplied 16:42 crash
  report names PID 35165, the frozen UI test process. Its main thread aborted
  while Qt WebEngine created `QWebEngineProfile` through AppKit's application
  registration. A minimal source WebEngine native test in the restricted shell
  failed with `bootstrap_check_in ... MachPortRendezvousServer: Permission
  denied (1100)`; with normal GUI access it passed 2/2. The *same prior frozen
  app* that aborted in the restricted shell passed its Control Center UI test
  with normal access. The newly built ZIP and DMG apps each passed the full
  packaged gate, including document, controls, and bridge stages. Source tests
  alone would not establish this result; the frozen product was exercised.

### Commands and results

All commands below used `.venv/bin/python` on macOS 26.6.2 arm64. The build,
DMG mounting, native GUI tests, and packaged tests ran with normal host access;
PyInstaller used `PYINSTALLER_CONFIG_DIR=/private/tmp/hanly-pyinstaller-final`.
The two `HANLY_PACKAGED_APP` values are shown with `$PWD` so the commands
resolve to the same absolute paths without recording a personal home directory.

| Command or check | Result |
| --- | --- |
| `PYINSTALLER_CONFIG_DIR=/private/tmp/hanly-pyinstaller-final .venv/bin/python tools/build_package.py` | Exit 0; ZIP, DMG, release manifest and descriptor produced from `e461fcd` |
| `.venv/bin/python tools/smoke_packaged_runtime.py --from-archive dist/hanly-desktop-macos.zip --reconstruct-into dist/final-macos-zip --reconstruct-only` | Passed |
| `.venv/bin/python tools/smoke_packaged_runtime.py --disk-image dist/hanly-desktop-macos.dmg` | Passed; image contains `Hanly.app` |
| `.venv/bin/python tools/smoke_packaged_runtime.py --from-disk-image dist/hanly-desktop-macos.dmg --reconstruct-into dist/final-macos-dmg --reconstruct-only` | Passed |
| `.venv/bin/python tools/smoke_packaged_runtime.py dist/final-macos-zip/Hanly.app --against-manifest dist/release/macos/manifest.json --inventory-only` | Passed; 7,339 entries, no missing, differing, or unexpected entries |
| `.venv/bin/python tools/smoke_packaged_runtime.py dist/final-macos-dmg/Hanly.app --against-manifest dist/release/macos/manifest.json --inventory-only` | Same result; all required runtime inputs present in both |
| `codesign --verify --deep --strict` (each reconstructed app) | Both passed |
| `HANLY_PACKAGED_APP="$PWD/dist/final-macos-zip/Hanly.app" HANLY_EXPECTED_SOURCE_COMMIT=e461fcd3ca9cd4046c54f640e67c7c4b5f5d7267 HANLY_REQUIRE_PACKAGED=1 .venv/bin/python -m pytest --suite packaged -q --tb=short` | 4 passed in 30.36 s: inventory, source identity, isolated worker, Control Center UI |
| Same packaged command with `HANLY_PACKAGED_APP="$PWD/dist/final-macos-dmg/Hanly.app"` | 4 passed in 28.44 s |
| `.venv/bin/python -m pytest -q --tb=short tests/native/macos/test_control_center_identity.py tests/native/macos/test_update_handoff_darwin.py tests/native/shared/test_control_center_lifecycle.py tests/native/shared/test_webengine_startup.py tests/native/shared/test_capture_prompt_shutdown.py` | 9 passed in 55.57 s |
| `.venv/bin/python -m pytest --suite portable -q --tb=short` with normal host access | 2,362 passed, 2 skipped in 120.20 s. In the restricted shell it was 2,357 passed, 4 failed, 3 skipped; the four failures all passed when rerun with normal access. |
| `.venv/bin/python -m ruff check packages packaging tests tools benchmarks` | Passed |
| `.venv/bin/python -m mypy packages packaging tests tools benchmarks` | Passed; 305 source files checked |

The ZIP is 554,966,156 bytes (SHA-256
`f3bf511eef2a4978efce18d43f363490c6fda4d3ad9de8758129d8f0eaa65bd0`);
the DMG is 631,715,759 bytes (SHA-256
`bfac7f60802d8224b6426e73a0ea5ab4ec681f7a8b240a5b69827e23374225d5`,
matching the release descriptor). Build ID:
`385ce93f-3009-4c45-940f-1a6ac7a04640`.

The restricted shell still cannot validate `hdiutil` or Chromium directly.
The normal-access checks above resolve those macOS gaps. Windows shutdown
diagnosis and validation remain exclusively for Part 2. Nothing was pushed,
merged, tagged, or released.

## Phase B Part 2 — Windows review (2026-09-30)

Reviewer: Codex. Scope: Windows and `clean/arch-optimization` only. **Initial
pause verdict (superseded by the resumption below):
Windows source validation passed, but the release-package boundary remains
unverified; this branch is not ready for merge.** The worktree
started clean at `8b69d3d51d221041014f63bdde69f5a91edcaac2`, matching
`origin/clean/arch-optimization`. The sole executable-adjacent correction is
`79e2239` (`test: drive capture shutdown from visible windows`), authored by
the configured human Git identity. It changes only a native test. No product
module, architecture, or prior commit was changed. This commit has not been
pushed; a fresh CI run for it remains a human decision.

### Fixed

- **Shutdown test scheduling:** The old test started 250/700 ms action/Quit
  timers and a 3-second wall clock before the prompt existed. Its uncancelled
  5-second fallback timer also survived into the next parametrized case in the
  shared `QApplication`. A slow import, window activation, or scheduled Qt
  callback could therefore fail the clock assertion or let the prior case
  close the next case's window. The test now reacts to each window's `Show`
  event, queues the region action or Quit only after that event, and stops its
  owned timers and removes its event filter after the loop. It asserts that
  Quit reached the intended visible window, selection returned `None`, no
  window remained, the quit policy was restored, and the watchdog did not fire.
  This is a test assumption correction; no product shutdown defect was
  demonstrated. Both old cases passed in ten local Windows runs; both revised
  cases passed in ten further runs. The pre-cleanup `5c510e5` selector and
  test differ from the moved versions only in import paths and comments. The
  earlier pre-move Windows CI failures (9.843-second prompt and missing region
  Quit record) and later 3.344-second prompt failure are consistent with the
  scheduling and timer-lifetime defects, but their exact runtime sequence is
  unavailable without the original event trace.

### Dismissed with evidence

- **Windows module moves and spawn seams:** `tests/test_package_imports.py`,
  `tests/test_packaging.py`, the real lookup-child native test, and the real
  Control Center lifecycle/native page checks pass with normal host access.
  `packaging/entrypoint.py` still calls only `hanly_app.cli:main`; the release
  workflow imports `hanly_app.updates.resource_service`. The production spec
  uses `collect_submodules("hanly_app")`, and the moved packages have package
  initializers. A frozen-product verdict is recorded separately below.
- **Restricted-host native failures:** The restricted full native run had 110
  passed, 35 skipped, 7 failed: five Control Center page cases, a lookup-child
  process-inventory case denied by `Get-CimInstance`, and WebEngine startup.
  Those affected files passed with normal Windows access (9 passed, 1 skipped),
  then the full required native gate passed (119 passed, 33 platform skips).
  This directly reproduces the access distinction for this checkout.
- **Portable process cleanup and OCR import order:** The restricted
  process-tree test could not unlink a child-held stderr file; its isolated
  normal-access rerun passed. In the default full portable run, 15 developer
  benchmark cases failed importing Torch `c10.dll` after Qt had been imported.
  Fresh-process `import torch` and the isolated benchmark case passed;
  `from PyQt6.QtWidgets import QApplication; import easyocr` reproduced
  `WinError 1114`. The Windows lookup child deliberately imports OCR before
  Qt, and the moved preload module has no changed executable statements. A
  full run with that order passed (2,260 passed, 104 skips). No OCR redesign
  or benchmark change is justified by this review.

### Deferred with trigger

- **Fresh Windows CI:** The supplied handoff records the latest 3.344-second
  prompt failure and earlier pre-move 9.843-second/missing-callback failures.
  `gh` is unavailable here, direct GitHub API access was denied, and the
  connector returned no runs for the inspected commits, so original job logs
  were not independently retrieved. After the human pushes `79e2239` and the
  handoff, inspect the new `native (windows)` job. Reopen shutdown diagnosis
  if the revised test fails or product Quit fails under a real user session.
- **Host-platform mypy:** `mypy` on Windows reports 22 POSIX-only API typing
  errors in seven files; the same host limitation is recorded before this
  cleanup. The CI-target `--platform linux` command passes all 305 files.
  Revisit only if Windows mypy becomes a required gate or a new error appears.
- **Frozen Control Center:** The fresh local bundle's inventory, source commit
  identity, and frozen lookup worker pass, but its UI self-check fails importing
  `PyQt6.QtWebEngineWidgets` with Windows exception `0xc0000139` (missing
  procedure entry point); the application wraps that `ImportError` as
  `ControlCenterUnavailable`. This local environment has `PyQt6-Qt6` and
  `PyQt6-WebEngine-Qt6` 6.10.2; the release constraint requires
  `PyQt6-Qt6==6.11.2`; local hooks-contrib is 2026.6 versus the constrained
  2026.7. All named Qt DLLs are present in the bundle, and removing
  MSYS from PATH did not change the failure. The version mismatch is a plausible
  cause, **not a proven diagnosis**. Rebuild with
  `packaging/release-constraints.txt` applied, run the four packaged checks
  against the new build (preferably reconstructed from its ZIP), and compare
  against `5c510e5` in the same environment if UI still fails. Do not merge or
  declare Windows packaging complete until the frozen UI check passes or a
  proven, narrow correction is reviewed.

### Windows commands and results

Host: Windows 10 19045; Python 3.13.11; pytest 9.1.1; PyQt6/Qt 6.10.2,
WebEngine 6.10.0; Torch 2.13.0+cpu; EasyOCR 1.7.2; PyInstaller 6.22.2;
Ruff 0.16.3; mypy 2.3.1. `.venv\Scripts\python.exe` was used throughout.
Normal-access tests used temporary test profiles. The native fixture's first
`cc.exe` on PATH (`C:\msys64\mingw64\bin`) displayed a missing-entry-point
error during collection; `C:\mingw64\bin\gcc.exe` compiled a probe. The
native command removed `msys64` only from that Python process's PATH and
collected 152 cases in 0.53 seconds.

| Command or check | Result |
| --- | --- |
| `python -m pytest -q -p no:cacheprovider tests/native/shared/test_capture_prompt_shutdown.py` (ten repetitions before and after the edit) | 20/20 cases passed in each series |
| Focused normal-access rerun of the six affected native files | 9 passed, 1 platform skip in 71.40 s |
| `python -c "import os,pytest; os.environ['PATH']=';'.join(p for p in os.environ['PATH'].split(';') if 'msys64' not in p.lower()); os.environ['HANLY_REQUIRE_NATIVE']='1'; raise SystemExit(pytest.main(['--suite','native','-q','--tb=short','-p','no:cacheprovider']))"` with normal host access | 119 passed, 33 skipped in 244.20 s |
| `python -m pytest --suite portable -q --tb=short -p no:cacheprovider` with normal host access | 2,245 passed, 15 failed (`c10.dll` after Qt), 104 skipped in 196.08 s |
| `python -c "import easyocr,pytest; raise SystemExit(pytest.main(['--suite','portable','-q','--tb=short','-p','no:cacheprovider']))"` with normal host access | 2,260 passed, 104 skipped in 180.46 s |
| `python -m ruff check packages packaging tests tools benchmarks` | Passed |
| `python -m mypy packages packaging tests tools benchmarks` | 22 POSIX API typing errors on Windows; no error in the revised test |
| `python -m mypy --platform linux packages packaging tests tools benchmarks` | Passed; 305 source files |

### Frozen package and stop boundary

The build stamp targets `79e2239afb107d81951acb015116bdb026bd9258`
(version `0.9.0`, Windows x86_64, build ID
`08ccd61b-cc42-4746-b7ba-051f5169c84a`).
The first `python tools/build_package.py` attempt completed analysis but the
restricted shell could not read the local `craft_mlt_25k.pth` during COLLECT.
A direct 16-byte read succeeded with normal access. The retry command is
`$env:PYINSTALLER_CONFIG_DIR='C:\Hanly\dist\.pyinstaller-cache'; python
tools/build_package.py --no-clean` with normal host access. It completed the
onedir tree and wrote `dist/hanly-desktop-windows.zip`,
`dist/release/windows/{manifest,descriptor}.json`, and the two Windows
compatibility files. The ZIP has 6,838 entries, is 664,256,251 bytes, and has
SHA-256 `52ec2d4a2c6e2731f25cd8fa6230ebb8056e2f838442b1a5b88257f7a5d8d9f9`.
`python tools/smoke_packaged_runtime.py dist/windows/hanly-desktop
--inventory-only` passed. With `HANLY_EXPECTED_SOURCE_COMMIT` set to the full
commit above and `HANLY_REQUIRE_PACKAGED=1`, `python -m pytest --suite
packaged -q --tb=short -p no:cacheprovider` returned **3 passed, 1 failed in
15.54 s**. The failing UI stage is described above; its `window host` stage
passed, while `main window` failed before document/controls/bridge. A separate
`--window-only` run reproduced it, including after MSYS was removed from PATH.
The ZIP was not reconstructed or exercised, and the local build did not use
the release-constrained Qt wheel; both are explicit remaining checks. A
successful source native suite does not close this packaged UI gap.

**Resume Windows packaging:** Use an isolated Python 3.10 environment matching
`.github/workflows/build.yml`. Install the dev group and desktop runtime with
`-c packaging/release-constraints.txt`, prepare the two EasyOCR weights, then
run `python tools/build_package.py` with a workspace-local
`PYINSTALLER_CONFIG_DIR`. Verify the build stamp names the then-current commit;
run `HANLY_REQUIRE_PACKAGED=1` and `HANLY_EXPECTED_SOURCE_COMMIT=<that full
commit>` with `python -m pytest --suite packaged`. Reconstruct the produced
Windows ZIP into a new directory and run the same four checks with
`HANLY_PACKAGED_APP` pointing there, plus compare its tree with
`dist/release/windows/manifest.json`. If the constrained frozen UI still fails,
capture the underlying WebEngine import/DLL loader error and reproduce on
`5c510e5` with identical dependencies before classifying it as a cleanup
regression or changing packaging. Preserve the existing release ZIP as this
session's evidence until that comparison is complete.

This handoff is the stop point. The human can decide whether to push the test
commit to obtain fresh CI evidence; the branch is **not ready for a merge
decision** until a constrained Windows packaged Control Center passes. No
push, merge, tag, release, or further cleanup wave was performed.

### Windows Part 2 resumption — 2026-09-30

The human authorized resumption of the remaining package boundary. The
worktree was clean at `cbdebc59500e4f520880c33dbdd1da52c85b840f`, matching
`origin/clean/arch-optimization`: the human had pushed the shutdown-test and
initial handoff commits. General and macOS review were not repeated. No
production code or architecture was changed during this resumption.

#### Finding classifications

- **Fixed — capture shutdown test assumptions:** `79e2239` remains the only
  test correction. Original GitHub logs were now independently retrieved:
  baseline run `36509183388`, Windows job `109217318228`, records the
  9.843-second assertion and missing region callback; cleanup run
  `36536192582`, job `109300688493`, records 3.344 seconds. Current-HEAD run
  `36699193317`, job `109834338640`, passes both revised cases. The nested
  choice shutdown path also passes the complete local native suite with the
  constrained runtime. The evidence supports correction of the timer and
  readiness assumptions, without an executable shutdown fix. Original CI
  event-loop timing cannot be reconstructed from its pytest traceback.
- **Dismissed with causal evidence — frozen module/import regression:** the
  first release-constrained build still returned 3 packaged passes and one
  Control Center failure in 16.41 seconds. PE inspection found that its
  `Qt6Core.dll` imported 20 unsuffixed ICU symbols absent from the collected
  `_internal/icuuc.dll`. `Analysis-00.toc` identifies that DLL's source as
  `C:\Users\Thiago\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\poppler\Library\bin\icuuc.dll`,
  an unrelated directory injected into this host's PATH. The System32 ICU
  exports all 20 symbols. Replacing only that DLL in the constrained bundle
  changed the UI self-check from failure to all five stages passing, with
  exit code 0 and no exit timeout; the original DLL was restored afterward.
  Explicitly preloading the same incompatible ICU in the same constrained
  environment reproduced `DLL load failed while importing QtCore` and
  `ControlCenterUnavailable` on baseline `5c510e5`'s
  `hanly_app/control_center.py:81`. This is a controlled native-loader baseline
  comparison, not a full frozen baseline build. Replacing only Qt's five MSVC
  DLLs had not fixed the error. The earlier Qt-version explanation was
  therefore insufficient: the demonstrated UI failure was host DLL discovery.
  The final production build excludes only the unrelated Poppler PATH entry
  inside its Python process and applies the existing release constraints.
- **Dismissed with reproduced baseline — host mypy:** checking the archived
  `5c510e5` source with the same mypy 2.3.1 and baseline source paths produced
  the same 22 POSIX API errors in the same seven logical files (301 baseline
  files, versus 305 after cleanup). The constrained current checkout passes
  the CI `--platform linux` check. No new typing regression was found.
- **Dismissed for the constrained review environment — portable OCR import
  failure:** the default full portable suite now passes without an OCR-first
  wrapper. This environment uses Qt 6.11.2 and Torch 2.14.1; the old environment
  used Qt 6.10.2 and Torch 2.13.0. Both changed, so this result does not isolate
  one wheel as the cause of the old `c10.dll` failure. It validates the current
  release-constrained dependency set without an OCR or benchmark code change.
- **Deferred with a trigger — current Windows CI process inventory:** current
  run `36699193317` has 118 native passes, 33 skips, and one failure in
  `test_the_window_opens_closes_and_reopens_without_touching_the_shell`:
  `powershell.exe did not answer in time`. The fixture calls
  `Get-CimInstance Win32_Process` with a 15-second subprocess bound and fails
  explicitly when required inspection is unavailable. This is an observation
  failure, not evidence of leaked Control Center processes. The probe is
  byte-for-byte unchanged from `5c510e5`; the lifecycle test changes only moved
  imports. Nevertheless, the exact CI timeout was not reproduced locally and
  is **not dismissed as pre-existing or a flake**. The same constrained runtime
  passes the baseline lifecycle file (2 passed, 1 platform skip in 9.80 seconds)
  and the current full native suite. Trigger: the human reruns the Windows
  native job; if the inventory timeout recurs, capture probe start/finish and
  CIM/provider timing on that runner before any change to its bound or
  implementation. A successful inventory is still required for a green CI
  retirement check. No threshold, sleep, or skip was added.

#### Reproducible environment and commands

All successful desktop and packaged runs used normal host access and temporary
test profiles. Only Python 3.13 was registered locally; the Python launcher
alias was inaccessible. The base installation's `ensurepip` bundled wheel was
missing, so venv creation left a usable interpreter without pip. Bootstrapping
it with the existing pip's `--python` option succeeded. The ordinary `.venv`
and the user's application profile were not modified.

PowerShell variables below abbreviate actual executable paths:

```powershell
$reviewPython = 'C:\Hanly\dist\review-windows-env\Scripts\python.exe'
$originalPython = 'C:\Hanly\.venv\Scripts\python.exe'
& $originalPython -m venv C:\Hanly\dist\review-windows-env
# The preceding ensurepip step failed; bootstrap its interpreter with working pip.
& $originalPython -m pip --python $reviewPython install --upgrade pip
& $reviewPython -m pip install --group dev -c packaging/release-constraints.txt -e packages/hanly -e 'packages/hanly-app[runtime]' pyinstaller
& $reviewPython -m pip check
& $reviewPython -m pip freeze > dist/review-windows-freeze.txt
& $reviewPython tools/prepare_easyocr_models.py
```

Python 3.13.11; pip 26.2.1; pytest 9.1.1; PyQt6 and PyQt6-WebEngine 6.11.0;
PyQt6-Qt6 and PyQt6-WebEngine-Qt6 6.11.2; EasyOCR 1.7.2; Torch 2.14.1;
torchvision 0.29.1; kiwipiepy 0.23.2; pywebview 6.2.1; PyInstaller 6.22.2;
hooks-contrib 2026.7; Ruff 0.16.9; mypy 2.3.1. `pip check` reports no broken
requirements. Full installed versions are retained in the ignored freeze file.
CI's Windows native job uses Python 3.10.11 and Torch 2.14.0. The local frozen
build uses Python 3.13.11; a Python 3.10 frozen build was not performed here.

| Actual command/check | Result |
| --- | --- |
| `& $reviewPython -m pytest --suite portable -q --tb=short -p no:cacheprovider` | 2,260 passed, 104 skipped in 209.98 s; default import order |
| `& $reviewPython -c "import os,pytest; os.environ['PATH']=';'.join(p for p in os.environ['PATH'].split(';') if 'msys64' not in p.lower()); os.environ['HANLY_REQUIRE_NATIVE']='1'; raise SystemExit(pytest.main(['--suite','native','-q','--tb=short','-p','no:cacheprovider']))"` | 119 passed, 33 platform skips in 209.27 s |
| `& $reviewPython -m ruff check packages packaging tests tools benchmarks` | Passed |
| `& $reviewPython -m mypy --platform linux packages packaging tests tools benchmarks` | Passed; 305 source files |
| Archived baseline source, original venv mypy `--no-incremental packages packaging tests tools benchmarks`, `MYPYPATH` pointing at both baseline package sources | 22 POSIX API errors in 7 files, 301 checked; matches current Windows-host errors |
| Baseline lifecycle file under the constrained interpreter, `HANLY_REQUIRE_NATIVE=1`, baseline root and both source packages first in `sys.path`/`PYTHONPATH` | 2 passed, 1 platform skip in 9.80 s |

Portable skips are the platform/capability exclusions already represented by
that suite; native skips are macOS/POSIX-only cases and the non-Windows SIGINT
case. Packaged skips are not accepted as a pass: both require variables are
set for its gates.

#### Package reconstruction and final stop boundary

**Final verdict: the Windows local review is complete, with no demonstrated
executable cleanup regression. The branch is ready for the human's push and CI
decision. Merge remains conditional on a successful Windows native CI run;
the latest run is still red on the process-inventory timeout above.**

The final build is from
`cbdebc59500e4f520880c33dbdd1da52c85b840f`, version `0.9.0`, Windows x86_64,
build ID `63149ac0-8a48-4737-b0ab-0dfc618f8e69`, stamped
`2026-09-30T19:29:51+00:00`. It uses the unchanged production spec, CLI entry
point, relocated lookup and Control Center targets, and release constraints.
The only subsequent tracked edit is this handoff. The final clean-PATH analysis
does not collect Poppler's ICU; Qt resolves the host's compatible Windows ICU.
The source-parent frozen-child harness explicitly models frozen Windows spawn
arguments and disables its venv-only executable substitution. It runs the
actual bundle executable and bundled target, but is not a second fully frozen
parent application. Both child generations reach the canonical parent bridge
and exit with code 0, and the source parent imports no WebEngine, Torch,
EasyOCR, or Kiwi.

The completed ZIP is 621,573,710 bytes with 6,264 entries under
`hanly-desktop/`. SHA-256:
`c220f76cad15cb342f122d817ada3ad2f2fdd43c93e9fe65147382ce9307d51e`.
The release manifest is 1,111,079 bytes, SHA-256
`b64971ceaca50624fe3151b91cb6ffe5bf3ef2b01c9f62847c0eae4de4a51cef`.
Archive and manifest size/hash match `dist/release/windows/descriptor.json`.
The legacy compatibility manifest has a different schema and derived build ID;
its file path/size/hash mapping matches the corresponding release-manifest
files, excluding the legacy manifest's own file. No previous published package
was supplied, so the descriptor explicitly omits a delta. Delta generation,
publishing, signing policy, installation, and an update against a previously
published release were not added to this cleanup review.

```powershell
# This retained script performs the following inside Python, before invoking
# the unchanged production build tool (PowerShell PATH edits did not propagate
# reliably through this host's Python launcher):
# os.environ['PATH'] = ';'.join(p for p in os.environ['PATH'].split(';') if 'poppler' not in p.lower())
# os.environ['PYINSTALLER_CONFIG_DIR'] = r'C:\Hanly\dist\.pyinstaller-cache-release'
# sys.argv = ['tools/build_package.py']
# runpy.run_path('tools/build_package.py', run_name='__main__')
& $reviewPython dist/review_clean_build.py
& $reviewPython -c "import os,pytest; os.environ['HANLY_EXPECTED_SOURCE_COMMIT']='cbdebc59500e4f520880c33dbdd1da52c85b840f'; os.environ['HANLY_REQUIRE_PACKAGED']='1'; raise SystemExit(pytest.main(['--suite','packaged','-q','--tb=short','-p','no:cacheprovider']))"
& $reviewPython dist/review_frozen_control_child.py C:\Hanly\dist\windows\hanly-desktop\hanly-desktop.exe
& $reviewPython dist/review_reconstruct_zip.py
& $reviewPython tools/smoke_packaged_runtime.py C:\Hanly\dist\review-windows-cbdebc5-reconstructed\hanly-desktop --against-manifest C:\Hanly\dist\release\windows\manifest.json --inventory-only
& $reviewPython -c "import os,pytest; os.environ['HANLY_EXPECTED_SOURCE_COMMIT']='cbdebc59500e4f520880c33dbdd1da52c85b840f'; os.environ['HANLY_REQUIRE_PACKAGED']='1'; os.environ['HANLY_PACKAGED_APP']=r'C:\Hanly\dist\review-windows-cbdebc5-reconstructed\hanly-desktop'; raise SystemExit(pytest.main(['--suite','packaged','-q','--tb=short','-p','no:cacheprovider']))"
```

| Final package check | Result |
| --- | --- |
| Built onedir inventory, exact source identity, real frozen lookup worker, Control Center UI | **4 passed, 0 skips in 16.10 s** |
| Separate real frozen Control Center spawn-target harness | Two generations opened and reached the parent bridge; both exited 0; no heavy imports in parent |
| ZIP extraction into a new directory, archive/descriptor hashes and compatibility file mapping | Passed |
| Extracted tree against the release manifest | 6,263 entries; no missing, differing, or unexpected entries; inventory passed |
| Extracted ZIP inventory, exact source identity, worker, Control Center UI | **4 passed, 0 skips in 14.84 s** |

The old unconstrained ZIP and reports remain under
`dist/review-windows-79e2239/`; the constrained but Poppler-contaminated ZIP,
descriptor, ICU DLL, and analysis remain under
`dist/review-windows-cbdebc5-polluted/`. Reconstructed final product:
`dist/review-windows-cbdebc5-reconstructed/hanly-desktop/`. Diagnostic scripts,
dependency freeze, and all resume logs are under ignored `dist/`; they contain
synthetic fixture results and loader/process metadata, not private screen
captures or recognized user text. The ordinary profile and venv are intact.
One temporary PE diagnostic held a DLL open during an earlier COLLECT attempt;
that diagnostic was terminated and the collection retried. Harness setup
errors were corrected before counting any of the successful checks above.

**Remaining human gate:** inspect or rerun
[Windows native job 109834338640](https://github.com/ThiagoRoss1/hanly/actions/runs/36699193317/job/109834338640).
Its shutdown, lookup, WebEngine, and other Windows cases passed; its process
inventory did not complete. Do not infer a green CI retirement check from the
local passes. If that timeout repeats, use the timing trigger above. A local
Python 3.10 frozen build remains unverified; the exercised release-constrained
Windows artifact uses Python 3.13.11. This resumption stops at this handoff.
No push, merge, tag, release, or additional cleanup wave was performed.
