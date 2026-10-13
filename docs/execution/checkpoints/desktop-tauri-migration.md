# Hanly Desktop Tauri migration checkpoint

Status: Phase A is incomplete. Inventory, approved architecture overlays and
a tested React/Tauri/Python protocol foundation are implemented. The foundation
was exercised natively on this Mac using a disposable debug app/profile. Runtime
composition, full UI/native parity, packaging/updater, Lab convergence and legacy
removal remain open. This is a continuation checkpoint, not a Review Handoff. The session stops at
a safe context boundary; the authorized migration remains unfinished. This checkpoint is the one migration plan; update it at meaningful
boundaries and end Phase A with one Review Handoff.

Branch: `desktop/tauri-migration`, based on `main` at `0902075`. Preserve
`spike/desktop-renderers` at preservation commit `39fc4e7` until the official
migration is complete. Main and origin/main were both `0902075` when fetched;
the branch was created there without merging the experimental branch. The spike
proved a shared React renderer against the old Qt shell; it did not prove this
Qt-free runtime, complete packaging, updater compatibility or Windows behavior.

## Local commit map

| Commit | Completed boundary and verification | Remaining responsibility |
|---|---|---|
| `39fc4e7` on `spike/desktop-renderers` | Preserved spike sources/docs only; 14 focused Python and 6 Electron tests, Lab Ruff and full Python mypy passed before switching. | Experimental Qt-hosted renderer evidence stays separate; no spike merge. |
| `c4cbb97` | Approved ownership overlays and synchronized architecture visuals; 6 invariant tests passed. | Replace baseline descriptions when the actual production migration reaches parity. |
| `4f48f5c` | Qt-free service protocol/config/logs; 11 focused service process/isolation tests, Ruff and mypy passed. | Runtime acquisition/lookup/provisioning/updater composition and worker-family lifecycle. |
| `c106a54` | Official React workspace and stable exact lock; 9 contract tests, 5 DOM interaction tests, strict types and Vite build passed. | Complete behavior/visual parity for every action, dialog and popup/selector scenario. |
| `09f2912` | Rust native/IPC supervision foundation; 12 tests, Clippy/rustfmt and isolated debug Mac UI/root-service shutdown checks passed. | Native adapters, restart/signals, fresh release bundle/updater and Lab acceptance. |

Three Luna workers were requested at `xhigh` under the repository execution
policy; their runtime configuration was not independently audited. No separate
implementation reviewer, Phase B run, push, merge, tag or release occurred.

## Baseline surface and replacement inventory

The implementation below is the 0902075 V1 baseline. Existing behavior remains
the acceptance reference until its replacement is implemented and verified.
The target is Tauri/Rust for the one native shell, React/TypeScript for every
desktop UI, a supervised Qt-free Python desktop service, and the existing
client-independent `hanly` engine with its isolated lookup child.

