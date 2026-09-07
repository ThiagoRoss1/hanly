# Hanly Desktop stabilization — Windows, macOS, and Linux

> Proposed plan for user review. Future execution follows `docs/execution/05-execution-plan.md`: implementation ends at a Review Handoff; deep review and integration remain separate. The planning skill supports decomposition and self-review without adding another orchestration layer.

**Goal:** make all three native desktop distributions initialize lookup reliably and open the main interface, with equivalent behavior through the packaged executable, `hanly`, and `python -m hanly_app`.

**Architecture:** preserve the `hanly` engine and `hanly_app` desktop boundary. Separate Qt bootstrap, runtime preparation, session state, and presentation. Initially retain HTML/CSS/JS and pywebview with one owner of the Qt event loop.

**Tech stack:** Python 3.10+, PyQt6/WebEngine, pywebview, PyInstaller, CPU EasyOCR, Kiwi, and KRDICT/SQLite.

**Specification:** the user's requests in this task and the [investigation report](../../execution/reports/windows-release-investigation-2026-09-05.md). Architectural sources: `docs/architecture/01` through `04`. Proposed architectural changes have not been applied to the approved documents.

**Language:** plans, reports, implementation handoffs, and related project documentation for this work must be written in English. The existing filenames remain stable to preserve links; their Windows names identify the original investigation, not the implementation scope.

## Claude execution guide — start here

**Executor:** Claude Opus 5, acting as orchestrator and default direct implementer, consistent with the repository's Claude execution policy. Use the model selected by the user; this document does not configure or verify the model. Direct sequential execution is sufficient. Do not introduce mandatory subagents, a second plan, or per-task reviewers.

**Execution unit:** one explicitly authorized stabilization bundle, containing Parts 1–8 below. The stages in this guide are internal work boundaries, not separate bundles or repeated approval checkpoints. Continue between stages when their focused checks pass. Stop at the single Review Handoff, a user interruption, or a genuine blocker affecting safe dependent work.

**Readiness:** ready for implementation once the user sends the execution instruction below. No implementation has occurred in this planning session. The investigation records the starting evidence; verify repository drift rather than repeating the entire investigation.

### Copy-ready implementation instruction

```text
Use Claude Opus 5 to execute Phase A of the Hanly Desktop stabilization plan at
docs/superpowers/plans/2026-09-05-windows-stabilization.md.

I authorize Parts 1–8 as one implementation bundle, including the proposed
shared startup/lifecycle changes and user experience documented in the plan:
open the main interface, become READY without automatic capture, select the
capture area through settings, and hide on close only when restoration works.
Preserve the engine boundary, EasyOCR, pywebview/Qt, and the cross-platform scope.

Follow the Claude execution guide and the repository's Phase A workflow.
Analyze only what each stage needs, implement, run focused checks, and continue
without asking for confirmation between internal stages. Work directly by
default. Inspect existing Linear records when available; do not create a new
issue breakdown or wait for missing tracker IDs to duplicate this approved plan.
If no matching records are available, use the plan's part IDs in the checkpoint.

Maintain one concise resumable checkpoint at meaningful boundaries or before
context loss. Keep all project artifacts in English. Preserve unrelated edits.
Complete work and checks available on the current host; record unavailable native
macOS/Linux validation as pending, never as passing. Do not publish or claim
cross-platform acceptance while mandatory native checks remain pending.

Stop after one implementation Review Handoff, or leave a blocker checkpoint if a
required implementation gate cannot be completed. Do not start Phase B deep
review, commit, push, merge, publish, or silently switch UI/OCR backends.
```

The instruction above is text for the user to send to Claude; its presence in this document does not itself authorize this planning session to implement. Sending it approves the explicitly listed design choices, not arbitrary architecture changes. A genuine new requirement or backend migration remains outside that authorization.

### Stage A0 — Targeted analysis and execution setup

**Input:** this plan, investigation report, current repository, and any existing checkpoint.
**Code:** none, except disposable reproduction probes if evidence changed.

