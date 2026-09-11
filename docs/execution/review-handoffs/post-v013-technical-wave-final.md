# Post-v0.1.3 Technical Wave — Final Handoff

Branch `codex/post-v013-technical-wave`. Two commits (`4e2301d`, `467193c`)
plus uncommitted HAN-40-continuation and HAN-41 work. Nothing merged, nothing
pushed, no release published, Linear untouched.

Per-phase detail lives in `han-42-updater-reliability.md`,
`han-40-packaged-size.md` and `han-41-idle-performance.md`; the execution
record is in `docs/execution/checkpoints/post-v013-technical-wave.md`. This
document is the wave-level summary and the honest statement of what was and
was not executed.

---

## HAN-42 — updater reliability

The in-place update was extracted into `hanly_app.app_update_handoff`: one
`UpdateTransaction` directory beside the installation holding the download, the
staged build, the backup and the readiness file, so finishing is a single
directory removal. The swap script is written to the system temp directory and
deletes itself, and paths cross as arguments rather than as generated script
text.

Fixed, against the previous `cmd.exe` batch handoff:

- the Windows relaunch resolved `hanly-desktop.exe.exe` and silently started
  nothing;
- the previous build was discarded the moment the rename returned, so a build
  that installed but could not run left the user with nothing — the new build
  must now report its own version through `--update-ready` before the backup
  goes;
- the macOS relaunch `exec`'d the program directly and produced a process with
  no Dock entry — it now goes through `/usr/bin/open`;
- a rejected build was deleted recursively rather than renamed aside;
- installation paths with spaces and non-ASCII were refused rather than handled.

**Validation.** `tests/test_app_update_handoff.py` compiles two real programs
and executes the actual swap, reading back which build started. On macOS that
covers the `darwin` and `linux` variants: verified update, rollback when the new
build never answers, a staged build that cannot be moved into place, a rollback
that itself fails, and a Hangul-and-spaces installation path. Beyond the test
suite, the real script was run three times against real signed bundles,
replacing a full baseline `Hanly.app` with each candidate and receiving the
exact `0.1.3` acknowledgement with clean transaction removal and a valid
signature.

**Remaining limitation — since closed.** The PowerShell body had never
executed. It has now: `han-42-windows-native-validation.md` records a native
Windows run of the real script against the real frozen build, in both the
accepted and the rejected direction. That run also found and fixed a rollback
defect this document could not have seen — Windows refuses to rename the
installation directory while the rejected build is still running from it, so
the restore did nothing and left the rejected build installed.

---

## HAN-40 — packaged size

Three accepted cuts, each measured on its own build before the next was layered
on, all acting at PyInstaller analysis time so nothing is stripped from a
signed bundle:

| Cut | Files | Tree bytes | ZIP on disk | DMG |
|---|---:|---:|---:|---:|
| EasyOCR collection → constrained hook | 157 | 15,725,852 | 2,943,899 | 5,292,888 |
| `ko` → `ko`,`en` (correctness, not a saving) | +1 | +368 | −388 | −64,593 |
| QtWebEngine locales → `en-US` + `ko` | 51 | 44,336,655 | 11,192,784 | 14,308,286 |
| Qt `.qm` catalogues → none | 157 | 9,459,015 | 2,720,511 | 8,068,388 |
| **Fresh baseline → final** | **364** | **69,521,154** | **16,857,582** | **27,734,155** |

4.89% of the package tree, 2.85% of the ZIP, 4.11% of the DMG on the
same-environment 3.13 comparison. The `.qm` cut removes files rather than
behaviour: nothing in the shipped process installs a `QTranslator`, so those
strings already rendered untranslated.

**Platform differences.** The real release artifact is built on Python 3.10,
which resolves smaller numpy and scipy than the developer 3.13 environment, so
the shipped ZIP is **534.28 MiB** rather than the 547.45 MiB measured during
development. Both were built from the same source.

**Deferred, with reasons.** `qtwebengine_devtools_resources.debug.pak` is
absent from every macOS artifact tested but was historically present on
Windows; that build differed in both platform and Qt version, so no
Windows-only exclusion was written from macOS evidence. The Windows OpenCV
FFmpeg DLLs are likewise a Windows-lane decision — and note the macOS linkage
evidence does not transfer, because on Windows that file is a lazily loaded
videoio plugin rather than an import-time link. `QtQuick3D` (605 KB
compressed), broader QML pruning, the non-debug devtools resource, the Torch
payload, Kiwi models and a custom OpenCV build are all recorded as
worse-risk-than-reward and out of this wave.

---

