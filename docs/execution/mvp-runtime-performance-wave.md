# MVP runtime / performance wave

## Authority and outcome

One branch, `perf/mvp-runtime-lifecycle`, based on integrated `main` at
`f508710`. The user explicitly authorizes architecture decisions within this
scope, Astra integration review, Claude implementation, logical commits and a
final feature-branch push. No Linear writes, merge, tags, force-push or release.
This authorization supersedes the usual separate implementation/review stop
for this wave. The live record is
`checkpoints/mvp-runtime-performance-wave.md`; the final handoff belongs in
`review-handoffs/mvp-runtime-performance-wave.md`.

Completion requires a working source and frozen macOS application, measured
before/after behavior, functional settings/logs, and explicit pending native
Windows/Linux scenarios. A green source suite alone is insufficient.

## Current implementation and evidence

- `cli.main` is the only entry point; `packaging/entrypoint.py` calls it.
  `packaging/runtime_hook.py` imports EasyOCR unconditionally, before CLI.
- `qt_bootstrap.ensure_qt_application` imports OCR, prepares WebEngine, then
  creates QApplication. `application.DesktopApplication.run` delegates the
  event loop to `ControlCenterHost.run`; pywebview starts that loop.
- `ControlCenterHost._on_closing` hides a restorable window; destroying it
  ends the current app loop. Native macOS probing found WebEngine resources
  still charged to the host after the window's loop returned.
- `_DesktopSession.activate` creates `ManualLookupRuntime`, then calls
  `prepare`, starting `LookupController` / `JobExecutor` and warming all
  providers. Readiness currently implies resident providers even before capture.
- Adapter modules themselves import cheaply: the application import graph
  loaded no `torch`, `easyocr`, or `kiwipiepy`. Native allocations happen in
  bootstrap and provider factories. Preserve lazy engine adapters.
- `JobExecutor` already bounds work to running plus latest pending.
  `LookupController._deliver_if_current` checks currency on the dispatch
  thread. `LookupRequest` includes a threading.Event and cannot be sent
  unchanged through a spawn boundary.
- `ManualLookupRuntime.start` currently couples hotkey registration, provider
  start and hover start. `pause` invalidates lookup and stops hover but leaves
  providers resident. Hotkeys are not registered during initial preparation.
- `HoverLookupRuntime._on_position` clears the popup on every movement and
  waits for provider readiness before accepting dwell. This needs a distinct
  on-demand path; waiting for an unstarted worker would otherwise deadlock UX.
- `ControlCenterBridge._update_config` persists before live application.
  A native rebind failure can therefore leave stored and registered settings
  different. Fix the transaction, not just the settings labels.
- `DiagnosticLog` already supplies a 500-record tail and rotating files
  (512 KiB, three backups). Extend it rather than introducing a second logger.
- Updater transactions own the download, staged build, previous installation
  and acknowledgement. Native scripts own the swap after shell exit. Never
  reap an unresolved rollback's only usable backup.

## Target ownership and process boundary

The persistent parent owns Qt Widgets, tray, global hotkeys, capture/permissions,
hover state, popup, settings, resources/update orchestration, and the canonical
diagnostic log. It owns the sole parent QApplication loop with
`setQuitOnLastWindowClosed(False)`. It imports neither WebEngine nor heavy
providers. Resource validation remains off the UI thread.

Two optional children have separate lifetimes:

1. Control Center process: pywebview, QtWebEngine, window and a narrow proxy
   for the existing bridge. X destroys the window and exits this process.
   Opening again creates a fresh process and fetches parent state. Neither X
   nor an unexpected child exit pauses capture or exits the parent.
2. One lookup process: EasyOCRProvider, KiwiProvider, KRDICTProvider and the
   existing LookupWorker/pipeline. Provider construction, lookup and close
   occur on its processing thread, preserving SQLite ownership. Worker code
   depends on normalized provider interfaces; no ONNX/backend selector.

