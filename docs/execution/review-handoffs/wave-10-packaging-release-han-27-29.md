# Wave 10 Packaging, CI, and Release Review Handoff

## Bundle

- Member issues: HAN-27, HAN-28, HAN-29
- Implementation ecosystem: GPT execution flow; Sol coordination/integration with three direct Luna xhigh workers
- Date: 2026-08-23

## Implemented

- Added the production cross-platform PyInstaller onedir definition, frozen entry point, PaddleOCR-before-Qt runtime hook, and platform-aware build/archive command.
- Kept PaddleOCR models and KRDICT outside the application package as independently versioned resource artifacts.
- Added a Windows/macOS/Linux GitHub Actions build matrix that runs repository gates, builds the desktop package, and retains platform artifacts.
- Added a manual-only release workflow that consumes separate application/resource artifact runs and publishes application archives, three resource assets, `hanly-resources.json`, and `SHA256SUMS` only when explicitly dispatched.
- Added a local release-manifest generator with supported-kind validation, HTTPS asset URLs, streamed SHA-256 checksums, and the metadata shape consumed by `UpdateService`.

## Main expected behavior

- `python tools/build_package.py` produces `dist/<platform>/hanly-desktop/` plus a release archive under the stable `hanly-desktop-<platform>` name.
- The frozen process enters through the existing production composition and preloads PaddleOCR before any Qt import while retaining the required external `--runtime-config` seam.
- CI can independently build and retain Windows, macOS, and Linux application artifacts using the same packaging command.
- An explicitly dispatched release run can combine a successful application-artifact run with a separately owned resource-artifact run and generate updater-compatible release metadata without moving GitHub or compatibility policy into `hanly`.

## Architecture / seams touched

- Packaging freezes the existing `hanly_app.application.main`; it does not replace the generic composition or worker-owned provider factories.
- The package boundary remains `hanly-app -> hanly`; GitHub workflow/tooling remains outside the engine.
- Application and resource artifacts remain separate so `UpdateService` obtains remote bytes and `ResourceManager` remains the local validation authority.
- The preserved Windows bootstrap constraint is implemented as a PyInstaller runtime hook that establishes native DLL directories and invokes the existing non-fatal PaddleOCR preload before GUI startup.

## Relevant files / diff areas

- `packaging/hanly-desktop.spec`, `entrypoint.py`, `runtime_hook.py`, and `README.md`
- `tools/build_package.py` and `tools/build_release_manifest.py`
- `.github/workflows/build.yml` and `.github/workflows/release.yml`
- `tests/test_packaging.py`, `tests/test_ci_workflows.py`, and `tests/test_release_manifest.py`

## Implementation-side validation already run

- Focused Wave 10 convergence: 14 tests passed; focused Ruff and mypy passed; all workflow YAML parsed; packaging dry-run emitted the expected spec command.
- Real Windows PyInstaller build completed from the authoritative `.venv`; corrected onedir output was approximately 1.77 GB and its release ZIP was 642,199,500 bytes.
- Corrected frozen `hanly-desktop.exe --help` exited 0; Control Center assets were present; `resources/dev`, local PaddleX model caches, OCR model weights, and KRDICT SQLite were absent from the package.
- Full repository gate: `.venv\Scripts\python.exe -m pytest` -> 323 passed.
- Full repository gate: `.venv\Scripts\python.exe -m ruff check packages tests tools` -> passed.
- Full repository gate: `.venv\Scripts\python.exe -m mypy packages tests tools` -> passed for 82 source files.
- Full repository gate: `git diff --check` -> clean.

## Known limitations / intentionally unvalidated areas