## HAN-41 — idle and lookup latency

### The reported regression was environmental

The human reported macOS felt near-instant before the branch and "much closer
to the Windows experience" after. **The branch was not the cause.** Four
orphaned Python processes — children of the ChatGPT app's `codex app-server`,
leaked by the earlier agent session that implemented the first HAN-40 block —
had been running at ~96% CPU each for **15 hours**, pinning four of this
machine's six cores. Load average was 11.3 on a 6-core box.

Removing exactly those four pids:

| Warm lookup, 192x48 ROI | p50 | p95 |
|---|---:|---:|
| With the four processes running | 96.1 ms | 136.5 ms |
| After removing them | **30.1 ms** | **44.2 ms** |

Three revisions measured against identical dependencies, isolating Hanly's own
code: branch HEAD 30.1 ms, `main` 31.7 ms, pre-macOS-fixes 31.8 ms. Identical
within noise. No file on the lookup path is touched by the branch.

### Baseline

| | |
|---|---|
| Pipeline p50 | ~30 ms, of which OCR is 98.5% |
| Everything after OCR | ~0.6 ms (token selection, Kiwi, KRDICT) |
| Hover total | ~110 ms = 80 ms dwell + ~30 ms compute |
| Hotkey total | ~30 ms + popup show |
| Frozen idle | 0.1% CPU p50, 2 processes, 50 threads, no OCR or capture loop |
| Frozen startup | window at 3,245 ms, ready at 10,102 ms |
| Release dependency set | 31.7 ms p50 / 37.2 ms p95 — same profile |

For comparison the historical Windows budget was ~287 ms total.

### Accepted optimizations: none

Both candidates were measured and rejected on their own evidence.

- **Torch thread count.** On the loaded host the default of 4 looked 29% slower
  than a single thread and lost the tail in three consecutive pairs. On a clean
  host, 1/2/4 threads give 33.4 / 30.7 / 31.9 ms — within noise. The
  cross-platform default stands. Had this been "fixed" from the loaded
  measurement, the wave would have shipped a worse default justified by a
  confident number.
- **Recognition-inclusive prewarm.** The blank prewarm never reaches the
  recognizer, so its lazy setup lands on the first lookup. Driving recognition
  during preparation buys ~13 ms on exactly one lookup for ~28 ms more
  preparation, with both figures far below the 80 ms dwell. Not material.

`hover_delay_ms` already defaults to 80 ms, the bottom of the approved range.
With compute at ~30 ms the dwell is now the majority of hover latency; lowering
it is a feel decision needing real interaction testing, and was deliberately
not taken.

---

## Tests

| Gate | Developer env (3.13) | Clean env (3.10.20) |
|---|---|---|
| `pytest` | 1,043 passed, 2 skipped | 1,020 passed, 14 skipped |
| `ruff check` | clean | clean |
| `mypy` | clean, 177 files | clean |
| `pip check` | clean | clean |

The 14 clean-environment skips are all environment-driven and correct: the
production KRDICT database is a local generated artifact (6), no frozen bundle
present at collection time (3), a Windows-specific abort code (1), opt-in real
EasyOCR inference (1), a KRDICT-dependent startup test (1), and two that need
`tomllib`. That last pair was checked rather than assumed: `tools/tagged_metadata.py`
deliberately requires 3.11+ and raises a clear error below it, and
`release.yml` pins Python 3.13 for the jobs that call it, while `build.yml`
(3.10) only calls `release_version.py`. Not a defect.

No test was skipped, xfailed or relaxed to reach green.

---

## Clean environment

Tracked files only (`git ls-files`) into a disposable tree — no `dist`, no
`.venv`, no PyInstaller cache, no developer artifacts. Fresh Python **3.10.20**
arm64 installed through pyenv, because the host had only 3.13 and packaging CI
pins 3.10. Dependencies installed the way `build.yml` installs them, under
`packaging/release-constraints.txt`.

Resolved: EasyOCR 1.7.2, Torch 2.14.0, torchvision 0.29.0, OpenCV-headless
5.0.0.93, PyQt6/WebEngine 6.11.0 with Qt 6.11.2, Kiwi 0.23.2 with model 0.23.0,
PyInstaller 6.22.2, hooks-contrib 2026.7, certifi 2026.7.22, pywebview 6.2.1,
pystray 0.19.5, mss 10.2.0, pynput 1.8.2, numpy 2.2.6, scipy 1.15.3, Pillow
12.3.0.

---

## Frozen artifacts

