# Final Lab update Review Handoff

## Bundle

- Member work: the approved final Lab update ([brief](../plans/final-lab-update.md)),
  Waves 1–6, plus the requested removal of `# pragma` / `type: ignore`
  suppressions from `lab/`.
- Implementation ecosystem: Claude Code (Opus 5.5) on macOS 26 (Darwin 25.6.0,
  arm64), `.venv` Python 3.13.11 (code kept 3.10-compatible).
- Branch `lab/app-health`, from `d05b8db` to `7236dc6` plus this handoff.
- Date: 2026-10-07. Phase B ran afterwards; see the outcome at the end. Nothing
  was pushed, merged, tagged or released.

## Implemented

| Commit | Wave | What |
|---|---|---|
| `d9a27e8` | — | Approved brief recorded |
| `8de9410` | 1 | `identity.py` (`run_identity`), `lab_provenance` block in every writer, start-time source, plan fingerprints, `pins.py`, `baseline`/`pin`/`unpin`, `report --list --kind` |
| `f3db81c` | 2 | `comparison.py`: compatibility, occurrence matching by target and rendering, stress comparison, explanations, `indicative-bands-v1`, provenance/reproduction blocks, bare `--baseline`; stress negatives fix |
| `3f7ec7f` | 3 | `storage.py`: `lab storage`, `lab gc` preview/apply; update-check log retention and disposable declarations |
| `bb1c337` | 4 | Corpus schema 2 (truth, generation, family), generator v2, font discovery, `--profile` with budgets, `ocr-corpus --fonts` |
| `74ed3ce` | 5A+5B | `stage_evidence.py`: stage facts, first observed bad stage, stability over repetitions, `--repeats` |
| `47ce842` | 5C | `stress --corpus --repeats`, rule `corpus-surface-v1`, corpus section in `campaign.md` |
| `6356154` | 5D | `differential.py`: `ocr-campaign --compare-backends` |
| `28e25c3` | — | Suppression cleanup: no `pragma`, `noqa` or `type: ignore` remains in `lab/` |
| `123693a`, `f0fdd7c` | 6 | Fixes found in real runs: the rule a campaign shows; "interrupted" instead of "unknown" |
| `7236dc6` | 6 | Lab README, checks and fixtures READMEs, CODE-MAP, AGENTS/CLAUDE guidance |

5A and 5B share one commit: stability is computed from the same per-pass facts,
so splitting them would have left an intermediate commit with dead fields.

## Main expected behavior

- `python -m lab report --list` lists every run of every kind with commit,
  clean/dirty/unknown, platform, backend, completion and pin roles; manual
  material (`20261005-mac-update`, `w17-frozen-1`, `w3-backend-probe`) is `unknown`.
- `summary.md` and `campaign.md` open with Provenance and, given a baseline, a
  compatibility verdict and fixed explanations beside the raw numbers.
- `lab baseline set` refuses unfinished, unattributed, conflicting or (without
  `--allow-dirty`) dirty runs; `baseline unset` touches only that registration.
- `lab gc` deletes nothing unless given `--apply --plan`; on this Mac it
  proposes 0 bytes (no current-writer declarations exist here yet).
- Generated corpora carry stated truth and full generation identity; OCR
  campaigns, corpus stress and the differential report stage facts and stability.

## Architecture / seams touched

Lab only. No public engine contract, shipped runtime or dependency changed;
`packages/` neither imports nor bundles `lab` (setuptools finds `src/` only; the
PyInstaller spec names no Lab path). The OCR seam is used as before
(`OCRProvider`, production `WordResolver.resolve_target_detail`); `ocr-campaign`
still constructs no morphology, dictionary or UI. Privacy rules are unchanged:
corpus truth is lab-authored; desktop readings follow the existing ownership
and `--retain-fixture-text` rules.

## Relevant files / diff areas

`lab/identity.py`, `lab/pins.py`, `lab/comparison.py`, `lab/storage.py`,
`lab/stage_evidence.py`, `lab/synthetic_profiles.py`, `lab/differential.py`,
`lab/metadata.py`, `lab/corpus.py`, `lab/synthetic_ocr.py`, `lab/ocr_benchmark.py`,
`lab/report/{build,model,campaign}.py`, `lab/session/{runner,stress,stress_page,
stress_driver,stress_scoring,stress_replay,browser_text}.py`,
`lab/checks/{runner,windows_update}.py`, `lab/cli.py`; tests in
`lab/tests/test_{identity_pins,comparison,storage,synthetic_profiles,
stage_evidence,corpus_stress,differential}.py` and
`tests/native/shared/test_lab_corpus_page.py`.

