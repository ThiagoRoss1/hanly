# Lab hardening and lookup corrections (macOS) Review Handoff

## Bundle

- Member issues: Hanly Lab hardening bundle after `fc4d257`: evidence retention, scoring, command polish, justified lookup corrections.
- Implementation ecosystem: Claude Code (Opus 5.5), macOS 26 arm64, Python 3.13.11 venv, Apple Vision.
- Date: 2026-10-01.
- Branch `lab/app-health`; commits `c8db0a6`..`HEAD` below. Nothing pushed, merged, tagged or released.

## Implemented

- `c8db0a6` **fix: bind tour evidence and verdicts to verified hovers.**
  - `events.jsonl` now never holds a content field (`*_evidence`, `ocr_boxes`), in any mode.
  - Answers are bound by hover/lookup ID, and ownership is re-sampled after the answer.
  - A refusal requires a deliberate decline.
  - Adds rule `strict-headword-v2`, same-rule baseline comparison, and English-translation eligibility for words.
- `13a8bcb` **feat: make the standard lab tour and reports easy to reach.**
  - Plain `python -m lab tour` is the comparable standard tour; adds `--quick` and `--baseline`.
  - Checks prerequisites before taking the pointer.
  - `report --list`, bare run names, and runs found by start-time name.
- `ffefa50` **fix:** probe the surface without trailing particles (손님이 → 손님, 비밀번호는 → 비밀번호).
- `bc155b0` **fix:** refuse whole-form joins across overlapping units (누군가는 no longer answers the invented 누이다).
- `e376cda` **fix:** probe an adverb's listed 하다 predicate (뭉클해졌습니다 → 뭉클하다), falling back to the adverb.
- `39e0bab` **fix:** a test assertion in `e376cda` was wrong and was committed with a failing exit hidden by a pipe. Corrected separately, not amended.
- `bd7527b` **docs:** lab README scoring and guarantees; stale-handoff correction; checkpoint path.

## Confirmed defects and evidence

- **Evidence retention.** A synthetic sentinel showed `result_evidence` persisted with the retention window closed, while `ocr_evidence` did not.
  - Scope, from recorded runs: human `run` sessions persisted none, because production emits no evidence to a sink that does not request it. Every tour persisted `result_evidence` for every lookup, including rest-point hovers outside verified windows.
  - The early spike `artifacts/lab/runs/20261001-043306-tour` predates the ownership guard and holds real recognized screen text (Control Center and other windows). It is gitignored and local. **Recommend the human delete it.** It was left untouched rather than deleted unasked.
- **Association.** The driver attributed every event inside a time window to the current target, so a stale lookup completing late could answer it. It is now bound by IDs, with regression tests for stale and only-stale cases.
- **Refusals.** A refuse target counted as refused on any non-`SUCCESS` status, including a missing result. A timeout, error or missing result now cannot pass.
- **Ownership guard.** It sampled five points before the hover only. It now samples a 15-point grid over the default 200×100 capture region, both before and after the answer.
  - An unknown owner counts as foreign.
  - A captured region larger than the probe (after device-pixel scaling) is unscored.
  - This is a sampled two-moment check, not per-pixel or continuous proof. The README says so.
- **애기.** The baseline database (`~/.config/hanly/resources/krdict/krdict.sqlite3`, 20260819-v1) has one sense for 애기: the cross-reference "→ 아기", with no English translation. The provider correctly serves only `t.language = 'en'`, and 1,685 entries have no English translation.
  - This was a corpus defect, not a provider defect. Words now require an English translation.
  - The same seed changes exactly one word: 애기 out, 삼총사 in. This was verified by re-running the old sampler, which reproduced the baseline's 300 words.
- **Lookups.** All five were reproduced through real Kiwi + KRDICT without OCR.
  - Three independent causes: a missing particle-stripped probe (손님이, 비밀번호는), a join across overlapping contraction spans (누군가는), and Kiwi not joining adverb + 하 (뭉클해졌습니다).
  - **누군가 is not in KRDICT at all**, so the story's expected answer is unreachable. The fix stops the invented 누이다, and the answer is now 누구 ("who"). It remains a `wrong_lemma` failure under the strict rule.
  - **드릴 is unchanged.** Its exact surface is a dictionary noun, and only sentence context selects 드리다. It is now labelled `ambiguous_surface`. No heuristic was added.
  - P3 was first considered as a Kiwi-adapter lemma swap. Over 231 real adverb + 하 readings, X하다 was answerable for 175 and absent for 56 (e.g. 옹기종기), so the swap would have regressed those 56. It was implemented instead as a dictionary-verified probe with fallback.

## Implementation-side validation already run

