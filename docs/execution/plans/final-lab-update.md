# Final Lab update — approved brief

**Status:** approved and in execution on `lab/app-health` from `d05b8db`. The live
state is in [`../checkpoints/final-lab-update.md`](../checkpoints/final-lab-update.md)
and the result in [`../review-handoffs/final-lab-update.md`](../review-handoffs/final-lab-update.md).
This file preserves the approved scope; once executed it is history.

Implement the approved final Hanly Lab update in six ordered waves. The
architecture, scope and wave structure are settled. This is Phase A:
implementation, proportional validation, logical commits and one Review Handoff.
Phase B is not authorized by this brief.

Done means the approved capabilities are implemented, applicable gates pass, real
Mac evidence is recorded where the environment permits, remaining Windows
validation is executable from the handoff, and the work stops at the Review
Handoff.

## Boundaries

Extend the existing primitives (session runner and `LabRecorder`, the external
sampler, tours and stress campaigns with ownership checks, OCR-only campaigns,
the synthetic generator with font hashes and glyph checks, corpus provenance,
tour/stress/OCR scoring, HTML/JSON reports with `summary.md`/`campaign.md`, fixed
checks and the Windows updater harness, memory-only Freeze and explicit Export).
Do not build parallel systems.

```text
run → observe → store → compare → explain
                         ↓
               protect evidence
                         ↓
           clean declared disposable data
```

Instrumentation stays under `lab/`. No public engine-contract change, shipped
runtime change or new dependency.

Excluded: React/Tauri or interface redesign; OCR tuning, new providers,
PaddleOCR or HanlyOCR; resolver, morphology or dictionary behaviour changes; new
product validation layers; direct-text redesign; capture threading, preloading
or process-topology changes; mixed-DPI fixes or unrelated updater redesign;
statistical frameworks, metadata databases or generic experiment frameworks;
duplicate AI-specific reports; whole-run retention or automatic `dist` cleanup.
Newly observed product defects are recorded with evidence, not fixed.

## Wave 1 — Identity, provenance and baseline foundation

- `lab/identity.py` with `run_identity(run_dir)`: run identity, kind, mode, start
  time; recording commit and dirty state; platform and architecture; configured
  versus observed OCR backend; relevant options/scenarios; corpus or plan
  fingerprint; scoring and measurement versions; completion and evidence
  availability. Layouts are recognized from contents, never from names or
  `schema_version: 1` alone: sessions, stress, checks, OCR campaigns, measurement
  campaigns, known update-check summaries. Unknown/manual material stays unknown;
  missing facts are `unknown`, irrelevant ones `not_applicable`; conflicting
  observations are reported.
- Writers gain additive provenance fields under a distinct provenance-version
  marker; historical artifacts are never rewritten. Source identity is captured
  at execution start; source changes during execution are recorded separately.
  No dirty-diff hash.
- Listing and resolution cover every kind without sending every kind through the
  session report builder.
- `lab/pins.py`: gitignored `artifacts/lab/pins.json` holding only run reference,
  role (`baseline`|`keep`) and reason. `lab baseline [set|unset]`, `lab pin`,
  `lab unpin`, `lab report --list [--kind]`. One active baseline per derived
  compatibility key; explicit registration and replacement; dirty registration
  needs `--allow-dirty`. `baseline unset <run>` removes only that registration,
  works for dangling entries, and is a clear non-success without mutation when
  absent. Incomplete legacy runs are protectable but never trusted automatic
  baselines.
- Exit: listings and identities are honest; baseline operations modify only the
  local registry.

## Wave 2 — Comparisons and compact explanations

- Pure helpers in `lab/comparison.py`, reusing `compare_tours`, `tour_summary`,
  `process_profile`, `build_report`, `build_campaign` and the Markdown renderers.
- Compatibility: `comparable | not_comparable | insufficient_evidence`, reasons,
  warnings, and eligibility for correctness / latency / memory. Checks mode,
  platform/architecture, observed backend, corpus/plan identity, rendered
  variants, rule, configuration, scenarios, completion and measurement protocol.
  Different commits are expected. Performance eligibility is stricter than
  correctness eligibility.
- Variant-aware occurrence matching replaces surface-only word matching. Stress
  baseline comparison keeps unscored, missing, partial and informational
  outcomes separate. Timeout/error negatives are not false presentations.
- Derived explanations beside the existing verdicts: correctness
  (`unchanged|improved|regressed|mixed|unavailable`), failure set
  (retained/introduced/resolved), process roles (`same|changed|unavailable`),
  performance (lower/higher/within indicative band/unavailable).
- One named heuristic policy: popup p50 `max(5% of baseline, 5 ms)`, sampled RSS
  `max(5% of baseline, 32 MiB)`. Not calibrated, not significance thresholds,
  not release gates. Raw values, deltas, sample counts and limitations stay
  primary.
- `--baseline <run>` preserved; bare `--baseline` selects the registered
  compatible baseline; stress gains baseline support. Incompatible pairs get
  explicitly labelled raw comparisons only.
