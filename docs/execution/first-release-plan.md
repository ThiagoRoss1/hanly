# First release runbook

This runbook bootstraps the first public desktop release. The release envelope
contains the three platform archives, `hanly-resources.json`, the exact
`krdict-<version>.sqlite3.zst` named by that manifest, and `SHA256SUMS`.

KRDICT is built locally from the manually acquired official ZIP. That ZIP and
the raw `krdict.sqlite3` never leave the operator's machine and are never
release assets. `release.yml` never downloads a source archive and never builds
the resource: it stages a draft, waits for the operator to attach the two local
files and approve, and publishes last. An application tag never rebuilds KRDICT
or changes its version.

## The two halves

- **`stage`** runs automatically after a successful same-repository tag build,
  or manually for an existing tag. It resolves the tag commit, verifies the
  successful **Build Desktop Artifacts** run for that exact commit, checks the
  tagged package versions and pins, and creates or repairs a private draft
  holding the three platform archives. It never publishes and never writes
  `SHA256SUMS`.
- **`finalize`** waits on the `hanly-release` environment. Approving it re-runs
  every check from the tag up, takes the KRDICT pair from the draft, validates
  the manifest, writes `SHA256SUMS`, uploads the six assets, asserts the draft
  holds exactly those six, and only then clears the draft flag.

The two halves are one run in one per-tag concurrency group, and that group is
never cancelled automatically. **A second run for the same tag queues behind a
run waiting for approval** — plan the sequence below accordingly.

## Before starting

- Confirm `release.yml` is merged on the repository's default branch. The
  `workflow_run` trigger uses that default-branch workflow definition; a tag
  pushed before it is available there will not stage automatically and must be
  recovered manually.
- Confirm the `hanly-release` environment exists with the intended required
  reviewers. Without it the finalize job cannot gate.
- Build the resource locally and keep both files to hand:
  `data/generated/krdict-<resource-version>.sqlite3.zst` and
  `data/generated/hanly-resources.json`. Build commands are in `data/README.md`.
- Verify the tag points at the intended commit. Actions never create, move, or
  recreate tags. If a public release already exists, bump the version instead of
  moving its tag.

GitHub's `releases/latest` ordering follows release/tag commit-date behavior,
not publication order. Do not publish a release tag from an older commit and
assume it will become `latest`.

## First-release sequence

1. On the intended application commit, push the matching `vMAJOR.MINOR.PATCH`
   tag. Verify the package versions and pins before pushing:

   ```powershell
   python tools/release_version.py --tag v0.1.0
   ```

2. Wait for the three platform jobs in **Build Desktop Artifacts** to succeed.
   The successful same-repository tag build triggers `release.yml`.
3. `stage` finishes with a private draft for the tag holding the three platform
   archives. There is no previous public release, so no resource pair is carried
   and none is required yet.
4. Open the draft in **Releases → Edit** and attach both local files: exactly
   one `krdict-<resource-version>.sqlite3.zst` and one `hanly-resources.json`.
   Save the draft. Leave the `Hanly-Release-Commit:` line in the body — the
   finalize job uses it to prove the draft is the one staged for this commit.
5. Open the run, find the `finalize` job waiting under **Review deployments**,
   and approve it. It revalidates everything and publishes.
6. Confirm the published release lists exactly six assets.
7. Verify first-run acquisition on a clean machine with no `HANLY_KRDICT_DB` and
   no local generated database. Confirm download, checksum/schema validation,
   installation, vocabulary lookup, and a restart while offline. Repeat with the
   packaged executable.

If the tag was pushed before `release.yml` reached the default branch, wait for
the build and use the manual recovery below; do not push or move the tag again.

## Later application-only release

1. Bump both package versions and the two `hanly-app` pins.
2. Commit and push, then push the matching `vMAJOR.MINOR.PATCH` tag.
3. After the successful platform build, `stage` creates the draft and copies the
   previous public release's `hanly-resources.json` and the KRDICT `.zst` it
   names into it. Nothing to upload by hand.
4. Approve `finalize`.

An application-only tag needs no local KRDICT build and no upload. A new
application tag never implies the dictionary changed.

## Changing KRDICT alongside an application release

Follow the app-only sequence, and before approving, replace **both** carried
resource assets in the draft with the newly built pair. A changed database must
use a new `resource_version`; the same version with a different checksum is
rejected at finalization.

The carried pair is written only when the draft is created. A rerun that repairs
an existing draft touches the three application archives and nothing else, so an
uploaded pair is never silently overwritten.

## Manual recovery

Use **Release Hanly Desktop** to recover a failed or unavailable automatic
staging. The tag must already exist and its successful desktop build artifacts
must still be available (application artifacts expire after 14 days; rerun the
tag build if needed).

```powershell
gh workflow run release.yml --ref <default-branch> -f tag=vMAJOR.MINOR.PATCH
```

A draft this lane staged for the same commit is not a collision: a rerun repairs
its application archives and leaves the resource pair alone. A draft naming
another commit, an unrelated draft, a prerelease, or an existing public release
is refused. An automatic rerun of a tag already published *in full by this lane*
— the same commit marker and exactly the six valid asset names — is a successful
no-op; a foreign, partial, or inconsistent public release fails instead.

## Dry runs

`validate_only: true` runs every check against an **existing** draft and writes
nothing: staging creates nothing, uploads nothing, and does not even download the
artifacts it would upload; finalize validates and stops before touching the
draft. It still passes through the same approval gate.

Because one per-tag run holds the concurrency group, a dry run cannot be started
while a normal run waits for approval. The supported orders are:

- **Approve directly.** Stage → attach files → approve. No dry run.
- **Dry run first.** Stage → attach files → cancel the pending run (cancelling
  deletes nothing; the draft stays) → dispatch with `validate_only: true` and
  approve it → dispatch normally again and approve. The second normal run reuses
  the same draft and repairs only the application archives.

Do not run both at once. Two runs mutating one draft is exactly what the
concurrency group exists to prevent.

## When something fails

A failed validation leaves the draft intact and unpublished. No workflow path
deletes a draft, overwrites a public release, or moves a tag. Fix the cause and
dispatch the same tag again.