## Implementation-side validation already run

- `ruff check packages packaging tests tools lab` → clean.
- `mypy packages packaging tests tools lab` → no issues in 355 files.
- `pytest --suite portable` → 2640 passed, 2 skipped (both pre-existing and
  environmental: opt-in EasyOCR inference; the non-macOS Vision path).
- `pytest --suite native` → 126 passed (includes the new corpus page layout).
- Real Mac evidence (all under gitignored `artifacts/lab/runs/`):
  - `20261007-193757-stress`: smoke corpus (`artifacts/lab/corpus/smoke-seed1`,
    `sha256:13aea30231312cdb`), 2 rounds, 48/48 scored, 0/24 false presentations,
    6/24 wrong (5 `ocr_misread`, 1 resolver); registered as the stress baseline.
  - `20261007-193919-stress`: same, `--baseline` → comparable, correctness
    unchanged, popup p50 and RSS within bands; baseline evidence byte-identical
    (checked with `shasum`).
  - `20261007-194020-stress`: SIGINT after ~30 s → 45 of 96 hovers kept, identity
    `interrupted`, refused as a baseline, every child process gone.
  - `20261007-194130-tour` (baseline) and `-194153-tour --baseline` → comparable,
    unchanged, popup within band, lookup sampled RSS "higher" (457.7 → 549.8 MiB).
  - `5faaaa7f-…`: two-backend differential on the smoke corpus, identical
    inputs, 19 shared passes, 5 backend-specific.
  - `lab storage` inventory (31.6 GiB: 9.69 GiB unknown in `runs/`, 16.75 GiB
    unknown and 5.03 GiB packaging in `dist/`) and `lab gc` dry run (0 bytes).
  - Earlier scratch checks: golden corpus contact sheet (targets and regions
    drawn on 22 images); legacy `20261005-053840-tour` vs `-053512-tour` (453
    matched occurrences, correctness unchanged, performance unavailable).

## Compatibility / migration

- Historical artifacts are never rewritten. Legacy sessions are read from their
  old fields and flagged "source read at shutdown"; their reproduction is never
  exact and they compare on correctness only (no protocol or host recorded).
- Corpus schema 1 still loads (no stated truth). The committed empty manifest
  moved to schema 2.
- Stress `false_positives` now counts presented answers only; timeouts and
  errors are in `negatives_failed_otherwise`. Older `campaign.json` files keep
  their recorded numbers until rebuilt.
- Adding `corpus`/`repeats` to the compared options changed every compatibility
  key once; the registry stores names only, so nothing needs migrating.

## Privacy and GC safety

- New report paths are tested for read text: a stress comparison with sentinel
  read text leaves none in `campaign.{json,md,html}`; the differential keeps
  only an exception type from a failing child. The real corpus run's
  `events.jsonl` has no `selected`/`recognized` field.
- GC was applied only to temporary fixtures: containment, links in and at the
  subtree, a redirected root, pinned/recent/unfinished/legacy/unknown runs,
  preserved names, stale contents, an edited plan, a replaced directory, a pin
  added after preview, a mid-deletion `PermissionError` and `KeyboardInterrupt`.
  **No real artifact was deleted.**

## Reproduction

```bash
python -m lab ocr-corpus-generate --profile smoke --seed 1
python -m lab stress --corpus artifacts/lab/corpus/smoke-seed1/manifest.json --repeats 2
python -m lab ocr-campaign --compare-backends --manifest artifacts/lab/corpus/smoke-seed1/manifest.json --repeats 3
python -m lab tour --quick --baseline
python -m lab storage && python -m lab gc
```

## Windows continuation (executable checklist)

On the Windows machine, after pulling `lab/app-health`:

1. `python -m pytest --suite portable -q`; `python -m pytest --suite native -q`;
   ruff and mypy as above.
2. `python -m lab report --list` → the existing Windows runs are recognized
   (`stress`, `tour`, `check`, `update_check`), with `-windows-update` runs whose
   `summary.json` predates provenance shown as `update_check` with unknown source.
