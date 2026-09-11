# MVP Runtime Performance Wave — Execution Checkpoint

## Environment

- Branch: `perf/mvp-runtime-lifecycle`.
- Base/current commit at start: `f5087106e1f1a82e52239a5d2df6741074a57ab4`.
- Latest `origin/main` fetched and matches HEAD; working tree was clean; previous technical wave merged.
- Host: macOS Darwin 25.6.0, arm64; development Python 3.13.11.
- Claude Code 2.1.268 is installed; implementation dispatch being verified.
- Relevant dependency versions: EasyOCR 1.7.2, Torch 2.13.0, kiwipiepy 0.23.2,
  PyQt6/WebEngine 6.11.0, pywebview 6.2.1, PyInstaller 6.22.2.
- Python 3.10.20 is also installed for the future clean constrained build.
- psutil is absent; native libproc and ps provide measurements instead.

## Plan

- [x] repository investigation
- [x] macOS baseline
- [x] implementation-ready execution plan
- [x] runtime / Control Center lifecycle
- [x] heavy lookup worker
- [x] preload policies
- [x] hover activation / hotkeys
- [x] hover stability / popup persistence
- [x] logs / diagnostics
- [x] cleanup / disk hygiene
- [x] integration review
- [x] full source gates
- [x] clean macOS frozen build
- [x] final performance measurements
- [x] final review
- [x] final handoff
- [ ] branch push

## Decisions

### 2026-09-11 — Claude dispatch unblocked; Claude implements

Decision: The user granted explicit approval to send repository files and code
to the authenticated Anthropic Claude service, and Claude Code is running as the
implementation agent in this repository. The earlier egress blocker is resolved.
Evidence: User's wave authorization message of 2026-09-11.
Files: None yet at the time of this entry.
Validation: Pre-implementation gates re-run on unchanged `f508710`:
1044 passed, 3 skipped in 128 s; Ruff and mypy clean.

### 2026-09-11 — One window host, two js_api providers

Decision: Keep a single `ControlCenterHost` that creates the pywebview window,
insists on the Qt backend and owns that process's loop, and give it two callers:
the Control Center child (js_api = `ControlCenterProxy`) and the packaging
`--self-check ui` mode (js_api = an in-process `ControlCenterBridge`).
Original assumption: The plan implied a new child-owned window implementation.
Evidence: `self_check._run_ui_check` drives the real window through
`host.run(on_started=...)`, `host.window.evaluate_js` and `host.close()`; a
second window implementation would have left that harness proving a code path
the desktop no longer uses.
Chosen alternative: One host; the hide-on-close/`set_restorable` behaviour was
deleted because X must now destroy the window and end its process.
Files: `packages/hanly-app/src/hanly_app/control_center_host.py`.
Validation: `tests/test_control_center_host.py` (7 passed) and the rewritten
`tests/integration/test_control_center_lifecycle.py` (real window, real child).

### 2026-09-10 23:09 -03 — Separate disposable process ownership

Decision: Parent Qt Widgets runtime owns input/tray/popup and canonical state;
optional spawned CC and lookup children own WebEngine and heavy providers.
Original assumption: Try destroying UI/native objects in the long-lived process.
Evidence: CC destruction left ~286 MiB parent footprint; deleting EasyOCR and
closing the full pipeline left footprint unchanged; prepared Pause retained
~1,011 MiB parent footprint. Existing controller already owns latest-wins.
Chosen alternative: Explicit spawn/Pipe children, generation-tagged transport,
existing controller final currency check and parent-owned bridge operations.
Files: Planned modules and acceptance are in the execution plan; no production
code changed. Runtime hook and Qt bootstrap must become role-specific.
Validation: Native before probes completed; target architecture is still unbuilt
and its spawn/frozen behavior is explicitly an early implementation gate.

### 2026-09-10 — Execution authority

Decision: Follow the user's explicit wave authorization: Astra leads and reviews,
Claude implements, one feature branch, logical commits and final push. No Linear
writes, merge, tags or release. Reviews and architecture choices within the
requested product scope are explicitly authorized by this request.
Evidence: User's attached full wave brief; clean integrated main at `f508710`.
Files: This checkpoint; execution plan to follow investigation.
Validation: `git fetch origin main`; HEAD and origin/main match.

## Progress Log

### 2026-09-11 — Task 6: integration, the clean frozen build, and the numbers

