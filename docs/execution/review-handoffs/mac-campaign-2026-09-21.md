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

---

# Post-Bundle Review Outcome

- **Reviewer / ecosystem / date:** Claude Opus 5, single run, macOS 26.6.2,
  `.venv/bin/python` 3.13.11, 2026-09-21.
- **Scope:** `22bb4be..ae3bccc`, reviewed against the worktree and commit graph
  rather than the handoff's claims.
- **Verdict:** **Accept, with the hardening in `1dbe8e8` applied.** Three
  defects were found at the native and trace boundaries, all fixed under review
  authority. Wave 6 was not started, nothing was pushed, and no existing commit
  was amended, squashed, rebased or reordered.

## Independently reproduced

| Claim | Verdict |
|---|---|
| Component bounds, ordering and the ≤5 query bound | **Confirmed** — 14 real-provider words and 7 adversarial provider shapes (spans past the end, negative and zero-length spans, `None` spans, empty lemmas, duplicates, 6 candidates) all held `0 <= start < end <= len(text)`, stable `start` order, ≤5 distinct queries, no duplicate query |
| `초대받다` is never invented | **Confirmed** — absent from KRDICT, and never appears as a headword or component at either cursor position |
| `초대받았어요` cursor sensitivity with the decomposition retained | **Confirmed** at indices 0 and 3 |
| `예뻤어요` overlapping spans | **Confirmed** — `예쁘다` [0,4), `었` [1,2), `어요` [2,4) |
| `깜짝이야`, `고소득층`, `고차원적`, `구시대적`, `꿀꿀이` answered as themselves | **Confirmed**, 1 query each |
| Engine free of desktop/AX/geometry, `LanguagePipeline` needs no recognizer | **Confirmed** — only prose mentions; constructing it loads neither torch nor easyocr |
| Public export surface changed deliberately and minimally | **Confirmed** — `LexicalComponent` plus one additive field, both guarded by updated tests |
| Transport and pickling | **Confirmed** both ways, including hostile labels up to 100k characters |
| TextEdit containment, including blank space below the last line | **Confirmed** — 52/66 direct, and it is containment, not a threshold, that rejects the false target |
| No CoreFoundation leak | **Confirmed** — 6,000 acquisitions, **0 bytes** peak-RSS growth |
| ctypes constants and structures | **Confirmed by round-trip** — CFRange(4), CGRect(3), CGPoint(1), kCFNumberLongType(10); a wrong-type read returns `False`, not garbage |
| Wave 7 correctness figures | **Reproduced exactly** — Vision 1.000/0.000/0.000, EasyOCR 0.375/0.215/0.177, region recall 1.000 for both, 0 errors |
| Wave 7 changed no production code | **Confirmed** — `b0851a8` touches one documentation file |
| Invariant IDs synchronized | **Confirmed** — RF-INV 13/13, CA-INV 16/16, identical and in order |
| Freeze, Export, artifact tracking | **Confirmed** — nothing private tracked in any campaign commit; `artifacts/benchmarks/` ignored and empty in the index |
| Wave 6 `NOT STARTED` and no speculative UIA code | **Confirmed** |

## Fixed now — `1dbe8e8`

**1. Accessibility offsets are UTF-16 code units, not Python indices.**
`CFStringGetLength("🙂초대받았어요")` is 8 while Python's length is 7. The adapter
used the AX index directly as a Python index, so on the real line
`🙂🙂초대받았어요` in TextEdit the pointer on `초` produced `cursor_index=4`, which
is `받` — the popup would define "receive" while the reader points at
"invitation". Reproduced in the wild at x=180. Fixed conservatively: a reading
whose offsets cannot be used as Python indices is refused and the caller falls
back to OCR. Pure-Korean lines are unchanged (52 direct before and after).
Guarded by `tests/native/macos/test_text_acquisition_units.py`, confirmed to
**fail** against the reviewed implementation.

**2. The timeout was measured but never enforced.** The adapter documented that
`timeout_ms` "is not enforced here", and `_on_stable` runs on the **Qt UI
thread** via `QtHoverScheduler`'s timer, so an unresponsive target application
could hold the interface for as long as it liked while the coordinator only
discarded the answer afterwards. Fixed by giving both the system-wide element
and the hit element their own `AXUIElementSetMessagingTimeout`. Results
unchanged (52 direct, 14 not-containing).

**3. The acquisition trace copied an unbounded, unsanitised label.** A 200,000
character `source` produced a 202 KB trace event for one lookup, and a label
containing recognized text put that text into a trace which must never carry
it. Only one producer sets the field today, so this was not reachable in
production, but the guarantee rested on nobody ever putting content there.
Fixed by emitting only a bounded route label (`[A-Za-z0-9_-]{1,32}`, otherwise
`unknown`). Guarded by a parametrized test confirmed to fail against the
reviewed implementation.

## Corrected measurements and overclaims

