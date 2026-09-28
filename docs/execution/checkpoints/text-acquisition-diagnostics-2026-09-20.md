# Checkpoint — Text acquisition diagnostics (Bundle A)

**Plan:** `docs/execution/plans/text-acquisition-diagnostic-microscope-2026-09-20.md`
**Authorized scope:** Part 1 — Bundle A (Waves 1–2), ending at one Review Handoff.
Wave 3 is a separate, evidence-gated, resumed run. Waves 4–7 are out of scope.
**Branch/worktree:** `visual/interface-update`, pre-existing worktree reused. No
branch was created.
**Interpreter:** `.venv/bin/python` (CPython 3.13.11). ruff 0.16.5, mypy 2.3.1,
pytest 9.1.1 all present.

This is a live ledger, not a second plan. It records completed task IDs,
material decisions, touched files, checks and their exact results, evidence run
IDs, privacy state, remaining native validation, blockers, and the exact next
action.

---

## Entry-state evidence (recorded before any change)

Full repository gates, run on the authoritative interpreter at the start of the
run:

```
.venv/bin/python -m pytest                    -> 1701 passed, 2 skipped, 5 warnings in 175.39s
.venv/bin/python -m ruff check packages packaging tests tools benchmarks -> All checks passed!
.venv/bin/python -m mypy  packages packaging tests tools benchmarks      -> Success: no issues found in 250 source files
```

## Environment limitations

- **Git blocker cleared after the implementation run.** The original executor
  could not invoke Git because the Xcode licence was unaccepted. On 2026-09-21,
  `git status --short --branch` succeeded on `visual/interface-update`, so a
  diff-based Phase B review is now possible. The worktree also contains changes
  from other Hanly bundles; reviewers must use this handoff's file list and
  acceptance boundary rather than treating every dirty path as Bundle A work.
  No commits were attempted (none are authorized).
- Platform is macOS (darwin 25.6.0). `auto -> Vision` is the resolved product
  backend here, so EasyOCR staged evidence must be produced by an explicitly
  pinned EasyOCR diagnostic run, never inferred from a product hover.
- Windows DPI matrix rows (100/125/150/mixed) are unavailable from this machine
  and must be declared `not available`, never simulated.

## Material decisions

