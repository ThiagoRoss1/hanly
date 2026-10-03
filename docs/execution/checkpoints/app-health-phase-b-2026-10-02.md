# Checkpoint — Phase B review of `lab/app-health` (paused 2026-10-02)

Phase B (deep review, explicitly authorized) of the Windows lab, updater and
stress work. **Paused by the human mid-validation; not finished.** No verdict has
been recorded yet. The Phase B outcome has **not** been appended to
`review-handoffs/lab-windows-implementation-and-stress.md`, and the report has not
been updated. Resume from "Pending" below.

Branch `lab/app-health`, HEAD `12b052c7f22ece9a82a6f745d0dbfeebf49d57b0` plus this
checkpoint. Phase A ended at `792b760`. Local commits only: nothing was pushed,
tagged or released, and no public endpoint was touched.

## Phase B commits (all `fix:`, each with a regression test)

| Commit | What | Evidence |
|---|---|---|
| `deb72a6` | Settling removes a challenge/ack only when it sits in this installation's own receipt directory (`receipt_store(install_root).directory`), not wherever a plan read back from inside the install points | new test with a tampered plan fails before and passes after; the existing cleanup test now uses the production store layout |
| `938fa6c` | The 22 win32-only mypy errors are fixed with `sys.platform` branches: no ignores, no config change (`handoff.py`, `inventory.py`, `installer.py`, `lab/ocr_benchmark.py`, three tests) | `mypy --platform win32/linux/darwin`: all clean. Side effects: the lock probe raises `HandoffError` rather than `ImportError` on Windows, and the xattr helpers raise `OSError(ENOTSUP)` |
| `7704dc8` | The lab driver finishes a hover on a `not_korean` direct-text outcome | the 7 "timed out" UIA Latin records in the final campaign were waiting on an event that never comes; fails before, passes after |
| `8594257` | `lab/tests/test_app_lab.py`: the bounded-output probe pins its child's stdout to UTF-8 | it failed whenever `PYTHONUTF8` was unset (cp1252 has no Hangul); environment-dependent and pre-existing |
| `24ac332` | The lab's process sampler runs in a separate process (`python -m lab.session.sampler`); the shell only publishes child roles; the venv launcher in front of the sampler is excluded from helpers | **root cause of the UIA deadline misses**: short campaigns (`--per-family 14`) had 79 and 111 direct-text timeouts with the in-process sampler on, 6 and 1 with it stubbed off, and 0 and 0 with the new sampler. psutil held the GIL in the lab-hosted shell, so this was a lab artifact, not product behaviour |
| `12b052c` | Reserved updater names are refused in any letter case: `.HANLY-UPDATE/...` (Windows/macOS tree paths and `require_safe_relative_path`) and case variants of `.hanly-manifest.json` | a case-insensitive filesystem would otherwise resolve them into the working area or the control file; 5 tests fail before and pass after; the real 6,834-entry Windows manifest still validates; Linux stays case-exact |

## Verified (with evidence)

- **WIN-UPD-01 fix reproduced:** pre-fix code fails the regression with
  `'.hanly-manifest.json' is inside the updater's own working area`; the fixed
  code passes. `require_installable_path` admits only the exact control-file name.
- **Affected installed Windows versions:** 0.5.3 (`4f9547b`), 0.9.0 (`e75ef4b`) and
  1.0.0 (`9e44e38`) all have schema-2 `WindowsFileStaging` plus
  `require_safe_relative_path(self.path)` in the journal. 0.5.2 has no tree
  staging (a different path).
- **Release-side workarounds, simulated against the legacy rule** (scratch script
  monkeypatching both call sites back to `require_safe_relative_path`):
  - release as today → fails;
  - **omit `.hanly-manifest.json` from the new release → fails** (the base owns it,
    so the plan gets a DELETE of the same path);
  - **full download instead of delta → fails** (same staging and journal);
  - control file byte-identical to the base → stages. This is not a safe fix: the
    installed V1 inventory would then describe the old build, and
    `read_installed_manifest` feeds the next differential base, so it would break
    integrity and future updates.
- **Migration recommendation (needs a human decision):** no release-manifest
  change rescues stranded 0.5.3/0.9.0/1.0.0 Windows clients without damaging
  integrity or future updates. Recommend a one-time manual replacement (download
  the fixed build's ZIP and replace the folder; settings and KRDICT live in the
  profile), announced in release notes. Those clients show "Update failed: …
  working area" and change nothing. Release tooling is unchanged.
- **The isolated 0.9.0 → 1.0.0 check proves this branch's updater**, not the one
  embedded in installed builds (`lab check windows-update` drives the checkout's
  updater against the real release source).
