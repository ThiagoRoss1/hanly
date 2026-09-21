# Wave 3 (Bundle B) — Vision model-input scale Review Handoff

## Bundle

- Member issues: none. Executed from
  `docs/execution/plans/text-acquisition-diagnostic-microscope-2026-09-20.md`
  §7 (Wave 3 only), on the evidence gate opened by the Bundle A Phase B review.
  No Linear state was created or changed.
- Implementation ecosystem: Claude Opus 5, single run.
- Date: 2026-09-21.
- Issue-local specification:
  `docs/execution/plans/wave-3-vision-input-scale-2026-09-21.md`
- Live ledger:
  `docs/execution/checkpoints/wave-3-vision-input-scale-2026-09-21.md`

## Implemented

Two logically separate parts, in this order.

**Preflight evidence corrections** (diagnostic only, no product behaviour):

- Phase B finding 4 — every diagnostic run and frozen export now records the
  resolved production OCR backend directly. `_TracingOCRProvider` stamps
  `ocr_backend` on each OCR stage event; both composition roots supply it, and
  it reaches `FrozenLookup.backend`, `describe_frozen`, the export metadata and
  diagnostic, the inspector heading, and the run summary.
- Phase B finding 5 — `SessionEvidenceCounts` separates freezes, export
  attempts, successes, failures, refusals, re-exports, and distinct exported
  directories.
- Phase B findings 6 and 7 — the Bundle A checkpoint and baseline report no
  longer lead with right-edge truncation or Korean-specific recognition; both
  are recorded as eliminated, with the evidence.

**The product causal change** (one variable):

- `VisionConfig.input_scale`, default 2, applied in
  `hanly.vision_provider._png_bytes` by nearest-neighbour replication.

## Main expected behavior

Hovering Korean that Vision previously dropped now produces the correct popup.
The two preserved real failures resolve the right word; the preserved control is
unchanged; the unchanged synthetic corpus scores identically.

## Architecture / seams touched

- `OCRProvider` seam, ROI contract, and `OCRResult` geometry are unchanged. Only
  the bytes handed to Vision inside the adapter differ.
- No coordinate mapping was added: Vision reports normalized coordinates and
  `_normalize` denormalizes against the **original** ROI, so results return in
  the captured coordinate space. Two tests guard this.
- `CA-INV-09` holds — no library object crosses the seam.
- `LookupSettings` already carried `ocr_backend`; the child now passes its value
  to the worker for attribution. No new message kind, no public `hanly` contract
  change.
- Provider selection, capture geometry, gate, caches, resolver, morphology,
  dictionary policy and popup behaviour are untouched.

## Relevant files / diff areas

Engine: `packages/hanly/src/hanly/vision_provider.py`.
App: `packages/hanly-app/src/hanly_app/{composition,lookup_process,runtime}.py`.
Benchmarks: `benchmarks/dev/{frozen_lookup,microscope,live_runner}.py`.
Tests: `tests/{test_vision_provider,test_lookup_evidence}.py`,
`tests/native/shared/test_vision_scale_regression.py` (new),
`benchmarks/dev/tests/{test_microscope,test_live_runner}.py`.

The worktree holds several bundles; scope attribution should use this list.
Nothing was committed.

## Implementation-side validation already run

| Check | Result |
|---|---|
| `.venv/bin/python -m pytest` | **1928 passed, 2 skipped** (entry: 1907 passed, 2 skipped) |
| `.venv/bin/python -m ruff check packages packaging tests tools benchmarks` | All checks passed |
| `.venv/bin/python -m mypy packages packaging tests tools benchmarks` | Success, 268 source files |
| Real failures, shipped provider | frozen-9 `None` → `초대받았어요`; frozen-10 `None` → `떨어뜨렸어요` |
| Real control, shipped provider | frozen-8 `깨뜨렸습니다` → `깨뜨렸습니다`, unchanged |
| Unchanged synthetic corpus, before/after | every correctness metric identical; 0 errors both |
| Backend attribution, real composition | runtime → worker → frozen record → export metadata, all `vision` |

### The causal variable, and how the alternatives were excluded

