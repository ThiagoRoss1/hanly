# Bundle Workflow Consistency Review

Review date: 2026-08-20. Scope: the uncommitted bundle-workflow changes to
`docs/execution/05-execution-plan.md`, `docs/architecture/04-agent-execution-flow.md`,
`docs/architecture/visual/Hanly Agent Execution Flow.html`, and `CLAUDE.md`, plus the live
Hanly Desktop V1 Linear project. Review only; no file, Linear, or Git action was taken.

## Overall result

`CHANGES REQUIRED`

The bundle model itself is sound, faithfully synchronized, and preserves every safety property
that was asked about. One regression introduced by the rewrite blocks the next execution run:
the instruction that promotes newly unblocked work to `Todo` was dropped, and the live Linear
project already shows the resulting stall.

## What changed

- `05-execution-plan.md`: default unit changed from one issue to an issue *or* an execution
  bundle; `Start and READY selection` became `Start and execution-unit selection`; the single
  one-issue loop was split into `Single-issue execution` and `Bundle execution and internal
  progression`; new `Validation proportionality` section; `BUNDLE-READY` defined as an execution
  convention; Linear-hygiene paragraph forbidding bundle parent issues, milestone repurposing,
  and speculative bundle objects; 3-5 Luna workstream target; pause/resume extended to bundle
  reconstruction; example commands updated.
- `04-agent-execution-flow.md`: new `Execution units` section; internal-progression rule added to
  the sources-of-truth section; Sol/Terra/Luna and internal-review roles restated for bundles;
  Linear execution loop redrawn; `AEF-INV-10`, `-11`, `-12` reworded.
- `Hanly Agent Execution Flow.html`: single-line bundle synchronized with the above.
- `CLAUDE.md`: one added sentence pointing at the `05` bundle rules.
- `03-implementation-dag.md`, `01`, `02`: unchanged.
- Linear: unchanged (verified - no bundle labels, no parent issues, milestones and blockers intact).

## Consistency check

| Verified property | Result |
|---|---|
| HAN issues remain granular tracking units | PASS - `04:34`, `05:38`, `05:77`; all 33 issues intact in Linear with original scopes, criteria, priorities, milestones |
| Bundles are orchestration/review units, not HAN replacements | PASS - `04:7`, `04:34`, `05:38` all state it explicitly |
| Bundle formation follows DAG + Linear dependencies/convergence | PASS - `05:27-29`, `04:32`; consecutive-number grouping and gate-crossing explicitly prohibited |
| Internal HAN dependencies may progress after focused validation | PASS - `05:50` (`BUNDLE-READY`), `04:28` |
| Intermediate progress does not imply human approval | PASS - `05:50`, `05:75`, `04:28` all deny it in the same sentence that grants progression |
| `Done` requires explicit human approval | PASS - `05:43`, `05:57`, `05:74` |
| Commit/push/merge separately human-authorized | PASS - `04:150-163` unchanged; `05:57`, `05:132` |
| Per-HAN testing focused and proportional | PASS - `05:61`, `04:84` |
| Broader integration/regression at bundle level | PASS - `05:63`, `05:54`, `04:84` |
| Necessary tests not weakened or removed | PASS - `05:63` keeps early tests early and forbids deferring a failing invariant; `05:52` stops internal progression on local failure; Linear acceptance criteria unchanged |
| Sol/Terra amortized across the bundle | PASS - `04:70`, `05:99` |
| 3-5 Luna `xhigh` target without artificial workers | PASS - `04:80`, `05:101`; both state "not a quota" |
| Luna model/reasoning and `UNVERIFIED` policy intact | PASS - `04:62-68` byte-identical to the approved text |
| Bundle-level human review mandatory | PASS - `05:55`, `04:126` |
| Execution stops after the authorized bundle | PASS - `05:57`, `05:113`, `05:144`, `04:36` |
| Linear blockers, milestones, priorities, scopes valid | PASS with one live-state defect - see Finding 1 |
| `03`/`04`/`05`/`CLAUDE.md`/HTML semantically consistent | PASS with notes - see Findings 2-4 |
| No V1 product scope or product architecture changed | PASS - `01`, `02`, `03` untouched; no `DAG-INV`, `RF-INV`, or `CA-INV` altered; no issue description changed |

The `AEF-INV-*` list was extracted from the HTML bundle and compared item by item: 19 invariants,
same order, same identifiers, text matching `04` exactly, including the three reworded entries.
The 1:1 mapping required by `CLAUDE.md` holds.

## Findings

### Finding 1 - The `Todo` promotion step was dropped; no issue is currently selectable

