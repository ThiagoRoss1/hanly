# Engine Convergence Review Handoff

## Bundle

- Member issues: HAN-12, HAN-13
- Implementation ecosystem: GPT — Sol orchestrator with direct Luna xhigh workers
- Date: 2026-08-20

## Implemented

- `LookupPipeline` orchestration across the normalized OCR, resolver, morphology, and dictionary seams.
- UI-independent success, empty, not-found, unusable, low-confidence, and processing-error outcomes with retained lookup context and diagnostics.
- A UI-free engine E2E gate using normalized image input, real Kiwi analysis, a deterministic KRDICT XML-to-SQLite build, and the read-only KRDICT provider.
- Explicit engine public export and focused stage-order/result-category coverage.

## Main expected behavior

`ROIImage` plus an engine-level target point can now flow through OCR evidence, Quad-aware text resolution, morphology, dictionary lookup, and construction of a completed `LookupResult`. The same engine-only path demonstrates success, normal not-found, and processing-error outcomes without importing `hanly-app`, UI code, `ResourceManager`, or concrete provider types into `LookupPipeline`.

## Architecture / seams touched

- `LookupPipeline` as the provider-only engine convergence point.
- `OCRProvider`, `MorphologyProvider`, `DictionaryProvider`, and `WordResolver` collaboration.
- `LookupResult`, `LookupContext`, and `LookupStatus` outcome semantics.
- RF-INV-03/04/05/10/12, CA-INV-02/03/05/09/13/15, and DAG-INV-01/02/14.

## Relevant files / diff areas

- `packages/hanly/src/hanly/lookup_pipeline.py`
- `packages/hanly/src/hanly/__init__.py`
- `tests/test_lookup_pipeline.py`
- `tests/test_engine_e2e.py`
- `tests/test_core_contracts.py`

## Implementation-side validation already run

- HAN-12 focused pipeline checks -> 12 passed; focused Ruff and mypy clean.
- HAN-13 focused E2E/pipeline/package-boundary checks -> 16 passed; focused Ruff and mypy clean.
- `.venv\Scripts\python.exe -m pytest --basetemp=C:\Hanly\.pytest_cache\han12-13-gate-20260820` -> 116 passed, including three engine E2E cases.
- `.venv\Scripts\python.exe -m ruff check packages tests` -> passed.
- `.venv\Scripts\python.exe -m mypy packages tests` -> no issues in 27 source files.

## Known limitations / intentionally unvalidated areas

- Ordinary E2E tests inject deterministic normalized OCR results instead of loading Paddle models; real Korean PaddleOCR inference was already verified and closed in the Wave 2 review.
- E2E dictionary data is a deterministic KRDICT-shaped test document, not the production KRDICT release.
- The pipeline deterministically looks up the first non-empty morphology lemma from the resolved OCR segment; broader multi-token selection policy was not invented here.
- The optional confidence threshold defaults to disabled when composition supplies no policy.
- Evidence is Windows/Python 3.13; no desktop worker, request-currency, UI, packaging, or cross-platform behavior was exercised.
- The previously deferred KRDICT SQLite threading strategy remains unresolved and reaches its stated revisit trigger before HAN-14 worker wiring begins.

## Suggested review targets

- Result-category boundaries and preservation of useful context through short-circuit and error paths.
- Confidence matching when duplicate OCR text appears in multiple regions.
- First-lemma selection for resolved segments containing multiple linguistic tokens.
- Engine-only dependency closure and whether the E2E composition is sufficient evidence for the deliberate pre-desktop gate.
- Carry the existing SQLite threading decision into HAN-14 planning rather than silently choosing a strategy in this bundle.

## Post-Bundle Review Outcome

- Reviewer: Claude (Opus 5)
- Review ecosystem: Claude, reviewing a Codex-implemented bundle
- Date: 2026-08-20
- Status: Closed. The engine gate holds. Real-provider evidence exposed one open V1 correctness issue — target-point-to-token selection — recorded below with its blocking trigger and candidate directions.

Gates after the review: **119 passed, Ruff clean, mypy clean across 29 source
files.**

### Verified against real runtimes

Composed the real `PaddleOCRProvider`, real `KiwiProvider`, and a real
`KRDICTProvider` over a built SQLite artifact, then ran `LookupPipeline.lookup`
on the committed Korean ROI fixture. The pipeline wiring itself is sound: stages
run in order, context is retained, and a `SUCCESS` result with a real
`DictionaryEntry` comes back offline.

**The product answer is wrong, though, and silently so.** Real PaddleOCR returns
one *line-level* region for the fixture, so both of these produce the same
result:

```text
over 책을     (20, 23)  -> SUCCESS  text='책을 읽습니다.'  lemma='책'  -> 'book'
over 읽습니다 (120, 23) -> SUCCESS  text='책을 읽습니다.'  lemma='책'  -> 'book'
```

