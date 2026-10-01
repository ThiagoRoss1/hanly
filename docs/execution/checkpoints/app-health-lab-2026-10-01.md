# App health lab — continuation checkpoint

**Updated:** 2026-10-01. **State:** planning/setup only; no lab code, tests, bug fixes, run report or Review Handoff exists yet.

- Local branch: `codex/app-health-lab`, created from `main` at `9e44e3857eedb8743ce967d9a9d262ac99c1dfef`. No push, merge, tag or release was performed for this lab.
- Execution prompt and scope: [`../plans/app-health-lab-2026-10-01.md`](../plans/app-health-lab-2026-10-01.md). Read it in full, then inspect the live worktree; this checkpoint must never override actual code or test evidence.
- Approved safety decision: all real updater scenarios use an isolated test installation and profile. The user's everyday installation/profile must not be used or mutated without separate explicit approval.
- Git authorization: commit completed features, fixes or coherent small bundles locally after relevant checks, with English conventional subjects and short English action-bullet bodies. Use the configured human author and no assistant/co-author trailers. The user alone will push and merge; no tag or release is authorized.
- Sequence: Mac foundation and Mac validation → stop at its Review Handoff; Windows implementation/validation when resumed on the Windows machine → stop at its handoff; human-authorized Claude deep review/refactor later.
- Known reports to investigate: `WIN-UPD-01` install loop, `WIN-UPD-02` empty owned directory, `UI-UPD-03` repeated stage animation, `MAC-START-04` transient apparent second app. None is diagnosed or fixed by creating this checkpoint.
- Existing related surfaces found: `benchmarks/dev/` developer harness; `updates/coordinator.py`, `updates/installer.py`, `updates/handoff.py` and `updates/cleanup.py`; Control Center `renderUpdates()`; native/packaged update tests. Existing Mac updater reportedly works, but this lab has not run it.

## Resume instructions

1. Inspect branch, worktree, commits, interpreter and any newer artifacts. Preserve all existing changes; do not reset or replay work from this checkpoint.
2. Read the execution prompt, repository instructions and relevant code. Determine whether the active boundary is Mac foundation, Windows continuation or separately authorized review.
3. Append only meaningful progress: completed scenarios and actual evidence, tests and results, current blocker/hypothesis, modified files, and the exact next safe action. Mark unrun checks `not run`.
4. If context or time is running low, stop at a coherent boundary and update this file before ending the session. A fresh agent should be able to continue without chat history.
