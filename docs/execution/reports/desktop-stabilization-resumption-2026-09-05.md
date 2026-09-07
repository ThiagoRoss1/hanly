# Desktop stabilization — resumption assessment

Date: 2026-09-05. Scope: inspect current implementation, reconcile the stale checkpoint with later evidence, identify remaining completion work, and prepare a Claude resumption packet. This was a targeted status/plan-coverage assessment, not a full Phase B review. No product code was changed.

## Executive assessment

Most of the planned implementation is present. Claude did not stop at the build described in the old checkpoint: a later implementation handoff records a completed Windows build and successful frozen-provider smoke. The current artifact exists and includes Kiwi.

The remaining work is a short completion pass plus acceptance, not another eight-part implementation. However, the handoff's `Implementation complete; native acceptance pending` label is too strong for several plan requirements still missing or only partially implemented. Resolve the specific gaps below, then perform the final acceptance run.

Estimated progress, based on capabilities rather than lines or checked boxes: **roughly 80–90% of the planned implementation is present**. This is not a release-readiness percentage. Native macOS/Linux acceptance, Windows interactive lookup acceptance, and clean-profile coverage remain outstanding.

## Where Claude actually stopped

| Evidence | Observed state |
|---|---|
| Original checkpoint, modified 20:25:58 | Stage A4; said the Windows build was running and the handoff still needed writing |
| Current executable | `dist/windows/hanly-desktop/hanly-desktop.exe`, 54,211,824 bytes; modified 21:25:10 |
| Current ZIP | `dist/hanly-desktop-windows.zip`, 613,383,233 bytes; modified 21:31:02 |
| Implementation handoff, modified 21:32:48 | Build and frozen smoke complete; implementation handoff already written |
| Repository | `main`, HEAD `75c188e`; uncommitted implementation plus new files |

Times are local filesystem timestamps. The latest durable evidence places Claude at **A5 handoff after A4 validation**, not in the middle of a running build. No Python/Hanly process was returned by the accessible `Get-Process` check. Full process command-line inspection through CIM was denied, so this is not a forensic statement about all past/background processes.

The token-limit event itself was not inspected; this assessment uses repository files and their timestamps. Do not restart a build merely because the older checkpoint said one was running.

Current ZIP SHA-256:

```text
a27ce47c1116a5c491144205977465a2990c2b5383125df0c7936ce487d89159
```

## Implemented work

| Plan area | Present implementation |
|---|---|
| WebEngine abort | `qt_bootstrap.py` centralizes QApplication construction with a program argument |
| Missing Kiwi | Shared PyInstaller spec collects Kiwi, its models, and `_kiwipiepy` |
| Readiness and errors | `runtime_status.py`, initialization-error callbacks, persistent rotating diagnostics |
| Main-window lifecycle | `control_center_host.py` owns pywebview's loop; competing desktop `exec` removed |
| Interface-first startup | `startup.py` and `_DesktopSession` prepare resources behind the main window |
| Settings selection | Persistent monitor/region settings and bridge action for the selector |
| Packaging verification | `self_check.py`, frozen inventory/provider harness, post-build CI steps |
| Documentation/tests | Updated READMEs/CODE-MAP, focused tests and native subprocess integration tests |

No engine-package source changes were listed by git status. The direction of the refactor follows the approved desktop scope rather than replacing the OCR engine or adding a new backend framework.

## What was verified in this assessment

Fresh checks against the current working tree:

```text
python -m pytest tests/test_startup.py tests/test_runtime_status.py
  tests/test_control_center_host.py tests/test_qt_bootstrap.py
  tests/test_diagnostics.py tests/test_application.py
  -q -p no:cacheprovider --basetemp=C:\Hanly\artifacts\resume-verification-temp
=> 59 passed in 0.92s

python tools/smoke_packaged_runtime.py dist/windows/hanly-desktop --inventory-only
=> inventory ok; Kiwi packages, native extension, and sampled model files present
```

The commands used `.venv/Scripts/python.exe`. A diagnostic comparison of all 36 app modules in the current source against the executable's PYZ found no differences in the compared bytecode/constants/names, ignoring filenames and line tables. This is useful freshness evidence, not a proof of all assets, dependencies, or behavior.

