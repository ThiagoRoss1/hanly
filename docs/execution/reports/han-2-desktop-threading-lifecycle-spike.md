# HAN-2 Desktop Threading / Lifecycle Spike

Status: **REVISED AFTER POST-BUNDLE REVIEW**

This report records a directly executable, Windows-only evidence experiment. It
does not add desktop production behavior, choose a UI architecture, or act as a
pytest test. Optional desktop libraries are observed only when already present
in the current interpreter.

> **Revised 2026-08-20 after post-bundle review.** The original harness recorded
> two observations that could never be false (an identifier captured on the main
> thread compared against the main thread) and exercised `QCoreApplication`,
> which has no widget layer. Both were corrected: the worker now reports its own
> identity, the shutdown worker records whether it actually observed the stop
> request, and the GUI probe now builds a real `QApplication`, a frameless
> always-on-top popup widget, and a cross-thread signal delivery. DPI/monitor
> geometry and WebView2 runtime probes were added. Evidence below is from the
> revised harness.

## Owned files changed

- `spikes/han2_desktop_threading_lifecycle.py`
- `docs/execution/reports/han-2-desktop-threading-lifecycle-spike.md`
- `.superpowers/sdd/05-execution-plan/han-2-task-report.md` (superseded; see the artifact budget in `05-execution-plan.md`)

## Focused re-review reproducibility

Command (PowerShell, repository root; human-preinstalled `.venv`):

```text
.\.venv\Scripts\python.exe spikes\han2_desktop_threading_lifecycle.py
```

Observed output (exit status `0`):

```text
HAN-2 desktop threading/lifecycle spike
platform=win32
windows_version=Windows-10-10.0.19045-SP0
python=3.13.11
threading.main_thread_ident=23768
threading.main_thread_name=MainThread
threading.queue_pump_callback_event=worker-complete
threading.queue_pump_callback_on_main_thread=True
threading.worker_completion_observed=True
threading.completion_worker_stopped=True
threading.shutdown_requested=True
threading.shutdown_worker_started=True
threading.shutdown_join_completed=True
main_thread_ui_loop.observation=stdlib queue pump callback was observed on the process main thread; this is evidence, not a production UI architecture
capability.PyQt6.status=AVAILABLE
capability.PyQt6.version=6.11.0
capability.PyQt6.detail=PyQt6 importable; bounded QCoreApplication loop completed
capability.PyQt6.ui_loop_exercised=True
capability.PyQt6.ui_loop_callback_on_main_thread=True
capability.PyQt6.ui_loop_exit_code=0
capability.PyQt6.tray_class_available=True
capability.PyQt6.tray_observation=QSystemTrayIcon class available; no tray icon created
capability.pywebview.status=AVAILABLE
capability.pywebview.version=6.2.1
capability.pywebview.detail=importable (6.2.1)
capability.pywebview.backend_initialized=True
capability.pywebview.backend_module=webview.platforms.winforms
capability.pywebview.renderer=edgechromium
capability.pywebview.window_or_web_loop_exercised=False
capability.pywebview.observation=initialize() selected webview.platforms.winforms (edgechromium); no window or web loop created
capability.pystray.status=AVAILABLE
capability.pystray.version=0.19.5
capability.pystray.detail=importable (0.19.5)
capability.pystray.icon_class_available=True
capability.pystray.tray_loop_exercised=False
capability.pystray.observation=pystray.Icon class available; no tray icon or loop created
macos_linux=UNEXERCISED
overall=PASS
```

The platform, Python, and thread identifier values are runtime observations;
the recorded identifier is specific to this process and will differ on a later
run.

Syntax check:

```text
.\.venv\Scripts\python.exe -m py_compile spikes\han2_desktop_threading_lifecycle.py
```

Observed result: no output, exit status `0`.

Focused Ruff check:

```text
.\.venv\Scripts\python.exe -m ruff check --isolated --select E,F,I,UP --target-version py310 spikes\han2_desktop_threading_lifecycle.py
```

Observed output (exit status `0`):

```text
All checks passed!
```

## Revised Windows evidence (2026-08-20)

Command:

```text
.\.venv\Scripts\python.exe spikes\han2_desktop_threading_lifecycle.py
```

Threading — every observation can now be false:

```text
threading.worker_reported_ident=19948          (main=26292)
threading.result_crossed_thread_boundary=True
threading.result_consumed_on_main_thread=True
threading.completion_worker_stopped=True
threading.shutdown_worker_started=True
threading.shutdown_request_acknowledged_by_worker=True
threading.shutdown_join_completed=True
overall=PASS
```

GUI layer — the actual risk this spike exists for:

```text
capability.PyQt6.version=6.11.0
capability.PyQt6.gui_application_created=True
capability.PyQt6.frameless_popup_widget_constructed=True
capability.PyQt6.ui_loop_exercised=True
capability.PyQt6.worker_result_delivered_on_ui_thread=True
capability.PyQt6.delivery_crossed_thread_boundary=True
capability.PyQt6.tray_available=True
```

