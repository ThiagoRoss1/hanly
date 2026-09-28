# Wave 4 (Bundle C) — acquisition-neutral language seam Review Handoff

## Bundle

- Member issues: none. Executed from
  `docs/execution/plans/text-acquisition-diagnostic-microscope-2026-09-20.md`
  §8. No Linear state was created or changed.
- Implementation ecosystem: Claude Opus 5, single run.
- Date: 2026-09-21.
- Live ledger:
  `docs/execution/checkpoints/wave-4-language-seam-2026-09-21.md`

**Architecture approval.** Wave 4 is the one bundle the master plan gates on
explicit human approval of an engine seam. It was granted on 2026-09-21 in these
terms: introduce the smallest provider-neutral selection value containing
surface text and cursor/character index in `hanly`; preserve
`LookupPipeline.lookup(image, target)` as the compatible pixel facade; route
pixel OCR and future native-text acquisition through one shared language
implementation; keep UIA, AX, DOM, screen geometry and desktop lifecycle out of
the engine; preserve OCR-provider selection, `NOT_FOUND` semantics, fallback
behaviour and popup behaviour; and synchronize the approved architecture
documents and visual companions. The Wave 3 wording correction was permitted as
documentation-only preflight.

## Implemented

**Preflight, documentation only.** The Wave 3 issue-local spec now carries the
Phase B equal-N re-measurements, withdraws the claim that exact doubling is
uniquely reliable, and explains that 2 is the smallest integer inside a wide
verified basin. No code changed.

**The seam.**

- `TextSelection` in `hanly/contracts.py`: surface text, a cursor index, and an
  inert `source` label for diagnostics. Nothing else.
- `LanguagePipeline` in `hanly/language_pipeline.py` (new): Hangul policy,
  morphology normalization, cursor-driven candidate selection, selection
  diagnostics, dictionary query, result construction. Constructed from two
  providers, so a non-pixel client builds no recognizer.
- `LookupPipeline` reduced to the pixel facade. It keeps recognition, target
  resolution and OCR confidence, then delegates. `lookup_selection` exposes the
  same stage to a caller with no image.
- `LanguagePipeline` and `TextSelection` exported from `hanly`.

## Main expected behavior

Nothing observable changes. Every existing caller of
`LookupPipeline.lookup(image, target)` gets the same results it did, and the
desktop needed no modification. What is new is that a caller which already knows
the word can reach the identical language stage without pixels.

## Architecture / seams touched

- **New public engine contract**, as approved: `TextSelection` and
  `LanguagePipeline`. The explicit export-surface test guarded this and was
  updated deliberately.
- `RF-INV-13` appended to `01-runtime-flow.md`; `CA-INV-16` appended to
  `02-component-architecture.md`. **Appended, never renumbered**, so no existing
  cross-reference moved.
- Both visual companions updated. Markdown and companion IDs are 1:1 and in the
  same order (13 `RF-INV-*`, 16 `CA-INV-*`), and each edit is provably additive:
  removing exactly the inserted row restores the pre-edit file byte-for-byte.
- `CA-INV-02` still holds — `hanly` imports nothing from `hanly_app`, and a test
  asserts the language module names no desktop or platform symbol.
- Unchanged: `OCRProvider` and the other provider interfaces, provider
  selection, capture, gate, caches, the resolver, dictionary-miss meaning,
  fallback behaviour, popup behaviour.

## Relevant files / diff areas

Engine: `packages/hanly/src/hanly/{contracts,language_pipeline,lookup_pipeline,__init__}.py`.
Tests: `tests/test_language_pipeline.py` (new), `tests/test_core_contracts.py`.
Docs: `docs/architecture/01-runtime-flow.md`,
`docs/architecture/02-component-architecture.md`, both visual companions,
`docs/CODE-MAP.md`, and the Wave 3 spec (preflight).

`hanly-app` is untouched. The worktree holds several bundles; scope attribution
should use this list. Nothing was committed.

## Implementation-side validation already run

