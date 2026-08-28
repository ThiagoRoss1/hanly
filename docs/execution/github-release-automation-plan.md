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
GitHub Releases, Python 3.10, pytest, PyYAML, existing `RemoteManifest` parsing.

**Spec:** `docs/execution/first-release-plan.md`, the completed HAN-38 plan and
handoff, and the approved clarification that application tags and KRDICT
versions advance independently.

## Global constraints

- Publish one public GitHub Release per application tag; do not create a second
  public resource-only release stream.
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
- Never publish when the platform build failed, the resource cannot be proven,
  the release already exists, or the tag/build commit relationship is unclear.
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
| First application release | Latest successful, unexpired KRDICT producer artifact | Publish app archives plus that manifest/database |
| New app tag, no KRDICT update | Previous public release | Copy the previous manifest and referenced database unchanged |
| KRDICT producer completed after the previous release was published | That staged producer artifact | Publish app archives plus the new resource version |
| No candidate and no previous release | None | Fail without creating a release |
| Candidate invalid or unavailable | Do not silently downgrade during an explicitly requested promotion | Fail without creating a release |
| Automatic lookup finds no newer usable candidate | Previous public release | Publish app-only update with unchanged KRDICT |

The producer run is a staged candidate, not a release. Dispatching the producer
means "make this validated KRDICT available for the next application release";
it never publishes by itself.

Candidate freshness is determined using GitHub-owned timestamps: compare the
producer run's `createdAt` with the previous release's `published_at`. Never use
the release `created_at`, because GitHub derives that value from the tagged
commit rather than publication time. A producer run newer than the previous
release is an intentional pending candidate. If its artifact is unavailable or
invalid, publication fails instead of silently retaining the old dictionary.

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
  ```

  The automatic job condition must require a successful triggering build. The
  manual path remains available for recovery and an explicit resource override.

- [ ] **Step 2: Assert automatic publication is tied to the triggering build**

  Add structural assertions proving that the automatic path uses
  `github.event.workflow_run.id` as the application artifact run and verifies:

  ```text
  triggering workflow == Build Desktop Artifacts
  conclusion == success
  triggering ref is an existing vMAJOR.MINOR.PATCH tag
  tag commit == triggering workflow head_sha
  package version == tag version
  ```

  It must not search for an arbitrary recent application build.

- [ ] **Step 3: Assert the resource-selection order**

  Require one resource-resolution step with these observable branches:

  ```text
  manual resource_run_id supplied
      -> download exactly that producer artifact or fail
  automatic path with producer.createdAt > previous_release.published_at
      -> download and validate that candidate; failure is fatal
  otherwise, previous public release exists
      -> download its hanly-resources.json and referenced KRDICT asset
  otherwise
      -> fail before gh release create
  ```

  Assert that neither tag path invokes `build_seed.py`, `validate_seed.py`, or
  `package_resource.py`.

- [ ] **Step 4: Assert publication remains all-or-nothing**

  Require validation before `gh release create`, exactly one application
  archive for each of `windows`, `macos`, and `linux`, one
  `hanly-resources.json`, one referenced `krdict-*.sqlite3.zst`, and one
  `SHA256SUMS`. Require a preflight failure if the tag already has a release.

- [ ] **Step 5: Run the focused tests and confirm the current workflow fails**

  Run:

  ```powershell
  .\.venv\Scripts\python.exe -m pytest tests/test_ci_workflows.py -q
  ```

  Expected: new automatic-trigger and resource-reuse assertions fail against
  the current manual-only `release.yml`; existing build/producer safety tests
  remain green.

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

  Give the run an identity containing `resource_version`, and set artifact
  retention to the repository-supported long retention used for release
  candidates. The implementation must not depend on indefinite artifact
  retention: after one app release contains the candidate, later app releases
  can copy it from that public release.

- [ ] **Step 3: Add structural assertions**

  Test that the producer remains manual/non-publishing, its output artifact name
  remains `hanly-krdict-resource`, its manifest is included, and no tag/app
  release trigger rebuilds the dictionary.

- [ ] **Step 4: Run the producer workflow tests**

  Run:

  ```powershell
  .\.venv\Scripts\python.exe -m pytest tests/test_ci_workflows.py -q
  ```

  Expected: producer contract tests pass.

---

### Task 3: Automate release publication after the tag build

**Files:**

- Modify: `.github/workflows/release.yml`
- Test: `tests/test_ci_workflows.py`

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
  ```

  For `workflow_run`, derive the application run ID and head SHA from the event;
  resolve the tag by requiring one existing `vMAJOR.MINOR.PATCH` ref pointing at
  that SHA. For recovery dispatch, resolve the successful build by the supplied
  tag as the current workflow already does.

