# macOS campaign Review Handoff — component panel, Wave 5 AX, Wave 7 verdict

## Campaign

- One authorized Phase A campaign with three internal boundaries, run on
  2026-09-21 by Claude Opus 5, macOS 26.6.2, `.venv/bin/python` 3.13.11.
- Branch `visual/interface-update`, existing worktree. Base `22bb4be`.
- Live ledger: `docs/execution/checkpoints/mac-campaign-2026-09-21.md`.
- Earlier context is **referenced, not repeated**: the Wave 4 seam handoff
  (`wave-4-language-seam-2026-09-21.md`) and the whole-form handoff with its
  Phase B outcome (`whole-form-lookup-and-component-panel-2026-09-21.md`).
- **No Phase B review was performed, and this campaign did not review itself.**

Commits, in order, none amended or pushed:

| Hash | Subject |
|---|---|
| `573b115` | feat: show lexical component context |
| `c083d62` | feat: add macos accessible text acquisition |
| `b0851a8` | docs: record OCR research verdict |

`0ec5008` and `22bb4be` remain separate, unchanged ancestors.

---

## 1. `LexicalComponent` and the component panel

**The approved public contract was added as specified**: `LexicalComponent`
(lemma, start, end, gloss, part_of_speech, grammatical) and an additive
`LookupContext.components`. `surface` is deliberately absent and derived from
`text[start:end]`. Offsets index `LookupContext.text`, components are ordered by
`start`, may overlap, and need not cover the text. The export-surface and
context-field tests were updated deliberately.

**The dictionary budget is five deduplicated queries**: the exact raw surface,
the reconstructed whole form, then up to three lexical components with the
cursor-selected one first.

**The exact-surface probe settled the four deferred copula misjoins.** `깜짝이야`,
`고소득층`, `고차원적`, `구시대적` and `꿀꿀이` are KRDICT headwords in their own
right and are now answered as themselves. The Phase B hardening against
`고소득층 → 고소득` is retained for the case where the surface itself is absent.

**A surface the dictionary lists whole keeps no lexical split**, because naming
the first syllable of `고소득층` as `고 · the late` explains the word wrongly.
Grammatical annotations are kept in that case.

Evidence: 4,530 real-provider lookups reached a **maximum of 4** distinct
queries against the bound of five, with **zero** duplicates and every component
satisfying `0 <= start < end <= len(text)` in `start` order. `초대받았어요`
answers `초대 · 招待 · invitation` near `초대` and `받다` near `받았어요`, both
retaining the full decomposition. `학교` carries no components. `예뻤어요` keeps
the overlapping `예쁘다` [0,4) / `었` [1,2) / `어요` [2,4).

New/changed tests: `tests/test_lexical_components.py` (22),
`tests/krdict/test_whole_form.py` (+9 real-provider), `tests/test_popup.py`
(+4). Architecture invariants were **not** touched: `RF-INV-13` and `CA-INV-16`
both remain true, nothing was renumbered, and no visual companion changed.

**`TextSelection.source` — kept, and now consumed.** Wave 5 is the first real
non-pixel client, and the lookup trace records which acquisition produced a
selection. A test asserts the label is emitted and the word is not. It remains a
plain string: not a registry, and no AX detail enters the engine.

## 2. Wave 5 — macOS direct-text acquisition

Every rule lives in the platform-neutral `DirectTextCoordinator`; the AX adapter
only reads. `hanly` is untouched.

Real evidence on this machine, accessibility granted:

| Target | Outcome |
|---|---|
| TextEdit (`AXTextArea`) | **52/66 on-text points direct**, all three Korean lines correct, p50 **0.514 ms** |
| TextEdit, below the last line | **40/40 refused** as `not_containing` |
| Safari, local Korean page | **0 direct** — `AXValue` exposes the line but `AXRangeForPosition` is unsupported |
| Discord (Electron) | **0 direct** over 504 points; capability probed only, no content read |
| Preview, raster Korean image | **396/396** unsupported; OCR retained |

**The nearest-but-not-containing failure was observed in the wild**: below the
last line, AX returns index 0 of line 1 whose rectangle is ~60 px away. Without
containment, hovering blank space would confidently define `초대`.

**Timeout measured before declaring a default**: warm n=300 gave p50 0.592 ms,
p95 2.574 ms, p99 5.558 ms, max 7.099 ms, **0 over 40 ms**; the cold first call
cost 71.37 ms and is discarded once. `DEFAULT_TIMEOUT_MS = 40` is a development
default with a measured basis, not a product SLA.

New tests: `tests/test_text_acquisition.py` (19) and
`tests/test_direct_text_routing.py` (23) — direct success, no OCR call, a
validated dictionary miss that does not reach OCR, all eleven refusals leaving
the capture path to run, supersession, transport both ways, cache separation,
and trace attribution without the word.

## 3. Wave 7 — research verdict

**Change nothing now.** Both shipped backends were re-run through the existing
Wave 2 corpus: Vision **1.000** target-surface correct with a 0.000 error rate
and 45.8 MB growth; EasyOCR **0.375** with a 0.215 syllable error rate and
1,010 MB. Region recall is 1.000 for both, so the gap is recognition alone.

A candidate evaluated today would measure an eight-case synthetic corpus rather
than a model. The report names the dataset, labeling, cross-platform, licensing
and budget evidence a future HanlyOCR decision requires. Nothing in production,
provisioning or packaging changed.

