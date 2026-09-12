# Post-runtime product fixes

**Status: DRAFT — Windows investigation complete; macOS phase pending.**

Investigated 2026-09-11 (America/Sao_Paulo), against
`5264c1299b90a63b63ecb5ce17ea24ddef0101f8`. This is the **one implementation
plan**, intended for Claude Opus after the human reviews it and the macOS phase
updates this same file. It is not authorization to implement yet.

## 1. Scope and non-goals

The two attached texts and four screenshots are product input: distinguish the
Portuguese observations from the suggested explanations. In particular, print4
marks where an intermittent error appeared; it is not itself proof of vertical
overlap. The desired products are three distinct global actions, truthful
readiness, reliable disposable UI, fast geometry-based exit, useful diagnostics,
and preservation of the low-residency architecture.

This pass investigated and planned only. No product implementation, commit,
push, Linear update, merge, tag, or release. Temporary probes and their logs live
under ignored `build/post-runtime-probes/`; the important results and replay
recipes are included here so the next machine does not need those local files.

No OCR replacement, ONNX, accuracy tradeoff, Kiwi dictionary removal, HTTP health
endpoint, framework, visual redesign, generic cleanup, or invented memory-leak
fix. The reported ~100 MB / ~30 MB / ~980 MB footprints are user observations,
not thresholds for CI and not measurements from this investigation.

## 2. Architecture assumptions that remain fixed

- `hanly-app -> hanly`; engine contracts and provider seams stay client independent.
- One desktop entry point, `hanly_app.cli:main`, including frozen spawn dispatch.
- Persistent shell: Qt Widgets, tray, input, capture, controller, popup, settings,
  diagnostics. Disposable Control Center child: pywebview/Qt WebEngine. Disposable
  lookup child: EasyOCR/Kiwi/KRDICT. Do not keep WebEngine resident to avoid reopen.
- Inherited bounded pipe messages, explicit operation allowlist, no listening
  port, no general remote dispatch. `LookupController` remains in the shell;
  bounded/latest-wins execution and the final presentation currency check stay.
- Resource validation, worker-wrapper readiness, and actual provider residency
  are different facts. `RuntimeStatus` already exists; do not create a second
  health subsystem that repeats it.
- Capture remains a small ROI; observing movement is not OCR. No motion/OCR
  polling while dormant. Popup navigation must remain possible.
- `05-execution-plan.md` controls later implementation/handoff. This platform
  investigation is not implementation Phase A or an automatic deep review.
- Architecture Markdown still predates parts of the previous runtime wave.
  The existing wave handoff records that drift; this file does not silently
  amend its invariants. See section 17 for the approval-sensitive clarifications.

## 3. Windows evidence

### Environment and validation boundaries

Windows 10 build 19045, x64; Intel Family 6 Model 158 Stepping 13. Two monitors
report 1920 x 1080, at x=0 and x=-1920. Native UI probes reported DPR=1.

| Environment | Python | Qt bindings / native runtimes | Other relevant versions |
|---|---|---|---|
| Repository `.venv` | 3.13.11 | PyQt6 6.10.2, WebEngine binding 6.10.0; both native Qt distributions 6.10.2 | pywebview 6.2.1, pynput 1.8.2, EasyOCR 1.7.2, Torch 2.13.0, Kiwi 0.23.2, PyInstaller 6.22.2 |
| Fresh UI-only venv | 3.13.11 | Same binding/native versions as repository | pywebview 6.2.1; no Torch, EasyOCR, Kiwi or pystray installed |
| Existing `dist/windows/hanly-desktop/hanly-desktop.exe` | 3.10.11 | PyQt6 and WebEngine bindings 6.11.0 | pywebview 6.2.1, Torch 2.14.0, EasyOCR 1.7.2, Kiwi 0.23.2 |

The existing frozen artifact reports Hanly 0.1.3 but was not rebuilt from this
HEAD during this pass; do not call it a frozen verification of this exact commit.
The clean environment isolates **UI dependencies**, not the complete runtime
or release build. `pip check` passes in the repository environment. The mismatch
between binding patch numbers is not, by itself, proof of incompatible native Qt.
The source WebEngine reports Chromium `134.0.6998.208`.

Initial sandbox runs could not read the OCR weight file and WebEngine failed to
load its document. Repeating the native probes outside the sandbox fixed those
restrictions. Those initial failures are not product regressions.

Executed checks:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_control_center_process.py tests/test_control_center_host.py tests/test_control_center_refresh.py tests/test_hover_target.py tests/test_hotkeys.py tests/test_hotkeys_darwin.py -q
# 92 passed; pytest cache write warning from sandbox permissions.

.venv/Scripts/python.exe -m pytest tests/integration/test_lookup_process_spawn.py tests/integration/test_control_center_lifecycle.py -q -p no:cacheprovider
# Outside sandbox: 2 passed in 74.13 s.