- [ ] **Step 2: Add publication preflight**

  Before downloading release inputs:

  ```text
  reject unsuccessful automatic builds
  validate vMAJOR.MINOR.PATCH
  verify tag -> build head SHA
  run python tools/release_version.py --tag "$RELEASE_TAG"
  reject an already-published release for the tag
  ```

  All workflow inputs must enter shell scripts through `env`, never direct
  expression interpolation.

- [ ] **Step 3: Download the exact application artifacts**

  Use `APPLICATION_RUN_ID` with `actions/download-artifact` and require exactly
  these three archives after extraction:

  ```text
  hanly-desktop-windows.zip
  hanly-desktop-macos.tar.gz
  hanly-desktop-linux.tar.gz
  ```

  Reject missing, duplicate, or unexpected platform archives.

- [ ] **Step 4: Resolve the KRDICT source independently**

  Implement one explicit selection function in the workflow:

  1. If `RESOURCE_RUN_ID_OVERRIDE` is non-empty, download exactly that
     `hanly-krdict-resource` artifact. Failure is fatal; do not fall back.
  2. On the automatic path, inspect the most recent successful
     `build-krdict-resource.yml` run and the previous latest public release. A
     producer whose GitHub `createdAt` is later than the release's
     `published_at` is the intentionally staged candidate. Download exactly its
     artifact; if it expired or fails validation, fail rather than downgrade.
  3. If no producer run is newer than the previous release, obtain
     `hanly-resources.json` from that release, parse its
     `krdict.asset_name`, and download that exact asset from the same release.
  4. If neither source exists, fail with a first-release instruction naming
     `build-krdict-resource.yml`.

  Do not compare the application tag to the KRDICT version. They are separate
  identities by design.

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

  Copy the producer manifest to `release-output/hanly-resources.json`. Do not
  add another manifest generator.

- [ ] **Step 6: Publish one complete release**

  Generate `SHA256SUMS` using published basenames, then call:

  ```bash
  gh release create "$RELEASE_TAG" \
    <three application archives> \
    <one KRDICT zstd asset> \
    release-output/hanly-resources.json \
    release-output/SHA256SUMS \
    --title "Hanly Desktop $RELEASE_TAG" \
    --generate-notes
  ```

  The workflow must create neither a tag nor a separate resource release.

- [ ] **Step 7: Run focused workflow tests and YAML parsing**

  Run:

  ```powershell
  .\.venv\Scripts\python.exe -m pytest tests/test_ci_workflows.py -q
  .\.venv\Scripts\python.exe -c "import pathlib, yaml; [yaml.safe_load(p.read_text(encoding='utf-8')) for p in pathlib.Path('.github/workflows').glob('*.yml')]"
  ```

  Expected: all workflow contract tests pass and every workflow parses.

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

- [ ] **Step 4: Document recovery**

  Keep the manual `release.yml` dispatch for a failed automatic publication.
  It accepts the existing tag and, only when explicitly needed, a producer run
  ID override. Re-running must never move the tag or overwrite an existing
  public release silently.

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
  missing all resource sources -> no release
  failed platform build -> no release
  mismatched/missing tag -> no release
  existing release -> no overwrite
  ```

- [ ] **Step 3: Write the review handoff**

  Record changed files, trigger rules, the independent application/resource
  version contract, test results, and the fact that no tag, workflow, or release
  was created during implementation.

- [ ] **Step 4: Stop at review**

  Do not commit, push, create/move a tag, dispatch either workflow, or publish a
  release until the human separately authorizes that mutation.

---

## Acceptance criteria

- Pushing a valid application tag starts the existing platform build and, only
  after all three platform jobs succeed, automatically publishes one complete
  GitHub Release.
- An application tag alone never rebuilds KRDICT.
- An application-only release reuses the previous KRDICT version and exact
  bytes.
- A deliberately staged KRDICT candidate is promoted by the next application
  release without coupling its version to the app version.
- A newer staged candidate can never silently fall back to or downgrade to the
  previously released dictionary when its artifact is missing or invalid.
- The first release cannot publish without a validated KRDICT candidate.
- `releases/latest` always exposes `hanly-resources.json` and its referenced
  KRDICT asset, so first-run acquisition remains valid.
- Users need download only an application archive or source checkout; manual
  database installation remains optional.
- The manual release path remains available for recovery.
- No runtime/database/provider code changes are required.
