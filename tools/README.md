# Developer tools

Rigs used to exercise Hanly by hand. **Nothing here ships.** Neither `hanly` nor
`hanly-app` imports this directory, and it is not part of either package.

## `dev_lookup.py`

Runs one real `image → PaddleOCR → Kiwi → KRDICT → LookupResult` lookup through
the actual `LookupController` and prints the normalized result as JSON. It
exists so the real path can be verified without a disposable script. Once the
popup (HAN-16) and hotkey (HAN-19) capabilities land, the application itself
becomes the way to see a lookup and this becomes a debugging aid.

### Setup

Install the dev extra, which adds Pillow to the optional provider runtime:

```powershell
python -m pip install -e "packages/hanly[concrete]"
python -m pip install -e "packages/hanly-app[dev]"
```

Build the gitignored SQLite dictionary from the tiny Korean source subset in the
repository:

```powershell
python -c "from pathlib import Path; from hanly.krdict_build import build_krdict_database; build_krdict_database(Path('resources/dev/krdict/krdict-mini.xml'), Path('resources/dev/krdict/krdict.sqlite3'))"
```

`resources/dev/krdict/krdict-mini.xml` is a hand-written two-entry file in
KRDICT's shape, not real dictionary data. It is a placeholder so this rig can
resolve a word offline until the real KRDICT dump is processed.

### Runtime configuration

`resources/dev/runtime.json` is the example configuration. Its paths are
relative to the file's own directory. Either populate the two gitignored model
directories under `resources/dev/models/`, or copy the example to the gitignored
`resources/dev/runtime-local.json` and replace the model paths with absolute
paths into an existing PaddleX cache.

The file keeps model names explicit alongside their directories, because
PaddleOCR 3.7 validates a cached directory against its model family and fails at
startup when the two disagree:

- `PP-OCRv5_mobile_det` → `models/PP-OCRv5_mobile_det`
- `korean_PP-OCRv5_mobile_rec` → `models/korean_PP-OCRv5_mobile_rec`

It also sets `enable_mkldnn` to `false`. That is a local workaround for machines
where MKL-DNN initialization is unstable, deliberately not a shipped default.

### Running

```powershell
$env:PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK = "True"
python tools/dev_lookup.py `
  --image tests/hanly_fixtures/assets/korean_reading_roi.png `
  --config resources/dev/runtime.json `
  --target-x 40 --target-y 25
```

Target coordinates are image-local pixels. The environment flag keeps PaddleX on
the explicit local model directories and disables its remote model-source
availability check, so the run is fully offline.

The rig loads the image through Pillow, submits one normalized `ROIImage`, waits
with a bounded timeout, stops the controller, and prints JSON containing the
`LookupResult` status, entries, context, error, and diagnostics.
