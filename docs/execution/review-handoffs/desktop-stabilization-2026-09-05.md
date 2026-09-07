# Hanly Desktop stabilization Review Handoff

## Bundle

- Member issues: no Linear records were consulted for this run. The work is
  identified by the part IDs of
  [the stabilization plan](../../superpowers/plans/2026-09-05-windows-stabilization.md),
  Parts 1–8, authorized as one implementation bundle, plus the bounded
  completion pass R1–R6 authorized in
  [the resumption report](../reports/desktop-stabilization-resumption-2026-09-05.md).
- Implementation ecosystem: Claude Opus 5, Claude Code, direct sequential
  execution. Windows 10 19045, `.venv` Python 3.13.11, PyQt6 6.10.2 / Qt 6.10.0,
  PyQt6-WebEngine 6.10.0, pywebview 6.2.1, pystray 0.19.5, kiwipiepy 0.23.2,
  easyocr 1.7.2, torch 2.13.0+cpu, PyInstaller 6.22.2. CI builds on Python 3.10.
- Dates: implementation 2026-09-05; completion pass 2026-09-06.
- Starting evidence:
  [the Windows release investigation](../reports/windows-release-investigation-2026-09-05.md).

## Implemented

- **Part 1** — The shared `QApplication` is built with a program name. Qt
  WebEngine initializes Chromium's command line from the application arguments
  and aborts without argument zero, which is what killed v0.1.0 on Windows.
- **Part 2** — `kiwipiepy`, `kiwipiepy_model`, and the top-level `_kiwipiepy`
  extension are collected unconditionally, outside the loop that may skip an
  absent optional package. A build that cannot collect them now fails. The spec
  also carries Qt/pywebview/pystray metadata so a frozen process can report the
  versions it is really running.
- **Part 3** — Runtime readiness is its own observable state
  (`runtime_status.py`); provider-construction failures reach a dedicated
  callback carrying the original exception instead of being dropped; and
  everything Hanly reports about itself also lands in a rotating per-user log
  (`diagnostics.py`), including Qt's own fatal messages.
- **Part 4** — One Qt bring-up (`qt_bootstrap.py`) and one window and
  event-loop owner (`control_center_host.py`). pywebview's `start` is the loop;
  the desktop's competing `QApplication.exec()` is gone.
- **Part 5** — The interface opens first. `startup.StartupCoordinator` resolves,
  provisions, and validates off the UI thread behind the visible window, and
  the launch asks nothing.
- **Part 6** — The capture target and region are persisted preferences chosen
  from settings (`select_capture_area` bridge action), not a launch-time prompt.
- **Part 7** — Responsibilities split across the new modules; CODE-MAP, README,
  and `packaging/README.md` describe the delivered behavior.
- **Part 8** — `hanly --self-check` drives the real runtime and the real window
  through the one entry point; `tools/smoke_packaged_runtime.py` and three
  integration tests gate a frozen bundle; every native CI job now checks the
  produced artifact before retaining it and records that artifact's identity.

### Completion pass R1–R6

- **R1 — one UI-thread dispatch seam.** Lifecycle actions arrived on
  pywebview's bridge thread and reached Qt-owned capture, hotkeys, and popup
  directly. `_DesktopSession._on_qt` is now the single seam, and `start`,
  `pause`, `resume`, `apply_config`, `set_capture_preferences`, `shutdown`,
  `begin_shutdown` and the new `quit` all cross it. Suspend → overlay → restore
  moved out of `ControlCenterBridge` into the session, so a selection is one
  indivisible dispatched action and a cancelled one cannot leave observation
  switched off.
- **R2 — a route back, or no hiding.** `TrayService.can_restore_window` reads
  the backend's real capability rather than assuming a started tray is a usable
  one, and "Open Control Center" is now also the icon's default action, which
  is the only route pystray's Xorg backend offers. `_start_tray` allows
  hide-on-close only when a route exists, and records why when it does not. The
  main window carries **Quit Hanly**, so ending the session never depends on a
  tray.
