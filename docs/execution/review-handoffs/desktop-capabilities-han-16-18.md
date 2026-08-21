# Desktop Capabilities Review Handoff

## Bundle

- Member issues: HAN-16, HAN-17, HAN-18
- Implementation ecosystem: GPT — Sol orchestrator with direct Luna xhigh workers
- Date: 2026-08-21

## Implemented

- An MSS-backed capture service with physical-monitor enumeration, monitor and
  region selection, cursor-centered ROI clipping, and ROI-local target
  coordinates.
- A Qt-independent popup controller for normalized `LookupResult` presentation,
  edge-safe placement, and show/update/hide/close lifecycle.
- An optional borderless, always-on-top PyQt6 popup plus a queued,
  non-blocking result dispatcher.
- UI-thread shutdown that closes the popup and requests
  `LookupController.stop(wait=False)`, avoiding the HAN-14 blocking-dispatch
  deadlock.
- A lazy pynput global-hotkey service for lookup, capture start, and capture
  pause actions, including normalization, duplicate detection, rollback, and
  clean unregister/shutdown behavior.
- Public lightweight `hanly_app` exports and desktop dependencies in the
  optional `runtime` extra.

## Main expected behavior

The desktop layer can capture a small ROI around a cursor, preserve the ROI's
screen origin and translate the cursor into ROI-local coordinates, deliver
global hotkey actions to application orchestration, and present a completed
provider-independent lookup result in a usable popup. Optional desktop
backends are initialized only when their concrete services are used.

## Architecture / seams touched

- Desktop capture boundary: `CaptureService -> CaptureBackend -> MSSBackend`.
- Presentation boundary: `LookupResult -> PopupController -> PopupView`.
- UI dispatch/shutdown: `QtResultDispatcher` and non-waiting
  `LookupController.stop`.
- Input boundary: `HotkeyService -> HotkeyAction` callback owned by application
  orchestration.
- Dependency direction remains `hanly-app -> hanly`; no provider construction,
  linguistic processing, or ResourceManager ownership moved into these
  services.

## Relevant files / diff areas

- `packages/hanly-app/src/hanly_app/capture.py`
- `packages/hanly-app/src/hanly_app/popup.py`
- `packages/hanly-app/src/hanly_app/qt_popup.py`
- `packages/hanly-app/src/hanly_app/hotkeys.py`
- `packages/hanly-app/src/hanly_app/__init__.py`
- `packages/hanly-app/pyproject.toml`
- `tests/test_capture.py`
- `tests/test_popup.py`
- `tests/test_hotkeys.py`

## Implementation-side validation already run

- Capture focused checks: 13 passed; focused Ruff and mypy clean.
- Popup focused checks: 7 passed; focused Ruff and mypy clean; offscreen Qt
  popup/dispatcher smoke check passed.
- Hotkey focused checks: 8 passed; focused Ruff and mypy clean.
- Bundle gate `.venv\Scripts\python.exe -m pytest`: **191 passed**.
- Bundle gate `.venv\Scripts\python.exe -m ruff check packages tests tools`:
  passed.
- Bundle gate `.venv\Scripts\python.exe -m mypy packages tests tools`: no issues
  in 49 source files.

## Known limitations / intentionally unvalidated areas

- Real monitor capture and OS-level global-hotkey registration were not
  exercised during implementation; deterministic backend/listener tests cover
  geometry, delivery, failures, and lifecycle. Platform interaction remains a
  review/manual-check target.
- PyQt rendering was checked offscreen, not visually reviewed on every desktop
  platform or scaling configuration.
- This bundle provides the three capability seams but does not compose the
  capture-to-lookup-to-popup path. That convergence belongs to HAN-19.
- Control Center, mouse observation, hover behavior, resource fetching, tray,
  and final desktop lifecycle composition remain outside this bundle.
- The known target-point-to-token correctness issue is unchanged. Capture now
  supplies a correct ROI-local target point, but token selection policy remains
  owned by HAN-19 and must be resolved before HAN-19 is functionally complete.

## Suggested review targets

- Multi-monitor geometry, negative virtual-desktop coordinates, clipping, and
  explicit region validation in `CaptureService`.