**macOS — actually built and validated from the clean environment.**
`Hanly.app`, `hanly-desktop-macos.zip` (560,234,863 B), `hanly-desktop-macos.dmg`
(640,532,052 B). Verified: ZIP reconstruction into an empty directory, DMG
mounted read-only, bundle inventory with no missing entries, real Korean OCR
(`책울 읽습니다.`), Kiwi (`한국어`), KRDICT lookup, Control Center with its
document title, four rendered controls and the JavaScript bridge,
`codesign --verify --deep --strict`, and a baseline-to-candidate updater
handoff. The HAN-40 cuts are confirmed in the shipped bundle: both character
files present, exactly `en-US.pak` and `ko.pak`, zero `.qm` files.

**Windows — not executed. No native host and no VM available here.** Assigned
to the GitHub Windows runner: the PowerShell handoff body, the four native
handoff tests (whose compile failure is fixed in this branch but has not run on
Windows), NTFS locking, console-less launch, and the
`qtwebengine_devtools_resources.debug.pak` question.

**Linux — not executed. No Docker, container or VM tooling on this host.**
Assigned to the GitHub Linux runner: the onedir build, tar.gz symlinks and
permissions, the Xvfb Control Center smoke, and a real frozen swap.

Using Wine or a cross-build and calling it native validation was not done and
should not be.

---

## GitHub Actions

Reviewed `build.yml`, `ci.yml` and `release.yml` semantically, not just as YAML.

**Fixed: the frozen Control Center smoke was not a gate.** `build.yml` carried
`continue-on-error: ${{ matrix.platform != 'windows' }}`, so a failed frozen
window on macOS or Linux produced a red step and a green build — and a release
could be cut from it. Its own test recorded this as meant to last "one release
before they become gates". Removed; it now gates all three platforms, and
`tests/test_ci_workflows.py` asserts the absence. Failure loses no evidence:
the step `tee`s its report to the log.

**Fixed: the Windows handoff tests could not compile.** Four tests failed
before reaching PowerShell because the harness passed paths straight into C
string macros — `-DLOG="C:\Users\runneradmin\..."` is a string of escape
sequences and `\U` is not a valid one. The harness now escapes into real C
string literals, passes the log as `as_posix()`, surfaces the compiler's stderr
instead of a bare `CalledProcessError`, and keeps the probe's own two files on
an ASCII path while the installation under test still carries spaces and
Hangul. A regression test asserts the exact failing shape. No test weakened.

**Checked and correct:** all three build jobs and the Windows test job pin
Python 3.10; the quality matrix covers 3.10–3.13; `fail-fast: false` gathers
all platform evidence; Linux installs `libegl1`, `libxcb-cursor0` and `xvfb`;
`if-no-files-found: error` on artifact retention.

**Noted, not changed:** `ci.yml` uses floating action tags (`@v7`) while
`build.yml` pins by commit SHA, and `ci.yml` installs without
`release-constraints.txt`. Neither is a functional fault; the inconsistency is
worth a decision later.

---

## Release contract

The seven assets are unchanged and enforced in both the stage and publish jobs
of `release.yml`: exactly four application archives by exact name
(`hanly-desktop-windows.zip`, `hanly-desktop-macos.zip`,
`hanly-desktop-macos.dmg`, `hanly-desktop-linux.tar.gz`), exactly one
`krdict-<version>.sqlite3.zst`, one `hanly-resources.json`, and `SHA256SUMS`
over the six payloads. Duplicates, extras and omissions each fail the job.
Nothing in this wave changed an artifact name, an archive root, the payload
layout, or the updater's asset lookup — HAN-40 changed only what goes inside
the bundle, and `tests/test_packaging.py` still guards the names.

The macOS half of that contract was rehearsed end to end from the clean
environment: source → build → archive → inventory → reconstruction → smoke →
updater consumption, using the repository's own scripts rather than a
simplified path.

---

## Post-wave cleanup

A bounded maintainability pass removed ~1,082 net lines of dead code: the
`spikes/` harnesses (1,081 lines, probing a backend retired on 2026-08-26),
a dead analyzer alias and wrapper class, an unreachable `Pandas` family
classifier, and two internal-only `__all__` entries. It also consolidated the
handoff script writer so the tests that execute a real swap now write through
the production writer — a mutation check confirms the suite now fails if the
PowerShell BOM is dropped, which it previously would not have noticed.

The last item was `EXCLUDED_MODULES` in `packaging/hanly-desktop.spec`, which
still listed `"spikes"` after that directory was deleted. Removed, with
`tests/test_packaging.py` updated to match. Verified beforehand that no
installed distribution ships a top-level `spikes` module and that none is
importable, so the entry could only ever have excluded the deleted directory.
A full clean rebuild confirms it: **4,906 files and 14,088 ZIP members, both
identical to the previous accepted build**, with the ZIP 364 bytes smaller.

