# Live checkpoint — lookup and popup correction (Bundle A)

**Plan:** `docs/execution/plans/lookup-and-popup-correction-2026-09-19.md`
**Phase:** A (implementation). Ends at one Review Handoff. Phase B is not authorized.
**Branch:** `visual/interface-update`

## Environment state

**Git is unavailable this run.** `/usr/bin/git` is an Xcode shim and the Xcode
licence has not been accepted, so every git invocation fails. The human chose to
defer `sudo xcodebuild -license accept`. Consequence: the authorized per-package
commits **cannot be made during this run**. Each package still records its file
set below so the eight commits can be replayed in order once git works.

Baseline verified before any change:

| Check | Result |
|---|---|
| `ruff check packages packaging tests tools benchmarks` | All checks passed |
| `mypy packages packaging tests tools benchmarks` | Success, 244 source files |
| `pytest --suite portable` | 1557 passed, 1 skipped |
| focused set (plan §2) | 88 passed |

One pre-existing failure was found and fixed before starting: the editable
install was stale (`hanly-app` metadata `0.5.2` vs `pyproject.toml` `0.5.3`),
failing `tests/test_release_version.py`. Reinstalled with `pip install -e ... --no-deps`.
That is an environment repair, not a repository change.

Known failing and **not** a regression: the macOS native case
`test_compact_and_expanded_sizes_follow_content_without_clipping` reads 640×480
instead of 386. It is A3's acceptance target.

---

## A1 — Short translations and structured senses

### Decision A1.1 — no schema change, no database rebuild

**Decision:** Implement A1 purely as a query and contract change in
`packages/hanly/src/hanly/krdict_provider.py` and `contracts.py`. Do not touch
`krdict_schema.py`, `tools/krdict/`, or the generated database.

**Why:** `krdict_schema.py:33` already lists `lemma` as a required column of
`translations`, so the short gloss is part of the validated contract every
shipped database satisfies. Confirmed against the live database: `사과하다` →
`apologize`, and `예쁘다` returns three senses with distinct glosses
(`pretty; beautiful; comely` / `adorable` / `nice; good`). The data was always
there; only the SELECT and the flattening discarded it.

**Still unverified:** nothing for this decision. It settles the operator-notes
question "Database rebuild required" as No.

### Decision A1.2 — `senses` is canonical, `definitions` is a derived view

**Decision:** `DictionaryEntry` accepts either representation and derives the
other in `__post_init__` (`contracts.py`). Supplying both with different content
raises. `DictionarySense` carries `definition`, optional `gloss`, optional
`sense_id`.

**Why:** The plan requires one canonical conversion path rather than two
representations that can contradict each other. Deriving means a definition-only
provider keeps working untouched and a gloss-carrying provider needs no second
code path. Raising on disagreement makes a contradiction impossible to express
rather than merely discouraged.

**What it does:** `DictionaryEntry("책", ("a book",))` still constructs and now
also exposes `senses`. `DictionaryEntry(headword=..., senses=(...))` exposes
`definitions` derived in sense order.

**Still unverified:** nothing.

### Decision A1.3 — `sense_id` and `entry_id` are excluded from value equality

**Decision:** Both are `field(..., compare=False)`.

**Why:** They are SQLite row ids — build artifacts, not dictionary content. Four
existing tests compare provider output to hand-built entries, and
`tests/krdict/test_pipeline.py` compares against the *production* database; if
row ids participated in equality, a KRDICT rebuild that renumbered rows would
break those tests without any dictionary content changing. Value equality should
mean "same word, same senses".

**Rejected alternative:** keeping them in equality and pinning row numbers in
tests. That couples test expectations to builder internals for no benefit; the
ids exist so a client can tell senses apart, not so tests can assert them.

**Observations:** excluding the ids did *not* by itself fix the four failing
tests, which is the correct outcome — the gloss is genuine new content, so those
expectations had to be updated to carry it rather than hidden. Updated:
`tests/krdict/test_runtime_schema.py`, `tests/test_engine_e2e.py` (two cases),
and `READ_ENTRY` in `tests/krdict/test_pipeline.py` (nine real production
glosses).

**Still unverified:** nothing.

### Decision A1.4 — deduplicate on the gloss-and-definition pair, not the definition

**Decision:** `_EntryRows.add_sense()` in `krdict_provider.py` treats a sense as
duplicate only when gloss *and* definition both match.

**Why:** the previous `definition not in definitions` check is precisely what
discarded distinct senses. Section 2D requires senses with equal definitions but
different glosses to stay separate.

**Observations:** the production database has exactly one English translation per
sense (0 senses with more) and no empty English glosses, so `sense_id` is the
sense's own row id. The shared fixture database *does* have a two-equivalent
sense (`책`), so both shapes are exercised.

**Still unverified:** nothing.

### A1 validation and state

| Check | Result |
|---|---|
| `ruff check packages packaging tests tools benchmarks` | All checks passed |
| `mypy packages packaging tests tools benchmarks` | Success, 244 source files |
| `pytest --suite portable` | 1563 passed, 1 skipped (was 1557; six new cases) |
| Offscreen Qt render | gloss in `hanlyPopupSense` (14px/600), definition in `hanlyPopupSecondary` (12px) |
| Live database | `사과하다`→`apologize`, `예쁘다`→three distinct glosses, `떨어뜨리다`→`drop`, `깨뜨리다`→`break; smash` |

