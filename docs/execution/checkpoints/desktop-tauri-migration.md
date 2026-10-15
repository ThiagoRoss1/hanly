# Hanly Desktop Tauri migration checkpoint

## Live acceptance pass — final build installed (2026-10-15)

- Product commit **e7ef391f8adb3be72851f855d9bf2da94e596df2**, build
  **20284932-80c5-4086-9015-5092705d6714**. ZIP `3d5cf257…dfd35e`, DMG
  `bc0a09e0…f5fe7`. Installed as `/Applications/Hanly.app`, and only that
  copy is registered with LaunchServices.
- Passed:
  - all 7 packaged checks;
  - ZIP and DMG verification;
  - three Lab tours (24/24, 24/24, 175/177);
  - a 3 ms frame sample over 192 shows (zero stale frames);
  - every live Safari/TextEdit, shortcut, tray and quit check, on the
    debug root at the same source.
- Fixed:
  - the CI failures (rustfmt toolchain component; mypy on Linux);
  - a flaky packaged check;
  - the popup's WebKit context menu, which blocked the event loop;
  - the Grant access label, and a hint for stale entries.
- Root cause of "granted but required": the enabled TCC entries belong to
  build `284bd3e3` (`cdhash 1e6db425…`). Each ad-hoc build is a new
  identity. Creating a stable local signing identity was blocked by this
  session's policy and remains the human's decision.
- Open:
  - the human's one-time grant on this build (remove the old entry first);
  - one physical press each of ⌃⌘H, ⌃⌘P and ⌃⌘R.

## Phase B follow-up — built and headless-verified (2026-10-15)

- Product commit **acd3c2841d9bfd8e96e16f456f141c6a8f39fead**, build
  **44161ec2-7c78-4765-a996-a231953b4f18** (arm64, ad-hoc). ZIP
  `339cb8be…5a503`, DMG `93e196c5…a370`. This build supersedes `96868d8` /
  `284bd3e3…`.
- Committed with the human's authorization: the review fixes below, removal of
  the Python keyboard listener (`HotkeyService`, `hotkeys_darwin.py`), service
  icons and `app_icon.py`, a state-aware tray capture item, and ordered state
  snapshots (series + number).
- Passed: the four headless packaged checks and the ZIP/DMG verification
  (3,748 entries each, manifest, inventory, strict signature). Not run yet: the three
  packaged checks that open windows, and every live step. Its ad-hoc cdhash
  requirement means the previous build's grants do not carry over.

## Phase B review — 2026-10-15

- Claude reviewed `0902075..0c93861` and, with authorization, fixed the
  following. They were later committed and built; see the follow-up above.
- Fixed: a group SIGKILL after the leader was reaped, which risked hitting a
  recycled PID (Rust supervisor). Fixed: the popup drew over its word when the
  measured height exceeded the 180 pt estimate. Removed: the dead
  `popup_rect` field. Added: a dev-only `npm run preview:mock` for the React
  views.
- Open: remove the dead keyboard `HotkeyService`/`hotkeys_darwin`; add a state
  revision; make tray labels state-aware.
- The sealed product is still `96868d8` / `284bd3e3…`. Build the committed
  review fixes next. Full findings and the deduplicated remaining work are at
  the end of the review handoff.

## Current stop boundary — 2026-10-15

The human reported Mac disruption and asked to finish within the remaining budget
or update the handoff and stop. This run takes the explicit handoff fallback.
No rebuild or permission cycle was started at closure. No root/service/lookup,
fixture, HTTP server or package/build job remained at the host process check.

- Product commit **ccf230da1e3076c25359467ecc8a9f3fc738984a** fixes a real Mac
  popup race: Tao size/position setters queue work while show is synchronous.
  One public AppKit frame is now committed before non-key presentation.
- **20 Rust tests pass**, all-target Clippy `-D warnings` passes; fmt/diff clean.
  No Python, React, capture/engine or shortcut change in this last correction.
- **Not built/live-verified yet.** Canonical sealed app/ZIP/DMG still source
  `96868d8`, build `284bd3e3-bef5-406f-8e16-6add3184a5c1`; its seven packaged
  checks and both archive inventories/signatures passed. Do not call it current
  with respect to the final native-frame fix.
- Human explicitly approved Screen Recording restore plus stale Accessibility
  re-add for that old canonical build. Done via normal Hanly/Settings actions;
  no new authentication prompt. After normal restart, both read granted inside
  Hanly in `20261015-000248-run`. No more reset without new explanation/approval
  while present. No TCC reset/database manipulation in app/tests.
- That run finished: 371.6s, 7,958 events, zero drops, Vision observed. Starts
  `76ef35ae9b75` clean, changed during recording, observed binary `96868d8`.
  Mixed manual pointer activity prevents treating aggregate latency as a baseline.
- Live old-build popup: rounded native compact 340×282; expansion 460×282 and
  collapse retain X111/Y134. Nonactivation observed. Adjacent changes exposed
  ~19ms old-frame-first race (fixed in source above) and two misses at 0.9s;
  those trials are not all green. Human's broader Mac disruption cause unknown.
- Keyboard question (Control–Command P twice/R twice) had no answer and zero
  native edges at closure. Physical input/Safari foreground/AX still unverified.
- Saved PIDs 55125/55152 and sessions 48163/9043 are historical, not live.
  Do not target them without fresh identity/ownership checks.

The **single detailed handoff** is
`docs/execution/review-handoffs/desktop-tauri-migration.md`. Its final section
contains exact completed evidence, private fixture pointers, rebuild commands
and all six remaining steps: official fresh `--no-clean` build at the full hash
above; seven packaged + both new archives; recheck grants/ask only if needed;
bounded live popup/transition/negative/retention checks; real native shortcuts
and controlled Safari foreground/AX/OCR; same-build persistence/whole-family
cleanup and final documentation/local commits. Old private Safari/verifier
scripts contain stale run/build IDs; update and revalidate before reuse.