| # | Decision | Reason |
|---|---|---|
| D11 | The interactive real failures are classified at the production OCR-output boundary, but no Wave 3 correction is selected yet. | In `frozen-9` and `frozen-10`, the gate passed and Vision executed uncached, yet normalized output contained only nearby list numbers and zero Hangul despite Korean pixels under the cursor. Vision exposes no raw detector boxes, so region and recognition omission are not separable. Phase B eliminated the two hypotheses this entry originally led with: the omission is not Korean-specific (a complete Latin line was dropped too) and right-edge truncation is shared with the `frozen-8` success. One controlled same-case input experiment must decide the causal task family before product code changes. |
| D9 | The committed corpus is committed **empty**, and the existing Korean fixture is not in it. | `tests/hanly_fixtures/assets/korean_reading_roi.json` marks itself `"benchmark": false`, DAG-INV-16 separates Korean fixtures from benchmark corpora, and the plan says a committed Korean fixture is correctness-regression evidence rather than accuracy evidence. No redistributable Korean face is installed either, so the generator refuses. Committing the empty manifest keeps the contract and the reason visible; the alternative was an undiscoverable absence. |
| D10 | Measurements were taken from a `local_synthetic` corpus rendered with Apple SD Gothic Neo. | It was that or no measurement at all. The tooling marks such samples local-only and a committed manifest refuses them, so the limitation is enforced rather than merely noted. The baseline report states it as the first limitation. |
| D7 | `LookupSettings` gained `trace_evidence`, carried across the spawn to the lookup child. | Found by the first real run, not by a test: the child builds its own tracing wrappers and cannot see what sink the parent attached, so `_ChildTraceSink` had no `retain_evidence` and a real desktop launch would have emitted **no** private evidence at all. It travels for the same reason `ocr_backend` does. |
| D8 | A frozen record distinguishes *not reached*, *skipped*, and *no evidence emitted*. | Also found by a real run. Reporting "no evidence" for morphology after an empty OCR pass reads as a broken microscope when it is in fact the answer. |
| D5 | The morphology evidence records the provider's own tokens and candidates and **does not** name a selected lexical unit. | Selection happens later, in `LookupPipeline._select_candidate`, using the cursor index. Naming one at the morphology stage would be a second guess at a decision that stage does not make. The unit actually chosen is already on `LookupResult.context.candidate`, which is the authoritative record from the computation that made it. |
| D6 | Two small helpers were made public on `hanly.easyocr_provider` (`easyocr_image_from_roi`, `normalize_easyocr_results`). | W1.3 explicitly allows touching the adapter "only if a minimal observation seam is required to avoid duplicating normalization". Both are pure and were already the adapter's own code paths; the alternative was copying the BGR channel swap and the reading-order/clamping rules into the benchmark, where they would silently drift. Neither is added to the `hanly` package's top-level exports. |
| D1 | The ROI byte digest stays **out** of the app-owned capture-observation value and is produced off the capture path by the benchmark's keyed `SessionPrivacy.roi_digest`. | The plan (W1.1) lists a "privacy-safe digest" in the value, but hashing 60 KB on every hover capture changes capture cost, and W1.1 explicitly forbids changing capture behavior and asks for "the smaller shape that preserves ID-based correlation". A keyed digest computed on the benchmark thread is both cheaper on the hover path and strictly more private than an unkeyed product-side hash. The value still carries image dimensions, pixel format, and byte length. |
| D2 | Rich diagnostic evidence crosses the lookup-child process boundary as a JSON-encoded string field on an ordinary trace event, not as a new transport message kind. | The lookup worker runs in a spawned child (`lookup_process.py`); only JSON-safe primitives cross `emit_trace`. Encoding keeps the production seam unchanged, adds no message kind, and lets the benchmark's privacy layer strip it from persisted traces while the in-memory freeze ring keeps it. |
| D3 | Staged EasyOCR (W1.3) runs in the **benchmark** process against frozen ROI bytes, never inside the lookup child. | Detector crops and recognizer inputs are images; sending them through the pipe would change child behavior and cost. This is also what makes the plan's live-vs-`comparison_replay` distinction structurally true rather than a label. |
| D4 | `_TracingResolver` exposes `resolve_target_detail` only when the wrapped resolver does, via a subclass selected at construction. | `LookupPipeline._resolve_target` probes with `getattr`. Unconditionally defining the method on the wrapper would silently upgrade a pair-only substituted resolver, which is a behavior change in the opposite direction from the defect being fixed. |

No public `hanly` contract has been extended for diagnostics so far. If that
becomes necessary, the technical reason and rejected private alternatives are
recorded here **before** the change.

## Privacy / export state

- Freeze pins one completed lookup in a bounded in-memory ring. No disk write.
- Export is a separate explicit developer action writing under the gitignored
  `artifacts/benchmarks/runs/` root only.
- Raw screen pixels, recognized text, and provider crops are absent from normal
  tracing and from every non-exported session, including one holding a frozen
  lookup.

---

## Progress

### Wave 1 — observability integrity and benchmark microscope

