# MVP Runtime / Performance Wave — Final Handoff

Branch `perf/mvp-runtime-lifecycle`, based on integrated `main` at `f508710`.
Seven commits, listed at the end. Nothing merged, nothing tagged, no release
published, Linear untouched.

The plan is `docs/execution/mvp-runtime-performance-wave.md`; the live execution
record, with per-task decisions, defects and measurements, is
`docs/execution/checkpoints/mvp-runtime-performance-wave.md`. This document is
the wave-level summary and the honest statement of what was and was not proven.

---

## What the wave was for

Hanly held around a gigabyte for a whole session whether or not it was doing
anything, took 12.5 s to become usable, and dismissed its own popup the moment
the cursor moved towards it. The measured cause was ownership, not waste:
destroying the Control Center window left ~286 MiB charged to the process, and
deleting an EasyOCR provider and closing the whole pipeline left the footprint
unchanged. Memory that a native library never returns can only be returned by
the process holding it exiting.

## What changed

**Three processes.** The persistent shell owns Qt Widgets, the tray, global
hotkeys, capture, hover state, the popup, settings, update orchestration and the
session log, and it holds the one event loop with
`setQuitOnLastWindowClosed(False)`. It imports neither Qt WebEngine nor the OCR
runtime. Two optional children do: `control_center_process.py` spawns the
window, `lookup_process.py` spawns the providers. Both use
`multiprocessing.get_context("spawn")` with an inherited `Pipe`;
`process_transport.py` is the only way they talk — explicitly pickled messages
with a checked size, serialized sends, one reader per direction, no listening
port, no dispatch by name from the wire, no shell command line.

**The bridge stayed in the shell.** `ControlCenterBridge` still owns
configuration, permissions, capture selection, updates and Quit. The page
reaches it through `ControlCenterProxy`, whose public methods are exactly
`CONTROL_CENTER_OPERATIONS`, and the parent resolves a message against that same
list rather than by `getattr`. Closing the window ends its process and nothing
else: capture, hotkeys and the popup carry on. With no usable tray there is no
way back, so that case quits deliberately rather than leaving a process nobody
can reach.

**The controller did not move.** `LookupController` still allocates request IDs,
still submits latest-wins, and still makes the final currency check on the
dispatch thread; `JobExecutor` still bounds work to one running job plus one
latest pending one. `composition.py`'s provider, cache and sensitive-retry logic
is untouched and now runs in the child. What changed is the worker at the
bottom: it sends an ROI down a pipe. A supersession is forwarded so the child
can stop between provider stages, while currency in the shell remains what
decides what is shown. A foreign exception becomes a stable error type and
message rather than a pickled library class.

**Readiness is no longer residency.** `RuntimeStatus` says whether a lookup can
happen at all; `LookupEngine.state` — sleeping, preparing, ready, error, with a
generation and the last failure — says whether the providers are loaded.
`LookupPreload` decides which a launch pays for: load while watching the screen
(the default), keep loaded, or load only for a lookup. Pause retires the engine
under every policy but Always, which is the choice that deliberately buys
residency. A manual lookup with capture off expires the engine sixty seconds
after its last completed lookup. An unexpected child exit gets one automatic
recovery per deliberate activation and then stays an error; a replacement coming
up does not refill that allowance.

**One shortcut turns hover on and off.** Both shortcuts register with the
session rather than with capture, so a denied capture permission costs no keys
and a combination another application owns costs only that combination. A manual
lookup without Screen Recording says so instead of reading the wallpaper and
reporting no Korean text. A settings change is a transaction: validate, register
with the operating system, persist, publish — and a save that fails after a
successful registration puts the previous shortcuts back, with the failure of
that too reported rather than called a success. The page shows what was actually
registered when it differs from what was asked for.

**The popup can be reached.** The engine reports the resolved word's own
geometry, not the whole recognized line, and each request's capture origin
travels with that request. While a successful answer is retained, the union of
the expanded word and the popup frame — never their hull — protects it: movement
inside captures nothing, recognizes nothing and dismisses nothing. A real exit
retires currency and arms a new dwell immediately while keeping the visible
answer for a 120 ms grace, and retention is generation-tagged so an old timer
cannot dismiss a newer answer.