- **R3 — a genuinely cold profile.** The smoke harness redirected only the
  settings root, so a frozen run could still read the developer's `~/.EasyOCR`
  cache. It now redirects settings, home, and all three model locations EasyOCR
  consults. `--model-cache DIR` seeds the isolated directory explicitly, which
  keeps the deterministic offline scenario available and distinct from the cold
  online one.
- **R4 — the frozen window, not just its providers.** New
  `hanly --self-check ui` opens the real main window through the production
  host, waits for its document and pywebview's injected bridge, has the page
  call `get_state`, and closes it. Driven by
  `tools/smoke_packaged_runtime.py --window-only`, by
  `tests/integration/test_packaged_desktop.py`, and by a new CI step.
- **R5 — retry teardown that neither blocks nor leaks.** `StartupCoordinator`
  now releases on its own preparation thread, *before* the next attempt rather
  than beside it, so a replacement can never be composed over providers that
  still hold their models and database handles. `_DesktopSession.release`
  dispatches only the detach; the provider join and the update coordinator's
  shutdown happen off Qt, and the coordinator is retired rather than orphaned.
- **R6 — validation and reconciliation.** This document, the checkpoint, and
  the three READMEs now match the evidence rather than the intent. A saved
  region that no longer applies is stated on the page instead of silently
  becoming whole-monitor capture.
- **Beyond R1–R6: the process exit.** Validating R4 turned up a defect none of
  the six named — Hanly could complete its own shutdown and then fail to end
  the process. It is in scope because the gate that found it is, and because
  leaving it would mean shipping a Quit that does not always quit. Diagnosis,
  the two wrong answers before the right one, and the measurements are below.

## Main expected behavior

Launching any of the three launchers opens the Control Center and nothing else.
Resource preparation and provider warm-up happen behind that window, reported as
`preparing` → `ready`, or `failed` with the real cause, a log path, and a retry.
Nothing observes the screen until the user presses Start. Where Hanly looks is
chosen from settings and saved; cancelling changes nothing, and a region that no
longer applies is named on the page. Closing the window hides it only when the
tray can bring it back, otherwise the window stays open. Quit is available from
the window and from the tray, ends the one event loop, and releases the worker's
providers.

A frozen bundle that cannot look a word up, or cannot open its window, now fails
its own build.

## Architecture / seams touched

No invariant was renumbered and no approved decision was redefined; the
Markdown/diagram pairs are untouched. The work stays inside existing seams:

- `CA-INV-06` (heavy work off the UI thread) is strengthened twice: resource
  resolution, provisioning, and validation moved off Qt, and so did the wait
  for a released runtime during a retry.
- `CA-INV-13` still holds — providers receive validated paths from composition,
  never a `ResourceManager`.
- `CA-INV-14` untouched: bounded/latest-wins submission and the final
  request-currency check are unchanged. Startup failure is reported through its
  own channel rather than as a fabricated `LookupResult`.
- The `LookupController` / `LookupPipeline` and `ResourceManager` /
  `UpdateService` boundaries are unchanged. `hanly` gained nothing.

New desktop-side seams: `RuntimeStatus` / `RuntimeStatusPublisher`,
`StartupCoordinator`, `ControlCenterHost`, `ensure_qt_application`,
`DiagnosticLog` (moved out of `application.py`), `paths.py`, and
`_DesktopSession._on_qt` as the one place a lifecycle mutation crosses onto Qt.

## Relevant files / diff areas

- New engine-side: none.
- New app modules: `hanly_app/{qt_bootstrap,control_center_host,startup,runtime_status,diagnostics,paths,self_check}.py`.
- Reworked composition: `hanly_app/application.py` (`_DesktopSession` plus a
  short `run_desktop`), `hanly_app/cli.py` (`run_selected_desktop` → `run_hanly`).
- Behavior changes: `capture_selector.py`, `config.py`, `control_center.py`,
  `tray.py`, `job_executor.py`, `lookup_controller.py`, `manual_lookup.py`,
  `hover_lookup.py`, `composition.py`, `runtime.py`.
