# Mac final verification of `lab/app-health` (2026-10-05)

Final macOS pass after the Windows implementation and its Phase B corrections.
Verdict and open items: the Windows Review Handoff's
[Mac verification outcome](../review-handoffs/lab-windows-implementation-and-stress.md#mac-verification-outcome-2026-10-05).

- Host: macOS 26 (Darwin 25.6.0), Apple Silicon (arm64), `.venv` CPython 3.13.11.
- Branch `lab/app-health`; recorded head `352e4ee` verified live (clean tree).
  Base for review: `main` at `9e44e38`. Shipped code last changed at `16dde15`;
  the build below is from `352e4ee`, whose `packages/`, `packaging/` and `tools/`
  equal `16dde15`'s.
- Agent: Claude Code (Opus 5.5).

## 1. Shared-code review for Mac regressions

Shipped diff `bd7527b..352e4ee` (the last Mac build to HEAD): nine files, all
under `updates/` plus one Control Center failure line. Findings by area:

| Area | Mac effect | Conclusion |
|---|---|---|
| `deb72a6` `_remove_challenge` | runs only for journals in `<install>/.hanly-update`; a Mac (POSIX tree) transaction lives in a sibling `.hanly-update-*` directory and is settled by `settle_native_update` | no Mac path reaches it; no regression (see the remnant finding below) |
| `12b052c` case folding | `require_tree_path` folds on macOS; `require_safe_relative_path` folds everywhere | refuses strictly more; the real Mac 1.0.0 and HEAD manifests (7,342 entries) still validate and stage |
| `e8f51e0` `require_installable_path` | admits only `.hanly-manifest.json`; Mac manifests may not carry it (`_require_control_entries`) | unchanged on Mac |
| `e8f51e0` `abandon` → `_remove_if_empty` | `Hanly.app/.hanly-update` never exists on Mac; a missing path is a no-op | no effect |
| `16dde15` `_unreachable` | receipt-less confirmation (every Mac manual install) | network failures now retryable; 404/410 and integrity failures still "cannot confirm"; exercised for real below |
| `0046cbc` helper process / waits | Windows PowerShell only; POSIX `_hand_off` unchanged | none |
| `938fa6c` win32 guards | `sys.platform == "win32"` branches only | none |
| `7b61f19` failure line | platform-independent JS | none |

Lab changes: `24ac332` (out-of-process sampler) reviewed and exercised (defect
below). `7704dc8` is consistent with the app: `NOT_KOREAN` is final on every
platform (`hover/lookup.py`), and the driver applies it only to events bound to
its own hover id. `352e4ee`/`762c1c4`/`38d9203` are Windows/Edge/replay paths;
the portable suite covers their imports.

No manifest/hash trust, path containment, recovery data, ordinary non-success,
three-process, UI-thread or request-currency code changed in this range.

## 2. Defects found and fixed

| Commit | Defect | Evidence |
|---|---|---|
| `1fcd2c3` (lab) | A terminal Ctrl+C reaches the whole foreground group: the out-of-process sampler (since `24ac332`) died with a `KeyboardInterrupt` traceback, and `metadata.json` recorded `process_samples: 0` beside 87 recorded samples | Real group SIGINT on `python -m lab --duration 120` after 25 s: before, run `20261005-030754-run` 0 vs 87 + traceback; after, `20261005-030907-run` 89 = 89, no traceback; both exit 130 with report and no survivors. New regression `test_the_sampler_outlives_a_terminal_interrupt` failed before, passes after |

No shipped-code defect was found, so no shipped code changed and the build
below remains current.

## 3. Gates

| Gate | Result |
|---|---|
| `pytest --suite portable` | 2,519 passed, 2 skipped, exit 0 (at `352e4ee`) |
| `pytest --suite native` | 125 passed, 0 skipped, exit 0 (at `352e4ee`, screen unlocked) — includes `macos/test_control_center_identity.py`, both `test_update_stage_animation.py` cases (normal and reduced motion), 3 lifecycle, 1 startup and all 25 `test_update_posix_native.py` cases |
| `pytest lab/tests` | 345 passed (after `1fcd2c3`) |
| `ruff check packages packaging tests tools lab` | clean (after `1fcd2c3`) |
| `mypy packages packaging tests tools lab` | clean, 340 files (after `1fcd2c3`) |
| `lab check run` UPDATE-APPLY-POSIX, UPDATE-COORDINATOR, RESOURCE-DELIVERY | 3/3 passed (`69e48bcb`) |

## 4. Fresh build and packaged acceptance

- Build from clean `352e4eef06cedc6c7b19a879527b7f7cff5e5b11`:
  `tools/build_package.py --platform macos --source-commit <sha>
  --base-package Hanly-v0.9.0.hup --base-checksums SHA256SUMS` (the published
  v0.9.0 pair, verified against its `SHA256SUMS`). Build id
  `f0c50a0b-03d5-4d1d-97dc-d6b1d805397d`, 1.0.0 arm64. It also produced a real
  `from-0.9.0-to-1.0.0` Mac delta (161,794,094 bytes).
- Products: ZIP sha256 `40cda36d…bc096862` (555,057,582 bytes), DMG
  `aa8d1441…7f40fea` (632,376,525 bytes). The `bd7527b` products were moved,
  not deleted, to `dist/archive-bd7527b/`.
- ZIP reconstruction `dist/reconstructed-352e4ee/` and DMG copy-out
  `dist/reconstructed-dmg-352e4ee/`: each matches all **7,342** manifest
  entries; `codesign --verify --deep --strict` passes on the build and on both.
  `--disk-image` check: the DMG opens onto exactly `Hanly.app`.
- `pytest --suite packaged` with `HANLY_EXPECTED_SOURCE_COMMIT=<full sha>` and
  `HANLY_REQUIRE_PACKAGED=1`, on the build and both reconstructions: **4 passed,
  1 skipped** each (identity/commit, inventory, worker, window passed). The skip
  is `macos/test_frozen_identity.py`: "Accessibility could not close the Control
  Center … window 1 … invalid index (-1719)". The session was locked
  (`CGSSessionScreenIsLocked = True` since about 04:14, after idle sleep). This is a
  host restriction, not a pass and not a product defect. `HANLY_REQUIRE_PACKAGED`
  does not cover this native-capability skip. Superseded: with
  `HANLY_REQUIRE_NATIVE=1` on an unlocked session it passed on both copies (§6).
- `lab check` BUNDLE-IDENTITY, BUNDLE-WINDOW, BUNDLE-WORKER with the SHA
  required: 3/3 on each reconstruction (`6e048e61`, `6c9c0138`). No `lab` or
  `tests` package inside the bundle.

## 5. Real isolated Mac application update

**Arrangement (state this exactly):** *this checkout's updater* — `TreeUpdateRunner`
and `UpdateCoordinator` composed as `application._tree_runner` composes them,
hosted in a short-lived shell-role process that exits after the helper's claim,
as a quitting shell does — acting on an **isolated copy of the published 0.9.0
Mac app** (`e75ef4b`, build `6856912b`, downloaded and verified against its
`SHA256SUMS`). The **target** is the fresh `352e4ee` build above (`f0c50a0b`), served
with its real delta and a `.hup` assembled by `tools/update_artifacts.py package`
from a **local release directory** through an injected downloader. Assets whose
URLs are public go through the production `GitHubReleaseFetcher`. The receipt-less
0.9.0 installation is confirmed against the **real public v0.9.0 release** (read
only). The **real C helper** (`hanly-update-posix`) swaps the tree and relaunches
with `open -n`; the **HEAD build** answers its challenge, and its own startup
settles the transaction on the next launch.

This is not the updater embedded in 0.9.0, and not a release published from
this branch. Driver: a scratchpad script (not committed); evidence under the
gitignored `artifacts/lab/runs/20261005-mac-update/`.

**Isolation:** installation, `LOCALAPPDATA` profile, `HOME`, `TMPDIR` and the
DevTools port all sit inside the run directory. A compiled probe bundle showed
that `open -n` on this host forwards the caller's environment
(`LOCALAPPDATA`, `HOME`, `TMPDIR`), so the relaunched build stayed in the run
profile. Afterwards no file under `~/.config/hanly` or `/Applications/Hanly.app` was
newer than the session start. Only processes whose executable lies inside the
run's installation were ever signalled.

| Run | Mode | Outcome |
|---|---|---|
| `install-1` | install | harness fault: my local downloader also served the *tagged* v0.9.0 `SHA256SUMS` from the local directory, so confirmation found no 0.9.0 digest; the product refused correctly ("cannot confirm … install by hand") and changed nothing |
| `install-2` | install | harness fault: the shell-role process's stdout was a pipe the detached helper inherited, so the driver never reaped it; the zombie still answers `kill(pid, 0)`. The helper waited its 120 s and wrote `abandoned — Hanly did not close, so nothing was changed`. Base intact; the next launch removed the staging directory and pending pointer — a real abandon path |
| `install-3` | install | helper `committed — the new version started` 17 s after quit. Every check held, but the driver's predicate expected JSON quotes, so it said FAILED; superseded by install-4 |
| **`install-4`** | install | **passed (driver verdict)**: staged 87.8 s (delta), helper committed, relaunched build is `f0c50a0b`/`352e4ee`, its page offers no update, the tree matches all 7,342 target entries, `codesign` passes, the next launch settles (pending pointer cleared, no `.hanly-update-*`), this checkout's re-check says current, no owned process remains |
| **`cancel-1`** | cancel | **passed**: cancelled during `inspecting`; "The update was stopped. Nothing was changed."; base identical; nothing in the store, install parent, recovery or TEMP |
| **`rollback-1`** | rollback | **passed**: after the claim, the staged candidate's executable was replaced with non-program bytes; the helper waited **602.9 s** (the full `READY_WAIT_SECONDS`), restored 0.9.0 exactly (`codesign` passes) and relaunched it; this checkout re-offers 1.0.0 |

The host went into idle sleep during install-4 (`time.monotonic` pauses, so the
wall-clock length is not a measurement). `caffeinate` was used from then on.

What these runs exercise from the branch on Mac: `12b052c` (case-folded
reserved names, applied to real Mac manifests), the `16dde15` confirmation path
(reachable server, published build confirmed by hash), staging, hand-off and
claim, the real C helper's swap/acknowledge/rollback, and the HEAD build's
settling. They do **not** exercise `deb72a6` on Mac: no Mac transaction reaches
that code.

### Findings from the real update (not regressions)

- **Challenge files remain after every Mac update.** After a committed update the
  store keeps `challenge-<id>.json` and `challenge-<id>.ack`; after a rollback it
  keeps `challenge-<id>.json` and `installed-receipt.pending.json`. The C helper
  removes only a stale acknowledgement before launch (`hanly-update-posix.c`), and
  `settle_native_update` removes the staging directory and pointer, not the
  challenge. One ~0.5 KB file pair per update in the per-user store; no
  integrity or ownership effect. Unchanged since the POSIX updater was introduced
  (Windows got the equivalent cleanup in `e8f51e0`/`deb72a6`). **Deferred**;
  revisit with the next POSIX helper or settling change, applying the same
  receipt-directory ownership guard as `deb72a6`.
- **Crashing new build waits the full deadline** (already deferred in Phase B):
  confirmed on real releases, 602.9 s.
- **A zombie parent counts as alive** (`installation_is_free` uses
  `kill(parent, 0)`). This was reached only through the harness. A frozen shell is reaped
  by launchd, and a terminal-started `hanly` by its shell. Recorded, not
  changed; revisit if a supported launcher ever keeps Hanly's output pipe open.

## 6. Lab on Mac

| Flow | Result |
|---|---|
| `python -m lab --duration 120`, real group Ctrl+C at 25 s (before/after `1fcd2c3`) | exit 130, report and summary, no survivors (sampler, resource tracker, both spawned children, WebEngine helper all gone); sample count correct after the fix |
| External sampler lifecycle | separate `lab.session.sampler` process in the session's group; stops on input close or shell exit; ignores SIGINT after `1fcd2c3`; no orphan in either run |
| Standard Vision tour `20261005-053512-tour` (post-`24ac332` baseline) | 446/453 (98.5 %), 0 not scored; popup median 150 ms; uncached medians: capture 28.6 ms, OCR 29.5 ms; lookup peak 510 MiB, shell 217 MiB (includes the lab recorder) |
| Standard Vision tour `20261005-053840-tour --baseline` the above | 446/453, 453 matched, 0 changed verdicts; popup median 142.8 → 141.3 ms; lookup peak 548 MiB, shell 219 MiB |
| Quick tour `20261005-054216-tour` | 23/24, finished |
| Quick tour interrupted by real pointer moves `20261005-054246-tour` | `stopped_by_user after 20 of 24 planned`, exit 0, partial report marked not comparable, no survivors |
| `report --list`, rebuild, newest, `--baseline` | exit 0; baseline files byte-identical afterwards |
| Packaged `test_frozen_identity.py` (both copies), `BUNDLE-LAUNCH-IDENTITY` (both) | passed, SHA and native capability required |

Tours: built-in Retina 2408×1506, one display, Vision, seed 7, default dwell,
clean `6c3cf75`. These are lab-hosted measurements; the only comparable
baseline is the first of the two runs, because earlier Mac tours used the
in-shell sampler.

Privacy and scoring guarantees were not changed by any commit in this pass.
