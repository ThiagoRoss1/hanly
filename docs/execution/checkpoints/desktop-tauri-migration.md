# Hanly Desktop Tauri migration checkpoint

Status: the implementation, requested cleanup and Codex code review are committed
through product `0b8a9f4` and Lab `e6250f7`. Final Mac package/archive checks pass
on build `7569005a`. Native
acceptance is in progress. Do not call
native hover acceptance complete from automated gates alone.

## Current continuation — 2026-10-14

- Removed all inline Python `noqa`/`type: ignore` suppressions through typed
  fixtures, explicit invalid-runtime-input boundaries, narrowing and teardown.
  Production event-loop work retains its generic type; obsolete popup/report
  helpers are removed. No engine source changed.
- Removed the remaining Lab Qt fixtures, HUD adapters, dependency group and
  private responsibility launcher. Pillow/AppKit/Tk now paint owned raster
  fixtures. The Mac loop returns through cleanup/report generation; failed
  launch FIFO release is bounded. Native Windows/X11 pointer signatures and
  signed DPI results are covered by portable seam tests.
- Public LaunchServices launches the exact fresh app PID, with allowlisted Lab
  environment and mode-0600 FIFO tracing. Private fixture evidence stays in
  memory; the sampler records actual root responsibility attribution. Protocol
  v3 separates this launcher/raster workload from former recordings.
- The shortcut investigation identified missing SecondaryFn interpretation in
  Lab's synthetic macOS function keys. Both press/release edges and the actual
  Start Capture action reached the packaged app using the corrected driver.
  Letter chords work through either Carbon target. No production shortcut
  backend change was justified or adopted. Physical keyboard/held push-to-hover
  confirmation remains distinct from that synthesized-input evidence.
- Popup actions now retain their authorized window identity, translate wire
  event sequence to Python popup content sequence and preserve increasing React
  freshness across replacement services. Rust regression coverage includes
  stale actions, duplicate events and restart counters.
- Actual release popup verification exposed a missing presentation trace after
  Qt retirement. `0b8a9f4` emits `popup_visible` only after React's rendered
  geometry completes a native resize, deduplicates expansion/repeated geometry,
  rejects stale result acknowledgements and preserves the request identity
  through expansion. No text or pixels enter that trace. The 77 focused
  service/popup/retention/loop checks and full portable/native/package gates pass.
- React code is formatted and unused local/parameter checks are enforced.
  All six pages and the responsive, full-height layout retain the approved
  Hanly appearance; hidden region controls are inert and absent from AX.
- Latest gates: portable Python 2,602 passed / 2 skipped; macOS native 86 passed;
  latest portable Lab 549 passed; real raster painting/ownership passed; Ruff
  and mypy clean (342 files); React 40 + Node 9, TypeScript/build passed; Rust
  17 + Clippy/rustfmt passed; workflow/raster focused 94 and packaging/
  architecture focused 169 passed. Native/process gates used host access.
- The earlier canonical packaged app's authorized Screen Recording and
  Accessibility registrations were refreshed for its new ad-hoc signature.
  Actual Start Capture reached Armed on the `a54784c` build.
  The human subsequently approved the debug Lab bundle's same two grants;
  both current identities still need their native registration refresh.
- Actual Retina selection previously saved logical 225/225/300/200 from a
  physical 450/450→1050/850 drag; Escape retained it. Only one display is
  connected, so real mixed-display claims remain unavailable.
- `20261013-232232-tour` adopted the debug root through LaunchServices, forwarded
  debug evidence through its FIFO and received both native capture edges, but
  capture was denied. It scored no successful hovers. Earlier failed/aborted
  tours and startup-only recordings remain historical evidence, not passes.

- The `2b93252` package showed actual 학교 / school content from a controlled
  Safari OCR hover, including Hanja, definitions, Expand and Close. Incorrect
  initial global coordinates were rejected, not counted as passes. Actual native
  geometry forwarding raised TypeError because fractional coordinates entered
  integer ScreenRect; `a54784c` encloses them with floor/ceil. Its 70 focused and
  full portable tests pass; the corrected final bundle is built.
- Final build `7569005a-6a5a-4efc-9739-a54266b2855a` embeds product source
  `0b8a9f4f9a6a33fdfdc4bb4846e0f3a5e28cfba9`. All seven packaged gates passed
  in 190.70s, including real React readiness, frozen OCR/lookup, updater root
  acknowledgement and failed-root POSIX-helper rollback. ZIP and DMG each
  match all 3,762 manifest entries; inventory and strict deep signatures pass.
