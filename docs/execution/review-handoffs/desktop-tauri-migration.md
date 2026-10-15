# Desktop Tauri Migration Review Handoff

**Current status — 2026-10-15, after the live acceptance pass.** Product
commit `e7ef391` is built as `20284932-80c5-4086-9015-5092705d6714` and
installed as `/Applications/Hanly.app`. All seven packaged checks and both
archive verifications pass. The live popup, shortcut, tray, Safari/TextEdit
and quit checks pass on the debug build of the same source. Only two things
are still open: the human's one-time grant for this build, and physical
keyboard confirmation. See "Live acceptance pass" at the end.

**Earlier status — 2026-10-15, after Phase B follow-up.** Product commit
`acd3c28` is built as `44161ec2-7c78-4765-a996-a231953b4f18`. It passes the
four headless packaged checks and both archive verifications. The three
window-opening packaged checks and all live acceptance still need the human
present. The grants from the previous ad-hoc build do not carry over to this
cdhash. See "Phase B follow-up" at the end.

**Phase B review — 2026-10-15 (supersedes the status line below where they differ).**
Reviewer: Claude (Opus 5.5), chosen by the human, reviewing `0902075..0c93861`.
The human then authorized fixing the findings. The fixes are uncommitted in the
working tree on top of `0c93861`. **The sealed app/archives are unchanged
(`96868d8`, build `284bd3e3…`)**, and none of these fixes has been built or
tested live. See "Phase B review findings and fixes" at the end. Remaining
work step 1 must now build the reviewed tree, not `ccf230d`.

**Previous status — 2026-10-15:** paused at the human's explicit remaining-budget
boundary. Migration, legacy cleanup, requested code review, Mac shortcuts and
popup corrections are implemented. Latest product commit is `ccf230d`; its
20 Rust tests, all-target Clippy with warnings denied, rustfmt and diff checks
pass. **The newest native-frame fix has not been rebuilt or tested live. The
migration must not be called fully accepted yet.** The sealed local app/archives
still contain `96868d8`, build `284bd3e3-bef5-406f-8e16-6add3184a5c1`.

Both permissions were restored with explicit human approval and verified granted
inside that sealed app after normal restart. Live popup evidence found and
motivated the latest fix. No Hanly root/service/lookup, acceptance fixture,
loopback fixture server or package/build job was running at the final host
process check. No permission entry was changed during this budget-limited close.
The human reported that the Mac was disrupted during the preceding test work;
the cause of that machine-wide symptom has not been established. Do not claim
that the latest popup correction proves that broader symptom resolved.

Branch `desktop/tauri-migration`; all commits remain local. No push, merge, tag
or public release. This is the single cumulative handoff. The final section
records the newest live evidence and the complete remaining work. Earlier
`0b8a9f4`/`96868d8` results below retain their original provenance and are
historical where superseded; they are not results for `ccf230d`.

## Implemented behavior and ownership

Tauri/Rust owns the one native root, system webviews, tray, shortcuts, selection,
window lifecycle and supervised process family. React owns all Control Center,
popup, selector and dialog presentation. The Qt-free Python desktop service
owns configuration, async provisioning, direct-first AX/UIA acquisition,
hover/request currency, resource updates and the existing verified updater.
Heavy providers stay in its isolated, unloadable lookup child. Engine source
is unchanged; `hanly-app → hanly` remains the only package dependency direction.

Private JSONL v1 retains 1 MiB frames, 32 pending requests, strict schemas,
IDs/order, explicit methods and per-window allowlists. Python keeps the final
request-currency gate. Readiness and provider residency remain separate.
New-root acknowledgement requires both the service handshake and React readiness.
No Tauri updater-plugin replacement or production Node service was added.

All six Control Center pages, settings, confirmations, diagnostics and popup/
selector actions are connected. The responsive shell fills its window, the
settings columns align, and collapsed region controls are inert and absent
from accessibility. Hanly's approved visual identity and native Mac icon are
preserved. `Hanly.app` is the normal packaged app; source `hanly` and
`python -m hanly_app` launch a built native root. npm is for development/builds.

Production and Lab Qt/WebEngine/pywebview adapters and dependencies are removed.
Lab uses Pillow with AppKit on Mac and Tk on Windows/Linux. Its former private
launcher is removed: public LaunchServices adopts the exact fresh root PID,
forwards allowlisted environment and carries debug evidence through a mode-0600
FIFO. Ordinary traces contain no recognized text or pixels. Qt names remain
only in exclusion/inventory guards, historical architecture and deliberate
old-product updater fixtures; there is no hidden legacy UI fallback.

## Local commits

| Commits | Boundary |
|---|---|
| `c4cbb97`, `4f48f5c`, `c106a54`, `09f2912`, `6213c2b` | Approved contracts and initial service/React/Rust foundations. |
| `62f7612`, `e02c011`, `1e0ded9` | UI parity, runtime acquisition/lookup, native ownership/supervision. |
| `624ba53`, `e8fca98`, `96cc73e`, `422bb07` | Production Qt retirement, Lab, packaging/updater and hidden-panel accessibility. |
| `805ad5d` | Typed service/test cleanup; removes inline Python suppressions. |
| `ca27111`, `3565de8`, `a54784c` | Popup authority, counter translation, recovery freshness and fractional geometry. |
| `0b8a9f4` | Native-frame presentation acknowledgement, deduplication, freshness and expansion identity. |
| `e6250f7` | Fresh LaunchServices process identity and exact-profile cleanup after failed adoption. |
| `16348d3` | Pass native desktop ownership into stress acquisition without admitting foreign/unknown windows. |
| `8ea89d8` | Declare pointer-width Windows Lab ownership/popup/browser query types and verify high-bit callback handles. |
| `8b9a4ed` | Readable React sources and enforced unused declarations. |
| `ff64a87`, `2b93252` | Qt-free Lab, public launch/FIFO, function-key input, cleanup and native handle contracts. |
| `dc8d6f4` | Runtime/setup/code-map and synchronized architecture guidance. |
| `776a7ef`, `19d5d67` | Mac letter defaults, native labels, conservative profile migration and platform-aware behavior fixtures. |
| `96868d8` | Measured popup presentation, public Mac corner clipping, anchored expansion and current-frame geometry. |
| `ccf230d` | Synchronous public AppKit frame commit before nonactivating popup show; negative-origin conversion coverage. |

Spike `39fc4e7` remains preserved on `spike/desktop-renderers`; it was not merged.
All commits are local under the explicit implementation authorization. No push,
merge, tag or release occurred. This remains the one handoff for the workstream.

## Latest verification

| Gate | Result |
|---|---|
| Full portable Python | 2,602 passed, 2 existing skips; final `0b8a9f4` source. |
| macOS native | 86 passed; actual Vision, capture/geometry and raster ownership assertions retained. |
| Latest portable Lab | 549 passed after the process-discovery/failed-adoption fix; 13 focused process tests also pass. |
| Native raster/launch cleanup focus | 13 passed; actual pixel colour/ownership and event-loop return verified. |
| Latest ownership/FFI regressions | 106 focused Lab checks passed after `8ea89d8`. |
| Ruff / mypy | Clean; full mypy checks 344 source files after `8ea89d8`. |
| React / Node | 40 UI + 9 contracts; TypeScript including unused checks and Vite production build passed. |
| Rust | 17 tests; Clippy warnings denied and rustfmt passed. |
| Workflow/raster focus | 94 passed after the final platform prerequisite changes. |
| Architecture/packaging source focus | 169 passed. |
| Final packaged | All 7 passed in 190.70s on build `7569005a`, product source `0b8a9f4`. |

The initial portable run exposed one obsolete Qt dependency-step assertion and
two sandbox-denied process checks. The migrated CI contract was corrected;
process checks were rerun with host access, then the full portable gate passed.
Native/framework tests used host access. No assertions, production timeouts or
currency/ownership checks were weakened to obtain these results.

## Actual Mac evidence and limits

The earlier source app exercised all six pages, settings/theme persistence,
default and approximately 730×563 layouts, scrolling, scope-dialog cancellation,
close/reopen with one root and confirmed Quit. The rebuilt package opens with
runtime ready/providers sleeping and the corrected layout. The actual collapsed
region controls remain absent from its AX tree.

The canonical `dist/macos/Hanly.app` was explicitly authorized for Screen
Recording and Accessibility. After refreshing its exact registrations it showed
both granted; real Start Capture reached Armed/Running, Stop returned Stopped.
Changing the ad-hoc signature required refreshing the exact registrations
despite ON switches. The earlier build `437cbe90` registrations were refreshed;
actual Start Capture reached Armed with the corrected frozen service.
The successor `7569005a` and rebuilt debug bundle initially reported required
despite macOS listing Hanly as enabled. The human approved both identities and
completed the canonical Screen Recording picker. Replacing its Accessibility
entry through the native picker, followed by normal Quit/restart, made both
grants visible inside Hanly. The same refresh enabled the debug scored runs.
Afterwards registrations were returned to the canonical release and both were
reverified in `20261014-185330-run`. These ad-hoc builds share an identifier but
have different signing identities; switching between them can invalidate an
ON entry. Production signing/notarization is outside this local migration.
The earlier permission probes stopped normally with exit zero and no surviving/
forced children; they were not capture acceptance. No extra product grant was
introduced.

