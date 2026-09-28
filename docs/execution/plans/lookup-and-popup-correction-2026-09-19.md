# Lookup accuracy and popup correction: investigation and implementation plan

**Status:** Bundle A was implemented and reviewed on 2026-09-19. A1–A4, A7 and A8 were delivered; A5 remains unwired in production and A6 remains broken in native macOS use. The remaining corrective work moved to [`vision-hover-and-macos-restore-stabilization-2026-09-20.md`](vision-hover-and-macos-restore-stabilization-2026-09-20.md). Bundle B still requires separate authorization.
**Baseline:** original investigation on `visual/interface-update`, commit `f9514d4`, 2026-09-19; implementation state is recorded in the checkpoint and Review Handoff because git was unavailable during that run.
**Scope:** this file remains the evidence-backed specification and historical execution record for Bundle A. Its successor plan contains only the incomplete clipping recovery, Apple Vision hover stability, and native macOS restore corrections found during live use. Broader visual redesign and platform work remain in Bundle B.
**Execution authority:** the original Bundle A run has ended at its Review Handoff. Do not resume implementation from this file. The successor plan is also a proposed fix specification and needs separate human authorization; neither document authorizes Linear changes, commits, pushes, merges, or Bundle B.

## MUST ACT — Historical execution checkpoint

The completed Bundle A implementation used **one separate living checkpoint** at:

`docs/execution/checkpoints/lookup-and-popup-correction-2026-09-19.md`

That requirement was fulfilled during the original run. Do not append successor-plan decisions to it; the remaining corrective bundle owns a new checkpoint so the two execution states cannot be confused. The rules below are retained as the historical requirements that governed the Bundle A run.

Every decision entry must state:

1. **Decision:** what was chosen.
2. **Why:** the evidence, constraint, or tradeoff behind it.
3. **Still unverified:** missing checks, native evidence, uncertainty, or follow-up.

Additional mandatory rules:

- Update the checkpoint before changing direction, accepting or rejecting a material hypothesis, pausing, or writing the Review Handoff.
- Never mark behavior complete from offscreen or mocked evidence when the acceptance criterion requires native behavior. Record the missing evidence explicitly.
- If work pauses, add the exact active package, repository state, and next action so another session can resume without redoing completed work.
- Keep the checkpoint decision-focused. Reference this plan and tests instead of copying sections or diffs; it supplements rather than replaces Linear and the Review Handoff.

## 0. Post-implementation disposition

The durable execution record is split across the completed
[`checkpoint`](../checkpoints/lookup-and-popup-correction-2026-09-19.md) and
[`Review Handoff`](../review-handoffs/lookup-and-popup-correction-2026-09-19.md).
Live use and the post-bundle review changed the disposition of three areas:

| Original package | Disposition after implementation and live use |
|---|---|
| A1, A2, A3, A4, A7, A8 | Implemented. Their remaining review notes stay in the Review Handoff and are not reopened by the successor plan unless directly required by the observed failures. |
| A5 | Only the pure clipping helpers and focused unit tests were implemented. No production path imports them, so live hover never performs the planned recapture. |
| A6 | A restore-before-show path was added, but it relies on `window.minimized` as live state. Pywebview's Qt backend does not update that construction flag when the native window is minimized, and the Dock/application-reopen route remains unhandled. The defect is reproduced in the 2026-09-19 screen recording. |
| Apple Vision path | Added after the original scope decision and fixed at the lookup-process spawn boundary, but real hover shows unstable recognition as the cursor moves and the capture ROI changes. The adapter also discards Vision's detailed geometry. |

These are correctness and native-lifecycle closures, not authorization for the
deferred Bundle B visual match, HTML renderer, custom listboxes, general motion
work, Windows title bar, or AppKit/Liquid Glass port.

## 1. Decided scope and diagnosis

Section 2 establishes that several independent defects combine. Bundle A corrects only the smallest coherent set that changes lookup truthfulness and restores the reported desktop behavior:

1. Short English glosses exist in KRDICT but the runtime query and flattened entry contract discard them.
2. Correctly recognized derived predicates are reduced to the first morpheme because the pipeline selects `lemmas[0]` instead of a cursor-owned lexical unit.
3. The popup measures rebuilt content before Qt layout and deferred deletion settle, producing clipped cards and the macOS 640×480 regression.
4. The popup lifetime is wrong for the default Push to Hover interaction: once deliberately opened, it should remain available after mouse exit and chord release.
5. A crop that clips detected text needs one bounded recapture; a full but incorrect OCR reading is a different problem and must not be presented as a verified unrelated prefix.
6. The macOS Control Center focus path shows but does not restore a minimized window.
7. The Control Center requests a fixed 1080×760 window instead of deriving a usable initial size from the available screen.

Bundle B retains every broader visual, renderer, corpus, motion, and platform item with a revisit trigger in Section 7. Deferral is not dismissal and Bundle A does not authorize Bundle B.

### Design facts that govern both bundles

1. OCR returns a detected box, recognized string, and confidence. Word extent is an OCR **output**, not an input, so “expand the capture to the word” cannot be an ordering of operations; any expansion is post-OCR reasoning over a detected region.
2. EasyOCR detects lines and regions rather than linguistic words. Hanly isolates a word on the recognized **string** by character offset, not by pixel boundary. `word_resolver.py:226` records that character positions are estimated from per-script advance weights rather than measured, so mixed-script lines can drift by a character or two. That approximation is adequate for pointing at a word but is not ground truth.
3. The layered division of labor mostly exists: `_most_interior` (`word_resolver.py:278`) selects the OCR box under the cursor, `_character_index` (`:300`) estimates the character, and `_word_span` (`:250`) selects the whitespace span. A2 adds the missing lexical-unit layer; A5 adds the missing clipping check.
4. A Korean eojeol may carry particles: the whitespace span `책을` is not the lexical unit `책`. Pixel or whitespace boundaries alone therefore cannot solve lexical selection.
5. Phrase-level lookup remains future work. `_word_span` is a policy over already detected text, so a phrase mode is a different span policy rather than a new lookup pipeline.

