# Live checkpoint — Vision hover and macOS restore stabilization

**Plan:** `docs/execution/plans/vision-hover-and-macos-restore-stabilization-2026-09-20.md`
**Phase:** A. Ends at one Review Handoff. Phase B is not authorized.
**Branch:** `visual/interface-update`

## Environment

**git remains unavailable.** Xcode auto-updated 26.5 → 27.0 at 17:19 on
2026-09-19; the licence for 27.0 has not been accepted, so every Apple tool stub
(`git`, `cc`, `clang`) refuses. Per the execution prompt: no sudo, no simulated
commits, intended commit boundaries recorded here instead.

Baseline before this bundle: `--suite portable` 1628 passed, 2 skipped; `ruff`
clean; `mypy` 248 files clean. `--suite native` 32 passed, 11 skipped, 24 errors
— all 24 are `test_update_posix_native.py` failing to compile its C helper
because `cc` is licence-gated. Not product failures.

---

## S1 — Control Center restore

### Decision S1.1 — `window.minimized` is not state; stop reading it

**Decision:** `_restore_if_minimized()` is replaced by an unconditional,
idempotent `restore()` before `show()` and activation.

**Why:** verified directly against the installed pywebview 6.2.1:

```
Window.__init__(..., minimized: bool = False)   # a construction option
self.minimized = minimized                      # assigned once, never again
events.minimized.set()                          # Qt backend fires the event...
                                                # ...and never updates the attribute
```

So a genuinely minimized window still reports `minimized is False`, my earlier
guard returned before calling `restore()`, and the window stayed in the Dock.
This is exactly the defect the human kept reporting after the "fix".

The previous test passed only because its fake mutated `window.minimized`, which
pywebview never does. That is the fifth instance in this project of a control
reporting success while the effect never reached the real code (see R7/R10 in
the Bundle A handoff).

**Still unverified:** whether unconditional `restore()` is harmful on a window
that is already up. The plan prefers idempotent restore over duplicating backend
state, and says to add a tracker only if native evidence proves harm.

### Decision S1.2 — the fake now models pywebview, and the old test is proven to fail

**Decision:** `_Window` in `tests/test_control_center_host.py` keeps `minimized`
permanently inert and adds `native_minimized`, which only `restore()` clears.
Tests assert the user-visible outcome instead of the flag.

**Why:** the previous fake flipped `minimized` on minimize, which pywebview never
does. That let a guard branch on state that does not exist, and is exactly how
the defect survived its own test.

**Verified by reverting:** reinstating the shipped guard fails 3 of the 15 host
tests; with the fix, 15 pass. The regression catches the real bug rather than
passing beside it.

### Decision S1.3 — the Dock route reuses the one open path, gated on liveness

**Decision:** new `hanly_app/app_reopen_darwin.py`. On macOS it connects
`QApplication.applicationStateChanged` and calls
`DesktopApplication.open_control_center()` when the application becomes active,
debounced at 0.5 s, and only when a Control Center child is already live.

**Why:** the child is an accessory process with no Dock tile, so clicking Hanly
in the Dock activates the *shell*, which previously did nothing while the child
sat minimized. Routing to the existing action creates no second entry point,
child, window or Dock identity, as the plan requires.

The liveness gate is what stops an ordinary Command-Tab from resurrecting a
window the user deliberately closed. Both liveness and the activation signal are
**probed** rather than demanded of the protocols: a substituted Control Center
or Qt double that cannot report them simply has no Dock route, which costs a
tray click instead of breaking startup. Three `tests/test_application.py` cases
failed on the first attempt because the Qt double has no
`applicationStateChanged`, which is what prompted the probe.

**Still unverified — and this is the important gap:**
**no real Dock cycle has been performed.** Clicking the Dock icon requires
human interaction that this session cannot perform. What is verified: the filter
installs against a real `QApplication`, the debounce and liveness gate behave,
and `restore()` now precedes `show()` unconditionally. What is not: that macOS
actually delivers `ApplicationActive` on a Dock click for an accessory-child
configuration, and that the window returns with page state intact across three
cycles. That is the Section 4 acceptance row and it needs the human.

### S1 state

Gates after S1: `--suite portable` 1630 passed, 2 skipped; `ruff` clean; `mypy`
249 files clean.

Intended commit 2 — `fix: restore the Control Center on macOS`:

```
packages/hanly-app/src/hanly_app/control_center_host.py
packages/hanly-app/src/hanly_app/app_reopen_darwin.py
packages/hanly-app/src/hanly_app/application.py
tests/test_control_center_host.py
tests/test_control_center_process.py
```

**Next action:** S0 — correlated trace, in `runtime_trace.py` and the hover path.

---

## S0 — Offset fixture and evidence

