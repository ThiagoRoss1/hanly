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
