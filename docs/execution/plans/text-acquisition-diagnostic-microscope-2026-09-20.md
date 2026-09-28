# Text acquisition diagnostics and semantic fallback execution plan

**Status:** implementation-ready plan only; no implementation is authorized by
this document.
**Date:** 2026-09-20
**Immediate priority:** Waves 1-2, ending at one Review Handoff.
**Later scope:** Waves 3-7 are evidence-gated, separately authorized execution
units.
**Linear:** the work most closely belongs to HAN-35, with performance evidence
overlapping HAN-41. HAN-35 is currently `Backlog` and blocked by HAN-32. This
planning run does not change that state, create issues, or bypass the blocker.
Before implementation, the human must authorize a Linear representation that is
actually READY (for example, a dedicated diagnostic bundle with honest
dependencies, or an approved lifecycle change to HAN-35).

This plan turns the 2026-09-20 text-acquisition investigation into bounded
implementation work. It follows `docs/execution/05-execution-plan.md`: Phase A
implements an authorized bundle, runs proportional checks, writes one Review
Handoff, and stops. Deep review is a separate human-triggered Phase B.

## 1. Fixed decisions and exclusions

The following are inputs, not questions for the executor to reopen:

1. ROI completeness, gate rejection, OCR-versus-resolver failure, DPI alignment,
   memory ceilings, and visual segmentation remain benchmark questions until
   measured on real frozen failures.
2. Waves 1-2 preserve current OCR selection, including macOS `auto -> Vision`.
   They do not promote or demote either backend.
3. No PaddleOCR, new OCR provider, OpenCV, classical-CV word splitter, native
   accessibility acquisition, DOM integration, or language-pipeline refactor is
   implemented in Waves 1-2.
4. Real screen pixels and text are local developer evidence. Freezing pins one
   coherent completed lookup in memory and writes no pixels, OCR text, or
   provider crops. Only a separate explicit developer export persists those
   private artifacts, below the existing gitignored
   `artifacts/benchmarks/runs/` tree.
5. Generated or sanitized fixtures may be committed only when their source and
   licensing are recorded. Private real-world captures remain local.
6. A future validated direct-text result does not fall back to OCR merely because
   KRDICT returns `NOT_FOUND`.
7. Native acquisition is implemented one platform at a time, after the pixel
   path is diagnosed. No permanent timeout is invented before native latency is
   measured.
8. Normal startup, packaging, first-run resources, popup behavior, bounded
   latest-wins execution, and the final request-currency check must remain
   unchanged during diagnostic work.

## 2. Current seams to reuse

The plan extends existing mechanisms rather than building a second diagnostic
stack:

- `hanly_app.runtime_trace.RuntimeTraceSink` and child-process trace replay for
  non-blocking correlated events.
- `CaptureService`, `CaptureResult`, `ScreenRect`, and `DEFAULT_ROI_GRID` for the
  real capture calculation.
- `LookupRequest`, `LookupWorker`, `_CachingOCRProvider`, `_TextPresenceGate`, and
  the full-result cache in `hanly_app.composition`.
- `EasyOCRProvider` and its injected-reader test seam.
- `WordResolver.resolve_target_detail`, `TargetResolution`, and
  `LookupContext`.
- `LiveTraceRecorder`, `RuntimeTraceAdapter`, `SessionPrivacy`,
  `LiveResourceSampler`, `RunStore`, `DiagnosticSnapshot`, and the existing
  JSON/PNG/HTML run artifacts.
- The benchmark CLI in `benchmarks/dev/cli.py`; no second executable or product
  entry point is created.

The current implementation defects that Wave 1 must correct before its evidence
is trusted are:

- `_TracingResolver` does not forward `resolve_target_detail`, so traced lookup
  can silently use `cursor_index=0` and differ from untraced behavior.
- `live-hover` constructs `CaptureService()` with grid 1 while production passes
  `DEFAULT_ROI_GRID` (32).
- HUD backend labeling is hard-coded rather than derived from the resolved
  provider.
- HUD green rectangles are every normalized OCR bounding box, but their visual
  treatment does not distinguish capture, raw detection, selected OCR region,
  resolved word bounds, or retained target.
- The gate reports no decision or measurements; a rejection is indistinguishable
  from provider-empty output.
- A capture digest is observed independently from lookup correlation. Exact
  pixels cannot yet be joined to one request without relying on event order.

## 3. Execution units, tiers, and stop boundaries

```text
Immediate Bundle A — diagnostic evidence
  Wave 1: observability integrity + complete benchmark microscope
  checkpoint: one trustworthy frozen lookup exists
  Wave 2: corpus + OCR-only/repeatable evaluation
  Review Handoff: STOP; no Phase B and no Wave 3

Bundle B — evidence-based pixel correction
  Wave 3 only, selected from Bundle A evidence
  Review Handoff: STOP

Bundle C — common language seam
  Wave 4 only, after human architecture approval
  Review Handoff: STOP

Bundle D — first native source
  Wave 5, one platform only
  Review Handoff: STOP

Bundle E — second platform/browser evaluation
  Wave 6
  Review Handoff: STOP

Bundle F — optional OCR research
  Wave 7, only if deliberately authorized
  Review Handoff: STOP
```

Bundle A is Gate tier because it crosses capture, worker-process tracing,
provider observation, resolver semantics, and durable benchmark evidence. Most
individual tasks are Standard or Light, but the convergence is Gate tier. The
later language-pipeline and native-acquisition bundles are also Gate tier.

If Bundle A is authorized, the executor creates and maintains exactly one live
ledger:

`docs/execution/checkpoints/text-acquisition-diagnostics-2026-09-20.md`

The ledger records material decisions, completed task IDs, checks, evidence run
IDs, current usage-limit state at wave boundaries, and the exact next action.
It is not a second plan or a running diary.

Bundle A ends at:

`docs/execution/review-handoffs/text-acquisition-diagnostics-2026-09-20.md`

The durable measured baseline, first written after real evidence exists, is:

`docs/execution/reports/text-acquisition-diagnostic-baseline.md`

No report is created merely to say implementation happened.

## 4. Evidence model and privacy boundary

Wave 1 introduces a versioned benchmark evidence schema, not a public engine
contract. One frozen lookup is identified by `run_id`, `hover_request_id`,
`lookup_request_id`, an immutable capture ID, and the resolved backend.

The evidence graph is:

```text
capture plan + exact ROI bytes
  -> gate observation
  -> cache decisions
  -> provider execution
  -> raw/provider-specific OCR stages where available
  -> normalized OCRResult values
  -> target-resolution calculation
  -> morphology candidates
  -> KRDICT query/result
  -> retained screen-space target and presentation outcome
```

The schema must distinguish `measured`, `derived`, and `estimated` values. For a
normal production EasyOCR lookup, the normalized output produced by the real
`EasyOCRProvider -> Reader.readtext()` invocation is the authoritative live OCR
evidence. If the same frozen ROI is later inspected by the staged EasyOCR
runner, every staged detector box, crop, recognizer input, and output is labeled
as replay/comparison evidence. Replay-only internals are never presented as the
exact internals of the earlier `readtext()` pass. The inspector compares the
live and staged normalized outputs and surfaces any divergence explicitly; a
divergent replay cannot explain or replace the live result.

