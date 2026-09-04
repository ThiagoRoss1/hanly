# GitHub Release Automation Implementation Plan

> **For agentic workers:** Execute this plan through the Hanly execution flow in
> `docs/execution/05-execution-plan.md`. Do not add a second decomposition layer.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically publish one complete GitHub Release after a successful
`vMAJOR.MINOR.PATCH` desktop build while keeping KRDICT independently versioned
and avoiding a database rebuild for ordinary application releases.

**Architecture:** `build-krdict-resource.yml` remains a manual, non-publishing
producer used only when KRDICT changes. A successful tag build triggers
`release.yml`, which either promotes the newest staged KRDICT candidate or
copies the manifest and referenced database from the previous public release.
Every public application release therefore contains the application archives,
`hanly-resources.json`, and exactly one referenced KRDICT asset even when the
dictionary version did not change.

**Tech stack:** GitHub Actions YAML, GitHub CLI, GitHub Actions artifacts,
GitHub Releases, Python 3.13 for the publisher's data-oriented version proof
(the build/producer floor may remain Python 3.10), native `tomllib` (no
`tomli` dependency), pytest, PyYAML, existing `RemoteManifest` parsing.

**Spec:** `docs/execution/first-release-plan.md`, the completed HAN-38 plan and
handoff, and the approved clarification that application tags and KRDICT
versions advance independently.

## Global constraints

- Publish one public GitHub Release per application tag; do not create a second
  public resource-only release stream.
- Automatic publication listens only for a completed, successful, same-repository
  `push` run of the exact `.github/workflows/build.yml` workflow. Normalize a
  REST workflow path's optional `@ref` suffix before comparing it. A manually
  dispatched build run never publishes automatically.
- For an automatic run, `workflow_run.head_branch` must be exactly
  `vMAJOR.MINOR.PATCH`; prove that the existing tag ref resolves to the same
  `workflow_run.head_sha`, dereferencing annotated tags as needed. Require one
  unambiguous tag, not an arbitrary tag found by searching recent builds.
- A pushed application tag does not build KRDICT and does not imply that KRDICT
  changed.
- KRDICT changes only after a successful manual
  `build-krdict-resource.yml` run.
- Every public application release contains `hanly-resources.json` and the
  exact `.sqlite3.zst` asset referenced by that manifest.
- The first public release requires a staged KRDICT candidate because no prior
  public release exists to copy.
- An application-only release copies the previous release's manifest and
  referenced KRDICT bytes unchanged.
- A release following an intentional KRDICT producer run promotes that
  candidate; the application and resource versions remain independent.
- Users download only the application archive or source. First run discovers
  `hanly-resources.json` from GitHub Releases and downloads KRDICT when needed.
- Keep checksum, size, manifest-shape, schema-version, and canonical asset-name
  validation before publication.
- Never create or move a Git tag in Actions. Publication must use an existing
  `vMAJOR.MINOR.PATCH` tag whose version matches the package metadata.
- The privileged release workflow checks out trusted default-branch tooling and
  never executes tag-controlled source. It reads package metadata as data from
  the exact tag commit and verifies that data against the tag.
- An automatic run that finds an existing successful public release for its tag
  exits successfully as a no-op. Manual dispatches fail on any existing release,
  and either path fails on a draft or prerelease collision.
- Previous-release and collision absence is valid only for numeric HTTP status
  `404`; every other status or API error is fatal. Scope `GH_TOKEN` to the
  individual `gh` steps that need it, never at workflow or job scope.
- Never publish when the platform build failed, the resource cannot be proven,
  or the tag/build commit relationship is unclear.
- Create a draft release, verify the exact six release assets, then publish the
  draft. Set release concurrency to `cancel-in-progress: false`; a failed draft
  remains for explicit operator repair rather than being overwritten.
- A staged KRDICT candidate is retained for 30 days, subject to the repository's
  artifact-retention ceiling; after promotion, later releases copy its bytes
  from the public release instead of depending on the artifact.
- If a candidate has the same `resource_version` as the previous release but a
  different checksum, fail before publication; resource version identity must
  not conceal changed bytes from existing clients.
