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
  └─ multiprocessing.freeze_support()            diverts a spawned child first of all
  └─ diagnostics.open_diagnostics()              rotating log, before anything native
  └─ application.run_desktop()                   the app itself
        └─ qt_bootstrap.ensure_qt_application()  QApplication("hanly"), Qt Widgets only
        └─ DesktopApplication.run()              the shell owns the one event loop
        └─ startup.StartupCoordinator.start()    off-thread, behind the open window
              └─ owned_cleanup                   what an interrupted session left
              └─ application.resolve_runtime_config()
                    └─ first_run.provision_runtime_config()   runtime.json, krdict
              └─ runtime.load_runtime()
  └─ cli._leave()                                ends the process, does not unwind
```

Nothing is asked before the window opens. The interface is on screen while
resources download and providers warm, and it stays usable if either fails.

### Three processes

The shell never exits while Hanly is running, so it must never hold memory a
library will not give back. Qt WebEngine and the OCR/morphology/dictionary
providers do exactly that, so each lives in a child the shell can retire.

```
hanly (the shell)                 Qt Widgets, tray, hotkeys, capture, hover,
  │                               popup, settings, updates, the session log
  ├── hanly-control-center        pywebview + Qt WebEngine + the page
  │     (spawned on open, gone on close; opening again is a new process)
  └── hanly-lookup                EasyOCR + Kiwi + KRDICT + the pipeline
        (spawned by the preload policy; retired on Stop, or after an idle
         manual session; a lookup wakes a sleeping engine on demand)
```

`process_transport.py` is the one way they talk: an inherited duplex `Pipe`,
explicitly pickled messages with a checked size, serialized sends, and one
reader per direction. There is no listening port, no dispatch by name from the
wire, and no shell command line.

Measured on macOS: the shell holds about 60 MiB for a whole session. The window
costs roughly 300 MiB while it is open and gives all of it back on close; the
lookup engine costs roughly 800 MiB while it is loaded and gives all of it back
when it is retired.

`main` ends the process rather than returning into interpreter finalization.
Qt WebEngine keeps Chromium alive until the process is gone, and unloading its
libraries on the way out is what a quit used to hang or fail fast on. See
`cli._terminate_without_unloading`.

---

## 3. Startup, in order

1. **`hanly_app/ocr_preload.py`** — imports EasyOCR before anything else *in the
   lookup child*. On Windows Qt changes native-library resolution once it
   initializes, and the child loads the OCR stack before it does anything else.
   The shell never imports it at all. A failure here is a reported diagnostic,
   not a crash.
2. **`hanly_app/first_run.py`** — a launch with no configuration of its own
   writes a default `runtime.json` under the per-user settings directory, then
   provisions any missing resource through `UpdateService`. Today that is only
   `krdict`; EasyOCR fetches its own models.
3. **`hanly_app/runtime.py`** — reads that JSON, asks `ResourceManager` to
   validate every declared resource, and returns a `HanlyRuntime` holding
   *factories* (not instances) for the three providers.
4. **`hanly_app/composition.py`** — wires those factories into a
   `LookupWorker`, wrapping them in caching, text-presence, and tracing layers.
5. **`hanly_app/application.py`** — builds the shell (tray, settings,
   diagnostics, runtime status, and the Control Center child) first, then
   everything that needs a validated runtime once `startup.StartupCoordinator`
   has one. The event loop belongs to the shell, with
   `setQuitOnLastWindowClosed(False)`: every Hanly window is transient, and the
   Control Center is not even in this process.

Steps 2 and 3 happen **after** the window is visible, on the startup
coordinator's thread. Readiness is reported through
`runtime_status.RuntimeStatus`, which is separate from the capture lifecycle:
launching reaches `ready` without watching the screen, and the Start action is
what begins capture.

Providers are constructed **on the thread that will later close them**, inside
the lookup child — a SQLite connection belongs to the thread that opened it.

**Readiness is not residency.** `runtime_status.RuntimeStatus` says whether a
lookup can happen at all; `LookupEngine.state` (sleeping, preparing, ready,
error) says whether the providers are loaded right now. Which of those the
launch pays for is `config.LookupPreload`.

---

## 4. The lookup pipeline

```
hover (while the push chord is held, or for the whole session)
  → is the cursor still on the last answer?   hover_target.py     (if so, stop here)
  → debounce + cursor-validity check          hover_controller.py
  → small ROI capture                         capture.py
  → submit, bounded / latest-wins             lookup_controller.py
  → executor thread                           job_executor.py
  → across the pipe into the lookup child     lookup_process.py
      → OCR                                   easyocr_provider.py
      → pick the word under the cursor        word_resolver.py
      → TextSelection (text + cursor index)   lookup_pipeline.py
      → Hangul-only gate                      language_pipeline.py
      → morphology (lemma)                    kiwi_provider.py
      → dictionary                            krdict_provider.py
  → final request-currency check              lookup_controller.py
  → popup, and the word it came from retained qt_popup.py / hover_target.py
