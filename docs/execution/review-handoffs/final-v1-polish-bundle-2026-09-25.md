# Final V1 Correction and Polish Bundle Review Handoff

## Bundle

- Member scope: the human's final V1 correction and polish list (hover
  false positives, hover stability and popup lifecycle, popup visuals, Control
  Center controls and palette, identity and icons, capture-area dialog,
  clipboard and updater cleanup, engine status) plus the mini-book acceptance
  fixture. No Linear issues created or mutated.
- Implementation ecosystem: Claude Opus 5.5, macOS 26.6.2 arm64,
  `.venv/bin/python` 3.13.11. No Windows host.
- Date: 2026-09-25. Branch `visual/interface-update`, starting at `5b7358c`.
  Earlier commits unchanged; nothing pushed, merged, rebased, amended or
  squashed. Phase B has not started.

| Commit | Boundary |
|---|---|
| `5869e9d` | `fix: keep Latin text out of Korean lookups` |
| `ea601ed` | `fix: hold one popup per word` |
| `3d03c80` | `style: refine the dictionary popup` |
| `ad14339` | `feat: design the Control Center choice lists` |
| `9aec5ef` | `feat: give Hanly its name and icon` |
| `2d97da9` | `fix: bring the capture-area prompt forward in Hanly's style` |
| `1278378` | `fix: clean up update handoff directories on Windows` |
| `3392488` | `fix: copy logs without the page clipboard` |
| `a30767a` | `fix: show engine loading even when it is brief` |
| `64131b9` | `test: count popups while the pointer stays on one word` |
| `5b016c4` | `feat: add the mini-book acceptance run` |
| this commit | `docs: record the final V1 polish bundle` |

## Causal evidence for the OCR and hover fixes

**Latin text became Hangul popups (`차`, `니`, `채`).** One variable changed
at a time, same pixels and targets, production pipeline:
- EasyOCR's `setLanguageList(['ko'])` builds `ignore_char` from every model
  character absent from `ko_char.txt`, which has no Latin letters. `korean_g2`
  itself contains A–Z/a–z, so Korean-only *forbade* Latin output: `CLI` read as
  `(니`, `Kiwi` as `*교담;`. The Hangul gate accepts Hangul plus punctuation,
  so these reached Kiwi and KRDICT.
- 51 Latin hovers: **10** Hangul popups with `("ko",)`, **0** with
  `("ko","en")`. Korean OCR text identical under both; warm latency equal
  within noise (Korean p50 46.7/49.6 vs 48.3/49.8 ms, n=40 ×2). Vision
  (`ko-KR`) produced 0 Hangul on the same 51 hovers, which is why macOS showed
  nothing on `Kiwi`.
- Fix: default `("ko","en")`; a `runtime.json` still holding the old generated
  `["ko"]` reads as the new default; a deliberate list is kept.
- Direct text: a control's exact `not_korean` reading now ends the hover
  instead of capturing for OCR to misread. Placeholders under the pointer
  (U+FFFC, U+FFFD, control/format/private/unassigned) refuse as `unsupported`,
  so a canvas or image still reaches OCR.

**W2 (`not_korean` over a canvas).** Standalone reads hit Chrome's canvas as an
Image element; live hovers at the same point said `not_korean`. That is what a
document-level text range yields if Chromium's embedded-object character U+FFFC
is under the pointer. Unconfirmed: Safari's web text answers no
`AXRangeForPosition` and Chrome is not installed here. The placeholder rule
keeps canvas on OCR either way.

**`이에요` sometimes `이`, later `이다`.** Five repeats of every cursor position
give one answer, and the mini book's 153 OCR and 153 direct repeats from
identical input were all identical. The lemma changes only with the selection:
`이에요` alone gives `이`; `…이에요` inside a run gives `이다`. So two different
acquisitions of one word — plausibly a UIA whole-run read against an OCR crop
that split it — not nondeterminism. Windows confirmation below.

**Popup rebuilt by a few pixels of movement (Windows).** A direct-text lookup
is a `TextSelection` with no ROI geometry, so `note_presented` cleared
retention (`no_word_region`) for every direct answer and each movement started
a new lookup. At `5869e9d` the new composition test presents **7** popups for 7
movements inside one word; after `ea601ed`, **1**, and exactly one more for the
next word. Retention and placement now use the reader's own word rectangle.

**Expand made the popup vanish.** A resize re-placed the popup from the cursor
and flipped it to the other side of the word when it grew. Placement now anchors
to the retained word, below it by preference, flips only at a screen edge, and a
resize keeps the chosen side. On macOS, a click on the popup activated the shell
and the reopen filter treated that as a Dock click; activations while the
pointer is on one of the shell's own windows no longer reopen the Control Center.

