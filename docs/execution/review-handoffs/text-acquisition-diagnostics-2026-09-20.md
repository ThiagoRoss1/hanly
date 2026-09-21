# Text acquisition diagnostics (Bundle A) Review Handoff

## Bundle

- Member issues: none. This ran from
  `docs/execution/plans/text-acquisition-diagnostic-microscope-2026-09-20.md`,
  Part 1 (Waves 1–2), authorized directly by the human. The plan notes the work
  belongs closest to HAN-35, which is `Backlog` and blocked by HAN-32; **no
  Linear state was created or changed**, and none should be until a genuinely
  `READY` representation exists.
- Implementation ecosystem: Claude Opus 5, single implementation run.
- Date: 2026-09-20 to 2026-09-21.
- Live ledger:
  `docs/execution/checkpoints/text-acquisition-diagnostics-2026-09-20.md`
- Measured baseline:
  `docs/execution/reports/text-acquisition-diagnostic-baseline.md`

## Implemented

**Wave 1 — observability integrity and the microscope**

- Traced and untraced lookup are now semantically identical: `_TracingResolver`
  forwards `resolve_target_detail`, which it previously dropped.
- `CapturePlan` on `CaptureResult` reports the exact ideal / snapped / actual
  rectangles, monitor, clip bounds, clamping, clipped edges and target edge
  distances behind one ROI.
- A `CaptureObserver` seam on the hover and manual paths hands a completed
  capture to a developer tool, correlated by request identifier.
- `_GateMeasurement` replaces the boolean gate calculation; `_OCRPathObserver`
  reports gate, OCR cache and provider execution as one decision chain.
- `ResolutionEvidence` explains a target resolution from the same computation
  that performs it; morphology, dictionary and normalized OCR evidence travel
  with it.
- `retained_target` / `retained_target_cleared` record both coordinate spaces
  and the transform between them; `popup_suppressed` now exists.
- `benchmarks/dev/easyocr_stages.py` reproduces `Reader.readtext` stage by
  stage, retaining the exact recognizer crops, with live-versus-replay
  comparison.
- `benchmarks/dev/frozen_lookup.py` and `benchmarks/dev/microscope.py` pin one
  completed lookup in memory, render it as labelled layers, and export it only
  on an explicit action.
- `live-hover` gained `--freeze-hotkey` and `--export-hotkey`; `--retain-text`
  was **removed**.

**Wave 2 — corpus and repeatable evaluation**

- `benchmarks/dev/corpus.py`: a versioned manifest that declares whether it is
  committed or local, and enforces the difference.
- `benchmarks/dev/synthetic_ocr.py`: a generator that refuses to substitute a
  missing face, refuses text a face has no glyphs for, and marks samples from a
  non-redistributable face as local-only.
- `benchmarks/dev/ocr_metrics.py`: exact match, CER, Hangul SER, false-empty,
  detection precision/recall at a declared IoU, target-region recall,
  target-surface correctness, repeated-input variance, gate false-negative rate.
- `benchmarks/dev/ocr_benchmark.py` and three new CLI commands: `ocr-campaign`
  (`ocr-only`, `detection-only`, `recognition-only`, `frozen-replay`),
  `ocr-corpus`, `ocr-corpus-generate`.

## Main expected behavior

Enabling tracing cannot change a lookup's answer. A developer can freeze one
completed lookup, inspect its pixels, geometry, decisions and outputs after the
pointer has moved, and export it deliberately. OCR can be scored and timed on a
corpus without constructing Kiwi, KRDICT, `LookupPipeline`, hover or UI.

Normal desktop behaviour is unchanged. Everything added to `packages/` is
instrumentation that is constructed only when a trace sink is attached, plus one
descriptive value on `CaptureResult`.

## Architecture / seams touched

- `CA-INV-09`, `RF-INV-05`: no library object crosses a provider seam. The
  staged EasyOCR runner lives in `benchmarks/dev` and converts every
  intermediate image to plain bytes.