- macOS and Linux packaging are represented by the same spec and platform-specific backend selection, but their matrix jobs were not run locally. HAN-30 owns launch, resource loading, lookup, and artifact inspection on all three platforms.
- The Windows frozen smoke verified packaged PaddleOCR preload and CLI startup, but did not run a full packaged lookup with production resource artifacts. Revisit in HAN-30 after HAN-27–29 are approved and real resource artifacts exist.
- No GitHub Actions run, release, upload, or remote update was executed. The release workflow is deliberately `workflow_dispatch` only; HAN-30 should exercise it using explicit application and resource run IDs.
- Production OCR/KRDICT resource archives are not created from developer caches. The release workflow requires separately produced `paddle_detection_model`, `paddle_recognition_model`, and `krdict` assets; their real content and end-to-end update behavior remain HAN-30 evidence.
- The application package is large. Record its final cross-platform sizes in HAN-30; optimize only under HAN-35 if completed-product measurements justify it.
- Real-terminal Ctrl+C on Windows, native tray/window interaction, popup placement over real Korean text, and the harmless Chromium/DirectComposition diagnostic retain their existing HAN-30/manual classifications.
- Windows open-SQLite replacement behavior and its controlled runtime teardown/rebuild remain unchanged.
- Manifest signing/provenance and archive extraction limits remain post-V1 hardening under their recorded triggers; this bundle adds neither.
- The existing HAN-19 target mapping and HAN-35 optimization/type/readability inventories remain settled and were not pulled into Wave 10.

## Applied Review Fixes

Deep review ran on human authorization after implementation. Each finding below
is Fixed now, Deferred with a trigger, or Dismissed.

### 1. The build matrix expanded to one job, not three — BUG, fixed

`build.yml` declared `python-version: ["3.10"]` as a matrix vector *and*
`platform`/`runner` under `include`. GitHub adds an `include` entry to every
combination whose original matrix values it does not overwrite; `platform` and
`runner` were not original matrix keys, so all three entries were applied to the
single base combination in order and the last one won. The matrix produced one
Linux job. Windows and macOS artifacts were never built, which is the whole of
HAN-28's acceptance criteria.

The existing test asserted `"platform: windows" in workflow` and passed against
a broken matrix — the defect and the test were compatible because the test read
text rather than structure.

Fixed by declaring one `include` entry per platform with no sibling vector.
`test_build_matrix_expands_to_one_job_per_desktop_platform` now asserts
`set(matrix) == {"include"}` and the exact platform/runner expansion.

*Not empirically confirmed:* no GitHub Actions run has been executed, here or in
the original bundle. The collapse is derived from GitHub's documented `include`
semantics. HAN-30 should confirm three jobs appear on the first dispatched run.

### 2. Every push built three multi-gigabyte packages — BUG, fixed

`build.yml` triggered on `push` and `pull_request` with no filter. Each job
installed the full desktop runtime, froze a ~1.77 GB onedir, and uploaded
`dist/` — which contained both the onedir tree *and* the 642 MB archive of that
same tree, so each platform artifact carried the payload twice. Correctness on
every push is already covered by `ci.yml` across four interpreters.

Fixed: the workflow now runs on `workflow_dispatch` and `push` of `v*` tags, and
retains only `dist/hanly-desktop-<platform>.{zip,tar.gz}`. The
`!dist/.pyinstaller` exclusions became unnecessary and were removed.

### 3. `if: always()` masked build failures — BUG, fixed

The upload step combined `if: always()` with `if-no-files-found: error`, so a
failed build produced a second, misleading "no files found" error on top of the
real one. Removed; the upload now runs only after a successful build.

### 4. Artifact verification proved nothing — fixed

The verification step was a single-line `python -c` that walked the whole 1.77 GB
tree with `rglob('hanly-desktop*')` and asserted only that *something* matched —
including the onedir directory itself, so it passed when no archive was created.
Replaced with an explicit check for the expected per-platform archive path, and
the build step now passes `--platform` from the matrix so the artifact path is
deterministic instead of host-detected.

### 5. `SHA256SUMS` listed staging paths, not asset names — BUG, fixed

Checksums were produced with `find`-relative paths such as
`release-inputs/app/hanly-desktop-windows/hanly-desktop-windows.zip`. A consumer
downloading published assets could not verify them with `sha256sum -c`. Now each
line is emitted from the asset's own directory, so the recorded name matches the
published asset.

### 6. A release could invent its own tag — BUG, fixed

`gh release create` creates a missing tag at the default branch head. The tag is
a free-text `workflow_dispatch` input independent of the two artifact run IDs, so
a typo would publish binaries under a ref that was never built or reviewed. The
publish step now fails unless the tag already exists.