- Optional-backend import behavior and cleanup for MSS and pynput.
- Popup result formatting and placement at work-area edges and under display
  scaling.
- The queued Qt dispatcher and non-waiting UI-thread shutdown behavior against
  an in-flight lookup.
- Hotkey normalization, rollback after listener startup failure, and suppression
  of callbacks queued before unregister/shutdown.
- Scope containment: no premature manual-lookup, hover, Control Center,
  resource-update, or target-token implementation.

## Post-Bundle Review Outcome

- Reviewer: Claude (Opus 5)
- Review ecosystem: Claude, reviewing a GPT-implemented bundle
- Date: 2026-08-21
- Status: Closed. Capture and the Qt popup/dispatch path hold up under real
  hardware and real threading. The hotkey lifecycle did not: two defects were
  found by running it against a listener that behaves like pynput, and both are
  fixed with regression tests.

Gates after the review: **193 passed, Ruff clean, mypy clean across 49 source
files.**

### Fixed now

- **A hotkey handler that shuts the service down crashed with
  `RuntimeError: cannot join current thread`.** This is the most natural
  desktop wiring there is — a "quit" or "pause" hotkey whose handler calls
  `HotkeyService.shutdown()`. `pynput.keyboard.GlobalHotKeys` **is** a
  `threading.Thread` (verified against the installed library, not assumed) and
  runs hotkey callbacks on itself, so `_stop_listener`'s `join(timeout=1.0)`
  was joining the thread it was running on. Reproduced end to end before the
  fix:

  ```text
  === quit-hotkey: action handler shuts the service down ===
    outcome: RuntimeError: cannot join current thread
  ```

  `_stop_listener` now treats that `RuntimeError` as expected: stopping has
  already been requested, and waiting on yourself is neither possible nor
  needed. After the fix the same probe reports `outcome: clean`.

- **`_trigger` ran the application handler while holding the service lock**, so
  any other thread calling `unregister()`, `shutdown()`, `registered`, or
  `bindings` blocked for the entire handler duration. With a handler that takes
  a moment — opening a popup, running a lookup — a UI thread trying to shut
  down simply waited. This is the same class of defect as the HAN-14 blocking
  shutdown that this bundle set out to avoid. Measured before the fix:

  ```text
  shutdown() from another thread returned while handler ran: False
  BLOCKED: _trigger holds the service lock across the user callback
  ```

  `deliver()` now re-checks currency under the lock, releases it, and only then
  calls the handler. The narrow trade-off is deliberate and worth stating: a
  shutdown landing in the gap between the check and the call can still let one
  final action through. A momentarily late action is a far smaller problem than
  a shutdown that hangs, and it matches the currency-then-deliver shape already
  used elsewhere.

Both regression tests were confirmed to **fail without their fix**. The first
draft of the lock test passed either way — `RLock` is reentrant, so probing
from the handler's own thread proved nothing — and was rewritten to contend
from a second thread before it was trusted.

### Verified by running it, not by inspection

**The HAN-14 deadlock really is fixed.** The Qt path was driven with a real
`QApplication`, a real worker, and an in-flight lookup:

```text
dispatcher(...) returned in 0.1 ms (must not wait ~400 ms)
queued callback executed on UI thread: True
UI-thread stop(wait=False) returned: True after 12 ms
result delivered after shutdown: False (expected False)
```

The queued connection is genuinely non-blocking, UI-thread shutdown returns
immediately with work still running, and no stale result is delivered
afterwards. This is the claim the bundle most needed checked, and it holds.

**Capture was exercised on this machine's real dual-monitor setup**, which the
handoff listed as unvalidated:

```text
Monitor 1: ScreenRect(left=0, top=0, width=1920, height=1080)
Monitor 2: ScreenRect(left=-1920, top=0, width=1920, height=1080)
real capture at Point(960, 540): region (860, 490, 200x100), target (100, 50)
real capture at corner Point(0, 0): region (0, 0, 100x50), target (0, 0)
byte count matches RGB_888: True
```

