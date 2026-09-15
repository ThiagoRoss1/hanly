# Cross-platform updater and distribution — Review Handoff

## Bundle

- Plan: [`docs/execution/updater-cross-platform-distribution-plan-2026-09-15.md`](../updater-cross-platform-distribution-plan-2026-09-15.md)
  (Gate-tier, Phase A only)
- Running record: [`docs/execution/reports/updater-cross-platform-execution-2026-09-15.md`](../reports/updater-cross-platform-execution-2026-09-15.md)
- Implementation ecosystem: Claude Opus 5, directly, one session
- Date: 2026-09-15
- Host: macOS arm64, Python 3.13 in `.venv` (the release matrix is 3.10)
- Branch `codex/updater-cross-platform` from `origin/main` `70f71b3`
- Committed on that branch only. **Nothing pushed, merged, tagged, or published.**

## What changed, in one sentence

macOS and Linux now update differentially like Windows already did — one
metadata package per release, one planning algorithm, and three ways of
applying what it decides — and an update commits only when the build that
started proves it is the build that was installed.

---

## 1. The shape of it

Everything a client needs to decide an update now comes from **one** release
asset, `Hanly-vX.Y.Z.hup`: a small ZIP holding an index and one tree manifest
per built platform, and no application bytes at all. A client finds the entry
for the build it is actually running, learns which assets it may fetch, and
downloads nothing else. Nobody downloads another platform's payload to read
their own metadata.

```
prepare (identical everywhere)          apply (three ways)
  pin the release                         windows-files  stage only what differs,
  read the package                                       PowerShell moves it in
  read the installation as a tree         posix-tree     build the whole candidate,
  establish what it is                                   a C helper swaps it
  plan
```

| Module | What it owns |
|---|---|
| `app_manifest.py` | schema-2 tree manifests beside the frozen schema 1 |
| `app_hup.py` | the package: bounded reader, index, descriptors |
| `app_build_identity.py` | the pre-freeze stamp, and the per-installation receipt store |
| `app_inventory.py` | reading an installation as a tree, following nothing |
| `app_update_plan.py` | the one planning algorithm |
| `app_update_install.py` | pin, prepare, download, and pick a staging strategy |
| `app_update_tree.py` | building and proving a POSIX candidate |
| `app_update_macos.py` | disk images, `ditto`, plists, `codesign` |
| `app_xattr_darwin.py` | the four libc calls CPython does not expose on macOS |
| `app_update_handoff.py` | the native descriptor, the helper copy, the claim |
| `packaging/updater/hanly-update-posix.c` | the swap itself |

---

## 2. The five decisions worth reviewing

**A version number is not an acknowledgement.** The old contract had the new
build write its version into a file, which any build of that version — and any
leftover file — satisfies. A schema-2 transaction poses a challenge binding the
transaction, a 256-bit nonce, the expected identity and the manifest digest.
The candidate answers from its **own** embedded stamp and refuses unless the two
agree, so echoing the question back proves nothing. Helpers compare the answer
as whole bytes against a file the installer wrote, because the POSIX helper is C
with no JSON parser. `--update-ready` is unchanged for helpers an older Hanly
installed.

**Ownership is established, never assumed.** An update may only delete what the
previous build owned, and may only claim a path that build owned. Equal bytes at
a path nobody claimed are somebody else's file. Ownership comes from a receipt
this updater wrote, or — for a fresh manual installation — from fetching the
package of the tag it is already running and checking every managed entry by
hash. Neither available means the update stops and asks for a manual install.

**POSIX builds a whole candidate rather than editing in place.** A bundle is
signed as a unit and a onedir's libraries are opened long after start, so an
installation caught between two builds is worse than one replaced in a single
step. Most of the candidate is copied from the installation itself; only what
changed travels. "Reused" means copied, not left alone, and the disk estimate
and the progress text both say so.

**The published signature material travels; nothing is re-signed.** macOS
signature bytes are ordinary hashed files and allow-listed `com.apple.cs.*`
extended attributes. The reassembled bundle is checked with
`codesign --verify --deep --strict`. That proves the bundle is intact and
self-consistent; with an ad-hoc signature it says nothing about who produced it,
and nothing in the product claims otherwise.