### Bundle A accuracy boundary

Require the named perfect-text corpus to select complete lexical units and prevent a clipped or misrecognized string from becoming a confident unrelated answer. Do not promise perfect OCR: when the full text is visible but recognized incorrectly, return an honest normal non-success. Do not hardcode corrections for the reported strings.

## 2. Evidence and limitations

### Environment and checks

- macOS; repository Python 3.13 environment; kiwipiepy 0.23.2, EasyOCR 1.7.2, PyQt6/WebEngine 6.11.0, pywebview 6.2.1.
- Read-only `data/generated/krdict.sqlite3`: **56,555 entries**. The four requested dictionary headwords and English short translations are present.
- Ordinary entry point `.venv/bin/python -m hanly_app`: sandboxed attempt exited; retry outside the sandbox reached **Ready**. Logs recorded runtime readiness at 1,443 ms and the Control Center showing its page. The investigation-launched process was subsequently sent SIGINT.
- **Not completed:** interactive live hover, clicking the real desktop popup, Control Center dropdown latency measurement, Windows or mixed-DPI validation. Native computer inspection timed out. App readiness is not evidence that these interactions work.
- Both HTML design references and their source structure were inspected. Browser opening of the local popup HTML was denied by URL policy; no browser screenshot comparison was completed. The design comparison below is source-based, with actual offscreen Qt renders inspected separately.
- Disposable scripts and renders were kept under `/tmp/hanly_*` and `/tmp/hanly-*.png`, outside project source. They are session evidence, not durable dependencies; reproduction recipes are below.
- Focused baseline: **88 passed in 2.50 s** with `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_kiwi_provider.py tests/test_lookup_pipeline.py tests/test_krdict_provider.py tests/test_popup.py tests/test_hover_target.py tests/native/shared/test_qt_popup_window.py -q`. This is not a full-suite or native-window certification.
- Current GitHub macOS native run: **65 passed, 1 failed in 152.14 s**. `test_compact_and_expanded_sizes_follow_content_without_clipping` expected the expanded width `386` but read `640×480` after the click/event cycle. Windows and Linux passed. A local offscreen rerun of that exact case passed; the macOS native runner remains the required reproduction and acceptance environment.

### A. Perfect-text morphology, without OCR

| Input | Actual Kiwi tokens (simplified) | Current chosen lemma | Result |
|---|---|---|---|
| 사과했어요 | 사과/NNG + 하/XSV + 었/EP + 어요/EF | 사과 | Fruit first, apology noun second; wrong lexical unit |
| 사과하다 | 사과/NNG + 하/XSV + 다/EF | 사과 | Same defect even in dictionary form |
| 예뻤어요 | 예쁘/VA + 었/EP + 어요/EF | 예쁘다 | Correct with intact text |
| 떨어뜨렸어요 | 떨어뜨리/VV + 었/EP + 어요/EF | 떨어뜨리다 | Correct with intact text |
| 깨뜨렸습니다 | 깨뜨리/VV + 었/EP + 습니다/EF | 깨뜨리다 | Correct with intact text |
| 공부했어요 | 공부/NNG + 하/XSV + 었/EP + 어요/EF | 공부 | Same derived-verb defect |
| 행복했어요 | 행복/NNG + 하/XSA + 었/EP + 어요/EF | 행복 | Same derived-adjective defect |
| “예뻤어요” | opening quote + predicate + endings + closing quote | “ | NOT_FOUND: punctuation selected as lemma |
| 책읽는 | 책/NNG + 읽/VV + 는/ETM | 책 | Cursor within the segment cannot select 읽다 |

`KiwiProvider` does preserve Kiwi's existing `lemma` property. It is incorrect to diagnose all verbs as missing a mechanically appended `다`: installed Kiwi already supplies `예쁘다`, `떨어뜨리다`, and `깨뜨리다`. It discards source spans, however.

Observed Kiwi spans overlap for contracted syllables: `예쁘` spans `(start=0,len=2)` while `었` spans `(1,1)` in `예뻤어요`; `하` and `었` share the `했` syllable in `사과했어요`. Never require disjoint token spans or reconstruct the original text by concatenating morpheme forms.

An isolated probe of `tokenize(text, match_options=Match.ALL | Match.JOIN_V_SUFFIX)` returned `사과하/VV → 사과하다`, `공부하/VV → 공부하다`, `행복하/VA → 행복하다`, and `깨끗하/VA → 깨끗하다`; plain `사과` and `사과를` remained nouns. This supplies a concrete candidate-generation route, but a joined-only stream would hide the derivational pieces the learner wants to see.

### B. Real OCR on controlled synthetic crops

Recipe: Pillow `AppleSDGothicNeo.ttc`, black text on white, font sizes 20 and 32; render each reported form at `(200,30)` on a 600×100 canvas; crop a 200×100 cursor-centered ROI at first, middle, and last syllable; use default `EasyOCRProvider(EasyOCRConfig(download_enabled=False))`, real Kiwi, real KRDICT, and the production pipeline. Twenty-four cases were examined. This is a synthetic reproduction, not the user's original screen or an accuracy benchmark.

| Font / location | Intended | Actual OCR | Current downstream result |
|---|---|---|---|
| 20 / first | 사과했어요 | 사과있어요, confidence .25 | 사과 → SUCCESS |
| 20 / first | 예뻤어요 | 예쨌어요, .41 | 예 → SUCCESS |
| 32 / middle | 예뻤어요 | 예벗어요, .25 | 예 → SUCCESS |
| 32 / middle | 떨어뜨렸어요 | 떨어뜨로어요, .25 | 떨다 → SUCCESS |
| 32 / first | 떨어뜨렸어요 | 떨어뜨럿, .40 | NOT_FOUND; suffix cropped |
| 32 / last | 떨어뜨렸어요 | 뜨럿어요, .15 | NOT_FOUND; prefix cropped |
| 32 / middle | 깨뜨렸습니다 | 깨뜨로습니다, .65 | NOT_FOUND |

