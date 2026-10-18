# Hanly Lab

**1.1.0** — developer tools for the matching Hanly desktop.

The developer lab: run the real Tauri desktop under observation, let the lab drive it,
and read a visual report of the native app and its owned service family. It also keeps the
measurement campaigns and regression checks that used to live in `benchmarks/`.

Nothing here ships: neither `hanly` nor `hanly_app` imports this package, and it
is not part of either distribution.

## Setup

Install the desktop and the development dependencies as described in the root
`README.md`. Lab pages and HUDs use the desktop runtime's Pillow and capture
dependencies; they do not add a separate UI toolkit dependency:

```bash
python -m pip install --group dev
python -m pip install --editable packages/hanly
python -m pip install --editable "packages/hanly-app[runtime]"
```

macOS uses the runtime's PyObjC frameworks to host Lab-owned image windows.
Windows and Linux use Tk; the Python build must include Tk support. Linux
fixture windows require an X11 display with Shape input-region support. Lab
reports a clear prerequisite error when a platform host is unavailable.
Every command runs from the repository root.

## The three commands

```bash
python -m lab                 # run Hanly; you use it, quit it, the report opens
python -m lab tour            # the lab uses Hanly itself and scores every answer
python -m lab report          # reopen the newest report
```

Everything else is optional. `python -m lab report --list` shows every recorded
run of every kind, and `python -m lab report <run-name>` reopens one.

### `python -m lab` (`run`) — you drive

Starts the native Hanly desktop as a separate process with a disposable app
profile and the selected runtime configuration. Lab observes its bounded trace
stream and samples the desktop, its Python service, lookup child and WebKit
helpers externally. Use Hanly normally; quit from the tray or with Ctrl+C, or
pass `--duration SECONDS`. `--desktop PATH` selects a packaged app or binary;
`--hud` also draws the Lab-owned on-screen HUD. A normal session does not opt in
to recognized text or capture geometry.

### `python -m lab tour` — the lab drives

Covers the virtual desktop with lab-authored Korean, presses the real capture shortcut,
glides the real pointer onto each word, and waits for the app's own trace to say
how that hover ended. Every target has a known answer:

- the **story** (`fixtures/minibook`): prose with hand-set dictionary forms,
  conjugations, particles, and Latin words that must be refused;
- **words**: KRDICT headwords with an English translation (the provider answers
  in English, so an entry without one has nothing to expect), sampled with
  seed 7 and painted at 16, 22, 30 and 40 px across three themes and the
  installed Korean typefaces.

The fixture page and HUD are opaque raster windows owned by Lab; the app being
measured is the launched Tauri desktop. The plain command is the **standard tour**: the whole story and 300 words, about
three and a half minutes. Tours with the same settings are comparable;
`--baseline <earlier-run>` adds a before/after table to the new report.
`--quick` is a 40-second smoke run (24 words, no story); `--words`,
`--story-sizes`, `--word-sizes` and `--seed` change the corpus, which makes a run
incomparable with the standard one.

Text is painted, so each hover exercises capture and OCR. **Move the mouse
yourself to stop the tour.** It checks that the capture shortcut is bound.
Hanly reports required screen-capture or accessibility access in its native
Permissions pane; the Lab does not grant or change OS permissions.

On macOS, the Lab sends an F1–F20 primary key through Quartz with the public
SecondaryFn flag, because pynput's function-key event can be interpreted as a
hardware alternate action before reaching Hanly's shortcut listener. Other
chord keys continue through pynput, and the Lab records only edge order and
index, never key contents.

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
- **Process and diagnostic data** comes from the isolated desktop profile and
  the external sampler. The regular session never mirrors service log text
  into the timeline.
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
instead of the seeded plan: each image is painted pixel for pixel on the Lab's
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
| `events.jsonl` | every accepted trace event from the native desktop service and lookup child (content fields removed), plus Lab lifecycle and driver events, including each tour result as described above |
| `processes.jsonl` | memory, CPU and threads for the native Tauri host and its owned Python service, lookup and webview helpers every 250 ms, sampled externally; macOS helper attribution uses the OS process-responsibility assignment when its runtime probe succeeds |
| `report.html` | the visual report: findings, system map, where time goes, funnel, timeline, hover explorer, tour accuracy, startup, processes |
| `report.json`, `summary.md` | the same model for scripts and agents |

The report rebuilds from the recorded files at any time and never writes beside
a baseline it compares with. Its findings name the code where each cost lives;
they are derived from the run, not hand-written.

Measurement limits: trace timestamps share the service's monotonic clock (`perf_counter`
is system-wide on every supported OS). RSS is resident, not private, memory and
is sampled, so short spikes can be missed. On macOS, Lab launches the app through
public LaunchServices and adopts the exact fresh app PID. It probes the OS
process-responsibility interface before assigning WebKit helpers. An absent OS
interface uses the process tree instead; each run records the chosen attribution
path, and tree-only attribution may omit reparented helpers. Protocol v3 separates
these runs from the previous launcher and Qt-painted fixture recordings.