Windows/Linux hardware acceptance, mixed monitors, Developer ID credentials/
notarization and Playwright planning remain explicit boundaries. No push, merge,
tag or public release. Historical sections below are preserved for provenance;
they do not override this current stop boundary.

## Popup and Mac shortcuts continuation — 2026-10-14 evening

Reopened by explicit human request after the earlier handoff. Current product
source is `96868d8f78ed30f42c78450f2b0ac6b9310f298e`.

- `776a7ef`: Mac defaults Control–Command H/P/R, native symbols, complete legacy
  default-set migration only; custom/partial/unbound profiles are preserved.
- `19d5d67`: hover/residency tests follow their configured platform bindings.
- `96868d8`: render/measure before native show, current actions on the native
  thread, rounded native Mac clipping/shadow with public APIs, expansion stays
  anchored and follows authoritative content, actual-size display clamp,
  ceiling-rounded measurements and unchanged-theme deduplication.
- Inspected the user's 45.6s recording locally. Visible defects include opaque
  square corners around the rounded card and a tall blank native window during
  transitions. No user recording or extracted frames are in Git.
- CaptureService and engine source remain byte-identical to `0902075`; no
  provider, ROI capture, hover debounce or prewarming policy change was made.
- Checks so far: 104 focused config/hotkey/service, 45 hover/residency, 40 React
  UI, 10 Node contracts, strict TypeScript/Vite, 19 Rust + Clippy, full Ruff and
  mypy (344 files); macOS native 86 passed. Final full portable passed
  2,611 with two existing skips in 553.11s;
  its first run exposed eight hardcoded old binding assumptions, corrected in
  `19d5d67`. The subsequent full run collected one fixture before its final
  correction; it is superseded by the final passing run.
- Fresh coordinated Mac build completed successfully with full source hash above and
  CARGO_BUILD_JOBS=2. Log: `/private/tmp/hanly-popup-fix-acceptance/build.log`.
  New build ID: `284bd3e3-bef5-406f-8e16-6add3184a5c1`.
  All seven packaged checks passed in 200.61s. ZIP and DMG each match all 3,762
  manifest entries and pass inventory/strict signatures. New hashes and the
  exact identity are recorded in the evening handoff section. The package is
  current; bounded live popup acceptance remains explicitly pending.

### Permission handling: explicit human instruction

Do not reset, remove or re-add a permission entry for testing without first
explaining why it could help and receiving approval while the human is present.
If authentication is needed, clearly report the dependency and keep doing
independent work. Do not leave a silent, stalled test session running.

Hanly and the test code contain no TCC reset/database manipulation. During this
continuation the agent manually removed the stale Hanly Screen Recording entry
while switching release/debug signatures; macOS required authentication, which
the human completed. This was a manual test action, not app behavior. The entry
is currently absent and must be restored for the final canonical app through
normal Hanly/System Settings actions when the human is present. Do not keep
switching grants to the debug variant. Accessibility has not been reset in this
continuation. No installed valid code-signing identity exists (`security
find-identity -v -p codesigning`: zero); ad-hoc rebuilds do not establish stable
cross-update TCC identity. Developer ID signing requires release credentials;
never weaken designated requirements or bypass TCC to conceal that limitation.
Normal same-build restart persistence must be checked after the final grant.

### Native sessions and continuation

- Old bare debug PID 45099 was identified and stopped with normal SIGINT.
- Disposable debug Lab run `20261014-215948-run` reached runtime ready, but
  permissions were required; it captured no text/pixels and ran no lookups.
  Closed normally (root PID 48292); all ten sampled PIDs independently absent
  afterwards, and no Hanly root running. Read its summary before using it.
  It is not popup acceptance or performance evidence.
- Prepared private controlled raster fixture and Mac-default profile under
  `/private/tmp/hanly-popup-fix-acceptance/`: `fixture.py`, `config.json`.
  Three adjacent targets 학교 / 단축키 / 한국어, a Latin negative, geometry-change
  observation and commands `school`, `shortcut`, `korean`, `hello`, `rest`,
  `chord` (Control–Command + letter), `enter_popup`, `stop`.
  Command writes must be atomic; inspect native ownership before each move.
- Final canonical Lab run `20261014-222748-run`, root PID 52072, closed normally
  through confirmed Quit: 241.8s, ten events, zero drops and zero captures/lookups.
  Actual packaged UI verified runtime ready/providers sleeping, native shortcut
  symbols and all registrations accepted. Both permissions last reported required.
  All nine sampled PIDs independently absent, and no Hanly root remains.
  Explicit presence/refresh question is pending; do not act without the human's
  answer. All other gates passed. CUA binding `canonicalPopupFix` is now stale:
  do not query it and accidentally reopen an unisolated app.
- Next: launch a fresh isolated session using the existing sealed canonical
  build (do not rebuild just for docs). Recheck grants first; if already valid,
  change nothing. Otherwise restore the final canonical grant only with the
  human's approval/presence, then test popup borders, repeated transitions,
  expand/collapse/Close, negative refusal, native letter shortcuts, retention,
  normal restart permission persistence and whole-family cleanup. Record exact
  observed timing/limits; do not infer visual/physical acceptance from unit tests.
- The same comprehensive handoff is updated through all completed gates and
  exact remaining native acceptance. Add the live results after approval and
  preserve historical evidence with explicit previous-build labels. No push/merge/tag/public release. No Playwright work in this scope.

## Current continuation — 2026-10-14

