# Automatic Hover Runtime Review Handoff

## Bundle

- Member issues: HAN-20, HAN-21, HAN-22, HAN-23, HAN-34
- Implementation ecosystem: GPT execution flow with Sol coordination and Luna xhigh implementation workers
- Date: 2026-08-22

## Implemented

- Added lifecycle-safe global mouse observation with normalized screen points and UI dispatch.
- Added configurable hover debounce, stability, monotonic request identity, and cancellation/invalidation state.
- Added the pywebview Control Center bridge and packaged responsive HTML/CSS/JavaScript surface for local app, resource, provider, capture, and settings state.
- Attached automatic hover to the existing manual runtime so both triggers share one capture service, bounded worker/controller, `LookupPipeline`, dispatcher, and popup presenter.
- Added final hover-owned request-currency suppression without making cursor movement indiscriminately cancel unrelated manual work.
- Made the supported development alpha start automatic hover while retaining `Ctrl+Shift+Space` manual lookup, and prepared Qt WebEngine before creating the shared `QApplication`.
- Added representative automatic-hover E2E scenarios through the real pipeline composition seam.

## Main expected behavior

The development alpha observes global cursor movement. After the cursor remains stable for the configured delay, Hanly captures one cursor-centered ROI on the UI thread, runs the existing lookup pipeline on its bounded worker, and presents only a still-current `LookupResult` through the existing popup. Moving again, pausing capture, or shutting down suppresses stale automatic work; the manual hotkey remains available through the same runtime path.

The Control Center can render normalized local runtime/resource state and round-trip its basic settings/actions without importing provider libraries or accessing dictionary storage in JavaScript.

## Architecture / seams touched

- `MouseObserver` observes OS cursor events; `HoverController` alone decides stability.
- `ManualLookupRuntime` is now the aggregate manual/automatic desktop composition and exposes `start`, `pause`, `resume`, `invalidate`, and `shutdown` lifecycle operations.
- `HoverLookupRuntime` tracks only hover-owned lookup request IDs over the existing `LookupController`; no second provider, worker queue, or pipeline exists.
- Capture remains UI-dispatched; OCR, morphology, and dictionary work remain worker-owned.
- `ControlCenterBridge` consumes normalized `ConfigManager`, `ResourceManager`, capture, and lifecycle seams.
- `prepare_control_center_qt()` establishes WebEngine startup order before the shared Qt application is constructed.

## Relevant files / diff areas

- `packages/hanly-app/src/hanly_app/mouse_observer.py`
- `packages/hanly-app/src/hanly_app/hover_controller.py`
- `packages/hanly-app/src/hanly_app/hover_lookup.py`
- `packages/hanly-app/src/hanly_app/manual_lookup.py`
- `packages/hanly-app/src/hanly_app/control_center.py`
- `packages/hanly-app/src/hanly_app/assets/control_center/`
- `packages/hanly-app/src/hanly_app/__init__.py`
- `packages/hanly-app/pyproject.toml`
- `tools/dev_alpha.py` and `tools/README.md`
- `tests/test_mouse_observer.py`
- `tests/test_hover_controller.py`
- `tests/test_hover_lookup.py`
- `tests/test_hover_lookup_e2e.py`
- `tests/test_control_center.py`
- `packages/hanly-app/src/hanly_app/qt_hover_scheduler.py`
- `packages/hanly-app/src/hanly_app/capture.py`
- `packages/hanly-app/src/hanly_app/popup.py`
- `packages/hanly-app/src/hanly_app/config.py`
- `packages/hanly-app/src/hanly_app/hotkeys.py`
- `packages/hanly-app/src/hanly_app/lookup_controller.py`
- `tests/test_package_imports.py`
- `tests/test_qt_hover_scheduler.py`
- `tests/test_capture.py`
- `tests/test_popup.py`
- `docs/execution/reports/han-34-control-center.md`

## Implementation-side validation already run

Final gates, run after the closeout cleanup pass:

- `python -m pytest` -> 265 passed.
- `python -m ruff check packages tests tools` -> all checks passed.
- `python -m mypy packages tests tools` -> no issues in 65 source files.
- `git diff --check` -> clean.

The cleanup pass was validated with focused tests for the renamed hover
scheduler, the Control Center bridge, capture, and popup (41 passed) before
the full suite above. No further native probe campaign was needed: the rename
and typing change did not alter runtime behavior.

