# Hanly Lab

The developer lab: run the real Hanly under observation, let the lab drive it,
and read a visual report of exactly what every process did. It also keeps the
measurement campaigns and regression checks that used to live in `benchmarks/`.

Nothing here ships: neither `hanly` nor `hanly_app` imports this package, and it
is not part of either distribution.

## Setup

Install the desktop as described in the root `README.md`, then add the `dev`
extra on top of it:

```bash
python -m pip install -e "packages/hanly-app[dev]"
```

That extra adds Pillow for image campaigns and psutil for process sampling. It
must come *after* `packages/hanly` is installed — `hanly-app` depends on
`hanly==1.0.0`, which exists only in this checkout. Every command runs from the
repository root.

## The three commands

```bash
python -m lab                 # run Hanly; you use it, quit it, the report opens
python -m lab tour            # the lab uses Hanly itself and scores every answer
python -m lab report          # reopen the newest report
```

Everything else is optional. `python -m lab report --list` shows every recorded
run of every kind, and `python -m lab report <run-name>` reopens one.

### `python -m lab` (`run`) — you drive

Starts the real desktop through `run_desktop`, the same composition `hanly`
uses, with the lab's recorder as its trace sink. The lookup engine and the
Control Center are still the real spawned children. Use Hanly normally; quit
from the tray or with Ctrl+C, or pass `--duration SECONDS`. `--hud` also draws
the on-screen HUD. Production tracing sends no recognized text to a sink that
does not ask for it, and this mode does not ask.

### `python -m lab tour` — the lab drives

Covers the screen with lab-authored Korean, presses the real capture shortcut,
glides the real pointer onto each word, and waits for the app's own trace to say
how that hover ended. Every target has a known answer:

- the **story** (`fixtures/minibook`): prose with hand-set dictionary forms,
  conjugations, particles, and Latin words that must be refused;
- **words**: KRDICT headwords with an English translation (the provider answers
  in English, so an entry without one has nothing to expect), sampled with
  seed 7 and painted at 16, 22, 30 and 40 px across three themes and the
  installed Korean typefaces.

The plain command is the **standard tour**: the whole story and 300 words, about
three and a half minutes. Tours with the same settings are comparable;
`--baseline <earlier-run>` adds a before/after table to the new report.
`--quick` is a 40-second smoke run (24 words, no story); `--words`,
`--story-sizes`, `--word-sizes` and `--seed` change the corpus, which makes a run
incomparable with the standard one.

Text is painted, so each hover exercises capture and OCR. **Move the mouse
yourself to stop the tour.** It checks before starting that Screen Recording and
Accessibility (to move the pointer) are granted to the terminal and that the
capture shortcut is bound, and says what to change if not.

#### Scoring

Rule `strict-headword-v3` (`session/scoring.py`): a hover is **correct** when the
lookup bound to that hover finished -- the app made its popup decision before
the driver's deadline -- and the dictionary form it answered with equals the
hand-set expected form. A must-refuse target is **refused** only when its lookup
finished and deliberately declined. A timeout (`timed_out`), a processing error
or a missing result is never a refusal or a pass, whatever partial result it
carried. `ambiguous_surface` marks an answer that is a valid reading of the
exact surface without sentence context (드릴); it counts as a failure but is
labelled apart. Hovers the lab could not attribute to its own page are **not
scored** and are reported, never folded into either side. The score is on this
controlled corpus; it is not general OCR or translation accuracy, and it does
not judge every definition shown.

A report always re-scores under the current rule and shows any verdict that
differs from the one recorded at the time. Scoring needs no stored text: each
result keeps text-free facts (did the answer match, was the surface read, was
the selection the target word), from which every rule since v2 is computed.

#### What is saved, and what is not

- **No recognized text or pixels in a session you drive.** Production tracing
  sends evidence only to a sink that asks for it, and `python -m lab` does not.
- **`events.jsonl` never holds a raw evidence or OCR-geometry field**, in any
  mode. A tour's driver reads that evidence in memory only.