What changed: Reviewed the whole branch against `main`. `docs/CODE-MAP.md` now
describes three processes, the transport, readiness against residency, the
retained hover target, and every new module; `CLAUDE.md` no longer says the OCR
runtime loads before Qt in the shell. New packaging contract tests assert that
neither child entry point reaches first-run provisioning, update
acknowledgement, `run_desktop` or hotkey registration, and that
`application.py` carries neither heavy runtime. The new public types are
exported from `hanly_app`.
Source gates, working tree: pytest 1155 passed / 3 skipped in 70 s; Ruff clean;
mypy clean over 190 files; `pip check` clean.
Clean constrained environment: tracked-source `git archive` export, Python
3.10.20, a fresh venv, `packaging/release-constraints.txt`, and the workflow's
installation order. `pip check` clean, Ruff clean, mypy clean over 190 files,
pytest **1137 passed / 8 skipped** in 130 s. The five extra skips are the
environment saying so: no `tomllib` on 3.10 (2), no frozen bundle yet (3, later
satisfied), a Windows-only abort code, a Windows-only rename rule, and the
opt-in real-model inference test.
Frozen build: `tools/build_package.py --platform macos` with
`PYINSTALLER_STRICT_BUNDLE_CODESIGN_ERROR=1` and the EasyOCR weights supplied as
verified inputs. Products: `hanly-desktop-macos.zip` (560,295,588 bytes) and
`hanly-desktop-macos.dmg` (639,494,440 bytes); the `.app` is 1.3 GB. The ZIP was
reconstructed and the DMG mounted read-only; the inventory reported every
expected entry and nothing missing, and `codesign --verify --deep --strict`
returned `valid on disk` and `satisfies its Designated Requirement`
(adhoc, `io.github.thiagoross1.hanly`, 6039 sealed files).
Frozen self-checks, run outside the checkout and the developer profile:
`--self-check worker` read **책을 읽습니다.** through the bundled EasyOCR
(2229 ms), analyzed 한국어 through Kiwi (1354 ms) and found 1 dictionary entry
(3 ms); `--self-check ui` opened the real window, rendered its four controls and
completed a bridge round trip.
Frozen process split, the new risk this wave had to retire:

| Frozen state | Processes | Tree footprint | Shell |
|---|---:|---:|---:|
| dormant, window open, engine asleep | 4 | 372.0 MiB | 66.8 MiB |
| window open, engine loaded (Always) | 5 | 1153.5 MiB | 63.0 MiB |

The Control Center child was 248.5 MiB with 28 threads plus a 27.2 MiB
`QtWebEngineProcess`; the lookup child was 810.8 MiB. Ready at 2040 ms with the
engine asleep and 7333 ms with it loaded. `SIGINT` logged
`Lookup engine: sleeping` and the process exited cleanly both times. No
recursive shell launch in either run.
Updater compatibility: the frozen build answered `--update-ready` in **3 s**
with `0.1.3`. This is the contract the handoff waits on, and it moved in this
wave from "the window opened" to "the shell's loop is running", so it was worth
proving on the real artifact.
Source-build lifecycle measurements, same host and dependency set as the before
baseline. MiB means 2^20 bytes; footprint is libproc `RUSAGE_INFO_V2` and RSS is
`ps`; they are different accounting measures and neither is a Windows working
set. The process count includes CPython's POSIX `multiprocessing` resource
tracker, a permanent ~29 MiB process that the spawn start method creates and
that Windows does not have.

| State | Processes | Tree footprint MiB | Shell footprint MiB |
|---|---:|---:|---:|
| A dormant, window closed, engine asleep | 2 | 69.3 | 60.4 |
| B Control Center open | 4 | 383.3 | 64.9 |
| C preparing, just after Start | 3 | 177.3 | 63.3 |
| D capture ready, engine loaded | 3 | 895.4 | 63.2 |
| E capture running after hover movement | 3 | 864.8 | 63.5 |
| F paused | 2 | 72.5 | 63.6 |
| G cold manual lookup, engine woken | 3 | 1210.2 | 63.5 |
| H warm manual lookup | 3 | 1148.8 | 63.6 |
| after shutdown, children gone | 2 | 72.3 | 63.4 |

Against the before baseline: full idle was 1010-1036 MiB of parent footprint and
a paused prepared runtime was 1011 MiB. Dormant is now 69 MiB across two
processes and pause returns to 72 MiB. Startup to ready went from 12.55 s to
1.44-1.78 s with the default policy. A cold manual lookup with capture off woke
the engine and reached ready in **5.1-6.6 s**; a warm one answered inside the
probe's 2 s sample window, and the dwell sweep measured the warm pipeline itself
at 0.06 ms in the child and 0.54-0.83 ms through the process boundary.
Honest limits of this sweep: the scripted hover step did not resolve a word on
the final memory passes. A full-screen capture taken at the moment of failure
showed only the desktop picture, so the fixture window was not on the Space
being captured; that is probe staging, not product behaviour. Hover is proven
natively by the dedicated dwell sweep recorded under task 4, which resolved the
first and second word at 80, 40 and 20 ms and did no work during micro-movement.
E is therefore labelled for what it measures -- capture running with the engine
loaded -- rather than as a warm hover lookup.
Global hot keys: registration is proven natively in both builds
(`lookup <ctrl>+<shift>+<space>`, `toggle_hover <ctrl>+<shift>+<f9>` reported by
the running session; the frozen run logged no shortcut failure). **Delivery
could not be proven from an automated probe**: macOS does not match a synthetic
`CGEvent` against a Carbon hot key, verified directly -- a registered service
with a posted ctrl+shift+space fired nothing. The manual lookup path after the
key is production code and was measured through it (G and H above). An actual
key press remains a pending human check.
Files: `docs/CODE-MAP.md`, `CLAUDE.md`, `tests/test_packaging.py`,
`packages/hanly-app/src/hanly_app/__init__.py`.
Next: the final handoff and the branch push.

### 2026-09-11 — Task 5: logs a user can read, and cleanup that refuses