### 7. `directory` resources could be published in a container no client unpacks — BUG, fixed

`UpdateService._extract_directory` unpacks with `zipfile` only, and installs every
other kind as the downloaded file itself. Nothing stopped the release workflow
from advertising `kind: directory` for a `.tar.gz` artifact — the failure would
have surfaced on a user's machine mid-update, after download and checksum
verification. `ResourceArtifact` now rejects a non-`.zip` directory resource at
construction, so the mismatch fails at release time.

### 8. Validated values were not the stored values — BUG, fixed

`_https_base_url` validated `value.strip()` and returned `value.rstrip("/")`, so
a base URL with surrounding whitespace passed validation and then produced a
malformed asset URL. `ResourceArtifact` had the same split: `resource_id`,
`kind`, and `version` were checked with `.strip()` but stored raw, so a padded id
became a manifest key with spaces. Both now normalize once and store what they
validated.

### 9. Asset-name validation lived in the wrong place — fixed

`build_manifest` resolved `asset_name or path.name` and validated it mid-loop.
The name is a property of the artifact, so `ResourceArtifact` now exposes
`published_asset_name` and validates it at construction. `build_manifest` reads
it and no longer re-derives it.

### 10. `packaging/*.py` was checked by nothing — fixed

`entrypoint.py` and `runtime_hook.py` are real Python frozen into the shipped
application, but `packaging/` was absent from both the ruff `include` list and
the mypy `files` list. Added to both, and to the gate commands in `ci.yml`,
`build.yml`, and `CLAUDE.md`. Two import-order violations surfaced immediately
and were fixed. The `.spec` is not a `.py` file and stays outside static
analysis, since it relies on PyInstaller's injected `SPECPATH` global; its syntax
is verified separately.

### 11. Dead native search paths — fixed

`runtime_hook.py` registered `torch/lib` DLL directories. Hanly has no torch
dependency; the paths were copied from a generic template and could only hide a
real gap in Paddle collection. Removed, and a test now asserts `torch` does not
reappear in the hook. The `_DLL_DIRECTORIES` list retains each handle for the
life of the process — that intent was undocumented and is now stated.

### 12. Redundant collection in the spec — simplified

`collect_all(package)` already returns dynamic libraries; the spec then called
`collect_dynamic_libs(package)` for the same package and appended the result.
The duplicates were removed later by `_unique`, so the output was correct but the
analysis ran twice per package. Removed. `collect_dynamic_libs` is still used for
PyQt6, which is not passed through `collect_all`.

### 13. `PackageLayout` normalized in `__post_init__`, so callers normalized too — simplified

The dataclass rewrote both fields through `object.__setattr__`, which meant its
declared types were not its real types. Callers compensated by pre-normalizing,
duplicating the work at every site, and typing the field honestly as `str | None`
broke every path property.

Replaced with a `PackageLayout.for_platform()` factory that normalizes once and
returns a plain, fully typed frozen dataclass. `build_command` and `run_build`
now take the layout instead of a repository-root/platform pair, which removes the
duplicate normalization and the reconstruction of a second layout inside
`run_build`.

Also in this file: `host_platform` reported `None` instead of the offending
platform when called with no argument, its `or normalized == "linux"` branch was
subsumed by the `startswith` check, `resource_archive_prefix` was an accessor
used only by a test asserting it equalled its own constant, and
`archive_application` sliced a compound suffix off a string to recover a base
name it could compose directly. All cleaned up.

### 14. `build_release_manifest` discarded its exit code — fixed

`if __name__ == "__main__": main()` dropped the returned status, unlike
`build_package.py`. Now `raise SystemExit(main())`.

### 15. Workflow tests asserted text, not behavior — replaced

`test_ci_workflows.py` matched raw substrings including exact indentation. Those
assertions passed against the broken matrix in finding 1, and would have broken
on any reformatting while still proving nothing. They are now structural: the
workflows are parsed with PyYAML and the tests assert the matrix expansion, that
artifact production is never automatic, that gates precede the build, that only
archives are retained, that no `if:` guards the upload, that release is
dispatch-only over two independent runs, that the tag is checked before
publishing, and that checksums use basenames.