1. Read `CLAUDE.md`, `docs/execution/05-execution-plan.md`, this guide, and the investigation. Read the relevant architecture documents before changing their seams. Inspect the Review Handoff template once.
2. Check git status and preserve unrelated work. The original investigation left untracked diagnostic artifacts and other existing handoffs; do not delete or overwrite them as cleanup.
3. Confirm the authoritative `.venv` interpreter, installed tools, OS, and available native test environments. Inspect existing Linear issues/blockers if accessible; record actual mappings only. The copy-ready instruction permits plan part IDs if tracking is unavailable, so do not manufacture issue IDs or stop solely to create duplicate planning artifacts.
4. Compare current affected code with the report's baseline. Re-run only the relevant reproduction if changed. Do not repeat broad dependency research or run the full suite just to re-establish context.
5. Inspect real consumer call sites for the proposed status/startup/host interfaces. Resolve routine naming/type details locally and record the settled signatures in the single checkpoint. The signatures below describe contracts, not code to paste without checking imports and consumers.
6. Confirm the stage ordering below and any actual environment limitations. Do not write another implementation plan.

**Exit:** scope, current evidence, interpreter, contract consumers, and available checks are understood; no unresolved blocker prevents the first implementation stage.

### Stage A1 — Correct the two blockers and make failures observable

**Parts:** 1, 2, 3; the minimal diagnostic entrypoint support specified in Part 8.
**Analysis:** inspect Qt construction, mandatory frozen imports, worker factory failure, and existing error/status consumers.
**Code order:**

1. Add the real Qt startup regression and fix nonempty argv (Part 1).
2. Add mandatory Kiwi collection and inventory validation (Part 2).
3. Implement initialization-error propagation, runtime status, and durable diagnostics (Part 3).
4. Introduce the minimal internal diagnostic mode and `tools/smoke_packaged_runtime.py` now, so the native bundle can initialize the real worker. Reuse the production composition; do not wait until Part 8 to create a prerequisite for Part 2's acceptance.
5. Perform one host-native build and provider smoke when those changes converge. The final full UI/capture matrix still belongs to Stage A4.

**Implementation-side review:** inspect only the affected diff for missing mandatory packages, error loss before the first request, false readiness, and Qt argument handling. Fix blocking defects immediately; do not launch a broad audit.
**Exit:** focused regressions pass, the host-native bundle reaches real worker readiness, and initialization failure is observable. Other-OS native execution may remain explicitly pending without blocking shared source work.

### Stage A2 — Establish the shared window lifecycle

**Part:** 4.
**Analysis:** verify the installed pywebview public API, callback threads, effective Qt backend, and close/restore events before editing lifecycle orchestration.
**Code:** centralize Qt bootstrap, give the host one event-loop owner, marshal UI actions, preserve one restorable window, and handle tray capability differences.
**Implementation-side review:** check that no second `exec/start` path survives, window state follows real events, and close/restore/Quit remain reachable.
**Exit:** the real host lifecycle test passes on the available native desktop, without the nested-loop warning. If the retained backend cannot satisfy the contract, record the concrete blocking API limitation rather than silently migrating frameworks.

### Stage A3 — Implement interface-first startup and settings selection

**Parts:** 5, then 6.
**Analysis:** trace configuration discovery, provisioning, UI snapshots before readiness, and capture preference persistence.
**Code:** implement background startup through the existing services, then move capture selection to settings with cancellation/state restoration and backward-compatible persistence.
**Implementation-side review:** check launcher parity, offline/error/retry behavior, no hidden heavy work on Qt, no automatic capture before Start, and preserved settings on cancellation.
**Exit:** focused startup/settings tests pass and the main interface remains usable before readiness and after failure. Both hover and manual-hotkey paths remain wired to the same worker.

### Stage A4 — Consolidate and validate the produced artifacts

**Parts:** 7, then remaining Part 8 work.
**Analysis:** inspect only changed-module responsibility overlaps and gaps in the acceptance matrix.
**Code:** remove obsolete paths, update English documentation, finish post-freeze CI smoke for every native job, and complete diagnostics/harness integration.
**Validation:** run bundle-wide pytest/lint/type gates once at convergence, then the final native build/smoke on available hosts. Re-run a passed gate only when subsequent changes affect it or a failure requires it. Do not rerun full suites after every checkbox.
**Implementation-side review:** confirm authorized scope, directly touched invariants, coherent interfaces, actual test results, and absence of obvious blockers. This is consolidation, not Phase B deep review.