## Implemented (summary)

- Popup: one painted rounded card clips every child (the escaped corners in the
  reference); headword and primary translation lead; quiet metadata; one
  section rhythm for READ AS and the components; Expand is the only disclosure
  control and reveals other entries; buttons use a fixed 26 px height and 7 px
  radius on every platform; an unchanged answer is not rebuilt.
- Control Center: every `<select>` is presented as one accessible combobox
  (button + listbox, `aria-activedescendant`, arrows/Home/End/Enter/Space/Esc,
  outside dismissal, disabled state, reduced-motion aware transition); the
  select remains the page's value. Semantic `--exit-*` and `--menu-*` tokens;
  Quit uses the accent. Apple Vision is offered only where available and
  refused otherwise; Automatic names what it resolves to.
- Identity: provisional icons (8 PNG sizes, favicon, `.ico`, `.icns`) in
  package data and PyInstaller; Qt window icon and display name; macOS menu
  name `Hanly` in source runs; Windows AppUserModelID; tray/menu-bar image;
  Control Center titled `Hanly` with an inline favicon; the Windows title bar
  follows the page's theme through DWM (a child-local `frame_theme` call, never
  forwarded to the shell). The packaged inventory requires the icons.
- Capture-area prompt: reusable `HanlyPrompt` styled from the shared Qt palette
  (`qt_theme`, now also the popup's); in front on the first request (the Control
  Center calls `AllowSetForegroundWindow` for the shell before asking; macOS
  activates the shell).
- Copy logs: falls back to a child-local `copy_text` that writes the system
  clipboard on the Qt thread and reports success; nothing is traced.
- Updater cleanup: the handoff helper starts from the temporary root, not the
  directory it leaves behind (which it and the relaunched Hanly held open);
  read-only entries are cleared once; only directories shaped as a handoff are
  reaped from the shared temp root; one still in use is kept for a later launch.
- Engine status: the shell numbers transitions and names the last load, so a
  load that finished before the page asked still shows `loading` for 700 ms.
  Display only; the engine never waits.

## Mini-book acceptance (macOS)

*Phase B superseded this table: its lemma and dictionary columns credited a
headword reached from a misread target. Recomputed figures are under
Phase B review.*

`benchmarks/fixtures/minibook/minibook.json`: original story, 144 Korean
targets (TOPIK 1–6 estimate), 9 Latin refusal targets, bold/italic/serif
variants. Run: `python -m benchmarks.dev.minibook evaluate --paths
language,ocr,direct`.

| Path | Target | Lemma | Dictionary | Latin FP | Identical-input stability |
|---|---|---|---|---|---|
| Language only (exact selection) | 144/144 | 139/144 | 139/144 | 0 | — |
| Direct text, TextEdit via production AX | 144/144 | 139/144 | 139/144 | 0 | 153/153 |
| Forced OCR, Apple Vision, production pipeline | 141/144 | 137/144 | 137/144 | 0 | 153/153 |
| Forced OCR, EasyOCR `ko+en` (Windows backend) | 106/144 | 122/144 | 122/144 | 0 | 153/153 |

Popup presentations while moving inside one word: **1** (composition test;
**7** before the fix).

Failures, with stage (kept as regression evidence, not tuned away):
- Language stage, every path — `손님이`→손 and `비밀번호는`→비밀 (NNG+XSN /
  NNG+NNG never joined; both whole forms are in KRDICT); `누군가는`→누이다
  (누구+이다+ㄴ가 reconstructed as the verb 누이다; `누군가` is not in KRDICT);
  `뭉클해졌습니다`→뭉클 (`뭉클해지다` absent, `뭉클하다` present but never
  probed); `드릴`→드릴 "drill" (exact-surface precedence over Kiwi's 드리다).
- OCR target resolution — `매일`, `보존하는`: pointer inside Vision's line quad,
  but the proportional character estimate on an edge-clipped line lands on a
  space. `뭉클해졌습니다` cut at the ROI edge (production's clipping recovery
  would recapture; the language miss remains).
- EasyOCR: 38 target misses are its known Korean misreads (the documented `ㅆ`
  loss), not new.

## Automated validation

| Check | Result |
|---|---|
| `python -m pytest` (before the fresh build) | 2413 passed, 3 skipped, 1 failed — the packaged inventory against the stale pre-bundle bundle, which lacked the now-required icons |
| `python -m pytest tests/packaged` after the build | 3 passed, 1 skipped (identity without the expected commit) |
| `python -m pytest --suite native` | 116 passed |
| `python -m pytest --suite packaged`, `HANLY_REQUIRE_PACKAGED=1`, expected commit `5b016c4` | **4 passed** |
| `python -m ruff check packages packaging tests tools benchmarks` | clean |
| `python -m mypy packages packaging tests tools benchmarks` | Success, 296 files |
| `git diff --check` | clean |

Each correction's regression was shown failing on the previous code (Latin
routing and placeholders, retention, popup count, dwell display, handoff cwd).