At 20 px the intended words fit, but OCR still corrupts them. At 32 px the first/last-syllable captures also cut text. Thus wider capture can address clipping but cannot by itself repair recognition. Confidence alone is not proof: a corrupted formal form scored .65.

`composition._nothing_was_read_at_target()` retries only EMPTY or UNUSABLE without resolved text. These corrupted SUCCESS/NOT_FOUND cases do not qualify. The inspected runtime config has no confidence threshold, so the default pipeline admits low-confidence text.

### C. Popup render and interaction geometry

A disposable offscreen probe used the actual `QtPopupView`, `PopupController`, real `떨어뜨리다` entry, and real `떨어뜨렸어요` analyses. After every action it processed Qt events and deferred deletions, rendered the widget, and recorded geometry:

| State | Card size | Content height after events | Viewport height | Observation |
|---|---|---|---|---|
| Initial compact | 340×310 | 267 | 267 | Two definitions visible |
| Expand | 386×203 | 607 | 160 | Card shrinks, most senses hidden |
| Collapse | 340×103 | 252 | 60 | Only header/top content visible |
| Expand, then remeasure after layout settles (separate probe) | 386×665 | 622 | 622 | Full content becomes visible |

This confirms a measurement-timing defect, not just an aesthetic mismatch. `_rebuild()` replaces children with deferred deletion and `_resize_to_content()` immediately asks for `sizeHint()`. The settled hint differed from the value used to fix the window size. The probe supports a layout-settlement fix; it does not establish that `deleteLater()` alone is the cause.

Related confirmed code paths:

- `_resize_to_content()` uses `sizeHint().height()` rather than the actual width-dependent wrapped height; it fixes the content width to `width - 2`, which exceeded the measured viewport width by two pixels even without a scrollbar. A scrollbar reduces available width further.
- Measurement chooses the screen at the *current cursor*, while `PopupController` retains the *original screen*. Interactive resizing can therefore measure and place against different work areas.
- `PopupController._handle_resize()` repositions relative to the original word cursor. With work area 1000×800 and original cursor `(400,400)`, compact 340×310 lands at `(416,416)`, but expanded 386×660 lands at `(416,0)`. A pointer at the former footer can end outside the new frame.
- `ManualLookupRuntime.update_popup_geometry()` calls `hover.retain(...)`, resetting the protected point to the word center. Geometry updates are propagated, so “missing resize callback” is not the diagnosis. Reusing new-result retention for a same-result resize loses interaction context.
- Only SUCCESS has a retained word via `_word_rect()`. Verify usability of technical details on non-success cards; do not assume the same retention path covers them.

### D. Data and visual differences

| Requirement / prototype | Branch behavior | Correction |
|---|---|---|
| Bold short translation, secondary explanatory definition per sense | Only `t.definition` selected; rendered as the main bold text | Preserve `translations.lemma` paired with its definition |
| Compact 340 px / expanded 386 px, sizes to content | Widths match; live content measurement fails | Repair measurement before visual acceptance |
| Korean reading typography, pronunciation line, labeled Hanja | 27 px generic title, no pronunciation, unlabeled Hanja | Match hierarchy; use actual available metadata only |
| Expanded grammar disclosure, separate token/role/explanation rows | One flat joined token line and role line | Add real disclosure and supported grammar descriptions |
| Informal polite vs formal polite; derivation | `어요/EF` becomes “ending”; XSV/XSA often raw tags | Map supported grammar precisely; preserve unknown tags safely |
| Rounded chips, footer controls, restrained dividers/shadow | Offscreen render shows substantial visual mismatch, including square-looking controls | Explicit Qt styling and platform screenshots |
| Alternate entry choices | Other entries are static labels with first definition | Make alternatives navigable if included; preserve selected entry identity |
| Genuine examples | No normalized examples | Optional follow-up using real source; never invent bilingual text |

Actual SQLite pairs include `사과하다: apologize`, `예쁘다: pretty; beautiful; comely`, `떨어뜨리다: drop`, and `깨뜨리다: break; smash`. The source parser and schema already preserve them; no dictionary rebuild is needed for short translations.

Another related defect: entry ordering is `e.id`, not relevance. `먹었어요` correctly becomes `먹다`, but the first returned entry means becoming unable to hear; the eating verb is second. Do not claim this is an OCR error or solve homonym ambiguity by silently discarding alternatives.

Control Center `.select` CSS exists, and the main reference also uses native `<select>`. Therefore “all CSS absent” is not established. Open menus remain platform-rendered. `renderTargets()` destroys/recreates options on each state render; `settings()` causes an additional render after `invoke()` already rendered. During pending activity, refresh is every 500 ms. These are concrete churn sources; whether they explain observed lag requires native timing, and polling is not unconditional when idle.

### E. Control Center macOS lifecycle and visual evidence

- `ControlCenterProcess.show()` sends a `focus` message to a live child. The child reaches `ControlCenterHost.show()`, which calls pywebview `show()` and activates the accessory application, but never calls pywebview's separate `restore()` operation. The installed Qt backend implements restore by clearing the minimized state, raising, and activating the window. This is a concrete missing operation on the reported path; the final fix must still verify both the tray/open command and a Dock/application-reactivation route on real macOS.
- The child being alive is expected: capture, lookup, and the shell are separate from visibility of the Control Center window. A restore fix must not destroy/recreate the child, lose page state, or disturb active capture merely to make the window visible.
- The supplied screenshot confirms a real dark-theme mismatch in an *open* select menu. Closed `.select` styling alone cannot satisfy this requirement on macOS because the expanded native menu is platform-owned. All three current dropdown surfaces—capture target, lookup preload, and log subsystem—must be covered by one accessible control treatment rather than a one-off monitor-menu patch.
- The current window requests 1080×760 with a 760×560 minimum. The requested correction is a denser initial macOS window, with width allowed to change only if that improves the composition. Exact dimensions should be chosen from real available-screen measurements, not copied blindly from one screenshot.
- The report of laggy macOS motion is not yet attributed to one animation. Broad page/rise animations, navigation motion, disclosure transitions, option rebuilding, duplicate renders, and periodic pending-state refresh are all candidates. Measure before removing useful feedback, and prevent background snapshots from replaying entrance motion.