| Existing surface or action | Current owner and behavior to preserve | Approved replacement |
|---|---|---|
| First run, startup, retry and readiness | `cli.py`, `first_run.py`, `StartupCoordinator`, `runtime.py`; shell opens before configuration/resource work, provisioning runs off the UI thread, failures can retry. Runtime readiness and provider residency are separate. | Tauri opens immediately; supervised Python service provisions and prepares asynchronously, streams status, and retries through one service owner. Rust process health is separate from service/runtime readiness. |
| Capture page | `assets/control_center/index.html` + `control_center.js`, `ControlCenterBridge`: start/stop, current monitor or selected region, cursor/monitor target, region coordinate edits/apply/clear, select area, hover delay, lookup preload, recognizer choice. | React Control Center page; typed commands for settings/actions and live service state. Preserve validation, persisted values, monitor enumeration and current appearance. |
| Permissions and first-run prompts | `permissions.py`, `permissions_darwin.py`, `hanly_dialog.py`, selector and Control Center: display state, request OS permission, refresh after Settings changes, initial whole-monitor/region choice, cancel without changing prior settings. | React presentation; Rust native permission/deep-link and dialog adapters; Python retains permission policy/config values. First-run and in-app selection use the same validated region contract. |
| Shortcuts and hover mode | `hotkeys.py`, `hotkeys_darwin.py`, `ControlCenterBridge`: Push to Hover, Pause/Continue Hover, Start/Stop Capture; configurable chords; push action ends on key release; one-shot manual lookup remains bindable. | Rust registers native global shortcuts and reports press/release edges; Python owns action policy and hover state. React edits and displays registered bindings. Preserve collision/error feedback and defaults. |
| Appearance and popup preferences | Control Center Appearance: system/light/dark, default compact/expanded popup, technical-detail level; the native Control Center frame follows the resolved theme. `qt_theme.py` and `popup/presentation.py` resolve presentation values. | React tokenized styles shared by all windows; system theme events and native title-bar colors from Rust; Python persists settings and returns normalized popup presentation. Match the current visual identity before any redesign. |
| Dictionary popup | `popup/presentation.py`, `popup/qt.py`, `PopupController`: compact/expanded card, headword/Hanja, definitions/senses, decomposition and selected token, alternate entries, technical details, close/expand, retained answer and pointer-crossing grace, cursor/screen-aware placement. | A transient React/Tauri popup window rendering only normalized `LookupResult` presentation. Rust owns geometry, focus/activation and window lifecycle; Python performs the final current-request check before publication. |
| Updates and resources | Control Center Updates + `updates/*`: check, progress/activity, resource install/cancel, app-update staging, explicit full-download confirmation, release notes; verified inventory, signatures, ownership, handoff, acknowledgement and rollback. | React presents status/confirmation; Python retains update preparation and transaction logic; Rust owns process restart/supervision. New-install acknowledgement is a Tauri root-readiness event after the new Rust app root starts and validates its service handshake, never Python service readiness alone. Keep the existing updater; do not silently switch to Tauri's updater plugin. |
| Diagnostics and logs | `diagnostics.py`, `runtime_status.py`, `runtime_trace.py`, Control Center Logs: readiness recheck, activity filtering by level/subsystem and search, refresh/copy/save report/clear, bounded session logs; startup, connection and action errors have retry/clear paths. | Python retains logging, status and explicit export behavior. Rust forwards bounded snapshots/events and owns native clipboard access; React renders filters and invokes only allowlisted commands. Ordinary traces retain no recognized text or pixels. |
| Shell, tray and reopening | `application.py`, `DesktopApplication`, `tray.py`, `app_reopen_darwin.py`: one persistent shell; tray status, Start/Resume, Pause, Open Control Center and Quit; app activation/reopen and Control Center re-show; close/reopen has one live window owner and bounded cleanup. | Tauri root owns native lifecycle, tray, activation, reopen and all webview windows. React Control Center close hides/closes that window without killing the root; tray reopen focuses the same window or creates one after its prior owner exits. |
| Region overlay and screen choice | `acquisition/selector.py`, `hanly_dialog.py`, Qt screen geometry: cross-monitor drag, negative virtual-desktop origins, escape/right-click cancel, tiny/out-of-screen rejection, saved global rectangle. | Dedicated React selector window plus Rust screen/coordinate adapter; keep physical/logical/DPI conversion explicit and reject invalid regions before Python persistence. |
| Hover, acquisition and lookup | `MouseObserver`, `HoverController`, `HoverLookupRuntime`, `CaptureService`, AX/UIA direct text, OCR fallback, `LookupController` / `JobExecutor` / `lookup/process.py`: direct-first acquisition, small ROI only, latest-wins, provider isolation, final currency gate, normal non-success outcomes, popup retention/crossing. | Python service retains business rules, acquisition, capture/monitor preferences, hover and request currency; `hanly` stays unchanged and client-independent. The service keeps heavy Vision/EasyOCR + Kiwi + KRDICT in its unloadable spawned lookup child. Rust relays normalized events; React does no OCR, lookup or arbitrary OS access. |
| Application identity and user data | `app_identity_darwin.py`, `paths.py`, build identity/inventory: `io.github.thiagoross1.hanly`, existing settings/runtime/recovery paths, icons and update install root. | Preserve identity, data, resources and recovery semantics across the transition. Document and test old-layout discovery/migration before changing any path or product identifier. |