Implementation, legacy removal, the requested code/optimization review and the
final product gates are complete. Product source is `0b8a9f4`; latest Lab-only
fix is `8ea89d8`. The one detailed handoff is
`docs/execution/review-handoffs/desktop-tauri-migration.md`.

### Verified closure

- Final arm64 Mac app: `dist/macos/Hanly.app`, v1.1.0,
  build `7569005a-6a5a-4efc-9739-a54266b2855a`, product stamp
  `0b8a9f4f9a6a33fdfdc4bb4846e0f3a5e28cfba9`. All seven packaged gates pass.
  ZIP/DMG each match all 3,762 manifest entries, inventories and strict deep
  ad-hoc signatures. Later Lab/docs commits do not change that product identity.
- Product gates: portable Python 2,602 passed / two existing skips, macOS native
  86 passed, React 40 UI + nine Node contracts, strict TypeScript/build, Rust
  17 + Clippy/rustfmt. Latest Lab ownership/FFI regressions: 106 focused checks,
  full Ruff and full mypy (344 files) pass. Earlier full portable Lab: 549 passed.
- Production and Lab Qt/WebEngine/pywebview implementations and dependencies
  are removed. Engine source is unchanged. Active Python/TS/Rust sources have
  no inline lint/type suppression. Historical spike and explicit compatibility
  fixtures remain intentional.
- Both approved grants were refreshed for the exact signing identities through
  Hanly's Permissions actions and the native macOS picker. After debug tests,
  registrations were returned to the final release. A normal restart verified
  both Screen Recording and Accessibility granted inside the canonical app.
  No third product permission was needed.
- Final release `20261014-183030-run`: actual 학교 / school / Hanja and
  definition, compact/expanded/Close, nearest-edge transfer, protected movement,
  negative refusal, stationary held chord, release/sticky readability, cache,
  F9 pause/resume and F10 capture stop/start. Render acknowledgement correctly
  records each answer once. Confirmed normal Quit: exit zero, no surviving or
  forced children, zero dropped events.
- That 449.4s release session has three answered hover observations: median
  340.2ms, first-cold maximum 4,750.7ms; family peak 751.7MiB, mean summed CPU
  3.2%. It includes waiting/manual UI and is not a general workload benchmark.
- Debug `20261014-183954-tour`: 153 executed, 139/143 scored correct (97.2%),
  ten excluded. The four scored misses are retained and explained in the
  handoff. No engine correction or relaxed timeout/ownership gate was added.
  Exit zero, zero surviving/forced children and dropped events.
- An initial stress smoke exposed missing root-PID forwarding into the shared
  driver. `16348d3` fixes that Lab-only attribution and tests owned/foreign/
  unknown window handling. Corrected `20261014-184549-stress`: 60 planned,
  54 executed, 33/33 scored correct, 21 excluded/informational; six Windows UIA
  cases did not run on Mac. Zero false presentations across 14 scored negatives.
  Multiple sizes/themes, rapid targets and late withholding exercised. Exit
  zero, no surviving/forced children or dropped events; source clean/unchanged.
- The earlier bare debug root PID 37654 was independently identified and closed
  through normal SIGINT. It was not attributed to a new Lab family. Never infer
  all Hanly instances are gone from one run's cleanup result alone.
- `8ea89d8` completes the Windows Lab FFI declarations for ownership, popup and
  browser-window probes. Actual ctypes callback regressions preserve high-bit
  parent/child handles and negative geometry; native Windows behavior still
  requires the host checklist below. No production build changed.
- `20261014-185330-run` verified restored canonical grants, then ended at its
  bounded 1,200s duration normally, with zero surviving/forced children. A stale
  CUA binding subsequently reopened a normal instance; it was closed via Quit
  without editing its preferences. Check live process identity before binding
  a closed app. Do not reopen a stale binding merely to inspect cleanup.

### Final closure and native limitations

`20261014-203458-run` used the final release, approved grants, private runtime
and disposable profile. It reached Armed with the Control Center hidden. The
human was asked to activate Safari's authored “Hanly controlled Mac acceptance”
window and physically press Control+Shift+F9/F10 twice each. Their uncertain
done reply was checked: no native shortcut edge had arrived. A clarification
specified Safari's Window menu and Fn. The bounded prerequisite observer still
could not confirm both Safari foreground and hardware edges, drove no controlled
pointer input and ended with `human_foreground_and_keyboard_not_confirmed`.
Neither that uncertain reply nor background AX clicks are counted as a pass.

The recording began at clean `16348d3`; Windows-only Lab FFI and docs changed
during it. Its rebuilt report is at `8ea89d8` with dirty docs, while the frozen
product remains `0b8a9f4`. It supplies input/cleanup evidence, not a controlled
latency or accuracy benchmark. Normal SIGINT ended the 846.6s recording with
2,768 events, zero dropped events, exit zero, no surviving/forced children.
All eleven sampled PIDs were independently absent afterwards. A separate process
scan found no Hanly root. The exact task-owned loopback server, prerequisite
observer and earlier bare debug root were absent too. No background task is
still waiting or running.

Remaining acceptance boundaries, explicitly recorded in the one handoff:

1. Real Safari activation, controlled native AX versus OCR, and foreground
   preservation across popup presentation. CUA can operate a Safari text box
   while macOS still reports another app foreground; that action is insufficient
   focus evidence. Do not bypass the tool limit with alternate desktop control.
2. Physical default shortcuts and actual Dock/Cmd+Tab activation. Synthesized
   held edges/actions and normal close/reopen already pass; hardware input was
   not observed in the last user-assisted attempt.
3. Additional physical displays, then Windows/Linux native behavior on their
   own hosts. Retina drag/cancel and shared geometry/FFI contracts already pass;
   one connected Mac display cannot establish mixed-monitor behavior.