The source page was gone, so live re-capture was impossible — and unnecessary:
all three captures replay **byte-identically** to their session records through
the real production provider, so the experiment ran on the real failure pixels
with no synthetic proxy and no human interaction.

| Variable | Outcome |
|---|---|
| `language_correction`, `languages=(ko-KR,en-US)`, `minimum_text_height` ×3 | **zero effect** on either failure |
| Clipped partial lines | flips frozen-9 **non-monotonically** — not a clean variable |
| Background padding | inconsistent: 2/3, 0/3, 3/3 |
| **Input scale** | 1.0 → control 7/7, failures **0/7**. 2.0 → all three **15/15**, one distinct output each |
| 1.75 / 2.5 / 3.0 | unstable; the numeral merges into the line |

ROI/grid offset could not be varied over real pixels — frozen-8 and frozen-9
overlap pixel-identically (0 of 6 048 differing) but their union leaves corners
uncovered, so no full 200×100 window translates between them. Recorded as
untested, not excluded.

### Cost

Control only, the one apples-to-apples comparison, n=15: p50 46.7 → 47.5 ms,
p95 53.4 → 49.4 ms. The failures were *faster* before (p50 13.5 ms) because they
were returning almost nothing; they now cost 56.6 and 61.4 ms, which is what
reading that content costs. Corpus warm p50 21.3 → 21.8 ms, warm p95 68.8 →
25.2 ms, peak RSS growth 49.6 → 45.6 MB.

## Known limitations / intentionally unvalidated areas

- **The mechanism is not explained, only measured.** Vision exposes no detector
  boxes, so whether it omits at region detection or at recognition is unknown.
  The change does not depend on the answer, but it means the scale factor is an
  empirical floor rather than a derived one.
- **Always-on, not a retry.** Doubling applies to every Vision lookup. A
  conditional retry would keep the fast path for ROIs that genuinely hold
  nothing, at the cost of a second variable — out of scope for a one-variable
  Wave 3. See the deferred item.
- **One machine, one display.** macOS 26.6.2 arm64, one internal display at
  1408×881, no external display, no Windows. Whether the same floor applies at
  other display scales is untested.
- **Two real failures.** Both from one session, one application, one font, one
  dark theme. The corpus that scores unchanged is eight synthetic samples.
- **`input_scale` is not exposed in runtime configuration.** It is a
  `VisionConfig` field with a measured default; no JSON key reads it.
- **The regression suite depends on private captures.** It skips when
  `artifacts/benchmarks/runs/ef2c1ffc-…` is absent, so CI on another machine
  proves only the committable mechanism.
- Odd and large factors were measured unstable but not diagnosed; only that they
  are unsuitable is established.

## Suggested review targets

- `_png_bytes` and `_normalize` together: the claim that geometry needs no
  mapping rests on `_normalize` using the original ROI dimensions. If either
  changes, the resolver silently starts pointing at the wrong place.
- `VisionConfig.__post_init__` validation against the frozen-dataclass contract.
- Whether nearest-neighbour is the right resampler. It was chosen so no
  subpixel detail is invented; LANCZOS and BILINEAR measured equally correct
  here, so this is a judgement about what the recognizer should be allowed to
  see, not about these three cases.
- The PNG payload is now 4× the pixels. Encode cost is inside the measured
  latency, but memory churn per lookup was not separately profiled.
- `SessionEvidenceCounts` — that the seven counters cannot disagree with each
  other, and that `frozen_lookups_exported` really is distinct directories.
- Backend attribution on the in-process path (`runtime.create_worker_factory`)
  versus the spawned child, which resolve it by different routes.

## Review assignment

Human-selected after implementation. Not started.

## Deferred considerations carried into this bundle

- **Conditional retry instead of always doubling.** Revisit when hover latency
  is next measured against a budget, or if a session shows Vision cost
  dominating the dwell-to-popup path. The data needed is the distribution of
  ROIs that genuinely hold no text in a real session.
- **ROI/grid offset as an independent factor.** Revisit if a failure appears
  that doubling does not fix. Capturing two overlapping full ROIs in one session
  would make the translation experiment possible.
