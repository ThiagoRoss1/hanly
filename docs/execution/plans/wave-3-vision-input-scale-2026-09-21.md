# Wave 3 — Vision model-input scale

**Issue-local specification.** Required by
`docs/execution/plans/text-acquisition-diagnostic-microscope-2026-09-20.md` §7,
which says the executor "writes a short issue-local specification for one
demonstrated dominant failure; it does not rewrite this master plan." This
document does not amend the master plan.

**Date:** 2026-09-21
**Bundle:** B (Wave 3 only)
**Task family selected:** *OCR detection* — "one isolated option/model-input
experiment", from the master plan's Wave 3 candidate table.

---

## The demonstrated dominant failure

Two real production hovers, captured by a human-operated `live-hover` session
and exported as
`artifacts/benchmarks/runs/ef2c1ffc-3746-4b94-a40a-680b7e9e29c3/frozen-9` and
`frozen-10`. Both were classified by Bundle A and confirmed by the Phase B
review: the gate passed, the OCR cache missed, production Vision executed, the
ROI visibly contained Korean under the recorded cursor, and Vision's normalized
output contained only the bold left-margin list numerals. Resolution reported
`no_candidate_contains_target`, morphology and dictionary were never reached,
and the popup correctly suppressed `UNUSABLE`.

The failure is silent: the user sees nothing and is told nothing.

## Why this task family and not another

Every alternative was excluded by evidence, not by preference.

| Family | Excluded because |
|---|---|
| Gate | It ran and passed. Re-measured from the exported pixels during Phase B: identical decision, 8 transitions against a target of 8. |
| Caches | Both missed. All eight exported ROIs have distinct fingerprints. |
| Resolver | Given Vision's output it behaved correctly, and given *corrected* Vision output for the same pixels it resolves the right word. |
| Morphology / dictionary | Never reached. |
| Presentation | Correctly suppressed a genuinely unusable result. |
| ROI right-edge truncation | `frozen-8` **succeeds** on Hangul running to x=198 of a 200-wide ROI. Truncation is shared by the successes. |
| Korean-specific recognition | `frozen-10` also dropped the complete, unclipped **Latin** line `do Hanly:`. |
| Clipped partial lines | Measured directly: blanking them flips `frozen-9` non-monotonically (bottom-only succeeds, both fails). Not a single clean variable. |
| ROI/grid offset | Not separable from the available evidence: the exported captures do not overlap enough to translate a full 200x100 window over real pixels. Left open, and no longer needed. |

## The single causal variable

**The size of the image handed to the recognizer**, holding the captured ROI,
its content, the provider, and every downstream stage fixed.

Measured on the real failure pixels through the real production Vision
provider. `frozen-8` is the control: it succeeded before and must keep
succeeding. The score is whether `WordResolver` resolves the word under the
recorded cursor.

Measured on the shipped mechanism (`VisionConfig(input_scale=S)`), N=15 per
cell. These are the Phase B re-measurements at equal N; the implementation run's
own table compared factors at 5, 7 and 15 repetitions and is superseded here.

| `input_scale` | frozen-8 (control) | frozen-9 | frozen-10 |
|---|---|---|---|
| 1 (production) | 15/15 | **0/15** | **0/15** |
| **2** | **15/15** | **15/15** | **15/15** |
| 3 | 15/15 | 0/15 | 15/15 |
| 4 | 15/15 | 0/15 | 15/15 |
| 5 | 15/15 | 0/15 | 15/15 |
| 6 | 15/15 | 15/15 | 15/15 |

Nothing else moved the failures at all. Every `VisionConfig` option was tested
and had **zero** effect on both: `language_correction=True`,
`languages=("ko-KR","en-US")`, and `minimum_text_height` at 0.005 / 0.02 / 0.05.
Background padding was inconsistent (2 of 3, then 0 of 3, then 3 of 3).

**Doubling is not uniquely reliable, and the earlier claim that it was is
withdrawn.** A fractional sweep at N=10–15, via manual pre-scaling with the
provider at 1x, passes at 1.1, 1.15, 1.2, 1.25, 1.3, 1.4, 1.5, 1.7, 1.8, 1.9,
1.95, 2.0, 2.05, 2.1 and 2.2, with isolated dropouts only at 1.6 and 1.75. The
behaviour is a broad passing basin with narrow notches, not a threshold, and
integer 6 passes as well.

**2 is chosen as the smallest integer inside that basin**, not as the only value
that works. `input_scale` is an integer, so 1 is the only smaller option and it
is the defect. 2 has passing neighbours at ±0.05, ±0.1 and ±0.2, and the basin's
upper edge lies between 2.2 and 3, so it is not near a measured cliff. Anyone
re-deriving a factor on another platform should re-measure the basin rather than
assume doubling is special.

## The change

`hanly.vision_provider` encodes the ROI at `VisionConfig.input_scale` (default
**2**) using nearest-neighbour replication, in `_png_bytes`. One variable, one
function.

Nearest-neighbour is deliberate: at an integer factor every output pixel is an
input pixel, so this is a presentation change and no subpixel detail is invented
for the recognizer to read. A test asserts the enlarged image introduces no
colour the original lacked.

Geometry needs no mapping. Vision reports normalized coordinates and
`_normalize` denormalizes against the **original** ROI, so results come back in
the captured coordinate space unchanged. Tests guard that.

**Not changed:** ROI size, grid, offset, clipping, capture, the gate, caches,
the resolver, morphology, dictionary policy, popup behaviour, provider
selection, EasyOCR, or any public contract.

## Cost

Measured on `frozen-8`, the only apples-to-apples comparison because it succeeds
either way (n=15): p50 46.7 → 47.5 ms, p95 53.4 → 49.4 ms.

The failing cases were *faster* before (p50 13.5 ms) precisely because they were
returning almost nothing. After the change they do real work at 56.6 and 61.4 ms
p50, which is what a succeeding lookup of that content costs.

On the unchanged 8-case synthetic corpus: every correctness metric identical,
warm p50 21.3 → 21.8 ms, warm p95 68.8 → 25.2 ms, peak RSS growth 49.6 → 45.6 MB,
zero errors.

## Regression evidence

- `tests/native/shared/test_vision_scale_regression.py` runs the two real
  failures and the control from the exported captures. They are private screen
  content under the gitignored artifact root and cannot be committed, so the
  tests skip when absent. One test asserts the failures **still reproduce** at
  `input_scale=1`: if that stops failing, the captures no longer demonstrate the
  defect and this change needs re-justifying.
- `tests/test_vision_provider.py` covers the committable mechanism: exact pixel
  replication, no new colours, validation, and geometry staying in the captured
  coordinate space.

## Open, and deliberately not addressed here

- Whether Vision omits at the region-detection or the recognition step. Vision
  exposes no detector boxes; this change does not need the answer.
- Whether a conditional retry would be better than always doubling. It would
  keep the 13.5 ms path for ROIs that genuinely hold nothing, at the cost of a
  second variable. Deferred with a trigger in the Review Handoff.
- ROI/grid offset as an independent factor.