The later Claude handoff additionally **records**, but this assessment did not rerun:

- 828 tests passed, 4 skipped, integration excluded.
- Ruff clean; mypy clean across 162 files.
- Two real WebEngine startup tests passed.
- One real window lifecycle test and one source-desktop startup test passed.
- Windows native build completed.
- Frozen provider smoke passed: OCR read the fixture, Kiwi analyzed Korean, KRDICT returned an entry.

Keep those results attributed to the previous run. Do not substitute the stale checkpoint's 821-test count for the later handoff's 828.

## Remaining completion work — ordered and bounded

### R1. Finish UI-thread dispatch for main-interface actions

**Evidence:** `control_center.py:269–289` calls lifecycle Start/Resume/Pause directly. `_apply_live_config():511` calls the desktop controller directly. The bridge receives pywebview callbacks off Qt, while `_DesktopSession.start/pause/resume/apply_config` simply forwards them. `_select_capture_area()` marshals the overlay itself, but the surrounding pause/resume and settings application are still direct calls.

**Finish:** marshal the complete mutating action through the existing Qt dispatcher, including lifecycle/settings and selector pause -> selection -> apply -> resume. Preserve cancellation, error propagation, and shutdown cancellation. Use one existing boundary rather than introducing a generic command bus. Add a focused regression asserting the thread at the real consumer seam, plus one real UI Start/Pause path.

This is a confirmed dispatch gap from source inspection. Its exact user-visible failure was not reproduced in this assessment.

### R2. Complete tray recovery and explicit Quit

**Evidence:** `application.py:264` sets `restorable=True` whenever `tray.start()` returns; there is no capability check in `tray.py`. The HTML/JS/bridge expose no explicit Quit action. Thus the stated cross-platform fallback is not complete: successful tray initialization does not prove that Linux Xorg has a usable Open menu/default restoration action.

**Finish:** add a main-window Quit action through the same Qt dispatch path; allow hide-on-close only with a working restoration route. Use backend capabilities or an explicitly wired default restoration action. Keep the main window reachable when no route exists. Validate macOS native integration on a Mac rather than describing it as already handled merely because the host has a boolean flag.

### R3. Make the cold-profile smoke genuinely isolate OCR models

**Evidence:** `_ProfileContext.__enter__()` in `tools/smoke_packaged_runtime.py:158` redirects `LOCALAPPDATA`/`XDG_CONFIG_HOME` and removes `HANLY_KRDICT_DB`, but leaves the home directory and EasyOCR override variables inherited. The installed EasyOCR configuration resolves models through `EASYOCR_MODULE_PATH`, `MODULE_PATH`, or `~/.EasyOCR`.

**Finish:** explicitly direct EasyOCR's model location to the temporary profile and remove conflicting inherited overrides. Keep deterministic preinstalled-resource and online cold-profile scenarios distinct. Add a regression proving an external developer model cache cannot make the cold test pass. Do not clear the user's real model directory.

The prior frozen smoke still proves frozen providers can run; it does **not** establish the stronger claim that no developer OCR cache was used.

### R4. Close the packaged UI/lookup acceptance gap

**Evidence:** `SELF_CHECK_MODES` contains only `worker`; `test_packaged_desktop.py` checks inventory and worker stages, not the frozen main window or JS bridge. The real UI/startup tests run the source interpreter. The worker smoke invokes providers independently; it is not a real screen-to-popup lookup.

**Finish:** exercise the built executable's main-window/bridge path with a bounded test, or retain a documented native manual gate until that test is practical. Run Windows Start, hover and hotkey over Korean text, popup display, pause/resume, region cancellation/persistence, tray restoration, and Quit. Record the actual observed result; do not infer it from provider readiness.

Reuse current integration helpers. Do not build a second application or a new end-to-end testing framework.

### R5. Verify retry teardown without blocking or leaking services

**Evidence:** `_DesktopSession.release():392` runs through the UI dispatcher, waits up to ten seconds for controller shutdown, ignores the returned completion boolean, and clears the update-coordinator reference. The existing handoff acknowledges the UI wait. This conflicts with the plan's nonblocking UI teardown goal and needs a narrow retry test.

