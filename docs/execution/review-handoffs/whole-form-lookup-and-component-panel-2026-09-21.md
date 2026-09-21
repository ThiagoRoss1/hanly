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

---

# Phase B deep review

- **Authorized:** 2026-09-21, separately from the implementation run. Scope: the
  committed diff `9c4cfea..0ec5008`. Wave 5 not begun, no public contract
  changed, `0ec5008` not amended, rebased or rewritten.
- **Reviewer ecosystem:** Claude Opus 5, single run, macOS 26.6.2,
  `.venv/bin/python` 3.13.11.
- **Method:** the committed diff read directly; the base `LanguagePipeline`
  extracted from `9c4cfea` and run side by side with `HEAD` against the real
  providers; every quantitative claim re-derived from SQL or from the shipped
  code rather than from the implementation's scripts.

## Claims reproduced independently

| Claim | Verdict |
|---|---|
| KRDICT has zero `초대받다` entries | **Confirmed** at SQL level — 0 rows in `lemmas` *and* 0 in `word_forms`, so the provider's `UNION` genuinely finds nothing |
| Only 35 `…받다` headwords exist | **Confirmed** (35) |
| Kiwi never produces `초대받다` | **Confirmed** — `초대` NNG [0,2) + `받다` VV [2,6), raw and `JOIN_V_SUFFIX` |
| 29,145-headword inventory | **Confirmed** exactly |
| 4,125 split forms | **Confirmed** exactly |
| 3,908 recoverable whole-form entries | **Not reproduced — see finding 2** |
| 48-position before/after differential: 40 unchanged, 8 changed | **Confirmed** exactly, against the extracted base |
| All eight changed cases are improvements | **Confirmed**, with a clarification below |
| Direct `TextSelection` vs pixel facade parity | **Confirmed**, 0 failures across all 48 positions |
| At most two dictionary calls | **Confirmed** — instrumented over 80 real positions, maximum observed 2 |
| Latency impact | **Confirmed** — independently p50 0.110 / 0.094 / 0.047 ms against the reported 0.118 / 0.097 / 0.050 ms |
| Package boundary | **Confirmed** — `packages/hanly` contains no reference to `hanly_app` |
| Privacy and exclusions | **Confirmed** — the diff touches one engine file, tests and docs; no capture, export, trace persistence, OCR, ROI, gate, cache, resolver or popup change, and no private artifact is committed |

**Clarification on the eight changes.** Only **two** (`초대받았어요` at indices 0
and 1) change the primary answer. The other six (`차를`, `눈이`, `말이`) leave the
primary identical and reorder the secondary homographs. Those reorderings were
inspected and are improvements — `눈` promotes *snow* above *gradation*, `말`
promotes *horse* above *measuring bucket*, `차` demotes the dependent-noun
reading below the matching nouns and verbs. The handoff already distinguishes
these, and the summary "eight improvements" is fair, but it is two behavioural
corrections plus six ordering improvements, not eight new answers.

## Findings

### Fixed now

**1. `_complete_form` silently dropped surface characters.** The join
substitutes `last.lemma` for the final unit's surface. That is right for an
inflected predicate (`받` → `받다`), but a *noun* whose span swallowed a
derivational suffix keeps its bare lemma, so the substitution dropped the
suffix. `고소득층` was asked for as **`고소득`** — a different word KRDICT also
holds — and answered "high income" while `LookupContext.candidate` claimed the
whole span `고소득층`, whose own entry exists and was never consulted. Same shape
for `고차원적`→`고차원`, `구시대적`→`구시대`, `꿀꿀이`→`꿀꿀`.

Measured across the 4,125 split headwords: **67 joins landed on a real but
different entry.** These are exactly the "incorrect joins that nevertheless
exist in KRDICT" the review was asked to hunt, and they fail confidently.