- UI: `hanly_app/assets/control_center/*`.
- Packaging and CI: `packaging/hanly-desktop.spec`, `.github/workflows/build.yml`,
  `tools/smoke_packaged_runtime.py`.
- Tests: `tests/{test_runtime_status,test_startup,test_qt_bootstrap,test_control_center_host,test_diagnostics}.py`,
  `tests/integration/*`, and updates to `test_application`, `test_app_config`,
  `test_capture_selector`, `test_control_center`, `test_ci_workflows`,
  `test_packaging`, `test_tray`.
- Docs: `README.md`, `packaging/README.md`, `docs/CODE-MAP.md`.
- Resumable state: `docs/execution/checkpoints/desktop-stabilization-2026-09-05.md`.

## Implementation-side validation already run

Run from `C:\Hanly` with `.venv\Scripts\python.exe`. This session's sandbox
denies pytest's default cache and temp roots, so runs used
`-p no:cacheprovider --basetemp=<scratchpad>`; nothing else was affected.

| Check | Result |
|---|---|
| `pytest` (whole suite, integration included) | **856 passed, 4 skipped, 0 failed, in 88 s. All three frozen gates run against the bundle that would ship** |
| `ruff check packages packaging tests tools benchmarks` | clean |
| `mypy packages packaging tests tools benchmarks` | clean, 162 files |
| `pytest tests/integration/test_webengine_startup.py` | 2 passed — the shared application loads a document in a real `QWebEngineView`; an empty argument list still aborts with "the program name is not passed" |
| `pytest tests/integration/test_control_center_lifecycle.py` | 1 passed — one window, one backend start, the page called the bridge, hide/restore twice, Quit destroyed the window, no nested-loop warning |
| `pytest tests/integration/test_desktop_startup.py` | 1 passed — the real `run_desktop` opened the window, prepared behind it, reached `ready`, and exited 0 without starting capture |
| `python -m hanly_app --self-check ui` (source) | exit 0 — window opened, document loaded, 4 controls rendered, `get_state` answered `EasyOCR`, loop exited cleanly |
| `tools/smoke_packaged_runtime.py <extracted v0.1.0> --inventory-only` | exit 1: `kiwipiepy`, `kiwipiepy_model`, `_kiwipiepy extension` and three model files missing — reproduces the released defect |
| `python tools/build_package.py --platform windows` (2026-09-06, final) | build complete, exit 0, about 18 minutes. `hanly-desktop.exe` 54,218,693 bytes; `dist/hanly-desktop-windows.zip` 613,494,401 bytes, SHA-256 `b1f74d9bd5ddc5bc4f9c6e1c791a8df82be41a8cbdcf05b10e74e74eff95bac7` |
| `tools/smoke_packaged_runtime.py dist/windows/hanly-desktop --inventory-only` (new bundle) | ok, nothing missing: `kiwipiepy`, `kiwipiepy_model`, `easyocr`, `_kiwipiepy.pyd`, and the three sampled model files |
| `tools/smoke_packaged_runtime.py … --image …/korean_reading_roi.png` (new bundle, cold isolated profile) | **ok, exit 0, `exit_timeout: false`, `frozen: true`** — runtime 244 ms, lookup worker 36.3 s, OCR read `책울 읽습니다.` in 5.5 s, Kiwi analyzed `한국어` in 2.5 s, KRDICT returned 1 entry in 60 ms |
| `tools/smoke_packaged_runtime.py … --window-only` (new bundle) | **ok, exit 0, `exit_timeout: false`, `frozen: true`** — the window opened and the loop exited cleanly in 847 ms, the document loaded as `Hanly · Control Center`, 4 controls rendered, and the page's own `get_state` answered `EasyOCR` |
| Frozen exit rate, `--self-check ui` × 12 (new bundle) | **12/12 exited 0.** The bundle before the exit fix managed 7 of 10, the other three ending `3221227010` after writing a complete green report |
| Frozen version reporting | The new bundle reports `PyQt6 6.10.2`, `PyQt6-WebEngine 6.10.0`, `pywebview 6.2.1`, `pystray 0.19.5`. The previous one said `not installed` for all four, so the `copy_metadata` spec addition is verified rather than assumed |
| **R3 evidence**, from the cold worker runs | The isolated profile ended up holding `models/model/craft_mlt_25k.pth`, `models/model/korean_g2.pth`, and `profile/Hanly/resources/krdict/krdict.sqlite3`. The bundle fetched every one of them: no developer model cache and no developer dictionary were reachable, and online provisioning through the release channel ran end to end |