**Logs and hygiene.** Records carry a timestamp, level and subsystem while the
one-line tail reads exactly as before. Rotation now bounds the file when no
backups are kept, and each record is bounded. The Control Center gained a Logs
section with level, subsystem and search filters, rendered with `textContent`,
plus refresh, copy, clear and a saved report that rewrites the user's home
directory and redacts anything reading as a credential. `owned_cleanup.py` owns
new temporary data under one marked root and reaps a directory only once its
owner is gone and it has aged, refusing symlinks and anything that does not
resolve inside its root — and preserving any staged update that still holds the
only copy of a working installation.

---

## What it costs now

Native macOS, same host and dependency set as the before baseline. MiB means
2^20 bytes; footprint is libproc `RUSAGE_INFO_V2`, RSS is `ps`, they are
different accounting measures and neither is a Windows working set. Process
counts include CPython's POSIX `multiprocessing` resource tracker, a permanent
~29 MiB process the spawn start method creates and Windows does not have.

| State | Processes | Tree footprint | Shell |
|---|---:|---:|---:|
| dormant, window closed, engine asleep | 2 | 69.3 MiB | 60.4 MiB |
| Control Center open | 4 | 383.3 MiB | 64.9 MiB |
| preparing, just after Start | 3 | 177.3 MiB | 63.3 MiB |
| capture ready, engine loaded | 3 | 895.4 MiB | 63.2 MiB |
| paused | 2 | 72.5 MiB | 63.6 MiB |
| cold manual lookup, engine woken | 3 | 1210.2 MiB | 63.5 MiB |
| after shutdown, children gone | 2 | 72.3 MiB | 63.4 MiB |

Before: full idle held 1010–1036 MiB of parent footprint, and a paused prepared
runtime held 1011 MiB.

- Startup to ready: **12.55 s → 1.44–1.78 s** with the default policy, 7.2 s
  when the user asks for the engine to be loaded at launch.
- Cold manual lookup with capture off: engine woken and ready in **5.1–6.6 s**.
- The process boundary itself: **0.5–0.8 ms** per lookup, measured against a
  cache hit in the child; cold, the executor spent 117.0 ms against the child's
  116.4 ms of pipeline.
- Hover stage timings, dwell 80 ms, cold: capture 52.6 ms, OCR 226.5 ms, token
  selection 0.06 ms, morphology 2.3 ms, dictionary 3.1 ms. These are callback
  and stage timings, not pixels-on-screen latency.

**Dwell stays at 80 ms.** 80, 40 and 20 all worked on a static fixture driven by
a scripted cursor, which is not evidence about a human hand on live text, and
the bar was a stable lower default. Saved user values are untouched.

---

## The frozen artifact

Built from a tracked-source `git archive` export with Python 3.10.20, a fresh
venv, `packaging/release-constraints.txt` and the workflow's installation order,
with the EasyOCR weights supplied as verified inputs.

- `hanly-desktop-macos.zip` 560,295,588 bytes; `hanly-desktop-macos.dmg`
  639,494,440 bytes; the `.app` is 1.3 GB.
- ZIP reconstructed, DMG mounted read-only, inventory complete with nothing
  missing, `codesign --verify --deep --strict` → `valid on disk` and
  `satisfies its Designated Requirement` (adhoc, `io.github.thiagoross1.hanly`,
  6039 sealed files).
- `--self-check worker`, run outside the checkout and the developer profile,
  read **책을 읽습니다.** through the bundled EasyOCR, analyzed 한국어 through
  Kiwi and found a dictionary entry. `--self-check ui` opened the real window,
  rendered its controls and completed a bridge round trip.
- The process split works frozen: dormant with the window open is 4 processes
  and 372.0 MiB; with the engine loaded it is 5 processes and 1153.5 MiB, of
  which the lookup child is 810.8 MiB. Ready at 2040 ms asleep, 7333 ms loaded.
  `SIGINT` retired the engine and exited cleanly. No recursive shell launch.