No additional implementation decision or permission approval is needed for the
completed Mac code work. Canonical Screen Recording and Accessibility grants
are already approved and verified; do not ask again for the same grants. Any
future physical acceptance attempt must launch a fresh isolated run and confirm
its live PID before binding CUA. Do not reopen a stale binding after its bounded
session ended. Only an actual OS credential/Touch ID prompt requires takeover.

Registered October 7 Qt recordings are incompatible with protocol-v3 launch/
raster measurements; no general RAM savings claim is supported. The code and
optimization review, logical local commits, process teardown and comprehensive
handoff are complete within these explicit native limitations. Playwright
planning remains a separate follow-up. No push, merge, tag or release.

Branch: `desktop/tauri-migration`, based on `main` at `0902075`. Preserve
`spike/desktop-renderers` at preservation commit `39fc4e7` until the official
migration is complete. Main and origin/main were both `0902075` when fetched;
the branch was created there without merging the experimental branch. The spike
proved a shared React renderer against the old Qt shell; it did not prove this
Qt-free runtime, complete packaging, updater compatibility or Windows behavior.

## Local commit map

| Commit | Completed boundary and verification | Evidence at that historical boundary |
|---|---|---|
| `39fc4e7` on `spike/desktop-renderers` | Preserved spike sources/docs only; 14 focused Python and 6 Electron tests, Lab Ruff and full Python mypy passed before switching. | Experimental Qt-hosted renderer evidence stays separate; no spike merge. |
| `c4cbb97` | Approved ownership overlays and synchronized architecture visuals; 6 invariant tests passed. | Replace baseline descriptions when the actual production migration reaches parity. |
| `4f48f5c` | Qt-free service protocol/config/logs; 11 focused service process/isolation tests, Ruff and mypy passed. | Runtime acquisition/lookup/provisioning/updater composition and worker-family lifecycle. |
| `c106a54` | Official React workspace and stable exact lock; 9 contract tests, 5 DOM interaction tests, strict types and Vite build passed. | Complete behavior/visual parity for every action, dialog and popup/selector scenario. |
| `09f2912` | Rust native/IPC supervision foundation; 12 tests, Clippy/rustfmt and isolated debug Mac UI/root-service shutdown checks passed. | Native adapters, restart/signals, fresh release bundle/updater and Lab acceptance. |
| `62f7612` | Complete React state/actions/dialogs/popup/selector interactions; aligned settings and full-height shell. | 40 UI + 9 contract tests, types/build; native source visual checks passed. |
| `e02c011` | Real async service/runtime, native input seam, acquisition/lookup and clean protocol shutdown. | 72 focused checks; final portable/native gates pass. |
| `1e0ded9` | Native windows, context, supervision, transactional hotkeys and root readiness. | Rust 15 + Clippy/fmt; native capture/shortcut acceptance still unverified. |
| `624ba53` | Removed production Qt adapters/assets and migrated retained tests. | Portable 2,569 and native 86 passed. |
| `e8fca98` | Official Lab launch, family attribution and private-evidence boundary. | 518 portable Lab and native corpus fixture passed; successful hover recording still absent. |
| `96cc73e` | Coordinated native/service packaging, updater transition and CI dependency ordering. | All 7 packaged Mac gates passed with native host access; frozen OCR/lookup, ordinary-root acknowledgement and failed-root rollback verified. |
| `422bb07` | Collapsed panels are inert and hidden from accessibility. | 40 React interactions, types/build and final 7-test packaged gate passed; hidden region controls absent from actual packaged AX tree. |
| `805ad5d` | Typed Python test/service cleanup; no inline suppressions. | Portable/native gates pass. |
| `ca27111`, `3565de8` | Popup window authority, counter translation and recovery freshness. | Rust 17 regressions + Clippy/fmt pass; live popup checks remain permission-dependent. |
| `8b9a4ed` | React formatting and enforced unused declarations. | React 40, Node 9, TypeScript/build pass. |
| `ff64a87`, `2b93252` | Qt-free Lab, public Mac launch/FIFO, Fn input, report cleanup and native FFI signatures. | Lab 548 portable + actual Mac raster/ownership pass; scored capture tour needs debug grants. |
| `dc8d6f4` | Current runtime/setup/code-map and synchronized architecture guidance. | Architecture/packaging focused gates pass. |
| `0b8a9f4` | Rendered popup acknowledgement, request freshness and expansion identity. | Final portable/native/seven packaged gates and live release popup pass. |
| `e6250f7` | Fresh process identity and failed-adoption cleanup. | 549 portable Lab checks and actual corrected native adoption/cleanup. |
| `16348d3` | Stress desktop ownership forwarding. | 97 focused checks and corrected 33/33 scored stress smoke. |
| `8ea89d8` | Windows Lab window-query handle/callback signatures. | 106 focused checks, full Ruff and mypy over 344 files. |

The human explicitly requested the cleanup, code review and optimization
continuation. Codex performed that requested review in this resumed run. No
independent/cross-provider reviewer, push, merge, tag or release occurred.

## Baseline surface and replacement inventory

The implementation below is the 0902075 V1 baseline. Existing behavior remains
the acceptance reference until its replacement is implemented and verified.
The target is Tauri/Rust for the one native shell, React/TypeScript for every
desktop UI, a supervised Qt-free Python desktop service, and the existing
client-independent `hanly` engine with its isolated lookup child.