```

`LookupPipeline` (`packages/hanly/src/hanly/lookup_pipeline.py`) is the only
place that knows the *order*. It has never heard of EasyOCR, Kiwi, or SQLite —
only the three interfaces in `providers.py`.

**Acquisition stops at `TextSelection`.** `lookup_pipeline.py` owns what only
pixels can decide — recognition, which region the pointer is in, OCR confidence
— and then hands a surface word plus a cursor index to
`language_pipeline.py`, which owns everything after. A caller that already knows
the word constructs `LanguagePipeline` directly and needs no recognizer; both
paths run that one implementation, which is what makes them answer identically.
`TextSelection` carries no rectangle, window, or element handle, so the engine
stays usable by a client that has none.

Two rules that are easy to break:

- **The currency check before presentation is mandatory.** Cancellation is
  resource control; it is not the correctness gate.
- **`LookupResult` models success, normal non-success** (empty / not-found /
  unusable / low confidence), **and processing errors.** Non-success is not an
  exception.
- **A successful answer is retained while the cursor is on it.** Movement inside
  the union of the expanded word and the popup frame starts no capture and
  dismisses nothing; a real exit keeps the answer for a short grace so the gap
  to the popup can be crossed.

---

## 5. The three providers

Every external library sits behind a seam. Library objects are normalized
before they cross it.

| Interface (`hanly/providers.py`) | V1 adapter | Returns |
|---|---|---|
| `OCRProvider` | `easyocr_provider.py`, `vision_provider.py` | `OCRResult` |
| `MorphologyProvider` | `kiwi_provider.py` | `MorphologyAnalysis` |
| `DictionaryProvider` | `krdict_provider.py` | `DictionaryEntry` |

Providers **never** consult `ResourceManager`. Composition asks the manager for
validated paths and passes them into constructors explicitly.

**Two OCR backends.** `config.OCRBackend` selects: `auto` (default) prefers
Apple Vision where the platform has it and falls back to EasyOCR; `vision` and
`easyocr` pin one. `auto` is resolved in the shell —
`HanlyRuntime.resolved_ocr_backend()` — and the lookup child receives a concrete
backend in `LookupSettings`, because loading a framework from a spawned process
to ask about it hangs. Vision ships with macOS and downloads no model.

---

## 6. KRDICT — where the dictionary comes from and goes

### Build (tooling — not shipped in any wheel)

```
data/source/<official KRDICT>.zip
  → tools/krdict/source.py          streams and normalizes the XML
  → tools/krdict/build_seed.py      writes the SQLite, using schema.sql
  → tools/krdict/validate_seed.py   proves it against the source
  → tools/krdict/package_resource.py  → .sqlite3.zst + hanly-resources.json
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

## 6a. Updating Hanly itself

A resource is swapped while Hanly keeps running. The application holds the
executable and the interpreter running from it, so it cannot be.

