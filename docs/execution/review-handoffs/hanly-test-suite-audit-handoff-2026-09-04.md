# Hanly test-suite audit — Claude execution handoff

Date: 2026-09-04

## Objective

Clean and harden Hanly's collected test suite without changing production behavior, weakening coverage, or creating a broad refactor. The immediate Windows CI failure has already been diagnosed and a narrow uncommitted fix exists. Execute only the justified changes below, then stop at the normal review handoff.

This is an audit of every Python file under `tests/` (57 files, 528 directly declared tests) and the separately collected `benchmarks/dev/tests/` suite (10 files, 50 directly declared tests). The benchmark tests are included because root `pytest` collects them and a previous CI dependency failure originated there.

## Repository state at handoff

- Repository: `C:\Hanly`
- HEAD when audited: `72a20d4` (`main`, `origin/main`, tag `v0.1.0`), `fix: Fixes ci/cd errors and windows build`
- Existing uncommitted change: `tests/test_app_update.py` only.
- That diff adds a `_posix_handoff` marker which skips the POSIX handoff tests on `sys.platform == "win32"` or when no Bash is present.
- The working tree is shared and was being changed by another Claude session. Begin with `git status --short` and `git diff`; preserve changes you did not author.
- Do not commit, push, merge, tag, publish, dispatch a workflow, or delete generated user data.

Read before editing:

- `C:\Hanly\CLAUDE.md`
- `C:\Hanly\docs\CODE-MAP.md`
- CI failure transcript: `C:\Users\Thiago\.codex\attachments\cc36d74c-4859-4ea1-ab1f-921629e57d13\pasted-text.txt`

## Baseline evidence

- The attached GitHub Windows run failed only three POSIX handoff tests.
- Root cause: `shutil.which("bash")` found `C:\Windows\System32\bash.exe`, the WSL launcher stub, even though no usable distribution existed. Windows Hanly uses the `.cmd` handoff, not the POSIX script.
- Claude's narrow fix is architecturally correct: gate a platform-specific test on the platform where that implementation is used, not on a coincidental executable name in `PATH`.
- After that diff, a local full run in the current checkout reported `688 passed, 4 skipped in 99.48s`. Claude separately reported a CI-equivalent Windows environment at `674 passed, 15 skipped`, with Ruff and mypy clean. Different optional dependencies explain the skip-count difference.
- No `assert True`, empty `pass` test, or duplicate test-function name was found. The suite is not broadly fake or disposable.

## Non-negotiable constraints

1. Preserve production behavior and public contracts. This is a test-quality cleanup, not permission to redesign runtime code.
2. Preserve the EasyOCR-only architecture. Do not reintroduce PaddleOCR, an OCR backend selector, or Paddle model resources.
3. Preserve the approved KRDICT schema and raw duplicated `source_id` behavior, including the reused ID `77610` regression.
4. Do not remove a test merely to reduce file count or make CI green. Every deletion must be replaced by equivalent or stronger coverage, or be demonstrably tautological/duplicated.
5. Do not turn deterministic unit tests into environment-dependent integration tests.
6. Keep `tests/krdict/test_pipeline.py` and `test_real_records.py` as explicit production-resource acceptance tests; their ordinary local skip is intentional when the artifact is absent.
7. Keep the root gates aligned with `CLAUDE.md`: pytest plus Ruff and mypy across packages, packaging, tests, tools, and benchmarks.
8. No Git or release mutations.

## Execution order

### Phase 1 — finish the immediate platform fix

1. Retain the existing `_posix_handoff` platform marker in `tests/test_app_update.py`.
2. Make `_run_posix_handoff` assert the subprocess exit status before reading the launch marker, so a silent shell failure is reported directly.
3. Add an executable Windows `.cmd` handoff test on Windows. Test actual filesystem state transitions: staged bundle activates, failed replacement restores the live bundle, and failed rollback launches nothing. Keep structural command-script assertions only where safely observing a spawned executable is impractical.
4. Add a separate `windows-tests` job to `.github/workflows/ci.yml`, using `windows-latest` and Python 3.10, without renaming or replacing the existing `quality` job. This avoids breaking required status checks pinned to the old job name. Install the same root dev group and editable packages as the existing CI lane and run the full suite. Do not dispatch it.