- **A tour result keeps the target's own corpus text** (the story's surface and
  expected form, or the KRDICT headword it sampled) and **structural facts**:
  verdict, status, timings, counts of regions and dictionary queries, and the
  text-free facts above. What the hover *read* -- the selected word, the answer,
  the recognized regions and the dictionary queries -- is not saved.
- **`--retain-fixture-text` saves what was read**, and only for verified hovers
  over the lab's own page, so a failure can be studied word by word. The choice
  is recorded in the run's `metadata.json`, and reports show read text only for
  such a run. This is retention of lab-authored fixture text; it is not the
  private-screen Export below, and it never applies to a session you drive.
- **Diagnostics** mirrored into the timeline keep their text only for
  informational lifecycle lines (startup, Control Center, lookup engine,
  cleanup, capture, updates, resources); any other line keeps its subsystem and
  level only. The run profile's own session log behaves as `hanly`'s does.
- **Private screen content** reaches disk only through `live-hover`'s explicit
  Export, under the gitignored `artifacts/lab/runs/`; Freeze stays in memory.

How a tour decides a hover is its own: the answer is bound to the hover that
fired after the pointer arrived and the lookup that hover submitted, so a stale
or neighbouring lookup cannot answer it. Before the hover and again after the
answer, the driver asks the window server who owns a grid of points over the
capture region; a foreign or unknown owner, or a captured region larger than the
probed one, makes the hover not scored and keeps nothing it read. That is a
sampled check at two moments, not proof of every pixel or of the time in
between, and it fails closed where attribution is impossible (always, on Linux).
Recordings made before this policy can still hold read text; rebuilding their
reports no longer shows it.

### `python -m lab stress` — the text-acquisition stress campaign

A seeded plan (`--seed`, default 11) of 1,158 hovers whose expectations are set
before anything runs (`session/stress.py`): KRDICT headwords across the installed
Korean faces, five sizes and four themes; the story at two sizes; cursor at the
beginning, middle and end; dense and mixed Latin/Korean lines; degraded raster
images; negatives (blank, numbers, punctuation, Latin, icons, illustrations, the
spot the previous popup occupied); repeats; rapid sweeps; leaving right after the
lookup was submitted; content changing under a still pointer; a covering foreign
window; and real accessible text read through UI Automation in an isolated
InPrivate Edge window (Windows), whose points are checked to be page content.