- `RF-INV-11` / `CA-INV-14`: bounded latest-wins execution and the final
  request-currency check are untouched. `popup_suppressed` is a new observation
  of an existing decision, not a new decision.
- `CA-INV-02`: `hanly` still imports nothing from `hanly-app`.
- The `TargetResolver` seam: `WordResolver` gained `resolve_target_evidence`.
  `resolve_target`, `resolve_target_detail` and `resolve` now all route through
  one `_resolve` computation, so they cannot disagree.
- `hanly.easyocr_provider` gained two pure helpers (`easyocr_image_from_roi`,
  `normalize_easyocr_results`) so the benchmark cannot duplicate normalization.
  Neither is added to the `hanly` package's top-level exports.
- `LookupSettings` gained `trace_evidence`, carried across the spawn boundary.
- **No public `hanly` contract was extended for diagnostics.**
  `ResolutionEvidence` and `CandidateEvidence` live in `word_resolver` and are
  not exported from `hanly/__init__.py`.

## Relevant files / diff areas

Engine: `packages/hanly/src/hanly/word_resolver.py`,
`easyocr_provider.py`.

App: `packages/hanly-app/src/hanly_app/capture.py`, `composition.py`,
`hover_lookup.py`, `manual_lookup.py`, `hover_target.py`, `lookup_process.py`,
`lookup_evidence.py` (new), `__init__.py`.

Benchmarks: `benchmarks/dev/{easyocr_stages,frozen_lookup,microscope,corpus,synthetic_ocr,ocr_metrics,ocr_benchmark}.py`
(new), `live_runner.py`, `cli.py`, `hud/session.py`, `README.md`.

Fixtures: `benchmarks/fixtures/ocr/{manifest.json,generator.json,README.md}`
(new).

Tests: `tests/{test_lookup_evidence,test_retained_target_evidence}.py` (new),
`tests/{test_app_composition,test_capture,test_hover_lookup,test_manual_lookup,test_lookup_process}.py`,
`benchmarks/dev/tests/{test_easyocr_stages,test_microscope,test_corpus,test_synthetic_ocr,test_ocr_metrics,test_ocr_benchmark,test_hud_session}.py`
(new), `benchmarks/dev/tests/{test_live_runner,test_cli}.py`.

**Git was unusable during the implementation run** because the Xcode licence was
unaccepted. It is usable as of 2026-09-21: `git status --short --branch` succeeds
on `visual/interface-update`, so Phase B can review a diff. The worktree contains
other Hanly bundle changes as well; use this handoff's file list and acceptance
boundary to scope attribution. Nothing was committed.

## Implementation-side validation already run

| Check | Result |
|---|---|
| `.venv/bin/python -m pytest` | 1895 passed, 2 skipped (baseline before this run: 1701 passed, 2 skipped) |
| `.venv/bin/python -m pytest --suite portable` | 1825 passed, 2 skipped |
| `.venv/bin/python -m ruff check packages packaging tests tools benchmarks` | All checks passed |
| `.venv/bin/python -m mypy packages packaging tests tools benchmarks` | Success, 267 source files |
| Real frozen hover, macOS | captured, complete, `missing=[]` — see below |
| Explicit staged EasyOCR replay | ran, diverged from live, divergence surfaced |
| Four OCR campaigns over an 8-case corpus | ran, 160 passes, 0 errors |
| Human-operated `live-hover`, macOS | 10 completed; 8 visible successes, 2 suppressed real failures; real freeze/export hotkeys exercised |

The W1.0 parity fixtures were confirmed to **fail** against the pre-fix wrapper
(3 failures) and pass after it, so they guard the defect rather than describing
the new code.

### Was a real failing hover captured and classified?