- `.venv/bin/python -m pytest --suite portable` → 2,460 passed, 2 skipped, exit 0. The 5 warnings are PyTorch deprecations raised inside EasyOCR during an existing packaging test.
- `.venv/bin/python -m pytest --suite native` → 125 passed, exit 0.
- `.venv/bin/python -m ruff check packages packaging tests tools lab` → clean. `.venv/bin/python -m mypy packages packaging tests tools lab` → clean, 324 files.
- Language regressions: real-KRDICT `tests/krdict/test_whole_form.py` 46→65 collected cases including adversarial neighbours (particle stripping never crosses whitespace or cuts endings, cursor sensitivity of 초대받았어요, unlisted 하다 forms keep the adverb, exact surface still first). Unit doubles in `tests/test_whole_form_lookup.py`. Five-query cap unchanged.
- Live quick tour `20261001-165816-tour`: 23/24, zero content fields on disk, one bound lookup per hover, no foreign events.
- **Baseline** `20261001-053159-tour` on `fc4d257`, recorded under v1: 434 correct, 9 refused, 10 failures, 97.8%. Its raw recording and its original derived report are preserved; the report was regenerated byte-identically with `fc4d257` code after an accidental rebuild. Re-scored under v2: 443/453 (97.8%). The only verdict change is 드릴, `wrong_lemma` → `ambiguous_surface`.
- **After** `20261001-171914-tour` on `39e0bab` code: same display, Vision, seed 7, story 22 px, 300 words at 16/22/30/40 px, default dwell. Corpus differs only by 애기 → 삼총사.
  - Score: 446/453 (98.5%) under v2, 0 unscored, 452 targets matched.
  - Changed outcomes: 손님, 비밀번호 and 뭉클하다 `wrong_lemma` → `correct`. Also OCR-only churn with no code involved: 교사 (16 px) `no_text` → `correct`, 대응 (16 px) `correct` → `no_text`, 흥미 (22 px) `correct` → `misread` (Vision read 훙미).
  - Popup median 149.9 → 148.4 ms. Dictionary queries 602 → 607 across the run, p50 1.3 ms. Pipeline p50 24.1 ms.
  - Remaining failures: 춥다 misread, 깊이 unresolved, 누군가 (absent from KRDICT), 드릴 (ambiguous), 안내판 and 대응 at 16 px (no text), 흥미 misread.
- Fresh macOS build: see "Build" below.

## Build

- Production code changed (`language_pipeline.py`; `result_evidence` from `0f298a5`), so a fresh macOS build was made from clean commit `bd7527bb8cfc245a577c6b37bce5054e4f8619ea` with `tools/build_package.py --platform macos`. It records 1.0.0, arm64, build id `e34400cb-9bfe-4233-b05e-344ff64763c0`.
- The previous `e15204d` artifacts were moved, not deleted or relabeled, to `dist/archive-e15204d/`.
- The ZIP was reconstructed into `dist/reconstructed-bd7527b/`. The DMG was attached read-only and copied with `ditto` into `dist/reconstructed-dmg-bd7527b/`. The `--disk-image` check confirmed it opens onto `Hanly.app`.
- Both reconstructions match all **7,342** entries of `dist/release/macos/manifest.json` through `read_tree`: none missing, extra, differing or unsupported. Both pass `codesign --verify --deep --strict`.
- `HANLY_EXPECTED_SOURCE_COMMIT=bd7527b… HANLY_REQUIRE_PACKAGED=1 pytest --suite packaged` → **4 passed** on each reconstruction.
- No `lab/` or `benchmarks/` module is in the bundle.
- Not claimed: normal frozen shell → Control Center child identity (the standalone self-check covers page, bridge and exit only), and the Windows updater.

## Known limitations / intentionally unvalidated areas

- Ownership on Retina: captured image sizes are divided by the page's device-pixel ratio. This display reports 1.0, so a 2× display has not been exercised.
- Windows ownership (`WindowFromPoint`) and the whole tour remain unexercised on Windows. Linux fails closed, so nothing is scored there.
- Run-to-run OCR variance at 16–22 px moves individual verdicts; one tour is not a stable per-word measurement.

## Deferred considerations

