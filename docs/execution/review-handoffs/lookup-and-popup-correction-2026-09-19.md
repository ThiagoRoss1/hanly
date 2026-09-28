# Lookup and popup correction (Bundle A) Review Handoff

## Bundle

- Member issues: plan-local work packages A1–A8 from
  `docs/execution/plans/lookup-and-popup-correction-2026-09-19.md`. No Linear
  issues were created or mutated.
- Implementation ecosystem: Claude Opus 5, single session, macOS 26.6.2,
  repository `.venv` (Python 3.13).
- Date: 2026-09-19
- Branch: `visual/interface-update`. **Nothing is committed** — see
  *Environment* below.

## Implemented

- **A1** KRDICT short glosses reach the popup. The runtime query now selects
  `t.lemma`; `DictionaryEntry` carries ordered `DictionarySense` values with a
  stable id, and the popup renders the gloss as primary text above its own
  definition.
- **A2** Lexical-unit selection. `MorphologyAnalysis` and `LexicalCandidate`
  join the engine contracts; the Kiwi adapter reconciles a raw and an
  affix-joined token stream by span; the pipeline selects the unit under the
  pointer instead of `lemmas[0]`.
- **A3** Popup measurement. Rebuilt children are made visible before the card is
  measured, and wrapped height is measured at the real viewport width with one
  bounded scrollbar pass.
- **A4** Sticky popup lifetime under Push to Hover, with Tier 1 dismissal:
  next result, chord re-press, and a footer **Close** control.
- **A5** *(core only)* Clipping detection, monitor-constrained widening, and
  cursor re-projection in a new `capture_recovery.py`. **The recapture wiring is
  not implemented** — see *Known limitations*.
- **A6** A minimized Control Center is restored before it is shown.
- **A7** The initial Control Center size is derived from the work area.
- **A8** Focused fixtures landed with the package each one serves.

## Main expected behavior

Hovering any syllable of `사과했어요` now answers `사과하다 · apologize` instead of
the fruit. `예뻤어요`, `떨어뜨렸어요` and `깨뜨렸습니다` likewise resolve to their
full lexical unit with the correct short gloss. `책읽는` answers `책` or `읽다`
depending on which syllable the pointer is on. The card no longer shrinks on
expand or collapse, and it stays on screen after the cursor leaves the word so
it can be read and reached. A minimized Control Center reopens, and its first
window no longer nearly fills a laptop display.

## Architecture / seams touched

- `MorphologyProvider.analyze()` now returns `MorphologyAnalysis | Sequence[TokenAnalysis]`.
  `MorphologyAnalysis` **is** a `Sequence[TokenAnalysis]`, so providers and
  consumers written against the old contract are unaffected; the pipeline
  normalizes both shapes at the seam.
- `WordResolver.resolve_target()` is unchanged. `resolve_target_detail()` is
  added beside it and probed for, so a substituted resolver stays valid.
- `DictionaryEntry` gains `senses` and `entry_id`; `definitions` is derived and
  still works for definition-only providers.
- `LookupContext` gains `candidate`.
- Package direction, small-ROI capture, bounded/latest-wins submission, and the
  final request-currency check are unchanged. No Kiwi or SQLite object crosses a
  provider seam.

## Relevant files / diff areas

- Engine: `contracts.py`, `providers.py`, `kiwi_provider.py`,
  `krdict_provider.py`, `word_resolver.py`, `lookup_pipeline.py`, `__init__.py`
- Desktop: `qt_popup.py`, `popup.py`, `hover_lookup.py`, `manual_lookup.py`,
  `control_center_host.py`, `control_center_process.py`, new `capture_recovery.py`
- Tests: `test_core_contracts.py`, `test_provider_interfaces.py`,
  `test_kiwi_provider.py`, `test_krdict_provider.py`, `test_lookup_pipeline.py`,
  `test_popup.py`, `test_hover_target.py`, `test_hover_lookup.py`,
  `test_control_center_host.py`, new `test_capture_recovery.py`,
  `test_engine_e2e.py`, `krdict/test_pipeline.py`, `krdict/test_runtime_schema.py`,
  `hanly_fixtures/krdict.py`, `native/shared/test_qt_popup_window.py`,
  `native/shared/test_hover_exit_qt.py`