## Framework and lifecycle replacement map

| Current dependency or adapter | Responsibility now | Replacement boundary |
|---|---|---|
| `qt_bootstrap.py`, `signal_bridge.py`, `application.py`, `app_icon.py` | QApplication, one event loop, Qt callback dispatch, OS signal shutdown, startup wiring, startup error dialogs and application QIcon. | Tauri owns the native event loop, signals, native dialogs and app icon; Python service has an independent entrypoint and explicit request/event loop. Keep `freeze_support()` first in that Python entrypoint because the packaged lookup child uses spawn. |
| `hover/qt_scheduler.py` | Single-shot dwell and popup-crossing timers on the Qt loop. | Python scheduler with an injected clock/timer or service event loop; preserve cancellation and one-pending-delay semantics. |
| `popup/qt.py`, `popup/macos.py`, `qt_theme.py`, `window_frame_win32.py` | Non-activating always-on-top popup, screen placement/resize, system theme, macOS inactive visibility, Windows frame behavior. | React popup plus small public-API Rust platform adapters. Validate native non-activation, focus, pointer crossing, DPI and multi-monitor coordinates on each OS. |
| `manual_lookup.py`, `app_reopen_darwin.py` | Read the native cursor and coordinate app/Dock reopen and activation through Qt. | Rust passes cursor/screen context to Python and owns app reopen/activation; Python keeps manual lookup policy and request flow. |
| `acquisition/selector.py`, `hanly_dialog.py` | Qt prompt and selection overlay; currently imported through the Control Center bridge. | Tauri/React selector and dialogs; remove these imports from service bootstrap. Keep selection geometry and validation policy in Qt-free Python contracts. |
| `control_center/host.py`, `control_center/process.py`, `control_center/bridge.py` | A separately spawned pywebview/QtWebEngine window, Qt host lifecycle, page proxy, allowlisted Python operations, state refresh, clipboard copy, Windows native-frame theme and foreground handoff to parent. | Control Center becomes a Tauri window in the root process. React uses scoped Tauri commands/events; Rust owns clipboard and native-frame adapters; Python receives only versioned, bounded, per-window authorized requests. Preserve one-window ownership, refresh coalescing and foreground handoff for selector/permission UI. |
| `tray.py` and `hotkeys*` native backends | pystray adapter plus global key listener/edge detection; dispatches policy callbacks to Qt. | Rust owns tray and native key registration/edges. Python retains action/configuration policy. Keep push-to-hover release observable and tests must prove it. |
| `diagnostics.py` Qt message hook and `self_check.py` UI probe | `qInstallMessageHandler`, Qt package reporting and a frozen pywebview document/bridge round trip. | Remove Qt-specific diagnostics; package self-check must exercise the Tauri root, React route/bridge, Python handshake and a real isolated lookup. A successful service start alone is not a usable-window check. |
| `hanly_app.cli:main`, `packaging/entrypoint.py`, `pyproject.toml`, `packaging/hanly-desktop.spec`, PyInstaller hooks/constraints and workflows | One Python user-facing entrypoint; production PyQt6, QtWebEngine and pywebview collection; Windows/macOS/Linux build and packaged tests. | Tauri becomes the user-facing executable; the frozen Python entrypoint becomes an internal `--service` role and still calls `freeze_support()` before spawned-child dispatch. Replace product inventory with Tauri plus bundled Python runtime/providers/resources. Remove Qt/WebEngine/pywebview from production dependencies/hooks only after parity tests pass; users install no Python/Rust/Node. |

Qt is not isolated to a visible renderer: the scheduler, popup, selection,
bootstrap/dispatch, app frame, diagnostics, package extras, frozen hooks and
native tests are production dependencies too. The service must import without
PyQt, Qt WebEngine or pywebview anywhere in its transitive startup path.

