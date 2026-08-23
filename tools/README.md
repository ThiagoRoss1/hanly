# Developer tools

Rigs used to exercise Hanly by hand. **Nothing here ships.** Neither `hanly` nor
`hanly-app` imports this directory, and it is not part of either package.

## `dev_alpha.py`

Starts the human-testable desktop alpha through the shared manual and automatic
hover lookup composition. It prepares the local mini dictionary, validates or
discovers the named PaddleOCR model directories, sets the offline PaddleX
source-check flag, and then launches the Qt popup, hotkey, and mouse-observer
path.

### Setup

Install the concrete and desktop developer extras:

```powershell
python -m pip install -e "packages/hanly[concrete]"
python -m pip install -e "packages/hanly-app[dev]"
```

The one supported startup command is:

```powershell
python tools/dev_alpha.py
```

When startup is complete, the command reports that automatic hover is active,
prints the default manual lookup hotkey, and opens the Control Center. The
Control Center shares the alpha's Qt event loop, so hover and the manual hotkey
stay live while it is open; closing it leaves the alpha running until the Qt
application is stopped. Ctrl+C now follows the same graceful SIGINT bridge as
the production desktop path. Opening it at startup is a development affordance for
manual testing, not the final end-user lifecycle.

Developer preferences are read from and written to the gitignored
`resources/dev/app-config.json`, which is also what the Control Center edits.
The hover debounce comes from that file's `hover_delay_ms`; changes apply at
the next start.

Local preparation lives in `dev_resources.py` beside this file. Every path it
resolves is relative to this checkout, so it stays out of the shipped
`hanly_app` package; reusable database construction remains in
`hanly.krdict_build`.

Startup automatically builds the gitignored `resources/dev/krdict/krdict.sqlite3`
from the committed `resources/dev/krdict/krdict-mini.xml` when the database is
missing. It never downloads resources or overwrites `runtime.json` or a
machine-local config. The canonical config points at
`resources/dev/models/`; if those directories do not contain model files,
startup also checks the standard local PaddleX cache at
`~/.paddlex/official_models/` (or `PADDLEX_HOME/official_models/`) and uses a
disposable effective config for that run. If neither location has the named
models, startup stops with the exact directories searched and the local setup
action required.

The canonical development config disables PaddleOCR's optional document and
text-line orientation models. The launcher also sets
`PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True`, so this path does not attempt
remote model acquisition.

For the first deterministic test, display Korean text containing `책` (for
example `책을 읽습니다.`) and keep the cursor stable on `책` for automatic
lookup. The default `ctrl+shift+space` hotkey exercises the same path manually.
The mini dictionary contains `책 → book` and `읽다 → to read`; other words
normally produce a visible not-found result.

## `dev_lookup.py`

Runs one real `image → PaddleOCR → Kiwi → KRDICT → LookupResult` lookup through
the actual `LookupController` and prints the normalized result as JSON. It
exists so the real path can be verified without a disposable script. The
desktop alpha is now the normal way to see a lookup; this remains a focused
engine/runtime debugging aid.

### Setup

Install the dev extra, which adds Pillow to the optional provider runtime:

```powershell
python -m pip install -e "packages/hanly[concrete]"
python -m pip install -e "packages/hanly-app[dev]"
```

`resources/dev/krdict/krdict-mini.xml` is a hand-written two-entry file in
KRDICT's shape, not real dictionary data. The supported `dev_alpha.py` command
builds its gitignored SQLite artifact automatically; the lookup rig can reuse
that artifact for a focused engine-only check.

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