`docs/execution/reports/ocr-research-verdict-2026-09-21.md`.

## 4. Convergence gates

```
pytest                                 -> 2089 passed, 2 skipped
pytest --suite native                  -> 72 passed
pytest --suite packaged                -> 3 passed
package boundary / exports / packaging -> 139 passed
privacy and trace serialization        -> 62 passed
ruff                                   -> All checks passed
mypy                                   -> Success, 277 source files
```

Worktree clean. No failure was dismissed as pre-existing: every failure during
the campaign was an expectation this work changed, reproduced and classified
before being updated. Those were the four promiscuous dictionary doubles that
answered any lemma, the stage-count assertions that now see two dictionary
probes, and the export-surface and context-field lists.

## 5. Deferred findings

1. **Web and Electron content has no direct path on macOS.** WebKit and Chromium
   expose no usable parameterized text range, so Korean websites and Discord
   still use OCR. *Revisit:* Wave 6's browser evaluation, which should decide
   whether an `AXValue`-plus-element-bounds path can ever be safe, given it would
   require estimating the cursor index.
2. **The 71 ms cold accessibility call** is paid once per process and falls back
   to OCR. *Revisit:* if a first hover after launch is observed to feel wrong.
3. **Component glosses are commonality-ordered, not contextually disambiguated.**
   A component gloss can name a less apt homograph. *Revisit:* only with a
   generic contextual signal; none exists today.
4. **Adapter vocabulary in the neutral language stage** — Kiwi tag families,
   KRDICT part-of-speech strings and now the grammatical-label table live in
   `language_pipeline.py`, and `_tag_family` is duplicated with
   `kiwi_provider.py`. It degrades safely to no signal. *Revisit:* when a second
   morphology or dictionary provider is added.
5. **No live hover through the real desktop application** was performed in this
   campaign. *Revisit:* at desktop integration validation.

## 6. Wave 6 — Windows continuation

**Wave 6 is `NOT STARTED — requires a real Windows environment.`** No Windows
code, abstraction or placeholder exists in this repository, deliberately.

**Required starting commits.** Branch `visual/interface-update` at `b0851a8`,
with `573b115` and `c083d62` present. Do not rebase; Wave 6 branches from there.

**Environment.** Windows 10/11 with a real display and a normal user account.
Python 3.13, `python -m pip install --group dev`,
`python -m pip install --editable packages/hanly`,
`python -m pip install --editable "packages/hanly-app[runtime]"`. A built
`krdict.sqlite3` via `HANLY_KRDICT_DB` or `data/generated/`. No pyobjc; UIA is
reached through `comtypes`/`ctypes`, matching the ctypes-only convention the
macOS adapters follow.

**Plan and acceptance.** Implement the second platform against the *existing*
`DirectTextCoordinator` without generalizing it unless the second
implementation proves a real need. Acceptance: Windows automatically uses valid
direct text and invisibly falls back to OCR with no user mode selection; a
validated dictionary miss does not invoke OCR; the macOS behaviour is unchanged.

**Expected boundary.** `packages/hanly-app/src/hanly_app/text_acquisition_uia.py`
exposing one class satisfying `DirectTextProvider` — `read_at(point, *, timeout_ms)
-> DirectText | None`. It returns `DirectText` with `text`, `cursor_index`,
`bounds` in the same screen coordinates the pointer uses, `secure`, and `role`.
**Every acceptance rule stays in `text_acquisition.py`**; the adapter adds none.
`default_text_acquisition()` gains a `win32` branch beside the existing `darwin`
one, and nothing else in the routing changes.

**Reused common tests.** `tests/test_text_acquisition.py` and
`tests/test_direct_text_routing.py` are platform-neutral and must pass
unchanged; they already cover the eleven refusal reasons, supersession, the
no-OCR guarantee, the dictionary-miss rule, cache separation and transport.

**Windows-specific tests to add.** Per-monitor-v2 DPI awareness and physical vs
logical coordinate conversion; multi-monitor origins including a negative-origin
secondary display; `UIA_IsPasswordAttribute` and protected/elevated windows;
integrity-level refusal against an elevated process; `TextPatternRangeEndpoint`
containment and `RangeFromPoint` returning the nearest range; COM apartment
initialization on the hover thread and teardown without leaking; a bounded call
that blocks past the deadline.

**Coverage matrix to record.** Edge/Chrome on a Korean site, an iframe within
it, Discord/Electron, a native text control (Notepad or WordPad), a raster
subtitle or image that must fall back, canvas/WebGL, and one custom control
exposing no text pattern. For each: direct or fallback reason, correctness,
permission/integrity state, and p50/p95.

**Evidence requirements.** Per-application direct-versus-fallback reason and
correctness; cold and warm p50/p95 from the same measurement method used here;
an explicit statement wherever a target application or permission was
unavailable, rather than a fabricated result. Compare direct text with OCR on
the same target only where safely repeatable.

**Privacy verification.** A trace of a direct lookup must contain the
acquisition label and outcome but no recognized text; secure fields must be
refused by reason and carry nothing; Freeze stays memory-only; only explicit
Export may persist pixels or text, beneath the gitignored artifact root.

**Commit and review boundaries.** One Phase A commit,
`feat: add windows accessible text acquisition`, configured human author, no
attribution trailers, no push. End at a Wave 6 Review Handoff. Phase B remains
separate and human-authorized.

## Review assignment

Human-selected. Not started. This handoff prepares the review; it does not
perform one.
