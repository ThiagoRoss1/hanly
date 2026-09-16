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
provided by `libegl1`. Qt's xcb platform plugin then needs the X client
libraries `libqxcb.so` and `libQt6XcbQpa` are linked against — thirteen xcb
and xkbcommon libraries the distribution owns rather than the Qt wheel. A
local Ubuntu builder prepares both with:

```bash
packages=(
  libegl1 libgl1 libfontconfig1 libx11-xcb1
  libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1
  libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-shm0
  libxcb-sync1 libxcb-util1 libxcb-xfixes0 libxcb-xkb1
  libxkbcommon-x11-0 xvfb
)
sudo apt-get update
sudo apt-get install --yes --no-install-recommends "${packages[@]}"
```

This list is not only the build machine's display stack. PyInstaller collects
a shared library only if the machine it builds on has it, so a builder missing
these freezes a Linux bundle carrying no loadable platform plugin, and the
artifact fails on every user's machine that does not happen to supply them
itself. `xvfb` is the display the frozen window check opens in.

Qt does not raise when a platform plugin will not load: it aborts the process,
so an unprepared machine used to lose the window check to SIGABRT with no
report. `hanly_app.qt_bootstrap.verify_platform_plugin` now loads that plugin
before the `QApplication` exists and names the missing library instead.

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
published ZIP, not the build directory it was made from. Reconstruction and the
disk image are separate invocations, because they check separate published
products and a ZIP that will not unpack says nothing about the DMG:

```bash
python tools/smoke_packaged_runtime.py \
    --from-archive dist/hanly-desktop-macos.zip \
    --reconstruct-into dist/reconstructed \
    --reconstruct-only
python tools/smoke_packaged_runtime.py --disk-image dist/hanly-desktop-macos.dmg
python tools/smoke_packaged_runtime.py dist/reconstructed/Hanly.app --inventory-only
python tools/smoke_packaged_runtime.py dist/reconstructed/Hanly.app --window-only
```

Mounting is not the disk-image check: a DMG that opens onto something other
than `Hanly.app` fails, because that is the download a person would find empty.

### Which source the bundle came from

A stale bundle passes every check it ever passed. Working is therefore not
evidence that an artifact is this tree's build, and one tested bundle reported
`0.1.3` beside a `0.5.0` checkout with nothing in the run saying so.

`--expect-version` makes the bundle answer for itself, from the metadata its
own interpreter collected:

```bash
python tools/smoke_packaged_runtime.py dist/windows/hanly-desktop \
    --image tests/hanly_fixtures/assets/korean_reading_roi.png \
    --krdict /tmp/hanly-smoke/krdict.sqlite3 \
    --expect-version "$(python tools/release_version.py)"
```

Both `hanly` and `hanly-app` must report that version. A mismatch fails, and so
does a report that names no version at all — a missing identity leaves the
release in the same position a wrong one does. The option is refused alongside
`--inventory-only` and `--reconstruct-only`: neither starts the executable, so
neither has anything to compare. `dist/reports/hanly-artifact-<platform>.json`
records the build commit and the source version beside the archive hashes,
because a hash says two downloads are the same file, not which source made it.

The inventory also names the two build inputs a frozen bundle cannot fetch:
`certifi/cacert.pem` and both EasyOCR weights. A bundle missing them has
working code and no way to verify a certificate or read a word.

`tests/packaged/shared/test_packaged_desktop.py` is the same gate as a test. It
uses the platform's build output (`dist/<platform>/hanly-desktop`, or
`dist/macos/Hanly.app`) by default, or the bundle named by
`HANLY_PACKAGED_APP`:

```bash
python -m pytest --suite packaged
```

## Three suites, three machines

`python -m pytest` runs everything and stays the full local gate. Each suite is
also selectable on its own, because each needs a different machine:

```bash
python -m pytest --suite portable   # no Qt, no Torch, no display
python -m pytest --suite native     # the desktop runtime and a window server
python -m pytest --suite packaged   # a frozen bundle
```

| Suite | Where it lives | What it needs |
| --- | --- | --- |
| portable | everything outside the two below | the root `dev` group only |
| native | `tests/native/shared/`, plus `tests/native/<os>/` for this host | `hanly-app[runtime]`, a display, the EasyOCR weights, a KRDICT database |
| packaged | `tests/packaged/` | a built bundle |

