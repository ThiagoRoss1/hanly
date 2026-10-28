# Hanly V2 post-redesign QA

**Date:** 2026-10-21  
**Workstream:** design/hanlyV2  
**Source:** 0554d96b3ef65bebcc87acf68ed53091b75546b3 (design/hanlyV2, clean at start)  
**Platform:** macOS 26.6.2 (25G83), arm64  
**Build exercised:** Hanly 1.1.0 debug-only .app bundle built from this checkout

## Assessment

The frontend checks, unit/UI suites, Python theme contrast suite, and debug app builds passed. The native session found two medium-severity UI defects: custom expanded panels did not show their contents, and invalid-region feedback was hidden inside the closed Capture settings disclosure.

Native capture, OCR, hover lookup, and popup behavior remain unverified because macOS Screen Recording and Accessibility grants were both missing (0/2). The Lab instrumentation attempt failed before launching the app and produced no performance samples. This report is a broad post-redesign QA pass with explicit coverage limits, not a complete capture-path or performance signoff.

## Coverage matrix

| Area | Status | Evidence and limit |
|---|---|---|
| Source/build identity | Pass | Clean HEAD 0554d96b3ef65bebcc87acf68ed53091b75546b3; frontend, Tauri debug executable, and debug bundle builds succeeded. This is not packaged release acceptance. |
| Control Center shell and navigation | Pass, sampled | Direct native launch; Capture, Permissions, Appearance, Updates, and Logs visited; light/dark theme and normal/compact rail viewed and restored. |
| Window sizing and full screen | Pass, sampled | Minimum and larger viewports, full-screen entry and keyboard exit. No visible clipping or horizontal overflow. Minimize and title-bar dragging were not tested. |
| Appearance controls | Pass, sampled | Popup typeface, size, technical-details level, navigation, and theme choices changed and restored. Popup itself was not rendered. |
| Capture configuration | Partial | Monitor, hover delay, engine preload, and selected-region controls exercised. Selected-region panel did not render; see QA-UI-01. Preferences were restored. |
| Keyboard and accessibility | Partial | Basic Tab focus and accessibility-tree inspection. No full keyboard-only or screen-reader audit; expanded-state mismatches are recorded in QA-UI-01. |
| Permissions and capture start | Blocked | Native app reported Screen Recording and Accessibility required; Permissions showed 0/2. No grants changed. |
| OCR, hover, dictionary popup | Blocked | No actual capture or recognized text due to missing grants. Popup styling and placement were not accepted. |
| Updates | Partial | Current version/resource state and Check now flow observed. No install action. Expanded resource/activity content did not render; see QA-UI-01. |
| Logs | Partial pass | Filters, subsystem, search, clear-search, and refresh exercised. Clear, Export diagnostics, and retry were not activated. |
| Quit/relaunch | Pass, sampled | Quit confirmation canceled, then quit and direct relaunch succeeded. Process-family/orphan enumeration was denied by the shell sandbox. |
| Automated checks | Pass | TypeScript check; 12 Node tests; 52 UI tests; 36 Python theme contrast tests; frontend and Tauri debug builds. UI tests emitted jsdom canvas getContext() warnings while passing. |
| Lab performance | Blocked | Session ended in 0.4 s with desktop_launch_failed / RuntimeError, before app startup or any process sample. No latency, CPU, RSS, or thread conclusions can be drawn. |
| Screenshot evidence | Blocked | Live CUA views were inspected but not saved. screencapture failed with “could not create image from display”; system permissions were left unchanged. |

## Findings

### QA-UI-01 — Expanded panels stay visually collapsed (P2)

**Steps**

1. On Capture, select **Selected region** and wait for the transition.
2. On Updates, activate **Dictionary and resources**, then **Update activity**.
3. Inspect the rendered view and the accessibility state.

**Expected:** each expanded section shows its controls or contents after the transition.

**Observed:** Capture’s accessibility tree exposed the Region heading, coordinate fields, and actions, but the Region panel did not appear. On Updates, both disclosures reported expanded state and their contents appeared in the accessibility tree, while the rendered rows stayed at their closed height. This reproduced when toggling and revisiting the pages.

**Scope and evidence:** native CUA observation on the debug bundle at both default-sized and smaller windows. Written steps are in [native-observations.txt](../../../artifacts/lab/runs/20261021-043207-hanly-v2-qa/native-observations.txt). No screenshot file could be saved.

**Observed facts:** the affected Capture and Updates content containers use the shared .region-collapse class and toggle data-open; AX state/content changed while visual content did not.  
**Suspected cause:** a rendering/layout issue in the shared collapse treatment. Computed styles and browser internals were not inspected, so the precise cause is undetermined.

### QA-UI-02 — Invalid region feedback is hidden when settings are closed (P2)

**Steps**

1. Select **Selected region**.
2. Set region width to 1 and activate **Apply** while **Capture settings** is collapsed.
3. Inspect the accessibility tree, then expand Capture settings.

**Expected:** a visible validation message appears next to the invalid region input/action.

**Observed:** Apply left the saved rectangle unchanged. No error appeared in the accessibility tree while Capture settings was closed. Expanding it exposed “The region must be at least 2 × 2 pixels.” The message is inside the Capture settings disclosure in the current implementation (CapturePage.tsx).

**Scope and evidence:** reproduced once during the native session; written record is in [native-observations.txt](../../../artifacts/lab/runs/20261021-043207-hanly-v2-qa/native-observations.txt). The input/action were activated through the accessibility interface because the selected-region panel itself was visually absent. The feedback location is confirmed; the exact user-visible visual presentation of the message was not captured.

