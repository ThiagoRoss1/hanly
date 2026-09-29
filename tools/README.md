# Developer tools

Developer rigs, and the build, CI and release tooling the workflows run.
**Nothing here ships.** Neither `hanly` nor `hanly-app` imports this directory,
and it is not part of either package.

| Script | Used by | What it does |
|---|---|---|
| `krdict/` | developer, release operator | Builds, validates and packages the dictionary (below) |
| `dev_lookup.py` | developer | One real engine lookup from an image, printed as JSON (below) |
| `build_smoke_krdict.py` | CI, build | The three-word dictionary native tests and the packaged smoke install; refuses to overwrite anything that is not an earlier smoke build without `--replace` |
| `prepare_easyocr_models.py` | CI, build | Fetches the two EasyOCR weights a packaged Hanly carries |
| `build_package.py` | build | Freezes the desktop and writes the platform products |
| `smoke_packaged_runtime.py` | build | Proves a frozen bundle's inventory, lookup and window with only what it ships |
| `native_host_fingerprint.py` | build | Records what a packaging host actually is |
| `update_artifacts.py` | build | The manifest, delta and update package a release publishes |
| `release_version.py`, `tagged_metadata.py` | build, release | The product/tag version contract, read from the tag commit |
| `release_build.py` | release | Resolves and classifies the GitHub state a release depends on, and derives its asset set |

## Running the desktop

There is no separate developer launcher: the desktop starts the way a user
starts it. See the root `README.md`. `--runtime-config` points it at an
explicit configuration instead; `resources/dev/` holds benchmark
configurations, not a second way to run the app.

## `krdict/`

The production KRDICT pipeline: `inspect_archive.py` reads the official ZIP,
`build_seed.py` builds the normalized eleven-table SQLite database,
`validate_seed.py` checks a build against its source, and `package_resource.py`
compresses and describes the release asset. Commands and the canonical source
identity live in `data/README.md`.

`build_release_asset.py` runs those three in order under one source identity and
writes the manifest as `hanly-resources.json`, the name a release publishes. Use
it to produce a release asset by hand; the three tools stay independently
runnable for everything else.

## `dev_lookup.py`

Runs one real `image → EasyOCR → Kiwi → KRDICT → LookupResult` lookup through
the actual `LookupController` and prints the normalized result as JSON. It
exists so the engine path can be checked without the desktop UI.

### Setup

Install the concrete and desktop developer extras:

```powershell
python -m pip install -e "packages/hanly[concrete]"
python -m pip install -e "packages/hanly-app[dev]"
```

### Running

```powershell
python tools/dev_lookup.py `
  --image tests/hanly_fixtures/assets/korean_reading_roi.png `
  --config resources/dev/runtime-local.json `
  --target-x 40 --target-y 25
```

Target coordinates are image-local pixels. The rig loads the image through
Pillow, submits one normalized `ROIImage`, waits with a bounded timeout, stops
the controller, and prints JSON containing the `LookupResult` status, entries,
context, error, and diagnostics.

### Runtime configuration

`resources/dev/runtime-local.json` is gitignored and machine-local. It points at
a KRDICT database you built yourself:

```json
{
  "manifest_version": 1,
  "skip_flat_rois": true,
  "resources": {
    "krdict": {
      "kind": "krdict",
      "path": "../../data/generated/krdict.sqlite3",
      "version": "20260819-v1"
    }
  },
  "easyocr": { "languages": ["ko", "en"] }
}
```

Paths are relative to the configuration file's own directory, never to the
process working directory.

## Packaging and release

`build_package.py` builds the frozen desktop application,
`release_version.py` checks the product/tag version contract, and
`krdict/package_resource.py` writes the producer manifest consumed by the
release workflow.
`packaging/README.md` documents the full release flow. KRDICT is built locally
by the operator and attached to the staged draft by hand only when it changed;
no workflow builds or downloads it. The approved release publishes the
application products, update package and compatibility files together with the
resource manifest, the exact KRDICT bytes it names, and `SHA256SUMS`.

### `release_version.py`

The default mode reads installed package metadata for a local pre-tag check:

```powershell
python tools/release_version.py
python tools/release_version.py --tag vMAJOR.MINOR.PATCH
```

The release publisher does not use installed metadata or execute the tag tree.
It reads both tagged `pyproject.toml` files as inert data from the exact tag
commit, then passes the values to the tested data mode:

```powershell
python tools/release_version.py --tag vMAJOR.MINOR.PATCH `
  --engine-version MAJOR.MINOR.PATCH `
  --app-version MAJOR.MINOR.PATCH `
  --app-hanly-pin hanly==MAJOR.MINOR.PATCH `
  --app-hanly-concrete-pin 'hanly[concrete]==MAJOR.MINOR.PATCH'
```

The privileged publisher runs this proof with Python 3.13 and trusted
default-branch tooling. A tag push never rebuilds KRDICT; a later app-only
release carries the previous public release's resource bytes into its draft.