MSS's virtual-desktop aggregate is correctly dropped, the negative-coordinate
monitor enumerates properly, and both a centred and a corner-clipped capture
produce correct regions, correct ROI-local targets, and exact RGB byte counts.
Synthetic probes additionally confirmed correct behavior for a monitor to the
left of the origin, a cursor on a shared monitor edge, an ROI larger than the
whole monitor, fractional cursor coordinates, and a cursor outside every
monitor.

### Recorded as a HAN-19 requirement

**The default dispatcher is inline, which contradicts what the service is
for.** `HotkeyService`'s docstring said the dispatcher exists "so a pynput
listener thread never runs application/UI orchestration directly", but with no
dispatcher supplied the handler runs on the listener thread — confirmed:
`handler ran on: Thread-4 (_loop)`. Changing the default would change behavior
for every existing caller, so only the docstring was corrected to describe what
actually happens.

This is **not deferred polish**. It is now an explicit V1 requirement on HAN-19,
recorded in that issue's scope, architecture constraints, acceptance criteria,
and validation:

- desktop composition must construct `HotkeyService` with a real, non-blocking
  UI dispatcher;
- callbacks must be posted to the UI thread and the dispatcher must return
  immediately;
- the inline default must not be relied on in the real desktop vertical slice;
- HAN-19 is not complete without it, and validation must confirm the dispatcher
  returns promptly while a slow handler is still running and that the handler
  does not execute on the pynput listener thread.

HAN-19's existing target-point-to-token correctness requirement is unchanged and
remains required before HAN-19 completion.

### Deferred considerations

- **`CaptureService.capture_at_cursor` re-enumerates monitors on every call** —
  10 captures produced 10 enumerations. Correct, and negligible for manual
  lookup, but hover is expected to fire every 80–250 ms and each enumeration is
  a display-system round trip. *Revisit at hover integration (HAN-20/21) with a
  measurement; cache with invalidation only if it actually costs something.*
- **`MSSBackend._mss_physical_monitors` falls back to keeping the aggregate.**
  When `monitors[0]` does not exactly equal the union of the rest, every entry
  is returned, so the virtual desktop would appear as a selectable "Monitor 1"
  and shift every index. It behaved correctly on this machine's two-monitor
  layout. *Revisit if a mixed-DPI or unusual arrangement is ever reported to
  enumerate a phantom monitor.*

### Dismissed

- **Qt dispatcher and non-waiting UI shutdown against an in-flight lookup.**
  Reviewed as a suggested target and measured above. No defect.
- **Multi-monitor geometry, negative coordinates, clipping, and region
  validation.** Exercised against both doubles and real hardware. Edge-clipped
  ROIs are correctly smaller than the configured size, the target point stays
  inside the returned region in every case, and `CaptureResult`'s invariants
  are enforced. No defect.
- **Optional-backend import behavior.** MSS, pynput, and PyQt6 are all imported
  lazily; importing `hanly_app` pulls in none of them. The engine and the
  lightweight CI path are unaffected.
- **Hotkey normalization and duplicate detection.** `shift+ctrl+k` and
  `ctrl+shift+k` canonicalize identically, duplicates across actions raise
  `DuplicateHotkeyError`, and a repeated key inside one binding is rejected.
  Correct.
- **Rollback after listener startup failure.** `register()` clears ownership
  and stops the partially constructed listener before re-raising; the existing
  test covers it and it survives the `_stop_listener` change.
- **Package dependency direction.** `hanly-app` imports `hanly`; no provider
  construction, linguistic processing, or ResourceManager ownership moved into
  these services.
- **Scope containment.** No manual-lookup, hover, Control Center,
  resource-update, or target-token implementation appears in the diff. The
  three seams are provided without composing them, as intended.

### Preserved V1 issues

Neither owned issue was touched, duplicated, or solved:

- **Target-point-to-token** remains required before HAN-19 is functionally
  complete. Capture now supplies a correct ROI-local target point, which is the
  input that policy will need, but the selection policy itself is unchanged.
- **UI-thread shutdown** is resolved for the Qt path by this bundle and
  verified above; the HAN-17 lifecycle decision it came from is unaffected by
  this review.

### Next bundle

