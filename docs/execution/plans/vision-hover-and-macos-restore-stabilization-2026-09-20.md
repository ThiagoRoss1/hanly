# Vision hover and macOS restore stabilization plan

**Status:** investigated and proposed; implementation is not authorized by this document.
**Branch context:** `visual/interface-update`, after the 2026-09-19 Bundle A implementation and post-bundle review. Git state is not asserted because the local Xcode licence currently prevents git from running.
**Scope:** stabilize word ownership while Apple Vision is active, finish the one-attempt clipping recovery that A5 left unwired, and make the existing Control Center reliably return from the Dock without replacing its process or state.
**Exclusions:** Bundle B visual reference matching, HTML popup rendering, custom listboxes, general animation polish, Windows title-bar work, the AppKit/Liquid Glass port, phrase lookup, dictionary-backed OCR guessing, and broad OCR-model research.
**Authority:** this is a proposed Phase A fix specification. It does not authorize implementation, architecture approval, Linear mutation, commits, pushes, merges, releases, or Bundle B. An authorized implementation ends at one Review Handoff and stops; deep review is a separate human-authorized run.

## MUST ACT — Maintain one live checkpoint

An authorized executor must create and update:

`docs/execution/checkpoints/vision-hover-and-macos-restore-stabilization-2026-09-20.md`

Write an entry when a material decision is made, not reconstructed at the end.
Each entry states only:

1. **Decision:** what was chosen.
2. **Why:** the evidence or constraint behind it.
3. **Still unverified:** missing native evidence or uncertainty.

Before pausing, record the active work package, touched files, checks already run,
and the exact next action. Never mark hover stability or window restoration
complete from mocks, offscreen Qt, synthetic OCR alone, or arithmetic alone.

## 1. Evidence and observed failures

### 1.1 Real hover recording

The 72.9-second macOS recording from 2026-09-19 is the first direct native
evidence for this path. Apple Vision is selected in the Control Center.

- Around 19–35 seconds, the visible `떨어뜨렸어요` produces several different
  recognized surfaces as the pointer moves by small amounts. The popup moves
  through `떨어드리다`, the correct `떨어뜨리다 · drop`, unrelated results such
  as `당` and `뛰다`, then `Too unclear`.
- `예뻤어요` succeeds around 43 seconds.
- `사과했어요` first resolves to `하다`, then correctly to `사과하다`.
- `친구들이` reports not found even though intact text should yield `친구`.
- `공부하려고` succeeds as `공부하다`.

The popup's recognized surface changes with the answer. That makes OCR/capture
instability the primary cause of the bizarre lemma changes; it is not evidence
that Kiwi splits an intact `떨어뜨렸어요` into those unrelated lemmas.

The same recording shows the Control Center loading, being minimized, and
remaining unavailable after the user clicks the running `python3.13`/Hanly Dock
item. The child stays alive and capture continues.

### 1.2 Perfect-text morphology control

The current `KiwiProvider` was probed with intact strings. Every character of
each predicate is owned by one complete candidate:

| Surface | Candidate from intact text |
|---|---|
| 떨어뜨렸어요 | 떨어뜨리다 |
| 예뻤어요 | 예쁘다 |
| 사과했어요 | 사과하다 |
| 친구들이 | 친구 |
| 공부하려고 | 공부하다 |

The unexplained `친구들이` live failure remains an explicit investigation item:
the trace must determine whether Vision returned a visually similar character,
the target mapper selected another span, or the running build differed from the
inspected source.

### 1.3 Capture and retention behavior

- `CaptureService` defaults to a 200×100 cursor-centred ROI.
- Production uses `DEFAULT_ROI_GRID = 32`. Nearby positions reuse one ROI, but
  crossing a grid boundary shifts the entire input by 32 pixels and changes the
  left/right context Vision receives.
- The OCR cache reuses only byte-identical images.
- Hover is debounced at 80 ms. Once the cursor leaves the retained estimated
  word rectangle, another capture and lookup can replace the popup.