The human's permission UX requirement is explicit: every required product grant
must be listed and actionable in Hanly's Permissions page. The current two
grants already follow that flow: OS request, direct privacy-pane link and
focus-return recheck; granted items stay visible. Screen Recording's actual
button opened the correct pane. The same two grants apply to the debug identity;
no third production grant was identified. macOS retains the final authorization.

The input investigation proved that ordinary synthetic function keys omitted
macOS SecondaryFn interpretation. Corrected Lab input delivered native press
and release and actual Start Capture to the packaged app. Letter chords worked
through either Carbon target. No unsupported production Carbon-target change
was adopted. Physical keyboard confirmation remains separate. Actual held
push-to-hover press/release, cache use, sticky readability and stopping new work
were verified with the approved synthetic input against the final release.

Actual Retina selector drag 450/450→1050/850 saved logical 225/225/300/200;
Escape retained that region. Only one display is connected. Negative-origin/
geometry contracts pass, but real mixed-DPI/multi-display selection needs a
host with that hardware.

`20261013-232232-tour` adopted the debug app and attributed its helpers through
LaunchServices, forwarded private evidence in memory and received native capture
edges. Capture was denied, so it supplies no successful scored hover or lookup
latency. Its first event-loop shutdown bypassed report finalization; that
implementation defect was fixed and a native return/cleanup check passed.
Other failed tours and startup-only recordings remain historical evidence.

The remaining Mac human-input acceptance is controlled Safari native AX versus
OCR with an independently established foreground application, popup
nonactivation from that reader, physical keyboard chords and actual Dock/Cmd+Tab
activation. Raster positives/negatives, multiple sizes/themes, popup rendering,
crossing, expansion/close, cache, held edges, stale withholding, scored Lab and
release family measurements now have actual evidence below. Mixed-display
geometry requires hardware absent from this Mac. No readiness/image self-check
is substituted for a native behavior check.

The `2b93252` package produced an actual controlled Safari OCR result for
학교, displayed the correct school definition and Hanja, and expanded/closed
through real React controls. Screen-point calibration used native Safari window
bounds and Lab owner checks; initial wrong-point attempts were UNUSABLE, not
passes. The actual run exposed a fractional `service.popup_geometry` TypeError.
`a54784c` encloses that logical rectangle with floor/ceil; 70 focused tests and
the full portable gate passed. The later final-release popup/retention check
below verifies the corrected frozen service. Ordinary traces remain text/pixel-free.

The `20261014-040129-run` summary reports Vision acquisition and a dictionary
entry, with current delivery in the recording but no live visual confirmation.
Its zero-popup and unseen-answer explanations cannot establish staleness: the
migrated service omitted the presentation trace. The 189.1s recording had
no dropped events, protocol v3, family peak 343.3 MiB and mean summed CPU 14.8%.
These whole-session values include startup and one cold lookup, not a steady
workload benchmark. Provider prewarm took 12.2s; the engine pipeline took 2.887s.
No user-visible latency is established. Automatic shutdown reported exit zero,
no remaining descendants and no forced kills. The subsequent controlled Safari
attempt refused a hover because Codex owned that screen point. Computer-use
forbids controlling Codex itself; the human must expose the controlled page.
The subsequent `20261014-040730-run` ended after 604.5s, with zero attempted
lookups and dropped events, exit zero, no surviving descendants or forced kills.
Its family peak was 205.5 MiB and whole-session mean summed CPU 1.6%. This is
idle/armed evidence only, with the same v3 provenance and no compatible Qt
baseline; it supplies no lookup or popup acceptance.

The resumed `20261014-144716-run` used the same `a54784c` frozen product. Actual
Lab-authored raster 학교 showed the expected school/Hanja/definition; Expand,
Close and transfer through the nearest popup edge worked. Fourteen movements
inside protection started no new lookup. A large diagonal jump outside the
narrow transfer corridor correctly dismissed it. The report's unseen-OCR and
zero-popup findings are invalidated by the missing trace. Confirmed normal Quit
ended the 918.8s session with exit zero, no survivors/forced kills or dropped
events. CUA app observation cannot establish foreground focus/nonactivation.

`0b8a9f4` fixes that telemetry seam: the existing `popup_visible` event is emitted
after React reports rendered geometry and the native resize succeeds, once per
answer. Stale acknowledgements and repeated geometry/expansion cannot emit it
again; expansion keeps the original request identity. The trace contains only
request ID and result status. The 77 focused service/popup/retention/loop checks
pass; full portable/native and final package/archive gates pass. The debug
bundle was rebuilt from current Rust/React source and its grants were later
refreshed for the scored runs below. No scored tour is inferred from release UI.

The final release probe `20261014-152133-run` exposed a Lab discovery timeout
with a root actually running. Cached psutil handles can describe a pre-exec
helper, so `e6250f7` reads fresh executable/argv identity and recovers/reaps a
fresh exact-profile root on failed adoption; pre-existing roots remain excluded.
Root 34394 was independently stopped via normal SIGINT with zero surviving
children. The bad recording's zero-survivor implication is not accepted.
The corrected native retry `20261014-152757-run` adopted root 35074 in 4.44s
with macOS responsibility attribution and ended after 186.2s with exit zero,
no surviving/forced children and no dropped events. Its family peak 250.5 MiB
and mean summed CPU 5.2% cover startup/idle only. Capture never started because
the new signature requires grants; no lookup/presentation latency follows.
The recording contains the then-uncommitted Lab fix, subsequently `e6250f7`.

The Dock activation/focus probe timed out in the computer-use service; no Safari
foreground/nonactivation pass follows from it. The controlled browser window was
visible and owned the hover point, but foreground focus was not established.
AX-native acquisition and focus checks therefore remain separate from the OCR
success. Root 14424 stopped through normal SIGINT; all ten sampler-attributed
root/service/lookup/WebKit PIDs were independently confirmed gone.

## Final release workload and scored Lab evidence

The acceptance below supersedes the permission-blocked probes, without changing
their recordings or converting their historical failures into passes. Ordinary
release traces remain text/pixel-free. Debug text/image retention was explicitly
enabled only for ownership-verified, Lab-authored fixtures; those artifacts stay
gitignored under `artifacts/lab/runs/`.

### Final packaged release: `20261014-183030-run`

Product `7569005a` / source `0b8a9f4`; Lab checkout `4c69ffa`, clean and unchanged
during recording. The run lasted 449.4s with 265 events and zero dropped events.

| Actual action | Observed result |
|---|---|
| Permissions after native registration refresh and restart | Screen Recording and Accessibility both displayed granted inside Hanly. |
| Start Capture | Armed, then Running after lookup; runtime/provider states stayed distinct. |
| Hover Lab raster 학교 | Correct 학교 / 學校 / school headword, English definition and analysis were visible in the real React popup. |
| Native rendered geometry | `popup_visible` acknowledged successful presentation with the original lookup ID; three answered hovers produced three acknowledgements. |
| Expand / Close | Compact width 340 logical points grew to 460, the actual content fit, and Close removed the popup. Expansion did not duplicate the presentation event. |
| Pointer transfer | Entering the nearest popup edge preserved the answer. Twenty protected pointer movements started no additional lookup. |
| Latin/digit/punctuation fixture | UNUSABLE, with no answer popup; a subsequent cache hit also preserved refusal. |
| Change hover mode through React | The disposable profile changed from always-active to Only while held and persisted the selected state. |
| Stationary Ctrl+Shift+Space hold | Native DOWN reached Python, submitted a lookup without requiring pointer movement, and displayed the cached answer. |
| Release / sticky readability | Native UP stopped new admission; the answer remained visible and readable while the pointer entered the popup with the chord released. |
| Movement with the chord released | Blank/Latin fixture movement produced no new lookup. A new held press over Latin produced a refused lookup without a popup. |
| Corrected synthetic F9 / F10 | Pause/resume and capture stop/start reached their respective action paths. Stop retired loaded providers; restart showed Armed with engine sleeping. |
| Quit confirmation | Normal Quit returned exit zero, with zero surviving descendants and zero forced children. |

The first cold answered hover took 4,750.7ms from the hover opportunity through
rendered presentation; the three-answer median was 340.2ms. The first engine
pipeline took 702.9ms and the next uncached successful pipeline 135.9ms. A later
cache-hit successful pipeline took 1.5ms. These are distinct measurements: a
backend cache hit is not an end-to-end popup latency. Runtime preparation was
reported at 4.44s from recording start. The whole-session sampled family peak
was 751.7MiB, mean summed CPU 3.2%; the native root peaked at 99.1MiB. The long
manual session includes startup, waiting, UI actions and a small lookup sample;
it is not a steady-state benchmark or a general latency guarantee.