**State:** A1 complete. **Commit pending** — git unavailable. Files for commit 1
(`fix: preserve short translations in dictionary results`):

```
packages/hanly/src/hanly/contracts.py
packages/hanly/src/hanly/krdict_provider.py
packages/hanly/src/hanly/__init__.py
packages/hanly-app/src/hanly_app/popup.py
packages/hanly-app/src/hanly_app/qt_popup.py
tests/hanly_fixtures/krdict.py
tests/test_core_contracts.py
tests/test_krdict_provider.py
tests/test_popup.py
tests/test_engine_e2e.py
tests/krdict/test_pipeline.py
tests/krdict/test_runtime_schema.py
```

**Resume point:** A2 — lexical-unit selection. Start at
`packages/hanly/src/hanly/kiwi_provider.py` and `lookup_pipeline.py:169`.

---

## A2 — Lexical-unit selection

### Decision A2.1 — `MorphologyAnalysis` is itself a `Sequence[TokenAnalysis]`

**Decision:** `MorphologyAnalysis` subclasses `collections.abc.Sequence` over its
own `tokens`, so `len()`, iteration, indexing, `tuple(...)` and truthiness all
behave as the old return value did.

**Why:** the plan requires changing the morphology contract without invalidating
providers and consumers written against `Sequence[TokenAnalysis]`. Making the
new type *be* the old shape means `self_check.py:362`, the tracing wrapper's
`len(result)` in `composition.py:778`, and every `tuple(...)` call site keep
working untouched, instead of a migration that edits each one.

**Rejected alternative:** a separate `analyze_detailed()` method beside
`analyze()`. That leaves two code paths in every adapter and wrapper and makes
the richer result the exception rather than the norm.

**Still unverified:** nothing. Round-tripped through `pickle`, which is what the
lookup child's transport uses.

### Decision A2.2 — candidates come from Kiwi's joined stream, raw tokens are kept

**Decision:** `KiwiProvider.analyze()` tokenizes twice — once plainly, once with
`Match.ALL | Match.JOIN_V_SUFFIX` — and reconciles them by source span inside
the adapter. `_CandidateBuilder` groups each content token with the endings,
particles and derivational suffixes that follow it.

**Why:** the joined stream is the only route to `사과하다` that does not append
`다` to a stem, which the plan rejects and which produces wrong forms for
irregulars. Keeping the raw stream preserves `하/XSV` and `었/EP` for the
learner-facing explanation, which a joined-only stream would hide.

**What it does:** `사과했어요` yields one candidate `사과하다` spanning the whole
string, so every syllable selects it. `책읽는` yields `책` (0,1) and `읽다` (1,3),
so the pointer decides. `책을` yields `책` spanning (0,2), so hovering the
particle still selects the noun. Punctuation never opens a candidate.

**Observations:** measured cost of the second pass on this machine —
raw tokenize 0.021 ms/word, full `analyze()` 0.058 ms/word, so the added cost is
**0.037 ms/word**. Against a hover budget in the hundreds of milliseconds this
is not worth optimizing away, and reusing one pass for both views is not
possible because the two streams differ by design.

An injected test double without `match_options` support returns no candidates
rather than failing; selection then falls back to the first usable lemma.

**Still unverified:** nothing at this layer.

### Decision A2.3 — a cursor outside every candidate picks the nearest, not nothing

**Decision:** `MorphologyAnalysis.candidate_at()` returns the containing
candidate, or the nearest one by character distance when none contains the index.

**Why:** punctuation is deliberately never a candidate, so a pointer resting on
`“` in `“예뻤어요”` falls outside every span. Refusing would reproduce the old
`NOT_FOUND: punctuation selected as lemma` defect in a new form. Answering with
the adjacent word is what the reader is plainly pointing at, and the punctuation
itself is still never looked up.

**Still unverified:** whether the nearest-candidate rule ever feels wrong in live
hover. It cannot produce a punctuation lookup, which was the reported defect.

### Decision A2.4 — `resolve_target()` is untouched; the richer API sits beside it

**Decision:** `WordResolver.resolve_target_detail()` returns a `TargetResolution`
carrying region, word, cursor index within that word, and the word's offset in
the region. `LookupPipeline._resolve_target()` uses it when the resolver offers
it and falls back to the pair API otherwise.

**Why:** composition can substitute a resolver (`word_resolver_factory`), and the
`TargetResolver` protocol is public. Probing for the richer method keeps every
existing resolver valid; a substituted resolver simply gets cursor index 0 and
the old first-unit behavior.

**Observations:** `_word_at_target` became `_locate_word_at_target`, returning
the word plus its offsets. The cursor index is relative to the *stripped* word,
which is safe because a whitespace-delimited span cannot begin with whitespace.

**Still unverified:** nothing.

### Decision A2.5 — the reduction diagnostic counts lexical units, not whitespace

**Decision:** `_selection_diagnostics()` fires when the analysis holds more than
one candidate and names the unselected lemmas.