| Task | State | Notes |
|---|---|---|
| W1.0 trace parity / production capture config / derived backend label | **done** | `_TracingResolver` now forwards `resolve_target_detail` through a subclass chosen at construction (`_traced_resolver`); `live-hover` builds capture through `production_capture_service()` with `DEFAULT_ROI_GRID`; the HUD label comes from `HanlyRuntime.resolved_ocr_backend()`. |
| W1.1 capture-plan and coordinate evidence | **done** | `CapturePlan` on `CaptureResult` (optional, default `None`); `CaptureObserver` protocol on the hover and manual seams; a plan summary added to `hover_capture_completed`. |
| W1.2 gate and cache decision evidence | **done** | `_GateMeasurement` replaces the boolean gate calculation; `_OCRPathObserver` joins gate, OCR cache, and provider execution into one decision chain on the OCR stage event; both full-result cache events carry a key fingerprint. |
| W1.3 staged EasyOCR evidence | **done** | `benchmarks/dev/easyocr_stages.py` reproduces `Reader.readtext` stage by stage against a pinned EasyOCR 1.7.2, retaining detector boxes, crops and recognizer inputs in memory. Normalization is the adapter's own (`normalize_easyocr_results`), not a copy. `compare_to_live` surfaces divergence without replacing the live result. |
| W1.4 resolver / morphology / dictionary evidence | **done** | `ResolutionEvidence` in `word_resolver.py`, produced by the one `_resolve` computation that all three resolver methods now share. Encoded by `hanly_app/lookup_evidence.py` onto trace events only for a sink that sets `retain_evidence`. |
| W1.5 retained-hover and presentation evidence | **done** | `retained_target` / `retained_target_cleared` record both coordinate spaces, the named `SCREEN_SCALE` transform, the padded rectangle, the popup and the corridor. `popup_suppressed` now actually exists, so a silent outcome is distinguishable from a stale one. |
| W1.6 in-memory freeze, explicit export, inspector | **done** | `frozen_lookup.py` (bounded ring, ID correlation, atomic freeze) and `microscope.py` (tee sink, off-path capture observer, export, layered inspector). `live-hover` gained `--freeze-hotkey` and `--export-hotkey`; `--retain-text` is gone. |
| W1.7 convergence and checkpoint | **done** | Focused suite, full suite, ruff and mypy all green. One complete real frozen hover and staged EasyOCR replay were followed by a human-operated `live-hover` session with real hotkey freezes/exports and two production failures. |

### Wave 2 — corpus and repeatable evaluation

| Task | State | Notes |
|---|---|---|
| W2.0 corpus manifest and provenance | **done** | `benchmarks/dev/corpus.py` plus `benchmarks/fixtures/ocr/{manifest,generator}.json` and a README. A manifest declares `committed` or `local`; validation refuses absolute paths and local/private cases in a committed one. |
| W2.1 synthetic Korean fixture generator | **done** | `benchmarks/dev/synthetic_ocr.py`. Refuses a missing face rather than substituting one, refuses text a face has no glyphs for, and marks non-redistributable output `local_synthetic`. |
| W2.2 OCR-only / detection-only / recognition-only / frozen-replay | **done** | `benchmarks/dev/ocr_benchmark.py` and the `ocr-campaign` / `ocr-corpus` / `ocr-corpus-generate` commands. A test asserts no mode constructs Kiwi or KRDICT. |
| W2.3 correctness metrics | **done** | `benchmarks/dev/ocr_metrics.py`. Missing ground truth is `not_applicable`, never zero. |
| W2.4 cold/warm latency and RSS | **done** | Cold/warm-up/warm conditions, nearest-rank percentiles over retained raw samples, peak RSS from the standard library and current RSS reported unavailable without `psutil`. |
| W2.5 repeatable baseline report | **done** | `docs/execution/reports/text-acquisition-diagnostic-baseline.md`. |
| W2.6 Bundle A convergence and Review Handoff | **done** | Full gates green; handoff written; **stop**. |

## Checks run so far

| Scope | Command | Result |
|---|---|---|
| Bundle A convergence | `.venv/bin/python -m pytest` | **1895 passed, 2 skipped** (entry state: 1701 passed, 2 skipped) |
| Bundle A convergence | `.venv/bin/python -m pytest --suite portable` | 1825 passed, 2 skipped |
| Bundle A convergence | `.venv/bin/python -m ruff check packages packaging tests tools benchmarks` | All checks passed |
| Bundle A convergence | `.venv/bin/python -m mypy packages packaging tests tools benchmarks` | Success, 267 source files |
| W1.7 focused | `.venv/bin/python -m pytest benchmarks/dev/tests tests/test_capture.py tests/test_app_composition.py tests/test_runtime_trace.py tests/test_word_resolver.py tests/test_lookup_pipeline.py tests/test_hover_target.py tests/test_hover_lookup_e2e.py tests/test_lookup_evidence.py tests/test_retained_target_evidence.py` | 268 passed |