Rule `stress-v1` (`session/stress_scoring.py`): positives keep the tour's rule; a
negative passes only when no answer was presented; an answer shown after the app
dropped its lookup is `stale_popup`, and one shown after the pointer deliberately
left is `late_popup`. Each failure names the stage it points at. The run writes
`campaign.html`, `.md` and `.json` beside the usual report. `--per-family N` is a
short check; `--retain-fixture-images` keeps the region a failing verified hover
captured, re-grabbed from the lab's own page, and `python -m lab stress-replay
<run>` feeds those through the production lookup worker, labelled as a lab
re-capture replay.

`--corpus <manifest> --repeats N` hovers a controlled-image corpus (below)
instead of the seeded plan: each image is painted pixel for pixel on the lab's
page, one per row, and hovered at its annotated point in N rounds, under the
same ownership checks. Rule `corpus-surface-v1` judges these: a surface target
passes when the selected word is the target, whatever the dictionary then
answered (reported apart as the language outcome); a no-Korean target passes
only when nothing was presented. `campaign.md` adds desktop stage facts and
each case's stability over the rounds. A repeat may be answered from the
lookup cache; `cache_hits` per hover says when. Negatives that time out or
error are counted apart from false presentations.

### What a run records and reports

Each run gets its own directory under gitignored `artifacts/lab/runs/` with its
own profile (`profile/`, so settings and logs never touch your everyday
profile; the runtime configuration, dictionary and models are reused read-only):

| File | |
|---|---|
| `events.jsonl` | every trace event from the shell and the lookup child (content fields removed), startup phases, lifecycle diagnostics, and the lab's own driver events, including each tour result as described above |
| `processes.jsonl` | memory, CPU and threads of the shell, `hanly-lookup`, `hanly-control-center` and their helpers every 250 ms, sampled from a separate process so it cannot stall the shell; roles are exact, not inferred |
| `report.html` | the visual report: findings, system map, where time goes, funnel, timeline, hover explorer, tour accuracy, startup, processes |
| `report.json`, `summary.md` | the same model for scripts and agents |

The report rebuilds from the recorded files at any time and never writes beside
a baseline it compares with. Its findings name the code where each cost lives;
they are derived from the run, not hand-written.

Measurement limits: child timestamps share the shell's clock (`perf_counter`
is system-wide on every supported OS). RSS is resident, not private, memory and
is sampled, so short spikes can be missed. The shell's numbers include the lab
recorder hosted in the same process.

## Evidence: identity, baselines, comparison, storage

Read a run's compact summary first: `summary.md` (sessions) or `campaign.md`
(stress). Each opens with **Provenance**: recording commit and whether the
checkout was clean, dirty or unknown when the run *started*, configured and
observed OCR backend, the rule recorded and the rule shown, how the run ended,
the code that rebuilt the report, and a reproduction command marked exact only
when nothing in it is unresolved. `report.json` is the full model (megabytes);
open it, or `events.jsonl`, only when the summary is not enough. Reports are
rebuilt under the current rules; recorded evidence is never rewritten.

```bash
python -m lab report --list [--kind tour|stress|check|ocr_campaign|...]
python -m lab baseline                       # registered baselines
python -m lab baseline set <run> --reason "..." [--replace] [--allow-dirty]
python -m lab baseline unset <run>
python -m lab pin <run> --reason "..."       # keep any run out of clean-up
python -m lab unpin <run>
python -m lab tour --baseline                # compare with the registered baseline
python -m lab report <run> --baseline <other-run>
python -m lab storage [--json]
python -m lab gc                             # preview; deletes nothing
python -m lab gc --apply --plan <the plan the preview wrote>
```

**Identity** (`identity.py`) recognizes every run from its contents (session,
stress, check set, OCR campaign, backend differential, measurement campaign,
update check) and leaves anything else `unknown`. Every writer adds a
`lab_provenance` block (version 1): start-time source, a separate end-of-run
reading when the checkout changed during the run, platform, host (OS release,
CPU count, memory), the measurement protocol and, where it has any, the working
subtrees it declares disposable. Runs recorded before the block say their
source was read at shutdown.

**Baselines** live in the gitignored `artifacts/lab/pins.json`, which holds
only run names, roles (`baseline` or `keep`) and reasons; everything else is
read from the run. One baseline is active per compatibility key (kind,
platform and architecture, observed backend, and the options that decide what
is hovered). A baseline must have finished, with a known commit, checkout state
and backend; a dirty one needs `--allow-dirty`. Anything can still be kept with
`pin`.

**Comparison** (`comparison.py`) first decides compatibility: `comparable`,
`not_comparable` or `insufficient_evidence`, with reasons. Different commits
never block it. Occurrences are matched by target *and* rendering (face, size,
theme). Correctness needs the same kind, platform, backend, options and
rendered plan; latency and memory also need both runs finished under one known
measurement protocol on an identical host description, so runs recorded before
provenance compare correctness only. An incompatible pair is shown as a raw
comparison only. Otherwise the summary adds fixed explanations beside the raw
numbers: correctness (`unchanged|improved|regressed|mixed|unavailable`), the
failure set (retained, introduced, resolved), process roles, and performance
under the named policy `indicative-bands-v1`:

| measure | band |
|---|---|
| popup p50 | max(5 % of the baseline, 5 ms) |
| sampled peak RSS per role | max(5 % of the baseline, 32 MiB) |

These bands are not calibrated against Hanly's run-to-run variance, not
significance tests and not release gates; they only label a raw delta, and
repeatability evidence may change them. Two identical quick Mac tours already
differed by 92 MiB of sampled lookup RSS.

**Storage** reports `artifacts/lab` and `dist/` by owner: the Lab (a writer it
recognizes), packaging (names `tools/build_package.py` writes) or unknown.
`gc` only ever proposes subtrees a run's own writer declared disposable after
keeping what explains the run: an update check's `install/`, `release/`,
`profile/` and `temp/` once their logs are copied to `logs/`, and a stress run's
`browser/`. It never touches a run root, recordings, reports, replay material,
frozen exports, a pinned, active, unfinished or unrecognized run, or `dist/`.
`--apply` deletes exactly the saved preview after re-checking eligibility,
directory identity and contents; one stale target refuses the whole plan, and a
deletion stopped midway reports what was deleted, what was partial and what was
never attempted.

## `check` — fixed regression scenarios

`python -m lab check list`, then `python -m lab check run --scenario ID`
(repeat the flag). These orchestrate fixed repository tests on disposable
profiles — startup, Control Center, settings, updater and packaged checks — and
label real and simulated evidence separately. See [checks/README.md](checks/README.md).
On macOS, `BUNDLE-LAUNCH-IDENTITY` launches a frozen bundle through LaunchServices
on an isolated profile and checks that only the shell is ever a Dock application
(`--bundle PATH --expected-commit FULL_SHA`). Updater checks use simulated builds;
none of them proves a complete real-release update.

---

## `dev-hud` — run Hanly with the on-screen HUD

**This is the one to reach for.** It starts the *real* desktop — same
composition, same providers, same hover behaviour — with a panel drawn on top
showing what each hover actually did: the stage timeline (dwell, capture, OCR,
token selection, morphology, dictionary), OCR hit rate, worker readiness, and
process resources. A second overlay outlines the region that was captured.

```powershell
python -m lab dev-hud
```

That uses your normal per-user configuration, exactly like `hanly`. To run it
against an explicit one instead:

```powershell
python -m lab dev-hud --config resources/dev/runtime-local.json
```

| Flag | |
|---|---|
| `--config PATH` | explicit runtime configuration; omit for the normal per-user one |
| `--app-config PATH` | explicit preferences file |
| `--roi-size WxH` | capture region size, for comparing detection areas |
| `--dwell-ms N` | the dwell the panel labels its timeline with (display only) |
| `--no-roi` | show only the panel, without the captured-region outline |

Both overlays are transparent to mouse input, so they cannot change the
behaviour they report. The panel is deliberately **opaque**: Windows refuses to
exclude a layered window from screen capture, and a see-through overlay would
feed its own pixels back into the OCR it is reporting on. For the same reason
the ROI outline is drawn strictly *outside* the captured region.

Close it from the tray, like the normal desktop.

---

## Measurement campaigns

These record evidence rather than draw it. Each writes metadata, flushed JSONL
measurements, process samples, summaries, and — where the input supports it —
structured/PNG/HTML diagnostics, under `artifacts/lab/runs/<run-id>/`.

```powershell
# Real resident providers: first inference, warm-ups, and 30 warm samples.
python -m lab real-lookup `
  --image tests/hanly_fixtures/assets/korean_reading_roi.png `
  --config resources/dev/runtime-local.json `
  --target-x 100 --target-y 24 --roi-size 192x48

# Dwell through an actually visible Qt popup.
python -m lab real-hover `
  --image tests/hanly_fixtures/assets/korean_reading_roi.png `
  --config resources/dev/runtime-local.json `
  --target-x 100 --target-y 24 --roi-size 192x48

