# Test Suite Audit Review Handoff

## Bundle

- Member issues: none — execution of `hanly-test-suite-audit-handoff-2026-09-04.md`
- Implementation ecosystem: Claude Code (Opus 5), single implementation run
- Date: 2026-09-04
- Base: `72a20d4` on `main`, plus the uncommitted `_posix_handoff` marker that existed at handoff

## Implemented

- Gated the POSIX handoff tests on the platform the script is written for, and made them assert the subprocess exit status.
- Added Windows `.cmd` handoff coverage that executes the real rendered script's swap and rollback, with only its two relaunch lines replaced by a marker command.
- Added a `windows-tests` job to `ci.yml` so every push exercises Windows, leaving the required `quality` job name untouched.
- Closed two false negatives in the dependency guard: `pytest.importorskip` now excuses an import only when it precedes it **in the same lexical scope**, so neither a guard written below an import nor one in a neighbouring function covers it.
- Replaced or repaired eleven tests that asserted their own fixtures, production source formatting, a release version literal, or nothing at all.
- Removed OCR-backend residue from three fixtures so no test presents Paddle, `ocr_backend`, or a managed EasyOCR model as live architecture.
- Cached the KRDICT fixture database as immutable bytes copied per test, cutting production builds per suite run from 47 to 2.
- Replaced wall-clock thresholds and count-bounded polling with bounded joins, deadlines, and event-loop-aware waits, and made every test thread joined and asserted dead -- the two shutdown threads release their blocker and join in `finally`, so a failed assertion cannot strand one.
- Moved the concrete provider lifecycle test to the EasyOCR runtime suite, onto the fakes that suite already owns.

## Main expected behavior

The suite runs green on Windows and Linux, in a CI-equivalent environment carrying only the root dev dependency group. No test launches a process with a UI, no test thread outlives its test, and no test depends on how fast the machine happens to be.

The Windows swap and rollback are now executed: the real rendered `.cmd` runs, moves the bundles, and reports its exit status. The relaunch itself is **not** executed — `start "" "%INSTALL%\hanly-desktop.exe"` is replaced in the test copy by a marker command, so what the tests prove about it is that the script reached the relaunch with the right bundle in place. That the relaunch is the real `start` line, in the right position, stays covered structurally.

## Architecture / seams touched

No production behavior changed. `packages/` and `tools/` are untouched; the only non-test file changed is `.github/workflows/ci.yml`.

- The POSIX and Windows handoff branches of `render_handoff_script` are now each covered on the platform that runs them.
- `tests/hanly_fixtures/krdict.py` gained `write_krdict_database`; `build_krdict_database` still performs a real production build for callers that need one.

## Relevant files / diff areas

- `.github/workflows/ci.yml`
- `tests/test_app_update.py`, `tests/test_ci_workflows.py`, `tests/test_dev_dependencies.py`
- `tests/test_application.py`, `tests/test_capture_selector.py`, `tests/test_provider_interfaces.py`
- `tests/test_control_center.py`, `tests/test_easyocr_runtime.py`, `tests/test_runtime.py`, `tests/test_update_service.py`
- `tests/hanly_fixtures/krdict.py`, `tests/test_engine_e2e.py`
- `tests/test_hotkeys.py`, `tests/test_job_executor.py`, `tests/test_manual_lookup.py`, `tests/test_popup.py`, `tests/test_qt_hover_scheduler.py`, `tests/test_update_coordinator.py`
- `tests/krdict/test_build_release_asset.py`, `tests/krdict/test_inspect_archive.py`
- `benchmarks/dev/tests/test_live_telemetry.py`

## Implementation-side validation already run

- `python -m pytest` → 695 passed, 4 skipped, 28.61 s (base: 688 passed, 4 skipped, 36.28 s).
- `python -m ruff check packages packaging tests tools benchmarks` → All checks passed.
- `python -m mypy packages packaging tests tools benchmarks` → no issues in 140 source files.
- CI-equivalent venv (root dev group plus both editable packages, no extras) → 681 passed, 15 skipped, 14.15 s; Ruff and mypy clean there too.
- Every thread the suite starts is joined and asserted dead; no process, console, or window survives a run.
- Fixture-cache A/B, back to back on the same machine: 47 production builds (11.5 s / 24.6 s in the builder across two uncached runs) → 2 builds, 0.17 s.
- Focused Windows check: `python -m pytest tests/test_app_update.py -v` → 37 passed, 3 skipped, 2.38 s, with no surviving process, console, or window.

## Known limitations / intentionally unvalidated areas

