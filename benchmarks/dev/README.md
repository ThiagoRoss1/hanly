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
*after* `packages/hanly` is installed — `hanly-app` depends on `hanly==0.1.0`,
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
fast movement, and normal browser/game use. Leave `--retain-text` off unless
you explicitly need raw OCR text and the content is controlled.

Each run writes `metadata.json`, `live-events.jsonl`, `process.csv`,
`summary.json`, and `stdout.log`. Pixel hashing runs on a separate bounded
thread; no screenshot or pixel buffer is written to disk.

The baseline does not poll the screen while the cursor is stationary, so a page
or game changing underneath an unchanged cursor should *not* produce a new
capture or OCR invocation. That is recorded as evidence, not treated as a
failure.

## Tests

```powershell
python -m pytest benchmarks/dev/tests
```

They run as part of the normal `python -m pytest` too — `testpaths` includes
this directory — so the harness cannot rot unnoticed.
