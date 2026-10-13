# Desktop Tauri Migration Review Handoff

Implementation session: 2026-10-13, branch `desktop/tauri-migration`.
This prepares the human-selected review; Phase B has not started. Product
implementation is committed. Native capture/hover acceptance is still blocked
by macOS privacy grants and unconfirmed shortcut delivery; do not call the
whole migration accepted from the portable or UI-readiness tests.

## Implemented and expected behavior

- One Tauri/Rust root owns React Control Center, popup, selection and dialogs,
  native windows/tray/reopen, restricted IPC and process-family supervision.
- One Qt-free Python service owns async provisioning, configuration, direct-first
  AX/UIA acquisition, hover/request policy, diagnostics and existing updates.
  Heavy providers stay in its unloadable lookup child; `hanly` source is unchanged.
- All six Control Center pages, settings, confirmations, status/errors, popup
  presentation and selector contracts are connected. The shell fills its window;
  settings align and adapt to narrow widths, preserving Hanly's existing identity.
- Production Qt, WebEngine, pywebview, legacy renderer assets and old adapters are
  removed. Qt remains only in the optional Lab fixture/HUD dependency group.
- The native root embeds the frontend and frozen Python runtime/providers/models.
  Users need no Python, Node or Rust. Source `hanly` / `python -m hanly_app` launch
  the built native executable; npm serves development and build workflows.
- Existing verified updater ownership, old-layout transition, root/frontend
  acknowledgement and rollback remain. No Tauri updater-plugin replacement.

The IPC contract is private JSONL v1, 1 MiB frames, 32 pending requests, strict
schemas/IDs/order and window allowlists. Python retains the final request-currency
check. Runtime readiness and provider residency are separate. Native APIs run
without holding the presentation lock across dispatch. See CODE-MAP and the
single checkpoint for the surface and test replacement map.

## Local commit map

| Commit | Boundary |
|---|---|
| `c4cbb97`, `4f48f5c`, `c106a54`, `09f2912`, `6213c2b` | Approved ownership/contracts and initial service, React, Rust and checkpoint foundation. |
| `62f7612` | Complete React interactions, events and corrected window/settings layout. |
| `e02c011` | Real asynchronous service/runtime and acquisition/lookup integration. |
| `1e0ded9` | Native windows, inputs, supervision and root/frontend readiness. |
| `624ba53` | Production Qt retirement and retained test migration. |
| `e8fca98` | Native Lab launch, whole-family attribution and privacy boundary. |
| `96cc73e` | Coordinated packaging, existing updater transactions and CI ordering. |
| `422bb07` | Hidden panels excluded from accessibility and keyboard focus. |

Spike `39fc4e7` stays on `spike/desktop-renderers`; it was not merged.
No push, merge, tag or release occurred. `08e048f` records the final runbooks,
code map, synchronized architecture companions and checkpoint. This handoff
is the final Phase A action.

## Implementation-side validation

| Gate | Actual result |
|---|---|
| Python portable | 2,569 passed, 2 skipped. Native Vision assertions were moved intact into native tests. |
| macOS native | 81 passed, plus 5 live Vision geometry/availability cases passed. |
| Service/event loop/launcher | 72 focused checks passed. |
| Lab / suite routing | 518 portable Lab and 7 routing checks passed; actual native corpus window passed. |
| Ruff / mypy | Clean; 337 Python files checked. |
| React / Node | 40 UI and 9 contracts passed; TypeScript and Vite build passed. |
| Rust | 15 tests passed; Clippy with warnings denied and rustfmt passed. |
| Architecture / workflows | 6 synchronized invariant checks and 88 workflow contracts passed. |
| Final packaged | 7 passed in 111.77s with native host access on the exact final build. |

Native framework/process gates require real host access: sandbox-denied `ps`,
empty Vision results or an absent Qt screen were diagnosed and rerun natively.
Assertions and production timeouts were not relaxed.

## Actual Mac UI, packaging and updater evidence

The current source native app was inspected with computer-use tools: all six
pages, persisted light/dark theme, default 1060x760 and approximately 730x563
windows, scrolling/aligned settings, scope-dialog cancellation, permission
failure, same-root close/reopen and real Quit confirmation. Root/service
89788/89793 both exited. The user's older 19:19 debug instance was closed.