**Exit classification:**

- `Implementation complete; native acceptance complete`: all required implementation and supported-platform native checks passed.
- `Implementation complete; native acceptance pending`: code and available-host gates passed, but named native environments/manual checks are unavailable. Hand off honestly; publication and a cross-platform completion claim remain blocked.
- `Implementation blocked`: a required available-host gate fails or essential code remains unimplemented. Leave the checkpoint with evidence and the exact next action; do not present this as a completed Review Handoff.

Unavailability of a macOS/Linux host does not justify leaving their shared code, CI checks, or platform-aware behavior unimplemented. It only limits execution evidence.

### Stage A5 — Single implementation Review Handoff, then stop

Create `docs/execution/review-handoffs/desktop-stabilization-2026-09-05.md` using the existing template. Include implementing ecosystem, actual part/issue mappings, relevant diff areas, behavior, commands/results, platform/architecture matrix, pending native gates, and suggested review targets. Omit the Post-Bundle Review Outcome section until Phase B actually runs.

Update existing tracked members consistently with the repository workflow when tracking is available. Do not mark them `Done`. Prepare any final checkpoint update before writing the handoff; writing the handoff is the final implementation act. Do not automatically begin a reviewer run.

### Phase B — Deep review, only in a separately authorized run

The user chooses the reviewer/ecosystem after receiving the implementation handoff. Review the implemented diff against the plan, architecture, actual validation, and acceptance criteria. Prioritize lifecycle/concurrency, resource initialization, launcher parity, native packaging, and platform capability handling.

Append the review outcome to the same handoff, classifying findings as `Fixed now`, `Deferred` with a revisit trigger, or `Dismissed`. Only cheap boundary hardening allowed by `05-execution-plan.md` is automatically in scope; larger corrections require separate authorization. Mechanical checks passing are not a substitute for this review.

Copy-ready instruction for that later run:

```text
Review the Hanly Desktop stabilization implementation as Phase B.
Read docs/execution/review-handoffs/desktop-stabilization-2026-09-05.md,
the linked plan, and the relevant architecture. Inspect the actual diff and
validation evidence. Return prioritized findings and append the review outcome
to the same handoff. Follow the repository's review/fix boundaries; do not
commit, push, merge, publish, or treat missing native tests as passing.
```

### Context and token-budget recovery

Use one file only: `docs/execution/checkpoints/desktop-stabilization-2026-09-05.md`. Create it during execution when durable state is needed, not as a claim that implementation has already started. Update at meaningful stage boundaries or before interruption/context loss; do not create per-task reports.

Keep it concise, with:

- Authorized scope and current stage/part.
- Part states: `not started`, `in progress`, `checked`, or `blocked`; separately list native acceptance per OS/architecture as `passed`, `failed`, or `not run`.
- Settled interface signatures and design decisions that affect remaining consumers.
- Changed files and preserved unrelated work; branch/base identity and last validation point.
- Commands actually run and results, with paths to larger evidence instead of pasted logs.
- Open blocker or pending native checks, exact next action, and any running process that must be resumed/cleaned up.

Resume by reading the checkpoint, checking git status/diff, and verifying whether relevant code changed since the recorded checks. Continue the first incomplete dependency-ready step. Do not repeat completed analysis, rewrite the plan, rerun unchanged successful gates, or infer completion from checkboxes without evidence. If limits prevent finishing, preserve a partial checkpoint and state what remains; do not label the bundle complete.

## Cross-platform scope verification

Repository inspection confirms that `cli.py`, `capture_selector.py`, `control_center.py`, worker initialization, and runtime state are shared across operating systems. The same `packaging/hanly-desktop.spec` is used by the Windows, macOS, and Linux jobs in `.github/workflows/build.yml`. The current platform branches select native input/tray modules; they do not isolate the identified startup defects.

