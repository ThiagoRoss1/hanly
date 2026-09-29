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
