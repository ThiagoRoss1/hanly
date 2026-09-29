# V1 Cleanup Wave Review Handoff

## Bundle

- Scope: one user-authorized pre-V1 cleanup wave over the findings in
  `docs/execution/reports/v1-cleanup-audit-2026-09-28.md` (Luna A-01–A-32 and
  Sonnet N-01–N-32; the Sonnet §10 corrections were applied first). No Linear
  issue; the brief is `docs/execution/plans/v1-cleanup-audit-brief-2026-09-28.md`.
- Implementation ecosystem: Claude Code, Opus 5.5, one session, direct execution
  with no subagents. Base: `main` at `e75ef4b`, with the two audit files
  untracked and preserved.
- Date: 2026-09-28.

### Human decisions taken during the wave

| Item | Decision |
|---|---|
| A-03 Control Center OCR selector | **Keep the dropdown.** The approved decision record was amended to match; visual companions untouched |
| A-32 popup keyboard focus | **Keep pointer-only by design**; pin it with a test and document it |
| Dead app-internal code (N-12, N-13, A-13, A-19, N-07/N-04) | Approved, remove only what is proven unused |
| Lazy `hanly_app/__init__` (A-20) | Approved, every export preserved |
| pyobjc for macOS (N-25) | Approved on `hanly-app[runtime]` with a darwin marker |
| `ResourceManager` alias removal (N-27) | **Declined.** Aliases kept and documented |
| A-07 enforcement, N-24 trim/delete, N-22 diagram edits | **Unanswered**, so existing behaviour and content were preserved |

## Implemented

- **Stale direct-text lookup (A-01).** Both hover routes now go through a single
  bookkeeping step (`_track_submission`), so a pointer movement also supersedes a
  lookup that read the word directly.
- **One readiness waiter (A-24).** Repeated pause/resume during startup no
  longer starts a new waiter thread each time.
- **Private Export (N-06).** The live benchmark always validates Export against
  the fixed gitignored `artifacts/benchmarks/runs/`; `--output-root` moves only
  the non-private evidence.
- **Raw-text tracing removed.** A `retain_text` branch in `composition.py` could
  still put recognized text into a trace for any sink that asked, and only a
  test did. It was removed, and that test now proves no sink can opt in.
- **Smoke dictionary (N-08).** `build_smoke_krdict.py` refuses to overwrite a
  file that is not an earlier smoke build unless `--replace` is given.
- **Engine: leading whitespace (A-02).** The cursor offset now shifts with the
  whitespace `LanguagePipeline` strips from the selection, so it still points at
  the same character.
- **Updater (A-05, A-28).** Cleanup no longer treats an *empty* `hanly-update.*`
  directory in the shared temp root as Hanly's. A refused multi-volume disk
  image now names every volume it could not detach.
- **Control Center (A-29, A-30, A-31, A-15).**
  - A refresh no longer resets the hover-delay slider during a drag.
  - Keyboard focus stays on its navigation section across re-renders.
  - Two diagnostics exports in the same second no longer overwrite each other.
  - The Vision help text is qualified to what Hanly's tests showed.
- **Benchmark fidelity (N-01–N-05, N-09, N-10).**
  - `detection-only` never calls the recognizer, and `recognition-only`
    excludes detection from its total.
  - Steady RSS is sampled before the provider closes.
  - The observed resolver forwards `resolve_target_detail`, so the pointer
    offset is kept.
  - The HUD's `retain_geometry` now crosses the spawn to the lookup child.
  - `process.csv` is appended to, not truncated. The live summary is labelled
    shell-only, and the shell no longer pre-imports the OCR runtime.
  - The packaged smoke tool kills the whole POSIX process group on timeout and
    shares one attach/detach helper, so a detach failure cannot hide the
    original error.
  - The synthetic corpus records the font's file name instead of its absolute
    path.
- **Dead code (N-12, N-13, A-13, A-19, N-04, N-07).**
  - Removed from the app: `ClippingRecovery` (its tested helpers stay, with
    provenance in the docstring), `InPlaceUpdateRunner`, `QtPopupRuntime`,
    `source_label`, `activation_policy`, `remove_value`, `HELD_ACTIONS`,
    `RECEIPT_BACKUP_SUFFIX` and `OCR_DISPLAY_NAME`.
  - Removed from the engine: `_locate_word_at_target`.
  - Removed from the benchmarks: `_has_text_like_structure` (its test now
    targets `_measure_text_presence`), `hud/capture_exclusion.py` and the dead
    HUD members, `--enable-mkldnn`, `StageProbe`, `sample_process`, the
    `probe_*` wrappers and aliases, the diagnostics aliases, `iter_case_images`
    and `dropped_captures`.
