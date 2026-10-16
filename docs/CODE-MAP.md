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
  the supervised desktop service, worker threads, settings and updates.
- **`apps/desktop`** — Tauri/Rust native shell and React product surfaces.

---

## 2. Entry points — what runs when

| You run | Reaches |
|---|---|
| `hanly` or `python -m hanly_app` | `hanly_app/cli.py:main` → existing native desktop executable |
| packaged Hanly | Tauri native executable → bundled internal Python service |
| `npm run tauri -- dev` | Development-only Vite + Tauri launch |

The Python command remains `hanly`; npm builds or develops the frontend.
`cli.main` calls `multiprocessing.freeze_support()` first and forwards only
supported flags. POSIX uses `execv` so the native root keeps the launched PID.
There is no second Python UI entry point or Qt fallback.

```text
Tauri root (native windows, tray, hotkeys, activation, lifecycle)
  ├─ system webview helpers (React Control Center, popup, selector)
  └─ hanly-service (configuration, startup, capture, hover, updates)
       └─ hanly-lookup (Vision/EasyOCR, Kiwi, KRDICT)
```

The root owns a private bounded JSONL channel to its service: explicit methods,
caller-derived window identity, protocol version, correlated IDs, deadlines,
32 pending requests and 1 MiB frames. Lookup still uses `lookup/transport.py`:
an inherited duplex pipe with checked sizes, one reader and serialized sends.
There is no localhost server or production Node backend. Native root shutdown
joins service threads and retires its owned process family; updater helpers
explicitly detach because they must survive the installation they replace.

## 3. Startup and readiness

The native window opens while `service/application.py` prepares configuration,
resources and composition off the UI thread. `first_run.py` provisions KRDICT,
`runtime.py` validates resources, and `composition.py` supplies provider factories.
`service/event_loop.py` owns callbacks and independent dwell/crossing timers.

`RuntimeStatus` describes whether lookup is usable. `LookupEngine.state`
describes provider residency; `config.LookupPreload` controls prewarming.
Providers initialize and close on the lookup child's owner thread, and the
service never imports the OCR/morphology runtime during its own bootstrap.
Capture starts only through a user action, regardless of readiness or hover mode.

The root derives native monitor context and registers both shortcut edges.
Python resolves `auto` before launching the lookup child: probing a framework
from a spawned process can hang. Startup errors stay visible with retry, and
service disconnects settle pending requests before an explicit restart.

---

## 4. The lookup pipeline

```
hover (while the push chord is held, or for the whole session)
  → is the cursor still on the last answer?   hover/target.py     (if so, stop here)
  → debounce + cursor-validity check          hover/controller.py
  → read the word without pixels, if the app  acquisition/direct_text.py (+ _ax / _uia)
    exposes it (then skip capture and OCR)
  → otherwise, small ROI capture              acquisition/capture.py
  → submit, bounded / latest-wins             lookup/controller.py
  → executor thread                           lookup/executor.py
  → across the pipe into the lookup child     lookup/process.py
      → OCR                                   vision_provider.py / easyocr_provider.py
      → pick the word under the cursor        word_resolver.py
      → TextSelection (text + cursor index)   lookup_pipeline.py
      → Hangul-only gate                      language_pipeline.py
      → morphology (lemma)                    kiwi_provider.py
      → dictionary, at most five queries       krdict_provider.py
        (exact surface, surface without particles,
         whole form, components)
  → final request-currency check              lookup/controller.py
  → popup, and the word it came from retained service/application.py / hover/target.py
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

`hanly_app/updates/resource_service.py` downloads, verifies the checksum **before**
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
  → updates/coordinator.py          one operation at a time, off the UI thread
  → updates/runner.py           TreeUpdateRunner takes the installation's lock
  → updates/installer.py  prepare()
        pin the release                              ReleaseSnapshot
        SHA256SUMS → Hanly-vX.Y.Z.hup                updates/package.py (metadata only)
        this machine's entry                         stamp: updates/build_identity.py
        read the installation as a tree              app_inventory.read_tree
        establish ownership: receipt, or bootstrap against the installed tag
        decide what changes                          updates.plan.plan_tree_update
    ↳ the delta cannot be used here → show the real size, ask again
  → updates/installer.py  stage()
        download the payload the plan named, verify it
        → WindowsFileStaging   stage only the changed files      (journal)
        → PosixTreeStaging     build a whole candidate and prove it
  → hand off, then Hanly quits
        → updates/helper.py    detached PowerShell, file by file
        → updates/handoff.py   the native helper, two renames
```