Only a lookup intentionally executed through the staged diagnostic path may
associate its staged detector, crop, and recognizer evidence with that actual
diagnostic invocation. Its normalized OCR output is authoritative for that
diagnostic invocation only, not for a separate production lookup.

Normal tracing continues to retain only JSON-safe, privacy-minimized metadata.
The benchmark may retain immutable ROI bytes and private text/crops in a small
bounded in-memory ring. Freeze pins one coherent completed lookup in that memory
only. It performs no disk write. Only a later explicit export action writes
`input.png`, recognized text, or provider crops to the gitignored artifact root.
Normal tracing and non-exported frozen sessions never persist raw screen
content.

Diagnostic evidence defaults to private, non-exported structures and narrow
observation seams. It is emitted from the same resolver/language calculation
being observed and is never reconstructed independently after the fact. Public
`hanly` contracts are not extended solely for diagnostics unless no technically
sound private seam exists; that necessity and the rejected alternatives must be
recorded before such a change begins.

## 5. Wave 1 — observability integrity and complete benchmark microscope

### W1.0 — Freeze the trace semantics before adding fields

**Tier:** Standard. Instrumentation-only production changes.

**Objective**

Make traced and untraced lookup semantically identical, report the actual
backend, and reproduce production capture configuration.

**Likely files**

- `packages/hanly-app/src/hanly_app/composition.py`
- `packages/hanly-app/src/hanly_app/runtime.py`
- `packages/hanly-app/src/hanly_app/application.py`
- `benchmarks/dev/live_runner.py`
- `benchmarks/dev/hud/session.py`
- `tests/test_app_composition.py`
- `tests/test_runtime_trace.py`
- `benchmarks/dev/tests/test_live_runner.py`

**Implementation**

- Add `resolve_target_detail` forwarding and tracing to `_TracingResolver`.
- Preserve the returned `cursor_index`, `region_start`, and selected region;
  never recompute a different resolution for tracing.
- Construct live benchmark capture with the same ROI size and
  `DEFAULT_ROI_GRID` used by production composition.
- Derive the displayed provider from resolved runtime composition rather than a
  hard-coded string.
- Add paired traced/untraced regression fixtures proving identical
  `LookupResult`, selected lexical candidate, lemma, and status.

**Manual validation**

Run one controlled EasyOCR and one macOS-auto session, when available, and
confirm the HUD label matches the worker provider.

**Evidence**

Trace parity tests and a provider/config header in every diagnostic run.

**Completion**

Enabling tracing cannot change the selected surface word, cursor index, lexical
candidate, lemma, or result status.

**Risks**

Structural protocol forwarding can accidentally cause a resolver method to run
twice or can make tests pass only with the tracing wrapper. The paired
traced/untraced fixture is the guard.

**Must not change**

Provider selection, resolver policy, cache policy, ROI dimensions, popup policy,
or language behavior.

### W1.1 — Capture-plan and coordinate evidence

**Tier:** Standard. App seam extension; no capture behavior change.

**Objective**

Expose the actual calculation that produced one ROI without independently
reimplementing capture math in the benchmark.

**Likely files**

- `packages/hanly-app/src/hanly_app/capture.py`
- `packages/hanly-app/src/hanly_app/hover_lookup.py`
- `packages/hanly-app/src/hanly_app/manual_lookup.py`
- `packages/hanly-app/src/hanly_app/runtime_trace.py`
- `benchmarks/dev/live_runner.py`
- `tests/test_capture.py`
- `tests/test_hover_lookup_e2e.py`
- `tests/test_manual_lookup.py`

**Contract extension**

Add an app-owned immutable capture-observation value, either attached optionally
to `CaptureResult` or emitted through a narrow capture observer. It contains:

- cursor coordinates as received by capture;
- selected monitor and its bounds;
- configured clip region/bounds;
- ideal unsnapped rectangle;
- snapped desired rectangle and grid size/cell;
- actual intersected capture rectangle;
- ROI-local target;
- left/top/right/bottom edge distances;
- returned image dimensions, format, byte length, and privacy-safe digest;
- coordinate-source labels and any OS/display-scale metadata actually observed.

The value is descriptive. It does not introduce a compensating scale factor or
change `_centered_region`, snapping, clipping, or monitor selection.

**Freeze correlation**

Add one non-blocking, optional benchmark observer at the point where
`HoverLookupRuntime` has both the `hover_request_id` and `CaptureResult`. It may
receive immutable bytes by reference for a bounded in-memory ring. Product code
defines only the narrow callback protocol; storage remains in `benchmarks/dev`.

**Tests**

- Exact ideal/snapped/actual rectangles around grid boundaries.
- Monitor and configured-region clipping.
- Negative virtual-desktop origins.
- Edge-distance calculations.
- Correlation by IDs rather than event order.
- Observer failure/drop cannot perturb capture or submission.

**Manual validation**

- macOS Retina and an external display where available.
- Windows 100%, 125%, 150%, and mixed DPI later in the validation matrix; these
  do not block initial microscope completion.
- Compare Qt cursor, pynput cursor, MSS bounds, and ROI-local target numerically.

**Evidence**

`capture.json` plus an image overlay showing ideal, snapped, actual, cursor, and
edge distances.

**Completion**

A frozen failure answers whether the complete target could fit in the actual
ROI and whether clipping or grid movement occurred. It does not claim that a
word is complete without looking at the captured pixels.

**Risks**

Adding evidence directly to `CaptureResult` can create churn across many test
doubles; an observer can create race/correlation errors. Choose the smaller
shape that preserves ID-based correlation and immutable capture math.

**Must not change**

ROI anchoring, ROI size, grid size, clipping policy, DPI transforms, monitor
selection, or capture backend.

### W1.2 — Gate and cache decision evidence

**Tier:** Standard. Instrumentation-only production changes.

**Objective**

Distinguish full-result cache hits, OCR cache hits, gate execution, gate
rejection, and actual provider execution.

**Likely files**

- `packages/hanly-app/src/hanly_app/composition.py`
- `packages/hanly-app/src/hanly_app/runtime_trace.py`
- `tests/test_app_composition.py`
- `tests/test_runtime_trace.py`
- `benchmarks/dev/tests/test_live_runner.py`

**Private diagnostic data**

- Full-result cache: hit/miss and privacy-safe key fingerprint.
- OCR cache: hit/miss and privacy-safe image fingerprint.
- Gate: enabled, ran/bypassed, pixel format, sampled channel/method, row and
  column steps, sampled rows/columns, delta threshold, transition target,
  observed transition count, pass/reject.
- Provider: executed/skipped and why.

Refactor the boolean gate calculation into a private immutable measurement so
the decision and its inputs cannot disagree. Preserve the current algorithm in
this task, including its first-channel behavior; changing it before evidence is
explicitly forbidden.

**Tests**

