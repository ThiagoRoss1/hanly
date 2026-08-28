# HAN-35 Benchmark and Diagnostic Protocol

Date: 2026-08-23  
Status: Phase A protocol; no performance conclusion yet.

## Isolation

- Tooling lives under `benchmarks/dev/` and is never imported by normal
  `hanly` or `hanly-app` runtime modules.
- Raw/transient evidence lives under gitignored
  `artifacts/benchmarks/runs/<run-id>/`.
- Durable conclusions live under `docs/execution/reports/han-35/`.
- The diagnostic UI is developer-only and launched only by the benchmark
  command. Normal application startup remains unchanged.
- Existing capture, provider, resolver, controller, hover, and presentation
  seams are observed or wrapped; the tooling does not replace Hanly behavior
  with a parallel algorithm.

## Per-run contract

Every run directory must retain:

```text
metadata.json       environment, commit, versions, config, scenario
measurements.jsonl  one flushed record per sample/stage
stdout.log          human-readable runner output
process.csv         timestamped CPU/RSS samples when process observation runs
diagnostic.json     latest structured correctness/diagnostic snapshot, when used
diagnostic.png      annotated ROI/OCR geometry, when used
diagnostic.html     visual inspector, when used
```

A partial failure must leave valid metadata and every sample written before the
failure. JSONL records include a schema version, run id, timestamp, evidence
class, scenario, stage, iteration, condition (`cold`, `warmup`, or `warm`),
duration, correctness status, and optional RSS/CPU/result fields.

## Quantitative rules

- Use `perf_counter_ns()` for durations.
- Flush each raw sample immediately.
- Warm-up samples are retained and excluded from warm percentiles by an
  explicit `condition`, never silently deleted.
- Report sample count, median/p50, and p95 for repeated measurements; retain
  min/max/mean as supplements.
- Nearest-rank p95 is used and documented; no interpolation ambiguity.
- Outliers remain in raw data and are annotated, not removed.
- Every reported value is labelled **measured**, **derived**, or **estimated**.
- Results from different commits, runtimes, machines, or power modes are not
  merged into one percentile set.

## Correctness gate

A timed lookup is valid only when its record confirms the expected evidence
available for that scenario: ROI/target containment, OCR region/text,
selected region/span, lemma/key, dictionary status, request currency, and no
stale result. Incorrect or stale results remain recorded but are excluded from
successful-latency summaries.

## Campaigns

1. **Framework self-test:** run-ledger append/recovery, metadata validation,
   percentile aggregation, package grouping, and diagnostic serialization.
2. **Stage benchmark:** capture, OCR, morphology, dictionary, total pipeline,
   and controller delivery using real providers/resources where available.
3. **Cold/warm application benchmark:** process startup, first provider
   initialization/lookup, repeated lookup, popup dispatch, and teardown.
4. **Idle/repeated observation:** choose and record an observation window long
   enough to reveal CPU drift, RSS growth, reinitialization, and duplicate work;
   start with 60 seconds idle and at least 30 repeated lookups, then extend if
   the trace has not stabilized.
5. **Hover campaign:** dwell, jitter, duplicate suppression, enumeration cost,
   latest-wins, cancellation, rapid movement, boundaries, popup interaction,
   idle/background CPU, and failure recovery. Count actual OCR invocations and
   attempted/delivered lookups separately during idle, small cursor jitter,
   movement across text, repeated hover over the same word, and movement across
   non-text regions. Report counts with observation duration and movement/stable
   event counts; do not infer an invocation rate from latency samples.
6. **Package composition:** exact top-level and dependency-family size groups,
   duplicate hashes/destinations, collected distributions, models/resources,
   package ZIP, and PyInstaller warnings. No exclusion recommendation without a
   runtime-necessity check.
7. **Behavioral matrix:** normal/edge/punctuation/spacing/multi-token/unknown/
   OCR-failure/rapid/shutdown/resource/offline scenarios. Platform-only cases
   remain unavailable rather than passed.
8. **ROI sensitivity:** compare a small set of practical ROI dimensions on the
   same retained inputs. Record total/stage latency, recognized regions/text,
   selected span, lemma/key/status, and whether the target remains correctly
   located. Padding/cropping transformations belong in scenario metadata so a
   size comparison is not misreported as an OCR-accuracy corpus.
9. **Resident-provider and CPU variants:** split provider construction, first
   inference, warm-up, and subsequent inference. Verify construction count so a
   warm result cannot conceal repeated Paddle/provider initialization. Run
   `enable_mkldnn` and reasonable CPU-thread limits as isolated, metadata-labelled
   processes on the same input. A failed or slower variant remains evidence; no
   knob is preferred before measurement.

10. **Live interactive session:** run the real development hover composition for
    120--300 seconds while the operator advances the scenario marker. This is
    the only campaign that measures ordinary desktop input and the complete
    user-visible path; fixture and synthetic campaigns must not be described as
    substitutes for it.

## Live interactive run (human-only)

The implementation-ready command is:

```powershell
python -m benchmarks.dev live-hover `
  --config resources/dev/runtime-local.json `
  --duration 300
```

Run it from the repository root in the development environment that has the
real Paddle models/resources. The command creates a new run directory under
`artifacts/benchmarks/runs/<run-id>/`, starts the resident provider composition and
the visible development popup, then records until the duration expires. The
default global marker is `Ctrl+Alt+Shift+B`; use `--marker-hotkey` only when
that chord is unavailable. `--retain-text` is opt-in and should normally be
omitted.