- The frozen build answered `--update-ready` in 3 s with `0.1.3`. That contract
  moved in this wave from "the window opened" to "the shell's loop is running",
  so it was worth proving on the real artifact.

Gates, clean constrained environment: pytest **1137 passed / 8 skipped**, Ruff
clean, mypy clean over 190 files, `pip check` clean. Gates on the working tree:
pytest **1155 passed / 3 skipped**, Ruff clean, mypy clean, `pip check` clean.

---

## What is not proven

**Global hot key delivery on macOS.** Registration is proven in both builds and
the running session reports `lookup <ctrl>+<shift>+<space>` and
`toggle_hover <ctrl>+<shift>+<f9>`. Delivery could not be proven from an
automated probe: macOS does not match a synthetic `CGEvent` against a Carbon hot
key, verified directly — a registered service with a posted ctrl+shift+space
fired nothing. Everything after the key is production code and was measured
through it. **A human key press is a pending check.**

**Frozen Control Center close and reopen by hand.** The mechanism is proven in
source by a real subprocess that opens the window in a child, lets the page call
the parent bridge across the pipe, closes it and opens a second one. The frozen
build was observed spawning and releasing the same child, but nobody clicked its
close button.

**Windows and Linux.** Nothing on either platform was run. The pending lists
below are unchanged from the plan and are the release dependency.

**Architecture documents.** `docs/architecture/01`–`04` and their visual
companions still describe a single-process desktop runtime. This wave's process
split, the engine-state model and the retained hover target are approved product
decisions for this branch, but architecture becomes authoritative only with
human approval, so those documents were deliberately not rewritten. They need an
ADR covering: the shell/child ownership boundary and its transport; engine state
as distinct from resource readiness; the preload policy matrix; and the retained
target as part of the hover contract. `docs/CODE-MAP.md` and `CLAUDE.md`, which
describe the code rather than approve it, were updated.

---

## Pending native Windows checklist

Source gates with symlink privilege; native and frozen spawn dispatch; no
recursive runtime; dormant memory and CPU; every preload policy; pause
termination; cold and warm manual lookup; toggle, rebind, conflict and rollback;
Control Center release and reopen; popup geometry on mixed DPI, where the
capture backend reports physical pixels while Qt may report logical ones and the
single conversion point in `hover_target.screen_rect` may need its scale;
logs and export; crash, parent death and shutdown; PowerShell accepted and
rejected updates including every child handle; ZIP and inventory smoke.

## Pending native Linux checklist

Native and frozen spawn; X11 mouse and hotkeys and rebinding; Control Center
release and reopen; popup interaction and multi-monitor geometry; all policies;
parent death and shutdown; frozen archive executable modes and internal
symlinks; updater accepted and rejected paths. POSIX source checks run on macOS
are macOS evidence and are labelled as such.

---

## Remaining risks

- **Word geometry scaling off macOS.** Verified 1:1 here — the capture backend's
  monitor bounds match Qt's logical geometry exactly (1408×881, device pixel
  ratio 2.0) and a captured ROI is the size of the region asked for. A scaled
  Windows display is the case that could differ; the conversion is in one named
  function with an explicit `scale` so it can be corrected there.
- **Qt teardown warning.** The Control Center child prints
  `Release of profile requested but WebEnginePage still not deleted` while it
  tears down. The child still exits and returns its memory. Recorded rather than
  suppressed.
- **A wedged child.** Every wait is bounded and stop escalates to terminate and
  kill, so shutdown cannot hang; a child that is killed mid-lookup surfaces as
  an engine error with one automatic recovery.
- **The idle expiry is not a preference.** Sixty seconds is a judgement, not a
  measurement. It only applies while capture is off.

---

## Commits

| Commit | What |
|---|---|
| `8c0d718` | the Control Center in a process the shell can retire |
| `01e10b4` | the lookup engine in a process the shell can retire |
| `7ca01a7` | when the lookup engine is loaded, as a user's choice |
| `a44a95b` | a popup the cursor can reach |
| `7de0c1d` | logs a user can read, and cleanup that refuses to guess |
| `c3b33c5` | the process split in the documentation, and child contracts |
| `35cebea` | this handoff and the completed execution record |