## 3. Proposed implementation decisions

These are the decided Bundle A constraints. They remain a proposed fix specification rather than an amendment to approved architecture.

1. **Carry structured dictionary senses without breaking definition-only providers.** Add a stable entry identifier and ordered `DictionarySense` values while preserving the existing `definitions` path as the compatibility fallback.
2. **Add lexical candidates beside raw morphology.** Kiwi may produce raw and joined streams internally, but only normalized `MorphologyAnalysis`, `LexicalCandidate`, and `TokenAnalysis` values cross the provider seam.
3. **Preserve public compatibility deliberately.** Keep `WordResolver.resolve_target()` unchanged and add a richer method beside it. Normalize legacy sequence-returning `MorphologyProvider.analyze()` implementations once at the pipeline seam with a conservative fallback.
4. **Repair Qt measurement before broader presentation work.** Stable content widgets are preferred; any replacement widgets must be measurable before size is published. Production rendering must not call `processEvents()`.
5. **Make the opened popup sticky by product policy.** Mouse exit and chord release no longer dismiss; dismissal becomes an explicit act. Because the popup never accepts focus, A4 tiers the routes rather than assuming widget-level Escape and outside-click handlers. This replaces resize-transfer and pointer-retention work whose only purpose was keeping the popup alive while the pointer crossed into it.
6. **Recover clipping through one observable condition.** Only a detected box touching the ROI boundary authorizes one padded recapture. Confidence, text-integrity guesses, and competing lexical units do not trigger retries.
7. **Keep screen access in the app.** The app owns recapture, monitor constraints, coordinate transforms, and request currency; the engine continues to receive images and normalized target context only.
8. **Finish the current Control Center lifecycle before platform replacement.** Restore a live minimized child and derive its initial size from available screen geometry. Custom controls, motion work, Windows chrome, and AppKit remain Bundle B.
9. **English remains the dictionary output for Bundle A.** The requested meanings do not authorize localization or a translation-provider project.

## 4. Bundle A work packages and dependency order

Bundle A is the only implementation scope proposed here. Its dependency order is:

```text
A8 focused fixtures
  ├─ A1 structured senses ───────────────┐
  ├─ A2 lexical-unit selection ──────────┤
  ├─ A3 popup measurement ─→ A4 sticky ─┤
  ├─ A5 clipping-only OCR recovery ──────┤
  ├─ A6 Control Center restore ──────────┤
  └─ A7 initial window density ──────────┘
                                      convergence → one Review Handoff
```

A1 and A3 are independent. A2 is independent of A1. A4 depends on A3 so dismissal behavior is tested against stable geometry. A5, A6, and A7 are independent. A8 is not a gate: it starts first and grows as each package needs its named regression, so the diagram shows where fixtures attach rather than a phase every package waits on. These identifiers are plan-local work packages, not Linear issues.

### A1 — Short translations end to end

**Files:** `hanly/{contracts,krdict_provider,__init__}.py`, `hanly_app/popup.py`, and focused contract, dictionary, serialization, and popup tests.

Current evidence: `krdict_provider.py:110-119` does not select `t.lemma`; `:135-153` flattens sense definitions into one deduplicated list.

```python
@dataclass(frozen=True)
class DictionarySense:
    sense_id: str
    gloss: str | None
    definition: str
```

- Select the stable entry identity, `s.id`, `s.sense_order`, `t.id`, `t.lemma`, and `t.definition`. KRDICT stores these identifiers as integers, so the adapter decides once whether `sense_id` is an integer or a stringified value and applies that single representation everywhere; a provider without numeric identifiers must produce the same shape rather than a second one.
- Add ordered `senses` and a stable identifier to `DictionaryEntry`. Keep `definitions` working for providers that supply definitions only, with one canonical compatibility conversion rather than two contradictory representations.
- Group translations by entry and sense in deterministic source order. Never zip independently deduplicated glosses and definitions.
- Render a sense's short gloss as visually primary and its own definition as secondary. A missing gloss omits the gloss row; it never invents a translation or repeats the definition.
- Preserve distinct senses when definitions happen to match but glosses differ.

**Done:** `apologize`, `drop`, `pretty; beautiful; comely`, and `break; smash` reach the popup paired with their correct definitions, while definition-only provider results still render.

### A2 — Lexical-unit selection, narrow

**Files:** `hanly/{contracts,providers,kiwi_provider,word_resolver,lookup_pipeline,__init__}.py`; affected app wrappers/serialization in `hanly_app/{composition,runtime_trace,lookup_process}.py`; focused engine and process tests.

Current evidence: `lookup_pipeline.py:169` assigns `lemma = lemmas[0]`, which reduces `사과했어요` to `사과`.

```python
@dataclass(frozen=True)
class LexicalCandidate:
    lemma: str
    start: int
    end: int
    part_of_speech: str | None = None
    token_indices: tuple[int, ...] = ()

@dataclass(frozen=True)
class MorphologyAnalysis:
    tokens: tuple[TokenAnalysis, ...]
    candidates: tuple[LexicalCandidate, ...]
```

