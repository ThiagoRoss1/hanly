# Hanly desktop application

Installing and launching are in the root `README.md`; what each module does is
in `docs/CODE-MAP.md`. This file covers only what is specific to consuming this
package.

## Extras

The native OCR stack is optional, so a lightweight CI install does not pull
Torch. `runtime` is what a machine that actually runs the desktop needs; `dev`
adds what the repository's developer rigs use on top of it.

```powershell
python -m pip install -e packages/hanly
python -m pip install -e "packages/hanly-app[runtime]"
```

The engine must go first: `hanly-app` depends on `hanly==0.1.0`, which exists
only in this checkout, so installing `hanly-app` on its own sends pip looking
for a package index that does not have it.

## Using the runtime as a library

`hanly_app.runtime` is the composition root that turns a JSON runtime
configuration into the real provider stack. It reads the file, asks
`ResourceManager` to validate every local resource the file names, and returns a
`HanlyRuntime` whose factories construct `EasyOCRProvider`, `KiwiProvider`, and
`KRDICTProvider` on the worker thread that will later close them.

```python
from hanly_app import load_runtime

runtime = load_runtime("path/to/runtime-config.json")
controller = runtime.create_lookup_controller(on_result)
```

Relative paths inside that JSON resolve against the directory containing it,
never against the process working directory. `tools/README.md` has the
configuration shape and a rig that runs one real lookup end to end.

## Optional remote resource delivery

Updates stay off until the configuration declares an `updates` block. A build
without one never contacts GitHub, and the engine never depends on the adapter:

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