| Existing surface or action | Current owner and behavior to preserve | Approved replacement |
|---|---|---|
| First run, startup, retry and readiness | `cli.py`, `first_run.py`, `StartupCoordinator`, `runtime.py`; shell opens before configuration/resource work, provisioning runs off the UI thread, failures can retry. Runtime readiness and provider residency are separate. | Tauri opens immediately; supervised Python service provisions and prepares asynchronously, streams status, and retries through one service owner. Rust process health is separate from service/runtime readiness. |
| Capture page | `assets/control_center/index.html` + `control_center.js`, `ControlCenterBridge`: start/stop, current monitor or selected region, cursor/monitor target, region coordinate edits/apply/clear, select area, hover delay, lookup preload, recognizer choice. | React Control Center page; typed commands for settings/actions and live service state. Preserve validation, persisted values, monitor enumeration and current appearance. |
| Permissions and first-run prompts | `permissions.py`, `permissions_darwin.py`, `hanly_dialog.py`, selector and Control Center: display state, request OS permission, refresh after Settings changes, initial whole-monitor/region choice, cancel without changing prior settings. | React presentation; Rust native permission/deep-link and dialog adapters; Python retains permission policy/config values. First-run and in-app selection use the same validated region contract. |
| Shortcuts and hover mode | `hotkeys.py`, `hotkeys_darwin.py`, `ControlCenterBridge`: Push to Hover, Pause/Continue Hover, Start/Stop Capture; configurable chords; push action ends on key release; one-shot manual lookup remains bindable. | Rust registers native global shortcuts and reports press/release edges; Python owns action policy and hover state. React edits and displays registered bindings. Preserve collision/error feedback and defaults. |
| Appearance and popup preferences | Control Center Appearance: system/light/dark, default compact/expanded popup, technical-detail level; the native Control Center frame follows the resolved theme. `qt_theme.py` and `popup/presentation.py` resolve presentation values. | React tokenized styles shared by all windows; system theme events and native title-bar colors from Rust; Python persists settings and returns normalized popup presentation. Match the current visual identity before any redesign. |
| Dictionary popup | `popup/presentation.py`, `popup/qt.py`, `PopupController`: compact/expanded card, headword/Hanja, definitions/senses, decomposition and selected token, alternate entries, technical details, close/expand, retained answer and pointer-crossing grace, cursor/screen-aware placement. | A transient React/Tauri popup window rendering only normalized `LookupResult` presentation. Rust owns geometry, focus/activation and window lifecycle; Python performs the final current-request check before publication. |
| Updates and resources | Control Center Updates + `updates/*`: check, progress/activity, resource install/cancel, app-update staging, explicit full-download confirmation, release notes; verified inventory, signatures, ownership, handoff, acknowledgement and rollback. | React presents status/confirmation; Python retains update preparation and transaction logic; Rust owns process restart/supervision. New-install acknowledgement is a Tauri root-readiness event after the new Rust app root starts and validates its service handshake, never Python service readiness alone. Keep the existing updater; do not silently switch to Tauri's updater plugin. |
| Diagnostics and logs | `diagnostics.py`, `runtime_status.py`, `runtime_trace.py`, Control Center Logs: readiness recheck, activity filtering by level/subsystem and search, refresh/copy/save report/clear, bounded session logs; startup, connection and action errors have retry/clear paths. | Python retains logging, status and explicit export behavior. Rust forwards bounded snapshots/events and owns native clipboard access; React renders filters and invokes only allowlisted commands. Ordinary traces retain no recognized text or pixels. |
| Shell, tray and reopening | `application.py`, `DesktopApplication`, `tray.py`, `app_reopen_darwin.py`: one persistent shell; tray status, Start/Resume, Pause, Open Control Center and Quit; app activation/reopen and Control Center re-show; close/reopen has one live window owner and bounded cleanup. | Tauri root owns native lifecycle, tray, activation, reopen and all webview windows. React Control Center close hides/closes that window without killing the root; tray reopen focuses the same window or creates one after its prior owner exits. |
| Region overlay and screen choice | `acquisition/selector.py`, `hanly_dialog.py`, Qt screen geometry: cross-monitor drag, negative virtual-desktop origins, escape/right-click cancel, tiny/out-of-screen rejection, saved global rectangle. | Dedicated React selector window plus Rust screen/coordinate adapter; keep physical/logical/DPI conversion explicit and reject invalid regions before Python persistence. |
| Hover, acquisition and lookup | `MouseObserver`, `HoverController`, `HoverLookupRuntime`, `CaptureService`, AX/UIA direct text, OCR fallback, `LookupController` / `JobExecutor` / `lookup/process.py`: direct-first acquisition, small ROI only, latest-wins, provider isolation, final currency gate, normal non-success outcomes, popup retention/crossing. | Python service retains business rules, acquisition, capture/monitor preferences, hover and request currency; `hanly` stays unchanged and client-independent. The service keeps heavy Vision/EasyOCR + Kiwi + KRDICT in its unloadable spawned lookup child. Rust relays normalized events; React does no OCR, lookup or arbitrary OS access. |
| Application identity and user data | `app_identity_darwin.py`, `paths.py`, build identity/inventory: `io.github.thiagoross1.hanly`, existing settings/runtime/recovery paths, icons and update install root. | Preserve identity, data, resources and recovery semantics across the transition. Document and test old-layout discovery/migration before changing any path or product identifier. |

## Framework and lifecycle replacement map