The W1.0 parity fixtures were confirmed to fail against the pre-fix wrapper
(3 failures) and pass after it, so they guard the defect rather than describing
the new code.

## Evidence runs

**Staged EasyOCR smoke run against the real reader** (macOS, EasyOCR 1.7.2,
`tests/hanly_fixtures/assets/korean_reading_roi.png`, 192x48 RGB):

| Evidence | Value |
|---|---|
| Live `EasyOCRProvider.recognize` | `[('책울 읽습니다.', 0.497)]` |
| Staged, `staged_diagnostic` | one horizontal region, same text and confidence, crop 285x64 grayscale (18 240 bytes) |
| Staged, `comparison_replay` vs live | `matches=True`, no differences |
| Stage timings | detect 21.4 ms, recognize 9.2 ms, normalize 0.02 ms, total 30.8 ms |

Two things this already shows. The staged runner reproduces `readtext`
faithfully (identical text and confidence), so its crops are usable evidence.
And it reproduces the known EasyOCR defect in the open: `책을` read as `책울` at
0.497 confidence. That is a recorded observation on a committed fixture, not a
real failing hover, and it does not satisfy the W1.7 exit criterion.

This run was a throwaway script in the session scratchpad, not a committed
command. The equivalent committed path arrives with W2.2's `ocr-only` mode.

### W1.7 — one real frozen lookup (macOS, 2026-09-21)

The human authorized displaying the committed Korean fixture
(`tests/hanly_fixtures/assets/korean_reading_roi.png`) in Preview so a real
hover had Korean text to land on; Preview was closed afterwards. The pointer was
never moved — `capture_at_cursor` takes the point it is given.

Composition: real `resources/dev/runtime-local.json`, real `CaptureService` with
`DEFAULT_ROI_GRID`, real Apple Vision (`auto -> vision`), real Kiwi, real
KRDICT, `skip_flat_rois=true`, real hover runtime, real microscope. Driven from
a scratchpad script because a `live-hover` session needs a human at the machine
for several minutes.

Exported evidence: `artifacts/benchmarks/runs/w17-frozen-1/` (gitignored) —
`metadata.json`, `input.png` (200x100 RGB), `diagnostic.json`, `diagnostic.html`,
`events.jsonl` (19 events), `ocr/staged-run.json`, `ocr/crops/region-00.png`
(296x64 grayscale).

The frozen lookup answers every question in the W1.7 exit criterion without
inference:

| Exit-criterion question | Answer from the frozen record |
|---|---|
| These were the pixels | 200x100 RGB_888, 60 000 bytes, keyed digest `da77b774199acee6` |
| Production-equivalent ROI/grid and coordinates | ideal `(269,175,200,100)` -> snapped on grid **32** -> desired `(256,160,200,100)`; actual == desired; not clipped |
| This was the cursor | requested `(369,225)` == effective, not clamped; ROI-local `(113,65)`; edge distances L/T/R/B `113/65/86/34` |
| The gate did this | enabled, ran, RGB_888, first-channel row delta, row step 3, column step 3, threshold 32, target 8, observed 8, **passed**, early exit |
| The caches did this | full-result miss; OCR cache consulted, miss, fingerprint recorded |
| This provider executed | Vision executed; `provider_skipped_reason` null |
| Hanly normalized the provider output this way | one region `책을 읽습니다.` at confidence 0.5 |
| This OCR region was selected | index 0, `contains_target` true, single hit so no tie-break recorded |
| The resolver mapped the target to this fraction, character, and surface | fraction `0.6688` -> character index 5 -> word span `[3,8]` -> surface `읽습니다.`, `region_start` 3, `cursor_index` 2. Advance weights exact: `[1.0, 1.0, 0.35, 1.0, 1.0, 1.0, 1.0, 0.35]` |
| Kiwi produced these analyses and selected this candidate | `읽`/VV -> `읽다`, `습니다`/EF, `.`/SF; one candidate `읽다` spanning `[0,4)` |
| KRDICT queried this lemma and returned this status | query `읽다`, 1 entry, found |
| These were the retained bounds and presentation decision | screen rect `(321,209,98,30)`, protected `(317,205,106,38)`, scale 1.0; terminal `lookup_current_delivered` |
| The observed failure entered at this named stage | no failure: `SUCCESS`, `missing=[]` |

