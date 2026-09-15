# Hanly cross-platform updater and distribution — execution report

Running record for the wave specified by
[the execution plan](../updater-cross-platform-distribution-plan-2026-09-15.md).
Phase A implementation only; Phase B deep review is not authorized here.

## Branch and base

| Field | Value |
|---|---|
| Branch | `codex/updater-cross-platform` |
| Base ref | `origin/main` |
| Base SHA | `70f71b3aca3ab39835fa7700680ada57bab19dbe` |
| Base subject | `chore: add new updater plan` |

`origin/main` and local `HEAD` were identical at branch time. The worktree
carried three uncommitted documentation changes (`docs/CODE-MAP.md`, the
superseded Windows plan, and this wave's untracked plan); all were carried onto
the branch untouched. Only this wave's files are staged in its commits.

## Status

Phases 1-6 complete. Convergence gates green, and one real macOS
build-to-update pair exercised end to end on this host. Nothing has been
pushed, merged, tagged or published.

## Completed capabilities

**Phase 1 - wire contract and release identity.** Schema-2 `TreeManifest`
describes a whole tree: directories, POSIX permission bits, relative links and
the material macOS extended attributes a detached signature lives in. Schema 1
is untouched and still produced for Windows. `app_hup.py` reads and writes the
`Hanly-vX.Y.Z.hup` metadata package within every bound in the plan's §3.
`app_build_identity.py` holds the pre-freeze build stamp and the per-user,
per-installation receipt store. `app_inventory.read_tree` reads an installation
as a tree without following anything.

**Phase 2 - one preparation core.** `TreeUpdateInstaller` pins a release into an
immutable `ReleaseSnapshot` and resolves every later download through it.
Ownership comes from a receipt this updater wrote, or from a bootstrap that
fetches the *installed tag's* own package and checks every managed entry by
hash; neither available means the update stops rather than guessing.
`plan_tree_update` is the one planning algorithm for all three platforms.
Windows now runs through it while keeping its proven apply path. The commit is
bound to a challenge naming the transaction, a 256-bit nonce, the build's own
UUID and the manifest digest; `--update-ready` is unchanged for older helpers.

**Phase 3 - POSIX candidates and full products.** `app_update_tree.py` builds a
whole candidate from verified local content plus delta bytes, or unpacks a whole
product into the same place under bounds, and both converge on one
`verify_candidate`. `app_update_macos.py` attaches a disk image read-only at a
private mount point, copies the bundle out with `ditto`, detaches the exact
device on success, error and cancel, and checks the reassembled bundle's
identity and nested signature without ever re-signing it.

**Phase 4 - native handoff, rollback and startup.**
`packaging/updater/hanly-update-posix.c` is C11 against libc (plus libproc on
macOS), compiled with `-Werror`. It reads one fixed binary descriptor, claims
the installation's lock, waits for every process running out of the
installation, renames durably, launches, compares the acknowledgement byte for
byte, and restores on any failure. A proved copy of it lives outside the
installation. One `TreeUpdateRunner` holds the lock and hands off by what was
staged rather than by a platform test; a launch settles both transaction
generations before anything initializes.

**Phase 5 - build and release integration.** One predecessor is pinned for all
three jobs. Each job stamps before freezing, declares its target machine and
verifies the executable it produced is really for it, and writes a private
per-platform descriptor. An aggregation job assembles the single package from
the descriptors and products of that one run, proving each advertised asset
against the file on disk. A release's asset set is derived from the package it
publishes. The macOS lane smokes the disk image a client downloads and holds it
and the compatibility ZIP to one published manifest.

**Phase 6 - documentation.** `docs/CODE-MAP.md` §6a and `packaging/README.md`
describe what is implemented: the one preparation core, the three apply paths,
the build order the stamp and the signature impose, the derived release set, and
how a client from before update packages reaches one.

## Commits

| SHA | Subject | Capability |
|---|---|---|
| `82f3dd3` | `chore: add the cross-platform updater plan and its execution report` | Wave documents |
| `fcba4c5` | `feat: add the cross-platform update wire contract` | Phase 1 |
| `47d67e9` | `feat: add one preparation and planning core for every platform` | Phase 2 |
| `c10f6c0` | `feat: build and prove a whole new installation on macOS and Linux` | Phase 3 |
| `bbc60ef` | `chore: record phases 1-3 in the execution report` | Report |
| `f4b1f9f` | `feat: apply a POSIX update with a native helper that outlives Hanly` | Phase 4 |
| `b4c0022` | `feat: produce and validate the cross-platform release contract` | Phase 5 (producer) |
| `8f62d7a` | `feat: build and publish the cross-platform release contract` | Phase 5 (lanes) |
| `7b3f305` | `fix: stop a packaging test stub writing a file named after a flag` | Defect found in passing |
| `e97118a` | `docs: describe the cross-platform updater as implemented` | Phase 6 |
| `8c7e2ee` | `test: ask the build stamp question of a package, not of this checkout` | Test coupling |
| `971b66f` | `fix: write an update acknowledgement as exact bytes` | Windows-blocking defect |
| `cb2d437` | `fix: keep an installation's receipt when an update staged nothing` | Ownership defect |
| `0b875df` | `fix: let a POSIX update commit while the build it started keeps running` | Three defects the real pair exposed |
| `33048ba` | `docs: record the real macOS release pair and what it exposed` | Evidence |

## Decisions and deviations

- **`app_xattr_darwin.py` added (not in the plan's file list).** CPython exposes
  `os.listxattr` on Linux only, and macOS is the platform that needs it: a
  detached signature lives in `com.apple.cs.*`. The four libc calls are bound
  through `ctypes` in a `_darwin` adapter, matching the repository's existing
  convention (`app_identity_darwin.py`, `permissions_darwin.py`). It is a
  platform primitive under `app_inventory.py`'s "platform metadata helpers
  called explicitly", not a new seam.
- **The acknowledgement a helper waits for is compared as whole bytes** against
  an `expected.txt` written into the transaction at staging time (Windows) or
  carried in the descriptor (POSIX), rather than reassembled by the helper. The
  POSIX helper is C with no JSON parser, and comparing bytes is the one thing
  both helpers can do identically.
- **The receipt is staged, not written, at staging time.** The candidate
  promotes it only after proving its own identity against the challenge, and a
  rollback restores the previous one. This keeps "persist only verified data"
  without teaching PowerShell the receipt format.
- **A Windows build carrying a link or an empty directory fails the producer.**
  The file-by-file Windows apply has no operation that creates either, so this
  is caught at build time rather than on a user's machine; the client checks
  again and refuses with a manual-replacement explanation.
- **Bootstrap admits a tree with extra files.** Every *managed* entry must match
  the published manifest by hash; unmanaged extras are preserved, not a reason
  to block. macOS blocks unexpected extras separately, at staging, per §6.
- **The helper's location is read from the installed build's own manifest**
  rather than assumed to sit beside the executable. A freezer decides where a
  collected binary lands and that has changed between its own versions.
- **The macOS full product is the disk image, not the ZIP.** §6 authorizes this
  once the bounded read-only acquisition exists, which it now does. The
  compatibility ZIP is still published and is held to the same manifest in the
  macOS lane, which is what proves the two are one application.
- **`tests/test_release_products.py` added** (not named in §10) for the
  producer-to-client round trip §12 requires under "Release": two builds, their
  products, one package, and a client reconstructing the published build from
  them without a network.

## Validation

### One real macOS release pair, end to end

Two **independently frozen and ad-hoc-signed** builds were made on this host,
0.5.2 and 0.5.3, each through `tools/build_package.py` exactly as the build lane
runs it. This is the evidence the plan asks for under §12: a pair that exposes
real signature churn rather than controlled edits to one tree.

| | |
|---|---|
| Entries per build | 7,325 — 1,063 directories, 4,725 files, **1,537 symlinks** |
| Product size | 1.30 GB; disk image 630 MB |
| Update package | **270 KB** for the whole release |
| Delta payload | **49.3 MB** — 92.2% smaller than the whole product |
| Files needing bytes | 20; **4,705 reused from the installation** (1.24 GB copied) |
| Paths the release drops | 19, correctly planned as deletions and not as a person's files |
| Inspect the installation | 1.7 s |
| Reconstruct the candidate | 3.5 s |
| Prove it (whole tree + `codesign --verify --deep --strict`) | 3.1 s |

The candidate reconstructed from the 0.5.2 installation plus the 49 MB delta is
**exactly** the published 0.5.3 build — every entry, mode, link target and
digest — and it passes nested-code signature verification. The Qt framework's
`Versions/Current/...` link chains reconstruct correctly, which is the case a
schema-1 file list could not have described at all.

Both published macOS products were also held to the one published manifest: the
bundle copied out of the **disk image** and the bundle unpacked from the
compatibility **ZIP** each match it exactly, which is what proves the two are
one application. `require_no_unsupported_metadata` found no ACLs.

The frozen bundle put the native helper at `Contents/Frameworks/hanly-update-posix`,
not beside the executable — which is why its location is read from the manifest
rather than assumed.

Products left in `dist/`: both disk images' successor, the compatibility ZIP,
`dist/release/macos/` and `dist/package/`. The disposable candidate was removed.

### Gates

At convergence, on this macOS arm64 host:

```text
python -m pytest --suite portable   1533 passed, 1 skipped
python -m pytest --suite native     50 passed
python -m ruff check packages packaging tests tools benchmarks
python -m mypy  packages packaging tests tools benchmarks   244 files
cc -std=c11 -Wall -Wextra -Werror -O2   the native helper builds clean
```

New focused suites: `tests/test_app_hup.py`, `tests/test_app_build_identity.py`,
`tests/test_app_update_hup.py`, `tests/test_app_update_tree.py`,
`tests/test_app_update_macos.py`, `tests/test_release_products.py`,
`tests/native/shared/test_update_posix_native.py`, plus schema-2 cases in
`tests/test_app_manifest.py`, `tests/test_app_update_handoff.py`,
`tests/test_release_build.py`, `tests/test_ci_workflows.py` and
`tests/test_packaging.py`.

The POSIX native cases compile the real helper from its own source and run it
as a program against disposable directories: a successful swap, a candidate
that never answers, a stale version-text answer, an interruption between the
two renames, an interruption after both, recovery with the installation absent,
an installation that is no longer the one recorded, lock contention, and four
malformed descriptors.

### NOT RUN

| Lane | State | Blocker |
|---|---|---|
| Windows build, packaged suite, native helper cases | **NOT RUN** | No Windows host in this session. Release blocker for Windows until run there. |
| Linux build, packaged suite, native POSIX swap on Linux | **NOT RUN** | No Linux host in this session. The POSIX helper's `/proc` process-identity branch is compiled but unexercised. Release blocker for Linux until run there. |
| A real frozen old-to-target update **through the native helper** | **NOT RUN** | The candidate was built and proved from real artifacts; the swap itself was exercised only against disposable directories, because performing it would replace this checkout's own products. |
| The build and release workflows end to end | **NOT RUN** | Needs GitHub Actions; the lanes are held by `tests/test_ci_workflows.py` only. |

### Defects found by the real pair

Three defects were found after the synthetic suites were green, each fixed with
a regression case. Two of them only a real pair could expose:

- **A path the previous build dropped was counted as a file somebody had
  added**, which would have blocked *every* macOS update that removes anything.
  The synthetic fixtures never dropped a file on macOS; the real 0.5.2-to-0.5.3
  pair drops 19.
- **The native helper forked once**, so it waited on the application it had
  launched rather than on that application's acknowledgement. A stand-in that
  exits immediately hides this; a real build runs until the user closes it, and
  the update would have held its backup open for the whole session.
- **The launched application inherited the helper's streams.** Redirecting them
  took the POSIX native suite from 145 s to 25 s, which is the same defect seen
  from the outside.

### Environment note

The checkout's editable installs were stale (`hanly-app` metadata reported
0.5.0 against a declared 0.5.2), which failed
`tests/test_release_version.py::test_installed_metadata_matches_the_declared_source_of_truth`
before any change in this wave. Reinstalling both packages editable fixed it.

The two builds above required the product version to be 0.5.2 and then 0.5.3,
because a macOS bundle's `Info.plist` versions come from installed metadata and
a delta between two builds of one version is deliberately not produced. Both
`pyproject.toml` files were bumped, the packages reinstalled, and **both
reverted afterwards**; `git diff` over them is empty, and the generated build
stamp (which is gitignored) was removed. This host runs Python 3.13, while the
release matrix is 3.10.

## Outstanding

Nothing Thiago-dependent. The unexercised lanes above are machine availability,
not decisions.