- Add optional source offsets to normalized token analysis where required. Overlapping Kiwi spans from contractions are valid.
- Have `KiwiProvider` obtain both the raw token stream and a `Match.ALL | Match.JOIN_V_SUFFIX` view. Reconcile them by source span inside the adapter. Retain raw pieces such as `하/XSV` and `었/EP` for explanation while exposing complete joined predicates as candidates.
- Record the cost of obtaining the second normalized view and avoid redundant tokenization where the adapter can safely reuse work; do not turn this correctness package into a general performance redesign.
- Keep `WordResolver.resolve_target()` unchanged. Add a richer target result beside it that retains the selected OCR result, resolved span, estimated character index, and geometry for the pipeline.
- Normalize legacy sequence-returning morphology providers once at the pipeline seam. Their conservative fallback may expose the legacy tokens as candidates, but must not silently invent joined forms.
- Select the lexical candidate owned by the estimated character, including attached endings/particles. Exclude punctuation and grammatical fragments from primary selection without globally rejecting valid standalone forms such as `예`.
- Ensure every relevant syllable in one conjugated predicate selects the complete predicate. For adjacent lexical units such as `책읽는`, use the cursor estimate rather than the first token.
- Preserve the surface, selected candidate, reason, and raw analyses in `LookupContext`. Do not restore whole-surface-first lookup or try unrelated shorter candidates until one dictionary lookup succeeds.

**Done:** the Section 6 perfect-text, derivation, control, and boundary cases select the intended lexical unit; legacy morphology providers remain usable; provider/process serialization passes; no Kiwi object leaves the adapter.

### A3 — Popup measurement repair

**Files:** `hanly_app/{qt_popup,popup}.py`; focused presentation, geometry, and native popup tests.

Current evidence: `qt_popup.py:121` schedules removed children with `deleteLater()`, while `_resize_to_content()` at `:449-454` immediately reads `sizeHint()`. Section 2 records the resulting shrink/clipping and the macOS 640×480 CI failure.

1. Preserve the native macOS regression: after the Cocoa event cycle, expanded width remains 386 rather than reverting to Qt's 640×480 default.
2. Prefer stable widgets/sections whose content is updated. If replacement is necessary, detach or hide obsolete children and make new children measurable before publishing the size.
3. Measure wrapped content at the actual viewport width, including content margins, footer, and scrollbar extent. Resolve scrollbar-dependent width with a bounded layout pass.
4. Choose one screen/work area and pass it into both measurement and placement. Clamp the result to that work area while keeping the footer and one vertical scroller usable.
5. Do not call `processEvents()` from production rendering; use explicit polish/layout activation or a generation-guarded queued measurement.

**Done:** repeated compact → expanded → compact toggles with long, many-sense content neither shrink nor clip; required content remains visible or scrollable; the focused native test holds the 340/386 width contract on macOS as well as the existing Windows/Linux paths.

### A4 — Sticky popup dismissal

**Depends on:** A3.

**Files:** `hanly_app/{qt_popup,popup,manual_lookup,hover_lookup,hover_target}.py` as the current dismissal paths require; focused popup, hover-target, and dismissal tests.

`config.py:72` makes Push to Hover the default: lookup already follows a deliberately held chord. Once a result opens, the popup must remain available for reading and interaction.

**Constraint that shapes every dismissal route.** `qt_popup.py:65-68` sets `WindowDoesNotAcceptFocus`, `:131` sets `WA_ShowWithoutActivating`, and the footer controls take `NoFocus` (`:410`, `:424`). The popup deliberately never accepts keyboard focus, because the source application must keep it. A window with those flags receives neither `keyPressEvent` nor any mouse event that occurs outside its own frame. Escape and outside-click are therefore **not** implementable as ordinary widget handlers, and an executor must not plan them as such.

Adopt the tiers in order. Each is independently shippable; a later tier is an upgrade, not a prerequisite.

- **Tier 1 — required, no new machinery.** Dismiss on presentation of the next lookup result, on a re-press of the hover chord, and through a visible close affordance in the popup footer. A footer control receives its own mouse events, so it works under the existing flags and needs no global monitor or additional OS permission.
- **Tier 2 — optional, Escape.** Register a scoped Escape through the existing global hotkey path (`hotkeys.py` / `hotkeys_darwin.py`) while a popup is open, and release it on dismissal. Do not add a widget key handler; the window cannot receive one.
- **Tier 3 — optional, outside click.** Requires a global mouse monitor. Measure the added permission prompt and the idle cost against the benefit before adopting it, and confirm it does not interfere with capture or hotkeys.
- Do not dismiss when the pointer leaves the retained word/popup region.
- Do not dismiss on chord release; the user must be able to release the chord and move to the popup.
- Apply the same explicit lifetime to successful and normal non-success/error cards so diagnostic content remains readable until an intentional dismissal.
- Keep stale-result currency as the correctness gate. A superseded result still must never replace the current one.
- Do not build the pointer-stable resize anchor, the same-result `retain(new_result)` separation, or the resize-transfer grace machinery: they were proposed work, not existing code, and the sticky lifetime removes their purpose. The one real call to re-examine is `ManualLookupRuntime.update_popup_geometry()`, which Section 2C records as calling `hover.retain(...)`; change it only where it is proven to serve the removed lifetime.

**Done:** mouse exit and chord release leave success and non-success cards visible; the Tier 1 routes dismiss them; a new current lookup replaces them; stale work cannot reopen or replace them. Any adopted tier is verified against the real non-activating window, and the source application keeps keyboard focus throughout.

### A5 — Bounded OCR recovery for clipping only

**Files:** `hanly_app/{capture,manual_lookup,lookup_process,composition,runtime_trace}.py` and normalized metadata in `hanly/{contracts,lookup_pipeline}.py` only as required; focused capture, worker, currency, and recovery tests.

- After the first OCR pass, test one condition: whether the selected detected text box touches an ROI boundary. Define “touches” as a measured tolerance in ROI pixels, not exact equality — a detection quad for clipped text lands near the edge rather than exactly on it, so an equality test would almost never fire. Derive the tolerance from the Section 2B clipped cases and record the chosen value.
- If it touches, perform exactly one additional capture centred on that detected box with padding, constrained to the selected monitor/region. Recompute the ROI-local target from the new origin and run OCR once more.
- Maintain one request-wide recovery budget. Do not recursively recapture or submit nested jobs that escape the one-running/one-latest bound.
- Preserve final request currency across the recapture. Cache/trace identity must distinguish the new geometry and record that clipping recovery occurred.
- Do not use a confidence threshold, the unmeasured 400×100 cap, text-integrity heuristics, or competing lexical units as retry triggers.
- State the limitation in behavior and diagnostics: this recovers clipping, not recognition errors. If the complete word is visible but OCR reads `예뻤어요` as `예벗어요`, return an honest non-success rather than a confident definition for an unrelated prefix.
- Keep recapture in `hanly-app`; the engine never gains screen access.

