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
- `_remove_tree` raising `PermissionError` to mean "in use".

## Review assignment

Human-selected after implementation. Not started.