**A release's asset set is derived from the package it publishes.** Not a list
kept beside it, which could disagree with it about a delta. Releases published
before packages existed are classified as what they are, so validating release
history is still a no-op; a release being made now must publish a package.

---

## 3. Findings

Everything found during implementation was fixed; nothing is deferred to a
reviewer. Recorded here because each was a real defect, not a refactor.

| Finding | Disposition |
|---|---|
| A file whose permissions or macOS signature changed but whose bytes did not was planned as needing payload bytes the release never publishes for it, which would have made every signature-only change fall back to a whole download. | **Fixed now** — `TreeOperation.needs_bytes` compares the file's content against what is on disk, not merely its kind. |
| `_is_manifest_member` used a chained comparison (`"/" in stem is False`) that is always false, so every manifest member name would have been rejected. | **Fixed now** — caught by the round-trip case before it could ship. |
| The update challenge required an alphanumeric transaction name, but `tempfile` names can contain `_`. It failed intermittently, which is the worst way for it to fail. | **Fixed now** — a plain-identifier pattern, with the suite run repeatedly to confirm. |
| `GitHubReleaseFetcher._json` read a release payload with no bound. | **Fixed now** — bounded at 1 MiB while reading. |
| A macOS packaging test double took every command's last argument for a path, so `hdiutil detach <mount> -force` wrote a file called `-force` into the repository root. | **Fixed now**, with a case for it. Found because a new case ended in that flag. |
| The acknowledgement was written through text mode, so Windows would have rewritten every newline in it and no update could ever have committed. | **Fixed now** — written as exact bytes, with a case asserting the two files are byte-identical and carry no CR. |
| Abandoning an update that had staged nothing cleared the installation's receipt, costing it the ownership its next update reads. Abandon runs on every failure path, including before staging. | **Fixed now** — restoring is a no-op when nothing was staged. |
| A path the previous build owned and the new one drops was counted as a file somebody had added, which would have blocked **every** macOS update that removes anything. | **Fixed now** — found by the real release pair in §4; the synthetic fixtures never dropped a file on macOS. |
| The native helper forked once, so it waited on the application it launched instead of on that application's acknowledgement — holding the backup open for the whole session on Linux. | **Fixed now** — double fork, with a native case whose stand-in keeps running after answering. |
| The launched application inherited the helper's streams and held them open for as long as it ran. | **Fixed now** — the grandchild's stdio goes to `/dev/null`. Visible from outside as the POSIX native suite dropping from 145 s to 25 s. |
| The Windows PowerShell helper cannot use PowerShell 7's ternary operator. | **Fixed now** before it was written to disk; the rendered body is asserted free of one. |
| PyInstaller decides where a collected binary lands, and that has changed between its own versions, so the native helper's path could not be assumed. | **Fixed now** — read from the installed build's own manifest. |

Two things are **deliberately not done**, both from the plan's non-goals:
APFS clone-based reuse (ordinary bounded copies give correct rollback on every
filesystem), and a publisher signing key (a secret in the same workflow that
publishes does not separate release-upload compromise from index authorization).

---

## 4. Validation

### One real macOS release pair

Two **independently frozen and ad-hoc-signed** builds were made on this host and
taken through the whole lane. This is the evidence the plan asks for: a pair
that exposes real signature churn, not controlled edits to one tree.

| | |
|---|---|
| Entries per build | 7,325 — 1,063 directories, 4,725 files, **1,537 symlinks** |
| Product | 1.30 GB; disk image 630 MB |
| Update package | **270 KB** for the whole release |
| Delta | **49.3 MB**, 92.2% smaller than the whole product |
| Files needing bytes | 20; **4,705 reused** from the installation (1.24 GB copied) |
| Inspect / reconstruct / prove | 1.7 s / 3.5 s / 3.1 s |