**Done:** boundary-touching text gets at most one monitor-constrained padded recapture with correct coordinate transforms and currency; non-boundary misrecognition does not trigger recapture or produce a disguised unrelated success.

### A6 — Restore a minimized macOS Control Center

**Files:** `hanly_app/{control_center_host,control_center_process,app_identity_darwin,application}.py` only as evidence requires; host/process/lifecycle and macOS identity tests.

Current evidence: `control_center_host.py:137-145` calls pywebview `show()` and activates the accessory process but never calls its separate `restore()`.

- Distinguish minimize from hide, destroy, deactivation, and simple occlusion.
- Restore a live minimized window before showing/raising and activating it. Use pywebview's public restore path when it satisfies native behavior; keep a Cocoa adapter narrow if evidence proves it necessary.
- Preserve the same child process, page state, settings edits, bridge connection, and capture state.
- Repeated minimize/restore cycles must not spawn another child or Dock tile.
- Cover the supported reopen route at host/process level and record real macOS behavior as unverified until exercised natively.

**Done:** a minimized Control Center returns visibly through the supported reopen action with the same child and state; repeated cycles create no duplicate process or application identity.

### A7 — Derive the initial Control Center size

**Files:** `hanly_app/{control_center_host,control_center_process}.py`, Control Center layout assets only if required for bounded scrolling, and layout/host tests.

- Choose the initial dimensions from the real available screen geometry instead of always requesting 1080×760.
- Keep native window controls on screen and retain usable bounds for supported displays.
- At the minimum supported size, keep the sidebar footer, page header/actions, and current setting reachable. The main content area may scroll.
- Preserve width unless available geometry requires clamping or evidence supports a denser composition; do not turn this into Bundle B visual redesign.

**Done:** representative short Mac work areas produce a materially less tall initial window with reachable controls and no clipped native chrome; larger screens remain well composed.

### A8 — Focused fixtures required by Bundle A

**Files:** focused existing tests and `tests/hanly_fixtures/` where shared deterministic inputs belong.

- Add perfect-text morphology fixtures for the Section 6 cases. Use real normalized morphology expectations rather than mocks that already contain the desired final lemma.
- Add a repeated compact → expanded → compact test using long real definitions and many senses. The existing single-definition `apple` case is not sufficient.
- Add only the capture geometry needed to prove boundary-touching recapture deterministically. The labeled real-screen crop corpus is Bundle B.
- Keep fixtures small and deterministic; they are the architecture's Korean Test Fixtures, not a new OCR benchmark corpus.

**Done:** each Bundle A behavior has a focused regression that fails for the diagnosed reason and can run without pretending synthetic/offscreen evidence is native proof.

### Bundle A convergence and handoff

Run focused checks while advancing, then the repository gates once:

```bash
.venv/bin/python -m pytest
.venv/bin/python -m ruff check packages packaging tests tools benchmarks
.venv/bin/python -m mypy packages packaging tests tools benchmarks
```

Run proportional native checks where the package requires them; record missing native evidence instead of claiming it from offscreen or mocks. Inspect package direction, Python 3.10 compatibility, provider normalization, process serialization, request currency, and packaging only where the implementation changes them. Update `docs/CODE-MAP.md` only if implemented structure changes.

Reconcile the live checkpoint with the actual diff, write one Review Handoff under `docs/execution/review-handoffs/`, and stop. Do not begin Bundle B, Phase B deep review, a commit, push, merge, architecture-source edit, or Linear mutation without separate authorization.

## 5. Why the existing tests missed this

- Kiwi tests mostly use injected tokens. The real smoke is `먹었어요`, whose first token already has a dictionary-form lemma; it cannot catch noun + derivational suffix grouping.
- The pipeline deliberately tests first-usable-lemma behavior, including a miss. The executor must replace that policy assertion with explicit lexical-selection cases, not merely add examples around it.
- The native density test uses one definition (`apple`), checks width and a layout hint, and does not prove wrapped body visibility or a full toggle round-trip.
- That density test also never shows the widget before toggling it. The macOS CI failure proves that an offscreen pass does not establish the native Cocoa window's post-event size.
- Existing hover-target tests protect the old mouse-exit lifecycle; they do not express the decided sticky lifetime or its explicit dismissal routes. Nothing in the suite exercises the popup's non-activating window flags, so a plan assuming widget-level key or outside-click handling would pass review and fail on the real window.
- A definitions-only contract makes the missing short-gloss path invisible to presentation tests.
- Control Center lifecycle fakes model `show()` but not a minimized native window or the Dock/application-reopen route, so a healthy child can satisfy the tests while remaining invisible to the user.
- Control Center layout tests exercise fixed requested dimensions rather than choosing an initial size from available screen geometry.

## 6. Acceptance matrix

This matrix records the original Bundle A acceptance contract. The completed run's actual evidence and gaps are in Section 0 and the Review Handoff. Open A5/A6 requirements and the new Vision stability requirements are carried forward only by the successor plan; Bundle B rows remain visible so deferral cannot be mistaken for deletion.