- `WordResolver` estimates character positions from script advance weights.
  Mixed Hangul, arrows and Latin translation can therefore drift from the
  actual glyph geometry.

The likely failure chain is: approximate retained bounds release the word,
cursor movement crosses an ROI grid boundary, Vision receives a shifted crop,
and a new recognized surface replaces the previous result.

### 1.4 Incomplete clipping recovery

`hanly_app/capture_recovery.py` contains tested helpers for edge detection,
monitor-constrained widening and cursor reprojection. No production module
imports them. A5 therefore has unit evidence for calculations but no live
recapture-and-resubmit behavior.

This recovery remains deliberately narrow: it can recover a clipped line or
word, not a fully visible misrecognition. Confidence alone is not a retry or
truth signal.

### 1.5 Vision normalization gap

`VisionProvider` requests only `topCandidates_(1)` and normalizes
`observation.boundingBox()`. It does not preserve the observation quadrilateral
or provider-supplied geometry for a substring. The engine consequently falls
back to estimated character advances even when Vision can supply more precise
native geometry.

No Objective-C or Vision object may cross the OCR provider seam. Any added
geometry must be immutable, provider-neutral engine data, and EasyOCR must keep
working without it.

### 1.6 Control Center restore root cause

`ControlCenterHost.show()` calls `_restore_if_minimized()`, but that helper
returns without restoring when `window.minimized is False`. In pywebview 6.2.1,
that attribute is the window's construction option; the Qt backend emits native
minimized/restored events without updating it. The real minimized window can
therefore still report `False` and skip `restore()`.

The focused tests pass because their fake window manually changes
`window.minimized`, which does not model pywebview's behavior. The Dock click in
the recording also shows that application reactivation is not reliably routed
to `DesktopApplication.open_control_center()`.

### 1.7 Investigation limitations

- The recording supplies native behavioral evidence, but no structured trace
  was captured alongside it.
- Direct Vision execution from the current Codex process returned no
  observations, likely because of the sandbox/native process context. That is
  not treated as evidence that the running application cannot use Vision.
- The Xcode licence blocks git, the compiler-backed native update tests, and
  some native tooling. Do not convert those environmental failures into product
  conclusions.
- A focused mocked/unit set passed 69 tests after the investigation. That pass
  demonstrates the tests do not cover the observed native failures.

## 2. Design decisions that are not to be re-litigated

1. OCR produces regions, strings, confidence and optional geometry. The extent
   of a recognized word is an OCR output, not an input. “Expand to the whole
   word, then recognize it” is not a valid operation order.
2. The intended order is: capture stable context, recognize it, resolve the
   pointer to a text/lexical span, then retain and reuse that result while the
   pointer remains within the same word.
3. ROI stability and target ownership are corrected before tuning Vision
   thresholds, enabling language correction, or ranking alternate candidates.
4. A shifted crop may legitimately change OCR output, but a few millimetres of
   movement inside one visible word must not continuously feed shifted crops to
   the recognizer.
5. Edge-triggered recapture remains one additional attempt per request. It does
   not become a generic retry loop or a dictionary-backed spelling correction.
6. Screen capture and monitor constraints stay in `hanly-app`; the engine
   receives images and normalized coordinates, never screen access.
7. Request currency remains the presentation correctness gate. Cached OCR and
   recovery work must never let stale results replace the current request.
8. The engine remains independent of Vision and pywebview. Provider and native
   framework objects are normalized inside their adapters.
9. Phrase lookup is separate future span policy. This bundle selects stable
   lexical units; it does not add phrase recognition.
10. Restoring the Control Center reuses the existing child, page, settings,
    bridge and capture state. Recreating the child is not an acceptable restore.

## 3. Work packages and dependency order

```text
S0 diagnostic trace and offset fixture
 ├─ S2 stable capture ownership
 ├─ S3 Vision geometry normalization
 └─ S4 clipping recovery wiring (after S2 fixes the primary flow)

S1 native macOS restore is independent

S0 + S1 + S2 + S3 + S4
 └─ S5 convergence, native acceptance, documentation and handoff
```