**Independent cross-check of the ROI -> screen transform.** A separate
full-screen Vision pass located `읽습니다.` at `(321,210)-(418,240)`. The frozen
retained rectangle, derived through the entirely different
`capture origin + word_region` path, is `(321,209)-(419,239)`. They agree to
one pixel, which is the resolution of the axis-aligned advance-weight estimate.

### W1.7 — explicit staged EasyOCR replay on the same frozen ROI

The same frozen ROI bytes were replayed through the staged EasyOCR runner and
labelled `comparison_replay`:

| | |
|---|---|
| Live (Vision, the production backend) | `책을 읽습니다.` @ 0.500 |
| Staged EasyOCR replay, EasyOCR 1.7.2 | `책올 읽습니다.` @ 0.562 |
| `compare_to_live` | `matches=False`, `region 0 text: '책을 읽습니다.' vs '책올 읽습니다.'` |
| Staged crop retained | 296x64 grayscale, the exact recognizer input |
| Staged timings | detect 74.7 ms, recognize 43.5 ms, total 121.7 ms |

The divergence is surfaced as a finding and the live Vision result stays
authoritative, which is exactly the rule the plan sets. It is also an
independent real-pixel reproduction of the EasyOCR defect class already recorded
in `docs/execution/reports/ocr-latency-and-roadmap.md` (a lost/retargeted
batchim: `을` read as `올`). This is one sample on one committed fixture, not a
corpus measurement, and no backend decision follows from it.

### Human-operated live hover and real failures (macOS, 2026-09-21)

Run `ef2c1ffc-3746-4b94-a40a-680b7e9e29c3` exercised the real global activation,
freeze, and export hotkeys for five minutes. It completed 10 lookups: eight
visible `SUCCESS` results and two suppressed `UNUSABLE` results. Eight distinct
frozen directories were exported (`frozen-2`, `-4`, `-5`, `-6`, `-7`, `-8`,
`-9`, `-10`); repeated freeze/export actions against the same lookup harmlessly
reused its directory.

`frozen-9` and `frozen-10` are the first real failures of the shipped macOS
configuration:

| Evidence | `frozen-9` | `frozen-10` |
|---|---:|---:|
| ROI / cursor | 200x100, target `(89,47)` | 200x100, target `(85,49)` |
| Gate | ran and passed | ran and passed |
| Cache / provider | miss; Vision executed | miss; Vision executed |
| OCR latency | 162.6 ms | 154.3 ms |
| Live normalized OCR | `6.`, `7.`, `8.` | `1.`, `2.` |
| Hangul regions | 0 | 0 |
| Resolution | `no_candidate_contains_target` | `no_candidate_contains_target` |
| Downstream | morphology/dictionary not reached | morphology/dictionary not reached |
| Outcome | `UNUSABLE`, popup suppressed | `UNUSABLE`, popup suppressed |

The exported pixels visibly contain Korean under each cursor. This rules out the
gate and every later stage: the failure first appears in live production OCR
output.

Two hypotheses were **eliminated** by the Phase B review and must not be
reintroduced. The omission is not Korean-specific: `frozen-10` also dropped the
complete, unclipped Latin line `do Hanly:`, and everything Vision returned in
either failure is a short bold left-margin numeral. Right-edge truncation is not
the discriminator either: `frozen-8` succeeded on Hangul running to x=198 of a
200-wide ROI. Because Vision exposes no raw detector boxes, region omission and
recognition omission remain inseparable; the nearer open variables are ROI/grid
offset and the clipped partial line at `frozen-9`'s top.

