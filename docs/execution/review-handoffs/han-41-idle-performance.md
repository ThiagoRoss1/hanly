# HAN-41 Idle and Lookup Latency Review Handoff

## Bundle

- Member issues: HAN-41 (Phase 3 of
  `docs/execution/post-v013-technical-wave.md`)
- Implementation ecosystem: Claude Opus, directly
- Date: 2026-09-10
- Branch: `codex/post-v013-technical-wave`, on top of `467193c`
- Uncommitted working-tree state. Nothing pushed, no PR, Linear untouched.

## The reported regression, and what it actually was

The human reported that macOS "felt almost instantaneous" before the
HAN-42/HAN-40 branch work and afterwards felt "much closer to the Windows
experience".

**The cause was environmental, not code.** Four orphaned Python processes were
running at ~96% CPU each, continuously, for **15 hours** — pinning four of this
machine's six cores. They were children of the ChatGPT app's `codex app-server`
(pid 33818), leaked by the earlier agent session that implemented the first
HAN-40 block, running out of the HAN-40 build venv with the Hanly checkout as
their working directory. They were stuck reading from stdin, producing nothing.
Load average was 11.3 on a 6-core machine.

Removing exactly those four pids (nothing else) restored the machine:

| Warm lookup pipeline, 192x48 ROI, source | p50 | p95 |
|---|---:|---:|
| While the four processes were running | 96.1 ms | 136.5 ms |
| After removing them | **30.1 ms** | **44.2 ms** |

That is a **3.2x** difference in warm OCR, on identical code. Every user-facing
symptom the human described follows from it, and so does "it feels like
Windows": the machine had lost most of its compute.

### The branch is not responsible

Three revisions were measured against the *same* interpreter and the *same*
installed dependencies, by putting each worktree's sources ahead of the
editable installs on `PYTHONPATH`. The only variable is Hanly's own code:

| Revision | p50 | p95 |
|---|---:|---:|
| `467193c` — branch HEAD (HAN-42 + HAN-40) | 30.1 ms | 44.2 ms |
| `ed51a6a` — `main`, before the branch | 31.7 ms | 34.0 ms |
| `337a346` — before the recent macOS fixes | 31.8 ms | 37.7 ms |

Identical within noise. Supporting evidence: no file on the lookup path
(`hover_controller`, `mouse_observer`, `qt_hover_scheduler`, `capture`,
`composition`, `lookup_controller`, `job_executor`, `easyocr_provider`,
`manual_lookup`) is touched by the branch at all. `application.py`'s only
change threads an optional `on_started` callback that is `None` on every launch
that is not an update handoff, and the `update_coordinator` changes add no
periodic or per-lookup work. The macOS popup commits on `main` *removed*
`raise_()` and do their one native call once per widget, in `__init__`.

**Measurement lesson worth keeping:** a loaded machine does not merely add
noise, it inverts conclusions. See the thread-count experiment below.

## Current latency baseline (macOS, clean machine)

Source runtime, real resident providers, 192x48 ROI, 40 samples:

| Stage | p50 |
|---|---:|
| OCR | 29.4 ms |
| Token selection | 0.06 ms |
| Morphology (Kiwi) | 0.27 ms |
| Dictionary (KRDICT) | 0.28 ms |
| **Total pipeline** | **~30 ms** |

OCR is 98.5% of the pipeline; everything after it costs about 0.6 ms together,
which matches the historical report and means there is nothing to win outside
OCR.

Trigger to visible popup, composed from the measured parts:

| Path | Dwell | Compute | Total |
|---|---:|---:|---:|
| Hover | 80 ms (`hover_delay_ms` default) | ~30 ms | **~110 ms** |
| Manual hotkey | none | ~30 ms | **~30 ms** + popup show |

For comparison, `docs/execution/reports/ocr-latency-and-roadmap.md` recorded a
~287 ms total budget (150 ms dwell + ~120 ms OCR) on Windows. The macOS figure
is now well inside that.

