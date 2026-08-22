# HAN-34 Basic Control Center

## Scope

HAN-34 adds the first pywebview Control Center surface without pulling in
hover integration, tray behavior, update delivery, or the final desktop shell.
The bridge exposes only normalized app/config/resource state and small desktop
actions. It does not construct an OCR provider, open dictionary storage, or
perform linguistic processing.

## Bridge contract

`hanly_app.control_center.ControlCenterBridge` exposes these pywebview methods:

The constructor accepts the current app config/controller and either a real
`ResourceManager` or the existing `HanlyRuntime` (from which it reads the
validated manager); no provider object is passed into the bridge.

- `get_state()` returns `app`, `config`, `runtime.resources`, and `updates` as
  JSON-compatible primitives. Resource rows are derived from the real
  `ResourceManager` metadata (`status`, `version`, `compatible`, checksum, and
  diagnostics), with the manifest kind included for model/dictionary clarity.
- `start_capture()` and `stop_capture()` delegate to the existing desktop
  lifecycle (`start` / `pause`).
- `set_capture_mode()`, `set_target()`, `set_region()`, `set_hover_delay()`,
  `set_hotkey()`, and `update_settings()` validate through the existing config
  and capture value types.
- `check_for_updates()` and `install_update()` raise
  `ControlCenterUnavailable`; the snapshot and UI mark these controls
  unavailable until HAN-24/HAN-25.

The JavaScript bundle has no provider, database, OCR, morphology, or dictionary
logic. It only renders snapshots and invokes bridge actions.

## Windows Qt coexistence path

`ControlCenterHost.open()` is intentionally main-thread-only. It creates one
pywebview window and calls `webview.start(gui="qt")`. pywebview 6.2.1's Qt
backend uses `QApplication.instance()` when one already exists and enters the
same Qt event loop; it does not create a second Python thread or a second GUI
process. `prepare_control_center_qt()` must run before the popup/runtime creates
the shared `QApplication`, because Qt WebEngine requires its module (or the
shared-OpenGL-context attribute) to be established first. The application then
dispatches `ControlCenterHost.open` on that same Qt UI thread. Closing the last
Control Center window returns from pywebview's nested Qt loop to the existing
popup loop.

The supported `tools/dev_alpha.py` launcher calls this preparation hook before
constructing its `QApplication`, so the later Control Center host can reuse the
already-running popup application without violating WebEngine startup order.

This is bounded source-level evidence from the installed pywebview 6.2.1
implementation. The runtime dependency is declared in
`packages/hanly-app/pyproject.toml`.

Bounded native probes were run after installing the declared Qt extra. On the
implementation host, a `QWebEngineView` could be constructed but the host
terminated as soon as the external renderer started; that was recorded as an
open limitation rather than reported as success.

**That limitation did not reproduce during review on a normal Windows desktop
host.** `QWebEngineView` loaded inline HTML cleanly (`loadFinished ok=True`),
and a full `ControlCenterHost.open()` ran pywebview inside an already-created
`QApplication` alongside an ordinary Qt widget, returned from the nested loop
when the window closed, and left `QApplication.instance()` unchanged. The
renderer failure was therefore specific to the implementation host, not to
Hanly's startup ordering or composition. macOS and Linux remain unexercised.

## Review corrections

Rendering the window revealed that the UI showed only placeholder data.
`control_center.js` captured `window.pywebview.api` into a module constant at
script-parse time, but pywebview injects that object after the document loads.
The constant stayed `null`, so `invoke()` returned early on every call,
including the `pywebviewready` handler; the page never left its fallback state
and every control was inert. The bridge is now resolved per call.

Measured in a real window before and after that change:

| | before | after |
| --- | --- | --- |
| resource rows | 1 (placeholder) | 3 |
| ocr provider | `-` | `PaddleOCR` |
| capture target options | 1 | 3 |

Two further bridge gaps were closed. `set_hotkey` and `update_settings` now
validate through the desktop `canonical_hotkey`, so a spelling the listener
could never register cannot reach the config file. `set_hover_delay` is bounded
by the named `HOVER_DELAY_MIN_MS`/`HOVER_DELAY_MAX_MS` range (20-2000 ms).

Nothing constructed the bridge or host, so the Control Center could not be
opened at all. `tools/dev_alpha.py` now builds it from the real runtime,
capture service, and `ConfigManager`, and opens it after startup. That wiring
is a development affordance for human testing; the application lifecycle/tray
owner decides how end users open the window.

## Focused checks

```text
.\.venv\Scripts\python.exe -m pytest tests/test_control_center.py -q
11 passed

.\.venv\Scripts\python.exe -m ruff check packages/hanly-app/src/hanly_app/control_center.py tests/test_control_center.py
All checks passed!

.\.venv\Scripts\python.exe -m mypy packages/hanly-app/src/hanly_app/control_center.py tests/test_control_center.py
Success: no issues found in 2 source files
```
