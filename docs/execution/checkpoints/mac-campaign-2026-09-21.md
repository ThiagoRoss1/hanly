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

---

## Boundary 2 — Wave 5, macOS direct-text acquisition

### Implemented

| Piece | Where |
|---|---|
| `Outcome`, `DirectText`, `Acquisition`, `DirectTextCoordinator` — every rule, platform-neutral | `hanly_app/text_acquisition.py` |
| `default_text_acquisition()` — macOS only, `None` elsewhere | `hanly_app/text_acquisition.py` |
| `AccessibilityTextProvider` — AX through `ctypes`, no Objective-C dependency | `hanly_app/text_acquisition_ax.py` |
| `LookupRequest.selection`, `image` now optional | `hanly_app/lookup_controller.py` |
| `LookupController.submit_selection` | `hanly_app/lookup_controller.py` |
| Direct branch that never calls OCR, and its own cache identity | `hanly_app/composition.py` |
| Selection-carrying transport message | `hanly_app/lookup_process.py` |
| `_submit_direct_text` before capture | `hanly_app/hover_lookup.py` |

Every rule lives in the coordinator, not the adapter, so a second platform
cannot relax one by implementing its reader differently. `hanly` is untouched:
no AX, geometry or lifecycle type entered the engine.

### Real evidence, macOS 26.6.2, accessibility granted

| Target | Result |
|---|---|
| **TextEdit** (native `AXTextArea`) | **52/66 on-text points direct**, all three Korean lines read correctly with correct cursor indices. p50 **0.514 ms**, p95 **0.879 ms** |
| **TextEdit, empty space below the text** | **40/40 refused** as `not_containing` |
| **Safari** (local Korean page) | **0 direct.** `AXStaticText` exposes the whole line through `AXValue` but **not** `AXRangeForPosition`, so the cursor index cannot be determined without guessing. Falls back to OCR |
| **Discord** (Electron) | **0 direct** over 504 points; roles `AXScrollArea`/`AXWebArea`/`AXGroup`. Falls back to OCR. Probed for capability only — no message content was read |
| **Preview** showing a raster Korean image | **396/396** `unsupported`; OCR retained exactly as required |
| **Canvas/WebGL** (canvas on the Safari page) | Covered by the Safari result: no direct text, OCR retained |

**The nearest-but-not-containing failure was observed in the wild.** Below the
last line of a TextEdit document, `AXRangeForPosition` returns index 0 and the
adapter reads line 1, whose rectangle is ~60 px away. Without the containment
check, hovering empty space would confidently define `초대`. Every such point was
refused.

### Timeout, measured before declaring a default

n=300 warm calls against TextEdit: p50 **0.592 ms**, p95 **2.574 ms**,
p99 **5.558 ms**, max **7.099 ms**, and **0 calls exceeded 40 ms**. The first
call after process start cost **71.37 ms** and would be discarded once, falling
back to OCR safely. `DEFAULT_TIMEOUT_MS = 40` is therefore a development default
with a measured basis — roughly 7× the observed p99 — not a product SLA.

### Focused tests

| Suite | Result |
|---|---|
| `tests/test_text_acquisition.py` (new, 19) | passed — direct, no provider, denied permission, unsupported, secure, not-containing, ambiguous geometry, index past the text, empty, non-Korean, timeout, late answer, exception, supersession |
| `tests/test_direct_text_routing.py` (new, 23) | passed — no OCR call on the direct path, dictionary miss without OCR, captured path unchanged, supersession, trace attribution without the word, cache separation, transport both ways, all 11 refusals leaving capture to run |
| Full portable suite | 2089 passed, 2 skipped |
| `pytest --suite native` | 72 passed |
| ruff / mypy | clean, 277 source files |

### Privacy

`Freeze` is untouched and remains memory-only; no export path changed. The
direct-text trace event carries the `accessibility` label and the outcome
reason, never the word — asserted by a test. The direct cache key holds the
word, so `_cache_key_fingerprint` hashes it exactly as it hashes pixels. A
secure field is refused by reason and carries no text at all.

### Known limitations

- **Web and Electron content has no direct path on macOS today.** This is a
  WebKit/Chromium accessibility limitation, not a missing rule, and it is the
  single most important coverage finding for Wave 6.
- The 71 ms cold call is paid once per process and falls back to OCR. No prewarm
  was added.
- `AXLineForIndex`/`AXRangeForLine` take a `CFNumber` while the other
  parameterized attributes take an `AXValue`; that asymmetry is the one place
  this binding is easy to get wrong, and it silently returned nothing until
  fixed.
- Evidence is one machine, one macOS version, one display scale.
- No live hover through the real desktop application was performed; the runtime
  path is covered by tests, and the adapter by direct measurement.

**Commit:** `feat: add macos accessible text acquisition`
**Next boundary ready:** yes.

---

## Boundary 3 — Wave 7 bounded research verdict

Evidence-only. Nothing in production changed; no candidate was added, no model
downloaded or trained, no selector or packaging touched.

Both shipped backends were re-run through the existing `ocr-campaign` path
against the local 8-case Wave 2 corpus (1 warmup, 3 samples, `ocr-only`).

| | Vision | EasyOCR |
|---|---|---|
| Target surface correct | **1.000** | 0.375 |
| Hangul syllable error rate | 0.000 | 0.215 |
| Character error rate | 0.000 | 0.177 |
| Target region recall | 1.000 | 1.000 |
| Warm p50 / p95 | 23.0 / 27.2 ms | 25.7 / 40.4 ms |
| Peak RSS growth | 45.8 MB | 1,010.4 MB |

**Verdict: change nothing now.** The incumbent already scores 1.000 on this
corpus, so a candidate evaluated today would measure the corpus rather than the
model. The report names the dataset, labeling, cross-platform, licensing and
budget evidence a future HanlyOCR decision needs.

Report: `docs/execution/reports/ocr-research-verdict-2026-09-21.md`.
Raw runs stayed under the gitignored `artifacts/benchmarks/runs/`.

**Commit:** `docs: record OCR research verdict` (`b0851a8`).

---

## Convergence gates

```
pytest                  -> 2089 passed, 2 skipped
pytest --suite native   -> 72 passed
pytest --suite packaged -> 3 passed
package boundary / exports / packaging -> 139 passed
privacy and trace serialization        -> 62 passed
ruff  -> All checks passed
mypy  -> Success, 277 source files
```

Worktree clean. No failure was dismissed as pre-existing; the only failures
encountered during the campaign were expectation changes caused by this work,
each reproduced and classified before being updated.

## Commit history

```
b0851a8 docs: record OCR research verdict
c083d62 feat: add macos accessible text acquisition
573b115 feat: show lexical component context
22bb4be fix: harden whole-form dictionary selection     (unchanged ancestor)
0ec5008 feat: prefer whole-form dictionary results      (unchanged ancestor)
9c4cfea test: keep retained evidence tests portable
```

Nothing was amended, squashed, rebased or pushed.

## Wave 6

**NOT STARTED — requires a real Windows environment.** No Windows code,
abstraction or placeholder was created. The continuation procedure is in the
Review Handoff.