First lookup after readiness costs ~48 ms rather than ~30 ms; frozen startup
reaches a visible window at 3,245 ms and full readiness at 10,102 ms.

## Idle

Frozen macOS build, Control Center visible, before Start Capture. 45 s settle,
120 s measured, 40 samples of the whole process tree:

| Metric | Result |
|---|---|
| Process-tree CPU | p50 **0.1%**, max 2.3% |
| Processes | 2 (`hanly-desktop` + one `QtWebEngineProcess`) |
| Threads | 50, stable |
| RSS | p50 25.6 MB as reported by `ps` |
| OCR invocations | 0 |
| Capture invocations | 0 |
| Network | none after the startup resource check |
| After quit | no `hanly-desktop` and no `QtWebEngineProcess` left |

There is no idle OCR loop, no capture loop, and no process leak. The RSS figure
is what `ps` reports for an idle process on a machine that had been under
memory pressure; treat it as "not growing", not as the working set of a warm
Torch. Memory was stable across the whole window.

## Accepted changes

**None to the runtime.** Every performance candidate measured this phase was
rejected on its own evidence — see below. The two changes made are a test-harness
fix and a CI gate, both described under *Wave items fixed here*.

## Rejected experiments, with evidence

### Torch thread count — kept at the existing default

`default_cpu_threads()` yields `min(4, cores - 1)` = 4 on this 2-performance /
4-efficiency-core machine.

| Threads | Loaded machine p50/p95 | **Clean machine p50/p95** |
|---|---:|---:|
| 1 | 86.4 / 101.2 ms | 33.4 / 35.8 ms |
| 2 | 92.1 / 134.7 ms | **30.7 / 33.1 ms** |
| 4 (default) | 111.7 / 143.6 ms | 31.9 / 36.6 ms |
| 6 | 119.7 / 261.8 ms | not re-run |

On the loaded machine the default looked 29% slower than a single thread, and
one thread won the tail in three consecutive pairs. That reading was an
artifact of four stolen cores. On a clean machine the three values are within
noise of one another. **No change**, and no new user-facing option: changing a
cross-platform default to chase a number produced on a broken host would have
been the wrong call, and the Windows evidence behind the cap still stands.

### Recognition-inclusive prewarm — rejected as immaterial

`prewarm()` runs one `recognize()` on an all-zero 96x32 image. CRAFT finds no
boxes on a blank, so the recognizer is never invoked and its lazy setup lands
on the first real lookup. Driving the recognizer directly during preparation
(`Reader.recognize` on a tiny grey box with an explicit line box, no network,
no external file, same reader) was measured three times each way on the clean
machine:

| | Blank prewarm (shipped) | Recognition-inclusive |
|---|---:|---:|
| First real lookup | 46.7 / 72.8 / 48.3 ms | 49.4 / 34.8 / 34.3 ms |
| Warm p50 | 30.8 / 31.3 / 30.4 ms | 30.2 / 29.6 / 29.3 ms |
| Extra preparation cost | — | 36.7 / 27.6 / 24.2 ms |

It buys roughly 13 ms on exactly one lookup, for ~28 ms of extra preparation,
and changes warm latency not at all. Both first-lookup figures are far below
the 80 ms dwell the user is already waiting through. Not material; **not
adopted**. On the *loaded* machine the same experiment showed an ~85 ms gain,
which is the same trap as the thread count.

### Hover dwell — measured and left alone

`hover_delay_ms` already defaults to **80 ms**, the bottom of the approved
80–250 ms range, and is user-configurable. With compute at ~30 ms the dwell is
now the majority of hover latency, but it is the deliberate anti-spam bound, not
overhead. Lowering it further is a product/feel decision needing real
interaction testing, not a benchmark; recorded as an option, not taken.

### Not investigated, deliberately

Kiwi (0.27 ms), the dictionary (0.28 ms), token selection (0.06 ms), the
capture backend, and the Qt signal-bridge pulse. Together the whole
post-OCR chain is ~0.6 ms of a ~30 ms pipeline; the idle measurement shows
0.1% CPU, so the 100 ms pulse is not costing anything measurable. Optimizing
any of them cannot move the product.