## Implementation-side validation already run

- `pytest --suite portable` → 1600 passed, 1 skipped (baseline 1557)
- `pytest --suite native` → 32 passed, 11 skipped, 24 errors (see below)
- `ruff check packages packaging tests tools benchmarks` → All checks passed
- `mypy packages packaging tests tools benchmarks` → Success, 246 source files
- End-to-end through real Kiwi, real KRDICT and the production pipeline: the
  four reported forms resolve correctly at **every** syllable position, with the
  required glosses.
- Offscreen Qt render: gloss in `hanlyPopupSense` (14 px/600), definition in
  `hanlyPopupSecondary` (12 px).
- Production expand/collapse measured before and after: 386×196 → 386×681 on
  expand, 340×96 → 340×241 on collapse.
- Native popup density test reproduced failing locally, then passing, five
  consecutive runs.

The 24 native errors are **environmental, not this bundle**: every one is
`test_update_posix_native.py` failing to compile its C helper because `cc` is an
Xcode shim blocked by an unaccepted Xcode licence. The same licence blocks git.

## Known limitations / intentionally unvalidated areas

- **A5 is half-delivered.** The clipping decision, widening and coordinate maths
  are implemented and tested; the recapture-and-resubmit wiring is not. No
  clipped capture is recovered at runtime yet. The checkpoint records the exact
  resume point. Nothing is blocked — the seams were checked and exist.
- **No commits.** git is unavailable this session (Xcode licence). The checkpoint
  lists the file set for each of the eight intended commits, in order.
- **No live hover was performed.** Every popup and hover result here comes from
  offscreen or native-widget tests, never from hovering real text on screen. The
  plan's own Section 2 states interactive hover was never exercised; that is
  still true.
- **A6's real macOS behaviour is unverified.** The restore ordering is proved
  against a fake pywebview window. Whether clicking the Dock tile reaches the
  focus path at all is not established.
- **A7's appearance is unverified.** The arithmetic is tested; how the denser
  window looks with real content needs a real launch.
- **Windows and Linux are unexercised.** Only macOS native was run locally.
- **Multi-monitor is unexercised.** A3's one-screen rule is implemented on a
  single-display machine.
- A5's tolerance was measured on synthetic renders of five words, not on real
  screen captures.

## Suggested review targets

- `_as_morphology_analysis` and `_select_candidate` in `lookup_pipeline.py`:
  the legacy-provider fallback path, and whether nearest-candidate selection can
  ever pick a unit the user is not pointing at.
- `MorphologyAnalysis` as a `Sequence`: whether any consumer distinguishes it
  from a tuple in a way the compatibility shim misses.
- `DictionaryEntry.__post_init__`: the derive-and-disagree rules, and whether
  excluding `sense_id`/`entry_id` from equality is right for the public contract.
- `_reveal()` in `qt_popup.py`: showing widgets during a rebuild, and whether it
  can fight the scroll area or flicker on a visible card.
- A4's lifetime change in `hover_lookup.py`: `_release_retained` versus
  `_dismiss_retained`, and whether any path can now leave a card on screen with
  no way to dismiss it.
- Whether tying stickiness to `HoverActivation` is the right rule.
- The eight commit groupings recorded in the checkpoint, before they are made.

The reviewer and ecosystem are human-selected. This handoff prepares that review;
it does not perform one.

---

## Post-Bundle Review Outcome

- **Reviewer:** Claude Opus 5, same session as the implementation
- **Ecosystem:** same-ecosystem review, human-selected
- **Date:** 2026-09-19
- **Status:** complete. One fix applied under cheap defensive hardening; eight
  findings recorded for a separately authorized run.

**A same-ecosystem review is the weakest configuration available.** `05` names
cross-provider review as often more valuable precisely because a reviewer with
different execution context catches different defects. I wrote this code hours
ago, so I share its blind spots. The findings below are real, but their absence
in an area is weak evidence that the area is clean.