Five real defects were found by these gates and fixed: the mandatory-Kiwi
collection (the released bug, reproduced then corrected); a
`UnicodeEncodeError` when the self-check printed Korean to a Windows console
codepage; the model-cache leak that let a "cold" frozen run read the
developer's `~/.EasyOCR`; the harness capturing a frozen run through a pipe —
Qt WebEngine's helper processes inherit that handle on Windows, so a finished
process could still look like a hang, and the harness now reports through
files, which is what turned a misleading diagnosis into a precise one; and the
process exit described next.

### Hanly could finish its work and then fail to end the process

This one took three diagnoses to get right, and only the third survived
measurement. It is recorded in full because the first two were plausible.

**What was seen.** Three whole-suite runs saw the frozen window check time out
with the child having **already written a complete report, every stage green** —
window opened, document loaded, four controls rendered, the page's own
`get_state` answered — and then not left. One of those logs carried:

```text
Qt QtWarningMsg: Release of profile requested but WebEnginePage still not
deleted. Expect troubles !
```

That warning is real and its source is in pywebview, not Hanly: its Qt backend
calls `page().deleteLater()` and then `_app.exit()` on the next line
(`webview/platforms/qt.py`), so the deferred deletion never gets the loop turn
it needs and the page outlives the profile that owns it.

**First fix, and the defect it introduced.** `cli.main` was changed to end the
process itself via `os._exit` once Hanly's own shutdown had finished, rather
than unwind into interpreter finalization. That removed the hang — and
introduced an intermittent Windows fail-fast. Measured over the resulting
bundle, 3 of 10 runs exited `0xC0000602` (`STATUS_FAIL_FAST_EXCEPTION`), every
one of them *after* writing a complete green report. Trading a rare hang for a
frequent crash-on-exit is not a fix, and a release gate cannot tell a user's
crash reporter that this one does not count.

**The measurement that settled it.** Rather than guess again at 25 minutes per
rebuild, a minimal frozen probe was built — pywebview and Qt WebEngine only, no
Torch — that opens a real window, closes it, and then leaves by a strategy named
on its command line. Twelve runs each:

| exit strategy | clean exits |
|---|---|
| return normally, full interpreter finalization | 12/12 |
| `os._exit` | **1/12** — eleven `3221227010` (`0xC0000602`) |
| delete the page, drain `DeferredDelete`, then `os._exit` | **0/12** |
| `TerminateProcess` on the current process | **12/12** |

The third row is the one that matters: fixing the Qt page/profile ordering
first changes nothing, so the profile warning was **not** the cause of the
fail-fast. The cause is `ExitProcess`, which `os._exit` reaches on Windows: it
stops Chromium's threads wherever they happen to be and *then* runs every
loaded library's detach handler, and Chromium intermittently fails fast out of
that unload. `TerminateProcess` skips the unload entirely.

**The fix.** `cli._leave` flushes the streams and then calls
`_terminate_without_unloading`, which on Windows terminates the current process
with Hanly's own status, falling through to `os._exit` on every other platform
and whenever the call is refused. By that point everything Hanly owns is
already closed — providers, the lookup worker, SQLite handles, the tray, the
window — and each diagnostic record is flushed as it is written, so nothing
depends on finalization running. Checked separately: the status survives
(`TerminateProcess(…, 3)` reports exit 3, four for four), and no Chromium
helper process is orphaned, because they live in a job object that dies with
the parent.