- **Whether `input_scale` should be runtime-configurable.** Revisit if a second
  platform or display scale needs a different floor.

---

## Post-Bundle Review Outcome

- Reviewer: Claude Opus 5
- Review ecosystem: Phase B deep review, single run, `.venv` on macOS 26.6.2 arm64
- Date: 2026-09-21
- Status: **Approved with deferred findings** for Wave 4 architecture authorization.

**Scope.** The worktree holds several bundles. Attribution used this handoff's
file list. `vision_provider.py`, `frozen_lookup.py`, `microscope.py` and most of
the test files are untracked — Vision and the microscope both predate `HEAD` as
uncommitted Bundle A work — so Wave 3's changes inside them were reviewed by
reading rather than by diff. `contracts.py`, `lookup_pipeline.py`, `popup.py`,
`qt_popup.py`, `control_center*` and the other dirty paths were treated as out
of scope.

### Preflight corrections: verified

**Backend attribution reaches all eight surfaces**, each checked directly:

| Surface | Result |
|---|---|
| In-process composition | `ocr_backend="vision"` on the OCR stage event |
| In-process wiring | `runtime.py` passes `resolved_ocr_backend().value` |
| Spawned lookup worker | `lookup_process.py` passes `settings.ocr_backend.value`; the child-settings tests pass |
| Runtime events | present on `lookup_stage_completed(stage="ocr")` |
| `FrozenLookup.backend` | `"vision"` |
| `diagnostic.json` | `live_ocr_backend: "vision"` |
| `metadata.json` | `live_ocr_backend: "vision"` |
| Inspector HTML | renders the backend; `"unrecorded"` when absent |
| Live-run summary | `resolved_ocr_backend` recorded where it is resolved |

It cannot be confused with staged replay: the live backend is a separate field
from `staged_ocr.evidence_class`, which is `comparison_replay`, and a test
asserts the two never collapse. Attribution adds no screen content, no
identifiers, and no public `hanly` contract — `hanly.__all__` gains nothing.

**All seven counters verified against all seven scenarios** in one sequence
(export-before-freeze, freeze, export, re-export, repeated freeze, second
lookup, failed export outside the root):

```
frozen_lookups_pinned 3 · export_attempts 5 · succeeded 3 · failed 1
refused_nothing_frozen 1 · reexports 1 · frozen_lookups_exported 2
```

Three internal invariants hold: attempts == succeeded + failed + refused;
exported directories <= succeeded; succeeded - reexports == exported. Values are
integers only.

**The privacy boundary is still structural.** Freeze writes nothing; export is
the only path that persists, and only under the gitignored root. `git
check-ignore` confirms the private captures are ignored and `git status` sees
nothing under `artifacts/`. No Wave 3 file contains a home path, a username, or
a temp machine path, and no committed fixture holds screen pixels.

### Product change: verified

- **Validation** rejects `0`, negatives, `1.5`, `2.0`, `True`, `False`, `"2"`,
  and `None`. It did **not** reject absurd magnitudes — see Fixed now 1.
- **`_png_bytes` / `_normalize` read correctly together.** `_normalize`
  denormalizes against the *original* ROI, and Vision reports normalized
  coordinates, so no mapping is needed. Verified independently, not just read:
  at `input_scale=2` every returned quad lies inside the original 200x100 ROI,
  and regions matched by text between the 1x and 2x runs agree within 0-7 px
  with comparable widths (16-26 vs 17-19). A doubling bug would show ~100 px
  offsets and 2x widths.
- **Nothing else is doubled or shifted.** `word_resolver.py`,
  `lookup_pipeline.py`, `kiwi_provider.py`, `krdict_provider.py`, `popup.py`,
  `hover_lookup.py`, `capture.py` and `composition.py` contain no reference to
  input scaling; gate thresholds are untouched; `capture.py` has no scale in its
  diff.
- **The OCR cache stays correct.** It keys on ROI bytes, dimensions and pixel
  format, upstream of the adapter, so the encoding change is invisible to it. An
  identical ROI hits (1 provider call for 2 lookups); a different ROI misses.