**Why:** the old condition was `len(text.split()) > 1`, which cannot see
`책읽는` — Korean writes compounds without spaces, so whitespace counting misses
exactly the ambiguous cases the diagnostic exists for. The plan calls this out.

**Observations:** the replaced test
`test_multi_word_segment_reports_that_only_the_first_lemma_was_used` asserted the
old first-lemma policy, which the plan directs to replace rather than extend. It
is now `test_a_provider_without_spans_keeps_the_first_usable_lemma` (compatibility)
plus `test_the_pointer_chooses_among_several_lexical_units` (the new policy).

**Still unverified:** nothing.

### A2 validation and state

End-to-end through real Kiwi, real KRDICT and the production pipeline, at every
syllable position:

| Surface | Every syllable resolves to | Gloss |
|---|---|---|
| 사과했어요 | 사과하다 | apologize |
| 예뻤어요 | 예쁘다 | pretty; beautiful; comely |
| 떨어뜨렸어요 | 떨어뜨리다 | drop |
| 깨뜨렸습니다 | 깨뜨리다 | break; smash |
| 책읽는 | 책 at index 0, 읽다 at 1–2 | — |

| Check | Result |
|---|---|
| `ruff` / `mypy` | All checks passed / Success, 244 files |
| `pytest --suite portable` | 1580 passed, 1 skipped |
| Acceptance cases | 14 forms × every syllable, via real Kiwi |

**State:** A2 complete. **Commit pending** (git unavailable). Files for commit 2
(`fix: select complete Korean lexical units`):

```
packages/hanly/src/hanly/contracts.py
packages/hanly/src/hanly/kiwi_provider.py
packages/hanly/src/hanly/lookup_pipeline.py
packages/hanly/src/hanly/word_resolver.py
packages/hanly/src/hanly/providers.py
packages/hanly/src/hanly/__init__.py
tests/test_kiwi_provider.py
tests/test_lookup_pipeline.py
tests/test_core_contracts.py
tests/test_provider_interfaces.py
```

**Resume point:** A3 — popup measurement repair, at `qt_popup.py:121` and
`_resize_to_content()`.

---

## A3 — Popup measurement repair

### Decision A3.1 — the plan's `deleteLater()` hypothesis is wrong; hidden children are the cause

**Decision:** the shrink is fixed by making rebuilt children visible before the
card is measured (`_reveal()` in `qt_popup.py`), not by changing how old children
are removed.

**Why:** measured, not assumed. Replacing `deleteLater()` with immediate
`setParent(None)` in an isolated process left the defect exactly as it was.
Instrumenting the layout straight after `_rebuild()` showed
`hasHeightForWidth() == False` and `sizeHint() == (36, 178)`; after one event
cycle the same layout reported `hasHeightForWidth() == True`,
`heightForWidth(384) == 640` and `sizeHint() == (304, 820)`.

The mechanism: a widget added to a layout is only shown when the event loop next
runs, and `QBoxLayout` ignores hidden items. So the card was being sized from an
almost-empty layout. Section 2C recorded the symptom and correctly hedged that
it "does not establish that `deleteLater()` alone is the cause" — it is not the
cause at all.

**What it does:** `_reveal()` walks the rebuilt content and footer layouts and
shows each widget, so the very next measurement sees real wrapped text.

**Observations:** production expand/collapse before and after, same content:

| Step | Before | After |
|---|---|---|
| compact | 340×241 | 340×241 |
| expand | 386×196 | 386×681 |
| collapse | 340×96 | 340×241 |

**Still unverified:** nothing at this layer; live hover feel is A-wide.

### Decision A3.2 — measure wrapped height at the real width, with one scrollbar pass

**Decision:** `_measure_content(width)` sets the host width, polishes, reveals,
activates the layout and returns `heightForWidth(width)`, falling back to
`sizeHint().height()`. `_resize_to_content()` measures once, and if the result
exceeds the work area measures a second time at the width left after the
scrollbar.

**Why:** wrapped text has no single natural height; it must be asked for at the
width it will occupy. The old code fixed the host to `width - 2` and read an
unconstrained `sizeHint()`. A visible scrollbar then narrows the text further,
which makes it wrap taller — one bounded second pass settles that instead of
looping.

**Still unverified:** behaviour on a very small work area is covered by the
`max(96, ...)` clamp but has not been exercised on a real short display.

### Decision A3.3 — one screen is chosen at placement and reused for measurement

**Decision:** `QtPopupView._screen` records the screen the result was placed on;
`_available_height()` prefers it over the screen under the cursor.

**Why:** Section 2C records that measurement used the screen at the *current*
cursor while the controller retained the *original* screen, so an interactive
resize could measure against one monitor and place against another.

**Still unverified:** genuinely multi-monitor behaviour. Single-display machine.

### Decision A3.4 — the native test now shows the popup, because that is the real sequence

**Decision:** `test_compact_and_expanded_sizes_follow_content_without_clipping`
calls `show_result(...)` first, uses a twelve-sense entry with wrapping text, and
asserts a full compact → expanded → compact → expanded round trip.

