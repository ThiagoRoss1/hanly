# Hanly code map

How the app actually runs, and which file does what. This document survives V1
launch: it describes the code, not the plan that produced it.

Read `docs/architecture/01`–`03` for *why* the boundaries are where they are.
This file is the *where*.

---

## 1. Two packages, one direction

```
packages/hanly-app   →   packages/hanly
   (the desktop)          (the engine)
```

`hanly` never imports `hanly_app`, and never imports repository tooling
(`tools/`). It is publishable on its own. `tests/test_package_boundary.py`
fails the build if that is ever violated.

- **`hanly`** — OCR orchestration, Korean linguistics, dictionary lookup,
  resource validation, contracts.
- **`hanly_app`** — everything desktop: OS integration, capture, hotkeys, tray,
  Qt popup, Control Center, worker threads, updates.

---

## 2. Entry points — what runs when

| You run | Reaches |
|---|---|
| `hanly` | `hanly_app/cli.py` → `main()` |
| `python -m hanly_app` | `__main__.py` → the same `main()` |
| the packaged `.exe` | `packaging/entrypoint.py` → the same `main()` |

**One command, one function.** `run` is the only verb and it is the default, so
plain `hanly` and `hanly run` are identical. `tests/test_packaging.py` fails if
a second entry point appears.

```
cli.main
  └─ capture_selector.select_capture_area()      whole monitor, or drag a region
  └─ application.resolve_runtime_config()
        └─ first_run.provision_runtime_config()  writes runtime.json, installs krdict
  └─ application.run_desktop()                   the app itself
```

---

## 3. Startup, in order

1. **`hanly_app/ocr_preload.py`** — imports EasyOCR *before* Qt. On Windows Qt
   changes native-library resolution once it initializes, so the OCR stack has
   to load first. A failure here is a reported diagnostic, not a crash.
2. **`hanly_app/first_run.py`** — a launch with no configuration of its own
   writes a default `runtime.json` under the per-user settings directory, then
   provisions any missing resource through `UpdateService`. Today that is only
   `krdict`; EasyOCR fetches its own models.
3. **`hanly_app/runtime.py`** — reads that JSON, asks `ResourceManager` to
   validate every declared resource, and returns a `HanlyRuntime` holding
   *factories* (not instances) for the three providers.
4. **`hanly_app/composition.py`** — wires those factories into a
   `LookupWorker`, wrapping them in caching, text-presence, and tracing layers.
5. **`hanly_app/application.py`** — builds capture, hover, hotkeys, popup,
   tray, Control Center, update coordinator, and the shutdown lifecycle, then
   enters the Qt event loop.

Providers are constructed **on the worker thread that will later close them** —
a SQLite connection belongs to the thread that opened it.

---

## 4. The lookup pipeline

```
hover (or hotkey)
  → debounce + cursor-validity check      hover_controller.py
  → small ROI capture                     capture.py
  → submit, bounded / latest-wins         lookup_controller.py
  → worker thread                         job_executor.py
      → OCR                               easyocr_provider.py
      → pick the word under the cursor    word_resolver.py
      → Hangul-only gate                  lookup_pipeline.py
      → morphology (lemma)                kiwi_provider.py
      → dictionary                        krdict_provider.py
  → final request-currency check          lookup_controller.py
  → popup                                 qt_popup.py / popup.py
```

`LookupPipeline` (`packages/hanly/src/hanly/lookup_pipeline.py`) is the only
place that knows the *order*. It has never heard of EasyOCR, Kiwi, or SQLite —
only the three interfaces in `providers.py`.

Two rules that are easy to break:

- **The currency check before presentation is mandatory.** Cancellation is
  resource control; it is not the correctness gate.
- **`LookupResult` models success, normal non-success** (empty / not-found /
  unusable / low confidence), **and processing errors.** Non-success is not an
  exception.

---

## 5. The three providers

Every external library sits behind a seam. Library objects are normalized
before they cross it.

| Interface (`hanly/providers.py`) | V1 adapter | Returns |
|---|---|---|
| `OCRProvider` | `easyocr_provider.py` | `OCRResult` |
| `MorphologyProvider` | `kiwi_provider.py` | `TokenAnalysis` |
| `DictionaryProvider` | `krdict_provider.py` | `DictionaryEntry` |

Providers **never** consult `ResourceManager`. Composition asks the manager for
validated paths and passes them into constructors explicitly.

**EasyOCR is the only OCR backend.** There is no backend selector. `OCRProvider`
remains the seam if a second adapter is ever wanted.

---

## 6. KRDICT — where the dictionary comes from and goes

### Build (tooling — not shipped in any wheel)

```
data/source/<official KRDICT>.zip
  → tools/krdict/source.py          streams and normalizes the XML
  → tools/krdict/build_seed.py      writes the SQLite, using schema.sql
  → tools/krdict/validate_seed.py   proves it against the source
  → tools/krdict/package_resource.py  → .sqlite3.zst + producer manifest
```

56,555 entries, 11 tables, ~92 MB, ~27 MB compressed. Build commands are in
`data/README.md`. `tools/krdict/inspect_archive.py` reads the source without building.

### Contract