The candidate built from the 0.5.2 installation plus that delta is **exactly**
the published 0.5.3 build — every entry, mode, link target and digest — and it
passes `codesign --verify --deep --strict`. The bundle copied out of the disk
image and the bundle unpacked from the compatibility ZIP each match the one
published manifest, which is what proves the two products are one application.

The frozen bundle put the native helper in `Contents/Frameworks/`, not beside
the executable — which is why its location is read from the manifest.

### Gates

Convergence gates on this host, all green:

```text
python -m pytest --suite portable     1539 passed, 1 skipped
python -m pytest --suite native         51 passed
python -m ruff check packages packaging tests tools benchmarks
python -m mypy  packages packaging tests tools benchmarks   244 files
cc -std=c11 -Wall -Wextra -Werror -O2 packaging/updater/hanly-update-posix.c
```

The POSIX native cases compile the real helper from its own source and run it as
a program against disposable directories: a successful swap, a candidate that
never answers, a stale version-text answer, an interruption between the two
renames, an interruption after both, recovery with the installation absent, an
installation that is no longer the one recorded, lock contention, and four
malformed descriptors. `tests/test_release_products.py` takes two builds through
the real producer to a real package and has a client reconstruct the published
build from it, with no network and no upload.

**What has not run** is in the report's `NOT RUN` table: the Windows and Linux
lanes have no host in this session, so the PowerShell helper's schema-2 changes
and the C helper's `/proc` branch are compiled and unit-covered but not
exercised on their own platforms. Both are release blockers for those platforms
until run there. The swap itself was exercised only against disposable
directories — performing it for real would replace this checkout's own
products. The workflows are held only by `tests/test_ci_workflows.py`.

---

## 5. What a reviewer should look at first

1. `app_update_tree.py::assemble_candidate` and `verify_candidate` — the claim
   that a reconstructed tree is byte-for-byte the published build.
2. `packaging/updater/hanly-update-posix.c` — the only code that mutates an
   installation on POSIX, and the only place a mistake is not recoverable by
   rerunning.
3. `app_update_install.py::TreeUpdateInstaller._established_base` — everything
   the updater is allowed to delete follows from this answer.
4. `app_update_journal.py`'s challenge and acknowledgement — what "the update
   worked" is actually taken to mean.
5. `tools/release_build.py::verify_published_assets` — the boundary between two
   generations of the release contract.

## 6. Codex's follow-up, reviewed

Codex resumed this branch after `58efb50`, made two functional changes, and
recorded them in
[`updater-cross-platform-codex-resumption-2026-09-15.md`](../reports/updater-cross-platform-codex-resumption-2026-09-15.md).
Both are correct and are kept:

- **A candidate's own startup no longer launches a recovery helper while the
  helper that installed it is still waiting.** The candidate reaches
  `settle_native_update` before it writes its acknowledgement, so settlement
  saw an unsettled transaction and started a second contender. The advisory
  lock meant it could not mutate anything, but the launch was pointless and
  the session log reported an interruption that had not happened. This now
  mirrors what the Windows path already did.
- **Recovery keeps a candidate that provably answered.** `installed + backup +
  no result` was always rolled back, but that state also occurs when the
  candidate wrote the exact transaction-bound answer and the helper died before
  its result became durable. Rolling back there turns a failed bookkeeping
  write into a product rollback. Recovery now retains the tree only when both
  independent checks hold - the installed directory's device and inode are the
  staged candidate's (a rename preserves the inode, so this really does prove
  identity) and the acknowledgement matches the descriptor byte for byte, which
  is nonce- and build-bound. Missing, stale, or wrong answers still roll back.

One gap in that follow-up, closed here: the Python regression monkeypatched
`native_helper_is_running` rather than exercising it, leaving the new function
itself untested. `tests/test_app_update_handoff.py` now takes a real `flock` and
asserts the function reports it, before and after.

Codex's one deferred item - `move_directory` ignoring the return of its parent
directory flushes - is deferred correctly. Once `rename` has returned, reporting
the move as failed would send recovery down a branch for something that did
happen; the right fix needs an explicit post-rename state transition and
injected `fsync` failures, not an error check. Revisit before a production
updater release.

Phase B has not been authorized and has not started.