3. `python -m lab baseline set 20261003-202512-stress --reason "Windows stress baseline (998/1,123)"`
   — expect refusal only if that run is unfinished or ambiguous; then `lab baseline`.
4. `python -m lab ocr-corpus --fonts` (expect Malgun Gothic, Batang/Gulim etc.
   from `C:\Windows\Fonts`), then `python -m lab ocr-corpus-generate --profile smoke --seed 1`.
5. `python -m lab stress --corpus artifacts\lab\corpus\smoke-seed1\manifest.json --repeats 2`
   → all hovers scored or honestly unscored; check `campaign.md` Provenance and
   Controlled images.
6. `python -m lab stress --per-family 14 --baseline 20261002-215759-stress`
   (a short campaign against an earlier short one) → compatibility verdict and
   raw-only labelling if the plan differs.
7. `python -m lab ocr-campaign --compare-backends --manifest artifacts\lab\corpus\smoke-seed1\manifest.json`
   → `easyocr` ran, `vision` not requested on Windows.
8. `python -m lab check windows-update --from v0.9.0 --mode rollback` → the new
   run's `summary.json` has `lab_provenance.disposable` and `logs/`; then
   `python -m lab gc` must list exactly that run's `install/`, `release/`,
   `profile/`, `temp/`. Apply only with the human's separate approval.
9. `python -m lab storage` → confirm Windows reparse points (junctions) under
   `dist/` or runs are counted as links and never followed.

## Known limitations / intentionally unvalidated areas

- **Performance bands are uncalibrated.** Two identical quick tours differed by
  92 MiB of sampled lookup RSS, outside the 32 MiB band; treat memory verdicts as
  indicative until repeatability evidence sets bands.
- Legacy runs have no plan fingerprint, protocol or host, so their comparisons
  are correctness-only by design.
- Windows: corpus stress, font discovery under `C:\Windows\Fonts`, the update
  check's log retention and reparse-point handling are implemented and
  unit-tested but not run on Windows.
- Corpus stress repeats can be answered by the lookup cache; `cache_hits` shows
  it, but stability over cached rounds says less than over fresh recognitions.
- A corpus image is painted at the primary screen's device pixel ratio; mixed-DPI
  setups (out of scope) may not paint 1:1.
- The GC has nothing to collect on this Mac; real reclamation needs a current
  Windows update-check run (checklist step 8) and human approval.
- Identity reads `events.jsonl` line by line with a keyword filter; a
  multi-gigabyte recording would make `report --list` slow.
- Generated corpora use local faces with unknown licences, so none are
  committed; the committed manifest is still empty.

## Deferred product findings (evidence, revisit condition)

- **Han characters read as Hangul.** Both backends read `漢字` as Hangul (Vision
  `로구`, EasyOCR `'#구`) in the golden corpus; a hover there could present a
  Korean answer. Revisit when the OCR branch evaluates script gating.
- **EasyOCR 을→올.** `golden-0-0000` is read as `기억올` (stable); the same
  family as the Windows stress misreads. Revisit with the OCR evaluation corpus.
- **Desktop vs offline divergence.** `smoke-1-0003` is correct in Vision
  `ocr-only` on the raw image but `ocr_misread` on the desktop in both rounds of
  two runs. Revisit by replaying the captured region (`--retain-fixture-images`)
  in the OCR branch; capture scaling is the first thing to check.
- **Backend-specific cases.** 5 of 24 smoke cases pass on one backend only (3
  Vision, 2 EasyOCR) in `5faaaa7f-…`. Revisit when choosing per-platform defaults.

## Suggested review targets

- `storage.apply` revalidation and deletion order, and `_is_link` on Windows
  junctions.
- `comparison.compatibility`: which mismatches block, which only warn, and
  whether performance eligibility is strict enough.
- `corpus_verdict`: that a dictionary miss after a correct selection never
  counts as an OCR failure, and `is_negative` for corpus no-Korean targets.
- `synthetic_ocr._draw_text` ink-box geometry and the supersample/scale
  transforms of the target point.
- `identity` content recognition for layouts not present on this Mac.

## Review assignment

Human-selected: Phase B general and macOS review, authorized 2026-10-07.

## Post-Bundle Review Outcome