.venv/Scripts/python.exe -m pip check
# No broken requirements found.
```

Frozen UI self-check, captured by `subprocess.run(..., capture_output=True,
timeout=90)` outside the sandbox: `ok=true`, four controls, bridge round trip
4.7 ms, whole window stage 1168.3 ms, empty stderr. A direct PowerShell invocation
of a windowed executable can return before it finishes; it is not a valid wait.
Clean UI-only source self-check: `ok=true`, bridge 5.4 ms, window stage 3718.1 ms;
DirectComposition warning remained.

### Reopen and reader failure

**Native reproduction: 3/3 rapid double-open cycles produced the exact supplied
reader-thread traceback.** Call `ControlCenterProcess.show()` twice immediately
after spawning. The second call observes an alive process and sends `focus`.
The child starts its reader **before** `ControlCenterHost.run()` creates a
window. `_receive_one()` calls `host.show()` unconditionally; `_require_window()`
raises `ControlCenterUnavailable`. The reader catches only `TransportClosed`.
Its finally block closes a host that may not have a window yet, then the main
thread proceeds to create the window with no functioning reply reader.

A diagnostic bridge returning `app.state="running"` still rendered `new` in the
broken child: this is the JS fallback, not a new shell. Repeating with the
**probe-only** `CALL_TIMEOUT_SECONDS=.8` reproduced `Hanly did not answer in
time.` for initial page calls. Production remains 900 seconds. This demonstrates
a mechanism for both symptoms, not proof that the historical timeout used the
same trigger or that it elapsed after exactly 900 seconds on the user's run.

Three ordinary native open/close cycles succeeded when each close completed
before reopening. Two full-application probe runs also exercised three capture
cycles each via `run_desktop`, the real bridge, native child windows and real
lookup providers. Capture remained RUNNING while the Control Center disappeared;
reopening rendered `running`. The corrected driver called `DesktopApplication.quit`
and ended with `multiprocessing.active_children() == []`. These are native
window-destroy events through pywebview, not physical clicks on the title bar.

The first driver mistakenly called `shutdown` without `quit` and read a nonexistent
diagnostics attribute; its shell stayed in the loop after cleanup. That was a
probe defect, not a Hanly defect. Only the corrected run proves final loop exit.

Additional source-supported ownership risks requiring regression coverage:

- Alive process is treated as focusable; no `starting/ready/closing` handshake.
- Child `closing` only sets a reader-local flag; it does not immediately make
  the manager non-focusable. The same host exception is possible after destruction.
- `_child_gone()` checks generation before calling `_retire()`, but `_retire()`
  unconditionally clears whichever process/transport is current. A concurrent
  replacement between the check and retirement can be detached.
- `_start()` spawns outside an ownership reservation; concurrent `show()` calls
  can both decide to spawn. Serialize ownership transitions without holding a
  UI thread across a child join.
- `_outstanding` is global and reset on retirement; old operation completions
  can decrement the replacement generation's count. `_run_operation()` checks
  currency only before replying, not before executing a queued mutation.
- A native child close can yield manager `running=False` while the old process
  is still alive during interpreter teardown. The standalone probe observed
  this transient state. It is not evidence of a persistent orphan/leak, but
  proves that manager fields alone are insufficient lifecycle assertions.

### Layout

Measured the actual WebEngine DOM after resize, not a browser approximation:

| Requested window width | JS innerWidth | Document scrollWidth | Action row bottom -> first field grid top |
|---|---|---|---|
| 1080 | 1080 | 1063 | 348.5 -> 370.5 (22 px gap) |
| 900 | 900 | 883 | 371 -> 393 (22 px gap) |
| 780 | 780 | 843 | 393.5 -> 415.5 (22 px gap), horizontal overflow |
| 760 | 760 | 743 | 1041.5 -> 1063.5 (22 px gap), stacked layout |

`ControlCenterHost._create_window()` has min_size=(760,560); CSS switches to
stacking only at max-width:760px. Above that, shell padding 116px, status-column
minimum 190px, layout gap 54px, section columns minimum 180+280px and section gap
34px cannot fit. `.action-row` also lacks wrapping above 500px. Vertical button
overlap was **not** reproduced at DPR=1. When the timeout alert is visible it
inserts another 18px before fields in the probe, explaining text in the marked
area. Fractional/mixed Windows DPI and zoom remain manual validation items.

### Runtime status and action routing

The real bridge reported `app.state=running, capture_running=true` while
`runtime.engine.state=preparing` immediately after Start, in every captured cycle.
`DesktopController.start/resume` sets RUNNING when observation is requested;
`RuntimeStatus` becomes ready when the executor has attached its lightweight
worker, even if the providers are asleep. JS renders `app.state` independently.
`_on_engine_state` updates another tuple and pushes refresh. There is no aggregate
product status. This is confirmed misleading presentation, not evidence that
loading the engine asynchronously is wrong.

`ManualLookupRuntime._handle_action(LOOKUP)` implements an actual one-shot
cursor capture and submission. It is not a no-op in code, but it has no hold or
release semantics. Whether a physical Ctrl+Shift+Space reaches it on the user's
machine remains unproven. `TOGGLE_HOVER` calls `_DesktopSession.toggle_capture`,
which invokes Start/Stop and releases the child under the default policy. It
does **not** implement the requested RAM-resident pause.

UI Start calls the session through the bridge; tray/shortcut Start goes through
`DesktopApplication`. Only the latter records the "Capture" log there. The full
bridge-driven session logs engine transitions but no corresponding Capture
records. `_DesktopSession.registered_hotkeys` returns configured bindings even
if registration failed; the method does not check `registered`. Do not label
those as successfully registered in diagnostics/UI.

### Popup exit

`MouseObserver` is event-driven and coalesces queued positions. There is no fixed
poll cadence to tune. `RetainedTarget` uses the union of a word expanded by 4px
and popup bounds; leaving arms 120ms grace. No OCR/Kiwi/KRDICT is needed to test
that geometry.

**Confirmed additional defect:** `create_qt_manual_lookup` supplies one
`QtHoverScheduler` to `HoverLookupRuntime`, which shares it with `HoverController`.
It has one reusable timer. `_leave_retained_target` schedules grace, then
`HoverController.on_position` schedules dwell and replaces the timer callback.
With real Qt, 80ms dwell, a retained word and pointer moved away, a 359.65ms probe
reported **0 dismissals, retained=true, one new capture, grace handle still set**.
This can delay dismissal until another result or event, rather than simply by
120ms. Tests in `test_hover_target.py` use a multi-handle fake scheduler and miss
the production scheduler's exclusivity.

## 4. macOS investigation evidence — pending

No native macOS work was performed here. Historical measurements and limitations
are in `review-handoffs/mvp-runtime-performance-wave.md`; they are not new evidence.
The Windows investigation does not identify which macOS PID owns the duplicate
Dock entry.

The next agent must append dated evidence here, using this table:

| Required observation | Record before finalizing |
|---|---|
| Source `hanly` / `python -m hanly_app` | PID, PPID, role, executable, activation policy, Dock entry before/after Start and each window close |
| Frozen `.app`, launch via Finder or `open` | Same observations, bundle identity and executable identity; compare direct internal executable only as a diagnostic |
| Shell vs CC vs lookup vs resource tracker | Identify the exact PID creating the extra user-facing app; do not infer from the Python icon |
| Carbon hold | Physical press, repeat, release of primary key, release of each modifier first, left/right modifiers, input-source change, rebind while held |
| Focus/security/session transitions | Alt/Cmd-Tab, popup focus, app inactive, lock/unlock, sleep/wake, secure input and denied permissions |
| Background | CC closed; tray restores exactly one usable UI; global actions still work; no unwanted Dock/window activation |
| Exit geometry | Word micro-motion, toward popup, away, popup controls, Retina/mixed monitors; event-to-dismiss timing |
| Native teardown | Page destroyed before profile, children reaped; source and frozen close/reopen under capture |

Read `hotkeys_darwin.py`, `popup_darwin.py`, `qt_bootstrap.py`,
`control_center_host.py`, `process_transport.py`, `lookup_process.py`,
`packaging/runtime_hook.py`, and the spec before choosing a fix. The lookup child
does not intentionally construct QApplication; shell and CC do. These are
inspection leads, not a proven Dock cause. Do not set global LSUIElement or
LSBackgroundOnly flags that hide or break the actual Hanly UI as a shortcut.

## 5. Confirmed defects and root causes

| ID | Defect | Confidence / evidence | Task |
|---|---|---|---|
| D1 | Early focus kills CC reader; page remains fallback | Native 3/3, exact supplied traceback; before-window ordering | T1 |
| D2 | Application RUNNING while providers prepare | Real session snapshots, independent state sources | T3 |
| D3 | Hover toggle retires heavy runtime; lookup key is not a hold | Exact production routing and press-only backend seam | T4/T5 |
| D4 | Exit grace lost to next dwell on Qt | Real Qt scheduler reproduction, not just constant inspection | T6 |
| D5 | Horizontal layout overflow above 760px breakpoint | Native DOM at 780px | T7 |
| D6 | Lifecycle diagnostics depend on which surface invoked action | Real bridge-driven log and call-site inspection | T2/T4 |
| D7 | "registered" hotkeys can actually be unregistered | `_register_hotkeys` catches failure, reporting reads `.bindings` only | T2/T5 |

The timeout is confirmed reproducible as a consequence of D1 with a shortened
test deadline. Its historical cause remains unconfirmed. Generation-retirement
races are source-supported defects/risk paths, not independently native-reproduced
historical failures; cover them as part of T1 rather than claiming every race ran.

## 6. Unconfirmed observations and remaining risks

- Slow single-open reopen while capture is active was not reproduced in the six
  ordinary cycles. D1 is a concrete matching failure mechanism, not a claim that
  capture is necessary or every instance of the user's symptom has one cause.
- WebEngine profile warning: reported by the user and previous wave; local
  pywebview queues `page.deleteLater()` and immediately exits the event loop.
  This is a credible teardown-order cause, not proven merely by the warning's
  presence. It did not recur in the successful elevated UI probes in this pass.
- Full frozen capture/reopen, crash recovery, abrupt parent death and physical
  hotkeys have not been revalidated here. The frozen self-check is narrower.
- macOS duplicate app, Carbon release behavior and all native macOS assertions
  remain pending; Linux desktop behavior is also not inferred from Windows.
- All measured display coordinates were DPR=1. `_word_rect` currently calls
  `screen_rect` with default scale=1 while QCursor/Qt can be logical and MSS
  physical on Windows. Mixed-DPI correctness must precede timing tuning.
- Lookup preparation had large outliers in this environment (section 13).
  They are not a stable startup SLA or proof of one particular provider bottleneck.
- `LookupProcess._await_reply` has cancellation polling, then an unbounded wait
  after cancellation is forwarded. A live but wedged provider is not covered by
  the 120s startup deadline. Stop can terminate it; do not claim every lookup wait
  is bounded or conflate this with the CC's 900s message.
- A preparation can be in `_start_now` before `_process` is published. Retire
  invalidates generation but cannot synchronously join that not-yet-published
  child. Queued prepare/recovery tasks also need currency rechecking after the
  start lock. T4/T10 must prove Stop/Shutdown cannot later resurrect providers.

## 7. Product behavior and state semantics

The following is the draft implementation contract. Human review of the final
plan must settle the two policy clarifications below; do not silently choose a
different interpretation during implementation.

1. **Start/Stop Capture** owns whether a capture session is requested, using saved
   monitor/scope/region. Stop invalidates work, dismisses the popup and retires
   the heavy child; input shortcuts and shell remain available.
2. **Pause/Continue Hover** is a mute for **Always active** mode, retaining the
   engine and capture-session intent. It does not call the existing `pause()`
   path that retires the engine. While stopped or in Push to Hover mode it is a
   documented no-op; no implicit Start and no hidden persistent mute of push.
3. **Push to Hover** is the default mode. A complete held chord enables the normal
   hover pipeline while capture is started. Release of any required key ends
   that activation, cancels dwell and invalidates in-flight presentation.
   Holding does not bypass dwell/currency, and auto-repeat cannot toggle it.
4. Default launch remains capture stopped. Pressing push while stopped does not
   secretly allocate a capture session; Start/Stop is the explicit global action.
   The UI explains this prerequisite. Starting while a chord is already held
   requires release then a fresh press, avoiding stale activation.
5. Always active remains available, including its existing launch preference;
   Pause/Continue changes a transient mute, not the persisted mode. Switching
   modes clears held state and pending work. No movement listener/dwell/OCR runs
   while stopped or muted. A popup-only exit observer may remain only while an
   existing popup needs it, and must be torn down when the popup closes.
6. The already-visible popup may remain on release if the cursor is on its word
   or moving through the explicit popup corridor. Release disables **new** work;
   geometry observation alone lets the user click/copy the answer without holding
   the chord. Stop/Pause always dismiss. Re-press at the same retained word does
   not recapture. Test this distinction explicitly.

**Policy clarification P1 — explicit Stop versus Always preload:** recommend that
explicit Stop releases providers even with `LookupPreload.ALWAYS`; Always means
eager preparation on launch/Start and residency through hover mute, not automatic
resurrection after Stop. This fulfills the Portuguese distinction that the third
shortcut releases RAM. It differs from today's Always exception in `pause()`.
Retain the user's saved preload value; do not rewrite it to implement Stop.

**Policy clarification P2 — one-shot lookup:** the user requests three shortcuts
and repurposes the current lookup binding into Push to Hover. Preserve the
existing one-shot capture/submit implementation for direct/internal consumers,
but do not add a fourth default shortcut or a competing UI mode. Document the
change to the V1 manual interaction contract before changing DAG-INV-05 wording.
If a separately bindable one-shot action is still required, obtain that product
decision at final-plan review; do not invent it in this wave.

Use the existing app ownership, a small immutable **application snapshot**, and
one derivation function in `runtime_status.py`. Inputs are real readiness,
capture intent, engine state/generation, activation mode, transient held/muted
state, stopping state and actual blocking failure. Publish coherently on the Qt
thread, and give bridge/tray/diagnostics the same snapshot. Do not replace engine
readiness with a guessed sleep duration or treat a resident PID as provider-ready.

Suggested user-facing aggregate labels: Stopped, Preparing, Armed, Running,
Stopping, Error. Armed means session enabled with on-demand engine asleep;
Running means operational engine ready, with detail such as "Hold … to look up"
or "Hover paused". Readiness during first launch takes precedence over Stopped;
after validation completes a dormant session is Stopped. A historical diagnostic
does not permanently force Error. A broken CC connection is displayed as
"Connecting"/"Connection lost", never as a convincing `new` runtime snapshot.

## 8. Ordered implementation tasks

Execute only after macOS evidence and human approval. Order:
**T1 -> T2 -> T3 -> T4 -> T5 -> T6 -> T7 -> T8 -> T9 -> T10 -> T11**.
T7 can be implemented independently after T1 evidence is understood; T8 native
ownership choices depend on the macOS investigation. This is not a request for
per-task reviewers or a second decomposition plan. Consolidate at one handoff.

## 9. Task contracts

All paths below are repository-relative. `app/` abbreviates
`packages/hanly-app/src/hanly_app/`; `engine/` abbreviates
`packages/hanly/src/hanly/`. Existing tests are named explicitly; add cases there
unless the new integration boundary needs its own test.

### T1 — Make disposable Control Center lifecycle generation-safe

- **Current/root cause:** D1 and ownership risks in section 3. Starting the reader
  before the host is valid permits focus to kill the only reply reader. Parent
  manager state is not a process-reaping guarantee.
- **Files/functions:** `app/control_center_process.py` (`show`, `_start`,
  `_read_until_gone`, `_child_gone`, `_retire`, `_run_operation`, `_reserve`,
  `_release`, `_ControlCenterChild.run/_receive_one`);
  `app/control_center_host.py` (`run`, `_subscribe`, `_on_closed`, `show`, `close`);
  `app/process_transport.py` (`stop_process`); shell callback in `application.py`.
- **Approach:** reserve spawn ownership, distinguish starting/ready/closing for
  this disposable UI, and acknowledge actual host readiness. Coalesce focus until
  ready; close requested during startup must prevent an orphan window. Mark
  closing before destroying; reopen requested then waits for retirement and starts
  one fresh generation. Keep reader processing replies while alive; an unexpected
  exception must report a terminal child failure, fail current/future waiters
  promptly and retire that child, not leave a window with a dead bridge.
  Detach only the expected generation and retain the old process handle until
  bounded off-Qt reaping finishes. Scope reservation counters and pending calls
  to generation; reject stale queued mutations before executing them. Already
  committed actions may finish, but cannot publish/release replacement state.
- **Must not change:** capture/lookup residency on UI close; allowlist; IPC model;
  one live usable CC; native Qt ownership; no permanent hidden WebEngine.
- **Tests:** `test_control_center_process.py`, `test_control_center_host.py`,
  `integration/test_control_center_lifecycle.py`: focus-before-create, focus-after-
  close, close-before-ready, repeated simultaneous show, reopen while closing,
  stale EOF/finally after replacement, old operation completion vs new capacity,
  reader fault releases waiters, late state refresh, shutdown during open.
- **Native:** repeated native close/reopen with capture stopped/preparing/ready,
  rapid restore clicks, actual bridge snapshot after every open; inspect descendant
  PIDs after a bounded settle interval, not only `manager.running`.
- **Acceptance/order:** exact double-show reproducer no longer crashes; no fallback
  masquerading as real state; each retired process exits; capture continues; final
  shutdown reaps all owned children. First task, and prerequisite for reliable UI QA.

### T2 — Correlate lifecycle diagnostics and identify timeout boundaries

- **Current:** D6/D7; reader exceptions and child Qt warnings bypass the shell log;
  `CALL_TIMEOUT_SECONDS=900` emits an uncorrelated sentence. Refresh errors are
  swallowed by JS, whose comment assumes a next poll even when no timer is active.
- **Files/functions:** `app/diagnostics.py` (`DiagnosticRecord`, `DiagnosticLog`,
  `install_qt_message_handler`, export helpers), `app/control_center_process.py`
  (call/register/await/reply/reader), `app/lookup_process.py` (state/start/exit/stop),
  `app/application.py`, `app/runtime_trace.py`, CC JS (`refresh`, `invoke`).
- **Approach:** send bounded normalized lifecycle events from children to the one
  parent-owned log sink. Add role, generation, operation/request ID, stage,
  monotonic duration and terminal reason where needed. Child Qt handler forwards
  what it receives; Chromium's own native stderr may bypass it, so do not pretend
  the handler captures everything. Install scoped child/thread failure reporting.
  Track outstanding CC operation metadata and log deadline, child/reader/transport
  state on timeout. Distinguish startup/focus/reply/selection/lookup. UI exposes
  connection failure and a bounded explicit retry; no endless recovery poll.
- **Must not change:** no images, OCR text, credentials, arguments/settings payloads
  or arbitrary paths in lifecycle records; no motion spam, separate file writers,
  global stderr suppression, or automatic timeout inflation. Developer trace stays
  opt-in and can feed summaries into diagnostics, not every hover event.
- **Tests:** `test_diagnostics.py`, process tests, `test_runtime_trace.py`,
  `test_control_center_refresh.py` and JS harness: shortened injected deadlines,
  no-reply versus EOF versus cancelled, bounded/escaped/sanitized events, no
  repeated idle polling, registered=false after backend registration failure.
- **Native:** kill a test-owned CC child/lookup child, inspect one causal record
  chain and actionable UI; console/file/UI correlate by IDs without duplicate spam.
- **Acceptance/order:** a next timeout identifies its boundary and operation;
  closed reader cannot leave calls waiting 15 minutes; missing registration is
  visible. After T1; basic event vocabulary is reused by later tasks.

### T3 — Derive one truthful application snapshot

- **Current:** D2; existing `RuntimeStatus` describes readiness, not all product
  state. Engine callback updates a separate tuple; bridge and tray derive labels
  independently. State sampling can interleave with transitions.
- **Files/functions:** `app/runtime_status.py`, `app/application.py`
  (`_DesktopSession.engine_status`, `_on_engine_state`, `_watch_readiness`,
  `refresh_tray`), `app/control_center.py:get_state`, `app/tray.py`, CC HTML/JS/CSS.
- **Approach:** add the small aggregate derivation described in section 7, keep
  readiness and residency available as component facts, marshal updates to one
  owner, reject stale engine/runtime generations, publish an immutable coherent
  view. Render aggregate label and accessible loading indicator from it. Errors
  use real active failure, not diagnostics count. Resetting an engine on Stop
  cannot advertise a completed stop before child retirement settles.
- **Must not change:** no HTTP route, service registry, provider imports in UI,
  inferred health pings or periodic engine heartbeat to keep idle processes alive.
- **Tests:** `test_runtime_status.py`, `test_application.py`, `test_control_center.py`,
  `test_control_center_refresh.py`: matrix in section 11, startup failure/retry,
  ready-to-error recovery, stale ready after Stop, on-demand Armed, no flicker to
  Running while preparing, reduced-motion behavior.
- **Native:** watch Start with cold providers, retry failure, Stop during preparation,
  reopen while active; tray and CC agree without focus/refresh clicks.
- **Acceptance/order:** no Running claim while required providers load; visible
  error/preparation detail; no inconsistent snapshot. After T2, before action changes.

### T4 — Separate capture session, hover mute, and provider retirement

- **Current:** `DesktopState.PAUSED`, `ManualLookupRuntime.pause()` and
  `_DesktopSession.toggle_capture()` conflate mute and Stop; UI and tray use
  different outer action paths. `LookupEngine.retire()` can block the Qt action
  while joining a child; Stop callbacks measured roughly 0.64–1.04s here.
- **Files/functions:** `app/application.py` (`start/pause/resume`, `toggle_capture`,
  `_start_or_resume`, `_apply_activation`, capture selector suspend/restore),
  `app/desktop_controller.py`, `app/manual_lookup.py` (`start`, `pause`,
  `_apply_preload_change`, idle expiry), `app/lookup_process.py`
  (`prepare`, `_ensure`, `_start_now`, `retire`, recovery), bridge and tray callbacks.
- **Approach:** one application action per Start, Stop, toggle Start/Stop and mute.
  Bridge/tray/hotkeys all delegate to it. Mute invalidates observation/results but
  does not retire/reset residency. Stop invalidates immediately, marks Stopping,
  requests retirement off Qt, retains ownership until joined, then Stopped.
  Apply P1 only after final-plan approval. Under ON_DEMAND, Start arms the session
  and first eligible push/hover wakes providers. Guard queued prepare/recovery
  with activation generation through lock waits and pre-ready ownership, so a
  completed Stop does not spawn a replacement. Log every surface through one action.
- **Must not change:** saved scope/monitor/region/preload; shell shortcut availability;
  bounded latest-wins and final currency; no heavy process per push press/release.
- **Tests:** `test_desktop_controller.py`, `test_manual_lookup.py`,
  `test_application.py`, `test_lookup_process.py`: every preload x Start/Stop/mute,
  Stop during start-lock wait and provider construction, rapid Stop/Start, automatic
  recovery racing Stop, settings/area-selection restore, duplicate action idempotence.
- **Native:** observe PIDs across preload modes; same PID through mute/unmute and
  push/release; new generation only when genuinely waking after Stop. During Stop
  verify CC remains responsive and another process cannot be orphaned.
- **Acceptance/order:** action distinctions in section 10 hold; Stop returns control
  promptly and later confirms retirement; no false RAM-release claim. After T3.

### T5 — Implement real press/release hotkeys and migrate preferences

- **Current:** app registers only LOOKUP and TOGGLE_HOVER. Windows uses
  `pynput.keyboard.GlobalHotKeys`, exposing activation callbacks; Carbon installs
  only `_EVENT_HOT_KEY_PRESSED=5`. Default `HoverActivation.HOTKEY` means off until
  Start/toggle, not held-to-hover. No release edge crosses the service seam.
- **Files/functions:** `app/hotkeys.py` (listener factory, normalization, `register`,
  `rebind`, `_trigger`), `app/hotkeys_darwin.py` (`_install_handler`, `_handle_event`,
  `_callback_for`, rebind/teardown), `app/config.py` (`AppConfig`, `from_dict`,
  migration, `ConfigManager.update`), `app/manual_lookup.py`, `app/application.py`,
  `app/control_center.py`, CC settings HTML/JS.
- **Approach:** normalized down/up activation edges for the hold action, discrete
  edges for toggles. Windows tracks a canonical chord through pynput press/release
  callbacks: one down when complete, one up when any required member releases.
  Filter auto-repeat and stale listener generations. Clear held state on Stop,
  shutdown, unregister, failed/replaced binding, mode change and native session
  interruption. Re-enable at the **current cursor** on a fresh press even without
  a mouse-move event. Reuse hover/capture controller, never a hold-specific OCR loop.
  For macOS investigate Carbon pressed+released events and GetEventKind using the
  installed SDK; prove modifier-first release natively before choosing the seam.
  Do not restore the known crashing pynput macOS keyboard layout path. If Carbon
  cannot meet release semantics, document the smallest native alternative and its
  permission consequence in section 4 before marking FINAL.
- **Bindings/migration:** keep legacy `hotkey` chord for Push to Hover and
  `hover_hotkey` for Pause/Continue; migrate `hover_activation=hotkey` and missing
  mode to explicit `push_to_hover`, preserve `always_active`. Add a Start/Stop
  binding, proposed Ctrl+Shift+F10. If it conflicts with an existing user chord,
  choose the first supported free candidate F10/F11/F12 with those modifiers and
  report the migration; if none is available, leave the new action unbound and
  show setup required rather than resetting all preferences. Preserve capture,
  dwell and preload preferences. Migration is idempotent and only saves via the
  usual config transaction. Validate all three together; rollback registrations
  and persisted config on failure. Report actual registration, including backend
  errors; do not imply pynput reserves/excludes another application's shortcut.
- **Must not change:** no hold-as-toggle, polling keyboard on every frame, repeated
  registration per press, implicit Start from push, or fourth default shortcut.
- **Tests:** `test_hotkeys.py`, `test_hotkeys_darwin.py`, `test_app_config.py`,
  `test_manual_lookup.py`, `test_application.py`, CC JS harness: repeat, arbitrary
  key release order, stationary cursor press, chord already held on Start, stale
  callbacks after rebind, two modifiers held on both sides, conflict/rollback,
  missing/legacy/explicit settings and persistent migration notices.
- **Native:** physical keys on Windows and macOS, other app focused, Korean/Latin
  layouts, reserved chord, no permissions, focus/lock/sleep cases; separately
  source and frozen. Synthetic key success is not proof of Carbon physical delivery.
- **Acceptance/order:** three literal names/functions match section 10; no OCR
  while push released; resume is warm after mute; global Start/Stop works with CC
  closed. After T4 and macOS backend evidence.

### T6 — Immediate true exit with a narrow popup-transfer exception

- **Current:** D4; 4px margin and unconditional 120ms grace; no cached-geometry
  issue requires Kiwi. Returning inside can cancel grace but not safely share its
  single timer with dwell. Coordinate-scale correctness is only proven at DPR=1.
- **Files/functions:** `app/hover_lookup.py` (`_on_position`, `_leave_retained_target`,
  `_arm_grace`, `_grace_expired`, `_cancel_grace`, retention/invalidation),
  `app/hover_target.py`, `app/qt_hover_scheduler.py`,
  `app/manual_lookup.py:create_qt_manual_lookup/_word_rect`, popup geometry seam.
- **Approach:** separate independently cancellable dwell and exit/transfer timers.
  On movement inside retained word or popup, preserve and do no capture. Outside,
  invalidate old request currency immediately. If movement is away from the popup,
  clear in that UI callback with **no grace/dwell wait**. Allow only a bounded
  transfer corridor from the last protected word point to the popup's facing edge,
  continuing toward it; use the existing 120ms only as an initial transfer cap,
  not a new all-direction delay. Leaving the corridor, reversing away or expiration
  dismisses. Do not use a rectangular hull covering neighboring words. While in
  the corridor do not run replacement capture against the popup gap. Entering
  popup cancels transfer; leaving popup to unrelated content dismisses immediately.
  Keep the 4px word margin until mixed-DPI evidence supports changing it.
- **Must not change:** clickable/selectable popup, micro-motion stability, old timer
  cannot dismiss a new answer, no OCR to detect exit. Proposed corridor geometry
  must be human/native checked; do not advertise zero OS/compositor latency.
- **Tests:** `test_hover_target.py`, `test_hover_lookup.py`,
  `test_qt_hover_scheduler.py`, `test_hover_lookup_e2e.py`: **real Qt timers** for
  simultaneous dwell+exit, away/toward/reverse/reenter, diagonally placed popup,
  next word in gap, stale expiry/new target, release while popup retained,
  negative monitor origins and scale conversion. Assert provider/capture counts.
- **Native:** event-to-clear and clear-to-visible-disappearance observations,
  micro-movement and real popup clicks at all supported DPI. Measure transfer
  success and failure, not just a synthetic timer unit test.
- **Acceptance/order:** true exit calls dismiss in first processed exit callback;
  retained micro-motion runs no capture; popup remains reachable. After T5 so
  held/released geometry behavior is tested in the final model.

### T7 — Functional Control Center layout repair

- **Current:** D5, section minimums overflow above 760px; no vertical collision
  measured. Alert placement is intentional but contributes variable height.
- **Files/functions:** CC `control_center.css`, `index.html`, host `_create_window`;
  browser/native layout test using actual `control_center_document()`.
- **Approach:** stack section introduction/controls or entire columns at a width
  derived from their actual minimum requirements; allow action rows to wrap and
  grid children to shrink. Keep error/readiness notices in normal flow. Test
  available CSS pixels, not only outer window dimensions. Retain useful minimum
  window size; increasing it alone is insufficient for zoom/scaled displays.
- **Must not change:** no redesign, rebranding, new typography system, hidden
  controls or clipped overflow to make a screenshot look clean.
- **Tests/native:** `test_control_center.py`/refresh harness for content plus real
  rendered bounding boxes at 760, 780, 900, 1080px and height 560/760; 100%, 125%,
  150%, 200% scaling/zoom; alert, permission panel, preparation, long log line,
  changed shortcut and region controls. The JS fake DOM cannot prove geometry.
- **Acceptance/order:** all controls reachable and readable, no horizontal overflow
  or overlap within supported widths/scales. After T1; final validation after T3/T5.

### T8 — Native application identity and WebEngine teardown

- **Current:** macOS duplicate entry unassigned; profile lifetime warning reported;
  clean Windows UI reproduces DirectComposition warning without functional failure.
- **Files/functions:** `app/control_center_host.py`, `app/control_center_process.py`,
  `app/qt_bootstrap.py`, `app/popup_darwin.py`, child entry points,
  `packaging/runtime_hook.py`, `packaging/hanly-desktop.spec`; relevant tests in
  `test_control_center_host.py`, `test_packaging.py` and native integration tests.
- **Approach:** after macOS identifies the guilty role, assign only that role the
  appropriate native application visibility/activation behavior. Preserve exactly
  one user-facing Hanly application and real CC focus/menu behavior. For Qt,
  prove page destruction before its non-default profile; prefer a supported
  upstream fix/version or a small child-local host compatibility adapter with
  explicit ownership and native deferred-delete completion. Verify before adding
  any pywebview-private compatibility code. The parent's bounded reap is a fallback,
  not a replacement for orderly native cleanup.
- **Must not change:** no permanent hidden CC, global stderr silence, blanket
  disable-GPU flags, forced process exits to conceal teardown errors, or hiding
  the legitimate macOS app. No dependency upgrade solely on binding patch numbers.
- **Tests/native:** object-lifetime ordering, host ready/closing focus race,
  app role vs spawn recursion; source/frozen macOS Dock and menu ownership;
  Windows render/close and child descendant exit. Non-default Qt profile must
  outlive its pages, per [Qt's page contract](https://doc.qt.io/qt-6/qwebenginepage.html).
- **Acceptance/order:** one visible app on macOS, children invisible as independent
  apps; no reproducible app-owned teardown warning/orphan. If a remaining upstream
  platform capability warning is demonstrably harmless, record its exact versions
  and trigger rather than claiming a warning-free runtime. Requires section 4.

### T9 — Dependency hygiene with actual-use evidence

- **Current:** direct package metadata contains no Paddle dependency; local `.venv`
  still has paddleocr 3.7.0 and paddlepaddle 3.3.1. Hidden imports are mostly dynamic
  Qt/input/provider imports and cannot be judged by grep alone. See section 14.
- **Files:** both package `pyproject.toml`, root `pyproject.toml`,
  `packaging/hanly-desktop.spec`, `packaging/release-constraints.txt`, runtime hook,
  `tools/build_package.py`, `tools/smoke_packaged_runtime.py`, packaging README.
- **Approach:** rebuild an isolated full repository runtime using documented
  installation order and constraints; compare metadata/import origins and frozen
  inventory. Remove only a direct declaration/hidden import demonstrated obsolete
  by that build. Keep local stale installations separate from repository changes.
  Prefer recreating a dev venv over guessing which Paddle transitives can be
  uninstalled without affecting another dependency.
- **Must not change:** no blanket uninstall of shared transitives, removal of
  pythonnet/PyObjC/bottle just because Hanly does not directly import them, or
  accidental promotion of optional engine dependencies to mandatory ones.
- **Tests/native:** packaging and package-boundary tests, clean `pip check`,
  independently install engine base and app base, full runtime smoke, frozen worker
  and UI self-check outside checkout; test updated hold backends' hidden imports.
- **Acceptance/order:** specific justified removal list or explicitly empty list;
  all retained lazy/native dependencies accounted for. No requirement to invent a
  removal. After T5/T8 determine the final native dependency needs.

### T10 — Lifecycle regression property and measured latency checks

- **Current:** existing integration tests prove two simple manager cycles or two
  lookup wakes, but not title-bar close with active capture, true child reaping,
  or shared Qt timers. No progressive leak established.
- **Files:** `tests/integration/test_control_center_lifecycle.py`,
  `tests/integration/test_lookup_process_spawn.py`, `test_lookup_process.py`,
  `test_application.py`, Qt hover tests; developer-only instrumentation in
  `benchmarks/dev/` if durable measurement helpers are needed.
- **Approach:** one bounded native subprocess driver using the real shell/bridge,
  fixture, process identities and finally cleanup. Repeat at least ten complete
  lifecycle cycles in native validation; keep ordinary CI smaller/deterministic.
  Cover Start, mute, push, release, CC close/reopen, Stop, error recovery and Quit.
  Preserve handles/role+generation+PID until exit; record descendants including
  QtWebEngineProcess. Do not infer orphan-freedom from manager fields or RSS.
  Give hung probes a whole-process deadline and test-owned descendant cleanup.
- **Must not change:** no exact RAM threshold, no leaked production instrumentation,
  no synthetic fixture benchmark advertised as human lookup SLA.
- **Tests/native:** a pre-ready killed child, stopped while loading, stalled lookup,
  exhausted recovery budget, abrupt parent exit, slow reply from old generation,
  final quit; source/frozen Windows/macOS and X11 native lane. Resource tracker
  may survive while POSIX shell lives but must exit with its owner.
- **Acceptance/order:** at most one eligible child of each role; each Stop/CC close
  eventually reaps its owned child, shell persists, Quit leaves no descendants;
  no unsolicited wake after Stop. Repeat warm timings without accuracy loss.
  After T1–T9; no new OCR tuning is authorized by current measurements.

### T11 — Documentation and one implementation handoff

- **Current:** user-facing hotkey names and architecture narrative are stale for
  the requested model; previous-wave ADR reconciliation is still pending.
- **Files:** this plan, `docs/CODE-MAP.md`, user README/settings documentation,
  proposed architecture/ADR updates described in section 17; one review handoff
  under `docs/execution/review-handoffs/` when later implementation completes.
- **Approach:** document final three-action/preload/status matrices and migration;
  synchronize approved architecture text/visuals without renumbering invariants.
  Handoff distinguishes automated/native evidence and remaining platform risks.
- **Must not change:** no invented approval, merge, release, Linear state change or
  second execution plan. Architecture proposals stay proposed until approved.
- **Tests/validation:** file links, identifiers and Markdown/HTML invariant mapping;
  read settings help against actual implemented behavior and native acceptance.
- **Acceptance/order:** Opus leaves one coherent handoff and stops per `05`; human
  retains commit/merge authority. Last task.

## 10. Hotkey behavior matrix (target)

Proposed defaults: Pause/Continue Ctrl+Shift+F9; Push Ctrl+Shift+Space;
Start/Stop Ctrl+Shift+F10 (migrate conflicts as in T5).

| Context | Pause / Continue | Push down / up | Start / Stop |
|---|---|---|---|
| Startup not ready or failed | No lifecycle change; actionable status | No lookup; no held latch retained | Start refuses with reason or existing retry path; no phantom Running |
| Capture stopped | No-op | No-op; tell user Start is required | Start with saved capture preferences |
| Started, Push mode, engine sleeping | No-op | Down arms dwell; eligible lookup wakes engine; up cancels new work | Stop; remain sleeping after completion |
| Started, Push mode, engine ready | No-op | Down enables hover; up disables new work; same child stays resident | Stop invalidates and retires |
| Started, Always active, unmuted | Mute and dismiss; engine retained | No additional activation; no one-shot side effect | Stop invalidates and retires |
| Started, Always active, muted | Continue, same warm engine | Does not bypass mute | Stop invalidates and retires |
| Preparing after Start | Mute only relevant for Always; no retirement | Release prevents late popup even if preparation completes | Stop cancels activation; no later resurrection |
| CC closed | Same global actions; CC need not open | Same | Same; does not launch an extra user-facing app |
| Rebind/mode change/session interruption | Apply atomically, clear transient hold | Old key-up/down cannot reactivate | UI/tray/shortcut share the same transition |

## 11. Runtime/status transition matrix (target)

| Event / facts | Aggregate label | Required detail / behavior |
|---|---|---|
| Initial resources/session constructing | Preparing | Actual preparation stage; Start unavailable |
| Session ready, capture off | Stopped | Engine may be sleeping or eagerly resident; separate detail |
| Start + WHEN_CAPTURE_STARTS / ALWAYS, not ready yet | Preparing | Spinner/loading text; Stop available |
| Start + ON_DEMAND, engine asleep | Armed | Explain wake on first eligible lookup, no false ready claim |
| Capture enabled, engine ready, Push released | Running | "Hold [binding] to look up"; no background OCR |
| Capture enabled, engine ready, Always muted | Running | "Hover paused"; resident engine unchanged |
| Eligible lookup wakes engine | Preparing -> Running | Release/Stop still prevents stale presentation |
| Active engine failure/recovery | Error -> Preparing -> Running, or Error | Bounded recovery; actual failure and role |
| Stop | Stopping -> Stopped | Input/currency off immediately; final state after retirement |
| CC close/reopen | Unchanged | UI connection status is not runtime status |
| New resource/config attempt replaces old one | Current attempt only | Old ready/error callback cannot overwrite current snapshot |
| Quit | Stopping, then process exit | No new work, all children reaped |

Always-preload behavior through explicit Stop is P1, not today's implementation.
Snapshot derivation must also surface fatal observer/capture/hotkey failures as
the affected capability/reason rather than infer health solely from engine.ready.
Missing one shortcut does not turn a functioning UI-based capture into a total
application failure; identify unavailable capability and keep usable actions.

## 12. Logging and timeout requirements

| Boundary | Required low-frequency events / fields |
|---|---|
| CC process | spawn/host-ready/closing/EOF/reaped/fault; role, generation, PID, exit code, reason |
| CC operation | on failure/slow/deadline: operation name, ID, generation, age, reader/transport liveness; no arguments |
| Capture and hover actions | accepted/rejected Start/Stop/mute/mode change, source UI/tray/hotkey, reason; no cursor stream |
| Lookup | preparing/ready/error/recovery/retire/reaped, generation and recovery allowance; slow stage summary only |
| Hotkey backend | registration/rebind/rollback result and unavailable action; distinguish configured from active |
| Readiness | changed aggregate state + blocking stage/capability, no per-poll duplicates |
| Native errors | scoped Qt/child failure forwarding and version/OS context; never blanket stderr filtering |

The exact sentence `Hanly did not answer in time.` occurs only in
`_ControlCenterChild._await_reply`. Any allowlisted operation can reach it.
`get_state` and `get_logs` run at initial page ready; action errors are displayed
at `#action-error`, between buttons and capture fields. Other relevant waits:
CC close 10s; application Qt dispatch 60s; user capture selection 600s; lookup
startup 120s; lookup Stop 10s plus terminate/kill waits. Lookup replies have no
absolute computation deadline. Preserve the distinction; do not fix a dead reader
by extending the CC timeout. Add per-operation deadline classification only with
actual ownership/cancellation semantics, especially for interactive selection.

