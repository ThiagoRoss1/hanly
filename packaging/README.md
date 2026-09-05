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
`krdict-<version>.sqlite3.zst` convention. The manifest built beside it carries
the independent resource version; it never substitutes the application tag. A
release expects exactly one `krdict` asset and publishes its
`hanly-resources.json` alongside it. These artifacts are not collected from
`resources/dev` or any other developer-machine cache by this spec.

A `directory` resource must be delivered as a `.zip`: `UpdateService` unpacks it
with `zipfile` and installs every other kind as the downloaded file itself.

## Versioning and the release flow

One product version covers both packages. It lives in
`packages/hanly-app/pyproject.toml` under `[project] version`;
`packages/hanly/pyproject.toml` carries the same value and `hanly-app` pins
`hanly==<version>`. Tags are `v{version}` — `0.1.0` publishes as `v0.1.0`.

Hanly is not published to PyPI in this flow. The version identifies a desktop
release, not a package index entry.

KRDICT is built locally from the manually acquired official ZIP. That ZIP and
the raw `krdict.sqlite3` never leave the operator's machine and are never
release assets. Only two files are attached by hand, to a draft:

- `data/generated/krdict-<resource-version>.sqlite3.zst`
- `data/generated/hanly-resources.json`

`release.yml` therefore never downloads a source archive and never builds the
resource. It runs in two halves around that manual step.

### Stage, approve, publish

1. `stage` runs automatically after a successful tag build, or manually for an
   existing tag. It resolves the tag commit, verifies the successful **Build
   Desktop Artifacts** run for that exact commit, checks the tagged package
   metadata against the tag, and creates a private **draft** holding the three
   platform archives. It never publishes and never writes `SHA256SUMS`.
2. If a previous public release exists, stage also copies that release's
   `hanly-resources.json` and the KRDICT `.zst` it references into the draft, so
   an application-only release needs no upload at all. A new application tag
   never implies the dictionary changed.
3. The operator edits the draft and attaches the two local files when KRDICT
   actually changed: exactly one `krdict-*.sqlite3.zst` and one
   `hanly-resources.json`, replacing any carried pair.
4. `finalize` waits on the `hanly-release` environment. Approving it under
   **Review deployments** re-resolves the tag and its build from scratch,
   re-downloads the three archives from that exact run, takes the resource pair
   from the draft, validates the manifest shape, filename, version, size,
   SHA-256, schema version and entry count, writes `SHA256SUMS` only once all
   five payload assets pass, uploads the six assets, asserts the draft holds
   exactly those six, and only then clears the draft flag.

A first release has no previous resource to copy, so its draft is created with
the three archives alone and waits for the operator's two files. Missing
resources fail at finalization, never at draft creation.

### Recovery, dry runs, and idempotency

Manual dispatch takes an existing tag; nothing here creates or moves a tag. A
draft this workflow staged for the same commit is not a collision — a rerun
repairs it. A draft naming another commit, an unrelated draft, a prerelease, or
an already-public release is refused, and an automatic rerun of an
already-published tag is a successful no-op.

`validate_only: true` runs the finalize half's checks against the real draft and
stops before writing: it uploads nothing, refreshes no draft asset, and
publishes nothing. It still needs the same approval, and a normal finalization
repeats every check, so a passing dry run is not treated as evidence later.

A failed validation leaves the draft intact and unpublished; no workflow deletes
one. Application artifacts expire after 14 days, so rerun the tag build before a
late recovery.

For a local pre-tag check (the publisher itself reads exact tag metadata as
data with trusted default-branch tooling):

```powershell
python tools/release_version.py                # print installed product version
python tools/release_version.py --tag v0.1.0   # check the local package/tag match
```

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