- Keep selection inside the existing workflow and extend the existing tested
  `tools/release_version.py` for the data-oriented tag proof; do not add a new
  Python helper/module or broaden this work into runtime, database, seed,
  provider, or resource-installation changes.
- Preserve a manual recovery dispatch, but automatic tag publication is the
  normal path.
- Do not change `hanly`, `hanly-app`, first-run, update, database-build, seed,
  provider, or resource-installation logic in this work.
- Implementation stops at the normal review handoff. Commit, push, tag,
  workflow dispatch, and release publication require separate human authority.

---

## Release behavior matrix

| Situation | Resource source | Result |
| --- | --- | --- |
| First application release, no override | Latest successful, default-branch KRDICT producer artifact | Publish app archives plus that manifest/database; if absent, expired, or invalid, fail with the bootstrap instruction |
| Any release with `resource_run_id` override | Exactly that successful, default-branch producer run | Publish it if provenance and validation pass; failure is fatal and never falls back |
| New app tag, no KRDICT update | Previous public release | Copy the previous manifest and referenced database unchanged |
| KRDICT producer created after the previous release was published | That staged producer artifact | Publish app archives plus the new resource version; missing/expired/invalid candidate is fatal |
| No candidate and no previous release | None | Fail without creating a release |
| Candidate invalid or unavailable | Do not silently downgrade during an explicitly requested promotion | Fail without creating a release |
| Automatic lookup finds no newer usable candidate | Previous public release | Publish app-only update with unchanged KRDICT |
| Automatic rerun finds an existing public release for the tag | None | Successful no-op; do not download or overwrite anything |
| Manual dispatch finds any existing release, or either path finds a draft/prerelease collision | None | Fail without overwriting the release |
| Publication fails after creating its draft | Existing partial draft | Leave it untouched; an operator repairs/publishes it explicitly or removes it before a new dispatch |

The producer run is a staged candidate, not a release. Dispatching the producer
means "make this validated KRDICT available for the next application release";
it never publishes by itself.

Candidate freshness is determined using GitHub-owned timestamps: compare the
producer run's creation/start timestamp (`createdAt` in `gh` JSON or
`created_at` in the REST payload) with the previous release's `published_at`,
parsed as UTC. Never use the release `created_at`; GitHub's `releases/latest`
selection follows its latest-by-tag-commit-date/create-date behavior rather
than a guarantee of publication order. A producer run strictly newer than the
previous release is an intentional pending candidate. If its artifact is
unavailable or invalid, publication fails instead of silently retaining the old
dictionary.

When no previous public release exists, the timestamp comparison is skipped: the
latest successful, default-branch producer run is the only eligible source. The
first-release selection order is explicit: reject contradictory manual overrides;
query `releases/latest`; on numeric HTTP status `404` select the latest producer run with
exact workflow/default-branch/completed-success provenance; validate its artifact
before creating a draft; and, if no candidate exists, fail before `gh release
create` while naming `build-krdict-resource.yml` as the required bootstrap
operation.

The previous release's KRDICT asset is copied byte-for-byte into the new release,
not referenced by URL. The runtime resolves `asset_name` against the same release
that supplied `hanly-resources.json`, and the canonical manifest forbids an
inline URL, so each public release must carry its own self-contained copy.

The repository currently has a stale `v0.1.0` tag pointing at `24ed285`. The human
must correct that tag/commit relationship before the first release; Actions must
never move or recreate it. Because first-run uses GitHub's `releases/latest`, tags
created from older commits can fail to become latest even when published later;
V1 therefore assumes application release tags follow the repository's normal
chronological ancestry, and treats older-commit hotfix publication as an explicit
operational constraint.

---

### Task 1: Specify the independent app/resource release contract in tests

**Files:**

- Modify: `tests/test_ci_workflows.py`

**Interfaces:**

- Consumes: the current YAML loader helpers and workflow structural assertions.
- Produces: executable structural requirements for the automatic and manual
  release paths.