One trap is worth naming for the next reader. Called through `ctypes` without
`argtypes`, `TerminateProcess` silently *fails*: the `GetCurrentProcess`
pseudo-handle is narrowed to 32 bits, the call returns false, and the process
then leaves the ordinary way — which looks exactly like success. The first
probe run made that mistake and reported a clean 12/12 for a call that never
happened. The production code sets `argtypes`/`restype` explicitly and the
comment says why.

**Confirmed on the real bundle**, not only on the probe: the rebuilt executable
exited `0` twelve times out of twelve, where the one before it managed seven of
ten. The harness still records the two facts separately — whether the check
passed, and whether the process exited (`exit_timeout`) — so a regression here
is named precisely instead of reading as "the frozen window is broken".

### Building this bundle needs a machine with room

Five rebuild attempts were killed mid-analysis by this host's low-memory guard
while PyInstaller collected Torch. The sixth, run with other
applications closed, completed in about 26 minutes: roughly 20 in the import
graph — which writes nothing to `dist/` and so looks stalled — and 5 in
COLLECT. Anyone reproducing the artifact should expect that, and several GB
free.

The frozen worker smoke has the same appetite: it loads Torch and two OCR
models inside the executable, and was itself killed once when about 1.4 GB was
free. Both are host limits rather than product behaviour, but they decide
whether the gates can run at all.

## Native acceptance matrix

| Environment | Required acceptance | State |
|---|---|---|
| Windows native desktop | Full monitor/region, mixed DPI, hover/hotkey, popup, pause/resume, tray restore, Quit, no new crash events | **automated acceptance complete; manual matrix not run.** Passing: WebEngine startup, window lifecycle (hide/restore/Quit), interface-first startup to `ready`, and — against the bundle that would ship — the frozen inventory, the frozen cold provider smoke, and the frozen window opening and answering its own page. Not exercised: mixed DPI, real hover/hotkey lookup and popup on screen, pause/resume by hand, tray restore by hand, crash-event review |
| macOS native desktop | Packaged and terminal launch; denied/granted screen-capture and keyboard permissions; display scaling; main-thread/tray integration; restore/Quit | **not run** — no macOS host available |
| Linux X11 desktop | Capture/input with a real display, WebEngine dependencies, tray with/without menu capability, window-accessibility fallback, restore/Quit | **not run** — no Linux host available |
| Linux Wayland session | Explicitly evaluate full-desktop input/capture and record support status | **not run** — no Linux host available |

Exit classification: **Windows implementation and frozen acceptance complete;
native macOS/Linux acceptance and the Windows interactive matrix pending.**
Publication and any cross-platform completion claim remain blocked.

## Known limitations / intentionally unvalidated areas

- **The process exit is a Windows-specific mechanism.** `TerminateProcess` is
  measured on Windows, where the defect was; macOS and Linux still leave
  through `os._exit`, which has no equivalent library-unload step but has not
  been exercised natively either.
- **pywebview's page/profile ordering is still wrong upstream**, and is left
  alone deliberately. Hanly no longer reaches interpreter finalization, so the
  ordering cannot bite it; poking Qt internals from the host to correct a
  third-party teardown would be new surface for no measured gain.
- **The frozen window gate can be slow enough to look stuck.** It is bounded at
  600 s and passes in seconds on a settled machine. Nothing here rules out a
  genuine hang on a platform that has never run it.
- **macOS and Linux were never executed.** Every fix is in shared code and one
  spec builds all three, but that establishes applicability, not proof. The
  macOS pystray `darwin_nsapplication` integration is still unexercised; the
  Linux `_xorg` tray's missing menu is now handled by a real capability check
  and a default action rather than by assumption, but that check has never run
  against pystray's Xorg backend.
