# Release Draft-and-Approval Lane Review Handoff

## Bundle

- Member issues: none — direct correction of the GitHub Release workflow
- Implementation ecosystem: Claude Code (Opus 5), single implementation run
- Date: 2026-09-04

## Implemented

- Split `release.yml` into `stage` (automatic, unprotected) and `finalize` (`needs: stage`, `environment: hanly-release`), with the manual KRDICT upload between them.
- `stage` reuses the successful tag build, validates the three platform archives, and creates or repairs a private draft. It never publishes and never writes `SHA256SUMS`.
- `stage` carries a previous public release's `hanly-resources.json` and the `.zst` it names into a **newly created** draft, so an application-only release needs no upload. A rerun that repairs an existing draft touches only the three application archives, so an operator's uploaded pair is never overwritten.
- `finalize` compares the published `SHA256SUMS` against the file it just generated, so a checksum file left on the draft by an earlier finalize cannot survive into a public release.
- `finalize` re-resolves the tag and its build from scratch, re-downloads the archives from that exact run, takes the resource pair from the draft, revalidates everything, writes `SHA256SUMS` last, uploads the six assets, asserts exactly six, and only then clears the draft flag.
- Moved the tag/build/release decisions into `tools/release_build.py`, so both halves share one implementation and the rules are testable without a real release.
- Removed the producer architecture: `.github/workflows/build-krdict-resource.yml`, `source_url`, `resource_run_id`, `reuse_previous_release_resource`, and the first-release requirement for a producer run.
- Adapted `validate_only` to the draft architecture: staging is read-only in that mode and requires the draft to exist already, finalize validates and stops, and nothing anywhere is created, uploaded, or replaced.
- Hardened the automatic no-op: it now demands the public release carry this commit's marker **and** exactly the six valid asset names, so a foreign, partial, or inconsistent public release fails instead of being passed over.
- `finalize` repeats the tagged version and pin validation rather than trusting staging, through the new `tools/tagged_metadata.py`.

## Main expected behavior

