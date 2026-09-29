# V1 cleanup execution checkpoint

Status: Phase A, Part 1 committed as `139032d`; Part 2 locally validated.
Base: `clean/arch-optimization` at `5c510e5`; clean worktree at entry.

## Boundaries

1. Organize desktop modules by feature without changing behavior or public root exports.
2. Remove only proven dead/redundant code and fix reproducible, bounded defects. No broad code refactor before V1.
3. Simplify authored comments and curate historical documentation. Defer editorial README, AGENTS.md, and CLAUDE.md work.

Commit and validate each part separately. Do not push, merge, tag, release, or begin Phase B. If a session limit interrupts the run, update this checkpoint with the last completed commit and remaining gates.

## Part 1 proposed move manifest

All paths below are relative to `packages/hanly-app/src/hanly_app/`. The destination names are internal, not compatibility aliases. The root `hanly_app` exports and `hanly_app.cli:main` remain stable. Asset paths remain unchanged.

| Current | Destination |
|---|---|
| `capture.py` | `acquisition/capture.py` |
| `capture_selector.py` | `acquisition/selector.py` |
| `text_acquisition.py` | `acquisition/direct_text.py` |
| `text_acquisition_ax.py` | `acquisition/ax.py` |
| `text_acquisition_uia.py` | `acquisition/uia.py` |
| `hover_controller.py` | `hover/controller.py` |
| `hover_lookup.py` | `hover/lookup.py` |
| `hover_target.py` | `hover/target.py` |
| `mouse_observer.py` | `hover/mouse_observer.py` |
| `qt_hover_scheduler.py` | `hover/qt_scheduler.py` |
| `lookup_controller.py` | `lookup/controller.py` |
| `lookup_process.py` | `lookup/process.py` |
| `lookup_evidence.py` | `lookup/evidence.py` |
| `job_executor.py` | `lookup/executor.py` |
| `ocr_preload.py` | `lookup/preload.py` |
| `process_transport.py` | `lookup/transport.py` |
| `popup.py` | `popup/presentation.py` |
| `popup_darwin.py` | `popup/macos.py` |
| `qt_popup.py` | `popup/qt.py` |
| `control_center.py` | `control_center/bridge.py` |
| `control_center_host.py` | `control_center/host.py` |
| `control_center_process.py` | `control_center/process.py` |
| `app_build_identity.py` | `updates/build_identity.py` |
| `app_hup.py` | `updates/package.py` |
| `app_inventory.py` | `updates/inventory.py` |
| `app_manifest.py` | `updates/manifest.py` |
| `app_update.py` | `updates/desktop_update.py` |
| `app_update_handoff.py` | `updates/handoff.py` |
| `app_update_helper.py` | `updates/helper.py` |
| `app_update_install.py` | `updates/installer.py` |
| `app_update_journal.py` | `updates/journal.py` |
| `app_update_macos.py` | `updates/macos.py` |
| `app_update_plan.py` | `updates/plan.py` |
| `app_update_runner.py` | `updates/runner.py` |
| `app_update_tree.py` | `updates/tree.py` |
| `app_xattr_darwin.py` | `updates/xattr_macos.py` |
| `update_coordinator.py` | `updates/coordinator.py` |
| `update_service.py` | `updates/resource_service.py` |
| `owned_cleanup.py` | `updates/cleanup.py` |

Before moving, inventory relative imports, dynamic import strings, lazy root exports, `__file__` paths, frozen entry points, release workflow imports, tests, tools, benchmarks, and documentation links. Every new package needs `__init__.py` for PyInstaller discovery. No permanent old-path wrappers.

## Part 2 initial candidate

`capture_recovery.py` is imported by its own test but has no located production caller. Recheck exports and dynamic references before removing it and its orphaned tests. Other removals require equivalent evidence; a passing static linter alone is insufficient.

Part 2 check: the module is referenced only by `tests/test_capture_recovery.py` among active code, and its one-shot recovery was rolled back in September. Removed that orphaned module and test; the historical checkpoint retains the measurements and rationale. The previous cleanup already removed the other verified app-internal dead definitions from the audit. Kept the staged OCR replay and metrics helpers as intentional developer interfaces, not live production code. The Windows prompt-shutdown failures are reproducible only in the supplied Windows CI log; both cases pass with macOS Qt offscreen and abort under this sandbox's native GUI. No speculative selector change is justified on Mac. Focused capture/microscope tests: 103 passed; Ruff clean; mypy clean on 305 files.

## Part 3 document policy

Inventory each Markdown file by active authority, unique evidence, supersession, inbound links, and privacy findings. Keep current architecture and V1 execution authority; archive unique history with date-first names; delete only redundant or superseded material after repairing links. The large HAN-43/44 report's embedded Git diff is an initial candidate for trimming, not its unique review findings. Do not rewrite Git history to address privacy without human approval.

## Baseline and validation

Entry Ruff: clean. Entry mypy: clean on 301 source files. Entry full pytest on the untouched branch aborted in the macOS native popup fixture after `test_control_center_identity.py` failed; this is not a post-move regression. The untouched portable suite yielded 2,364 passed, 4 failed, 3 skipped: both `test_process_probe.py` cases cannot call sandboxed `ps`, and two Vision OCR fixture cases return no regions. The user's current Windows CI log for this same pre-move branch reports 117 native passes, 33 skips, and two failures in `test_capture_prompt_shutdown.py`: the prompt case exceeded its three-second limit and the region case never recorded the quit callback. Revisit as a bounded Part 2 defect if a production cause can be established; otherwise leave exact Windows repro and review steps in the handoff.

Part 1 relocated 39 modules into six feature packages and updated imports, workflows, tests, and the code map. Root symbol exports and the CLI entry point remain unchanged. After repairing five relocation-specific portable test failures, the focused checks pass (8/8); Ruff and mypy pass (307 files). The full post-move portable run exactly matches the untouched baseline: 2,364 passed, 4 failed, 3 skipped, with no new failure. Python 3.10 syntax compilation and the CLI help entry point pass. The targeted native capture-prompt test aborts under the sandboxed macOS GUI, but both cases pass with Qt offscreen. The broader native run was interrupted while blocked in a sandboxed UI test; the offscreen native suite was also interrupted before running tests. The Windows shutdown result remains unconfirmed here.

The macOS app and ZIP were built from `139032d` (verified in `hanly-build.json`). ZIP reconstruction, inventory, and the packaged worker's runtime/OCR/morphology/dictionary/version stages all pass. `hdiutil` refused DMG creation with “device not configured,” and the packaged Control Center window aborted in the sandboxed Qt/WebEngine runtime, so neither DMG nor window smoke is verified. Remote CI is pending until the human pushes.

After Part 1, check imports, frozen discovery, release imports, Python 3.10 compatibility, full portable pytest, Ruff, mypy, feasible native tests, and a committed-SHA macOS packaged smoke. After Part 2, run focused regression checks and full code gates. After Part 3, check Markdown links, privacy, invariants, full gates, and the final stamped package. Record exact results here or in the final Review Handoff.