- Gate pass, reject, malformed-safe-pass, and early threshold exit.
- OCR cache hit reports `gate_ran=false`, not a stale previous gate result.
- Full-result hit reports both downstream cache/provider stages skipped.
- Identical and changed bytes produce the expected cache decisions.
- Tracing disabled has no additional persistence and no result change.

**Manual validation**

Freeze one flat ROI and one text ROI and confirm the numerical measurement
matches the visible pixels.

**Evidence**

One ordered decision chain in `diagnostic.json` and the inspector.

**Completion**

An empty OCR result can be attributed to gate rejection, provider-empty output,
or cache reuse without guessing.

**Risks**

Mutable `last_*` fields can leak a previous request's decision across a cache
hit. Every lookup must reset observation state and tests must cover the bypass
path.

**Must not change**

Gate thresholds, sampling algorithm, cache sizes/keys/eviction, retry policy, or
provider behavior.

### W1.3 — Staged EasyOCR evidence

**Tier:** Gate. Developer-only execution path plus narrowly scoped adapter test
seams; normal provider behavior remains unchanged.

**Objective**

For an explicit EasyOCR diagnostic run, record the exact regions and crops used
by detection and recognition.

**Likely files**

- `benchmarks/dev/easyocr_stages.py` (new)
- `benchmarks/dev/microscope.py` (new)
- `benchmarks/dev/cli.py`
- `packages/hanly/src/hanly/easyocr_provider.py` only if a minimal observation
  seam is required to avoid duplicating normalization
- `tests/test_easyocr_provider.py`
- `benchmarks/dev/tests/test_easyocr_stages.py` (new)
- `benchmarks/dev/tests/test_microscope.py` (new)

**Implementation policy**

- Keep normal `EasyOCRProvider.recognize -> Reader.readtext` untouched.
- Preserve the live normalized output of that high-level production call as the
  authoritative OCR evidence for a normal production lookup.
- Implement a benchmark-owned staged runner pinned to the installed EasyOCR API:
  input reformatting, `detect`, horizontal/free grouping, crop extraction,
  rectification, recognizer resize/pad/normalization, and `recognize`.
- Reuse the adapter's normalization logic through a small pure helper if needed;
  do not copy Hanly normalization into the benchmark.
- A microscope intentionally launched in staged EasyOCR mode uses the staged
  result as that diagnostic lookup's actual OCR result, so its staged crops are
  the exact crops that reached recognition in that diagnostic invocation.
- Any staged inspection performed after a normal production lookup is labeled
  `comparison_replay`, whether the production provider was EasyOCR or Vision.
  Its detector/crop internals are not attributed to the original provider pass.
- Add a compatibility test that compares high-level and staged normalized output
  on controlled fixtures and frozen ROIs. A mismatch is surfaced as an explicit
  live-versus-staged divergence; it is not hidden by coercing outputs or by
  replacing the authoritative live result.

**Captured evidence**

The following may be held in memory for a staged invocation. They become disk
artifacts only after an explicit export:

- Raw detector polygons/boxes before Hanly normalization.
- Grouped horizontal and free-form regions.
- Exact grayscale/extracted crop.
- Perspective-rectified crop where applicable.
- Resized/padded recognizer image where practical.
- Raw recognized text and confidence.
- Final normalized `OCRResult` order, text, confidence, and quad.
- Detection, crop/preprocess, recognition, and normalization timings.

**Tests**

- API-shape failure is explicit and actionable when the pinned EasyOCR version
  changes.
- Horizontal and free-form crop fixtures.
- Crop bytes/dimensions and region IDs join correctly.
- High-level/staged comparison fixture that records equality or an explicit
  divergence without requiring replay to replace live output.
- Blank strings, confidence clamping, BGR conversion, and reading-order behavior
  remain covered by existing adapter tests.

**Manual validation**

Inspect at least one horizontal Korean line and one tilted/free-form fixture.
Confirm the in-memory staged crops are the images whose outputs are displayed;
after an explicit export, confirm the saved copies are byte-identical.

**Exported evidence**

After an explicit export: `ocr/raw-detections.json`,
`ocr/grouped-regions.json`, `ocr/crops/`, `ocr/recognizer-inputs/`,
`ocr/raw-recognition.json`, and `ocr/normalized-results.json`.

**Completion**

An EasyOCR lookup intentionally executed through the staged diagnostic path can
be followed from ROI bytes through the exact recognizer crops of that invocation
to its normalized OCR results. A normal production lookup instead preserves its
live normalized output as authoritative and identifies any staged follow-up as
comparison replay.

**Risks**

EasyOCR staging uses non-public implementation details and can drift on upgrade.
The version pin, API-shape failure, and high-level/staged equivalence check keep
that fragility inside developer tooling rather than the shipped provider.

**Must not change**

The shipped default call path, EasyOCR thresholds/options, model files, CPU
thread policy, sensitive retry policy, provider selection, or Vision behavior.

### W1.4 — Resolver, morphology, and dictionary evidence

**Tier:** Standard. Instrumentation-only engine/app changes.

**Objective**

Separate raw OCR correctness from target resolution and downstream language
selection.

**Likely files**

- `packages/hanly/src/hanly/word_resolver.py`
- `packages/hanly/src/hanly/contracts.py` only if a public contract change is
  proven technically necessary and its rationale is recorded first
- `packages/hanly/src/hanly/lookup_pipeline.py`
- `packages/hanly-app/src/hanly_app/composition.py`
- `tests/test_word_resolver.py`
- `tests/test_lookup_pipeline.py`
- `tests/test_app_composition.py`

**Contract approach**

Prefer a private, non-exported `TargetResolutionEvidence` calculation or a
narrow observation seam. It must be produced by the same resolver computation,
not by a second reconstruction after the lookup. Diagnostic evidence alone is
not a reason to extend the public `hanly` contracts or package exports. If a
public contract change becomes genuinely necessary, record the technical reason
and rejected private alternatives in the live checkpoint before changing it.
The evidence records:

- every usable OCR candidate and whether its quad contains the target;
- vertical-interior and tie-break scores;
- selected provider-order index;
- text-axis endpoints;
- horizontal fraction;
- per-character advance weights and cumulative ranges;
- estimated absolute character index;
- whitespace span, `region_start`, and cursor index within the surface;
- resolved surface word and estimated word bounds;
- reason for no resolution.

Tracing must preserve `TargetResolution` exactly. The morphology trace records
normalized tokens, POS, spans, lexical candidates, selected candidate, and
lemma when explicit text retention is enabled. Dictionary evidence records the
actual query key, result status, and entry count. Private text may be pinned by
freeze in memory, but remains subject to explicit export before any persistence.

**Tests**

- Evidence and ordinary resolver APIs return the same selection.
- Mixed Hangul/ASCII/space weights are exact.
- Overlap tie-break, target-on-space, tilted quad, and no-hit reasons.
- Cursor index reaches Kiwi unchanged under tracing.
- KRDICT query equals the selected lemma.

**Manual validation**

Freeze a multi-word OCR region and verify the displayed fraction, character,
surface, Kiwi candidate, and query visually.

**Evidence**

Separate inspector panes for raw OCR text, resolved surface word, Kiwi analysis,
selected lexical candidate, lemma, and KRDICT result.

