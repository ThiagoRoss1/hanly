# GitHub Release Automation Review Handoff

## Bundle

- Member issues: GitHub release automation feature, including R1–R22.
- Implementation ecosystem: Hanly execution flow; Codex orchestration with Luna
  xhigh implementation and review workers.
- Date: 2026-09-01.
- Status: implementation complete; ready for normal human review.

## Outcome / topology

- The approved topology is two independent lanes, not two competing public
  release streams: a manual KRDICT producer creates a staged candidate, while
  each application tag publishes one complete public GitHub Release.
- Every public release carries the three application archives,
  `hanly-resources.json`, the exact referenced KRDICT bytes, and `SHA256SUMS`.
  This preserves the existing first-run `releases/latest` lookup without runtime
  changes.

## Main expected behavior

- **Automatic:** a successful same-repository `push` run of `Build Desktop
  Artifacts` with a strict semver head branch is admitted. The workflow proves
  the exact tag/ref, build `head_sha`, workflow provenance, and tagged package
  metadata before downloading artifacts. An existing public release is a
  successful automatic no-op; draft/prerelease collisions fail.
- **Manual:** dispatch resolves the supplied existing tag to an exact successful
  build commit. Operators may provide a producer run override, or explicitly
  set `reuse_previous_release_resource`; the escape is manual-only,
  mutually exclusive with the override, requires a previous public release,
  and records its decision in the summary and notes. Existing releases fail.
- **First release:** after a numeric HTTP 404 from `releases/latest`, select and
  validate the newest successful default-branch KRDICT producer candidate. If
  none is available, fail with the bootstrap instruction rather than publish.
- **Application-only:** copy the previous public release's manifest and
  referenced KRDICT bytes unchanged; do not run the producer merely because the
  application version changed.
- **KRDICT plus application:** dispatch a new producer identity, then push the
  application tag. A candidate created after the previous release's
  `published_at` is promoted; missing, expired, invalid, or same-version/
  changed-checksum candidates fail without downgrade.

## Architecture / seams touched

- Updated the three workflows, release operator documentation, the existing
  `tools/release_version.py` authority, and focused structural/version tests.
  Engine, first-run, update, database, provider, and resource-installation
  code remain unchanged.
- The publisher uses Python 3.13 and native `tomllib` to read the exact tagged
  `pyproject.toml` files as inert data, then invokes the tested data-oriented
  version authority. It verifies engine version, app version, and both exact
  `hanly` pins while preserving installed-metadata behavior for `build.yml`.
- The final correction pass closed the identified P1 paths: REST workflow paths
  normalize an optional `@ref`; manual resolution uses exact commit matching;
  absence accepts only numeric HTTP 404; the tag is recursively re-peeled and
  re-compared immediately before draft creation. `GH_TOKEN` is step-scoped.
- Resolved state now uses `application`, `preflight`, and `resources` step
  outputs; job-level placeholders and `$GITHUB_ENV` shadowing are removed. A
  repository-wide structural invariant rejects any name written to
  `$GITHUB_ENV` when it is also declared in that job's environment.
- Publication concurrency is per application tag with `cancel-in-progress: false`;
  duplicate runs for one tag serialize while different tags may publish
  independently. Tagged product verification and collision detection are
  separate named steps.
- The release lane checks out trusted default-branch tooling, never executes
  tag-controlled code, validates the canonical final staged manifest/resource
  bytes once after copy/download and before draft creation, creates a draft,
  verifies exactly six assets, and only then publishes. The KRDICT producer
  remains the SQLite/database validation authority.

## Relevant files / diff areas

- **Workflows:** `.github/workflows/build.yml`,
  `.github/workflows/build-krdict-resource.yml`,
  `.github/workflows/release.yml`.
- **Version authority:** `tools/release_version.py`.
- **Tests:** `tests/test_ci_workflows.py`, `tests/test_release_version.py`.
- **Operator/implementation docs:** `docs/execution/first-release-plan.md`,
  `docs/execution/github-release-automation-plan.md`, `packaging/README.md`,
  `tools/README.md`.