- **Payload and transient memory.** The encoded PNG grows only 9.5 -> 10.3 KiB
  (+11%) because nearest-neighbour produces highly compressible 2x2 blocks; the
  decoded buffer is the real cost, 60 -> 240 KB, and is transient. Python-side
  transient peak is flat at ~67 KiB across scales 1-4.
- **Repeated calls.** ~1.8 KiB retained per call — **identical at
  `input_scale=1` and `2`** (measured at 30/60/120 calls). Pre-existing, not
  introduced here. See Deferred 4.

### Evidence: independently reproduced

Every claim reproduced from the private captures:

| Claim | Result |
|---|---|
| `input_scale=1` preserves the failures | frozen-9 **0/15**, frozen-10 **0/15** |
| `input_scale=2` corrects them | frozen-9 **15/15**, frozen-10 **15/15** |
| frozen-8 remains correct | **15/15** at every scale tested |
| Outputs are stable | one distinct output per case |
| Resolver selection under the recorded cursor | correct word in every passing trial |
| Unchanged corpus retains correctness | per-case `exact_match` and `target_surface_correct` identical before/after, all 8 cases |

### Statistical and performance claims: verified, with one correction

- **p50/p95 recomputed from `samples.jsonl`** for both corpus runs: every
  reported cold/warm p50, p95 and count matches exactly.
- **The before/after corpus runs are comparable**: identical case set, identical
  sample counts (40 each), identical mode, backend, manifest, warmup, samples,
  IoU, machine, Python, and corpus inventory.
- **Equal-success latency**, frozen-8 only, N=25: `input_scale=1` p50 46.62 ms /
  p95 53.62 ms; `input_scale=2` p50 47.56 ms / p95 51.66 ms. The handoff was
  right not to use the failing path as a baseline — its 13.5 ms was the cost of
  returning almost nothing.
- **Correction:** the handoff's uniqueness claim is overstated. See Deferred 5.

### Fixed now

1. **`input_scale` had no upper bound.** `VisionConfig(input_scale=10**9)` was
   accepted, and scale grows the decoded image quadratically, so a configuration
   slip became an allocation the machine cannot satisfy. Added
   `MAX_INPUT_SCALE = 8` with a range check, plus tests for the rejected
   magnitudes and for the whole permitted range being constructible. Cheap
   defensive hardening at a public engine contract; nothing else changed.

### Deferred considerations

2. **The scale-factor conclusion is overstated in the spec and this handoff.**
   Both say exact doubling "is the only factor that is both reliable and stable"
   and that "non-integer and larger factors are measurably unstable". At equal N
   that is not what the data shows. Re-run at N=15 per cell on the shipped
   mechanism, integers only: 1 fails both, **2 passes all three**, 3/4/5 fail
   frozen-9, **6 passes all three**. Fractionally, via manual pre-scale at
   N=10-15: 1.1, 1.15, 1.2, 1.25, 1.3, 1.4, 1.5, 1.7, 1.8, 1.9, 1.95, 2.0, 2.05,
   2.1 and 2.2 all pass; only 1.6 and 1.75 are isolated notches. The behaviour is
   a broad passing basin with narrow dropouts, not a threshold. **Revisit when
   the spec is next edited, or before any second platform re-derives a factor** —
   the wording should say 2 is the smallest integer in a wide verified basin,
   not that it is unique.

3. **The chosen default is nonetheless adequately supported, and I did not
   change it.** 2 is the smallest permitted integer above 1 that passes, it sits
   with passing neighbours at +/-0.05, +/-0.1 and +/-0.2, and the next integers
   (3, 4, 5) fail. The upper edge of the basin lies between 2.2 and 3, so 2 is
   not near a measured cliff. **Revisit if a third real failure appears that 2
   does not fix**, which would mean the basin is content-dependent.

4. **~1.8 KiB retained per `recognize()` call.** Measured identical at
   `input_scale=1` and `2`, so Wave 3 neither caused nor worsened it; it is most
   likely pyobjc autorelease behaviour. It matters because hover calls this
   continuously. **Revisit when idle or long-session resident memory is next
   measured**, or if a multi-hour session shows growth.