## Process ownership and private IPC contract

```text
Hanly Tauri/Rust root
  ├─ React Control Center / popup / region-selector windows (all product UI)
  └─ one supervised Python desktop service (domain policy, OS acquisition,
       config, resources, updates, hover and lookup coordination)
       └─ one spawned lookup child (OCR, Kiwi, KRDICT and LookupPipeline)
```

Rust owns native windows, tray, app activation/reopen, platform adapters, child
supervision, IPC validation/dispatch and whole-family shutdown. React owns
presentation and interaction only. Python owns desktop business rules, config,
resource acquisition, AX/UIA and capture policy, hover decisions, request IDs
and final currency check, lookup execution and updater transactions. The
`hanly` engine owns only reusable lookup contracts/providers/pipeline. The
lookup child owns concrete heavy providers and closes them on the thread/process
that created them.

Use private stdin/stdout JSONL between Rust and the Python service; no listening
socket, shell command or arbitrary method lookup. Protocol v1 is:

- Rust request: `{"version":1,"type":"request","id":"…","method":"…","params":{},"window":"…"}`.
- Service reply: `{"version":1,"type":"reply","id":"…","result":{…}}` or `{"version":1,"type":"reply","id":"…","error":{"code":"…","message":"…"}}`.
- Service event: `{"version":1,"type":"event","sequence":1,"event":"…","payload":{…}}`.
- Maximum frame: 1 MiB; at most 32 outstanding requests. Enforce strict JSON,
  unique keys, bounded identifiers/depth/error text, monotonic event sequence,
  explicit methods and parameter shapes, and per-window authorization.
- Stdout carries frames only; diagnostics go to the private session log/stderr.
  A disconnect fails pending requests, marks runtime unavailable, attempts only
  the defined service restart path, and never leaves a detached lookup child.
- The current PyInstaller executable is windowed (`console=False`), and
  `cli.main()` eventually uses `_leave()` / `os._exit()` for the old Qt shell.
  The packaged service must prove redirected stdin/stdout exist for JSONL, and
  must answer graceful shutdown before returning. Keep `freeze_support()` first
  so spawned lookup children still re-enter the service executable correctly;
  do not reuse the old abrupt shell exit path for the supervised service.
- Python emits only normalized JSON values. The final request-currency check
  remains in Python immediately before popup publication; a later frontend
  sequence check may discard superseded presentation but cannot replace it.
- Shutdown stops admission, cancels hover work, stops capture/hotkeys, closes
  and joins the lookup child, flushes diagnostics, replies when possible, then
  exits. Rust waits a bounded interval and terminates the process family only
  after graceful shutdown fails.
- Updater handoff waits for the new Tauri/Rust root's readiness event after its
  native root and service protocol handshake are live. Provider preload/runtime
  readiness and an opened React window are later, separate milestones.

## Test migration inventory