- [ ] **Step 1: Replace the manual-only release trigger assertion**

  Assert that `release.yml` has both:

  ```yaml
  workflow_run:
    workflows: ["Build Desktop Artifacts"]
    types: [completed]
  workflow_dispatch:
    inputs:
      tag: {required: true, type: string}
      resource_run_id: {required: false, type: string}
      reuse_previous_release_resource: {required: false, default: false, type: boolean}
  ```

  Assert that the release job condition admits `workflow_dispatch` and admits an
  automatic event only when all of these are true: the event is `workflow_run`,
  `workflow_run.event` is `push`, `workflow_run.conclusion` is `success`,
  `workflow_run.head_repository.full_name` equals `github.repository`, and the
  triggering workflow is the exact build workflow after normalizing any REST
  path `@ref` suffix. A completed
  `workflow_dispatch` run of `build.yml` must not satisfy the automatic path.

  Assert that workflow-level concurrency is the global `release-publish` group
  and explicitly sets `cancel-in-progress: false`; do not derive the group from
  a tag or branch.

  Assert that `release.yml` grants only the permissions required for its two
  cross-run operations: `actions: read` for artifact/run provenance and
  `contents: write` for the one GitHub Release. The producer remains
  `contents: read`; no broader write permission is needed.

  Assert that the manual path remains available for recovery and an explicit
  resource override, and that its existing-release behavior differs from the
  automatic path: an existing successful public release is a successful no-op
  only for automation; manual dispatch fails. A draft or prerelease collision
  fails for either path.

- [ ] **Step 2: Assert automatic publication is tied to the triggering build**

  Add structural assertions proving that the automatic path uses
  `github.event.workflow_run.id` as the application artifact run and verifies:

  ```text
  triggering workflow path == .github/workflows/build.yml
  triggering repository == github.repository
  triggering event == push
  conclusion == success
  workflow_run.head_branch == vMAJOR.MINOR.PATCH
  triggering ref is an existing vMAJOR.MINOR.PATCH tag
  tag commit == triggering workflow head_sha
  package versions read from the exact tag commit == tag version
  ```

  The tag/ref check must handle both lightweight and annotated tags and require
  exactly one semver tag for the triggering SHA. It must not search for an
  arbitrary recent application build on the automatic path. Assert that the
  release checkout remains trusted default-branch tooling and that the version
  proof reads the fetched tag commit's `pyproject.toml` data without executing
  tag-controlled code.

- [ ] **Step 3: Assert the resource-selection order**

  Require one resource-resolution step with these observable branches:

  ```text
  manual resource_run_id supplied
      -> require exact producer workflow + default branch + success provenance
      -> download exactly that producer artifact or fail
  manual reuse_previous_release_resource == true
      -> require no resource_run_id override and a previous public release
      -> reuse the previous manifest/asset despite a newer invalid or expired
         candidate, recording the explicit operator decision in the summary and
         release notes
  no previous public release
      -> select latest successful producer with exact provenance, or fail with
         the build-krdict-resource.yml first-release instruction
  automatic path with producer createdAt/created_at > previous_release.published_at
      -> download and validate that candidate; expiry or failure is fatal
  otherwise, previous public release exists
      -> download its hanly-resources.json and referenced KRDICT asset
  otherwise
      -> fail before gh release create
  ```

  Assert that a manual resource-run override never falls back, the explicit
  manual `reuse_previous_release_resource` escape is mutually exclusive with
  `resource_run_id` and unavailable on automatic runs, and a newer automatic
  candidate never silently downgrades. Assert that a same-version candidate
  with a changed checksum fails by comparing the actual candidate and prior
  manifests. Assert that producer timestamps are compared with the previous
  release's `published_at`, never its `created_at`, and that the previous
  release comes from REST `GET /repos/{owner}/{repo}/releases/latest`.

  Assert that neither tag path invokes `build_seed.py`, `validate_seed.py`, or
  `package_resource.py`.

- [ ] **Step 4: Assert publication remains all-or-nothing**

  Require validation before `gh release create`, exactly one application
  archive for each of `windows`, `macos`, and `linux`, one
  `hanly-resources.json`, one referenced `krdict-*.sqlite3.zst`, and one
  `SHA256SUMS`. Require exact-six-asset verification after creating a draft and
  before publishing it. Require `--verify-tag`, no tag-creation/movement command,
  and a preflight collision check with these outcomes: automatic + existing
  public release is exit-0 no-op; manual + any existing release fails; draft or
  prerelease collision always fails. Assert that partial-draft recovery is
  documented rather than silently overwriting the draft.