**Completion**

A wrong popup can be classified as raw OCR, region selection, character/word
mapping, morphology candidate, lemma, or dictionary behavior.

**Risks**

A separately reconstructed explanation can disagree with the resolver it
describes. Evidence must be emitted from the same calculation and remain absent
rather than guessed when a detail is unavailable.

**Must not change**

Resolver weights, tie-breaking, whitespace policy, Hangul gate, confidence
policy, Kiwi selection, or KRDICT lookup behavior.

### W1.5 — Retained-hover and presentation evidence

**Tier:** Standard. Instrumentation-only production changes.

**Objective**

Show the screen-space region that suppresses subsequent captures and the final
currency/presentation outcome.

**Likely files**

- `packages/hanly-app/src/hanly_app/hover_target.py`
- `packages/hanly-app/src/hanly_app/hover_lookup.py`
- `packages/hanly-app/src/hanly_app/manual_lookup.py`
- `packages/hanly-app/src/hanly_app/qt_popup.py`
- `tests/test_hover_target.py`
- `tests/test_hover_lookup_e2e.py`

**Data**

- ROI-local estimated word bounds.
- Explicit transform used to reach screen space.
- Unpadded and protected retained word rectangles.
- Popup rectangle and transfer corridor when present.
- Request-current/stale decision and popup-visible/suppressed outcome.

**Tests**

- Coordinate conversion and padding.
- Current and stale result traces.
- Retained-target events correlate with the lookup that produced them.
- Trace failure cannot alter retention.

**Manual validation**

Move the pointer inside and outside the drawn retained bounds after freezing;
the frozen display stays unchanged while live behavior remains observable.

**Evidence**

Distinct overlays for selected OCR region, estimated word bounds, and retained
screen-space bounds.

**Completion**

The inspector can show whether a wrong retained rectangle prevented the next
capture or held the wrong answer.

**Risks**

Screen-space overlays can be mistaken for ROI-local geometry or can contaminate
capture. Coordinate spaces stay labeled, and any live overlay follows the
existing capture-exclusion/outside-border rules.

**Must not change**

Sticky-hover behavior, protection margin, transfer timing, dismissal, popup
placement, or request-currency policy.

### W1.6 — In-memory freeze, explicit export, and ergonomic inspector

**Tier:** Standard. Developer-only.

**Objective**

Make one completed lookup remain inspectable after the pointer moves.

**Likely files**

- `benchmarks/dev/microscope.py` (new)
- `benchmarks/dev/frozen_lookup.py` (new)
- `benchmarks/dev/diagnostics.py`
- `benchmarks/dev/live_runner.py`
- `benchmarks/dev/hud/hover_hud.py`
- `benchmarks/dev/hud/session.py`
- `benchmarks/dev/cli.py`
- `benchmarks/dev/README.md`
- `benchmarks/dev/tests/test_microscope.py` (new)
- `benchmarks/dev/tests/test_live_runner.py`
- `benchmarks/dev/tests/test_diagnostics.py`

**Behavior**

- Add a configurable developer freeze hotkey distinct from the phase-marker
  hotkey.
- Keep only a bounded in-memory ring of recent correlated lookups.
- The freeze action selects one completed request atomically and pins its
  evidence. Moving the mouse may continue normal live lookup, but it cannot
  mutate the pinned record. Freeze performs no disk write and persists no raw
  pixels, OCR text, or provider crops.
- Export is a separate explicit developer action. It serializes the already
  frozen record into the existing gitignored run directory; without export,
  the private evidence disappears with the session.
- Normal trace files may retain privacy-minimized metadata and digests, but raw
  screen content and recognized text are absent from normal tracing and every
  non-exported frozen session. Any existing raw-text retention option must obey
  this export boundary rather than persisting during live tracing.
- Render the pinned lookup in the in-memory inspector. Only explicit export
  produces the local HTML plus PNG/JSON evidence. The exported HTML uses the
  exact frozen ROI and numerical evidence; it does not invent illustrative
  crops.
- Rename the generic green-box presentation. Use distinct labeled layers for
  actual ROI, raw detector regions, normalized OCR regions, selected OCR region,
  estimated surface bounds, retained bounds, and cursor.
- Record missing evidence as `unavailable` with a reason. Vision does not pretend
  to have EasyOCR crops; an EasyOCR replay is visibly separate.

**Tests**

- Freeze is immutable after later events.
- Ring eviction and missing/incomplete request handling.
- Export requires an explicit action and writes only inside the configured
  gitignored output root.
- Freeze alone causes no file creation or raw-content persistence.
- Privacy rules exclude raw text/images/crops from normal tracing and every
  non-exported session, including a session with a pinned frozen lookup.
- HTML/JSON layer labels correspond to schema fields.
- Hotkey callback remains non-blocking; expensive encoding and file writes run
  away from the mouse/UI callback.

**Manual validation**

Freeze a real lookup, move to another word, and verify every in-memory displayed
field and image still belongs to the original IDs without creating a private
artifact file. Then explicitly export it, close/reopen the exported local
inspector, and confirm that export is self-contained.

**Exported evidence**

Only after the explicit export, at minimum:

```text
metadata.json
input.png
diagnostic.json
diagnostic.png
diagnostic.html
events.jsonl
result.json
process.csv
ocr/...                 # EasyOCR staged run only
```

**Completion**

The frozen lookup remains visually and numerically inspectable after pointer
movement entirely from in-memory evidence. No real pixels, OCR text, or provider
crops reach disk before the separate explicit export.

**Risks**

The freeze hotkey may arrive between capture and terminal presentation, or an
export may block the UI. Freeze selects only a coherent completed in-memory
record and never encodes to disk; export is asynchronous and reports incomplete
records explicitly.

**Must not change**

Normal `hanly` startup, package contents, product hotkeys, Control Center,
continuous persistence policy, or target application pixels.

### W1.7 — Wave 1 convergence and checkpoint

**Tier:** Gate convergence.

**Checks**

- Focused benchmark tests and all touched package tests.
- `.venv/bin/python -m pytest benchmarks/dev/tests tests/test_capture.py tests/test_app_composition.py tests/test_runtime_trace.py tests/test_word_resolver.py tests/test_lookup_pipeline.py tests/test_hover_target.py tests/test_hover_lookup_e2e.py`
- `.venv/bin/python -m ruff check packages packaging tests tools benchmarks`
- `.venv/bin/python -m mypy packages packaging tests tools benchmarks`
- A real macOS/Windows frozen lookup where the available environment permits.
- An explicit EasyOCR staged lookup, even when macOS auto continues to use
  Vision for the product run.

At the boundary, update the one checkpoint with run IDs, checks, gaps, and the
exact Wave 2 next action. Do not write a Review Handoff yet when Waves 1-2 were
authorized as one bundle.

**Risks**

Native/manual evidence may be unavailable even when automated checks pass. The
checkpoint must preserve that gap and must not let synthetic evidence satisfy a
real-frozen-lookup exit criterion.

**Wave 1 exit criterion**

One frozen lookup can answer, without inference:

```text
These were the pixels.
This was the production-equivalent ROI/grid and coordinate calculation.
This was the cursor.
The gate did this.
The caches did this.
This provider executed or was skipped for this reason.
EasyOCR detected these regions and recognized these exact crops when EasyOCR
was the diagnostic provider.
Hanly normalized the provider output this way.
This OCR region was selected.
The resolver mapped the target to this fraction, character, and surface.
Kiwi produced these analyses and selected this lexical candidate.
KRDICT queried this lemma and returned this status.
These were the retained bounds and presentation decision.
The observed failure entered at this named stage.
```

## 6. Wave 2 — corpus and repeatable OCR evaluation

Wave 2 consumes the Wave 1 schema and staged runner. It does not rebuild the
microscope.

### W2.0 — Corpus manifest and provenance

**Tier:** Standard. Developer-only.

**Objective**

Define a small versioned corpus that can mix committed licensed fixtures and
local private frozen cases.

**Likely files**

- `benchmarks/dev/corpus.py` (new)
- `benchmarks/fixtures/ocr/manifest.json` (new)
- `benchmarks/fixtures/ocr/generated/` (new, licensed outputs only)
- `benchmarks/dev/tests/test_corpus.py` (new)
- `.gitignore` only if a new local corpus path is needed; prefer the existing
  `artifacts/benchmarks/` root.

**Manifest contract**

Each case records a stable ID, image path, privacy/provenance class, expected
complete text when known, expected target surface and point when known,
expected regions when annotated, render/source metadata, and applicable tags:
light/dark, font size/weight, mixed script, punctuation, scale, blur/compression,
orientation, browser/chat/native/raster, and real/synthetic.

Private cases may be referenced from a local manifest below the run artifacts;
committed manifests must not contain machine-specific absolute paths or private
text.

**Tests**

Schema validation, duplicate IDs, missing assets, bounds, privacy/provenance,
unknown metric fields, and deterministic ordering.

**Manual validation**

Open every initial committed image and confirm its label and licensing record.

**Evidence**

Corpus inventory with counts by provenance and tag.

**Completion**

The same command can enumerate committed and opted-in local cases without
copying private captures into Git.

**Risks**

Manifest portability can leak absolute paths or private labels. Validation must
reject those in committed manifests and keep private roots outside Git.

**Must not change**

Product fixtures, runtime resources, KRDICT, or OCR defaults.

### W2.1 — Synthetic Korean screen-text fixture generator

**Tier:** Light. Developer-only.

**Objective**

Generate reproducible Korean UI-like samples without pretending they represent
real application rendering.

**Likely files**

- `benchmarks/dev/synthetic_ocr.py` (new)
- `benchmarks/fixtures/ocr/generator.json` (new)
- `benchmarks/dev/tests/test_synthetic_ocr.py` (new)

**Coverage**

Licensed Korean fonts only; light/dark backgrounds; several font sizes and
weights; Hangul with particles/endings; mixed Latin/digits/punctuation; multiple
line spacings; controlled scale and mild compression. Record the font file/hash,
renderer/library versions, and generation parameters.

**Tests**

Deterministic manifest and dimensions, target inside image, text label retained,
font/license validation, and no platform font fallback hidden as a named font.

**Manual validation**

Review a contact sheet for clipping, bad glyph fallback, and unreadable cases.

**Evidence**

Generated images plus reproducible generator metadata.

**Completion**

Fixtures regenerate byte-identically in the supported environment or document
the exact platform-dependent fields when byte identity is impossible.

**Risks**

Silent font fallback produces mislabeled evidence. Resolve and hash the actual
font file, and fail generation when the requested licensed face is unavailable.

**Must not change**

OCR or product rendering code; synthetic success is not a product accuracy
claim.

### W2.2 — OCR-only, detection-only, and recognition-only commands

**Tier:** Gate. Developer-only.

**Objective**

Measure OCR without constructing Kiwi, KRDICT, `LookupPipeline`, hover, or UI.

**Likely files**

- `benchmarks/dev/ocr_benchmark.py` (new)
- `benchmarks/dev/easyocr_stages.py`
- `benchmarks/dev/cli.py`
- `benchmarks/dev/run_store.py`
- `benchmarks/dev/README.md`
- `benchmarks/dev/tests/test_ocr_benchmark.py` (new)
- `benchmarks/dev/tests/test_cli.py`

**Commands/modes**

- `ocr-only`: image to normalized OCR results.
- `detection-only`: detector/grouping geometry, no transcription scoring.
- `recognition-only`: annotated or previously extracted crop directly to the
  recognizer, bypassing detection.
- `frozen-replay`: exact Wave 1 ROI and configuration, clearly labeled replay.

The command selects an existing provider explicitly or uses the recorded
product backend. It does not add a new provider. Vision participates only in
the stages it actually exposes; EasyOCR-specific crops stay backend-specific.

**Tests**

Prove that OCR-only modes never construct Kiwi/KRDICT, validate mode-specific
inputs, retain raw samples, close providers, and report unavailable stages
honestly.

**Manual validation**

Run one case in every mode and confirm detection-only and recognition-only do
not execute the omitted stage.

**Evidence**

Appendable per-sample JSONL and stage artifacts compatible with the microscope.

**Completion**

Detection and recognition can be timed and scored independently on identical
inputs.

**Risks**

Mode implementations can accidentally include omitted setup or reuse warmed
state inconsistently. Record construction/warm state and assert omitted
providers/stages were not called.

**Must not change**

The full `real-lookup` command, production composition, models, provider
selection, or language pipeline.

### W2.3 — Correctness metrics

**Tier:** Standard. Developer-only.

**Objective**

Score provider output and target usefulness separately.

**Likely files**

- `benchmarks/dev/ocr_metrics.py` (new)
- `benchmarks/dev/ocr_benchmark.py`
- `benchmarks/dev/statistics.py`
- `benchmarks/dev/tests/test_ocr_metrics.py` (new)

**Metrics**

- Exact complete-string match.
- Unicode-normalized character error rate.
- Hangul syllable error rate, with normalization stated.
- False-empty rate.
- Detection precision/recall at declared IoU thresholds.
- Target-containing-region recall.
- Correct target-surface rate where a point/surface annotation exists.
- Repeated-input output variance.
- Gate false-negative rate when gate evidence exists.

Metrics with missing ground truth are `not_applicable`, never zero. Provider
ordering and normalization are retained so a correct string in the wrong region
does not become a target-word success.

**Tests**

Known edit-distance examples, Korean Unicode normalization, empty references,
multiple regions, IoU boundaries, target-containing logic, and variance.

**Manual validation**

Hand-calculate a small scored case and compare the report.

**Evidence**

Per-case results plus aggregate counts and confidence intervals/sample counts
where appropriate.

**Completion**

Every aggregate is reproducible from retained raw per-case records.

**Risks**

Unicode normalization or region matching can make a metric look better while
changing the expected task. Store raw and normalized strings and state every
normalization/IoU rule in the run metadata.

**Must not change**

OCR outputs, annotations to make a model look better, or product acceptance
criteria based on one synthetic corpus.

### W2.4 — Cold/warm latency and memory/RSS