- **Final campaign `20261002-192328-stress` recomputed from `events.jsonl`:**
  - 1,158 planned = 1,158 results, no duplicate IDs. Verdicts: correct 729,
    misread 124, wrong_lemma 2, refused 18, quiet 210, withheld 40, observed 26,
    obscured 6, obscured_during_capture 3.
  - The 35 unscored are 9 covered-under-cover (6 + 3), 11 covered-outside-cover
    evidence (9 correct, 1 wrong, 1 NOT_FOUND) and 15 changing.
  - All 124 misreads: neither the live nor the replayed normalized recognition
    contains the target surface, so they are genuine OCR-level misrecognitions.
  - Replay "124/124 same as live" compares status and selection only. The
    recognized lines are identical for 123/124; `m007-ko` replay adds one extra
    line (`대이`). **The report must say this.**
  - Repeat family: 0/60 cache hits. Repeats render at a different size and face
    and the cache is exact-input, so this measures re-recognition, not caching.
    1,318 cache hits happened on hovers outside any scored window; 5 inside, all
    in `after_popup`.
  - No stale or late popups; negatives 228: 210 quiet + 18 refused.
- **Bundles exclude the lab:** 0 `lab.*` or `tests.*` modules among the 6,302
  frozen modules; no `_internal/lab`.
- **Tracked diff `main...HEAD`:** no images, binaries, artifacts or dist files.
  Machine-path hits are env-var names and test fixtures only.
- **Gates at `24ac332` (before the last fix):** portable 2,401 passed / 105
  skipped; native 121 / 33. After `12b052c`: updater + manifest tests 196 passed /
  36 skipped; ruff clean; mypy clean on win32/linux/darwin. Full portable and
  native were **not** rerun at `12b052c`.
- **Fresh build at `12b052c`** (old `9fe7c41` products moved to
  `dist/archive-9fe7c41-windows/`, not deleted):
  - build id `821d84d0-27a3-4614-a284-25952ff0bdd7`, 1.0.0, CPython 3.13 venv; log
    in `dist/phaseb-build-12b052c.log`;
  - ZIP sha256 `a80b88a07f02a7b73aeb519dea3dd33af7766512ca53aab81b01786281012be2`;
  - reconstructed into `dist/reconstructed-12b052c/`: all 6,834 manifest entries
    match by size and hash, nothing undescribed or missing, and the control file
    is described;
  - `pytest --suite packaged` with `HANLY_EXPECTED_SOURCE_COMMIT` and
    `HANLY_REQUIRE_PACKAGED=1`: **5 passed** on the build and **5 passed** on the
    reconstruction (`HANLY_PACKAGED_APP`);
  - `lab check run` BUNDLE-IDENTITY, -WINDOW, -WORKER and -LAUNCH-IDENTITY-WIN with
    that SHA: 4/4 passed.
- **`lab check windows-update` at `12b052c`:**
  - install passed (`20261002-223240`);
  - cancel passed (`20261002-223936`);
  - **rollback failed once** (`20261002-224157`: "the update helper did not start;
    nothing has been changed"; remnants were the working area, the recovery
    `hanly-update-helper.ps1` and one challenge);
  - rollback passed with a diagnostic wrapper that extended the claim wait
    (`20261002-225328`; **not an unmodified pass**);
  - install passed again with the wrapper (`20261002-231221`);
  - one unmodified rollback (`20261002-232003`) was interrupted by the human and has
    no summary. Its lab-owned 0.9.0 processes (exe under that run directory) were
    stopped by PID.

## Open finding: Windows helper claim latency (investigate first)

- `CLAIM_WAIT_SECONDS = 30` (`updates/helper.py:44`). The shell waits that long for
  the PowerShell helper to write its claim before declaring "did not start" and
  abandoning (safe: nothing changes).
- Measured spawn → claim: **5.4 s** in install mode (no app running) and **25.6 s**
  in rollback mode (the old build is running, as for a real user). One rollback
  missed the 30 s window entirely.
- Unloaded, `powershell.exe` cold start plus parsing a 6,834-entry JSON takes
  0.37–0.41 s, so the delay is environmental. Suspects:
  - Defender/AMSI scanning the 650 MB payload unpacked just before the spawn, or the
    script itself;
  - load from the running app.
- The human reports that PowerShell "takes more than an hour to finish" on the
  rollback run that was interrupted. **Not yet investigated.** A system load sample
  for that window is at
  `%TEMP%\claude\C--Hanly\2dbed427-…\scratchpad\load.jsonl`, the session
  scratchpad (top processes > 20 % CPU every 2 s), and has not been read.