- [ ] **Step 5: Run the focused tests and confirm the current workflow fails**

  Run:

  ```powershell
  .\.venv\Scripts\python.exe -m pytest tests/test_ci_workflows.py -q
  ```

  Expected: new automatic-trigger and resource-reuse assertions fail against
  the current manual-only `release.yml`; existing build/producer safety tests
  remain green.

- [ ] **Step 6: Add build-expression and shell-input safety assertions**

  Assert that the externally influenced `github.ref_name` in `build.yml` is
  routed through a step `env` variable, quoted, and absent as direct shell
  interpolation. Keep the closed workflow-controlled matrix literals unchanged;
  expressions for those literals may remain in action inputs and shell commands.
  Apply the no-direct-input interpolation assertion to producer and release
  shell scripts: workflow inputs, event values, and manifest-derived asset names
  must arrive through `env`, be validated before use, and be quoted or passed as
  array arguments.

---

### Task 2: Keep KRDICT production manual and mark its artifact as the next candidate

**Files:**

- Modify: `.github/workflows/build-krdict-resource.yml`
- Modify: `tests/test_ci_workflows.py`

**Interfaces:**

- Consumes: the existing HTTPS source URL, source SHA-256, deterministic build,
  validator, packager, and `hanly-krdict-resource` artifact.
- Produces: a validated resource candidate discoverable by the release workflow.

- [ ] **Step 1: Preserve the producer's non-publishing contract**

  Keep `workflow_dispatch` as its only trigger and retain `contents: read`.
  Continue uploading only:

  ```text
  producer-output/krdict-<resource-version>.sqlite3.zst
  producer-output/krdict.resource.json
  producer-output/validation-report.json
  ```

  The source ZIP and uncompressed SQLite database must never be uploaded.

- [ ] **Step 2: Make candidate intent and retention explicit**

  Give the run an identity containing `resource_version` (for example with
  `run-name`) and set `retention-days: 30`, subject to the repository's lower
  retention ceiling. The implementation must not depend on indefinite artifact
  retention: after one app release contains the candidate, later app releases
  copy it byte-for-byte from that public release.

  The release resolver must accept a candidate only when the selected run is
  the exact `.github/workflows/build-krdict-resource.yml` workflow, belongs to
  this repository's default branch, is a completed successful
  `workflow_dispatch` run, and still owns the named `hanly-krdict-resource`
  artifact. A run name is descriptive only; provenance comes from the run API.

- [ ] **Step 3: Add structural assertions**

  Test that the producer remains manual/non-publishing, its output artifact name
  remains `hanly-krdict-resource`, its manifest is included, `run-name` contains
  `inputs.resource_version`, and the upload retention is exactly 30 days. Test
  that no tag/app release trigger rebuilds or publishes the dictionary and that
  all producer shell inputs are env-backed rather than interpolated directly.

- [ ] **Step 4: Run the producer workflow tests**

  Run:

  ```powershell
  .\.venv\Scripts\python.exe -m pytest tests/test_ci_workflows.py -q
  ```

  Expected: producer contract tests pass.

---

### Task 3: Automate release publication after the tag build

**Files:**

- Modify: `.github/workflows/build.yml`
- Modify: `.github/workflows/release.yml`
- Modify: `tools/release_version.py`
- Test: `tests/test_ci_workflows.py`
- Test: `tests/test_release_version.py`

**Interfaces:**

- Consumes: a completed `Build Desktop Artifacts` run, an existing application
  tag, and either a staged producer artifact or a previous public release.
- Produces: one complete public GitHub Release for the existing application tag.