S1 may proceed independently. S0 precedes behavioral tuning so the executor can
explain each transition rather than infer it from the popup. S2 establishes the
normal capture lifecycle before S4 adds its one exceptional recapture. S3 can
develop beside S2, but both converge on one retained target representation.

### S0 — Trace the complete lookup decision

**Primary areas:** `hanly_app/{runtime_trace,capture,hover_lookup,lookup_controller,lookup_process}.py`, engine lookup diagnostics, and development-only fixture/trace tests.

- Extend the existing opt-in trace to correlate one hover request across the
  shell and lookup child.
- Record the concrete OCR backend, screen-space ROI, grid key, ROI-local target,
  recovery-attempt number, OCR observation geometry/confidence, selected
  recognized span, character index, lexical candidate and final status.
- Do not log screen pixels or recognized text by default. If either is needed
  for a developer capture, require an explicit privacy-sensitive diagnostic
  option and keep it out of normal logs.
- Add a deterministic offset fixture that presents the same Korean line at
  several cursor positions and crop origins. It must expose recognition churn;
  it must not fake the desired final lemma.
- Use the trace to classify the `친구들이` failure before changing candidate
  policy.

**Done:** one correlated trace can explain why each popup transition occurred,
and the fixture can compare repeated observations of one unchanged source word.

### S1 — Restore the Control Center through every supported macOS reopen route

**Primary areas:** `hanly_app/{control_center_host,control_center_process,application,app_identity_darwin}.py` and focused host/process/native macOS tests.

- Remove correctness dependence on `window.minimized` as live state. When a
  focus request reaches a live window, call public `restore()` when available,
  then `show()`, raise/activate the native application, and update only
  host-owned visibility state.
- Prefer unconditional idempotent restore over duplicating backend state. Add a
  backend-specific state tracker only if native evidence proves unconditional
  restore harmful.
- Route macOS application/Dock reopen to the existing
  `DesktopApplication.open_control_center()` path. Do not create another entry
  point, child, Dock tile or bridge.
- Change the fake to model pywebview: minimizing the native window does not
  mutate the constructor's `window.minimized` value.
- Add a real macOS exercise: open, change page state, minimize, reactivate from
  the Dock/application route, and repeat three times. Record child PID or
  generation, page state and native minimized state.

**Done:** all three cycles return the same visible child with the same page and
capture state, and no duplicate child or Dock identity appears.

### S2 — Keep one stable OCR context while the pointer owns a word

**Primary areas:** `hanly_app/{capture,hover_controller,hover_lookup,hover_target,composition}.py` and focused capture/retention tests.

- Separate pointer movement within a recognized context from movement that
  requires a new capture.
- Anchor the active ROI for the held chord/current hover episode, or while the
  pointer remains inside an inner safe region. Reproject new screen coordinates
  into that ROI and resolve them against cached OCR without rerunning Vision.
- Re-anchor only after the pointer leaves the safe region. Use bounded
  hysteresis so movement near an edge cannot alternate between two ROI origins.
- Preserve the 32-pixel grid only if offset measurements show it still helps;
  do not let crossing one grid boundary invalidate an otherwise usable context.
- Benchmark candidate context sizes with the offset fixture before changing the
  200×100 default. Choose the smallest stable context that stays within the
  approved small-ROI architecture and latency budget.
- Preserve monitor selection, bounded/latest-wins work and final request
  currency. A cached context has explicit generation/geometry identity.
- Do not suppress a real transition to an adjacent word. The resolver should
  change the selected span once while reusing the same recognized context when
  both words are already present.

**Done:** small movements across every syllable of one word and across the old
grid boundary keep one recognized surface/lemma; moving to an adjacent word
changes ownership once without popup oscillation.

### S3 — Preserve Vision geometry across the provider seam