- Reviewer: Claude Code (Opus 5.5), the same ecosystem and session that
  implemented the bundle; not an independent cross-provider review.
- Review ecosystem: macOS 26 (Darwin 25.6.0, arm64, display scale 2.0),
  `.venv` Python 3.13.11.
- Date: 2026-10-07. Reviewed range `d05b8db..2d82e8b` (13 commits, verified);
  corrections `db0c823..ace1a7d` (8 commits).
- Status: **accepted for macOS with corrections**; Windows validation pending.

### Fixed now

Each fix's regression test was shown failing before the correction.

- **GC could partly delete a subtree it could not read** (`db0c823`). A
  directory with mode 000 inside a declared `install/` was invisible to preview,
  so `install/` was proposed and apply deleted `install/x/f` before failing.
  Preview now keeps such a subtree ("cannot be read completely"), and the
  deletion walk fails before touching anything unread.
- **GC case-variant evidence** (`db0c823`). A declaration of `REPLAY` was
  proposed although on macOS and Windows it *is* `replay/`; preserved names are
  now compared case-folded.
- **Raw stderr in the differential** (`5e9fd38`). A failing child whose last
  line named no exception type put the text before its colon into the report;
  only a real exception type name, or `unknown`, is kept now. The per-backend
  `initialization` field was each case's first pass, not provider construction,
  and is now `cold_passes`.
- **Detector evidence from normalized output** (`0f4e8a3`). `recognition-only`
  regions are normalized results that can drop detector boxes; a detector
  response on an empty image is now claimed only from `detection-only`.
- **Hidden raw values; ambiguous baselines; registry crash** (`95cf16d`). An
  ineligible measure printed only "unavailable"; every line now leads with raw
  before/after and sample counts. Two baselines sharing a derived key were
  settled by registry order; the comparison now names both and uses neither.
  A corrupt `pins.json` made `report --list`, `storage` and `gc` end in a
  traceback; they now refuse with the registry's error (still failing closed).
- **Cached answers counted as fresh** (`87ea2dd`). Popup latency and corpus
  stability treated lookup-cache answers as fresh recognitions. The real seed-2
  run `20261007-230556-stress` had 3 cached repeats; they are now reported apart
  and excluded from judged repetitions (2 of 3 rounds judged for those cases).
- **Memory lines without sample counts** (`5266517`): `n=?/?` became the
  recorded process sample counts (`n=72/69` on the real tours).
- **Listing order** (`f43e90c`). Sessions write naive local time and campaigns
  UTC with an offset; sorting the strings misplaced runs by the local offset
  (three hours here). Runs are now ordered by a normalized instant.
- **Display scale unrecorded** (`ace1a7d`). On this 2.0 display a corpus image
  painted 1:1 is captured by the app as 200x100 pixels for a 200x100-point
  region, i.e. at half the painted density, while `ocr-campaign` reads it at
  full density. Nothing recorded this. Sessions now log the page's display
  scale; a known mismatch is not comparable, an unrecorded one is a warning; the
  corpus section shows the scale beside the captured region sizes. No cause is
  claimed.

### Commands and results

- `ruff check packages packaging tests tools lab` → clean.
- `mypy packages packaging tests tools lab` → no issues in 355 files.
- `pytest --suite portable` → 2656 passed, 2 skipped (opt-in EasyOCR model
  inference; the non-macOS Vision path). The skips are not passes.