This required `pyyaml` and `types-PyYAML` in the dev group. It also closes a gap:
nothing in the suite previously verified that the workflow YAML even parses — a
syntax error in `build.yml` or `release.yml` would have reached GitHub. The
release-workflow assertions moved out of `test_release_manifest.py`, which is now
only about the tool.

### 16. The manifest was never checked against its consumer — test added

HAN-29's acceptance criterion is metadata "consumed by the approved update flow",
but no test fed generator output to `RemoteManifest.from_payload`. The shape was
asserted by hand on both sides, so the two could drift apart silently.
`test_generated_manifest_is_accepted_by_the_update_service_contract` now builds a
manifest and parses it with the real consumer.

### Deferred, with triggers

- **Application/resource provenance.** The release tag, the application run id,
  and the resource run id are three independent inputs; nothing verifies that the
  build run's head SHA matches the tag. Requiring that match would be genuine
  supply-chain hardening, but the bundle explicitly defers manifest signing and
  provenance to post-V1, so only the tag-existence guard was added. Revisit with
  artifact signing.
- **`console=False` on Windows discards diagnostics.** The frozen executable is
  windowed on every platform, so `--help`, argument errors, and stderr from a
  failed `--runtime-config` produce no visible output on Windows. The handoff
  records `hanly-desktop.exe --help` exiting 0, which is consistent with output
  going nowhere. Revisit in HAN-30 with real launch-failure evidence; a console
  build or a log file are both options.
- **`find_resource` takes the first match.** `-print -quit` silently picks one
  file if an artifact directory holds several. The total-count check partly
  covers this. Revisit if resource artifacts ever ship variants.

### Dismissed

- **The build matrix pins Python 3.10.** Flagged but deliberately not changed —
  see *Interpreter selection* below. This is a decision, not a defect.
- **`excludes` in the spec.** PyInstaller matches top-level module names only, so
  vendored subpackages are unaffected.
- **Asset-name percent-encoding.** `quote` never escapes `_`, so
  `paddle_detection_model` survives unchanged. No bug.

## Interpreter selection — raised, not changed

`build.yml` freezes the shipped application on Python 3.10, but the only real
build recorded in this handoff was produced from the local `.venv`, which runs
**3.13**. The shipped interpreter has therefore never been exercised on the
version CI would ship. The two also resolve different dependency sets: numpy
requires `>=3.11` from 2.3 onward, so a 3.10 job installs an older numpy than
development uses.

Left at 3.10 deliberately. Whether paddlepaddle and PyQt6 publish wheels for a
given interpreter on macOS and Linux is not verifiable from this machine, and
guessing would trade a known-unvalidated combination for an unknown-broken one.

Worth separating two decisions that currently move together: `requires-python`
is a compatibility floor for the `hanly` library on PyPI, while the frozen
application's interpreter is a deployment choice. They need not match, and the
application can ship on a newer interpreter than the library supports. HAN-30
should settle this with real cross-platform wheel evidence.

## Post-review validation

```text
Local .venv (3.13, full desktop runtime extras)
  python -m pytest                                      338 passed
  python -m ruff check packages packaging tests tools    All checks passed
  python -m mypy packages packaging tests tools          Success: 84 source files
  git diff --check                                       clean

CI-equivalent venv (dev group + editable packages, no runtime extras)
  python -m pytest                                      322 passed, 13 skipped
  python -m ruff check packages packaging tests tools    All checks passed
  python -m mypy packages packaging tests tools          Success: 84 source files

mypy --python-version 3.10 / 3.11 / 3.12 / 3.13          Success: 84 source files each

python tools/build_package.py --dry-run --platform linux  expected spec command
packaging/hanly-desktop.spec                              compiles
```

Re-validated after the versioning pass; see *Versioning and Release Flow Pass*
below for the final numbers.

No PyInstaller build, GitHub Actions run, release, or upload was executed in this
pass. Every finding above is verified by tests, static analysis, or reading, not
by a real platform build — HAN-30 still owns that evidence.

## Versioning and Release Flow Pass

A follow-up pass established the product version, tied it to the release tag,
and wired the tag into the build/release chain. No commit, tag, dispatch, or
publication was performed.

### Authoritative version