**Tier:** Standard. Developer-only.

**Objective**

Measure initialization, warm inference, steady resident memory, peak memory,
and repeated-input variance without assuming a memory budget.

**Likely files**

- `benchmarks/dev/ocr_benchmark.py`
- `benchmarks/dev/live_telemetry.py`
- `benchmarks/dev/probes.py`
- `benchmarks/dev/statistics.py`
- `benchmarks/dev/tests/test_ocr_benchmark.py`

**Measurements**

- Baseline process RSS.
- Provider-initialized RSS.
- First inference.
- Warmup and warm sample durations.
- Detection/crop/recognition/normalization durations where exposed.
- Warm steady-state and peak RSS.
- One-provider-at-a-time measurements by default.
- Optional two-engine comparison only as an explicit research run, never normal
  product composition.

Every percentile states environment, sample count, condition, and whether it is
measured or derived.

**Tests**

Cold/warm labeling, percentile derivation from raw samples, unavailable RSS,
process cleanup, and no accidental inclusion of disk flush time in inference.

**Manual validation**

Run a short smoke campaign and a longer repeatable campaign; compare raw samples
to the summary.

**Evidence**

`process.csv`, per-stage JSONL, environment metadata, and p50/p95 summaries.

**Completion**

Accuracy, latency, and resident-memory evidence can be compared without loading
two heavy engines by default.

**Risks**

OS caches, model initialization, sampling overhead, and child processes can
confound RSS/latency. Record process identity and condition, retain raw samples,
and avoid treating a single machine as a product budget.

**Must not change**

Product residency/unloading strategy, CPU-thread defaults, or a permanent
memory ceiling.

### W2.5 — Repeatable report and regression comparison

**Tier:** Standard. Developer-only plus one durable evidence report.

**Objective**

Turn raw runs into a reproducible baseline without turning one machine into a
cross-platform claim.

**Likely files**

- `benchmarks/dev/ocr_benchmark.py`
- `benchmarks/dev/statistics.py`
- `docs/execution/reports/text-acquisition-diagnostic-baseline.md` (new)
- `benchmarks/dev/tests/test_ocr_benchmark.py`

**Report content**

- Run IDs and exact commands.
- Environment and provider versions.
- Corpus composition/provenance.
- Measured capture/gate/OCR/resolver failure classifications from frozen cases.
- Correctness, p50/p95, RSS, and repeated-input variance.
- Explicit unknowns and missing platform matrix rows.
- No OCR-backend product decision unless the evidence and a human decision both
  support it.

**Tests**

Regeneration from raw run files, missing/corrupt run handling, and stable schema
version reporting.

**Manual validation**

Regenerate the report tables from a clean command and spot-check against JSONL.

**Completion**

A fresh agent can find the raw evidence and reproduce every reported number.

**Risks**

A hand-edited report can drift from raw runs. Generate quantitative tables from
run files and reserve prose for interpretation, limitations, and decisions.

**Must not change**

Architecture sources, provider defaults, product budgets, or backend status.

### W2.6 — Bundle A convergence and Review Handoff

Run the full repository gates once:

```bash
.venv/bin/python -m pytest
.venv/bin/python -m ruff check packages packaging tests tools benchmarks
.venv/bin/python -m mypy packages packaging tests tools benchmarks
```

Also run one real frozen-hover exercise and the OCR corpus smoke command on the
available native platform. Missing Windows/macOS matrix cells are declared, not
simulated.

**Risks**

The bundle can appear complete from tooling alone without a real failing case.
The handoff must say whether a real failure was captured and keep all unanswered
benchmark questions open when it was not.

Update the one checkpoint, write the baseline report from actual runs, then
write one Review Handoff at the declared path. Move only authorized Linear
members to `In Review` if and when a real READY bundle exists. Stop. Do not begin
deep review, pixel fixes, a language refactor, native acquisition, or commits.

**Wave 2 exit criterion**

- A manifest-driven corpus mixes safe committed fixtures and opted-in private
  frozen cases.
- OCR-only, detection-only, recognition-only, and frozen-replay modes work.
- Correctness, detection, target-word, latency, memory, and variance metrics are
  regenerated from raw evidence.
- At least one real failure is classified to a named stage, or the report
  truthfully states that no real failing sample was supplied.

## 7. Wave 3 — evidence-based pixel-path correction

Wave 3 is not part of Bundle A. Its exact implementation task is chosen only
from Waves 1-2 evidence. The executor writes a short issue-local specification
for one demonstrated dominant failure; it does not rewrite this master plan.

**Dependencies:** Bundle A Review Handoff, raw failing runs, and explicit Wave 3
authorization.
**Tests:** one regression test for each preserved real failure, the focused
component tests, the unchanged corpus, and bundle mechanical gates.
**Manual validation:** reproduce the original failure and the corrected behavior
on the same application/display configuration.
**Evidence:** before/after correctness, latency, and any affected resource
measurement using identical inputs and configuration.

**Post-Bundle A evidence update (2026-09-21):** human-operated production run
`ef2c1ffc-3746-4b94-a40a-680b7e9e29c3` captured two real silent hover failures
as `frozen-9` and `frozen-10`. In both, the gate passed and the live production
Vision provider executed on an uncached 200x100 ROI containing Korean under the
cursor, but normalized OCR contained only nearby numbered-list markers and no
Hangul region. Resolution therefore had no candidate at the target, and
morphology and dictionary were correctly not reached. This classifies where the
failure first becomes observable as **production OCR output** and rules out a
gate, resolver, morphology, dictionary, or presentation cause for those cases.
Vision exposes no separable detector evidence, and both captured UI lines extend
beyond the fixed ROI, so the record does not yet distinguish detector omission,
recognition omission, or sensitivity to truncated line context. Wave 3 must
change no product behavior until one controlled same-case input experiment
separates those causes. The successful glued-word captures from the same run are
a separate morphology/dictionary-policy observation and must not be bundled
into this pixel-path correction.

Candidate task families and likely files are:

| Evidence | Likely files | Allowed first experiment | Explicit exclusion |
|---|---|---|---|
| ROI/grid truncation | `hanly_app/capture.py`, `hover_lookup.py`, capture tests | shift an edge-clipped ROI inward, or one bounded evidence-triggered wider recapture | global larger ROI without measurement |
| gate false negatives | `hanly_app/composition.py`, gate tests | conservative measured-channel/luminance correction | threshold tuning from synthetic-only data |
| DPI mismatch | `capture.py`, native coordinate adapter/tests | explicit proven transform | guessed scale factor |
| OCR detection | EasyOCR config/benchmark and provider tests | one isolated option/model-input experiment | new provider or PaddleOCR |
| OCR recognition | EasyOCR config/benchmark and provider tests | one isolated recognizer/input experiment | dictionary-backed guessing |
| resolver mapping | `hanly/word_resolver.py`, contracts/tests | provider geometry first; smallest NumPy/Pillow projection experiment only after the approved evidence pattern | OpenCV or generic CV layer |
| retained target | `hover_target.py`, `hover_lookup.py`, tests | correct measured transform/bounds | sticky policy redesign |
| morphology | `lookup_pipeline.py`, `kiwi_provider.py`, tests | one demonstrated cursor/candidate correction | broad language redesign |