## Real macOS validation

Done:
- Fresh `Hanly.app` at `5b016c4`: stamp `source_commit` = HEAD, 0.5.3, arm64;
  `CFBundleName`/`CFBundleDisplayName` `Hanly`; `hanly.icns` byte-identical to
  the supplied file; nine icon assets bundled; packaged gate 4/4 (frozen worker
  and frozen Control Center included).
- Real TextEdit direct text through the production AX coordinator: the table
  above (before the screen locked).
- Real Chromium (QtWebEngine) page: combobox open/keyboard/Escape/outside/
  disabled/value sync; Recognizer list `auto, vision, easyocr` on macOS; Copy
  logs with `navigator.clipboard` removed reaches the system clipboard (the
  user's clipboard is restored).
- Source run: Qt window icon at all 8 sizes, display name and application menu
  `Hanly`, Dock icon image set.
- Rendered and inspected: popup light/dark compact/expanded (corners clipped),
  Control Center combobox and exit role, capture prompt light/dark.

**Not done — the screen locked (`loginwindow` frontmost) partway through**, so
these need an unlocked session, on the fresh bundle:
1. Dock and menu-bar icon appearance; the Dock label of the bundle.
2. Hover over the TextEdit mini book with push-to-hover: one popup per word,
   the crossing to the popup, Expand/Collapse keeping it, Close, and a click on
   the popup not reopening the Control Center while a Dock click still does.
3. Select Area: prompt in front after one click; whole monitor, region, cancel.
4. Engine `loading` visible on a quick load in the Control Center.
5. A macOS source run's Dock tooltip still reads `python` (it comes from the
   interpreter executable); the bundle is `Hanly`.

## Windows continuation

On a Windows host, pull through this commit, then from `C:\Hanly` with the
validation interpreter (`$py`, as in the Windows report):

```powershell
& $py -m pip install -e packages/hanly -e "packages/hanly-app[runtime]" -c packaging/release-constraints.txt
& $py -m pytest --suite portable; & $py -m pytest --suite native
& $py tools\build_package.py
$env:HANLY_EXPECTED_SOURCE_COMMIT = (git rev-parse HEAD); $env:HANLY_REQUIRE_PACKAGED = "1"
& $py -m pytest --suite packaged
& $py -m benchmarks.dev.minibook render --out <scratch>\minibook
& $py -m benchmarks.dev.minibook evaluate --paths language,ocr --backend easyocr
```

Required evidence, one item per Windows-specific change:
- [ ] Latin: hovering `Claude projects vs CLI workflow`, `Kiwi`, `Wi-Fi`,
  `memo` in `minibook.html` (Chrome) and `minibook.rtf` (WordPad) produces no
  popup; the trace shows `not_korean` and no capture for UIA-read Latin.
- [ ] W2: over `minibook-canvas.html` and the Appendix B canvas, the refusal is
  `unsupported` and OCR runs; record the character under the pointer from a raw
  UIA read (U+FFFC or not).
- [ ] `이에요`-style stability: repeated hovers on one word give one answer;
  record the route (direct or OCR) of any divergence.
- [ ] Moving inside a word (Chrome, WordPad): one `popup_visible` per word; the
  next word updates once; leaving dismisses per policy; the crossing to the
  popup holds it; Expand/Collapse keeps it on screen.
- [ ] Popup: rounded corners clipped on a light and a dark background; button
  shape identical to macOS.
- [ ] Control Center: combobox with mouse and keyboard in the packaged window;
  Apple Vision absent; Automatic says it uses EasyOCR; Quit in the accent.
- [ ] Identity: the executable, taskbar button, window and tray show the Hanly
  icon (not Python's); the title bar follows Light/Dark (Windows 10 dark mode;
  Windows 11 caption colour).
- [ ] Select area: the Hanly prompt is in front on the first click from the
  Control Center; whole monitor, region and cancel work.