- `pytest --suite native` → 126 passed.
- Real macOS runs at `87ea2dd`–`ace1a7d` (isolated profiles, lab-authored pages):
  - `ocr-corpus-generate --profile smoke --seed 2` → 24 cases (8/8/8), 0 omitted.
  - `20261007-230556-stress` (seed 2, `--repeats 3 --baseline`) → 63/72,
    0/39 false presentations; "no registered baseline" (different corpus and
    rounds, correctly a different key); 3 cached hovers kept apart.
  - `20261007-230700-stress` (seed 1, `--repeats 2 --baseline`) → comparable with
    `-193757`, correctness unchanged, latency and memory within bands; baseline
    `events.jsonl`, `metadata.json`, `processes.jsonl` unchanged (`shasum -c`).
  - `20261007-230810-tour` (`--quick --baseline`) → comparable with
    `-194130-tour`, unchanged, popup 131.2 → 126.2 ms (n=24/24), lookup RSS
    457.7 → 468.1 MiB (n=72/69).
  - `20261007-230934-tour`: pointer moved mid-tour from another process → stopped
    by user after 3 of 24, identity `stopped_by_user`, no leftover sampler,
    lookup, Control Center or WebEngine process. A SIGINT interruption was
    covered in Phase A (`-194020-stress`).
  - `report <tour> --baseline <tour>` rebuild → baseline files byte-identical;
    `report --list` and `--kind unknown` correct; manual directories stay unknown.
  - `ocr-campaign --compare-backends` on seed 2 (`3d46b5c5-…`) → identical
    inputs for both; Vision 24/24 stable correct, EasyOCR 21/24; 3
    backend-specific cases, all passed by Vision only.
  - `20261007-231205-stress` (`--retain-fixture-images`) and `-231418-stress`
    (display scale recorded: 2.0, regions 200x100 px).
  - `lab storage` (31.62 GiB; 9.69 GiB unknown in runs, 16.75 GiB unknown and
    5.03 GiB packaging in `dist/`) and `lab gc` (0 bytes; no plan written).
  - GC apply exercised only on disposable fixtures. No real artifact was deleted.
- Not rerun: packaged checks (no change affects frozen execution or packaging;
  `packages/` still neither imports nor bundles `lab`).

### Deferred considerations

- **Capture density on Retina** - the app captured corpus regions at 1 pixel
  per point on a 2.0 display; the 3 seed-2 cases Vision reads correctly offline
  (`smoke-2-0000`, `-0015`, `-0021`) are stable misreads on the desktop. Revisit
  in the OCR/capture branch, starting from `20261007-231418-stress` and the
  retained regions in `-231205-stress/replay/`.
- **Han read as Hangul; EasyOCR 을→올; backend-specific cases** (from Phase A) -
  revisit when the OCR branch builds its evaluation corpus.
- **Indicative bands uncalibrated** - Phase A saw a 92 MiB lookup RSS swing
  between identical quick tours; this session's pair moved 10 MiB. Revisit after
  a repeatability series of at least five identical tours.
- **Vision provider construction reads 0 bytes** - the framework loads on first
  use, so its cost lands in the first pass, not `provider_construction_bytes`.
  Revisit if memory attribution between backends becomes a decision input.
- **1:1 painting not independently verified at physical resolution** - the
  page sets the image's device pixel ratio and the native test checks placement,
  but no physical-resolution capture compared pixels (the lab re-grab is at
  logical resolution). Revisit with the capture-density item.
- **`report --list` reads every `events.jsonl`** - about 1 s for 70 runs here.
  Revisit if a machine holds multi-gigabyte recordings.
- **Same-session review** - the reviewer implemented the bundle. Revisit by
  choosing a cross-provider reviewer for the Windows pass if independence matters.

### Remaining Windows validation

Run the "Windows continuation" checklist above, plus, for the review fixes: a
junction inside a declared update-check subtree is kept with a reason; an
unreadable directory under one is kept; `REPLAY`-style case variants are never
proposed on NTFS; corpus campaigns record the Windows display scale and captured
region sizes; and `gc` lists exactly the new update-check run's working copies.
Real GC application still needs the human's separate approval.

### CI after the review (2026-10-08)

- **Linux `--suite portable`: 2 Lab test failures, fixed in `d39b757`.** The
  session identity fixture stamped the host's platform, so it passed only on
  Darwin arm64; `storage.preview`, `apply` and `inventory` bound their default
  roots at import, so a relocated runs root was ignored and `gc` passed only
  where the real `artifacts/lab/runs` existed. Reproduced on this Mac by
  reporting the host as Linux x86_64 with no real runs root; 80 passed after
  the fix. Portable here: 2656 passed, 2 skipped.
- **Windows `--suite native`: `test_lookup_process_spawn` fails, not fixed.**
  The real lookup child reached `ready` and then died on its first Korean lookup
  ("the lookup engine stopped") with empty stderr, which points to a native
  crash or a kill rather than a Python exception. No Lab commit touches the
  product or this test, and it passes in this Mac's native suite. One unproven
  hypothesis: the OCR runtime is unpinned (`easyocr>=1.7,<2` pulls torch), and
  torch 2.14.1 (2026-09-30, with a cp310 Windows wheel) is newer than the 2.13.0
  this Mac was validated with. Revisit on the Windows machine: run
  `python -m pytest tests/native/shared/test_lookup_process_spawn.py -q`, note
  `pip show torch kiwipiepy easyocr`, and if torch is 2.14.x retry with
  `pip install "torch<2.14" "torchvision<0.29"` before changing any code. Pin
  nothing until a version is shown to be the cause.