| Existing tests | Classification and destination |
|---|---|
| `tests/krdict/*`, engine/provider/pipeline/contracts, language and word resolution, resource validation, package boundary/imports | Keep as engine or Qt-free Python behavior tests. Engine outputs and provider seams must remain equivalent. |
| `test_app_config.py`, `test_runtime.py`, `test_runtime_status.py`, `test_first_run.py`, `test_owned_cleanup.py`, `test_diagnostics.py`, `test_update_*`, `test_app_update_*`, `test_update_coordinator.py`, `test_update_service.py` | Keep domain/config/resource/updater guarantees. Port UI dispatch and root lifecycle seams; extend install-tree compatibility, new-root acknowledgement and rollback cases. |
| `test_capture.py`, `test_text_acquisition*`, `test_direct_text_routing.py`, `test_mouse_observer.py`, `test_hover_controller.py`, `test_hover_lookup*`, `test_lookup_controller.py`, `test_lookup_process.py`, `test_job_executor.py`, `test_manual_lookup.py`, `test_retained_target_evidence.py` | Keep Qt-free behavior contracts; add service IPC, restart, ordering, 1 MiB/32 pending, malformed frame, per-window authorization and disconnect/cleanup coverage. |
| `test_qt_bootstrap.py`, `test_signal_bridge.py`, `test_capture_selector.py`, Qt-specific cases in `test_popup.py`, `native/shared/test_qt_hover_scheduler.py`, `test_hover_exit_qt.py`, `test_qt_popup_window.py`, `test_qt_screen.py`, `native/macos/test_popup_panel.py`, `native/shared/test_capture_prompt_shutdown.py`, `test_app_icon_qt.py`, `native/windows/test_window_frame.py` | Qt adapter tests: port each behavior to Rust/native window or Python scheduler boundary before removing the old test. Keep the Qt-independent `popup/presentation.py` placement/content assertions. Retain genuine geometry, focus, cleanup and selection assertions. |
| `test_control_center.py`, `test_control_center_host.py`, `test_control_center_process.py`, `test_control_center_refresh.py`, `native/macos/test_control_center_identity.py`, `native/shared/test_control_center_combobox.py`, `test_control_center_copy.py`, `test_control_center_layout.py`, `test_control_center_lifecycle.py`, `test_webengine_startup.py`, `native/windows/test_webengine_arguments.py`, `tests/hanly_fixtures/assets/control_center_harness.js` | Keep Python action validation/configuration semantics in service tests; replace pywebview/DOM harness behavior with React state, routing, settings and interaction tests; replace host/process/WebEngine behavior with Rust window/command/lifecycle tests. Delete old host-only cases only after replacement evidence exists. |
| `tests/packaged/*`, `test_packaging.py`, `test_release_build.py`, `test_release_products.py`, workflow checks | Replace PyInstaller inventory/self-check assumptions with Tauri + sidecar/runtime identity and inventory tests, real fresh-bundle startup, user-data transition and updater smoke. Preserve version/source identity and target-platform coverage. |
| `lab/tests/*` plus Lab app launch/control/sampling tests | Port launch/control/observation to the official root and count the whole process family (Tauri + Python service + lookup child + owned helpers). Preserve privacy and ownership guards. |

No framework test is removed just because it names Qt. A test is obsolete only
when its responsibility no longer exists and that fact is recorded with a
replacement or a clear explanation.

## Ordered continuation A–F

| Phase | Work and exit evidence | Status |
|---|---|---|
| **A. Inventory and contracts** | Inventory surfaces/actions/dependencies/lifecycle; approve the transitional overlay in architecture sources and synchronized visuals without renumbering RF/CA/DAG/AEF IDs; lock the versioned IPC and process ownership contract; classify tests and gaps. | Initial inventory/contract written here; code parity remains open. |
| **B. Official Tauri foundation and Python service** | Establish official `apps/desktop` React/Tauri workspace; Qt-free Python service entrypoint; root supervision, bounded IPC, startup/provisioning/status, disconnect/crash/restart, bounded clean shutdown and isolated lookup child. Prove shell/window remains responsive during resource/provider preparation. | Protocol foundation checked; asynchronous provisioning, provider composition, restart and packaged process-family cleanup remain open. |
| **C. React behavior and visual parity** | Port Control Center sections/actions, live status, settings, compact/expanded popup and entries/decomposition, dialogs, permissions/onboarding, region selection, update progress/confirmation/results, diagnostics/export. Compare against the current V1 appearance; no new visual identity. | React routes/settings/logs and unavailable-action feedback implemented; full behavior and visual parity remain open. |
| **D. Replace Qt infrastructure** | Port ROI/monitor geometry, timers/callbacks, tray/reopen, hotkey press and release, native permissions/activation, popup focus/nonactivation/placement/retention, shutdown/signals. Run native Mac checks and platform contract tests; remove Qt adapters only after replacements pass. | Not started. |
| **E. Packaging, updater and CI** | Build Tauri plus Python runtime/providers/models/resources for Windows/macOS/Linux; preserve product identity, config/data paths and icons; adapt inventory, signatures/manifests, workflows and old-layout transition; carry forward updater verification/ownership/handoff/root acknowledgement/rollback. Never substitute Tauri updater plugin without explicit approval. | Not started. Linux distro/display limits and Windows acceptance stay explicit. |
| **F. Lab, convergence and legacy removal** | Lab launches and attributes the official root plus complete child family; run controlled Mac visual/native and compatible Lab comparisons; measure release startup/first/warm lookup/RAM/CPU/shutdown; update CODE-MAP/readmes/commands; remove production Qt, QtWebEngine and pywebview dependencies/assets/hooks after parity; run proportional portable/native/packaged/frontend/Rust gates; write the single final Review Handoff and stop Phase A. | Not started. No final handoff until all authorized Phase A work and evidence are present. |