What changed: `diagnostics.py` gained `DiagnosticRecord` (timestamp, level,
subsystem, message) while `snapshot()` still returns exactly the one-line tail
every existing surface showed. Records are bounded at 2000 characters each,
rotation now truncates when no backups are kept (it previously grew for ever at
`backup_count=0`) and an oversized write is cut before it reaches the file.
Startup, capture, the Control Center, the lookup engine and cleanup all record
against their own subsystem; the lookup child's records travel over the existing
transport and the parent alone writes the file. Lookup timings are recorded only
when one exceeds 1.5 s, so hover never becomes a motion stream. The Control
Center gained a Logs section with level, subsystem and search filters,
timestamped rows rendered with `textContent` only, refresh, copy, clear and a
Save report action. Clear empties the displayed records and the file, and says
so when the file cannot be emptied. The export writes a sanitized JSON bundle
beside the log with versions, platform, frozen flag, preferences, resource,
engine, hotkey and permission state, and bounded recent records; the user's home
directory is rewritten to `~` and anything reading as a credential is redacted.
New `owned_cleanup.py` owns new temporary data under one marked root, with a
marker version, the owner's process id, what it was doing, and a status. A
directory is reaped only when its owner is gone and it has aged out, so a
recycled process id can only cause Hanly to keep one. Symlinks and anything that
does not resolve inside its root are refused. The audited update locations -- the
staging directory beside the installation and the handoff script directory in
the system temporary directory -- are swept by age, and anything still holding a
`previous` or `rejected` installation is reported as needing recovery and left
alone. Cleanup runs at startup, on the preparation thread, and after an update
completes. There is no periodic collection.
Why: A windowed build has no console, so what Hanly reports about itself is all
a user has; and an interrupted session leaves staging behind in a profile nobody
looks at.
Evidence/result: Native macOS session, real subsystems recorded in order --
`Startup: qt bootstrap 333 ms`, `Startup: resources 5309 ms`,
`Startup: runtime ready at 5691 ms`, `Lookup engine: preparing`,
`Capture: Hanly is watching the screen.`, `Lookup engine: sleeping`,
`Capture: Hanly stopped watching the screen.` Pausing during preparation
correctly produced no `ready` record: the generation moved first and the child
that finished starting afterwards closed instead of becoming current. The
exported bundle carried platform, versions, preferences, engine, registered
hotkeys, resources and permissions, 21 records, and no occurrence of the user's
home directory.
Updater script ownership reviewed: the handoff script already removes its own
transaction on success and on a clean rejection, and deliberately keeps it when
the restore itself fails because its backup is then the only copy of a working
Hanly. The sweep preserves exactly those, so cleanup cannot undo that decision.
Decision recorded: the rotating log on the user's own machine is kept raw,
absolute paths and all, because a debuggable path is what makes it worth having.
Sanitization applies to the export, which is the artifact designed to be shared.
Files:
- `packages/hanly-app/src/hanly_app/diagnostics.py:L30-L90,L100-L200,L230-L300`
- `packages/hanly-app/src/hanly_app/owned_cleanup.py` (new)
- `packages/hanly-app/src/hanly_app/control_center.py:L440-L560`
- `packages/hanly-app/src/hanly_app/control_center_process.py:L37-L60,L390-L410`
- `packages/hanly-app/src/hanly_app/application.py:L245-L260,L470-L520,L900-L930`
- `packages/hanly-app/src/hanly_app/lookup_process.py:L58-L70,L390-L420`
- `packages/hanly-app/src/hanly_app/assets/control_center/*`
Tests/measurements: full suite 1153 passed, 3 skipped in 90 s; Ruff and mypy
clean over 190 files. New `tests/test_owned_cleanup.py` (15) covers the marker, a
completed operation, a live owner keeping its directory however old, an
abandoned one being reaped, a young one being left, recovery-required,
an unmarked directory, a symlink into the root, a path outside the root, an
invalid operation name, update staging by age, and both unresolved-backup cases.
`tests/test_diagnostics.py` gained record structure, the unchanged one-line tail,
the per-record bound, the zero-backup rotation bound, clearing, and both export
sanitizations. `tests/test_control_center.py` gained the logs snapshot, clearing
both halves, a file that cannot be emptied, the export contents, a build without
a log, and a check that the panel renders through `textContent`.
Next: task 6, integration, clean frozen build and final performance.

### 2026-09-11 — Task 4: a popup the cursor can reach

