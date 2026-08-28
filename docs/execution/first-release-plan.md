# First release plan — publishing the dictionary and finalizing the tag

Status: **not started.** Written 2026-08-28 from the state the code is in now.
No commit, tag, workflow dispatch, or release publication has been performed.

## Why this exists

Everything downstream of "install Hanly" works today except the one step that
makes it usable by anyone other than the person who built the database.

A first launch provisions KRDICT from the GitHub release channel. There is no
release. So a fresh clone or a packaged executable on a machine that has never
seen `krdict.sqlite3` cannot start, and the only workaround is the developer
environment variable:

```
HANLY_KRDICT_DB=/path/to/krdict.sqlite3
```

Publishing the release closes that. It is the last thing standing between the
current tree and someone else being able to run Hanly.

## Current state, verified

| | |
|---|---|
| Tag `v0.1.0`, local and on `origin` | exists, points at `24ed285` |
| Commits between that tag and `HEAD` | 2, and none of the recent work |
| GitHub Releases on the repository | **none** (`/releases` returns `[]`) |
| Product version in both `pyproject.toml` files | `0.1.0` |
| Dictionary asset built locally | yes, gitignored |
| Producer workflow | present, never dispatched |
| Release workflow | present, never dispatched |

The tag is therefore stale *and* unreleased. Nothing was ever built or
published from it, nothing links to it, and the repository has no other
consumers — so it can be moved or deleted without the usual cost of rewriting a
published ref.

## What the release has to contain

`hanly_app.first_run` asks the release channel for a manifest asset named
**`hanly-resources.json`** and expects it to advertise one `krdict` resource.
`release.yml` already asserts the shape, so the release must carry:

| Asset | Produced by |
|---|---|
| `hanly-resources.json` | `tools/krdict/package_resource.py`, copied by `release.yml` |
| `krdict-<version>.sqlite3.zst` | `tools/krdict/package_resource.py` |
| `hanly-desktop-windows.zip` | `build.yml` |
| `hanly-desktop-macos.tar.gz` | `build.yml` |
| `hanly-desktop-linux.tar.gz` | `build.yml` |
| `SHA256SUMS` | `release.yml` |

The asset name is checked against `krdict-{version}.sqlite3.zst` and against the
file actually uploaded, so the resource version and the file name cannot drift
apart.

Locally reproduced values for the current database, for comparison when the
workflow produces its own:

- resource version `20260819-v1`, schema version `1`, source date `2026-08-19`
- 56,555 entries, 76,833 senses
- SQLite 92,508,160 bytes → Zstandard 27,352,629 bytes (29.6%)
- asset SHA-256 `62748d8a37dab9bc3c551672cf4cebde3ea7dc1abb6f5f404e11e99db64b9ab9`

## Open question, and it blocks everything

`build-krdict-resource.yml` takes `source_url`: an **HTTPS URL the runner can
download the official KRDICT archive from**, plus its exact SHA-256. It
deliberately does not read a source archive from the repository.

**There is no such URL recorded anywhere.** The archive was acquired by hand.
Before the producer workflow can run even once, someone has to establish either:

1. a stable public HTTPS URL for the official archive that the runner may fetch,
   with the licence permitting automated download; or
2. a private location the runner is allowed to reach, which means adding a
   secret and changing the workflow's current no-credentials shape; or
3. a decision that the resource is built locally and uploaded to the release by
   hand, which makes the producer workflow dead weight and should delete it
   rather than leave it unusable.

**Do not start the sequence below until this is settled.** Option 3 is a real
option — it is honest about how the database is actually built today — but it
trades reproducibility in CI for one person's machine, so it deserves a
deliberate decision rather than a default.

## Sequence

Each step is human-dispatched. Nothing here happens automatically on push.

### 1. Decide the version

Re-tagging `v0.1.0` is safe *only* while no release exists. Once one is
published from a tag, moving that tag leaves the release pointing at the old
commit while the ref says otherwise.