### Windows: change the files that differ, in place

The installation path never changes and no second copy is made. Everything
lives under `<installation>/.hanly-update/<transaction>/`: the staged files,
the originals moved aside, the journal, and the answer the new build has to
produce. `updates/helper.py` renders the PowerShell that applies it.

### macOS and Linux: build the whole thing, then swap

`updates/tree.py` reconstructs the published build in a private directory
beside the installation - mostly out of bytes the installation already holds -
and `verify_candidate` proves it entry by entry. `updates/macos.py` adds
what only macOS needs: a disk image attached read-only at a private mount
point, `ditto`, and `codesign --verify --deep --strict` on the result. Nothing
is re-signed locally; the published signature material travels as file content
and extended attributes (`updates/xattr_macos.py` binds the four libc calls
CPython does not expose).

The swap itself belongs to `packaging/updater/hanly-update-posix.c`, a small
C program linked against nothing but the system. It has to work when the thing
it is repairing does not: the installation path is briefly absent between its
two renames, so a helper that loaded an interpreter or a script out of that
directory would be relying on the tree it is replacing.

Five rules hold the whole thing together:

- **The previous build outlives the update.** It is discarded only once the new
  one has answered that transaction's challenge - its own build UUID, a random
  nonce, and the manifest digest - which the Tauri root answers through
  `--update-ready-v2` after the service handshake and React readiness. A version number is
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
| `contracts.py` | The value types that cross every seam: `OCRResult`, `TokenAnalysis`, `DictionaryEntry`, `LookupResult`, `ROIImage`, `TextSelection`, `LexicalComponent` |
| `providers.py` | The three provider interfaces |
| `lookup_pipeline.py` | The pixel facade: ROI → `TextSelection` → `LookupResult` |
| `language_pipeline.py` | `TextSelection` → `LookupResult`; owns the Hangul-only gate, candidate selection, and the dictionary query. Knows nothing about pixels |
| `word_resolver.py` | Which word is under the cursor, including inside one line-level quad |
| `vision_provider.py` | Apple Vision adapter, the preferred recognizer on macOS |
| `easyocr_provider.py` | EasyOCR adapter, plus the sensitive-retry options |
| `kiwi_provider.py` | Kiwi adapter (surface form → lemma) |
| `krdict_provider.py` | Read-only SQLite dictionary lookup |
| `krdict_schema.py` | The KRDICT database contract |
| `resource_manager.py` | Understands *local* resources: paths, versions, schema, integrity |
| `errors.py` | Error base types |

### `packages/hanly-app` — the desktop

**Service and desktop behavior**