| Current dependency or adapter | Responsibility now | Replacement boundary |
|---|---|---|
| `qt_bootstrap.py`, `signal_bridge.py`, `application.py`, `app_icon.py` | QApplication, one event loop, Qt callback dispatch, OS signal shutdown, startup wiring, startup error dialogs and application QIcon. | Tauri owns the native event loop, signals, native dialogs and app icon; Python service has an independent entrypoint and explicit request/event loop. Keep `freeze_support()` first in that Python entrypoint because the packaged lookup child uses spawn. |
| `hover/qt_scheduler.py` | Single-shot dwell and popup-crossing timers on the Qt loop. | Python scheduler with an injected clock/timer or service event loop; preserve cancellation and one-pending-delay semantics. |
| `popup/qt.py`, `popup/macos.py`, `qt_theme.py`, `window_frame_win32.py` | Non-activating always-on-top popup, screen placement/resize, system theme, macOS inactive visibility, Windows frame behavior. | React popup plus small public-API Rust platform adapters. Validate native non-activation, focus, pointer crossing, DPI and multi-monitor coordinates on each OS. |
| `manual_lookup.py`, `app_reopen_darwin.py` | Read the native cursor and coordinate app/Dock reopen and activation through Qt. | Rust passes cursor/screen context to Python and owns app reopen/activation; Python keeps manual lookup policy and request flow. |
| `acquisition/selector.py`, `hanly_dialog.py` | Qt prompt and selection overlay; currently imported through the Control Center bridge. | Tauri/React selector and dialogs; remove these imports from service bootstrap. Keep selection geometry and validation policy in Qt-free Python contracts. |
| `control_center/host.py`, `control_center/process.py`, `control_center/bridge.py` | A separately spawned pywebview/QtWebEngine window, Qt host lifecycle, page proxy, allowlisted Python operations, state refresh, clipboard copy, Windows native-frame theme and foreground handoff to parent. | Control Center becomes a Tauri window in the root process. React uses scoped Tauri commands/events; Rust owns clipboard and native-frame adapters; Python receives only versioned, bounded, per-window authorized requests. Preserve one-window ownership, refresh coalescing and foreground handoff for selector/permission UI. |
| `tray.py` and `hotkeys*` native backends | pystray adapter plus global key listener/edge detection; dispatches policy callbacks to Qt. | Rust owns tray and native key registration/edges. Python retains action/configuration policy. Keep push-to-hover release observable and tests must prove it. |
| `diagnostics.py` Qt message hook and `self_check.py` UI probe | `qInstallMessageHandler`, Qt package reporting and a frozen pywebview document/bridge round trip. | Remove Qt-specific diagnostics; package self-check must exercise the Tauri root, React route/bridge, Python handshake and a real isolated lookup. A successful service start alone is not a usable-window check. |
| `hanly_app.cli:main`, `packaging/entrypoint.py`, `pyproject.toml`, `packaging/hanly-desktop.spec`, PyInstaller hooks/constraints and workflows | One Python user-facing entrypoint; production PyQt6, QtWebEngine and pywebview collection; Windows/macOS/Linux build and packaged tests. | Tauri becomes the user-facing executable; the frozen Python entrypoint becomes an internal `--service` role and still calls `freeze_support()` before spawned-child dispatch. Replace product inventory with Tauri plus bundled Python runtime/providers/resources. Remove Qt/WebEngine/pywebview from production dependencies/hooks only after parity tests pass; users install no Python/Rust/Node. |

Qt is not isolated to a visible renderer: the scheduler, popup, selection,
bootstrap/dispatch, app frame, diagnostics, package extras, frozen hooks and
native tests are production dependencies too. The service must import without
PyQt, Qt WebEngine or pywebview anywhere in its transitive startup path.

## Process ownership and private IPC contract

```text
Hanly Tauri/Rust root
  ├─ React Control Center / popup / region-selector windows (all product UI)
  └─ one supervised Python desktop service (domain policy, OS acquisition,
       config, resources, updates, hover and lookup coordination)
       └─ one spawned lookup child (OCR, Kiwi, KRDICT and LookupPipeline)
```

Rust owns native windows, tray, app activation/reopen, platform adapters, child
supervision, IPC validation/dispatch and whole-family shutdown. React owns
presentation and interaction only. Python owns desktop business rules, config,
resource acquisition, AX/UIA and capture policy, hover decisions, request IDs
and final currency check, lookup execution and updater transactions. The
`hanly` engine owns only reusable lookup contracts/providers/pipeline. The
lookup child owns concrete heavy providers and closes them on the thread/process
that created them.

Use private stdin/stdout JSONL between Rust and the Python service; no listening
socket, shell command or arbitrary method lookup. Protocol v1 is:

- Rust request: `{"version":1,"type":"request","id":"…","method":"…","params":{},"window":"…"}`.
- Service reply: `{"version":1,"type":"reply","id":"…","result":{…}}` or `{"version":1,"type":"reply","id":"…","error":{"code":"…","message":"…"}}`.
- Service event: `{"version":1,"type":"event","sequence":1,"event":"…","payload":{…}}`.
- Maximum frame: 1 MiB; at most 32 outstanding requests. Enforce strict JSON,
  unique keys, bounded identifiers/depth/error text, monotonic event sequence,
  explicit methods and parameter shapes, and per-window authorization.
- Stdout carries frames only; diagnostics go to the private session log/stderr.
  A disconnect fails pending requests, marks runtime unavailable, attempts only
  the defined service restart path, and never leaves a detached lookup child.
- The internal frozen service is console-capable with redirected JSONL pipes;
  Windows hides its console. Its entrypoint calls `freeze_support()` first,
  and graceful shutdown returns normally after the service/lookup owner closes.
- Python emits only normalized JSON values. The final request-currency check
  remains in Python immediately before popup publication; a later frontend
  sequence check may discard superseded presentation but cannot replace it.
- Shutdown stops admission, cancels hover work, stops capture/hotkeys, closes
  and joins the lookup child, flushes diagnostics, replies when possible, then
  exits. Rust waits a bounded interval and terminates the process family only
  after graceful shutdown fails.