A tag build finishes, `stage` leaves a draft holding the three archives (plus the previous release's resource pair, when there is one), and stops. The operator attaches the two locally built KRDICT files if the dictionary changed, then approves the deployment. `finalize` revalidates from the tag up and publishes exactly six assets, or leaves the draft untouched and unpublished.

KRDICT is built locally from the manually acquired official ZIP. No workflow fetches a source archive, builds the database, or uploads the raw `krdict.sqlite3`.

## Architecture / seams touched

No application behavior changed. `packages/` is untouched.

- `tools/release_build.py` is new: `resolve_tag_commit`, `unique_semver_tag`, `verify_application_run`, `find_application_run`, `classify_release`, behind a `ReadOnlyAPI` protocol so tests inject a fake.
- A draft is identified by a `Hanly-Release-Commit: <sha>` line written into its body at stage time. `classify_release` reuses only a draft carrying the marker for the commit being released.

## Relevant files / diff areas

- `.github/workflows/release.yml` (rewritten), `.github/workflows/build-krdict-resource.yml` (deleted)
- `tools/release_build.py`, `tools/tagged_metadata.py` (new), `tests/test_release_build.py`, `tests/test_tagged_metadata.py` (new)
- `tests/test_ci_workflows.py` (release contract rewritten)
- `packaging/README.md`, `docs/execution/first-release-plan.md`, `docs/CODE-MAP.md`

## Implementation-side validation already run

- `python -m pytest` → 769 passed, 4 skipped.
- `python -m ruff check packages packaging tests tools benchmarks` → All checks passed.
- `python -m mypy packages packaging tests tools benchmarks` → no issues in 144 source files.
- All three workflows parse; `release.yml` exposes exactly `stage` and `finalize`.
- Read-only live exercise of the decision logic against `ThiagoRoss1/hanly`, creating nothing:
  - tag commit → `68bab7ff99a9e619f7651688a0fbca6f358880ad`
  - unique semver tag → `v0.1.0`
  - application run → **33929041113**, the run the recovery must reuse
  - stage decision → `create` (no release holds the tag)

## Known limitations / intentionally unvalidated areas

- **No part of this has run in Actions.** Nothing was dispatched, and the `hanly-release` approval gate, `gh release create --draft`, `gh release upload --clobber`, and `gh release download` from a draft are exercised only by structure and by the read-only checks above.
- **The draft marker is editable.** Finalization identifies the draft by the `Hanly-Release-Commit:` line in its body. An operator who rewrites the body and drops that line will see finalize refuse the draft. The draft's own notes now say so, but nothing enforces it.
- **`--method GET` and the external `jq` no longer appear in `release.yml`.** Both list queries moved into `tools/release_build.py`, which paginates through `Link` headers in Python, so the flag combination that failed cannot occur there any more. The two guards remain in `tests/test_ci_workflows.py` and still cover every workflow; they are now vacuous for `release.yml`. Pagination is covered by `tests/test_release_build.py`, which drives `GitHubAPI.get_all` through three pages of a stubbed opener, checks that only `rel="next"` continues a listing, and proves a semver tag on a second page is still found.
- **`validate_only` still requires approval**, because the checks it runs read the draft and therefore live in the protected job. It is a dry run, not an unprotected one, and it cannot run while a normal run for the same tag waits for approval.
- **The first finalization is the first real test of the resource validator against operator-produced files.** The validator itself is unchanged from the previous workflow, but it has never run against a manually attached pair.
- **`releases/latest` ordering.** Carrying the previous resource reads `releases/latest`, which GitHub orders by release/tag commit date rather than publication order. A release cut from an older commit may not be `latest`.

## Deviations from the instruction, with reasons

- **The tag/build resolution bash became a Python tool** rather than being duplicated in both jobs. The instruction asked for the finalize job to re-resolve independently and for the decision logic to be testable without a real release; ~110 lines of duplicated shell would have satisfied the first and defeated the second.
- **`reuse_previous_release_resource` was removed rather than kept.** Carrying the previous pair is now unconditional whenever a previous release exists, so the flag had nothing left to select.

## Suggested review targets

- `classify_release`: whether the body marker is the right identity for a draft, and whether any legitimate operator edit could remove it.
- The stage job's upload list: the three archives are named explicitly and the carried pair is appended only on the create branch. Confirm no path can reach `gh release upload` with a resource file during a repair.
- `tools/release_build.py` pagination against a repository with more than 100 tags.

## Operator sequence after this is committed

One run per tag holds the concurrency group, and it is never cancelled
automatically, so a second run for the same tag **queues behind a run waiting for
approval**. Pick one of the two orders below; do not interleave them.

### Approve directly (the supported first release)

1. Commit and push to `main`. `workflow_run` uses the default branch's copy of
   `release.yml`, so the new lane only exists once it is there.
2. Build KRDICT locally from the manually acquired official ZIP, producing
   `data/generated/krdict-20260819-v1.sqlite3.zst` and
   `data/generated/hanly-resources.json`. The source ZIP and `krdict.sqlite3`
   stay on the machine.
3. Actions → **Release Hanly Desktop** → **Run workflow**, `tag = v0.1.0`,
   `validate_only` unchecked. The existing `v0.1.0` tag is reused; nothing moves it.
4. `stage` finishes with a private `v0.1.0` draft holding the three platform
   archives from build run **33929041113**. No previous release exists, so no
   resource pair is carried and none is required yet.
5. Releases → the `v0.1.0` draft → **Edit** → attach both local files. Save.
   Leave the `Hanly-Release-Commit:` line in the body.
6. In the same run, approve the `finalize` job under **Review deployments**.
7. `finalize` revalidates from the tag up, uploads the six assets, and clears the
   draft flag. Confirm the release lists exactly: `hanly-desktop-windows.zip`,
   `hanly-desktop-macos.tar.gz`, `hanly-desktop-linux.tar.gz`,
   `krdict-20260819-v1.sqlite3.zst`, `hanly-resources.json`, `SHA256SUMS`.

### Dry run first

Steps 1-5 as above, then:

6. **Cancel the pending run.** Cancelling deletes nothing; the draft and its
   assets stay exactly as they are. This is what frees the concurrency group.
7. Dispatch again with `tag = v0.1.0` and `validate_only` checked, and approve
   it. Staging is read-only in this mode — it creates nothing, uploads nothing,
   and does not download the artifacts it would upload — and finalize validates
   the draft and stops. It requires the draft from step 4 to already exist.
8. Dispatch a third time with `validate_only` unchecked and approve. Staging
   reuses the draft and repairs only the three application archives, leaving the
   pair from step 5 untouched. Finalize repeats every check and publishes.

A failed validation leaves the draft intact and unpublished; fix the cause and
dispatch the same tag again. Later application-only releases skip steps 2 and 5
entirely — staging copies the previous release's resource pair into the new draft.

## Review assignment

Human-selected after implementation. Not started.
