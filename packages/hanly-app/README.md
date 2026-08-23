# Hanly desktop application

## Optional runtime dependencies

The desktop package keeps the native OCR stack optional, so installing it for
lightweight CI does not pull PaddlePaddle. Install the `runtime` extra only on a
machine that has the PaddleOCR models and native runtime available:

```powershell
python -m pip install -e "packages/hanly[concrete]"
python -m pip install -e "packages/hanly-app[runtime]"
```

The `dev` extra adds what the repository's developer rigs need on top of that:

```powershell
python -m pip install -e "packages/hanly-app[dev]"
```

## Runtime configuration

`hanly_app.runtime` is the composition root that turns a JSON runtime
configuration file into the real provider stack. It reads the file, asks
`ResourceManager` to validate every local resource the file names, and returns a
`HanlyRuntime` whose factories construct `PaddleOCRProvider`, `KiwiProvider`, and
`KRDICTProvider` on the worker thread that will later close them.

```python
from hanly_app import load_runtime

runtime = load_runtime("resources/dev/runtime.json")
controller = runtime.create_lookup_controller(on_result)
```

Relative paths in the file resolve against the directory containing it, never
against the process working directory. See `resources/dev/runtime.json` for the
canonical shape and `tools/README.md` for running a real lookup end to end.

## Desktop V1 entry point

The shipped desktop composition is available through either equivalent command:

```powershell
hanly-desktop --runtime-config path/to/runtime.json
python -m hanly_app --runtime-config path/to/runtime.json
```

Use `--app-config` to override the per-user preferences path. Startup preloads
PaddleOCR before importing Qt on Windows, then composes the worker-owned lookup
runtime, Control Center, background update coordinator, system tray, live
settings, and graceful SIGINT/shutdown lifecycle.

Remote resource delivery is optional. A runtime may configure the represented
GitHub Releases adapter without making the engine depend on it:

```json
{
  "updates": {
    "github": {
      "owner": "example",
      "repository": "hanly",
      "manifest_asset": "hanly-resources.json"
    }
  }
}
```