- **Do not raise `CLAIM_WAIT_SECONDS` without a root cause and human approval.**
  Next steps:
  1. Read `load.jsonl` and correlate it with the run's events.
  2. Log the helper's own timestamps (process start vs. claim `at`) in a lab run.
  3. Test the Defender hypothesis by timing a PowerShell start right after
     unpacking a large payload. Do not change security settings without approval.
  4. Check whether the hour-long run was the helper waiting in `Wait-ForStartup`
     on a sabotaged executable, which would be expected for rollback, against a
     genuine hang.
- Diagnostic scratch scripts (session scratchpad, not in the repo):
  - `rollback_claim.py <mode>`: extends the claim wait to 180 s and prints the
    spawn → claim time;
  - `rollback_why.py`: prints the coordinator failure message;
  - `legacy_options.py`: the release-workaround simulation;
  - `verify_campaign.py <run>`: recounts a campaign;
  - `uia_sampler_ab.py on|off`: the sampler A/B;
  - `reconstruct.py`: ZIP reconstruction and inventory check;
  - `load.py`: the system load sampler.

  The scratchpad may not survive. Recreate a script from its description here if
  needed.

## Pending (everything)

1. **Helper claim latency / the hour-long rollback.** Investigate as above, then
   get unmodified rollback passes or record the defect with evidence. Also check
   whether a failed handoff's remnants (working area, recovery script, challenge)
   are cleaned at the next launch.
2. **Lab: record the coordinator failure reason in `windows-update` summaries**
   (exception class and the fixed message text, no paths). It currently records
   only "staging ended failed".
3. **Lab: replay provenance.** `stress-replay` output has no code commit or dirty
   flag, and `same_as_live` ignores recognized lines. Add both, with a test.
4. **Re-run the full stress campaign** (`python -m lab stress`, seed 11, same
   machine) at the new HEAD, now that the sampler and direct-text fixes are in.
   UIA numbers will change: compare against `20261002-192328-stress`. Then
   `stress-replay` the misreads again.
5. **Final gates at the final HEAD:**
   - `pytest --suite portable` and `--suite native`;
   - ruff;
   - mypy (default plus `--platform win32/linux/darwin`).
   - If shipped code changes again: commit, rebuild fresh (move `dist/windows` and
     products to `dist/archive-12b052c-windows/`), then rerun packaged on the build
     and the reconstruction, the BUNDLE-* checks and all three windows-update modes.
6. **Docs (Phase B outcome):**
   - Append to `review-handoffs/lab-windows-implementation-and-stress.md`:
     - verdict;
     - verified claims;
     - defects with commits (table above);
     - dismissed concerns;
     - deferrals with triggers;
     - exact test, build and campaign outcomes;
     - the migration recommendation and the decision needed;
     - Mac checks;
     - review-ready vs shipping/migration-ready.
   - Update `reports/lab-windows-validation-and-stress.md`:
     - stranded versions are **0.5.3, 0.9.0, 1.0.0** (not only 0.9.0/1.0.0);
     - omitting the control file does **not** help;
     - UIA timing is now attributed to the lab sampler;
     - replay 123/124 identical lines;
     - unscored breakdown;
     - win32 mypy is fixed;
     - the "no rebuild needed" line is superseded by the `12b052c` build.
   - Update `checkpoints/app-health-lab-2026-10-01.md` to point here.
7. **Deferrals to record:**
   - **User-visible failure text.** `Update failed: {error}` (pre-existing,
     `coordinator.py` `_finish_error`) can show the user's own absolute paths from
     an `OSError`. It is local display only, not persisted. Scrubbing it changes
     product behaviour, so it needs approval. Trigger: any error-presentation work.
   - Mixed DPI / >100 % scaling: untested here (two 1080p displays at 100 %).
   - Single instance on Windows: a product decision.
   - OCR misreads (EasyOCR); the replay corpus is ready.
   - 누군가 is missing from KRDICT.
   - Friend's screenshot cases need the original images.
8. **Mac checks that still need a Mac:**
   - `UPDATE-APPLY-POSIX`;
   - `tests/native/shared/test_update_posix_native.py`;
   - `MAC-IDENTITY`;
   - packaged Mac `test_frozen_identity`;
   - the Mac Control Center stage-animation probe;
   - a Mac regression of `deb72a6`/`12b052c`: the receipt-directory check and
     case folding on APFS.

   Shared changes to re-verify there: `handoff.py` win32 branches (unreachable on
   POSIX), `runner.py` challenge cleanup, `manifest.py` folding.
9. **Cross-platform review items not yet written up.** All are unchanged by
   inspection; record them in the outcome:
   - the single entry point and three-process model;
   - import separation;
   - the final request-currency check;
   - non-success behaviour.

## Not to do

- Push, merge, tag or release.
- Omit `.hanly-manifest.json` or weaken integrity checks.
- Raise timeouts to improve scores.
- Open or delete the old Mac private-content run.
- Add Co-authored-by or any attribution.