## EasyOCR crop, decoder and alphabet diagnosis

`python -m lab.easyocr_audit --manifest PATH --output NEW_DIRECTORY` runs a
deterministic font-balanced subset of authored synthetic images through the
real CPU adapter. It records actual Torch threads/device, model hashes and
alphabet limits, strict token/line scores, raw repetitions and staged replay
agreement. It downloads no model, refuses private screenshots and never
overwrites a previous output directory.

Defaults compare product inference, the existing sensitive pass, beam search
and annotated tight line crops. `--variants product model-alphabet
line-oracle-padded` checks language masking and crop margin sensitivity;
`--variants product --no-quantize` checks quantization. Annotated boxes are
diagnostic ground truth unavailable at runtime, not an alternative production
detector or an accuracy upper bound. No variant changes product settings.

Use `--limit 120 --samples 2 --cpu-threads 4` for the recorded investigation's
selection. Run comparisons sequentially and do not infer Windows performance
from Mac timings. Full results and the observed Korean output-alphabet limit
are in the [2026-10-18 investigation](../docs/execution/reports/easyocr-lab-investigation-2026-10-18.md).

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

It supervises the *real* Tauri desktop and shows a separate Lab-owned panel
with its bounded trace events: dwell, capture, OCR, token selection,
morphology, dictionary and popup decisions. Process-family resource samples
are recorded in the Lab report; the panel labels those measurements there.
An optional second overlay outlines the last captured region.

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
| `--desktop PATH` | Hanly executable or `.app` |
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

# Dwell through the native Tauri popup using a controlled private ROI.
python -m lab real-hover `
  --image tests/hanly_fixtures/assets/korean_reading_roi.png `
  --config resources/dev/runtime-local.json `
  --target-x 100 --target-y 24 --roi-size 192x48 `
  --expected-text 읽습니다.

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

`real-hover` paints the supplied image in a temporary Lab-owned page, drives
the real desktop hover pipeline, and times the native popup trace. Its private
image and expected surface are removed after the run; the report retains only
text-free outcome facts and timing measurements.

`resources/dev/runtime-local.json` is gitignored and machine-local; it points
at a KRDICT database you built yourself. `tools/README.md` has its shape.

## `resources` — what each part costs, and whether a change helps

```bash
python -m lab resources stages [--components ocr,kiwi,dictionary] [--repeats 3]
python -m lab resources session <run>          # phases of a recorded session
python -m lab resources compare <baseline> <candidate>
```

`stages` runs Hanly's real providers, built as the lookup child builds them, in
fresh interpreters. Each child walks fixed stages and waits at every boundary
while the parent reads it from outside:

1. interpreter, imports and runtime validation;
2. each provider's construction;
3. worker assembly with prewarming;
4. the first lookup;
5. repeated lookups on varied inputs (fresh) and on the same input (cache hits);
6. idle, unload, and idle after unloading.

`--components` adds one isolated process per provider. The run records:
- macOS physical footprint (RSS elsewhere), RSS and sampled peaks;
- CPU, threads, disk reads and writes, latency and exit time;
- a digest of each lookup's decision. No text and no pixels are kept.

Inputs are minibook lines rendered in an installed Hangul face, kept in a
temporary file that is deleted with the run. One unrecorded warm-up child runs
before each experiment's repeats. A `calibration` experiment maps and releases a
known 64 MiB; if it is not attributed and released, distrust the run.
`summary.md` states the method and its limits:
- Deltas between boundaries are estimates.
- Native allocators keep freed pages, so what unloading leaves is released
  only when the process exits.
- RSS falls when idle pages are compressed.
- GPU memory is always unavailable.

`session` attributes an existing session's `processes.jsonl` to the phases its
own events mark: startup, engine warm-up, active, idle and shutdown. It reports
per-role peaks, sustained medians, growth, duplicate processes and anything
still running after the stop. It writes `resources.md` beside the run.

`compare` refuses pairs that differ in protocol, inputs, plan, recognizer,
library versions or host, or that have fewer than two repeats a side. It then
compares the decision digests before labelling any cost: `unchanged`,
`improved`, `regressed` or `inconclusive`.
It also refuses failed calibration on either side and failed or unfinished
repeats. `resources-v3` includes morphological explanations in the decision
digest and detects an OCR input missing from a later repeat. Earlier v2
recordings remain unchanged and cannot be compared directly with v3.
- Memory uses a band of max(5 %, 16 MiB); timing uses max(5 %, 5 ms).
- Overlapping ranges are `inconclusive`.
- A timing change needs five repeats a side. Two identical-code runs of three
  repeats each produced six false timing labels and no false memory label.

`compare` never accepts a change. An accepted optimization still needs
reproducible evidence, stated trade-offs and regression coverage. Nothing here
tunes a production setting.

## `grammar` and `word-selection` — what the reader is shown, and why it misses