- **The new CI window gate is a soak on macOS and Linux.** It is blocking on
  Windows and `continue-on-error` on the other two for one release, because no
  native run of it exists and a first GUI gate should not block a release on a
  platform nobody has seen it pass. Its report is retained either way. Making
  it blocking is a deliberate follow-up, not a cleanup.
- **Wayland** is not evaluated at all. A visible window is not evidence of
  global capture or input there.
- **No CI step in this workflow has ever executed.** The inventory, worker, and
  window gates cannot run without a push.
- **The frozen worker smoke is now cold by default.** With the model cache
  isolated, a run with no `--model-cache` downloads EasyOCR's models, so both CI
  and the local suite are network-dependent and slower. That was chosen over a
  check a developer cache could quietly satisfy, and it immediately paid for
  itself: the cold run above is the first end-to-end evidence of online
  provisioning.
- **`QApplication.quit()` blocks when called from a non-Qt thread** on this
  host. Every path now marshals: the tray through the Qt dispatcher, the
  window's Quit through `_on_qt`, SIGINT on the main thread, the update
  coordinator through its dispatch.
- **pywebview owns SIGINT** once the window exists: its `create_window`
  replaces the handler `QtSignalBridge` installs. Its handler calls
  `_app.quit()`, which reaches `aboutToQuit → shutdown()`, so shutdown stays
  idempotent — but Ctrl+C behaviour is now pywebview's.
- **`AppConfig` allows region mode with no region** on purpose: a monitor can
  disappear between sessions, and refusing to load settings would be worse than
  degrading to whole-monitor capture. The page now says so; the log does not.
- **`select_capture_area` from settings runs a modal overlay on the Qt thread**
  while pywebview's bridge thread waits (600 s cap). A user who leaves the
  overlay open blocks that one bridge call.
- **Update install/restore was not re-exercised end to end** after the session
  refactor; its unit tests pass and the dispatch paths are unchanged in shape.
- **No test covers a first launch with no network.** The cold *online* path is
  now proven end to end, but the offline failure and warm offline recovery
  paths still are not: `first_run` covers provisioning failures in unit tests
  only.

## Suggested review targets

- **The one dispatch seam.** `_DesktopSession._on_qt` decides on
  `threading.current_thread() is threading.main_thread()`. That holds for
  Hanly, where pywebview's Qt backend runs the loop on the process main thread;
  check whether any path could make it false and silently take the direct
  branch.
- **Loop and shutdown ownership, and the hard exit that follows it.** The
  `ControlCenterHost.run` / `DesktopApplication.run` / `shutdown` /
  `aboutToQuit` chain, and whether any path can leave the process alive with no
  window — especially the non-restorable close and `quitOnLastWindowClosed`
  around `select_capture_area`. `cli._leave` then terminates once that chain
  returns, so the question for a reviewer is whether anything is expected to
  run after it: an `atexit` hook, a `__del__` with real work, or a buffered
  writer Hanly does not flush itself.
- **Release ordering.** `StartupCoordinator._release_previous` runs before
  `_prepare` on the same thread and refuses to continue when release raises;
  check that a superseded attempt cannot release a *live* runtime.
- **The tray capability probe.** `getattr(icon, "HAS_MENU", True)` defaults to
  permissive for a backend that does not declare it. A reviewer who knows
  pystray's backends may prefer the opposite default.
- **Packaging completeness beyond Kiwi.** The inventory list is deliberately
  small; a reviewer may know of other by-name imports PyInstaller misses.
- **The window self-check's probes.** `UI_PROBE_ELEMENTS` names four ids and
  the bridge round-trip is a real `get_state` from the page. Whether that is the
  right minimum for a release gate is worth a second opinion.
- **Bridge surface growth.** `ControlCenterBridge` gained
  `select_capture_area`, `retry_runtime`, `quit`, `set_retry`, and
  `attach_runtime`; worth checking that none leaks a provider or a Qt object.
- **Missing tests worth considering:** offline cold start; a monitor removed
  between sessions; a second `run_desktop` in one process; a real hover lookup
  reaching the popup.

## Review assignment

Human-selected after implementation. Not started.
