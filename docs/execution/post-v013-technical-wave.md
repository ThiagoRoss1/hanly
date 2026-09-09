# Post-v0.1.3 Technical Wave

Status: **investigation complete; implementation proposed for human review**. This document authorizes no production changes, commits, pushes, publication, or Linear mutations. Investigation date: 2026-09-09. Repository inspected: `02feae412fe3de95907e83b16f19e1a643386b9d`; working tree was clean before this document.

Executor: Claude Opus, directly, using this as the single implementation plan. Follow `AGENTS.md`, architecture `01`–`04`, and `docs/execution/05-execution-plan.md`. Do not introduce a second task decomposition, generic execution-skill chain, or mandatory per-block reviewer. This wave has three independently reviewable implementation phases: **HAN-42 → HAN-40 → HAN-41**. Each phase runs its gate, leaves a Review Handoff, and stops for human review before the next phase begins. Deep review is separately human-authorized. A failed gate blocks progression. Approval does not imply commit or release authority.

## 1. Investigation summary

### Scope and evidence

Read the live descriptions, relations, and comments of [HAN-42](https://linear.app/hmx-gen-projects/issue/HAN-42/make-application-self-update-reliable-and-in-place), [HAN-40](https://linear.app/hmx-gen-projects/issue/HAN-40/reduce-packaged-desktop-size-and-dependency-bloat), and [HAN-41](https://linear.app/hmx-gen-projects/issue/HAN-41/minimize-idle-resource-usage-and-hover-lookup-latency). All were Backlog, with no blocking predecessors; HAN-42 blocks HAN-30. Their relationship to one another is related work, not a native dependency chain. The requested execution order is a technical/review constraint; do not rewrite Linear relations to manufacture it.

Evidence classes used below:

- **Verified source/reproduction:** current implementation inspected, or a bounded local probe executed against it.
- **Local artifact:** existing Windows ZIP/tree inspected, not rebuilt during this investigation. It uses Python 3.13.11, unlike CI's packaging Python 3.10. Do not treat it as proof of the current release runner environment.
- **Historical:** previous measurements with their dates and limitations. They are not fresh measurements of this checkout.
- **Required native validation:** macOS/Linux behavior that cannot be executed on this Windows host, and full desktop/frozen update tests still required during implementation.

Only this Markdown file was intentionally changed. No installed Hanly was updated or launched for an update. Focused existing tests were run with bytecode/cache writing disabled:

```text
.venv/Scripts/python -B -m pytest -p no:cacheprovider \
  tests/test_app_update.py tests/test_update_coordinator.py \
  tests/test_packaging.py tests/test_ci_workflows.py -q
161 passed, 3 skipped (POSIX handoff tests on Windows), 3.27 s
```

This is investigation evidence, not a full project gate. The suite can pass despite the real Windows relaunch defect described below. No fresh frozen build, complete desktop idle campaign, macOS execution, Linux execution, or live GitHub release round trip was performed. The web attempt to read the public latest-release API was unavailable; hosted release bytes and deployed environment protection remain unverified. Local release producers/consumers were traced instead.

### Architecture to preserve

`hanly-app → hanly` remains the only package dependency direction. The engine's provider interfaces and normalized results remain unchanged. The app owns native update replacement and lifecycle. Resource validation remains in `ResourceManager`, resource delivery in `UpdateService`. Application installation already lives in `packages/hanly-app/src/hanly_app/app_update.py` (the code map's update index is incomplete).

The sole entry point is `hanly_app.cli:main`; packaged startup goes through `packaging/entrypoint.py` and the OCR-preloading runtime hook. Keep OCR imported before Qt, one QApplication, one pywebview-owned event loop, worker-owned provider lifetimes, bounded/latest-wins submission, and the final request-currency check before popup presentation. Keep Python 3.10 compatibility, EasyOCR CPU operation, Kiwi, KRDICT, popup behavior, and external user data. No Paddle, alternate OCR backend, generic plugin/updater framework, Update UI redesign, or resource-updater redesign.

### Findings that determine the wave

| Finding | Evidence and implication |
|---|---|
| Windows relaunch resolves to `hanly-desktop.exe.exe` | `_PLATFORM_LAYOUTS['win32'].executable_path` already includes `.exe`; `_WINDOWS_HANDOFF` appends another. Rendering with the actual layout reproduces it in both success and rollback branches. Fix the production composition, not just the template default. |
| Staging is mistaken for completion | `ApplicationInstaller.apply()` merely starts a helper. Neither helper obtains a new-process version/readiness acknowledgement. Both delete the previous installation before knowing relaunch succeeded. |
| Persistent clutter is real | Fixed `Hanly.app.staged`/`hanly-desktop.staged`, `.previous`, and sibling scripts; scripts never delete themselves. Interrupted attempts have no recovery record. `_reserve()` and `_place()` delete prior names without determining ownership. |
| Reported macOS `.cmd` is not reproduced by current source | Darwin selects `/bin/sh`, `.sh`, ZIP, and whole `.app`. No `*-spec` staging name exists here. Do not claim the report is false, but do not invent a current platform-selection root cause. A stale deployed build or manually mixed artifacts requires original-machine evidence. |
| Update ownership has a callback race | `_active_locked()` becomes false when a future finishes, before its daemon callback updates state. A new operation can start in that interval; the older callback can clear `_future` or overwrite the newer operation. Shutdown has no closed/generation guard. |
| Artifact identity is incomplete | Selection is platform-only, not architecture-aware. Windows/Linux staging proves only an executable exists. macOS checks identifier and signature-file existence, not signature validity or target version. |
| Linux application extraction conflicts with frozen format | Shared `_extract_gztar()` rejects all links. PyInstaller 6 POSIX onedir bundles use symlinks. Current Linux CI smokes the build tree, not archive extraction through the updater. Native failure is not reproduced here; the contract mismatch is concrete. |
| Package baseline includes build-environment residue | Two OpenCV FFmpeg versions exist in both `.venv/cv2` and the ZIP. Installed distribution RECORD owns only `500`; the Analysis TOC names the residual `4100` file as its source. |
| Runtime is already demand-driven | Worker sleeps on an unbounded condition wait. Hover is movement/debounce-driven, mouse deliveries are coalesced, and pause stops the listener while keeping the manual hotkey alive after Start. No idle OCR loop was found. |
| Warm-up does not eliminate first text-image cost | Blank prewarm exercises detection; current local direct-provider probe still takes 649 ms on its first Korean image, then about 103 ms warm median. Treat this as a measured candidate, not a complete desktop bottleneck diagnosis. |
| Release gates permit UI failure | `build.yml` uses `continue-on-error` for frozen Control Center smoke on macOS/Linux. The green build can therefore feed release staging while its UI smoke failed. |

### Cross-phase dependencies

HAN-42 defines and validates the artifact identity and archive consumer before HAN-40 changes collection. HAN-40 must preserve the same release filenames, inner payload roots, model availability, signature validity, and update round trip. Its dependency changes become the baseline for HAN-41; do not compare latency across different unrecorded Torch/OpenCV builds. HAN-41 must preserve the startup acknowledgement and shutdown behavior introduced by HAN-42. Reuse each phase's smoke as the next phase's regression gate. No dependency found requires reordering.

## 2. Phase 1 — HAN-42: updater correctness and reliability

### 2.1 Actual end-to-end path

Paths in this section without a prefix are under `packages/hanly-app/src/hanly_app/`.