| File | What it does |
|---|---|
| `cli.py` | User command, bounded native flag forwarding and executable resolution |
| `service/server.py`, `service/protocol.py` | Private JSONL dispatch, framing, request authorization and shutdown |
| `service/application.py` | Qt-free composition, event-backed popup, host input adapter and bridge actions |
| `service/event_loop.py` | Serialized callbacks and cancellable dwell/crossing timers |
| `service/snapshot.py` | Active-selector-only bounded in-memory capture; no tracing or disk |
| `service/self_check.py` | Inventory, worker, OCR and UI service checks |
| `service/application.py`, `first_run.py`, `runtime.py` | Asynchronous provisioning and validated resource/provider factories |
| `composition.py` | Worker composition, caching, text-presence gates and tracing wrappers |
| `config.py`, `paths.py` | Persisted desktop preferences and per-user locations |
| `diagnostics.py` | Rotating session log, filtered tail and sanitized export |
| `control_center/bridge.py` | UI-independent state snapshots, validation and desktop business actions |
| `desktop_controller.py`, `runtime_status.py` | Capture lifecycle and readiness, separate from residency |
| `manual_lookup.py` | Qt-free lookup composition and shortcut/preload behavior |
| `hover/mouse_observer.py`, `hover/controller.py` | Cursor observation and debounce decisions |
| `hover/lookup.py`, `hover/target.py` | Acquisition/lookup coordination, retained answer and crossing grace |
| `acquisition/capture.py`, `acquisition/selection.py` | Small ROI capture, monitor plans and pure region-selection geometry |
| `acquisition/direct_text.py`, `acquisition/ax.py`, `acquisition/uia.py` | Direct-first platform acquisition, with pixel fallback |
| `permissions.py`, `permissions_darwin.py` | Required grants, native status and settings flows |
| `hotkeys.py` | Canonical shortcut validation and action contracts used by the service |
| `lookup/controller.py`, `lookup/executor.py` | Request currency and bounded latest-wins worker execution |
| `lookup/process.py`, `lookup/transport.py`, `lookup/preload.py` | Isolated providers and private lookup IPC |
| `popup/presentation.py` | UI-independent content, placement and resize/retention contracts |
| `runtime_trace.py`, `lookup/evidence.py` | Privacy-safe stage metadata and opt-in in-memory diagnostic evidence |

**Updates**

| File | What it does |
|---|---|
| `updates/resource_service.py` | Obtains remote *resources*: download, verify, decompress, validate, activate, roll back |
| `updates/coordinator.py` | Runs updates off the UI thread and reports progress; one operation owns it at a time |
| `updates/desktop_update.py` | The *application* half: which release is newer, and the whole-bundle download → verify → extract → stage macOS and Linux still use |
| `updates/handoff.py` | The whole-bundle swap: the native script that waits for this process to exit, replaces the installation, relaunches it, and waits to be told the new build started |
| `updates/manifest.py` | What a build is made of and what a release offers: the manifest, the update metadata, the delta descriptor, and every path rule |
| `updates/inventory.py` | Hashing a tree into that inventory — the producer's build, and the client's own installation |
| `updates/plan.py` | Diffing the target against what is installed: add, replace, delete, collisions, and which payload can supply it |
| `updates/installer.py` | The Windows differential path: metadata, plan, download, selective extraction, disk preflight |
| `updates/journal.py` | The durable record of one in-place update, the paths it owns, and the per-installation lock |
| `updates/helper.py` | The Windows PowerShell program that applies and undoes it, depending on nothing inside the installation |
| `updates/runner.py` | The desktop's seam: hold the lock, wait for the helper to take over, settle whatever the last run left |
| `updates/package.py` | Reads the one update package (`.hup`) a release publishes for every platform |
| `updates/build_identity.py` | Which build is running, from its stamp, and what the last update left about it |
| `updates/tree.py` | The macOS/Linux candidate: rebuild the published tree beside the installation and verify it |
| `updates/macos.py` | What only macOS needs: the private read-only disk-image mount, `ditto`, `codesign --verify` |
| `updates/xattr_macos.py` | The four libc extended-attribute calls CPython does not expose |

### Outside the packages