- **Hygiene.**
  - The engine `__all__` duplicates were removed, and a test now asserts every
    name is unique (A-14).
  - The resolver's docstring was corrected (A-12).
  - `LookupController` now documents that it expects one serialized caller
    (A-18).
  - 7 unused `noqa` directives were removed and RUF100 enabled (N-15).
  - `build_seed.py` uses `KRDICT_SCHEMA_VERSION` (N-28).
- **Imports and dependencies.**
  - `hanly_app/__init__.py` is lazy (PEP 562); all 109 names are preserved
    (A-20).
  - `pyobjc-core` and `pyobjc-framework-Cocoa` are declared with
    `sys_platform == 'darwin'` markers (N-25).
- **Tests and harness (A-17, N-14, N-20, N-29, N-26).**
  - The Actions replay now models the implicit `success()`, and its comment
    states what it leaves unmodelled.
  - The DOM harness can observe focus and drive the slider.
  - New `tests/test_architecture_invariants.py` checks, for all four pairs,
    that each Markdown invariant list matches its visual companion, that
    `CONTEXT.md` matches, and that AGENTS.md and CLAUDE.md stay in sync.
  - The package boundary test now also forbids `hanly_app` from importing
    `tools` or `benchmarks`.
  - A vacuous Kiwi assertion and an overclaiming benchmark docstring were
    fixed.
- **Documentation.**
  - README: current OCR behaviour, direct-text reading, the Mac function-key
    note (N-18), the popup focus policy, and the gates without `spikes/`
    (A-10).
  - CLAUDE.md and AGENTS.md rewritten short and rule-focused with one shared
    body (A-11, N-19).
  - CODE-MAP: Vision in the flow, direct text, a complete file index, the HUD
    wording, and the release asset set (A-08, N-16).
  - Release asset counts reconciled with `release_build.py` in the runbook,
    `packaging/README.md` and CODE-MAP (A-06).
  - N-17: the deleted KRDICT workflow was removed from `data/` and `tools/`
    READMEs, and `tools/` now has a full index.
  - `CONTEXT.md` synced (N-20).
  - The Linear workspace slug was removed from 5 places (N-11).
  - A broken link was fixed, and root `reports/` moved into
    `docs/execution/reports/` with `git mv` (N-21).
  - N-23 navigation:
    - 22 historical banners added;
    - a caveat added to the §4.2 baseline;
    - a note added to `REVIEW-2026-08-18`;
    - new `docs/README.md` index;
    - `plans/` now described in `05`.

## Main expected behavior

- In hover, moving off a word that was read through accessibility or UIA no
  longer shows its popup late.
- Normal tracing carries no recognized text, whatever the sink claims.
  Private evidence reaches disk only through explicit Export under the
  gitignored root.
- Starting a single submodule no longer runs the whole desktop package. For
  example, `import hanly_app.lookup_process` takes about 34–45 ms warm,
  against 93–123 ms in the audit.
- Everything else is behaviour-preserving, apart from the stated fixes.

## Architecture / seams touched

- `DECISION-2026-09-22-ocr-backend.md` gained a dated **amendment** approved by
  the human (A-03). The OCR callouts in `01`, `02` and `03` were aligned with
  it. No invariant ID or diagram changed.
- Engine: `LanguagePipeline` cursor handling (a bug fix within the existing
  `TextSelection` contract, whose docstring now says so) and the doc-only
  `SchemaSpec` and `ResourceManager` notes. The public API is unchanged except
  that the private `_locate_word_at_target` is gone.
- App: hover request currency (`hover_lookup.py`), the `LookupSettings` spawn
  payload (new `trace_geometry` field), and the package export surface (the
  same names, loaded lazily).

## Relevant files / diff areas

- `packages/hanly-app/src/hanly_app/`:
  - `hover_lookup.py`, `lookup_process.py`, `composition.py`, `__init__.py`,
    `control_center.py`;
  - `assets/control_center/control_center.js`;
  - `owned_cleanup.py`, `app_update_macos.py`;
  - the dead-code files named above.
- `packages/hanly/src/hanly/`: `language_pipeline.py`, `contracts.py`,
  `word_resolver.py`, `resource_manager.py`, `__init__.py`.
- `benchmarks/dev/`: `ocr_benchmark.py`, `easyocr_stages.py`, `campaigns.py`,
  `live_runner.py`, `live_telemetry.py`, `probes.py`, `synthetic_ocr.py`,
  `hud/`.
