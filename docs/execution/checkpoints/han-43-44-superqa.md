# HAN-43 / HAN-44 / Super QA session updates

## Session
- Branch / base SHA: `codex/han-43-44-superqa` from `main` at `5f7eb2af68ab7883ec5f43525e00fd325867fd49`
- Interpreter / OS / display and process-inspection availability: `.venv` Python 3.13.11,
  macOS 26.6.2 arm64 (Darwin 25.6.0). This session has a **visible window server**,
  `/bin/ps` is permitted, and a KRDICT database plus the EasyOCR weights are present —
  none of which the sandbox that produced `superqa.md` had.
- Packaging interpreter: a disposable Python 3.10.20 environment built from
  `packaging/release-constraints.txt`, outside the repository. It is the interpreter
  `build.yml` uses, not `.venv`.
- Scope: HAN-44, HAN-43, SUPERQA-001–006
- Linear: connected mid-session. HAN-43 and HAN-44 were read directly only after
  implementation — the work was built against the patch plan's summary of them. Both
  were re-checked against their real acceptance criteria afterwards; the two fields
  that were missing are closed in `1f8354a`, and the one scope note (no native hotkey
  coverage exists to route) is in the handoff.

## Checkpoints
| Patch | State | Main changes | Check and result | Commit |
| --- | --- | --- | --- | --- |
| HAN-44 | Implemented | Stage progress markers on stderr (`self_check.py`) and their harness side (`read_progress`, `current_stage` in the failure description); `tools/native_host_fingerprint.py`; per-product `build.yml` failure graph with step ids and explicit prerequisites; failure-safe `hanly-diagnostics-<platform>` upload; `--reconstruct-only` and a standalone `--disk-image` in the smoke harness. | Focused: 153 passed across `test_packaging`, `test_ci_workflows`, `test_host_fingerprint`. Bundle gates below. | `3e05574` |
| HAN-43 | Implemented | Native and packaged cases routed into `tests/native/{shared,macos,windows}` and `tests/packaged/shared`; `--suite portable\|native\|packaged` selection that excludes a suite before its modules import; `HANLY_REQUIRE_NATIVE` / `HANLY_REQUIRE_PACKAGED` turn capability skips into failures in the jobs that own them; `ci.yml` gains three source-native jobs and `build.yml` gives up the duplicated portable suite, lint, and types. | Collected node IDs compared before/after: every case has an owner; the only two not collected on this host are the Windows-only pair, now OS-routed instead of collected-and-skipped. `pytest --suite native` 37 passed, 0 skipped. | `17c841a` |
| Super QA | Implemented | `--expect-version` plus the build commit and source version in the artifact record (005); `verify_primary_screen` between Qt initialization and pywebview window creation (002); the embedded process inventory raises `ProcessInspectionUnavailable` rather than returning nothing, and both consumers report it as unavailable rather than as a retired child (004); the benchmark RSS fallback reads this platform's own `ru_maxrss` unit. | A fresh macOS bundle was built from this branch with the 3.10 packaging environment and validated end to end — see the dispositions below. | `ce94fe4`, `af44fd7`, `13de683` |

## HAN-43 routing inventory

| File | Disposition |
| --- | --- |
| `tests/integration/test_packaged_desktop.py` | → `tests/packaged/shared/`; stale-bundle and missing-bundle skips now fail under `HANLY_REQUIRE_PACKAGED` |
| `tests/integration/test_control_center_layout.py` | → `tests/native/shared/`; the capability check no longer imports Qt in the parent |
| `tests/integration/test_control_center_lifecycle.py` | → `tests/native/shared/`; the macOS identity case → `tests/native/macos/test_control_center_identity.py`. The POSIX-signal case stays shared: POSIX is not one OS |
| `tests/integration/test_desktop_startup.py` | → `tests/native/shared/` |
| `tests/integration/test_lookup_process_spawn.py` | → `tests/native/shared/` |
| `tests/integration/test_webengine_startup.py` | → `tests/native/shared/`; the Windows abort case → `tests/native/windows/test_webengine_arguments.py`; the child program → `tests/hanly_fixtures/webengine_probe.py` |
| `tests/test_qt_popup_window.py` | → `tests/native/shared/` (real Qt widgets); the Cocoa panel case → `tests/native/macos/test_popup_panel.py`; the zero-pointer guard is a pure platform decision and moved to `tests/test_popup.py` |
| `tests/test_hover_exit_qt.py`, `tests/test_qt_hover_scheduler.py` | → `tests/native/shared/`: both build a real `QApplication` and run a real event loop, which is what kept `PyQt6` in the portable collection |
| `tests/test_control_center.py` | the WebEngine-ordering case → `tests/native/shared/test_webengine_startup.py`, now in a child: the production guard refuses once any `QApplication` exists, so it had been passing on collection order |
| `tests/test_app_update_handoff.py` | split. Rendered-script decisions stay portable; the executing cases → `tests/native/shared/test_update_handoff_native.py`, the Windows rollback → `tests/native/windows/`, the macOS rollback → `tests/native/macos/`; shared scaffolding → `tests/hanly_fixtures/update_handoff.py` |
| `tests/test_hotkeys.py`, `tests/test_hotkeys_darwin.py` | stay portable: both drive doubles (`_Listener`, `_FakeCarbon`), never a real registration |
| `tests/hanly_fixtures/process_probe.py` | stays; rewritten by the Super QA patch to refuse an empty inventory |