What changed: The engine now reports where the answer came from.
`WordResolver.word_bounds` maps the resolved word's character span back onto the
line quad, `LookupContext` carries it as `word_region`, and the pipeline fills it
through an optional resolver member so a substituted resolver stays valid. New
`hover_target.py` holds `RetainedTarget`, the expanded-word plus popup-frame
union, the ROI-to-screen placement, and `CaptureOrigins`, which keeps each
request's capture origin with that request rather than with a mutable latest
capture. `HoverLookupRuntime` stops clearing the popup on every movement:
movement inside the protected union captures nothing, recognizes nothing and
dismisses nothing, while a real exit retires request currency, arms a new dwell,
and keeps the visible answer for a 120 ms grace. Re-entry cancels the grace, a
newer retained result cancels the older one's timer, and an expired timer from a
previous answer can never dismiss the current one. Pause, invalidate, shutdown,
and a capture target change all forget the retained target.
Why: The popup disappeared as soon as the cursor moved towards it, which made a
result impossible to read and made every micro-movement a full OCR call.
Evidence/result: Native macOS sweep with the real screen, the real cursor (posted
`kCGEventMouseMoved` events, not a warp, which produces no events at all), the
real capture backend and the real lookup child, over the checked-in Korean
fixture shown in a window. At dwell 80, 40 and 20 ms alike: the first word was
recognized, the second word was recognized after moving to it, four micro-moves
inside the word produced **0 captures and 0 OCR calls** with four
`hover_inside_retained_target` events, the answer stayed on screen throughout,
and leaving cleared it. Stage timings, dwell 80, cold: capture 52.6 ms p50,
OCR 226.5 ms p50 (first inferences), token selection 0.06 ms, morphology 2.3 ms,
dictionary 3.1 ms, child total 116.4 ms, executor total 117.0 ms, so the whole
new process boundary costs **0.59 ms**. The 40 and 20 ms sweeps re-read the same
pixels and were answered from the worker's OCR cache (child total 0.06-0.07 ms,
executor total 0.54-0.83 ms), which confirms IPC overhead of **0.5-0.8 ms** and
also means the three dwells are not comparable on latency.
These are callback and stage timings, not pixels-on-screen latency.
Dwell decision: **80 ms is kept.** All three values worked on a static fixture
driven by a scripted cursor, which is not evidence about a human hand on live
text, and the plan's bar is a stable lower default. Saved user values are
untouched.
Probe defects found and corrected, both mine rather than the product's:
`CGWarpMouseCursorPosition` moves the cursor without emitting any event, so the
observer saw nothing; and a Qt window that is never activated opens behind the
front Space, so the capture read the desktop picture and every lookup came back
EMPTY. Screen Recording and Accessibility were confirmed granted and working by
capturing the full screen and reading back the fixture.
Files:
- `packages/hanly/src/hanly/word_resolver.py:L60-L140,L230-L300`
- `packages/hanly/src/hanly/contracts.py:L189-L200`
- `packages/hanly/src/hanly/lookup_pipeline.py:L100-L180,L250-L275`
- `packages/hanly-app/src/hanly_app/hover_target.py` (new)
- `packages/hanly-app/src/hanly_app/hover_lookup.py:L60-L120,L260-L420`
- `packages/hanly-app/src/hanly_app/manual_lookup.py:L400-L470,L560-L700`
- `packages/hanly-app/src/hanly_app/composition.py:L726-L740`
Tests/measurements: full suite 1125 passed, 3 skipped in 75 s; Ruff and mypy
clean over 188 files. New `tests/test_hover_target.py` (20) covers word geometry
against the whole line, the pipeline carrying it, placement on a monitor with a
negative origin, the union never becoming a hull, the margin, bounded origins,
same-word movement doing no work, entering the popup, the gap grace, re-entry
cancelling it, a real exit arming a new dwell, a stale timer failing to dismiss a
newer result, pause and invalidate forgetting the target, and a capture target
change forgetting it.
Next: task 5, logs, diagnostics and owned cleanup.

### 2026-09-11 — Task 3: preload policies, one toggle, transactional rebinding

What changed: `config.py` gained `LookupPreload` (when_capture_starts, always,
on_demand), `HoverActivation` (hotkey, always_active) and `hover_hotkey`, plus
`AppConfig.migrate` and `ConfigManager.migrations`. A profile written before
this keeps its lookup key untouched; only the new toggle moves, and only when
the lookup key already sits on the toggle's default, in which case it takes the
next position in a fixed list and says so in the log. `hotkeys.py` gained
`HotkeyAction.TOGGLE_HOVER` and `validate_binding`, which asks the running
platform's own backend whether a combination is registrable rather than only
checking its spelling. `ManualLookupRuntime` now separates the session from
capture: `prepare()` registers both shortcuts and builds the lookup path,
`start()` applies the policy and begins observing, `pause()` retires the engine
unless the policy is Always, and a manual lookup with capture off arms a
60-second idle expiry measured from completion. A shortcut another application
owns is reported and costs only that shortcut. A manual lookup without Screen
Recording says so instead of reading the wallpaper and reporting no Korean text.
The Control Center bridge makes a settings change a transaction: validate,
register with the operating system, persist, then publish; a save that fails
after a successful registration puts the previous shortcuts back, and a failure
of that too is reported rather than called a success. The page gained controls
for all three new preferences, a lookup-engine status row separate from shell
readiness, and a hint showing what was actually registered when it differs from
what was asked for.
Why: Readiness used to imply resident providers, so the engine was loaded even
when nothing was watching the screen, and Pause left it loaded.
Evidence/result: Native macOS, source build, default policy: ready at
**1.76 s** (before: 12.55 s); dormant with the window closed **73.6 MiB tree
footprint over 2 processes** (before: 1010-1036 MiB parent footprint); Start
Capture goes preparing 174 MiB then ready 888 MiB; Pause returns to 76.2 MiB
and `sleeping`. With Always: ready at 7.17 s, resident at launch, and still
882 MiB after Pause, which is the residency that choice deliberately buys.
Registered shortcuts reported as `lookup <ctrl>+<shift>+<space>` and
`toggle_hover <ctrl>+<shift>+<f9>`.
Defect found and fixed during the task: `prepare()` re-applied the preload
policy on every call, so `start()` (which prepares first) published a second
redundant residency decision. Preparation is now once per session.
Files:
- `packages/hanly-app/src/hanly_app/config.py:L23-L120,L150-L330`
- `packages/hanly-app/src/hanly_app/hotkeys.py:L22-L80,L183-L210`
- `packages/hanly-app/src/hanly_app/manual_lookup.py:L60-L200,L250-L560`
- `packages/hanly-app/src/hanly_app/lookup_process.py:L360-L420`
- `packages/hanly-app/src/hanly_app/control_center.py:L195-L260,L430-L460,L560-L660`
- `packages/hanly-app/src/hanly_app/application.py:L430-L560`
- `packages/hanly-app/src/hanly_app/assets/control_center/*`
Tests/measurements: full suite 1105 passed, 3 skipped in 75 s; Ruff and mypy
clean over 186 files. New `tests/test_lookup_policy.py` (16) covers the whole
matrix: shortcuts registered with the session rather than with capture, a
shortcut another application owns, each of the three policies at launch, start
and pause, the recovery-budget refresh on deliberate activation, idle expiry and
its re-arm, capture keeping the engine warm, the toggle routing to the capture
lifecycle, a refused manual lookup without Screen Recording, live policy changes
in both directions, a manual session surviving a policy change, and a binding
change leaving a running session alone. `tests/test_app_config.py` gained the
migration cases; `tests/test_control_center.py` gained register-before-store,
refused registration, save rollback, rollback failure, the engine snapshot, an
invented choice, and a check that every new preference has a control on the page.
Next: task 4, popup stability and dwell.

