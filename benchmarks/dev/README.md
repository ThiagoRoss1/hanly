# Hanly developer harness

On-screen instrumentation and measurement campaigns for the real hover
pipeline. Nothing here ships: neither `hanly` nor `hanly_app` imports this
package, and it is not part of either distribution. Raw evidence is written
under the gitignored `artifacts/benchmarks/` tree.

## Setup

Install the desktop as described in the root `README.md`, then add the `dev`
extra on top of it:

```powershell
python -m pip install -e "packages/hanly-app[dev]"
```

That extra adds Pillow, which the image-driven campaigns need. It must come
*after* `packages/hanly` is installed — `hanly-app` depends on `hanly==0.5.3`,
which exists only in this checkout.

Every command below runs from the repository root.

---

## `dev-hud` — run Hanly with the on-screen HUD

**This is the one to reach for.** It starts the *real* desktop — same
composition, same providers, same hover behaviour — with a panel drawn on top
showing what each hover actually did: the stage timeline (dwell, capture, OCR,
token selection, morphology, dictionary), OCR hit rate, worker readiness, and
process resources. A second overlay outlines the region that was captured.

```powershell
python -m benchmarks.dev dev-hud
```

That uses your normal per-user configuration, exactly like `hanly`. To run it
against an explicit one instead:

```powershell
python -m benchmarks.dev dev-hud --config resources/dev/runtime-local.json
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
structured/PNG/HTML diagnostics, under `artifacts/benchmarks/runs/<run-id>/`.

```powershell
# Real resident providers: first inference, warm-ups, and 30 warm samples.
python -m benchmarks.dev real-lookup `
  --image tests/hanly_fixtures/assets/korean_reading_roi.png `
  --config resources/dev/runtime-local.json `
  --target-x 100 --target-y 24 --roi-size 192x48

# Dwell through an actually visible Qt popup.
python -m benchmarks.dev real-hover `
  --image tests/hanly_fixtures/assets/korean_reading_roi.png `
  --config resources/dev/runtime-local.json `
  --target-x 100 --target-y 24 --roi-size 192x48

# OCR invocation opportunities by hover condition. Deterministic, no hardware.
python -m benchmarks.dev hover-rate

# Real monitor enumeration and ROI capture. Retains no screen pixels.
python -m benchmarks.dev desktop-capture

# Exact composition of a frozen build tree.
python -m benchmarks.dev package `
  --root dist/windows/hanly-desktop `
  --output artifacts/benchmarks/package-composition.json
```

A committed Korean fixture is correctness-regression evidence, not an OCR
accuracy corpus.

`resources/dev/runtime-local.json` is gitignored and machine-local; it points
at a KRDICT database you built yourself. `tools/README.md` has its shape.

## `live-hover` — human-operated session

```powershell
python -m benchmarks.dev live-hover --config resources/dev/runtime-local.json --duration 300
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
`summary.json`, and `stdout.log`. Pixel hashing runs on a separate bounded
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
`events.jsonl` under `<run>/frozen-<lookup-id>/`, plus `ocr/` when a staged
EasyOCR run is attached. It refuses any destination outside
`artifacts/benchmarks/runs/`.

There is no raw-text tracing option any more. Recognized text reaches disk
through an export of one pinned lookup or not at all.

Each geometry layer is named and drawn apart — the captured ROI, raw detector
regions, normalized OCR regions, the selected region, the estimated surface
word, the retained screen rectangle, and the cursor — and a layer that is
genuinely unavailable says so with a reason rather than being drawn as empty.
Apple Vision exposes no detector boxes, so on macOS that layer is normally
absent rather than zero.

### Staged EasyOCR

`benchmarks/dev/easyocr_stages.py` reproduces `Reader.readtext` stage by stage
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
python -m benchmarks.dev ocr-campaign --mode ocr-only --backend vision

# Time detection and recognition separately. EasyOCR only: it is the one
# backend with separately addressable stages.
python -m benchmarks.dev ocr-campaign --mode detection-only --backend easyocr
python -m benchmarks.dev ocr-campaign --mode recognition-only --backend easyocr

# List a corpus without loading an OCR runtime at all.
python -m benchmarks.dev ocr-corpus --manifest benchmarks/fixtures/ocr/manifest.json
```

| Mode | |
|---|---|
| `ocr-only` | image to normalized results, through the provider seam |
| `detection-only` | detector geometry; the text is dropped, and every transcription metric reports `not_applicable` rather than a perfect score for a transcription that never happened |
| `recognition-only` | annotated or detected crops straight to the recognizer |
| `frozen-replay` | a frozen ROI at its recorded configuration, labelled as replay |

Every run writes `metadata.json`, `corpus-inventory.json`, `samples.jsonl` (one
raw record per pass, so any summary can be regenerated) and `summary.json`.

The first pass of each case is `cold`, then `--warmup` passes, then `--samples`
warm ones. Only warm passes are scored; percentiles are nearest-rank over the
retained raw durations. Peak RSS comes from the standard library and is always
available; current RSS needs `psutil` and reports itself unavailable without it,
rather than reporting zero.

## The corpus

`benchmarks/fixtures/ocr/manifest.json` is the committed corpus and
`benchmarks/fixtures/ocr/README.md` explains why it is currently empty. A
manifest declares whether it is `committed` or `local`, and validation enforces
the difference: a committed manifest may not carry an absolute path and may not
reference a `local_private` or `local_synthetic` case.

```powershell
# Render the synthetic corpus. Refuses if the licensed face is not installed.
python -m benchmarks.dev ocr-corpus-generate
```

The generator never substitutes a face for a missing one — a mislabelled font
turns every measurement into a measurement of something else — and it refuses
text the chosen face has no glyphs for. Samples from a face whose licence
forbids redistribution are marked `local_synthetic`, which a committed manifest
then refuses.

## Tests

```powershell
python -m pytest benchmarks/dev/tests
```

They run as part of the normal `python -m pytest` too — `testpaths` includes
this directory — so the harness cannot rot unnoticed.