**Yes.** Human-operated run
`artifacts/benchmarks/runs/ef2c1ffc-3746-4b94-a40a-680b7e9e29c3/` captured two
silent failures as `frozen-9` and `frozen-10`. Both exported ROIs visibly contain
Korean under the recorded cursor. The gate ran and passed, the OCR cache missed,
and live production Vision executed, but normalized output contained only nearby
number markers and zero Hangul regions. Resolution consequently reported
`no_candidate_contains_target`; morphology and dictionary were not reached and
the popup correctly suppressed `UNUSABLE`.

The failure first appears at the **live production OCR-output stage**. It is not
a gate, resolver, morphology, dictionary, or presentation defect. The record
does not yet distinguish Vision detection from recognition, and both longer UI
lines continue beyond the fixed 200x100 ROI even though the ROI is not clipped
by the monitor. A single controlled same-case model-input/context comparison is
required before choosing the Wave 3 correction family.

The earlier EasyOCR recognition failure remains separately classified comparison
evidence. No EasyOCR replay is attached to the new production failures, and no
replay result is attributed to their live Vision invocation.

The successful glued-word captures are also separate: live OCR is correct and
cursor mapping selects Kiwi candidates by position. `초대받았어요` is analyzed
as `초대` plus `받다`, while KRDICT has no `초대받다` lemma. A different whole-
compound answer would require an explicit language/dictionary policy decision;
it must not be folded into the pixel-path correction.

Three defects in this bundle's own work were found by running it for real rather
than by a test, and are worth a reviewer's attention as a pattern:

1. `_ChildTraceSink` had no `retain_evidence`, so a real desktop launch would
   have emitted no private evidence at all. Fixed by `LookupSettings.trace_evidence`.
2. `ocr_evidence` was missing from the redaction list and leaked recognized text
   into a persisted trace file. Fixed, and the rule made structural (any field
   ending `_evidence` is stripped) with a test for a hypothetical future field.
3. `detection-only` scored transcription metrics it deliberately does not
   produce, reporting a character error rate of 1.00 for a transcription never
   attempted. Fixed to report `not_applicable`.

## Known limitations / intentionally unvalidated areas

- **Wave 3 causal choice remains open.** A real repeated OCR-output failure now
  exists, but Vision's private detector/recognizer boundary and the truncated
  surrounding line cannot be separated from the current exports alone. Do not
  choose a correction before the one-variable comparison described above.
- **The committed corpus is empty.** Every number in the baseline report §4 came
  from `local_synthetic` samples rendered from a proprietary font on this
  machine and cannot be reproduced elsewhere from Git alone. Installing Noto
  Sans KR and running `ocr-corpus-generate` fixes this.
- **macOS only.** No Windows machine and no external display. Every DPI row of
  the validation matrix is `not available`, not simulated.
- **Current RSS unavailable** (`psutil` not installed). Only peak RSS is
  measured; the code reports the gap rather than reporting zero.
- **No annotated regions** in the scored corpus, so detection precision and
  recall are `not_applicable` there. The live failures prove omission at the
  normalized OCR-output boundary, not a provider-internal detector metric.
- **Gate false-negative rate is implemented but never exercised** against real
  gate observations; no campaign yet pairs them with known-text ROIs.
- The staged EasyOCR runner is **pinned to EasyOCR 1.7.2** and reproduces
  `Reader.readtext`'s body. It verifies the API shape and fails loudly, but an
  upgrade will need it revisited.
- `MicroscopeCaptureObserver` retains ROI bytes by reference in a bounded ring
  (24 entries, ~60 KB each at production size). Not exercised under sustained
  hover for a long session.
- The `_resolve` refactor in `word_resolver.py` is the highest-risk change to
  shipped behaviour in this bundle: three public methods now share one
  implementation. Existing resolver tests all pass unchanged, and the parity
  fixtures cover the traced path, but this is where a subtle regression would
  live.

## Suggested review targets

- `WordResolver._resolve` and `_judged_candidates` against the previous
  `resolve_target`: the tie-break index changed from a position within the hits
  list to a position within the full results list. Provider order is preserved
  so the winner should be identical; worth confirming.