The native Windows message is an optional DirectComposition capability check.
Current upstream Chromium returns false when querying Device4 fails and now logs
that case as a warning; this supports a fallback-capability interpretation, not
a claim that our bundled Chromium has identical code. See
[Chromium DirectComposition source](https://chromium.googlesource.com/chromium/src/+/refs/heads/main/ui/gl/direct_composition_support.cc).
It occurred on Windows 10 build 19045 with functioning UI in both repository and
clean UI environments. The 6.11-based existing frozen UI emitted no captured
warning. Therefore prioritize reader/ownership bugs; do not prescribe GPU disabling,
an OS upgrade or a global warning filter. A future dependency change needs its
own same-OS render/teardown comparison.

## 13. Performance measurements and justified work

Real `LookupEngine` child, local full KRDICT, existing EasyOCR weights, Korean
reading fixture `tests/hanly_fixtures/assets/korean_reading_roi.png`.
Twenty warm uncached samples after one initial request; changed one background
corner pixel per sample to bypass caches without changing glyphs. All 21 returned
SUCCESS. Ten identical requests separately measured cache hits. No screen text
was recorded. Trace overhead is included. These are fixture results, not a corpus
accuracy result or end-to-end human hover timing.

| Stage, repeat without lifecycle workload | Warm median | Notes |
|---|---|---|
| Parent synchronous engine request | 85.058 ms | p95 88.069ms, max 89.905ms, 20 samples |
| Child total pipeline | 84.689 ms | Matched per request |
| OCR | 83.948 ms | Dominates; contains input preparation/cache wrapper and inference |
| Word selection | 0.043 ms | Existing trace `token_selection` |
| Kiwi | 0.163 ms | Existing morphology trace |
| KRDICT | 0.246 ms | Real dictionary |
| Parent total minus child pipeline | 0.330 ms | Median matched difference; includes pipe/scheduling/serialization, not pure IPC |
| Identical-request cache hit | 0.286 ms | Max 0.372ms |

Separate native Qt/capture probe: displayed the fixture, 21 captures of a 200x100
ROI, then 21 queued Qt dispatches and presentations of a fixture result. This
isolates seams; **do not sum these independent medians into a measured SLA**.

| Seam | First sample | Warm median / max |
|---|---|---|
| CaptureService incl monitor/ROI/normalize | 59.919ms | 6.742 / 11.509ms |
| MSS grab + RGB conversion | 56.582ms | 6.663 / 11.424ms |
| Remaining capture/ROI preparation | 3.337ms | 0.084 / 0.139ms |
| Lookup message pickle encode+decode, same process | 0.177ms | 0.045 / 0.128ms; not a transport measurement |
| Queued Qt callback dispatch | 73.990ms | 0.048 / 0.130ms |
| Qt popup open call | 950.825ms | 1.026 / 1.765ms; API timing, not compositor-visible pixels |

Cold data is variable: first standalone attach 8.258s; a repeat took 52.681s.
First uncached inference in the latter run took 272.330ms. Normal full-session
Start cycles took 7.84–8.26s in the first run, then 25.35/9.02/8.54s in the second;
its initial resource validation also took 14.788s. These outliers were not isolated
to a root cause; do not turn them into an optimization prescription. First popup
call's ~951ms also needs separate cold profiling before deciding to prewarm UI.
The first warm run, concurrent with other probes, had median 77.692ms and max
112.913ms; the isolated repeat above is the primary warm table.

Exit measurement is a failed timer property: **no dismissal by 359.65ms** with
the production Qt scheduler, not a measured 120ms exit. A 120ms constant is not
an observed user latency. T6 provides zero deliberate delay for true exit and
measures actual native dispatch/render afterwards.

**Authorized optimization recommendation:** fix timer ownership and geometry
exit; prevent unwanted hover work through real hold activation; make Stop
retirement nonblocking on Qt. Keep dwell default 80ms and current OCR/provider
settings. OCR dominates warm uncached work; removing small IPC/Kiwi costs would
not deliver instant lookup. No model/preprocessing tuning justified by this one
fixture. Further cold or accuracy/performance work is deferred until a repeatable
isolated stage trace and representative corpus support it.

## 14. Dependency audit results

| Dependency / declaration | Evidence / disposition |
|---|---|
| `hanly` base | No mandatory dependencies; preserve independent installation |
| `hanly[easyocr]`: numpy, easyocr | Direct adapter data conversion and lazy Reader; retain |
| `hanly[kiwi]`: kiwipiepy | Lazy concrete morphology, native `_kiwipiepy` and model package; retain |
| App base: hanly, certifi, zstandard | Engine contracts, TLS resource/app updates, compressed resources; retain |
| App runtime: mss, pynput | Capture; Windows/X11 keyboard and mouse, macOS mouse still used; retain |
| PyQt6, pywebview[qt6], pystray | Popup/shell/UI/tray, lazy native backends; retain |
| QtPy, PyQt6-WebEngine, pythonnet, bottle, proxy_tools; macOS PyObjC packages | pywebview's own metadata/runtime dependencies, not obsolete Hanly declarations |
| torch/torchvision, opencv-python-headless, scipy, scikit-image, Pillow, YAML, Shapely, pyclipper, ninja, python-bidi | EasyOCR requirements; no removal based on missing Hanly imports |
| Root dev dependencies | build/release tooling, pytest/ruff/mypy, fixtures and workflow YAML tests; preserve runtime/dev separation |
| psutil | Developer telemetry already degrades if absent; not app runtime requirement |
| Spec hidden imports | Qt dynamically selected; pynput/pystray platform modules; `_kiwipiepy` native; keep and recheck after hotkey work |
| torchvision full collection | Prior measured attempt lost native modules for negligible size gain; do not repeat generic pruning |
| Paddle | No production dependency/import/hidden import found; packaging test explicitly excludes Paddle. `.venv` still has paddleocr 3.7.0, paddlepaddle 3.3.1 and related ecosystem |
| Stale local runtime manifest | Ignored `resources/dev/runtime-local.json` still has `ocr_backend: easyocr`; not a shipped dependency or reason to restore selector |

**Repository removal list: empty on current evidence.** **Environment-only
cleanup candidates: paddleocr and paddlepaddle**, followed by an evaluated
dependency-graph cleanup or a fresh venv. Do not remove Paddle transitives en masse:
metadata can include optional extra requirements and packages such as safetensors
may be shared. No package was uninstalled or production dependency changed here.

Clean UI-only verification proves Paddle/OCR/tray are unnecessary to construct
the CC host, not that they should be removed from the whole desktop. A clean
full runtime build and frozen worker smoke remain T9 validation; the existing
frozen artifact and current `pip check` do not substitute for them.

## 15. Automated regression plan and replay recipes

Fast unit/seam tests cover normalized action/state/generation policy. Real Qt
timer tests must supplement fake schedulers. Native subprocess tests prove
process/window properties; optional-heavy tests skip with an explicit reason
when no desktop/models/dictionary exists. Run relevant focused tests during
implementation, then repository gates once at the bundle boundary:

```powershell
python -m pytest
python -m ruff check packages packaging tests tools benchmarks
python -m mypy packages packaging tests tools benchmarks
```

No full suite was run in this planning pass; the 94 focused/integration successes
are the executed baseline, not a new repository-wide green claim.

### Replay A: early-focus seam (no GUI required)

Run with repository interpreter. Current code prints the same exception; the
regression test should instead assert no reader crash and deferred focus.

```python
from hanly_app.control_center_process import _ControlCenterChild, ControlCenterOptions

class Wire:
    def receive(self):
        return {"kind": "focus"}

child = _ControlCenterChild(Wire(), ControlCenterOptions())
try:
    child._read_until_gone()
except Exception as error:
    print(type(error).__name__, str(error))
# ControlCenterUnavailable the Control Center window is not available
```

For the native replay, adapt the existing integration test's `_CHILD_PROGRAM`:
call `control.show()` twice immediately at each spawn, instrument a bridge that
returns a known `running` state, and close the native window through the child's
`ControlCenterHost.run(on_started=...)` after document load. Assert the page
reaches the parent and renders that value; current code remains on fallback `new`.
Use an injected short call timeout **only in the probe/test** to assert the
timeout chain without waiting 15 minutes. Give the outer subprocess a deadline
and explicitly reap its descendants. Keep ordinary close and racing-close cases
separate so a test cannot pass by always waiting out the problematic window.

### Replay B: scheduler exclusivity

Use the existing `_Capture`, `_ListenerFactory`, `_Worker` doubles from
`tests/test_hover_lookup.py`, but replace `_Scheduler` with the actual
`QtHoverScheduler`. Create a QCoreApplication, release the worker's wait event,
start `HoverLookupRuntime(delay_ms=80, scheduler=QtHoverScheduler())`, wait for
controller readiness, retain `RetainedTarget(1, ScreenRect(100,100,40,20),
ScreenRect(150,150,100,100))`, and deliver `Point(20,20)`. End the Qt loop after
350ms. Current result: no invalidation callback, retained target still present,
one capture. Desired T6 result: clear at true exit, independent of next dwell.
This requires an integration assertion, not just changing the grace constant.

### Replay C: warm profile

Use the existing `integration/test_lookup_process_spawn.py` child program and
its dictionary/models/fixture selection, with `LookupSettings(trace=True)` and
`LookupEngine(on_trace=...)`. Time `attach` separately. Send one initial and 20
warm requests, adjusting only a background corner byte to avoid cache hits;
then 10 identical requests. Group `lookup_stage_completed` by request ID and
stage. Report status, timings, cache provenance, ROI dimensions, versions and
sample count; do not retain text/image trace fields. Native capture/dispatch/
presentation and actual pixels-on-screen require separate measurement.

## 16. Native validation matrix

| Platform/build | This pass | Before implementation can be called validated |
|---|---|---|
| Windows source | Real lookup spawn; three simple CC cycles; six full-app capture cycles; rapid-focus failure; real Qt timer failure; layout DPR=1; warm stage profile; corrected final Quit with no active multiprocessing children | Physical hotkeys, ten-cycle descendant accounting including WebEngine, crash/parent death/Stop-during-load, fractional/mixed DPI, popup corridor and revised behavior |
| Windows clean UI source | Fresh UI deps, self-check passes, DirectComposition warning persists | Clean **full** runtime and complete regression smoke, not just UI |
| Windows frozen (existing artifact) | UI self-check and bridge pass outside sandbox; no captured stderr | Build from final code in constrained environment; worker+UI smoke; same full native lifecycle, actions, DPI, recovery and update/shutdown ownership |
| macOS source | Pending | PID/Dock cause, Carbon physical edges, source background/permissions, all relevant lifecycle/geometry cases |
| macOS frozen | Pending | Finder/open app identity, one Dock entry, actual hold/release, helpers/background, sign/inventory and full lifecycle |
| Linux CI | Not run here | Portable tests, headless Qt timer tests; Xvfb UI smoke if configured; skips must state absent desktop/models |
| Linux native/frozen | Pending | X11 physical hotkeys, capture/retention, tray restore, children/parent-death; document Wayland limitations instead of promising unsupported global input |

Maintain one row per actual environment and version; never label source-only
evidence as frozen, or Windows/macOS as Linux. Physical human validation may be
recorded by the user separately; missing evidence must remain visible.

## 17. Documentation and architecture changes

The next finalization must explicitly resolve P1 (Stop vs Always) and P2 (manual
one-shot vs push), then propose the small ADR/doc patch that reconciles the
previous runtime split with current resource-readiness/residency and new activation
semantics. The authoritative source is still architecture Markdown; diagrams are
companions. Preserve invariant IDs and their 1:1 order if approved text changes.
Do not silently change DAG-INV-05, RF/CA boundaries, or treat this draft as that
approval. No structural engine change is needed for the proposed fixes.

Update user-facing names, default behavior, migration notice, permission/refusal
help, preload description, and `docs/CODE-MAP.md` after implementation. The
documentation must distinguish mute's warm RAM retention from explicit Stop.

## 18. Final execution checklist for Claude Opus

- [ ] Read this plan, `CODE-MAP`, architecture and `05`; verify HEAD and local changes.
- [ ] Complete only missing macOS-native evidence in section 4; do not redo Windows
  investigation without changed code or a contradictory result.
- [ ] Resolve P1/P2 in human final-plan review; establish correct macOS hold backend,
  guilty Dock PID and role-specific repair. Record any remaining Windows/native
  validation gaps without calling them proven.
- [ ] Update this same file to **FINAL / READY FOR EXECUTION** only when the macOS
  investigation and product-contract decisions make the tasks directly executable.
- [ ] Obtain the user's implementation authorization; this planning request is not it.
- [ ] Execute T1–T11 with focused checks and one consolidated handoff; no generic
  per-task reviewer chain or duplicate plan.
- [ ] Preserve provider/currency/ownership invariants; compare successful Korean
  fixture outcomes alongside performance, not latency alone.
- [ ] Run bundle mechanical gates and native matrix appropriate to the changed code.
- [ ] Record unreproduced observations, deferred work with triggers, and upstream
  warnings honestly; no invented leak fix or unsupported clean-runtime claim.
- [ ] Leave one Review Handoff and stop. No commit, push, merge, tag, release or
  Linear changes without the appropriate separate human authorization.

**Windows phase result:** exact focus reader failure reproduced natively; timeout
mechanism reproduced with injected deadline; misleading Running state and Qt timer
conflict confirmed; layout overflow measured; ordinary capture/reopen and clean
Quit succeeded; warm OCR dominates. macOS ownership/release semantics, physical
keys, mixed DPI, complete frozen lifecycle and full clean dependency build remain
explicitly pending. **DRAFT, not FINAL.**
