# Final Lab update — checkpoint

Plan: [`../plans/final-lab-update.md`](../plans/final-lab-update.md). Branch
`lab/app-health`, started from `d05b8db`. Phase A only.

## State

| Wave | State | Commit |
|---|---|---|
| Brief recorded | done | `d9a27e8` |
| 1 Identity, provenance, registry | done | `8de9410` |
| 2 Comparison and compact explanations | done | `f3db81c` |
| 3 Storage inventory and GC | next | |
| 4 Controlled-image corpus | not started | |
| 5A–5D Stage evidence, repetition, differential | not started | |
| 6 Integration, docs, handoff | not started | |

## Validation so far

`pytest lab/tests` 397 passed; ruff and mypy over `packages packaging tests tools
lab` clean at `f3db81c`. Real check: identities of all 62 Mac run directories are
read in 0.75 s; `20261005-mac-update`, `w17-frozen-1` and `w3-backend-probe` are
`unknown`. A rebuilt copy of `20261005-053840-tour` against `-053512-tour` is
comparable for correctness (453 matched occurrences, unchanged) with performance
unavailable because neither legacy tour records a protocol or host; the baseline
copy stayed byte-identical.

## Decisions

- Provenance is an additive `lab_provenance` block (version 1): start-time
  source, optional `source_at_end`/`source_changed`, platform, host
  (release, CPU count, RAM), kind, and kind-specific fields. Legacy fields stay.
- A legacy session's commit/dirty were read at shutdown; identity says so and
  reproduction is never exact for it.
- Compatibility key = kind / system-machine / observed backend / hash of the
  plan-deciding options. Plan fingerprints are compared separately.
- Performance needs both runs finished, one known measurement protocol and an
  equal host description; legacy runs therefore compare correctness only.
- Stress `false_positives` now counts presented answers only;
  `negatives_failed_otherwise` holds timeouts and errors.

## Continue

```bash
.venv/bin/python -m pytest lab/tests -q
.venv/bin/python -m ruff check packages packaging tests tools lab
.venv/bin/python -m mypy packages packaging tests tools lab
```

Then Wave 3 (`lab/storage.py`, `lab storage`, `lab gc`). Never apply GC to real
artifacts without the human's separate approval.