HAN-16, HAN-17, and HAN-18 are closed. Both hotkey lifecycle defects are fixed
with regression coverage, the Qt dispatch path and multi-monitor capture are
validated against real hardware, and the two remaining observations stay
deferred behind their triggers. Nothing here blocks the next implementation
bundle.

The one item HAN-19 must not inherit silently — the inline dispatcher default —
is no longer an open review note: it is written into HAN-19 as a V1 completion
requirement.

## Typing, Readability, and Coverage Follow-up

- Reviewer: Claude (Opus 5)
- Date: 2026-08-21
- Scope: typing, readability, and coverage-boundary cleanup only. Capture,
  hotkey, popup, and dispatcher lifecycle semantics are unchanged, HAN-19's
  requirements are untouched, and the deferred findings above still stand.

Gates after this pass: **195 passed, Ruff clean, mypy clean across 49 source
files.**

### What changed

**`capture.py` — the MSS session is described, not erased.** `Callable[[], Any]`
and the `getattr(screenshot, ...)` reads are gone. MSS ships `py.typed`, but it
is an optional extra that the lightweight CI install omits, so importing its
concrete types — even under `TYPE_CHECKING` — would make type checking depend on
an install the engine path deliberately avoids. Two small private Protocols
(`_MSSScreenShot`, `_MSSSession`) describe exactly the four members this adapter
touches, and `_MSSSessionFactory` names the injection seam. The screenshot
`size` is typed `Sequence[int]` rather than a fixed pair because MSS returns its
`Size` named tuple, and `rgb` is `bytes | bytearray` because the buffer type is
not guaranteed — the length check that used to compensate for `Any` now reads as
what it is: boundary validation.

`MSSBackend.close()` calls `self._session.close()` directly instead of
discovering it with `getattr`; the session Protocol requires it, and the test
double gained a `close()` that the existing test now asserts against.

**`hotkeys.py` — the adapter no longer suppresses attribute checking.**
`_PynputListener` stored its listener as `object` and carried
`# type: ignore[attr-defined]` on both `start()` and `stop()`, plus a `getattr`
probe for `join`. `types-pynput` (the typeshed stub distribution, 12 KB, added
to the dev dependency group) supplies real types, so the listener is now typed
`keyboard.GlobalHotKeys` behind a `TYPE_CHECKING` import — the concrete import
stays lazy inside the factory. `GlobalHotKeys` derives from `threading.Thread`,
so `start`, `stop`, and `join(timeout)` are all checked. All three suppressions
are gone and `keyboard.GlobalHotKeys(...)` construction is now type-checked
rather than opaque.

**`qt_popup.py` — `Any` removed from our own interface.**
`QtPopupRuntime(lookup_controller: Any)` is now
`lookup_controller: LookupStopper`, the Protocol `PopupRuntime` already
consumes — no new abstraction, and `LookupController.stop(wait=...)` satisfies
it.

**Readability.** `CaptureService.capture_at_cursor` was one dense 48-line block
mixing monitor selection, region validation, ROI geometry, backend capture, and
backend-response validation. Region validation moved to `_resolve_clip_bounds`
and capture-plus-validation to `CaptureService._grab`, leaving the public method
as four readable phases. The MSS request/response normalization moved into
`_mss_region` and `_mss_capture`, and the lazy import into
`_import_mss_factory`. `_coerce_action` no longer rebuilds its alias table on
every call. Missing blank lines between top-level definitions and inside dense
loops were restored.

### `# pragma: no cover` review

Both pragmas this bundle introduced are gone, replaced by real tests. Neither
needed environment manipulation: assigning `None` into `sys.modules` is the
documented way to make an import fail, and `monkeypatch.setitem` unwinds it.

- `capture.py` optional-MSS import — covered by
  `test_mss_backend_reports_a_missing_mss_installation`.
- `hotkeys.py` optional-pynput import — covered by
  `test_register_reports_a_missing_pynput_installation`, which also asserts the
  rollback leaves the service unregistered and never touches OS-level
  registration.