**One plan, three ways of applying it.** Preparing an update is identical
everywhere: pin the release, read the one metadata package, read the
installation, establish what it is, decide what changes. Only what happens to
the plan afterwards differs.

```
Control Center "Update now"
  → update_coordinator.py          one operation at a time, off the UI thread
  → app_update_runner.py           TreeUpdateRunner takes the installation's lock
  → app_update_install.py  prepare()
        pin the release                              ReleaseSnapshot
        SHA256SUMS → Hanly-vX.Y.Z.hup                app_hup.py (metadata only)
        this machine's entry                         stamp: app_build_identity.py
        read the installation as a tree              app_inventory.read_tree
        establish ownership: receipt, or bootstrap against the installed tag
        decide what changes                          app_update_plan.plan_tree_update
    ↳ the delta cannot be used here → show the real size, ask again
  → app_update_install.py  stage()
        download the payload the plan named, verify it
        → WindowsFileStaging   stage only the changed files      (journal)
        → PosixTreeStaging     build a whole candidate and prove it
  → hand off, then Hanly quits
        → app_update_helper.py    detached PowerShell, file by file
        → app_update_handoff.py   the native helper, two renames
```

### Windows: change the files that differ, in place

The installation path never changes and no second copy is made. Everything
lives under `<installation>/.hanly-update/<transaction>/`: the staged files,
the originals moved aside, the journal, and the answer the new build has to
produce. `app_update_helper.py` renders the PowerShell that applies it.

### macOS and Linux: build the whole thing, then swap

`app_update_tree.py` reconstructs the published build in a private directory
beside the installation - mostly out of bytes the installation already holds -
and `verify_candidate` proves it entry by entry. `app_update_macos.py` adds
what only macOS needs: a disk image attached read-only at a private mount
point, `ditto`, and `codesign --verify --deep --strict` on the result. Nothing
is re-signed locally; the published signature material travels as file content
and extended attributes (`app_xattr_darwin.py` binds the four libc calls
CPython does not expose).

The swap itself belongs to `packaging/updater/hanly-update-posix.c`, a small
C program linked against nothing but the system. It has to work when the thing
it is repairing does not: the installation path is briefly absent between its
two renames, so a helper that loaded an interpreter or a script out of that
directory would be relying on the tree it is replacing.

Five rules hold the whole thing together:

- **The previous build outlives the update.** It is discarded only once the new
  one has answered that transaction's challenge - its own build UUID, a random
  nonce, and the manifest digest - which `cli.main` answers through
  `--update-ready-v2` when the shell's event loop starts. A version number is
  not an acknowledgement; `--update-ready` remains exactly as it was for
  helpers an older Hanly installed.
- **Correctness comes from the filesystem, not the record.** Every apply,
  rollback, and recovery step reads what is actually there before acting.
- **The helper depends on nothing it is changing.** A verified copy of it lives
  outside the installation, with a route to run it when Hanly will not start.
- **Ownership decides deletion.** Only a path the previous build owned, and the
  new one dropped, is removed. Ownership comes from a receipt this updater
  wrote, or from a tree proved to match a published manifest exactly - never
  from equal bytes at a path nobody claimed.
- **A plan is decided before a payload is fetched.** The size a person is shown
  is the size that will be downloaded, and a full download is always asked for.

### What a release publishes for it

| Asset | Read by |
|---|---|
| `Hanly-vX.Y.Z.hup` | every package-aware client: the index and one tree manifest per platform |
| `hanly-desktop-<platform>-<arch>-from-<base>-to-<target>.delta.zip` | one platform's changed bytes, when a verified predecessor existed |
| `hanly-desktop-windows.zip`, `-macos.dmg`, `-linux.tar.gz` | the whole product, when a delta cannot be used |
| `hanly-desktop-macos.zip`, `-windows.manifest.json`, `-windows.update.json` | compatibility, for clients from before update packages |