## Wave items fixed here

### The Windows CI failure in `tests/test_app_update_handoff.py`

Four Windows handoff tests failed before reaching PowerShell because the C
probe would not compile. The harness passed paths straight into C string
macros: `-DLOG="C:\Users\runneradmin\...\launched.txt"` is a string of escape
sequences, and `\U` is not a valid one.

Fixed in the harness, not by weakening the tests:

- `_c_string()` escapes backslashes and quotes into a real C string literal,
  and the log path is passed as `as_posix()` so there is nothing left to
  escape. Guarded by `test_a_windows_path_survives_being_compiled_into_the_probe`,
  which asserts the exact failing shape.
- A failed compile now raises with the command and the compiler's own stderr
  instead of a bare `CalledProcessError`.
- The probe's own two files (its log and the readiness file) moved to an ASCII
  `probe_root`. The C probe receives paths through a compile-time macro and an
  ANSI `argv` on Windows, so it only ever handles ASCII; the installation under
  test still carries spaces and Hangul, and the test now asserts that. What the
  handoff renames, relaunches and cleans up is still the awkward path.

No test was skipped, xfailed or relaxed. 24 pass on macOS, which runs the
`darwin` and `linux` handoff variants; the `win32` variant remains for the
Windows runner.

### The Control Center smoke was not a gate

`build.yml` carried `continue-on-error: ${{ matrix.platform != 'windows' }}` on
"Smoke the frozen Control Center", so a failed frozen window on macOS or Linux
produced a red step and a green build. Its own test said this was meant to last
"one release before they become gates". Removed; the smoke now gates on all
three platforms, and `tests/test_ci_workflows.py` asserts the absence rather
than the expression. Evidence is not lost on failure: the step `tee`s its
report to the log.

## Validation

- Full suite **1,042 passed, 2 skipped**; Ruff clean; mypy clean across 177
  source files; `pip check` clean. Re-run in the clean Python 3.10 environment
  as well — see the wave handoff.
- Benchmark evidence under the session scratchpad, **expired and no longer
  retrievable; every figure above is inline here**: `bench/clean-*` (thread
  sweep and per-revision runs), `bench/threads-*` and `bench/confirm-*` (the
  loaded-machine runs kept deliberately, as the counter-example).
- Idle and startup evidence from a real frozen macOS launch of the HAN-40
  optimized bundle.

## Known limitations

- **macOS only.** Every number here is macOS arm64 on a 2P/4E machine. No
  Windows or Linux latency claim is made or implied; those need their own
  native runs.
- **Popup paint is not instrumented.** "Trigger to visible popup" is composed
  from the measured pipeline plus the configured dwell. `real-hover` exists for
  the visible-popup path but was not run: the post-OCR chain including Qt
  dispatch measures ~0.6 ms, so the composition is sound, but a true
  pixels-on-screen acknowledgement is still not instrumented.
- **The hover and hotkey paths were not driven by real input.** Hover, hotkey,
  tray, capture and hide/restore need Accessibility and Screen Recording
  permission and a human at the machine; the frozen self-check has only
  `worker` and `ui` modes. Unchanged limitation, not introduced here.
- **The sensitive retry was not measured on real text.** The report records it
  at about 2.7x a normal lookup. A hover that first returns non-success pays
  it, so real-world feel can be worse than the fixture numbers above.
- The single-lookup diagnostics in frozen smoke runs (~4–5 s OCR) are cold
  first calls in a freshly reconstructed bundle, not warm latency.

## Suggested review targets

- Whether "no runtime change accepted" is the right outcome, given that both
  candidates were rejected on measured evidence rather than on principle.
- The thread-count table, as the clearest example of a loaded host producing a
  confident and wrong optimization.
- Whether the 80 ms dwell should be lowered now that compute is ~30 ms — a feel
  decision this phase deliberately did not make.

## Review assignment

Human-selected after implementation. Not started.