- [ ] Copy logs pastes the visible records.
- [ ] Updater: leave `%TEMP%\hanly-update.*` directories from an interrupted
  whole-bundle handoff older than an hour; the next launch removes them, or
  logs "still in use … later launch" while a helper or relaunched Hanly runs,
  never an Access-denied line; no `.hanly-update` transaction with `backup`,
  `previous` or `plan.json` is touched.
- [ ] Engine status shows `loading` then `loaded` on a warm start.

## Findings

**Fixed now:** the Latin false-positive chain (EasyOCR language mask; terminal
`not_korean`); placeholder refusal for canvas and images; direct-text retention
(the Windows rebuild); resize flipping; popup click reopening the macOS Control
Center; popup corner clipping and hierarchy; native selects; Vision offered on
Windows; Quit colour; application name and icons; the Windows title bar; the
capture prompt's style and foreground; Copy logs without `navigator.clipboard`;
`hanly-update.*` cleanup; invisible brief engine loads.

**Deferred:**
- **Noun compounds and derivations not joined** (`손님`, `비밀번호`) — revisit
  with the next whole-form change; add both as regressions first.
- **Pronoun+copula reconstructed as a verb** (`누군가는`→`누이다`) — revisit
  with the next whole-form change.
- **`-어지다` forms skip the `-하다` base** (`뭉클해졌습니다`) — same trigger.
- **Exact-surface precedence ignores morphology's part of speech** (`드릴`) —
  revisit when surface precedence next changes; `고소득층` must stay protected.
- **Line-quad character estimation on edge-clipped lines** (`매일`,
  `보존하는`) — revisit by reading Vision's per-range boxes
  (`boundingBoxForRange`) instead of estimating.
- **U+FFFC as the W2 cause** — unconfirmed; revisit with the Windows item above.
- **Real macOS interaction checks** listed under Real macOS validation.
- Existing W1, W3, F5 recovery, F12 and the host `ensurepip` item are
  unchanged.

**Dismissed:**
- *Nondeterminism on identical input* — none measured (306 repeats, one answer
  each); the reported divergence is route/crop dependent.
- *Cheaper Vision PNG encoding* — measured at 0.3–1.1 ms of 22–37 ms warm.

## Privacy

- The mini book is original synthetic text; every report string is from it.
- The reference screenshots and the logo generators, social and wordmark files
  were not committed; only the production icon assets were.
- Renders and experiments lived in the session scratchpad; no screen capture of
  real content was taken or written; traces kept event kinds and ids only.
- Copy-logs text goes only to the clipboard; the native test restores the
  user's clipboard.
- Freeze and Export are unchanged; EasyOCR production `readtext()` evidence was
  not mixed with staged diagnostics (none were run).

## Suggested review targets

- `_stands_in_for_content` and the terminal `not_korean` route: whether any real
  control reports whitespace or a glyph where OCR should still run.
- The legacy `["ko"]` upgrade in `runtime._easyocr_config`.
- `PopupController._place`/`_move`: side memory, clamping, and the equal-result
  skip (structural equality of `LookupResult`).
- The combobox's value-descriptor override and `MutationObserver` sync.
- `frame_theme` and `copy_text` as the only child-local page calls, outside the
  shell allowlist by design.
- `_remove_tree` raising `PermissionError` to mean "in use" (Phase B
  replaced this; see below).

## Review assignment

Human-selected after implementation. Completed on macOS; see Phase B review
at the end of this file.

---

# macOS Interactive Acceptance — Phase A Resume, 2026-09-25/26

- **Run:** Claude Opus 5.5, macOS 26.6.2 arm64, unlocked session. Phase A
  only; nothing pushed or merged. Starts at `b241f96`.
- **Package identity:** `dist/macos/Hanly.app` built from the clean tree at
  **`1461a2e`** (stamp `source_commit` = `1461a2e64d576591df980e23ce0bf28d1215339f`,
  0.5.3, arm64; `CFBundleName`/`CFBundleDisplayName` `Hanly`; `hanly.icns`
  byte-identical to the supplied file). `caf76b1` changes only
  `tests/conftest.py`; this handoff commit is documentation. The earlier
  `5b016c4` bundle is superseded.
- The packaged app ran with a scratch `--app-config` (push-to-hover, `auto`
  recognizer, load while watching); the user's own config was not touched.
  Input was synthetic (Quartz events). Only Hanly's own windows and its Dock
  and menu-bar item rectangles were captured, to the session scratchpad.

## Real checks exposed defects — fixed, rebuilt, rechecked

Five product defects (five product-fix commits) and one test defect
(`caf76b1`, test-only).

