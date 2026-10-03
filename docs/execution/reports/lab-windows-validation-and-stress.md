# Hanly Lab on Windows: validation, updater and text-acquisition stress

Branch `lab/app-health`, 2026-10-02. Two implementation phases on one Windows
machine; Phase 2 starts only after Phase 1's gates. Mac results referenced here are
the reference matrix in
[`lab-hardening-mac-2026-10-01.md`](../review-handoffs/lab-hardening-mac-2026-10-01.md),
not Windows evidence.

## Environment

| | |
|---|---|
| OS | Windows 10 Enterprise 10.0.19045 |
| Hardware | Intel i7-9700K (8 cores), 16 GB, NVIDIA RTX 2060 (EasyOCR runs on CPU in every run here) |
| Displays | two 1920×1080 at 100 % (96 DPI); primary at x=0, second at x=−1920. Mixed DPI and >100 % scaling **not tested** (changing them would change the user's display settings) |
| Interpreter | `.venv` CPython 3.13.11; editable `hanly` / `hanly-app` 1.0.0 |
| Qt | aligned with `packaging/release-constraints.txt` before any evidence: PyQt6 6.10.2 / Qt 6.10.2 → PyQt6 6.11.0, Qt 6.11.2, WebEngine 6.11.0; hooks-contrib 2026.6 → 2026.7 |
| Released builds | v0.9.0 (`e75ef4b`, build `84d4836e`) and v1.0.0 (`9e44e38`, build `8bdae2ce`) are frozen with **CPython 3.10.11** (their session logs say so); a local build from this venv is 3.13 |
| OCR | EasyOCR 1.7.2 (Vision is macOS only); recognizer setting `easyocr` |
| Korean faces installed | Batang, Dotum, Gulim, Gungsuh (+Che), Malgun Gothic (+Semilight), Noto Sans KR (6 weights) |

## Phase 1 — lab, app and updater on Windows

### Baseline (before any change, `65e4968`)

- `pytest --suite portable`: 2,372 passed, 105 skipped (POSIX permission/xattr cases and other host-specific skips).
- `pytest --suite native`: 121 passed, 33 skipped (POSIX native helper, absent private Vision captures).
- `ruff`: clean.
- `mypy`: clean with `--platform linux` and `--platform darwin` (CI runs it on Ubuntu). With the Windows host's own platform it reports 22 errors in POSIX-only branches (`fcntl`, `os.statvfs`, `os.getxattr`, `os.O_NOFOLLOW`, `resource.getrusage`, `os.mkfifo`); an earlier Windows review measured the same set at `5c510e5` on the main lineage. This branch had added 6 more in `lab/` (fixed below). The pre-existing 22 are deferred, not dismissed (see Remaining).

### Defects found and fixed

| Case | Evidence | First failing stage / cause | Fix |
|---|---|---|---|
| Lab quit on Windows | `python -m lab run --duration 25`: exit **2**, no `report.html`/`summary.md`, metadata without `exit_code` (run `20261002-143134-run`) | `_request_quit` used `os.kill(own_pid, SIGINT)`, which on Windows is `TerminateProcess` | `signal.raise_signal` reaches the shell's handler; same run: exit 0 with report (`06b3792`) |
| Sampler attribution | `processes.jsonl` listed the Control Center's QtWebEngine helper as `shell.helper` and again as `control_center.helper` | recursion from the shell reached the child's helpers first | nearest owned ancestor decides (`06b3792`) |
| Lab type-check on Windows | 6 mypy errors only on win32 | `os.name` checks mypy cannot narrow | `sys.platform` narrowing (`f89f3c2`) |
| `artifacts/` untracked on this branch | 81 MB of Aug–Sep benchmark runs showed as untracked | the lab root move dropped the `artifacts/benchmarks/` ignore | ignore restored, nothing deleted (`7028aac`) |
| **WIN-UPD-01** install loop | real isolated 0.9.0 → public 1.0.0; page returned to "Update available" ~6 s after download | **staging**: `JournalOperation` validated every planned path with the rule that reserves `.hanly-manifest.json`; that file is the control entry every Windows tree manifest publishes and every release changes, so every differential Windows update fails. Same code in 1.0.0 and HEAD. Reason shown only in the collapsed activity list | `require_installable_path` admits that one root file for journal and archive mapping, the working area stays refused (`e8f51e0`); failure reason shown under the offer (`7b61f19`) |
| **WIN-UPD-02** empty directory | after the failure `<install>\.hanly-update\` existed, empty, through quit; removed by the next launch | owner `WindowsFileStaging._open_transaction`; the failed staging removed only its `t*` transaction | `abandon` removes an empty working area (`e8f51e0`) |
| Challenge remnants | `challenge-*.json`/`.ack` stay in `%LOCALAPPDATA%\Hanly\updates\<key>\` after every update | nothing removed them | settling removes the pair its plan names, by name shape only (`e8f51e0`) |
| Test TEMP leak | every portable run left `%TEMP%\hanly-update.*` and `hanly-update-image.*`; this machine had 47 such directories | two tests used the real `tempfile` root | redirected per test (`536c94d`) |

### WIN-UPD-01 / WIN-UPD-02 reproduction (before the fix)

Owned installation: v0.9.0's `hanly-desktop-windows.zip` (SHA-256 `b33555ec…`,
matching its `SHA256SUMS`) unpacked into the session scratch directory, launched
with its own `LOCALAPPDATA`, `TEMP`/`TMP`, the local KRDICT, and a local DevTools
port to drive the real Control Center. Transitions (from the page, the profile and
the install tree, sampled ~every 1.5 s):

| t (s) | Observation |
|---|---|
| 0 | Install update clicked; "Preparing the update to Hanly 1.0.0…"; install lock taken |
| 3.9–57 | "Checking installed files…" over 1,401,875,434 bytes |
| 55.9 | `%TEMP%\hanly-update-metadata.*\SHA256SUMS` |
| 57.4 | target manifest cached in the profile; `%TEMP%\hanly-update-payload.*\…from-0.9.0-to-1.0.0.delta.zip` (127.4 MB) |
| ~64 | "Verifying the download…" → **"Update failed: '.hanly-manifest.json' is inside the updater's own working area"**; payload and metadata temp directories removed; lock released; `<install>\.hanly-update\` created and left empty |
| 65.5 | panel back to "0.9.0 → 1.0.0 … Install update" (red tint, no reason visible) |

The published delta does contain `.hanly-manifest.json` (143 members), so a
journal-only fix would have moved the failure to "payload is missing".

### The identical update after the fix

Production `TreeUpdateRunner` + `UpdateCoordinator` from the checkout, composed as
`application._tree_runner` composes them, against the real release source (read
only); the real PowerShell helper; the real 1.0.0 build answering its challenge.
Now reproducible as `python -m lab check windows-update` (see `lab/checks/README.md`).
The process hosting the coordinator is the lab, not the frozen shell, so this proves
the checkout's updater, not the one shipped in 0.9.0.

| Mode | Result |
|---|---|
| install | prepared → applying (264 operations) → awaiting-startup → **committed** in ~1.8 s after relaunch; installed stamp 1.0.0 / `8bdae2ce`; tree matches all **6,316** entries of the published 1.0.0 manifest; relaunched page "Hanly and all local resources are current"; a fresh check offers nothing; next launch removes the transaction and recovery pointer |
| cancel (during "Checking installed files") | "The update was stopped. Nothing was changed."; no working area, nothing in TEMP, lock released |
| rollback (staged new executable replaced with bytes that cannot start, before apply) | helper waits its 600 s deadline, **restored**; tree matches all 6,316 entries of the published 0.9.0 manifest; 0.9.0 relaunched and reports "Hanly 1.0.0 did not start, so the previous version is back"; update offered again |

Remaining after success: the recovery copy of the helper (by design), the install
lock file (taken over by the next update; by design), and, when the settling build is
1.0.0 itself, its challenge pair (the fix applies from the next build on).

### The lab on Windows

| Flow | Evidence | Result |
|---|---|---|
| `python -m lab run --duration 25` | real source session | after `06b3792`: exit 0, report + summary, no orphan (before: exit 2, no report) |
| `python -m lab run` + real Ctrl+C (separate console, `CTRL_C_EVENT`) | real source session | exit 130 (user interrupt) within 0.9 s; report + summary; no owned process left |
| `python -m lab tour --quick` | real driven hovers, EasyOCR | **0/24 before `9fe7c41`**, 22/24 after |
| standard tour (`20261002-160956-tour`) | real driven hovers | 408/453 (90.1 %) strict-headword-v3, 0 unscored, 197 s |
| `--baseline 20261002-160956-tour` (`20261002-161813-tour`) | real driven hovers | 409/453; all 453 matched; 3 changed verdicts, all `no_hover` ↔ `correct`; every misread repeated exactly |
| quick tour + a hand-like pointer move from another process | real driven hovers | `stopped_by_user after 6 of 24 planned`; report flags the score as not comparable |
| quick tour under a foreign topmost window (separate process, re-raised every 200 ms) | `WindowFromPoint` ownership | 12/24 unscored (8 `obscured`, 4 `obscured_during_capture`); none kept facts or read text; the foreign window's text is not on disk |
| `report --list` / rebuild / `--baseline` | rebuild from recordings | working |
| `check run` APP-STARTUP, CC-LIFECYCLE, CC-CONTROLS, CC-UPDATE-STAGE, CAPTURE-CHOICE, HOVER-POPUP, SETTINGS, UPDATE-COORDINATOR, RESOURCE-DELIVERY | mixed, labelled per catalog | 9/9 passed (`8d929256`); UPDATE-APPLY-POSIX and MAC-IDENTITY are not Windows scenarios |
| `check windows-update` install / cancel / rollback | real releases, real helper, checkout updater | passed / passed / passed (`20261002-152622`, `-152409`, `-154548`) |

Lab defects found by running it on Windows, all fixed in `9fe7c41`:

- **Every Windows tour scored no hovers.** The tour runs with hover always
  active; the app honours that by starting capture at launch
  (`application._start_if_always_active`, approved behaviour), and the tour then
  pressed Start/Stop Capture, turning it off: `capture_toggle_received` →
  "Hanly stopped watching the screen", then 24 × `no_hover`. The driver now waits
  for the app's own `hover_observation_started`, presses only if capture did not
  start, and aborts with `capture_never_started` otherwise (`tour_capture`
  records which).
- **A person's pointer move during a hover went unnoticed**: the driver glided
  back to its rest point before checking, overwriting the evidence. Now checked
  after each hover's wait; the disturbed hover is not recorded. A single
  synthetic jump that lands inside the driver's own ~50 ms glide can still be
  missed; a moving hand cannot.
- `metadata.json` recorded the end of a session as its `started`.

### Normal frozen launch on Windows

`tests/packaged/windows/test_frozen_identity.py` (`05faed3`, catalog
`BUNDLE-LAUNCH-IDENTITY-WIN`): launch the frozen executable on an isolated
profile, start capture from the page, close the Control Center with
`WM_CLOSE`, reopen it with the tray's default action (pystray's notify message
with `WM_LBUTTONUP`), quit from the page's Quit control; sample the owned tree
and all top-level windows every ~100 ms.

- Roles are exact: shell, Control Center (hosts `QtWebEngineProcess`), lookup
  (the other direct child), WebEngine helpers, and the lookup child's own
  `cmd.exe`/`conhost.exe`.
- Taskbar / Alt+Tab entries (visible, uncloaked, `WS_EX_APPWINDOW` or an unowned
  non-tool window): **only** each Control Center instance, exactly one window
  each; the shell, lookup child and helpers never; nothing outlives quit; shell
  exit code 0. Passed on public 1.0.0 and on the fresh build.
- Observation, not a defect: the frozen lookup child runs `cmd.exe /c ver`. That is
  CPython 3.10's `platform` module (3.12+ uses WMI, which is why the 3.13 source
  run spawns nothing); `subprocess` starts it with `SW_HIDE` and no window was ever
  sampled for it.
- Shell windows: two `…SystemTrayIcon` message windows exist; only the later one
  answers. The check posts to both.
- No single-instance guard on Windows: a second launch would start a second shell
  with its own tray and hotkeys. Not changed (product decision); recorded.

### Fresh build and packaged gates

- Clean commit `9fe7c415496075c33d6f74b497c914cbf029f3b3` (docs stashed during the
  build), `tools/build_package.py --platform windows`: version 1.0.0, build
  `9dc5e5af-a4f6-420f-afdf-0578dc06e14b`. The previous `cbdebc5` 0.9.0 build and its
  products were moved to `dist/archive-cbdebc5-windows/`, not deleted.
- `HANLY_EXPECTED_SOURCE_COMMIT=<full sha> HANLY_REQUIRE_PACKAGED=1 pytest --suite packaged`:
  **5 passed** on `dist/windows/hanly-desktop` and **5 passed** on the ZIP unpacked
  into `dist/reconstructed-9fe7c41/`, whose tree matches all **6,834** entries of
  `dist/release/windows/manifest.json`.
- `check run` BUNDLE-IDENTITY, -WINDOW, -WORKER, -LAUNCH-IDENTITY-WIN with that SHA: 4/4 passed.
- This build uses CPython 3.13 and Qt 6.11.2 from this venv; released builds use
  3.10.11, so file counts and timings are not comparable with 1.0.0's.

### UI-UPD-03 on Windows

Real Windows Chromium (Qt WebEngine 6.11.2), `test_update_stage_animation.py`
through `ui_probe`: progress-only refreshes keep the same label element; one
`animationstart` per changed label (2 over 4 steps); iteration count 1; duration
≤ 0.5 s, ≤ 1 ms under `--force-prefers-reduced-motion`; progress percent updates;
the Cancel control stays present while cancellable. The real 0.9.0 → 1.0.0 run
also showed "Checking installed files…" holding one label across ~30 progress
refreshes. Passed with normal and reduced motion.

## Phase 2 — text-acquisition stress and corrections

### The campaign

`python -m lab stress` (`f3e8329` and follow-ups), seed 11, the everyday runtime's
KRDICT (`20260819-v1`), EasyOCR 1.7.2, hover delay 20 ms (the copied everyday
setting), always-active hover, primary display 1920×1080 at 100 %. Faces used on
this machine: Malgun Gothic, Batang, Gulim, Dotum, Gungsuh, Noto Sans KR; sizes
14–44 px; themes light, dark, sepia, gray. Expectations come from the plan, set
before running; none was changed after seeing output. Planned 1,158 hovers:
873 positive-scored, 200 negative, 40 leave-early, 15 changing (evidence), 20
covered (evidence/unscored), 10 UIA Latin negatives.

### Defects found by the campaign and fixed (all lab, no shipped code)

| Defect | Evidence | Fix |
|---|---|---|
| Hovers firing before the driver listened | `le016` "stale popup": `hover_stable_fire` 0.13 ms before the driver's `tour_target`; also the tours' intermittent `no_hover` | listen before the final glide (`b40e11d`), regression fails before / passes after |
| A current answer counted as stale | `ra031`: a rapid sweep paused > 20 ms on a word (Windows `sleep(0.004)` ≈ 15 ms); its correct popup arrived 2 ms before the pointer left | stale only once the app invalidated the lookup (`ab7110c`) |
| UIA segment never measured | Qt `QPlainTextEdit` answers `ElementFromPoint` with its viewport and its `RangeFromPoint` fails on the parent | measured InPrivate Edge window (`f3e8329`, `0f599dc`) |
| Account dialog over the page | a fresh Edge profile showed Windows' implicit sign-in dialog (with the account e-mail) over the page | InPrivate, and every point must be `Chrome_RenderWidgetHostHWND` before hovering; the one scratch screenshot and three replay images from that smoke run were deleted unviewed |
| Twelve-line windows refused | one point landed on a `Chrome_WidgetWin_1`, refused by the guard | six lines per window (`0f599dc`) |

An ancestor walk for UIA text patterns was implemented, shown not to help any real
control (Qt fails at `RangeFromPoint`; Edge already answers on the hit element),
and reverted without a commit.

### Before / after (same seed, same plan, same machine)

| Run | Commit | Executed | Scored | Passed | False positives | Missing/wrong | Late/stale popups |
|---|---|---|---|---|---|---|---|
| `20261002-184134-stress` | `f3e8329` | 1,108 (UIA refused) | 1,073 | 948 | 0/200 | 125/873 | 1 (race) |
| `20261002-185509-stress` | `b40e11d` | 1,108 (UIA refused) | 1,073 | 949 | 0/200 | 124/873 | 0 |
| `20261002-191054-stress` | `0f599dc` | 1,158 | 1,123 | 996 | 0/210 | 127/913 | 1 (rapid, misclassified) |
| **`20261002-192328-stress`** | **`ab7110c`** | **1,158** | **1,123** | **997 (88.8 %)** | **0/210** | **126/913** | **0** |

Final run, by family: word 202/240, story 248/306 (incl. 18/18 Latin refused),
cursor 80/90, dense 29/32, mixed Korean 20/25, raster text 35/40, repeat 57/60,
rapid 38/40, UIA Korean 38/40, leave-early 40/40 withheld; every negative family
(blank, number, punctuation, Latin, mixed Latin, icon, illustration, after-popup,
UIA Latin) passed every hover. Changing content: 15/15 kept the first answer and
fired no new hover (no polling, by design). Covered page: 9/20 refused by
ownership, the rest outside the cover.

Latency (hover → popup, live): p50 253.9 ms, p90 349.7 ms over 1,105 answered or
declined hovers; word 200.9 / 274.0; dense 394.0 / 514.5; icon and illustration
negatives about 336–350 p50 (the sensitive retry runs when the first pass reads
nothing). Peak sampled RSS: lookup 1,088 MiB, Control Center 191 MiB, shell 143 MiB
(includes the lab recorder; `shell.helper` 164 MiB is the lab's own Edge and cover
processes). Sampled resident memory, not private memory or a precise peak.

### Where the failures are

- **124 OCR misreads.** Every one replays to the same status and selection through
  the production lookup worker from the saved region (`stress-replay`: 124/124,
  labelled `lab_recapture_production_worker_replay`; the recognized lines themselves
  are identical for 123/124, and `m007-ko` adds one extra line on replay), so capture,
  geometry, gate, resolver, cache and presentation are excluded. Phase B checked each
  one at the OCR stage: neither the live nor the replayed normalized recognition
  contains the target surface. Rates by face: Batang 41/251, Malgun Gothic
  37/251, Dotum 15/107, Gulim 13/107, Gungsuh 11/50, Noto Sans KR 5/49; worst at the
  story's Batang 18 px. Confusions are EasyOCR's: 요→오, final ㄹ/ㅁ/ㅂ (차를→차름,
  꽁꽁→공공), 았/었→앗/없, ㄷ/ㅁ initials (모르→도르). Raster degradation is not the
  driver (5/40 misread). Not fixed: OCR tuning is out of this scope.
- **2 morphology/dictionary:** 누군가는 → 누구 at two sizes; 누군가 is not in KRDICT
  (known since the Mac handoff).
- **UIA timing (not a scored failure).** On Edge, 22/40 Korean hovers were answered by
  direct text; 10 hit the 40 ms direct-text budget and fell back to OCR (still
  correct), 6 were `unsupported` (Chromium enabling accessibility on first contact).
  **Attributed in Phase B to the lab:** its psutil sampler ran on a thread of the
  lab-hosted shell and held the interpreter lock (short campaigns: 79 and 111
  direct-text timeouts with it, 6 and 1 with it stubbed out, 0 and 0 once it moved to
  its own process in `24ac332`). Not product behaviour; `DEFAULT_TIMEOUT_MS` unchanged.
- **Repeats had no cache hits (0/60):** each repeat sits in a different cell, so its
  pixels differ from the original's; this measures repeat correctness, not cache.
  (1,318 cache hits happened outside scored windows; 5 inside, all `after_popup`.)
- **The 35 unscored hovers** are 9 covered-page hovers under the cover (6 `obscured`,
  3 `obscured_during_capture`), 11 covered-page hovers outside it kept as evidence
  (9 correct, 1 wrong, 1 NOT_FOUND) and the 15 changing-content hovers. The 7
  "timed out" UIA Latin negatives were a lab defect (fixed in `7704dc8`): a
  `not_korean` direct-text refusal is final and emits no popup event.

### Friend's screenshot cases (investigation only)

The original images are not on this machine and were not substituted. With the
words given as correctly read text through the production language stage:

| Word | Result with perfect recognition | Classification without the image |
|---|---|---|
| 백련성신 | NOT_FOUND; 백련, 성신 and the whole are absent from KRDICT | correct recognition would still give no usable dictionary entry (a name/coverage case) |
| 출석체크 | the compound is not listed; 출석 or 체크 by cursor | answerable by component |
| 갤러리 | SUCCESS 갤러리 | if no answer appeared, the failure is upstream: capture, gate, OCR or word selection |
| 이벤트 | SUCCESS 이벤트 | same |

Next action for the dedicated phase: attach the images, then run each through
`stress-replay`-style production replay (or `live-hover` Freeze/Export) to name
the first failing stage per word.

### Phase 2 gates

On clean `ab7110cd02b6a7cb7cdc66ef403d1e022d44728c`: portable 2,398 passed / 105
skipped; native 121 / 33; ruff clean; mypy clean for linux and darwin (the same 22
pre-existing win32-only errors); no TEMP leaks. No file under `packages/`,
`packaging/` or `tools/` changed since `9fe7c41`, so that build and its packaged
results stood at the end of Phase 2. *Superseded by Phase B, which changed shipped
code and rebuilt at `16dde15` (below).*

## Phase B — deep review (2026-10-02/03)

### Defects found and fixed

| Commit | Defect | Evidence |
|---|---|---|
| `deb72a6` | Settling deleted any `challenge-*.json` a plan pointed at, wherever it was | the plan is read back from inside the installation; a tampered plan's file outside the receipt directory was deleted (test fails before, passes after) |
| `938fa6c` | 22 win32-only mypy errors | `sys.platform` branches, no ignores or config changes; mypy clean for win32, linux and darwin |
| `7704dc8` | (lab) UIA Latin negatives recorded as timed out | a `not_korean` direct-text refusal is final and emits no popup decision |
| `8594257` | (lab) bounded-output test failed without `PYTHONUTF8` | cp1252 cannot encode Hangul; the child's stdout is pinned to UTF-8 |
| `24ac332` | (lab) UIA direct-text deadline misses | the sampler held the GIL in the lab-hosted shell: 79/111 timeouts with it, 6/1 stubbed, 0/0 out of process |
| `12b052c` | Reserved updater names matched case-sensitively | `.HANLY-UPDATE/...` resolves into the working area on Windows and macOS (5 tests fail before) |
| `0046cbc` | Windows helper waits outlasted the processes they waited on | see below |
| `38d9203` | (lab) failure reasons and replay provenance missing | summaries now record the path-free failure message; replays record commit, dirty state and line-level agreement |
| `16dde15` | A release-server outage told first-time updaters to install by hand | see below |
| `762c1c4` | (lab) first Edge hovers captured an undrawn window | waits until the targets are drawn; records `painted_ms` |

**Windows helper waits (`0046cbc`).** One isolated rollback failed with "the update
helper did not start". A timeline injected into the helper showed the PowerShell
process created at 0.1 s but its first script line running at 8.0 s (3.2 s in a
second run; a third had claimed at 25.6 s); parsing the plan and writing the claim
took 0.26 s. The same helper starts in 0.2 s on a quiet machine, also after writing
650 MB of novel files and with an empty profile, so this is a slow PowerShell cold
start under load (the lab's running 0.9.0 and a second run; the helper used about
12 % of a core), not a hang, Defender, or this branch: the helper and its 30 s claim
wait are byte-identical in 0.9.0, 1.0.0 and before Phase B. Two fixes:

- the shell watches the helper process it started: an exit without a claim fails at
  once; a live helper is given 120 s;
- the helper stopped waiting the full 600 s `READY_WAIT_SECONDS` behind its progress
  window when the new build could not launch or had exited; it now rolls back as
  soon as the build is gone. Native tests running the shipped PowerShell against
  compiled builds: rollback took 35 s and 28 s (the whole shortened window) before,
  and passes under half of it after. The isolated rollback check went from about 25
  to 7.9 minutes.

These help only updates started by a build that contains them: the helper script
is written by the running app.

**Release outage (`16dde15`).** During a live GitHub 502/503, the isolated install
failed with "Hanly cannot confirm that this installation is the published 0.9.0
build … Install the new version by hand". The tagged-release lookup that every
receipt-less (manually installed) client uses on its first update swallowed network
errors as absence. An unreachable server (no connection, 5xx, other non-404 statuses)
now fails retryably and changes nothing; a 404/410 for the tag still cannot be
confirmed.

**Native helper instead of PowerShell?** Considered and not done. The Mac/Linux
helper is compiled C (`packaging/updater/hanly-update-posix.c`); a Windows
equivalent would add a compiler to every Windows build and CI job, a new signed
binary, and a second recovery path, and installed clients would keep writing the
PowerShell helper anyway. The measured problems were the two waits, not
PowerShell's correctness; revisit if a Windows helper start is ever seen to exceed
120 s, or PowerShell becomes unavailable by policy.

### Legacy clients and release manifests

- Affected installed Windows versions: 0.5.3 (`4f9547b`), 0.9.0 (`e75ef4b`), 1.0.0
  (`9e44e38`); all have schema-2 tree staging and the journal's
  `require_safe_relative_path`. 0.5.2 has no tree staging.
- Simulated against the legacy rule (both call sites patched back): the release as
  today fails; **omitting `.hanly-manifest.json` fails** (the base owns it, so the
  plan deletes it); **a full download fails** (same staging and journal); only a
  byte-identical control file stages, and that would leave the installed V1
  inventory describing the old build, which the next update reads as its base, so it
  breaks integrity and future updates.
- No release-manifest change rescues these clients safely. **Recommendation:** a
  one-time manual replacement for 0.5.3/0.9.0/1.0.0 Windows installs (replace the
  folder with the new ZIP; settings and the dictionary are in the profile),
  announced in the release notes. Those clients fail with a "working area" message
  and change nothing. Needs a human decision; release tooling is unchanged.
- The isolated 0.9.0 → 1.0.0 check proves this branch's updater against real
  releases, not the updater embedded in installed builds.

### Gates and builds (Phase B)

- At `16dde15e4aaed14d2f0023938f850099dac4a026` (the last shipped change; `762c1c4`
  after it is lab-only: lab tests 326 passed / 18 skipped, ruff and mypy clean): portable 2,415
  passed / 105 skipped; native 123 / 33 (including 9/9 shipped-PowerShell helper
  cases); ruff clean; mypy clean for `--platform` win32, linux and darwin.
- Fresh build at `16dde15` (build `0b5c0920-a362-4498-a7fe-7b27e33261d5`, 1.0.0,
  CPython 3.13 venv); earlier products moved to `dist/archive-{9fe7c41,12b052c,38d9203}-windows/`.
  ZIP sha256 `7fe65ee6ff31326c37d31ea29f973c7ca867e23070f80f0a94d6c7e9c1042055`,
  reconstructed into `dist/reconstructed-16dde15/`: all 6,834 manifest entries match by
  size and hash, nothing undescribed or missing. `pytest --suite packaged` with the
  full SHA and `HANLY_REQUIRE_PACKAGED=1`: 5/5 on the build, 5/5 on the
  reconstruction. BUNDLE-IDENTITY, -WINDOW, -WORKER, -LAUNCH-IDENTITY-WIN: 4/4. No
  `lab` or `tests` module among the 6,302 frozen modules.
- `lab check windows-update` at `16dde15`, unmodified: install passed (8.1 min),
  cancel passed (2.3 min), rollback passed twice (7.9 min each; restored, manifest
  matches, re-offered). Remnants after install/rollback are the published 1.0.0's or
  restored 0.9.0's own challenge files, since those builds do the settling.
- Campaign at HEAD: `20261003-202512-stress` (seed 11, same plan and machine, code `762c1c4`,
  only docs uncommitted): **998/1,123 (88.9 %)**, 0/210 false positives, 125/913
  missing or wrong (123 OCR misreads, 2 morphology), 0 stale or late popups; 1,158
  planned = executed, the same 35 unscored. UIA Korean 39/40, 32 answered by direct
  text (22 before), direct-text timeouts across the campaign 2 (303 before). Replay:
  123/123 same outcome, 122/123 same recognized lines (`m007-ko`), every misread
  confirmed at the OCR stage. Lab-hosted latency fell once the sampler left the
  shell: all hovers p50 254 → 135 ms, p90 349 → 337 ms; word p50 199 → 129 ms, p90
  273 → 141 ms. These are lab-hosted measurements on this machine, not general app
  latency; the Phase 2 latency figures above were inflated by the lab itself.
  An intermediate run (`20261003-201036`, 995/1,123) exposed a lab race fixed in
  `762c1c4`: the first three Edge hovers captured a fresh window before it was drawn
  (pure white frames, `no_text`).

### Privacy and packaging

- `main...HEAD` adds no images, binaries, run artifacts or dist files; machine-path
  matches in added lines are environment-variable names and test fixtures.
- The user-visible "Update failed: {error}" text (pre-existing, `coordinator.py`) can
  quote a local path from an `OSError`; shown only on the user's own screen, not
  persisted. Not changed (product behaviour); see deferrals.

## Remaining and deferred

- **Stranded clients (needs a decision).** Installed **0.5.3, 0.9.0 and 1.0.0**
  carry the WIN-UPD-01 defect and cannot install any later update in place, delta
  or full. Phase B showed that omitting `.hanly-manifest.json` from a release does
  not help (see Phase B). Recommendation: a documented one-time manual
  replacement. Release tooling was not changed.
- **OCR misreads** — revisit with an OCR-tuning bundle; the replay images under
  `artifacts/lab/runs/20261002-192328-stress/replay/` are a ready offline corpus.
- **Mixed DPI, >100 % scaling** — untested on this hardware configuration.
- **Single instance on Windows** — a second launch starts a second shell; product
  decision.
- **Screenshot cases** — need the original images.
- **Update failure text may quote a local path** — `Update failed: {error}` shows an
  `OSError` as-is on the user's own screen (not persisted). Changing it changes
  product wording; revisit with any error-presentation work.
- **Fixed cleanup and helper waits in a real update** — proven by tests and the
  lab-driven updater; a released build containing them has not yet performed a
  real update. Revisit with the first release cut from this branch.
- **A crashing new build on Mac/Linux** — the C helper fails fast only when the
  program cannot be executed; one that starts and exits waits out
  `READY_WAIT_SECONDS`. Same class as `0046cbc`; revisit with the next Mac helper change.
- **Mac checks** — need a Mac: `UPDATE-APPLY-POSIX`,
  `tests/native/shared/test_update_posix_native.py`, `MAC-IDENTITY`, packaged
  `test_frozen_identity`, the Control Center stage-animation probe, and one real Mac
  update over `deb72a6`/`12b052c` (receipt-directory check, APFS case folding).
