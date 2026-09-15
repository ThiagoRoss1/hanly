# Cross-platform updater — Codex resumption and review report

Date: 2026-09-15. Reviewer/resumer: Codex. Host: macOS arm64, Python 3.13.

This report is intentionally separate from Claude's
[`updater-cross-platform-execution-2026-09-15.md`](updater-cross-platform-execution-2026-09-15.md)
and its
[`Review Handoff`](../review-handoffs/updater-cross-platform-2026-09-15.md).
It records only what Codex inspected, changed, and validated after Claude's
last commit. Claude's report and handoff were not rewritten.

## Starting point

- Branch: `codex/updater-cross-platform`
- Base: `main` / `origin/main` at `70f71b3aca3ab39835fa7700680ada57bab19dbe`
- Starting HEAD: `58efb5041c7935b23ee37920c4ad1525891e931d`
- Worktree at resumption: clean
- Diff inherited from Claude: 48 files, 14,288 insertions, 395 deletions
- Scope used for review: `main...58efb50`, the current cross-platform plan,
  Claude's execution report and handoff, the superseded differential report
  and handoff, and the updater-critical runtime, artifact, native-helper, test,
  packaging, and workflow files.

The inherited branch contained these commits; Codex did not author or amend
them:

| Commit | Subject |
|---|---|
| `82f3dd3` | `chore: add the cross-platform updater plan and its execution report` |
| `fcba4c5` | `feat: add the cross-platform update wire contract` |
| `47d67e9` | `feat: add one preparation and planning core for every platform` |
| `c10f6c0` | `feat: build and prove a whole new installation on macOS and Linux` |
| `bbc60ef` | `chore: record phases 1-3 in the execution report` |
| `f4b1f9f` | `feat: apply a POSIX update with a native helper that outlives Hanly` |
| `b4c0022` | `feat: produce and validate the cross-platform release contract` |
| `8f62d7a` | `feat: build and publish the cross-platform release contract` |
| `7b3f305` | `fix: stop a packaging test stub writing a file named after a flag` |
| `e97118a` | `docs: describe the cross-platform updater as implemented` |
| `8c7e2ee` | `test: ask the build stamp question of a package, not of this checkout` |
| `971b66f` | `fix: write an update acknowledgement as exact bytes` |
| `cb2d437` | `fix: keep an installation's receipt when an update staged nothing` |
| `0b875df` | `fix: let a POSIX update commit while the build it started keeps running` |
| `33048ba` | `docs: record the real macOS release pair and what it exposed` |
| `58efb50` | `chore: close the execution report at the final gate` |

## Changes made by Codex

No commit, push, merge, tag, release, or workflow dispatch was made.

### 1. Do not start recovery while the original POSIX helper is live

Files changed:

- `packages/hanly-app/src/hanly_app/app_update_handoff.py`
- `packages/hanly-app/src/hanly_app/app_update_runner.py`
- `tests/test_app_update_hup.py`

The candidate launched by the native helper enters normal application startup
before writing its update acknowledgement. During that interval,
`settle_native_update` saw an unsettled transaction and unconditionally started
a recovery helper. The existing advisory lock prevented the second helper from
mutating anything, but the launch was unnecessary and startup incorrectly
reported an interrupted update.

Codex added `native_helper_is_running`, which observes the same advisory lock
used for handoff ownership. `_recover_native` now leaves a live owner alone and
reports that the update is being applied. The regression stages a real POSIX
transaction, records it as pending, simulates the live lock owner, and proves
that no recovery process is started and no transaction data is removed.

### 2. Keep an exactly acknowledged candidate after an interrupted result write

Files changed:

- `packaging/updater/hanly-update-posix.c`
- `tests/native/shared/test_update_posix_native.py`

The native helper previously treated `installed + backup + no result` as an
uncommitted update and always rolled it back. That state also occurs if the
candidate wrote the exact transaction-bound acknowledgement and the helper
then died before its committed result became durable. Rolling back in that
case converts a bookkeeping failure into a product rollback, contrary to the
plan's recovery decision table.

