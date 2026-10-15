# Hanly Desktop packaging

The official desktop product is a native Tauri root with React-owned windows and
a private, console-capable Python service. Rust supervises the service through
bounded JSONL pipes and hides the child console on Windows. The service keeps
the Hanly engine, desktop business rules, providers, resource acquisition, and
verified updater; it does not contain a second user-facing shell.

| Platform | Product root | Native executable | Python service |
| --- | --- | --- | --- |
| macOS | `Hanly.app` | `Contents/MacOS/hanly-desktop` | `Contents/Resources/hanly-service/` |
| Windows | `hanly-desktop/` | `hanly-desktop.exe` | `resources/hanly-service/` |
| Linux portable | `hanly-desktop/` | `hanly-desktop` | `resources/hanly-service/` |

Each Python service directory is PyInstaller onedir output with `_internal/`.
The macOS bundle also carries `hanly-update-posix` in `Contents/Resources`; the
portable Linux product carries it in `resources/`. Windows keeps its existing
PowerShell updater. Product identity remains `io.github.thiagoross1.hanly`,
and the Tauri and Python product versions continue to come from `hanly-app`.
The build inventory rejects a missing service payload or required provider
inputs and rejects collected Qt, WebEngine, pywebview, and pystray modules.

macOS products are ad-hoc signed after the service and helper are staged, then
checked with `codesign --verify --deep --strict`. The designated requirement is
the default ad-hoc one, the build's cdhash, so each rebuild or update needs
Screen Recording and Accessibility granted again. An identifier-only
requirement must not replace it: any ad-hoc code naming that identifier would
satisfy it and inherit the grants. This is an unnotarized local and release
build. Developer ID signing and notarization need separate release
credentials and configuration; the Python freezer does not force the hardened
runtime on this product.

## Build inputs a frozen service cannot fetch

A packaged Hanly verifies TLS against its bundled `certifi` store and reads its
EasyOCR weights from `hanly_app/assets/easyocr_models`, with downloading
switched off. Both are build inputs:

```bash
python tools/prepare_easyocr_models.py
```

That fetches exactly two files over HTTPS - `craft_mlt_25k.pth` and
`korean_g2.pth` - checks each against the MD5 EasyOCR 1.7.2 publishes for it,
extracts only that member from the release archive, and reuses a file that
already matches. The digest identifies the content EasyOCR itself re-checks on
load; it is not a claim of cryptographic authenticity. The spec refuses to
build without both files rather than producing a service that cannot read text.

`packaging/release-constraints.txt` pins EasyOCR, PyInstaller, and
`pyinstaller-hooks-contrib`; it is a release-build constraint file, not a lock
for the full dependency graph. Kiwi, its model data and native extension are
collected as mandatory inputs: a service missing any of them cannot perform a
lookup. Qt and webview packages are not required or collected by the service.

## Build the official product

Build on the target operating system with the matching Python, Node, and Rust
toolchains:

```bash
npm ci --prefix apps/desktop
python tools/prepare_easyocr_models.py
python tools/build_package.py
```

Use `--platform windows|macos|linux` to select the explicit product name; the
default is the current host. `--dry-run` prints the PyInstaller command.
Cross-platform builds are not supported: PyInstaller, Tauri, and the native
updater helper produce host-specific binaries. The builder stamps
`hanly_app/assets/hanly-build.json`, compiles the POSIX helper when applicable,
freezes the Python service, creates a generated Tauri resource overlay, builds
the native root, stages both payloads, verifies the complete product, and then
creates the archive and existing update metadata. The overlay lives under the
ignored `dist/` directory and is generated only after its resources exist, so
ordinary Cargo tests do not need a frozen service.

For Ubuntu release builds, install Tauri's WebKit and native build dependencies
before freezing:

```bash
sudo apt-get update
sudo apt-get install --yes --no-install-recommends \
  build-essential curl file libssl-dev libxdo-dev librsvg2-dev \
  libwebkit2gtk-4.1-dev libayatana-appindicator3-dev xvfb
```

