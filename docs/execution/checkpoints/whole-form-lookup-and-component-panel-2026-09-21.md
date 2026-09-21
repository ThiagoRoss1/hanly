# Checkpoint — Whole-form lookup and contextual component panel

**Spec:** `docs/execution/plans/whole-form-lookup-and-component-panel-2026-09-21.md`
**Authorized scope:** this bundle only, between Wave 4 and Wave 5. Wave 5 is out of scope.
**Branch/worktree:** `visual/interface-update`, existing worktree reused, base `9c4cfea`.
**Interpreter:** `.venv/bin/python` (CPython 3.13.11).

Status: **complete for the contract-free part; stopped at the public-contract
boundary for the component panel.**

---

## Entry state

```
pytest -> 1966 passed, 2 skipped
ruff / mypy -> clean, 270 source files
```

## Evidence gate (real Kiwi, real KRDICT)

Recorded before any change. The full transcript is in the spec §2; the load-bearing
results:

| Question | Answer |
|---|---|
| Does Kiwi produce `초대받다`? | **No.** Two units: `초대` NNG 0–2, `받다` VV 2–6 |
| Does KRDICT contain `초대받다`? | **No.** Zero entries; only 35 `…받다` headwords exist |
| Is the complete-form rule supported anyway? | **Yes.** Kiwi splits 4,125 real KRDICT headwords; joining recovers a real entry for **3,908 (94.7%)** |
| Does Kiwi already merge some compounds? | **Yes.** `인정받았어요` → `인정받다`, which KRDICT holds |
| Why is `初代` promoted over `招待`? | `ORDER BY e.id`; `初代` is id 318, `招待` id 319 |
| Is there a generic ordering signal? | **Yes.** KRDICT's own `vocabulary_level`: `招待` 초급, `初代` 고급 |
| Before-state | 13 surfaces × every index = 48 positions, **0 direct/pixel parity failures** |

**The approved direction's representative presentation cannot be produced.**
`초대받다 / be invited` is not in the shipped dictionary, and composing that
translation is forbidden. For this surface the approved fallback governs, so the
primary result is the cursor-selected component and the homograph fix is what
makes it correct.

## Implemented

Both changes live in the one shared `LanguagePipeline`; no public contract changed.

| Piece | Where |
|---|---|
| `_complete_form` — join the leading surface to the final unit's lemma, never across whitespace | `hanly/language_pipeline.py` |
| `_resolve_entries` — probe the complete form once, else the cursor component | `hanly/language_pipeline.py` |
| `_rank_entries` — order homographs by POS match, then `vocabulary_level`, then entry id | `hanly/language_pipeline.py` |

The dictionary is asked **at most twice** per lookup. The whole-form candidate
spans the entire form, which is what keeps the primary result stable while the
cursor moves inside it.

## Measured behaviour change

Same 48 positions, before vs after: **40 unchanged, 8 changed**, all improvements.

| Surface | Before | After |
|---|---|---|
| `초대받았어요` idx 0–1 | `초대 · 初代 · first` | **`초대 · 招待 · invitation`** |
| `가공식품` | `가공` | **`가공식품 · processed food`** |
| `가까워지다` | `가깝다` | **`가까워지다 · approach; draw near`** |
| `가로놓이다` | `가로` | **`가로놓이다 · lie across`** |
| `책상` (fixture) | `상` | **`책상`** |
| `차를` / `눈이` / `말이` | primary already right | unchanged primary, remaining homographs reordered |

Unchanged: `사과했어요`→`사과하다`, `예뻤어요`→`예쁘다`, `떨어뜨렸어요`→`떨어뜨리다`,
`깨뜨렸습니다`→`깨뜨리다`, `학교`→`학교`, `인정받았어요`→`인정받다`, and
`책을 읽는` still selects the two words independently.

Latency, real providers, n=400:

| Surface shape | p50 | p95 | dictionary calls |
|---|---|---|---|
| split, two units (`초대받았어요`) | 0.118 ms | 0.133 ms | 2.00 |
| single unit (`사과했어요`) | 0.097 ms | 0.116 ms | 1.00 |
| simple noun (`학교`) | 0.050 ms | 0.056 ms | 1.00 |

The probe costs ~21 µs on split forms against a hover budget dominated by dwell
(150 ms) and OCR (~120 ms).

## Public-contract boundary — STOPPED, approval requested

The contextual component panel needs a **gloss per component**. The popup
already renders the structural decomposition from `LookupContext.analyses`
(`popup.py`, `PopupAnalysisPiece`, shown as `READ AS` / `WORD ANALYSIS`), so the
breakdown itself is not what is missing — only the glosses are, and those are
dictionary data producible only in the engine.

Rejected alternatives: the desktop calling `lookup_selection` per component
re-runs morphology, multiplies pipe round-trips and hover latency, and is the
forbidden after-the-fact reconstruction; carrying product data in `diagnostics`
abuses a debugging channel. No existing field can hold it.

**Smallest proposed change**, for human architecture approval:

```python
@dataclass(frozen=True)
class LexicalComponent:
    surface: str            # the characters this component covers
    lemma: str
    start: int
    end: int
    gloss: str | None = None          # None for a grammatical component
    part_of_speech: str | None = None
    grammatical: bool = False         # an ending is an explanation, not an entry

# LookupContext gains exactly one field:
components: tuple[LexicalComponent, ...] = ()
```

Populated only when the surface holds more than one component, so a simple word
carries an empty tuple and the popup shows no panel. Grammatical components
carry a label rather than a dictionary entry. Component glosses come from the
same bounded dictionary work, one query per lexical component, and the field is
additive so every existing consumer is unaffected.

**Nothing of this proposal is implemented.** `LexicalComponent` does not exist
in the repository, and `LookupContext` is unchanged.

## Gates

```
pytest              -> 2010 passed, 2 skipped   (entry: 1966 passed, 2 skipped)
pytest --suite native -> 72 passed
ruff                -> All checks passed
mypy                -> Success, 272 source files
```

## Privacy state

Unchanged. This bundle touched no capture, export, or trace persistence. The
evidence used the gitignored `data/generated/krdict.sqlite3` and retained
nothing. No screenshots, frozen exports, or benchmark artifacts were written to
the repository. Evidence scripts and the before/after JSON stayed in the
session scratchpad.

## Files touched

Engine: `packages/hanly/src/hanly/language_pipeline.py`.
Tests: `tests/test_whole_form_lookup.py` (new), `tests/krdict/test_whole_form.py`
(new), `tests/test_language_pipeline.py`, `tests/test_lookup_pipeline.py`,
`tests/test_lookup_evidence.py`, `tests/test_app_composition.py`.
Docs: the spec, this checkpoint, and the Review Handoff.

`hanly-app` is untouched.

## Blockers

The component panel is blocked on human architecture approval of the
`LookupContext.components` addition above.

## Exact next action

**Stop.** This bundle ends at
`docs/execution/review-handoffs/whole-form-lookup-and-component-panel-2026-09-21.md`.
Phase B deep review and Wave 5 are separate authorizations.