### 2026-09-11 — Task 2: the lookup engine is a child the shell can retire

What changed: New `lookup_process.py`. `LookupSettings` is the plain value that
crosses spawn (validated KRDICT path, `EasyOCRConfig`, threshold, flat-ROI gate);
a `HanlyRuntime` never does. `LookupProcess` owns one child, its pipe and its
generation; `LookupEngine` owns residency (sleeping / preparing / ready / error)
and is itself the `JobExecutor` worker. `LookupController` and `JobExecutor` are
unchanged: request IDs, latest-wins submission, the final currency check on the
dispatch thread and one-running-plus-one-latest-pending all still happen in the
shell. `composition.py` provider, cache and sensitive-retry logic is untouched
and now runs in the child. `runtime.py` gained `lookup_settings`,
`create_lookup_engine`, and a `create_lookup_controller` that takes an engine;
a substituted `word_resolver_factory` is a callable and cannot cross spawn, so
that one caller keeps the in-process composition it was already asking for.
Why: Deleting an EasyOCR provider and closing the whole pipeline left the
measured footprint unchanged. Only process exit returns that memory.
Evidence/result: Native macOS, source build. Startup to Ready 7.6 s (before:
12.55 s). Shell footprint steady at 58.6 MiB across the session (before: parent
1010-1086 MiB). Capture-ready with the window open: 5 processes, 1122 MiB tree
footprint. Closing the window: 3 processes, 888 MiB. Shutdown returns in 0.7 s
and leaves 67 MiB. Real Korean lookup through a spawned child verified
end to end.
Defect found and fixed during the task: the first cut constructed the engine
eagerly in `LookupEngine.__init__`, which runs on the Qt thread inside
`_DesktopSession.activate`; the desktop then blocked the UI thread on provider
construction and `tests/integration/test_desktop_startup.py` timed out.
Residency is now honoured in `LookupEngine.attach`, which the executor calls on
its own thread, exactly where the wait belonged.
Defect found and fixed in passing: the desktop's controller path never
forwarded `skip_flat_rois` (only `create_worker_factory` did), so a
configuration asking for the flat-ROI gate was silently ignored. It travels in
`LookupSettings` now.
Test-harness defect fixed: `tests/conftest.py` points `EASYOCR_MODULE_PATH` at a
temporary directory, which the desktop startup integration test inherited, so
every run downloaded 99 MB of weights and the test took 105-193 s and had begun
failing on the download. It now reads prepared weights with downloading off, and
skips when there are none: 9.4 s.
Files:
- `packages/hanly-app/src/hanly_app/lookup_process.py` (new, L1-L700)
- `packages/hanly-app/src/hanly_app/runtime.py:L124-L270`
- `tests/hanly_fixtures/lookup_child.py` (new)
- `tests/test_lookup_process.py` (new, 15 tests)
- `tests/integration/test_lookup_process_spawn.py` (new)
- `tests/test_easyocr_runtime.py:L238-L275`
- `tests/integration/test_desktop_startup.py:L108-L185`
Tests/measurements: full suite 1074 passed, 3 skipped in 81 s; Ruff and mypy
clean over 185 files. Deterministic coverage: spawn, provider lifecycle on one
child thread, a plain picklable boundary value, sleeping start, waking on
demand, retire-and-wake, retirement during preparation, a failing child
reported as error rather than a fabricated lookup, one automatic recovery then
a persistent error, a replacement not refilling the budget, cancellation
forwarded and applied between stages, only the latest pending request reaching
the child, EOF releasing a blocked lookup, and a closed engine refusing to
start another child.
Next: task 3, preload policies and input configuration.