| Commit | Defect found in the packaged app | Evidence |
|---|---|---|
| `714cca1` | Select Area's prompt opened **behind** the Control Center: macOS 14+ activation is cooperative and the Control Center kept it. The child now yields activation to the shell before asking. | Prompt first in window order at 0.75 s, behind from 1.0 s; child frontmost |
| `f313c41` | Once the shell could activate, the reopen route read that activation as a Dock click and raised the Control Center over the prompt. An activation while a shell modal is open is no longer a reopen. | Prompt on top at 0.5 s, covered from 0.75 s |
| `f3cb2ca` | A second Select area click while the prompt was open nested a second prompt; a region chosen from it left an overlay under the first modal that took no input. One choice at a time; a repeat brings the open one forward. | Two prompt windows; overlay ignored drag and Escape |
| `38f494f` | Qt styles named faces the platform lacks (`Segoe UI…` on macOS); Qt scanned every family (`Populating font family aliases took 119 ms`). | First popup render 172–315 ms → 89–153 ms |
| `1461a2e` | The permission rows flashed: every refresh (grant watch ticks, window refocus) rebuilt them and replayed their entrance. They are redrawn only when an answer changes. | Reported by the human; harness counts 0 rebuilds on identical refreshes (failed before) |
| `caf76b1` | `test_hover_e2e_supersedes_stale_movement…` read the real screen through AX (the TextEdit mini book) and failed; portable compositions no longer use the host reader. | Real AX at the test's points: `direct`, `unsupported`, `timed_out` |

Each product fix has a regression that failed before it; each was followed by
a rebuild from the new product HEAD and the identical check.

## The five requested checks

1. **Dock and menu bar (packaged): pass.** The Dock item's AX title is `Hanly`
   with the Hanly icon; the menu-bar status item shows the Hanly mark (soft at
   22 pt, as pystray scales the 24 px source); the application menu reads
   `Hanly`; the Control Center child is an accessory (one Dock tile).
2. **Push-to-hover over the TextEdit mini book: pass, with one disclosed
   substitution.** macOS does not deliver injected key events to Carbon hot
   keys (0 of 3 injection methods reached a registered hot key in isolation),
   so the chord edge was delivered to the handler Carbon calls
   (`ManualLookupRuntime._set_push_held`) through Hanly's UI dispatcher.
   Everything else was real: Start from the Control Center, pointer events
   through Hanly's observer, TextEdit read through AX, Vision, the Qt popup.
   This ran as a **source run at `1461a2e`**, because the packaged ad-hoc
   build has no macOS grants (below).
   - resting on `할머니는`: 1 lookup, `direct`, `SUCCESS`, 1 `popup_visible`;
   - 12 small movements and 3 syllable moves inside it: 26
     `hover_inside_retained_target`, **0 new lookups, 0 new popups**;
   - moving to `매일`: **exactly 1** lookup and 1 `popup_visible`; the popup
     moved to sit just below the new word (x 80 → 147, top 178);
   - moving from the word down onto the popup: same window, no lookup;
   - Expand 340×250 → 386×310 and Collapse back, top-left fixed at (147,178);
   - popup clicks with the Control Center minimized: it **stayed minimized**;
   - Close: popup gone;
   - a deliberate Dock click (packaged) restored the minimized Control Center.
3. **Select Area (packaged, final build): pass.** The Hanly prompt is in front
   0.41 s after one click and stays there with the shell frontmost; Cancel
   changes nothing; a second request keeps one prompt, in front; Select an
   area puts the overlay on top and a drag saves the region; Whole monitor
   saves `full_monitor`; Escape on the overlay cancels.
4. **Engine status (packaged): pass.** Switching Lookup engine to Keep loaded
   in the Control Center gave `sleeping` → `loading` (≈4.2 s, frames 1–24) →
   `loaded`, a real Vision + Kiwi + KRDICT load with no added delay; a warm
   reload also showed `loading`. The sub-round-trip case stays covered by the
   controlled-provider test.
5. **Source-run Dock label: recorded.** The Dock lists the source run as
   `python3.13` — from the interpreter executable, a non-packaged
   limitation — and the packaged app as `Hanly`.

Also in the packaged Control Center: the comboboxes opened in Hanly's design
(flipping upward near the window edge), a keyboard choice saved `always` and
was restored, Escape closed the recognizer menu unchanged; Copy logs copied
**21 records** ("Copied 21 records."), and the clipboard was restored.

## Not confirmed

