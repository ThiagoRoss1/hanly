# Hanly Desktop packaging

`hanly-desktop.spec` is the production PyInstaller definition. It builds a
platform-native **onedir** application and includes the `hanly` engine,
`hanly_app`, Control Center assets, and the native EasyOCR/torch and Qt
runtime libraries. The frozen startup hook preserves the required
OCR-before-Qt ordering.
`hanly-desktop.exe` is the whole interface: it calls `hanly_app.cli:main`, the
same function the installed `hanly` script calls, so it accepts the same flags
and opens the same area chooser. No launcher script is shipped beside it.

Build with the authoritative interpreter for the current host:

```powershell
python tools/build_package.py
```

Use `--platform windows|macos|linux` to select the explicit handoff name (the
default is the current host), and `--dry-run` to inspect the PyInstaller
command. The tool creates the release archive after a successful onedir build;
it never installs dependencies, downloads models, or contacts a remote service.

PyInstaller loads `PyQt6.QtWidgets` while analyzing a Linux build, which needs
the system `libEGL.so.1` loader. On Ubuntu 22.04 and 24.04 that loader is
provided by `libegl1`. The build workflow installs only that package, without
recommended extras, on its Linux job. A local Ubuntu builder can prepare the
same dependency with:

```bash
sudo apt-get update
sudo apt-get install --yes --no-install-recommends libegl1
```

## Artifact and resource conventions

The onedir output is written under `dist/<platform>/hanly-desktop/`. The tool
then creates one application archive at the root of `dist/`:

| Platform | Application archive |
| --- | --- |
| Windows | `hanly-desktop-windows.zip` |
| macOS | `hanly-desktop-macos.tar.gz` |
| Linux | `hanly-desktop-linux.tar.gz` |

Release tooling publishes those files under the stable
`hanly-desktop-<platform>` stem. Resource delivery is separate and uses one
asset per runtime resource under the
`krdict-<version>.sqlite3.zst` convention. The producer manifest carries the
independent resource version; it never substitutes the application tag. A
release run expects the one `krdict` asset and publishes the producer's
manifest as `hanly-resources.json` alongside it. These artifacts are not
collected from `resources/dev` or any other developer-machine cache by this
spec.

A `directory` resource must be delivered as a `.zip`: `UpdateService` unpacks it
with `zipfile` and installs every other kind as the downloaded file itself.

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
   produced resource artifacts. It finds the tag's application build itself;
   resource versions come from the resource artifact names.

```powershell
python tools/release_version.py                # print the current version
python tools/release_version.py --tag v0.1.0   # fail loudly on a mismatch
```

Step 5 stays manual because the KRDICT resource is produced and versioned
independently of the application, so a tag push cannot supply it. Everything else is derived: the release title is
`Hanly Desktop <tag>`, notes are GitHub-generated, and the application build is
selected by tag rather than by a copied run id.

## Runtime configuration

The packaged application looks for `runtime.json` beside the executable, then in
the settings directory (`%LOCALAPPDATA%\Hanly` or `~/.config/hanly`). What a
first launch then does — and where the KRDICT database comes from — is in the
root `README.md`; `docs/CODE-MAP.md` names the files that do it.

Two facts specific to a packaged build: the application embeds no resource
artifacts, so a corresponding public release must exist for first-run
acquisition to succeed, and each activated artifact's release identity is
stored as `installed_version`, so later launches skip provisioning while the
local resources remain valid.

`--runtime-config` overrides discovery and bypasses automatic configuration
creation and remote provisioning:

```powershell
dist/windows/hanly-desktop/hanly-desktop.exe --runtime-config path/to/runtime.json
```

Paths inside that JSON resolve relative to the configuration file. Remote updates
stay off until the configuration declares an `updates` block naming a release
channel, so a build with no such block never contacts GitHub.
