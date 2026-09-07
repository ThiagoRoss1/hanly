# Windows release investigation and cross-platform applicability — 2026-09-05

Authorized scope: investigate, prepare and review the plan for the user. No product fix, commit, publication, or GitHub mutation was performed. This report and the related plan are maintained in English.

## Release identity and environment

- GitHub API source: [Hanly Desktop v0.1.0](https://github.com/ThiagoRoss1/hanly/releases/tag/v0.1.0), published at `2026-09-05T03:00:41Z`.
- Release commit: `2c4f39c1c00866faa19277e1da2a958a7fa656be`. Investigated checkout: `75c188e`. `git diff v0.1.0 HEAD -- packages packaging` was empty.
- Windows ZIP: 482,533,400 bytes; SHA-256 `99cdcdd177c0054a5a1af33ef9749afbdbca560fa5c76a8611a15df273e79fdf`.
- `C:\Users\Thiago\Downloads\hanly\hanly-desktop-windows.zip` matches that checksum. The executable in the extracted directory was inspected with `PyInstaller.archive.readers.CArchiveReader`.
- The release also contains the resource manifest, compressed KRDICT, checksums, and macOS/Linux archives. Asset presence alone does not prove successful clean-profile provisioning.
- Local reproduction: Python 3.13, PyQt6 6.10.2, WebEngine 6.10.0, pywebview 6.2.1. CI builds with Python 3.10; Windows recorded Qt6Core 6.11.2 in the published executable. A corrected native bundle still requires validation.

## Findings

### 1. Control Center abort: missing program argument — reproduced cause

`capture_selector.py:119–128` creates the shared application with `application_type([])`. The selector works, but WebEngine needs a program name when initializing Chromium. The application remains alive and is reused by `application.py`, so its alternative `QApplication(sys.argv)` does not repair the existing object.

Windows recorded failures of the downloaded executable at 00:14:50 and 18:56:19 in `Qt6Core.dll`, exception `0xc0000409`. That code alone does not establish the cause; the instrumented reproduction below isolated it.

```powershell
.venv\Scripts\python.exe artifacts\investigation-2026-09-05\probe_qt_variants.py
```

All three variants failed: OCR preloaded/existing loop, no OCR/existing loop, and no OCR/direct opening.

```text
EXIT 3221226505
QT QtFatalMsg Argument list is empty, the program name is not passed to QCoreApplication. base::CommandLine cannot be properly initialized.
```

Changing only `QApplication([])` to `QApplication(['hanly'])` in the harness:

```powershell
.venv\Scripts\python.exe artifacts\investigation-2026-09-05\probe_qt_argv.py
```

All three variants exited with code 0 through the five-second timer. Removing OCR preload was unnecessary. The change exists only in the diagnostic harness, not product code.

### 2. Competing event loops and lost window ownership — independent defect

After removing the abort in the experiment, variants opening the host within the existing event loop reported:

```text
QCoreApplication::exec: The event loop is already running
```

`DesktopApplication.run()` calls `self._qt.exec()`. The tray action calls `ControlCenterHost.open()`, which calls `webview.start(gui='qt')`. The installed backend, `webview/platforms/qt.py:921–972`, reuses QApplication but also calls `_app.exec_()`.

Sharing QApplication does not establish correct event-loop ownership. When `start()` returns through this path, `control_center.py:611–613` clears `_opened` and `_window`, although the backend may still retain the window. This risks duplicate reopening, incomplete cleanup, and lost close control. The warning was reproduced; a full reopening matrix against the release was not performed.

### 3. Kiwi missing from the published Windows bundle — verified inventory

The PYZ contains `hanly.kiwi_provider`, but no `kiwipiepy` or `kiwipiepy_model`. The external bundle tree contains no Kiwi files, including the native extension and models.

`KiwiProvider._get_analyzer()` uses `import_module('kiwipiepy')`, requiring explicit freezer collection. `hanly-desktop.spec:60` collects EasyOCR/Torch/Torchvision but not Kiwi. `LookupWorker` warms morphology before reporting readiness (`composition.py:118`). Missing Kiwi therefore blocks readiness even if OCR and KRDICT are available.

The minimized reproduction uses the real adapter and controller while restricting imports to the observed release inventory:

```powershell
.venv\Scripts\python.exe artifacts\investigation-2026-09-05\probe_worker.py
```

```text
Frozen Kiwi modules: ['hanly.kiwi_provider']
Frozen Kiwi files: []
Worker ready: False
Accepting: False
User error callbacks: []
Root provider error: kiwipiepy is unavailable
cause: No module named 'kiwipiepy' (release inventory)
AssertionError: REPRO: missing Kiwi prevents readiness; initialization error is not delivered
```

This harness does not execute the entire pipeline inside the executable. It reproduces the real adapter's failure under the verified bundle restriction and does not exclude additional frozen OCR defects.

### 4. Initialization error dropped and misleading running state — reproduced

`JobExecutor._run()` reports a factory failure with request `None`. `LookupController._on_executor_error():392` returns if no request is current. The original message never reaches its public error callback; the harness confirmed an empty callback list.

Hover detects failed readiness but reports only `lookup worker initialization failed`. `DiagnosticLog` retains messages in memory, accessible through the crashing Control Center. `DesktopController.start():80` already marks `RUNNING` before readiness. Together, these produce a live process without functional lookup or useful visible diagnostics.

### 5. Local KRDICT and OCR: positive evidence with limits

`load_runtime()` validated `%LOCALAPPDATA%\Hanly\resources\krdict\krdict.sqlite3`: 92,508,160 bytes, state `VALID`. Local `craft_mlt_25k.pth` and `korean_g2.pth` models exist.

```powershell
.venv\Scripts\python.exe artifacts\investigation-2026-09-05\probe_real_worker.py
```

```text
EXIT 0
Real EasyOCR + Kiwi + KRDICT ready: True
```

The real worker was constructed and warmed on its own thread with model downloads disabled, local dependencies, and existing KRDICT. This proves local readiness, not successful hover lookup in the executable. No user resource reinstall or modification was required.

### 6. Current launch flow differs from the requested experience

All three launchers already converge on `hanly_app.cli:main`. Mandatory selection (`cli.py:134`) precedes runtime resolution/provisioning. The desktop starts capture but does not automatically open the Control Center. Provisioning messages go to stderr while the bundle is `console=False`.

Part of the apparent inactivity follows this flow; missing Kiwi compounds it. Change the shared launch flow rather than creating a separate CLI application.

## Cross-platform applicability review

The follow-up review inspected `.github/workflows/build.yml`, `packaging/hanly-desktop.spec`, shared launch/runtime files, `tray.py`, current settings-path resolution, and installed pywebview/pystray backend code.

**Confirmed by source:** all three OS jobs use the same application code and packaging spec. Nonempty argv, Kiwi collection, readiness/error propagation, and main-window startup should be corrected unconditionally. The spec's platform branches select `_win32`, `_darwin`, and `_xorg` input/tray modules; they do not create independent launch implementations.

**Not confirmed by native execution:** macOS/Linux release inventories, crash behavior, permissions, capture, tray, and corrected lifecycle. Those require native builds and acceptance. The plan now makes them explicit gates rather than assuming Windows results transfer.

### macOS checks required

The installed pystray `run_detached` contract describes integration with the other framework's native application through `darwin_nsapplication`. Current `TrayService` simply calls `run_detached()`. This is an integration risk to validate, not a reproduced macOS bug. The main-loop design must satisfy native thread requirements. See [pystray framework integration](https://pystray.readthedocs.io/en/latest/usage.html#integrating-with-other-frameworks).

Check capture permission and keyboard-monitoring permission denial/recovery separately for packaged and terminal launches. pynput documents macOS keyboard authorization requirements and possible terminal authorization. See [pynput platform limitations](https://pynput.readthedocs.io/en/latest/limitations.html).

### Linux checks required

The spec explicitly collects pystray's Xorg backend. That backend does not provide ordinary menu functionality, so tray-only access to Quit/Open cannot be assumed. Keep lifecycle actions in the main interface and only hide it when restoration is available. See [pystray backend capabilities](https://pystray.readthedocs.io/en/latest/usage.html#supported-backends).

The input stack uses Xorg; pynput documents restricted event visibility under XWayland. A visible window is not evidence of global capture/input support under Wayland. Require a real X11 acceptance run and explicit Wayland capability evaluation. Unsupported session capabilities must be reported, not labeled fixed. See [pynput Linux limitations](https://pynput.readthedocs.io/en/latest/limitations.html#linux).

### Shared paths and backend constraints

`default_app_config_path()` currently uses `%LOCALAPPDATA%/Hanly` on Windows and `$XDG_CONFIG_HOME/hanly` or `~/.config/hanly` elsewhere, including macOS. Planned logs now derive from that helper's parent rather than hardcoding Windows paths. Existing settings must not move as an incidental refactor.

The installed pywebview loader can fall back from requested Qt to other native backends. The proposed single-Qt-loop design must verify the effective backend and report failure rather than silently combining frameworks. Native architecture/version identities must be recorded per artifact; one macOS CI architecture cannot prove support for another.

## Validation and limitations

- `pytest tests/test_control_center.py tests/test_easyocr_runtime.py tests/test_packaging.py -q`: **45 passed**.
- `pytest tests/test_application.py -q`: **22 passed**.
- An initial command referenced nonexistent `tests/test_cli.py`; it ran no tests and was replaced by the commands above.
- The existing host test injects a fake webview and does not initialize Chromium. CI currently tests before freezing, then checks archive existence/size without exercising the produced app.
- No automated real-text capture/hover test was performed against the released executable. No clean-profile provisioning or native macOS/Linux execution was performed.
- Diagnostic scripts and outputs remain under `artifacts/investigation-2026-09-05/`; they are evidence, not finalized regression tests.
- The follow-up changed documentation only. Native tests were specified, not executed or marked passing.

## Technical conclusion

The Windows investigation identified empty argv and absent Kiwi as blockers, plus separate lifecycle and error-visibility defects. There is no evidence supporting an OCR replacement or KRDICT rebuild as the initial remedy.

The [revised implementation plan](../../superpowers/plans/2026-09-05-windows-stabilization.md) covers shared fixes for Windows, macOS, and Linux, with explicit native acceptance and platform capability limits. Implementation coverage is cross-platform; completed validation is currently Windows-only.
