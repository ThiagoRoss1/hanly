# Post-runtime product fixes — Review Handoff

## Bundle

- Member issues: none; this executes `docs/execution/post-runtime-product-fixes.md`
  (T1–T11), which is FINAL after the macOS investigation in its section 4.2.
- Implementation ecosystem: macOS 26.6.2 (arm64), repository `.venv` on Python
  3.13.11, plus a clean Python 3.10.20 environment for the dependency floor.
- Date: 2026-09-11

## Implemented

- **T1** The Control Center child is startup-phase aware: a focus that arrives
  before its window exists is deferred instead of killing the only reply
  reader, and a close during startup leaves no orphan window. Ownership
  transitions are named, so two `show()` calls cannot both spawn and a reopen
  cannot race the window it replaces. Retirement, operation capacity and queued
  mutations are all scoped to the generation that owns them.
- **T2** Window generation, pid, readiness, exit code and terminal reason reach
  the one parent-owned diagnostic log. A call that runs out of time names its
  operation, id, age, and whether the window is still connected. Only shortcuts
  the operating system actually accepted are reported. The page shows a lost
  bridge with one explicit retry instead of rendering its own placeholder.
- **T3** One `ApplicationSnapshot`, derived in `runtime_status.py` from
  readiness, provider residency, capture intent, mute and stopping. Tray and
  page read the same label and detail.
- **T4** Start, Stop and the hover mute are three distinct things. Stop releases
  the providers under every preload policy including Always (P1), retires off
  the thread that asked, and cannot be undone by a residency request queued
  behind the engine start lock. The mute keeps the warm child.
- **T5** Both edges of a chord on both backends. Push to Hover is a real hold;
  auto-repeat is one activation; a press with capture stopped does nothing and
  does not latch. Start/Stop gets its own binding, with a migration that never
  moves a shortcut the user already has.
- **T6** A true exit dismisses in the callback that saw it. Only a bounded
  crossing along a narrow corridor towards the popup survives, and the exit has
  its own timer.
- **T7** The Control Center fits every supported width.
- **T8** The Control Center child is no longer a second macOS application.
- **T9** Repository dependency removal list stays empty, now with a clean-room
  build to say so from.
- **T10** Lifecycle assertions are about processes, not manager fields.

## Main expected behavior

Three global shortcuts: hold `Ctrl+Shift+Space` to hover, `Ctrl+Shift+F9` to
pause and continue hover, `Ctrl+Shift+F10` to start and stop capture. Stopping
gives the lookup engine's memory back; pausing hover does not. Nothing is
observed, captured or recognized while the hold is released. An answer already
on screen survives the release so it can be read and copied, and disappears the
moment the cursor leaves its word by any route but the popup. The interface
never says Running while the providers are still loading, and one Hanly appears
in the macOS Dock.

## Architecture / seams touched

No structural change. `LookupController` stays in the shell, providers stay
behind their interfaces, `ResourceManager` is untouched, and the three-process
split is unchanged. `HotkeyHandler` now carries a `HotkeyEdge`, and
`LookupRuntime.pause` became `stop` with a new `set_hover_muted`; both are
internal desktop seams.

**Approved during focused review (2026-09-12).** DAG-INV-05 now states the
three default global actions. One-shot lookup remains internally available
and bindable, without requiring a fourth default shortcut.

## Relevant files / diff areas

`packages/hanly-app/src/hanly_app/`: `control_center_process.py`,
`control_center_host.py`, `app_identity_darwin.py` (new), `qt_bootstrap.py`,
`runtime_status.py`, `application.py`, `desktop_controller.py`,
`manual_lookup.py`, `lookup_process.py`, `hover_lookup.py`, `hover_target.py`,
`hotkeys.py`, `hotkeys_darwin.py`, `config.py`, `control_center.py`,
`assets/control_center/*`. Tests under `tests/` and `tests/integration/`,
including new `tests/test_hover_exit_qt.py` and
`tests/integration/test_control_center_layout.py`.