### Fixed now

**R1 — Pinning an unavailable recognizer failed once per lookup instead of once
at load.** `HanlyRuntime._wants_vision()` returned `True` for
`ocr_backend: "vision"` without checking availability, so a Windows or Linux
profile pinning Vision constructed a provider that raised
`VisionProviderError` on *every* lookup. Now `RuntimeConfigError` at
configuration load, naming the working alternatives. `auto` still falls back
silently, which is the point of `auto`. Two tests cover both paths.

This met every condition in *Cheap defensive hardening*: a configuration
boundary, obvious, no architecture change, converts a repeated obscure runtime
failure into one clear configuration error, and cheaper to fix than to carry.

### Deferred considerations

Ordered by what I would fix first.

**R2 — A4's stickiness does not follow a live activation change.** `_sticky` is
set only in `HoverLookupRuntime.__init__`. `ManualLookupRuntime.apply_config()`
handles a live Push to Hover ↔ Always Active switch (`_release_push`,
`_apply_activation_mode`) but never updates it, so the popup lifetime stays at
whatever it was when the runtime was built. A user toggling the mode in
Settings gets the other mode's dismissal behaviour until restart.
*Fix shape:* a `set_sticky()` on the runtime, called from `apply_config`.
*Revisit:* before any release that ships the sticky popup, since the setting is
user-visible and the wrong behaviour is silent.

**R3 — `capture_recovery.py` is dead code with tests that imply otherwise.**
Nothing in `packages/` imports it; only its own test file does. Eight passing
tests and a green suite give a reader the impression clipping recovery exists.
It does not: no clipped capture is recovered at runtime.
*Revisit:* when A5's wiring is authorized, or delete the module if A5 is
dropped in favour of the Vision work, which removes much of its motivation.

**R4 — The Vision adapter discards real quad geometry.** `_normalize()` uses
`observation.boundingBox()`, which is axis-aligned, while
`VNRecognizedTextObservation` exposes `topLeft` / `topRight` / `bottomRight` /
`bottomLeft`. `WordResolver` documents that it hit-tests the real
quadrilateral because a derived rectangle "cannot decide a hit for tilted
text", so the Vision path is strictly less faithful than the EasyOCR path.
Low impact in practice: on-screen UI text is almost always axis-aligned.
*Revisit:* before Vision becomes the shipped default on macOS, or sooner if
rotated text is ever a target.

**R5 — `_select_candidate`'s fallback fabricates a span.** When a provider
reports no spans it returns
`LexicalCandidate(lemma=lemma, start=0, end=max(1, len(lemma)))`. Those offsets
describe the *lemma*, not the analyzed text, and the value reaches
`LookupContext.candidate`, which is documented as naming "which part of `text`
the answer is about". A client highlighting that span would highlight the wrong
characters.
*Fix shape:* leave `candidate` unset on the spanless path, or carry an explicit
"span unknown" marker.
*Revisit:* before any client uses `candidate` for presentation; nothing does yet.

**R6 — `_reveal()` will unhide a deliberately hidden widget.** It calls
`setVisible(True)` on every widget in the rebuilt content and footer layouts.
No current widget is intentionally hidden, so it is correct today, but it makes
"hidden" unusable as a state inside the popup for anyone who adds one later.
*Revisit:* when the popup next gains conditional content, e.g. the Bundle B
reference match.

**R7 — The silent-acceptance pattern appeared three times in one bundle.**
`SETTABLE_FIELDS` accepted `ocr_backend` while `candidate()` dropped it; the
readiness panel reported a hardcoded `EasyOCR` regardless of the setting;
obsolete popup children kept painting after being removed from their layout.
Each passed its tests, because every test asserted the happy path and none
asserted the change took effect. The generic
`test_a_settable_field_actually_survives_being_set` now closes one instance.
*Revisit:* worth one pass asking, for each user-visible setting, "what test
would fail if this silently did nothing?"

