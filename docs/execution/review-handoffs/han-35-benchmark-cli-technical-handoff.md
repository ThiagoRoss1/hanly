# HAN-35 Benchmark, Reconciliation, and CLI Technical Handoff

Date: 2026-08-23  
Issue: HAN-35  
Base revision: `24ed285bd8cc33390875917d602a3a8526e77128` (`v0.1.0`)  
Implementation status: **technical HAN-35 execution complete; pending
human/external evidence and separate Claude review**

## Scope completed

- Reconciled HAN-30 against the human-confirmed macOS/Linux/Windows Actions
  build result without treating builds as frozen runtime proof.
- Re-read all tracked handoffs/reports and normalized 51 deferred/future items
  into the five HAN-35 disposition classes.
- Added an isolated, production-independent benchmark package under
  `benchmarks/dev/` with durable metadata, append/flush JSONL recovery,
  p50/nearest-rank-p95 summaries, process CPU/RSS sampling, stage probes,
  package composition, real campaigns, hover-rate scenarios, and structured
  JSON/PNG/HTML diagnostics.
- Ran real Windows development campaigns for resident providers, ROI sizes,
  MKLDNN/thread variants, monitor enumeration/capture, 60-second idle behavior,
  hover dwell-to-visible Qt presentation, and controlled terminal SIGINT.
- Added the explicitly approved terminal workflow: `hanly run` selects the
  cursor monitor or a dragged single-monitor region, then starts the existing
  desktop composition with a session-only override. Cancellation is a no-op;
  normal `hanly-desktop`/`.exe` startup is unchanged. Windows frozen output
  includes `hanly.cmd`, and the Python distribution exposes a `hanly` console
  script.
- Applied no performance mutation. Evidence supports the existing 200x100 ROI
  default and `enable_mkldnn=false`; it does not support caching, thread-limit,
  callback-lock, backend, binding, or package-exclusion changes yet.

## Authoritative durable evidence

- `docs/execution/reports/han-35/inventory.md` — 51 final dispositions and
  source coverage.
- `docs/execution/reports/han-35/baseline.md` — HAN-30 reconciliation and exact
  missing human/frozen checklist.
- `docs/execution/reports/han-35/benchmark-protocol.md` — isolation, evidence,
  correctness, ROI/knob, invocation-rate, and perceived-latency rules.
- `docs/execution/reports/han-35/behavioral-matrix.md` — 181-test focused
  behavior campaign and evidence-class boundaries.
- `docs/execution/reports/han-35/results-and-decisions.md` — measurements,
  invalidated run, final decisions, and unfiled dedicated-issue drafts.

Raw generated evidence is intentionally gitignored under `artifacts/benchmarks/`.
Important run IDs are listed in `results-and-decisions.md`. Do not review the
old `a9a20637-...` total percentile as Hanly performance: per-stage `fsync`
perturbed it and the corrected run is `a3d8b6cc-...`.

## Main measured result

Corrected 192x48 resident baseline, 30 warm samples, 33/33 total correct:

| Stage | p50 | p95 |
| --- | ---: | ---: |
| OCR | 184.58 ms | 238.08 ms |
| Token selection | 0.04 ms | 0.06 ms |
| Morphology | 0.17 ms | 0.25 ms |
| Dictionary | 0.17 ms | 0.27 ms |
| Total pipeline | 185.39 ms | 238.84 ms |

Paddle construction was 8.815 s and lazy first Kiwi analysis 3.303 s; the same
resident provider set served every later sample. The development visible-hover
campaign constructed one worker, invoked lookup/OCR seven times, measured warm
event-to-popup-visible at 440.51 ms p50 / 675.03 ms p95, and measured popup
render itself at 0.14 ms p50. Frozen/compositor evidence remains absent.

## Production and packaging changes

- `packages/hanly-app/src/hanly_app/capture_selector.py`
- `packages/hanly-app/src/hanly_app/cli.py`
- `packages/hanly-app/src/hanly_app/application.py`
- `packages/hanly-app/pyproject.toml`
- `packaging/hanly.cmd`
- `packaging/hanly-desktop.spec`
- CLI/packaging READMEs and focused tests

The benchmark package is developer tooling, not a production dependency.
Root Ruff/mypy configuration now includes it so it cannot silently rot.

## Verification completed

```text
.venv\Scripts\python.exe -m pytest
409 passed in 44.90s

.venv\Scripts\python.exe -m ruff check benchmarks packages packaging tests tools
All checks passed!

.venv\Scripts\python.exe -m mypy benchmarks packages packaging tests tools
Success: no issues found in 110 source files

.venv\Scripts\python.exe tools\build_package.py --platform windows --dry-run
C:\Hanly\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean ...
```

Additional real evidence:

- 33/33 corrected baseline and all ROI/thread successful variants returned the
  expected Korean result.