`tests/native/linux/` is deliberately absent: no case is Linux-only. Linux-native
behavior (the xcb plugin, the display) is exercised by the shared cases on the Linux job.

## SUPERQA-001–006 dispositions

| ID | Outcome | Evidence |
| --- | --- | --- |
| SUPERQA-001 | **Not reproduced** on a visible session; diagnostics kept for the case that remains | Fresh bundle, `--self-check ui`: `ok: true`, exit 0, 2.54 s wall — window host 0.1 ms, main window 2,069 ms, document 883 ms, 4 controls rendered, bridge answered `EasyOCR`. Source `python -m hanly_app --self-check ui` likewise passes. The abort in `superqa.md` belonged to the screenless child it was reported in. HAN-44's markers now name the stage when it does happen |
| SUPERQA-002 | **Fixed now** | `verify_primary_screen` runs after `ensure_qt_application` and before pywebview creates the window, raising `ControlCenterUnavailable`. Both branches covered portably with an injected probe; a real session's screen covered by `tests/native/shared/test_qt_screen.py`. It cannot prevent an abort *inside* `QApplication` — that case stays with the stage markers, and the README says so |
| SUPERQA-003 | **Not reproduced** | The whole popup suite runs on this visible Cocoa session: `tests/native/shared/test_qt_popup_window.py` (7 cases) and `tests/native/macos/test_popup_panel.py`, including `hides_when_inactive(winId()) is False` across a show/hide cycle. No adapter change was made, and none is evidenced |
| SUPERQA-004 | **Not reproduced** (this host permits `/bin/ps`) and **hardened** | The embedded inventory now raises `ProcessInspectionUnavailable` for a missing tool, a denial, a timeout, or a non-zero exit; both consumers report it as unavailable rather than as a retired child. Darwin handoff retested for real with compiled builds and LaunchServices: `tests/native/macos/test_update_handoff_darwin.py` and the shared native handoff cases pass. No production updater logic was changed |
| SUPERQA-005 | **Confirmed, then fixed** | The `dist/macos/Hanly.app` on this machine reported `hanly`/`hanly-app` `0.1.3` against a `0.5.0` tree. `smoke_packaged_runtime.py --expect-version 0.5.0` exits 1 on it and names both packages. The fresh build reports `0.5.0` for both, and `dist/reports/hanly-artifact-*.json` now carries the build commit and source version |
| SUPERQA-006 | **Measured; no regression, residual cost recorded** | See the table below |

### SUPERQA-006 measurements

Fresh macOS build from this branch: embedded Python 3.10.20, torch 2.14.0,
EasyOCR 1.7.2, Kiwi 0.23.2, PyQt6 6.11.0.

| Metric | Now | `superqa.md` (stale 0.1.3 artifact) |
| --- | ---: | ---: |
| Frozen worker self-check, wall clock (warm) | 7.74 s | 9.32 s |
| Lookup worker construction (cold first touch / warm) | 7,863 / **4,277** ms | 5,555 ms |
| OCR (cold / warm) | 3,047 / **1,800** ms | 1,907 ms |
| Morphology (cold / warm) | 1,881 / **1,300** ms | 1,154 ms |
| Dictionary | **3–4** ms | 136 ms |
| Frozen UI self-check, wall clock | **2.54 s** | aborted |
| Source warm lookup, 192x48 ROI, 40 samples | **p50 29.8 ms / p95 30.7 ms** | not measured |
| RSS with providers resident, 20 s idle | **834.9 MiB, flat** | not measurable |
| `Hanly.app` tree | 1,342,418,115 B (4,906 files) | ~1.3 G |
| macOS ZIP | 560,323,613 B | 534 M |
| macOS DMG | 637,255,977 B | 608 M |