**One measurement caveat found while validating that rebuild.** The DMG is
produced by `hdiutil ... -format UDZO`, which is not deterministic. Three
images built from the *byte-identical* `Hanly.app` measured 646,422,876,
634,794,643 and 639,148,336 bytes — a 1.8% spread. Every DMG figure in this
wave's handoffs sits inside that band, so DMG bytes should be read as
indicative only; the ZIP and package-tree figures remain exact and are the
ones to judge packaging changes by.

## Remaining risks

1. **Linux still has no native execution.** ~~No native Windows or Linux
   execution happened in this wave.~~ Windows is now covered — see
   `han-42-windows-native-validation.md`: a real frozen build, the Korean
   OCR/Kiwi/KRDICT and Control Center smokes, and both handoff directions ran
   on Windows 10 x64 against Python 3.10.11. Linux remains source-and-workflow
   work assigned to the runner.
2. **The Windows `debug.pak` question is answered, and the file stays.** It is
   present at 75,843,657 B, 14,716,243 B compressed in the ZIP — close to the
   ~15 MiB estimated here. Nothing was observed to attribute to it, so it was
   not removed. It remains the largest known Windows size item.
3. **Popup, hover, hotkey, tray, capture and hide/restore are not exercised in
   a frozen artifact.** They need Accessibility and Screen Recording permission
   and a human at the machine; the packaged self-check has only `worker` and
   `ui` modes. This is a pre-existing gap, not one this wave introduced, and it
   means "trigger to visible popup" is composed from measured parts rather than
   observed as pixels.
4. **The 30-minute interactive stability session was not performed** for the
   same reason. What was done instead is a bounded resident session on the
   clean frozen build — see *Stability* below — which covers memory plateau,
   thread count, idle CPU and clean shutdown, but not hover, hotkey,
   pause/resume or hide/restore.
5. **The sensitive retry costs about 2.7x a normal lookup** and was not
   measured on real text. Real-world hover feel can be worse than the fixture
   numbers whenever a first pass returns non-success.
6. **`UpdateCoordinator._handed_off` is a one-way latch.** It is set only after
   the swap script is already waiting for this process to exit, which is
   correct, but a session where the user never restarts cannot check or install
   another update until Hanly is restarted.
7. **Latency numbers are macOS arm64 on a 2-performance-core machine.** No
   Windows or Linux latency claim is made.
8. **The signature is ad hoc build validity**, not Developer ID trust or
   notarization.

---

## Stability

A 15-minute resident session on the clean frozen build, 294 samples of the
whole process tree, after a 60 s settle:

| Metric | Result |
|---|---|
| Process-tree CPU | p50 **0.1%**, max 5.6% |
| RSS | p50 23.2 MB, min 17.9, max 98.0 — flat, no growth trend |
| Processes | 2 throughout (`hanly-desktop` + one `QtWebEngineProcess`) |
| Threads | 51–55, stable |
| Shutdown | verified separately with nothing else running: no `hanly-desktop`, no `QtWebEngineProcess` left |

Memory plateaus rather than climbing, thread count is stable, idle compute is
negligible, and quitting leaves nothing behind. What this session does **not**
cover is the interactive half — hover, hotkey, pause/resume, hide/restore, a
stuck popup or a stale result — which needs permissions and a human.

One incidental but useful confirmation: the WebEngine renderer launches with
`--lang=pt` on this pt-BR host against a bundle that now ships only `en-US.pak`
and `ko.pak`. The Control Center still renders, the bridge still answers, and
nothing is logged. That is the HAN-40 locale cut exercising its fallback for
real rather than by assumption.

Two failures seen during this wave were traced to measurement contention, not
to the product: a `hdiutil ... Resource busy` unmount while two of the
developer's own Hanly DMGs were mounted, and
`test_the_desktop_opens_and_reaches_ready_without_starting_capture` failing
while the 15-minute frozen session was resident. Both pass in isolation.

---

## A measurement lesson worth keeping

A loaded host does not add noise, it inverts conclusions. On this machine with
four cores stolen, the Torch thread experiment said the shipped default was 29%
too slow and the prewarm experiment said it was worth ~85 ms. Both were
artifacts. Both would have been shipped as confident, numerically justified
regressions. Check the host before trusting a benchmark — and prefer
interleaved A/B runs over sequential ones.