## Implementation-side validation already run

- `python -m pytest` → 1161 passed, 3 skipped (repository `.venv`, 3.13.11).
- `python -m ruff check packages packaging tests tools benchmarks` → clean.
- `python -m mypy packages packaging tests tools benchmarks` → clean.
- `python -m pip check` → no broken requirements.
- Clean Python **3.10.20** venv, `pip install ./packages/hanly
  "./packages/hanly-app[runtime]"` from repository metadata only →
  `pip check` clean; full suite 1148 passed, 5 skipped; `hanly --self-check ui`
  ok; `hanly --self-check worker --self-check-image …` ok, reading
  `책을 읽습니다.` and resolving `한국어` to one dictionary entry.
- Native macOS, before and after each fix: the Control Center child registers
  as `UIElement` rather than `Foreground`; the Control Center at 780px went
  from `scrollWidth` 835 to 760; the double-open reproducer went from the
  supplied `ControlCenterUnavailable` traceback to three clean cycles; the
  lookup child and the window child both actually exit.

## Known limitations / intentionally unvalidated areas

- **Physical keys.** Every hold and toggle was exercised through the real
  `HotkeyService` and, on macOS, through Carbon with synthesized `CGEvent`s
  delivered by the window server. No human pressed a key. Windows and Linux
  ran neither: the pynput chord listener is new code that only CI and a human
  have exercised paths for.
- **The function-key defaults are inert on a default Mac.** Driving the
  production `HotkeyService` over the real window server, `ctrl+shift+space`
  delivered both edges and `ctrl+shift+k` delivered both edges, while
  `ctrl+shift+f9`, `f10`, `f11` and `f12` each registered successfully and then
  received nothing: the top row is media and system keys unless the user turns
  on standard function keys. So the hover pause (a default that predates this
  wave) and Start/Stop Capture are silently inert on macOS out of the box, and
  because registration succeeds the interface cannot tell. Push to Hover is
  unaffected. The defaults the plan specifies were shipped unchanged, because
  they are correct on Windows, on Linux, and on a Mac with standard function
  keys enabled; **choosing different macOS defaults is a product decision and
  is not made here.** See the plan's section 4.2, M7.
- **Carbon release order.** On macOS, releasing a modifier while the primary
  key stays down is not a release edge; Carbon reports the hot key released
  when its own key goes up. Measured, documented in the backend, not worked
  around.
- **WebEngine profile warning.** Reproduces intermittently at child exit and is
  upstream pywebview ordering. Three child-local remedies failed to make it
  deterministic; see the plan's section 4.2 (M5) for what was tried.
- **Mixed and fractional DPI.** All geometry was measured at DPR 1. The corridor
  half-width and the 4px word margin are unchanged constants and have not been
  checked on a Retina or mixed-scale arrangement.
- **Frozen Finder launch.** The accessory policy is a property of any process
  that creates a `QApplication`, and the fix lives in the code path source and
  frozen builds share, but a Finder launch of the signed bundle was not
  observed.
- **The popup `hidesOnDeactivate` hypothesis did not reproduce**, so nothing in
  the popup was changed. If the intermittent hide is reported again it needs a
  fresh observation, not this wave's assumption.

## Suggested review targets

- `ControlCenterProcess` ownership: the `_ChildPhase` transitions, and whether
  `close()` racing a reader EOF can leave the phase wrong.
- `LookupEngine._ensure(wake)`: whether a real lookup deliberately bypassing the
  guard can still resurrect an engine the user stopped.
- `ManualLookupRuntime` held state: every path that clears `_push_held`
  (rebind, unbind, mode change, Start, Stop, shutdown) and whether one is
  missing.
- `HoverLookupRuntime.set_accepting` and `_stop_observing_if_idle`: the mouse
  listener is created and destroyed per push, which is by design but worth a
  second opinion at high press rates.