Both packages previously declared the placeholder `0.0.0`. They now declare
**`0.1.0`**, with `packages/hanly-app/pyproject.toml` `[project] version` as the
single source of truth: `hanly-app` is the released product, and it already
pinned `hanly==<version>` exactly, so one product version across both packages
costs nothing and removes a second thing to keep in step. Tags are `v{version}`.

No `VERSION` file was added, no bump tooling was introduced, and nothing about
this depends on PyPI — the version identifies a desktop release, not an index
entry. `hanly` remains independently distributable later at whatever version
policy that decision brings; today it tracks the product.

The version is *read* through `importlib.metadata`, not by parsing TOML. That
keeps `tools/release_version.py` free of a TOML dependency the 3.10 floor would
otherwise require, and metadata is the same project metadata the pyproject
declares. The cost is that a stale editable install reports a stale version, so
`test_installed_metadata_matches_the_declared_source_of_truth` compares metadata
against the declared literal and says "reinstall the editable packages" when they
drift. CI installs fresh on every run, so the release gate never reads stale.

### Tag/version consistency

`tools/release_version.py` is the whole mechanism — one module, no framework:

```text
python tools/release_version.py                # prints 0.1.0
python tools/release_version.py --tag v0.1.0   # prints 0.1.0, exit 0
python tools/release_version.py --tag v0.1.1   # explains the mismatch, exit 1
```

`verify_tag` rejects a tag that names a different version, a tag that is not
`vMAJOR.MINOR.PATCH`, and an engine version that has drifted from the product
version. Pre-release and local version segments are deliberately unsupported
until a release needs them; the regex is one line and easy to widen.

Both workflows call it. `build.yml` checks on a tag push, before any artifact is
produced under that name. `release.yml` checks the dispatched tag before
publishing. The human types the version once, into the pyproject.

### Human release flow

```text
1. edit version in packages/hanly-app/pyproject.toml (and the hanly pins)
2. commit and push
3. create and push the matching tag v{version}
4. the tag push builds Windows, macOS, and Linux archives
5. dispatch release.yml with that tag and the resource run id
```

**One manual step remains, deliberately.** Steps 1-4 need no dispatch. Step 5
does, because resource archives — the Paddle models and the KRDICT database —
are produced and versioned outside this repository, so a tag push has no way to
supply them. Automating it would mean inventing a resource-production workflow
this bundle does not own.

What step 5 no longer needs is the application run id. `release.yml` resolves it
with `gh run list --workflow build.yml --branch <tag> --status success`, so the
published binaries come from the build that ran *for that tag*. This is a safety
improvement, not only ergonomics: the previous free-text `run_id` input could
pair a tag with a build of an entirely different commit.

Release title and notes were already derived — `Hanly Desktop <tag>` with
`--generate-notes`. Unchanged, and now asserted by a test.

### Release safety — all existing properties preserved

The tag-existence guard, exact per-platform artifact names, explicit resource
ids and kinds, the directory-must-be-zip rule, checksummed `SHA256SUMS` under
published asset names, HTTPS-only asset URLs, and the absence of secrets in
runtime configuration are all unchanged. Two properties were added: tag/version
agreement, and build-run provenance by tag.

Publication remains impossible from a normal push: `build.yml` triggers only on
`workflow_dispatch` and `v*` tags and holds `contents: read`; `release.yml` is
dispatch-only.

### Runtime configuration and first-run

`--runtime-config` was `required=True`, so a packaged user could not launch the
application without knowing a CLI flag. It is now optional and discovered:
`runtime.json` beside the executable, then in the existing settings directory
(`default_runtime_config_path` is `default_app_config_path` with a different file
name, so no new platform convention was invented). An explicit flag still wins,
and a failure names every location searched.

This makes the packaged app *launchable* without CLI knowledge. It does not
create the configuration or acquire the resources it points at.

**That first-run gap has no owner.** HAN-25 (Resource / Update UI Integration) is
Done and covered in-app update UI, not initial bootstrap; HAN-30 validates
startup rather than implementing it. A normal user still needs someone to place
a `runtime.json` and the resource files. This needs a new HAN — first-run
resource acquisition and configuration bootstrap — or an explicit HAN-30 scope
extension. Recorded here rather than absorbed into a packaging bundle.