# OCR invocation opportunities by hover condition. Deterministic, no hardware.
python -m lab hover-rate

# Real monitor enumeration and ROI capture. Retains no screen pixels.
python -m lab desktop-capture

# Exact composition of a frozen build tree.
python -m lab package `
  --root dist/windows/hanly-desktop `
  --output artifacts/lab/package-composition.json
```

A committed Korean fixture is correctness-regression evidence, not an OCR
accuracy corpus.

`resources/dev/runtime-local.json` is gitignored and machine-local; it points
at a KRDICT database you built yourself. `tools/README.md` has its shape.

## `live-hover` — human-operated session

```powershell
python -m lab live-hover --config resources/dev/runtime-local.json --duration 300
```

Not part of normal startup and not covered by fixture benchmarks: it uses the
current real mouse/capture/hover/OCR/lookup/popup composition and needs you to
provide desktop input for two to five minutes. Only start it when you are ready
to do that.

The session starts in `idle`; **`Ctrl+Alt+Shift+B`** advances to the next phase
after each interval. The remaining phases are empty areas, non-Korean text,
repeated same Korean word, several Korean words, stationary changing content,
fast movement, and normal browser/game use.

Each run writes `metadata.json`, `live-events.jsonl`, `process.csv`,
`summary.json`, and `stdout.log`. `process.csv` and the summary's resource use
describe the benchmark's own shell process only; the lookup child that holds the
OCR models is a separate process and is not sampled. Pixel hashing runs on a separate bounded
thread; no screenshot or pixel buffer is written to disk.

### Freeze and export

A hover popup disappears, which is what makes a wrong answer hard to study. Two
more hotkeys are there for that:

| Hotkey | |
|---|---|
| **`Ctrl+Alt+Shift+F`** | pin the newest completed lookup in memory |
| **`Ctrl+Alt+Shift+E`** | write that pinned lookup's evidence to the run directory |

**Freezing writes nothing.** It selects one completed lookup from a bounded
in-memory ring and pins its ROI bytes, capture geometry, gate and cache
decisions, resolver reasoning, morphology, dictionary query, retained bounds and
presentation outcome. Move the mouse afterwards and the pinned record does not
change. Close the session without exporting and it is gone.

Exporting is the separate, deliberate act that puts real screen content on disk.
It writes `metadata.json`, `input.png`, `diagnostic.json`, `diagnostic.html` and
`events.jsonl` under `<run>/frozen-<lookup-id>/`. (The export can also carry an
`ocr/` folder for a staged EasyOCR replay, but no command attaches one yet, so
`live-hover` never writes it.) It refuses any destination outside
`artifacts/lab/runs/`, including a run directory placed elsewhere with
`--output-root`: the rest of that run's evidence goes there, but an export is
refused.

There is no raw-text tracing option any more. Recognized text reaches disk
through an export of one pinned lookup or not at all.

Each geometry layer is named and drawn apart — the captured ROI, raw detector
regions, normalized OCR regions, the selected region, the estimated surface
word, the retained screen rectangle, and the cursor — and a layer that is
genuinely unavailable says so with a reason rather than being drawn as empty.
Apple Vision exposes no detector boxes, so on macOS that layer is normally
absent rather than zero.

### Staged EasyOCR

`lab/easyocr_stages.py` reproduces `Reader.readtext` stage by stage
against a pinned EasyOCR version, keeping the exact crop that reached the
recognizer for each region. Normalization is the shipped adapter's own, so a
staged run and a production run cannot disagree about what a detection means.

Evidence from it carries one of two labels, and they are never mixed. A lookup
deliberately run through the staged path owns its crops. Replaying a frozen ROI
*after* a production lookup is `comparison_replay`: `compare_to_live` reports
any divergence from the live normalized output and leaves the live result
authoritative.

The baseline does not poll the screen while the cursor is stationary, so a page
or game changing underneath an unchanged cursor should *not* produce a new
capture or OCR invocation. That is recorded as evidence, not treated as a
failure.

---

## OCR on its own

A `real-lookup` run measures capture, OCR, Kiwi, KRDICT and presentation
together. These commands measure the recognizer and construct nothing else — no
morphology, no dictionary, no `LookupPipeline`, no hover, no UI — which is what
makes an OCR number attributable.

```powershell
# Score the committed corpus with the product's own backend.
python -m lab ocr-campaign --mode ocr-only --backend vision