Selection excludes a suite **before its modules are imported**, so a portable
run never loads Qt, pywebview, or the OCR stack, and one platform's adapters
are never imported on another. A marker cannot do that: deselection by marker
happens after the import.

`ci.yml` owns the first two — a Python matrix for the portable suite plus one
native job per platform, each installing the runtime and building the
dictionary its cases read. `build.yml` owns the third and no longer repeats the
portable suite, the lint, or the type check.

A capability a developer's machine lacks is a skip with a reason. In the jobs
that exist to exercise it, `HANLY_REQUIRE_NATIVE=1` and
`HANLY_REQUIRE_PACKAGED=1` turn every one of those reasons into a failure: a
native gate that skipped everything would be a green run proving nothing.

The portable suite builds real installation trees, and two of the things a
published tree carries are the host's to give. A macOS or Linux tree is only
itself where permission bits survive being read back and a framework's symbolic
links exist, so a Windows session skips those cases rather than reading back a
tree nothing wrote. A signed build's `com.apple.cs.*` attributes are macOS's
alone - Linux refuses every namespace but `user.`, and Windows has no attribute
at all - so elsewhere a published build is simply unsigned, and the three cases
whose subject is that material are skipped. The rules a manifest applies to
those attributes are checked on every host, from entries built in memory; the
round trip through a real filesystem is a macOS one, and the portable matrix
does not run there.

## What a failed run leaves behind

A native fault ends the frozen process before it prints its report, so the exit
status used to be the whole account — and `3221225501` names no suspect. Two
things now survive that.

The self-check writes one flushed JSON line per stage boundary on **stderr**,
which the harness reads before it truncates anything. The stage that was
started and never completed is reported as `current_stage`, so a failed run
says `current_stage: ocr; exit: ILLEGAL_INSTRUCTION (0xC000001D)` rather than a
number. A crash before the first marker stays `current_stage: unknown`; naming
the last stage that passed would invent a diagnosis. Provider construction,
OCR, morphology, dictionary, closing the worker, the Qt WebEngine import, the
window itself, and each page probe all carry a marker.

Two native boundaries now say what they could not do instead of reaching into
it. The Control Center checks for a usable primary screen after Qt
initializes and before pywebview creates its window: pywebview reads the
primary screen's geometry there without checking that there is one, so a
screenless session used to fail from inside that library, under Qt's own fatal
"no screens available". The check runs after the `QApplication` exists, so it
cannot prevent an abort inside the constructor — that case stays with the
stage markers above. And the process inventory the native smokes embed raises
rather than returning nothing when the host refuses to answer: a denied `ps`
and an empty child list look identical and mean opposite things, and only one
of them is a retired child.

`tools/native_host_fingerprint.py` records what the machine actually is —
operating system and build, CPU model and vendor, core counts, the build
interpreter — before the first install, so a run that dies later still says
which host it died on. `--with-torch` adds what Torch reports about the CPU
from a subprocess of its own, since importing Torch is one of the things that
ends a packaging run. A field the host will not answer for carries the reason;
nothing is filled in with a plausible default, and neither environment
variables nor process inventories are collected.

```bash
python tools/native_host_fingerprint.py --context "before install" \
    --output dist/reports/hanly-host-macos.json
```

In CI every check states the product it needs, so one failure no longer skips
the rest. A failed worker smoke still leaves the window smoke, the archive
checks, and the artifact identity; a failed reconstruction still leaves the
disk-image evidence. The `hanly-diagnostics-<platform>` artifact is uploaded
whether or not the run succeeded, and carries `dist/reports/` — every JSON
report, the captured stdout and stderr of each smoke, and the host
fingerprints — plus PyInstaller's warning and cross-reference output. It is
never a release product, and a required failure still fails the job.

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
3. **Freeze**, and on macOS sign.
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
executable **inside the installation** to exit — the shell, the Control Center,
and the lookup child — then applies the plan one file at a time: the original is
moved into `backup/`, the staged file is moved into place. It relaunches the
build with `--update-ready-v2` and waits for it to answer that transaction's
challenge. Only then are the backups discarded. If it does not answer within ten
minutes, every backup goes back and the previous build is relaunched.

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
into place, relaunches it, and waits for it to answer that transaction's
challenge with the exact bytes the installer decided it would accept. Only then
is the previous installation discarded. If it does not answer, the candidate is
moved to `rejected/`, the previous installation goes back, and it is relaunched.

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