**Observed facts:** invalid width was rejected, the stored region remained 537 × 334, and the error text was exposed only after opening Capture settings.  
**Suspected cause:** the shared formError placement follows the settings controls even when the error originated from region validation. This is based on source structure; no code change was made.

## Agent work sections

### A — Visual inventory (visual_inventory)

Performed a source and handoff inventory, not a native UI session. Mapped the Control Center shell, navigation, VillageScene/theme animation, runtime card, popup success and non-success surfaces, Tauri title bar, UI tests, and Lab checks. The agent correctly treated the prior handoff and historical Lab report as non-current evidence. Native visual results for these surfaces are recorded under the coordinator section and in the coverage matrix.

### B — Controls inventory (controls_inventory)

Performed a source/test inventory, not a native UI session. Mapped the six Control Center pages and the React UI suite, including appearance (test lines 217–312), capture (578–722), shortcuts (723–792), permissions (794–852), updates (853–986), and logs (987–1038) in apps/desktop/tests/ui/desktop-pages.test.tsx; also identified service coverage in tests/test_control_center.py. Mock IPC coverage does not establish native rendering.

### C — Native app session (coordinator)

Built and opened the debug .app, exercised native navigation, appearance, Capture settings, window sizing/full screen, Updates, Logs, Permissions, and quit/relaunch. Restored the real profile settings, did not grant permissions, and left the app open on Capture with capture stopped. Native steps and limitations are in [native-observations.txt](../../../artifacts/lab/runs/20261021-043207-hanly-v2-qa/native-observations.txt).

### D — Logs and performance checks (logs_perf_checks)

Reviewed the Logs and Lab instrumentation paths and ran the requested automated checks. The agent confirmed Lab samples text-free process metrics at 250 ms intervals and requires a compatible baseline before performance comparisons. No native performance evidence was produced in this run. CC-CONTROLS Lab probing was not repeated because it overlaps the React mock-IPC suite.

## Automated results and evidence

All checks below ran against the source commit listed above:

| Check | Result | Log |
|---|---:|---|
| npm run --prefix apps/desktop check | Pass | [npm-check.log](../../../artifacts/lab/runs/20261021-043207-hanly-v2-qa/npm-check.log) |
| npm test --prefix apps/desktop | 12 passed | [npm-test.log](../../../artifacts/lab/runs/20261021-043207-hanly-v2-qa/npm-test.log) |
| npm run --prefix apps/desktop test:ui | 52 passed | [npm-test-ui.log](../../../artifacts/lab/runs/20261021-043207-hanly-v2-qa/npm-test-ui.log) |
| .venv/bin/python -m pytest tests/test_theme_contrast.py -q | 36 passed | [pytest-theme-contrast.log](../../../artifacts/lab/runs/20261021-043207-hanly-v2-qa/pytest-theme-contrast.log) |
| npm run --prefix apps/desktop build | Pass | [frontend-build.log](../../../artifacts/lab/runs/20261021-043207-hanly-v2-qa/frontend-build.log) |
| Cargo Tauri debug build | Pass | [tauri-build.log](../../../artifacts/lab/runs/20261021-043207-hanly-v2-qa/tauri-build.log) |
| Tauri debug .app bundle | Pass | [tauri-bundle-build-retry.log](../../../artifacts/lab/runs/20261021-043207-hanly-v2-qa/tauri-bundle-build-retry.log) |

The UI test run printed jsdom warnings that HTMLCanvasElement.getContext() is not implemented in its environment; both UI test files and all 52 tests passed.

The Lab attempt is recorded at [20261021-061310-run/summary.md](../../../artifacts/lab/runs/20261021-043207-hanly-v2-qa/lab-run/20261021-061310-run/summary.md), with its [events](../../../artifacts/lab/runs/20261021-043207-hanly-v2-qa/lab-run/20261021-061310-run/events.jsonl) and [process samples](../../../artifacts/lab/runs/20261021-043207-hanly-v2-qa/lab-run/20261021-061310-run/processes.jsonl). It recorded commit 0554d96b3ef6, clean checkout, configured backend vision, observed backend none, zero pointer/capture/lookup events, and one empty process sample. Since the failure occurred before the app launched, it gives no performance result and does not show that the direct app launch failed; the bundle launched through CUA.

## Gaps and follow-up

- Repeat capture, OCR, hover lookup, dictionary result, popup size/typeface/details, popup placement, and close behavior after Screen Recording and Accessibility are granted in the test environment.
- Repeat Lab startup and performance capture, then compare only with a compatible baseline and the recorded source/backend provenance.
- Recheck selected-region and Updates disclosure rendering after the UI issue is addressed, including at the minimum supported window size.
- Repeat invalid-region validation from a visually accessible form and verify the message is visible without opening unrelated settings.
- Attach native screenshots on a host/API path that can save them without changing macOS permissions.
- Complete the remaining shortcut interactions and destructive/export log actions in a disposable profile; they were outside this pass’s native coverage.

## Cleanup and final app state

The real user preferences were restored and re-read from /Users/thiago/.config/hanly/config.json. The initial snapshot is preserved at [config.initial.json](../../../artifacts/lab/runs/20261021-043207-hanly-v2-qa/profile/config.initial.json); the checked final values are in [config.json](../../../artifacts/lab/runs/20261021-043207-hanly-v2-qa/profile/config.json). Capture mode is full monitor, target follows the cursor, hover delay is 20 ms, backend is Apple Vision, lookup preload is when capture starts, and auto-start remains unset.

No OS permissions were granted, no OCR backend was changed, no real log was cleared, and no diagnostics export was written. The temporary debug bundle remains available because it is the verified app left open for the user. At handoff, it is on Capture with status **Stopped · Runtime ready · Engine sleeping** and the Capture settings disclosure collapsed.