- **Ledger and handoff:** `docs/execution/github-releases-feature-ledger.md` and this file.

## Review scope

The implementation review should inspect the current diff, the authoritative
release plan and ledger, all three workflows, the version authority, and the
structural tests. It should focus on executable workflow behavior and the
independent app/resource version contract; no runtime or database redesign is
in scope.

## Implementation-side validation already run

- Integrated release/version/workflow focus: **47 passed**.
- Full repository suite: **583 passed, 1 skipped**.
- Full Ruff and mypy gates: passed (mypy covered 135 source files).
- All workflow YAML files parsed successfully.
- Every workflow shell block passed `bash -n`.
- `git diff --check` passed with only expected line-ending/config warnings.

## Known limitations / operational caveats

- The existing `v0.1.0` tag points at stale commit `24ed285`; a human must
  correct that relationship before the first release. Actions never move it.
- `workflow_run` executes the default-branch `release.yml` revision. A tag
  pushed before that workflow is merged requires manual recovery.
- GitHub `releases/latest` follows tag commit/create-date ordering rather than
  publication order. A tag from an older commit may publish successfully without
  becoming `latest`; V1 documents this as an operational constraint.
- Desktop artifacts retain for 14 days; a recovery after expiry requires rerunning
  the tag build. KRDICT candidates retain for 30 days subject to repository
  limits, and published resources are thereafter copied from the public release.
- A failed draft or exact-six-asset check leaves the partial draft untouched for
  explicit repair/removal. The manual stale-candidate escape is deliberately
  narrow and audited.
- Publisher manifest parsing uses trusted default-branch `RemoteManifest`, not
  a parser shipped in the tag client. Repository contract tests protect the
  interface but do not prove compatibility with every future shipped parser.
- Command-substitution helpers that call `exit 1` rely on `set -euo pipefail` to
  propagate the failed assignment. Preserve that shell mode when maintaining or
  refactoring those helpers; this is an intentional R22 maintenance caveat.
- No GitHub Actions run, artifact upload, release publication, tag operation, or
  external API mutation was performed. Specifically, no commit, push, tag,
  workflow dispatch, or release was created or published.

## Suggested review targets

- Exercise automatic/manual collision outcomes and the no-op path.
- Verify normalized workflow provenance, recursive tag checks, and exact
  application run/tag SHA binding.
- Inspect candidate freshness, previous-release copying, final staged-byte
  validation, and six-asset draft verification.
- Confirm the Python 3.13 inert-metadata path and the unchanged installed-
  metadata path used by the build workflow.

## Post-implementation cleanup pass (2026-09-04)

A targeted cleanup, security, and UX pass ran over this diff before any commit.
It changed behavior in three places and simplified the workflow in several more.

**Application updates are installed in Hanly, not in a browser.** The check now
also reports whether the running installation *can* apply a build, and
`hanly_app.app_update` gained an installer that downloads the platform archive
through the existing release fetcher, verifies it against the release's
`SHA256SUMS`, unpacks it with the shared archive extractor, and stages it beside
the installation. Three delivery primitives in `update_service` were made public
for that reuse (`verify_checksum`, `extract_archive`, `activate_path`); no second
updater exists. The browser is now reachable only from a secondary "View release
notes" action, and only for a URL that is both the one the last check returned
and a `https://github.com/.../releases/...` page.

**Restart is classified, not assumed.** `restart_required` is part of the update
snapshot. A resource install stays hot-swappable and reports that no restart is
needed. An application install replaces the bundle holding the running
executable, so it stages, then hands the swap to a detached script that waits
for this process to exit, moves the new bundle into place, restores the previous
one on failure, and relaunches. The desktop's ordinary quit path is what runs.