### Frozen build interpreter — unchanged, still 3.10

Left at 3.10, as instructed and as the previous review concluded. The three
concerns stay separate and are recorded together here:

| Concern | Value | Authority |
| --- | --- | --- |
| Library minimum | `requires-python = ">=3.10"` | `pyproject.toml` of both packages |
| CI test matrix | 3.10, 3.11, 3.12, 3.13 | `ci.yml` |
| Frozen build interpreter | 3.10 | `build.yml` matrix |

The only real PyInstaller build evidence came from the local 3.13 `.venv`, so
the shipped interpreter remains unexercised at the version CI would ship. The
first real cross-platform build is the authoritative evidence; nothing was
changed for consistency alone.

### First real CI build must show

- A Windows archive, a macOS archive, and a Linux archive produced — three jobs,
  confirming the matrix fix from the previous review actually expands.
- Archive names matching `hanly-desktop-<platform>.{zip,tar.gz}` exactly, since
  `release.yml` selects assets by that pattern.
- A tag push failing the build when the tag and product version disagree.
- Packaged startup finding its runtime configuration by discovery, and loading
  the external Paddle/KRDICT resources it names.
- The Windows frozen build still satisfying PaddleOCR-before-Qt ordering and the
  bundled DLL-directory registration.

None of this is provable locally. It is HAN-30 evidence.

### Post-V1 measurement, not optimization

Recorded for measurement once real cross-platform artifacts exist. The ~1.77 GB
Windows onedir should trigger measurement, not speculative trimming:

- Paddle / PaddleOCR / PaddleX contribution, collected via `collect_all` for all
  three packages.
- Qt and QtWebEngine contribution.
- `collect_dynamic_libs("PyQt6")`, which is the one remaining explicit dynamic
  library sweep after the duplicate Paddle sweeps were removed.
- Any binaries or data present twice under different destinations; `_unique`
  removes identical source/dest pairs only.

### Packaging typing inventory — framework boundaries, not duck typing

Reviewed, deliberately not changed. These are dynamic PyInstaller boundaries, and
narrowing them would remove legitimate framework behavior:

- `_DLL_DIRECTORIES: list[object]` — holds `os.add_dll_directory` handles, whose
  type (`os._AddedDllDirectory`) exists only on Windows, so a precise annotation
  would need a platform-conditional type for a list that is never read.
- `getattr(sys, "_MEIPASS", ...)` — `_MEIPASS` is injected by the bootloader and
  absent from every type stub. The `getattr` fallback is also what makes the hook
  work when run unfrozen.
- The spec's PyInstaller globals (`SPECPATH`, `Analysis`, `COLLECT`) are injected
  into a controlled namespace; the file is not a module and stays outside mypy.

Distinct from accidental duck typing in our own code, which the previous review
already removed. `packaging/*.py` is now covered by ruff and mypy; only the
`.spec` is exempt.

### Not done in this pass

- **Resource versions are the release tag.** `release.yml` passes `$RELEASE_TAG`
  as each resource's `version`, but the architecture treats Paddle models and
  KRDICT as *independently* versioned artifacts. Deriving the real version from
  the documented `hanly-resources-<id>-<version>.<ext>` name would be the fix,
  and it should be written against artifacts that actually exist. HAN-30.
- **The frozen application cannot report its own version.** No dist-info is
  collected into the bundle, so `importlib.metadata` fails there. Not needed by
  V1 — the updater compares resource versions, not application versions — but it
  is the obvious prerequisite for an About box or an application self-update.

## Suggested review targets

- Inspect the spec and runtime hook for cross-platform native dependency collection and PaddleOCR-before-Qt ordering.
- Verify the build matrix retains only releasable outputs, not PyInstaller work caches, and uses the same archive names expected by the release workflow.
- Check that manual release inputs and resource naming make accidental/automatic publication impossible while producing the exact `UpdateService` manifest shape.
- Confirm external resource ownership is explicit enough for HAN-30 without embedding development assets or introducing a second compatibility authority.

## Review assignment

Human-selected after implementation. Deep review applied; stopping for human review. No commit, push, or merge.