### Phase 2 — remove or repair genuinely weak tests

Implement these narrowly:

- Delete `tests/test_application.py::test_the_desktop_passes_the_persisted_setting_to_the_coordinator`. It asserts a production source-code string and duplicates the behavior tests immediately above it.
- Delete or relocate `tests/test_provider_interfaces.py::test_ocr_results_are_returned_in_reading_order`. The fake returns a hard-coded tuple and the test only verifies that tuple. Put the reading-order invariant against actual EasyOCR adapter normalization in `test_easyocr_provider.py` if it is not already covered.
- Rewrite `tests/test_capture_selector.py::test_the_selector_prepares_the_ocr_runtime_before_qt`; the injected `record` callback does not exercise `select_capture_area`, so the present test does not establish the promised ordering.
- Strengthen `test_a_missing_control_center_runtime_does_not_block_area_selection` with a spy/assertion proving the fallback path was actually invoked.
- Replace the hard-coded installed version assertion in `tests/test_app_update.py` (`== "0.1.0"`) with a metadata-behavior test. It must survive a legitimate release version bump.
- Make `test_the_snapshot_is_json_compatible_primitives` assert the expected message rather than reconstructing the object from the payload value it is supposed to verify.
- Fold/delete `tests/krdict/test_build_release_asset.py::test_the_manifest_is_written_under_the_name_a_release_publishes`; verify the filename in a successful end-to-end builder test instead of testing a constant against itself.
- Consolidate the duplicate release-preflight assertions in `tests/test_ci_workflows.py`; do not keep two tests that establish the same trigger/collision classification.
- Rename `test_building_desktop_artifacts_is_never_automatic`; it explicitly permits automatic tag builds. Suggested name: `test_desktop_build_runs_only_manually_or_for_release_tags`.
- Strengthen `benchmarks/dev/tests/test_live_telemetry.py::test_summary_json_is_serializable` with a JSON round trip and meaningful shape/value assertions.
- Replace the vacuous `--help` encoding check in `tests/krdict/test_inspect_archive.py` with a command that emits Korean content under a legacy Windows console encoding.

### Phase 3 — fix guards that can themselves lie

1. In `tests/test_dev_dependencies.py`, static imports must never be excused merely because the same module name appears later in `pytest.importorskip`. The current set subtraction allows this false negative:

   ```python
   import PIL
   pytest.importorskip("PIL")
   ```

   Treat static imports separately from literal dynamic imports. Static third-party imports must be declared in the root dev group; `importorskip` may guard only the optional/dynamic acquisition it actually precedes. Add a negative regression for this exact case. Parse `pyproject.toml` with native `tomllib` on the Python 3.13 development runtime rather than a broad regex; keep compatibility in CI only where required.
2. The new build-workflow shell-variable guard is overbroad if it requires Bash for every `$...` occurrence: a legitimate Windows `pwsh` step may use `$env:NAME`. Prefer the simplest correct contract: assert `shell: bash` directly on the cross-platform release-tag/version-check step that needs POSIX `$RELEASE_TAG`. Only keep a global guard if it understands the declared shell, `${{ ... }}` expressions, and platform-specific steps.
3. Where workflow/package tests claim to parse structure, prefer YAML/TOML/AST data or generated artifact inspection over comments and raw-text regexes. Do not add a parser dependency unless already justified.

### Phase 4 — remove stale architecture artifacts