| Check | Result |
|---|---|
| `.venv/bin/python -m pytest` | **1965 passed, 2 skipped** (entry: 1936 passed, 2 skipped) |
| `.venv/bin/python -m ruff check packages packaging tests tools benchmarks` | All checks passed |
| `.venv/bin/python -m mypy packages packaging tests tools benchmarks` | Success, 270 source files |
| Behavioural parity, real Kiwi + real KRDICT, 10 cases | **10/10 identical** |
| Extraction cost, n=300 | language stage p50 164 µs; full pixel path p50 237 µs |
| Invariant 1:1 mapping, both companions | verified in order |
| Companion edits additive | byte-for-byte restore confirmed |

### Parity evidence

Each case run twice — once as a direct `TextSelection`, once through the pixel
facade aimed at the same character — against the real providers:

| Surface | idx | direct | via pixels |
|---|---|---|---|
| 초대받았어요 | 0 | SUCCESS `초대` | SUCCESS `초대` |
| 초대받았어요 | 3 | SUCCESS `받다` | SUCCESS `받다` |
| 읽습니다. | 0 | SUCCESS `읽다` | SUCCESS `읽다` |
| 떨어뜨렸어요 | 2 | SUCCESS `떨어뜨리다` | SUCCESS `떨어뜨리다` |
| 책을 | 0 | SUCCESS `책` | SUCCESS `책` |
| 예뻤어요 | 1 | SUCCESS `예쁘다` | SUCCESS `예쁘다` |
| 심심해서 | 0 | SUCCESS `심심하다` | SUCCESS `심심하다` |
| 없는말입니다 | 0 | SUCCESS `없다` | SUCCESS `없다` |
| `Hanly 2.0` | 0 | UNUSABLE | UNUSABLE |
| (whitespace) | 0 | UNUSABLE | UNUSABLE |

The gap between the language stage (164 µs) and the full pixel path (237 µs) is
OCR and target resolution, not the delegation.

## Known limitations / intentionally unvalidated areas

- **No native acquisition exists yet**, so the neutrality is proved by
  construction and by tests, not by a second real client. Wave 5 is the first
  time a non-pixel caller will actually exercise it, and that is when a wrong
  assumption in `TextSelection`'s shape would surface.
- **`source` is inert by design and nothing enforces that it stays inert.** A
  test asserts results are identical across four different labels, but a future
  edit could read it.
- **`lookup_selection` on `LookupPipeline` still requires an OCR provider to
  have been supplied at construction.** That is why `LanguagePipeline` is
  separately constructible; the convenience method is for a caller that already
  has a pipeline, not the recommended path for a pixel-free client.
- **Cursor index is not bounded against the text length.** `TextSelection`
  rejects negatives but accepts an index past the end;
  `MorphologyAnalysis.candidate_at` resolves it to the nearest candidate rather
  than failing. That is the pre-existing behaviour, preserved deliberately.
- **The parity table is 10 cases on one machine** with one KRDICT build. It is
  behavioural parity, not a correctness claim about any of the lemmas.
- **The visual companions were verified structurally, not visually.** The
  invariant rows map 1:1 and the edits are provably local, but nobody has opened
  the rendered pages.
- **`hanly.__all__` still lists `MorphologyAnalysis` and `TargetResolution`
  twice.** Pre-existing, from another uncommitted bundle; left untouched rather
  than absorbed into this diff.

## Suggested review targets

- `LanguagePipeline.lookup`'s context handling: it fills language fields onto a
  caller-supplied `LookupContext` with `replace`. If a pixel caller's evidence
  were dropped or overwritten, a popup would lose the geometry it needs to keep
  itself alive.
- The confidence check's position. It stayed in the facade because the language
  stage has no confidence to judge, which means the low-confidence `UNUSABLE`
  context is now built in two places — worth confirming it matches what it was.
- `TextSelection.__post_init__` against the frozen-dataclass contract, and
  whether rejecting a bool for `cursor_index` is consistent with the rest of the
  engine's validation style.
- Whether `source` belongs on the contract at all, given nothing reads it.
- The appended invariants' wording, and whether `RF-INV-13` is genuinely a
  runtime-flow invariant rather than a component one.
- `tests/test_language_pipeline.py::test_no_desktop_or_platform_module_reaches_the_language_stage`
  is a source-text scan, which is crude; a reviewer may prefer an import-graph
  assertion.