A worker-thread result reached a main-thread slot through a Qt signal while a
frameless, always-on-top, translucent widget existed — the V1 popup shape and
the `RF-INV-06` path. No window was shown and no tray icon was created.

Display geometry and DPI:

```text
display.process_dpi_awareness=PER_MONITOR_DPI_AWARE
display.system_dpi=96
display.screen_count=2
display.screens=[{'name': 'LG ULTRAGEAR', 'geometry': (0, 0, 1920, 1080), 'device_pixel_ratio': 1.0, 'logical_dpi': 96.0},
                 {'name': 'Artist22R Pro',  'geometry': (-1920, 0, 1920, 1080), 'device_pixel_ratio': 1.0, 'logical_dpi': 96.0}]
display.any_negative_origin=True
display.any_display_scaling=False
```

**A monitor sits at x = -1920 on this machine.** Negative virtual-desktop
origins are real here, not hypothetical: cursor and ROI coordinates must be
reconciled against the virtual desktop, not against a 0-based primary screen.
`BoundingBox` already permits negative coordinates, which is correct.

Qt reports the process as per-monitor DPI aware. Both monitors run at
`device_pixel_ratio` 1.0, so **scaled-display behavior (125%/150%) remains
unexercised** and is the main open Windows display risk.

WebView2 deployment prerequisite:

```text
capability.webview2_runtime.available=True
capability.webview2_runtime.version=151.0.4129.93
capability.webview2_runtime.source=HKLM
```

pywebview selects `webview.platforms.winforms` with the `edgechromium`
renderer, which requires the Evergreen WebView2 Runtime. It is present here,
but packaging must still guarantee it on target machines.

## Still unexercised after this revision

- Scaled displays (125%/150%) and mixed-DPI multi-monitor setups.
- A real pywebview window and its event loop coexisting with the Qt loop in one
  process. Backend selection was probed; loop contention was not.
- An actual tray icon and its message loop.
- macOS and Linux.

## Original Windows evidence (superseded harness)

- The process main thread was identified and a bounded stdlib queue pump handled
  a worker completion event on that same main thread.
- A completion worker signaled completion and joined successfully. A separate
  cooperative shutdown worker observed a shutdown request and joined within the
  bounded timeout.
- PyQt6 `6.11.0` was available. Its bounded `QCoreApplication` loop completed
  with exit code `0`, and the timer callback ran on the process main thread.
  `QSystemTrayIcon` was available; no tray icon was created.
- pywebview `6.2.1` was importable. Its local `initialize()` backend probe
  selected `webview.platforms.winforms` with the `edgechromium` renderer. No
  window was created and no interactive web loop was started.
- pystray `0.19.5` was importable and its `Icon` class was available. No tray
  icon or tray loop was created.
- The stdlib and optional-library evidence intentionally does not select or
  claim a production desktop architecture, cancellation policy, or GUI
  integration design.

## Platform limitation

Only Windows was exercised (`sys.platform == "win32"`). macOS and Linux are
explicitly **UNEXERCISED**; no cross-platform behavior or parity claim follows.

## Installation and network confirmation

PyQt6 `6.11.0`, pywebview `6.2.1`, pystray `0.19.5`, and the validation tools
were human-preinstalled in `C:\Hanly\.venv` before this focused re-review. This
task performed no dependency installation, package-manager command, network
request, or model download.

## TDD applicability

TDD RED/GREEN is **not applicable**: this task adds no production behavior and
the harness is an evidence script, not a pytest test. Reproducibility is covered
by the exact commands and observed exit statuses above.

## Focused re-review self-review

- Scope remains limited to the three HAN-2-owned paths listed above.
- Version reporting uses local package metadata; no package state was changed.
- The PyQt6 loop probe has a bounded fallback timeout and creates no GUI window.
- The pywebview probe initializes only the local backend selection/setup needed
  to observe WinForms/EdgeChromium availability; it creates no window and starts
  no interactive web loop.
- The pystray probe checks `Icon` class availability without creating an icon or
  loop.
- Worker completion and shutdown retain bounded waits and explicit join checks.
- No production architecture, engine contract, or cross-platform behavior was
  added or inferred.
- No files outside HAN-2 ownership were intentionally changed.

## Concerns

- pywebview backend selection was observed, but an actual native window and
  interactive web loop were intentionally not started.
- pystray and `QSystemTrayIcon` class availability were observed, but actual
  shell/tray integration was intentionally not exercised.
- macOS/Linux remain unexercised, and runtime configuration metadata remains
  **UNVERIFIED**.
- This spike demonstrates bounded lifecycle and local capability evidence, not
  performance, cancellation semantics, or a final desktop event-loop design.