- Remove the obsolete `"ocr_backend": "easyocr"` key and “backend selection” wording from the helper in `tests/test_easyocr_runtime.py`. EasyOCR is the architecture, not a runtime selector.
- In `tests/test_control_center.py`, replace the stale `detection_model` managed-resource fixture with the real current resource shape (KRDICT only) or a clearly generic resource only when the test genuinely exercises arbitrary resources. EasyOCR's downloaded model is not currently a `ResourceManager` resource.
- In `tests/test_update_service.py`, keep the invariant that remote resources absent from the local manifest are ignored, but rename the stale `paddle_detection_model` fixture to a neutral `unconfigured-resource`.
- Keep `tests/test_packaging.py`'s negative assertion that Paddle is absent if it remains a useful regression guard; it is different from modeling Paddle as a live resource.

### Phase 5 — make the suite faster without sharing mutable state

The largest avoidable cost is repeated production KRDICT fixture construction. `tests/hanly_fixtures/krdict.py::build_fixture_krdict` runs the production builder repeatedly, and many tests call it again for each fetcher/config.

Add one process-cached immutable fixture database image, built from deterministic XML and fixed dates. Each test must copy/write those cached bytes into its own `tmp_path`; never share one mutable SQLite file. Tests that deliberately exercise builder determinism, failure preservation, schema construction, or mutation must continue to perform independent builds.

The audit's slowest observed cases included a 19.43 s unchanged-launch integrity test and several 3–7 s first-run/resource tests, largely because of repeated database construction. Measure the full suite before and after and report the delta. Do not weaken `PRAGMA quick_check`/identity behavior.

The real 512 MiB Zstandard bomb test costs roughly 7–10 seconds and allocates/streams a huge frame. Preserve one assertion tied to the shipped 512 MiB ceiling, but exercise streaming-overrun mechanics through an injectable/reduced ceiling so ordinary tests do not process >512 MiB. The declared-size-above-ceiling header test should remain cheap and real.

### Phase 6 — deterministic synchronization, targeted only

Replace polling sleeps and absolute elapsed-time thresholds with events/futures where the affected test already has a worker completion or dispatch seam. Prioritize:

- `test_hotkeys.py`
- `test_hover_lookup.py`
- `test_hover_lookup_e2e.py`
- `test_job_executor.py`
- `test_manual_lookup.py`
- `test_popup.py`
- `test_qt_hover_scheduler.py`
- `test_update_coordinator.py`

Always join/close workers in `finally` or fixture cleanup. Do not create a large generic test framework; a small `wait_until` helper with a monotonic deadline and useful failure message is enough where no event exists. Do not simply increase sleeps/timeouts.

### Phase 7 — cautious consolidation

Only perform consolidations that improve ownership:

- Move the concrete provider lifecycle/deferred-factory test from `tests/test_runtime.py` into `tests/test_easyocr_runtime.py`; keep the two resource-validation tests in `test_runtime.py` unless the file becomes genuinely empty.
- Optionally merge `benchmarks/dev/tests/test_hover_rate.py` and `test_desktop_probes.py` into `test_probes.py` if names/imports remain clear. This is low priority.
- Do not merge unrelated large files solely to hit a file-count target. `test_ci_workflows.py`, `test_update_service.py`, `test_hover_lookup.py`, and the KRDICT tests have distinct coherent responsibilities despite their size.
- Do not delete `test_package_imports.py` merely because it is short; package import smoke and dependency-boundary AST checks fail for different reasons. Merge only if both failure modes remain explicit.

## File-by-file disposition: `tests/`