## Applied Review Fixes

A focused review ran before human alpha testing and exercised the bundle
against the real runtime. Every finding below was reproduced by running the
code, not by reading it. No later issue was started and no commit was made.

### Fixed

1. **The Control Center rendered only placeholder data.**
   `control_center.js` captured `window.pywebview.api` at script-parse time,
   but pywebview injects that object after the document loads. The constant
   stayed `null` for the lifetime of the window, so `invoke()` returned early
   on every call - including the `pywebviewready` handler - and every button,
   dropdown, and field was inert. The bridge is now resolved per call, and the
   script also requests state directly when the ready event already fired.
   Rendered in a real window, the page went from 1 placeholder row to the 3
   real resources, `PaddleOCR`, and 3 real capture targets.

2. **The Control Center was unreachable.** No application code constructed
   `ControlCenterBridge` or `ControlCenterHost`; `tools/dev_alpha.py` paid the
   full Qt WebEngine import for a window that could not be opened. The
   developer alpha now builds the bridge from the real runtime, capture
   service, and a `ConfigManager`, and opens the Control Center after startup.
   It runs the same Qt event loop, so hover and the manual hotkey stay live
   while it is open, and closing it returns to the ordinary alpha loop. This
   is explicitly a development affordance; the later application lifecycle
   owner decides how end users open this window.

3. **A fatal lookup failure left hover capturing the screen forever.**
   `JobExecutor` is single-use, so a worker factory that cannot construct its
   providers - missing models on a first run - moves it to `failed`
   permanently. Hover kept observing, kept capturing a cursor ROI on every
   stable point, and every submission raised `JobExecutor is not running` into
   an error handler the alpha did not supply. The user saw one error popup and
   then silence, while screen capture continued indefinitely.
   `LookupController` now reports whether it is still `accepting`, and the
   hover runtime treats a non-accepting controller as fatal: it stops
   observation, stops capturing, reports one diagnostic, reports
   `running == False` and `failed == True`, and refuses to resume until the
   process restarts. No retry or restart lifecycle was introduced and no
   persistent technical popup was added; a future recovery policy stays open.

4. **`invalidate()` deregistered the global mouse listener.**
   `ManualLookupRuntime.pause()` was an alias for `invalidate()`, so dropping
   the current attempt also stopped OS observation until an explicit resume.
   `invalidate()` now delegates to `HoverLookupRuntime.invalidate()` - which
   already existed and was never called - and `pause()` alone stops
   observation.

5. **The configured hover delay was inert.** No composition read
   `AppConfig.hover_delay_ms`; the alpha used `HoverController`'s hardcoded
   150 ms, and the Control Center persisted the setting with no runtime
   effect. Both compositions now accept an `app_config` and resolve the delay
   from it, and the developer alpha loads a `ConfigManager` that the Control
   Center then edits.

6. **Invalid hotkeys could be persisted.** The bridge validated delays,
   regions, targets, and capture modes but not hotkeys, so `"!!!"` and
   `"ctrl+ctrl+a"` reached the config file and would fail at the next
   startup's hotkey registration. `set_hotkey` and `update_settings` now go
   through the desktop canonicalizer, which was exposed as `canonical_hotkey`
   and tightened to reject punctuation-only key names pynput could never
   register.

7. **One OS thread per cursor movement.** The Qt composition inherited the
   `threading.Timer` fallback scheduler, so every mouse event created and
   cancelled a thread (measured 0.119 ms per movement) only to marshal the
   result back to the UI thread. `QtHoverScheduler` reuses one single-shot
   `QTimer` on the Qt thread that already dispatches movement. Measured on the
   real composition: 50 movements, zero thread growth.

8. **Unbounded hover delay.** `set_hover_delay` accepted 1 ms and 10^9 ms.
   `HOVER_DELAY_MIN_MS`/`HOVER_DELAY_MAX_MS` (20-2000 ms) are now the one
   named V1 range, enforced by both `AppConfig` and the bridge. Architecture
   V1's empirical 80-250 ms tuning window sits inside it.

### Deleted Speculative API Surface

All of the following had zero non-test consumers: `MouseObserver`'s `on_move`
alias, `HoverController`'s `on_hover` and `hover_delay_ms` aliases, its
`handle_position`/`handle_move`/`stop`/`close` aliases, its
object-with-`schedule()` scheduler coercion branch, `HoverRequest.position`,
and `create_hover_lookup` (exported but never called). Each seam now has one
spelling.