**Why:** the 640×480 reading is a *second*, distinct defect from the shrink, and
it only happens to a top-level widget that has **never been shown**. Isolated
single-process trials: `show()` fixes it; `winId()`, `adjustSize()`, a repeated
`setFixedSize()`, presetting `WA_Resized`, and removing `deleteLater()` all do
not. (An earlier batch of trials sharing one `QApplication` gave misleading
passes — deferred deletions from previous trials contaminated later ones.)

No production path is affected: `PopupController.show()` calls `prepare_result`,
then `position_for`, then `show_result` with no event loop in between, so the
measured size always survives to the show. Section 5 of the plan already names
the missing `show()` as a test deficiency. The assertion still observes the real
widget after a real Cocoa event cycle, so it is not weakened.

**Rejected alternative:** forcing the platform window early with `winId()` in
`__init__`. It does not fix the reset, and it would create an NSWindow for every
constructed view whether or not it is ever shown.

**Still unverified:** Windows and Linux native runs of this test. Only macOS was
exercised locally; CI covers the other two.

### A3 validation and state

| Check | Result |
|---|---|
| `ruff` / `mypy` | All checks passed / Success, 244 files |
| `pytest --suite portable` | 1580 passed, 1 skipped |
| `pytest --suite native tests/native/shared/test_qt_popup_window.py` | 11 passed, five consecutive runs |
| Full `--suite native` | 31 passed, 11 skipped, **24 errors** |

The 24 native errors are **environment, not Bundle A**: every one is
`test_update_posix_native.py` failing to compile its C helper because `cc` is an
Xcode shim blocked by the same unaccepted licence that blocks git. They were not
run at baseline for the same reason.

**State:** A3 complete. **Commit pending.** Files for commit 3
(`fix: stabilize popup content measurement`):

```
packages/hanly-app/src/hanly_app/qt_popup.py
tests/native/shared/test_qt_popup_window.py
```

**Resume point:** A4 — sticky popup dismissal. Tier 1 only: next result, chord
re-press, footer close control.

---

## A4 — Sticky popup dismissal

### Decision A4.1 — stickiness follows the hover activation, it is not unconditional

**Decision:** `HoverLookupRuntime(..., sticky=True)` is the default, and
composition sets it from the config: sticky for `PUSH_TO_HOVER`, not sticky for
`ALWAYS_ACTIVE` (`_hover_is_sticky()` in `manual_lookup.py`).

**Why:** A4's whole argument is that the lookup was *deliberate* — "lookup
already follows a deliberately held chord". That is true of Push to Hover and
false of Always Active, where hover is continuous and an answer that never left
would sit on top of the next thing being read. Applying stickiness to both modes
would fix one mode by breaking the other.

**What it does:** under Push to Hover, leaving the word releases the protection
so the next word can be looked up, but the card stays on screen. Under Always
Active the previous behaviour is unchanged.

**Observations:** this also keeps the transfer-corridor machinery honest. It is
still used to gate new captures while the cursor crosses to the popup, and it
still performs dismissal under Always Active, so none of it becomes dead code
kept alive only by tests.

**Still unverified:** whether Always Active users would also prefer sticky. Not
changed without evidence.

### Decision A4.2 — Tier 1 only; no global hooks, no new permissions

**Decision:** the three dismissal routes are the next current result (already the
behaviour of `retain`), a re-press of the hover chord, and a **Close** control in
the popup footer. Escape and outside-click are not implemented.

**Why:** the popup sets `WindowDoesNotAcceptFocus` and `WA_ShowWithoutActivating`
and gives its controls `NoFocus`, because the source application must keep
keyboard focus. Such a window receives neither `keyPressEvent` nor any mouse
event outside its own frame, so Escape and outside-click would need a global
hotkey and a global mouse monitor. The plan makes those optional later tiers and
forbids adding hooks or permissions without evidence.

**What it does:** `QtPopupView` gains a `Close` button wired to
`set_dismiss_handler`; `PopupController._handle_dismiss()` clears the card and
calls the handler composition registered, which is `HoverLookupRuntime.clear_target`
so a dismissed card cannot be resurrected by geometry for a stale target. A chord
press calls `HoverLookupRuntime.dismiss()` before accepting new work.

**Observations:** the view falls back to hiding itself when no handler is
composed, which keeps a standalone view and the benchmark harness usable.

**Still unverified:** whether Tier 1 alone feels sufficient in live use. It is a
product question that only real hovering answers; the tiering means Escape can be
added later without re-planning.

### Decision A4.3 — the old lifetime tests express the new policy, they were not patched

**Decision:** five tests that asserted dismissal-on-exit now assert the sticky
default, with the old assertions preserved against a `sticky=False` harness.

**Why:** Section 5 names these tests as encoding the old mouse-exit lifetime.
Because stickiness is per activation mode (A4.1), both behaviours are real
product behaviour and both deserve coverage — this is not keeping a dead path
alive for a test's sake.

**Observations:** renamed/split —
`test_leaving_the_word_keeps_a_push_to_hover_answer_on_screen` and
`test_leaving_the_word_dismisses_under_continuous_hover`;
`test_a_retained_word_with_no_popup_is_released_but_not_dismissed`;
`test_turning_back_while_crossing_dismisses_under_continuous_hover`;
`test_movement_with_nothing_retained_clears_under_continuous_hover` plus
`..._is_silent_under_push_to_hover`; new
`test_an_explicit_dismissal_takes_the_answer_off_screen` and
`test_an_in_card_dismissal_clears_the_popup_and_notifies_composition`.

