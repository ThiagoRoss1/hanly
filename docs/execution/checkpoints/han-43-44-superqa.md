# HAN-43 / HAN-44 / Super QA session updates

## Session
- Branch / base SHA: `codex/han-43-44-superqa` from `main` at `5f7eb2af68ab7883ec5f43525e00fd325867fd49`
- Interpreter / OS / display and process-inspection availability: `.venv` Python 3.13.11,
  macOS arm64 (Darwin 25.6.0). `/bin/ps` is permitted in this session, unlike the
  sandbox that produced `superqa.md`. Visible-desktop availability is checked per native
  run and recorded with the result.
- Scope: HAN-44, HAN-43, SUPERQA-001–006
- Linear: not reachable from this session (the MCP Linear server is unauthenticated).
  No issue state was changed and no comment was posted. Status progression for HAN-43
  and HAN-44 is pending human action.

## Checkpoints
| Patch | State | Main changes | Check and result | Commit |
| --- | --- | --- | --- | --- |
| HAN-44 | Implemented | Stage progress markers on stderr (`self_check.py`) and their harness side (`read_progress`, `current_stage` in the failure description); `tools/native_host_fingerprint.py`; per-product `build.yml` failure graph with step ids and explicit prerequisites; failure-safe `hanly-diagnostics-<platform>` upload; `--reconstruct-only` and standalone `--disk-image` in the smoke harness. | `pytest tests/test_packaging.py tests/test_ci_workflows.py tests/test_host_fingerprint.py` 153 passed; full `pytest` 1275 passed / 3 skipped; ruff + mypy clean. | |
| HAN-43 | Implemented | Native and packaged cases routed into `tests/native/{shared,macos,windows}` and `tests/packaged/shared`; `--suite portable\|native\|packaged` selection that excludes a suite before its modules import; `HANLY_REQUIRE_NATIVE` / `HANLY_REQUIRE_PACKAGED` turn capability skips into failures in the jobs that own them; `ci.yml` gains three source-native jobs and `build.yml` gives up the duplicated portable suite, lint, and types. | Collected node IDs compared before/after: every case has an owner (`--suite` totals 1286 + 1 skipped, and the two Windows-only cases are now OS-routed rather than collected-and-skipped on macOS). `pytest --suite native` 35 passed on this host; full `pytest` 1286 passed / 1 skipped; ruff + mypy clean. | |
| Super QA | Pending | | | |

## HAN-43 routing inventory

| File | Disposition |
| --- | --- |
| `tests/integration/test_packaged_desktop.py` | → `tests/packaged/shared/`; stale-bundle and missing-bundle skips now fail under `HANLY_REQUIRE_PACKAGED` |
| `tests/integration/test_control_center_layout.py` | → `tests/native/shared/`; capability check no longer imports Qt in the parent |
| `tests/integration/test_control_center_lifecycle.py` | → `tests/native/shared/`; the macOS identity case → `tests/native/macos/test_control_center_identity.py`. The POSIX-signal case stays shared: POSIX is not one OS |
| `tests/integration/test_desktop_startup.py` | → `tests/native/shared/` |
| `tests/integration/test_lookup_process_spawn.py` | → `tests/native/shared/` |
| `tests/integration/test_webengine_startup.py` | → `tests/native/shared/`; the Windows abort case → `tests/native/windows/test_webengine_arguments.py`; the child program → `tests/hanly_fixtures/webengine_probe.py` |
| `tests/test_qt_popup_window.py` | → `tests/native/shared/` (real Qt widgets); the Cocoa panel case → `tests/native/macos/test_popup_panel.py`; the zero-pointer guard is a pure platform decision and moved to `tests/test_popup.py` |
| `tests/test_hover_exit_qt.py`, `tests/test_qt_hover_scheduler.py` | → `tests/native/shared/`: both build a real `QApplication` and run a real event loop, which is what kept `PyQt6` in the portable collection |
| `tests/test_control_center.py` | the WebEngine-ordering case → `tests/native/shared/test_webengine_startup.py`, now in a child: the production guard refuses once any `QApplication` exists, so it was passing on collection order |
| `tests/test_app_update_handoff.py` | split. Rendered-script decisions stay portable; the executing cases → `tests/native/shared/test_update_handoff_native.py`, the Windows rollback → `tests/native/windows/`, the macOS rollback → `tests/native/macos/`; shared scaffolding → `tests/hanly_fixtures/update_handoff.py` |
| `tests/test_hotkeys.py`, `tests/test_hotkeys_darwin.py` | stay portable: both drive doubles (`_Listener`, `_FakeCarbon`), never a real registration |
| `tests/hanly_fixtures/process_probe.py` | stays; consumers updated by the Super QA patch |

`tests/native/linux/` is deliberately absent: no case is Linux-only. Linux-native
behavior (xcb plugin, display) is exercised by the shared cases on the Linux job.

## Observations for future review
| Finding / decision | Evidence or rationale | Disposition / limitation | Revisit trigger |
| --- | --- | --- | --- |
| `ci.yml` job names changed: `windows tests (py3.10)` is gone, replaced by `native (windows)`, `native (macos)`, `native (linux)` | The Windows job was a duplicate full suite; the three native jobs are the explicit owner of native coverage | **Needs a human decision**: branch protection or any required-check list naming the old job must be updated. `quality (py<version>)` is unchanged on purpose | Before the next merge that relies on required checks |
| `build.yml` no longer runs the portable suite, ruff, or mypy | `ci.yml` owns them explicitly, and `ci.yml` runs on every push including a tag push | Release eligibility now depends on CI for the tag rather than on the build job repeating it. `release.yml` still requires a successful build run | If a release is ever cut from a tag whose CI run did not pass |
| Per-OS runner behaviour of the new `build.yml` failure graph is unproven | The conditions are checked by a local scenario replay in `tests/test_ci_workflows.py`, not by Actions | Implemented; pending CI confirmation. No push authorization in this run | The next `workflow_dispatch` or tag build |
| `worker close` became a reported stage | A crash while releasing native handles used to be attributed to the last provider stage | Implemented. The worker report now carries one extra stage | If a consumer parses the stage list positionally |
| `torch.backends.cpu.get_cpu_capability()` reports `DEFAULT` on this host | Local fingerprint run, macOS arm64 | Observation only; it is the field the Windows `ILLEGAL_INSTRUCTION` hypothesis needs from the real runners | When a Windows runner produces a fingerprint alongside a crash |

## Next action / blockers
- HAN-43: route native cases into `tests/native/**` and `tests/packaged/**`, add suite
  selection, and rebuild the CI job layout.