- **Windows native lookup spawn:** reported fixed by the human outside this
  session; confirm it on the next Windows CI run.
- **macOS `--suite native`: `test_capture_prompt_shutdown` timed out once in
  CI** (passes locally, alone and in CI order). Its watchdog reported "did not
  close after Quit" for any timeout, even when the prompt never appeared in
  time. `8b93d50` gives each case its own message with the visible windows and
  widens the deadlock guard from 5 to 15 s; pass conditions are unchanged.
  Revisit if it fails again: the message now says which case it was.
- **Linux `--suite native`: `test_control_center_combobox` failed, fixed in
  `4c779e6` (product).** Choice-list options highlighted on any `mousemove`,
  and Chromium replays one at a resting pointer when the content under it
  changes, so under Xvfb the option under the pointer took the highlight from
  the keyboard and Enter chose it. Reproduced by replaying a still-pointer
  `mousemove` (same failure as CI), then fixed: only a pointer that has moved
  since the list opened changes the highlight. Native coverage for a resting
  and a moving pointer. Gates on macOS at `4c779e6`: ruff and mypy clean,
  portable 2656 passed / 2 skipped, native 126 passed. Linux and macOS CI not
  yet seen green after this push.

## Windows Phase B Review Outcome

- Reviewer: Claude Code (Opus 5.5), a different session from the
  implementation and the macOS review, same provider; not cross-provider.
- Date: 2026-10-11. Reviewed `lab/app-health` at `f3262a7` (equal to origin;
  nothing fetched or fast-forwarded), corrections `f2e9fa4..73882c5`.
- Environment: Windows 10 Enterprise 10.0.19045 AMD64, `.venv` Python 3.13.11
  (code kept 3.10-compatible), two 1920x1080 monitors at 96 DPI (display scale
  1.0), 303 processes running. torch 2.13.0, torchvision 0.28.0, easyocr 1.7.2,
  kiwipiepy 0.23.2, PyQt6 / WebEngine 6.11, Pillow 12.3.0 (FreeType 2.14.3).
- CI: run 38122063816 at `f3262a7` passed all seven jobs, `native (windows)`
  included. CI runs `--suite portable` on Linux only, which is why the Windows
  portable failures below had never been seen.
- Status: **accepted for Windows with corrections**.

### Fixed now

Each regression test was shown failing on this machine before its correction.

- **Lab link and unreadable-folder tests never ran on Windows** (`f2e9fa4`).
  Portable at `f3262a7` had 4 failures: three tests created symbolic links
  (WinError 1314, no privilege) and one used `chmod(0)`, which leaves a Windows
  folder listable. A `link_directory` fixture adds a junction case on Windows,
  and `unreadable` denies the listing right through the folder's ACL; a
  symbolic-link case is skipped only when the privilege is missing.
- **The GC deletion walk deleted before it had read everything** (`9f5f693`).
  `_delete_tree` unlinked files from a lazy walk, so a junction or an unreadable
  folder appearing after revalidation was met only after shallower files were
  gone (shown on Windows with a real junction and a real ACL deny). It now reads
  the whole subtree first and refuses it whole. Nothing outside the subtree was
  ever touched, before or after.
- **A junction in the runs root was listed as a run** (`cbf755a`).
  `recorded_runs` and `storage._children` recognized links only with
  `Path.is_symlink`, so `report --list` and `lab storage` showed a run living
  elsewhere that `resolve_name` then refused. One `identity.is_link` (symbolic
  link or reparse point) is now used for listing, naming and revalidation. GC
  was already safe here ("outside the canonical runs root").
- **README claimed peak RSS is always available** (`73882c5`); it is `null` on
  Windows, which has no `resource` module.

### Commands and results

Evidence is under gitignored `artifacts/lab/`; scratch output is not kept.