Linux support remains the existing portable tarball. This Mac session cannot
prove Linux runtime behavior; Linux native and packaged gates must run on Linux
CI or a Linux host. Windows native packaging and updater behavior likewise
require a Windows host. Do not treat a cross-compiled executable or static test
as native validation.

## Proving the packaged product

A built Python tree is not the shipped product. Run inventory, provider, and
native-window checks against the resulting root:

```bash
python tools/smoke_packaged_runtime.py dist/macos/Hanly.app --inventory-only
python tools/build_smoke_krdict.py /tmp/hanly-smoke/krdict.sqlite3
python tools/smoke_packaged_runtime.py dist/macos/Hanly.app \
  --image tests/hanly_fixtures/assets/korean_reading_roi.png \
  --krdict /tmp/hanly-smoke/krdict.sqlite3 --expect-version 1.1.0
python tools/smoke_packaged_runtime.py dist/macos/Hanly.app --window-only
```

Inventory checks the native root and service payload without constructing
providers. The worker self-check runs through the native entry point and tests
the actual packaged service against an isolated profile; the image check also
exercises its configured OCR provider. The UI check opens the native window,
waits for React's `frontend_ready`, calls the state bridge, and exits cleanly.
A check that is unavailable on its host is not a pass, and
`HANLY_REQUIRE_PACKAGED=1` makes missing products a failure.

The packaged suite also exercises the ordinary update-ready startup path on a
test-owned copy of the product. It stages a v2 challenge and pending receipt in
an isolated per-user profile, launches the native root with
`--update-ready-v2`, and verifies the exact acknowledgement and receipt
promotion after the React page reports ready. This path does not use self-check
mode to acknowledge an update. macOS and Windows process-identity checks verify
that the native root owns the service and UI family without QtWebEngine or
pystray processes.

On POSIX, the packaged gate also runs the shipped native update helper against
disposable copies of the app. A test launcher passes an unsupported argument to
the real native root, which exits before creating a window; the helper must
reject that candidate, restore the previous executable, and leave no launcher
or root process alive. Its two-second readiness deadline is test-only data in
the helper descriptor. Windows rollback remains covered by the native
PowerShell handoff tests on Windows CI; this Mac host cannot validate that
platform's helper or process-family behavior.

The smoke harness redirects settings, home, KRDICT and OCR model paths into a
temporary profile so a developer environment cannot make a damaged bundle pass.
The dictionary is licensed and ships in neither the application nor repository.
`--krdict PATH` and `tools/build_smoke_krdict.py` provide the small local test
resource; this does not change the separately published dictionary used by a
real first launch. The model cache can be supplied explicitly for deterministic
offline runs; otherwise the cold test measures the bundle's own provisioning.

On macOS, also reconstruct the published ZIP and inspect the published disk
image separately. The ZIP must preserve the signed bundle's symlinks and
permissions; opening a DMG alone is not proof that it contains `Hanly.app`:

```bash
python tools/smoke_packaged_runtime.py \
  --from-archive dist/hanly-desktop-macos.zip \
  --reconstruct-into dist/reconstructed --reconstruct-only
python tools/smoke_packaged_runtime.py --disk-image dist/hanly-desktop-macos.dmg
python tools/smoke_packaged_runtime.py dist/reconstructed/Hanly.app --inventory-only
python tools/smoke_packaged_runtime.py dist/reconstructed/Hanly.app --window-only
```

### Product build identity

A stale bundle can pass functional checks. The embedded build stamp carries a
fresh UUID, source commit, platform, architecture, and version; release tooling
compares those values with the manifest generated from the finished tree.
`HANLY_EXPECTED_SOURCE_COMMIT` names the full commit required by the packaged
test gate and is never inferred from the checkout that runs the test:

```bash
HANLY_EXPECTED_SOURCE_COMMIT="$(git rev-parse HEAD)" \
  python -m pytest --suite packaged
```

The bundle's own `hanly-build.json`, together with its version, platform and
architecture, is the identity source. Package versions alone cannot tell two
builds of one version apart. CI stores the build's source commit explicitly;
a locally built bundle without that expected commit has incomplete source
identity evidence.

## Test suites and host requirements

