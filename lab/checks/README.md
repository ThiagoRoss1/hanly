# Whole-app health lab

Developer-only orchestration of fixed repository scenarios. This is not a new
desktop entry point, an OCR benchmark or a shipped dependency. Install the
desktop's `dev` extra for `pytest` and `psutil`, then run from the repository root:

```bash
python -m lab check list
python -m lab check run \
  --scenario APP-STARTUP --scenario MAC-IDENTITY \
  --scenario UPDATE-COORDINATOR --scenario UPDATE-APPLY-POSIX
python -m lab check run \
  --scenario BUNDLE-IDENTITY --scenario BUNDLE-WINDOW --scenario BUNDLE-WORKER \
  --bundle dist/macos/Hanly.app --expected-commit <full-source-sha>
```

## Evidence and isolation

Each selection executes in its own disposable test workspace and child profile.
The updater helper touches test-created installation trees, not the everyday
installation. The bundled app is inspected or self-checked; it is not updated.
Fixed test selectors are the scenario's executable actions and assertions.
Use `catalog.py` to see the scope, prerequisites and expected transitions.

Evidence labels distinguish real source startup, real UI with injected services,
real helpers with simulated builds, and a real frozen runtime. A scripted update
state does **not** prove that an application update downloaded or installed.
Human hover remains an explicit coverage gap.

## A complete Windows update

```powershell
python -m lab check windows-update --from v0.9.0 --mode install   # or cancel, rollback
```

It downloads a published release's Windows archive, checks it against that
release's `SHA256SUMS`, and unpacks it under its own run directory with its own
profile and TEMP. It then updates that installation with **this checkout's**
updater (`TreeUpdateRunner` and `UpdateCoordinator`, composed as the desktop
composes them) against the real public release source, read only. The real
PowerShell helper applies the update and relaunches the new build, which has to
answer its challenge. The command then quits through the page, relaunches once
to settle, and checks the tree against the published manifest. It also checks
that the update is not offered again and lists what remains.

`--mode cancel` stops during preparation. `--mode rollback` keeps the source
build running so the helper waits, then replaces the staged new executable with
bytes that cannot start. The helper must then wait out its deadline (ten
minutes), restore every file and relaunch the previous build. Only processes
running an executable inside the run's installation are ever stopped.

The process hosting the coordinator is the lab, not the frozen shell. This
proves the checkout's updater against real releases, not the updater shipped
inside the source release.

`passed` means all selected cases passed and observation/cleanup completed.
A skipped prerequisite is `unavailable`, never a pass. A failed check, deadline,
unclean child exit or unfinished output reader fails the scenario. The CLI exits
nonzero if any selected scenario is not passed; unselected coverage is `not_run`.

## Durable output

Each run writes `metadata.json`, `measurements.jsonl`, `summary.json` and a
standalone `report.html` under gitignored `artifacts/lab/runs/<run-id>/`.
These contain only structural results, counts, timings, sampled RSS and owned
PID/role/activation transitions. Raw child output is bounded to 64 KiB in memory
and discarded. No screenshot, OCR output, profile path or arbitrary exception
message enters the report. Capture/export semantics of `live-hover` are unchanged.

RSS is the sampled **sum of the scenario runner and observed descendants**, not
the application's private memory or a precise peak. Process roles are inferred
from fixed command markers; `spawned_python` does not distinguish lookup from
Control Center. Nominal sampling is 100 ms plus inspection overhead: absence of
a transient event is not proof that nothing happened between samples. Retained
events are capped at 1,000, with an explicit dropped count. Denied inspection is
unavailable. Cleanup addresses tracked process handles and the spawned POSIX
group, never applications found by name.

The summary records source commit and dirty-state availability. A dirty source
run is not evidence for a clean commit. Frozen identity needs an explicit full
expected SHA; a successful stale bundle is not current-source acceptance.