- **Push-to-hover inside the packaged app.** macOS answers "not granted" to
  `AXIsProcessTrusted`/`CGPreflightScreenCaptureAccess` in the packaged shell.
  Both builds are ad-hoc signed, whose designated requirement is their exact
  cdhash: the human's existing grant belongs to the installed 0.5.2
  (`2029c435…`), this build is `6d6ccc7d…`-class and new with every rebuild.
  The hover evidence above is the same product code as a source run.
  **Revisit** with a stably signed build, or after a grant for this binary.
- **The real Carbon chord**, which only physical keys reach.

## Validation

| Check | Result |
|---|---|
| `python -m pytest` | **2418 passed, 3 skipped** (non-macOS Vision, opt-in real EasyOCR, packaged identity without the expected commit) |
| `python -m pytest --suite packaged`, `HANLY_REQUIRE_PACKAGED=1`, expected `1461a2e` | **4 passed** |
| `python -m pytest --suite native` | **117 passed** |
| ruff / mypy (297 files) / `git diff --check` | clean |

## Privacy

Synthetic mini-book text only; captures were Hanly's own windows and item
rectangles, kept in the scratchpad; traces kept event kinds and ids; the
copied log records and the clipboard content were not persisted, and the
clipboard was restored; the user's config and grants were not modified by the
run.

## Windows continuation (unchanged, plus the new fixes)

The checklist in *Windows continuation* above still applies, on a build of
`1461a2e` or later. Add:
- [ ] Select Area in front on the first click **and** a second click while
  it is open keeps one prompt (the re-entrancy guard is platform-neutral).
- [ ] The permission rows do not flash when the window regains focus.

---

# Phase B Review — 2026-09-26

- **Reviewer:** Claude Opus 5.5 (Claude Code), chosen by the human. macOS 26.6.2
  arm64, `.venv` Python 3.13.11. No Windows host; no Windows behaviour was
  simulated.
- **Range:** `5b7358c..a8ef82e` (19 commits, `5869e9d`…`a8ef82e`), all left
  unchanged; review commits follow `a8ef82e`.
- **Verdict:** **Accepted for macOS with four review corrections.** The Windows
  items stay open on the checklist below.

## Reproduced independently

- **Latin routing.** Same model and charset, `["ko"]` vs `["ko","en"]` over the
  Latin fixtures: 10 → 0 Hangul hallucinations, Korean reads unchanged, warm
  latency equal. The frozen build loads `en_char.txt` and runs `ko+en` in its
  self-check. Verified non-Korean direct text is terminal `not_korean`;
  U+FFFC/U+FFFD and control categories stay `unsupported` and go to OCR.
- **Hover retention.** Moving inside one word: 1 popup (the mutation that
  drops retention gives 7). Identical input is stable (153/153 per path).
  `이에요` on Windows is **not** claimed resolved.
- **Popup placement.** Right/bottom edges, negative-origin screens, corridor
  to the popup, Expand/Collapse at the edge: placement stays on-screen, and the
  AX edge scan found 1439/1440 positions inside. Cold first render measured
  72–162 ms after `38f494f` (the Qt font alias scan is gone).
- **Comboboxes.** One canonical `<select>`, value setter and `MutationObserver`
  keep the menu in step, Arrow/Home/End/Escape/Enter, ARIA roles and
  `aria-activedescendant`, no duplicate options; Apple Vision offered only on
  macOS; a choice is saved once.
- **Identity.** Icons packaged once; removing any icon size now fails the
  packaged inventory; `CFBundleName` `Hanly`. The source-run Dock label
  `python3.13` remains a documented limitation.
- **Capture prompt.** The Phase A packaged checks (first click, rapid second
  click, Cancel, Whole monitor, region, Escape, Dock reopen) were re-read
  against the code; the repeat-request guard has a composition test.
  **Shutdown with the prompt open was not exercised** (closed below by `bdb66fe`): by reading, the
  `finally` blocks restore the hover mute and clear `_choosing_area`, but no
  test or real run covers it. Revisit with the next capture-prompt change.
- **Clipboard.** `copy_text` is child-local, runs on the Qt thread, is
  bounded, and writes no trace; the real embedded test
  (`tests/native/shared/test_control_center_copy.py`) passed again and
  restored the clipboard.
- **Mini book.** Original text, schema validated, every metric recomputed from
  the per-target records (below).

## Findings

**Fixed now** (each with a regression that failed on the reviewed code):