# Time detection and recognition separately. EasyOCR only: it is the one
# backend with separately addressable stages.
python -m lab ocr-campaign --mode detection-only --backend easyocr
python -m lab ocr-campaign --mode recognition-only --backend easyocr

# List a corpus without loading an OCR runtime at all.
python -m lab ocr-corpus --manifest lab/fixtures/ocr/manifest.json
```

| Mode | |
|---|---|
| `ocr-only` | image to normalized results, through the provider seam |
| `detection-only` | detector geometry; the text is dropped, and every transcription metric reports `not_applicable` rather than a perfect score for a transcription that never happened |
| `recognition-only` | detected crops through the recognizer; detection still runs to find them but is excluded from the reported total |
| `frozen-replay` | a frozen ROI at its recorded configuration, labelled as replay |

Every run writes `metadata.json`, `corpus-inventory.json` (with the corpus
fingerprint), `samples.jsonl` (one raw record per pass, so any summary can be
regenerated) and `summary.json`.

For cases that state their truth (schema 2), each pass also records stage facts,
`observed_true`, `observed_false` or `unavailable`, and the first stage
observed to go wrong (`stage_evidence.py`): exact target-surface correctness
through the engine's own resolver, a detector response on an empty image (only
in EasyOCR's `detection-only`, whose regions are the detector's own;
`recognition-only` and Vision return normalized results, which are not detector
internals), false Hangul, and false Korean target
selection. `--repeats N` sets the warm repetitions, and the summary classifies
each case as stable or varying apart from correct or wrong, so a consistently
wrong answer is never mistaken for reliability.

`--compare-backends [easyocr,vision]` runs the same corpus through each backend
in a fresh `ocr-only` process and writes `differential.md` and `.json`: whether
every child saw identical input hashes, each backend's first passes (one per
case, including its first inference), memory and errors, and per case whether all passed, all failed at the same or
different stages, or only some passed. A backend this machine lacks is
`unavailable`; no winner is chosen, and staged EasyOCR replay is never mixed in.

The first pass of each case is `cold`, then `--warmup` passes, then `--samples`
warm ones. Only warm passes are scored; percentiles are nearest-rank over the
retained raw durations. Peak RSS comes from the standard library and is always
available; current RSS needs `psutil` and reports itself unavailable without it,
rather than reporting zero.

## The corpus

`lab/fixtures/ocr/manifest.json` is the committed corpus and
`lab/fixtures/ocr/README.md` explains why it is currently empty. A
manifest declares whether it is `committed` or `local`, and validation enforces
the difference: a committed manifest may not carry an absolute path and may not
reference a `local_private` or `local_synthetic` case.

```powershell
# Render the synthetic corpus. Refuses if the licensed face is not installed.
python -m lab ocr-corpus-generate
```

The generator never substitutes a face for a missing one — a mislabelled font
turns every measurement into a measurement of something else — and it refuses
text the chosen face has no glyphs for. Samples from a face whose licence
forbids redistribution are marked `local_synthetic`, which a committed manifest
then refuses.

### Generated corpora

`ocr-corpus-generate --profile golden|smoke|balanced|difficult [--seed N]
[--max-cases N] [--max-bytes N]` renders from faces installed on this machine
into gitignored `artifacts/lab/corpus/<profile>-seed<N>/` (`manifest.json`,
`generation.json` with every recipe and omission, `images/`). `golden` is a
fixed set covering each family and condition once; `smoke` and `balanced` are
seeded and split evenly across positive, negative and mixed cases; `difficult`
draws only small, low-contrast, blurred, compressed, noisy or scaled-down text.
Positives use the minibook's Korean lines and hand-set target words; negatives
are Latin, numbers, punctuation, blank areas, icons, borders and textures;
Japanese and Chinese cases appear only when a face proves those glyphs.
`ocr-corpus --fonts` lists the installed faces and the scripts each can draw.

Schema 2 states each case's truth (text present, Korean present, a surface or
no-Korean target, complete or missing regions), its family and its generation
identity: seed, generator and renderer versions, face hash, style and index,
layout, colours, supersampling (rendered large and reduced once) apart from
post-render display scaling, blur, JPEG, seeded noise and the final pixel hash.
A missing face or glyph is an omission with its reason, never a substitute;
discovered faces have unknown licences, so their cases stay `local_synthetic`.
Schema 1 manifests still load, without stated truth.

## Tests

```powershell
python -m pytest lab/tests
```

They run as part of the normal `python -m pytest` too — `testpaths` includes
this directory — so the harness cannot rot unnoticed.
