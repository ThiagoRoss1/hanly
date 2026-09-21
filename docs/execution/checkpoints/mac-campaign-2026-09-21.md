# Checkpoint — authorized macOS campaign (component panel, Wave 5 AX, Wave 7 research)

**Authorized:** 2026-09-21, one continuous Phase A campaign with three internal
boundaries. Phase B review is **not** part of this run.
**Branch/worktree:** `visual/interface-update`, existing worktree, no new branch.
**Required ancestors preserved unchanged:** `0ec5008`, `22bb4be`.
**Interpreter:** `.venv/bin/python` (CPython 3.13.11), macOS 26.6.2.

Entry state: `2012 passed, 2 skipped`; ruff clean; mypy clean, 272 source files.

---

## Boundary 1 — contextual `LexicalComponent` panel

### Approved public contract and why it is necessary

The human approved a public engine contract change on 2026-09-21. The necessity
was established in the previous bundle's Phase B review and re-confirmed here:
component glosses are dictionary data, the dictionary provider lives in the
lookup child, and the popup lives in the shell. `LookupContext.analyses` carries
surface, lemma, part of speech and spans but **no gloss**; `entries` carries only
the primary headword. No existing field can hold per-component glosses, and the
only alternative — the desktop calling back per component — re-runs morphology
across the process boundary and is the forbidden reconstruction.

```python
@dataclass(frozen=True)
class LexicalComponent:
    lemma: str
    start: int
    end: int
    gloss: str | None = None
    part_of_speech: str | None = None
    grammatical: bool = False

LookupContext.components: tuple[LexicalComponent, ...] = ()
```

### Invariants recorded before the change

1. `surface` is **not** duplicated; it is `LookupContext.text[start:end]`.
2. `start`/`end` are character offsets into `LookupContext.text`, and every
   component satisfies `0 <= start < end <= len(text)`.
3. Components are ordered by `start`, stable in morphology order for ties.
4. Components **may overlap** and need not cover the whole text. Kiwi's
   overlapping spans are legitimate — `예뻤어요` yields the lexical `예쁘다`
   [0,4) together with the grammatical `었` [1,2) and `어요` [2,4).
5. Where overlapping components contain the cursor, the **lexical** component is
   preferred for selection and highlighting; the grammatical component is
   retained as annotation.
6. `grammatical=True` marks a grammatical ending, distinguishing it from a
   lexical component that merely has no dictionary gloss.
7. A gloss is the first sense of the first entry under the existing
   POS/commonality/stable-provider ordering. It is **not** contextual
   sentence-level disambiguation.
8. Components are produced inside `LanguagePipeline`, from the same morphology
   and dictionary computation that produced the answer.
9. The contract stays acquisition-neutral: no AX, UIA, DOM, screen geometry or
   desktop lifecycle type enters `hanly`.

### Approved dictionary-query bound

Five deduplicated queries per lookup, in order: the exact raw surface, the
reconstructed whole form, then up to three distinct lexical-component lemmas
(cursor-selected component first, then morphology order). Duplicates are cached
within the lookup and cost nothing.

### Implemented

| Piece | Where |
|---|---|
| `LexicalComponent`, exported | `hanly/contracts.py`, `hanly/__init__.py` |
| `LookupContext.components` | `hanly/contracts.py` |
| `_DictionaryProbes` — deduplicated, capped at five | `hanly/language_pipeline.py` |
| Exact-surface probe before any reconstruction | `hanly/language_pipeline.py` |
| `_components` / `_lexical_components` / `_grammatical_components` | `hanly/language_pipeline.py` |
| `PopupComponent` and `_popup_components` | `hanly_app/popup.py` |
| `HOW THIS FORM IS BUILT` panel | `hanly_app/qt_popup.py` |

**The exact-surface probe settles the copula misjoins.** `깜짝이야`, `고소득층`,
`고차원적`, `구시대적` and `꿀꿀이` are KRDICT headwords in their own right and are
now answered as themselves rather than as the different word their morphology
reconstructed. The Phase B hardening against `고소득층 → 고소득` is retained and
still guards the case where the surface itself is absent.

**A surface the dictionary lists whole keeps no lexical split.** Naming the
first syllable of `고소득층` as `고 · the late` would explain the word wrongly, so
when the answer *is* the surface its lexical parts are dropped and only the
grammatical annotations remain.

### Evidence

- 4,530 real-provider lookups across a 1,500-word random KRDICT sample plus the
  named corpus: **maximum 4 distinct dictionary queries** against the bound of
  five, **zero** duplicate queries issued, and every component satisfied
  `0 <= start < end <= len(text)` and arrived ordered by `start`.
- `초대받았어요` — index 0/1 answer `초대 · 招待 · invitation`, index 2–5 answer
  `받다 · receive; get`, and both retain the decomposition
  `초대 · invitation + 받다 · receive + 었 · tense or honorific + 어요 · sentence ending`.
- `학교` carries no components, so the panel does not appear.
- `예뻤어요` keeps the overlapping spans `예쁘다` [0,4), `었` [1,2), `어요` [2,4).
- Privacy: a normal trace of a `초대받았어요` lookup contains none of the
  recognized text, component lemmas or glosses.

### Focused tests

| Suite | Result |
|---|---|
| `tests/test_lexical_components.py` (new, 22) | passed |
| `tests/test_popup.py` (+4) | 24 passed |
| `tests/krdict/test_whole_form.py` (+9, real providers) | 35 passed |
| `tests/test_core_contracts.py` (export surface, context fields) | 48 passed |
| `pytest --suite native` | 72 passed |
| Full portable suite | 2047 passed, 2 skipped |
| ruff / mypy | clean, 273 source files |

### Architecture synchronization

**No invariant changed, so none was edited.** `RF-INV-13` (surface text plus a
cursor index is the whole input to the language stage) and `CA-INV-16` (the
language stage is acquisition-neutral) both remain true: `components` is
additive output produced by that same stage, and no platform type entered
`hanly`. No ID was renumbered and no visual companion was touched.
`docs/CODE-MAP.md` names the new contract and the five-query bound.

### `TextSelection.source` — decision recorded, wiring in Boundary 2

**Decision: keep it, and give it a consumer.** Wave 5 is the first real
non-pixel client and must produce direct-versus-fallback evidence per target,
which is exactly a narrow, app-neutral attribution label. It is wired to the
lookup trace in Boundary 2 and verified consumed there. It stays a plain string
set by whoever built the selection — not a registry, not a platform handle, and
nothing about AX enters the engine. If Boundary 2 had not consumed it, the
alternative was removal.

### Known limitations

- Component glosses are the first sense of the first-ranked entry. That ordering
  is commonality plus part-of-speech, **not** contextual disambiguation, so a
  component gloss can name a less apt homograph.
- Grammatical labels come from a Kiwi-tag table in the engine, which extends the
  deferred finding about adapter vocabulary living in the neutral stage.
- The panel was exercised through the offscreen and native suites; **no live
  hover was performed**.

**Commit:** `feat: show lexical component context`
**Next boundary ready:** yes.

