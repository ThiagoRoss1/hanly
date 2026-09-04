# Developer tools

Rigs used to exercise Hanly by hand. **Nothing here ships.** Neither `hanly` nor
`hanly-app` imports this directory, and it is not part of either package.

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
  "easyocr": { "languages": ["ko"] }
}
```

Paths are relative to the configuration file's own directory, never to the
process working directory.

## Packaging and release

`build_package.py` builds the frozen desktop application,
`release_version.py` checks the product/tag version contract, and
`krdict/package_resource.py` writes the producer manifest consumed by the
release workflow.
`packaging/README.md` documents the full release flow. There are two lanes but
one public release envelope: the KRDICT producer is manual and non-publishing;
the successful application tag build publishes the app archives together with
the manifest, exact referenced KRDICT bytes, and `SHA256SUMS`.

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
default-branch tooling. A tag push never rebuilds KRDICT; dispatch the producer
only for a new independent resource identity. Its successful candidate is
retained for 90 days, subject to repository limits, while published resource
bytes are copied from the previous public release for later app-only tags.
