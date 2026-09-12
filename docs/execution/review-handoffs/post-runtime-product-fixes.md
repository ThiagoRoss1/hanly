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

**Proposed, not applied.** `DAG-INV-05` says "Manual Hotkey Lookup remains a V1
feature". The capture-and-submit path is unchanged and reachable through
`ManualLookupRuntime.lookup_at_cursor()`, and a client may still bind it, but
the desktop no longer gives it a default shortcut: that combination is now the
hold. Whether the invariant's wording should be clarified is a human decision;
nothing in `docs/architecture/` was edited.

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

Human-selected after implementation. Not started.
