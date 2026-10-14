# Hanly

**1.1.0** — a Korean OCR popup dictionary for the desktop. Hover over Korean
text anywhere on screen and a dictionary popup tells you what the word under
the cursor means.

Where an application exposes its text through the platform's accessibility
interface, Hanly reads the word directly. Otherwise it captures a small region
around the cursor and recognizes it — with Apple Vision on macOS, and EasyOCR
on Windows, Linux, or wherever Vision is unavailable. Either way it resolves
the word you are pointing at, lemmatizes it with Kiwi, and looks the lemma up
in a 56,555-entry KRDICT database. There is no continuous full-screen scanning,
and captured pixels are never written to disk or sent anywhere — recognition
and lookup both run locally.

Windows, macOS, and Linux. CPU only. Packaged applications include their Python
runtime; source development requires Python 3.10+, Node and Rust.

---

## What you need

- **For source development:** Python 3.10+, Node 22.12+ and Rust 1.99.
  Packaged users install the Hanly application without these tools.
- **A KRDICT database.** Hanly cannot start without it. It is a ~92 MB SQLite
  file built from the licensed official KRDICT source, and it is not part of
  this repository — `data/README.md` has the commands that build one.
- **Network access on the first EasyOCR lookup** of a source install, once, so
  EasyOCR can fetch its Korean recognition models. Packaged builds bundle them,
  and Apple Vision is part of macOS. After that Hanly runs offline.

## Install

Clone the repository, then from its root:

```bash
python -m pip install --upgrade pip
python -m pip install --group dev
python -m pip install --editable packages/hanly
python -m pip install --editable "packages/hanly-app[runtime]"
```

**Hanly itself is not on any package index.** `--editable <path>` installs it
from the folder you just cloned — that is what these commands do, and it is why
they name directories instead of package names. The *third-party* libraries it
depends on do come from PyPI, and pip fetches them for you; there is no
`requirements.txt` because `pyproject.toml` already declares them.

Install the engine **first**. `hanly-app` depends on `hanly==1.1.0`, which
exists only in this checkout, so installing `hanly-app` on its own sends pip
looking for a package index that does not have it.

`packages/hanly` is the engine and has no required dependencies of its own. The
`[runtime]` extra on `packages/hanly-app` is what pulls the real stack —
EasyOCR, Torch, Kiwi and capture dependencies. Several GB and a few minutes,
most of it Torch.

Editable means the installed commands run this checkout's code, so `git pull`
is enough to update — no reinstall, unless dependencies changed.

## Point it at the dictionary

```bash
export HANLY_KRDICT_DB=/path/to/krdict.sqlite3     # Windows: set HANLY_KRDICT_DB=...
```

A checkout that already contains `data/generated/krdict.sqlite3` is found
without the variable.

Hanly installs the database into its own settings directory the first time it
starts — staged, checksummed, schema-validated, then activated atomically —
so the copy you point at is read once and never used directly at runtime.

Build the native shell following [desktop development](apps/desktop/README.md).
The Python command launches that existing executable; it does not compile it or
fall back to a Python UI.

## Run it

```bash
hanly                  # the command
python -m hanly_app    # the same thing, without the script
```

The packaged executable is the Tauri native desktop — regular users just
double-click it. `hanly run` is accepted too: `run` is the default and the only
verb, so it changes nothing.

Launching opens the Control Center and nothing else. Hanly prepares its
runtime behind that window — writing `runtime.json`, installing the dictionary,
and warming the providers — and reports each step there. The window stays
usable throughout, and if preparation fails it says why, points at the log, and
offers to try again.

Nothing watches the screen until you press **Start capture**. Where Hanly looks
is a setting: **Select capture area…** offers a whole monitor or a region you
drag, and the choice is saved for next time. Cancelling changes nothing.

First start takes a few seconds longer, because the dictionary has to be
installed and validated. Later starts skip the install.

### Using it

Three global shortcuts, and each one does exactly one thing:

- **`Ctrl+Shift+F10`** starts and stops watching the screen. Stopping gives the
  lookup engine's memory back; nothing is watched until you start again.
- **`Ctrl+Shift+Space`** is **Push to Hover**: hold it, and hovering over
  Korean text for ~80 ms looks the word up. Let go and Hanly stops looking.
  An answer already on screen stays until you move away from its word, so you
  can read it, click it, and copy from it with the keys released.
- **`Ctrl+Shift+F9`** pauses and continues hover without stopping capture. It
  matters in **Whenever capture is running** mode, where hover has no key to
  let go of; in Push to Hover the chord is already the switch.

