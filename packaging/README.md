# Hanly Desktop packaging

`hanly-desktop.spec` is the production PyInstaller definition. Windows and
Linux build a **onedir** application; macOS wraps the same collection in
**`Hanly.app`**, whose program is `Hanly.app/Contents/MacOS/hanly-desktop`. It
includes the `hanly` engine, `hanly_app`, Control Center assets, and the native
EasyOCR/torch and Qt runtime libraries. The frozen startup hook preserves the
required OCR-before-Qt ordering.
`hanly-desktop.exe` is the whole interface: it calls `hanly_app.cli:main`, the
same function the installed `hanly` script calls, so it accepts the same flags
and opens the same window. No launcher script is shipped beside it.

The macOS bundle identifier is `io.github.thiagoross1.hanly`, and its
`CFBundleShortVersionString`/`CFBundleVersion` come from the installed
`hanly-app` metadata that `tools/release_version.py` checks against the tag.
Builds are signed ad hoc, which is what an unnotarized build can honestly
claim; a Developer ID and notarization are separate, later work. The spec names
no `codesign_identity`, and that absence is deliberate. PyInstaller ad-hoc signs
every macOS binary either way, but its `sign_binary` adds `--options=runtime`
whenever an identity is named - the ad-hoc `"-"` included - and that hardened
runtime is what an unsigned bundle cannot survive: library validation refuses to
map the bundle's own ad-hoc signed libraries into a hardened process, and the
app dies on `libpython3.13.dylib ... different Team IDs` before Python starts.
Naming no identity keeps the ad-hoc signature and drops the restriction, so the
0.x bundle needs no entitlements and carries none. It signs as
`flags=0x2(adhoc)` and passes `codesign --verify --deep --strict`.

### What Developer ID and notarization will need

Notarization requires the hardened runtime, so the entitlement question returns
then rather than now. Measured on this bundle under `--options=runtime`:

- `com.apple.security.cs.disable-library-validation` was required, and should
  stop being required once every nested binary carries one real Team ID.
- `com.apple.security.cs.allow-jit` was still required with library validation
  already disabled: QtWebEngine's V8 aborted with "Failed to reserve virtual
  memory for CodeRange" without it.
- `com.apple.security.cs.allow-unsigned-executable-memory` and
  `com.apple.security.cs.allow-dyld-environment-variables` were **not** needed
  in any configuration measured, hardened or not; PyInstaller's own PyQt6 hook
  sets `DYLD_LIBRARY_PATH` for non-`.app` builds only. Neither should be
  adopted without its own evidence.

## Build inputs a frozen bundle cannot fetch

A packaged Hanly verifies TLS against a bundled `certifi` store and reads its
EasyOCR weights from `hanly_app/assets/easyocr_models`, with downloading
switched off. Both are therefore build inputs:

```bash
python tools/prepare_easyocr_models.py
```

That fetches exactly two files over HTTPS - `craft_mlt_25k.pth` and
`korean_g2.pth` - checks each against the MD5 EasyOCR 1.7.2 publishes for it,
extracts only that one member from the release archive, and reuses a file that
already matches. The digests identify the content EasyOCR itself re-checks on
load; they are not a claim of cryptographic authenticity. The spec refuses to
build without both files rather than producing a bundle that cannot read
anything.

`packaging/release-constraints.txt` pins the three inputs that decide what a
released bundle contains - `easyocr`, `pyinstaller`, and
`pyinstaller-hooks-contrib` - and the build workflow installs with
`-c packaging/release-constraints.txt`. It is a release-build constraint file,
not a lock file for the whole dependency graph.

Morphology is collected unconditionally. `kiwipiepy`, `kiwipiepy_model`, and
the top-level `_kiwipiepy` extension are imported by name at runtime, so
PyInstaller cannot see them, and the worker warms Kiwi before reporting
readiness — a bundle without them can never look a word up. Their collection is
deliberately outside the tolerant loop that may skip an absent optional
package: failing to collect them fails the build.

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
provided by `libegl1`. The build workflow installs only what the build and the
window gate need, without recommended extras, on its Linux job. A local Ubuntu
builder can prepare the same dependencies with:

```bash
sudo apt-get update
sudo apt-get install --yes --no-install-recommends libegl1 libxcb-cursor0 xvfb
```

`libegl1` is what PyInstaller's Qt collection needs, `libxcb-cursor0` is what
Qt 6.5 and later require before the xcb platform plugin will load, and `xvfb`
is the display the frozen window check opens in. Without the cursor library Qt
does not raise: it aborts the process, so the window check dies with SIGABRT
rather than reporting a failure.

## Proving a build before it ships

A build that passes every pre-freeze gate can still be unusable: v0.1.0 did,
in two independent ways. Three checks run against the produced bundle, in this
order.