- `_traced_resolver`'s contract-matching: a substituted pair-only resolver must
  not gain pointer-offset semantics under tracing.
- `MicroscopeSink._persistable` and `_is_private_evidence`: the privacy boundary
  is one predicate, and the leak found in this bundle went through it.
- `export_frozen`'s `_validated_destination`: path containment is the only thing
  stopping private screen content leaving the gitignored root.
- `LookupRing._record_for`: identifier merging when a hover id and a lookup id
  first arrive together. Eviction interacting with a merge is the case worth
  poking at.
- `_missing` / `_last_stage_reached` in `frozen_lookup.py`: the not-reached
  versus skipped versus absent distinction is newer than the rest.
- `CapturePlan` construction inside `capture_at_cursor`: it is built on every
  capture, including in the shipped path with no trace sink. It is pure integer
  arithmetic over values already computed, but it is on the hover path.
- Whether `benchmarks/fixtures/ocr/manifest.json` being committed-but-empty is
  the right call, versus not committing it until it has cases.

## Review assignment

Human-selected after implementation. Not started. The updated evidence makes a
diff-based Phase B review possible; that review remains a separate run and does
not itself authorize Wave 3 or collapse the later bundle handoffs.

---

## Post-Bundle Review Outcome

- Reviewer: Claude Opus 5
- Review ecosystem: Phase B deep review, single run, `.venv` on macOS 26.6.2 arm64
- Date: 2026-09-21
- Status: **Approved with deferred findings.** Wave 3 stays gated on the
  one-variable comparison this bundle already identified, now further
  constrained by findings 6 and 7 below.

**Scope.** The worktree is dirty with several bundles. Attribution used this
handoff's file list plus `git diff` against `f9514d4`. Note that
`TargetResolution`, `resolve_target_detail`, `LexicalCandidate` and
`MorphologyAnalysis` do **not** exist at HEAD — they belong to a different
uncommitted bundle that Bundle A built on top of. `contracts.py`,
`lookup_pipeline.py`, `kiwi_provider.py`, `krdict_provider.py`, `qt_popup.py`,
`popup.py`, `runtime.py`, `config.py`, `application.py`, `control_center*` and
their tests were treated as out of scope and not reviewed.

### Evidence conclusion: confirmed

Every claim in the stated conclusion was checked against
`artifacts/benchmarks/runs/ef2c1ffc-3746-4b94-a40a-680b7e9e29c3/`, and each is
**confirmed**. The stronger checks were independent recomputation rather than
re-reading the record:

| Claim | How it was confirmed |
|---|---|
| Gate passed | Re-ran `_measure_text_presence` on the exported pixels. frozen-9 and frozen-10 reproduce `passed=True`, 8 transitions, 1 row, 17/12 columns — identical to the recorded values. |
| OCR cache missed | Recomputed `blake2b` over the exported PNG: fingerprints match the recorded ones exactly, which also proves **the export is byte-identical to what OCR saw**. All 8 frozen ROIs have distinct fingerprints, so no cache hit was possible. |
| Production Vision executed | `resources/dev/runtime-local.json` parses to `AUTO`; `resolved_ocr_backend()` returns `VISION` on this machine. True — but see finding 4: no artifact records it. |
| Korean pixels under the cursor | Inspected both exported ROIs at 4× with the recorded ROI-local cursor drawn on. frozen-9's cursor sits on `았` in `초대받았어요`; frozen-10's on `렸` in `떨어뜨렸어요`. Unambiguous. |
| Normalized OCR omitted all Hangul | `hangul_region_count=0`, `hangul_char_count=0`; only `6. 7. 8.` and `1. 2.` returned. |
| Resolution had no candidate | `no_candidate_contains_target`, `selected_index=None`, and all recorded candidates have `contains_target=False`. |
| Morphology and dictionary not reached | `missing` names both as `not reached; the lookup ended earlier` — correctly distinguished from absent evidence. |
| Popup correctly suppressed | `popup_suppressed` with `UNUSABLE`, which is not in `_PRESENTED_STATUSES`. |
| Failure enters at the production OCR-output boundary | Capture geometry recomputes exactly, the gate reproduces, the cache missed, the provider executed, and the resolver behaved correctly given what it was handed. Nothing upstream is implicated. |
| Evidence does not yet distinguish the causes | Confirmed, and **understated** — see findings 6 and 7. |