The successful glued-text cases are separate. Vision read the strings correctly,
the resolver produced a cursor index, and Kiwi selected `초대`, `받다`, or
`깨뜨리다` according to that index. The production KRDICT contains `초대` and
`받다`, but no `초대받다` lemma. Treating the entire surface as one dictionary
word is therefore a morphology/dictionary product-policy question, not evidence
for the same pixel-path correction.

## Remaining native / manual validation

- **Done:** one complete real frozen hover, an explicit EasyOCR staged replay,
  and a genuine human-operated `live-hover` session using the production
  activation, freeze, and export hotkeys.
- **Done:** two real silent failures classified to the production OCR-output
  stage. Their provider-internal detection-versus-recognition cause remains
  unavailable from Vision evidence alone.
- **Not available:** macOS external display, and every Windows DPI row
  (100/125/150/mixed). Declared, never simulated.

## Remaining evidence before a Wave 3 correction

The shipped configuration now has a demonstrated repeated failure at the OCR
output boundary. Before selecting a correction, run one controlled comparison
against `frozen-9`/`frozen-10` that changes only model input context while
holding application, display, target content, provider and downstream pipeline
constant. If preserving the full line makes Vision emit the target Hangul, the
ROI/context family is supported. If it does not, the correction remains inside
the OCR family. Do not mix this experiment with dwell, gate, resolver,
morphology, dictionary, or provider changes.

Windows rows of the validation matrix need a Windows machine and are declared
`not available` until one exists. Installing Noto Sans KR and re-running
`ocr-corpus-generate` would make the corpus committable and its numbers
comparable across machines.

## Blockers

None for reviewing Bundle A. Git is usable again. Wave 3 product work remains
evidence-gated on the one controlled causal comparison above.

## Wave 2 evidence runs

All under `artifacts/benchmarks/runs/` (gitignored), 8 cases x 5 passes each:

| Run ID | Backend | Mode |
|---|---|---|
| `5b18673a-1648-4af1-a7a3-66c2966a7ac5` | Vision | ocr-only |
| `74e187fb-360a-4990-9edc-0ca6ddd3bf4f` | EasyOCR | ocr-only |
| `2a74fd7b-37b3-4029-bd40-ef568a92da0f` | EasyOCR | detection-only |
| `858a61e2-350a-4a3a-ae44-f48c3fa80a0d` | EasyOCR | recognition-only |

Headline, all *derived* from retained `samples.jsonl`: Vision scored 1.00 exact
match and 0.000 CER; EasyOCR scored 0.00 exact match, 0.177 CER, 0.215 Hangul
SER and got the target word right in 3 of 8 cases. Warm p50 21.3 ms versus
27.1 ms. Peak RSS growth 49.6 MB versus 945.2 MB. Full tables, per-case
failures and every limitation are in the baseline report.

The EasyOCR failures independently reproduce the batchim defect already recorded
in `docs/execution/reports/ocr-latency-and-roadmap.md` (`떨어뜨렸어요` read as
`떨어뜨렇어요`). This corroborates the 2026-09-20 Vision selection; it proposes
no new backend decision.

## Exact next action

**Stop at the updated Bundle A Review Handoff.** The missing human-operated
evidence has been supplied and classified. Begin Phase B only as a separate
human-authorized review run. After Bundle A review/approval, Wave 3 begins as
its own Bundle B with the controlled causal comparison above; it may implement
only the corresponding task family once that result is known.

Waves 4–7 remain the final acquisition program, not one combined implementation
bundle. Preserve their existing gates: Wave 3 stability plus explicit engine-
seam approval before Wave 4; one real selected platform for Wave 5; a real
second-platform environment before Wave 6; and separate deliberate research
authorization for optional Wave 7. Each bundle still ends at its own Review
Handoff.