Final app: `dist/macos/Hanly.app`, arm64, version 1.1.0, bundle identifier
`io.github.thiagoross1.hanly`. Build ID `77d09d75-bbc9-4565-98d0-6ebb7f6304ad`,
source commit `422bb0742c062ed6358973addb896125bfa9d83f`.
Deep/strict ad-hoc codesign passes. The intended ICNS matches its source;
ZIP and DMG each reconstruct to the exact 3,762-entry manifest, with no missing,
different or unexpected files. Both inventories and the mounted DMG pass.
ZIP SHA-256: `ccf3f8aefcbd01038d271b823164d2fd1ea054e7d12c57a035f98e262640131f`.
DMG SHA-256: `65baad8a20ff3699b6b2f3d3b0951eade06b76d810b308627cbf06bec6b12e04`.
The final packaged Capture page was visually inspected; its collapsed region
controls are absent from the native accessibility tree.

The real packaged UI self-check, frozen worker/OCR lookup, ordinary native-root
update-ready acknowledgement and failed-root POSIX helper rollback passed on
the preceding current-source build. The final build re-stamps committed source;
its complete suite and archive results are reported above. Update fixtures use
disposable copies/profiles and preserve the real installation/settings.

## Lab evidence and blocking limits

Release recording `artifacts/lab/runs/20261013-202154-run` finished in 124.9s
with on-demand providers sleeping, an existing runtime/database, and no capture
or lookup. It includes native activation and visual inspection. Family peak
RSS was 246.7 MiB, whole-period mean summed CPU 6.0%; the 30–120s samples averaged
77.39 MiB RSS / 1.51% CPU. Runtime preparation finished 9.576s after owned-root
spawn. This is one startup/idle observation, not a visible-UI or lookup-latency
measurement and not a guarantee. Rust, frozen service, GPU/network/WebContent
and macOS helpers were attributed. Root 95648 exited 0, no surviving or forced
children; all nine sampled PIDs were independently confirmed gone.
Provenance: product commit 422bb07, documentation dirty; no product code changed
during the run. No compatible registered baseline exists for this protocol and
workload, so no Qt/spike RAM-saving comparison is made.

Earlier driven tours 141441, 143450, 144857, 152425 and 154154 failed/aborted
before a scored hover. They provide no first/warm hover latency or memory-saving
claim. The former Qt/spike recordings are not compatible with this sampler and
workload. Read recording summary/provenance/baseline before any comparison.

The source app and final packaged self-check report Screen Recording and
Accessibility missing;
Start capture returns the correct permission error. No OS grant was modified; the permission question is unanswered.
Native registrations report 3/3; Lab input preflight succeeds and emits every
press/release, but no native shortcut edge reached the sole clean app. The
Carbon dispatcher comparison failed to launch reliably, so no unsupported
production target swap was adopted. Capture, native AX versus raster OCR,
positive/negative targets, popup placement/nonactivation/crossing and actual
first/warm latency remain unverified. A successful React handshake does not
prove these behaviors. Multi-monitor/negative-origin contracts pass, but actual
mixed-display selection still needs its native acceptance.

Windows Job ownership, redirected stdio, UIA/UTF-16, mixed DPI, WebView2 focus,
tray/hotkeys and native updater/rollback require Windows. The executable
PowerShell continuation is in the checkpoint. Linux portable packaging remains
supported; Ubuntu/Xvfb CI does not prove Wayland portals, real compositor focus,
tray or mixed-monitor behavior. No Windows/Linux acceptance is claimed here.

## Exact continuation and commands

Run from the repository root with the source dependencies installed:

```sh
python -m pytest --suite portable
python -m pytest --suite native
python -m ruff check packages packaging tests tools lab
python -m mypy packages packaging tests tools lab
npm run --prefix apps/desktop check
npm test --prefix apps/desktop
npm run --prefix apps/desktop test:ui
npm run --prefix apps/desktop build
cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml --locked
cargo clippy --manifest-path apps/desktop/src-tauri/Cargo.toml --all-targets --locked -- -D warnings
cargo fmt --manifest-path apps/desktop/src-tauri/Cargo.toml --check
build_commit="$(git rev-parse HEAD)"
python tools/build_package.py --source-commit "$build_commit"
HANLY_REQUIRE_PACKAGED=1 HANLY_EXPECTED_SOURCE_COMMIT="$build_commit" \
  python -m pytest --suite packaged
```

For another rebuild, pin its build-start commit and use that exact value in the
packaged gate; do not infer an advanced checkout HEAD as the stamp's source.
After macOS grants and real shortcut delivery are confirmed, run the controlled
Safari text/raster/negative cases and native popup/selector scenarios, then a
Lab-authored debug `python -m lab tour --no-open` and a separately attributed
release measurement. Keep all private profiles/recordings gitignored. Playwright
and performance/prewarming/redesign work stay deferred.

Suggested review targets: host/service window authorization and recovery,
request-currency/retention geometry, updater root-versus-service ownership,
macOS public-window/input behavior and real Windows process/stdio adapters.

## Review assignment

Human-selected after implementation. Not started.