### Final Cleanup Pass

Applied after the startup investigation, before human closeout:

- `control_center._screen_rect` built its arguments in a dict and expanded them
  with `**`, which mypy could not narrow, so it carried
  `# type: ignore[arg-type]`. It now reads each bound through a small
  `_region_bound` helper and constructs `ScreenRect` explicitly. Same
  validation semantics, no suppression, no `cast`.
- `qt_scheduler.py` was renamed to `qt_hover_scheduler.py` (and
  `tests/test_qt_scheduler.py` to `tests/test_qt_hover_scheduler.py`) so the
  module is not mistaken for application-wide scheduling infrastructure.
  `QtHoverScheduler` keeps its name; all imports, tests, and documentation
  references were updated. The broader Qt module layout was deliberately left
  alone for post-V1 cleanup.
- Imports affected by the rename were re-sorted; no new `noqa`, `type: ignore`,
  or `cast` was introduced. The lazy `QtHoverScheduler` import inside
  `create_qt_manual_lookup` was preserved because PyQt6 is an optional extra.

### Corrected Evidence

The previously recorded limitation - that this host terminated when the
WebEngine renderer started - **does not reproduce**. `QWebEngineView` loads
inline HTML cleanly, and `ControlCenterHost.open()` runs pywebview inside the
alpha's existing `QApplication`, returns from the nested loop on close, and
leaves `QApplication.instance()` unchanged. That was an implementation-host
problem, not a Hanly one. macOS and Linux remain unexercised.

## Evidence

### Automated-Test-Backed

- Stability controller, mouse observer, hover runtime, and Control Center
  bridge behavior (existing suites, updated for the single spellings).
- Hover delay bounds accepted and rejected at both edges, and hotkeys
  validated through the desktop canonicalizer
  (`tests/test_control_center.py`).
- The UI script resolving the bridge after injection rather than at parse time
  (`tests/test_control_center.py`).
- A fatal worker-factory failure stopping observation, stopping further
  captures, surfacing exactly one diagnostic, and refusing to resume
  (`tests/test_hover_lookup.py`).
- `invalidate()` keeping observation alive while `pause()` stops it
  (`tests/test_hover_lookup.py`).
- The configured `AppConfig.hover_delay_ms` reaching the scheduler
  (`tests/test_hover_lookup.py`).
- `QtHoverScheduler` firing on the Qt thread, cancelling cleanly, replacing a
  pending delay across 50 reschedules, and creating no threads
  (`tests/test_qt_hover_scheduler.py`).

### Real/Manual-Evidence-Backed

Run on a normal Windows desktop host.

**Control Center reachability**, through the real `run_dev_alpha` runner with
real resources: the window opened with title `Hanly - Control Center`, 3
resource rows, `PaddleOCR`, 3 capture-target options, and the real
`hover_delay` and `hotkey` values; closing it returned to the alpha, which
exited 0.

**Fatal hover failure**, on the real Qt composition with provider construction
failing:

```text
scheduler in use : QtHoverScheduler
start:         running=True  failed=False mouse=True
after failure: running=False failed=True  mouse=False
captures taken        : 1
listener stop() calls : 1
hover errors surfaced : [('automatic hover disabled', 'JobExecutor is not running')]
threads before/after  : 2/2
captures after 50 more moves: 1 (was 1)
resume(): correctly refused -> automatic hover is unavailable until Hanly is restarted
```

Popup placement during hover, real global mouse hooks over real Korean text,
and Control Center visual/interaction behavior remain manual-check items for
human alpha testing.

## Startup Failure Investigation

A fresh `python tools/dev_alpha.py` reported two diagnostics before any user
interaction. They were investigated separately and had unrelated causes.

### Root cause 1 - `hover capture: no monitor contains cursor`

pynput's move events can carry **pre-clamp** coordinates. Sweeping the cursor
on the real dual-monitor host showed the OS clamping the pointer while the
hook reported the unclamped value:

```text
monitors: 1: x[0,1920) y[0,1080)   2: x[-1920,0) y[0,1080)
requested (2200,540)  -> OS reports (-1, 540)   pynput delivered (2200, 540)
requested (960,1300)  -> OS reports (-1,1079)   pynput delivered (960, 1300)
requested (-2400,540) -> OS reports (-1920,540) pynput delivered (-2400, 540)
```