No pragma was kept, and no coverage hack was added to chase a number. The three
pragmas in `tools/dev_lookup.py` are outside this bundle and were left alone.
Worth noting for whoever wires coverage later: nothing in the repository
currently *reads* these markers — there is no coverage configuration — so they
were documentation, not suppression.

### Removed suppressions

| Removed | Where | Replaced by |
| --- | --- | --- |
| `Callable[[], Any]`, `cast(..., Any)` | `capture.py` MSS factory | `_MSSSessionFactory` / `_MSSSession` |
| `getattr(screenshot, "size"/"rgb")` | `capture.py` `grab` | typed `_MSSScreenShot` members |
| `getattr(self._session, "close")` | `capture.py` `close` | `_MSSSession.close()` |
| `# type: ignore[import-untyped]` | `hotkeys.py` pynput import | `types-pynput` stubs |
| `# type: ignore[attr-defined]` ×2 | `hotkeys.py` `start`/`stop` | `keyboard.GlobalHotKeys` |
| `getattr(self._listener, "join")` | `hotkeys.py` `join` | `Thread.join` via the same type |
| `lookup_controller: Any` | `qt_popup.py` | `LookupStopper` |

### Boundary suppressions kept, and why

- **`cast(Any, signal).connect(...)` became `# type: ignore[call-arg]`.** The
  cast was hiding a real PyQt6 limitation, so it was narrowed rather than
  removed. Verified against the installed stubs: `pyqtBoundSignal.connect` is
  declared with a single `slot` parameter only, so passing
  `Qt.ConnectionType.QueuedConnection` produces
  `Too many arguments for "connect"`. The queued connection type is
  load-bearing — it is what makes dispatch non-blocking when a caller emits from
  the UI thread — so it stays, with the narrowest possible suppression. The
  signal object itself remains fully typed.
- **`_stop_listener`'s `getattr(listener, "join", ...)`.** `HotkeyListener`
  intentionally requires only `start`/`stop`, and any caller-supplied
  `listener_factory` may return something without `join`. This is the seam
  working as designed, not a typing gap.
- **`CaptureService.close`'s `getattr(self._backend, "close", ...)`.** Same
  reasoning: `CaptureBackend` does not require `close`, because only a backend
  that owns a display session has anything to close.
- **`except Exception` around the MSS import.** Preserved as written. Narrowing
  it to `ImportError` would change behavior on a platform where importing MSS
  fails for a non-import reason.

### CI type-check gap found and closed

The bundle gates were green locally, where the `runtime` extra is installed. CI
installs only the dev dependency group plus the two packages without extras, so
`mss` and `PyQt6` are absent there and `mypy` would have failed with
`import-not-found` on `capture.py` and three lines of `qt_popup.py`. Confirmed
by re-running the type check with site packages excluded.

The fix follows the convention already in `pyproject.toml` for `paddleocr`,
`kiwipiepy`, and `PIL`: `mss.*` and `PyQt6.*` were added to the same per-module
`ignore_missing_imports` override. This is scoped to optional external
libraries — no global mypy setting was relaxed — and it is inert locally, where
both packages ship their own typing and mypy keeps using it. `pynput` needs no
override, because stub-only distributions resolve whether or not the runtime
package is installed.

### Validation

- Focused suites `test_capture.py`, `test_popup.py`, `test_hotkeys.py`:
  **32 passed**.
- Full suite: **195 passed** (193 before, plus the two optional-import tests).
- `ruff check packages tests tools`: clean.
- `mypy packages tests tools`: no issues in 49 source files.
- Type check re-run with optional extras excluded: the `mss` and `PyQt6` errors
  are gone.
- Behavior re-verified by running it, not by inspection:
  - Real dual-monitor capture through the retyped MSS path — `Monitor 1
    (0, 0, 1920x1080)`, `Monitor 2 (-1920, 0, 1920x1080)`, ROI
    `(860, 490, 200x100)` with ROI-local target `(100, 50)`, exact RGB byte
    count, and a clean `close()` through the Protocol member rather than
    `getattr`.
  - Real pynput registration through the retyped `_PynputListener` —
    `GlobalHotKeys` constructed, started, and shut down cleanly, with the
    binding normalized to `<ctrl>+<shift>+<f24>`.
  - Offscreen Qt popup with a real `QApplication`, a slow worker, and an
    in-flight lookup — popup placed, UI-thread shutdown returned in **0.5 ms**,
    popup hidden afterwards.

