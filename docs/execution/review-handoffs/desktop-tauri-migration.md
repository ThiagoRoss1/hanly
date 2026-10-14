# Desktop Tauri Migration Review Handoff

Branch `desktop/tauri-migration`, implementation and resumed cleanup/review on
2026-10-13–14. Code cleanup and the human-requested Codex review are complete.
Final source-stamped Mac package/archive checks passed on `0b8a9f4`; the Lab-only
cleanup continuation is committed as `e6250f7`. Native acceptance still needs
human authentication/permissions and input. It is not established by automated
or window-readiness tests alone.

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
| `8b9a4ed` | Readable React sources and enforced unused declarations. |
| `ff64a87`, `2b93252` | Qt-free Lab, public launch/FIFO, function-key input, cleanup and native handle contracts. |
| `dc8d6f4` | Runtime/setup/code-map and synchronized architecture guidance. |

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
| Ruff / mypy | Clean; 342 source files checked. |
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
The successor `7569005a` and rebuilt debug bundle both still report required
despite macOS listing Hanly as enabled. The human has now approved both app
identities' grants. The exact canonical app is selected through the System
Settings picker, but automation has not reliably confirmed that native picker;
human completion was requested. No grant refresh is claimed yet. The release
and debug probes `20261014-175027-run` and `20261014-180055-run` stopped normally
with exit zero and no surviving/forced children; neither started capture.

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
was adopted. Physical keyboard/held push-to-hover confirmation is separate and
still unverified.

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

Remaining permission-dependent acceptance: controlled Safari native AX versus
raster OCR, positive/negative targets at different sizes/themes, popup placement,
nonactivation, crossing, expansion/close, cache/stale answers, held shortcuts,
scored Lab tour and first/warm lookup/family measurements. Do not convert a
successful React handshake or provider image self-check into those passes.

The `2b93252` package produced an actual controlled Safari OCR result for
학교, displayed the correct school definition and Hanja, and expanded/closed
through real React controls. Screen-point calibration used native Safari window
bounds and Lab owner checks; initial wrong-point attempts were UNUSABLE, not
passes. The actual run exposed a fractional `service.popup_geometry` TypeError.
`a54784c` encloses that logical rectangle with floor/ceil; 70 focused tests and
the full portable gate passed. The corrected frozen service still needs its
fresh native popup/retention check. Ordinary trace content remains text/pixel-free.

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
bundle was rebuilt from current Rust/React source; its approved grants still
need the native registration refresh. No successful scored tour is inferred
from release UI.

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
Registered October 7 Qt baselines are incompatible. No RAM-saving, visible-popup
latency or general performance guarantee is claimed.

## Post-Bundle Review Outcome

Reviewer: Codex, same ecosystem, resumed run explicitly requested by the human;
2026-10-13–14. Code/cleanup review finished; native acceptance remains access-dependent.
No independent or cross-provider review is claimed.

**Fixed now:** popup window authorization and event/content-counter mismatch;
missing native presentation acknowledgement and expansion request identity;
Lab pre-exec executable caching and recovery cleanup after failed root adoption;
React freshness after service replacement; Lab synthetic function-key edges;
Lab shutdown that bypassed reporting; bounded FIFO failed-launch cleanup;
Windows import scope, pointer-width Windows/X11 APIs and signed DPI results;
fractional native geometry rejected by integer retention bounds;
obsolete Qt dependencies/adapters/setup, unused helpers and inline suppressions;
React formatting/unused declarations and stale architecture/source mappings.

**Deferred considerations:** controlled native workload acceptance resumes when
macOS grants/authentication are available; physical mixed-display geometry and
Windows/Linux behavior are reconsidered on their native continuation hosts,
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
.venv/bin/python tools/build_package.py --source-commit 0b8a9f4f9a6a33fdfdc4bb4846e0f3a5e28cfba9
HANLY_REQUIRE_PACKAGED=1 HANLY_EXPECTED_SOURCE_COMMIT=0b8a9f4f9a6a33fdfdc4bb4846e0f3a5e28cfba9 \
  .venv/bin/python -m pytest --suite packaged
.venv/bin/python -m lab tour --config /path/to/runtime.json --quick --no-open
```

For another rebuild, pin its build-start commit; do not infer a later docs-only
HEAD as the product stamp. Native/process/package gates need real host access.
The executable Windows PowerShell checklist remains in the existing checkpoint:
UIA/UTF-16, mixed DPI, focus, Job/stdio ownership, tray/hotkeys, packaged Lab,
old-layout update verification, acknowledgement and rollback. Linux CI/build
compatibility is retained; this Mac cannot prove its compositor, accessibility,
Wayland portals, tray or actual monitor behavior. Neither platform is accepted
from portable seams or cross-compilation alone.