`CaptureService._select_monitor` requires strict containment, so those events
matched no monitor and raised. Every coordinate source agrees on this host
(Win32, pynput, and Qt all report the same position; DPI awareness is
per-monitor and both screens are at scale 1.0), so this was never a DPI or
coordinate-space mismatch, and a cursor genuinely on either display always
resolved correctly.

A cursor outside every monitor rectangle now resolves to the nearest monitor
and is clamped onto it, so a pre-clamp event still captures. An explicit
`monitor=` selection still rejects an outside cursor, and having no monitor at
all is still a real `CaptureError`.

### Root cause 2 - `automatic hover disabled: JobExecutor is not running`

Independent of the capture failure, and not caused by it. The executor's
worker factory genuinely failed:

```text
executor error item=None error=PaddleOCRProviderError: PaddleOCR is unavailable:
[WinError 1114] ... Error loading ".venv\Lib\site-packages\torch\lib\c10.dll"
```

Provider construction happens lazily on the worker thread, which is created
after Qt. Importing PyQt6 first changes the process DLL search path, and
PaddleOCR's native dependency chain then fails to load. Isolated per-process
checks:

| import order before building providers | result |
| --- | --- |
| no Qt | providers OK |
| PyQt6 only | providers FAIL |
| PyQt6 + Qt WebEngine | providers FAIL |
| `paddle` then Qt | providers FAIL |
| `torch` then Qt | providers OK |
| `paddleocr` then Qt | providers OK |

So this is PyQt6 in general, not the Control Center's WebEngine preparation.
`tools/dev_alpha.py` now imports the OCR library before any Qt import. A
missing library remains non-fatal and is reported rather than raised.

The fatal-executor behavior is unchanged: a genuinely fatal worker failure
still disables hover until restart. A transient capture failure was already
non-fatal and remains so.

### Stop-capture popup state

Stopping capture left the last popup on screen, so a stale error or result
stayed visible for work that was no longer running. `PopupController.clear()`
hides the popup and drops the result it was showing, `ManualLookupRuntime`
calls it from `pause()` only, and the developer alpha passes the runtime to
the Control Center bridge so its Stop button reaches that path. `invalidate()`
deliberately does not touch the popup. Popup formatting, wording, auto-hide
timing, OCR lifecycle, and the broader meaning of stopping capture are
unchanged.

### Validation

Real `python tools/dev_alpha.py` now starts with only its readiness line - no
capture or executor diagnostics. On the real dual-monitor host:

```text
hover.running True   hover.failed False   mouse observing True
controller accepting True
capture monitor 1 (960,540)    -> OK ScreenRect(left=860, top=490, ...)
capture monitor 2 (-960,540)   -> OK ScreenRect(left=-1060, top=490, ...)
capture pre-clamp (2200,540)   -> OK ScreenRect(left=1819, top=490, ...)
capture pre-clamp (960,1300)   -> OK ScreenRect(left=860, top=1029, ...)
capture pre-clamp (-2400,540)  -> OK ScreenRect(left=-1920, top=490, ...)
real lookup through shared worker -> UNUSABLE (normal non-success)
controller accepting after real lookup: True
popup visible/result before stop : True / ERROR
popup visible/result after stop  : False / None
hover diagnostics over whole run : NONE
```

Focused tests cover the nearest-monitor fallback, both physical monitors, the
no-monitor failure, `PopupController.clear()`, and pause clearing the popup
while `invalidate()` does not.

## Remaining Known Issues / Runtime Constraints

Each item below is classified so a future reader does not have to re-derive
its severity. Findings already fixed in this bundle are recorded as resolved
in the sections above and are deliberately not repeated here.

### Runtime/platform constraint: Windows Qt / PaddleOCR native-library bootstrap

**Status: worked around in the developer alpha; unowned in production.**
**Owner: HAN-26 (Desktop V1 Integration) for the startup path, HAN-27**
**(Packaging) for the packaged build. Do not treat this as dev-only.**

Proven behavior, reproduced with isolated single-purpose processes on Windows:

- PaddleOCR provider construction fails with a native DLL load error when
  PyQt6 has initialized first:
  `[WinError 1114] ... Error loading ".venv\Lib\site-packages\torch\lib\c10.dll"`.