### MSS deprecation — resolved

Found during this pass and initially deferred; **now fixed**. MSS 10.2.0
deprecates the `mss.mss()` factory in favour of `mss.MSS`, so `MSSBackend()`
construction raised under `-W error::DeprecationWarning` (silent under default
warning filters). `_import_mss_factory` now returns `mss.MSS`.

The two are the same construction — `mss.mss(**kwargs)` is a thin wrapper that
returns `MSS(**kwargs)` — so capture behavior is unchanged, and `MSS()` takes
no positional arguments, which keeps it a drop-in for the
`Callable[[], _MSSSession]` seam. The import stays lazy inside
`_import_mss_factory`, the private Protocol boundary is untouched, and the
`factory=` injection seam needed no adjustment, so the existing doubles still
work as written.

`MSS` became a public export in 10.2.0, so `packages/hanly-app`'s runtime extra
moved from `mss>=10,<11` to `mss>=10.2,<11`. That raises the floor inside the
already-intended major rather than widening the range, and 10.2.0 is the latest
release on PyPI. No other dependency range changed: `pynput>=1.8,<2`,
`PyQt6>=6.7,<7`, `Pillow>=10,<13`, and `types-pynput>=1.8` all already admit
their current latest releases (1.8.2, 6.11.0, 12.3.0, 1.8.1.20260712), and every
one of those is what is installed here.

`test_default_factory_uses_the_current_non_deprecated_mss_api` locks it in: it
asserts the factory is `mss.MSS` with `DeprecationWarning` escalated to an
error, and does not construct a display session, so it stays safe headless
(`importorskip` handles an install without the extra).

Re-verified on this machine's real dual-monitor layout through `mss.MSS`, with
`DeprecationWarning` promoted to an error:

```text
constructed with no DeprecationWarning; session: MSS
Monitor 1 ScreenRect(left=0, top=0, width=1920, height=1080)
Monitor 2 ScreenRect(left=-1920, top=0, width=1920, height=1080)
cursor (960, 540):   region (860, 490, 200x100)   target (100, 50)  bytes_ok=True
cursor (0, 0):       region (0, 0, 100x50)        target (0, 0)     bytes_ok=True
cursor (-1920, 0):   region (-1920, 0, 100x50)    target (0, 0)     bytes_ok=True
cursor (-960, 540):  region (-1060, 490, 200x100) target (100, 50)  bytes_ok=True
close is idempotent; real dual-monitor path OK
```

Geometry is identical to the `mss.mss()` results recorded above, including the
negative-coordinate monitor and both corner-clipped ROIs.

Gates after this fix: **196 passed** (focused capture/popup/hotkey suites: 33
passed), Ruff clean, mypy clean across 49 source files.

## Future backend direction

`mss` and `pynput` are pragmatic V1 choices: one cross-platform dependency each
for capture and global hotkeys, cheap to install and adequate for the desktop
slice. They are not a commitment.

Native per-platform capture and hotkey backends remain valid future
alternatives, but they should be pursued only on evidence — a measured problem
in capture latency or throughput under hover, a permissions or reliability
issue, a platform-integration need these libraries cannot express, or concrete
Wayland/macOS behavior that they handle poorly. Speculative rewriting to "be
native" is not a reason.

What makes that decision cheap later is the abstraction already in place, and
keeping it that way is the actual requirement: `CaptureBackend` and
`HotkeyListener`/`HotkeyListenerFactory` are the only places that know these
libraries exist, and the private MSS Protocols added above narrow that knowledge
further. `CaptureService`, `HotkeyService`, the popup, and everything in `hanly`
must continue to depend on the seams rather than on `mss` or `pynput` directly,
so a native backend stays an added adapter rather than a refactor.

This is not a request to implement native backends now.

## Review assignment

Human-selected after implementation. Review completed 2026-08-21 — see the Post-Bundle Review Outcome above.