Consequently, the argv correction, explicit Kiwi collection, lifecycle correction, error propagation, and interface-first launch must be implemented in shared paths. Do not guard these fixes with `sys.platform == 'win32'`.

**Evidence boundary:** the fatal Qt error and missing Kiwi inventory were verified on Windows. macOS/Linux artifacts have not been executed or inspected here. Shared source establishes applicability of the fixes, not proof that either native release currently exhibits every Windows symptom or that a future build works.

| Area | Shared change | Required native verification |
|---|---|---|
| WebEngine startup | Nonempty argv and one QApplication | HTML load and JS bridge on all three OSes |
| Morphology packaging | Collect Kiwi package, models, and native extension | Matching extension/CPU architecture in each native artifact |
| Runtime readiness | Initialization errors independent of lookup requests | Ready/failure/retry and persisted logs on each OS |
| Main window | One loop, one host, consistent launch behavior | Native window/tray close, restore, and quit |
| Capture and input | Existing provider/controller seams retained | macOS permissions; Linux display-session capabilities; Windows DPI |
| Resources and settings | Same lifecycle and validation policy | Writable per-user paths, clean-profile acquisition, offline restart |

## Proposed user experience

1. Every existing launcher opens the same main interface. Reuse the current Control Center as the functional main window; final visual redesign remains a separate deliverable.
2. Show preparation, resource download/validation, readiness, or actionable failure. Settings and diagnostics remain available if runtime initialization fails.
3. Monitor/region selection is an action in settings. Cancelling preserves the previous selection and leaves the main interface open.
4. Interpretation: the user's restriction on a startup popup refers to the capture selector. Dictionary result popups remain controlled by `popup_enabled`.
5. Proposed behavior for review: launch into `READY` without automatically starting capture; the Start action activates lookup. An autostart preference is not required for this delivery.
6. Closing the main window hides it only when a verified tray/restoration mechanism is available. Otherwise keep the window accessible and explain that background hiding is unavailable. Quit remains available from the main interface and ends all services.
7. The installed Python package already provides `hanly`. Extracting a portable archive does not install a PATH command. This plan preserves launcher parity without silently changing global PATH or promising a new installer/macOS app-bundle format.

## Global constraints

- Dependency direction remains `hanly-app -> hanly`; the engine must not import desktop or tooling.
- EasyOCR remains the only V1 backend and uses CPU execution.
- OCR, morphology, network access, and heavy validation stay off the UI thread.
- SQLite connections are opened and closed on their owning worker thread.
- Preserve hover, hotkey lookup, bounded/latest-wins execution, and final request-currency validation.
- Full-monitor mode defines allowed capture space, not continuous full-screen OCR.
- Explicit runtime configuration continues to bypass automatic provisioning.
- Tests use temporary profiles and preserve existing user resources/settings.
- Shared fixes require native release gates on Windows, macOS, and Linux.
- No product implementation, commit, push, merge, or publication is authorized by this planning update.

## Delivery order

| Part | Priority / proposed tier | Dependencies | Reviewable outcome |
|---|---|---|---|
| 1 | P0 / Standard | None | Valid WebEngine startup arguments |
| 2 | P0 / Standard | None | Complete native morphology bundles |
| 3 | P0 / Gate | None | Observable readiness and initialization failures |
| 4 | P0 / Gate | 1 | One Qt loop and recoverable main window |
| 5 | P1 / Gate | 3, 4 | Interface opens before runtime preparation |
| 6 | P1 / Standard | 5 | Persistent capture selection through settings |
| 7 | P1 / Standard | 3–6 | Focused cleanup and consistent documentation |
| 8 | P0 release gate / Gate | 1–7 | Native packaged-app acceptance on all three OSes |

These are technical dependencies. The Claude execution guide groups the parts into internal stages without duplicating their requirements. Existing matching issues may be mapped to parts; this document does not authorize creating issues or dispatching agents. Implementation authorization comes from the user's execution instruction.

## Part 1 — Remove the WebEngine abort