**Correction to the plan text:** the plan's A4 says the resize-transfer grace
"was proposed work, not existing code". That is right for a *resize*-transfer
grace, but a *hover*-transfer corridor does exist (`_arm_transfer`,
`_transfer_ms`, `in_transfer_corridor`) and handles the word-to-popup crossing.
It is retained and still used.

### A4 validation and state

| Check | Result |
|---|---|
| `ruff` / `mypy` | All checks passed / Success, 244 files |
| `pytest --suite portable` | 1585 passed, 1 skipped |
| `--suite native` popup window | 11 passed |

**State:** A4 complete. **Commit pending.** Files for commit 4
(`feat: keep lookup popups open until explicit dismissal`):

```
packages/hanly-app/src/hanly_app/hover_lookup.py
packages/hanly-app/src/hanly_app/manual_lookup.py
packages/hanly-app/src/hanly_app/popup.py
packages/hanly-app/src/hanly_app/qt_popup.py
tests/test_hover_target.py
tests/test_hover_lookup.py
tests/test_popup.py
```

**Resume point:** A5 — clipping-only OCR recovery, in `capture.py` /
`composition.py`. The edge-touch tolerance must be derived from Section 2B and
recorded.

---

## A6 — Restore a minimized macOS Control Center

### Decision A6.1 — restore before show, guarded by the backend's own flag

**Decision:** `ControlCenterHost.show()` calls `_restore_if_minimized(window)`
before `show` and process activation. The helper skips the call only when the
backend explicitly reports `minimized is False`.

**Why:** Section 2E established the missing operation: the Qt backend
implements un-minimizing as its own `restore`, and `show` alone leaves the
window in the Dock. Order matters — showing and then restoring would flash the
old geometry.

Reading the flag defensively (restore unless it says `False`) means a backend
that does not publish `minimized` still gets restored; restoring an already-up
window is harmless, while skipping it reproduces the reported defect.

**What it does:** the same child, page, bridge and capture state are preserved,
because nothing is destroyed or recreated — only the window state changes.

**Still unverified:** **real macOS behaviour.** The tests drive a fake pywebview
window. Whether clicking the Dock tile reaches this focus path at all is
explicitly *not* established, and the plan's A6 leaves the Dock route in scope.
This must be exercised by hand before A6 is called done natively.

---

## A7 — Derive the initial Control Center size

### Decision A7.1 — width preserved, height derived from the work area

**Decision:** `initial_window_size(available_width, available_height)` clamps
width into `[760, 1080]` and derives height as 78% of the work area, clamped to
`[560, 760]` and never exceeding the work area itself. `width`/`height` become
`None`-by-default on both `ControlCenterHost` and `ControlCenterOptions`,
meaning "derive"; an explicit value is still honoured.

**Why:** measured on this machine, the work area is **1408×787**, so the fixed
1080×760 was asking for **97% of the available height** — that is the reported
"unnecessarily tall" window, quantified. Width is preserved because the plan
says to keep it unless geometry forces a clamp and the composition was designed
around it.

**What it does:**

| Work area | Requested |
|---|---|
| 1408×787 (this MacBook) | 1080×614 — 19% shorter, 78% of the area |
| 2560×1380 | 1080×760 — unchanged at the cap |
| 1440×700 | 1080×560 — the layout minimum |
| 900×500 | 860×500 — fits, native controls stay reachable |

**Observations:** an explicit size still wins, so the packaging harness and
tests pin a size without depending on the machine they run on.

**Still unverified:** how the denser window *looks* with real content; that is a
visual judgment needing a real launch. The layout tests cover reachability at
the minimum size.

### A6/A7 validation

| Check | Result |
|---|---|
| `ruff` / `mypy` | All checks passed / Success, 244 files |
| `pytest --suite portable` | 1592 passed, 1 skipped |

**State:** A6 and A7 complete apart from the native macOS pass noted above.
**Commits pending.** Files for commit 6 (`fix: restore the minimized Control Center`):
`control_center_host.py`, `tests/test_control_center_host.py`. For commit 7
(`fix: size the Control Center to the available screen`):
`control_center_host.py`, `control_center_process.py`,
`tests/test_control_center_host.py`.

**Resume point:** A5 — clipping-only OCR recovery. Nothing else is outstanding.

---

## A5 — Clipping-only OCR recovery  **(core complete, wiring NOT done)**

### Decision A5.1 — the edge tolerance is 6 ROI pixels, measured

**Decision:** `EDGE_TOLERANCE_PIXELS = 6` in the new
`hanly_app/capture_recovery.py`.

**Why:** the plan requires the tolerance be derived from Section 2B and
recorded, and warns that an exact-equality test would almost never fire.
Reproduced 2B's recipe against real EasyOCR — five words, 20 px and 32 px,
cropped at first/middle/last syllable, 30 cases — and measured the gap between
the detected region and the nearer ROI edge:

```
0 px   ×12
2-5 px × 6
19 px and above × 12     (19, 20, 22, 22, 25, 25, 25, 36, 38, 38, 38, 53, 54, 54)
```

