# App health lab — Mac implementation evidence

## Scope and result

The first implementation boundary adds developer-only whole-app scenarios and
two evidenced desktop corrections. It does not complete the Windows lab or
claim a full release-update acceptance. Phase B review has not started.

The lab reuses fixed repository tests rather than creating a second app
composition. Each scenario owns a temporary child profile, reads bounded raw
output in memory, records safe typed observations and cleans up owned children.
Coverage distinguishes `passed`, `failed`, `unavailable` and `not_run`.
Developer `psutil` supplies process observation; declared runtime extras and
public engine contracts are unchanged.

## Reported cases

| Case | Evidence and outcome |
|---|---|
| `UI-UPD-03` | Reproduced in the real Chromium page with controlled update snapshots. The busy panel rebuilt every 500 ms, recreating the label and restarting entry motion; its second animation was also infinite. Corrected by retaining the busy view during progress updates and replacing only a changed label. |
| `MAC-START-04` | Source-run sampling observed the Control Center child as Foreground, then UIElement. Corrected the earlier Qt transformation, not the existing Accessory policy or shell lifecycle. |
| `WIN-UPD-01` | Not investigated on macOS. The actual Windows download → install loop remains a Windows-phase task. |
| `WIN-UPD-02` | Not investigated on macOS. The empty directory's transaction/helper ownership and first failing stage remain unresolved. |

These are local case labels from the approved plan, not claims about Linear
issue identifiers or status.

## Stage animation: before and after

The probe drives the shipped page through inspecting at 10/20/30%, then
downloading at 40%, waiting through multiple real refreshes at each step. Only
the updater snapshot is scripted; rendering and animation events are real.

- Before production changes, both native regression cases failed because the
  label was not retained. The first 10% observation already held four entry
  starts and four shimmer starts. Computed iterations were `1, infinite`.
- After: the same three inspecting observations retain the label and have one
  animation start in total. Changing to downloading creates exactly one more.
  Progress remains 10/20/30/40%, and returning to idle exits the busy mode.
- Normal motion is 240 ms, not a repeating effect. The Chromium reduced-motion
  flag is checked with `matchMedia`; computed duration is at most 1 ms, with a
  single iteration. Both real-page cases pass.

No updater download, installation or server action is inferred from this UI
test. Its profile is disposable; no everyday app state is modified.

## Mac identity: why the settled test missed the flash

Run `926f2121-a857-4a79-96b8-468166dc3437` sampled child PID 69128:

| Elapsed from scenario start | Owned process observation |
|---|---|
| 317.0 ms | Spawned Python child, not yet registered in the sampled listing |
| 606.8 ms | Foreground application |
| 748.9 ms | UIElement application |

The existing native case only inspected the settled child, so it passed despite
this roughly 142 ms observed interval. The lab's identity scenario now refuses
an observed Foreground event rather than discarding it as already corrected.
A repeat baseline run missed the short interval; sampling is not exhaustive.

