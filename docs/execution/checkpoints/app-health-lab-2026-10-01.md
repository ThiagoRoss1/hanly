# App health lab — continuation checkpoint

**Updated:** 2026-10-01. **State:** Mac foundation implemented; final gates and fresh packaged validation in progress. No Review Handoff yet.

- Local branch: `lab/app-health`, created from `main` at `9e44e3857eedb8743ce967d9a9d262ac99c1dfef`. No push, merge, tag or release was performed for this lab.
- Execution prompt and scope: [`../plans/app-health-lab-2026-10-01.md`](../plans/app-health-lab-2026-10-01.md). Read it in full, then inspect the live worktree; this checkpoint must never override actual code or test evidence.
- Approved safety decision: all real updater scenarios use an isolated test installation and profile. The user's everyday installation/profile must not be used or mutated without separate explicit approval.
- Git authorization: commit completed features, fixes or coherent small bundles locally after relevant checks, with English conventional subjects and short English action-bullet bodies. Use the configured human author and no assistant/co-author trailers. The user alone will push and merge; no tag or release is authorized.
- Sequence: Mac foundation and Mac validation → stop at its Review Handoff; Windows implementation/validation when resumed on the Windows machine → stop at its handoff; human-authorized Claude deep review/refactor later.
- Known reports to investigate: `WIN-UPD-01` install loop, `WIN-UPD-02` empty owned directory, `UI-UPD-03` repeated stage animation, `MAC-START-04` transient apparent second app. None is diagnosed or fixed by creating this checkpoint.
- Existing related surfaces found: `benchmarks/dev/` developer harness; `updates/coordinator.py`, `updates/installer.py`, `updates/handoff.py` and `updates/cleanup.py`; Control Center `renderUpdates()`; native/packaged update tests. Existing Mac updater reportedly works, but this lab has not run it.

## Implementation decisions

- Reuse fixed existing pytest cases as bounded scenarios; label real UI with injected services separately from a full source app or frozen build. Keep unsupported and human-operated cases visible in the coverage inventory.
- Each scenario owns a temporary test workspace and redirected child profile. Persist only typed outcomes, counts, process roles/activation types and resource samples; discard raw subprocess output after reading its bounded summary.
- Add `psutil` only to developer dependencies for process-tree sampling and cleanup. No shipped runtime or engine dependency changes. Track owned process handles so cleanup does not target unrelated applications.
- `app-lab list/run` now exposes fixed scenarios with isolated profiles, bounded output, process observation, safe JSON/HTML coverage and nonzero exit for unavailable/failed selections.
- `UI-UPD-03` reproduced in real Chromium before correction: unchanged text was replaced at every poll, restarting both entry motion and infinite shimmer. The busy view now survives progress updates; the label animates once per text change. Normal/reduced-motion native cases passed.
- `MAC-START-04` captured in run `926f2121-a857-4a79-96b8-468166dc3437`: child PID 69128 changed Foreground → UIElement at 606.8/748.9 ms. Cocoa transformed the process during QApplication creation, before the existing Accessory policy. The child now sets Qt's foreground-transform opt-out before creating QApplication. No shell/Windows/Linux policy change.
- Post-fix source run `40bcdf1f-85d1-4315-8125-4702d7f57cbf`: startup, Mac identity and window lifecycle passed. Sampling cannot exclude flashes shorter than the inspection interval; initialization-order regression tests cover the causal boundary deterministically.
- Run `70e3c2cf-d757-4c0d-a510-d154d9bcaa80`: stage motion, Control Center lifecycle/controls, capture choice, hover/popup and settings all passed. Run `926f2121-a857-4a79-96b8-468166dc3437` also verified 26 coordinator, 25 POSIX helper and 58 resource cases. Helper builds are simulated; not a whole-release update.
- Full native gate: 125 passed. First portable convergence: 2388 passed, 2 skipped, 1 failure from moving app-lab ahead of dev-hud in help. Corrected by preserving dev-hud first; 41 focused CLI/lab tests then passed. Full portable rerun remains pending.
- Commits through `2099ac2` separate lab foundation, observer typing correction, stage-label fix, Mac identity fix and report improvements. The first feature commit's body contains literal `\\n` separators; later bodies use proper action-bullet lines. No history was rewritten to correct formatting.
- Next: finish final portable/Ruff/mypy gates, commit this checkpoint and any validated remaining lab correction, build from the clean head, then run explicit frozen identity/window/worker scenarios. Write the Mac Review Handoff and stop. Windows evidence remains pending.

## Resume instructions

1. Inspect branch, worktree, commits, interpreter and any newer artifacts. Preserve all existing changes; do not reset or replay work from this checkpoint.
2. Read the execution prompt, repository instructions and relevant code. Determine whether the active boundary is Mac foundation, Windows continuation or separately authorized review.
3. Append only meaningful progress: completed scenarios and actual evidence, tests and results, current blocker/hypothesis, modified files, and the exact next safe action. Mark unrun checks `not run`.
4. If context or time is running low, stop at a coherent boundary and update this file before ending the session. A fresh agent should be able to continue without chat history.