### Decision S0.1 — the fixture measures stability, not accuracy

**Decision:** `tests/hanly_fixtures/offsets.py` renders one unchanged Korean
line and crops it at many origins across the production 200×100 ROI. It asserts
nothing about the right lemma.

**Why:** a fixture that encoded the desired answer could not show churn, which
is the thing worth seeing. The plan requires it to expose churn, not fake a
result.

**Observation worth keeping:** Pillow resolves a bare font name through its own
search path, so a *wrong* literal path still rendered correctly and only
`Path.is_file()` revealed it. The Korean face is at
`/System/Library/Fonts/AppleSDGothicNeo.ttc`, not under `Supplemental/`. Every
ad-hoc measurement earlier in this project used the wrong path and worked
anyway. The fixture now resolves it explicitly.

### Finding S0.2 — the plan's churn hypothesis is wrong for Vision

**Measured:** one word, 13 crop origins, 8-pixel steps.

| Word | Distinct surfaces |
|---|---|
| 떨어뜨렸어요 | 1 |
| 사과했어요 | 1 |
| 친구들이 | 1 |
| 공부하려고 | 1 |
| 예뻤어요 | 2 — the correct reading, or *nothing at all* |

Vision is essentially offset-invariant on crisp text. Section 1.3's chain
("crossing a grid boundary shifts the crop and changes what Vision reads") is
**not** what produced the recording's unrelated lemmas. The one instability is
`예뻤어요` returning no observation, which is a detection miss, not a misread.

### Finding S0.3 — the real mechanism, reproduced

A 200×100 ROI on a real four-line list spans more than one line. Moving the
pointer ±12 px vertically while it stays visually on `예뻤어요`:

```
dy −12  (none)        dy  +4  (none)   ← the ROI now contains only line 3
dy  −8  예뻤어요        dy  +8  예뻤어요
dy  −4  예뻤어요        dy +12  (none)   ← no observations at all
   dy 0  예뻤어요  (3 observations, including a garbled "? 사과해어O")
```

Found → not found → found → nothing, for millimetres of movement. That is the
recording's popup flicker, reproduced without a screen. The cause is that a
cursor-centred crop changes *which lines it contains*, so the recognizer is
shown a different picture and the resolver sometimes finds no region under the
pointer at all.

A second, smaller effect: Vision reads the `→` in the source as `-`, `->` or
`-*` and joins it to the word with no space, so the whitespace-delimited
resolver returns `떨어뜨렸어요->`. Checked downstream — Kiwi's candidate
selection is unaffected (`떨어뜨렸어요-*`, `예뻤어요-*`, `사과했어요 -> 사` all
still yield the right lemma), so this is cosmetic in the surface, not a defect.

**Still unverified:** the `친구들이` live failure. Intact text resolves to
`친구` and the offset sweep shows one stable surface, so the recording's failure
is not reproduced by any fixture yet. Left open rather than explained away.

---

## S2 — Stable OCR context

### Decision S2.1 — anchor the region for the episode, do not re-centre on the cursor

**Decision:** new `hanly_app/capture_anchor.py` holds the region a hover episode
settled on; `CaptureService.capture_at_cursor` gained an `anchor` parameter that
captures that exact region instead of a cursor-centred one. `HoverLookupRuntime`
reuses the anchor while the pointer stays inside it and releases on chord
release or dismissal.

**Why:** measured above. A cursor-centred crop is the right way to *start*
looking at something and the wrong way to keep looking at it.

Identical pixels also hit the existing `_OCRCacheKey`, which is keyed on
dimensions, format and digest and is already target-independent — so a reused
region costs a capture rather than a recognition, with no new protocol.

**Measured result**, same pointer path as S0.3:

```
before   (none), 예뻤어요, 예뻤어요, 예뻤어요, (none), 예뻤어요, (none)
after    (none), 예뻤어요-*, 예뻤어요-*, 예뻤어요-*, 예뻤어요-*, 예뻤어요-*, 예뻤어요-*
```

One capture to settle, then a constant surface.

### Decision S2.2 — the safe area is a fraction of the region, not a pixel margin

**Decision:** `DEFAULT_SAFE_FRACTION = 0.5`, a centred share of each axis.

**Why:** found by measuring, not reasoning. The first implementation used a flat
48-pixel margin, which on the 200×100 production ROI leaves a **four-pixel-tall**
safe strip — so every small vertical movement re-anchored and the measured
flicker was completely unchanged. The ROI is not square and a fixed margin
cannot serve both axes. Half of each axis gives 100×50 of real safe area.

**Still unverified:** whether 0.5 is the best value on a real screen. It was
chosen to make the measured case stable, not tuned.

### Decision S2.3 — the capture seam widened, so the doubles had to model it