**Release-lane hardening and simplification.** Every action in the three
release-lane workflows is pinned to a full commit SHA with its release named in
a trailing comment, and a structural test now fails if a floating tag returns.
Duplicated checks were removed where the same invariant was already proven:
the event-payload re-checks of `event`/`conclusion`/`head_repository` that the
job-level `if` already enforced; the second `build.yml` path check in the
tagged-version step; the `event`/`status` jq predicates that repeat REST query
parameters; the archive allowlist pass that the count checks already imply; the
staged-archive existence loop that the publish step repeats; the length check on
a literal six-element array; and the `$GITHUB_ENV` copy of a step output. The
manifest validator kept every `require`, including the redundant-but-explicit
`"url" not in resource`; only its four aliases for two objects were collapsed.
`pip install --upgrade pip` was dropped from the `contents: write` job.

**Other.** KRDICT candidate retention is now 30 days. `tools/krdict/inspect.py`
is `inspect_archive.py`, so the script bootstrap no longer works around a
standard-library shadow; the remaining `sys.path` insert exists only so a plain
`python tools/krdict/...` run can resolve `tools.krdict`, and says so.
`build_release_asset` names its step runner instead of asserting it is callable.
The dead `persist_resource_version` shim was removed. The Zstandard limits are
unchanged; only their comments were made exact. The agent ledger moved from the
repository root to `docs/execution/github-releases-feature-ledger.md`.

Gates after the pass: **661 passed, 1 skipped**; Ruff clean; mypy clean over 139
source files; all workflow YAML parses and every workflow shell block passes
`bash -n`. No commit, push, tag, workflow dispatch, or release was created.

## Correctness pass (2026-09-04)

A second pass fixed defects found while reviewing the cleanup. No architecture
changed.

- **KRDICT inspector.** It read pronunciation only from
  `WordForm/FormRepresentation` and categories from a `SubjectField/subject`
  element that does not exist, so both were reported empty for most of the
  dictionary. It now reads `WordForm/pronunciation` first and the entry-level
  `semanticCategory` / `subjectCategiory` features, matching `source.py`;
  `subjectCategiory` is the official misspelling. The single `category` field
  became `semantic_categories` and `subject_categories`.
- **`update_checks_enabled` is respected.** `_update_coordinator` takes
  `automatic_check`, wired to the persisted setting. The coordinator is still
  always built, so the explicit "Check for updates" works either way; only the
  unattended startup check is gated.
- **`restart_required` timing.** It was set when the install was scheduled. It
  is now set only after a build is staged with its handoff ready, and cleared
  on failure. Resource installs remain `false` throughout.
- **Application download bound to the checked release.** `stage()` re-reads the
  cached release payload and requires `tag_name == v<version>` before any
  download, so assets cannot come from a release the user never saw.
- **`RemoteManifest.from_payload`.** An object-form entry whose value is not a
  mapping raised a bare `TypeError`; it is now a `RemoteManifestError`.
- **`activate_path` for directories.** A failed cleanup of the displaced tree
  reported a completed swap as a failed activation. Cleanup after a live swap
  now goes through `_discard`, which cannot fail the operation. Rollback and
  file-resource behavior are unchanged.
- **Download size bound.** `GitHubReleaseFetcher` aborts mid-stream when a
  response exceeds the manifest's declared size.
- **Handoff script.** Paths now travel as process arguments rather than baked
  into batch text, which fixes non-ASCII install paths and removes the
  injection surface; the body is fixed ASCII. Windows waits are bounded, the
  first `move` is retried because the directory stays locked briefly after the
  process exits, and `timeout /t` was replaced by `ping` because it needs
  console input a detached process lacks. An install path containing characters
  `cmd.exe` cannot quote is refused rather than mishandled. On a failed
  replacement the restored previous bundle is relaunched; if the rollback
  itself fails, nothing is launched and the previous bundle stays under its
  `.previous` name for manual recovery.

Gates after the pass: **688 passed, 1 skipped**; Ruff clean; mypy clean over 139
source files. Three of the new tests execute the generated POSIX handoff script
end to end. No commit, push, tag, workflow dispatch, or release was created.

## Review assignment

Human-selected after implementation. Not started.