- **The checkpoint's "18 elements support `AXRangeForPosition`" in Discord does
  not reproduce.** A finer probe of 874 points found **zero** elements
  supporting it; every point fails at the index stage. The conclusion (falls
  back to OCR) is unaffected.
- **Safari's classification is correct and now has stronger evidence than Phase
  A had.** Walking the tree — the hit `AXStaticText`, five ancestors and its
  zero children — found no element supporting the range attribute, so it is a
  WebKit limitation rather than an adapter traversal omission. No
  browser-specific workaround was implemented.
- **EasyOCR peak RSS varies run to run**: the re-run measured **889.6 MB**
  against the reported 1,010.4 MB. The reported figure is a single-run peak
  presented as a firm number; the order of magnitude and the comparison with
  Vision (47.6 MB re-measured) stand.
- Warm latency re-measured as Vision 21.1/25.7 ms and EasyOCR 26.8/40.8 ms
  against the reported 23.0/27.2 and 25.7/40.4 — ordinary variance.
- **The corpus is 8 cases, every one `local_synthetic`, one font
  (Apple SD Gothic Neo, Apple-Proprietary), zero real captures.** The verdict's
  self-imposed limitation is therefore accurate and not overstated. Both
  backends ran in `ocr-only` mode, so no staged replay is described as
  production evidence.
- The Wave 5 browser/Electron gap is correctly presented as an acquisition
  limitation, not something an OCR recognizer would solve.

## Deferred considerations

1. **The suppression rule hides roughly twice as many useful decompositions as
   misleading ones.** Of 165 sampled verbatim-headword splits, **114 (69%)** had
   parts that are all real dictionary words whose surfaces match their spans —
   `두통거리` (두통 + 거리), `동력선` (동력 + 선), `고종사촌` — and those panels
   are now hidden; only 51 were genuinely misleading (`여행가` → 여행 + 가다).
   The distinguishing signal is visible in the measurement: span-aligned parts
   that are themselves entries. *Revisit trigger:* when component-panel
   behaviour is next revised, gate suppression on span alignment rather than on
   the surface being an entry.
2. **Proper UTF-16 to code-point conversion**, instead of the refusal applied
   above, would restore direct text on lines containing emoji. *Revisit
   trigger:* if emoji-adjacent Korean is observed to matter, or when Wave 6
   settles the equivalent Windows offset units.
3. **Acquisition runs on the Qt UI thread.** Capture already does, so this is
   consistent rather than new, but the master plan's Wave 5 policy says these
   calls run away from the UI thread. The messaging deadline bounds the damage.
   *Revisit trigger:* moving hover capture off the UI thread, which should carry
   acquisition with it.
4. **Retina, multi-display, negative-origin and mixed-scale coordinates are
   unvalidated.** This machine has one display at scale 1.00, where AX points
   and capture pixels coincide. On a Retina display they may not, which would
   either refuse everything (safe) or misplace the retained-word rectangle.
   *Revisit trigger:* first run on a Retina or multi-display machine.
5. **The panel grows the compact card by 47%** (340×200 → 340×293 for a
   four-component word), because rendering is not gated on expansion.
   *Revisit trigger:* the next popup sizing or density pass.
6. **Two grammatical components can share one surface and span** — `사과했어요`
   yields `했 · verb-forming suffix` and `했 · tense or honorific` at [2,3).
   Both morphemes are real and the contract permits overlap, but it reads as a
   duplicate. *Revisit trigger:* same as 5.

## Dismissed

- **CoreFoundation ownership and release paths.** Every `Copy`/`Create` result
  is released on success, failure and exception paths; 6,000 acquisitions grew
  peak RSS by 0 bytes. The attribute-name `CFString` cache is deliberately
  retained and bounded by the number of attribute names.
- **ctypes signature errors.** All widths, structures and return types verified
  by round-trip. (A segfault during review came from the reviewer's own untyped
  probe, not from the adapter, which types `CFRelease` correctly.)
- **`TextSelection.source` influencing results.** Identical status, entries,
  lemma and components across seven labels including a 200,000-character one.
- **Stale direct results.** The coordinator re-checks currency after the call
  and the hover runtime re-checks before submitting; a request built outside the
  hover state machine is correctly treated as not current.

## Final gates

```
pytest                  -> 2098 passed, 2 skipped
pytest --suite native   -> 75 passed   (+3 from this review)
pytest --suite packaged -> 3 passed
ruff                    -> All checks passed
mypy                    -> Success, 278 source files
```

No failure was dismissed as pre-existing; the only failures during this review
were the two regression tests written to demonstrate defects 1 and 3, each
confirmed to fail against the reviewed implementation and pass after the fix.

## Commits created during review

| Hash | Subject |
|---|---|
| `1dbe8e8` | fix: bound accessibility offsets, deadline and trace label |

`0ec5008`, `22bb4be`, `573b115`, `c083d62`, `b0851a8` and `ae3bccc` are
unchanged. **Wave 6 was not started, and nothing was pushed or merged.**