Every shortcut can be changed under **Settings → Shortcuts**, and the Control
Center says so when the operating system refused one. On a Mac keyboard the
top row sends brightness and media keys by default, so the two function-key
chords arrive only while you hold **Fn**, or with *Use F1, F2, etc. keys as
standard function keys* turned on — or pick different shortcuts.

The popup is operated with the pointer. Its buttons deliberately take no
keyboard focus, because focusing them would pull Hanly in front of the
application you are reading.

- The **tray icon** starts, stops, opens the Control Center, and quits.
  Opening it is also the icon's default action, for desktops whose tray has no
  menu at all.
- The **Control Center** is the main window: capture controls, the capture
  area, live settings (including the text recognizer: Automatic, Apple Vision
  where macOS provides it, or EasyOCR), resource state, runtime readiness,
  diagnostics, and **Quit Hanly**, which is the one way out that every desktop
  has.
- Closing the window hides it while the tray can bring it back. Without a tray
  that can, it stays open instead, so Hanly is never running out of reach.

### Options

| Flag | What it does |
|---|---|
| `--runtime-config PATH` | Use an explicit runtime configuration instead of the per-user one. Bypasses first-run provisioning entirely |
| `--app-config PATH` | Use an explicit preferences file |
| `--roi WIDTHxHEIGHT` | Change the capture region size, for comparing detection areas |

Per-user files live in `%LOCALAPPDATA%\Hanly\` on Windows and
`~/.config/hanly/` elsewhere: `runtime.json` (resources and providers),
`config.json` (preferences), `resources/` (the installed dictionary), and
`logs/hanly.log` (a rotating session log the Control Center links to).

Installing the Python package puts `hanly` on your PATH. Extracting a portable
archive does not: run the executable from where you unpacked it. Both are the
same program with the same behaviour.

## Build the desktop application

```bash
npm ci --prefix apps/desktop
python tools/prepare_easyocr_models.py
python tools/build_package.py
```

Build on the platform you intend to ship; the native root, Python service and
updater helper are host binaries. The coordinated build produces a Tauri
application with its React assets and frozen Python service under `dist/`, then
creates the existing Windows ZIP, Linux tarball, and macOS ZIP and DMG. The
native executable is `hanly-desktop.exe` on Windows, `hanly-desktop` in the
Linux product, and `Contents/MacOS/hanly-desktop` inside `Hanly.app` on macOS.
All three use the same native application and preserve the existing app identity
and user-data paths.

The product bundles Python, the engine, providers and OCR models. It does not
bundle the licensed KRDICT database; first-run provisioning acquires and
validates it through the existing resource flow. The production UI is Tauri and
React. Lab fixtures render with Pillow in native AppKit windows on macOS and
Tk windows on Windows/Linux; neither the product nor Lab needs Qt. The product
build and updater release flow are documented in
[`packaging/README.md`](packaging/README.md).

## The repository

| Path | What it is |
|---|---|
| `packages/hanly` | The engine: OCR orchestration, Korean linguistics, dictionary lookup, resource validation. Depends on no desktop code |
| `packages/hanly-app` | Qt-free Python desktop service: capture, hover and lookup coordination, settings, resources, diagnostics and verified updates |
| `apps/desktop` | Tauri/Rust native root and React Control Center, popup and region selector |
| `tools/` | Builds the dictionary; developer rigs. Ships in neither package |
| `lab/` | The developer lab: `python -m lab` runs Hanly under observation and reports. Ships in neither package |
| `packaging/` | Frozen Python service spec, updater helpers and product build/release tooling |
| `docs/` | Architecture, `CODE-MAP.md`, and execution history; `docs/README.md` is the index |

**[`docs/CODE-MAP.md`](docs/CODE-MAP.md) is where to start reading the code**:
what runs when, the startup sequence, the lookup pipeline mapped onto real
files, the provider seams, and where the dictionary comes from.

## Development

```bash
python -m pytest
python -m ruff check packages packaging tests tools lab
python -m mypy packages packaging tests tools lab
```

`python -m pytest --suite portable` selects tests that need no native window
server or OCR runtime. `--suite native` exercises host desktop behavior and
`--suite packaged` checks a freshly built product. Lab's native raster fixtures
use Pillow with AppKit on macOS and Tk on Windows/Linux. The desktop runtime
provides the macOS frameworks; other hosts need a Python build with Tk support.

See [`packaging/README.md`](packaging/README.md) for host requirements and
packaged validation details. Build the frontend with `npm`. From
`apps/desktop`, `npm run tauri -- dev` starts the Vite development workflow;
the `hanly` command launches an already-built native root and never builds one
automatically.

`tools/dev_lookup.py` runs one real `image → EasyOCR → Kiwi → KRDICT` lookup
and prints the result as JSON, without starting the desktop. `tools/README.md`
has the rigs; `lab/README.md` has the developer lab.