| File | Disposition | Required action / rationale |
|---|---|---|
| `tests/__init__.py` | KEEP support | Package marker; no tests expected. |
| `tests/hanly_fixtures/__init__.py` | KEEP support | Intentional fixture export surface. |
| `tests/hanly_fixtures/korean.py` | KEEP support | Shared deterministic Korean fixtures. |
| `tests/hanly_fixtures/krdict.py` | OPTIMIZE | Keep production-builder fidelity; add immutable process-cached DB bytes copied per test. |
| `tests/krdict/test_build_release_asset.py` | STRENGTHEN | Fold constant-only manifest-name test into successful orchestration; cover build/validation/package failures and actual default date. |
| `tests/krdict/test_build_seed.py` | KEEP | Strong schema, determinism, failure preservation, and reused-source-ID coverage. |
| `tests/krdict/test_inspect_archive.py` | STRENGTHEN | Make legacy-console UTF-8 test emit Korean; current `--help` check proves nothing about Korean output. |
| `tests/krdict/test_package_resource.py` | KEEP/STRENGTHEN | Strong deterministic round trip; add atomic failure cleanup only if production contract supports it. |
| `tests/krdict/test_pipeline.py` | KEEP acceptance | Valuable real-resource checks; require it only in a production-resource/release-candidate lane. |
| `tests/krdict/test_real_records.py` | KEEP acceptance | Golden records and reused `77610` regression; version the fixture identity when required in CI. |
| `tests/krdict/test_runtime_schema.py` | KEEP | Shared validator/provider schema coverage; missing-index/table cases are optional hardening. |
| `tests/krdict/test_schema.py` | KEEP | Exact schema/index/non-unique-source-ID contract belongs here. |
| `tests/krdict/test_source.py` | KEEP | Strong XML hierarchy/scoping and normalization coverage. |
| `tests/krdict/test_validate_seed.py` | KEEP | Strong validation counts, reused IDs, metadata drift, query-plan, UTF-8 CLI checks. |
| `tests/test_app_composition.py` | KEEP | Strong worker/cache/target/retry composition seams. |
| `tests/test_app_config.py` | STRENGTHEN | Assert exact defaults and malformed/boolean config rejection, not just truthiness. |
| `tests/test_app_update.py` | STRENGTHEN | Retain platform guard; assert subprocess status; add Windows `.cmd` execution; remove version literal and tautological snapshot assertion. |
| `tests/test_application.py` | STRENGTHEN | Delete source-string wiring test; behavior already covered. Add actual quit callback coverage if missing. |
| `tests/test_capture_selector.py` | STRENGTHEN | Repair vacuous ordering/no-exception tests; make subprocess module path absolute/portable. |
| `tests/test_capture.py` | KEEP | Deterministic backend seams cover clipping, monitor choice, RGB, MSS, and snapping. |
| `tests/test_ci_workflows.py` | STRENGTHEN | Keep release security/provenance coverage; consolidate duplicate test, rename misleading one, prefer structural assertions. |
| `tests/test_control_center.py` | STRENGTHEN | Remove stale `detection_model`; avoid private mutation; isolate Qt global-state checks. |
| `tests/test_core_contracts.py` | KEEP | Broad immutable value/domain contract coverage. Rename any overclaim about typing if touched. |
| `tests/test_desktop_controller.py` | STRENGTHEN | Add forwarding coverage for `apply_config` and `set_capture_preferences`. |
| `tests/test_dev_dependencies.py` | FIX | Close static-import/importorskip false negative; use structural TOML parsing; keep as valuable CI guard. |
| `tests/test_dev_lookup.py` | KEEP/STRENGTHEN | Useful harness lifecycle/serialization/timeouts; ensure intended Pillow tests are declared, not silently skipped by dependency drift. |
| `tests/test_easyocr_provider.py` | KEEP/STRENGTHEN | Broad adapter coverage; house real reading-order behavior here; reduce only needless internal numeric coupling. |
| `tests/test_easyocr_runtime.py` | STRENGTHEN | Remove backend-selector residue; absorb concrete provider lifecycle test from runtime module. |
| `tests/test_engine_e2e.py` | KEEP integration | Real Kiwi/KRDICT with deterministic OCR; make intended CI lane install Kiwi or clearly label optional signal. |
| `tests/test_first_run.py` | KEEP/OPTIMIZE | Strong provisioning/offline/atomic identity coverage; use cached immutable DB fixture. |
| `tests/test_hotkeys.py` | STRENGTHEN | Replace fixed waits/untracked thread with explicit barriers and cleanup. |
| `tests/test_hover_controller.py` | KEEP | Deterministic cancellation/supersession/scheduler coverage. |
| `tests/test_hover_lookup.py` | STRENGTHEN | Strong orchestration; replace polling/conditional drains and guarantee shutdown. |
| `tests/test_hover_lookup_e2e.py` | STRENGTHEN | Rename fake-provider “real pipeline” to composition pipeline; event-driven result wait. |
| `tests/test_job_executor.py` | STRENGTHEN | Explicit completion and cleanup; avoid assertions failing invisibly inside worker threads. |
| `tests/test_kiwi_provider.py` | KEEP | Good normalized/fallback/prewarm/error coverage; installed-Kiwi smoke may remain optional. |
| `tests/test_korean_fixtures.py` | KEEP | Fixture and PNG metadata coherence is meaningful; do not delete shared assets. |
| `tests/test_krdict_provider.py` | STRENGTHEN | Bound thread join; avoid private connection reach if a public read-only assertion exists. |
| `tests/test_lookup_controller.py` | STRENGTHEN | Actually assert frozen request; cover latest pending delivery and close semantics. |
| `tests/test_lookup_pipeline.py` | STRENGTHEN | Inject raising OCR provider through constructor rather than private `_ocr_provider` mutation. |
| `tests/test_manual_lookup.py` | STRENGTHEN | Replace polling/elapsed assertions; isolate process environment/Qt ownership. |
| `tests/test_mouse_observer.py` | KEEP | Deterministic coalescing/stale/restart/idempotence coverage. |
| `tests/test_package_boundary.py` | KEEP/STRENGTHEN | Important dependency-direction guard; document limits for dynamic/relative imports. |
| `tests/test_package_imports.py` | KEEP | Small but distinct public-import smoke test; do not delete just for file count. |
| `tests/test_packaging.py` | STRENGTHEN | Inspect archive members/formats; add mocked build failures; retain useful negative Paddle guard. |
| `tests/test_popup.py` | STRENGTHEN | Replace wall-clock shutdown assertion; isolate Qt application ownership. |
| `tests/test_provider_interfaces.py` | STRENGTHEN | Keep protocol contracts; remove fake reading-order self-test and avoid excess annotation-shape coupling. |
| `tests/test_qt_hover_scheduler.py` | STRENGTHEN | Reduce wall-clock/thread-count fragility with event-loop-aware observation. |
| `tests/test_release_version.py` | STRENGTHEN | Parse TOML rather than regex; keep function and CLI matrices; cover malformed installed metadata. |
| `tests/test_resource_manager.py` | STRENGTHEN/OPTIMIZE | Rename or truly replace file in “replacing” test; add identity cases if needed; cache DB bytes. |
| `tests/test_runtime_trace.py` | KEEP | Strong privacy, JSON, timing, correlation, stale/capture coverage. |
| `tests/test_runtime.py` | CONSOLIDATE | Move concrete EasyOCR/provider lifecycle case to EasyOCR runtime suite; keep resource validation ownership. |
| `tests/test_signal_bridge.py` | KEEP | Deterministic signal/timer restoration and graceful exit coverage. |
| `tests/test_tray.py` | KEEP | Deterministic menu/status/dispatch/idempotence coverage. |
| `tests/test_update_coordinator.py` | KEEP/STRENGTHEN | Strong lifecycle/thread/hooks; replace polling and cover concurrent rejection/before-install cleanup. |
| `tests/test_update_service.py` | STRENGTHEN | Neutralize Paddle-named fixture; add malformed manifest/archive traversal/special-file cases; reduce bomb-test cost without weakening ceiling. |
| `tests/test_word_resolver.py` | KEEP/STRENGTHEN | Preserve semantic Hangul/geometry coverage; loosen exact typographic heuristic constants if implementation may evolve. |