Qt's Cocoa integration transforms a plain executable during `QApplication`
creation unless `QT_MAC_DISABLE_FOREGROUND_APPLICATION_TRANSFORM` is set. The
host previously applied Accessory policy only after that creation. The opt-out
is now set inside the window host before Qt constructs the application, only
on macOS; the shell does not execute this host path. The existing policy and
explicit activation remain. [Qt 6.11 Cocoa integration source](https://github.com/qt/qtbase/blob/v6.11.0/src/plugins/platforms/cocoa/qcocoaintegration.mm).

The deterministic initialization-order test fails on the old macOS code and
passes on the correction; Windows/Linux assert no environment mutation.
Post-fix source run `40bcdf1f-85d1-4315-8125-4702d7f57cbf` passes startup,
identity and reopen checks. Absence of a sampled flash is not proof against a
shorter event; the causal order regression covers that gap.

## Scenario evidence

| Run | Checks and verified case counts |
|---|---|
| `926f2121-a857-4a79-96b8-468166dc3437` | Startup 1; settled identity 1; coordinator 26; POSIX update helper 25; resource delivery 58. This prototype run recorded the transient identity but predated its stricter verdict. |
| `70e3c2cf-d757-4c0d-a510-d154d9bcaa80` | Stage UI 2; window lifecycle 1; controls/layout 3; capture choice 2; hover/popup 21; settings 113. |
| `40bcdf1f-85d1-4315-8125-4702d7f57cbf` | Corrected source startup 1; identity 1; lifecycle 1. No tracked children required forced cleanup. |
| `18741011-62db-408d-bb7c-e2d7c0ec16a5` | Fresh frozen inventory/source identity 2; actual window 1; actual worker/committed Korean fixture 1. |
| `7150ca99-aafb-48ea-8b9d-0fc213e65d8a` | ZIP reconstruction: inventory/source identity 2; window 1; worker 1. |
| `768f7e98-65fb-4b05-8341-1efc53ac2aa1` | DMG reconstruction: inventory/source identity 2; window 1; worker 1. |
| `b64386da-9c0c-4ce8-b9e5-aac2ccb84c43` | Final observer: source startup 1; identity 1; stage UI 2; POSIX helper 25. No tracked children required forced cleanup. |

Private run directories are under gitignored
`artifacts/benchmarks/runs/<run-id>/`. Their HTML includes typed coverage,
duration, sampled RSS and owned PID/role/activation timelines; no screenshot,
OCR transcript, absolute user path or arbitrary child output is persisted.
The final privacy screen inspected all 32 typed artifacts in eight lab runs:
only the four declared filenames appeared, every root was gitignored, and no
Hangul, user/private path, OCR-text or private-evidence markers were present.
Implementation diffs include no run artifacts or generated build binaries.

The POSIX helper executes against simulated build trees with real filesystem
apply/acknowledgement/rollback. It is not a real old-release → new-release update.
Control Center controls use real UI with injected bridges. Hover/popup scenarios
use simulated input/lookup results; `LIVE-HOVER` remains human-operated.

## Gates and frozen build

- Final portable gate: **2391 passed, 2 skipped**. Earlier convergence found
  one introduced CLI-order regression; preserving `dev-hud` first fixed it.
- Full macOS native gate: **125 passed**. The subsequently strengthened motion
  duration assertions also passed **2/2**.
- Ruff clean; mypy clean on **312 source files**. Python 3.10 syntax parsing
  passed for all six added lab/native modules; no actual 3.10 runtime was run.
- Fresh macOS build produced ZIP, DMG and manifests. It started from clean
  commit `e15204df2d14aa0ecefc6ec5a7d9a8b93ab69efc`, version 1.0.0, arm64.
  Later changes only strengthen developer tests/observation or document evidence; they do
  not alter the shipped code/assets of that build.
- Built app: `codesign --verify --deep --strict` passed. The lab's frozen
  identity, window and worker checks all passed with that full SHA required.
- ZIP and DMG were independently reconstructed into owned temporary directories.
  Both matched all **7,342 release-manifest entries**, passed signature
  verification and passed all **four packaged cases**, with the exact original
  build SHA required. Temporary reconstructions were removed after inspection.

## Local commit provenance

The human authorized correcting two unpublished messages after implementation:
literal `\\n` separators became actual bullet lines in the first feature commit,
and the motion-test subject changed from `test:` to `chore:`. No code or author
changed, and all eight implementation commits remain separate. The complete
implementation tree stayed `7fea412a377482e453d0fe4ae60ebc8381dcf96b`.

| Original local commit | Message-corrected commit | Boundary |
|---|---|---|
| `ee2e371` | `4c7c429` | Scenario catalog, isolated runner and contracts |
| `994c7d8` | `4131a3f` | Activation-observer typing |
| `6dce7b9` | `286586a` | Stable updater stage motion |
| `5923c50` | `96c1335` | Source Control Center identity |
| `2099ac2` | `6b09a2e` | Safe visual timing/process report |
| `e15204d` | `20af3eb` | Honest observation availability |
| `dc2c071` | `00e03b4` | Real rendered motion durations |
| `3485433` | `432b466` | Process birth-identity ownership |

The built artifact retains its original `e15204d` stamp; it was not relabeled.
That commit and `20af3eb753a3a85e84a2a278aea607e7431b6ffe` have the identical
tree `6c45c863ffc1a0a5eedc92a2745009439f4dfbeb`. Persisted run metadata likewise
keeps the original SHA and actual dirty state rather than being rewritten.

## Measurement and packaging limits

The RSS measure is the sampled sum of pytest and its observed descendants,
not private application memory, a precise peak, or a normal-hover benchmark.
The frozen worker scenario reached about 1.13 GiB for that combined tree;
this is not a claim that the preferred Vision desktop consumes that amount.

The nominal 100 ms sample interval has process-inspection overhead and can miss
short-lived children. Role labels are inferred from fixed command markers;
`spawned_python` does not separately identify lookup and Control Center.
Unobserved identity, inspection denial, unfinished output and forced child
cleanup cannot produce a passed scenario.

PyInstaller transitively collected `psutil` through the existing dependency
graph; no `benchmarks.dev` modules were found in the analysis. Declaring psutil
only in developer extras does not guarantee absence from frozen artifacts.
No unrelated packaging exclusion or dependency-pruning change was attempted.
Revisit this distinction in the separately authorized packaging review.

The full normal frozen launch is not an end-to-end user interaction campaign:
the frozen checks separately exercise window and worker self-check modes.
In both reconstructed builds, the standalone frozen UI-check process was
sampled as Foreground before UIElement. This is **not** a passing proof of
frozen child identity: `BUNDLE-WINDOW` gates rendering/bridge/exit, whereas
`MAC-IDENTITY` gates the source-spawned child. A normal frozen shell → window
child launch still needs its own identity observation to distinguish initial
bundle registration from a second Dock entry. No speculative bundle-policy
change was made; this remains a review/acceptance target.
Live hover, mixed-DPI/multiple displays, real release update delivery and all
Windows behavior remain outside this Mac foundation's acceptance claim.