| Scope | Layer | Required cases | Observable pass condition |
|---|---|---|---|
| Bundle A / A1 | Dictionary senses | Four required glosses; ordered multi-translation senses; equal definitions with different glosses; missing gloss; definition-only provider | Correct gloss/definition pairing and order; no invented/duplicated gloss; compatibility rendering remains |
| Bundle A / A2 | Perfect text | 사과했어요, 사과하다, 예뻤어요, 떨어뜨렸어요, 깨뜨렸습니다 | Correct complete lexical lemma; every syllable owned by one predicate agrees |
| Bundle A / A2 | Derivation | 공부했어요, 행복했어요, 깨끗했어요 | Correct verb/adjective candidate; raw derivational morphemes remain available |
| Bundle A / A2 | Controls | 사과, 사과를, 예, 책을, 먹었어요, 아름다웠어요 | Nouns, particles, interjections, and irregular predicates remain valid; no unconditional first-token policy |
| Bundle A / A2 | Boundaries | Quoted/parenthesized forms, leading punctuation, 책읽는 at each lexical unit | Punctuation is not primary; cursor estimate selects the intended lexical unit; legacy providers remain usable |
| Bundle A / A3 | Popup measurement | Compact/expanded; one and many senses; long wrapped gloss/definition; repeated round trip; small work area | Content is visible or scrollable, footer remains reachable, no shrink/clipping regression |
| Bundle A / A3 | Native popup CI | macOS Cocoa event cycle plus existing Windows/Linux native paths | Expanded width remains 386 rather than reverting to 640×480; compact remains 340 |
| Bundle A / A4 | Sticky lifetime | Success and non-success cards; mouse exit, chord release, next current lookup, chord re-press, footer close, late stale lookup; any adopted Tier 2/3 route | Exit/release keep the popup; every adopted dismissal route works against the real non-activating window; the next current result replaces it; stale work cannot revive it; the source application keeps keyboard focus |
| Bundle A / A5 | Clipping recovery | Box touches each ROI edge; box does not touch; selected monitor/region edge; cancellation | Exactly one padded recapture only on boundary contact; transforms and request currency remain correct |
| Bundle A / A5 | Misrecognition boundary | Full visible word misread as 예벗어요 or another corrupted form | No recapture from confidence alone and no confident unrelated-prefix definition; honest non-success |
| Bundle A / A6 | Control Center restore | Minimize then use each supported reopen action; repeat | Same child becomes visible/active with page, edits, bridge, and capture state intact; no duplicate Dock tile |
| Bundle A / A7 | Initial window density | Representative available-screen geometries, including a short Mac work area and minimum supported size | Initial window fits the work area; sidebar footer, header/actions, and current setting remain reachable |
| Bundle A / A8 | Fixture quality | Real normalized morphology and long many-sense popup data | Regression fails for the diagnosed behavior without encoding the desired result in a fake |
| **Deferred — Bundle B** | Full popup reference match | Typography, pronunciation, chips, grammar disclosure, navigable alternatives | Not an A acceptance gate; revisit under Section 7 trigger |
| **Deferred — Bundle B** | HTML/CSS popup renderer | Renderer/process/lifecycle comparison | Not an A acceptance gate; requires a separate architecture decision |
| **Deferred — Bundle B** | Custom listboxes | Three native `<select>` surfaces and full accessible interaction | Not an A acceptance gate; revisit during authorized Control Center polish |
| **Deferred — Bundle B** | Motion and render churn | Native macOS frame behavior and snapshot rerenders | Not an A acceptance gate; requires measured native evidence |
| **Deferred — Bundle B** | Real-screen crop corpus | Labeled source screenshots, ground truth, scaling, ROI, OCR, target, and result | Not an A acceptance gate; revisit before recognition tuning |
| **Deferred — Bundle B** | Windows/macOS platform UI | Windows title bar and AppKit/Liquid Glass port | Not an A acceptance gate; use the platform-specific triggers in Section 7 |
| **Deferred — future product scope** | OCR model research, accessibility-text acquisition, localization, contextual sense disambiguation, generated examples | Outside the decided correction bundle | Not an A acceptance gate; use the individual triggers in Section 7 |

Planned native acceptance procedure for Bundle A: launch through `hanly` or `python -m hanly_app`, use a controlled Korean source, and exercise the A2 forms at relevant character positions. Toggle a long popup compact → expanded → compact, then verify sticky behavior across mouse exit, chord release, Escape, outside click, and a new lookup. Exercise clipped text at ROI/monitor boundaries separately from a fully visible OCR misreading. Minimize and reopen the Control Center repeatedly, then inspect the initial window on a short available work area. Confirm the source application keeps keyboard focus where the popup contract requires it. This is a procedure for the later executor, not a claim that interactive or native verification has already occurred.

## 7. Scope review and deferred Bundle B

The diagnosis remains supported by Section 2, but the former plan mixed correctness repairs, interaction policy, visual redesign, renderer research, and platform modernization. Bundle A was the smallest coherent correction set at the time. It was subsequently implemented and reviewed; Section 0 records the result and links the narrower successor plan created from live/native evidence. That successor does not authorize any Bundle B item below.

### Why the old pointer-retention work is no longer needed

The old P4 steps for pointer-stable resize anchoring, separating same-result geometry updates from `retain(new_result)`, and a bounded resize-transfer grace existed to keep a popup alive while the pointer crossed from the source word into the card. A4 changes the product rule: mouse exit and chord release no longer dismiss an opened popup. Escape, outside click, or the next lookup are explicit dismissal events. With that policy, pointer crossing is not a lifetime transition, so those mechanisms add complexity without enforcing the chosen behavior. Request currency remains mandatory because it prevents stale lookup results, not because it controls dismissal.

### Bundle B — separately authorized later