- Root 14424 from the earlier `2b93252` build exited on SIGINT; all ten
  sampler-attributed native/service/lookup/WebKit PIDs were confirmed gone.
- Recording `20261014-040129-run` found a dictionary entry through Vision and
  recorded current delivery, but had no visual verification before shutdown.
  Its zero-popup summary cannot establish staleness: the presentation trace was
  missing. Automatic shutdown reported no survivors or forced kills.
- The Dock focus probe timed out in computer-use. Safari owned the actual
  controlled hover point, but active-app/nonactivation was not established.
  No native AX or focus pass is inferred from the successful OCR popup.

Remaining on final build `7569005a`: verify rendered-popup acknowledgement;
run the controlled Safari AX/raster/
negative, popup focus/crossing/expand/close and first/warm/family measurements.
Run the scored debug tour after its permission answer. Update this checkpoint
and the existing handoff with final provenance and exact remaining limits.
The current Safari test is obstructed by Codex's foreground window; the owner
check refuses to hover over it. Computer-use explicitly forbids controlling
Codex's own app, so bringing the controlled Safari window forward requires the
human. No other interface is used to bypass that restriction.
`20261014-040730-run` ended automatically after 604.5s with no lookup attempted,
zero dropped events, exit zero, no surviving descendants and no forced kills.
Its family peak was 205.5 MiB and whole-session mean summed CPU was 1.6%; this
idle/armed recording does not establish lookup latency or workload acceptance.
Windows/Linux physical native acceptance remains host-dependent. Playwright
planning stays deferred until native migration acceptance. No push, merge, tag
or release is authorized.

The resumed `20261014-144716-run` used the `a54784c` frozen product. Its actual
Lab-authored raster 학교 showed school, Hanja and the expected definition;
Expand, Close and transfer through the nearest popup edge worked. Fourteen
pointer samples stayed protected without another lookup. A large diagonal jump
outside the narrow transfer corridor dismissed the popup as expected. The
summary's zero-popups/unseen-OCR explanations are invalidated by the missing
presentation trace. Confirmed normal Quit ended the 918.8s session with exit
zero, no survivors/forced kills and no dropped events. CUA app observations do
not establish native foreground focus. Safari, debug-grant refresh and
physical key input remain pending. The debug bundle was rebuilt from current
Rust/React source before applying any grant.

The final `7569005a` canonical and debug apps still show both required, although
macOS lists Hanly enabled. Both identities are now explicitly authorized by the
human. Native picker confirmation remains incomplete through automation, and
human completion was requested. The human also requires every necessary grant
to be actionable from Hanly's Permissions page. The existing two-grant flow
already requests OS consent, opens the correct privacy pane and rechecks on
focus return; no third product grant was found. No grant refresh is claimed.
Both latest permission-only probes exited normally with zero surviving/forced
children. No passwords were entered or requested in chat.

`20261014-152133-run` exposed failed Lab adoption while a root actually ran;
its cleanup implication is invalid. Root 34394 was independently stopped with
zero survivors. `e6250f7` refreshes executable/argv identity across exec and
reaps only a fresh exact-profile root after failed adoption. All 549 portable
Lab tests, 13 focused process checks, Ruff and mypy pass. The corrected native
retry `20261014-152757-run` adopted root 35074 in 4.44s, attributed its helpers
through macOS responsibility, and ended after 186.2s with no surviving/forced
children. That startup/idle run contains the then-uncommitted Lab fix and no
capture; no lookup latency or RAM saving follows. Lab is not shipped, so its
later commit does not change the sealed `0b8a9f4` product identity.

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
| `62f7612` | Complete React state/actions/dialogs/popup/selector interactions; aligned settings and full-height shell. | 40 UI + 9 contract tests, types/build; native source visual checks passed. |
| `e02c011` | Real async service/runtime, native input seam, acquisition/lookup and clean protocol shutdown. | 72 focused checks; final portable/native gates pass. |
| `1e0ded9` | Native windows, context, supervision, transactional hotkeys and root readiness. | Rust 15 + Clippy/fmt; native capture/shortcut acceptance still unverified. |
| `624ba53` | Removed production Qt adapters/assets and migrated retained tests. | Portable 2,569 and native 86 passed. |
| `e8fca98` | Official Lab launch, family attribution and private-evidence boundary. | 518 portable Lab and native corpus fixture passed; successful hover recording still absent. |
| `96cc73e` | Coordinated native/service packaging, updater transition and CI dependency ordering. | All 7 packaged Mac gates passed with native host access; frozen OCR/lookup, ordinary-root acknowledgement and failed-root rollback verified. |
| `422bb07` | Collapsed panels are inert and hidden from accessibility. | 40 React interactions, types/build and final 7-test packaged gate passed; hidden region controls absent from actual packaged AX tree. |
| `805ad5d` | Typed Python test/service cleanup; no inline suppressions. | Portable/native gates pass. |
| `ca27111`, `3565de8` | Popup window authority, counter translation and recovery freshness. | Rust 17 regressions + Clippy/fmt pass; live popup checks remain permission-dependent. |
| `8b9a4ed` | React formatting and enforced unused declarations. | React 40, Node 9, TypeScript/build pass. |
| `ff64a87`, `2b93252` | Qt-free Lab, public Mac launch/FIFO, Fn input, report cleanup and native FFI signatures. | Lab 548 portable + actual Mac raster/ownership pass; scored capture tour needs debug grants. |
| `dc8d6f4` | Current runtime/setup/code-map and synchronized architecture guidance. | Architecture/packaging focused gates pass. |