- This is **not** specific to the Control Center or Qt WebEngine. Importing
  plain PyQt6 and constructing a `QApplication` is sufficient to reproduce it.
- The executor builds providers lazily on its worker thread, so without an
  explicit preload the first OCR-native import happens *after* Qt has already
  initialized and changed the process DLL search path.

| import order before building providers | result |
| --- | --- |
| no Qt | providers OK |
| PyQt6 only | providers FAIL |
| PyQt6 + Qt WebEngine | providers FAIL |
| `paddle` then Qt | providers FAIL |
| `torch` then Qt | providers OK |
| `paddleocr` then Qt | providers OK |

`tools/dev_alpha.py` currently works around this by calling
`_preload_ocr_runtime()` before any Qt import; a missing library stays
non-fatal and is reported rather than raised.

**Required follow-up.** The production application bootstrap must preserve
this ordering or deliberately replace it, and must then re-verify it on the
packaged Windows build. PyInstaller and similar packagers change DLL
resolution, so the current preload must be validated rather than assumed to
remain correct. If provider construction is ever moved earlier, or Qt
initialization later, re-run the import-order probe above before concluding
the constraint no longer applies.

### Real unresolved product defect: SIGINT / Ctrl+C does not stop the alpha

**Status: unresolved. Owner: HAN-26.**

`main()` catches `KeyboardInterrupt` and returns 130, but Qt's event loop does
not deliver SIGINT to Python, so that handler never runs. Verified by sending
SIGINT to a running `python tools/dev_alpha.py`: the process was still running
afterwards and had to be terminated. Closing the Qt application exits cleanly;
only the terminal interrupt path is affected. Not fixed here because it
belongs to the application lifecycle owner rather than this bundle.

### Harmless external-library diagnostic: Chromium DirectComposition

**Status: reproducible, non-blocking, no action needed.**

`ERROR:direct_composition_support.cc ... QueryInterface to IDCompositionDevice4
failed` is printed by Chromium inside Qt WebEngine. It appears on every run
that imports WebEngine, including alpha startups that never open the Control
Center, and does not prevent rendering: pages load (`loadFinished ok=True`),
the Control Center renders real data, and the window closes cleanly. Treat it
as external log noise, not a Hanly defect.

### Manual validation still pending

Not functionally validated by any automated or real probe in this bundle:

- Popup placement and readability while hovering over real Korean text.
- Real global mouse hooks driving a full hover lookup end to end on screen
  (the pipeline was exercised with real providers, but through injected
  movement and direct submission, not by a human hovering).
- Control Center visual and interaction behavior under real clicking, beyond
  the DOM-level assertions already recorded.
- macOS and Linux: entirely unexercised.

### Post-V1 UX / performance / polish items

- Changing the hover delay or hotkey in the Control Center persists to config
  but applies at the next start; live re-binding belongs to the desktop-shell
  owner (HAN-26), not this bundle.
- After a fatal lookup failure, automatic hover stays disabled until the
  process restarts. A recovery/restart policy is deliberately deferred past
  V1 and should be reconsidered only with real evidence.
- Opening the Control Center at alpha startup is a development affordance
  only. The application lifecycle/tray owner may replace it entirely.
- Control Center target/region state is exposed at the bridge boundary; final
  desktop-shell convergence with all capture preferences remains owned by
  HAN-26. Update actions stay unavailable until HAN-24/HAN-25.
- The approved HAN-19 proportional line-mapping limitation is unchanged.
  Revisit only if real evidence shows materially wrong selection for
  variable-width or mixed-script OCR lines.
- Monitor enumeration happens only after hover stability when an ROI capture
  is requested, not on raw mouse events. Revisit during final platform
  performance validation if measurement shows it affects lookup latency.
- HAN-35 and all other post-V1 hardening remain out of scope.

## Suggested review targets

- Verify final request currency when manual and automatic triggers interleave, especially pause/resume and shutdown ownership.
- Inspect that repeated movement leaves at most one pending timer and one pending worker item.
- Check the pre-`QApplication` WebEngine preparation contract and the documented host-specific native limitation.
- Inspect the Control Center bridge boundary for provider/storage leakage and validate the UI/settings round trips on a real desktop host.
- Confirm the E2E tests traverse the shared `LookupWorker`/`LookupPipeline` path rather than a hover-specific substitute.

## Review assignment

Human-selected after implementation. Review applied; stopping for human alpha testing.