Largest families: Torch 484.7 MB, Qt/PyQt6/QtWebEngine 387.4 MB, Kiwi 124.0 MB,
OpenCV 123.6 MB, EasyOCR weights 99.2 MB.

Process lifecycle, from the real spawned child: one lookup child while ready
(one pid), `children_after_retire: []`, `children_after_close: []`, a new
generation after waking a retired engine, and none of `easyocr`, `torch`, or
`kiwipiepy` imported in the shell.

**Residual cost:** worker construction still dominates the first lookup after a
retirement — about 4.3 s frozen and warm. That is the price the approved policy
already charges (`LookupPreload.WHEN_CAPTURE_STARTS` loads at Start;
`manual_lookup.IDLE_TIMEOUT_SECONDS` retires an idle manual session after 60 s),
and the warm path is 30 ms. Nothing was changed for it.
**Revisit trigger:** a reported user-visible delay on the first lookup after an
idle retirement, or any change to the `LookupPreload` default.

## Observations for future review
| Finding / decision | Evidence or rationale | Disposition / limitation | Revisit trigger |
| --- | --- | --- | --- |
| Per-OS runner behaviour of the new `build.yml` failure graph is unproven | The conditions are checked by a local scenario replay in `tests/test_ci_workflows.py`, not by Actions | Implemented; pending CI confirmation. No push authorization in this run | The next `workflow_dispatch` or tag build |
| `ci.yml` job names changed: `windows tests (py3.10)` is gone, replaced by `native (windows)`, `native (macos)`, `native (linux)` | The Windows job was a duplicate full suite; the three native jobs are the explicit owner of native coverage | **Needs a human decision**: branch protection or any required-check list naming the old job must be updated. `quality (py<version>)` is unchanged on purpose | Before the next merge that relies on required checks |
| `build.yml` no longer runs the portable suite, ruff, or mypy | `ci.yml` owns them explicitly and runs on every push, tag pushes included | Release eligibility now leans on CI for the tag rather than on the build job repeating it. `release.yml` still requires a successful build run | If a release is ever cut from a tag whose CI run did not pass |
| `worker close` became a reported stage, and `window host` another | A crash while releasing native handles used to be attributed to the last provider stage, and a Qt WebEngine import failure to no stage at all | Implemented. The worker report carries one extra stage and the UI report one more | If a consumer parses the stage list positionally |
| `torch.backends.cpu.get_cpu_capability()` reports `DEFAULT` on this host | Local fingerprint run, macOS arm64 | Observation only; it is the field the Windows `ILLEGAL_INSTRUCTION` hypothesis needs from the real runners | When a Windows runner produces a fingerprint alongside a crash |
| The benchmark RSS fallback read macOS bytes as kibibytes | `getrusage` reports `ru_maxrss` in KiB on Linux and in bytes on the BSDs; the first idle sample read 39 MiB as 39 GiB | Fixed now, with a focused test. Developer instrumentation only; nothing in `packages/` uses it | If `psutil` becomes a declared dependency and the fallback stops being reached |
| No native hotkey coverage exists to route | HAN-43 names hotkeys as a pain area, but `test_hotkeys.py` and `test_hotkeys_darwin.py` drive doubles and never register a real hotkey | Reported, not written: new coverage rather than restructuring | If a hotkey regression reaches a release again |
| `tests/native/linux/` is absent | No case is Linux-only; an empty suite is a gate that asked nothing | Deliberate. HAN-43 names Linux-specific suites, so this reading is worth a second opinion | When a genuinely Linux-only case appears |
| The manual-session idle retirement (60 s) was not timed live | Process-level retirement is proven by the real spawned child; the 60 s expiry is covered by `tests/test_manual_lookup.py` with an injected scheduler | Deferred to a human desktop session | The manual pass below |

## Native evidence still owed to a human session

The automated native suite covers desktop startup to `ready`, Control Center
open/close/reopen through the real window and the real child, the frozen window
and its bridge, the popup window contract, the Cocoa panel property, real
process retirement, and the Darwin update handoff. These need a person at the
keyboard and were **not** performed: capture start/stop, ROI and target
selection, hotkey lookup, popup retention and dismissal against a real target
application, a resource update through the Control Center, quit, and relaunch on
a disposable profile.

## Next action / blockers
- None. The bundle is at its Review Handoff,
  `docs/execution/review-handoffs/han-43-44-superqa.md`. Phase B not started.