Nothing lands between 5 and 19. Six sits in that empty band rather than on
either cluster.

**Observation that validates the whole package:** the production ROI default is
`(200, 100)` — exactly the synthetic crop size — so the clipping Section 2B
found is the clipping real users get, not an artefact of the probe.

**Observation that limits it:** at these sizes EasyOCR produced *no* perfectly
read case, so "clipped" could not be separated from "misrecognized" by text
completeness. Edge contact is therefore a cheap observable trigger meaning "the
text may continue past the crop", not a claim that it does.

### Decision A5.2 — recovery is a pure decision plus one bounded widening

**Decision:** `capture_recovery.py` exposes `clipped_edges()`,
`widened_region()` and `recovery_target()`: which ROI edges the answer's own
region reached, the monitor-constrained wider rectangle, and the original cursor
re-expressed inside it. `RECOVERY_MARGIN_PIXELS = 100` per side.

**Why:** the engine only ever receives images, so "did this capture cut its own
subject" is screen geometry and belongs in `hanly-app`. Keeping the decision
pure makes it testable without a screen, a worker, or EasyOCR.

Only the region that produced the answer is considered — another line elsewhere
in the crop touching an edge says nothing about the word under the cursor. A
result with no `selected_ocr` is never clipped, which is what keeps fully
visible misrecognition (`예뻤어요` read as `예벗어요`) from triggering a retry.

**Still unverified:** nothing in the core; eight focused tests cover edge
contact, the tolerance band, monitor clamping, the no-growth case, and cursor
preservation across the widening.

### A5 — what is NOT done, and why

**The async wiring is not implemented.** Detecting clipping is the pure half;
acting on it means recapturing and resubmitting *from the result-dispatch path*
— wrapping the controller's `on_result` so a clipped answer triggers one wider
capture, resubmitted through the same bounded controller, guarded so it cannot
recurse, with cache and trace identity distinguishing the second pass.

That code sits on the exact path the architecture names as its correctness
gate: bounded/latest-wins submission and the final request-currency check. It is
the highest-concurrency-risk change in Bundle A, and it is the wrong thing to
write quickly at the end of a long implementation run — a subtle stale-result
regression there would be both severe and hard to see.

**Nothing is blocked.** The seams needed all exist and were checked:
`CaptureService.capture_at_cursor(cursor, region=...)` accepts a wider
rectangle; `LookupController.submit()` makes the new request current, which
gives latest-wins for free; `CaptureOrigins` already carries each request's
capture region; and `on_result` in `manual_lookup._create_controller` is a
clean interception point with a late-bound holder pattern already used in that
file. It is scope deliberately left for a short follow-up, not an obstacle.

**Resume point for A5:** wrap `on_result` in `manual_lookup.py`. On a result
whose `hover_request_id` has not yet been recovered, call
`clipped_edges(result, origin.width)`; if clipped, `widened_region(...)`,
recapture with `region=`, `recovery_target(...)`, resubmit via
`controller.submit(...)`, and mark that hover request as recovered so the
second answer is always presented. Emit the recovery count and reason through
the existing trace seam.

---

## A8 and convergence

### Decision A8.1 — fixtures landed with the package each one serves

**Decision:** no separate fixture package. The perfect-text morphology cases
live in `tests/test_kiwi_provider.py` behind a module-scoped real-Kiwi fixture;
the many-sense popup round trip lives in the native popup test; the shared XML
for the gloss case went into `tests/hanly_fixtures/krdict.py`, which already
carries literal XML behind a file-level `noqa: E501` with a stated reason.

**Why:** the plan says A8 "grows alongside the other packages", and a commit
stays coherent and revertible when its regression travels with it. Putting the
XML in the shared fixtures module follows the existing convention rather than
adding a second noqa to a test file.

**Observations:** the real-Kiwi parametrized cases took 15.8 s with a provider
per case and 2.0 s with one shared across the module.

### Final convergence

| Gate | Result |
|---|---|
| `pytest --suite portable` | 1600 passed, 1 skipped (baseline 1557) |
| `pytest --suite native` | 32 passed, 11 skipped, 24 errors (environment) |
| `ruff check packages packaging tests tools benchmarks` | All checks passed |
| `mypy packages packaging tests tools benchmarks` | Success, 246 source files |

The 24 native errors are `test_update_posix_native.py` failing to compile its C
helper: `cc` is an Xcode shim blocked by the unaccepted Xcode licence, the same
cause as git being unavailable. They did not run at baseline either.

`docs/CODE-MAP.md` was **not** updated. Its §4 sentence "a real exit keeps the
answer for a short grace so the gap to the popup can be crossed" now describes
only Always Active hover, and its §5 provider table still shows
`MorphologyProvider → TokenAnalysis`. Both are structural statements that A2 and
A4 changed, so the map needs a small edit — deliberately left for after the
review, since the reviewer may change these decisions.

### Bundle state

| Package | State |
|---|---|
| A1 short translations | complete |
| A2 lexical-unit selection | complete |
| A3 popup measurement | complete |
| A4 sticky dismissal | complete (Tier 1) |
| A5 clipping recovery | **core only** — wiring not implemented |
| A6 Control Center restore | complete, native pass outstanding |
| A7 initial window size | complete, visual check outstanding |
| A8 fixtures and artifacts | complete |