- [ ] **Step 1: Add automatic and recovery triggers**

  Configure `workflow_run` for completed `Build Desktop Artifacts` runs and
  retain `workflow_dispatch`. Normalize both events into these internal values:

  ```text
  RELEASE_TAG
  APPLICATION_RUN_ID
  APPLICATION_HEAD_SHA
  RESOURCE_RUN_ID_OVERRIDE (optional)
  REUSE_PREVIOUS_RELEASE_RESOURCE (manual boolean, default false)
  ```

  Set workflow permissions to `actions: read` and `contents: write` only. The
  producer keeps `contents: read` and never receives release-write authority.
  Set the workflow-level `concurrency.group` to the literal global
  `release-publish` group and set `cancel-in-progress: false`; do not derive
  concurrency from a tag or branch. The job condition must reject every
  `workflow_run` except a successful `push` run from this repository whose API
  path is exactly `.github/workflows/build.yml`; a successful manual build run
  is never an automatic publication trigger.

  For `workflow_run`, require a strict semver `head_branch`, derive the
  application run ID and head SHA from the event, and prove that the existing
  tag ref points to that SHA. Handle lightweight and annotated tags by peeling
  the latter, and fail if zero or multiple semver tags match. For recovery
  dispatch, resolve the successful build by the supplied tag's exact commit,
  not merely by the newest run on a branch.

  In `build.yml`, route only the externally influenced `github.ref_name` used by
  shell commands through a step-level `env` variable and quote it. Leave the
  closed workflow-controlled matrix literals as they are; expressions for those
  literals may remain in action inputs and shell commands. No shell `run` block
  may interpolate an event value or other untrusted input directly.

- [ ] **Step 2: Add publication preflight**

  Before downloading release inputs:

  ```text
  reject unsuccessful, non-push, cross-repository, or wrong-workflow automatic runs
  validate vMAJOR.MINOR.PATCH
  verify tag -> build head SHA (including annotated-tag peeling)
  fetch the exact tag commit object with git; parse its package metadata as data
  using trusted default-branch tooling; verify package versions/pins == tag
  classify any release collision
  ```

  Pin `actions/setup-python` in `release.yml` to `python-version: "3.13"` for
  the publisher; the lower build/CI/runtime floor must not force this job to
  Python 3.10. Check out the explicit repository default branch for trusted
  release tooling, never the supplied tag or a tag-selected ref. Do not
  checkout or execute the tag tree in this
  privileged `workflow_run` job. Fetch only the exact verified tag commit and
  read its `packages/hanly-app/pyproject.toml` and
  `packages/hanly/pyproject.toml` with `git show <verified-tag-sha>:<path>` as
  inert TOML data using native `tomllib` (do not add `tomli`). Extend the
  existing tested `tools/release_version.py` `verify_tag_metadata`
  data-oriented API/CLI with the parsed product project version, engine project
  version, and both app `hanly` pins. Require product and engine versions to
  equal the tag version, an exact `hanly==<version>` project dependency pin,
  and an exact `hanly[concrete]==<version>` runtime optional-dependency pin.
  Invoke only this inert-metadata mode (the `--app-version`,
  `--engine-version`, and pin arguments); never invoke the installed-metadata
  `product_version`/`verify_tag` path in the publisher.
  Add focused tests for matching values, each mismatching project version, and
  missing or wrong pins. Do not add a new helper module, and do not parse the
  tag tree with a tag-controlled parser.

  Query the release by tag before downloading assets. A confirmed public,
  non-draft, non-prerelease release is exit-0 no-op only for an automatic run;
  manual dispatch fails. A draft or prerelease collision fails for both paths.
  Treat absence as valid only for numeric HTTP status `404`; every other API
  error is fatal. All workflow inputs,
  event values, and manifest-derived names must enter shell scripts through
  `env`, never direct expression interpolation.

- [ ] **Step 3: Download the exact application artifacts**

  Use `APPLICATION_RUN_ID` with `actions/download-artifact` and require exactly
  these three archives after extraction:

  ```text
  hanly-desktop-windows.zip
  hanly-desktop-macos.tar.gz
  hanly-desktop-linux.tar.gz
  ```

  Reject missing, duplicate, or unexpected platform archives. A missing or
  expired cross-run artifact is fatal; recovery documentation must say to rerun
  the desktop build when its 14-day artifact has expired.

