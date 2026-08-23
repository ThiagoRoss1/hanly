# Hanly Desktop packaging

`hanly-desktop.spec` is the production PyInstaller definition. It builds a
platform-native **onedir** application and includes the `hanly` engine,
`hanly_app`, Control Center assets, and the native Paddle/PaddleOCR/PaddleX and
Qt runtime libraries. The frozen startup hook preserves the required
PaddleOCR-before-Qt ordering; the application still enters through
`hanly_app.application.main` and retains the `--runtime-config` argument.

Build with the authoritative interpreter for the current host:

```powershell
python tools/build_package.py
```

Use `--platform windows|macos|linux` to select the explicit handoff name (the
default is the current host), and `--dry-run` to inspect the PyInstaller
command. The tool creates the release archive after a successful onedir build;
it never installs dependencies, downloads models, or contacts a remote service.

## Artifact and resource conventions

The onedir output is written under `dist/<platform>/hanly-desktop/`. The tool
then creates one application archive at the root of `dist/`:

| Platform | Application archive |
| --- | --- |
| Windows | `hanly-desktop-windows.zip` |
| macOS | `hanly-desktop-macos.tar.gz` |
| Linux | `hanly-desktop-linux.tar.gz` |

HAN-28/HAN-29 release tooling can publish those files under the stable
`hanly-desktop-<platform>` stem. Resource delivery is separate and uses one
asset per runtime resource under the
`hanly-resources-<resource-id>-<version>.<archive>` convention. A release run
expects the `paddle_detection_model`, `paddle_recognition_model`, and `krdict`
assets and generates their checksummed `hanly-resources.json` metadata. These
artifacts are not collected from `resources/dev`, a local PaddleX cache, or any
other developer-machine cache by this spec.

A `directory` resource must be delivered as a `.zip`: `UpdateService` unpacks it
with `zipfile` and installs every other kind as the downloaded file itself. The
manifest generator rejects any other container rather than publishing a resource
no client can activate.

## Versioning and the release flow

One product version covers both packages. It lives in
`packages/hanly-app/pyproject.toml` under `[project] version`;
`packages/hanly/pyproject.toml` carries the same value and `hanly-app` pins
`hanly==<version>`. Tags are `v{version}` — `0.1.0` publishes as `v0.1.0`.

Hanly is not published to PyPI in this flow. The version identifies a desktop
release, not a package index entry.

Releasing is semi-automatic. The human chooses the version and creates the tag:

1. Edit `version` in `packages/hanly-app/pyproject.toml`, and match it in
   `packages/hanly/pyproject.toml` and the `hanly==` pins.
2. Commit and push.
3. Create and push the matching tag, `v{version}`.
4. Pushing the tag runs the build workflow, which refuses to build if the tag
   and the product version disagree, then produces the three platform archives.
5. Dispatch the release workflow with that tag and the run id of the separately
   produced resource artifacts. It finds the tag's application build itself.

```powershell
python tools/release_version.py                # print the current version
python tools/release_version.py --tag v0.1.0   # fail loudly on a mismatch
```

Step 5 stays manual because resource archives — the Paddle models and the KRDICT
database — are produced and versioned outside this repository, so a tag push
cannot supply them. Everything else is derived: the release title is
`Hanly Desktop <tag>`, notes are GitHub-generated, and the application build is
selected by tag rather than by a copied run id.

## Runtime configuration

The packaged application looks for `runtime.json` beside the executable, then in
the settings directory (`%LOCALAPPDATA%\Hanly` or `~/.config/hanly`).
`--runtime-config` overrides both:

```powershell
dist/windows/hanly-desktop/hanly-desktop.exe --runtime-config path/to/runtime.json
```

Paths inside that JSON resolve relative to the configuration file. Remote updates
stay off until the configuration declares an `updates` block naming a release
channel, so a build with no such block never contacts GitHub.

Producing that first configuration and acquiring the resources it points at is
not yet automated — see the Wave 10 handoff for the first-run gap and its owner.