Use explicit `multiprocessing.get_context("spawn")` and inherited `Pipe`
connections for these trusted parent/child pairs. No public listening port,
temporary screenshot files, arbitrary method dispatch or subprocess shell
command strings. Keep the small process launch helper in `hanly_app`, with
top-level child target functions importable under spawn. Do not pickle a
HanlyRuntime with manager/locks/factories or a LookupRequest with Event.

`cli.main` must invoke `multiprocessing.freeze_support()` before desktop
startup work. The runtime hook must stop preloading OCR in every process.
Child targets explicitly initialize only their role. Check actual PyInstaller
spawn dispatch early in task 2, before building settings on an unproven base.
The same executable remains the sole user entry point. A child must not run
first-run provisioning, acknowledge an update, register hotkeys, or open an
extra runtime shell.

### Lookup transport

New `lookup_process.py` owns worker lifecycle and pipe transport. Preserve the
existing controller's request IDs and final delivery check; adapt the existing
bounded executor to call a lightweight process proxy instead of native providers.
Pass validated resource paths and explicit provider configuration as a small
spawn value. A lookup message carries generation, request ID, hover ID,
ROIImage bytes/dimensions/format and local target; reconstruct local cancellation
state in the child. Only normalized result values and bounded diagnostic records
return. Convert external exception objects to stable error type/message values.

One reader owns each receive direction; serialize sends. A reader must continue
receiving cancellation/EOF while provider code runs. Never queue unlimited image
messages in the pipe: the parent retains one latest pending job and sends the
next only after the running job completes or its process exits. A supersession
can cancel between stages; currency on the parent UI thread remains decisive.
Generation changes on process retirement invalidate responses, readiness and
error callbacks from the prior child, including after a new child is ready.

EOF means the other owner is gone. Children stop on EOF; the parent detects exit
even with no pending lookup. Normal stop requests cancellation/close, then uses a
bounded join and terminate/kill fallback. All readers/waiters are released. No
join on a UI thread that the reader needs to dispatch into. Explicit stop is
distinguished from crash and never causes automatic recovery.

### Control Center transport

New `control_center_process.py` keeps a fixed allowlist matching the bridge's
public UI operations, request IDs, replies and lifecycle messages. The canonical
ControlCenterBridge stays in the parent, keeping configuration, permissions,
capture selection, update and Quit ownership unchanged. Its operations marshal
to Qt where required. Blocking bridge responses wait in the child/transport
thread, never the parent's UI loop. Cancel pending RPCs with a useful error on
either process closing; bound payloads and outstanding requests.

Parent state changes notify a visible UI; opening always fetches a snapshot.
Use existing bounded pending-operation refresh where useful. Logs can refresh
on opening/explicit refresh or a visible-tab timer; no permanent 100 ms loop.
Repeated open requests focus the existing child instead of spawning duplicates.
If tray startup fails, keep a reachable Control Center with an explicit error;
do not leave an inaccessible background process.

## Lifecycle and preferences

Separate shell/resource readiness from engine state. Engine state is exactly
Sleeping, Preparing, Ready or Error, plus a generation and last failure. Runtime
and worker state have one authoritative owner each. UI wording must distinguish
capture requested/preparing from capture ready. A stopped engine can accept a
new request; an unrecoverable shell/resource failure cannot.

| Preference | Persisted value | Default |
|---|---|---|
| Lookup engine preload | `when_capture_starts`, `always`, `on_demand` | `when_capture_starts` |
| Hover activation | `hotkey`, `always_active` | `hotkey` |
| Manual lookup hotkey | existing `hotkey` field | preserve `ctrl+shift+space` |
| Hover toggle hotkey | new `hover_hotkey` | `ctrl+shift+f9` |

Add typed enums/fields to `config.py`; missing fields migrate to these defaults
and existing hotkey/dwell/capture selections are preserved. Never reinterpret the
old manual hotkey as a toggle. Validate supported key names through each native
backend and reject canonical duplicates across actions. An existing manual
binding equal to the new toggle default needs a nonconflicting migration default
selected from a short deterministic fallback list, with a visible diagnostic.