| Deferred work | Why it remains valid | Revisit trigger |
|---|---|---|
| Full popup visual reference match | Typography, pronunciation, chips, grammar disclosure, navigable alternate entries, detailed spacing, and broader theme fidelity are real learner-facing improvements, but A1/A2/A3 must stabilize the data and measurement first. | After Bundle A is accepted and the popup's structured data, sticky lifetime, and measured geometry are stable. |
| Conditional HTML/CSS popup renderer | It may improve fidelity, but it does not solve OCR, lexical selection, or dictionary loss. `CLAUDE.md` warns against loading another WebEngine into the permanent shell because WebEngine is isolated in the Control Center child for lifecycle and memory reasons. | Only if the bounded Qt repair fails native popup requirements, followed by a separately approved architecture spike covering process ownership, focus, input, stale results, cleanup, performance, and packaging. |
| Custom accessible listbox for the three native `<select>` controls | The macOS screenshot confirms a real visual mismatch, but it is cosmetic relative to Bundle A and replacing native controls requires a complete accessible interaction model rather than a styled fragment. | During a separately authorized Control Center polish bundle after A6/A7, with keyboard, focus, screen-reader, outside-click, scrolling, and rerender behavior in scope together. |
| macOS motion measurement and render-churn reduction | Option rebuilding, duplicate settings renders, polling, and replayed entrance motion are plausible sources of lag, but Section 2 records no native timing measurement. | After Bundle A functional behavior is accepted, or earlier only if measured native lag blocks A6/A7 verification. |
| Labeled real-screen crop corpus | Real screen evidence would support recognition tuning, but A8's deterministic perfect-text and geometry fixtures are sufficient for the decided corrections. Arbitrary captured content also requires an opt-in privacy discipline. | Before any work that tunes OCR recognition, confidence policy, non-clipping retries, or claims real-world accuracy improvement. |
| Windows top/title bar | The defect needs Windows-native screenshots and window-state behavior; speculative changes from macOS cannot be accepted. | First Windows-native UI session or before the next Windows release candidate, whichever comes first. |
| macOS AppKit/Liquid Glass port | A native replacement may be desirable after the interaction and visual design are finished, but it changes process ownership, the Python bridge, packaging, accessibility, updates, and parity expectations. | After the current design and Bundle A behavior are accepted, through a separate Xcode/AppKit feasibility and architecture decision. |

### Further deferred product work

| Deferred work | Rationale | Revisit trigger |
|---|---|---|
| Model fine-tuning or another OCR implementation | EasyOCR remains the sole V1 backend and clipping recovery does not establish a recognition-model case. | After a representative authorized OCR corpus shows residual recognition errors that materially block the product. |
| Accessibility-text acquisition | It is a different acquisition path and scope, not a correction to the approved screenshot/OCR pipeline. | When the product explicitly authorizes a non-OCR acquisition mode and its platform/privacy design. |
| Output-language localization | Bundle A exposes the English data already present; it does not add translation services. | When target languages and a localization/data source are approved. |
| Automatic contextual sense disambiguation | Isolated forms and same-POS homonyms lack enough context; silently choosing one would overclaim accuracy. | After structured senses and candidates are stable and a contextual corpus demonstrates a testable policy. |
| Generated bilingual examples | Invented learner text is not acceptable without a genuine source and provenance. | When an approved licensed/source-normalized example pipeline exists. |

### Decisions retained and rejected

- Keep raw morphemes separate from lookup candidates, structured senses paired by identity, one request-wide clipping retry, app-owned recapture, provider normalization, bounded/latest-wins execution, and final request-currency validation.
- Reject blanket ROI enlargement, appending `다` to every first token, whole-surface-first lookup, returning the first hit from unrelated candidates, arbitrary confidence thresholds, the unmeasured 400×100 cap, and renderer migration as a bugfix shortcut.
- Same-POS ambiguity remains visible rather than being silently discarded. Phrase lookup remains a later span-policy capability.
- The `hanly-app → hanly` direction, external-provider seams, small-ROI flow, and UI-independent `LookupResult` remain unchanged. Any future renderer or AppKit change requires the approval stated above.

## 8. References and reproductions

### References for the executor

- `docs/CODE-MAP.md`
- `docs/architecture/01-runtime-flow.md` through `04-agent-execution-flow.md`
- `docs/execution/05-execution-plan.md`
- `docs/execution/reports/ocr-latency-and-roadmap.md` — especially §3.6 and rejected tuning; historical Paddle sections are superseded.
- `docs/execution/review-handoffs/popup-redesign-2026-09-18.md` — records the prior visual redesign and its untested native interactions.
- `.design-reference/popup/Hanly Popup Prototype.dc.html` and `.design-reference/Hanly Prototype.dc.html`; adjacent `support.js` files support the prototypes, not a production renderer.
- Installed Kiwi `_wrap.py` / `const.py` are the exact-version API evidence for `Match.JOIN_V_SUFFIX`; [official Kiwi repository](https://github.com/bab2min/kiwipiepy) documents the tokenizer and reconstruction APIs.
- [Qt layout management](https://doc.qt.io/qt-6/layout.html) and [QLayout](https://doc.qt.io/qt-6/qlayout.html) document width-dependent layout measurement. The defect diagnosis above comes from the local executable probe, not documentation alone.

### Minimal reproduction snippets

Run from the repository root using the existing venv. These investigate behavior without changing project code.

```python
from kiwipiepy import Kiwi, Match
from hanly.kiwi_provider import KiwiProvider
from hanly.krdict_provider import KRDICTProvider

kiwi = Kiwi()
dictionary = KRDICTProvider("data/generated/krdict.sqlite3")
for text in ("사과했어요", "예뻤어요", "떨어뜨렸어요", "깨뜨렸습니다"):
    raw = kiwi.tokenize(text)
    joined = kiwi.tokenize(text, match_options=Match.ALL | Match.JOIN_V_SUFFIX)
    print(text, [(t.form, t.tag, t.lemma, t.start, t.len) for t in raw])
    print("joined", [(t.form, t.tag, t.lemma) for t in joined])
    selected = KiwiProvider(kiwi).analyze(text)[0].lemma
    print("current selection", selected, dictionary.lookup(selected))
dictionary.close()
```

For popup reproduction, construct `LookupResult(SUCCESS, entries=provider.lookup("떨어뜨리다"), context=LookupContext(text="떨어뜨렸어요", lemma="떨어뜨리다", analyses=tuple(KiwiProvider().analyze("떨어뜨렸어요"))))`, open it through `PopupController(QtPopupView(...))`, and activate the density button. Inspect geometry only after the event loop has processed layout and deferred deletion; compare initial compact, expanded, then collapsed, and record viewport/content heights and scrollbar policy/range. A second explicit measurement after settled layout restored expanded height in the investigation; use that as diagnostic evidence, not as a production `processEvents()` workaround.