- The corridor geometry in `hover_target.py` against a popup placed above or
  left of the word, which the tests only cover to the right.
- `config.AppConfig` migration: `capture_hotkey` may be the empty string, and
  every consumer of a binding should tolerate that.

## Review assignment

Human selected Codex/Astra for the focused review below. The final full-project
super-review remains separate.

## Focused technical review outcome — 2026-09-12

Reviewer: Codex/Astra, on macOS arm64. This is the human-authorized surface
review of `git diff main...HEAD`, plus directly affected boundaries; the final
project-wide super-review remains separate. Review baseline: `3f1eb81`.

### Reviewed and confirmed

The shell/Control Center/lookup ownership split, normalized provider seams,
final result-currency gate, configurable independent interaction bindings and
preservation of custom bindings in migration remain intact. Start/Stop and
hover mute remain distinct; separate dwell and exit timers avoid interference.
The responsive Control Center layout and parent-derived activity are retained.
No OCR model, backend, dependency-pruning or speculative optimization work was
introduced. The current F-key defaults were retained.

### Bugs found and fixed now

- Terminal SIGINT interrupted the lookup child independently of shell shutdown,
  producing the reported `KeyboardInterrupt`. Spawned roles ignore SIGINT before
  initialization; the shell owns their graceful shutdown and bounded retirement.
- Hotkey callbacks captured the generation when an event arrived, so a replaced
  listener could deliver late presses/releases as current. Callbacks now capture
  their registration generation, with the existing delivery-time check retained.
- Clearing/restoring a capture shortcut could duplicate live Carbon registrations
  or fail its replace-only operation. Native rebind now supports adding/removing
  one binding while keeping the other registrations.
- Closing a Control Center did not invalidate queued mutations until another
  window opened. Operation currency now also requires a live running owner.
  Reader EOF also reaps its child before dropping ownership.
- An already-submitted lookup and crash recovery could adopt residency after Stop.
  Their wake epochs are retained through the start boundary; deliberate new
  lookups after Stop remain allowed.
- A lost page connection did not cancel an already-running refresh interval.
  Failure now stops polling instead of repeatedly calling a disconnected bridge.
- Native smoke process inventories invoked POSIX `ps` on Windows. Windows now
  uses PowerShell/CIM process IDs and names; macOS/Linux retain `ps`. This path
  still needs native Windows execution.
- The approved three-action decision is reflected narrowly in DAG-INV-05, its
  visual companion, and manual-lookup companion text. Invariant numbering and
  order are unchanged; one-shot lookup stays internally available/bindable.

### macOS source validation

A real `.venv/bin/hanly` launch with an isolated preferences file and local
KRDICT/models reached ready with the lookup child loaded. Terminal Ctrl+C
returned 130 with no child traceback or WebEngine warning in that run. The exact
shell, resource tracker, Control Center, renderer and lookup PIDs were absent
once shutdown completed. The initial sandboxed launch could not reach the native
macOS services; only the subsequent unsandboxed run is native evidence.

The diagnostic log still recorded a late Control Center close notification as
`DesktopShuttingDown` during shutdown. Deferred as harmless shutdown log noise:
revisit in the final lifecycle review if it obscures real failures. pywebview
installs its own SIGINT handler for the UI child, so the common child bootstrap
specifically fixes the lookup interruption; it is not a claim of exclusive shell
signal handling throughout the third-party UI loop.

### Clean macOS frozen build

One clean PyInstaller build completed from the reviewed runtime tree, using
`/private/tmp/hanly-release-build/venv` (Python 3.10.20, system packages disabled,
repository packages rebound to this checkout). EasyOCR 1.7.2, PyInstaller
6.22.2 and hooks 2026.7 match `packaging/release-constraints.txt`; build-venv
`pip check` passed. This reused the isolated metadata-built dependency environment,
not the developer `.venv`; it was not a newly downloaded environment.

