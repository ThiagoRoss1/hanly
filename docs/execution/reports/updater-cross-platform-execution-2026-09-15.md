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

Phases 1-3 complete. Phase 4 (native POSIX handoff, rollback, startup) in
progress. Nothing has been pushed, merged, tagged or published.

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
Windows now runs through it while keeping its proven apply path.

**Phase 3 - POSIX candidates and full products.** `app_update_tree.py` builds a
whole candidate from verified local content plus delta bytes, or unpacks a whole
product into the same place under bounds, and both converge on one
`verify_candidate`. `app_update_macos.py` attaches a disk image read-only at a
private mount point, copies the bundle out with `ditto`, detaches the exact
device on success, error and cancel, and checks the reassembled bundle's
identity and nested signature without ever re-signing it.

## Commits

| SHA | Subject | Capability |
|---|---|---|
| `82f3dd3` | `chore: add the cross-platform updater plan and its execution report` | Wave documents |
| `fcba4c5` | `feat: add the cross-platform update wire contract` | Phase 1 |
| `47d67e9` | `feat: add one preparation and planning core for every platform` | Phase 2 |
| `c10f6c0` | `feat: build and prove a whole new installation on macOS and Linux` | Phase 3 |

## Decisions and deviations

- **`app_xattr_darwin.py` added (not in the plan's file list).** CPython exposes
  `os.listxattr` on Linux only, and macOS is the platform that needs it: a
  detached signature lives in `com.apple.cs.*`. The four libc calls are bound
  through `ctypes` in a `_darwin` adapter, matching the repository's existing
  convention (`app_identity_darwin.py`, `permissions_darwin.py`). It is a
  platform primitive under `app_inventory.py`'s "platform metadata helpers
  called explicitly", not a new seam.
- **The acknowledgement a helper waits for is compared as whole bytes** against
  an `expected.txt` written into the transaction at staging time, rather than
  reassembled by the helper. The POSIX helper is C with no JSON parser, and
  comparing two files is the one thing both helpers can do identically.
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

## Validation

Run after each phase, all green at the Phase 3 commit:

```text
python -m pytest --suite portable   1472 passed, 1 skipped
python -m ruff check packages packaging tests tools benchmarks
python -m mypy  packages packaging tests tools benchmarks   242 files
```

New focused suites: `tests/test_app_hup.py`, `tests/test_app_build_identity.py`,
`tests/test_app_update_hup.py`, `tests/test_app_update_tree.py`,
`tests/test_app_update_macos.py`, plus schema-2 cases in
`tests/test_app_manifest.py`. Shared fixtures build real trees, real archives
and real digests: `tests/hanly_fixtures/update_tree.py` and
`tests/hanly_fixtures/update_release.py`.

Native and packaged suites have **NOT RUN** yet; they belong to Phases 4-6.

### Environment note

The checkout's editable installs were stale (`hanly-app` metadata reported
0.5.0 against a declared 0.5.2), which failed
`tests/test_release_version.py::test_installed_metadata_matches_the_declared_source_of_truth`
before any change in this wave. Reinstalling both packages editable fixed it.

## Outstanding

Nothing Thiago-dependent yet.