- **Severity:** High
- **Source:** `docs/execution/05-execution-plan.md:43` and `:57`; live Linear project
- **Issue:** The pre-change plan ended its loop with "After approval, update Linear, reevaluate
  real dependencies, identify newly READY issues, **and move newly actionable work to `Todo` when
  appropriate**." The rewrite reduced both completion steps to "reevaluate dependencies" (`:43`)
  and "reevaluate native Linear dependencies" (`:57`). Nothing in `05`, `04`, or `CLAUDE.md` now
  instructs anyone to move an unblocked issue from `Backlog` to `Todo`. Selection step `05:26`
  still requires a root whose "Linear state is `Todo`". The live project shows the consequence
  already: HAN-1 is `Done`, HAN-2, HAN-3, and HAN-4 are `blockedBy` HAN-1 only and are therefore
  substantively READY, yet all three - and every other issue - are still `Backlog`. Under
  `05:26` the next run finds zero eligible roots, so neither a single issue nor a bundle can be
  derived. The two halves of the defect are independent: restoring the instruction does not fix
  the current state, and fixing the current state does not stop it recurring.
- **Must be fixed before the next execution run:** Yes, both halves.

### Finding 2 - `BUNDLE-READY` appears in the visual companion but is undefined in `04`

- **Severity:** Medium
- **Source:** `docs/architecture/visual/Hanly Agent Execution Flow.html` (Linear input node,
  "READY root / BUNDLE-READY internal", and the DAG/Linear note) vs `04-agent-execution-flow.md`
- **Issue:** `CLAUDE.md` makes `docs/architecture/*.md` authoritative and the HTML its
  synchronized companion. `04` describes the mechanism at `:28` and `:34` but never names it; the
  term `BUNDLE-READY` is defined only in `05:50`. The diagram therefore surfaces a labelled state
  that its own authority does not define, so a reader working from `04` alone cannot resolve it,
  and the visual currently leads its Markdown source. This is the same class of fidelity defect
  `REVIEW-2026-08-18.md` grades as A.
- **Must be fixed before the next execution run:** No. It does not affect execution behavior, but
  it should be closed before the next architecture-doc change so the visual does not drift further.

### Finding 3 - `AEF-INV-11` now carries a numeric team-size target that `AEF-INV-18` forbids

- **Severity:** Low
- **Source:** `docs/architecture/04-agent-execution-flow.md:212` vs `:222`
- **Issue:** `AEF-INV-18` states that flexible wording "must not be converted into mandatory
  delegation or **team-size rules**." `AEF-INV-11` now embeds "three to five Luna workstreams is a
  target." The qualifier "not a forced count" keeps it a target rather than a rule, so the two are
  reconcilable as written, but a numeric team-size figure now sits inside the invariant list that
  `AEF-INV-18` exists to protect, and a future reader may treat it as the quota `04:80` and
  `05:101` both disclaim. This is a wording tension, not a contradiction.
- **Must be fixed before the next execution run:** No.

### Finding 4 - `05` declares bundles the normal unit; `04` and `CLAUDE.md` stay neutral

- **Severity:** Low
- **Source:** `docs/execution/05-execution-plan.md:5` vs `docs/architecture/04-agent-execution-flow.md:32`
  and `CLAUDE.md:9`
- **Issue:** `05:5` reads "The normal orchestration unit is an execution bundle..."; `04:32` reads
  "The authorized unit of work **may** be one substantial or isolated Linear issue, or an execution
  bundle"; `CLAUDE.md:9` reads "Execution **may** use one issue or a ... bundle." `05` owns
  operational default and `04` owns semantics, so this is defensible ownership rather than a
  conflict, and every document agrees the human authorizes the actual unit. Flagged only because
  the asymmetry could later be read as `05` setting an architectural default it does not own.
- **Must be fixed before the next execution run:** No.

### Informational - HAN-1 comment vs current CI file

Outside the bundle-workflow scope: HAN-1's approval comment records "Python 3.10 is configured in
package metadata, Ruff, mypy, and CI." The working tree's `.github/workflows/ci.yml` now runs a
3.10-3.13 matrix. The change is uncommitted and post-approval; no action implied by this review.

## Final recommendation

The bundle-based workflow is **not yet ready** for the next real Hanly execution run, for one
narrow and mechanical reason: Finding 1. Restore an explicit instruction in `05` that newly
unblocked issues move to `Todo` after approved work reaches `Done`, and bring the live Linear
project into that state so at least one root is selectable, and the workflow is ready.

Everything else holds. No test, acceptance criterion, blocker, milestone, priority, issue scope,
invariant identifier, worker-model policy, `UNVERIFIED` rule, human-approval gate, or Git-authority
rule was weakened, and no V1 product scope or product architecture was touched. Findings 2-4 are
documentation-hygiene items that can be handled in the next architecture-doc pass without delaying
execution.

Once Finding 1 is resolved, the first run should explicitly authorize either one issue or one
dynamically derived bundle and stop at that unit's human checkpoint.