**R8 — `VisionProvider.is_available()` reloads the framework on each call.** It
constructs a throwaway provider and resolves classes rather than caching at
module level, and `_wants_vision()` calls it per `_ocr_factory()`. Negligible
today (once per engine load), but it is a surprising cost for a predicate.
*Revisit:* if backend selection ever moves onto a per-lookup path.

**R9 — A no-screen environment yields a 32768 px height bound.**
`_available_height()` returns `2 ** 15` when no screen resolves, so
`min(desired, max_height)` leaves `desired` unclamped and the popup is fixed to
its full content height. Harmless where a popup implies a display.
*Revisit:* if headless or virtual-display usage is ever supported.

### Dismissed

- **`MorphologyAnalysis` as a `Sequence` breaking a consumer.** Checked every
  call site: `self_check.py:362`, the `_TracingMorphologyProvider` token and
  Hangul counts, and the pipeline's own normalization all behave identically to
  the old tuple. Pickle round-trips across the lookup-child boundary.
- **`sense_id` / `entry_id` excluded from equality weakening the contract.**
  They are SQLite row ids; including them would couple test expectations to
  builder internals and break `tests/krdict/test_pipeline.py` on any rebuild
  that renumbers rows. Sense content still compares.
- **Thread-safety of `VisionProvider._classes`.** Providers are constructed per
  worker thread and never shared, which the runtime's factory design enforces.
- **`_EntryRows.add_sense()` being O(n²) per entry.** Entries have single-digit
  sense counts; the largest observed is twelve.

### Not reviewed

- Anything requiring **live hover on real screen content**. Still zero real
  captures; every OCR result in this bundle came from rendered text.
- **Windows and Linux.** Only macOS was exercised.
- **The 24 native errors**, which are an unaccepted Xcode licence blocking `cc`,
  not code.
- **The minimize/restore defect the human asked to carry into Phase B.** It is
  unwritten A6 scope — the Dock-reopen route — so a review cannot produce it.
  It remains a work item, recorded in the checkpoint.

### Post-review defect found in live use (2026-09-19, same session)

**R10 — the recognizer choice never crossed the spawn boundary. Fixed.**

Reported as "even with Apple Vision it gets the same word". It did, because
every lookup was still running EasyOCR.

`LookupProcess` deliberately does not receive a `HanlyRuntime` — it takes its
own `LookupSettings` across the spawn boundary — and `_build_worker()`
constructed `EasyOCRProvider` unconditionally. So `HanlyRuntime._ocr_factory()`
selected Vision in the shell, the readiness panel truthfully reported "Apple Vision",
and the child that actually performs OCR ignored all of it.

The give-away was the popup title: `떨어뜨렇어요`, character-for-character the
EasyOCR misread, when Vision reads that word at confidence 1.00 in a realistic
200×100 ROI.

**Fix:** `ocr_backend` now travels in `LookupSettings`, and the child builds
from it.

**Second defect found while fixing the first:** resolving `auto` *inside* the
child hung `tests/test_lookup_process.py` indefinitely — loading
`Vision.framework` from a spawned process under pytest blocks. The parent now
resolves `auto` to a concrete backend before sending it
(`HanlyRuntime.resolved_ocr_backend()`), so the child receives a decision
rather than a policy and never loads a framework to ask about one. That suite
went from hanging to 2.6 s.

**Why the review missed it:** Phase B inspected the seam the *shell* uses and
confirmed it resolved correctly. It never asked whether the process that
actually runs OCR uses that seam. Both `_ocr_factory()` and the readiness label
agreed with each other and were both irrelevant to the running lookup — a
consistent, verifiable, wrong answer.

This is the **fourth** instance of the R7 pattern in this bundle: a control
that reports success while the effect never reaches the code that matters.
R7's suggested sweep should be considered required rather than optional.

**Regressions added:** the child's factory honours each backend, `auto` never
reaches the child, and the runtime sends a resolved value.

**Gates:** `pytest --suite portable` 1628 passed, 2 skipped · `ruff` clean ·
`mypy` 248 files clean.
