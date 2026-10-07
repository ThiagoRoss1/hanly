# Final Lab update Review Handoff

## Bundle

- Member work: the approved final Lab update ([brief](../plans/final-lab-update.md)),
  Waves 1–6, plus the requested removal of `# pragma` / `type: ignore`
  suppressions from `lab/`.
- Implementation ecosystem: Claude Code (Opus 5.5) on macOS 26 (Darwin 25.6.0,
  arm64), `.venv` Python 3.13.11 (code kept 3.10-compatible).
- Branch `lab/app-health`, from `d05b8db` to `7236dc6` plus this handoff.
- Date: 2026-10-07. Phase B has not started. Nothing was pushed, merged, tagged
  or released.

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

Human-selected after implementation. Not started.