5. **`input_scale` is not runtime-configurable and the basin is characterised
   from three captures in one session, one application, one font, one dark
   theme, one display scale.** **Revisit when a second display scale or platform
   is exercised.**

6. **Vision's omission mechanism is still unexplained** — region detection
   versus recognition remains unseparable because Vision exposes no detector
   boxes. The fix does not depend on it. **Revisit only if a failure appears that
   scaling does not correct.**

### Dismissed

7. **"Geometry may be silently doubled or shifted."** Dismissed on evidence:
   every 2x quad lies inside the original 200x100 ROI, and text-matched regions
   agree within 0-7 px. Additionally, a deliberate mutation that maps geometry
   against the enlarged image is caught by the committed
   `test_recognized_regions_carry_top_left_pixel_geometry` and by all three
   private-capture regression tests.

8. **"CI may be inadequate without the private captures."** Dismissed by
   mutation testing. Removing the scaling: the committed
   `test_scaling_replicates_pixels_exactly_and_invents_no_detail` fails.
   Mis-mapping geometry against the enlarged image: the committed
   `test_recognized_regions_carry_top_left_pixel_geometry` fails. Both mutations
   are caught with the private run absent.

9. **"The private-capture regression test may fail or mislead when the captures
   are absent."** Dismissed: with the run directory renamed away the suite
   reports `5 skipped`, exit code 0. It also asserts the failures *still*
   reproduce at `input_scale=1`, so the evidence itself is guarded.

10. **"The OCR cache may be wrong now that the adapter's encoding changed."**
    Dismissed: the cache is upstream of the adapter and keys on ROI bytes,
    dimensions and format. Hit and miss both verified.

### Checks run during this review

| Check | Result |
|---|---|
| Equal-N shipped-mechanism trials, integers 1-6, N=15 x 3 cases | 2 and 6 pass; 1, 3, 4, 5 fail |
| Fractional basin sweep, 16 factors, N=10-15 | basin 1.1-2.2 with notches at 1.6 and 1.75 |
| Geometry containment and 1x/2x agreement | all quads inside the ROI; 0-7 px agreement |
| Mutation: scaling removed | caught by committed and private tests |
| Mutation: geometry mapped against enlarged image | caught by committed and private tests |
| Seven counters x seven scenarios | all correct; three invariants hold |
| Backend attribution x eight surfaces | all present |
| Validation probes (10 values) | 9 refused, 1 accepted -> Fixed now 1 |
| Percentiles recomputed from raw samples | exact match, both runs |
| Corpus comparability | identical inputs and conditions |
| Equal-success latency, N=25 | p50 46.62 -> 47.56 ms; p95 53.62 -> 51.66 ms |
| Memory: transient and retained | flat transient; retention identical at 1x and 2x |
| Privacy scan of Wave 3 files | no paths, usernames, or pixels |
| `.venv/bin/python -m pytest` | **1936 passed, 2 skipped** |
| `.venv/bin/python -m ruff check packages packaging tests tools benchmarks` | All checks passed |
| `.venv/bin/python -m mypy packages packaging tests tools benchmarks` | Success, 268 source files |

### Verdict

**Approved with deferred findings for Wave 4 architecture authorization.**

The preflight corrections do what the Bundle A review asked: backend attribution
is present on every surface and can no longer be confused with staged replay,
the freeze/export counters are separated and self-consistent, and the privacy
boundary remains structural. The product change is correctly scoped to the model
input, its geometry claim holds under independent measurement and mutation
testing, and it corrects both real failures deterministically while leaving the
control and the whole synthetic corpus unchanged at a measured cost of about
1 ms on the only honest comparison.

One defect was found and fixed: an unbounded `input_scale`.

The one substantive criticism is documentary, not behavioural. The claim that
exact doubling is uniquely reliable does not survive equal-N testing — a wide
band of factors works, and 2 is the smallest integer inside it rather than the
only option. The chosen default remains adequately supported and I did not
change it, but the reasoning recorded in the spec should be corrected before it
is relied on to re-derive a factor on another platform.

Nothing here blocks Wave 4. Wave 4 is a separate bundle that additionally
requires explicit human approval of the engine seam it changes, and this review
does not grant that approval.