- Compact reports gain provenance (clean/dirty/unknown), configured and observed
  backend, recorded versus current rule, baseline/compatibility/coverage, a
  reproduction command when safely reconstructible or the missing prerequisites,
  introduced/resolved failures and eligible resource changes. Recording, replay
  and rebuild code identities are distinguished; a command with placeholders is
  never called exact.
- Exit: baseline files byte-identical after rebuild/compare; interpretation never
  mutates recorded evidence.

## Wave 3 — Storage inventory and conservative GC

- `lab/storage.py`: read-only inventory of `artifacts/lab/runs`,
  `artifacts/lab/corpus`, other `artifacts/lab` material, legacy benchmark
  artifacts and `dist`, separating Lab-owned, packaging-owned and unknown/manual
  material, with size, ownership, activity and protection.
- `lab storage [--json]`, `lab gc` (preview), `lab gc --apply --plan <plan>`
  consuming the exact preview plan.
- Only current-writer-declared disposable subtrees under the canonical runs root
  are eligible, after the logs/results needed to understand the run are kept.
  Run roots, metadata, recordings, measurements, process samples, summaries,
  reports, frozen exports, replay inputs/results, retained corpus evidence,
  unknown/manual, active, pinned or ambiguous material are preserved. Pinned
  runs are excluded.
- Containment and redirected-root rejection; no symlink/reparse traversal;
  ownership and filesystem identity revalidated before deletion; stale-plan and
  newly-active refusal; explicit interrupted/partial results; fail closed.
- Apply is tested on disposable fixtures only; real artifacts get inventory and
  dry run only, unless separately approved.

## Wave 4 — Expanded controlled-image corpus

- Versioned extension of the corpus schema with explicit truth: text present or
  intentionally absent, Korean present or absent, exact target surface or a
  target that should hold no Korean, complete or missing region annotation.
  Schema 1 keeps loading.
- Reproducible generation identity: seed, generator version, font-file hash,
  face/weight, collection index, renderer version, text, layout, spacing,
  colours, target geometry, scaling/antialiasing/compression/blur/noise and the
  final image hash.
- Local font discovery including Windows locations; no downloads, substitutions
  or installations; missing fonts/glyphs are reported omissions. Unknown
  licensing stays local-only. Post-render resizing is distinguished from
  supersampled rendering.
- `ocr-corpus-generate` gains named profiles, seed and case/output budgets;
  `ocr-corpus` gains a font inventory. Golden recipes, balanced seeded samples,
  positive/negative/mixed families and targeted difficult combinations; no
  unrestricted Cartesian product. Japanese/Chinese/emoji only with verified
  glyphs. Broad output defaults to gitignored local storage.

## Wave 5 — Stage evidence, repetition and backend differential

- **5A** Controlled stage metrics: exact target-surface correctness, detector
  response on known-empty inputs only where detector evidence exists, normalized
  OCR false-Hangul, false Korean target selection, false/stale presentation, and
  separate timeout/error/unavailable/unscored counts. Facts are observed true,
  observed false or unavailable; the first observed bad stage is attributed, not
  a root cause. Vision normalized regions are not detector internals. The actual
  resolver computation is used.
- **5B** Configurable repetitions with per-case counts; stability separate from
  correctness; incomplete repetitions and raw variation preserved.
- **5C** `lab stress --corpus <manifest> --repeats N` through the existing stress
  page/driver with ownership and correlation checks, under an explicit
  target-surface policy; a correct target with a dictionary miss is not an OCR
  error. `ocr-campaign` stays independent of morphology, dictionary and UI.
- **5D** `lab ocr-campaign --compare-backends` over identical input hashes in
  fresh processes, reporting shared versus backend-specific observations without
  choosing a winner. Production EasyOCR output is authoritative; staged
  inspection is replay. If 5D proves invasive, checkpoint after 5A–5C and stop.

## Wave 6 — Integration, documentation and Review Handoff

Integrate commands, report dispatch, identity, registry, comparisons, corpus
experiments and storage. Update the Lab README/help and code map, and add
concise matching guidance to `AGENTS.md` and `CLAUDE.md` (read compact summaries
first; verify provenance, baseline and comparability; inspect raw evidence only
when needed; reports can be rebuilt under newer rules). Run final gates and real
Mac checks, produce an executable Windows checklist, and stop at the Review
Handoff.

## Privacy

Ordinary tracing carries no recognized text or pixels; Freeze stays in memory;
private evidence reaches disk only through explicit Export under the gitignored
root. Controlled corpus truth is permitted; live readings follow the existing
ownership and retention rules (`--retain-fixture-text`, image retention).
Unverified hovers retain nothing read. Richer reports expose no legacy private
text or raw exception content. Replay labels are kept. The everyday profile is
never touched.

## Validation, commits and stop conditions

Focused checks at each dependency boundary; at convergence
`pytest --suite portable`, `--suite native`, ruff and mypy over
`packages packaging tests tools lab`. Commits are authorized on `lab/app-health`
with `feat|fix|chore|docs:` subjects, bullet bodies, the configured human author
and no AI attribution; no push, merge, tag, release or workflow dispatch. Stop for
the human only on scope/architecture conflict, missing authority, unexplained
blocking failure, unavailable environment, invasive 5D or session limits.