**Finish:** verify provider timeout and update-coordinator lifecycle using the existing seams. Ensure release completes before replacement activation; do not activate over a still-owned provider/resource. Move blocking waiting off Qt where needed, retain ownership until shutdown is confirmed, and avoid orphaning update work. This is a concrete code path to resolve, not evidence that a production leak has already occurred.

### R6. Finish validation and reconcile documentation

- Run focused checks for R1–R5, then one convergence pytest/lint/type run and rebuild after final code changes.
- Run the corrected frozen smoke and Windows native manual matrix.
- Run clean online provisioning and cold offline failure/warm offline recovery with isolated resources.
- Inspect update restore and invalid/missing saved region behavior during that targeted pass; both are acknowledged unvalidated paths in the handoff. Do not silently broaden a saved region to full-monitor capture without clear user-visible handling.
- Execute native macOS/Linux checks when hosts/CI are available. Pending host access is not evidence of failure, but it prevents a cross-platform completion claim.
- Update the existing handoff, not a duplicate routine report. Correct claims about frozen UI coverage, cache isolation, tray guarantees, and completion status to match evidence.

## Was this overengineering?

**The inspected structure does not establish overengineering.** Seven new app modules total about 1,321 lines and largely match the plan: bootstrap, host, startup, status, diagnostics, paths, and self-check. New tests total about 1,337 lines across ten Python files; the smoke tool adds 308 lines. The tracked diff separately shows 1,501 additions and 645 deletions across 28 files; it excludes those untracked new files.

This was substantially more than fixing two bugs: the authorized plan included startup UX, persistent selection, diagnostics, native lifecycle, CI packaging gates, and regression tests. Two hours alone cannot tell us whether time/tokens were wasted, especially without the execution transcript.

There is nevertheless a practical stopping rule: **no further broad refactor, module split, generic abstraction, or test-framework expansion**. The remaining work should repair the specific incomplete boundaries above and prove user-facing behavior. Existing wrappers can be evaluated during the separately authorized review; simplification is not a prerequisite for this completion pass unless it directly fixes a listed gap.

## Approximate remaining effort

These are planning ranges, not measured timings or a guarantee of agent token consumption:

- R1/R2/R3/R5 targeted code and regressions: approximately **2–4 hours**.
- Final Windows build/smoke and interactive acceptance, if no new blocker appears: approximately **45–90 minutes**, including build/download waits.
- Native macOS/Linux execution: roughly **1–3 additional hours once suitable environments are available**, potentially longer if platform defects emerge. Access/setup time is not estimable here.

Practical expectation: **one focused continuation session, possibly two**, to finish the Windows implementation/acceptance pass. Do not budget another complete execution of Parts 1–8. Full cross-platform acceptance depends on native access and cannot be promised from this Windows session.

## Resumption instruction

Send Claude the [updated checkpoint](../checkpoints/desktop-stabilization-2026-09-05.md), this report, and the existing implementation handoff. Use this instruction:

```text
Resume the existing Hanly Desktop stabilization work. Read
 docs/execution/checkpoints/desktop-stabilization-2026-09-05.md
and docs/execution/reports/desktop-stabilization-resumption-2026-09-05.md.

The old build-running checkpoint was stale: the Windows build and provider smoke
already completed and an implementation handoff exists. Do not restart Parts 1–8.

I authorize the bounded completion pass R1–R6 in the resumption report: resolve
UI-thread dispatch, tray recovery/Quit, cold-profile isolation, retry teardown,
and the missing native acceptance evidence. Verify each stated gap against the
current code, fix only what remains, and reuse existing modules/test helpers.
Do not introduce another architecture, plan, generic abstraction, or broad refactor.

Run focused checks while editing, then one final convergence validation and build.
Preserve unrelated work. Update the existing checkpoint and implementation handoff
with actual results. Record unavailable native OS tests as pending; do not claim
cross-platform completion. Stop at the updated handoff. No deep Phase B review,
commit, push, merge, publication, or new issue breakdown is authorized.
```