- `tools/`: `build_smoke_krdict.py`, `smoke_packaged_runtime.py`,
  `krdict/build_seed.py`.
- Config: `pyproject.toml` (RUF100), `packages/hanly-app/pyproject.toml`
  (pyobjc).
- Documentation: the root README, AGENTS.md and CLAUDE.md; under `docs/`:
  `README.md`, `CODE-MAP.md`, the architecture documents, `execution/CONTEXT.md`
  and `execution/05-execution-plan.md`, the runbook, and the banners above; the
  `packaging/`, `tools/`, `data/` and `benchmarks/dev/` READMEs.
- New tests: `tests/test_architecture_invariants.py`, plus focused cases in
  about 20 existing test files. Each regression test was confirmed to fail
  without its fix.

## Branch and commits

At the human's direction the work was committed on a new local branch rather
than `main`, using the configured author and no attribution trailers. Nothing
was pushed, merged, tagged, published or dispatched.

- Branch: `clean/arch-optimization`, created from `main` at `e75ef4b`.
- Commits, oldest first:
  1. `cbef102` fix: supersede direct-text lookups on movement and keep one
     readiness waiter
  2. `a8f1600` fix: shift the selection cursor with stripped whitespace
  3. `1b31f4a` fix: keep private evidence under the artifact root and refuse
     smoke-db overwrites
  4. `5ec872e` fix: harden updater cleanup and Control Center state, focus and
     exports
  5. `656dae3` fix: measure the stages and processes each benchmark mode claims
  6. `c8a29ea` refactor: remove dead code, load package exports lazily, declare
     pyobjc
  7. `b8df026` docs: reconcile documentation with the V1 product and record the
     cleanup wave (includes this handoff, the audit report and the brief)
  8. docs: record the cleanup wave's branch, commits and final validation (the
     commit that adds this list; `git log -1 clean/arch-optimization`)
- Worktree after commit 8: clean.
- Gates re-run on `b8df026`, the branch head before this record, in the
  repository `.venv` (Python 3.13.11):
  - ruff: clean;
  - mypy: no issues in 301 files;
  - portable: 2,369 passed, 2 skipped;
  - native: 123 passed.
- Staging:
  - Files mixing two concerns (`composition.py`, `live_runner.py` and
    parts of `probes.py`/`cli.py`/`test_probes.py`) were staged by hunk, so
    each commit holds its own change.
  - Before commits 5 and 6, the staged snapshot was checked out separately
    and run through ruff (and, for 6, mypy) and the affected tests.
  - Each staged diff was inspected: no screen captures, pixels, OCR output,
    run artifacts, patch files or binaries.
  - The audit report's machine-specific repository path was replaced with a
    neutral reference.

## Implementation-side validation already run

Environment: macOS 26.6.2 arm64 and the repository `.venv` (Python 3.13.11).
The stale editable metadata that caused the only baseline failure (0.5.3
against 0.9.0) was refreshed with `pip install --no-deps -e`.

- Baseline, before changes:
  - portable: 2,332 passed, 2 skipped, 1 failed (the stale metadata above);
  - ruff and mypy: clean.
- Portable suite (`pytest --suite portable`): 2,369 passed, 2 skipped.
- Native suite (`pytest --suite native`): 123 passed.
- `ruff check packages packaging tests tools benchmarks`: clean, with RUF100
  now selected.
- `mypy packages packaging tests tools benchmarks`: no issues in 301 files.
- Python 3.10.20, in a scratch venv shaped like CI's `quality` job (dev group
  plus editable packages, no runtime extra):
  - all 302 tracked `.py` files compile;
  - ruff and mypy are clean;
  - portable suite: 2,255 passed, 90 skipped, 15 failed. The **same 15 fail at
    HEAD `e75ef4b`** in a detached worktree. They need PyQt6 or `objc`, which a
    macOS environment without the runtime extra lacks; CI runs this job on
    Linux, where they skip or take the off-darwin path. They are environmental,
    not regressions.
- Import and spawn checks:
  - a new test shows `import hanly_app.ocr_preload` loads only that module;
  - every export resolves to the same object as its defining module;
  - `from hanly_app import <submodule>` still works;
  - PyInstaller collects the package with `collect_submodules("hanly_app")`,
    so lazy loading hides nothing from the frozen build;
  - the native suite's spawned-lookup-child cases pass.
- Moves: only documentation moved (`reports/*` → `docs/execution/reports/`).
  No module was moved or renamed, so no dotted import, string target, package
  data or PyInstaller path changed.
- Packaged macOS build and smoke: see the next subsection.

### Packaged macOS build (local)