**Modify:** `packages/hanly-app/src/hanly_app/capture_selector.py`.
**Create:** `tests/integration/test_webengine_startup.py`.

- [ ] Convert the reproduction into a bounded subprocess test using the real `_shared_application(QApplication)` after `prepare_control_center_qt()`. Construct a `QWebEngineView`, load HTML, and await `loadFinished(True)`.
- [ ] Require exit code 0 and a `WEBENGINE_LOADED` marker. Survival for a few seconds is insufficient. Capture Qt messages and stderr.
- [ ] Confirm that the current Windows code fails with `0xC0000409` and the empty-argument diagnostic. Other OSes must assert the successful contract, not a Windows exception code.
- [ ] Apply the minimal correction in the shared selector:

```python
_application = application_type(["hanly"])
```

- [ ] Run `python -m pytest tests/integration/test_webengine_startup.py -q` on each native desktop environment, preserving OCR-before-Qt ordering.

**Acceptance:** HTML loads through the selector's real application constructor. This does not complete Part 4.

## Part 2 — Complete morphology packaging

**Modify:** `packaging/hanly-desktop.spec`, `tests/test_packaging.py`.
**Create:** `tools/smoke_packaged_runtime.py`.

- [ ] Check the bundle inventory for `kiwipiepy`, `kiwipiepy_model`, native extension, and required model files. Run against Windows v0.1.0 and confirm failure for missing Kiwi.
- [ ] Add mandatory collection outside the existing `except Exception: continue` block:

```python
for package_name in ("kiwipiepy", "kiwipiepy_model"):
    package_datas, package_binaries, package_imports = collect_all(package_name)
    datas.extend(package_datas)
    binaries.extend(package_binaries)
    hiddenimports.extend(package_imports)
```

- [ ] Verify the actual extension name and architecture for each build's installed version. Missing mandatory dependencies must fail the build. Apply collection unconditionally on all three OSes.
- [ ] Build on each corresponding host with `python tools/build_package.py --platform windows`, `--platform macos`, or `--platform linux`. The flag selects artifact layout; it is not a cross-compilation facility.
- [ ] Run a worker smoke inside each frozen artifact, without falling back to the checkout, `.venv`, or developer Kiwi models.
- [ ] Introduce the minimal same-entrypoint diagnostic support from Part 8 during Stage A1 so this smoke has an executable path. Finish its UI coverage and matrix integration in Stage A4.
- [ ] Warm EasyOCR, analyze `한국어` with Kiwi, and look up a known KRDICT entry through the real provider interfaces. Record dependency versions and readiness.

**Acceptance:** all native frozen workers become ready using an isolated profile. Inventory alone is not evidence of successful initialization.

## Part 3 — Readiness, initialization failure, and diagnostics

**Create under `packages/hanly-app/src/`:** `hanly_app/runtime_status.py`, `hanly_app/diagnostics.py`.
**Create:** `tests/test_runtime_status.py`.
**Modify:** `job_executor.py`, `lookup_controller.py`, `hover_lookup.py`, `desktop_controller.py`, `application.py`, `control_center.py`, `tray.py`, and corresponding tests.

Proposed interfaces:

```python
RuntimePhase = Literal["idle", "preparing", "ready", "failed", "stopping", "stopped"]

@dataclass(frozen=True)
class RuntimeStatus:
    phase: RuntimePhase
    stage: str
    message: str

# Independent from per-request lookup errors.
on_initialization_error: Callable[[BaseException], None] | None
```