**Commits: none.** git is unavailable (Xcode licence). Eight commit groupings
with their file sets are recorded above, in order, ready to replay.

**Artifacts written:** this checkpoint,
`docs/execution/review-handoffs/lookup-and-popup-correction-2026-09-19.md`, and
`docs/execution/lookup-and-popup-correction-operator-notes-2026-09-19.md`.

**Stop.** Phase A ends here. Phase B deep review is not authorized and was not
begun.

---

## Post-handoff findings from the first real launch (2026-09-19, same session)

The human ran the desktop from source and reported three things. All were
investigated before changing anything.

### Finding 1 — `떨어뜨렸어요` reports "Not in the dictionary": OCR, not morphology

**Evidence:** the popup's own title in the supplied screenshot reads
**`떨어뜨렇어요`**, not `떨어뜨렸어요`. OCR misread the batchim `ㅆ` in `렸` as
`ㅎ`. `떨어뜨렇어요` is not a Korean word, so Kiwi cannot reduce it and KRDICT has
no entry; the honest non-success was the correct outcome. Hovering the
dictionary form `떨어뜨리다` in the same document answered correctly with both
senses, which isolates the failure to recognition.

**Three recovery attempts, all measured, all negative** (20 px white-on-black,
five test words, real EasyOCR):

| Variant | `떨어뜨렸어요` read as | confidence |
|---|---|---|
| as captured | 떨어뜨**덧**어요 | 0.25 |
| 2× LANCZOS upscale | 떨어뜨**렇**어요 | 0.21 |
| inverted to dark-on-light | 떨어뜨**로**어요 | 0.21 |

Every word failed in every variant, at 0.19–0.52 confidence. The consistent
pattern is the **double-consonant batchim** (`ㅆ` in 렸/했/뻤).

**Capture resolution was investigated and ruled out as a lever.** The display is
2880×1760 physical at dpr 2.0, but `mss` reports the monitor as 1408×881 and
grabs 1:1, so the ROI is half the rendered resolution. Upscaling afterwards does
not recover the lost detail, as the table shows. Requesting a true physical-pixel
grab is untested and is the one remaining idea.

**Conclusion:** this is the EasyOCR accuracy ceiling the plan already defers to
the HanlyOCR research track, not a Bundle A defect. A translation API would not
help: it would receive the same corrupted string.

### Finding 2 — obsolete children painted under rebuilt content

**Decision:** `_clear()` in `qt_popup.py` now calls `widget.hide()` before
`widget.deleteLater()`.

**Why:** found by rendering the restyled popup and *looking at it* rather than
trusting the tests. Sense 3 showed ghost text behind it and the footer read
"ExpandCollapse" / "CloseClose". Taking a widget out of a layout does not stop
it painting, and deletion is deferred, so the old children kept drawing at their
previous geometry. A3's `_reveal()` exposed it; the plan's A3 step 2 asked for
"detach or hide obsolete children **and** make new children measurable" and only
the second half had been implemented.

**Observation:** no test caught this. Every popup assertion is about geometry or
label text, and a ghost widget changes neither. A pixel or overlap assertion
would be needed, which is noted as a review target rather than added here.

### Finding 3 — footer controls and scrollbar restyled

**Decision:** footer buttons became one family — a filled accent pill for the
primary action, a quiet outline for the secondary, both with hover and pressed
states. The scrollbar became an overlay: no track, inset 4 px, a handle that
firms up under the pointer.

**Why:** the reported screenshots show two hard-outlined rectangles and a bare
track. The saturated accent `#F08FA6` now appears only on the primary button's
*pressed* state, which is where a brand colour earns its contrast; the resting
state uses the softer `accent_ink` on `accent_wash`.

**Observation:** removing the old accent outline briefly broke
`test_light_and_dark_preferences_apply_the_approved_palettes`, which asserts the
approved accent appears in the stylesheet. That was a correct signal — the
accent had become unused — so the fix put it back in the pressed state rather
than weakening the assertion.

**Still unverified:** light theme was not rendered; only dark was inspected.

### Standing correction to the record

The human has asked that the minimize/restore defect be carried into Phase B.
Recorded as instructed, with one note that remains true: the Dock-reopen route
is unwritten A6 scope, not a review finding, so a review cannot produce it.

### Gates after these changes

| Gate | Result |
|---|---|
| `pytest --suite portable` | 1600 passed, 1 skipped |
| `pytest --suite native` | 32 passed, 11 skipped, 24 environment errors |
| `ruff` / `mypy` | All checks passed / Success, 246 files |

---

## Vision OCR spike (human-directed, outside Bundle A)

### Measurement that motivated it

EasyOCR's `korean_g2` fails systematically on the **ㅆ batchim**, which is the
marker of the past tense Hanly exists to explain:

```
렸 → 로/렇     했 → 있/햇     뻤 → 쁘     겠 → 켓     았 → 앗
```

Ruled out as causes, each measured rather than assumed: capture resolution
(0/7 even at true Retina 40 px), 2× upscaling (0/7), and dark-mode inversion
(0/7). A model defect cannot be fixed by cleaner pixels.

