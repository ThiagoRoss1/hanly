# Vision hover and macOS restore stabilization Review Handoff

## Bundle

- Member issues: plan-local work packages S0–S5 from
  `docs/execution/plans/vision-hover-and-macos-restore-stabilization-2026-09-20.md`.
  No Linear issues created or mutated.
- Implementation ecosystem: Claude Opus 5, macOS 26.6.2, repository `.venv`.
- Date: 2026-09-20
- Branch: `visual/interface-update`. **Nothing is committed** — see *Blockers*.

## Implemented

- **S0** A deterministic offset fixture (`tests/hanly_fixtures/offsets.py`) that
  crops one unchanged Korean line at many origins, and the measurements it
  produced. The existing trace already correlates by request id.
- **S1** The Control Center restores unconditionally instead of branching on a
  flag pywebview never updates, and a macOS reactivation routes to the existing
  open path (`app_reopen_darwin.py`).
- **S2** Hover anchors its capture region for the episode
  (`capture_anchor.py`), so a pointer that still owns a word keeps seeing one
  picture — and hits the existing target-independent OCR cache.
- **S3** Vision's real quadrilateral survives the provider seam.
- **S4** One bounded recapture when the answer's own region touches the crop
  edge (`ClippingRecovery`), submitted through the same controller.
- **S5** `CLAUDE.md` and `docs/CODE-MAP.md` reconciled with the two-backend
  runtime; operator note written.

## Main expected behavior

Hovering a Korean word keeps one answer while the pointer stays on it, instead
of alternating between the right lemma, unrelated words and "Too unclear". A
minimized Control Center comes back — from the tray and, now, from the Dock.

## Architecture / seams touched

- `CaptureSource.capture_at_cursor` gained an optional `anchor`; six test
  doubles were updated to model it. The runtime still falls back for a narrow
  seam.
- `LookupSettings` carries `ocr_backend`, resolved to a concrete value in the
  shell by `HanlyRuntime.resolved_ocr_backend()`.
- No Vision, Objective-C or pywebview object crosses an engine contract.
- Bounded/latest-wins and the final currency check are unchanged: the recovery
  submits through the controller rather than around it.

## Implementation-side validation already run

- `pytest` (full) → **1686 passed, 13 skipped, 24 errors**
- `pytest --suite portable` → 1651 passed, 2 skipped
- `pytest --suite native` → 32 passed, 11 skipped, 24 errors
- `ruff check packages packaging tests tools benchmarks` → All checks passed
- `mypy packages packaging tests tools benchmarks` → Success, 253 source files

The 24 errors are `test_update_posix_native.py` failing to compile its C helper
because an unaccepted Xcode 27.0 licence gates `cc`. Identical at baseline.

Measured evidence, all reproducible from the fixture:

| Measurement | Result |
|---|---|
| Vision surface stability over 13 crop origins | 1 distinct surface for 4 of 5 words |
| Pointer ±12 px on a 4-line list, unanchored | found → none → found → none |
| Same path, anchored | one constant surface after the first capture |
| Rotated text quad | top corners differ by 24 px; previously identical |
| Clipping recovery | exactly one recapture on edge contact, none otherwise |

## Known limitations / intentionally unvalidated areas

- **No real Dock cycle.** The three-cycle native acceptance in the plan's
  Section 4 was not performed; it needs a human to click the Dock icon.
- **No live hover.** Every OCR measurement is rendered text, not a screen
  capture. The stability fixture reproduces the defect's *mechanism*, not the
  user's exact screen.
- **`친구들이` is still unexplained.** Intact text resolves to `친구`, the offset
  sweep is stable, and no fixture reproduces the recorded failure.
- **S3's optional substring range geometry was not implemented** — deliberately;
  see the checkpoint.
- **`DEFAULT_SAFE_FRACTION = 0.5` was chosen, not tuned.** It makes the measured
  case stable; no sweep established it as best.
- Windows and Linux unexercised.

## Blockers

**git is unavailable.** Xcode auto-updated 26.5 → 27.0 at 17:19 on 2026-09-19
and its licence is unaccepted, so every Apple tool stub refuses. No commits were
made and none were simulated. Intended boundaries and file lists are in the
checkpoint. `sudo xcodebuild -license accept` clears it.

## Suggested review targets

- `ClippingRecovery.intercept` — the double currency check, and whether
  returning `True` can ever suppress a result that no recovery replaces.
- `AnchorPolicy` — whether releasing only on chord release and dismissal leaves
  an anchor alive across a genuine move to a distant word.
- `capture_at_cursor(anchor=...)` — the interaction between an anchored region
  and `CaptureMode.REGION` clip bounds.
- `_quad_from_corners` — the single vertical flip, against a provider revision
  that reports corners differently.
- The R7 pattern from the Bundle A handoff, which recurred twice more here
  (the inert `minimized` flag; the recognizer that never crossed the spawn
  boundary). Worth a dedicated sweep.

The reviewer and ecosystem are human-selected. This handoff prepares that
review; it does not perform one.