### Debug tour: `20261014-183954-tour`

The native debug app ran with refreshed grants against the official source
service and rebuilt React/Rust. Source `4c69ffa` was clean and unchanged during
the 169.8s recording; protocol v3, zero dropped events, normal shutdown, exit
zero and zero surviving/forced children. This is debug workload evidence, kept
separate from the sealed release measurement above.

- Planned and executed: 153 authored minibook targets at 22px over three pages.
- Strict-headword-v3: 139/143 scored targets correct (97.2%); ten excluded by
  ownership checks. Excluded targets are not passes or OCR failures.
- Correct outcomes include 130 dictionary answers and nine refusals.
- Four scored misses remain visible in the report: first-cold 우리 returned no
  text, 누군가는 resolved through the unchanged language pipeline to 누구,
  드릴 selected its valid exact-surface dictionary reading rather than the
  story's intended 드리다, and one 곳입니다. hover remained inside the preceding
  answer's retained popup area and submitted no new lookup.
- The first-cold no-text sample included a 30.1s capture outlier. Later captures
  progressed normally; this run does not establish its cause. A separate stress
  rendering of 우리 answered successfully. No timeout was inflated, miss hidden,
  dictionary correction added or engine behavior changed to improve the score.
- Answer presentation p50 was 250.6ms over 132 answered pipeline observations;
  uncached OCR segment median was 57.4ms, capture 45.5ms and return/presentation
  30.7ms. These observation counts include incidental pointer-path work, not
  just the 143 scored targets.
- Sampled family peak 702.3MiB, mean summed CPU 18.0%; native root peak 101.1MiB.

The engine/dictionary source was not modified by this migration. The language
and exact-surface misses therefore remain engine-quality observations, not
evidence that the renderer changed the lookup answer. They are not relabelled
as correct. The retained-area case records the tour's approach limitation;
the separate held-mode release/repress check verifies the product's intended
way to ask for a new word while a sticky answer is present.

### Corrected stress smoke: `20261014-184549-stress`

An initial 20-case smoke exposed a Lab bug: `StressDriver` stored the root PID
for popup geometry but omitted it from its inherited ownership allowlist.
Hanly's own popup was consequently labelled foreign in valid acquisition
probes. `16348d3` forwards the already-validated desktop PID. Its regression
accepts the owned desktop but still refuses a foreign PID or unknown owner;
97 focused Lab checks, Ruff and full mypy (343 files) pass. This changes only
Lab and requires no product rebuild or altered signing identity.

The corrected run starts from clean `16348d3`, unchanged during recording:
109.0s, 3,275 events, zero dropped events, normal shutdown, exit zero and zero
surviving/forced children. Three cases per family produced 60 planned targets,
54 executed; six Windows-only UIA browser targets did not execute on macOS.
Of the executed targets, 33 were scored and 21 excluded or informational.

| Scored category | Actual result |
|---|---|
| Non-negative scored cases | 19/19 correct, including late-answer withholding; no missing/wrong presentations. |
| Refusal targets | 14/14 quiet; zero false presentations, timeouts or errors. |
| Representations | Headwords, prose, pointer positions, dense text, mixed Korean and raster-image text. |
| Negative content | Blank, numbers, punctuation, Latin, mixed Latin, icons, images without Korean and prior-popup locations where verifiable. |
| Rapid pointer movement | Three settled targets correct; incidental stale work remained subject to final currency checks. |
| Leave early | Two verifiable cases withheld their late answer; the other was excluded. |
| Changing / covered content | Informational evidence retained separately; not counted as strict positive/negative passes. |
| Presentation variation | Actual cases included multiple font sizes and light, dark and sepia themes. |

The sampled family peak was 452.3MiB, mean summed CPU 25.0%; native root peak
102.2MiB. These stress values and the tour values have different workload mixes
and are not a before/after performance comparison. Every excluded observation
remains excluded; the privacy probe was not widened to admit arbitrary apps.

### Process and grant closure

The release workload, tour and corrected stress each ended with zero surviving
owned children and no forced termination. A separately running unbundled debug
root, started before these resumed checks, was identified by exact executable,
PID/start time and lack of children. It was closed through normal SIGINT; it
was not mistaken for a child of the current Lab session. Whole-family claims
apply to the attributed run, not every unrelated process on the machine.

After debug acceptance, the native picker returned Screen Recording and
Accessibility to `dist/macos/Hanly.app`. A normal release restart verified both
granted inside Hanly. The bounded `20261014-185330-run` later ended normally
after its 1,200s duration, with no surviving/forced children. Reading a stale
computer-use binding can reopen an app after a bounded session has ended; an
observation-reopened normal instance was closed through its Quit confirmation
without changing its preferences. Rebind only after confirming a fresh owned
run is still alive. Do not infer current liveness from a stale UI binding.

The final user-assisted probe was `20261014-203458-run`. It reached Armed with
the canonical release and approved grants. The human's uncertain “done” reply
was checked against actual input telemetry: zero native physical shortcut edges
were observed. A clarification named Safari's Window menu, the exact authored
page and Control+Shift+Fn+F9/F10. A bounded read-only prerequisite observer still
could not establish Safari foreground plus the required key edges, so it drove
no controlled pointer input and recorded
`human_foreground_and_keyboard_not_confirmed`. Safari AX/nonactivation and
physical default shortcuts therefore remain unverified rather than failed or
passed product assertions.

That release recording started at clean `16348d3`; docs and Windows-only Lab
FFI changes landed during it, and its report was rebuilt at `8ea89d8` with dirty
docs. The frozen product did not change. It is used for input/cleanup evidence,
not a controlled latency, accuracy or before/after benchmark. It ended after
846.6s with 2,768 events, zero dropped events, normal SIGINT exit zero, zero
surviving children and zero forced children. All eleven sampled PIDs were
independently confirmed absent immediately afterwards. A separate enumeration
found no Hanly native root. The exact authored loopback server and prerequisite
observer also exited; the earlier unbundled debug root remained absent. There
is no pending background acceptance run or fixture server.

## Cleanup and optimization review

The human explicitly requested removal of dead/unused implementation and
replacement of suppression shortcuts. This review covered production Python,
Lab, React/TypeScript, Rust, tests, dependency declarations, packaging hooks,
CI and current runtime documentation.

- No active PyQt, Qt WebEngine or pywebview UI implementation or dependency
  remains in the official product or Lab. The historical spike is preserved
  deliberately. Old names in exclusion/inventory checks and old-to-new updater
  fixtures remain meaningful compatibility tests.
- Active sources contain no Python `# noqa` or `# type: ignore`, TypeScript
  suppression, ESLint-disable or Rust allow annotation. Invalid-input tests
  now express their dynamic boundary explicitly; real union/optional results
  are narrowed and native FFI contracts are typed instead of silenced.
- React source is formatted; TypeScript rejects unused parameters/locals.
  Obsolete adapters, helpers, assets and dependency groups were removed after
  their replacement responsibilities were covered. No hidden legacy fallback
  or second lifecycle owner was retained.
- Review fixes include popup authority, wire/content counters, replacement-
  service freshness, fractional geometry, rendered-presentation acknowledgement,
  Lab public launch identity/recovery, FIFO bounds, event-loop finalization,
  function-key edges, native handle widths and stress root attribution.
- The final Lab FFI sweep found additional window queries relying on ctypes'
  default integer signatures. `8ea89d8` declares HWND, callback, pointer and
  return types for point ownership, popup bounds and accessible browser probes.
  Three regressions exercise actual ctypes callback marshalling with handles
  above 32 bits, parent/child ownership and negative rectangle origins. The
  106-test focused gate, full Ruff and full mypy (344 files) pass. These are
  portable ABI-seam checks; they do not establish native Windows acceptance.
- The review identified capture and cold provider loading as measurable future
  work. It did not change preload policy, debounce, recognition semantics,
  provider choices or package contents to manufacture migration performance.
  There is no compatible Qt recording for a general RAM-saving claim.
- Processing/provider work remains isolated from React, and admission/currency,
  frame size, backpressure and ownership assertions were retained. The measured
  capture cost on the service owner thread is an explicit optimization follow-
  up, not a reason to introduce continuous full-screen OCR or weaken privacy.

Playwright implementation remains deferred as requested. React interaction
tests already cover UI behavior; a later Playwright plan must distinguish web
rendering tests from native permission, global shortcut, focus and packaged-
process acceptance. Neither a browser test nor a successful Rust API call can
replace those native checks.

## Acceptance matrix and explicit boundaries