At each boundary update this file with changed status, commits, actual checks,
results, unresolved risks and exact next steps. Do not create per-worker reports
or an interim Review Handoff.

## Native Windows continuation checklist

Run on a real Windows desktop after the shared contract and platform adapter
land. Hosted/simulated providers do not establish Windows acceptance. From a
PowerShell checkout, use a disposable profile and install fixture; do not point
the updater at the user's Hanly installation or settings.

```powershell
py -3.10 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install --group dev
& .\.venv\Scripts\python.exe -m pip install -e packages/hanly
& .\.venv\Scripts\python.exe -m pip install -e 'packages/hanly-app[runtime]'
& .\.venv\Scripts\python.exe tools/prepare_easyocr_models.py
& .\.venv\Scripts\python.exe tools/build_smoke_krdict.py data/generated/krdict.sqlite3
& .\.venv\Scripts\python.exe -m pytest --suite portable
& .\.venv\Scripts\python.exe -m ruff check packages packaging tests tools lab
& .\.venv\Scripts\python.exe -m mypy packages packaging tests tools lab
$env:HANLY_REQUIRE_NATIVE = "1"
& .\.venv\Scripts\python.exe -m pytest --suite native
Push-Location apps/desktop
npm ci
npm run check
npm test
npm run build
npm run tauri -- build
Pop-Location
$env:HANLY_REQUIRE_PACKAGED = "1"
# Set HANLY_PACKAGED_APP to the fresh bundle's executable or install fixture.
& .\.venv\Scripts\python.exe -m pytest --suite packaged
```

The exact native/build commands must be updated here if the official manifests
choose different scripts or packaging hooks. Then, on the produced Windows
bundle and a temporary `%LOCALAPPDATA%` profile:

1. Install/run a fresh bundle without developer Python, Rust or Node on PATH;
   verify executable identity, sidecar/runtime inventory and WebView2 startup.
2. Confirm first-run settings/resource provisioning stays responsive, reaches
   accurate runtime/engine readiness, retries after a controlled failure, and
   never reports providers resident when they are unloaded.
3. Exercise tray reopen/quit, Control Center close/reopen, activation and
   Alt+Tab task switching, every page/action/dialog, permission
   refresh, settings persistence, logs/export, and scope errors from each
   window's command allowlist.
4. With monitor layouts that include mixed DPI and a negative secondary origin,
   select/cancel/apply regions and verify coordinates, cursor monitor choice,
   clipping and popup placement. Check UTF-16 offsets and AX/UIA acquisition,
   then OCR fallback on text rendered as raster/image.
5. Hold/release Push to Hover, pause/resume and start/stop shortcuts; test direct
   text and OCR, positive/negative Lab targets, compact/expanded/close, pointer
   crossing, non-activation, no stale popup and no focus theft.
6. Use a Lab-owned InPrivate Edge page only. Run `python -m lab` for a
   person-driven session, then `python -m lab tour --no-open` (and a compatible
   stress run if applicable); read summary/provenance/baseline before comparing.
   Confirm the report attributes Tauri, Python and lookup descendants together,
   and that no recognized text or pixels were retained.
