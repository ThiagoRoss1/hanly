# Checkpoint — Wave 3 (Bundle B), Vision model-input scale

**Master plan:** `docs/execution/plans/text-acquisition-diagnostic-microscope-2026-09-20.md`
**Issue-local spec:** `docs/execution/plans/wave-3-vision-input-scale-2026-09-21.md`
**Authorized scope:** Bundle B — Wave 3 only. Waves 4–7 out of scope.
**Branch/worktree:** `visual/interface-update`, existing worktree reused. No
branch created, nothing committed.
**Interpreter:** `.venv/bin/python` (CPython 3.13.11).

Status: **complete.** Ends at the Wave 3 Review Handoff.

---

## Entry state

```
.venv/bin/python -m pytest  -> 1907 passed, 2 skipped   (after Phase B review)
ruff / mypy                 -> clean, 267 source files
```

The worktree carries several bundles. Wave 3 touched only the files listed
below; everything else was left alone.

## Work in two logically separate parts

The preflight evidence corrections and the product causal change are kept apart
deliberately, as instructed. They could be committed as two changes.

### Part 1 — preflight evidence corrections (diagnostic only, no product behaviour)

| Phase B finding | What was done |
|---|---|
| 4 — no artifact named the OCR backend | `LookupWorker` accepts the resolved backend and `_TracingOCRProvider` stamps `ocr_backend` on every OCR stage event. Both composition roots supply it: the spawned child from `LookupSettings.ocr_backend`, the in-process path from `resolved_ocr_backend()`. It flows into `FrozenLookup.backend`, `describe_frozen`, the export `metadata.json` and `diagnostic.json`, the inspector heading, and the live-hover run summary. |
| 5 — one counter conflated freeze with export | `SessionEvidenceCounts` reports `frozen_lookups_pinned`, `frozen_lookup_export_attempts`, `..._exports_succeeded`, `..._exports_failed`, `..._exports_refused_nothing_frozen`, `frozen_lookup_reexports`, and `frozen_lookups_exported` (distinct directories). Counts only — no identifiers, no screen content. |
| 6 / 7 — stale leading hypothesis | The checkpoint and baseline report no longer lead with right-edge truncation or Korean-specific recognition. Both are recorded as eliminated, with the evidence that eliminated them. |

Verified end to end in the real composition, not only by tests:

```
runtime resolved backend : vision
FrozenLookup.backend     : vision
describe live_ocr_backend: vision
export metadata backend  : vision
```

### Part 2 — the product causal change

`hanly/vision_provider.py`: `VisionConfig.input_scale` (default 2), applied in
`_png_bytes` by nearest-neighbour replication. One variable, one function. No
coordinate mapping needed — `_normalize` already denormalizes against the
original ROI.

## The experiment

The source page was gone, so live re-capture was impossible. It was not needed:
**the failure is perfectly deterministic from the exported pixels.** All three
captures replay byte-identically to their session records through the real
production provider, so the whole experiment ran on the real failure pixels with
no human interaction and no synthetic proxy.

| Experiment | Result |
|---|---|
| Replay fidelity | frozen-8/9/10 all reproduce their recorded output exactly |
| Partial-line contamination | Flips `frozen-9` **non-monotonically** (bottom-only succeeds, both-removed fails). Not a clean variable. |
| `VisionConfig` options | `language_correction`, `languages=(ko-KR,en-US)`, `minimum_text_height` 0.005/0.02/0.05 — **zero effect** on either failure |
| Background padding | Inconsistent: 2/3, then 0/3, then 3/3 |
| **Input scale** | **The reliable flip.** 1.0: control 7/7, failures 0/7. 2.0: all three 15/15, one distinct output each. |
| Odd/large factors | Unstable — 1.75 and 2.5 merge the numeral into the line |