| Responsibility | State and evidence |
|---|---|
| Official architecture, ownership and IPC | Implemented, documented and covered by Python/Rust/React boundaries. |
| Existing engine and dictionary behavior | Engine source unchanged; portable/native/frozen lookup gates retained. Four strict tour misses are reported, not hidden. |
| All desktop presentation and settings | React interactions, strict types/build and real Mac Control Center/popup/selector checks completed. |
| Legacy code and suppressions | Retired production/Lab Qt and pywebview; active inline suppressions absent; replacement tests mapped in the checkpoint. |
| Mac frozen product and updater | All seven final packaged checks, old-layout transition/acknowledgement/rollback, complete archive inventories and signatures verified. |
| Mac permission UX | Both required cards remain visible/actionable; exact privacy-pane links and canonical grants verified. No third grant. |
| Native raster lookup and popup behavior | Real release School lookup, negative refusal, rendering, expand/close, transfer, cache, held edges and provider unload verified. |
| Lab official-runtime integration | Public launch/responsibility/FIFO, complete family sampling, scored tour/stress and normal zero-survivor cleanup verified in recorded runs. |
| Physical default shortcuts | Synthetic Fn-aware edges/actions pass; the requested physical test has not produced observed native edges. Remains unverified. |
| Safari native AX and reader nonactivation | Controlled page exists and is measurable, but tool-addressed clicks/menu actions have not established Safari as the OS foreground app. Requires real activation before the final controlled probe. |
| Actual Dock/Cmd+Tab | Reopen/lifecycle contracts and close/reopen pass; physical task switching remains unverified. The Dock tool timed out and was not repeatedly retried. |
| Multiple physical displays | Contract/negative-origin/Retina coverage passes; only one real display is available. |
| Windows / Linux | Shared gates and build/CI adapters prepared; native acceptance explicitly belongs to their continuation hosts. |
| Distribution | Local ad-hoc build only. Commit authorization does not authorize push, merge, tag, public release, signing enrollment or notarization credentials. |

The missing Safari foreground evidence is a tool limitation, not a missing
permission approval. The human approved both grants and they are granted in the
canonical release. CUA can address Safari's AX controls while macOS reports Hanly, System Settings
or Codex foreground. A focused text box or a successful AX action is therefore
insufficient focus evidence. Owner checks refuse obstructed points, and no
alternate/private desktop-control interface is used to bypass that boundary.
The last controlled probe waited for actual Safari foreground and physical
native key edges before moving the pointer, then stopped with its precise
unconfirmed-prerequisite result. An uncertain human “done” without those
observations was not treated as a pass.

The absent physical key edges do not identify their cause: OS keyboard mapping,
the exact physical chord and native delivery still need to be isolated with an
observed keyboard attempt. The passing synthetic route does not dismiss a
possible physical-input problem. This is an unresolved native acceptance item
before claiming macOS fully accepted, alongside the reader-focus check.

No additional implementation decision or permission approval is needed for the
Mac code work already authorized. The bounded physical probe did not establish
its prerequisites, so this handoff records that exact acceptance gap rather
than claiming the whole Mac native matrix green. The packaged release and all
preceding successful evidence remain available independently of that gap. No
implementation, cleanup, test run, process teardown or documentation edit is
left silently running. Any future attempt at those human/hardware checks must
start a fresh isolated session; it must not reuse a closed CUA binding.

## Packaging and measurement provenance

Final build from `0b8a9f4f9a6a33fdfdc4bb4846e0f3a5e28cfba9` is stamped at
2026-10-14T18:02:50Z, build ID `7569005a-6a5a-4efc-9739-a54266b2855a`.
Product: `dist/macos/Hanly.app`, arm64, v1.1.0, bundle identifier
`io.github.thiagoross1.hanly`. It embeds React and its private frozen Python
service/providers/models, so users install no Node, Python or Rust.

All seven packaged checks passed on this exact final artifact, including frozen
OCR/lookup, native React readiness, ordinary root acknowledgement and failed-root
POSIX helper rollback. Update probes used disposable copies and profiles.
Extracted ZIP and DMG each match every one of the 3,762 manifest entries, with
zero missing, differing or unexpected files; inventory and strict deep ad-hoc
signatures passed. Earlier `422bb07`, `2b93252` and `a54784c` artifacts are
superseded. `e6250f7` changes only Lab and does not ship in the product; a later
Lab/docs HEAD must not replace the sealed product's source stamp.

Archive SHA-256:

- `hanly-desktop-macos.zip`: `90a299ef74f397d992c9f55788d8ad61fec2868dc883ff3d12bdb0a087478742`
- `hanly-desktop-macos.dmg`: `a3c9cad25914b82a3ffa636b13ef93d90e137a86979618ca0e438a0525001439`

Historical release idle recording `20261013-202154-run`: 124.9s, peak family RSS
246.7 MiB, 30–120s mean RSS 77.39 MiB / summed CPU 1.51%, runtime preparation
9.576s, all nine sampled PIDs gone. It had no capture/lookup. Protocol v3 now
separates public LaunchServices/Qt-free raster sessions from that recording.
Registered October 7 Qt baselines are incompatible. That idle recording supports
no RAM-saving or visible-latency claim; the later release workload supplies only
the explicitly bounded measurements above, not a general performance guarantee.

## Post-Bundle Review Outcome

Reviewer: Codex, same ecosystem, resumed run explicitly requested by the human;
2026-10-13–14. Code/cleanup review and automated/native raster acceptance are
recorded above; physical keyboard and Safari foreground/AX acceptance remain
human-input-dependent.
No independent or cross-provider review is claimed.

**Fixed now:** popup window authorization and event/content-counter mismatch;
missing native presentation acknowledgement and expansion request identity;
Lab pre-exec executable caching and recovery cleanup after failed root adoption;
stress ownership forwarding to its inherited acquisition driver;
pointer-width ownership/popup/browser query signatures in Lab's Windows seams;
React freshness after service replacement; Lab synthetic function-key edges;
Lab shutdown that bypassed reporting; bounded FIFO failed-launch cleanup;
Windows import scope, pointer-width Windows/X11 APIs and signed DPI results;
fractional native geometry rejected by integer retention bounds;
obsolete Qt dependencies/adapters/setup, unused helpers and inline suppressions;
React formatting/unused declarations and stale architecture/source mappings.

**Deferred considerations:** physical keyboard and Safari foreground/AX checks
need the requested real activation/input; permissions are already granted.
Physical mixed-display geometry and Windows/Linux behavior need their native hosts,
before claiming platform acceptance. Provider prewarming, package pruning and
further performance tuning wait for functional workload acceptance and measured
bottlenecks. Playwright planning follows migration acceptance.

**Dismissed:** replacing the production Carbon target; public-API probes showed
both targets delivering letter chords and the corrected Fn input delivering
function-key edges. Old Qt names in explicit inventory exclusions and old→new
update fixtures remain intentional compatibility guards, not live dependencies.

## Reproduction and cross-platform continuation

Use the repository venv; the default global Python lacks required packages.
Cargo must be on PATH for Tauri builds. From the repository root:

```sh
.venv/bin/python -m pytest --suite portable
.venv/bin/python -m pytest --suite native
.venv/bin/python -m ruff check packages packaging tests tools lab
.venv/bin/python -m mypy packages packaging tests tools lab
npm run --prefix apps/desktop check
npm test --prefix apps/desktop
npm run --prefix apps/desktop test:ui
npm run --prefix apps/desktop build
cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml --locked
cargo clippy --manifest-path apps/desktop/src-tauri/Cargo.toml --all-targets --locked -- -D warnings
cargo fmt --manifest-path apps/desktop/src-tauri/Cargo.toml --check
.venv/bin/python tools/build_package.py --source-commit 96868d8f78ed30f42c78450f2b0ac6b9310f298e
HANLY_REQUIRE_PACKAGED=1 HANLY_EXPECTED_SOURCE_COMMIT=96868d8f78ed30f42c78450f2b0ac6b9310f298e \
  .venv/bin/python -m pytest --suite packaged
.venv/bin/python -m lab tour --config /path/to/runtime.json --quick --no-open
.venv/bin/python -m lab stress --config /path/to/runtime.json --per-family 3 --no-open
.venv/bin/python -m pytest --suite portable lab/tests/test_windows_window_queries.py \
  lab/tests/test_stress_ownership.py lab/tests/test_lab_session.py \
  lab/tests/test_private_corpus_recording.py lab/tests/test_raster_ui.py -q
```

For normal use, open `dist/macos/Hanly.app`. The source `hanly` /
`python -m hanly_app` command remains available and resolves an explicit
`HANLY_DESKTOP_EXECUTABLE`, then this checkout's built debug executable or an
installed `hanly-desktop`; it does not silently build or open a web page. npm
serves/builds the React/Tauri development workspace. Source/debug launches and
the canonical packaged app can have different macOS permission attribution; use
the exact bundle whose grants are being verified. Users of the packaged app
need no npm, Python, Rust or development server.

For another rebuild, pin its build-start commit; do not infer a later docs-only
HEAD as the product stamp. Native/process/package gates need real host access.
The executable Windows PowerShell checklist remains in the existing checkpoint:
UIA/UTF-16, mixed DPI, focus, Job/stdio ownership, tray/hotkeys, packaged Lab,
old-layout update verification, acknowledgement and rollback. Linux CI/build
compatibility is retained; this Mac cannot prove its compositor, accessibility,
Wayland portals, tray or actual monitor behavior. Neither platform is accepted
from portable seams or cross-compilation alone.