### 2026-09-11 — Frozen spawn dispatch gate passed

What changed: Built a minimal PyInstaller onedir program that calls
`multiprocessing.freeze_support()` first and then `spawn_child`.
Why: The plan required proving PyInstaller spawn dispatch before building
settings on an unproven base.
Evidence/result: The child reported `frozen: True`, ran only its target, and
exited 0; the parent's own startup line was never printed a second time, so
there is no recursive shell launch. PyInstaller 6.22.2 replaces
`multiprocessing.freeze_support` with a cross-platform diverter in
`pyi_rth_multiprocessing`, which is what makes the call in `cli.main` load
bearing on macOS and Linux as well as Windows.
Files: Scratch build only; no repository change.
Tests/measurements: `dist/spawngate/spawngate` ran clean.
Next: implement the lookup child on that basis.

### 2026-09-11 — Task 1: the shell owns the loop, the window owns a process

What changed: The persistent shell now owns the single `QApplication` and its
event loop with `setQuitOnLastWindowClosed(False)`; the Control Center runs in a
spawned child. New `process_transport.py` carries explicitly pickled,
size-bounded messages over an inherited duplex `Pipe`, with serialized sends,
one reader per direction, and a terminate/kill-bounded `stop_process`. New
`control_center_process.py` holds the parent-side manager (at most one child,
generation-tagged, focus instead of a duplicate, bounded outstanding
operations) and the child entry point. The canonical `ControlCenterBridge`
stays in the parent; the page reaches it through `ControlCenterProxy`, whose
public methods are exactly `CONTROL_CENTER_OPERATIONS` and which the parent
resolves against that same list rather than by `getattr` from the wire.
`qt_bootstrap` no longer imports Qt WebEngine or the OCR runtime;
`packaging/runtime_hook.py` no longer preloads OCR into every process;
`cli.main` calls `multiprocessing.freeze_support()` before argument parsing.
Why: Measured before-state: destroying the window left ~286 MiB charged to the
long-lived process. Memory that a library never returns can only be returned by
the process exiting.
Evidence/result: Native macOS probe, source build, this host —
shell alone 22.1 MiB footprint / 33.8 MiB RSS / 1 process; Control Center open
4 processes and 326.7 MiB tree footprint with the shell still at 22.2 MiB;
closed 31.0 MiB tree footprint; reopened 321.9 MiB; closed again 31.1 MiB. The
window's cost is 273.4 MiB (child) + 22.3 MiB (QtWebEngineProcess) and all of
it leaves on close. A second, permanent 8.8 MiB process appears on the first
spawn: CPython's POSIX `multiprocessing` resource tracker, which
`spawn.get_preparation_data` starts unconditionally. It is counted above and is
not present on Windows. Qt prints `Release of profile requested but
WebEnginePage still not deleted` while the child tears down; the child still
exits and its memory is returned.
Tray decision: with the window in a child, closing it can no longer end the
session, so an unusable tray (start failed, or no menu and no default action)
now makes a closed window quit the shell rather than leave a process the user
cannot reach.
Shutdown ordering now: closing flag, startup stopped, input/capture/lookup
retired and joined, then the Control Center child, then the tray, then signals —
so an update handoff only takes over after every Hanly process has let go.
Files:
- `packages/hanly-app/src/hanly_app/process_transport.py` (new, L1-L214)
- `packages/hanly-app/src/hanly_app/control_center_process.py` (new, L1-L470)
- `packages/hanly-app/src/hanly_app/control_center_host.py:L1-L300`
- `packages/hanly-app/src/hanly_app/qt_bootstrap.py:L1-L70`
- `packages/hanly-app/src/hanly_app/application.py:L199-L232,L285-L330,L360-L400`
- `packages/hanly-app/src/hanly_app/cli.py:L111-L125`
- `packaging/runtime_hook.py:L1-L14`
- `packages/hanly-app/src/hanly_app/assets/control_center/control_center.js:L359-L366`
Tests/measurements: full suite 1058 passed, 3 skipped in 184 s; Ruff clean;
mypy clean over 181 files. New `tests/test_control_center_process.py` (13) covers
the allowlist, duplicate open, refused operation, failing operation, the
outstanding bound, child death, reopen generation, shutdown refusal, the size
bound and reader release. `tests/integration/test_control_center_lifecycle.py`
rewritten: a real shell process that never creates a `QApplication` opens the
real window in a child, the page reaches the parent bridge across the pipe,
close/reopen produce generations 1 and 2, and the shell's `sys.modules` contains
none of `PyQt6.QtWebEngineWidgets`, `easyocr`, `torch`, `kiwipiepy`.
Next: task 2, the disposable lookup process, starting with a frozen-spawn
dispatch check before settings are built on an unproven base.

### 2026-09-10 23:09 -03 — Before baseline and concrete plan