For any selected task:

- Preserve the exact failing cases as regression evidence.
- Change one causal variable.
- Re-run the same frozen cases and corpus.
- Record correctness and latency before/after.
- End at its own Review Handoff.

Wave 3 must not preemptively combine ROI, gate, OCR, resolver, and morphology
changes.

**Wave 3 risks:** fixing a synthetic proxy instead of the real failure, moving
the error to a later stage, or accepting a faster incorrect result. Preserve the
original pixels and compare the complete stage chain before and after.
**Wave 3 completion:** one demonstrated dominant defect is corrected without
regressing the unchanged corpus or architectural invariants.
**Wave 3 must not change:** any unrelated stage, provider status, direct-text
architecture, or architecture source without separate approval.

## 8. Wave 4 — smallest acquisition-neutral language pipeline

**Authorization gate:** this changes an approved engine seam. The human must
approve the architecture decision and any authoritative documentation patch
before implementation makes it canonical.

**Objective**

Allow both pixel-derived and future semantic text to reuse:

```text
surface text + cursor index
  -> Hangul/usability policy
  -> Kiwi
  -> lexical candidate
  -> lemma
  -> KRDICT
  -> LookupResult
```

**Likely files**

- `packages/hanly/src/hanly/contracts.py`
- `packages/hanly/src/hanly/lookup_pipeline.py`
- `packages/hanly/src/hanly/language_pipeline.py` (new only if extraction is
  clearer than an internal helper)
- `packages/hanly/src/hanly/__init__.py`
- `packages/hanly-app/src/hanly_app/composition.py`
- `tests/test_lookup_pipeline.py`
- `tests/test_language_pipeline.py` (new)
- `docs/architecture/01-runtime-flow.md`
- `docs/architecture/02-component-architecture.md`
- matching visual companions only after approval, preserving invariant IDs
- `docs/CODE-MAP.md`

**Dependencies**

Bundle A evidence, any authorized Wave 3 stabilization needed for a trustworthy
pixel baseline, and explicit human approval of the new engine seam.

**Contract**

Introduce the smallest provider-neutral selection value containing surface text
and cursor/character index. Optional acquisition metadata must not pull UIA, AX,
DOM, screen rectangles, or desktop lifecycle into `hanly`.

The existing `LookupPipeline.lookup(image, target)` remains the compatible pixel
facade: OCR and `WordResolver` produce the selection, then delegate to the common
language stage. Direct callers may invoke the language stage without an image.

**Tests**

- Pixel and direct selections with identical text/index produce identical Kiwi,
  lemma, KRDICT, and `LookupResult` behavior.
- `NOT_FOUND` remains a language result.
- Existing OCR/provider protocol tests and package-direction tests remain green.
- No `hanly_app` or platform object enters the engine.

**Manual validation**

Replay a frozen pixel lookup and a manually supplied equivalent surface
selection and compare results.

**Evidence**

Behavioral parity table and focused timings showing the extraction itself adds
no meaningful cost.

**Completion**

The pixel path is backward-compatible and one acquisition-neutral language API
exists without a generic plugin framework.

**Risks**

The extraction can accidentally make screen geometry an engine concern, change
normal non-success semantics, or create two language implementations. Keep one
language implementation and prove pixel/direct parity from identical selections.

**Must not change**

OCR provider interfaces, provider selection, native acquisition, fallback
policy, dictionary-miss meaning, or popup behavior.

## 9. Wave 5 — one native direct-text source

Select Windows UIA **or** macOS AX only after considering available real test
machines, target applications, risk, and product priority. Do not implement
both in this bundle.

**Dependencies:** Wave 4's approved common language contract, a real validation
machine for the selected OS, and explicit platform selection.
**Production behavior:** this is the first wave that changes source-selection
behavior; all prior diagnostic work remains dev-only or observational.

**Likely files**

- one platform module under `packages/hanly-app/src/hanly_app/`, such as
  `text_acquisition_uia.py` or `text_acquisition_ax.py`
- `packages/hanly-app/src/hanly_app/text_acquisition.py` for the small app-owned
  result/validation/coordinator contract
- `application.py`, `hover_lookup.py`, `manual_lookup.py`, and composition only
  where routing requires them
- platform-specific tests plus common fallback tests
- permissions/config UI only when the chosen OS requires it

**Runtime policy**

```text
stable pointer
  -> one bounded native acquisition attempt
  -> validate freshness, geometry/range, target, security, and Korean surface
  -> valid: common language pipeline
  -> unsupported/ambiguous/error/timeout: existing capture/OCR pipeline
```

The development timeout is configurable and measured. No final product value is
declared until p50/p95 evidence exists. Calls run away from the UI thread and
remain subject to request currency.

**Coverage validation**

Prioritize browsers/Korean websites, Discord/Electron, and native text-heavy
controls. Explicitly retain OCR for games, images, video/raster subtitles,
canvas/WebGL, webtoon/manga content, and custom/inaccessible interfaces.

**Tests**

Fresh valid range, nearest-but-not-containing text, stale result, secure field,
unsupported provider, timeout, exception, non-Korean exact target, ambiguous
geometry, `NOT_FOUND`, cancellation, and stale presentation.

**Evidence**

Per-application coverage, accuracy, p50/p95, permission state, fallback reason,
and comparison with OCR on the same target where safely measurable.

**Completion**

One platform automatically uses valid direct text and invisibly falls back to
OCR without user mode selection. A validated KRDICT miss does not invoke OCR.

**Risks**

Accessibility calls can block, return nearest rather than containing text,
expose secure content, or report geometry in another coordinate space. Enforce
deadline, freshness, secure-field, containment, and request-currency checks
before bypassing OCR.

**Must not change**

The other platform, DOM integration, generic provider/plugin registries, or OCR
coverage for raster surfaces.

## 10. Wave 6 — second desktop platform and browser coverage

Implement the other native platform using the validated Wave 5 common contract.
Do not generalize the contract unless the second implementation proves a real
need. Evaluate browser accessibility across representative Korean sites,
iframes, Electron/chat, video subtitle surfaces, canvas, and inaccessible
content.

**Objective:** prove the common contract on the second desktop OS and document
where browser accessibility supplies semantic text versus OCR fallback.
**Likely files:** the second `text_acquisition_<platform>.py`, focused native
tests, permission/config integration where required, and only evidence-driven
changes to `text_acquisition.py`.
**Dependencies:** accepted Wave 5 contract and a real machine for the second OS.
**Tests:** reuse all common validation/fallback cases, plus platform coordinate,
permission/integrity, timeout, process-lifecycle, and browser-frame cases.
**Manual validation:** browsers/Korean sites, Discord/Electron, a native text
control, raster subtitle/video, image/webtoon, canvas/WebGL, and one inaccessible
custom surface.
**Evidence:** application coverage matrix, direct/fallback reason, correctness,
latency p50/p95, and coordinate/permission state.

Likely files are the second platform module, common coordinator only for proven
shared behavior, platform permission/config handling, and native/fallback tests.

