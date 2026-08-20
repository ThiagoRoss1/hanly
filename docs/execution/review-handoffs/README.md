# Review Handoffs

Concise material produced at the end of an implementation bundle so that a later
reviewer can inspect that bundle efficiently. One handoff per bundle, written
from [`TEMPLATE.md`](TEMPLATE.md).

A handoff **prepares** the review. It never performs one, and it is never a
source of truth.

How this differs from its neighbours:

| Directory | Holds |
| --- | --- |
| `reports/` | Durable technical evidence whose value exists independently of any later review — cross-platform investigations, spike findings, long-lived technical results. |
| `checkpoints/` | Concise execution state needed to survive a pause or context loss. |
| `review-handoffs/` | What a later reviewer needs to review one completed implementation bundle. |

Writing the handoff is the last act of an implementation run. Deep review is a
separate, human-triggered phase — see the two-phase model in
[`../05-execution-plan.md`](../05-execution-plan.md).

## Two moments in one file

1. **Before review** the handoff is written by the implementation run and
   *prepares* the review. It performs none of it.
2. **After a separately authorized review runs**, that same file receives one
   concise appended **Post-Bundle Review Outcome**. There is no separate routine
   review-report file.

The outcome classifies every finding as exactly one of:

- **Fixed now** — cheap defensive hardening applied at a boundary during review,
  or a correction the human separately authorized.
- **Deferred** — valid but premature. **Must state its revisit trigger.**
- **Dismissed** — considered and rejected, or no longer relevant. Omit the
  section when empty.

Deferred items are the part with a long life: at final V1 validation the
deferred review sweep re-evaluates them against the completed V1, dismissing
what later work already solved and implementing only what then matters.

Keep the whole file concise. It is not a competing source of truth and never an
audit log.

These files are V1 execution scaffolding. After V1 they may be removed,
archived, or consolidated once their deferred considerations have been resolved
or intentionally carried forward. They are not permanent product documentation.
