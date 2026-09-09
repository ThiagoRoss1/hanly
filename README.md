# Hanly

**0.1.2** — a Korean OCR popup dictionary for the desktop. Hover over Korean
text anywhere on screen and a dictionary popup tells you what the word under
the cursor means.

It reads a small region around the cursor, recognizes the text with EasyOCR,
resolves the word you are pointing at, lemmatizes it with Kiwi, and looks the
lemma up in a 56,555-entry KRDICT database. There is no continuous full-screen
scanning, and captured pixels are never written to disk or sent anywhere —
recognition and lookup both run locally.

Windows, macOS, and Linux. Python 3.10 or newer. CPU only.

---

## What you need

- **Python 3.10+**
- **A KRDICT database.** Hanly cannot start without it. It is a ~92 MB SQLite
  file built from the licensed official KRDICT source, and it is not part of
  this repository — `data/README.md` has the commands that build one.
- **Network access on first lookup**, once, so EasyOCR can fetch its Korean
  recognition models. After that Hanly runs offline.

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

Install the engine **first**. `hanly-app` depends on `hanly==0.1.2`, which
exists only in this checkout, so installing `hanly-app` on its own sends pip
looking for a package index that does not have it.

`packages/hanly` is the engine and has no required dependencies of its own. The
`[runtime]` extra on `packages/hanly-app` is what pulls the real stack —
EasyOCR, Torch, Kiwi, Qt, capture, hotkeys, tray. Several GB and a few minutes,
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

## Run it

```bash
hanly                  # the command
python -m hanly_app    # the same thing, without the script
```

The packaged executable is the same command again — regular users just
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

- **Hover** over Korean text and hold still for ~80 ms.
- **`Ctrl+Shift+Space`** looks up whatever is under the cursor right now.
- **`Ctrl+Shift+F9` / `Ctrl+Shift+F10`** start and pause watching.
- The **tray icon** starts, pauses, opens the Control Center, and quits.
  Opening it is also the icon's default action, for desktops whose tray has no
  menu at all.
- The **Control Center** is the main window: capture controls, the capture
  area, live settings, resource state, runtime readiness, diagnostics, and
  **Quit Hanly**, which is the one way out that every desktop has.
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
python tools/build_package.py
```

This produces a self-contained application under `dist/<platform>/` and the
release products at the root of `dist/`: a Windows `.zip`, a Linux `.tar.gz`,
and both a macOS `.zip` and `.dmg` containing `Hanly.app`. Run
`hanly-desktop.exe` on Windows, `hanly-desktop` on Linux, or `Hanly.app` on
macOS. Each is the same program as `hanly`, so it opens the same window and
accepts the same flags. Unpacking an archive does not put `hanly` on your PATH;
installing the Python package does.

The build bundles Python, the engine, Qt, and the OCR runtime. It does **not**
bundle the dictionary — a packaged install acquires that the same way a source
install does. `packaging/README.md` covers the build and release flow.

## The repository

| Path | What it is |
|---|---|
| `packages/hanly` | The engine: OCR orchestration, Korean linguistics, dictionary lookup, resource validation. Depends on no desktop code |
| `packages/hanly-app` | The desktop: capture, hover, hotkeys, popup, tray, Control Center, updates |
| `tools/` | Builds the dictionary; developer rigs. Ships in neither package |
| `benchmarks/dev/` | Measurement harness. Ships in neither package |
| `packaging/` | PyInstaller spec and the frozen entry point |
| `docs/` | Architecture, and `CODE-MAP.md` |

**[`docs/CODE-MAP.md`](docs/CODE-MAP.md) is where to start reading the code**:
what runs when, the startup sequence, the lookup pipeline mapped onto real
files, the provider seams, and where the dictionary comes from.

## Development

```bash
python -m pytest
python -m ruff check packages packaging tests tools benchmarks spikes
python -m mypy packages packaging tests tools benchmarks spikes
```

`tools/dev_lookup.py` runs one real `image → EasyOCR → Kiwi → KRDICT` lookup
and prints the result as JSON, without starting the desktop. `tools/README.md`
has the rigs; `benchmarks/dev/README.md` has the measurement harness.