`python -m pytest` remains the full local gate. Each suite is selectable because
it needs a different machine:

```bash
python -m pytest --suite portable   # no native window server or OCR runtime
python -m pytest --suite native     # desktop runtime and a window server
python -m pytest --suite packaged   # a built native root and Python service
```

| Suite | Where it lives | What it needs |
| --- | --- | --- |
| portable | everything outside the two below | root development dependencies |
| native | `tests/native/shared/`, plus `tests/native/<os>/` for this host | native desktop runtime, display, EasyOCR weights, KRDICT database |
| packaged | `tests/packaged/` | built product, native UI session, isolated appcopy for update acknowledgement |

Selection excludes a suite before its modules are imported, so portable tests
do not load platform window libraries or the OCR stack, and one platform's
native adapters are not imported on another. `ci.yml` owns portable and native
checks; `build.yml` owns frozen bundle checks and does not repeat those gates.
A capability unavailable on a developer's machine is a skip with a reason.
`HANLY_REQUIRE_NATIVE=1` and `HANLY_REQUIRE_PACKAGED=1` turn those skips into
failures in jobs whose purpose is to exercise the capability.

## What a failed packaged check leaves behind

The root self-check writes its JSON result to a file before shutdown, and the
smoke harness stores stdout and stderr separately. This leaves a report when a
native framework or OCR library aborts before the ordinary reply. Process
inventory includes the native root, Python service, WebKit/WebView2 family and
isolated lookup worker;
a denied operating-system query is reported as an error, not as an empty
process family. `tools/native_host_fingerprint.py` records the OS, CPU, core
counts and build interpreter before installation. `--with-torch` records what
Torch reports from a separate process. A host field that cannot be queried
carries its reason rather than an invented default.

```bash
python tools/native_host_fingerprint.py --context "before install" \
  --output dist/reports/hanly-host-macos.json
```

CI uploads `dist/reports/` and freezer diagnostics whether the build succeeds
or fails. These reports are evidence, not release products; a failed required
check still fails the build.

## Transition from the Qt product layout

The migration retains the application bundle identifier, product version,
user-data paths, executable stem, and existing updater. Windows and Linux keep
their established `hanly-desktop` installation root. macOS keeps `Hanly.app`;
its native root replaces the old Python UI executable and the service is staged
under `Contents/Resources/hanly-service/`. Existing user settings, logs,
resources, and update receipts remain outside the app.

The updater determines deletions from the prior installation's verified
ownership manifest or receipt. It must not remove old Qt files merely because
the new product no longer contains them. On an installation without a receipt,
the updater first proves the installed tree against the release that produced
it. Once ownership is established, the regular update plan removes only paths
the previous product owned and the Tauri product dropped. If the predecessor
cannot be established, update stops for manual installation rather than
assuming every existing file belongs to Hanly.

The native root owns update readiness. After replacement it starts the Python
service, receives the service handshake, waits for the actual React page to
report ready, and only then sends the existing host-only acknowledgement. If
that readiness is not reached, the helper restores the prior product. Windows
and POSIX helpers continue to keep their previous staging, ownership, recovery,
and rollback behavior.

## Artifact and resource conventions

Windows and Linux write the native root and `resources/` payload under
`dist/<platform>/hanly-desktop/`; macOS writes `dist/macos/Hanly.app` with the
Python service and updater helper under `Contents/Resources`. The tool then
creates the platform products at the root of `dist/`:

| Platform | Products |
| --- | --- |
| Windows | `hanly-desktop-windows.zip` |
| macOS | `hanly-desktop-macos.zip`, `hanly-desktop-macos.dmg` |
| Linux | `hanly-desktop-linux.tar.gz` |

macOS publishes two products from the one built application. The **ZIP** is
made with `ditto --keepParent`, so it holds `Hanly.app` with its symlinks and
permissions intact; it remains available to clients from before update
packages. The **DMG** is made with `hdiutil` from the same application. It is
the human-facing download and the full-tree payload referenced by the HUP
update package. Neither product modifies the built application.