- Gates at `73882c5`: `ruff check packages packaging tests tools lab` clean;
  `mypy packages packaging tests tools lab` no issues in 356 files;
  `pytest --suite portable` **2555 passed, 113 skipped** (at `f3262a7`: 4
  failed, 2547 passed, 107 skipped). Skips are platform-bound with stated
  reasons: 66 POSIX-tree cases, macOS frameworks, POSIX signals/locks, 6
  symbolic-link cases without the privilege, opt-in EasyOCR inference, and 13
  `test_synthetic_ocr` cases hard-wired to Apple SD Gothic Neo (see deferred).
- `pytest --suite native` at `cbf755a` (after the last code change): **1
  failed, 123 passed, 33 skipped**. The failure is
  `test_update_helper_windows.py::test_a_build_that_exits_without_answering_is_rolled_back_without_waiting`,
  reproduced 5/5 alone at 13.8-14.1 s against a 12.5 s bound; see deferred.
  The updater helper, its test and fixture are identical to `d05b8db`.
- Named regressions, alone and verbose: `test_lookup_process_spawn` passed
  (18.7 s; the earlier CI failure does not reproduce here with torch 2.13.0);
  `test_capture_prompt_shutdown` passed for both cases; the choice-list test
  passed with keyboard selection under a resting pointer (`on_demand`) and
  pointer selection after movement (`when_capture_starts`).
- `report --list` (3.4 s, 70 runs): stress, tour, check and `update_check`
  recognized; the 19 legacy `-windows-update` runs show commit and checkout
  `unknown` (their `source_commit` is the release's and is not taken as the
  recording commit) and sort first because their start is unknown.
- Baselines: `baseline set 20261003-202512-stress` was **refused** because that
  run was recorded from a dirty checkout; the checklist missed this. Registered
  with `--allow-dirty` as documented. A same-key run without `--replace`, a
  legacy update check, an interrupted tour and unset of an absent entry were
  each refused with nothing written; two baselines on one key (throwaway
  registry) are refused naming both. Registry now: `20261003-202512-stress`,
  `20261011-054710-stress`, `20261011-055144-tour`.
- `ocr-corpus --fonts`: 13 Hangul faces from `C:\Windows\Fonts` and the
  per-user font folder, collections by index (Batang/Gungsuh, Gulim/Dotum),
  Malgun Gothic Regular/Bold/Semilight, Noto Sans KR (variable, default
  instance "Thin"), Moirai One. `ocr-corpus-generate --profile smoke --seed 1`
  → 24 cases (8/8/8), 0 omitted, fingerprint `sha256:80c257dc7b924c6c`. Every
  pixel hash, size, truth flag and target re-checked from the PNGs, and a
  contact sheet showed each target on its word. A rerun and a different seed
  into the same folder were refused, the folder byte-identical.
- `20261011-054710-stress` (corpus, `--repeats 2`): clean at `cbf755a`, 48/48
  scored, 40 passed, 0/24 false presentations (0 timed out or errored), 8
  `ocr_misread` in 4 stable-wrong cases, dictionary answered all 16 selected
  targets, 0 cache hits, display scale 1.0, captured regions 200x100.
  Registered as baseline. `20261011-054819-stress --baseline` → comparable,
  correctness unchanged, 8 retained / 0 introduced / 0 resolved, 48 matched
  occurrences, popup p50 170.3 → 168.1 ms (n=48/48), lookup RSS 1065.6 → 1060.3
  MiB (n=77/75), all within bands; baseline byte-identical (SHA-256, 11 files).
- `20261011-054905-stress --per-family 14 --baseline 20261002-215759-stress` →
  235/249, 0/122 false presentations; comparable for correctness only
  (unchanged, 14 retained, 277 matched), performance "unavailable" with raw
  values and sample counts (legacy: no host, no protocol, display scale not
  recorded, dirty); legacy files byte-identical. An incompatible pair (corpus
  vs per-family) → `not_comparable` with reasons, raw only.
- Tours: `20261011-055144-tour` (22/24, baseline) and `-055208-tour --baseline`
  → comparable, unchanged, popup 119.5 → 117.4 ms (n=24/24), lookup RSS 1053.6
  → 1008.2 MiB (n=39/38). `-055312-tour`: pointer moved from another process
  after 14 s → "15/17 … stopped_by_user after 17 of 24 planned", exit 0,
  report written, no new Python, Hanly, WebEngine or Edge process left;
  `-055239-tour` (stopped before its first hover) is `stopped_by_user` and
  refused as a baseline. Rebuilding `-055208-tour --baseline -055144-tour` and
  the corpus pair left recordings and both baselines byte-identical.
