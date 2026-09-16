# POSIX Updater Hardening Review Handoff

## Bundle

- Member issues: human-authorized `hanly-update-posix.c` safety findings 1–6; no Linear issue supplied
- Implementation ecosystem: Codex
- Date: 2026-09-15

## Implemented

- Rollback now treats process-inspection uncertainty as unsafe, revalidates executable path and process start identity before signaling, and proves all target processes stopped before renaming.
- Recovery validates the recorded original and candidate directory identities before restoring, rejecting, or retaining either tree.
- Directory moves distinguish failure, durable completion, and completion with an uncertain durability barrier; uncertain states retain recovery material.
- Result files use checked writes, strongest supported file flushing, checked close/rename/parent synchronization, and handled persistence failures.
- Exit and startup waits use monotonic deadlines; detached launch reports immediate `setsid`, `fork`, and `exec` failures through a close-on-exec pipe.
- Native fault tests cover identity mismatches, inspection and stop uncertainty, directory-sync and result-write failures, timeout bounds, live-candidate termination, and immediate exec failure.
- Windows build routing removes inherited `HANLY_UPDATE_HELPER`, never compiles the POSIX helper, and the PyInstaller spec refuses to collect it on `win32`.

## Main expected behavior

Linux and macOS whole-tree updates either commit a transaction-bound acknowledged candidate, durably restore the recorded previous installation, or stop in `recovery-required` without guessing through uncertain process, identity, or filesystem state. Windows builds continue to use the PowerShell updater and contain no POSIX helper.

## Architecture / seams touched

- POSIX whole-tree handoff and recovery state machine
- Native descriptor process and directory identity enforcement
- Packaging boundary between the POSIX helper and Windows PowerShell updater
- No engine, provider, lookup, UI, or package-dependency seams changed

## Relevant files / diff areas

- `packaging/updater/hanly-update-posix.c`
- `tests/native/shared/test_update_posix_native.py`
- `tools/build_package.py`
- `packaging/hanly-desktop.spec`
- `tests/test_packaging.py`

## Implementation-side validation already run

- `python -m pytest tests/test_packaging.py tests/test_app_update_handoff.py -q -k "not test_a_timed_out_run_takes_the_processes_it_started_with_it"` → 105 passed, 6 skipped, 1 sandbox-sensitive test deselected
- `python -m pytest --suite portable` → 1458 passed, 82 skipped; 3 unrelated Windows process-inspection failures because CIM access is denied in this sandbox
- `python -m ruff check packages packaging tests tools benchmarks` → passed
- `cppcheck --enable=warning,performance,portability --check-level=exhaustive --std=c11 --platform=unix64 packaging/updater/hanly-update-posix.c` → passed
- `git diff --check` → passed
- `python -m mypy packages packaging tests tools benchmarks` → blocked by 20 existing Windows-host POSIX-stub errors across six files; no new updater implementation diagnostic was isolated

## Known limitations / intentionally unvalidated areas

- This host is Windows. The real helper and the new native fault cases remain skipped here and must compile and execute in both the Linux and macOS native CI lanes.
- The full unrestricted pytest run also entered native Windows tests and hit an unrelated Control Center failure before timing out.
- Hardware power-loss guarantees remain limited by the host filesystem and kernel even after successful durability barriers.

## Suggested review targets

- Recheck Linux `/proc/<pid>/stat` start-time parsing and macOS `proc_bsdinfo` start identity on their native compilers.
- Exercise each injected post-rename durability state and confirm recovery preserves every available tree.
- Confirm the close-on-exec launch pipe reports immediate failures without delaying successful macOS LaunchServices startup.
- Inspect Windows release archives and manifests to confirm `hanly-update-posix` is absent.

## Review assignment

Claude (Claude Code), reading review only - this host cannot compile the
helper, so nothing here was executed against a built binary.

### Findings

- **Fixed now.** `apply_update` read `FIELD_PARENT_PID`, validated it, and then
  discarded it: `wait_for_exit` no longer consulted the process that asked for
  the update, so freedom was decided only by what runs from the installation
  root. The check is back inside `installation_is_free`, which keeps the
  descriptor's own record of who must exit first.
- **Fixed now.** Three result writes in `recover_update` returned
  `EXIT_FAILED` silently, and two of them withheld the restored build over a
  diagnostic write. One `record_restored` now reports the failure and starts
  the installation that is already back, as `roll_back` always did.
- **Fixed now.** Nothing kept the fault-injection hooks out of a shipped
  helper. `test_a_released_helper_carries_none_of_its_fault_injection` holds
  the release flags to defining no hook and every `HANLY_TEST_` read to the
  block it is compiled in.

### Still open for the deep review

- The helper is unbuilt here. Both native lanes must compile it, and the
  `/proc/<pid>/stat` and `proc_bsdinfo` start-identity reads have never run.
- Everything under "Suggested review targets" above stands.
