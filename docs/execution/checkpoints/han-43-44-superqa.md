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
| HAN-43 | Pending | | | |
| Super QA | Pending | | | |

## Observations for future review
| Finding / decision | Evidence or rationale | Disposition / limitation | Revisit trigger |
| --- | --- | --- | --- |
| Per-OS runner behaviour of the new `build.yml` failure graph is unproven | The conditions are checked by a local scenario replay in `tests/test_ci_workflows.py`, not by Actions | Implemented; pending CI confirmation. No push authorization in this run | The next `workflow_dispatch` or tag build |
| `worker close` became a reported stage | A crash while releasing native handles used to be attributed to the last provider stage | Implemented. The worker report now carries one extra stage | If a consumer parses the stage list positionally |
| `torch.backends.cpu.get_cpu_capability()` reports `DEFAULT` on this host | Local fingerprint run, macOS arm64 | Observation only; it is the field the Windows `ILLEGAL_INSTRUCTION` hypothesis needs from the real runners | When a Windows runner produces a fingerprint alongside a crash |

## Next action / blockers
- HAN-43: route native cases into `tests/native/**` and `tests/packaged/**`, add suite
  selection, and rebuild the CI job layout.