| Path | What it is |
|---|---|
| `tools/krdict/` | Builds, validates, and packages the dictionary |
| `tools/smoke_packaged_runtime.py` | Proves a frozen bundle's inventory and its real providers |
| `tools/build_smoke_krdict.py` | The small dictionary that smoke installs, so a clean machine needs no release channel |
| `tools/dev_lookup.py` | Engine-only lookup rig |
| `tools/build_package.py`, `tools/release_version.py` | Release tooling: freeze the bundle, prove a tag matches the packages |
| `tools/release_build.py`, `tools/tagged_metadata.py` | The release lane's decisions — peel the tag, verify its build, classify an existing release, read the tagged identity |
| `packaging/` | Internal service spec/runtime hook, native updater helper and platform bundle configuration |
| `lab/` | The developer lab: `python -m lab` runs the real desktop under observation (`session/`), `lab tour` drives it over lab-authored Korean, `report/` turns a run into a visual report; `identity.py`, `pins.py`, `comparison.py` and `storage.py` say what a run is, which runs are baselines, what a comparison may claim and what may be cleaned; `synthetic_ocr.py`, `synthetic_profiles.py`, `stage_evidence.py` and `differential.py` build and score controlled-image corpora; `resources/` attributes memory, CPU, threads, latency and I/O to stages in fresh processes, splits recorded sessions into phases and compares two experiments; plus measurement campaigns, `checks/`, its own `tests/` and the `hud/`. Nothing in `packages/` imports it |
| `data/` | Local KRDICT source and build outputs. Gitignored except the README |
| `resources/dev/` | Machine-local benchmark configuration. Gitignored |
| `tests/` | Product tests for both packages, in three selectable suites: portable by default, `tests/native/` for real desktop and OS adapters, `tests/packaged/` for the frozen product |

---


## 7a. Native shell and React

| Path | Responsibility |
|---|---|
| `apps/desktop/src/pages/` | React Control Center, popup and region selector |
| `apps/desktop/src/services/`, `src/hooks/` | Restricted bridge, subscriptions, state and structured errors |
| `apps/desktop/src-tauri/src/commands/` | Per-window authorization and parameter validation |
| `apps/desktop/src-tauri/src/lifecycle/` | Service supervision, bounded IPC and process-family cleanup |
| `apps/desktop/src-tauri/src/platform/` | Public OS adapters, monitor context and native shortcut transactions |
| `apps/desktop/src-tauri/src/windows/` | Window lifecycle, coalesced presentation and selector geometry |
| `apps/desktop/tests/`, `tests/test_desktop_service.py` | React interactions, state/contract checks and service behavior |
| `lab/session/raster_ui.py`, `raster_fonts.py` | Developer-only AppKit/Tk image windows, explicit coordinate transforms and Pillow font resolution |

Current acceptance evidence and outstanding gates live in the single
[migration checkpoint](execution/checkpoints/desktop-tauri-migration.md).
See [desktop development instructions](../apps/desktop/README.md) and
[packaging runbooks](../packaging/README.md). The updater remains the existing
receipt/challenge-based updater; it is not replaced by a Tauri plugin.

## 8. Running it from a fresh clone

```bash
python -m pip install --group dev
python -m pip install --editable packages/hanly
python -m pip install --editable "packages/hanly-app[runtime]"
hanly
```

The `runtime` extra is what pulls the real stack — EasyOCR, Torch, Kiwi and capture dependencies. Build the native shell using
`apps/desktop/README.md`; Node and Rust are development/build tools only. Several GB, mostly Torch.

**The dictionary is not in this repository.** Until the GitHub release carrying
it exists, point a fresh clone at an already-built copy:

```bash
export HANLY_KRDICT_DB=/path/to/krdict.sqlite3    # Windows: set HANLY_KRDICT_DB=...
```

A clone that already has `data/generated/krdict.sqlite3` is found without the
variable. Where EasyOCR is the recognizer, a source install downloads its models
on the first lookup, so that launch needs network access; packaged builds bundle
them, and Apple Vision needs none.

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
   checksum, writes `SHA256SUMS` last, and publishes exactly the asset set
   `tools/release_build.py assets` derives from the update package: ten on a
   release without deltas, plus one delta per platform with a verified
   predecessor.

`docs/execution/first-release-plan.md` is the operator runbook.

## 9. Gates

```bash
python -m pytest
python -m ruff check packages packaging tests tools lab
python -m mypy packages packaging tests tools lab
```

`python -m pytest` is the full local gate. CI splits it by the machine each
suite needs — `--suite portable`, `--suite native`, `--suite packaged` — and
`packaging/README.md` says what each one requires.
