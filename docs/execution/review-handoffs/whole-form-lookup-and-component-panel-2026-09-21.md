# Whole-form lookup and contextual component panel Review Handoff

## Bundle

- Member issues: none. Executed from the issue-local specification
  `docs/execution/plans/whole-form-lookup-and-component-panel-2026-09-21.md`.
  No Linear state was created or changed. A pre-Wave-5 bundle; the
  text-acquisition master plan was not modified.
- Implementation ecosystem: Claude Opus 5, single run, macOS 26.6.2,
  `.venv/bin/python` 3.13.11.
- Date: 2026-09-21.
- Live ledger:
  `docs/execution/checkpoints/whole-form-lookup-and-component-panel-2026-09-21.md`
- Branch: `visual/interface-update`, base `9c4cfea`. One Phase A commit.

## Implemented

Both corrections live in the one shared `LanguagePipeline`. **No public `hanly`
contract changed.**

- **Whole-form preference.** When morphology reports two or more lexical units,
  the language stage probes the dictionary once for the joined complete form —
  the leading surface plus the final unit's lemma, never across whitespace. If
  the dictionary has it, it becomes the primary result and spans the whole form,
  so the answer stays stable while the cursor moves inside it. If not, behaviour
  is exactly the previous cursor-selected component. The dictionary is asked at
  most twice per lookup.
- **Generic homograph ordering.** One lemma's entries are ordered by whether the
  entry's part of speech matches the morphology unit's, then by KRDICT's own
  `vocabulary_level`, then by entry id for stability. No word-specific override,
  no English-definition keyword matching, no semantic heuristic, no translation
  service.

## Main expected behavior

Hovering `초대받았어요` near `초대` now answers **`초대 · 招待 · invitation`**
instead of `初代 · first`. Compounds the dictionary genuinely holds but Kiwi
splits — `가공식품`, `가까워지다`, `가로놓이다`, `책상` — are now answered whole
instead of by a fragment. Everything previously correct is unchanged, and two
space-separated words still select independently.

## The approved representative example cannot be produced

`초대받다` **is not in KRDICT** (zero entries; only 35 `…받다` headwords exist)
and Kiwi never produces it. The direction's illustrative presentation
(`초대받다 / be invited`) would require inventing a composed translation, which
is forbidden. For this surface the approved fallback rule governs: the primary
result is the cursor-selected component, and the homograph correction is what
makes that component right. This is reported rather than worked around.

## Architecture / seams touched

- `LanguagePipeline` only — the shared implementation both acquisition paths
  already run. `LookupPipeline.lookup(image, target)` is unchanged in signature
  and behaviour, and `hanly-app` needed no change.
- No engine contract, provider interface, or export surface changed;
  `RF-INV-*`/`CA-INV-*` and the visual companions are untouched.
- Unchanged: OCR providers and selection, Vision scaling, ROI, capture, gate and
  cache behaviour, the resolver, dwell, fallback ordering, dictionary-miss
  semantics, `NOT_FOUND`/`UNUSABLE`/`ERROR` meaning, popup behaviour,
  `TextSelection.source`.

## Relevant files / diff areas

Engine: `packages/hanly/src/hanly/language_pipeline.py`.
Tests: `tests/test_whole_form_lookup.py` (new, 18),
`tests/krdict/test_whole_form.py` (new, 26), and updated expectations in
`tests/test_language_pipeline.py`, `tests/test_lookup_pipeline.py`,
`tests/test_lookup_evidence.py`, `tests/test_app_composition.py`.
Docs: the spec, the checkpoint, this handoff.

## Implementation-side validation already run

| Check | Result |
|---|---|
| `.venv/bin/python -m pytest` | **2010 passed, 2 skipped** (entry: 1966 passed, 2 skipped) |
| `.venv/bin/python -m pytest --suite native` | **72 passed** |
| `.venv/bin/python -m ruff check packages packaging tests tools benchmarks` | All checks passed |
| `.venv/bin/python -m mypy packages packaging tests tools benchmarks` | Success, 272 source files |
| Before/after on 48 real-provider positions | 40 unchanged, 8 changed, all improvements |
| Direct `TextSelection` vs pixel facade | **0 parity failures**, before and after |
| Complete-form rule support | Kiwi splits 4,125 real KRDICT headwords; joining recovers a real entry for **3,908 (94.7%)** |
| Latency, real providers, n=400 | split form p50 0.118 ms / p95 0.133 ms; single unit p50 0.097 ms; **≤ 2 dictionary calls** |

Four pre-existing tests changed expectation deliberately, because the new
behaviour is the intended one: `책상` and `초대받다` are now probed as whole forms.
One was a genuine regression caught by the suite and fixed — a dictionary
failure had briefly lost `lemma`/`candidate` from its error context, and the
error path now reports the unit that was being looked up.

## Known limitations / intentionally unvalidated areas

- **The contextual component panel is not implemented.** It reaches a public
  contract boundary and the bundle stopped there, as instructed. See below.
- **Homograph ordering is commonality ordering, not contextual disambiguation.**
  KRDICT's grading says which reading is common; nothing here reads the
  surrounding sentence. It fixes the demonstrated case and orders 눈→eye,
  배→abdomen, 차→tea, 말→speech sensibly, but a rarer sense that is correct in
  context will still rank below a common one. Part-of-speech matching is the only
  genuinely contextual signal used, and it only separates entries of different
  classes.
- **The 94.7% recovery figure is a property of the joined form's presence in
  KRDICT**, not a judgement that each recovered entry is the reading a reader
  wanted. It was measured on headwords, not on hovered running text.
- **No live hover was performed.** All evidence is from the engine and the
  offscreen/native test suites.
- **One machine, one KRDICT build.** macOS only.
- `hanly.__all__` still lists `MorphologyAnalysis` and `TargetResolution` twice —
  pre-existing, untouched.

## Requires human approval before it can proceed

The component panel needs a gloss per component. The popup already renders the
structural decomposition from `LookupContext.analyses` (`READ AS` /
`WORD ANALYSIS`), so only the glosses are missing, and those are dictionary data
producible only inside the engine. Having the desktop call `lookup_selection`
per component would re-run morphology, multiply pipe round-trips and hover
latency, and is the forbidden after-the-fact reconstruction; `diagnostics` is a
debugging channel, not a product model.

The smallest proposed change — a new `LexicalComponent` value and exactly one
additive `LookupContext.components` field — is written out in the checkpoint.
**None of it is implemented.**

## Suggested review targets

- `_complete_form`: joining the leading surface to the final lemma, and whether
  any real surface makes that reconstruction wrong where the dictionary
  nonetheless holds the joined string.
- The whitespace guard as the only thing keeping two words from being joined,
  and whether a selection containing punctuation between units can slip past it.
- `_rank_entries`: the Kiwi-tag-to-KRDICT part-of-speech table, and whether
  ranking by `vocabulary_level` can demote a correct rarer reading in a way a
  reader would notice.
- Whether the whole-form candidate's span (`first.start` to `last.end`) is right
  when the final unit's span overlaps the one before it, as Korean contractions
  make it.
- The bounded two-query rule under a cache, and whether the extra probe changes
  cache-key behaviour in `composition.py`.
- The four deliberately changed test expectations.

## Review assignment

Human-selected after implementation. Not started. This handoff prepares the
review; it does not perform one.