## File-by-file disposition: `benchmarks/dev/tests/`

These are collected intentionally. Do not delete the benchmark suite or add it to `.gitignore`.

| File | Disposition | Required action / rationale |
|---|---|---|
| `benchmarks/dev/tests/__init__.py` | KEEP support | Package marker. |
| `test_benchmark_core.py` | KEEP | Strong metadata privacy, store recovery, validation, and statistics contracts. |
| `test_campaigns.py` | KEEP | Exercises real pipeline seams, stage timings, correctness failures, and warm summaries. |
| `test_cli.py` | KEEP | Useful parser/privacy/duration/lazy-import and production-boundary contracts. |
| `test_desktop_probes.py` | KEEP/optional merge | Useful capture shape/count contract; may move into `test_probes.py` for cohesion. |
| `test_diagnostics.py` | KEEP | Strong diagnostic round trip, null semantics, rendering, and self-contained artifacts. Keep `importorskip` only if Pillow is truly optional here. |
| `test_hover_rate.py` | KEEP/optional merge | Small but meaningful invocation-rate regression matrix; may move into `test_probes.py`. |
| `test_live_runner.py` | KEEP | Correlation, privacy-safe frame hashing, hotkey cleanup, and failure-tolerant cleanup. |
| `test_live_telemetry.py` | STRENGTHEN | Broad useful telemetry coverage; strengthen the serialization-only smoke with round-trip assertions. |
| `test_probes.py` | KEEP | Core probe, sampler, and package-analyzer behavior. Natural owner for the two optional tiny-file merges. |