- [ ] **Step 4: Resolve the KRDICT source independently**

  Implement one explicit selection function in the workflow:

  1. If `RESOURCE_RUN_ID_OVERRIDE` is non-empty, verify the exact producer
     workflow/default-branch/completed-success provenance and download exactly
     its `hanly-krdict-resource` artifact. Failure is fatal; do not fall back.
  2. If the manual-only `reuse_previous_release_resource` boolean is true,
     reject any `resource_run_id`, query the previous public release, and copy
     its manifest and referenced asset. Require an existing public release and
     record the explicit operator decision, previous release tag, and reason in
     both the step summary and release notes; do not use this escape on the
     automatic path.
  3. For normal selection, query the previous public release with REST
     `GET /repos/{owner}/{repo}/releases/latest` (numeric HTTP status `404` means no
     previous release; any other API error is fatal). If none exists, select the
     latest successful producer run with the exact workflow/default-branch/
     completed-success provenance; if none exists, fail with a first-release
     instruction naming `build-krdict-resource.yml`. A missing/expired artifact
     or invalid candidate is fatal.
  4. If a previous release exists, inspect the latest successful producer run
     with exact workflow/default-branch/success provenance. Compare its GitHub
     creation/start timestamp (`createdAt`/`created_at`) strictly to the
     previous release's `published_at`. If newer, download and validate exactly
     that candidate; expiry or validation failure is fatal rather than a
     downgrade. Compare the actual candidate manifest to the actual prior
     manifest: a same-version candidate with a changed checksum is fatal.
  5. If no producer run is newer, obtain `hanly-resources.json` from the
     previous release, parse its `krdict.asset_name`, and download that exact
     asset from the same release. Copy both files byte-for-byte into the new
     release staging area; do not reference the old URL because the runtime
     resolves the asset name within the release that supplied the manifest and
     the manifest forbids an inline URL.
  6. If neither source exists, fail before `gh release create` with the same
     first-release instruction.

  Do not compare the application tag to the KRDICT version. They are separate
  identities by design. If a selected candidate's resource version equals the
  previous release's version but its checksum differs, fail before publication;
  a changed database must carry a new resource identity. The manual reuse
  escape is mutually exclusive with `resource_run_id`, manual-only, and
  fail-closed when no previous public release exists.

- [ ] **Step 5: Reuse the existing strict resource validation**

  Validate the chosen manifest and asset before publication:

  ```text
  manifest_version == 1
  resources contains exactly krdict
  no inline URL
  canonical krdict-<version>.sqlite3.zst asset_name
  sha256:<64 lowercase hex> checksum
  actual checksum == manifest checksum
  actual size == manifest size
  schema_version == 1
  positive expected_entry_count
  valid source_date
  RemoteManifest.from_payload accepts the payload
  ```

  Copy or download the selected manifest and resource into the final staging
  paths, then perform one strict validation of the canonical final staged
  manifest and resource bytes before any draft is created. Do not add another
  manifest generator or a separate pre-copy validation pass.

- [ ] **Step 6: Publish one complete release**

  Generate `SHA256SUMS` using published basenames. Write a release-notes audit
  section describing the selected producer run or previous release; when the
  manual reuse escape was requested, include the explicit boolean decision,
  previous release tag, and reason in both `release-output/release-notes.md`
  and `$GITHUB_STEP_SUMMARY`. Create a draft with exactly six assets, verify the
  draft's asset list by API, and only then publish the draft:

  Immediately before `gh release create`, recursively re-peel the existing
  application tag ref and recompare its final commit SHA with
  `APPLICATION_HEAD_SHA`; fail on any mismatch.

  ```bash
  gh release create "$RELEASE_TAG" \
    <three application archives> \
    <one KRDICT zstd asset> \
    release-output/hanly-resources.json \
    release-output/SHA256SUMS \
    --draft \
    --verify-tag \
    --title "Hanly Desktop $RELEASE_TAG" \
    --generate-notes \
    --notes-file release-output/release-notes.md
  # Verify exactly six asset basenames through the release API.
  gh release edit "$RELEASE_TAG" --draft=false
  ```

  The workflow must create neither a tag nor a separate resource release. The
  six exact names are the three application archives, one canonical
  `krdict-<version>.sqlite3.zst`, `hanly-resources.json`, and `SHA256SUMS`.
  If draft creation or asset verification fails after the draft exists, leave
  the partial draft untouched; a later automatic run fails on that collision,
  and an operator must explicitly repair/publish or remove it before dispatching
  recovery. No silent overwrite or tag movement is allowed.