- **Screen capture on the main thread (~31 ms median, about OCR's cost)** — revisit when latency work is scheduled; measure with a standard tour before and after.
- **OCR on 16 px text and individual misreads (춥다, 흥미, 안내판, 대응)** — revisit when OCR tuning gets its own bundle; build an image replay corpus first so changes are measured offline.
- **Startup prewarm (Kiwi about 1.1 s of a 1.2–2.0 s engine prewarm; first hover up to 6.7 s)** — revisit with the LookupPreload policy.
- **Following KRDICT cross-references (애기 → 아기) for untranslated entries** — revisit when dictionary coverage is in scope; it is a product decision, not a lab fix.
- **Context to choose between homographs (드릴 / 드리다)** — revisit only with an approved disambiguation design.
- **Resolver miss for 깊이 in "마음을 깊이 흔들었어"** — revisit with the word-resolver geometry.
- **Windows updater (`WIN-UPD-01`, `WIN-UPD-02`) and normal frozen-child identity** — unchanged by this bundle; revisit on the Windows machine.

## Suggested review targets

- `lab/session/driver.py` `observe`: the ID binding under re-fire, cache hits and popup-only events.
- `lab/session/scoring.py`: whether `ambiguous_surface` should count as a failure, and the `correct` rule's lemma-or-headword match.
- `language_pipeline._without_particles`: trailing-token ordering when Kiwi reports overlapping spans.
- Whether the 하다 probe should also cover an `XR`/`NNG` root that Kiwi leaves unjoined in other inputs.

## Mac completion bundle (2026-10-01, later)

A second, bounded correction and validation pass on the same branch. The
sections above describe `c8db0a6`..`aa570e2` as they were written; where this
section corrects them, it says so.

### Confirmed defects and corrections

- **Timeout scoring** (`b88ba79`, rule `strict-headword-v3`). `classify` passed a timed-out hover as `correct` (with a successful partial result) or `refused` (with a declined one), which contradicted the documented rule. Completion means the app's own popup decision for the bound lookup arrived before the driver's deadline. A hover without it is now `timed_out`, a failure, whatever partial result it carried.
  - `no_hover` (no lookup ever bound) and `error` keep precedence.
  - Six regressions failed before the fix and pass after.
  - Neither recorded tour contains a timed-out hover, so under v3 the baseline still scores 443/453 and `20261001-171914-tour` still scores 446/453.
- **Privacy claim** (`d7f598e`). The previous section's "recordings never contain recognized text" was **false**: `tour_result` persisted the selected word, answer, recognized regions and dictionary queries. The policy now enforced:
  - A tour result keeps the target's own corpus text (story surface and expected form, or the sampled KRDICT headword) and structural facts only: verdict, status, timings, region and query counts, and six text-free booleans.
  - Scoring is computed from those booleans, so every rule since v2 can re-score a run that kept no text.
  - What the hover read is persisted only with `--retain-fixture-text`, only for verified hovers, recorded as `fixture_text_retained` in `metadata.json`.
  - Unverified, stale, oversized-region and foreign captures keep neither text nor facts.
  - Reports (JSON, HTML, Markdown) show read text only for runs that opted in, so rebuilding an older recording no longer re-propagates its text.
  - The diagnostics mirror keeps text only for informational lifecycle lines; other lines keep subsystem and level, with `message_withheld`.
  - Sentinel tests cover the default, opted-in, unverified and late-result paths, rebuilt reports in all three formats, and withheld diagnostics.
  - Live check: `20261001-210808-tour` holds 0 evidence fields and no read-text keys.
- **Unfinished tours** (`5434009`). A tour stopped by the user scored "6/6 (100%)" with no sign it had stopped. Reports, summaries and the score line now state how the tour ended and how many planned hovers it reached, and add a finding that the score is not comparable.
- **Frozen identity check** (`c29702a`, `9485fac`). Added `tests/packaged/macos/test_frozen_identity.py` and catalog scenario `BUNDLE-LAUNCH-IDENTITY`. `9485fac` fixes a mypy error that `c29702a` was committed with: a `;` instead of `&&` hid the failing gate. Corrected, not amended.

### Frozen launch identity (the open gap from the earlier handoffs)

- **Method:** the `bd7527b` bundle launched through LaunchServices (`open -n` with an isolated `LOCALAPPDATA`/`XDG_CONFIG_HOME`/`HOME`, a smoke KRDICT, and update checks off). Owned processes were sampled about every 100 ms with `lsappinfo` and `psutil`. The test then: closes the Control Center with its own Accessibility close button; reactivates with a second `open`; reopens from the menu bar item "Open Control Center"; sends SIGINT to the shell only.
- **Observed:**
  - The shell is Foreground throughout.
  - Both Control Center children (initial, and tray-reopened) go unregistered → UIElement and are never Foreground.
  - WebEngine helpers and the multiprocessing resource tracker never register.
  - Every owned child exits within the 15 s grace after quit.
- **Results:** passed 4/4 runs directly (3 ZIP, 1 DMG reconstruction), and through `lab check` on both reconstructions with the SHA required.
- **Not defects:**
  - The first attempt "failed" to reopen on reactivation. That is approved behaviour (`application._install_reopen_route`): activation never resurrects a window the user closed on purpose; the tray is the documented route.
  - The absent "Window N is closed" log line after a user close is by design; only a shell-initiated close logs it.
  - A "survivor" in the first attempt was a child still winding down; it was already terminated when inspected.
- **Limit:** a registration shorter than the ~100 ms sampling interval cannot be excluded.

### Mac acceptance matrix (all on macOS 26 arm64, this display, `aa570e2`..`5434009`)

| Flow | Evidence | Result |
|---|---|---|
| `python -m lab --duration 20` | real source session | exit 0; report + summary; 0 evidence fields; no owned survivor |
| `python -m lab` interrupted by SIGINT at 14 s | real source session | exit 130 (user interrupt); report + summary; no owned survivor |
| `python -m lab tour --quick` | real driven hovers | 23/24, finished |
| Quick tour stopped by moving the mouse | real driven hovers | `stopped_by_user` after 6/24, exit 0, partial report, no survivor |
| `python -m lab tour --baseline 20261001-171914-tour` | real driven hovers | 446/453, 453 matched, 0 changed verdicts |
| `report <run>`, `report --list`, newest discovery, `--baseline` | rebuild from recordings | working; baseline directories never written |
| `check`: APP-STARTUP, CC-LIFECYCLE, CC-CONTROLS, CC-UPDATE-STAGE, CAPTURE-CHOICE, HOVER-POPUP, SETTINGS, UPDATE-COORDINATOR, UPDATE-APPLY-POSIX, MAC-IDENTITY, RESOURCE-DELIVERY | mixed real UI / injected / simulated, as labelled in the catalog | 11/11 passed (run `e8c959e8`) |
| `check`: BUNDLE-IDENTITY, -WINDOW, -WORKER, -LAUNCH-IDENTITY on ZIP and DMG reconstructions, SHA `bd7527b…` required | real frozen bundle | 4/4 passed on each |
| `pytest --suite packaged` on both reconstructions, SHA required, skips forbidden | real frozen bundle | 5/5 on each; `codesign --verify --deep --strict` on each |
| WINDOWS-UPDATE | not implemented | not run (Windows) |
| LIVE-HOVER on private screens | human-operated | not run; tours cover lab-authored pages only |

Fixed updater-helper checks (`UPDATE-APPLY-POSIX`, `UPDATE-COORDINATOR`) use simulated builds and delivery; they do **not** prove a complete real-release update.

### Tour comparison (same rule, same corpus)

- `20261001-210808-tour` on `5434009` vs `20261001-171914-tour` on `39e0bab`, both under `strict-headword-v3`, with seed 7, story at 22 px, 300 words at 16/22/30/40 px, Vision, this display and default dwell. The corpus is identical (the eligible word set has been unchanged since `c8db0a6`).
- Score: 446/453 → 446/453 (98.5%), 0 unscored, all 453 targets matched, **0 changed verdicts**. The OCR churn seen between the earlier pair (교사, 대응, 흥미) did not move this time; one rerun does not establish its rate.
- Popup median 148.4 → 150.5 ms, p90 172.7 ms. Medians: OCR 31.7 ms, capture 33.6 ms, dictionary 1.4 ms, pipeline 25.2 ms.
- Peak RSS: lookup 706 MiB, Control Center 303 MiB, shell 234 MiB. The shell figure includes the lab's in-process recorder.
- 98.5% is a score on this controlled corpus under this rule. It is not general OCR or translation accuracy.

### Gates

- `pytest --suite portable` → 2,475 passed, 2 skipped. `pytest --suite native` → 125 passed. `ruff check packages packaging tests tools lab` and `mypy packages packaging tests tools lab` → clean, 326 files. All exit 0.
- No file under `packages/`, `packaging/` or `tools/` changed since `bd7527b`, so its build remains the shipped code's build and no new build was made. It was never relabeled.

### What "Mac complete" covers

- **Covered:** every lab command on macOS; the fixed source checks listed above, each under its own evidence label; the frozen bundle's inventory, commit identity, window, worker and normal-launch identity on ZIP and DMG reconstructions; and the lab's own privacy, scoring and stop behaviour.
- **Not covered:**
  - a complete real-release update on any platform;
  - hover over private real-world screens, which needs a person;
  - Retina scaling of the tour's ownership probe;
  - sub-100 ms identity transients.

### Remaining work

- **Human cleanup item, still open:** `artifacts/lab/runs/20261001-043306-tour` was reported to hold private screen text from before the ownership guard. It was not opened, printed or deleted. Deleting it needs your authorization, and that authorization covers only that exact path.
- **Windows:**
  - the tour's `WindowFromPoint` ownership path and pointer driving;
  - a Windows counterpart of the launch-identity check;
  - `WIN-UPD-01` / `WIN-UPD-02` on an isolated real installation.
- **Deferred items above are unchanged:** capture threading, small-text OCR, startup prewarm, KRDICT cross-references, homograph context, and the 깊이 resolver miss.

## Review assignment

Human-selected after implementation. Not started.