Before starting, open representative content without covering it with the
terminal: a blank/desktop area, non-Korean text, Korean text with one word and
several words, an image, and a normal browser/game view. Do not move the mouse
until the command reports that the session is ready. The ready message starts
the `idle` phase. Spend approximately 10--30 seconds in it, then press the
marker once to advance between each remaining phase:

1. **idle (automatic first phase):** leave the cursor still in an empty area;
2. **empty:** move normally over empty/non-text areas;
3. **non-Korean:** move across Latin text or other non-Hangul text;
4. **same-word:** settle repeatedly on one Korean word, moving away and back;
5. **Korean sequence:** move across several Korean words in sequence;
6. **stationary-changing:** keep the cursor still while the underlying page,
   video, game, or animation changes;
7. **fast movement:** sweep quickly across content and empty areas;
8. **normal use:** use the browser/game normally, including short pauses.

The marker is a label for analysis only; it does not alter hover behavior. If a
phase cannot be performed, mark it anyway and note the reason in the run log.
Stop early with `Ctrl+C` only if necessary; the recorder must still finalize
metadata, process samples, trace events, and summary output.

The baseline intentionally has **no production polling for stationary-cursor
screen changes**. Therefore the stationary-changing phase is expected to show
no new capture/OCR solely because pixels changed beneath an unchanged cursor.
That is a measured baseline, not a claim that screen-change awareness is
impossible or a recommendation to add it in this task.

The live report must retain, at minimum, session duration, phase durations,
hover opportunities, capture/OCR counts and rates, capture/OCR/selection/
morphology/dictionary/popup-visible timings, full dwell-to-popup latency,
duplicate/repeated-region observations, queued/replaced/stale/cancelled work,
Hangul and non-Hangul outcomes, dictionary hits/misses, and idle CPU/RSS. All
raw events use monotonic high-resolution timestamps and remain labelled
measured; p50/p95 summaries are derived from those events.

The run directory contains `metadata.json`, append-only `live-events.jsonl`,
`process.csv`, derived `summary.json`, and `stdout.log`. Runtime callbacks only
perform primitive classification/correlation and bounded `put_nowait` queueing.
ROI bytes are handed by immutable reference to a separate bounded digest
thread; only the keyed digest and geometry reach the event file. Queue drops,
digest drops, write errors, and incomplete cleanup are explicit summary fields.

## Live privacy and evidence limits

The default live trace does not retain screenshots, pixels, raw OCR text,
headwords, window titles, or application names. It records geometry and a
session-keyed ROI digest for repeated-region analysis, plus character-class
counts, Hangul presence, confidence, status, and dictionary hit/miss. The
digest is not a reversible screenshot and is only comparable within that run.
`--retain-text` explicitly changes that privacy boundary and should be used
only on private content.

The live run is development-runtime evidence from one operator, machine, power
mode, display setup, and content mix. It does not prove low-end CPU behavior,
frozen-package behavior, cross-platform behavior, OCR corpus accuracy, or a
performance SLA. It also measures the current call path rather than proving
that every Paddle/PaddleX component is necessary. Any optimization decision
requires a later controlled comparison with correctness evidence.

## Paddle call-path audit boundary

The current CPU path is resident PaddleOCR text detection followed by Korean
recognition, with document preprocessing and line orientation disabled by the
runtime configuration. The current ROI contract does not provide trusted text
boxes, so recognition-only execution is not equivalent without changing the
capture/provider contract. The live trace should therefore measure the
existing detector and recognizer path, provider construction count, first-use
latency, subsequent latency, and configured CPU knobs (`enable_mkldnn` and
thread limits) as metadata-labelled variants. No backend replacement,
fine-tuning, or unmeasured detector/recognizer removal is part of HAN-35.

## Perceived hover latency

In addition to the provider/stage records, each end-to-end hover sample retains
one correlated trace:

```text
dwell -> capture -> OCR -> token selection -> dictionary lookup -> popup visible
```

The total begins at the cursor event that starts the final stability interval
and ends only when the popup sink reports visibility. Records include both the
configured dwell and its observed duration. Worker completion or result
dispatch alone is not labelled popup-visible latency. If a UI/frozen popup
cannot be observed, report the nearest available endpoint by name and mark the
popup-visible value unavailable rather than estimating it.

## Diagnostic view

The developer view must expose, when available:

- cursor, monitor, screen rectangle, capture ROI and ROI-local target;
- hover radius/dwell/pending/active state;
- OCR quads, selected region, text and confidence;
- morphology tokens/offsets, selected span, lemma and dictionary key/status;
- per-stage timing and active providers/resources;
- controller request id/currentness, cancellation/latest-wins, stale/current
  delivery, fallback and error state.

The annotated ROI is the primary correctness surface: target marker and OCR
quads are drawn in ROI coordinates, with the selected region visually distinct.
The HTML/PyQt inspector presents the full structured snapshot. Fields that the
current provider contract cannot supply are shown as unavailable, not invented.

## Environment limitations for this campaign

- Available: Windows 10, Python 3.13 development runtime, real local PaddleOCR,
  Kiwi, KRDICT, MSS, pynput, PyQt6, pywebview, and a local static PyInstaller
  tree.
- Not available: low-end comparison hardware, macOS, Linux desktop/Wayland,
  current frozen Actions artifacts, final production resources, release assets,
  and a Meikipop installation.
- Low-end results may be estimated only from clearly labelled constrained runs;
  they are not presented as actual low-end hardware measurements.