Fixed as cheap defensive hardening inside the already-private `_complete_form`:
the lemma substitution is refused when it would not account for the surface it
covers (`last.end > last.start + len(last.lemma)`) unless the final unit is a
predicate. Measured effect: **63 of the 67 wrong joins rejected, 0 of the 3,812
correct recoveries lost**, and no additional dictionary call. Two regression
tests were added, one for the refusal and one proving the predicate case the
rule exists for still works.

**2. The recovery figure did not match the shipped rule.** The handoff's
"3,908 (94.7%)" was produced by the ad-hoc exploration script, which lacked the
guards the committed `_complete_form` has. Re-measured with the shipped code:

| | splits | recovered | join == headword | join ≠ headword |
|---|---|---|---|---|
| Reported | 4,125 | 3,908 (94.7%) | not distinguished | not distinguished |
| Shipped code, as committed | 4,125 | 3,879 (94.0%) | 3,812 | **67** |
| After this review's hardening | 4,125 | 3,816 (92.5%) | 3,812 | **4** |

The load-bearing number is **3,812 correct whole-form recoveries**, identical
before and after hardening; the hardening removed only wrong answers. The
conclusion the bundle rests on is unchanged, but the published figure was
measured with code that was never shipped, and it counted wrong joins as
successes.

**3. "then entry id" is not what the code does.** The handoff and checkpoint
describe the ordering as part-of-speech, then vocabulary level, "then entry id
for stability". `_rank_entries` never reads `entry_id`; its final key is the
provider's **input position**. That is the better choice — `entry_id` is
`compare=False` build-artifact data — and it answers the review's question
directly: entry id is not used as linguistic evidence, and is not used at all.
Corrected here rather than by rewriting the implementation's own record.

### Deferred

**4. Four mis-joins remain, all copula cases.** `깜짝이야` still joins to
`깜짝이다` ("blink") because `이다` is tagged `VCP` and passes the predicate
exception, while `깜짝이야` is itself a KRDICT headword. Probing the **raw
surface** `text[first.start:last.end]` before the lemma join would fix
**67 of 67**, including these four — but it costs a third dictionary call and
breaks the documented "at most two" guarantee, so it is a design change, not
hardening. *Revisit trigger:* when the component panel's dictionary budget is
designed, since that work must set a new call bound anyway — decide both
together.

**5. The provider-neutral language stage now encodes two specific adapters'
vocabulary.** `_POS_EQUIVALENTS` hardcodes Kiwi tag families on one side and
KRDICT's Korean part-of-speech strings on the other, and `_tag_family`
duplicates the identical helper in `kiwi_provider.py`. Nothing is imported, and
an unknown tag degrades safely to level-only ordering, so no invariant is
broken today. Deduplicating `_tag_family` would couple the language stage to the
Kiwi adapter, which is worse. *Revisit trigger:* when a second morphology or
dictionary provider is added, move this mapping behind the provider seam.

### Dismissed

**6. Punctuation is not excluded from joins.** The whitespace guard has no
punctuation sibling, so `가.나` joins through. Evidence that this is not
reachable in practice: the 1,584 KRDICT headwords that contain punctuation
without a space are conjugation stems ending in `-` (`가깝-`, `가려우-`), which a
join cannot produce because Kiwi lemmas never end in `-`. A punctuated join
therefore finds nothing and falls through to the component, which is the
correct outcome. No collision was found.

**7. Adversarial input handling.** Empty and malformed analyses, a single
candidate, unsorted candidates, `last.start <= first.start`, spans past the end
of the text, and empty text all return `None` without raising. Every whitespace
form is refused, including tab, newline and non-breaking space. Repeated
substrings behave correctly. `_rank_entries` is stable for duplicates, handles
missing, unknown and `없음` levels, unknown and `None` parts of speech, and
Kiwi's irregular suffixes (`VV-R` → `동사`); 50 repeated runs produced exactly
one ordering. No defect found.

**8. `NOT_FOUND` / `UNUSABLE` / `ERROR` semantics and the error context.** A
failing dictionary still reports the unit that was being looked up, because the
implementation builds `attempted` before the probe. Verified: this was itself a
regression the implementation introduced and repaired, and the repair holds.