1. `assets/control_center/control_center.js`: the `update-application` click invokes `install_application_update`; `control_center.py::ControlCenterBridge.install_application_update` delegates to `UpdateCoordinator`.
2. `application.py::_update_coordinator` supplies `_application_updates(service)` and a restart callback dispatched onto Qt. Automatic update checking is a startup setting, not a periodic background job.
3. `app_update.py::installed_version()` reads `importlib.metadata.version('hanly-app')`; the spec copies product metadata. Both packages and the app's engine pins currently equal 0.1.3.
4. `installation_root()` returns None for source installs; frozen macOS uses `paths.macos_bundle_root()` to find an exact `.app/Contents/MacOS` path. Other frozen paths use the executable's parent. It follows resolved paths, so a moved normal installation is discoverable, but a renamed `.app.staged` no longer has the recognized suffix and can resolve to its internal MacOS directory instead.
5. `update_service.py::GitHubReleaseFetcher` defaults to `ThiagoRoss1/hanly` through `first_run.py`, configurable in runtime JSON. `/latest` or `/tags/<tag>` supplies metadata. Resource checking refreshes the cached payload; application checking and downloads reuse it. `_collect_updates()` currently calls resource checking first, so a resource manifest failure prevents application checking entirely.
6. `check_application_update()` compares plain three-part versions, offers only strictly newer tags, and checks platform asset and `SHA256SUMS` presence. It does not explicitly reject payloads marked draft/prerelease, handle architecture, or distinguish missing assets from an externally managed source install in its message.
7. `ApplicationInstaller.stage()` confirms the selected tag, writes fixed sibling `.hanly-update.download`, streams the archive, downloads `SHA256SUMS`, verifies SHA-256 before extraction, and stages a payload. HTTPS certificate validation and HTTPS-only redirects already exist; retain them. Application downloads currently omit the available asset-size bound.
8. Windows uses ZIP → `hanly-desktop/`; Linux tar.gz → `hanly-desktop/`; macOS uses `hanly-desktop-macos.zip` → `ditto` → `Hanly.app/`. DMG is human installation media and is never mounted by this updater.
9. macOS preflights archive member/link paths and checks `CFBundleIdentifier` plus `Contents/_CodeSignature/CodeResources`. The post-extraction walk does not inspect symlinked directory entries explicitly. `ditto --sequesterRsrc` packaging may include AppleDouble metadata; the strict current root check does not allow `__MACOSX`. Test actual generated ZIPs before deciding whether this affects this build.
10. `_place()` moves the payload to `<install-name>.staged`; the running install remains intact. `apply()` writes a sibling script and starts it. The coordinator reports restart, then Qt quits. `DesktopApplication.shutdown()` waits for the update executor; `cli._leave()` terminates without unloading native libraries.
11. Helpers poll for old PID exit (120 s), rename install to `.previous`, rename staged to install, restore old on second-rename failure, and launch from final location. Windows retries initial rename for lingering locks. This is two recoverable renames with a gap, **not an atomic exchange**. Existing backup is deleted before beginning; failure can destroy the only recoverable version from an earlier interrupted attempt.
12. POSIX directly execs the inner binary, including on macOS. Windows has the doubled extension defect. Helpers persist, backup is removed too early, launch success is not verified, original explicit runtime/app-config arguments are lost, and no next-launch recovery or version receipt exists.

### 2.2 Chosen implementation direction

Keep the existing app installer and coordinator; replace the incomplete handoff with one small durable transaction and native helpers. A durable record is justified by process exit and interruption between two renames; it is not a general update state-machine framework.

**Canonical target:** the current frozen installation, discovered anew from the running executable. For Darwin require a real `.app` with the expected identity; never fall back to `Contents/MacOS` for a malformed/staged bundle. Reject execution from updater-owned transaction/backup trees and read-only mounted/translocated installation locations with an actionable install/move message. Do not search for and delete other user-created copies, move arbitrary apps into `/Applications`, or assume a hardcoded Windows path. “One installation” means this canonical target plus no updater-created usable siblings after success.

**Transaction location:** one uniquely named, hidden app-owned directory beside the canonical target, on the same filesystem, holding archive, staging, rollback, helper, and a small UTF-8 JSON receipt. Reserve an exclusive lock keyed by canonical target; two Hanly processes targeting the same installation must not update concurrently. Do not use global fixed download/script names. Parent writability and space for archive + extraction + retained old payload are checked before shutdown. No auto-elevation.

**Record:** transaction ID, resolved target, expected old/new versions, platform/architecture, old PID with process identity, validated staging/backup paths, explicit relaunch configuration arguments, and progress necessary to recover interrupted rename/launch. Write records atomically within the transaction. A small marker/receipt for helper-ready and new-app-ready is enough; keep persisted progress understandable. Never use a record to delete arbitrary paths: require containment, target identity, owned basename/ID, and safe symlink handling again on recovery.

**Build identity:** generate a tiny `application-build.json` in the packaged app assets before freezing/signing, containing schema version, app/engine versions, platform, and build interpreter architecture. Validate against installed distribution metadata and native executable architecture before handoff. On macOS also validate Info.plist version/identifier and `codesign --verify --deep --strict`. Include the build identity inside the archive, covered by its SHA-256; do not add a separate hosted manifest or change the seven-asset release contract. Record architecture explicitly in the build matrix and assert runner/Python/native payload agree. Preserve the existing single artifact per platform: reject unsupported architectures clearly rather than guessing or adding Intel/universal macOS builds to this wave. Running under translation must compare the executing build architecture, not only physical CPU architecture.

**Archive handling:** retain existing ZIP/DMG/tar filenames. Keep macOS `ditto` and whole-bundle replacement. Make Linux application extraction app-specific so legitimate relative internal symlinks and executable permissions survive; keep the resource extractor's conservative policy unchanged. Validate all entries before writing: exactly the expected root, no absolute/drive/traversal paths, duplicate conflicting members, devices, or links escaping the payload. Reject hard links unless a real produced archive proves they are needed; then validate their internal target too. Verify the resolved complete tree, including symlinked directories. Account narrowly for legitimate AppleDouble entries only if the real ditto archive includes them; never globally relax root containment.

**Handoff and acknowledgement:** old app stages, validates, starts the helper, and receives helper-ready before requesting normal Qt shutdown. Helper waits for the specific old process to exit, swaps, and launches **only the final target**. New app uses the existing `cli.main` path with an internal transaction argument; validates its actual path, installed version, identity, and transaction token, then reports startup PID and readiness. Confirm readiness once the shell/bridge and worker are ready, without requiring capture permission, Start Capture, or a successful network update check. A fresh metadata check alone never restarts the app. Suspend automatic update checks until pending transaction recovery/acknowledgement completes.

Retain rollback until version/readiness acknowledgement. Start with the existing 120 s bound for old-process exit; use the established UI/runtime smoke bounds to choose and document a separate new-app readiness timeout (not an unmeasured short sleep). A timeout is failure, never assumed success. Before rollback terminate/wait only for the exact new process launched for this transaction; if its identity cannot be established or it cannot stop, retain the backup and actionable recovery information without overwriting a live installation. A failed rollback launches nothing and preserves the previous payload.

**Platform helpers:** keep shell mechanics at natural OS seams; no Python dependency outside the frozen app and no second frozen executable.