Recovery now retains the installed tree only when both independent checks
hold: its device/inode are the staged candidate's recorded identity, and its
acknowledgement matches the descriptor byte for byte. It rewrites the committed
result and leaves the old tree available for normal later cleanup. Missing,
stale, or wrong acknowledgements still take the existing rollback path.

The native regression recreates the exact post-ack/pre-result filesystem state
with real renames and the compiled helper, then proves recovery reports
`committed`, keeps the target installed, and retains the previous tree.

### 3. This report

This file is the user-requested provenance boundary between the inherited
Claude implementation and Codex's follow-up. It is the only updater report
Codex added.

## Review outcome

### Fixed now

1. A candidate startup launched a redundant recovery helper while the original
   native helper still owned the transaction.
2. Recovery rolled back a proven, exactly acknowledged candidate when the
   durable result record was missing.

### Deferred consideration

`move_directory` attempts to flush both affected parent directories but ignores
the return values. Changing that is not a one-line error check: once `rename`
has succeeded, reporting the move as though it did not happen sends callers
down the wrong recovery branch. Revisit this before a production updater
release with injected directory-`fsync` failures and define the post-rename
state transition explicitly. The current supported local filesystems normally
accept the flush; network/package-manager installations are already out of
scope.

### Dismissed

None.

## Validation

Executed after the Codex changes unless noted:

| Check | Result |
|---|---|
| Focused Python update/handoff tests | **52 passed** |
| Updater-focused protocol, staging, product, and native set | **127 passed** |
| `python -m pytest --suite portable` | **1540 passed, 1 skipped** |
| `python -m ruff check packages packaging tests tools benchmarks` | **passed** |
| `python -m mypy packages packaging tests tools benchmarks` | **passed**, 244 source files |
| C11 helper compile with `-Wall -Wextra -Werror -O2` | **passed** |
| `python -m pytest --suite native` | **52 passed** |

The first sandboxed undivided `python -m pytest` attempt was not evidence: the
macOS UI test process aborted and `ps` was denied by the sandbox. Re-running the
repository's split portable/native gates with the required host permissions
removed those environment failures.

## Release blockers and intentionally unclaimed evidence

The following items were already unrun in Claude's handoff and remain unrun;
Codex did not relabel them as passing:

- Windows build, packaged tests, and native PowerShell helper tests on Windows.
- Linux build, packaged tests, and the native helper's `/proc` branch on Linux.
- A real frozen old-to-target update whose final swap is performed by the
  native helper rather than a disposable fixture.
- End-to-end execution of the build and release GitHub Actions workflows.

The branch must not be treated as release-cleared for Windows or Linux until
their native lanes pass. No remote CI result was inferred from local workflow
structure tests.

## Installed macOS observation

At Thiago's request, Codex inspected the visible Finder state and the installed
bundle read-only after the code review.

- `/Applications/Hanly.app` is one Apple-silicon application at the expected
  stable path. Finder reports version `0.5.2`, 1,353,705,440 bytes, created and
  modified on 2026-09-15 at 15:25.
- `codesign --verify --deep --strict` reports the installed bundle valid on disk
  and satisfying its designated requirement.
- The two other Hanly entries in Finder are mounted Downloads disk images,
  containing versions `0.1.2` and `0.1.3`. They are not additional installed
  applications.
- `/Applications/hanly-update.sh` is a 453-byte legacy swap script created at
  18:42. Its body waits for the old PID, renames the installed and staged
  directories, deletes the backup, and relaunches Hanly. It has no startup
  acknowledgement or durable recovery record. Its presence is consistent with
  the older whole-bundle update generation and it is not part of the new native
  helper design.
- The installed `0.5.2` bundle contains no `hanly-build.json`, schema-2 embedded
  manifest, or `hanly-update-posix`. It therefore predates this branch's HUP
  protocol. None of Codex's uncommitted changes altered this installed app.

This is positive evidence for the old path's visible outcome: the update kept
the same `/Applications/Hanly.app` location and produced a valid `0.5.2`
bundle. It is not evidence that the new differential/native path has run on the
installed copy. The first move from this pre-HUP `0.5.2` build to an HUP-aware
target remains the compatibility bridge and should be tested on a disposable
copy before publishing. Once that target is installed, the following release
is the first meaningful proof of the new macOS differential path in normal use.