ROI/grid offset could not be varied over real pixels: frozen-8 and frozen-9
overlap (pixel-identical, 0 of 6 048 differing) but their union leaves the
corners uncovered, so no full 200x100 window can be translated between them. It
is recorded as untested rather than excluded — and it is no longer needed, since
a different variable reliably flips the case.

## Before / after

Real failures, through the shipped provider:

| Capture | Before | After | p50 before | p50 after |
|---|---|---|---|---|
| frozen-8 (control) | `깨뜨렸습니다` OK | `깨뜨렸습니다` OK | 48.6 ms | 49.0 ms |
| frozen-9 | **None** | **`초대받았어요`** | 13.5 ms | 56.6 ms |
| frozen-10 | **None** | **`떨어뜨렸어요`** | 13.5 ms | 61.4 ms |

The failures' low "before" latency was the cost of finding almost nothing.
Control latency, the only apples-to-apples comparison (n=15): p50 46.7 → 47.5 ms,
p95 53.4 → 49.4 ms.

Unchanged 8-case synthetic corpus, Vision ocr-only
(`5b18673a…` before, `bc68750e…` after): exact match 1.00 → 1.00, CER 0.000 →
0.000, Hangul SER 0.000 → 0.000, false-empty 0.00 → 0.00, target surface 1.00 →
1.00, variance 0.00 → 0.00, warm p50 21.3 → 21.8 ms, warm p95 68.8 → 25.2 ms,
peak RSS growth 49.6 → 45.6 MB, 0 errors both.

## Exact commands

```bash
.venv/bin/python -m benchmarks.dev ocr-campaign --mode ocr-only --backend vision \
  --manifest artifacts/benchmarks/corpus/manifest.json --warmup 1 --samples 3
.venv/bin/python -m pytest
.venv/bin/python -m ruff check packages packaging tests tools benchmarks
.venv/bin/python -m mypy packages packaging tests tools benchmarks
```

## Gates

```
pytest -> 1928 passed, 2 skipped   (entry: 1907 passed, 2 skipped)
ruff   -> All checks passed
mypy   -> Success, 268 source files
```

## Artifacts

| Path | What |
|---|---|
| `artifacts/benchmarks/runs/ef2c1ffc-…/frozen-{8,9,10}/` | the preserved real control and failures |
| `artifacts/benchmarks/runs/5b18673a-…/` | corpus baseline **before** |
| `artifacts/benchmarks/runs/bc68750e-…/` | corpus baseline **after** |
| `artifacts/benchmarks/runs/w3-backend-probe/` | real-composition proof that the backend reaches an export |

All under the gitignored `artifacts/benchmarks/` root.

## Privacy state

Unchanged and re-verified. Freeze writes nothing; export is the only path that
persists pixels or recognized text, and only under the gitignored root. The
backend name is not screen content and carries no identifiers. The new counters
are integers only. The regression suite reads private captures from the artifact
root and skips when they are absent — it commits none of them.

## Files touched by Wave 3

Engine: `packages/hanly/src/hanly/vision_provider.py`.
App: `hanly_app/{composition,lookup_process,runtime}.py`.
Benchmarks: `benchmarks/dev/{frozen_lookup,microscope,live_runner}.py`.
Tests: `tests/{test_vision_provider,test_lookup_evidence}.py`,
`tests/native/shared/test_vision_scale_regression.py` (new),
`benchmarks/dev/tests/{test_microscope,test_live_runner}.py`.
Docs: this checkpoint, the issue-local spec, the Wave 3 handoff, and the
corrected wording in the Bundle A checkpoint and baseline report.

## Blockers

None.

## Exact next action

**Stop.** Wave 3 ends at
`docs/execution/review-handoffs/wave-3-vision-input-scale-2026-09-21.md`.

Next actions are the human's: authorize a Phase B review of Wave 3, or decide on
the deferred conditional-retry question recorded in that handoff. Wave 4 (the
language seam) additionally needs explicit architecture approval and is not
opened by this bundle.
