# App health lab — continuation checkpoint

**Updated:** 2026-10-01. **State:** Mac Phase A stopped at its [Review Handoff](../review-handoffs/app-health-lab-mac-2026-10-01.md). Windows implementation and human-assigned Phase B are not started.

- Local branch: `lab/app-health`, created from `main` at `9e44e3857eedb8743ce967d9a9d262ac99c1dfef`. No push, merge, tag or release was performed for this lab.
- Execution prompt and scope: [`../plans/app-health-lab-2026-10-01.md`](../plans/app-health-lab-2026-10-01.md). Read it in full, then inspect the live worktree; this checkpoint must never override actual code or test evidence.
- Approved safety decision: all real updater scenarios use an isolated test installation and profile. The user's everyday installation/profile must not be used or mutated without separate explicit approval.
- Git authorization: commit completed features, fixes or coherent small bundles locally after relevant checks, with English conventional subjects and short English action-bullet bodies. Use the configured human author and no assistant/co-author trailers. The user alone will push and merge; no tag or release is authorized.
- Sequence: Mac foundation and Mac validation → stop at its Review Handoff; Windows implementation/validation when resumed on the Windows machine → stop at its handoff; human-authorized Claude deep review/refactor later.
- Reported cases: `UI-UPD-03` is corrected; `MAC-START-04` has an evidenced source-child correction, with normal frozen-child identity still unvalidated. `WIN-UPD-01` install loop and `WIN-UPD-02` empty owned directory remain for real Windows investigation.
- Existing related surfaces found: `benchmarks/dev/` developer harness (moved to `lab/` by `4da283c`; the `app-lab` command is now `lab check`); `updates/coordinator.py`, `updates/installer.py`, `updates/handoff.py` and `updates/cleanup.py`; Control Center `renderUpdates()`; native/packaged update tests. Existing Mac updater reportedly works, but this lab has not run it.

## Implementation decisions

- Reuse fixed existing pytest cases as bounded scenarios; label real UI with injected services separately from a full source app or frozen build. Keep unsupported and human-operated cases visible in the coverage inventory.
- Each scenario owns a temporary test workspace and redirected child profile. Persist only typed outcomes, counts, process roles/activation types and resource samples; discard raw subprocess output after reading its bounded summary.
- Declare `psutil` only in developer dependencies for process-tree sampling and cleanup. Public engine contracts and runtime extras are unchanged; PyInstaller nevertheless collected it transitively. Track the original process birth identity and owned handles so cleanup does not target unrelated applications.
- `app-lab list/run` now exposes fixed scenarios with isolated profiles, bounded output, process observation, safe JSON/HTML coverage and nonzero exit for unavailable/failed selections.
- `UI-UPD-03` reproduced in real Chromium before correction: unchanged text was replaced at every poll, restarting both entry motion and infinite shimmer. The busy view now survives progress updates; the label animates once per text change. Normal/reduced-motion native cases passed.
- `MAC-START-04` captured in run `926f2121-a857-4a79-96b8-468166dc3437`: child PID 69128 changed Foreground → UIElement at 606.8/748.9 ms. Cocoa transformed the process during QApplication creation, before the existing Accessory policy. The child now sets Qt's foreground-transform opt-out before creating QApplication. No shell/Windows/Linux policy change.
- Post-fix source run `40bcdf1f-85d1-4315-8125-4702d7f57cbf`: startup, Mac identity and window lifecycle passed. Sampling cannot exclude flashes shorter than the inspection interval; initialization-order regression tests cover the causal boundary deterministically.
- Run `70e3c2cf-d757-4c0d-a510-d154d9bcaa80`: stage motion, Control Center lifecycle/controls, capture choice, hover/popup and settings all passed. Run `926f2121-a857-4a79-96b8-468166dc3437` also verified 26 coordinator, 25 POSIX helper and 58 resource cases. Helper builds are simulated; not a whole-release update.
- Final portable: 2391 passed, 2 skipped; full native: 125 passed; strengthened real motion cases: 2 passed; lab contracts: 26 passed. Ruff and mypy clean, 312 files. An introduced CLI help-order failure was corrected, not dismissed as pre-existing. Python 3.10 syntax parsed; actual 3.10 runtime not run.
- Fresh frozen build: original clean `e15204df2d14aa0ecefc6ec5a7d9a8b93ab69efc`, version 1.0.0 arm64. ZIP and DMG reconstructions each match 7,342 manifest entries, retain valid signatures and pass all four packaged cases with that SHA required. Later changes are developer tests/observation and docs, not shipped code/assets.
- Final observer run `b64386da-9c0c-4ce8-b9e5-aac2ccb84c43`: startup, source identity, two stage-UI cases and 25 POSIX helper cases pass. Actual `source_dirty=true` is retained in the record; this run does not claim a clean source snapshot.
- Human explicitly authorized rewording only two unpublished messages. Eight commits, authors and code trees are preserved; implementation head is `432b466`. The report records the old/new hash mapping and unchanged tree. The existing build and run stamps keep their original hashes.
- Frozen standalone UI probes still sample Foreground → UIElement; their passing verdict covers the page, bridge and exit, not normal frozen-child Dock identity. Do not turn the source-child correction into an unverified packaged identity claim.
- Next safe implementation boundary: real Windows continuation after the human resumes it. Use the executable section in the Mac handoff. The full Windows update, normal frozen Mac identity, live hover and cross-display checks remain explicit gaps; final deep review is separately authorized.