Registration starts with the shell, independent of capture or engine residency.
Manual lookup checks Screen Recording on macOS; automatic hover additionally
checks Accessibility. Capture permission denial must not break hotkey setup.
Add a normalized toggle action while preserving existing action compatibility.

| Event | When capture starts | Always | On demand |
|---|---|---|---|
| launch, hotkey activation | worker off | prepare | worker off |
| launch, always-active hover | prepare then observe | prepare then observe | observe dwell; no preload |
| Start Capture / toggle on | prepare then observe | ensure ready then observe | observe dwell; first stable target prepares |
| Pause / toggle off | retire immediately | stay warm by explicit policy | retire immediately |
| manual lookup while off | prepare, lookup, idle timeout | use/prepare worker | prepare, lookup, idle timeout |
| capture remains active after first demand | stay warm | stay warm | stay warm |

The Always choice deliberately opts into residency through Pause. All other
policies terminate on explicit Pause. A manual session while capture is off uses
a 60-second internal idle timeout measured from completion/latest activity; no
timeout preference. Do not terminate an in-flight current manual lookup. Use
one-shot timers and generation checks, not a polling resource manager.

Apply policy changes immediately: Always prepares; changing away while capture
is off stops residency unless a current manual session is in use. Always-active
starts capture subject to permissions; switching to hotkey activation pauses
automatic capture. Changing a binding or preload choice alone must not reset a
current capture session. Manual and hover remain independent triggers.

Rebind as one transaction: construct/validate candidate, register candidate
bindings with backend rollback, persist atomically, then publish config. If save
fails, restore old bindings and report failure. If native rollback itself fails,
surface that failure and keep the UI consistent with the actual registered set;
never report a lost binding as successful.

Unexpected lookup crash: invalidate its generation, report Error, and allow at
most one automatic recovery for the current active session. A second failure
stays Error until explicit Retry or a new deliberate activation resets the
budget. Do not reset recovery budget merely because a replacement reported Ready.
Normal initialization failures must be shown without fabricated dictionary hits.

Shutdown ordering: stop accepting input/capture, cancel dwell and invalidate
requests, retire/join lookup child, dismiss popup, close/join Control Center,
stop native listeners/tray, close transport/log resources and exit parent.
Update handoff receives control only after child processes have released their
installation/resource handles. Preserve readiness acknowledgement semantics
while decoupling acknowledgement from the Control Center window.

## Hover geometry and latency

Extend result handoff to retain the request's CaptureResult region plus resolved
word geometry from LookupResult context. Keep capture origin/scale with that
request, not with a mutable latest global capture. Map pixel coordinates to
screen/Qt logical coordinates once, including Retina and negative monitor origins.
Use resolved word bounds, not the whole OCR line, when word geometry is available.

While a successful target is retained, the union of a small expanded word region
(initially 4 logical px) and the actual popup frame protects it. Do not replace
that union with one bounding rectangle that covers unrelated words. A short exit
grace (initially 120 ms) bridges the word-to-popup gap. Re-entry cancels grace;
movement wholly inside a protected region starts no capture/OCR and does not
invalidate the current popup. Real exit immediately retires old request currency
and arms a new dwell; keep the old visual only for the grace interval. A new
current result may replace it before grace expires; old timers cannot dismiss
that newer result. Popup close/Pause/config target change clears retained state.

Measure dwell 80/40/20 ms with the same Korean fixture and native interaction
sequence. Keep 80 until evidence supports a stable lower default; preserve saved
user values. Report capture, IPC, OCR, morphology, dictionary, dispatch and total
separately. Distinguish measured callback latency from actual pixels-on-screen
latency. No timing assertions in unit tests, continuous CV, or provider tuning
previously rejected in `reports/ocr-latency-and-roadmap.md`.

## Logging, diagnostics and cleanup