Capture geometry was recomputed from first principles for both failures: ideal
rectangle, grid snap, ROI-local target and all four edge distances match the
recorded plan exactly.

The privacy boundary was confirmed empirically on the real 300-second session:
`live-events.jsonl` holds 738 events, **zero** Hangul characters, **zero**
`*_evidence` fields, and no text-bearing keys. `stdout.log` shows
`export: nothing is frozen; press the freeze hotkey first` before any freeze,
so freeze and export are genuinely separate acts.

### Fixed now

1. **Ring eviction could unregister a live record.** `LookupRing._evict` popped
   an evicted record's identifiers unconditionally. When two records claim one
   lookup id — a lookup-only event arriving before the hover record that later
   adopts it — evicting the orphan removed the *live* record's index entry, and
   the next lookup-only event started a third record. `freeze()` then returned a
   record holding only `popup_visible`: no capture, no OCR, no resolution, which
   reads as a capture failure that never happened. Now an index entry is dropped
   only when it still points at the record being evicted. Latent, not active:
   the production event order always carries both identifiers on the first
   lookup-bearing event, verified against the real 738-event trace. Regression
   test added.

2. **A committed manifest could reference a private capture.** `_case_image`
   checked only `Path.is_absolute()`, which on POSIX is false for Windows
   absolute paths, UNC paths and `~`-relative paths — precisely the paths that
   carry someone's user name. Worse, `../` traversal was unchecked: I
   demonstrated a committed manifest accepting the real `frozen-9/input.png`
   from the gitignored artifact root as a `committed_fixture` with
   `is_private=False`, passing the asset-existence check because the file
   genuinely exists. A committed manifest's images must now stay inside the
   manifest's own directory tree and may not name one machine. Local manifests
   are deliberately unaffected. This is the input-side counterpart of the
   containment `export_frozen` already had. Regression tests added.

3. **A corrupted `selected_index` wrapped.** `_selected_layer` rejected an index
   past the end but not a negative one, so decoded evidence with `-1` presented
   the *last* candidate as selected. Decoded evidence is untrusted by the
   module's own contract. Guarded; parametrized test added.

All three are cheap defensive hardening at a boundary, all in `benchmarks/dev`,
and none changes shipped desktop behaviour.

### Deferred considerations

4. **No exported artifact names the OCR backend.** Neither the frozen
   `metadata.json`, `diagnostic.json`, nor the run `metadata.json` records the
   resolved recognizer. "Production Vision executed" is true, but only
   verifiable by re-running `load_runtime` against today's config — inference,
   in a system built to answer without it. W1.0 asked for "a provider/config
   header in every diagnostic run"; the config half landed, the resolved
   provider half did not. **Revisit before the Wave 3 one-variable comparison**,
   whose entire value depends on attributing behaviour to a named backend.

5. **`summary.json` mislabels a counter.** `frozen_lookups_exported` is
   `len(frozen_holder)`, which accumulates on *freeze*. The session reports 9
   against 8 actual export directories; `stdout.log` shows nine freezes and
   eight distinct exports, one re-export, and one freeze never exported. The
   ground truth is preserved in the log, so nothing is lost — but the field name
   asserts the opposite of what it counts, in the one place the plan insists the
   two acts differ. **Revisit when a run summary is next used as evidence for
   anything beyond a smoke check.**

