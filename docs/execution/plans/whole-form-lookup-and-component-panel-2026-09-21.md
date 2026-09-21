# Whole-form lookup and contextual component panel

Issue-local execution specification. A pre-Wave-5 bundle between Wave 4
(acquisition-neutral language seam) and Wave 5 (native direct-text
acquisition). It does not modify the text-acquisition master plan.

- **Date:** 2026-09-21
- **Branch:** `visual/interface-update`, existing worktree, base `9c4cfea`.
- **Tier:** Gate — it touches the language stage, dictionary ordering, and the
  popup, and it reaches a public-contract boundary.

## 1. Reported behaviour

For the recognized surface `초대받았어요` the popup shows `초대` promoted to the
`初代` homograph ("first generation") rather than `招待` ("invitation"), and a
cursor near `받았어요` shows `받다`. OCR is correct; the defect is whole-form
selection, homograph ordering, and presentation.

## 2. Evidence gathered before implementation

Real `KiwiProvider` and real `KRDICTProvider`
(`data/generated/krdict.sqlite3`, 56,555 entries). Full transcript in the
checkpoint.

**E1 — Kiwi never produces `초대받다`.** `JOIN_V_SUFFIX` yields two lexical
units: `초대` (NNG, span 0–2) and `받다` (VV, span 2–6). Raw tokens are
`초대/NNG`, `받/VV-R`, `었/EP`, `어요/EF`.

**E2 — KRDICT does not contain `초대받다`.** The probe returns zero entries.
KRDICT holds only 35 `…받다` headwords, and this is not one of them. The
representative presentation in the approved direction (`초대받다 / be invited`)
therefore **cannot be produced from the shipped dictionary** without inventing
a composed translation, which is forbidden. For this surface the approved
fallback rule governs: the primary result is the cursor-selected component.

**E3 — the complete-form rule is nonetheless strongly supported.** Over the
29,145 space-free KRDICT headwords of length 3–7, Kiwi splits **4,125** into
two or more lexical units, and joining the leading surface to the final lemma
reconstructs a genuine dictionary entry for **3,908 of them (94.7% of splits,
13.4% of all such headwords)** — `가공식품`, `가까워지다`, `가로놓이다`,
`가까이하다`. Hanly currently answers these with a fragment. `초대받다` is one of
the 5% where the joined form genuinely is not in the dictionary.

**E4 — Kiwi already merges lexicalized compounds.** `인정받았어요` is a single
candidate `인정받다`, which KRDICT holds ("be recognized"). That path already
works and must not regress.

**E5 — the homograph defect is ordering by row id.** `KRDICTProvider` orders
`ORDER BY e.id`. For `초대`, `初代` is id 318 and `招待` is id 319, so the rarer
sense wins on insertion order alone. KRDICT ships `vocabulary_level`
(초급/중급/고급/없음) on every entry; `招待` is 초급 and `初代` is 고급. Level
ordering also yields 눈→eye, 배→abdomen, 차→tea, 말→speech, 받다→receive.

**E6 — before-state preserved.** 13 surfaces × every cursor index = 48
positions, recorded through both acquisition paths with **0 parity failures**.

## 3. What this bundle changes

**C1 — whole-form preference (no contract change).** When morphology reports
two or more lexical units, the language stage probes the dictionary **once**
for the joined complete form. If it exists, it becomes the primary result and
stays stable while the cursor moves anywhere inside that form. If it does not,
behaviour is exactly today's cursor-selected component.

**C2 — generic homograph ordering (no contract change).** Entries for one
lemma are ordered by two signals that already exist in the observed
computation: whether the entry's part of speech matches the morphology unit's
part of speech, then KRDICT's own `vocabulary_level`, then entry id for
stability. No word-specific override, no English-keyword matching, no semantic
heuristic.

**C3 — contextual component panel.** Blocked on a public-contract decision;
see §5.

## 4. Non-goals

Wave 5, native acquisition, OCR providers, Vision scaling, ROI, capture, gate
and cache behaviour, sentence translation, fallback ordering, dictionary-miss
semantics, unrelated popup redesign, `TextSelection.source`, and general Korean
word segmentation are all out of scope. No-space strings such as
`초대받았어요깨뜨리다` are exploratory evidence only.

## 5. Public-contract boundary reached

The component panel needs, per component, a surface, a lemma, a **gloss**, and
whether the component is grammatical. `LookupContext.analyses` already carries
surface, lemma, part of speech, and spans — everything except the glosses.
Glosses are dictionary data and can only be produced where the dictionary
provider lives, which is the engine inside the lookup child.

The alternatives were rejected: having the desktop call `lookup_selection` per
component re-runs morphology, multiplies pipe round-trips and hover latency,
and is the forbidden after-the-fact reconstruction; and carrying product data
in `diagnostics` abuses a debugging channel. No existing field can hold it.

Per the authorized rule this bundle **stops before making that change** and
requests explicit human architecture approval. The proposal is in the
checkpoint.