- MKLDNN=true returned 13/13 normalized errors with the retained oneDNN
  unsupported-attribute diagnostic; no misleading latency conclusion was made.
- 100 monitor enumerations and 30 real small ROI captures completed; no pixels
  were retained by that campaign.
- 60-second resident idle trace completed with zero observed CPU and −64 KiB
  RSS delta.
- Controlled real-terminal Ctrl+C exited promptly (1.17 s, status 1, no
  traceback); frozen/zero-status semantics remain open.
- `git diff --check` passed apart from Git's expected LF/CRLF notices.

No commit, push, merge, tag, workflow dispatch, release, or Linear mutation was
performed. The pre-existing untracked `.claude/` directory was not touched.

## Separate Claude review focus

1. Verify the benchmark ledger does not let instrumentation contaminate the
   corrected totals and that evidence classes/invalidated runs remain honest.
2. Review nullable diagnostic serialization and ROI coordinate rendering for
   invented facts or source mutation.
3. Review `hanly run` for Qt-before-Paddle ordering, cancellation, virtual
   desktop/negative coordinates, single-monitor containment, session-only
   override, update-runtime rebuild behavior, and unchanged normal startup.
4. Verify `hanly.cmd` lands at the Windows onedir root in a fresh real build;
   static spec tests and dry-run passed, but this edited package was not rebuilt.
5. Challenge the no-performance-change decisions, especially same-word cache,
   monitor caching, thread limits, callback lock scope, and dependency
   exclusions, against the actual evidence rather than expected wins.
6. Confirm the 51-row final inventory has exactly one allowed disposition each
   and no missing source handoff.

## Human/external evidence still required

### Live interactive HAN-35 addendum

The live benchmark command, optional production trace seam, bounded recorder,
resource sampler, phase marker, privacy adapter, and summary generator are now
implemented for the next human evidence pass:

```powershell
python -m benchmarks.dev live-hover `
  --config resources/dev/runtime-local.json `
  --duration 300
```

This command must be run manually from the Windows development environment
with the real desktop visible. The ready message begins `idle`; the operator
then uses the default `Ctrl+Alt+Shift+B` chord to advance through empty areas,
non-Korean text, repeated same Korean word, several Korean words, stationary
changing content, fast movement, and normal game/browser use. Spend roughly
10--30 seconds in each phase and leave the marker as analysis metadata only.
The real command was deliberately not run by this implementation pass; only
parser, queue/writer, sampler, marker, privacy, correlation, summary, and
cleanup behavior received deterministic validation.

The live evidence boundary is explicit: the default trace retains no pixels,
screenshots, raw OCR text, headwords, window titles, or application names. It
retains geometry, a session-keyed ROI digest, character-class counts, Hangul
presence, confidence, status, and dictionary hit/miss. `--retain-text` is an
opt-in privacy change. The baseline does not poll stationary-cursor screen
changes, so content changing under an unmoved cursor should not trigger a new
capture/OCR event; this is recorded, not optimized during HAN-35.

The live report must correlate monotonic events for dwell, capture, OCR,
token selection, morphology, dictionary, and popup-visible delivery, while
also retaining CPU/RSS, idle baseline, queue/pending/replaced/stale/cancelled
work, repeated-region observations, Hangul/non-Hangul outcomes, and dictionary
hits/misses. It remains development-runtime evidence from one machine and does
not prove frozen, low-end, cross-platform, corpus-accuracy, or SLA behavior.
The Paddle audit remains measurement-only: current detector + Korean
recognizer, resident construction/first-use/subsequent timings, and controlled
MKLDNN/thread variants are recorded before any future optimization decision.

The disabled path passes no sink and constructs no trace wrappers. The enabled
path emits monotonic, request-correlated primitive events from hover,
controller, latest-wins executor, stage wrappers, and Qt popup visibility.
Runtime packages never import `benchmarks.dev`; disk writes, process sampling,
phase control, redaction, digesting, and summary generation remain benchmark
owned. A bounded queue drop loses evidence rather than delaying hover work.

The exact 13-step checklist remains in `baseline.md`. Highest-priority items:

- Fresh Windows frozen build: confirm `hanly.cmd`, `hanly run` selection/cancel,
  normal `.exe` launch, provisioning, visible startup failure, tray, Control
  Center, OCR, manual/hover popup, offline repeat launch, SQLite replacement,
  and terminal SIGINT/exit status.
- Actual macOS and Linux/X11/Wayland frozen runtime, permissions, capture,
  hotkeys, tray, DPI, selector, and popup smoke tests.
- Production release resources and production-sized KRDICT timing.
- Final artifact/manifest/checksum/release-flow inspection before publication.

Do not mark HAN-30, HAN-31, HAN-32, or HAN-35 Done from this handoff alone.