**Primary areas:** `hanly/{contracts,vision_provider,word_resolver}.py`, provider interfaces/exports, process serialization if the normalized contract crosses it, and focused provider/resolver tests.

- Normalize Vision's real quadrilateral rather than deriving only an
  axis-aligned bounding rectangle.
- Add optional provider-neutral text-span geometry when the installed Vision
  API can return a bounding region for the selected recognized range.
- Define coordinates and range offsets once: orientation, normalization,
  inclusivity and conversion to ROI pixels must be explicit and tested.
- Let `WordResolver` prefer measured span geometry for hit testing, character
  ownership and retained word bounds. Keep weighted script advances as the
  fallback for EasyOCR and Vision results without range geometry.
- Do not expose Vision observations, Objective-C ranges or framework classes.
- Keep recognition at the primary candidate during this package. Collecting or
  ranking additional candidates requires separate evidence and authorization.

**Done:** Vision hit testing and retention use measured geometry where
available, tilted quadrilaterals remain faithful, and providers without span
geometry preserve their existing behavior.

### S4 — Wire the single clipping-recovery attempt

**Primary areas:** `hanly_app/{capture_recovery,capture,hover_lookup,manual_lookup,lookup_controller}.py`, lookup-process metadata only where required, and integration tests.

- Invoke the existing edge test after the current result identifies the OCR
  observation responsible for the target.
- On boundary contact, compute one padded, monitor/selected-region-constrained
  capture around the observation, reproject the original screen target, and
  submit exactly one recovery lookup.
- Carry one request-wide recovery budget and explicit attempt identity. The
  recovery cannot recursively authorize another recovery.
- Recheck request currency before capture, submission and presentation.
- Ensure S2's stable normal context is not discarded unless clipping is
  actually observed.
- Do not retry a complete but incorrect reading based on confidence, dictionary
  miss, text shape, or competing lexical units.
- Replace pure-helper-only evidence with an integration test proving that a
  second capture occurs once and its result can become current.

**Done:** boundary-touching target text gets at most one correctly transformed
recapture; non-boundary misrecognition receives none and cannot masquerade as a
confident unrelated definition.

### S5 — Converge, verify natively, and document operational impact

**Primary areas:** focused tests, `CLAUDE.md`, `docs/CODE-MAP.md`, the relevant architecture source/visual only after human approval where it changes an approved decision, one Review Handoff, and one short operator note.

- Run the focused offset, provider, resolver, capture/recovery, hover, process
  and Control Center tests during implementation.
- At convergence run once:

```bash
.venv/bin/python -m pytest
.venv/bin/python -m ruff check packages packaging tests tools benchmarks
.venv/bin/python -m mypy packages packaging tests tools benchmarks
```

- Run native macOS hover and restore acceptance in Section 4. Missing native
  evidence is a stated gap, never replaced by offscreen or mocked success.
- Reconcile current documentation with the human-approved Apple Vision path.
  `CLAUDE.md` and `docs/CODE-MAP.md` currently say EasyOCR is the only backend;
  update them and any authoritative architecture only to the extent separately
  approved by the human.
- Produce one Review Handoff at
  `docs/execution/review-handoffs/vision-hover-and-macos-restore-stabilization-2026-09-20.md`
  and stop before deep review or Bundle B.
- Produce one short operator/release note at
  `docs/execution/reports/vision-hover-and-macos-restore-operator-notes.md`.
  It must list what changed, whether KRDICT/schema/resources changed, whether a
  database rebuild is required, packaging/release actions, platform-specific
  requirements, and any user-visible configuration migration. Use explicit
  `None`/`No` entries rather than omitting unaffected categories.

**Done:** mechanical gates are recorded, native evidence is recorded honestly,
architecture/code maps no longer contradict the authorized runtime, the
operator can prepare a release without reading the implementation checkpoint,
and the Review Handoff ends Phase A.

## 4. Acceptance matrix

