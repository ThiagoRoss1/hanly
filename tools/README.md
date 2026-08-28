# Developer tools

Rigs used to exercise Hanly by hand. **Nothing here ships.** Neither `hanly` nor
`hanly-app` imports this directory, and it is not part of either package.

## Running the desktop

There is no separate developer launcher: the desktop starts the way a user
starts it. See the root `README.md`. `--runtime-config` points it at an
explicit configuration instead; `resources/dev/` holds benchmark
configurations, not a second way to run the app.

## `krdict/`

The production KRDICT pipeline: `inspect.py` reads the official ZIP,
`build_seed.py` builds the normalized eleven-table SQLite database,
`validate_seed.py` checks a build against its source, and `package_resource.py`
compresses and describes the release asset. Commands and the canonical source
identity live in `data/README.md`.

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
`release_version.py` reads the version a release publishes, and
`krdict/package_resource.py` writes the producer manifest consumed by the
release workflow.
`packaging/README.md` documents the full release flow.