| Recognizer | 20 px | 40 px | latency |
|---|---|---|---|
| EasyOCR | 0/7 | 0/7 | 72.3 ms |
| Apple Vision | 5/7 | **7/7** | **25.5 ms** |

Through the **full production pipeline** (Vision → Kiwi → KRDICT): **7/8**
successful against EasyOCR's 0/8 on the same words.

### Decision V.1 — `VisionProvider` sits in `hanly`, beside `easyocr_provider`

**Decision:** `packages/hanly/src/hanly/vision_provider.py`, implementing the
existing `OCRProvider` seam. The framework is loaded lazily through `pyobjc`'s
bridge and only on Darwin.

**Why:** both are adapters for the same engine interface, and splitting them
across packages would make the seam asymmetric. Lazy loading keeps `hanly`
importable on every platform, exactly as the EasyOCR adapter already does. No
new dependency: `pyobjc-core` and `Foundation` are already installed, and
`Vision.framework` is loaded by path rather than through a wrapper package.

**Open question for review:** `hanly-app` holds the `*_darwin.py` convention for
platform code. A macOS-only adapter in the engine is defensible but is the kind
of placement a reviewer should confirm.

### Decision V.2 — `language_correction` defaults to off

**Decision:** `VisionConfig.language_correction = False`.

**Why:** correction can turn one real word into a *different* real word, which
matters far more for a dictionary than for prose. Measured both ways on ten
words: **10/10 either way**, so correction buys nothing here and the safer
default costs nothing.

### Decision V.3 — `auto` is the default, and it is a deliberate upgrade

**Decision:** `OCRBackend` (`auto` / `vision` / `easyocr`) in `config.py`.
`auto` prefers Vision where available and falls back to EasyOCR. A runtime or
profile written before the setting existed reads as `auto`.

**Why:** an existing macOS user silently gets the recognizer that can actually
read conjugation endings. Pinning is available for comparison and debugging.

**Observation:** this broke three `test_easyocr_runtime.py` cases, which is the
correct signal — they test EasyOCR composition specifically, so they now pin
`"ocr_backend": "easyocr"` rather than relying on a default that no longer
favours them.

**This reverses an approved decision.** `CLAUDE.md` states EasyOCR is the only
backend and says not to reintroduce a backend-selection seam. That instruction
came from the PaddleOCR removal, and the human has now directed the opposite in
this session. It needs recording in `CLAUDE.md` or an ADR so a later session
does not read the old instruction and undo it. **Not yet done.**

### What is wired

- `HanlyRuntime.ocr_backend`, read from `runtime.json` via `_ocr_backend()`.
- `AppConfig.ocr_backend`, with `to_dict`/`migrate` round-trip and rejection of
  unknown values; the Control Center bridge accepts it as a settable field.
- A **Text recognizer** dropdown in the Control Center settings, with help text.
- Verified against the human's real installed runtime: `auto` →
  `VisionProvider`.

### Still unverified

- Only rendered text was tested, never a real screen capture.
- `예뻤어요` returned `EMPTY` in the full-pipeline run while succeeding in
  isolation — an intermittent detection miss worth chasing before this is
  called done.
- Changing the recognizer in the Control Center persists, but the provider is
  built once per lookup engine, so it applies when that engine next loads. No
  explicit engine restart is triggered on change.
- Windows has no equivalent adapter; `auto` correctly falls back to EasyOCR.

### Gates

`pytest --suite portable` 1606 passed, 2 skipped · `--suite native` 32 passed,
11 skipped, 24 environment errors · `ruff` clean · `mypy` 248 files clean.

### Decision V.4 — a settable field must survive `candidate()`, and now a test says so

**Reported:** the human could not change the recognizer in the Control Center.

**Cause:** `ConfigManager.candidate()` builds the new `AppConfig` field by
field, and `ocr_backend` was missing from that constructor. `SETTABLE_FIELDS`
accepted the change without error, then the value was silently replaced by the
default. The interface offered a control that did nothing, and nothing anywhere
reported a problem.

**Fix:** pass `ocr_backend` through `candidate()`.

**Why it matters beyond this field:** the two lists — what is *declared*
settable and what is *actually constructed* — can drift silently for any future
preference. So the regression is generic rather than about this one field:
`test_a_settable_field_actually_survives_being_set` is parametrized over
`SETTABLE_FIELDS` and asserts each one round-trips through update *and* reload,
with `test_every_settable_field_has_a_sample_so_this_test_cannot_rot` forcing a
sample to exist for each.

**Verified by reverting:** with the fix removed the new test fails
(1 failed, 14 passed); with it restored, 46 passed. The test catches the bug it
was written for rather than merely passing beside it.

**Observation:** this is the second silent-acceptance defect in this session —
the first was `SETTABLE_FIELDS` promising more than `candidate()` delivered, and
earlier the Vision `minimized` guard falling through because the attribute does
not exist on the real pywebview window. Both were invisible to tests that
asserted the happy path.

**Gates:** `pytest --suite portable` 1622 passed, 2 skipped · `ruff` clean ·
`mypy` 248 files clean.