Extend `diagnostics.py` with timestamp/level/subsystem/message records and keep
compatibility for existing textual sinks. Parent alone rotates the file; child
records flow over transport. Log startup/shutdown, CC lifecycle, worker state and
provider preparation, hotkey registration/toggle failures, capture state, lookup
timings and actionable failures. No mouse-motion stream. Bound each record as
well as the total tail/file; repair rotation for zero backups and oversized input.

Add functional Logs in existing `assets/control_center/index.html`, JS and CSS:
level/subsystem/search, timestamped rows, refresh, copy, clear and diagnostics
export. Render messages with textContent. Clear both displayed/history data
according to a documented UI contract; return errors when file cleanup fails.
Export sanitized JSON/text through an explicit save action, with version,
OS/architecture, frozen/dependency metadata, non-sensitive preferences,
resource/worker state and bounded recent records. Exclude screenshots, OCR text,
secret-like fields, absolute user paths and raw tracebacks carrying them. Sanitize
both direct records and exception chains before export/persistence where needed.

New `owned_cleanup.py` runs at startup and after completed operations. Own new
temporary data under a clearly identified directory with a marker/version, owner
PID/start identity and status; refuse symlinks and paths outside the managed root.
Reap abandoned disposable staging only after ownership, age and inactive owner
checks. Successful operations remove their transaction immediately. Preserve
unresolved backups and report recovery-required rather than deleting them to meet
a disk bound. Preserve current models/KRDICT and never scan arbitrary user caches.
The cleanup audit includes app-update extraction, resource staging, handoff script
directories and config-write leftovers. No periodic GC or aggressive sweep.

## Dependency order, commit boundaries and acceptance

Claude updates the checkpoint during each task. Astra reviews the actual diff,
focused evidence and principal lifecycle paths, records findings, orders fixes
and verifies them. Commit only a green logical boundary; no attribution trailers.

1. **Runtime and Control Center.** Change `application.py`, `qt_bootstrap.py`,
   `control_center_host.py`, `cli.py`, runtime hook; add CC process transport.
   Shell owns loop; X exits child and preserves runtime; reopen reflects live
   state; Quit stops children. Tests: loop ownership, duplicate open, RPC failure,
   real close/reopen, no heavy/WebEngine imports in parent. Native memory proof.
2. **Disposable lookup.** Add lookup process manager; adapt `runtime.py`,
   `job_executor.py` / `lookup_controller.py` at the smallest necessary seam;
   preserve `composition.py` provider/cache/retry logic. Deterministic tests:
   spawn, bounded pending work, A→B stale completion, retirement while preparing,
   restart generations, crash/recovery budget, EOF and bounded shutdown. Early
   constrained PyInstaller child smoke proves no recursive shell launch.
3. **Preload and input configuration.** Change `config.py`, `manual_lookup.py`,
   `hover_lookup.py`, `runtime_status.py`, `desktop_controller.py`,
   `hotkeys.py` / `hotkeys_darwin.py`, `control_center.py`, UI assets and
   permissions wiring. Full policy matrix, migration, cold/warm manual lookup,
   transactional rebind/save rollback and permission failures. All choices visible.
4. **Popup stability and dwell.** Change `hover_lookup.py`, `hover_controller.py`,
   `manual_lookup.py`, `popup.py` / `qt_popup.py` and capture-result handoff.
   Fake clock and geometry tests for same-word no OCR, popup interaction, gap
   grace, exit, different target, display scale, stale timers and results. Native
   dwell sweep determines the new default only after stability is proven.
5. **Logs and hygiene.** Extend logger, bridge and UI; add owned cleanup and
   integrate app/resource update staging. Verify log/file bounds, sanitization,
   copy/export/clear, crash leftovers, live-owner preservation, symlink refusal
   and unresolved rollback preservation. Review updater script child ownership.