- [ ] Add a regression for factory failure before the first submission: deliver the original exception through the initialization callback, keep readiness false, and do not invent a dictionary result.
- [ ] Preserve per-request failures and stale-result suppression. Do not fabricate a request to report startup failure.
- [ ] Separate runtime readiness from capture `RUNNING/PAUSED`. Starting preparation must not imply that lookup is available.
- [ ] Publish immutable status snapshots to desktop, tray, and bridge; dispatch UI mutations through Qt.
- [ ] Extract locked diagnostics with rotating files beneath `default_app_config_path().parent / 'logs'`. This preserves current paths: `%LOCALAPPDATA%/Hanly` on Windows and `$XDG_CONFIG_HOME/hanly` or `~/.config/hanly` on macOS/Linux. Do not move macOS settings as an incidental refactor.
- [ ] Record stage, versions, chained traceback, and Qt failures, excluding captured images/text by default. Install diagnostics before native initialization and tolerate absent stdout/stderr in windowed builds. Flush fatal Qt diagnostics before abort.
- [ ] Show an actionable error and log location without ready providers. Retry releases the previous worker and creates a new one; JobExecutor remains single-use.
- [ ] Test missing display/input permissions and inaccessible paths as visible failures rather than silent background states.
- [ ] Run `python -m pytest tests/test_runtime_status.py tests/test_job_executor.py tests/test_lookup_controller.py tests/test_hover_lookup.py tests/test_desktop_controller.py -q`.

**Acceptance:** provider failure before any hover leaves the interface alive with the original cause available and no misleading running status.

## Part 4 — One event-loop owner and one host

**Create under `hanly_app`:** `qt_bootstrap.py`, `control_center_host.py`.
**Create:** `tests/integration/test_control_center_lifecycle.py`.
**Modify:** `control_center.py`, `application.py`, `capture_selector.py`, `signal_bridge.py`, `tray.py`, and host/application tests.

Proposed interface signatures:

```python
ensure_qt_application(argv: Sequence[str]) -> QApplication
ControlCenterHost.run() -> int
ControlCenterHost.show() -> None
ControlCenterHost.hide() -> None
ControlCenterHost.close() -> None
```

`run()` owns the sole `webview.start` call on the main thread. `close()` destroys the window during Quit; normal restoration uses `show()`.

- [ ] Centralize preload -> WebEngine preparation -> QApplication with nonempty argv. Retain a strong application reference until shutdown.
- [ ] Separate loop execution from window presentation. Retain pywebview as loop owner through one `start(gui='qt')`; remove the competing desktop `QApplication.exec()` call.
- [ ] Create the main window once and derive its state from actual window events, not the return from `webview.start`.
- [ ] Ensure Qt is the effective backend on each OS. If backend loading falls back to Cocoa/GTK/WinForms, surface an actionable startup error rather than silently mixing frameworks in this shared-Qt design.
- [ ] Marshal bridge callbacks onto Qt before lifecycle/capture mutations. Do not create widgets in pywebview's background startup callback.
- [ ] Account for pywebview's SIGINT handler; preserve idempotent shutdown without blocking joins on the UI thread.
- [ ] Validate macOS tray integration with the shared native application/main thread. Inspect the installed pystray contract for `darwin_nsapplication` and use supported integration if required; do not assume Windows detached-loop behavior applies.
- [ ] On Linux, verify the effective pystray backend and its menu/restoration capabilities. The spec explicitly collects `_xorg`, whose menu support is limited. Keep Start/Pause/Open/Quit available in the main UI regardless of tray capabilities.
- [ ] Hide on window-close only with a verified restoration route. With no usable tray, keep the window accessible and expose the limitation; never leave an unreachable background process.
- [ ] Native test: load HTML, call bridge, hide/restore twice when supported, close normally, and Quit. Require one window, one backend start, no nested-loop warning, and released workers/native resources.
- [ ] Run `python -m pytest tests/integration/test_control_center_lifecycle.py tests/test_control_center.py tests/test_application.py -q` on all three OSes.

**Decision gate:** if the supported pywebview public API cannot satisfy this lifecycle, document the concrete limitation before proposing `QWebEngineView/QWebChannel`. No private backend monkeypatch or second GUI thread. Backend migration is not the initial proposal.

## Part 5 — Open the interface before background preparation

**Create:** `hanly_app/startup.py`, `tests/test_startup.py`.
**Modify:** `cli.py`, `application.py`, `first_run.py`, `control_center.py`, Control Center assets, and `tests/test_application.py`.

Proposed `StartupCoordinator` signatures:

```python
start(explicit_runtime: Path | None) -> None
retry() -> None
begin_shutdown() -> None
await_shutdown(timeout: float) -> bool
```