`packages/hanly/src/hanly/krdict_schema.py` — the single definition of what a
valid KRDICT database *is* (tables, columns, indexes, metadata, cardinality).
The builder, the engine, and the update seam all validate against this one
file.

### Read at runtime

`packages/hanly/src/hanly/krdict_provider.py` — opens SQLite `mode=ro`, one
query per lookup, joining `lemmas`/`word_forms` → `entries` → `senses` →
`translations`. Only `DictionaryEntry` values leave the module.

### Deliver

`hanly_app/update_service.py` downloads, verifies the checksum **before**
decompressing, validates the schema, activates atomically, and keeps the
previous copy as a rollback. `hanly_app/first_run.py` reuses that exact path to
install an already-built local database, so a developer install and a real
download run the same code.

---

## 7. File index

### `packages/hanly` — the engine

| File | What it does |
|---|---|
| `contracts.py` | The value types that cross every seam: `OCRResult`, `TokenAnalysis`, `DictionaryEntry`, `LookupResult`, `ROIImage` |
| `providers.py` | The three provider interfaces |
| `lookup_pipeline.py` | ROI → `LookupResult`; owns the Hangul-only gate |
| `word_resolver.py` | Which word is under the cursor, including inside one line-level quad |
| `easyocr_provider.py` | EasyOCR adapter, plus the sensitive-retry options |
| `kiwi_provider.py` | Kiwi adapter (surface form → lemma) |
| `krdict_provider.py` | Read-only SQLite dictionary lookup |
| `krdict_schema.py` | The KRDICT database contract |
| `resource_manager.py` | Understands *local* resources: paths, versions, schema, integrity |
| `errors.py` | Error base types |

### `packages/hanly-app` — the desktop

**Startup and composition**

| File | What it does |
|---|---|
| `application.py` | Composition root: `run_desktop`, lifecycle, shutdown |
| `cli.py` | The one entry point: parser, chooser, dispatch |
| `ocr_preload.py` | Imports EasyOCR before Qt |
| `first_run.py` | Writes the default config, provisions missing resources |
| `runtime.py` | JSON config → validated `HanlyRuntime` with provider factories |
| `composition.py` | Builds the worker: caching, text-presence gate, tracing wrappers |
| `config.py` | Per-user preferences |

**Input and capture**

| File | What it does |
|---|---|
| `mouse_observer.py` | Observes the cursor. Only observes |
| `hover_controller.py` | Decides when a hover is worth acting on |
| `qt_hover_scheduler.py` | Hover timing on the Qt thread |
| `capture.py` | Screen ROI capture |
| `capture_selector.py` | The launch-time "which area?" chooser |
| `hotkeys.py` | Global hotkeys |

**Lookup execution**

| File | What it does |
|---|---|
| `lookup_controller.py` | Request IDs, stale handling, bounded / latest-wins submission |
| `job_executor.py` | The worker thread that owns the providers |
| `hover_lookup.py` | The hover-driven lookup runtime |
| `manual_lookup.py` | The hotkey-driven lookup runtime, and the Qt composition |
| `runtime_trace.py` | Structured per-stage trace events |

**Presentation and shell**

| File | What it does |
|---|---|
| `popup.py` / `qt_popup.py` | The dictionary popup |
| `tray.py` | System tray |
| `control_center.py` | pywebview settings/diagnostics window (`assets/control_center/`) |
| `desktop_controller.py` | Start / pause / resume state |
| `signal_bridge.py` | Ctrl+C → clean Qt shutdown |

**Updates**

| File | What it does |
|---|---|
| `update_service.py` | Obtains remote resources: download, verify, decompress, validate, activate, roll back |
| `update_coordinator.py` | Runs updates off the UI thread and reports progress |

### Outside the packages

| Path | What it is |
|---|---|
| `tools/krdict/` | Builds, validates, and packages the dictionary |
| `tools/dev_lookup.py` | Engine-only lookup rig |
| `tools/build_package.py`, `tools/release_version.py` | Release tooling |
| `packaging/` | PyInstaller spec, runtime hook, frozen entry point |
| `benchmarks/dev/` | Developer-only measurement harness — code, its own `tests/`, and the unwired hover `hud/`. Nothing in `packages/` imports it |
| `data/` | Local KRDICT source and build outputs. Gitignored except the README |
| `resources/dev/` | Machine-local benchmark configuration. Gitignored |
| `tests/` | Product tests for both packages |

---

## 8. Running it from a fresh clone

```bash
python -m pip install --group dev
python -m pip install --editable packages/hanly
python -m pip install --editable "packages/hanly-app[runtime]"
hanly
```

The `runtime` extra is what pulls the real stack — EasyOCR, Torch, Kiwi, Qt,
capture, hotkeys, tray. Several GB, mostly Torch.

**The dictionary is not in this repository.** Until the GitHub release carrying
it exists, point a fresh clone at an already-built copy:

```bash
export HANLY_KRDICT_DB=/path/to/krdict.sqlite3    # Windows: set HANLY_KRDICT_DB=...
```

A clone that already has `data/generated/krdict.sqlite3` is found without the
variable. EasyOCR downloads its own recognition models on the first lookup, so
that launch needs network access.

## 9. Gates

```bash
python -m pytest
python -m ruff check packages packaging tests tools benchmarks
python -m mypy packages packaging tests tools benchmarks
```