```bash
# Deterministic and offline: names any runtime dependency the build forgot.
python tools/smoke_packaged_runtime.py dist/windows/hanly-desktop --inventory-only

# Runs the executable itself on a temporary profile, outside the checkout,
# with no developer virtual environment or model cache to fall back on.
python tools/build_smoke_krdict.py /tmp/hanly-smoke/krdict.sqlite3
python tools/smoke_packaged_runtime.py dist/windows/hanly-desktop \
    --image tests/hanly_fixtures/assets/korean_reading_roi.png \
    --krdict /tmp/hanly-smoke/krdict.sqlite3

# Opens the frozen main window and makes its page call the bridge.
python tools/smoke_packaged_runtime.py dist/windows/hanly-desktop --window-only
```

The last two drive `hanly --self-check worker` and `hanly --self-check ui`,
internal modes on the same entry point rather than a second application.
`worker` loads the runtime, constructs the real providers, reads the Korean
fixture with EasyOCR, analyzes it with Kiwi, looks the word up in KRDICT, and
prints one JSON report. `ui` opens the one main window, waits for its document
and injected bridge, calls `get_state` from the page, and closes it; it needs
no runtime, because the window deliberately opens before any resource exists.
Inventory alone is not evidence of readiness, ready providers are not evidence
of a usable window, and a skipped check is not a pass.

Every run redirects the settings root, the home directory, and all three
EasyOCR model locations into a temporary profile, so no developer cache can be
what makes a check succeed. That makes the worker run *cold*: it fetches its
own models. `--model-cache DIR` copies a named EasyOCR model directory into
the isolated profile instead, which is the deterministic offline scenario.

The dictionary is redirected for the same reason and answered the same way. It
is licensed, so it ships in neither the bundle nor the repository, and a frozen
run given none provisions itself from the public release channel — an
unauthenticated GitHub API call that a hosted macOS runner is rate-limited on,
which is how one release run reached its timeout instead of a result.
`--krdict PATH` names an already-built database for the run to install through
the ordinary local-seed path, and `tools/build_smoke_krdict.py` builds a small
one carrying the words the self-check probes. What it writes is temporary and
belongs to no bundle and no artifact; the released dictionary is still the
independently published resource a real first run downloads.

On macOS the checks run against the application unpacked back out of the
published ZIP, not the build directory it was made from, and the disk image is
mounted read-only and reported on beside it:

```bash
python tools/smoke_packaged_runtime.py \
    --from-archive dist/hanly-desktop-macos.zip \
    --reconstruct-into dist/reconstructed \
    --disk-image dist/hanly-desktop-macos.dmg \
    --inventory-only
python tools/smoke_packaged_runtime.py dist/reconstructed/Hanly.app --window-only
```

The inventory also names the two build inputs a frozen bundle cannot fetch:
`certifi/cacert.pem` and both EasyOCR weights. A bundle missing them has
working code and no way to verify a certificate or read a word.

`tests/integration/test_packaged_desktop.py` is the same gate as a test. It
uses the platform's build output (`dist/<platform>/hanly-desktop`, or
`dist/macos/Hanly.app`) by default, or the bundle named by
`HANLY_PACKAGED_APP`.

## Artifact and resource conventions

Windows and Linux write a onedir tree under `dist/<platform>/hanly-desktop/`;
macOS writes `dist/macos/Hanly.app`. The tool then creates the platform's
products at the root of `dist/`:

| Platform | Products |
| --- | --- |
| Windows | `hanly-desktop-windows.zip` |
| macOS | `hanly-desktop-macos.zip`, `hanly-desktop-macos.dmg` |
| Linux | `hanly-desktop-linux.tar.gz` |

macOS publishes two products from the one built application. The **ZIP** is
made with `ditto --keepParent`, so it holds `Hanly.app` with its symlinks and
permissions intact; that is what the in-app updater downloads and installs.
The **DMG** is made with `hdiutil` from the same application and is what a
person downloads and drags to Applications. The disk image is never an update
input, and neither product modifies the built application.

A release therefore holds seven assets: four application products, one
`krdict-<version>.sqlite3.zst`, `hanly-resources.json`, and `SHA256SUMS`
(which lists the six payload digests).

### Updating from a 0.1.1 macOS installation

0.1.1 shipped `hanly-desktop-macos.tar.gz` and installed a plain directory. A
release with the new products has no such asset, so a 0.1.1 macOS build reports
the new version and says the installation updates itself outside Hanly, rather
than downloading something it cannot install. That migration is manual and
happens once: download `hanly-desktop-macos.dmg`, drag `Hanly.app` to
Applications, and remove the old directory. Settings, diagnostics, and the
KRDICT database live in the per-user profile, not inside the application, so
nothing has to be moved with it.

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
   re-downloads the four application products from that exact run, takes the
   resource pair
   from the draft, validates the manifest shape, filename, version, size,
   SHA-256, schema version and entry count, writes `SHA256SUMS` only once all
   six payload assets pass, uploads the seven assets, asserts the draft holds
   exactly those seven, and only then clears the draft flag.

A first release has no previous resource to copy, so its draft is created with
the four application products alone and waits for the operator's two files. Missing
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