Hovering the verb returns the noun's definition, with `SUCCESS` status and a
plausible entry. The target point selects an OCR *region*; it never reaches
token selection, and `_first_usable_lemma` then took token zero.

`return_word_box=True` — already a `PaddleOCRConfig` field — does not fix this:
it returns one "word" spanning the whole line
(`text_word=[['책을 읽습니다.']]`), so there is no cheap configuration route.

### Fixed now

- **Multi-token reduction is no longer silent.** When a resolved segment yields
  more than one usable lemma, the result now carries a diagnostic naming the
  count, the lemma actually used, and the reason ("the target point selects a
  region rather than a token"). Selection policy is unchanged — this makes the
  limitation visible to `LookupController` and to anyone debugging a wrong
  popup, rather than inventing token selection inside the pipeline.
  `_first_usable_lemma` became `_usable_lemmas` to support the count.
- **Error diagnostics no longer double the stage prefix.** A synthesized error
  produced `"OCR failed: OCR failed: boom"`; the message is now built once.
- Focused coverage added for both, plus a single-token case asserting no
  diagnostic noise when there is nothing to report.

### Open V1 correctness issue

**Target-point-to-token selection is unresolved, and this is a V1 correctness
bug rather than post-V1 polish.**

What happens today, verified with real providers:

1. Real PaddleOCR may return a single line-level region, e.g. `책을 읽습니다.`
2. `WordResolver` correctly selects that region from the target point.
3. Kiwi then produces several usable tokens and lemmas for the region.
4. The pipeline cannot determine which token inside the region corresponds to
   the target point, so it uses the first.
5. The result is a plausible but wrong `SUCCESS`: targeting `읽습니다` resolves
   `책` and shows "book".

Nothing here is a defect in `WordResolver`, Kiwi, or the OCR adapter
individually — each does its own job correctly. The gap is that the target point
stops being consulted once a region has been chosen.

**Blocking status:** this does **not** block HAN-14 / Desktop Foundation, whose
scope is desktop lifecycle rather than lookup semantics. It **must** be resolved
before HAN-19 Manual Hotkey Lookup can be considered functionally complete,
because that is the first capability whose visible output is a definition for the
word under the cursor.

Candidate solution directions:

1. **Map the target point's relative position inside the OCR quad to Kiwi
   token/character offsets.**
2. **Obtain tighter OCR/detection regions** closer to individual words or
   tokens.
3. **Perform geometric token resolution after morphology**, deriving
   token-level regions from the line region and the token sequence.

**Option 1 is the current leading hypothesis, not a final design decision.** It
reuses the line-level OCR geometry already available together with morphology
offsets, and it does not depend on PaddleOCR producing better word boxes — which
matters, because `return_word_box=True` was tested here and returned one "word"
spanning the whole line. It still needs validation against real Korean text,
proportional fonts, spacing behavior, punctuation, tilted text, and
OCR-to-morphology offset alignment before it can be adopted.

The diagnostic added in **Fixed now** stays: it does not solve the selection
problem, but it keeps the ambiguity from being silent while the decision is
pending.

*Revisit at Wave 4-6 planning; resolve before HAN-19 is accepted.*

### Deferred considerations

- **Confidence matching by text equality.** `_is_low_confidence` matches OCR
  regions to the resolved text by string equality and takes the minimum
  confidence of the matches; a custom resolver that normalizes text finds no
  match and the policy silently does not apply. Reasonable and documented today.
  *Revisit when a resolver that rewrites text exists, or when confidence policy
  moves into composition.*
- **`assert threshold is not None` in the low-confidence branch.** Correct by
  construction and only used for message formatting, but `assert` is stripped
  under `python -O`. Harmless now. *Revisit if the engine is ever run
  optimized, or fold the threshold into the branch that computes it.*

### Dismissed

- **Engine dependency closure for the pre-desktop gate.** Checked as a review
  target: `LookupPipeline` imports only contracts, provider protocols and
  `WordResolver`; nothing in `hanly` reaches `hanly-app`, UI, `ResourceManager`,
  or a concrete provider type. The deliberate DAG gate is satisfied.
- **Result-category boundaries through short-circuit and error paths.** Walked
  each branch: `EMPTY`, `UNUSABLE` (unresolved / low confidence / no lemma),
  `NOT_FOUND`, `ERROR` and `SUCCESS` all retain the context available at that
  stage, and only `SUCCESS` carries entries. No defect found.
- **SQLite threading strategy reaching its trigger here.** The handoff notes it
  reaches its revisit trigger before HAN-14. It stays deferred on the Wave 2
  handoff, which owns it; nothing in this bundle runs a lookup off-thread, and
  duplicating it here would split the record.

## Review assignment

Human-selected. Review completed 2026-08-20 — see the Post-Bundle Review Outcome above.