- **The Windows failed-rollback branch is not executed.** Making `move "%BACKUP%" "%INSTALL%"` fail requires the install path to be occupied between two moves inside a script that is already running, which cannot be arranged without racing it. It stays covered structurally by `test_the_rollback_relaunch_is_gated_on_the_rollback_actually_succeeding[True]`, and executably on POSIX through the shimmed `mv`.
- **The Windows `.cmd` relaunch itself is not executed.** `start` goes through the shell: with the executable present it launches a real process, and without it a modal error. Neither belongs in a unit test, so the two relaunch lines are substituted for a marker after asserting that exactly two exist. The swap, the rollback, and the exit status are executed; the relaunch command is covered only by that count assertion and by `test_the_rollback_relaunch_is_gated_on_the_rollback_actually_succeeding`, which pins its text and position. A change to what `start` launches would pass unnoticed by execution.
- **`windows-tests` has never run.** The job was added but not dispatched, per the no-dispatch constraint. It mirrors the `quality` install steps and runs the suite only — lint and type checks stay on the Linux lane.
- **Wall-clock numbers on this machine are unreliable.** Identical runs ranged from 18 s to 238 s, apparently from on-access scanning. The deterministic figure for the fixture work is the build count (47 → 2); treat the times as indicative.
- **The dev runtime here is 3.13, and CI's floor is 3.10.** The guard reads `sys.stdlib_module_names` from whichever interpreter runs it, so a module that is standard library on 3.11+ but not on 3.10 -- `tomllib` -- passed locally and failed every 3.10 lane. `_NEWER_THAN_THE_SUPPORTED_FLOOR` now subtracts it and `test_the_guard_models_the_oldest_supported_runtime_not_this_one` pins the floor, but the set is hand-maintained: raising `requires-python` fails that test rather than updating itself. No 3.10 interpreter exists on this machine, so the fix was verified against a simulated 3.10 stdlib set rather than a real one.
- **The suite was not re-run on Linux.** POSIX handoff tests skip on Windows, so the three of them are exercised only by CI.
- `run_desktop`'s update-setting wiring is asserted through the syntax tree rather than by execution, because reaching it needs Qt, which the CI quality lane does not install.

## Deviations from the audit, with reasons

- **`test_the_desktop_passes_the_persisted_setting_to_the_coordinator` was rewritten, not deleted.** The audit called it a duplicate of the behaviour tests above it; those tests call `_update_coordinator` directly with the flag, so nothing else covered the composition site. It now reads the call out of the AST — structural rather than formatting-dependent — which keeps the coverage the audit's own rule 4 requires.
- **The global build-workflow shell guard was removed rather than kept.** Per the audit's stated preference, the `shell: bash` contract now sits on the version-check step that needs POSIX expansion, inside `test_build_context_values_are_env_backed_in_shell_commands`.
- **`benchmarks/dev/tests/test_hover_rate.py` and `test_desktop_probes.py` were not merged into `test_probes.py`.** The audit marked this optional and low priority; the files name their subjects clearly as they are.
- **`tests/test_capture_selector.py`'s subprocess path was left alone.** The audit asked for it to be made absolute and portable; it already uses `sys.executable` with `cwd=tmp_path`.
- **`_drain` in `tests/test_hover_lookup.py` was left alone.** It drains an in-process queue with no sleep and no clock, so it is deterministic rather than a poll.

## Deferred hardening

- **`test_update_service.py` extra cases** (malformed remote fields, duplicate IDs, ZIP/tar traversal, symlink and device rejection) — revisit when the update service next changes how it reads a remote manifest or unpacks an archive.
- **`test_packaging.py` archive member inspection and mocked build failures** — revisit when the packaging spec or the archive format changes.
- **`test_release_version.py` structural TOML parsing** — revisit when the repository targets 3.11 as its minimum, at which point `tomllib` removes the reason for the regex.
- **`test_resource_manager.py` same-size/mtime identity transitions** — revisit when resource identity stops being checksum-led.
- **`test_first_run.py` malformed runtime and partial persistence paths** — revisit when first-run provisioning gains another failure mode.
- **`test_web_engine_is_prepared_before_the_shared_qapplication_exists`** asserts the order of two calls the test itself makes; the real order is now covered by the rewritten `test_the_selector_prepares_the_ocr_runtime_before_qt` — revisit when `select_capture_area` next changes.

## Suggested review targets

- The Windows handoff substitution: whether replacing the relaunch line is an acceptable trade for executing the real swap, and whether the count assertion is a strong enough guard on the part that is not executed.
- `tests/test_dev_dependencies.py`: whether the positional `importorskip` rule holds for every legitimate pattern in the suite, and whether the `ast.literal_eval` fallback cross-checked against `tomllib` is the right shape for a 3.10 minimum.
- The KRDICT fixture cache: that no test that needs an independent build now gets a copy instead.
- `tests/test_easyocr_runtime.py`: the shared fakes now record thread identity for every test in the module, not only the moved one.

## Review assignment

Human-selected after implementation. Not started.