- [ ] **Step 7: Run focused workflow tests and YAML parsing**

  Run:

  ```powershell
  .\.venv\Scripts\python.exe -m pytest tests/test_ci_workflows.py -q
  .\.venv\Scripts\python.exe -c "import pathlib, yaml; [yaml.safe_load(p.read_text(encoding='utf-8')) for p in pathlib.Path('.github/workflows').glob('*.yml')]"
  ```

  Expected: all workflow contract tests pass and every workflow parses. The
  structural scenarios must cover first release with a candidate, app-only
  reuse, candidate promotion, failed/expired candidate without downgrade,
  missing resource sources, failed platform build, mismatched/missing tag,
  automatic existing-public-release no-op, manual/collision failure, exact
  six-asset draft publication, partial-draft recovery, and changed bytes under
  an unchanged resource version. Also cover the manual reuse escape's
  mutual-exclusion, previous-release requirement, and summary/release-note
  audit trail, plus the Python 3.13 data-oriented version-proof path and its
  rejection of installed metadata.

---

### Task 4: Document the three release operations

**Files:**

- Modify: `docs/execution/first-release-plan.md`
- Modify: `packaging/README.md`
- Modify: `tools/README.md`

**Interfaces:**

- Consumes: the implemented automatic release and manual KRDICT producer
  behavior.
- Produces: exact operator instructions without implying that every app tag
  rebuilds or changes KRDICT.

- [ ] **Step 1: Document first-release bootstrap**

  Record this order:

  ```text
  dispatch Build KRDICT resource
  verify its manifest/checksum/count report
  push the corrected application tag
  wait for the platform build
  automatic release publishes app + staged KRDICT
  verify first-run download on a clean machine
  ```

  State that the existing `v0.1.0` tag points at stale commit `24ed285` and
  must be corrected by the human before this bootstrap; no Action moves or
  recreates the tag. Explain that GitHub's `releases/latest` is ordered by the
  release/tag commit-date behavior rather than publication order, so tags from
  older commits may not become latest; the first release must use the corrected
  chronological application tag. `workflow_run` executes the `release.yml`
  revision on the default branch, so a tag pushed before this workflow is
  merged there has no automatic publication; recover it manually after the
  workflow is available.

- [ ] **Step 2: Document an application-only release**

  Record this order:

  ```text
  bump package versions
  push vMAJOR.MINOR.PATCH
  automatic release copies prior hanly-resources.json and KRDICT unchanged
  ```

  State explicitly: do not dispatch the KRDICT producer merely because the app
  version changed.

- [ ] **Step 3: Document a KRDICT-plus-application release**

  Record this order:

  ```text
  dispatch Build KRDICT resource with new source identity
  verify candidate output
  bump/push application tag
  automatic release promotes the candidate alongside the new app archives
  ```

  State that a staged candidate is retained for 30 days, subject to the
  repository setting, and that after it is promoted later app-only releases
  copy the exact manifest and KRDICT bytes from the public release. A changed
  KRDICT database must use a new `resource_version`; the workflow rejects a
  same-version, changed-checksum candidate.

- [ ] **Step 4: Document recovery**

  Keep the manual `release.yml` dispatch for a failed automatic publication.
  It accepts the existing tag, a producer run ID override, or the manual-only
  boolean `reuse_previous_release_resource`. The boolean is mutually exclusive
  with the run-ID override, is permitted only when a previous public release
  exists, and is an explicit escape for an invalid/expired newer candidate; the
  operator's decision, previous release tag, and reason must appear in the step
  summary and release notes. An automatic rerun that already has a successful
  public release is a no-op; manual dispatch fails on any existing release, and
  draft or prerelease collisions fail for both paths. Re-running must never move
  the tag or overwrite an existing public release silently.

  Explain draft-first recovery: if draft creation or exact-six-asset verification
  fails, the partial draft remains untouched. An operator must explicitly repair
  and publish it, or remove it before dispatching recovery; no workflow path
  silently overwrites a partial draft. If the 14-day desktop artifact has
  expired, rerun the tag build before recovery. Resource candidates are retained
  for 90 days but, once published once, are copied from the public release.