`tools/update_artifacts.py` produces each platform's manifest, delta, and
descriptor from the finished, signed tree, and assembles the one package from
every platform that succeeded. `packaging/README.md` has the build order and
the migration routes.

---

## 7. File index

### `packages/hanly` — the engine

| File | What it does |
|---|---|
| `contracts.py` | The value types that cross every seam: `OCRResult`, `TokenAnalysis`, `DictionaryEntry`, `LookupResult`, `ROIImage`, `TextSelection` |
| `providers.py` | The three provider interfaces |
| `lookup_pipeline.py` | The pixel facade: ROI → `TextSelection` → `LookupResult` |
| `language_pipeline.py` | `TextSelection` → `LookupResult`; owns the Hangul-only gate, candidate selection, and the dictionary query. Knows nothing about pixels |
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
| `application.py` | Composition root: `run_desktop`, the desktop session, shutdown |
| `cli.py` | The one entry point: parser, dispatch, `--self-check`, process exit |
| `qt_bootstrap.py` | The one `QApplication` per process, with a program name. Nothing heavy |
| `startup.py` | Prepares the runtime off the UI thread, behind the open window |
| `ocr_preload.py` | Imports EasyOCR first, in the lookup child |
| `first_run.py` | Writes the default config, provisions missing resources |
| `runtime.py` | JSON config → validated `HanlyRuntime` with provider factories |
| `composition.py` | Builds the worker: caching, text-presence gate, tracing wrappers |
| `config.py` | Per-user preferences, including the capture target and region |
| `paths.py` | Per-user settings, runtime-config, and log locations |
| `diagnostics.py` | Rotating session log, the filterable record tail, and the sanitized export |
| `owned_cleanup.py` | What an interrupted session left behind, and what must never be removed |
| `process_transport.py` | The one way the shell and its children talk |
| `runtime_status.py` | Readiness, separate from the capture lifecycle and from engine residency |
| `self_check.py` | `--self-check`: the frozen bundle proving its own runtime and window |

**Input and capture**

| File | What it does |
|---|---|
| `mouse_observer.py` | Observes the cursor. Only observes |
| `hover_controller.py` | Decides when a hover is worth acting on |
| `qt_hover_scheduler.py` | Hover timing on the Qt thread |
| `capture.py` | Screen ROI capture |
| `capture_selector.py` | The "which area?" overlay, reached from settings |
| `hotkeys.py` | Global hotkeys, both edges of a chord, and the backend per platform |
| `hotkeys_darwin.py` | The macOS backend: Carbon `RegisterEventHotKey`, pressed and released |
| `popup_darwin.py` | Keeps the macOS popup panel on screen while Hanly is inactive |
| `app_identity_darwin.py` | What macOS thinks a Hanly process is, so only one is an application |
| `permissions.py` | Which grant each feature needs, and how it is reported |
| `permissions_darwin.py` | The macOS status and grant flows, through ctypes |

**Lookup execution**

| File | What it does |
|---|---|
| `lookup_controller.py` | Request IDs, stale handling, bounded / latest-wins submission |
| `job_executor.py` | The executor thread: one job running, one latest pending |
| `lookup_process.py` | The lookup child, its transport, and the engine that owns provider residency |
| `hover_lookup.py` | The hover-driven lookup runtime, and the answer the cursor may rest on |
| `hover_target.py` | Where a result came from on screen, what protects it, and the crossing to the popup |
| `manual_lookup.py` | The shortcut-driven runtime, the preload policy, and the Qt composition |
| `runtime_trace.py` | Structured per-stage trace events, forwarded from the child |

**Presentation and shell**

| File | What it does |
|---|---|
| `popup.py` / `qt_popup.py` | The dictionary popup |
| `tray.py` | System tray |
| `control_center.py` | The bridge behind the window (`assets/control_center/`), which stays in the shell |
| `control_center_process.py` | The window's own process, its operation allowlist, and the proxy the page calls |
| `control_center_host.py` | One pywebview window and the loop it runs in |
| `desktop_controller.py` | Start / pause / resume state |
| `signal_bridge.py` | Ctrl+C → clean Qt shutdown |