Outputs: `dist/macos/Hanly.app`, `dist/hanly-desktop-macos.zip`, and
`dist/hanly-desktop-macos.dmg`. Strict deep codesign verification and the DMG checksum verification passed.
The application build and ZIP succeeded in the sandbox; only `hdiutil` needed
native access, and the DMG was completed from that same app without rebuilding.

The full suite's three frozen gates passed: inventory, actual Korean fixture
through EasyOCR/Kiwi/KRDICT on an isolated profile, and window/JavaScript bridge.
A separate ordinary frozen launch reached ready with the heavy child loaded.
LaunchServices reported exactly one `Foreground` Hanly (shell) and one
`UIElement` Hanly (Control Center); the lookup child had no app registration.
SIGINT to the shell returned 130; the Control Center exited 0 and all recorded
owned PIDs disappeared. No child traceback or profile warning appeared in that
frozen shutdown.

**Still unverified:** interactive frozen Start/Stop, close/reopen and page Quit,
and a Finder-originated launch. The native UI tool timed out before those
interactions; the automatic source lifecycle tests are not substituted as frozen
proof. Thus the requested complete macOS interactive smoke/stop condition is
not fully closed. Carry these items into the next native review.


### Mechanical gates

- Full `.venv/bin/python -m pytest`: **1227 passed, 3 skipped, 2 failed** in
  124.12 s. Both failures were in test harnesses: macOS identity process-row
  parsing (introduced while making the other probes portable) and a hover test
  assuming its background worker was already ready. Both were corrected.
- Focused reruns: macOS identity **1 passed**; retained-target tests **23 passed**.
  Focused bug regressions also passed. The entire suite was not repeated after
  these test-only corrections, per the proportional-testing instruction.
- Ruff: clean. Mypy: clean, **195 source files**. Repository and build-venv
  `pip check`: no broken requirements. `git diff --check`: clean.
- Native source layout, lifecycle/reopen, bridge, lookup process retirement and
  the three frozen smoke gates passed in the full run. Windows/native and Linux
  native results remain unclaimed.

A tiny test-only readiness wait replaced a scheduling assumption; no production
hover behavior was changed to make that test pass.


### Remaining Windows native verification

Run from this final branch with the Windows authoritative venv. Verify source
and a clean frozen build: window open/close/reopen, working page bridge, one
shell and only its intended children, Start/Stop provider retirement, no child
resurrection after Stop, Ctrl+C/Quit cleanup, three custom binding changes,
clear/restore capture binding, held chord release and auto-repeat on pynput,
Korean OCR/Kiwi/KRDICT fixture, and no leaked renderer/lookup processes. Exercise
the PowerShell/CIM smoke probes. Observe DirectComposition warnings separately
from functional failures. macOS is not Windows evidence.

### Remaining Linux/native concerns

No new Linux investigation or expensive CI rerun was requested. Verify native
pynput press/release and modifier ordering, tray-dependent close behavior, and
window/child cleanup on the intended X11/Wayland environment. CI status must be
read for the pushed commit; this review does not claim a Linux native pass.

### Deferred QA/performance and product decision

Retest physical keys, sustained hold/rebind use, fractional/mixed DPI, popup
crossing geometry on real screens, CPU/memory residency and perceived latency in
the later QA/performance pass. No benchmarks or model optimization ran here.
The intermittent pywebview WebEngine profile warning remains a known upstream
teardown limitation; absence in one smoke does not prove it eliminated.

**Product decision pending: final default shortcuts, especially on stock macOS
where F9/F10-style bindings may be inert unless standard function keys are
enabled.**

### Diff produced by this review

The [review patch](patches/post-runtime-product-review.patch) captures the
Codex/Astra changes relative to `3f1eb81`, including the visual companion and
the new portable process-probe fixture, and excludes this handoff and the patch
itself. It is a record of that pass only: the second pass below amended several
of those files, so the patch no longer reconstructs the branch. Read the
commits instead.