6. **Integration, build and performance.** Review entire diff against base,
   fix integration findings, update CODE-MAP and stale launch documentation.
   Run source gates, clean tracked-source release build, reconstructed artifact
   inventory/signature/UI/provider/runtime validation, final measurements and
   updater compatibility. Record all real evidence in checkpoint/handoff.
7. **Final handoff and push.** Confirm every product requirement and native Mac
   acceptance condition, list pending Windows/Linux checks, commit final records
   and push this green feature branch. Do not merge.

## Validation protocol

Focused tests extend existing suites for application/config/CC/controller/executor,
manual/hover/popup/hotkeys/diagnostics/updater. Use injected child factories and
events for deterministic races, plus genuine spawn integration tests. Do not turn
all tests into subprocess tests or weaken old assertions merely to pass.

Final source gates, using repository configuration:

```
.venv/bin/python -m pytest
.venv/bin/python -m ruff check packages packaging tests tools benchmarks
.venv/bin/python -m mypy packages packaging tests tools benchmarks
.venv/bin/python -m pip check
```

Build from a clean tracked-source export using installed Python 3.10.20, a fresh
venv and `packaging/release-constraints.txt`, following `.github/workflows/build.yml`
installation order. Models are explicit verified inputs. Run
`tools/build_package.py --platform macos`; retain .app, ZIP and DMG. Reconstruct
ZIP, mount DMG read-only, verify inventory and `codesign --verify --deep --strict`,
then run frozen worker/UI and lifecycle self-checks outside checkout/developer
profile. Test real Korean OCR, Kiwi, KRDICT and updater accepted/rejected paths
where practical. No release publication or tags are needed for local validation.

Measure native Mac before and after on the same host/dependency set and fixture;
measure final frozen artifact separately. Record host load, parent/child IDs,
process-tree RSS, per-process physical footprint, threads, CPU interval, provider
imports, startup/readiness and lookup timings. Capture A dormant closed, B CC
open, C preparing, D capture Ready, E warm lookup, F paused, G cold manual and H
warm manual, plus post-child termination. Footprint/RSS can diverge under memory
compression; never compare them numerically to Windows WS. Prefer process absence
and memory return over an unqualified 100–200 MB target.

Native interaction: launch, close/reopen CC, rebind, change activation/preload,
Start → Preparing → Ready, Korean hover, micro-move, enter popup, different word,
Pause, cold/warm manual, idle expiry, reopen/reconfigure, Quit. Use available native
permissions; record an actual permission blocker instead of claiming simulation
proves global input. Source-only tests do not establish native behavior.

Windows pending checklist: source gates with symlink privilege; native/frozen
spawn; no recursive runtime; dormant memory/CPU; every preload policy; Pause
termination; manual cold/warm; toggle/rebind/conflict/rollback; CC release/reopen;
popup geometry on mixed DPI; logs/export; crash/parent-death/shutdown; PowerShell
accepted and rejected updates including all child handles; ZIP/inventory smoke.

Linux pending checklist: native/frozen spawn; X11 mouse/hotkeys and rebinding;
CC release/reopen; popup interaction/multimonitor geometry; all policies; parent
death and shutdown; frozen archive executable modes and internal symlinks;
updater accepted/rejected paths. Mac POSIX tests remain labeled Mac source tests.

## Non-goals and active risks

No ONNX, alternate OCR, persistent word cache, custom analyzer, browser runtime,
visual redesign, multiple heavy workers, generic plugin/state-machine/RPC framework
or unrelated architecture rewrite. Existing in-memory caches remain worker-owned.

Risks needing proof: PyInstaller spawn before any role-specific imports; native
thread affinity and CC proxy shutdown; source/frozen macOS privacy grants;
word geometry scaling; retirement during resource update; log sanitation without
losing actionable failure context. Native Windows/Linux are final validation
dependencies, not reasons to postpone Mac implementation.

Current execution blocker: automatic review rejected Claude repository egress;
the user's explicit Anthropic transfer approval is pending. Local investigation,
baseline and this concrete plan continue independently. No Claude implementation
has been claimed or substituted.