A release's asset set is **derived from the update package it publishes**, not
kept as a list beside it. `python tools/release_build.py assets --package
<hup> --resource <krdict asset>` prints it, and both the staged draft and the
approved publish use exactly that.

| Asset | What it is |
| --- | --- |
| `Hanly-v<version>.hup` | the one update package: an index and one tree manifest per built platform, and no application bytes at all |
| `hanly-desktop-<platform>-<arch>-from-<base>-to-<target>.delta.zip` | one per platform, only where a verified predecessor existed |
| `hanly-desktop-windows.manifest.json` | compatibility: every managed file in the Windows build, for clients from before update packages |
| `hanly-desktop-windows.update.json` | compatibility: what such a client downloads. **Full-only** from the bridge release on |
| `krdict-<version>.sqlite3.zst`, `hanly-resources.json` | resource delivery, versioned independently of the application |
| `SHA256SUMS` | every payload's digest but its own, including the package's |

The four application products above are published unchanged. The compatibility
assets stay on **every** release while clients from before update packages are
supported: one bridge release cannot teach a client that skips it a new
protocol, so there is no finite release at which they can be dropped without
stranding somebody.

### How a release is produced

Each platform job writes its own products and, into
`dist/release/<platform>/`, a `manifest.json` and a private `descriptor.json`.
One later job reads every descriptor, proves each advertised product against
the file the run actually produced, and assembles the single package. No job
writes a fragment of the package and no release rebuilds an application.

The order inside one build matters and is the same everywhere:

1. **Stamp.** A fresh UUID, the source commit, and the target architecture go
   into the package as `hanly_app/assets/hanly-build.json`, *before* the
   freeze. On macOS it could not be otherwise: a manifest written inside
   `Hanly.app` after signing would change the seal it describes.
2. **Compile the POSIX helper**, also before the freeze, so macOS signs it with
   the bundle rather than breaking the seal by adding it afterwards.
3. **Freeze the Python service and build the Tauri root.** Stage both into
   the product and ad-hoc sign the completed macOS bundle.
4. **Windows only:** write `.hanly-manifest.json` into the tree, so the archive
   beside it carries what an older client reads.
5. **Archive** the products.
6. **Manifest and delta**, read from the finished, signed tree.

The delta's base is the previous **published** package, proved against that
release's `SHA256SUMS`, and pinned once for all three jobs. Rebuilding an old
tag produces a different tree, and a delta whose base is a build nobody has
installed applies to nothing. A release with no usable predecessor publishes no
delta and says why; that is what the first package-aware release does.

### How a Windows update replaces an installation

**The installation path never changes and no second copy of the application is
made.** Everything the update writes lives under
`<installation>/.hanly-update/<transaction>/`: the downloaded payload, the
staged files, the originals moved aside, the journal, and the file the new
build answers through. A finished or abandoned update is that one directory
being removed.

An ordinary update runs in two halves, and only the first happens while Hanly
is still open:

1. **Prepare.** Fetch `SHA256SUMS` and `Hanly-v<version>.hup` — nothing else.
   Find this machine's entry, hash the installation, establish what it is, and
   decide which files must be added, replaced, and removed. No application
   payload is downloaded before the user clicks Update now, and none is
   downloaded here either.
2. **Stage.** Download the delta the plan chose, verify it against the release's
   digest, extract only the members the plan named, verify each against the
   manifest, and write the journal. The running installation is untouched.

Then Hanly hands the transaction to `hanly-update-helper.ps1`, waits for it to
acknowledge ownership, and quits. The helper waits for every process running an
executable **inside the installation** to exit — the native root, Python service,
and isolated lookup worker — then applies the plan one file at a time: the
original is moved into `backup/`, the staged file is moved into place. It
relaunches the native root with the transaction challenge. The root acknowledges
only after its Python service handshake and frontend readiness gates pass. Only
then are the backups discarded. If it does not answer within ten minutes, every
backup goes back and the previous build is relaunched.

Four properties are worth knowing:

- **Only changed files are written.** An unchanged dependency is neither
  downloaded nor rewritten, which is most of the bundle on a patch release.