## Second pass — human-requested review of the above, 2026-09-12

Reviewer: Claude, on macOS arm64, over the uncommitted Codex/Astra tree.
Baseline `3f1eb81`; everything below is committed on
`fix/post-runtime-product-fixes`.

### Confirmed in the first pass

The SIGINT child bootstrap (main thread, `terminate()`/SIGTERM unaffected,
target still picklable under spawn); moving the RUNNING settle before the
reader starts, which operation currency now requires; the `_child_exited` wake
capture that actually closes the post-Stop resurrection window; and the Carbon
add/remove/rollback paths, where `_unregister_one` already clears `_callbacks`
and `_held`. No leak, no behavior to correct in any of those.

### Corrected

- **The Windows process inventory was broken.** It selected `Name`, so every
  row read `python.exe`, while both smoke tests identify multiprocessing's
  resource tracker and the inventory command by command-line substring. Every
  Windows run would have reported a false leaked child, and a null parent id
  would have crashed the caller's unguarded `int()`. Now selects `CommandLine`
  with a name fallback, and skips rows with no pid or ppid. This is squarely in
  the Windows-pending checklist below and is still unverified natively.
- **The hotkey generation coupling was implicit.** `_callbacks` returned
  handlers bound to `self._generation + 1`, obliging three call sites to bump
  the counter exactly once afterwards with nothing enforcing it. The candidate
  is now a parameter, committed by name after the listener starts so a failed
  start leaves the running listener current. The handler became a named
  closure, which types cleanly and removes both the default-argument trick and
  the suppression it needed.
- **The lookup engine guarded one stop condition twice**, three lines apart,
  with different wording. One guard remains, immediately before the generation
  bump and the spawn. The `_ensure` docstring said a lookup carries its
  "submission" epoch; it reads the epoch on entry to the worker, which is the
  distinction the whole race turns on.
- **The EOF reap was silent.** A window it has to terminate is now reported the
  way an explicit close already reports it.
- **The refresh-timer stop moved to the state change.** It is scoped to the
  not-connected branch on purpose: `setConnection("connected")` runs before the
  snapshot is rendered, so deciding there starts a timer against the
  placeholder state. Caught by `test_control_center_refresh` on the first
  attempt; the narrower placement is what shipped.
- `canonical_hotkey` no longer rebuilds its modifier ordering per call.

### Repository-wide type-suppression cleanup

Reviewed as a separate concern and committed separately. 45 of 48 suppressions
were replaced; several had already gone dead with nothing reporting it, so
`warn_unused_ignores = true` is now set and the repository is clean under it.

Every replacement is an annotation, an identity call (`unchecked()`), or the
same attribute write spelled `setattr` — no runtime behavior was changed to
satisfy the type checker. Two production typing changes were reverted for
exactly that reason: the `live_telemetry` output checks, whose `hasattr`
duck-typing deliberately accepts any writable and must not be narrowed to the
declared union, keep their `[assignment]` suppressions. A test view's `move()`
override keeps `[override]`, being deliberately narrower than `QWidget`'s
`QPoint` overload; widening it traded a clear signature for an unpack that
fails differently.

The PyQt6 workaround was inspected specifically. The stubs declare
`connect()` with the slot alone, so the connection type goes through one local
untyped reference, confined to that statement and documented at both sites.
`PYQT_SLOT` is `Callable[..., Any] | pyqtBoundSignal`, so the removed
`[call-arg]` suppression was protecting nothing; the emitted call is identical.

### Gates for this pass

`pytest` 1229 passed, 3 skipped. Ruff clean. Mypy clean, 196 source files, with
`warn_unused_ignores` on. `pip check` clean. Focused reruns for every touched
area passed. macOS source only: this pass adds no native, frozen, Windows or
Linux evidence, and the pending checklists above are unchanged by it.