The human explicitly requested the cleanup, code review and optimization
continuation. Codex performed that requested review in this resumed run. No
independent/cross-provider reviewer, push, merge, tag or release occurred.

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
- The internal frozen service is console-capable with redirected JSONL pipes;
  Windows hides its console. Its entrypoint calls `freeze_support()` first,
  and graceful shutdown returns normally after the service/lookup owner closes.
- Python emits only normalized JSON values. The final request-currency check
  remains in Python immediately before popup publication; a later frontend
  sequence check may discard superseded presentation but cannot replace it.
- Shutdown stops admission, cancels hover work, stops capture/hotkeys, closes
  and joins the lookup child, flushes diagnostics, replies when possible, then
  exits. Rust waits a bounded interval and terminates the process family only
  after graceful shutdown fails.
- Updater handoff waits for the new Tauri/Rust root after both the service
  handshake and React frontend readiness. Provider preload/runtime readiness
  remains a separate milestone; a service handshake alone never commits an update.

## Test migration inventory

| Existing tests | Classification and destination |
|---|---|
| `tests/krdict/*`, engine/provider/pipeline/contracts, language and word resolution, resource validation, package boundary/imports | Keep as engine or Qt-free Python behavior tests. Engine outputs and provider seams must remain equivalent. |
| `test_app_config.py`, `test_runtime.py`, `test_runtime_status.py`, `test_first_run.py`, `test_owned_cleanup.py`, `test_diagnostics.py`, `test_update_*`, `test_app_update_*`, `test_update_coordinator.py`, `test_update_service.py` | Keep domain/config/resource/updater guarantees. Port UI dispatch and root lifecycle seams; extend install-tree compatibility, new-root acknowledgement and rollback cases. |
| `test_capture.py`, `test_text_acquisition*`, `test_direct_text_routing.py`, `test_mouse_observer.py`, `test_hover_controller.py`, `test_hover_lookup*`, `test_lookup_controller.py`, `test_lookup_process.py`, `test_job_executor.py`, `test_manual_lookup.py`, `test_retained_target_evidence.py` | Keep Qt-free behavior contracts; add service IPC, restart, ordering, 1 MiB/32 pending, malformed frame, per-window authorization and disconnect/cleanup coverage. |
| `test_qt_bootstrap.py`, `test_signal_bridge.py`, `test_capture_selector.py`, Qt-specific cases in `test_popup.py`, `native/shared/test_qt_hover_scheduler.py`, `test_hover_exit_qt.py`, `test_qt_popup_window.py`, `test_qt_screen.py`, `native/macos/test_popup_panel.py`, `native/shared/test_capture_prompt_shutdown.py`, `test_app_icon_qt.py`, `native/windows/test_window_frame.py` | Qt adapter tests: port each behavior to Rust/native window or Python scheduler boundary before removing the old test. Keep the Qt-independent `popup/presentation.py` placement/content assertions. Retain genuine geometry, focus, cleanup and selection assertions. |
| `test_control_center.py`, `test_control_center_host.py`, `test_control_center_process.py`, `test_control_center_refresh.py`, `native/macos/test_control_center_identity.py`, `native/shared/test_control_center_combobox.py`, `test_control_center_copy.py`, `test_control_center_layout.py`, `test_control_center_lifecycle.py`, `test_webengine_startup.py`, `native/windows/test_webengine_arguments.py`, `tests/hanly_fixtures/assets/control_center_harness.js` | Keep Python action validation/configuration semantics in service tests; renderer and settings interactions belong in Vitest React DOM tests; host/process/WebEngine behavior belongs in Rust window/command/lifecycle tests. The legacy refresh JS harness is removed after React behavior coverage; host-only cases remain until native replacements pass. |
| `tests/packaged/*`, `test_packaging.py`, `test_release_build.py`, `test_release_products.py`, workflow checks | Replace PyInstaller inventory/self-check assumptions with Tauri + sidecar/runtime identity and inventory tests, real fresh-bundle startup, user-data transition and updater smoke. Preserve version/source identity and target-platform coverage. |
| `lab/tests/*` plus Lab app launch/control/sampling tests | Port launch/control/observation to the official root and count the whole process family (Tauri + Python service + lookup child + owned helpers). Preserve privacy and ownership guards. |