| Platform | Implement |
|---|---|
| Windows | Replace the brittle generated batch body with a small locally generated PowerShell helper using native filesystem operations and explicit process ownership. Windows PowerShell 5.1-compatible syntax; UTF-8 JSON paths, literal paths, no path interpolation into executable script text. Launch hidden, no profile, no machine policy changes. Validate helper startup before quitting; policy refusal leaves old app running. Use an explicit full executable path exactly once, without suffix reconstruction. Test argument quoting at the native process boundary; `Start-Process -ArgumentList` alone does not prove correct quoting. Keep bounded retries for locked files. Delete helper/transaction after confirmed readiness, or arrange next-launch cleanup if it cannot delete itself yet. |
| macOS | Locally generated POSIX helper, `/usr/bin/open` with the full final `.app` path and explicit arguments for native launch. No name-only `open -a Hanly`, no `.cmd`/PowerShell, no launching staged bundle or mounting the human DMG. Obtain new process identity through the startup receipt because `open` is not the app process. Validate existing ad-hoc signature structurally, preserve quarantine behavior, never strip xattrs or disable Gatekeeper as a fix. |
| Linux | POSIX helper launches the final executable, preserving executable bits and relative library links. It owns/waits for the launched PID. Require a writable extracted onedir installation; package-manager/system-owned locations are an actionable unsupported target. |

Helpers are generated from local trusted code; never download a helper separately. Keep platform rendering in `app_update_handoff.py`, with short private functions per platform if needed. `app_update.py` owns check/stage/record/recovery policy; avoid a hierarchy of managers.

### 2.3 Four implementation blocks, in dependency order

**A. Release identity and canonical staging.** Modify `app_update.py`, `paths.py`, `packaging/hanly-desktop.spec`, `tools/build_package.py`, `tools/smoke_packaged_runtime.py`, and the build matrix in `.github/workflows/build.yml`. Generate/collect/read the embedded build identity. Normalize supported architecture aliases; check native payload architecture, version, expected root, and signature before touching live files. Pin the checked release payload's asset IDs/URLs, size, and digest for the whole attempt. Reject drafts/prereleases explicitly, same-version/downgrades, malformed/duplicate checksum entries, missing/multiple platform assets, and missing integrity data. Stable-only remains the product policy even for a configured tag; no prerelease feature is introduced. A fresh user check refreshes once; stage consumes that selection or fails with “check again,” never mixes cached releases. Pass size to the existing downloader and verify exact byte count plus SHA-256. Resource manifest failure must not hide the application check: collect the two outcomes independently while retaining one serialized update owner and the shared fetcher. Changes to `update_service.py`, if needed, stay confined to delivery primitives/cache use, not resource activation.

**B. Recoverable replacement and native relaunch.** Implement the transaction, extraction rules, platform helper, acknowledgement, and rollback above. Modify `app_update.py`; create `app_update_handoff.py`; add the internal transaction argument/validation in `cli.py` and readiness wiring in `application.py`. Keep `packaging/entrypoint.py` as a forwarding entry point. Remove `_reserve`'s destructive fixed names, old template bodies, unconditional backup deletion, and the doubled extension path. Do not leave parallel old/new handoff implementations.

**C. Ownership, shutdown, recovery, and data survival.** In `update_coordinator.py`, consider an operation active until its matching callback finalizes, not until `Future.done()`. Use future identity plus a closed flag (or a single generation) to ignore stale callbacks; keep the existing single executor and lock. Refuse new update actions after handoff starts. On user quit before handoff, abort at download/progress boundaries and clean the owned transaction while leaving the install intact; ensure shutdown cannot wait forever on a download making slow progress. After helper-ready, the helper owns recovery. Hiding the Control Center leaves the operation alive. Failure clears busy state only after transaction ownership has been resolved, allowing a safe retry.

Startup inspects only this install's owned pending record: discard an abandoned pre-swap transaction; restore a backup when install is absent; validate an unacknowledged final payload and finish or roll back; finish cleanup of an acknowledged update. Never delete the only old healthy payload to start another update. If OS restart leaves the canonical path absent, the retained transaction must include a minimal platform recovery command/helper capable of restoring it without Python; document this in its diagnostic receipt. Do not pretend an absent canonical executable can run startup recovery by itself.

Preserve external config/KRDICT by leaving their paths and bytes untouched. `paths.discover_runtime_config()` currently prefers executable-adjacent runtime JSON on Windows/Linux; replacing its containing tree would lose that file. Before staging, resolve actual runtime/app-config/resource/model paths. For legacy install-local mutable data, copy the known referenced files/directories to an owned per-user location, rewrite their resolved references, validate the new runtime, and retain the originals until success. Preserve existing per-user data on conflicts; do not overwrite it blindly or copy arbitrary install contents. Refuse ambiguous/unmigratable configuration before exit with an actionable explanation. Preserve explicit external `--runtime-config` and `--app-config` arguments across relaunch; never replay `--self-check` or unvalidated arbitrary CLI text. Relevant files: `paths.py`, `application.py`, `cli.py`, and existing runtime-path normalization in `runtime.py`.

**D. Gate at the actual native boundary.** Extend current tests and a small packaged update probe; see below. Update `packaging/README.md` with canonical installation/update limitations and receipt/recovery instructions. Correct the `docs/CODE-MAP.md` update index during implementation. No architecture invariant changes are required by this direction; any newly discovered conflict needs human approval.

### 2.4 Focused tests and native validation

Use existing fixture seams (`AssetDownloader`, release source, spawn, temporary filesystem), not a mock GitHub server ecosystem. Existing `tests/test_app_update.py` Windows script tests substitute relaunch with a marker and render the default executable name; that explains why they miss `.exe.exe`. Replace/extend them to exercise the actual `ApplicationInstaller.stage → apply` command and the new native helper, retaining useful rollback tests.

| Test boundary / files | Required behavior |
|---|---|
| `tests/test_app_update.py` | Table of current/equal/older/newer/non-comparable/draft/prerelease/missing asset/checksum/architecture cases. Non-update never downloads, stages, or exits. Mutating cached metadata cannot change an in-progress selection. Truncated/oversized/corrupt/checksum-mismatched inputs leave old bytes unchanged and clean temporary files. |
| Same file, real temporary archives | Expected payload/version/architecture required; malicious paths/links rejected before extraction; internal POSIX links/modes preserved. Real ditto archive preflight on Darwin, not solely `_Ditto`'s `zipfile.extractall` imitation. Wrong signature/version refused before swap. |
| Native helper tests, new `tests/test_app_update_handoff.py` | Execute each platform's helper on that platform against tiny temporary old/new programs. New program acknowledges its final path/version/token. Prove success, first/second move failure, new-launch failure, missing acknowledgement, cleanup, path spaces/non-ASCII, and exact-process shutdown. No replacing relaunch with a marker for the principal success test. |
| `tests/test_update_coordinator.py` | Deterministically defer callback execution after future completion, attempt a second click, then deliver old callback. Only one operation proceeds and old callbacks cannot clear newer/closed state. App check still available after resource-check failure. No resource/app overlap; no second handoff between completion and Qt quit. |
| `tests/test_application.py`, `tests/test_first_run.py`, `tests/test_app_config.py` | Restart only after helper-ready; hide does not cancel; user quit has bounded behavior; explicit external config is retained; install-local legacy data survives migration and rollback; pending transaction confirmation does not depend on network or capture permission. |
| `tests/test_packaging.py`, `tests/test_ci_workflows.py` | Embedded identity is collected and agrees with versions/architecture; sole entry point preserved; required native updater/UI lanes run after build and cannot silently skip. |

Add a bounded `tools/smoke_application_update.py` and `tests/integration/test_application_update.py` only for what existing smoke cannot prove: a **real frozen old → new process swap**. Reuse `tools/smoke_packaged_runtime.py` isolation and `tools/build_smoke_krdict.py`. The probe supplies local release bytes at the downloader seam while exercising real checksum/extraction/handoff/relaunch; no production insecure HTTP or test-channel option. The frozen old build needs a narrow internal self-check route through the same CLI to invoke this path and report the transaction; it is not a second application entry point. Unit tests exercise GitHub metadata/TLS separately.