Built with `.venv/bin/python tools/build_package.py --platform macos`
(PyInstaller 6.22.2, `PYINSTALLER_STRICT_BUNDLE_CODESIGN_ERROR=1`), using the
working tree on top of `e75ef4b`. The build wrote `dist/hanly-desktop-macos.zip`
(555 MB), `dist/hanly-desktop-macos.dmg` (637 MB), and `dist/release/macos/`
(the manifest and descriptor). The checks below follow `packaging/README.md`,
against the application reconstructed from the published ZIP; all exited 0.

- `--from-archive … --reconstruct-into dist/reconstructed --reconstruct-only`:
  ok.
- `--disk-image dist/hanly-desktop-macos.dmg`: ok (the image holds `Hanly.app`).
- `dist/reconstructed/Hanly.app --inventory-only`: ok. That covers the models,
  data files, the certifi bundle and the code signature, and it shows the lazy
  `__init__` lost no module.
- Worker: `--image tests/hanly_fixtures/assets/korean_reading_roi.png --krdict
  <smoke db> --expect-version 0.9.0` is ok. The runtime, lookup worker, OCR,
  morphology, dictionary and close stages all reported ok, and both packages
  report 0.9.0. This is the frozen spawned lookup child importing through the
  lazy package.
- `--window-only`: ok. The window host, document, controls and page→bridge
  `get_state` all passed.
- `HANLY_PACKAGED_APP=dist/reconstructed/Hanly.app HANLY_REQUIRE_PACKAGED=1
  HANLY_EXPECTED_SOURCE_COMMIT=$(git rev-parse HEAD) pytest --suite packaged`:
  4 passed. As noted under limitations, the stamped commit is HEAD, not this
  uncommitted candidate.

## Known limitations / intentionally unvalidated areas

- The local frozen build was made before the commits, from a working tree whose
  code equals the branch's (commit 7 changes only docstrings in
  `resource_manager.py`). It is stamped with `e75ef4b`, because
  `build_package.py` records `git rev-parse HEAD`, so its identity check proves
  nothing about this branch. A build from the branch head is needed for that.
- **Remote CI and `Build Desktop Artifacts`: NOT VERIFIED.** The branch is local
  only; pushing and dispatching were explicitly not authorized.
- Windows and Linux: not exercised live. Windows UIA, DPI and capture (A-21)
  remain unverified on this Mac, and so does the POSIX process-group change on
  Linux.
- A-01 and A-24 were validated with deterministic in-process barriers, not in a
  live hover session. A-29 and A-30 were validated in the Node DOM harness, not
  a real WebEngine window or screen reader.
- The lazy `__init__` changes import timing. Startup was measured by import
  cost only, not as frozen launch latency.