- [ ] **Step 5: Scan active documentation for the old coupling**

  Run:

  ```powershell
  rg -n "every tag.*KRDICT|resource_run_id.*required|Each step is human-dispatched" docs packaging tools
  ```

  Expected: no active instruction claims every app tag requires a new KRDICT
  run or manual publication.

---

### Task 5: Convergence verification and review handoff

**Files:**

- Modify: the existing release-related review handoff selected by the Hanly
  execution flow; do not create parallel routine reports.

**Interfaces:**

- Consumes: Tasks 1-4.
- Produces: reviewable workflow automation with no external mutation.

- [ ] **Step 1: Run repository gates**

  ```powershell
  .\.venv\Scripts\python.exe -m pytest
  .\.venv\Scripts\python.exe -m ruff check packages packaging tests tools benchmarks
  .\.venv\Scripts\python.exe -m mypy packages packaging tests tools benchmarks
  git diff --check
  ```

- [ ] **Step 2: Perform static release scenarios**

  Demonstrate from tests/workflow structure:

  ```text
  first release + staged candidate -> complete release
  app-only tag + previous release -> same resource checksum/version
  new candidate + app tag -> new resource checksum/version
  same resource version + changed checksum -> fail before publication
  missing all resource sources -> no release
  failed platform build -> no release
  mismatched/missing tag -> no release
  automatic existing public release -> successful no-op
  manual existing release -> failure
  draft/prerelease collision -> failure
  manual reuse-previous escape -> explicit audit, no run-ID override, prior release required
  draft partial upload -> explicit repair/removal before recovery
  stale v0.1.0 tag -> human correction required; Actions do not move it
  release from older commit -> latest-order constraint documented
  workflow_run manual build or cross-repository run -> no publication
  annotated tag -> peeled head_sha proof
  ```

- [ ] **Step 3: Write the review handoff**

  Record changed files, trigger rules, the independent application/resource
  version contract, test results, and the fact that no tag, workflow, or release
  was created during implementation. Note the handoff caveat that publisher
  manifest parsing uses the trusted default-branch `RemoteManifest` parser,
  not a parser shipped in the tag client; repository contract tests protect the
  interface but do not prove the shipped parser is compatible.

- [ ] **Step 4: Stop at review**

  Do not commit, push, create/move a tag, dispatch either workflow, or publish a
  release until the human separately authorizes that mutation. In particular,
  no implementation shortcut may replace the trusted tag-commit data proof with
  execution of tag-controlled tooling.

---

## Acceptance criteria

- Pushing a valid application tag starts the existing platform build and, only
  after all three platform jobs succeed, automatically creates a draft,
  verifies exactly six assets, and publishes one complete GitHub Release. The
  automatic path accepts only a successful same-repository `push` run of
  `.github/workflows/build.yml`; manual build runs never auto-publish.
- Automatic reruns for an existing successful public release are successful
  no-ops; manual dispatches fail on any existing release, and draft/prerelease
  collisions fail without overwrite.
- An application tag alone never rebuilds KRDICT.
- An application-only release reuses the previous KRDICT version and exact
  bytes.
- A deliberately staged KRDICT candidate is promoted by the next application
  release without coupling its version to the app version.
- A newer staged candidate can never silently fall back to or downgrade to the
  previously released dictionary when its artifact is missing or invalid.
- A candidate with changed bytes cannot reuse the previous `resource_version`.
- Manual recovery may set `reuse_previous_release_resource` only without a
  `resource_run_id`, only when a previous public release exists, and only with
  an explicit reason recorded in both the step summary and release notes; all
  other combinations fail closed.
- The first release cannot publish without a validated KRDICT candidate.
- The previous public release is selected through REST `releases/latest` and
  always exposes `hanly-resources.json` and its referenced KRDICT asset, so
  first-run acquisition remains valid.
- The release workflow never creates or moves a tag, and its privileged tooling
  never executes tag-controlled code; Python 3.13/native `tomllib` reads the
  exact tag commit as data and the existing data-oriented
  `tools/release_version.py` verification rejects installed-metadata proof.
- Users need download only an application archive or source checkout; manual
  database installation remains optional.
- The manual release path remains available for recovery.
- No runtime/database/provider code changes are required.