## Component-panel proposal

**A public engine contract is genuinely necessary — confirmed independently.**
`LookupContext.analyses` carries surface, lemma, part of speech and spans but no
gloss; `entries` holds only the primary headword; the dictionary provider lives
in the lookup child while the popup lives in the shell. No existing field can
carry per-component glosses, and no route to them exists that does not re-run
morphology across the process boundary.

**Existing consumers stay compatible — confirmed.** Every `LookupContext(...)`
construction site in `packages`, `tests` and `benchmarks` is keyword-based, so
an additive field with a default breaks nothing, and the value pickles across
the transport like the rest of the context.

**`grammatical` is not redundant.** It distinguishes "an ending, which by policy
is an explanation rather than a dictionary entry" from "a lexical component the
dictionary happens to lack". `gloss is None` cannot tell those apart, and the
approved direction depends on the distinction.

### Recommendation: **approve with named changes**

1. **Drop `surface`.** It is `LookupContext.text[start:end]`. A second copy can
   disagree with the text it came from, and nothing needs it.
2. **Define `start`/`end` explicitly**, as offsets into `LookupContext.text`,
   and **state the overlap rule**. Kiwi spans genuinely overlap — `예뻤어요`
   yields `예쁘` [0,2) and `었` [1,2) — and `TokenAnalysis` already documents
   that consumers must not require disjoint spans. A panel that renders
   components side by side will mis-highlight unless the contract says whether
   `components` may overlap or must be normalized to display spans. This is the
   most important gap in the proposal.
3. **State ordering and bounds as invariants**: ordered by `start`, offsets
   within `text`, and whether the components must cover the whole surface.
4. **Say which entry `gloss` comes from.** `초대` has two homographs with
   different glosses, and this bundle established that choosing between them is
   *commonality ordering, not contextual disambiguation*. `gloss: str | None`
   silently commits to one reading with no provenance. Either carry the
   originating `entry_id`, or document the rule as "the first sense of the
   first-ranked entry" and accept it explicitly.
5. **State the new dictionary-call bound.** "One query per lexical component"
   replaces today's verified "at most two" with "at most two plus one per
   component". Give it an explicit cap and say whether it is lazy, so the
   guarantee stays testable — and settle finding 4 in the same design.

Keep `lemma`, `start`, `end`, `gloss`, `part_of_speech` and `grammatical`.
Nothing here was implemented: `LexicalComponent` does not exist in the
repository and `LookupContext` is unchanged.

## What this review did not establish

- Equivalence was measured against a **reconstruction of the base module**
  extracted from `9c4cfea` and import-rewritten, not against a full base
  checkout.
- The 3,812 figure counts **presence of the joined form in KRDICT**, not that
  each recovered entry is the reading a reader wanted. It was measured on
  headwords, not on hovered running text.
- **No live hover was performed**, and the popup was exercised only through the
  existing offscreen and native suites.
- One machine, one KRDICT build, macOS only.

## Gates after this review's change

```
pytest                -> 2012 passed, 2 skipped   (2010 before; +2 hardening tests)
pytest --suite native -> 72 passed
ruff                  -> All checks passed
mypy                  -> Success, 272 source files
```

## Verdict

**Accept, with the hardening applied.** The bundle does what it claims: the
whole-form preference is generic and evidence-backed, the homograph correction
uses only signals the lookup already computed, the ≤2 call bound and the
acquisition parity hold, and the exclusions and privacy rules were respected.
The implementation was also right to report that `초대받다` does not exist rather
than work around it.

One real defect was found and fixed — a join that dropped surface characters and
answered a different word confidently, in 67 measured cases. Two published
numbers were corrected. Two items are deferred with triggers, three dismissed
with evidence. The component panel remains correctly blocked on human
architecture approval, recommended **approve with the five named changes above**.