- N-15: the audit's "36 unused `noqa`" was an artifact of running `--select
  RUF100` alone. The real count with the configured rules was 7.

## Findings dispositions

Legend:
- **Impl**: implemented.
- **Doc**: documentation or test correction only.
- **Def**: deferred, with the trigger for revisiting it.
- **Dis**: dismissed.
- **Hum**: human decision.

| ID | Disposition |
|---|---|
| A-01 | Impl, with a movement barrier test |
| A-02 | Impl (engine), with whitespace tests |
| A-03 | Hum, keep the selector: DECISION amended; `01`–`03`, CLAUDE, AGENTS and README aligned; visuals unchanged |
| A-04 | Dis: environment limitation. `tests/test_vision_provider.py` passes here (27 passed, 1 off-macOS skip) |
| A-05 | Impl, with an empty-directory test |
| A-06 | Doc: runbook, packaging README and CODE-MAP reconciled with `release_build.py` |
| A-07 | Doc: `version` documented as descriptive. Def enforcement: revisit when a second KRDICT schema version exists or a caller passes a non-default version |
| A-08 | Doc |
| A-09 | Dis: the HAN-15 gate is closed and deliberately EasyOCR-scoped; rewording an ID'd invariant needs approval |
| A-10, A-11 | Doc |
| A-12 | Doc |
| A-13 | Impl: removed |
| A-14 | Impl, plus a uniqueness assertion |
| A-15 | Impl: copy qualified |
| A-16 | Def: revisit in an accessibility pass with screen-reader validation (the harness can now observe focus) |
| A-17 | Impl: implicit `success()` modelled and the claim narrowed |
| A-18 | Doc: serialized-caller contract. Def a locking change: revisit if a non-dispatcher caller appears |
| A-19 | Impl |
| A-20 | Impl |
| A-21 | Def: revisit during Windows validation with exact-edge, fractional, scaled and negative-origin cases |
| A-22 | Def: revisit if release policy requires native Carbon delivery tests |
| A-23 | Dis |
| A-24 | Impl, with a barrier test |
| A-25 | Dis: hypothesis only |
| A-26 | Def: revisit when an external display and a Dock-cycle test environment are available |
| A-27 | Def: revisit if crash residue is reported or updater staging prefixes change |
| A-28 | Impl, with a failing-detach test |
| A-29, A-30 | Impl, with DOM-harness tests |
| A-31 | Impl, with a same-second test |
| A-32 | Hum, keep pointer-only: native test plus README |
| N-01 | Impl: stage isolation, with tests; baseline §4.2 caveated. The Vision/EasyOCR decision is unaffected (it rests on `ocr-only`) |
| N-02, N-03 | Impl, with tests |
| N-04 | Impl: geometry forwarded; dead HUD members and module removed |
| N-05 | Impl: append, scope label, shell preload removed. Def child-process sampling: revisit when child resource use must be benchmarked |
| N-06 | Impl, with tests |
| N-07 | Impl for the listed zero-caller items. Def the staged-OCR export attachment (tested but not wired to a command; README corrected): revisit when a replay command is wanted. Dis `gate_false_negative_rate`, `Corpus.tagged` and `is_committed` (small, tested). Def the legacy `live_telemetry` vocabulary: revisit once old run logs need no summarizing |
| N-08 | Impl, with tests |
| N-09 | Impl, with a grandchild-kill test and a detach-masking test |
| N-10 | Impl |
| N-11 | Impl (5 places, including the HAN-38 handoff). The slug remains in git history, which needs no action without a history rewrite |
| N-12 | Impl: class removed, helpers kept with provenance |
| N-13 | Impl except `build_lookup_controller` and `create_worker_factory_from_config`, which `hanly_app` exports. Def: revisit when the export surface is next reviewed |
| N-14 | Impl |
| N-15 | Impl: 7 real directives; RUF100 enabled |
| N-16, N-17 | Doc |
| N-18 | Doc. Def changing the default shortcuts: a product decision |
| N-19, N-20 | Doc, plus sync tests |
| N-21 | Impl: link fixed; `reports/` moved. Dis the "`self` link", which is inside a fenced Python block |
| N-22 | Hum, **unanswered**: no diagram edit |
| N-23 | Doc: banners, index, `05` note |
| N-24 | Hum, **unanswered**: historical banner only; §8 and the `.patch` untouched |
| N-25 | Impl: darwin-marked dependencies |
| N-26 | Impl for the Kiwi assertion and the benchmark claim. Def the duplicate tests, implementation coupling and the `tests/krdict` helper: revisit in a test-quality pass |
| N-27 | Hum, keep the aliases: canonical methods documented. The forwarding is already single-line |
| N-28 | Impl for the schema constant. Def the `user_version`/minibook version fields, the index list and the private imports: revisit with the next KRDICT schema change |
| N-29 | Impl: app boundary covered. Def the suite-routing triplication: revisit if routing changes |
| N-30 | Def: changes remote CI triggers; the human decides |
| N-31 | See organization below |
| N-32 | Def: `.design-reference/` provenance and licence are the human's to decide |

### Organization (§10.5, N-31)

**No module moves.** The candidate `updates/` package was evaluated and rejected
for V1:

- It would need edits to `release.yml:642`, four `tools/` modules, about 91
  test import lines, 8 dotted-string `monkeypatch` targets and a new
  `__init__.py`.
- It adds PyInstaller namespace risk.
- Its only benefit is navigation, which the CODE-MAP "Updates" index now
  provides at zero import risk.

The rest of the proposed tree increases cross-group edges (§10.5). Navigation
was delivered instead through a complete CODE-MAP file index, the new
`docs/README.md`, the `tools/` index and the historical banners.

## Suggested review targets

- `hover_lookup.py`:
  - does `_track_submission` on the direct route interact safely with
    `_on_direct_text` falling back to capture?
  - the single-waiter readiness logic when a waiter wakes after
    shutdown/`_fail`.
- The lazy `hanly_app/__init__.py`: frozen startup on all three platforms, and
  any consumer that relied on side effects of the eager imports.
- The `LookupSettings.trace_geometry` field across spawn and pickling on
  Windows.
- `smoke_packaged_runtime.py`: `start_new_session` together with
  `os.killpg` on Linux CI and macOS runners.
- The engine cursor shift (A-02), for inputs whose cursor lies inside trailing
  whitespace or beyond the text.
- The amended OCR decision wording. The visual companions were checked and
  mention no provider-selection policy, so they needed no change.

## Review assignment

Human-selected after implementation. Not started.