## Review assignment

Human-selected after implementation. Not started.

---

# Phase B deep review

- **Authorized:** 2026-09-21, separately from the implementation run. Scope:
  review the completed seam and this handoff independently. Wave 5 not begun,
  approved architecture not redesigned, nothing committed.
- **Reviewer ecosystem:** Claude Opus 5, single run, `.venv/bin/python` (3.13.11).
- **Method:** differential execution against a reconstruction of the pre-Wave-4
  `LookupPipeline`, transitive import-graph analysis, adversarial evidence
  injection, mutation testing of the new assertions, and independent
  re-derivation of the invariant mapping rather than re-reading the claim.

## What was verified independently

**The refactor is behaviourally identical where it matters.** The pre-Wave-4
pipeline was reconstructed from the prior implementation and both were run over
**1,728 combinations** (texts x OCR confidences x thresholds x morphology modes
x dictionary modes x targets), comparing field by field:

| Field | Differences |
|---|---|
| `status` | **0** |
| `entries` | **0** |
| `context` | **0** |
| `error` | **0** |
| provider call counts | **0** |
| `diagnostics` | **216** |

The 216 are the subject of finding 2 below. Because `context` matched in every
case, the handoff's own concern — that the low-confidence `UNUSABLE` context is
now built in two places and might have drifted — is **resolved: it matches**.

**The plan's named risk did not materialize.** All six language helpers
(`_as_morphology_analysis`, `_candidates_from_tokens`, `_select_candidate`,
`_selection_diagnostics`, `_is_korean_segment`, `_is_hangul_character`) are
defined exactly once, in `language_pipeline.py`. There is no second language
implementation.

**The stage is genuinely free of acquisition.** Importing
`hanly.language_pipeline` pulls in 31 modules and **none** of `torch`, `PIL`,
`numpy`, `easyocr`, `kiwipiepy`, `sqlite3`, Qt, `webview`, `mss`, or any Apple
framework. The approved goal that a non-pixel client "constructs no recognizer"
holds by measurement, not only by construction. `language_pipeline` also does
not import `lookup_pipeline` — the dependency points one way.

**The invariant mapping is 1:1 and in order**, re-derived rather than trusted:
13 `RF-INV-*` and 16 `CA-INV-*` list rows, `01`..`13` and `01`..`16`, matching
the markdown. A first naive scan appeared to show RF-INV out of order; that was
the scan picking up the diagram's *citations* of invariants, which precede the
list. The artifact was correct and the scan was wrong.

**`TextSelection.source` is provably inert**: constructed in exactly one place
(`source="ocr"`), read nowhere in `packages/`, `tests/`, or `benchmarks/`.

**Cursor index past the end** resolves to the nearest candidate (0 -> `초대`;
3, 6, 50, 10^6 -> `받다`), as the handoff documents.

## Findings

### Fixed now

**1. Stale language fields survived an early return.** *(latent defect, new
public boundary)* `LanguagePipeline.lookup` used a caller's `evidence` as its
base context unchanged. On the two early returns, language fields the caller had
left in that context survived into the result: a non-Korean selection returned
`text='Hanly 2.0'` alongside `lemma='WRONG'`, `candidate='WRONG'`,
`analyses=['X']`, and an empty selection returned `text='WRONG'` — a result
whose explanation contradicts its own answer.

Unreachable from the shipped pixel path, which builds fresh evidence holding
only `ocr_results`, `selected_ocr` and `word_region` — which is exactly why the
differential's `context` column is 0. It is reachable by the non-pixel callers
this seam was created for: handing a previous result's `LookupContext` back as
`evidence` is a natural thing for such a client to do.

Fixed as cheap defensive hardening at a public boundary: the stage now clears
the four fields it owns on entry and leaves every other field alone. Pixel
evidence still passes through untouched. Guarded by
`test_stale_language_fields_in_caller_evidence_never_survive_an_early_return`,
which was confirmed to **fail** against the unpatched implementation.

**2. "This changes no outcome" was overstated.** The 216 diagnostic differences
have two causes, both real consequences of the seam:

- the Hangul-policy message lost the word "OCR" ("Resolved OCR target must
  contain Hangul..." -> "Resolved target must contain Hangul..."), correct now
  that the stage does not know what produced the text;
- **stage order changed.** The Korean check used to run before the confidence
  check; confidence is now judged in the facade first. A low-confidence
  non-Korean region therefore reports the confidence reason instead of the
  script reason.

User-visible impact is **zero**: `_PRESENTED_STATUSES` is
`frozenset({SUCCESS, ERROR})`, so no `UNUSABLE` diagnostic ever reaches a popup.
But the claim as written was wrong. `01-runtime-flow.md` now says "This changes
no *presented* outcome" and names both differences. This is a fidelity
correction to prose; no approved decision was altered, and no invariant was
added, renumbered or reworded. The visual companion carries only the invariant
rows and does not contain this prose, so it needed no edit.

**3. The platform-purity test was a source-text scan.** The handoff flagged it
as crude and it was: it read one file's text, so a platform dependency arriving
through a sibling engine module — the realistic way one would appear — would
pass. Replaced with a transitive AST walk of the import closure rooted at
`language_pipeline`, asserting the closure was actually walked. Mutation-tested:
adding `import sqlite3` to `hanly/errors.py` makes it fail, which the old scan
did not detect. `errors.py` was restored byte-clean.

### Deferred

**4. `TextSelection.source` has no reader and exceeds the approved minimum.**
The approval names "surface text and cursor/character index"; `source` is a
third field, written once and read nowhere. It is harmless and useful for
diagnostics, but removing a field from a published contract later is a breaking
change, whereas removing it now costs nothing.

*Revisit trigger:* when Wave 5 lands the first non-pixel acquisition. If that
client does not read `source`, remove it before `hanly` is published to PyPI.

### Dismissed

**5. `TextSelection.__post_init__` validation style.** It is stricter than most
sibling contracts, which raise `ValueError` on semantic conditions rather than
`TypeError` on types — but precedent exists (`ROIImage` raises `TypeError` for
`pixel_format`), and stricter validation is appropriate at a brand-new public
boundary that external callers construct directly. Rejecting `bool` for
`cursor_index` is correct, not pedantic: `True` would otherwise silently index
as 1.

**6. Cursor index is not bounded against text length.** Verified pre-existing
`candidate_at` behaviour, preserved deliberately, and documented. Changing it
would be a behaviour change outside this bundle.

**7. `RF-INV-13` placement.** It states what the language stage receives and
that both acquisitions reach one stage — an ordering-and-flow statement, which
belongs in `01`. `CA-INV-16` carries the component-ownership half. Neither
duplicates the other.

## Gates re-run after the review's changes

```
.venv/bin/python -m pytest  -> 1966 passed, 2 skipped   (1965 before; +1 regression test)
.venv/bin/python -m ruff check packages packaging tests tools benchmarks -> All checks passed
.venv/bin/python -m mypy packages packaging tests tools benchmarks -> Success, 270 source files
```

## Limits of this review

- Behavioural equivalence was established against a **reconstruction** of the
  prior pipeline, not against a checked-out revision — git history was not used
  to obtain the original file.
- The differential used provider doubles. The 10-case real-provider parity table
  in the implementation section remains the only evidence involving real Kiwi
  and real KRDICT.
- The companions were again verified structurally. **Nobody has opened the
  rendered pages**; the implementation-side limitation stands.
- Neutrality remains proved by construction, tests and import analysis. No
  second real acquisition exists yet, so Wave 5 is still the first genuine test
  of `TextSelection`'s shape.

## Verdict

**Accept.** The seam does what the approval authorized: one shared language
implementation, a compatible pixel facade with an unchanged signature, no
platform or geometry concepts in the engine, and preserved `NOT_FOUND`,
provider-selection, fallback and popup behaviour. The one real defect was latent
rather than shipped, is fixed and guarded, and the one inaccurate claim is
corrected. Nothing found requires rework of the approved design, and nothing
blocks Wave 5.

Three findings fixed, one deferred with a trigger, three dismissed. Nothing
committed.