What changed: Wrote `docs/execution/mvp-runtime-performance-wave.md`, with
ownership/IPC, policy matrix, exact modules, migration, hotkey rollback, retained
geometry, logging, cleanup and source/frozen/native acceptance. Measured unchanged
source in isolated temporary profiles and verified all probe processes exited.
Why: Process isolation must be justified by measured retention and integrated
with existing controller currency and updater ownership.
Evidence/result: See native baseline below. The shell import graph is light;
heavy imports are introduced by Qt bootstrap/runtime hook and provider warming.
`ControlCenterBridge` persists configuration before live rebinding; include a
transactional correction. Pause leaves all heavy imports resident.
Files:
- `packages/hanly-app/src/hanly_app/qt_bootstrap.py:L30-L35`
- `packaging/runtime_hook.py:L5-L9`
- `packages/hanly-app/src/hanly_app/application.py:L424-L450`
- `packages/hanly-app/src/hanly_app/control_center_host.py:L269-L291`
- `packages/hanly-app/src/hanly_app/control_center.py:L548-L563`
- `packages/hanly-app/src/hanly_app/hover_lookup.py:L263-L294`
- `docs/execution/mvp-runtime-performance-wave.md`
Tests/measurements: 57 focused existing tests passed (app config, lookup
controller, hover lookup, Control Center host, hotkeys); diff whitespace check
passed. Initial test invocation used a nonexistent `test_config.py`; corrected
to `test_app_config.py`, with no tests changed. Initial ps probe used unsupported
`thcount`; replaced with native libproc thread count. These were harness failures.
Next: Obtain pending Claude transfer approval, dispatch task 1, keep this record
current. No production implementation or full-source/frozen validation yet.

### 2026-09-10 — Claude dispatch blocked by automatic review

What changed: Read-only Claude dispatch in the sandbox failed with ENOTFOUND and
zero API tokens. A network-enabled retry was rejected by automatic approval
review before starting. The initial process subsequently exited; no Claude work
has been completed or represented as completed.
Why: Automatic reviewer required explicit permission to send potentially private
repository content to the authenticated Anthropic service, beyond the instruction
to use Claude as implementer.
Evidence/result: User was asked for explicit transfer approval or Codex-local
implementation as an alternative; answer pending. Do not retry Claude egress or
substitute another implementer until the user answers.
Files: No implementation edits. CLI failure report is temporary under
`/private/tmp/hanly-wave-claude-investigation.json`.
Tests/measurements: Local investigation and baseline proceeded independently.
Next: Resume the implementation dispatch after this blocker is resolved.

## Native macOS before baseline

Unchanged `f508710` source; Python/dependency versions above. MiB means 2^20
bytes. RSS is the sum of `ps` resident KiB across the measured process tree.
Physical footprint is libproc `proc_pid_rusage(..., RUSAGE_INFO_V2)`;
layout checked against the installed macOS SDK `sys/resource.h`. Thread counts
come from `PROC_PIDTASKINFO`, checked against SDK `sys/proc_info.h`.
Footprint and RSS are different accounting measures, neither Windows WS.
Short `ps` CPU samples are observations, not an interval-integrated CPU study.

| Probe/state | Tree RSS MiB | Parent footprint MiB | Other evidence |
|---|---:|---:|---|
| bare Python | 17.6 | 9.6 | no heavy imports |
| engine imports | 20.2 | 12.0 | no heavy imports |
| application import graph | 35.3 | 23.9 | no heavy imports; ~0.20 s from process probe start |
| Kiwi ready | 380.1 | 470.5 | ~1.64 s; kiwipiepy loaded |
| Kiwi object deleted + gc | 332.9 | 365.8 | large native allocation remains |
| OCR imported | 283.2 | 256.3 | ~2.61 s; Torch/EasyOCR loaded |
| OCR ready | 536.2 | 893.3 | ~5.35 s cumulative |
| OCR object deleted + gc | 646.2 | 893.3 | footprint unchanged |
| isolated CC created | 221.9 | 334.9 | 2 processes; OCR preload deliberately excluded |
| isolated CC hidden | 160.3 | 249.9 | WebEngine still alive |
| isolated CC destroyed, loop returned | 124.3 | 285.7 | WebEngine helper exited; host libraries remain |
| full app Ready, second run | 666.6 | 1085.7 | 12.55 s; helper footprint 25.0 MiB; 56 total threads |
| full idle, 6 samples after settling | 87.4–110.5 | 1010.4–1035.9 | helper ~24.1 MiB; 52–54 threads; tree CPU 0.1% each sample |
| full app CC hidden, second run | 114.9 | 1011.0 | helper 24.2 MiB; all heavy imports remain |
| full app pause from prepared state | 83.2 | 1011.0 | helper 24.2 MiB; 53 threads; worker remains resident |
| full shutdown function returned, before process exit | 265.4 | 889.3 | heavy native modules remain; helper exited |
| provider pipeline after 41 real lookups | 547.9 | 879.1 | 19 threads |
| pipeline close before process exit | 548.2 | 879.1 | footprint unchanged |

The large RSS fall during idle with roughly stable footprint is a reason to
report both, not evidence that providers unloaded. No background compute-heavy
Python orphans were present in the initial host snapshot. Ordinary user apps and
WindowServer were active; this is not a controlled dedicated benchmark machine.