| Commit | Defect | Class |
|---|---|---|
| `0eb908f` | Update cleanup could leave its boundary: a *directory* named like the helper script matched the "ours" shape; the read-only retry `chmod`ed through a symlink out of the tree; a held directory in Hanly's own root raised instead of reporting "in use". | product (Windows path, exercised portably) |
| `7e56ebd` | The packaged inventory required only some icon sizes, so a bundle missing the tray's size passed. | test/packaging |
| `9eccfdc` | A Control Center opened after a load finished replayed that load as `loading`; the latch now takes its baseline from the page's first answer. | product (display) |
| `6207c86` | The mini-book scorer divided lemma/dictionary by reached targets only and counted a right headword from a wrong word as success; empty OCR and skipped targets fell out of the denominator. | diagnostic |

Recomputed mini book (success = right target, lemma and headword):

| Path | Success | Target | Lemma | Headword | Headword from inexact target | Latin FP | Stable |
|---|---|---|---|---|---|---|---|
| Language only | 139/144 | 144 | 139 | 139 | 0 | 0 | — |
| Direct text (TextEdit AX) | 139/144 | 144 | 139 | 139 | 0 | 0 | 153/153 |
| Apple Vision | 137/144 | 141 | 137 | 137 | 0 | 0 | 153/153 |
| EasyOCR `ko+en` | 103/144 | 106 | 122 | 122 | 19 | 0 | 153/153 |

EasyOCR's dictionary column exceeded its target column because 19 misreads
still lemmatized to the right headword; they are no longer successes. The
Vision misses are the same seven (k008, k122 target; k061, k088, k099, k102,
k137 morphology) and remain classified as in Phase A.

**Deferred:**
- **In-place update helper starts with its transaction as working
  directory** (`app_update_helper.start_helper`, `runner(arguments,
  script.parent)`) — the pattern `1278378` removed from the whole-bundle
  handoff. Windows-only; revisit on the Windows updater check below.
- **Light-theme tertiary ink contrast** (closed below by `cee728d`) — `ink3` is 3.55:1 on the popup
  background and 3.23:1 on the footer (dark: 4.37:1), under 4.5:1 for small
  text. Palette predates this range; revisit with the next popup palette
  change.
- **Packaged hover on macOS** (trigger restated below) — ad-hoc signing binds TCC grants to each
  build's cdhash; revisit with a stably signed build.
- All Phase A deferrals stand (language misses, edge-clipped line estimation,
  W2 U+FFFC, physical Carbon chord).

**Dismissed:**
- *Pointer on the digit of `2개` refuses* — a digit is not Korean; the
  counter itself looks up.
- *Engine latch hides real state* — it only delays `loaded` for display;
  status and the permission rows redraw on any changed answer.

## Validation (HEAD `6207c86`)

| Check | Result |
|---|---|
| `python -m pytest` | **2425 passed, 3 skipped** |
| `python -m pytest --suite native` | **117 passed** |
| `python -m pytest --suite packaged`, `HANLY_REQUIRE_PACKAGED=1`, expected `6207c86` | **4 passed** |
| ruff / mypy (297 files) / `git diff --check` | clean |

**Package identity:** `dist/macos/Hanly.app` rebuilt from the clean tree at
`6207c86` (stamp `source_commit` `6207c8623de6b3ddf08d70013e790c0b26b1a2d5`,
0.5.3, arm64, `CFBundleName` `Hanly`, `hanly.icns`, nine icon assets).
The `1461a2e` bundle is superseded.

## Privacy

Only synthetic mini-book text and Hanly's own windows were read; renders and
logs stayed in the session scratchpad; no screen pixels, AX text, OCR text or
clipboard contents were written to the repository or to Hanly's data
directories; the clipboard was restored by the native test.

## Windows continuation (after Phase B)

On a build of `6207c86` or later, the checklists above still apply. Add:
- [ ] Updater cleanup: a directory named `hanly-update-helper.ps1` and a
  symlink inside a stale `hanly-update.*` are left untouched; a held
  directory logs "still in use", never an exception.
- [ ] In-place update: the helper completes and its transaction directory is
  removed afterwards (record whether its working directory blocks removal).
- [ ] Control Center opened after a warm load shows `loaded`, not `loading`.

---

# macOS Deferral Closure — 2026-09-26

- **Run:** Claude Opus 5.5, macOS 26.6.2 arm64. Starts at `206ad98`; no
  Windows work.
- **Commits:** `cee728d fix: give small muted text AA contrast in both themes`,
  `bdb66fe test: quit while the capture-area choice is open`, and this
  documentation commit.

## Contrast — Fixed now (`cee728d`)

The tertiary ink (`ink3` in `qt_theme.PALETTES`, `--text-muted` in the
Control Center) moved the least distance, along its own hue, that clears
4.5:1 against both popup surfaces:

| Theme | Before → after | On card (`bg`) | On footer (`foot`) | `ink2` on card |
|---|---|---|---|---|
| Light | `#85888F` → `#6B6E75` | 3.55 → **5.11** | 3.23 → **4.65** | 6.12 |
| Dark | `#858890` → `#898C94` | 4.37 → **4.61** | 4.75 → **5.01** | 7.99 |

`tests/test_theme_contrast.py` checks every ink against both surfaces in both
themes (3 cases failed on the old tokens), keeps `ink` > `ink2` > `ink3` with
at least 0.5 between the secondary and tertiary inks, and ties the Control
Center token to the popup's. Light and dark renders of three entries,
compact and expanded, keep the hierarchy: section labels, hanja and meta
lines stay quieter than the secondary text.

## Shutdown with the capture prompt open — no defect (`bdb66fe`)

- `tests/native/shared/test_capture_prompt_shutdown.py` (real Qt): Quit while
  the Hanly prompt **or** the region overlay is open ends the application loop
  in under 1 s. The choice returns `None`, no Hanly window stays visible, and
  `quitOnLastWindowClosed` is restored. A mutation that reshows the prompt
  after an interrupted `exec()` fails it.
- `tests/test_application.py::test_quitting_while_choosing_restores_hover_and_the_guard`:
  hover is muted then restored (`mute=True`, `mute=False`), `_choosing_area`
  is cleared, and a later request shows the prompt again. Restoring the mute
  after shutdown has begun is a no-op (`ManualLookupRuntime.set_hover_muted`
  returns once closed).
- **Packaged, real:** the app was built at `bdb66fe`. Select area was clicked
  (the prompt opened), then Quit Hanly → Quit in the Control Center. **All
  three processes** (shell, resource tracker, Control Center) exited in
  **0.47 s**. The child's pending `select_capture_area` call reported
  `RuntimeError: Hanly closed before answering.` on its stderr: a truthful
  refusal while it exits, not a hang (Dismissed). Hover restoration was not
  observable in the package (no grants, below); the composition test covers it.

## Packaged hover and TCC — Deferred, signing identity

`codesign -dv` / `-d -r-`: `dist/macos/Hanly.app` (`bdb66fe`) and the
installed `/Applications/Hanly.app` (0.5.2) are both `Signature=adhoc`,
`TeamIdentifier=not set`. Their designated requirements are
`cdhash H"fbc2046c…"` and `cdhash H"2029c435…"`. TCC keys a grant to the
designated requirement, so each rebuild is a new app to macOS. Hanly's
`AXIsProcessTrusted`/`CGPreflightScreenCaptureAccess` answers report that
truthfully. This is a signing-identity limitation, not a runtime defect.
Permissions were not reset, bypassed or automated.

**Revisit trigger:** the first macOS build signed with a Developer ID
certificate, whose designated requirement names the team rather than a cdhash.
Then:
- [ ] grant Accessibility and Screen Recording once;
- [ ] confirm the grant survives a rebuild and an update to a newer signed
  build;
- [ ] run packaged push-to-hover over the TextEdit mini book.

## Found in passing — Deferred

- **Light accent ink on small text:** `accent_ink` `#B75C76` is 4.37:1 on the
  light card and 3.84:1 on its chip wash (the part-of-speech chip, 11 px).
  Outside this change's tertiary-ink scope; revisit with the next accent or
  popup palette change. Dark is 8.05:1 / 6.22:1.

## Validation (HEAD `bdb66fe`)

| Check | Result |
|---|---|
| `python -m pytest` | **2445 passed, 3 skipped** |
| `python -m pytest --suite native` | **119 passed** |
| `python -m pytest --suite packaged`, `HANLY_REQUIRE_PACKAGED=1`, expected `bdb66fe` | **4 passed** |
| ruff / mypy (299 files) / `git diff --check` | clean |

**Package identity:** `dist/macos/Hanly.app` built from the clean tree at
`bdb66fe` (stamp `source_commit` `bdb66fe55617ac2916ba4eec97eceafe02e37f47`,
0.5.3, arm64). It contains `cee728d`'s tokens. The `6207c86` bundle is
superseded.

**Privacy:** the renders were of synthetic dictionary entries, kept in the
scratchpad; the packaged run used a scratch `--app-config` and read only
Hanly's own windows and buttons.

**Windows continuation:** unchanged. Use a build of `bdb66fe` or later, and add:
- [ ] popup and Control Center muted text readable in Light and Dark.