- **First real attempt:** delete and re-create `v0.1.0` on the current commit.
- **Any repeat after a release exists:** bump instead.

Bumping touches four lines, and `release.yml` refuses to publish when the tag
and the product version disagree:

- `packages/hanly/pyproject.toml` → `version`
- `packages/hanly-app/pyproject.toml` → `version`
- `packages/hanly-app/pyproject.toml` → `dependencies = ["hanly==<v>", …]`
- `packages/hanly-app/pyproject.toml` → `runtime = ["hanly[concrete]==<v>", …]`

### 2. Finalize the tag

```bash
python tools/release_version.py                 # print the product version
python tools/release_version.py --tag v0.1.0    # fail loudly on a mismatch

git tag -d v0.1.0
git push origin :refs/tags/v0.1.0
git tag v0.1.0
git push origin v0.1.0
```

Pushing a `v*` tag triggers `build.yml`, which produces the three platform
archives. It refuses to build if the tag and the product version disagree.

### 3. Produce the resource

Dispatch **Build KRDICT resource** with `source_url`, `source_sha256`, and the
resource identity (`resource_version`, `source_date`, `build_date`,
`expected_entries`, `expected_senses`).

The runner downloads the archive, verifies the digest *before* parsing, builds,
validates, packages, and uploads `hanly-krdict-resource` — the `.sqlite3.zst`,
the producer manifest, and the validation report. It cannot publish anything.

Compare its outputs against the locally reproduced values above. A byte-identical
`.zst` with the same SHA-256 confirms the build is deterministic across machines;
a difference is a finding, not a rounding error.

Record the **run id**.

### 4. Publish

Dispatch **Release Hanly Desktop** with the tag and that `resource_run_id`. It
finds the tag's application build itself, assembles the six assets, writes
`SHA256SUMS`, and creates the release with generated notes.

### 5. Verify the thing this was all for

On a machine that has **never** run Hanly, with no `HANLY_KRDICT_DB` set and no
`data/generated/krdict.sqlite3` present:

- [ ] Start it. It should report `Preparing Hanly` → `Checking resources` →
      `Downloading Korean dictionary` → `Verifying` → `Installing` → `Ready`.
- [ ] Confirm the phases are visible in the Control Center, not just on stderr.
      They were only wired to their labels recently and have never run against
      a real download.
- [ ] Confirm the installed database validates and real vocabulary resolves.
- [ ] Restart with the network disconnected. It must start offline — that path
      is already covered by tests, and this is the end-to-end confirmation.
- [ ] Repeat with the packaged executable, not only a source install.

Until step 5 passes, the first-run download path has never executed against a
real release. Every test of it uses a fake fetcher.

## Worth doing before publishing, not after

Recorded in `review-handoffs/han-38-krdict-production-resource-pipeline.md`
and unresolved:

- **`_decompress_zstd` has no output bound.** The checksum is verified before
  decompression, so a decompression bomb needs a compromised release manifest —
  but publishing a real release is exactly when that stops being hypothetical.
  A `max_output_size` from the frame content size closes it cheaply.
- **Startup validation costs ~4.5 s cold** on the 92 MB resource, dominated by
  `PRAGMA quick_check` reading the whole file on *every* launch. Users will feel
  this the moment they have the real dictionary. The fix is to tie the deep
  check to a verified resource identity so it runs on first launch after an
  install rather than always — with tests proving the full checks still run on
  install, recovery, and every identity change.
- **A `record_install` failure is reported as an install failure** even though
  the resource is already active. Narrow window, self-heals on the next
  validation, but a real download makes it reachable for the first time.

## Not in scope here

- Keeping the desktop open when no dictionary can be obtained. That is a
  separate feature and an approved-architecture change; it is described in the
  handoff and needs a decision of its own.
- Publishing either package to PyPI. Nothing in this flow depends on an index,
  and `README.md` says so plainly.
