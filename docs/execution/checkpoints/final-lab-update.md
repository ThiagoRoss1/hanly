# Final Lab update — checkpoint

Plan: [`../plans/final-lab-update.md`](../plans/final-lab-update.md). Handoff:
[`../review-handoffs/final-lab-update.md`](../review-handoffs/final-lab-update.md).
Branch `lab/app-health`, from `d05b8db`. Phase A only.

## State: stopped at the Review Handoff

| Wave | State | Commits |
|---|---|---|
| Brief | done | `d9a27e8` |
| 1 Identity, provenance, registry | done | `8de9410` |
| 2 Comparison and compact explanations | done | `f3db81c` |
| 3 Storage inventory and GC | done | `3f7ec7f` |
| 4 Controlled-image corpus | done | `bb1c337` |
| 5A+5B Stage facts, repeatability | done | `74ed3ce` |
| 5C Corpus through stress | done | `47ce842` |
| 5D Backend differential | done | `6356154` |
| Suppression cleanup | done | `28e25c3` |
| 6 Real-run fixes, docs, handoff | done | `123693a`, `f0fdd7c`, `7236dc6`, handoff commit |

## Validation

ruff and mypy clean; `--suite portable` 2640 passed, 2 pre-existing skips;
`--suite native` 126 passed. Real Mac runs and their results are listed in the
handoff. Phase B has not started; nothing was pushed, merged, tagged or released.

## Decisions worth keeping

- `lab_provenance` v1 is additive; legacy runs are read from old fields and
  flagged "source read at shutdown".
- Performance comparison needs a known protocol and equal host on both sides;
  legacy runs compare correctness only.
- GC trusts only a run's own `lab_provenance.disposable`, after the writer kept
  its logs; nothing on this Mac is eligible.
- Corpus stress is judged by `corpus-surface-v1` (selection, not dictionary).
- 5A and 5B share a commit because stability is computed from the same facts.

## Continue (Windows)

Follow "Windows continuation" in the handoff. Real GC application needs the
human's separate approval.