Build two genuine versions from tracked inputs in separate disposable checkouts and preserve both build provenance records. For the first corrected updater, use a predecessor fixture containing the corrected handoff to prove future updates, **and separately test the actually shipped v0.1.3 updater if its artifact is available**. A defect inside v0.1.3 cannot be repaired by code that has not yet been installed. If v0.1.3 cannot self-update safely, record manual canonical replacement as the one-time migration path; do not claim backward upgrade works or patch installed users remotely. Synthetic renaming of a ZIP/version string is not a two-version test.

On Windows/macOS/Linux native lanes verify final path and metadata version, one Hanly main process (Chromium children are expected), working window/bridge/popup/lookup, stable user config and KRDICT hashes, no mounted update image, no staging/archive/helper/backup after acknowledgement, and repeated Check/Update returns current. Exercise a moved installation, spaces/non-ASCII paths, read-only parent, duplicate clicks, slow old shutdown, corrupt archive, and interrupted handoff. A real macOS old/new swap and a real Linux tar extraction remain CI/native-only here.

For the original macOS report, collect old build version, actual process executable path, folder names, helper contents, selected release/asset, and receipt/logs on that machine. Current-source reproduction should first establish whether `.cmd` can appear at all (expected: no). This is the remaining incident-attribution gap, not permission to re-investigate the whole architecture.

### 2.5 Phase completion gate

- Focused checks after each block, then all ordinary project gates: `python -m pytest`, `python -m ruff check packages packaging tests tools benchmarks`, `python -m mypy packages packaging tests tools benchmarks`.
- Native helper tests and real frozen corrected-old → new update pass on the three supported build lanes; archive round trip, final version, rollback, cleanup, and external data survival are evidenced. Original-v0.1.3 transition is explicitly passed or documented as requiring manual replacement.
- macOS/Linux frozen Control Center smoke is blocking; release cannot consume a build with required smoke failure or skip. No UI redesign.
- A Review Handoff states exact tested artifacts/platforms and remaining blockers. Stop for human review; unresolved reliability failures block HAN-40.

## 3. Phase 2 — HAN-40: packaged/download size

### 3.1 Measured baseline and collection causes

Existing `dist/hanly-desktop-windows.zip` was read with `zipfile`; sums below are actual member sizes, not rough directory guesses:

| Metric | Baseline |
|---|---:|
| Files, excluding ZIP directory entries | 6,481 |
| Uncompressed member bytes | 1,535,857,417 (1.4304 GiB) |
| ZIP file bytes | 663,943,375 (633.19 MiB) |
| Reported download family totals from HAN-40 | Qt ~178.7 MiB; Torch ~102.1; EasyOCR weights ~87.9; Kiwi ~87.4; OpenCV ~54.2 |

The local environment has OpenCV-headless 5.0.0.93, Torch 2.13.0, torchvision 0.28.0, PyQt6/Qt 6.10.2, PyQt6-WebEngine 6.10.0, Kiwi 0.23.2/model 0.23.0, PyInstaller 6.22.2, and hooks-contrib **2026.6**. `packaging/release-constraints.txt` requires hooks-contrib **2026.7** and EasyOCR 1.7.2. Record this mismatch: a fresh constrained build must establish its own baseline before measuring code changes.

`packaging/hanly-desktop.spec` already explicitly selects Qt modules and OS input/tray backends. It is not simply collecting all of Qt. It does broadly `collect_all('easyocr')`, `collect_all('torchvision')`, and both Kiwi packages; Torch's installed upstream hook collects its submodules. `_unique()` removes identical source/destination pairs, not redundant files at different destinations. The Qt hook collects the complete resources directory. OpenCV's Windows hook collects dynamic libraries present under `cv2`, including unowned residue. `--clean` resets PyInstaller analysis; it does not clean site-packages.

### 3.2 Removal decisions, savings, and risk

Values are **MiB of local uncompressed bytes / ZIP compressed member bytes**. They are upper bounds for a comparable build, not guaranteed deltas across Python/dependency versions. Final ZIP central-directory overhead is small but measured separately. A dash means no defensible saving measured; budget it as zero until proven.

| Candidate | Why included / ownership and runtime use | Decision, saving, risk, frozen proof |
|---|---|---|
| `cv2/opencv_videoio_ffmpeg4100_64.dll` | 26,391,552 / 10,930,768 bytes. Present in `.venv` and TOC; installed OpenCV-headless RECORD names only `500`. No opencv-python distribution installed. This is an unowned older file, not two proven active variants. | **Remove at build source via clean environment**, not by deleting user venv files. Expected 25.17 / 10.42 MiB versus local baseline. Low risk if no longer collected; real frozen image OCR and cv2 import required. |
| `qtwebengine_devtools_resources.debug.pak` | 81,573,852 / 15,334,066 bytes; Qt resource directory collection includes it despite `debug=False` host. | First explicit pruning experiment: exclude this exact debug asset at analysis/collection. Expected 77.79 / 14.62 MiB if safe. Medium risk; fresh frozen window, JS bridge, hide/restore, popup and 100%/200% DPI smoke. Restore on missing-resource errors. |
| `qtwebengine_devtools_resources.pak` | 11,020,759 / 11,006,260 bytes; remote-debugging resources, but upstream deployment docs list it with required files. | **Keep initially**. Possible 10.51 / 10.50 MiB, not counted in accepted saving. Only remove in a separate measured experiment if this Qt build demonstrably operates without it on all native lanes. `debug=False` alone is insufficient. |
| Current `opencv_videoio_ffmpeg500_64.dll` | 30,876,160 / 13,002,127 bytes, owned by OpenCV-headless; its video backend is not called by Hanly's RGB-array EasyOCR path. | After stale-file cleanup, test removal of this exact optional video plugin. Possible 29.45 / 12.40 MiB. Medium risk: verify native dependencies, cv2 import and real detection/recognition/preprocessing, including sensitive retry. Do not remove `cv2.pyd` or build a custom OpenCV in this wave. |
| `torchvision/python313.dll` | 7,145,800 / 2,686,645 bytes; `collect_all(torchvision)` collects its bundled Python DLL. Root Python DLL is 6,113,624 bytes; SHA-256 differs. | **Do not deduplicate by filename.** At most 6.81 / 2.56 MiB candidate; determine native dependency/loading relationship in the fresh wheel/TOC. Keep unless proven unnecessary with OCR-before-Qt startup and all frozen smoke. High risk for modest saving. |
| Broad EasyOCR/torchvision Python/data collection | Local exposed trees: EasyOCR 15,683,040 / 2,828,429 bytes; torchvision 11,685,567 / 4,114,568. Those totals are not removable budgets. Hidden modules may also live in the executable PYZ. | Replace blanket collection with required data plus import graph/hook handling, one package at a time. Preserve dynamically selected Korean recognition module, CRAFT, character data, torchvision dependencies, and metadata used by runtime. Saving unmeasured; zero budget. Frozen OCR of real Korean text, not import-only, after each change. |
| Vendor tests/docs/stale OS backends | Only four `/tests/` members found in exposed ZIP paths, totaling 25,042 / 4,086 bytes. Existing OS hidden imports are already conditional. | Do not promise large savings here. Inspect PYZ/TOC for additional Python-only modules and remove only named unused content. Preserve legal/license files. Backend removal must retain native hotkey/mouse/tray smoke on each OS. |
| Torch/functorch/torchgen | `torch_cpu.dll` alone 305,081,856 / 84,263,667 bytes; necessary CPU inference. Exposed functorch only 1,485,682 / 367,727 bytes; no exposed torchgen directory does not prove absence from PYZ. | Keep CPU engine, quantization and dependent native DLLs. Confirm CPU wheels, especially Windows (workflow explicitly preinstalls CPU only on Linux). Limit Python collection only when import evidence supports it. No blind DLL pruning, ONNX conversion, or broad `torch.*` exclusions. Savings unmeasured. |
| Kiwi/model assets | Model tree 109,042,347 / 88,064,468 bytes; `cong.mdl` alone 75,667,563 / 72,416,557. `KiwiProvider._get_analyzer()` uses `Kiwi()`; defaults and lazy loading belong to its native implementation. | Keep models/default dictionaries in this wave unless actual native file-open evidence proves a file unused across normal tokenization. Wrapper `model_type='none'` is not evidence that `cong.mdl` can be deleted. No dictionary/quality trade for a size claim. Savings zero until a tested removal exists. |