## Evening follow-up: Mac shortcuts and recorded popup defects

The human approved replacing media/function-key-dependent Mac defaults and
provided a 45.6-second screen recording. They specifically requested visual
border fixes, removal of entry/word-to-word flicker and blank/error behavior,
a capture/performance investigation without changing capture, and a detailed
update to this same handoff. They later clarified that permission entries must
not be reset by either the product or its tests, and that any proposed manual
reset must first be explained and approved while they are present. Independent
work must continue while an OS authentication step waits.

### Changes and intended behavior

`776a7ef` gives Mac the following defaults:

| Action | macOS | Windows/Linux |
|---|---|---|
| Hold to read | Control–Command–H (`⌃⌘H`) | Control–Shift–Space |
| Pause/resume hover | Control–Command–P (`⌃⌘P`) | Control–Shift–F9 |
| Start/stop capture | Control–Command–R (`⌃⌘R`) | Control–Shift–F10 |

The stored protocol remains `ctrl+cmd+h` etc.; React formats Mac modifiers with
native symbols. The existing shortcut recorder still stores normalized portable
bindings. A full profile with the exact old three defaults is recognizable and
migrates to the Mac set; missing keys use current host defaults. Partial profiles,
custom keys and deliberate unbinding retain every explicitly stored binding.
This avoids silently replacing someone's chosen shortcut. Windows/Linux keep
their desktop defaults. `19d5d67` updates the hover/residency behavior tests to
press the binding their fixture actually configures, preserving activation,
release, capture and resource-residency assertions.

`96868d8` corrects the popup presentation sequence. Previously the native shell
positioned, resized to an estimated Python height and showed the window before
emitting the new React content. React then waited for an animation frame to
measure and resize it again. The recording visibly contains rounded cards in
opaque rectangular windows and tall blank native frames during transitions.
Showing old/empty content before rendering and relying on a hidden webview's
animation callback were concrete lifecycle hazards; the recording alone does
not distinguish every asynchronous interleaving that produced each bad frame.

New replacements remain hidden until React has committed and measured the
current content. Measurement runs directly in the layout effect, also works
when animation frames are suspended, rounds up fractional pixels and retains
size/sequence deduplication. Native popup actions execute on the main event loop
and revalidate freshness there. Geometry is applied before visibility; obsolete
snapshots/actions cannot intentionally show a superseded answer. Measured frames
are constrained to their native display, including negative logical origins.
Already-visible same-answer expansion does not reorder/show the window again.

Expansion no longer changes React optimistically and then changes it again when
Python publishes the authoritative expanded content. It also preserves the
original answer position instead of following the cursor that clicked its footer.
Native appearance updates are applied only when the configured theme changes.
The provider child, lookup outcomes, final request-currency gate, popup crossing
rules and debounce/prewarming settings are preserved.

On macOS the entire native content view is clipped to the same 14-point radius
as the React card with public AppKit/Core Animation APIs. The native background
is clear and its native shadow is enabled. CSS no longer draws a shadow beyond
the exact-size window, and viewport minimum-size rules no longer keep empty
content at the previous native extent. No private WKWebView transparency API,
new permission or new production dependency was introduced. Other platforms'
actual native corner/compositor behavior still requires their own host checks.

### Capture and performance scope

`packages/hanly-app/src/hanly_app/acquisition/capture.py` and the complete engine
source have no changes against base `0902075`. Screen acquisition still prefers
native accessible text and falls back to small cursor-centered ROI capture;
this follow-up changes no capture algorithm, OCR backend/provider, dictionary,
hover delay or preload choice. The Tauri migration does replace Qt dispatch,
timers and window presentation, so unchanged OCR/capture code alone cannot prove
equivalent end-to-end latency. The investigated extra resize/show/theme work is
in that presentation path. Native capture/Vision tests pass separately.

The fresh release is v1.1.0 arm64, source
`96868d8f78ed30f42c78450f2b0ac6b9310f298e`, build
`284bd3e3-bef5-406f-8e16-6add3184a5c1`, stamped at
2026-10-15T01:08:09Z (2026-10-14 local). It replaces the earlier `0b8a9f4`
package as the current local product. The coordinated build completed normally.
All seven packaged gates passed in 200.61s, covering dependency/source identity,
frozen real OCR/lookup, Tauri foreground ownership, actual React bridge readiness,
root acknowledgement and failed-root rollback. Extracted ZIP and DMG each match
all 3,762 manifest entries and pass runtime inventory, bundle identity and strict
deep signature verification.

| Follow-up gate | Result |
|---|---|
| Full portable Python | 2,611 passed, two existing skips, 553.11s. |
| macOS native | 86 passed, 146.48s; one existing MSS deprecation warning. |
| Focused config/hotkey/service | 104 passed; final service focus 39 passed. |
| Hover/residency behavior | 45 passed after platform binding fixture correction. |
| Frontend | 40 UI + ten Node contracts; TypeScript/Vite production build passed. |
| Rust | 19 passed; all-target Clippy with warnings denied and rustfmt passed. |
| Static Python | Full Ruff clean; mypy clean across 344 files. |
| Frozen packaged product | Seven passed on the exact source/build above. |
| Both archives | 3,762/3,762 entries match; inventory and strict signatures pass. |

Archive SHA-256:

- ZIP: `0e389f3ca8a0cd1348ddec8a5c36d8495475ae18f9d4ab263f49235a54b04d8e`
- DMG: `becdfa726658f2237cf20ead6ef727cfdcadfea1c658cab77ddadb63122c8072`

The initial full run had eight obsolete shortcut expectations. An overlapping
rerun collected one fixture before its final correction and failed that fixture;
both are superseded by the final full passing run above. No production timeouts,
assertions, ownership gates or test requirements were weakened.

Native recording `20261014-222748-run` launches the exact canonical bundle with
a disposable profile. Runtime is ready/providers sleeping. Actual packaged
Shortcuts UI shows `⌃⌘H`, `⌃⌘P`, `⌃⌘R` with all three native registrations accepted.
Both permissions report required, so capture was not started and no positive
popup/flicker/performance pass is claimed yet. The human was asked to confirm
presence and approve restoring Screen Recording plus the stale Accessibility
entry. No new permission reset has been performed after that explicit policy.
The session was then closed through React's confirmed Quit. It ran 241.8s,
recorded ten events and zero drops, and performed zero captures/lookups. Every
one of its nine sampled PIDs was independently absent afterwards; a separate
process scan found no Hanly root. This is startup/UI/registration/cleanup evidence,
not popup acceptance. Fresh live workload results must be added after that
approval dependency is satisfied. No test session remains silently waiting.
Do not reuse the earlier release/debug timing as measurements of this new build.
The temporary debug recording `20261014-215948-run` performed zero lookups because
grants were required; it provides startup/shutdown evidence only, not popup
correctness, capture acceptance or a performance comparison.

### Permission identity and the human's explicit reset policy

The source/test scan contains no TCC reset command or database modification.
Hanly uses the public screen-capture/Accessibility request/preflight APIs and
opens the exact System Settings privacy pane from its Permissions page; granted
items remain visible and status rechecks when returning. macOS owns the actual
security approval. The app does not grant itself access or change global
security settings.

The repeated registration refreshes in this session were manual agent actions
while switching ad-hoc-signed debug/release identities, not resets performed by
Hanly. During this continuation the agent removed the stale Screen Recording
entry, macOS prompted for authentication, and the human completed it. The human
then explicitly prohibited repeating such resets without a prior explanation
and approval while present. No Accessibility removal happened in this follow-up.
The next grant should target only the final canonical bundle; do not repeat
registration switching between variants or conceal a waiting OS prompt.