- **Files the installation does not own are never overwritten.** If something
  occupies a path the new build needs and the previous build did not own it,
  the update stops and reports the path. Equal bytes are not ownership.
- **Deletions come from ownership.** Only a path the previous build owned, and
  the new one dropped, is removed.
- **A version number is not an acknowledgement.** The challenge binds the
  transaction, a random nonce, the build's own UUID, and the manifest digest.
  A build of the right version that is not the build this update installed
  cannot produce it, and neither can a stale file from an earlier attempt.

Ownership comes from a receipt this updater wrote, kept per installation under
`%LOCALAPPDATA%\Hanly\updates\<key>\`. A fresh manual installation has none,
so its first update fetches the package of the tag it is already running and
checks every managed entry by hash before admitting ownership. If that cannot
be done, the update stops and asks for a manual install rather than guessing
which files are the product's and which are yours.

#### If an update is interrupted

This is not an atomic whole-tree replacement, so a power loss mid-apply leaves a
mixed tree. Two things make that recoverable:

- Every apply and rollback step decides from what is on disk, not from the
  record, so it replays to the same result.
- Before the first file moves, a copy of the helper and a pointer to the
  transaction are written to `%LOCALAPPDATA%\Hanly\recovery\`, outside the
  installation, with **`Finish Hanly update.cmd`** beside it. Running that
  finishes or undoes the transaction using nothing but Windows — no Hanly, no
  Python, no network. It is the route to use when the installation itself will
  not start.

When Hanly *can* start, it settles the previous transaction before anything
else initializes.

### How a macOS or Linux update replaces an installation

Neither changes an installation in place. A whole candidate is reconstructed in
one uniquely named `.hanly-update-*` directory beside the installation, proved
to be exactly the published build, and only then swapped in. Two renames are
cheaper to undo than forty, a rejected candidate is one directory to throw
away, and macOS gets the one thing it cannot get any other way: a bundle whose
signature material is reproduced rather than regenerated.

**Most of a candidate is not downloaded.** Every file the installation already
holds with the right content is copied into the candidate; only what changed
comes over the network. "Reused" means copied, not left alone — the candidate
is a real second copy, and the disk it needs is the whole product.

1. **Prepare**, exactly as Windows does: the package, the installation, the
   plan.
2. **Reconstruct.** Copy verified local content, write the payload's bytes for
   everything else, then create directories, permission bits, relative links,
   and the macOS extended attributes a published signature lives in — all from
   the manifest. Every file is hashed as it is written, wherever it came from.
3. **Prove.** Compare the candidate to the manifest entry by entry. On macOS,
   check the bundle identifier, both plist versions, and run
   `codesign --verify --deep --strict`. Nothing is ever re-signed locally.
4. **Hand off** to `hanly-update-posix`, a small C program built from
   `packaging/updater/hanly-update-posix.c` and linked against nothing but the
   system. A proved copy of it is kept outside the installation, because the
   installation path is briefly absent between the two renames.

The helper takes the installation's lock, waits for every process running out
of the installation to exit, renames the old root aside, renames the candidate
into place, relaunches the native root, and waits for its host-authorized service
acknowledgement of that transaction's challenge. The root sends it only after
the service handshake and desktop readiness gates pass. Only then is the previous
installation discarded. If it does not answer, the candidate is moved to
`rejected/`, the previous installation goes back, and it is relaunched.

**A whole product is downloaded only when a delta cannot be used**, and Hanly
asks first, with the real size. On macOS that product is the disk image: it is
attached read-only at a private mount point, the bundle is copied out with
`ditto`, and the device this process attached is detached on success, on error,
and on cancel. Nothing is ever launched from a mounted image.

What each platform allows inside an installation differs, and only there:

- **Linux** carries a person's own files across into the new installation,
  recorded separately so they never become product content.
- **macOS** stops rather than installing when `Hanly.app` contains something
  Hanly did not put there, and lists what it found. A bundle is sealed; an
  unexplained file in it is not something to carry silently into a new one.

Hanly will not update itself from a translocated copy, a read-only volume, or a
directory whose parent it cannot write to. It says so and says what to do.

#### If a POSIX update is interrupted

The installation path is briefly absent between the two renames — this is not
an atomic whole-tree exchange, and the ordinary shortcut will not repair a
missing executable. Two things make it recoverable:

- Recovery decides from what is actually on disk, not from a record written
  before a crash, and an interrupted uncommitted swap rolls back rather than
  retrying a candidate nobody watched start.
- The verified helper and a pointer to the transaction live under the per-user
  update directory, outside the installation. Running it with `--recover` and
  the transaction's descriptor finishes or undoes the transaction with no
  Hanly, no Python, and no network.

Two limitations are deliberate and known on every platform:

- **Explicit command-line arguments are not carried across an update.** A build
  relaunched by the handoff starts the way a double-click starts it. An
  installation driven with `--runtime-config` or `--app-config` needs those
  passed again after updating.
- **The handoff is not started under a supervisor.** If it cannot start at all,
  Hanly quits without being replaced; the installation is untouched and
  reopening it works.

Per-user settings, diagnostics, and the KRDICT database live outside the
installation, so an update - and a rollback - never touches them.

### Updating a Windows installation from 0.5.0 or 0.5.1

Those builds carry no inventory, and their own updater cannot exit correctly in
a windowed build (`cli._leave` raised on absent streams, so the process held a
modal crash dialog and the handoff waited out its timeout). Publishing a fixed
build does not repair the updater already installed, so **the first update from
0.5.0 or 0.5.1 is a manual replacement**, not a differential one:

1. Close Hanly.
2. Download `hanly-desktop-windows.zip` and unpack it.
3. Replace the contents of the existing `hanly-desktop` directory with the
   unpacked ones, keeping the same installation path.
4. Launch it. Settings, diagnostics, and the KRDICT database are in the
   per-user profile and are not affected.

That build carries `.hanly-manifest.json`, and every update after it is an
ordinary differential one.

### Reaching a release that publishes an update package

A client from before update packages reads the compatibility assets, which
every release keeps: it downloads the whole Windows ZIP, the macOS ditto ZIP,
or the Linux tarball, swaps it in the way it always has, and the new build
answers its version-text acknowledgement. The build it lands on carries an
identity stamp but no receipt, so its **next** update fetches the package of
the tag it is running and checks the tree against it before admitting
ownership. That first transition costs a whole download, once.

Nothing redirects an unmodified old client: not release notes, not a package,
not keeping a particular release in the archive. That is why the compatibility
assets stay on every release rather than on one bridge release.

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
   metadata against the tag, and creates a private **draft** holding the four
   application products, the Windows compatibility files, the update package
   and any deltas it indexes. It never publishes and never writes `SHA256SUMS`.
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
   SHA-256, schema version and entry count, writes `SHA256SUMS` only once every
   payload passes, uploads the asset set derived from the update package (ten
   on a release without deltas), asserts the draft holds exactly that set, and
   only then clears the draft flag.

A first release has no previous resource to copy, so its draft is created
without a resource pair and waits for the operator's two files. Missing
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
python tools/release_version.py --tag v1.1.0   # check the local package/tag match
```

## Runtime configuration

The native root and Python service preserve the established per-user settings
and runtime locations (`%LOCALAPPDATA%\Hanly` on Windows or `~/.config/hanly`
on Linux and macOS). A packaged app checks for `runtime.json` beside its
executable where that layout permits, then uses the per-user settings
directory. A macOS service does not write inside the signed, replaceable app
bundle. What first launch provisions and where KRDICT comes from is in the root
`README.md`; `docs/CODE-MAP.md` names the responsible files.

The product does not embed the licensed dictionary. A corresponding public
resource release must exist for first-run acquisition unless the operator
provides a local database through `HANLY_KRDICT_DB`. Activated resource
identities remain in the existing runtime manifest, so later launches skip
provisioning while those resources validate.

The native root accepts `--runtime-config` and `--app-config` and passes the
resolved values to its supervised service. Paths inside the runtime JSON stay
relative to that file. Remote updates remain disabled unless the configuration
declares an `updates` block naming a release channel.