7. With disposable old and new install trees, apply the official update fixture
   from the existing V1 layout. Check hash/signature/inventory/ownership,
   unchanged data paths, cancellation before mutation, new Tauri-root readiness
   before commit, rollback when root start or service handshake fails, and
   recovery after interruption. Confirm a Python-only service start cannot
   acknowledge the install.
8. Close the app normally and after a forced service/lookup crash; verify no
   Python service, lookup child, updater helper or tray owner remains. Record
   `HANLY_REQUIRE_NATIVE=1` and `HANLY_REQUIRE_PACKAGED=1` results from Windows
   CI in addition to the real-desktop checks.

At this checkpoint `package-lock.json` and `Cargo.lock` exist and stable
versions are exact. Scripts include `check`, `test`, `test:ui`, `build` and
`tauri`; the official configuration still disables release bundling. The debug
Mac `.app` uses developer Python and proves neither Windows redirected stdio nor
release packaging. The Windows continuation above is staged for the complete
runtime; update its packaged commands when implementation phase E lands.

## Linux validation limits

Hanly's current release workflow builds a Linux x86_64 tarball on Ubuntu and
runs native/packaged checks under Xvfb. CI can validate the Linux build, shared
protocol, Python behavior and the display-backed paths its virtual X server
exercises. It does not establish behavior on a person's Wayland compositor,
actual mixed-DPI/multi-monitor setup, accessibility bus, global shortcut
permissions, desktop tray/status-notifier implementation, focus/activation or
screen-capture portal.

Tauri's WebKitGTK and OS integration introduce a different system-library and
desktop-session boundary from the old Qt bundle. Keep the existing Linux
distribution product supported; record the exact supported distro/runtime
dependencies from the official build, run native checks on a real Linux session
when available, and mark absent compositor/portal/tray checks unverified.
This Mac session cannot claim Linux native acceptance. A passing Ubuntu/Xvfb
job is build/virtual-display evidence, not cross-desktop equivalence.

## Verification recorded for this checkpoint

- Read the migration brief, repository instructions, code map, architecture
  sources, execution plan, OCR decision/latency record, spike plan/handoff and
  README from `spike/desktop-renderers`, Lab README, and packaging/updater/CI
  entry points.
- Architecture overlay was added to sources 01–03 and their visual companions;
  each existing invariant ID and its order is unchanged.
- `.venv/bin/python -m pytest tests/test_architecture_invariants.py -q` — 6
  passed. This checks ordered RF, CA, DAG and AEF markdown/visual lists and the
  repository's derived invariant index.
- `.venv/bin/python -m pytest -q --tb=short` outside the sandbox: **2,800 passed,
  3 skipped, 1 failed** in 413.88 s. Failure:
  `tests/packaged/shared/test_packaged_desktop.py::test_the_frozen_worker_becomes_ready_on_an_isolated_profile`:
  the existing `dist/macos/Hanly.app` reports both package versions as 1.0.0, while
  the checkout expects 1.1.0. The full gate is not green. No assertion, timeout,
  skip or bundle identity was changed to conceal this stale build.
- The earlier sandbox-only portable run had 2,663 passes, 3 skips and 6 failures
  from denied process inventory/sysctl and Vision access. The unsandboxed full
  run resolved those failures; it still exposed the stale packaged identity.
- Final focused service/invariant checks: **17 passed** (11 service, 6 architecture).
  Ruff passed; mypy passed across **362** source files after the final edits.
- Frontend: **9** Node contract/state/settings/routing tests and **5** Vitest/jsdom
  page-interaction tests passed; strict TypeScript check and Vite build passed.
  The ISO log timestamp regression is covered by a real rendered-page test.
- Rust: **12** tests passed, including actual Rust→Python service handshake and
  cleanup, malformed protocol, deadlines, monotonic events and window scopes.
  Clippy with `-D warnings` and rustfmt check passed.
- Tauri debug custom-protocol executable and disposable debug `.app` built.
  This `.app` uses developer `.venv` Python and is not a self-contained release.
  `bundle.active` remains false in the official configuration pending phase E.
