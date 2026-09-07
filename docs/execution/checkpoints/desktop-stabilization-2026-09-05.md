# Checkpoint — Hanly Desktop stabilization

Updated during the bounded completion pass on 2026-09-06. It replaces the
resumption-assessment checkpoint of 2026-09-05, keeps that assessment's
findings by reference, and records what the completion pass actually changed.

## Read first

1. `CLAUDE.md` and the Phase A rules in `docs/execution/05-execution-plan.md`.
2. [Resumption report and the bounded R1–R6 work](../reports/desktop-stabilization-resumption-2026-09-05.md).
3. [Implementation handoff](../review-handoffs/desktop-stabilization-2026-09-05.md), which carries the current evidence.
4. Consult the [original plan](../../superpowers/plans/2026-09-05-windows-stabilization.md) only for a specific requirement. Do not restart its stages.

## State

Parts 1–8 are implemented and the bounded completion pass R1–R6 is done. The
Windows artifact was rebuilt and passes all three frozen gates. What remains is
outside this pass: the native macOS and Linux matrix, which has never run, and
the Windows interactive hover/hotkey/tray matrix, which is manual. The frozen
window gate is a recorded, non-blocking soak on macOS and Linux for one
release.

Repository: `main`, HEAD `75c188e`; the whole implementation remains
uncommitted, as Phase A requires.

## What the completion pass changed

| Item | Change |
|---|---|
| R1 — UI-thread dispatch | `_DesktopSession._on_qt` is the one marshalling seam. `start`, `pause`, `resume`, `apply_config`, `set_capture_preferences`, `shutdown`, `begin_shutdown`, and `quit` all cross it. Suspend → overlay → restore moved out of the bridge into the session, so it is one dispatched action |
| R2 — Tray recovery and Quit | `TrayService.can_restore_window` reads the backend's real capability; "Open Control Center" is also the icon's default action, which is the only route on pystray's Xorg backend. `_start_tray` hides on close only when a route exists. The window carries a **Quit Hanly** action through the bridge |
| R3 — Cold-profile isolation | The smoke harness redirects settings, home, and all three EasyOCR model locations into the temporary profile. `--model-cache` seeds the isolated model directory explicitly, which is the deterministic offline scenario |
| R4 — Frozen UI acceptance | New `hanly --self-check ui` opens the real main window, waits for its document and injected bridge, has the page call `get_state`, and closes it. Driven by `tools/smoke_packaged_runtime.py --window-only`, by `tests/integration/test_packaged_desktop.py`, and by a new CI step |
| R5 — Retry teardown | `StartupCoordinator` releases on its own thread, before the next attempt rather than beside it. `_DesktopSession.release` dispatches only the detach; the provider join and the update-coordinator shutdown happen off Qt, and ownership is held until the join returns |
| Process exit (beyond R1–R6) | Found while validating R4: a frozen run could finish green and then not end. `cli._leave` now flushes and calls `_terminate_without_unloading`, which terminates the Windows process rather than unloading Chromium's libraries on the way out. Diagnosed by measurement, not inspection — see the handoff |

## Validation

Run with `C:\Hanly\.venv\Scripts\python.exe`, `-p no:cacheprovider` and a
scratchpad `--basetemp` (the sandbox denies pytest's cache directory).

- Full suite: **856 passed, 4 skipped, 0 failed, in 88 s. All three frozen gates run against the bundle that would ship**.
- `ruff` clean; `mypy` clean across 162 source files.
- `python -m hanly_app --self-check ui` from source: window opened, document
  loaded, 4 controls rendered, `get_state` answered `EasyOCR`, exit 0.
- Windows rebuild (2026-09-06, the artifact that would ship): exit 0, about
  18 minutes. `hanly-desktop.exe` 54,218,693 bytes;
  `dist/hanly-desktop-windows.zip` 613,494,401 bytes, SHA-256
  `b1f74d9bd5ddc5bc4f9c6e1c791a8df82be41a8cbdcf05b10e74e74eff95bac7`.
- Frozen inventory: ok, nothing missing.
- Frozen cold worker smoke: exit 0, OCR `책울 읽습니다.`, Kiwi `한국어`, KRDICT 1
  entry. The isolated profile ended up holding the EasyOCR models and KRDICT
  the bundle fetched itself — the R3 evidence, and end-to-end online
  provisioning.
- Frozen window smoke: exit 0, `exit_timeout: false`, window opened in 847 ms,
  document loaded, 4 controls rendered, the page's `get_state` answered
  `EasyOCR`.
- Frozen exit rate: **12/12 clean exits**. The bundle before the exit fix
  managed 7 of 10, the other three ending `3221227010` after writing a
  complete green report.
- The new bundle reports `PyQt6 6.10.2`, `PyQt6-WebEngine 6.10.0`,
  `pywebview 6.2.1`, `pystray 0.19.5`; the old one said `not installed` for all
  four, so the `copy_metadata` spec change is verified.

## Next action

Nothing in this pass is unfinished. What is left is not authorized by it:

1. The Windows interactive matrix — mixed DPI, real hover and hotkey lookup on
   screen, pause/resume, tray restore, Quit — is manual and has not been done.
2. macOS and Linux acceptance needs hosts nobody has here.
3. The CI window gate becomes blocking on macOS and Linux once one native run
   is on record.
4. Phase B deep review, on explicit human authorization, with the human
   choosing the reviewer.

Note for whoever rebuilds: PyInstaller's analysis of Torch needs several GB
free. Five attempts were killed mid-analysis on this host; the one that
succeeded ran with other applications closed and took about 26 minutes.

## Native acceptance

| Environment | Status |
|---|---|
| Windows | Automated source **and frozen** acceptance complete against the bundle that would ship; interactive hover/hotkey/tray matrix still manual and unrun |
| macOS | Not run; suitable host required |
| Linux X11 | Not run; suitable desktop required |
| Linux Wayland | Not evaluated; do not assume full-desktop support |

A skipped test is not a pass, and a written handoff is not evidence.

## Working set

App modules: `qt_bootstrap.py`, `control_center_host.py`, `startup.py`,
`runtime_status.py`, `diagnostics.py`, `paths.py`, `self_check.py`, plus
`application.py`, `control_center.py`, `tray.py`, `cli.py` and the Control
Center assets under `packages/hanly-app/src/hanly_app/`.

Harness and CI: `tools/smoke_packaged_runtime.py`, `.github/workflows/build.yml`,
`tests/integration/test_packaged_desktop.py`.

Preserve unrelated work: the 2026-09-04 handoffs, the investigation and plan,
benchmark artifacts, and everything outside this completion pass. Do not clean
`artifacts/`.