**Decision:** `CaptureSource.capture_at_cursor` declares the optional `anchor`;
six test doubles were updated to match, and the runtime still falls back to a
centred capture when a narrow seam rejects the keyword.

**Why:** a double that does not model the seam is how three of this project's
defects survived their tests. Updating them was the point, not an obstacle.

### S0/S2 state

`tests/test_hover_stability.py` holds the acceptance case and a **premise
guard**: one test asserts the anchored path keeps a single surface, the other
asserts the unanchored path still does not, so the first cannot quietly stop
proving anything.

Gates: `--suite portable` 1643 passed, 2 skipped; `ruff` clean; `mypy` 253 files.

Intended commits — 1 `chore: trace hover lookup decisions`
(`tests/hanly_fixtures/offsets.py`), 3 `fix: stabilize OCR context during hover`
(`capture.py`, `capture_anchor.py`, `hover_lookup.py`, `tests/test_capture_anchor.py`,
`tests/test_hover_stability.py`, six updated doubles).

**Next action:** S3 — preserve Vision's real quadrilateral in
`hanly/vision_provider.py::_normalize`, which currently uses `boundingBox()`.

---

## S3 — Vision geometry

### Decision S3.1 — use the observation's own corners, fall back to the box

**Decision:** `_quad_from_corners()` reads `topLeft`/`topRight`/`bottomRight`/
`bottomLeft`; `_quad_from_box()` keeps the axis-aligned path for a revision that
does not expose them. The vertical flip from Vision's bottom-left origin happens
once, in `_to_pixels()`.

**Why:** `WordResolver` documents that it hit-tests the real quadrilateral
because a derived rectangle "cannot decide a hit for tilted text". The adapter
was discarding geometry Vision already reports.

**Measured:** text rotated 8° now yields top-left y `97.0` against top-right
`72.7`; upright text stays level within 2 px. The old path reported both
corners identical for both cases.

**Not done — and deliberately:** optional per-substring range geometry. The plan
lists it as "when the installed Vision API can return a bounding region for the
selected recognized range". Adding it means a second coordinate convention
(range offsets against the recognized string) with its own inclusivity rules,
and the measured problem was context stability, not character mapping. Recorded
as remaining scope rather than done.

---

## S4 — Clipping recovery

### Decision S4.1 — intercept at presentation, not inside the hover loop

**Decision:** `ClippingRecovery.intercept()` runs in `present_result`. When the
answer's own OCR region touches the crop edge it captures one widened region and
submits it through the same controller, and the original result is **not**
presented.

**Why:** the controller makes the new request current, so bounded/latest-wins
and the final currency gate are inherited rather than re-implemented — which is
what made this the riskiest deferred item in Bundle A. Presenting the old result
as well would put a stale answer on screen.

Currency is checked twice: before capturing, and again after, because the
capture is the slow part and the pointer may have moved on during it.

**Budget:** a bounded ledger of request ids, so a request recovers at most once
and a recovery cannot authorize another. `spend()` marks an id ineligible.

**Still unverified:** no live clipped capture has been observed. The integration
tests drive a recording capture/submit pair and prove exactly one recapture on
edge contact, none for text clear of the edges, none for a stale request, none
for a recovery of a recovery, none when the monitor leaves no room, and a clean
fall-back when the capture itself fails.

---

## S5 — Documentation

### Decision S5.1 — `CLAUDE.md` now states why the one-backend rule changed

**Decision:** the OCR section records both the 2026-08-26 Paddle removal and the
2026-09-20 Vision addition, with the measurement that motivated it, and says
explicitly not to read the former as "one backend forever".

**Why:** the old text said "do not reintroduce a backend-selection seam". A
later session reading only that would correctly undo this work. The instruction
that changed needs the evidence attached to it, not just a new default.

`docs/CODE-MAP.md` gains the second adapter in its provider table, the resolution
rule, and the corrected `MorphologyProvider` return type from Bundle A.

**Not done:** architecture Markdown and the synchronized visuals under
`docs/architecture/`. Nothing here changed an approved architecture decision —
the provider seam is unchanged and was designed for exactly this — so per the
prompt those sources are left alone.

---

## Convergence and stop

| Gate | Result |
|---|---|
| `pytest` (full) | 1686 passed, 13 skipped, 24 errors |
| `pytest --suite portable` | 1651 passed, 2 skipped |
| `pytest --suite native` | 32 passed, 11 skipped, 24 errors |
| `ruff check packages packaging tests tools benchmarks` | All checks passed |
| `mypy packages packaging tests tools benchmarks` | Success, 253 source files |

The 24 errors are the licence-gated `cc`, identical at baseline.

### Native evidence actually obtained

- **Obtained:** Vision offset stability, the multi-line flicker and its removal,
  rotated-quad geometry, pywebview's inert `minimized` attribute read from the
  installed library, and Vision availability inside a spawned child.