Two primary-source constraints support the conservative choices: [Qt WebEngine deployment](https://doc.qt.io/QT-6/qtwebengine-deploying.html) describes the runtime resources and helper process; [PyInstaller POSIX symlink requirements](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html) explain why apparently duplicate POSIX paths may be necessary links. Installed hooks are the precise local collection evidence; confirm the constrained hook version's behavior before editing filters.

### 3.3 Three implementation blocks

**A. Reproducible inventory and clean baseline.** Use `benchmarks/dev/package_composition.py` rather than adding an inventory framework. Extend its existing report to include ZIP `compress_size`, Kiwi/model and EasyOCR-weight groups, and optional same-size/hash duplicate candidates; preserve separate logical size and symlink-aware physical size on POSIX. Its current family matching misses some important groupings, and it does not measure download bytes. Add concise tests in `benchmarks/dev/tests/test_benchmark_core.py` using tiny archives. Retain exact component/file list and resolved dependency versions in build reports, alongside TOC and PyInstaller warnings. Inspect candidates in `dist/.pyinstaller/<platform>/hanly-desktop/Analysis-00.toc`, `COLLECT-00.toc`, and `PYZ-00.toc`. Build from a new constrained environment to eliminate the stale FFmpeg without modifying the developer environment.

**B. Targeted pruning, in requested priority order.** Start with accidental residue/debug content, then replace broad collection, then test the current OpenCV video plugin; only then evaluate additional Qt, Torch, and Kiwi candidates. Put small exact filters near the spec's collection logic, before final packaging/signing, with a comment naming owner and absent runtime use. Do not strip files out of a signed `.app` after build. Do not edit third-party site-packages. Modify `packaging/hanly-desktop.spec`, `packaging/release-constraints.txt` only for validated version requirements, and `.github/workflows/build.yml` for clean dependency installation/reporting. Change package extras only if the actual dependency contract changes; do not add runtime dependencies solely for packaging inspection. Every accepted group gets a fresh build and relevant frozen smoke before another group is layered on. Revert the group immediately if it breaks native behavior.

**C. Freeze the budget and gate.** Initial comparable-local target: remove stale `4100` plus debug `.pak` for about **102.96 MiB unpacked / 25.05 MiB ZIP**, giving roughly **608.1 MiB ZIP / 1.330 GiB payload**. This is a target contingent on the debug smoke, not a claimed achieved saving. Current FFmpeg removal would bring total reduction to about **132.41 / 37.45 MiB** (roughly **595.7 MiB ZIP / 1.301 GiB payload**), contingent on its own smoke. Do not sum overlapping family and file savings.

The gate requires a measured reduction with every accepted removal accounted for. If clean constraints materially change totals, record both the original 633.19 MiB comparison and a same-environment before/after comparison. Use a 610 MiB Windows ZIP / 1.34 GiB logical payload provisional budget for the first two cuts; a failed safety experiment or dependency drift requires an explicit reviewed budget adjustment, not unsafe pruning to hit a number. No platform may silently grow more than 2% relative to its fresh baseline without explanation and human acceptance. Keep the existing <2 GiB individual release-asset limit, but that alone is not a useful optimization budget.

### 3.4 Phase completion gate

Run focused packaging/inventory tests throughout, then pytest/Ruff/mypy. Fresh Windows/macOS/Linux archives must pass inventory, real OCR/Kiwi/KRDICT, frozen Control Center/bridge, popup, hide/restore, and native hotkey/tray/capture checks. Re-run HAN-42's update from an unpruned predecessor to the pruned candidate and verify identity/checksums/cleanup. Confirm EasyOCR models and certifi are bundled, KRDICT stays external, development tooling stays out, and all seven hosted asset names are unchanged. Report startup and warm OCR before/after to catch collection-induced latency changes. Leave the phase Review Handoff and stop before HAN-41.

## 4. Phase 3 — HAN-41: cheap idle and low lookup latency

### 4.1 Current behavior and measurements

| Area | Current source result |
|---|---|
| Startup/provider residency | `application.py::_DesktopSession.activate → manual.prepare()` starts worker construction/warm-up before Start Capture. `composition.LookupWorker` constructs OCR, Kiwi, and dictionary on its owning thread and caches/reuses them. |
| Work while idle | `job_executor.JobExecutor._run()` waits on `Condition.wait()` with no timeout. No OCR/capture loop exists. `mouse_observer.MouseObserver` coalesces movement to one pending delivery; desktop uses the reused single-shot `qt_hover_scheduler.QtHoverScheduler`, not a thread timer per event. |
| Trigger modes | `ManualLookupRuntime.start()` registers the hotkey and starts hover. `pause()` invalidates pending work and pauses hover/listener while retaining the manual hotkey. Before Start, providers are prepared but hotkey is not registered. This existing Start → Pause path already provides manual-only availability. |
| Stationary hover | No new capture on stationary changing content. Movement/debounce/currency/target checks determine a lookup; no full-screen continuous OCR. Keep this deliberate behavior. |
| Capture | `capture.MSSBackend` owns a reusable MSS session; captures an ROI, converts screenshot RGB, and normalizes dimensions. Default is 200×100, with 32-pixel origin snapping. Production `--roi` can override it. Measure physical dimensions/DPI instead of assuming logical pixels. |
| Cache/gates | `composition.py`: 32-result lookup cache, 96-result OCR cache; optional flat-region gate. Gate is off by default. Same-image cache hits must not be reported as model inference latency. |
| Compute | `EasyOCRConfig` requests `gpu=False`, and Torch thread default caps at four. `prewarm()` uses blank 96×32 grayscale, not actual recognition text. Kiwi uses default worker settings; local wrapper maps omitted `num_workers` to `-1` (automatic), a candidate for measurement because Hanly submits serial work. |
| UI idle | Control Center refresh is 500 ms only during pending runtime/update or bounded permission watch (60 ticks). It stops in stable idle. Do not replace this with a new push/event infrastructure. `signal_bridge.QtSigintBridge` does run an unconditional 100 ms no-op Qt pulse to service Python signals. |
| Background availability | Control Center hides/restores through its host/tray lifecycle; providers must stay available. WebEngine remains resident and may have child processes; this is not evidence of ongoing inference. |
| Network | First-run provisioning and optional startup update check; no periodic update polling found. Remote download requests have timeout/stream behavior independent of idle lookup. |

Fresh isolated Windows **provider-only**, current-source probe (not full desktop/frozen latency): explicit model paths to the local frozen weights, downloads disabled, temporary user/network/cache paths, Korean fixture 192×48, EasyOCR + Kiwi resident, Torch four threads. No real user configuration was read/written.

| Observation | Result / limit |
|---|---|
| Construction + OCR blank prewarm + Kiwi prewarm | 21.72 s in this run; includes cold imports/initialization, not a reproducible startup percentile. |
| First Korean fixture OCR after blank warm-up | 649.43 ms |
| Subsequent OCR samples | 10 measured after two fixture calls: median 103.34 ms, max 112.53 ms; direct provider bypasses application caches. |
| RSS / threads | 998,944,768 bytes / 40 native threads after work. This is residency, not 40 busy threads. |
| Immediate 10 s post-work CPU | 0.5 CPU s = 5.0% of one core on average, not machine-wide CPU percentage. |
| Separate repeat, successive 5 s idle windows | 0.5312, 0.0469, 0.0312 process CPU s (10.62%, 0.94%, 0.62% of one core). The first interval had several active native threads; later intervals were much cheaper. RSS settled around 1.012 GB, 40 threads. This suggests post-work settling, not proof of a permanent busy loop. |

These probes exclude Qt/WebEngine, mouse, capture, dispatch and dictionary lookup; they do not establish whole-app idle CPU/GPU or explain macOS-vs-Windows. GPU was not instrumented. Do not convert 103 ms OCR into a hover-to-visible-pixel claim.

Historical evidence: `docs/execution/reports/ocr-latency-and-roadmap.md` reports roughly 150 ms dwell + 16.6 ms MSS + 120 ms OCR on Windows, with Kiwi/dictionary/Qt together around 0.5 ms. It records rejected allowlist/magnification/upscale/full-ROI recognize-only experiments; do not repeat them without new evidence. Its CRAFT/CRNN subsection's printed percentage is inconsistent with its listed timings, so use the stage timings cautiously, not the percentage. An August 28 EasyOCR run (`artifacts/benchmarks/runs/a7ff076b-f087-47a7-b4db-49dc5afa16fc`, commit `7478f653`) has only three samples: OCR median 80.85 ms, total pipeline 81.76 ms at 192×48. Older August 23–24 runs are from an obsolete backend snapshot and cannot establish today's idle baseline. Existing frozen smoke stages create extra providers and include initialization; their multi-second stage durations are not warm lookup measurements.

### 4.2 Chosen direction and profiling block

Keep providers warm, one worker, existing Start/Pause/Resume and manual hotkey behavior. Do not unload Torch/Kiwi or rebuild providers per request. Do not add a mode state machine or change default capture activation. Phase 3 starts with the HAN-40 dependency/build baseline, not an unrelated developer environment.

Use `benchmarks/dev`'s existing campaigns, traces and process sampler. If process-tree/settled-idle measurements are missing, extend `live_telemetry.py`, `desktop_probes.py`, `campaigns.py` or add one focused `idle.py` under that directory. Developer-only instrumentation stays outside `packages/`. Declare `psutil` in the appropriate development extra/group if the command requires it; it is installed locally but not declared by the current dev group/extra. No new mandatory production dependency.

Measure three runs of each controlled state, 30 s settling then 120 s sampling: ready before Start; active hover with stationary cursor over flat/text ROI; Start then Pause/manual-only; Control Center visible and hidden; after a short lookup burst; after restore. Include separate mouse movement over a controlled test window. Count capture and real OCR invocations after startup: **zero during settled stationary/no-trigger idle**, and one bounded request path for an explicit trigger. Do not capture arbitrary user screen pixels or touch real profile/model data; use an isolated profile and controlled Korean window. Measure with instrumentation disabled as a control so sampler overhead is visible.

Record process-tree CPU seconds/wall seconds with one-core normalization, per-child CPU, RSS/private bytes (and USS/PSS where available), thread count and active-thread CPU, context switches/wakeups where available, GPU engine usage for Hanly/Chromium where available, timer counts, network events, and sample duration. Mark unavailable GPU/wakeup metrics unavailable; `gpu=False` only establishes OCR configuration, not Chromium GPU behavior. On Windows include Chromium children and native profiling if CPU remains active; on macOS use native process sampling/Energy tools; Linux uses process stats/perf where practical. Do not double-count shared-memory RSS as physical usage.

For latency, capture 30 warm samples per scenario per platform after separately reporting startup/first actual lookup. Use controlled text at matched physical 192×48 and default 200×100 ROIs, plus a high-DPI/multimonitor case. Record OS/hardware/power mode, Python and dependency versions, OCR readtext options, Torch thread count, exact ROI, scaling, capture backend, image content class and result correctness. Separate:

```text
movement/hotkey → dwell → capture/RGB conversion → queue wait → OCR conversion
→ detection/recognition → resolver → Kiwi → KRDICT → Qt dispatch → popup show
```

Existing traces give much of this through `runtime_trace.py`, `hover_lookup.py`, `manual_lookup.py`, `lookup_controller.py`, and composition wrappers. Add missing timestamps only where they distinguish a candidate bottleneck; off by default. `show()` completion is a dispatch/show endpoint, not measured screen presentation; label it honestly. Use a frame/paint acknowledgement for visible-popup timing where practical. Separate cache hit, warm uncached OCR, sensitive retry, flat/no-Hangul, success and non-success. The existing `real-hover` fixture campaign is not a native capture measurement.

### 4.3 Bounded optimization blocks after the baseline

**A. Remove demonstrated idle work.** Test whether the 100 ms signal pulse contributes measurable wakeups. Preserve source/terminal Ctrl+C behavior; if a frozen GUI process has no console signal source, avoid installing the pulse there using a simple composition condition in `application.py`/`signal_bridge.py`. Do not delete signal support globally or infer absence of a console from `sys.frozen` alone. Keep visible/in-progress update/permission refresh working. Investigate WebEngine hidden-window activity only if process-tree samples attribute meaningful CPU to it; retaining the host/window is necessary for restore and readiness. Do not destroy/recreate WebEngine to save speculative RAM.

**B. Improve first usable lookup and the measured dominant stage.** First A/B test recognition-inclusive prewarm in `easyocr_provider.py::prewarm`: a tiny deterministic in-memory text-like input or a tightly bounded recognition warm call on the existing reader, with no file/network data dependency. Confirm which kernels run; blank detection alone may not warm CRNN. Keep only if first real text lookup improves materially without unacceptable startup cost, added models, or OCR output changes. Use the existing prewarm hook/worker readiness, not a second initialization manager.

Then A/B Torch 1/2/4 threads on representative machines through existing `cpu_threads`; preserve the default unless evidence supports changing it. Measure active CPU and post-inference settling as well as median/p95 latency. Test Kiwi `num_workers=1` versus its current default in an isolated probe before considering a constructor change in `kiwi_provider.py`; do not add an engine configuration seam for one experiment. Keep only a demonstrated improvement with identical normalization/tokenization results.

For warm steady-state latency, choose the measured largest stage: retain caches and ROI snapping; profile MSS/RGB/DPI normalization if capture dominates, or inference if OCR dominates. Keep 200×100 and the current 150 ms dwell default unless multiple text sizes/lines and targets demonstrate a safe change. Reducing dwell is a UX/false-trigger trade, not faster inference. Do not narrow ROI merely to win the one fixture. Do not change resolver, dictionary schema/queries, morphology model, or add caches there based on historical sub-millisecond costs. Do not replace capture backends or add OCR algorithms without a measured bottleneck and separate approval for structural changes.

Each accepted change must state what complexity/work disappears, its before/after result, quality checks and rollback trigger. If current behavior already meets the targets, retain it and record evidence rather than manufacture a refactor.

### 4.4 Tests, performance budgets, and gate

Focused regression files: `tests/test_job_executor.py`, `tests/test_mouse_observer.py`, `tests/test_hover_controller.py`, `tests/test_qt_hover_scheduler.py`, `tests/test_hover_lookup.py`, `tests/test_manual_lookup.py`, `tests/test_lookup_controller.py`, `tests/test_app_composition.py`, `tests/test_easyocr_provider.py`, `tests/test_kiwi_provider.py`, `tests/test_signal_bridge.py`, `tests/test_control_center_refresh.py`, and relevant `benchmarks/dev/tests`. Touch only those affected by chosen changes.

Prove no idle capture/OCR after readiness; bounded latest-wins behavior under movement; pause stops hover but allows manual lookup; hide/restore leaves the app available; stale results cannot present; warm providers are created once and closed on their worker; sensitive retry and small-text quality remain intact. Use deterministic schedulers/events for invariants, not real-time performance assertions in unit CI.

Initial performance targets, subject to the measured machine baseline and human review:

- Settled hidden/manual-only process-tree CPU mean ≤1% of one logical core over 120 s, zero capture/OCR/network checks without a trigger; stationary hover should be comparable. Report GPU independently, aiming for no sustained Hanly-attributable idle compute.
- Same-machine warm uncached lookup/popup p95 must not worsen by more than 5% across three runs; first lookup after readiness should approach warm latency, with a provisional ≤1.5× warm p95 target. Cache hits cannot satisfy this gate.
- No unbounded memory/thread growth over a 30-minute hide/restore/pause/lookup session. Initial budget: settled memory after repeated activity within 5% or 50 MiB (whichever larger) of its settled baseline; explain allocator plateaus rather than demanding provider unloading.
- For an optimization claimed as latency work, require a repeatable ≥10% reduction in its targeted stage or remove the change. If variance exceeds the claimed gain, evidence is inconclusive and the old implementation stays.
- Preserve fixture outcomes and manually checked dense lines, isolated syllables, punctuation, high DPI and multi-monitor targets. The small fixture is regression evidence, not a recognition-accuracy corpus.

Run ordinary pytest/Ruff/mypy and fresh frozen smoke on the dependency set from HAN-40. Windows and macOS comparison requires native measurements; record Linux where practical. If macOS evidence is unavailable, mark the comparison incomplete; never assert why it feels faster. Leave phase Review Handoff; no unresolved idle busy-loop, latency regression, failed platform smoke, or unreviewed budget exception may be hidden by local green tests.

## 5. Final clean-machine / CI / release validation

This is mandatory **after all three implementations and their phase reviews**, even if every local test passed. It proves the final combination and build contract. It is not authorization to publish. Use one final evidence section in the wave handoff, not a new collection of planning documents.

### 5.1 Tracked-only source and independent environments

Use a fresh clone of a human-approved revision. If changes are not yet committed, export HEAD plus the exact reviewed tracked-file diff and explicitly approved new source/test files into an empty disposable directory; enumerate/hash that candidate source list. Do not use the live working directory, copy `.venv`, or silently omit new untracked implementation files. Once committed by an authorized human, repeat/associate validation with that exact SHA. Never commit merely to obtain a clean checkout.

Use no old `dist/`, generated model/resource directories, pip/PyInstaller caches, or existing venv. Provision new cache/profile directories explicitly; keep test profile/config/log/model/resource paths under the disposable root. Remove developer `PYTHONPATH`, model-path, KRDICT and Qt overrides. The existing test autouse fixture isolates Hanly paths but does not universally sandbox `HOME`/`APPDATA` or every native child cache; strengthen test subprocess isolation where this wave exercises those boundaries. The packaged smoke's `IsolatedProfile` already redirects home/profile/models and uses a separate cwd; reuse it.

For each environment install latest compatible pip first (required for `--group`), then the commands the lane declares. A packaging environment must execute:

```text
python -m pip install --upgrade pip
python -m pip install --group dev -c packaging/release-constraints.txt
# Linux: install CPU torch/torchvision from the CPU wheel index before runtime extra.
python -m pip install --editable packages/hanly
python -m pip install --editable "packages/hanly-app[runtime]" -c packaging/release-constraints.txt
python -m pip install "pyinstaller>=6,<7" pyinstaller-hooks-contrib -c packaging/release-constraints.txt
python -m pip check
python -m pytest
python -m ruff check packages packaging tests tools benchmarks
python -m mypy packages packaging tests tools benchmarks
python tools/release_version.py --tag v<actual-candidate-version>
python tools/prepare_easyocr_models.py
python tools/build_package.py --platform <native-platform>
```

Placeholders here are run-specific identities, not unresolved implementation choices. Do not pass another OS to `--platform` and call that a cross-build. `build_package.py`'s option names an output layout; the host interpreter/native libraries still determine the binary. Add a host/target mismatch rejection during HAN-42 if retaining this option.

`prepare_easyocr_models.py` is the explicit CI model-provisioning path; KRDICT for smoke comes from `tools/build_smoke_krdict.py`, never a developer's generated DB. Do not introduce developer-only dependencies that merely happen to satisfy tests locally. Capture `pip freeze`, `pip check`, native interpreter architecture and tool versions.

Build both Python distributions with `python -m build packages/hanly` and `python -m build packages/hanly-app` into the disposable workspace. In separate clean venvs install the local engine wheel alone (base imports without desktop dependencies), then app wheel with engine wheel available; install concrete/runtime extras using a local wheel find-links directory so pins resolve to the candidate rather than an unrelated index version. Test imports and `importlib.metadata` versions, exact engine pins, and wheel contents. Packaging-installed weights must not accidentally become ordinary wheel package data. Engine independence remains a gate.

### 5.2 Configuration and workflow review — concrete contract

Review all three `pyproject.toml` files, `packaging/release-constraints.txt`, the spec, runtime hook/entry point, `tools/build_package.py`, `tools/prepare_easyocr_models.py`, `tools/release_version.py`, `tools/tagged_metadata.py`, `tools/release_build.py`, and every `.github/workflows/*.yml`/`*.yaml` (currently `ci.yml`, `build.yml`, `release.yml`). Parse TOML/YAML with compatible tooling; syntax parsing alone does not validate Actions expressions/job semantics. Existing `tests/test_ci_workflows.py` must cover the new gates; supplement with an Actions-aware validator such as actionlint in a declared tooling lane, not an undeclared local binary requirement.

| Current lane | Required final validation |
|---|---|
| CI quality | Ubuntu Python 3.10/3.11/3.12/3.13, Node 22, base editable packages + dev group; all three project checks. Verify every claimed version, including additions that might accidentally import `tomllib` on 3.10. |
| CI Windows | Python 3.10, Node 22, base packages, pytest; native helper tests must run, not skip for a missing optional shell dependency. |
| Build native matrix | Windows/macOS/Linux, Python 3.10, Node 22, constrained full runtime and PyInstaller, tests/lint/types before build, models explicitly prepared. Declare/assert architecture. Hosted `-latest` labels can move: [runner image inventory](https://github.com/actions/runner-images) currently maps standard macOS to arm64; assert actual build facts instead of relying on the label name. |
| Linux desktop prerequisites | Existing apt list is `libegl1 libxcb-cursor0 xvfb`. Run UI/source integration that needs a display under `xvfb-run -a`; verify xcb/X11/xauth/font/runtime dependencies on the clean image and add only missing ones. Current pre-build pytest may skip display tests, while the later UI smoke is nonblocking: fix that gap. |
| macOS | Native frameworks/dependencies from full runtime, strict PyInstaller signing-error setting; ditto ZIP and DMG reconstruction, real `.app` version/signature/runtime/UI/update checks. Current ad-hoc distribution remains intentional, not notarization proof. |
| Windows | Native loader dependencies, CPU runtime selection, GUI/PowerShell handoff from a console-less process, whitespace/non-ASCII paths and running-file locks. Never infer Python 3.10 success from this investigation's 3.13 artifact. |
| Required smoke | Remove non-Windows `continue-on-error` for Control Center; run packaged/update tests after artifacts exist. Set `HANLY_PACKAGED_APP` explicitly. Missing bundle/executable, old self-check mode, missing display or skipped required test fails the native gate. |
| Job/artifact semantics | `fail-fast: false` preserves evidence but does not excuse failed matrix members. Enforce all four application archives and required JSON reports explicitly; `upload-artifact if-no-files-found:error` only checks that some matching files exist. A successful build must mean all required native checks passed. |

Do not change Python support, default engine, dependency boundaries, or artifact architecture silently to make CI green. Repository-installed environment review protection (`hanly-release` required reviewers) must be checked in GitHub settings; YAML naming an environment does not prove required reviewers are configured.

### 5.3 Fresh frozen products

For each native platform reconstruct **the actual release archive** into an empty location and smoke that result, not only `dist/<platform>`:

```text
python tools/build_smoke_krdict.py <isolated-root>/krdict.sqlite3
python tools/smoke_packaged_runtime.py <reconstructed-app> --inventory-only
python tools/smoke_packaged_runtime.py <reconstructed-app> \
  --image tests/hanly_fixtures/assets/korean_reading_roi.png \
  --krdict <isolated-root>/krdict.sqlite3
python tools/smoke_packaged_runtime.py <reconstructed-app> --window-only
```

On Linux prefix the window command and display-dependent integration tests with `xvfb-run -a`. Current `--from-archive` smoke reconstruction is macOS-specific; extend it minimally for Windows ZIP/Linux tar using the corrected application extractor, or have the native workflow reconstruct explicitly before supplying the path. Do not route Linux through the unchanged resource extractor.

macOS additionally uses existing `--from-archive ... --reconstruct-into ... --disk-image ...` to exercise both products; assert read-only DMG detach on success/failure. Run `codesign --verify --deep --strict --verbose=2` on reconstructed and final updated `.app` (see [Apple's verification guidance](https://developer.apple.com/library/archive/technotes/tn2206/)). Verify identity/version and internal links; do not re-sign a damaged downloaded bundle to conceal a packaging error. Ad-hoc verification is not Developer ID trust/notarization.

Run HAN-42 old/new frozen update with the final pruned/performance-adjusted candidate, including rollback and cleanup. Run the small controlled normal-desktop path too: real hotkey/hover capture → popup, pause/manual lookup, hide/restore/tray, quit, and config/resource survival. Worker/UI self-checks separately are necessary but do not prove this integration. Record platform/hardware limitations and required CI/manual outcomes; Windows-host inspection cannot be labeled macOS/Linux testing.

### 5.4 Release contract and final publication gate

The intended unchanged public assets are exactly:

```text
hanly-desktop-windows.zip
hanly-desktop-macos.zip
hanly-desktop-macos.dmg
hanly-desktop-linux.tar.gz
krdict-<resource-version>.sqlite3.zst
hanly-resources.json
SHA256SUMS
```

Four application archives, one resource payload, one resource manifest, one checksum file. `SHA256SUMS` covers the other six; resource manifest has its own compressed size/checksum/schema/count/version contract. Embedded app build identity adds no eighth release asset. Keep updater selection and both release-stage/finalize asset lists synchronized.

Current `release.yml` uses trusted default-branch tooling, resolves exact tag/build identity, checks tagged app/engine metadata/pins, stages a draft, optionally carries the previous resource, waits at `hanly-release`, re-resolves, validates the resource pair, generates sums, uploads and verifies seven asset names, then publishes. Preserve that structure. `tools/release_build.py` and `tools/tagged_metadata.py` are already the useful seams; do not replace this with a release manager framework.

Require final evidence that all selected build jobs and required smoke reports passed for that exact SHA/architecture; not merely workflow conclusion with nonblocking failures. Validate missing/duplicate/misnamed artifacts, mismatched tag/package/embedded versions, tampered bytes, changed resource bytes under an unchanged resource version, and incorrect draft identity. Keep `validate_only` genuinely write-free. Note that finalize's dry run still waits on the environment because the job declares it.

Before publication compare/re-download **all candidate draft asset bytes** against expected hashes, not only `SHA256SUMS` (the current workflow only explicitly re-downloads and compares that file after upload). Preserve HTTPS download/integrity model; checksum availability from the same release is integrity validation, not independent publisher authentication. Do not redesign signing in this wave.

Where authorized and an existing draft exists, exercise `validate_only` against it. Creating/editing a draft or publishing is outside this planning run and requires execution authorization. A local reproduction of release validation must use the same scripts and fixture artifacts, record any GitHub-only checks pending, and never claim it proved hosted permissions/environment protection.

**Wave completion requires all of:** reviewed source; ordinary gates on claimed Python versions; fresh dependency/extras/wheel install; clean packaging; reviewed workflow semantics; required native frozen/UI/update evidence; measured size/performance results; coherent seven-asset release contract; no unresolved blocking regression. Local pytest alone cannot complete this wave. Finish with the review handoff and human release decision, not an automatic commit/push/publish.

## 6. Deferred findings and explicit non-goals

| Finding / idea | Disposition and revisit trigger |
|---|---|
| Exact original macOS `.cmd` / `*-spec` provenance | Unresolved incident attribution; collect original-machine build/path/helper evidence during HAN-42 native validation. Current source does not produce that filename/platform combination. Reliability and cleanup acceptance are not deferred. |
| Developer ID, notarization, signed update metadata | Out of wave. Preserve ad-hoc distribution and HTTPS/checksums; revisit with a deliberate distribution/trust project. |
| Universal/Intel macOS or additional Windows/Linux architectures | No new supported architectures. Make current artifacts explicit and reject mismatches; revisit when a second architecture is intentionally published. |
| ONNX/custom OCR, replacing Qt/WebEngine/Torch/Kiwi, custom OpenCV build | Deferred until safe collection cleanup leaves a documented unmet size/performance target and a separate product decision justifies maintenance cost. |
| Model unloading, lazy WebEngine rebuild, generic power/runtime modes | No evidence justifies their complexity. Revisit only if settled memory/compute profiling shows a concrete budget failure that cannot be solved locally. |
| Changing morphology/resolver/dictionary semantics to improve performance | Historical cost is negligible relative to OCR/dwell. Only revisit with current traces showing a real bottleneck or a separately scoped correctness issue. |
| OCR tuning previously rejected in the roadmap | Do not repeat without new corpus/model evidence. Recognition-inclusive warm-up is distinct from replacing full detection with recognize-only lookup. |
| Reported `torch: not installed` in existing frozen smoke | Metadata absence, not proof Torch failed to load: OCR smoke ran. Add accurate build/runtime identity reporting where used by this wave; do not infer missing inference code or add recursive distribution metadata collection. |
| Arbitrary cleanup of old user-created Hanly copies | Never scan/delete by product name. Clean only transaction-owned paths; any unrelated historical duplicate needs a human-directed cleanup. |
| Live GitHub settings and unavailable native hardware | Explicit final gate evidence still required. “CI-only” is a validation assignment, not a pass. |