- Updater handoff waits for the new Tauri/Rust root after both the service
  handshake and React frontend readiness. Provider preload/runtime readiness
  remains a separate milestone; a service handshake alone never commits an update.

## Test migration inventory

| Existing tests | Classification and destination |
|---|---|
| `tests/krdict/*`, engine/provider/pipeline/contracts, language and word resolution, resource validation, package boundary/imports | Keep as engine or Qt-free Python behavior tests. Engine outputs and provider seams must remain equivalent. |
| `test_app_config.py`, `test_runtime.py`, `test_runtime_status.py`, `test_first_run.py`, `test_owned_cleanup.py`, `test_diagnostics.py`, `test_update_*`, `test_app_update_*`, `test_update_coordinator.py`, `test_update_service.py` | Keep domain/config/resource/updater guarantees. Port UI dispatch and root lifecycle seams; extend install-tree compatibility, new-root acknowledgement and rollback cases. |
| `test_capture.py`, `test_text_acquisition*`, `test_direct_text_routing.py`, `test_mouse_observer.py`, `test_hover_controller.py`, `test_hover_lookup*`, `test_lookup_controller.py`, `test_lookup_process.py`, `test_job_executor.py`, `test_manual_lookup.py`, `test_retained_target_evidence.py` | Keep Qt-free behavior contracts; add service IPC, restart, ordering, 1 MiB/32 pending, malformed frame, per-window authorization and disconnect/cleanup coverage. |
| `test_qt_bootstrap.py`, `test_signal_bridge.py`, `test_capture_selector.py`, Qt-specific cases in `test_popup.py`, `native/shared/test_qt_hover_scheduler.py`, `test_hover_exit_qt.py`, `test_qt_popup_window.py`, `test_qt_screen.py`, `native/macos/test_popup_panel.py`, `native/shared/test_capture_prompt_shutdown.py`, `test_app_icon_qt.py`, `native/windows/test_window_frame.py` | Qt adapter tests: port each behavior to Rust/native window or Python scheduler boundary before removing the old test. Keep the Qt-independent `popup/presentation.py` placement/content assertions. Retain genuine geometry, focus, cleanup and selection assertions. |
| `test_control_center.py`, `test_control_center_host.py`, `test_control_center_process.py`, `test_control_center_refresh.py`, `native/macos/test_control_center_identity.py`, `native/shared/test_control_center_combobox.py`, `test_control_center_copy.py`, `test_control_center_layout.py`, `test_control_center_lifecycle.py`, `test_webengine_startup.py`, `native/windows/test_webengine_arguments.py`, `tests/hanly_fixtures/assets/control_center_harness.js` | Keep Python action validation/configuration semantics in service tests; renderer and settings interactions belong in Vitest React DOM tests; host/process/WebEngine behavior belongs in Rust window/command/lifecycle tests. The legacy refresh JS harness is removed after React behavior coverage; host-only cases remain until native replacements pass. |
| `tests/packaged/*`, `test_packaging.py`, `test_release_build.py`, `test_release_products.py`, workflow checks | Replace PyInstaller inventory/self-check assumptions with Tauri + sidecar/runtime identity and inventory tests, real fresh-bundle startup, user-data transition and updater smoke. Preserve version/source identity and target-platform coverage. |
| `lab/tests/*` plus Lab app launch/control/sampling tests | Port launch/control/observation to the official root and count the whole process family (Tauri + Python service + lookup child + owned helpers). Preserve privacy and ownership guards. |

No framework test is removed just because it names Qt. A test is obsolete only
when its responsibility no longer exists and that fact is recorded with a
replacement or a clear explanation.

The former `test_control_center_refresh.py` and its JS harness are now replaced
by `apps/desktop/tests/ui/desktop-pages.test.tsx`: the 40 DOM tests cover
readiness and update polling, poll failure/reconnect, event state replacement,
permission recheck on return from OS settings, stable navigation focus and
in-progress settings edits, shortcut and delay validation, update confirmation
and cancellation, logs filtering/copy/export, and popup/region routes. The
Python `test_control_center.py` keeps bridge business rules but no longer
asserts legacy page HTML, JavaScript or CSS. `test_theme_contrast.py` reads the
React palette tokens directly instead of importing the Qt palette; its light
muted-text token was adjusted to clear 4.5:1 on the popup footer surface.
Focused evidence: `npm run test:ui` (40 passed), `npm run check`, `npm run
build`, `pytest tests/test_control_center.py tests/test_theme_contrast.py -q`
(76 passed), and Ruff on the edited Python tests.

## Current execution state

| Phase | Implemented boundary | Remaining evidence |
|---|---|---|
| A | Inventory, approved ownership/IPC contracts and synchronized invariants. | None. |
| B | Asynchronous service, runtime/lookup composition, bounded IPC and family supervision. | None in verified Mac scenarios. |
| C | All React surfaces and interactions; actual popup/selector and corrected shell/settings layout. | Native foreground/AX reader confirmation. |
| D | Native windows, tray/reopen, synthetic held shortcuts, permissions, timers, crossing and shutdown. | Physical keyboard, Dock/Cmd+Tab, popup nonactivation and mixed-monitor hardware. |
| E | Coordinated Tauri/Python product, existing updater transition/ack/rollback and CI. | Windows/Linux host execution. |
| F | Lab attribution/privacy, scored tour/stress, legacy retirement, detailed handoff and independent zero-survivor closure. | Human/hardware acceptance limits above. |

## Native Windows continuation checklist

Run on a real Windows desktop after the shared contract and platform adapter
land. Hosted/simulated providers do not establish Windows acceptance. From a
PowerShell checkout, use a disposable profile and install fixture; do not point
the updater at the user's Hanly installation or settings.