- **Not obtained:** the three-cycle Dock reopen, and any live hover over real
  screen text. Both need a human at the machine. Neither is replaced by a mock.

### Commits — blocked, not skipped

git refuses because Xcode 27.0's licence is unaccepted. Intended boundaries:

1. `chore: trace hover lookup decisions` — `tests/hanly_fixtures/offsets.py`
2. `fix: restore the Control Center on macOS` — `control_center_host.py`,
   `app_reopen_darwin.py`, `application.py`, `tests/test_control_center_host.py`,
   `tests/test_control_center_process.py`
3. `fix: stabilize OCR context during hover` — `capture.py`, `capture_anchor.py`,
   `hover_lookup.py`, `tests/test_capture_anchor.py`,
   `tests/test_hover_stability.py`, and the six updated capture doubles
4. `fix: preserve Apple Vision text geometry` — `vision_provider.py`,
   `tests/test_vision_provider.py`
5. `fix: wire bounded clipping recovery` — `capture_recovery.py`,
   `manual_lookup.py`, `tests/test_capture_recovery.py`
6. `chore: finalize stabilization documentation` — `CLAUDE.md`,
   `docs/CODE-MAP.md`, this checkpoint, the operator note, the Review Handoff

### Stop

Phase A ends with the Review Handoff at
`docs/execution/review-handoffs/vision-hover-and-macos-restore-stabilization-2026-09-20.md`.
Phase B was not begun and Bundle B was not touched.

---

## ROLLED BACK at the human's direction (2026-09-20)

The human reported that hover got **worse** — "even past words aren't getting
recognized" — and directed a rollback and a restart.

### Why it got worse: S4 had an unbounded recovery chain

Reproduced before touching anything. `ClippingRecovery.intercept()` submits the
recapture through the controller, which mints a **new request id**. That id is
not in the spent ledger, so its result is eligible to recover again:

```
recaptures : 10
crop width : 200 → 400 → 500 → 600 → … → 1300 px
popup      : never shown until the crop ran out of monitor
```

Three violations at once: the plan's "exactly one additional attempt", the
architecture's ban on growing toward full-screen OCR, and — the symptom the
human saw — no popup at all, because every intermediate result was suppressed
in favour of a recovery.

`spend()` exists and works. **Nothing in production ever called it.** The test
`test_a_recovery_of_a_recovery_is_refused` called it by hand, so it proved the
brake existed rather than that it was connected. That is the sixth occurrence of
the pattern R7 named in the Bundle A handoff, and the second time I have shipped
it in code I wrote while reviewing for it.

### What was reverted

S2 (capture anchoring), S3 (Vision quadrilateral), S4 (clipping recovery), the
`anchor` parameter on the capture seam, the six widened test doubles, and the
modules and tests belonging to those packages.

**Retained:** S1 (Control Center restore and Dock reopen) — unrelated to the
regression and the defect the human has reported repeatedly — and S0's offset
fixture, which is test-only and produced the evidence. Both flagged to the human
for removal if they disagree.

**Verified after reverting:** `--suite portable` 1630 passed, and the four
acceptance words resolve again through the real pipeline
(`떨어뜨렸어요 → 떨어뜨리다`, `예뻤어요 → 예쁘다`, `사과했어요 → 사과하다`,
`공부했어요 → 공부하다`).

**git could not perform this.** The Xcode 27.0 licence still blocks it, so the
revert was done by reversing each edit by hand and confirming with the suite.
A `git diff` against the last commit would prove it exactly, and cannot be run.

### New design decision — silence is the default

**Decision:** `popup.should_present()` — a popup appears only for `SUCCESS` and
`ERROR`. `EMPTY`, `UNUSABLE` and `NOT_FOUND` are silent.

**Why:** the human's design. A popup means a Korean word was read and looked up.
An empty crop, a picture, English text, or an OCR misreading are all "nothing to
hover", and a card for each turns ordinary pointer movement into a stream of
noise to dismiss. `ERROR` stays visible so a genuine fault — an unreadable
database — is not hidden by the same rule.

**Consequence worth stating:** OCR misreadings are now **invisible** rather than
wrong-looking. `떨어뜨렇어요` produces no popup instead of a "Not in the
dictionary" card. This makes the product quieter and makes recognition failures
harder to notice; the trace remains the way to see them.

**Still unverified:** live behaviour. Two tests changed contract
(`test_a_word_the_dictionary_does_not_carry_shows_nothing`, and the NOT_FOUND
branch of the hover e2e), and a new one asserts `ERROR` still reaches the popup.

**Gates:** `--suite portable` 1631 passed, 2 skipped; `ruff` clean; `mypy` 250
source files clean.