**Updates**

| File | What it does |
|---|---|
| `update_service.py` | Obtains remote *resources*: download, verify, decompress, validate, activate, roll back |
| `update_coordinator.py` | Runs updates off the UI thread and reports progress; one operation owns it at a time |
| `app_update.py` | The *application* half: which release is newer, and the whole-bundle download → verify → extract → stage macOS and Linux still use |
| `app_update_handoff.py` | The whole-bundle swap: the native script that waits for this process to exit, replaces the installation, relaunches it, and waits to be told the new build started |
| `app_manifest.py` | What a build is made of and what a release offers: the manifest, the update metadata, the delta descriptor, and every path rule |
| `app_inventory.py` | Hashing a tree into that inventory — the producer's build, and the client's own installation |
| `app_update_plan.py` | Diffing the target against what is installed: add, replace, delete, collisions, and which payload can supply it |
| `app_update_install.py` | The Windows differential path: metadata, plan, download, selective extraction, disk preflight |
| `app_update_journal.py` | The durable record of one in-place update, the paths it owns, and the per-installation lock |
| `app_update_helper.py` | The Windows PowerShell program that applies and undoes it, depending on nothing inside the installation |
| `app_update_runner.py` | The desktop's seam: hold the lock, wait for the helper to take over, settle whatever the last run left |

### Outside the packages

| Path | What it is |
|---|---|
| `tools/krdict/` | Builds, validates, and packages the dictionary |
| `tools/smoke_packaged_runtime.py` | Proves a frozen bundle's inventory and its real providers |
| `tools/build_smoke_krdict.py` | The small dictionary that smoke installs, so a clean machine needs no release channel |
| `tools/dev_lookup.py` | Engine-only lookup rig |
| `tools/build_package.py`, `tools/release_version.py` | Release tooling: freeze the bundle, prove a tag matches the packages |
| `tools/release_build.py`, `tools/tagged_metadata.py` | The release lane's decisions — peel the tag, verify its build, classify an existing release, read the tagged identity |
| `packaging/` | PyInstaller spec, runtime hook, frozen entry point |
| `benchmarks/dev/` | Developer-only measurement harness — code, its own `tests/`, and the unwired hover `hud/`. Nothing in `packages/` imports it |
| `data/` | Local KRDICT source and build outputs. Gitignored except the README |
| `resources/dev/` | Machine-local benchmark configuration. Gitignored |
| `tests/` | Product tests for both packages, in three selectable suites: portable by default, `tests/native/` for real Qt and OS adapters, `tests/packaged/` for the frozen product |

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

## 8a. How a release is made

The dictionary is built **locally**, from the manually acquired official ZIP.
Neither that ZIP nor the raw `krdict.sqlite3` is ever a release asset, and no
workflow downloads a source archive or builds the resource.

`.github/workflows/release.yml` has two jobs around one manual step:

1. `stage` reuses the successful tag build, validates the three platform
   archives, and leaves a **private draft**. On a repeat release it also copies
   the previous public release's `hanly-resources.json` and the KRDICT `.zst` it
   names, so an application-only release needs no upload at all.
2. The operator attaches `krdict-<version>.sqlite3.zst` and
   `hanly-resources.json` to the draft, by hand, when the dictionary changed.
3. `finalize` waits on the `hanly-release` environment. After approval it
   re-resolves the tag and its build, revalidates the manifest and every
   checksum, writes `SHA256SUMS` last, and publishes exactly seven assets.

`docs/execution/first-release-plan.md` is the operator runbook.

## 9. Gates

```bash
python -m pytest
python -m ruff check packages packaging tests tools benchmarks
python -m mypy packages packaging tests tools benchmarks
```

`python -m pytest` is the full local gate. CI splits it by the machine each
suite needs — `--suite portable`, `--suite native`, `--suite packaged` — and
`packaging/README.md` says what each one requires.