A future DOM extension remains a design-compatible consumer of the Wave 4
selection contract. Wave 6 may produce a scoped extension proposal and evidence;
it does not automatically authorize extension implementation or a local service.

Completion requires a cross-platform fallback matrix and separate native
latency/accuracy evidence. It must not weaken OCR fallback or run both native
implementations on the same OS.

**Risks:** premature common abstraction, platform-specific coordinates leaking
into the engine, and treating browser accessibility as universal DOM access.
**Must not change:** the validated first-platform behavior, dictionary-miss
policy, or future DOM transport without separate authorization.

## 11. Wave 7 — optional OCR alternatives / HanlyOCR

This is a future research bundle, not a fallback for unresolved shared-pipeline
defects. It uses the Wave 2 corpus, metrics, run storage, and staged comparison
format. Any candidate is evaluated one at a time for:

- target-word correctness;
- detection and recognition accuracy;
- cold/warm p50/p95;
- steady and peak RSS;
- model/package size;
- cross-platform availability and licensing.

**Likely files:** `benchmarks/dev` candidate adapters/runners, corpus manifests,
raw run artifacts, HAN-33 research documentation, and no production composition
unless a later human decision explicitly promotes a candidate.
**Dependencies:** accepted Wave 2 methodology, resolved shared-pipeline defects,
and separate HAN-33 authorization.
**Tests:** adapter isolation, metric comparability, resource cleanup, licensing
metadata, and unchanged reference-corpus scoring.
**Manual validation:** inspect representative successes and failures rather than
accepting aggregate accuracy alone.
**Evidence:** per-candidate raw outputs, accuracy, latency, RSS, package/model
size, environment, and failure-class comparison.

Likely files stay under `benchmarks/dev` and the existing future HAN-33 research
scope until a human approves a product provider. No PaddleOCR is restored, no
backend is promoted from a single machine, and no production selector changes
inside the research bundle.

**Risks:** benchmark overfitting, incomparable preprocessing, hidden model
licensing/distribution costs, and two heavy resident engines.
**Completion:** a reproducible recommendation or an explicit decision to change
nothing, followed by a Review Handoff.
**Must not change:** shipped backend selection, resource provisioning, or package
composition during research.

## 12. Dependency graph

```text
W1.0 trace parity
  + W1.1 capture evidence
  + W1.2 gate/cache evidence
  + W1.4 resolver/language evidence
  + W1.5 retained-target evidence
      -> W1.6 in-memory freeze + explicit export + inspector

W1.3 staged EasyOCR ------------------┘
      -> W1.7 trustworthy frozen lookup checkpoint
      -> W2.0 corpus contract
      -> W2.1 synthetic fixtures
      -> W2.2 OCR modes
      -> W2.3 metrics
      -> W2.4 latency/RSS
      -> W2.5 baseline report
      -> W2.6 Review Handoff and STOP

Waves 1-2 evidence -> select exactly one Wave 3 correction
Wave 3 evidence/stability + architecture approval -> Wave 4
Wave 4 -> Wave 5 one platform -> Wave 6 second platform/browser evaluation
Wave 2 corpus may later feed Wave 7 independently; Wave 7 never blocks V1.
```

## 13. Intended reviewable change boundaries

These are intended commit boundaries for human use; this plan does not authorize
the agent to commit:

1. `fix: preserve lookup semantics under tracing`
2. `chore: trace production capture gate and cache decisions`
3. `chore: expose resolver and retained-target evidence`
4. `feat: freeze and inspect one real lookup`
5. `feat: add staged EasyOCR diagnostic evidence`
6. `test: add the OCR corpus contract and synthetic fixtures`
7. `feat: add OCR-only detection and recognition campaigns`
8. `docs: record the reproducible text-acquisition baseline`

If implementation shows two boundaries are inseparable, record why in the
checkpoint. Do not force mechanical commits that split a working contract from
its tests.

## 14. Validation matrix

Automated evidence is necessary but cannot establish native coordinate
correctness. The durable report carries this matrix and marks each cell
`measured`, `not available`, or `not yet run`:

| Platform/configuration | Capture geometry | Cursor alignment | Freeze | OCR stages | DPI/external display |
|---|---|---|---|---|---|
| macOS Retina | required where available | required | required | Vision live; EasyOCR explicit | required |
| macOS external display | when available | when available | when available | provider as configured | when available |
| Windows 100% | required before broad claim | required | required | EasyOCR | required |
| Windows 125% | required before broad claim | required | required | EasyOCR | required |
| Windows 150% | required before broad claim | required | required | EasyOCR | required |
| Windows mixed DPI | when available | required before mixed-DPI claim | required | EasyOCR | required |

Linux remains supported by the pixel architecture but is not silently claimed
from macOS/Windows evidence.

## 15. Limit monitoring, pause, and raw-agent continuation

At the start of each authorized bundle and after each meaningful wave boundary,
read current Codex usage limits. `usedPercent` is consumption, so remaining
capacity is `100 - usedPercent`. The executor does not spend a reset credit
without explicit human authorization.

When the active window or weekly capacity becomes too small to complete the next
coherent task plus checkpoint safely, stop before starting that task. Update the
single checkpoint with:

- authorized bundle and current task ID;
- completed behavior and files touched;
- tests/gates and exact results;
- evidence run directories and privacy state;
- unresolved failures or architecture decisions;
- Linear state and blockers;
- working-tree limitations, including unavailable Git tooling;
- exact next command/action;
- current limit percentages and reset times.

If implementation has reached its authorized convergence boundary, write the
Review Handoff and stop. If it has not, the checkpoint is the continuation
artifact; do not mislabel partial work as review-ready and do not create a
second ad-hoc handoff.

## 16. Planning-time environment limitations

- Git commands were blocked during planning and Bundle A implementation by the
  unaccepted local Xcode licence, so those runs could not assert branch status
  or inspect a Git diff. The licence blocker was cleared by 2026-09-21 and Git
  is available for subsequent review; this historical limitation still applies
  to claims made by the original runs.
- Current source and some architecture/execution prose disagree about Apple
  Vision and previously claimed capture/geometry work. Implementation must use
  the live source as executable state while treating authoritative architecture
  changes as human-governed.
- No real failing ROI accompanied the original planning request. The later
  human-operated run recorded in §7 supplied two; synthetic input was not used
  to fabricate their classification.

## 17. Planning completion criteria

This plan is complete when it provides:

- bounded implementation tasks with files, seams, contracts, tests, manual
  validation, evidence, dependencies, risks, exit criteria, and exclusions;
- a clear distinction between instrumentation-only and behavioral work;
- one immediate Waves 1-2 bundle ending at a Review Handoff;
- evidence gates before Wave 3, architecture approval before Wave 4, and one
  platform at a time in Waves 5-6;
- local-only in-memory-freeze and explicit-export privacy rules;
- a durable limit-aware pause/resume procedure without duplicate artifacts.

Creating this plan does not satisfy any implementation exit criterion and does
not authorize Linear mutation, architecture edits, commits, pushes, merges,
releases, Phase B review, or the next bundle.