No framework test is removed just because it names Qt. A test is obsolete only
when its responsibility no longer exists and that fact is recorded with a
replacement or a clear explanation.

The former `test_control_center_refresh.py` and its JS harness are now replaced
by `apps/desktop/tests/ui/desktop-pages.test.tsx`: the 40 DOM tests cover
readiness and update polling, poll failure/reconnect, event state replacement,
permission recheck on return from OS settings, stable navigation focus and
in-progress settings edits, shortcut and delay validation, update confirmation
and cancellation, logs filtering/copy/export, and popup/region routes. The
Python `test_control_center.py` keeps bridge business rules but no longer
asserts legacy page HTML, JavaScript or CSS. `test_theme_contrast.py` reads the
React palette tokens directly instead of importing the Qt palette; its light
muted-text token was adjusted to clear 4.5:1 on the popup footer surface.
Focused evidence: `npm run test:ui` (40 passed), `npm run check`, `npm run
build`, `pytest tests/test_control_center.py tests/test_theme_contrast.py -q`
(76 passed), and Ruff on the edited Python tests.

## Current execution state

| Phase | Implemented boundary | Remaining evidence |
|---|---|---|
| A | Inventory, approved ownership/IPC contracts and synchronized invariants. | None. |
| B | Asynchronous service, runtime/lookup composition, bounded IPC and family supervision. | None in verified Mac scenarios. |
| C | All React surfaces and interactions; corrected full-height shell and settings grid. | Live popup and selector screen-content acceptance. |
| D | Native windows, tray/reopen, shortcuts, permissions, timers and shutdown adapters. | Real shortcut press/release, popup nonactivation/crossing, mixed-monitor selection. |
| E | Coordinated Tauri/Python product, existing updater transition/ack/rollback and CI. | Windows/Linux host execution. |
| F | Lab root/family attribution, privacy, legacy removal, runbooks and final handoff. | Permission/input-dependent native workload acceptance. |

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
npm run test:ui
npm run build
Pop-Location
cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml --locked
cargo clippy --manifest-path apps/desktop/src-tauri/Cargo.toml --all-targets --locked -- -D warnings
cargo fmt --manifest-path apps/desktop/src-tauri/Cargo.toml --check
& .\.venv\Scripts\python.exe tools/build_package.py
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

Exact dependency locks and scripts are committed. Use the coordinated builder;
the checked-in Tauri config disables standalone bundling because its generated
service/resource overlay exists only during that build. The Mac debug app uses
developer Python and cannot establish Windows redirected stdio, Job ownership,
WebView2 behavior or updater acceptance.

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

## Current verification and remaining work — 2026-10-13

The latest continuation results and active steps are listed at the top. Older
Phase A build `77d09d75-bbc9-4565-98d0-6ebb7f6304ad` from product commit
`422bb07` passed seven packaged gates and archive/signature checks, but it is
superseded by the final rebuild. Never infer its acceptance for new source.

Release recording `20261013-202154-run` was startup/idle only: 124.9s, family
peak RSS 246.7 MiB, 30–120s mean RSS 77.39 MiB / summed CPU 1.51%, runtime
preparation 9.576s, all nine attributed PIDs gone. It had no capture or lookup
and used the earlier protocol. October 7 Qt baselines are incompatible. No
memory-saving or first/warm lookup-latency claim follows from these recordings.

The single handoff remains `docs/execution/review-handoffs/desktop-tauri-migration.md`.
Its final continuation must distinguish completed code/build checks from native
acceptance blocked by OS access and unavailable cross-platform hardware.