```powershell
py -3.10 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install --group dev
& .\.venv\Scripts\python.exe -m pip install -e packages/hanly
& .\.venv\Scripts\python.exe -m pip install -e 'packages/hanly-app[runtime]'
& .\.venv\Scripts\python.exe tools/prepare_easyocr_models.py
& .\.venv\Scripts\python.exe tools/build_smoke_krdict.py data/generated/krdict.sqlite3
& .\.venv\Scripts\python.exe -m pytest --suite portable
& .\.venv\Scripts\python.exe -m ruff check packages packaging tests tools lab
& .\.venv\Scripts\python.exe -m mypy packages packaging tests tools lab
$env:HANLY_REQUIRE_NATIVE = "1"
& .\.venv\Scripts\python.exe -m pytest --suite native
Push-Location apps/desktop
npm ci
npm run check
npm test
npm run test:ui
npm run build
Pop-Location
cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml --locked
cargo clippy --manifest-path apps/desktop/src-tauri/Cargo.toml --all-targets --locked -- -D warnings
cargo fmt --manifest-path apps/desktop/src-tauri/Cargo.toml --check
& .\.venv\Scripts\python.exe tools/build_package.py
$env:HANLY_REQUIRE_PACKAGED = "1"
# Set HANLY_PACKAGED_APP to the fresh bundle's executable or install fixture.
& .\.venv\Scripts\python.exe -m pytest --suite packaged
```

The exact native/build commands must be updated here if the official manifests
choose different scripts or packaging hooks. Then, on the produced Windows
bundle and a temporary `%LOCALAPPDATA%` profile:

1. Install/run a fresh bundle without developer Python, Rust or Node on PATH;
   verify executable identity, sidecar/runtime inventory and WebView2 startup.
2. Confirm first-run settings/resource provisioning stays responsive, reaches
   accurate runtime/engine readiness, retries after a controlled failure, and
   never reports providers resident when they are unloaded.
3. Exercise tray reopen/quit, Control Center close/reopen, activation and
   Alt+Tab task switching, every page/action/dialog, permission
   refresh, settings persistence, logs/export, and scope errors from each
   window's command allowlist.
4. With monitor layouts that include mixed DPI and a negative secondary origin,
   select/cancel/apply regions and verify coordinates, cursor monitor choice,
   clipping and popup placement. Check UTF-16 offsets and AX/UIA acquisition,
   then OCR fallback on text rendered as raster/image.
5. Hold/release Push to Hover, pause/resume and start/stop shortcuts; test direct
   text and OCR, positive/negative Lab targets, compact/expanded/close, pointer
   crossing, non-activation, no stale popup and no focus theft.
6. Use a Lab-owned InPrivate Edge page only. Run `python -m lab` for a
   person-driven session, then `python -m lab tour --no-open` (and a compatible
   stress run if applicable); read summary/provenance/baseline before comparing.
   Confirm the report attributes Tauri, Python and lookup descendants together,
   and that no recognized text or pixels were retained.
7. With disposable old and new install trees, apply the official update fixture
   from the existing V1 layout. Check hash/signature/inventory/ownership,
   unchanged data paths, cancellation before mutation, new Tauri-root readiness
   before commit, rollback when root start or service handshake fails, and
   recovery after interruption. Confirm a Python-only service start cannot
   acknowledge the install.
8. Close the app normally and after a forced service/lookup crash; verify no
   Python service, lookup child, updater helper or tray owner remains. Record
   `HANLY_REQUIRE_NATIVE=1` and `HANLY_REQUIRE_PACKAGED=1` results from Windows
   CI in addition to the real-desktop checks.

Exact dependency locks and scripts are committed. Use the coordinated builder;
the checked-in Tauri config disables standalone bundling because its generated
service/resource overlay exists only during that build. The Mac debug app uses
developer Python and cannot establish Windows redirected stdio, Job ownership,
WebView2 behavior or updater acceptance.

## Linux validation limits

Hanly's current release workflow builds a Linux x86_64 tarball on Ubuntu and
runs native/packaged checks under Xvfb. CI can validate the Linux build, shared
protocol, Python behavior and the display-backed paths its virtual X server
exercises. It does not establish behavior on a person's Wayland compositor,
actual mixed-DPI/multi-monitor setup, accessibility bus, global shortcut
permissions, desktop tray/status-notifier implementation, focus/activation or
screen-capture portal.

Tauri's WebKitGTK and OS integration introduce a different system-library and
desktop-session boundary from the old Qt bundle. Keep the existing Linux
distribution product supported; record the exact supported distro/runtime
dependencies from the official build, run native checks on a real Linux session
when available, and mark absent compositor/portal/tray checks unverified.
This Mac session cannot claim Linux native acceptance. A passing Ubuntu/Xvfb
job is build/virtual-display evidence, not cross-desktop equivalence.

## Historical initial verification — 2026-10-13

The latest continuation results and active steps are listed at the top. Older
Phase A build `77d09d75-bbc9-4565-98d0-6ebb7f6304ad` from product commit
`422bb07` passed seven packaged gates and archive/signature checks, but it is
superseded by the final rebuild. Never infer its acceptance for new source.

Release recording `20261013-202154-run` was startup/idle only: 124.9s, family
peak RSS 246.7 MiB, 30–120s mean RSS 77.39 MiB / summed CPU 1.51%, runtime
preparation 9.576s, all nine attributed PIDs gone. It had no capture or lookup
and used the earlier protocol. October 7 Qt baselines are incompatible. No
memory-saving or first/warm lookup-latency claim follows from these recordings.

The single handoff remains `docs/execution/review-handoffs/desktop-tauri-migration.md`.
Its final continuation must distinguish completed code/build checks from native
acceptance blocked by OS access and unavailable cross-platform hardware.