## Lab evolution and hardening (2026-10-01, later)

- `benchmarks/dev/` became the top-level `lab/` (`4da283c`), with `python -m lab` / `lab tour` / `lab report` added (`a066076`) and documented (`fc4d257`). The hardening bundle is `c8db0a6`..`bd7527b` plus the final docs commit; its [Review Handoff](../review-handoffs/lab-hardening-mac-2026-10-01.md) is the authoritative record.
- Tour baseline `artifacts/lab/runs/20261001-053159-tour` (on `fc4d257`, rule v1) is preserved; under `strict-headword-v2` it scores 443/453. The corrected standard tour `20261001-171914-tour` scores 446/453, 0 unscored, with the same settings and a one-word corpus change (애기 → 삼총사).
- Fresh macOS build from `bd7527bb8cfc245a577c6b37bce5054e4f8619ea`: ZIP and DMG reconstructions match all 7,342 manifest entries, pass strict signature checks, and pass 4/4 packaged cases with that SHA required. The earlier `e15204d` build was moved to `dist/archive-e15204d/`.
- Local artifact to remove by hand: `artifacts/lab/runs/20261001-043306-tour` holds real screen text from before the ownership guard existed.
- Next safe boundary: the Windows continuation (tour ownership via `WindowFromPoint`, then `WIN-UPD-01`/`WIN-UPD-02`). Deferred lookup/OCR/capture items are listed in the hardening handoff.

## Mac completion bundle (2026-10-01, latest)

- Commits `b88ba79` (timeout scoring, rule v3), `d7f598e` (read text out of recordings unless `--retain-fixture-text`), `c29702a` + `9485fac` (frozen launch-identity check, `BUNDLE-LAUNCH-IDENTITY`), `5434009` (unfinished-tour reporting), plus the docs commit that records this.
- Gates: portable 2,475 passed / 2 skipped, native 125, ruff and mypy clean on 326 files. Packaged 5/5 on the ZIP and DMG reconstructions of `bd7527b` with that SHA required. `check` 11/11 source scenarios and 4/4 bundle scenarios on each reconstruction.
- Frozen normal-launch identity is now observed: the shell is Foreground; no child is ever Foreground; all exit on quit.
- Standard tour `20261001-210808-tour`: 446/453 under v3, 0 changed verdicts against `20261001-171914-tour`.
- The Mac acceptance matrix and the exact meaning of "Mac complete" are in the [hardening handoff](../review-handoffs/lab-hardening-mac-2026-10-01.md#mac-completion-bundle-2026-10-01-later).
- Still open: deletion of `artifacts/lab/runs/20261001-043306-tour` (needs human authorization, that path only). Windows continuation as listed in the handoff.

## Resume instructions

1. Inspect branch, worktree, commits, interpreter and any newer artifacts. Preserve all existing changes; do not reset or replay work from this checkpoint.
2. Read the execution prompt, repository instructions and relevant code. Determine whether the active boundary is Mac foundation, Windows continuation or separately authorized review.
3. Append only meaningful progress: completed scenarios and actual evidence, tests and results, current blocker/hypothesis, modified files, and the exact next safe action. Mark unrun checks `not run`.
4. If context or time is running low, stop at a coherent boundary and update this file before ending the session. A fresh agent should be able to continue without chat history.