- [ ] Test all existing launchers reaching the same bootstrap on each OS. Native executable launch and terminal launch must not diverge in feature behavior.
- [ ] Make `cli.main` parse arguments and dispatch the shared desktop. Remove mandatory `selector()` from the default path.
- [ ] Construct shell and bridge before runtime resolution/provisioning. Initialize tray when available. Allow snapshots without `HanlyRuntime` during preparation.
- [ ] Run resolution, provisioning, and heavy validation off Qt, reusing `first_run`/`UpdateService`. Dispatch completion to Qt; providers remain owned by JobExecutor.
- [ ] Show resource progress and separate OCR/morphology/dictionary states. Import success alone is not readiness; use indeterminate stage progress when byte counts are unavailable.
- [ ] Cover offline operation, timeout, checksum failure, invalid config, and unwritable paths. Keep the UI accessible; retry must not duplicate downloads/workers.
- [ ] Preserve `--runtime-config`, `--app-config`, and `--roi-size`. Explicit configuration must not trigger automatic provisioning.
- [ ] Run `python -m pytest tests/test_startup.py tests/test_first_run.py tests/test_application.py -q`.

**Acceptance:** the functional interface appears before downloads/heavy validation. Native OCR preload still precedes Qt; measure that delay separately rather than promising instant opening.

## Part 6 — Persistent capture selection through settings

**Modify:** `config.py`, `capture_selector.py`, `control_center.py`, `desktop_controller.py`, Control Center assets, `tests/test_app_config.py`, `tests/test_capture_selector.py`, and `tests/test_control_center.py`.

- [ ] Persist monitor/region preferences with backward-compatible reading of existing desktop settings. Bridge-only transient state must not be the persistent source.
- [ ] Add bridge action `select_capture_area() -> dict[str, object]`, dispatched to Qt. Return the applied snapshot or an unchanged snapshot on cancellation.
- [ ] Suspend observation and invalidate old requests while selecting a region. Apply validated coordinates and restore the previous capture state on success, failure, or cancellation.
- [ ] Test removed monitors, negative coordinates, scaling, and display reconfiguration. Invalid restored regions require reselection from the UI.
- [ ] Check macOS display-coordinate scaling and capture/input permission denial/recovery separately for packaged and terminal launches.
- [ ] On Linux, test a real X11 desktop. Detect unsupported/restricted Wayland capture/input rather than claiming full-desktop lookup because the window opens. Native Wayland support would require a separately scoped adapter if current dependencies cannot meet it.
- [ ] Keep `popup_enabled` dedicated to dictionary popups.
- [ ] Run `python -m pytest tests/test_app_config.py tests/test_capture_selector.py tests/test_control_center.py tests/test_capture.py -q`.

**Acceptance:** launch shows no selector; settings selection works and persists; cancellation preserves the previous choice; unavailable platform capabilities are clearly reported.

## Part 7 — Responsibility-focused cleanup and documentation

**Modify:** `application.py`, `control_center.py`, `README.md`, `docs/CODE-MAP.md`, `packaging/README.md`, relevant architecture documents, and visual companions when semantics change.

- [ ] Keep application composition in `application`, native bootstrap in `qt_bootstrap`, preparation in `startup`, diagnostics in `diagnostics`, host lifecycle in `control_center_host`, and bridge actions in `control_center`.
- [ ] Remove obsolete mandatory-selection paths and duplicate window flags. Preserve interfaces with actual consumers.
- [ ] Unify status callbacks used by desktop, tray, and main interface.
- [ ] Write all new/updated work documentation in English. Describe native launch and CLI parity, portable archives versus installed commands, and platform-specific supported environments.
- [ ] Preserve invariant IDs and Markdown/diagram synchronization. Avoid provider rewrites or generic controller/plugin frameworks.
- [ ] Run package boundary/import checks, lint, and type checks.

**Acceptance:** every changed responsibility has one owner, documents describe the final behavior, and the engine remains independent.

## Part 8 — Native artifact release gate