- `ocr-campaign --compare-backends` (`e71ee6df-…`): requested `easyocr` only,
  Vision never requested; identical inputs, `cold_passes` labelled derived,
  0 errors, 20 stable correct / 4 stable wrong; peak RSS `null` on Windows.
- `check windows-update --from v0.9.0 --mode rollback`
  (`20261011-055508-windows-update`): passed; helper `prepared → applying →
  awaiting-startup → rolling-back → restored`, after 0.9.0, manifest matches;
  clean start and end source, `retained_logs` `profile/Hanly/logs/hanly.log`
  (in `logs/`), `disposable` exactly `install, release, profile, temp`. The
  everyday `%LOCALAPPDATA%\Hanly` was unchanged (7 files, times and sizes).
- `lab storage`: 4.64 GiB (runs 2.42 GiB, `dist/` packaging 2.15 GiB, 77.2 MiB
  legacy `artifacts/benchmarks`); no real reparse point exists under `dist/`
  or `artifacts/`, so junction handling rests on fixtures. `lab gc` inside the
  15-minute window kept everything ("active"); after it, the preview proposes
  exactly the update check's four subtrees (1.96 GiB) and
  `20261011-054905-stress/browser` (the lab's own 361-byte `lines.html`),
  nothing else. Plan `artifacts/lab/.gc-plan-ac783efa3c6e64ce.json` written;
  **not applied**.
- GC on throwaway fixtures (real junctions and ACLs): a junction inside or at a
  declared subtree, a junctioned run, a junctioned runs root, an ACL-denied
  folder and `REPLAY`/`Logs`/`LOGS`/`Frozen-2` declarations are all kept with a
  reason; the outside target was never touched.
- Privacy: no `selected`, `recognized`, `regions`, `queries` or `text` field in
  any `events.jsonl` recorded here; no image file in any new run.
- Not run: packaged checks (no correction touches frozen execution or
  packaging; `packages/` neither imports nor bundles `lab`).

### Deferred considerations

- **Windows updater rollback is slow on a busy desktop (product).** The helper
  restored correctly but took ~10 s after the rejected build exited:
  `Get-InstallProcesses` reads `.Path` for every process (2.56 s per walk with
  303 processes) and the rollback walks several times beside 3 s of fixed
  sleeps. The native bound (`TEST_READY_WAIT / 2`) fails here 5/5 and passes
  on CI. Not weakened. Revisit in updater work: measure a rollback with ~300
  processes, or filter by executable path before reading `.Path`.
- **Desktop and offline also diverge at display scale 1.0.** Desktop stable
  misreads `smoke-1-0003/0005/0006/0012`; offline EasyOCR fails `0003`, `0005`,
  `0012` and `0009` (target selection). So the Retina divergence is not only
  capture density. Revisit with that item, starting from
  `20261011-054710-stress` and `e71ee6df-…`.
- **`test_synthetic_ocr` never runs off macOS**: 13 cases require Apple SD
  Gothic Neo and say "no Korean-capable face is installed" on Windows. Revisit
  by choosing the face from discovery.
- **`session/runner.recorded_runs`** (pre-update) still accepts a linked run
  for the default newest report, and `windows_update._retain_logs` uses
  `rglob`, which can enter a junction inside `profile/` or `temp/`. Neither
  was observed. Revisit if a run or the app ever creates a junction there.
- **Report wording**: the corpus line counts all session captures (96 for 48
  hovers); an incompatible pair's heading says "both under" the current rule
  while the warning names both rules; a tour stopped before its first hover
  prints no closing line. Revisit with the next report change.
- Display-scale mismatch blocking is unit-tested only; this machine has one
  scale. Revisit on a mixed-scale machine if one becomes available.

### Remaining blockers

None for the Lab update. The native updater-helper timing failure on this
machine is a product finding, outside this update. Real GC application of
the plan above needs the human's separate approval.

## Next

Human decision: merge `lab/app-health`, approve (or not) applying
`.gc-plan-ac783efa3c6e64ce.json`, and schedule the deferred updater-rollback
timing investigation.