## Additional hardening backlog — do only if it stays small

- `test_update_service.py`: malformed remote-resource fields, duplicate IDs, malformed JSON/content length, ZIP traversal, tar traversal/symlink/device rejection, activation cleanup and rollback-result assertions.
- `test_packaging.py`: inspect produced members for ZIP and tar and mock build subprocess failures.
- `test_release_version.py`: parse `[project]` and dependency pins structurally.
- `test_resource_manager.py`: test actual same-size/mtime identity transitions and clarify synthetic `os.access` behavior.
- `test_first_run.py`: malformed runtime/partial persistence failure paths if not already covered.

Do not let this backlog expand the cleanup indefinitely. Complete Phases 1–5 first, run gates, then add only high-risk missing cases that expose real production branches.

## Acceptance criteria

1. Existing Windows POSIX failure cannot recur; POSIX handoff runs only on POSIX, and Windows `.cmd` behavior has executable Windows coverage.
2. Ordinary pushes exercise a Windows test lane without renaming the existing required `quality` check.
3. No test pins the current release version literal or asserts production wiring through source formatting.
4. The dependency guard fails for a bare undeclared static import even if the file later calls `importorskip` with the same module.
5. No test fixture presents Paddle, `ocr_backend`, or EasyOCR model downloads as a live configurable/managed architecture.
6. KRDICT schema, duplicated raw source IDs, and ID `77610` regression remain intact.
7. Production-resource tests remain explicit and do not silently pretend to run without their artifact.
8. Full-suite wall time is measured before/after; fixture caching preserves per-test isolation and materially reduces repeated KRDICT build cost.
9. Run and report:

   ```text
   python -m pytest
   python -m ruff check packages packaging tests tools benchmarks
   python -m mypy packages packaging tests tools benchmarks
   ```

10. Report exact files deleted/merged, why each deletion was safe, before/after test counts and wall time, skips with reasons, and any item deliberately deferred.
11. Stop at review handoff. No commit/tag/push/release/workflow dispatch.

## Suggested skills for the executing agent

- `superpowers:receiving-code-review` — validate each audit claim against the current moving checkout before editing.
- `superpowers:systematic-debugging` — for any failure whose cause is not already proven.
- `superpowers:test-driven-development` — when adding the Windows `.cmd`, dependency-guard, or archive-safety regressions.
- `superpowers:verification-before-completion` — required before reporting the suite clean.

## Expected final report shape

- Outcome first: pass/fail totals, lint/type results, and measured runtime delta.
- Immediate CI fix and Windows coverage.
- Tests deleted, rewritten, consolidated, and intentionally retained.
- Architecture residue removed.
- Deferred hardening items, each with a concrete reason.
- Explicit confirmation that no Git/release action was performed.