**Modify:** `.github/workflows/build.yml`, `tools/build_package.py`, `tools/smoke_packaged_runtime.py`, packaging tests, and release runbook.
**Create:** `tests/integration/test_packaged_desktop.py` and minimal Korean text/image fixtures.

- [ ] Add an internal diagnostic mode to the same entrypoint so the harness drives the real UI/runtime and emits JSON/exit status without introducing a second application lifecycle.
  The minimal worker mode is implemented in Stage A1 for Part 2; extend that same mode here rather than creating a competing diagnostic entrypoint.
- [ ] Add post-freeze smoke to every existing native matrix job before artifact retention: HTML/JS handshake, provider readiness, fixture OCR, morphology, and KRDICT lookup. Use a temporary profile and working directory outside the repository, without developer dependency fallbacks.
- [ ] Separate deterministic preinstalled-resource tests from online provisioning. Verify manifest/hash/activation online, successful warm offline use, and actionable cold offline failure.
- [ ] Record OS version, CPU architecture, Python/Qt/WebEngine/provider versions, display backend, permissions, artifact hash, and test outcomes. Do not claim both Apple Silicon and Intel support from a single runner architecture.
- [ ] Complete this native acceptance matrix before claiming the work fixed across platforms:

| Environment | Required acceptance |
|---|---|
| Windows native desktop | Full monitor/region, mixed DPI, hover/hotkey, popup, pause/resume, tray restore, Quit, no new crash events |
| macOS native desktop | Packaged and terminal launch; denied/granted screen-capture and keyboard permissions; display scaling; main-thread/tray integration; restore/Quit |
| Linux X11 desktop | Capture/input with a real display, WebEngine dependencies, tray with/without menu capability, window-accessibility fallback, restore/Quit |
| Linux Wayland session | Explicitly evaluate full-desktop input/capture. Limited XWayland operation is not full Wayland support; expose limitations and record support status |

- [ ] Headless/Xvfb UI tests may supplement Linux coverage but do not replace desktop capture, tray, or permission acceptance. If a CI runner lacks an interactive desktop, require a recorded native manual gate before publication; a skipped test is not a pass.
- [ ] Freeze dependency constraints from the validated combinations. Do not blame the Windows abort on a Qt version change when empty argv is already isolated.
- [ ] Run final relevant checks once:

```text
python -m pytest
python -m ruff check packages packaging tests tools benchmarks
python -m mypy packages packaging tests tools benchmarks
```

Build each native artifact on its corresponding OS:

```text
python tools/build_package.py --platform windows
python tools/build_package.py --platform macos
python tools/build_package.py --platform linux
```

- [ ] Deliver an English Review Handoff with commands, artifact identities, the native acceptance matrix, and remaining limitations. Publication follows separate approval.

**Final acceptance:** all supported native environments open the interface through existing launchers, perform real lookup after readiness, expose failures, select capture through settings, restore windows without duplicate loops, and shut down cleanly. Explicitly document unsupported Linux session capabilities rather than marking them fixed.

## Plan self-review

- User requirements map to Parts 2/3/8 (lookup), 1/4/8 (crash/lifecycle), 5 (main interface/launcher parity), 6 (settings selection), and 7 (cleanup).
- Shared changes cover Windows/macOS/Linux; native proof remains mandatory per artifact and architecture.
- The Windows-only diagnostic path and log location were generalized. macOS tray/main-thread integration and Linux tray/Wayland constraints are explicit.
- No Windows experiment is presented as a completed macOS/Linux runtime test.
- Native subprocess and post-freeze tests address the gap left by passing tests with doubles.
- Product decisions remain reviewable: READY without automatic capture; close-to-tray only with recovery; popup means selector; archive-only PATH installation is outside scope.
- Documentation is in English. No product implementation has been performed.
- Execution is ordered as targeted analysis -> staged code/focused checks -> convergence validation -> one handoff; deep review remains a separate human-triggered run.
- The Part 2 diagnostic prerequisite is scheduled in Stage A1, resolving the previous forward dependency on Part 8.
- One resumable checkpoint distinguishes implemented code from pending native acceptance. No duplicate plans, per-task reports, or routine approval prompts are required between internal stages.