`python -m lab grammar-pages --output artifacts/lab/grammar-pages` generates
paired `text.html` and `ocr.html` pages without opening windows. The first
contains selectable Korean; the second contains images with empty alt text
and keeps ground truth outside the accessible page. Each case changes the
actual browser/OS cursor; the selector can hold a cursor constant, including
zoom-in/out. Image zoom and drag use native element behavior. Native tests
that open windows or move the pointer require the operator's approval.

The inventory enumerates every particle and ending entry in the selected
KRDICT database and retains one locatable example per entry. Kiwi helps locate
grammatical tokens rather than identically spelled noun characters. This is
fixture construction, not an independent oracle for Kiwi or proof of complete
Korean grammar coverage. Missing examples remain listed. Hand-authored lemma
expectations, including prospective `-(으)ㄹ 거예요`, remain separate.

Normal, handwritten/comic-like, display and pixel faces are pinned with their
OFL licenses in `fixtures/fonts/`. A bounded matrix varies size, contrast,
scaling, blur, compression and noise; `--stress-cases 0..12` controls its size.
Missing glyphs are reported, never silently substituted. The external manifest
records source, dictionary/font identities, generated pixels and target
geometry. Authored lemma answers remain indexed by syllable; raw OCR token
truth also retains punctuation, independently of the grammatical target.
These pages are native-test inputs, **not** native detector/OCR
acceptance results. The existing language/word-selection commands below keep
their original measurement scopes.

Run the image batch separately with `python -m lab ocr-campaign --backend vision
--manifest artifacts/lab/grammar-pages/corpus.json --samples 1 --warmup 0`
(or `--backend easyocr`). This measures the existing recognizer/word resolver
over images; it does not exercise native screen capture or accessibility.

```bash
python -m lab grammar                                   # language stage only
python -m lab word-selection --ocr-backend vision       # or easyocr; --stride N
```

`grammar` scores the language stage (Kiwi and KRDICT, no OCR) on
`lab/fixtures/korean/grammar.json`. That is a reviewed, finite corpus covering:
- particles and particle combinations;
- syllables that look like particles but belong to the word;
- conjugations and irregulars;
- copulas;
- auxiliary constructions;
- ambiguous forms;
- Korean fused to digits, emoji or punctuation.

Every target is hovered at every syllable, in both forms acquisition produces:
the whitespace-delimited word OCR resolves (with its neighbouring words), and
the Korean run accessibility text yields. Every expected headword and
construction is checked against KRDICT before scoring, so a corpus typo fails
loudly instead of passing as a model error. Ambiguous cases list what is
acceptable and say why.

`word-selection` renders Lab-authored pages of three lines at several sizes,
contrasts and display-edge positions. It hovers the first, middle and last
syllable of each word on the middle line, and crops exactly as the desktop
does (the shipped ROI and grid, clipped to the page as to a display). The real
lookup worker then runs on the crop, constructed, used and closed on one
provider thread. This is an in-process replica; it does not exercise the
service, real process transport, native capture, accessibility or windows.
Protocol v2 stamps source identity/diff before work, plus dependency, font,
dictionary and corpus hashes and the stride/limit. Glyph geometry is exact, so every miss
is classified against ground truth:

| category | meaning |
|---|---|
| `clipped_by_roi` | the word extends past the captured crop |
| `ocr_false_space` | the recognized line splits the word with a space |
| `ocr_misread` | the line lacks or alters the word's characters |
| `neighbor_word` | the line holds the word, but another one was selected |
| `wrong_line` | a different line was selected |
| `no_result` | nothing usable came back |
| `lexical` | the right surface, a headword the corpus does not accept |

It also counts genuine OCR calls (cache hits are not recognitions) and fresh
lookup p50 and p95, and how often the resolved word touches the crop edge.
Results are Mac evidence for the recognizer they name. They are never Windows
evidence: Windows capture, DPI scaling and UIA need their own native runs.

## `live-hover` — human-operated session

```powershell
python -m lab live-hover --config resources/dev/runtime-local.json --duration 300
```

This launches the checkout's debug Tauri app with an isolated profile and
observes its real mouse, capture, hover, OCR, lookup, and native popup path. It
needs you to provide desktop input for two to five minutes. Only start it when
you are ready to do that. Pass `--desktop` to select a different debug app and
`--app-config` to choose the preferences copied into the disposable profile.

The session starts in `idle`; **`Ctrl+Alt+Shift+B`** advances to the next phase
after each interval. The remaining phases are empty areas, non-Korean text,
repeated same Korean word, several Korean words, stationary changing content,
fast movement, and normal browser/game use.

Each run writes `metadata.json`, `live-events.jsonl`, `process.csv`,
`processes.jsonl`, `summary.json`, and `stdout.log`. `process.csv` measures the
native Tauri shell; `processes.jsonl` samples the owned desktop family, including
its lookup child and macOS WebKit helpers where responsibility attribution is
available. Pixel hashing runs on a separate bounded thread; no screenshot or
pixel buffer is written to disk unless you explicitly export a frozen lookup.

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
retained raw durations. Peak RSS comes from the standard library's `resource`
module, which Windows lacks, so there it is reported unavailable (`null`);
current RSS needs `psutil`. Neither is ever reported as zero.

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