6. **The failure is script-independent, not Hangul-specific.** The handoff and
   the baseline report both describe it as "normalized OCR omitted all Hangul
   regions". True, but incomplete in a way that matters. A row-ink profile of
   frozen-10 shows five bands carrying glyphs; Vision reported only two, and the
   omitted set includes the complete, unclipped **Latin** line `do Hanly:` at
   rows 17–27. Everything Vision returned across both failures is a short bold
   left-margin numeral; everything it dropped is proportional body text, Korean
   or Latin. A Korean-recognition hypothesis is therefore not supported by this
   evidence. **Revisit before Wave 3 selects a task family** — this rules a
   candidate family out and adds one the handoff does not name.

7. **Right-edge truncation is present in a success too.** The handoff leans
   towards truncated surrounding-line context, noting both failing lines
   continue past the 200×100 ROI. But frozen-8 **succeeded** on three Hangul
   regions that also run to the ROI edge (x=66–198 of 200) and were read
   correctly. Truncation is common to the successes and the failures, so it
   cannot by itself be the discriminator. The nearer difference between
   frozen-8 and frozen-9 is a 32 px horizontal and 64 px vertical ROI shift, and
   frozen-9 additionally carries a clipped partial line at the ROI *top* that
   frozen-8 lacks. **Revisit at the same trigger as finding 6**; the one-variable
   comparison should vary ROI offset and leading/trailing partial lines, not
   only line length.

8. **`hanly.__all__` lists `TargetResolution` twice.** Harmless, and it belongs
   to the other uncommitted bundle, not Bundle A. **Revisit when that bundle is
   reviewed.**

### Dismissed

9. **The `_resolve` refactor risk, which this handoff flagged as the highest.**
   Dismissed on evidence: a differential harness ran the current
   `resolve_target` against the committed HEAD implementation over 100,000
   randomized cases — 40,000 general (2,420 producing real hits, including
   malformed sequence members and negative desktop origins) and 60,000
   constructed to force overlapping quads, of which **51,140 exercised the
   multi-hit tie-break** the handoff singled out. **Zero mismatches.** The
   tie-break index change from hits-position to results-position is provably
   harmless because `hits` preserves the order of `results`, so the argmin is
   identical.

10. **Committed-but-empty `manifest.json`.** The handoff asked whether this was
    the right call. It is: the manifest carries the contract and the reason, the
    loader validates it, and a test asserts it stays valid. Not committing it
    would make the absence undiscoverable.

11. **`CapturePlan` on the hover path.** Confirmed to be pure integer arithmetic
    over values `capture_at_cursor` already computes, retaining no pixels. No
    action.

### Checks run during this review

| Check | Result |
|---|---|
| Resolver differential vs HEAD, 100 000 cases | 0 mismatches |
| Export containment probes (traversal, absolute, symlink, prefix-confusion) | all refused; only the root and genuine nesting allowed |
| Malformed evidence probes (truncated, wrong version, wrong types, missing fields) | nothing raised; layers report unavailable with reasons; HTML still renders |
| Capture geometry + gate recomputed from exported pixels | exact match on both failures |
| Bundle A focused suite | 477 passed |
| `.venv/bin/python -m pytest` | **1907 passed, 2 skipped** |
| `.venv/bin/python -m ruff check packages packaging tests tools benchmarks` | All checks passed |
| `.venv/bin/python -m mypy packages packaging tests tools benchmarks` | Success, 267 source files |

### Verdict

**Approved with deferred findings.**

Bundle A does what it was authorized to do. Its evidence conclusion is confirmed
in full, including by independent recomputation of the gate and capture geometry
from the exported pixels, and the privacy boundary holds empirically across a
real 738-event session. The three defects found were latent rather than active
and are fixed.

This approval does **not** authorize Wave 3. The evidence gate remains what this
bundle already stated: one controlled same-case comparison, still required.
Findings 6 and 7 change what that comparison must vary — the omission is not
Korean-specific, and right-edge truncation is shared with a success — so a Wave 3
task family selected against the current narrative would likely chase the wrong
variable. Finding 4 should land first so that comparison can name its backend.