| Layer | Required case | Observable pass condition |
|---|---|---|
| Trace | One hover request across shell and child | ROI, target, observation, selected span/candidate and final status share one correlation identity without private content in default logs |
| Stable word ownership | `떨어뜨렸어요`, `예뻤어요`, `사과했어요`, `친구들이`, `공부하려고`; every syllable and small movements crossing the old grid edge | Each unchanged source word keeps one recognized surface and the expected lemma: `떨어뜨리다`, `예쁘다`, `사과하다`, `친구`, `공부하다` |
| Adjacent text | Move from one Korean lexical unit to the next within one recognized line | Selection changes once to the adjacent unit and does not oscillate between popups |
| Honest OCR failure | A full visible word is misrecognized | No dictionary-backed guess, confidence-only retry or unrelated-prefix success is presented as truth |
| Vision geometry | Axis-aligned and tilted observations, optional measured substring geometry | Hit testing and retained bounds use normalized measured geometry; fallback providers remain valid |
| Clipping recovery | Selected observation touches each ROI edge; no touch; monitor/selected-region edge; stale request | Exactly one constrained recapture on touch, none otherwise, correct reprojection, stale result never presents |
| Control Center focus path | Live child minimized while pywebview's construction flag remains false | Focus invokes restore before show/activation and the real native window becomes visible |
| Dock reopen | Open, edit page state, minimize, click Dock/application icon; repeat three times | Same child PID/generation, page/settings/capture state preserved, no duplicate process or Dock tile |
| Cross-platform safety | EasyOCR on supported platforms; Vision unavailable or not selected | EasyOCR behavior remains valid and Vision-specific imports/objects do not leak across the provider seam |
| Operations | Final short operator note | Database/resource/rebuild/release impacts are explicit and sufficient to prepare the next release |

Native acceptance should be recorded with a short screen capture or equivalent
observable evidence plus the correlated trace. The trace explains the result;
the recording proves the user-facing behavior.

## 5. Explicit non-goals and stop boundary

- Do not begin the Bundle B visual reference match, HTML renderer, custom
  listboxes, broad motion cleanup, real-screen corpus program, Windows title
  bar, or AppKit/Liquid Glass port.
- Do not treat this as permission for continuous full-screen OCR, phrase lookup,
  a generic OCR plugin system, dictionary-backed spelling correction, or model
  training.
- Do not change KRDICT data or schema unless new evidence proves the stabilization
  work actually requires it. The expected operator-note answer is that no
  database rebuild is needed.
- Do not claim Apple Vision is better or worse from one centred crop. Compare
  stability across offsets and latency on the same source material.
- Do not commit, push, merge, mutate Linear, or release unless the human
  separately authorizes that action.
- After the Review Handoff is written, stop. Phase B deep review begins only in
  a new human-authorized run with the reviewer/ecosystem chosen by the human.

## 6. References

- [`lookup-and-popup-correction-2026-09-19.md`](lookup-and-popup-correction-2026-09-19.md) — original evidence and Bundle A specification; preserve its empirical Section 2 and reproduction Section 8.
- [`lookup-and-popup-correction checkpoint`](../checkpoints/lookup-and-popup-correction-2026-09-19.md) — implementation decisions and validation.
- [`lookup-and-popup-correction Review Handoff`](../review-handoffs/lookup-and-popup-correction-2026-09-19.md) — delivered scope, limitations and R2–R10 findings.
- [`docs/CODE-MAP.md`](../../CODE-MAP.md) — current file ownership and runtime flow, noting its OCR-backend description is stale.
- [`docs/execution/05-execution-plan.md`](../05-execution-plan.md) — authoritative two-phase execution workflow.
- `packages/hanly-app/src/hanly_app/capture.py`
- `packages/hanly-app/src/hanly_app/capture_recovery.py`
- `packages/hanly-app/src/hanly_app/hover_lookup.py`
- `packages/hanly-app/src/hanly_app/control_center_host.py`
- `packages/hanly/src/hanly/vision_provider.py`
- `packages/hanly/src/hanly/word_resolver.py`