`security find-identity -v -p codesigning` reports zero valid signing identities
on this host. The current builder produces ad-hoc signatures. It is therefore
incorrect to promise that independently rebuilt debug/release products or later
updates retain one TCC identity. Stable release signing credentials and compatible
designated requirements are needed for that release guarantee; no credentials
were created, no trust policy was weakened and no identifier-only requirement
was substituted. Same-build relaunch persistence must be checked independently.
Apple documents privacy-resource identity and compatible designated requirements
in [TN3127](https://developer.apple.com/documentation/technotes/tn3127-inside-code-signing-requirements)
and [distribution signing](https://developer.apple.com/documentation/xcode/creating-distribution-signed-code-for-the-mac).


### Latest live continuation and bounded close — 2026-10-15

The permission question was answered explicitly: “Yes, restore both; I’m here.”
For only the canonical `dist/macos/Hanly.app`, Screen Recording was added through
Hanly's Permissions action and the normal Settings picker; the stale enabled
Accessibility entry was removed/re-added under that same approval. No additional
authentication prompt appeared in this approved refresh. The OS reopen prompt
was deferred so the app could close normally and relaunch under isolation.
`20261014-235747-run` closed; `20261015-000248-run` launched the same sealed build.
Both grants then read **granted inside Hanly**. This establishes same-build
restart persistence, not persistence between independent ad-hoc rebuilds.
The earlier statement that Accessibility had not been removed described the
state before this subsequently approved refresh.

The latter recording finished normally: 371.6s, 7,958 events, zero drops, Vision
observed. Provenance starts at `76ef35ae9b75`, clean at launch and changed during
the run; the observed executable remains source `96868d8`, not the source being
edited. Its summary was read before the raw trace. Mixed interactive pointer
activity makes its aggregate latency unsuitable as a controlled baseline or
Qt/Tauri comparison. Recorded uncached answered-hover segments include capture
66.8ms, OCR 37.0ms, back-to-shell/popup 15.5ms and dwell 84ms; provider preparation
was 7.0s. These are descriptive samples, not a performance acceptance threshold.
No capture/engine behavior was altered to improve those numbers.

An owned raster fixture under `/private/tmp/hanly-popup-fix-acceptance/` displayed
학교 / 단축키 / 한국어 plus Latin negative text. Native ownership was checked before
cursor moves; only this authored fixture was observed for controlled content.
Stable school lookup showed a compact 340×282 popup, correct Hanja/definition,
rounded clipped corners and native shadow without the previous opaque square
surround. Expansion to 460×282 and collapse to 340×282 preserved X=111/Y=134.
Foreground application identity was unchanged by the observed popup show.
Closing the Control Center's native window exposed the popup accessibility
surface for visual inspection; binding by native window ID is unsupported by
this Mac CUA backend. No screenshots, user video, private profile or recognized
text were added to Git.

Adjacent-word trials exposed a remaining **real native ordering race**. For one
observed ~19ms step, the new visible answer used the preceding answer's rectangle:
111/134/340/282 before 187/134/340/365. Tao 0.37.1's Mac setters queue size and
position, while showing is synchronous. Putting those calls inside a main-thread
callback therefore did not ensure the frame was committed before show. Two
shortcut targets also had no visible popup at their 0.9s observation; that trial
was not declared green and production timeouts were not relaxed.

`ccf230da1e3076c25359467ecc8a9f3fc738984a` corrects the frame race in
`platform::present_popup_frame`: on the main thread, set one public AppKit
`NSWindow.setFrame_display`, lay out content and invalidate its shadow, then
order the non-key window front. Logical coordinates are converted against the
primary screen, with negative/fractional-origin unit coverage. Other hosts retain
the existing Tauri adapter. No dependency, Python/React, provider, capture,
request-currency or shortcut change is part of this last correction. Rust:
20 tests passed (final rerun 10.13s); all-target Clippy `-D warnings`, rustfmt and
`git diff --check` pass. **No fresh release, archive or live result exists for
this commit.**

The human was asked for Control–Command P twice and R twice. No reply and no
`native_hotkey_edge` events were recorded in this run at closure. Registration,
synthetic checks and asking for a keypress do not establish physical keyboard
acceptance. The old F9/F10 attempt likewise remains unverified. Do not leave a
new session waiting silently for these inputs.

The human then requested a bounded close because limits were almost exhausted.
No new rebuild or permission cycle was started. Host process inspection found
no remaining Hanly executable/service/lookup, private acceptance fixture,
loopback HTTP server or package/build job. Rust verification launched during
closure also completed. The old root/fixture PIDs 55125/55152 are historical;
never kill by a saved PID without rechecking its current executable/ownership.

### Complete remaining work, in execution order

1. **Build the latest committed fix once.** Use the coordinated builder and the
   full product hash below, with Cargo on PATH. `--no-clean` may reuse unchanged
   Python freeze analysis; the official builder still stages/signs/manifests the
   complete product. Do not hand-edit a sealed bundle. Documentation-only commits
   do not require another build. Record the new UUID, source identity and hashes;
   do not reuse the current `284bd3e3` identity as proof for `ccf230d`.
2. **Verify that exact new product.** Run all seven packaged checks against its
   source hash; extract/verify ZIP and DMG against the new manifest, bundle
   identity, inventory and strict signatures. The private archive verifier
   currently asserts the old UUID and must be updated before use. Prior full
   Python/frontend/native gates remain recorded above; rerun affected checks for
   any further source change rather than repeating unrelated gates without cause.
3. **Check grants on the new canonical bundle before changing anything.** If
   already valid, do nothing. If its new ad-hoc identity invalidates grants,
   explain the concrete need and ask the human to be present and approve the
   refresh. Past approval for the previous build is not blanket reset authority.
   Use Hanly's Permissions actions and normal OS approval. Never reset TCC as
   routine setup, swap grants to debug, modify its database or weaken signatures.
4. **Bounded final live popup acceptance on that release.** Use an isolated Lab
   profile and an owned authored page, with no competing pointer driver. Verify
   rounded borders/shadow and no stale/blank rectangle on first show, repeated
   adjacent-word changes and rapid changes. Specifically confirm that the new
   answer's first visible native frame has its final position/size. Recheck the
   two previously missed shortcut-word observations and inspect their trace if
   they recur; do not silently extend a timeout and call the old trial a pass.
   Check latest-result freshness, anchored expand/collapse, Close, Latin/blank
   refusal, word-to-popup crossing/retention and held-read release. Keep cold
   provider preparation separate from warm/cache/presentation timing. Investigate
   the reported Mac disruption if reproduced; no machine-wide fix is proven yet.
5. **Actual native input/reader evidence.** Verify Control–Command H held/released,
   P pause/resume and R capture toggles, with native edges and resulting state.
   Obtain the bounded real keyboard confirmation while the human is present.
   For Safari, verify the controlled authored page is actually the foreground
   application, then exercise direct AX text and raster OCR fallback without
   popup activation. Background AX actions did not establish foreground in prior
   attempts. The prepared private Safari script references a closed run and must
   be repointed and ownership checked before use. Keep the exact failed/missing
   prerequisites visible rather than substituting synthetic evidence.
6. **Close the final acceptance.** Normal quit/restart of the same new bundle,
   grants retained without reset, then normal quit and independent whole-family/
   fixture/server cleanup. Read each compact Lab summary and provenance first.
   Update this same handoff/checkpoint with actual new identity, results, precise
   residual limits and authorized local commits. No indefinite waiting sessions.

```sh
PATH=/Users/thiago/.cargo/bin:$PATH CARGO_BUILD_JOBS=2 \
  .venv/bin/python tools/build_package.py --no-clean \
  --source-commit ccf230da1e3076c25359467ecc8a9f3fc738984a
HANLY_REQUIRE_PACKAGED=1 \
HANLY_EXPECTED_SOURCE_COMMIT=ccf230da1e3076c25359467ecc8a9f3fc738984a \
  .venv/bin/python -m pytest --suite packaged
```

Private continuation material, if still available: fixture/controller scripts,
`final-fixture.jsonl`, `verify-archives.py`, `archive-results.json`, build logs
under `/private/tmp/hanly-popup-fix-acceptance/`; controlled Safari HTML under
`/private/tmp/hanly-final-native-acceptance/safari/`. These paths are disposable,
not repository dependencies. Check provenance and stale run IDs before reuse.
The recorded Lab run under gitignored `artifacts/lab/runs/20261015-000248-run/`
contains summary, metadata, process samples and ordinary privacy-safe events.

Windows/Linux native acceptance, real mixed-display hardware, Developer ID
signing/notarization credentials and the deferred Playwright planning remain
outside completion on this Mac. They are not silently waived. Existing Windows
PowerShell continuation and platform matrix above still apply. The user can
run Hanly as `Hanly.app` or `hanly`; npm remains a developer tool. No push, merge,
tag or public release is authorized or performed. This handoff ends the current
budget-limited run with the newest implementation committed and acceptance
explicitly unfinished.

## Phase B review findings and fixes — 2026-10-15

Scope: the complete migration `0902075..0c93861` (256 files), not only `ccf230d`.
These were read: Rust root/IPC/lifecycle/windows/platform/hotkeys/selector,
the Python service (application, protocol, server, event loop), the React
popup/state/selector and Control Center effects, the updater handoff, the
permissions module, the Lab process-control paths and the latest Lab summary.
The engine (`packages/hanly`), `acquisition/capture.py` and `direct_text.py`
are byte-identical to the base. No desktop, cursor, shortcut or permission
action was performed. No process was launched apart from unit fixtures and a
headless Vite server that was stopped afterwards.

### Fixed (uncommitted, unit-verified, not yet in a sealed build)

| Grade | Defect | Change |
|---|---|---|
| B | `lifecycle/mod.rs`: `Service::stop()` and the watcher sent `kill(-pgid, SIGKILL)` after `try_wait()` had reaped the leader. `Drop` repeated `stop()`, and Retry or Exit after a crash signalled the saved PID again, possibly minutes later. Once reaped, that ID can name an unrelated process group (macOS app leaders own their group). | A `Family` signals the group only while the exited leader is an unreaped zombie (`waitid(WEXITED\|WNOHANG\|WNOWAIT)`), then reaps it once. Later `terminate`/`stop` are no-ops. New regression: a leader that exits leaves a grandchild, the grandchild is ended, and a double `stop()` is harmless. |
| B | Popup placement used Python's estimated 180 pt height. React measures about 282–365 pt, and Rust kept the estimated top-left. On a 900 pt display, any word in roughly the lower 280 pt got a card drawn over it. Above-placement grew down over the word, and below-placement was clamped up onto it. Base Qt re-placed through `PopupController._handle_resize` with the real size, so this is a migration regression. | Python publishes the word's vertical `band` (shared `PopupController.vertical_band`, also used by `_place`). Rust `place_measured` chooses below/above from the measured height. It keeps that side for the same answer's expansion and clamps to the display. A payload without a band keeps the old clamping. Rust and service tests cover it. |
| C | `native.context.popup_rect` was accepted and handled by Python, but the host never sends it. | Removed from the protocol and the service. |
| — | Requested: browser visual iteration of the React views. | `npm run preview:mock` serves `apps/desktop/preview.html` through Tauri `mockIPC` fixtures (popup samples/themes, Control Center, selector). It is not part of `vite build`, which emits only `index.html`. It covers web layout only. |

### Open findings (not changed)

- **C, cleanup:** the pynput/Carbon keyboard `HotkeyService` (`hotkeys.py`) and
  `hotkeys_darwin.py` (about 1,100 lines) are dead in production, because Rust
  owns registration and the service always injects `_NativeHotkeyRuntime`. They
  are reachable only as `manual_lookup._create_hotkey`'s default, which would
  install a global keyboard hook (Input Monitoring) if a composition omitted
  `hotkey_factory`. Remove them together with their test fixtures in a
  dedicated change. The earlier "obsolete adapters removed" statement is
  therefore incomplete.
- **C:** React applies pushed `desktop-state`, request replies and 900 ms polls
  without ordering. A reply computed before a newer event can briefly show
  older state until the next event or poll. A monotonic state revision from
  Python would make this exact.
- **C:** the tray's labels are static. "Pause capture" actually stops capture
  and does not reflect the current state.
- **Hypotheses needing live evidence:** (1) Hiding a replaced answer until
  React measures the next one can produce a brief blank gap between adjacent
  words; this is preferred over a wrong frame, but is still visible. (2) A
  long-hidden WKWebView may be throttled, which could add latency to the first
  show; this is unproven and could relate to the two 0.9 s misses. (3) Clicking
  Expand or Close in the non-key NSWindow may activate Hanly; only *show*
  nonactivation has been observed. Recorded run `20261015-000248-run` has no
  service warnings or errors, so owner-queue overload is not supported as the
  cause of those misses.
- **Checked, no defect:** the IPC framing, limits, schemas, duplicate-key
  rejection and per-window allowlists on both sides. Also checked:
  stale-sequence handling for popup close, expand and geometry; navigation/CSP
  and capability scope; updater handoff path confinement; public permission
  APIs only, with no TCC use in the app or its tests. The Lab kills only
  psutil-snapshotted owned descendants. The `ccf230d` frame commit runs on the
  main thread (`MainThreadMarker` enforced). It converts against
  `NSScreen.screens[0]`, matching Tao's `CGDisplay::main()` read-back, on a
  borderless window where frame equals content.

### Checks run in this review

Baseline at `0c93861`: all of Ruff, mypy (344 files), tsc, 10 Node and 40 UI
tests, all-target Clippy `-D warnings` and 20 Rust tests passed. After the
fixes: Ruff, mypy (344), tsc, Vite build, 10 Node + 40 UI, rustfmt, Clippy
`-D warnings` and 22 Rust tests passed. Full portable Python passed: 2,611
with 2 existing skips. The sealed bundle stamp was read directly, and both archive
SHA-256 values match the `96868d8` values above.

### Stale or unsupported statements elsewhere in this file

- The first "Reproduction" block builds `--source-commit 96868d8…`. Use the
  final reviewed commit instead.
- "Obsolete adapters … removed" does not cover the dead keyboard
  `HotkeyService`/`hotkeys_darwin` path above.
- Rust test counts of 17, 19 and 20 are historical. Now 22.
- "Measured frames are constrained to their native display" was true, but it
  did not prevent the overlap fixed above.

### Complete remaining Mac work (deduplicated; replaces the earlier six steps)

1. The human reviews and commits these fixes. Build once at that commit with the
   coordinated builder, then record the new UUID and hashes.
2. Run the seven packaged checks and both archive verifications against that
   build. Update the private verifier's expected UUID first.
3. Check grants on the new canonical bundle. Change nothing if they are
   valid; otherwise explain, then wait for the human's presence and approval.
4. Run the bounded live popup pass on the new release. Check the first
   visible frame at the final rectangle, then rounded clipping and shadow.
   Check adjacent and rapid word changes, and recheck the two 0.9 s misses
   with a trace. **Hover words in the lower third of the screen and confirm
   the card sits above the word without covering it, including after
   Expand.** Check that clicking Expand/Close keeps the reader app frontmost.
   Also check Close, Latin/blank refusal, crossing and retention, and
   held-read release.
5. Verify physical ⌃⌘H hold/release, ⌃⌘P and ⌃⌘R with native edges. Then the
   controlled Safari foreground: direct AX text, OCR fallback and nonactivation.
6. Quit and restart the same bundle with grants retained, then quit and confirm
   whole-family/fixture cleanup. Update this file and the checkpoint.
7. Follow-ups that do not block acceptance: remove the dead keyboard adapter;
   add a state revision; make the tray labels state-aware; extend the mock
   preview into the deferred Playwright/visual tests.

Windows/Linux native acceptance, mixed-display hardware and Developer ID
signing/notarization remain outside this Mac completion.

## Phase B follow-up — cleanup, build and headless verification (2026-10-15)

The human authorized local commits, with no agent attribution in messages
(now a rule in `CLAUDE.md` and `AGENTS.md`). Push, merge and permission changes
were not authorized and were not performed.

### Commits after `0c93861`

| Commit | Change |
|---|---|
| `5f6e75c`, `e700d10`, `3024397`, `7acd74a` | The review fixes and mock preview recorded above. |
| `4fb9fba` | Removed the Python global keyboard listener: `HotkeyService`, the pynput/Carbon listeners, `hotkeys_darwin.py` and their tests (about 2,100 lines). `hotkeys.py` keeps the action names and canonical spelling. `ManualLookupRuntime` now requires the host's hotkey runtime and drops the dead rebind/unbind path and the never-bound one-shot `lookup_hotkey`. `lookup_at_cursor()` is kept. Tests use `tests/hanly_fixtures/hotkeys.py`, which delivers edges the way the host does. The architecture doc and its visual were corrected. The frozen spec keeps pynput's keyboard backend import, because `pynput/__init__` imports `keyboard` even for the mouse observer. |
| `f63ebb3` | Deleted `app_icon.py`, the Qt tray and title-bar loader. The frozen service and wheel no longer copy icons, and the packaged inventory no longer requires them. The native root still embeds `hanly-icon-128.png` and `hanly-macos-icon.png` from source. The `window-face-*` and `favicon.ico` art is kept because the design README calls it approved identity, but no surface uses it now. That is the human's call. |
| `bce8f98` | The desktop README no longer cites the removed Lab PyQt dependency group. |
| `cbda0f9` | The tray has one capture item that reads Start or Stop capture from the published state and sends the matching request. The static "Pause capture" item actually stopped capture. |
| `acd3c28` | Every service state snapshot, including bridge replies, carries `revision: {series, number}` from the serialized loop. React drops an older snapshot of the same series; a restarted service starts a new series. |

Remaining Python UI mentions are intentional guards: the frozen-build exclusion
list, the forbidden-runtime checks, and updater fixtures that clean V1 installs
that shipped PyQt6.

### Gates on `acd3c28`

Ruff; mypy (342 files); full portable Python 2,570 passed with 2 skips (fewer
because the deleted listener's tests went with it); tsc; 11 Node and 40 UI
tests; Vite build; rustfmt; Clippy `-D warnings`; 22 Rust tests.

### Build and verification

`tools/build_package.py --no-clean --source-commit acd3c28…` produced build
`44161ec2-7c78-4765-a996-a231953b4f18` (arm64, ad-hoc,
`designated => cdhash H"0542aab3…1931"`).

- ZIP SHA-256 `339cb8be60fe6982c018eeaa2e77f891f610bef6ee745aa2c287028a82d5a503`
- DMG SHA-256 `93e196c5378032ca43ceb679f44586814bd1bfa109caf5c2a91db0960336a370`

Packaged checks passed with `HANLY_EXPECTED_SOURCE_COMMIT=acd3c28…`, headless only:

- runtime dependencies;
- source identity;
- the isolated OCR self-check;
- helper restore after the root rejects startup.

The archive verifier was run as a copy that takes the build ID as an argument.
ZIP and DMG each had 3,748 entries; manifest match, inventory and strict
signature all passed.

Not run, because each opens Hanly windows:

- `test_the_tauri_root_is_the_only_foreground_app_and_owns_the_service` (`open -n`);
- `test_the_native_window_waits_for_react_and_answers_its_state_bridge`;
- `test_the_packaged_native_root_acknowledges_only_after_its_real_ui_is_ready`.

Observation: after the build and these checks, the `dist` DMG was found
attached with no mount point. It was detached. Re-running the updater's
`acquire_disk_image` alone left nothing attached, and so did detaching by
volume or by mount point. The source of that attachment is not isolated, so
there was no code change for it. On the next build, check `hdiutil info`
before and after.

### Remaining work (needs the human present)

1. Run the three window-opening packaged checks above against `acd3c28`.
2. Open `dist/macos/Hanly.app`. Its new cdhash needs Screen Recording and
   Accessibility approval through Hanly's Permissions actions. The human
   performs this; no TCC reset.
3. Run the live popup pass from step 4 of the previous list:
   - the lower-third word stays visible above the card, before and after Expand;
   - adjacent and rapid changes;
   - the two 0.9 s misses, with a trace;
   - Expand and Close keep the reader app frontmost;
   - the tray item reads Start or Stop capture correctly.
4. Physical ⌃⌘H hold/release, ⌃⌘P and ⌃⌘R; controlled Safari AX and OCR.
5. Quit and restart with grants retained; quit; check that the family has
   ended; record the results here.

Deferred, not blocking: Playwright/visual tests over `preview/`; Windows and
Linux native acceptance; Developer ID signing.

## Live acceptance pass (2026-10-15)

The human approved the build-grant-finish sequence, then left. They asked
for everything else to be finished without another grant in this session.

### Commits after `63e988b`

| Commit | Change |
|---|---|
| `d9a7520` | The permission action is labelled Grant access; it already runs Apple's request first |
| `148cd7c` | The helper-restore packaged check waits for the detached relaunch instead of reading once |
| `aa7dadf` | CI installs `rustfmt` and `clippy` with the pinned 1.99.0 toolchain |
| `a1a2a14` | `lab/session/desktop_process.py` types the stream as `IO[bytes]` and guards its FIFO paths as macOS-only |
| `fea73a9` | The Permissions page explains a switched-on entry that belongs to an earlier build |
| `e7ef391` | The popup suppresses WebKit's context menu unless text is selected |

### Root causes found

- **"Granted in System Settings, required in Hanly."** Before any change,
  macOS's TCC log showed both entries rejected with `authReason=5`. The
  stored requirement was `cdhash H"1e6db425…"`, which is build `284bd3e3`
  (`96868d8`) from the earlier session. Switching an existing entry on does
  not rebind it to a new build. Each ad-hoc rebuild is a new identity, which
  is also why system prompts repeated. Responsibility was checked and is
  correct: the service is attributed to the Hanly root.
- **CI on `0c93861`.** The `--profile minimal` toolchain lacked `rustfmt`, so
  the native job stopped at the format check on all three platforms. On Linux,
  mypy checks the non-macOS branch of `desktop_process.py`, where `Popen`'s
  `IO[bytes]` failed the `BinaryIO` protocol. No other job or step failed.
- **Popup context menu.** A right-click opened WebKit's menu, including
  Reload. While that menu tracks, the native event loop does not process a
  quit request: an observed SIGTERM waited until the menu closed. The
  first sighting came from a harness Control-click; the menu itself is
  product behaviour.
- **`hanly` with a blank window.** A plain `cargo build` produced a debug root
  without the `custom-protocol` feature, so it expected the Vite dev server.
  It was rebuilt the README's way. The debug bundle is also current.

### Not changed, with reason

- **Stable local signing identity.** This would make rebuilds keep one TCC
  identity. Creating a self-signed identity in a dedicated keychain was
  blocked by this session's permission policy, so nothing was created. It
  remains the human's decision. Until then, every new ad-hoc build needs one
  fresh grant.
- **`acceptFirstMouse` on the popup.** It was tested and dropped. With clean
  modifiers, Expand, Collapse and Close work without it. The earlier failure
  was a Control-click from the harness.

### Live evidence

These runs used the debug root at the same source. It was started directly,
so the service inherits the terminal's existing grants. The frozen product
cannot be live-tested that way. macOS attributes the packaged root and service
to the `io.github.thiagoross1.hanly` bundle (seen in the TCC log), which is
correct production behaviour. Its capture therefore needs the human's grant.

**Lab tours** (summaries read first; commit `fea73a9`, clean, Vision observed):

| Run | Result |
|---|---|
| `20261015-050500-tour` | Quick: 24/24; median answer 159 ms; cold first answer 6.2 s |
| `20261015-050610-tour` | Quick, compared with baseline `20261007-194130-tour`: not comparable (plan and protocol differ); raw 23/24 → 24/24 |
| `20261015-050824-tour` | Story: 175/177; the misses are `누군가` (wrong lemma) and `드리다` (alternate reading), both engine-level |

**Frame race (`ccf230d`).** WindowServer frames were sampled every 3 ms through
two tours: 24 shows, then 168 shows over adjacent story words. There were
zero frame changes while a popup was visible, and no show reused the
previous answer's rectangle or origin. Every first visible frame was final.

**Authored Safari page.** All words were read through AX frames. Every result
held with Safari frontmost.

| Check | Result |
|---|---|
| ⌃⌘R | `native_hotkey_edge` press/release; capture starts and stops |
| ⌃⌘P | Hover pauses (no popup) and resumes |
| ⌃⌘H in push-to-hover (product default) | A held, stationary pointer opens the answer, which stays readable after release. When capture is stopped, a press is ignored by design |
| Adjacent words, ×3 each way, plus 4 rapid sweeps | Popup in 0.24–0.29 s, frame correct for each word |
| Lower-third word | Card bottom 706 above word top 709; Expand grows upward to 460×539 with the bottom unchanged |
| Expand / Collapse / Close | 340→460→340, anchored; Close hides in 0.03 s |
| Right-click on blank popup space | No menu (`e7ef391`) |
| Latin word | No popup |
| Canvas word (no AX text) | Direct text `unsupported` → OCR → popup |
| Safari DOM text | Direct text `unsupported` → OCR. This matches `mac-campaign-2026-09-21` ("Safari: 0 direct") |
| TextEdit (authored RTF) | 2 of 3 words read directly (no capture, no OCR); the first was the discarded cold AX call |
| Tray | Reads "Start capture" when stopped and "Stop capture" when running |
| Quit | Tray Quit exits 0 in 1.0 s; SIGTERM exits 0 in 0.7 s; no root, service or lookup process remains |

The previously recorded 0.9 s shortcut-word misses did not recur. In the
runs above, every warm target answered.

**Harness artefacts, not product defects.**
- Hanly was launched from a background process, which macOS's cooperative
  activation refuses. The Control Center's launch request to take focus was
  then honoured at the first popup click. That brought the Control Center in
  front of Safari, and a canvas lookup read Hanly's own window (`EMPTY`).
- With Safari activated per trial, no popup click took focus, measured
  between mouse-down and mouse-up.

A real launch activates Hanly immediately, so this sequence does not arise.

### Final build

- Build `20284932-80c5-4086-9015-5092705d6714` from
  `e7ef391f8adb3be72851f855d9bf2da94e596df2`.
- ZIP SHA-256 `3d5cf2578208cb887b2ac733c810bb07dd10f84fcaeb2adbaaeaf46803dfd35e`.
- DMG SHA-256 `bc0a09e02915285dd2da6a78419546fceaad508b11b7a2680dc2c337051f5fe7`.
- Ad-hoc signature, `designated => cdhash H"70ed70a16dc3019c4ff98e00943ea18e6c35a5c9"`.
- All seven packaged checks pass, and both archives verify (3,748 entries;
  inventory and strict signatures).
- No `dist` DMG was left attached on this build.

The intermediate builds were:
- `ef5503aa` (`63e988b`): 7/7 on the second run. Its first run lost one
  SIGTERM in the native-UI check and left a test root; that root then
  exited on a manual SIGTERM.
- `135355e5` (`d9a7520`): 6/7, then the helper test fix above; the fixed
  check passed 3/3.

Installed state:
- `/Applications/Hanly.app` is this build.
- The two mounted 0.1.2 installer volumes were ejected; the `.dmg` stays in
  `~/Downloads`.
- LaunchServices was cleaned so that only `/Applications/Hanly.app` is
  registered. A rebuilt debug bundle registers itself again.

### Remaining

1. **The human:** in Hanly → Permissions, use Grant access for Screen
   Recording and Accessibility. If the old entry is still switched on,
   remove it with − first, because it belongs to `284bd3e3`. Then quit and
   reopen Hanly. No TCC reset.
2. **The human:** press ⌃⌘H, ⌃⌘P and ⌃⌘R on the physical keyboard once.
   Synthetic HID chords are verified above; physical input is not.
3. Optional: decide on a stable local signing identity so later rebuilds
   keep the grant.

Deferred, not blocking: Playwright over `preview/`, Windows/Linux native
acceptance, and Developer ID signing. No push, merge or tag.