- Native Computer Use on the disposable app/profile: Control Center Capture,
  Appearance, Logs and Permissions navigation; visible unavailable capture;
  Light theme acknowledged, persisted and retained after reopen; incumbent
  three-panel Appearance layout; valid ISO log times; explicit unavailable
  permission checks; Quit confirmation and normal exit code 0. Exact observed
  root/service PIDs and creation times were checked: **2 observed, 0 remaining**.
  No screenshot, private profile, recording or process evidence was added to Git.
- Tray/Dock/Cmd+Tab/close-reopen via tray, real hover/direct-text/OCR, popup
  non-activation/retention/crossing, region overlay and packaged updater acceptance
  were not established. No official Lab tour or release memory/latency result
  exists. No Windows/Linux native or CI acceptance is claimed.

## Implemented foundation and continuation — 2026-10-13

- `apps/desktop`: React Router pages, incumbent CSS/icon and shared token aliases,
  typed native bridge/events, structured errors, settings/logs and interaction
  tests. Rust creates native windows and tray/reopen scaffolding, derives caller
  window identity, restricts navigation/CSP/permissions, coalesces pending event
  snapshots and supervises the fixed private Python process.
- `hanly_app.service`: strict JSONL and Qt-free startup; handshake, honest idle/
  sleeping state, configuration persistence, bounded log snapshot and shutdown.
  All remaining recognized service actions explicitly return `unavailable`.
  `freeze_support()` precedes service main dispatch; production frozen service
  packaging is still absent. No provider, dictionary outcome or engine code changed.
- Stable dependencies were resolved from npm/crates registries; exact versions
  and lockfiles are committed. Tauri 3 alpha hits were rejected in favor of
  stable Tauri 2.12.3; no experimental performance settings or private SPI was
  copied into production. Diagnostic spike code stays on its preserved branch.
- Existing production CLI, Qt/pywebview shell, adapters, dependencies, packaging,
  updater and tests remain. The foundation does not switch users to an incomplete
  desktop or provide a hidden runtime fallback. No tests were discarded.
- Service failures resolve outstanding requests and show a restart-required
  error. An automatic restart budget, worker family ownership/kill guarantees,
  event acknowledgement during hover, update root acknowledgement and native
  signal supervision must be completed before production integration.

Continue on this branch, without another plan or intermediate handoff:

1. Extend the service with one serialized owner for callbacks/timers, then port
   `StartupCoordinator`, Qt-free bridge actions and `create_manual_lookup` using
   the existing engine/AX/UIA/MSS contracts. Keep resource work off the UI thread,
   readiness/residency separate and the final Python currency check intact.
2. Implement event-backed popup presentation/geometry feedback and retained-target
   crossing; connect monitor/cursor capture and the React selector. Complete
   native hotkey press/release, permissions, non-activation, theme and shutdown.
   Test every migrated adapter responsibility before deleting its Qt tests/code.
3. Complete update/diagnostics actions and confirmations through the existing
   Python updater. Resolve root-versus-service installation identity and challenge
   acknowledgement. A protocol handshake alone must never commit an update.
4. Produce a console-capable, console-hidden-on-Windows frozen service plus its
   providers/models/resources/helpers; define Tauri bundle inventory and stable
   identity, and preserve old product layout/update/data-path compatibility.
   Then adapt self-checks, CI, native/packaged tests and official launch commands.
5. Port Lab launch/control and exact whole-family attribution, respecting existing
   ownership/privacy guards. Run fresh Mac packaged acceptance and controlled
   Safari tours; record compatible release measurements. Execute the real Windows
   continuation and retain explicit Linux limitations. Only then remove production
   Qt/Qt WebEngine/pywebview, update current architecture descriptions/companions,
   run final gates and write the single Review Handoff. Do not start Phase B.

Development and boundary commands are in `apps/desktop/README.md`. Do not treat
this checkpoint as migration completion or as approval of unchecked behavior.