Warm lookup baseline: production provider pipeline over the checked-in 192×48
Korean fixture, center target, 40 warm samples after one cold call; a corner pixel
varied per sample to avoid reporting OCR cache hits as inference. Result SUCCESS.
Warm p50 **34.46 ms**, p95 **40.01 ms**; first call **240.34 ms** in this run.
This is pipeline callback time, not captured-screen or pixels-on-screen latency.
Provider preparation in this run: 9.04 s cumulative. No dwell change selected yet.
CPU immediately after lookups is not labeled idle CPU.

Probe implementation/raw records currently live under
`/private/tmp/hanly-wave-baseline.py` and `/private/tmp/hanly-wave-baseline/`;
all decision-relevant numbers are retained here if those temporary files expire.
Full app samples use a temporary runtime/app config and existing local KRDICT,
not the user's saved preferences. The CC-only probe suppresses OCR preload to
isolate UI cost and is explicitly not the unmodified production launch.
Native active-capture/input and complete stage/dwell measurements remain to do.

### 2026-09-10 — Reconciliation started

What changed: Created the authorized branch and live record before implementation.
Why: Preserve a resumable engineering record and an unchanged before baseline.
Evidence/result: Previous wave is integrated; current startup preloads OCR before
Qt and lets the Control Center own the event loop. These are investigation targets,
not yet replacement decisions. Developer dependency probe found psutil absent.
Files: `docs/CODE-MAP.md`; `CLAUDE.md`; architecture 01–04; execution manual 05;
previous HAN-40/41/42 and post-v0.1.3 handoffs.
Tests/measurements: None claimed yet for this wave.
Next: Inspect concrete ownership, verify Claude dispatch, gather native before data.

## Platform Validation

### macOS

- Before baseline: real source CC create/hide/destroy, full startup, idle,
  pause and shutdown, provider memory retention and Korean fixture lookup.
- After, source build: every lifecycle state A-H measured; hover verified over
  real screen pixels at 80, 40 and 20 ms dwell with micro-movement doing no
  work; preload policies measured; logs and diagnostics export exercised.
- After, frozen build: clean constrained release build, reconstructed ZIP,
  mounted DMG, complete inventory, `codesign --verify --deep --strict` valid,
  frozen worker and window self-checks outside the checkout and developer
  profile, the three-process split with the lookup child at 810.8 MiB, a clean
  `SIGINT` exit, and a 3 s `--update-ready` acknowledgement.
- Native source permission probe reports Screen Recording and Accessibility
  granted, and both were confirmed working by capturing the full screen and
  reading the fixture back. The first permission harness call used `snapshot`;
  corrected to the actual `statuses` API.
- **Pending human interaction:** an actual global hot key press (macOS does not
  match synthetic `CGEvent` against a Carbon hot key, verified directly), and
  closing and reopening the frozen Control Center window by hand.
- Previous HAN-41 measurements are historical, not this wave's baseline.

### Windows

- PRE-WAVE WINDOWS EVIDENCE supplied by user: shell/import graph ~32 MB WS;
  Control Center ~190 MB; Kiwi ~494 MB incremental; OCR/Torch ~490 MB
  incremental; full frozen idle process tree ~1.25–1.35 GB. Hiding UI and deleting
  native provider objects did not reclaim most memory; process termination did.
- Previous HAN-42 handoff records native frozen OCR/Kiwi/KRDICT/CC and accepted /
  rejected updater validation. This does not validate changes in this wave.
- Pending final native validation: source gates, spawn/frozen workers, dormant
  memory, preload/pause, cold/warm hotkeys and rebinding, CC close/reopen, popup,
  logs, shutdown, updater compatibility, complete frozen packaging.

### Linux

- PENDING FINAL NATIVE VALIDATION: spawn, X11 mouse/hotkeys, frozen runtime,
  CC lifecycle, popup, shutdown, archive packaging and symlinks.
- POSIX source checks run on macOS will not be labeled native Linux evidence.

## Current Risks

- `docs/architecture/01`-`04` and their visual companions still describe a
  single-process runtime. The split, the engine-state model and the retained
  hover target need a human-approved ADR before they become authoritative
  architecture; they were deliberately not rewritten here.

- Frozen spawn dispatch is proven with a minimal PyInstaller program, not yet
  with the real Hanly bundle; that is part of task 6.
- Qt prints `Release of profile requested but WebEnginePage still not deleted`
  while the Control Center child tears down. The child still exits and returns
  its memory; the warning is recorded rather than suppressed.
- Source UI permissions granted; frozen permission identity and clean release
  build still require validation.
- Frozen child dispatch and deterministic WebEngine cleanup require design/proof.
- Native Windows/Linux hosts unavailable in the current execution environment.

## Completed / Deferred

- Completed: every task in the plan. Seven commits on the feature branch, the
  final handoff in `review-handoffs/mvp-runtime-performance-wave.md`, source
  gates green on the working tree and in a clean constrained environment, and a
  validated frozen macOS artifact.
- Intentionally deferred future work: ONNX/other OCR adapters, persistent word
  cache, custom morphology, browser runtime, visual redesign, generic frameworks.
- Native-platform tests awaiting another host: Windows/Linux scenarios above.
