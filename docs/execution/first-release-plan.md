# First release runbook

This runbook bootstraps the first public desktop release. The release envelope
contains the three platform archives, `hanly-resources.json`, the exact
`krdict-<version>.sqlite3.zst` named by that manifest, and `SHA256SUMS`.

There are two independent lanes: `build-krdict-resource.yml` is a manual,
non-publishing KRDICT candidate producer; `release.yml` publishes one public
release per application tag. An application tag never rebuilds KRDICT or
changes its version.

## Before starting

- Confirm `release.yml` is merged on the repository's default branch. The
  `workflow_run` trigger uses that default-branch workflow definition; a tag
  pushed before it is available there will not publish automatically and must
  be recovered manually.
- The existing `v0.1.0` tag points at stale commit `24ed285`. A human must
  correct that tag/commit relationship before the first release. Actions never
  create, move, or recreate tags. If a public release already exists, bump the
  version instead of moving its tag.
- Confirm an approved HTTPS KRDICT source URL and SHA-256 are available for the
  producer workflow. The producer needs the independent resource identity,
  source/build dates, and expected entry/sense counts.

GitHub's `releases/latest` ordering follows the release/tag commit-date
behavior, not publication order. Do not publish the stale tag or a release tag
from an older commit and assume it will become `latest`; first release history
must use the corrected chronological application tag.

## First-release sequence

Run these operations in order:

1. Dispatch **Build KRDICT resource** with the approved source URL/digest and
   resource metadata.
2. Verify the successful producer output: manifest shape, resource checksum,
   asset name, size, and validation/count report. Record its run ID. The
   candidate is retained for 30 days, subject to the repository ceiling; it
   does not publish a release.
3. On the intended application commit, human-correct and push the matching
   `vMAJOR.MINOR.PATCH` tag (for the current bootstrap, `v0.1.0`). Verify the
   package versions and pins before pushing:

   ```powershell
   python tools/release_version.py --tag v0.1.0
   ```

4. Wait for the three platform jobs in **Build Desktop Artifacts** to succeed.
   The successful same-repository tag build triggers `release.yml`, which
   selects the staged candidate, creates a draft, verifies exactly six assets,
   and publishes one public release.
5. Verify first-run acquisition on a clean machine with no
   `HANLY_KRDICT_DB` and no local generated database. Confirm download,
   checksum/schema validation, installation, vocabulary lookup, and a restart
   while offline. Repeat with the packaged executable.

If the tag was pushed before `release.yml` reached the default branch, wait for
the build and use the manual recovery below; do not push or move the tag again.

## Later application-only release

1. Bump both package versions and the two `hanly-app` pins.
2. Commit and push, then push the matching `vMAJOR.MINOR.PATCH` tag.
3. After the successful platform build, let `release.yml` copy the previous
   public release's manifest and referenced KRDICT bytes unchanged.

Do not dispatch the KRDICT producer merely because the application version
changed. An app-only tag requires a previous public release; the first release
requires a validated staged candidate.

## KRDICT candidate plus application release

1. Dispatch **Build KRDICT resource** with a new source identity and a new
   `resource_version`.
2. Verify its manifest, checksum, size, and validation report.
3. Bump/push the application tag and wait for the platform build.
4. The automatic release promotes the candidate when its producer creation
   time is strictly later than the previous public release's `published_at`.
   A missing, expired, or invalid newer candidate fails publication; it never
   silently falls back to the old resource.

After promotion, later app-only releases copy the manifest and KRDICT bytes
from the public release, so they no longer depend on the 30-day Actions
artifact. A changed database must use a new `resource_version`; equal version
with a different checksum is rejected.

## Manual recovery

Use **Release Hanly Desktop** only to recover a failed or unavailable automatic
publication. The tag must already exist and its successful desktop build
artifacts must still be available (the application artifacts expire after 14
days; rerun the tag build if needed).

Normal recovery selection:

```powershell
gh workflow run release.yml --ref <default-branch> -f tag=vMAJOR.MINOR.PATCH
```

To force one exact, successful KRDICT producer run, supply its run ID. It must
be an unexpired artifact from the successful default-branch producer workflow;
an invalid override fails and never falls back:

```powershell
gh workflow run release.yml --ref <default-branch> `
  -f tag=vMAJOR.MINOR.PATCH -f resource_run_id=<producer-run-id>
```

To explicitly reuse the previous public resource when a newer candidate is
invalid or expired, use the manual-only escape. It requires a previous public
release and cannot be combined with `resource_run_id`:

```powershell
gh workflow run release.yml --ref <default-branch> `
  -f tag=vMAJOR.MINOR.PATCH `
  -f reuse_previous_release_resource=true
```

The workflow records the reuse decision, previous release tag, and reason in
the job summary and release notes. Keep the operator reason in the recovery
record. Automatic runs cannot use this escape.

An automatic rerun for an already-published public tag is a successful no-op.
Manual dispatch fails on any existing release; draft or prerelease collisions
fail on both paths. If draft creation or exact-six verification leaves a
partial draft, leave it untouched: an operator must inspect and repair/publish
it or remove it before dispatching recovery. No workflow path overwrites a
partial draft or moves a tag.
