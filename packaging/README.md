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
release, not a package index entry. The release topology has two independent
lanes but one public envelope: the manual KRDICT workflow stages a candidate,
and a successful application tag build publishes the three app archives plus
the manifest, exact referenced KRDICT asset, and `SHA256SUMS`.

### Application-only release

1. Bump both package versions and the `hanly-app` dependency/runtime pins.
2. Commit and push, then push the matching `vMAJOR.MINOR.PATCH` tag.
3. After the successful platform build, `release.yml` copies the previous
   public release's `hanly-resources.json` and KRDICT bytes unchanged.

Do not dispatch the KRDICT producer for an application-only change. A first
release has no previous public release and therefore needs a validated staged
KRDICT candidate.

### KRDICT candidate plus application release

1. Dispatch **Build KRDICT resource** with its approved source URL/digest and a
   new independent `resource_version`.
2. Verify its manifest, checksum, size, and validation/count report.
3. Bump/push the application tag and wait for the platform build.
4. The automatic release promotes the candidate when its producer
   `created_at` is later than the previous public release's `published_at`.

Producer artifacts are retained for 90 days, subject to repository limits. A
newer candidate that is missing, expired, or invalid fails publication rather
than silently downgrading; a changed database must use a new resource version.
Once published, later releases copy the exact resource bytes from the public
release and no longer depend on the Actions artifact.

### Recovery and first-release notes

The normal path is automatic only after `release.yml` is merged on the default
branch; `workflow_run` uses that revision. A tag pushed earlier can be
recovered manually. Manual recovery accepts the existing tag and optionally
one exact successful producer `resource_run_id`; an invalid override never
falls back. The manual-only `reuse_previous_release_resource=true` escape
requires a previous public release and is mutually exclusive with
`resource_run_id`. It records the explicit reuse decision in the job summary
and release notes.

Automatic reruns of an already-public tag are successful no-ops. Manual
duplicates, drafts, and prerelease collisions fail. A partial draft is left
untouched for an operator to repair/publish or remove before recovery; no
workflow moves tags or overwrites releases. Application artifacts expire after
14 days, so rerun the tag build before recovery if necessary.

The existing `v0.1.0` tag points at stale commit `24ed285` and must be
human-corrected before the first release. Actions never create or move it.
GitHub's `releases/latest` follows release/tag commit-date ordering rather than
publication order, so a release from an older commit may not become latest.

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
