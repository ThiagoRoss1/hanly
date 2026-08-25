# Final V1 Beta Implementation and Validation Review Handoff

> **HAN-30 evidence update (2026-08-23).** The human has now confirmed that the
> current real GitHub Actions build completed for macOS, Linux, and Windows.
> This supersedes the earlier in-progress matrix snapshot below only for build
> completion. It proves that all three packaging jobs completed; it does not
> prove that any frozen desktop launches, provisions real resources, or performs
> OCR/lookup correctly. The remaining artifact/runtime checks are tracked in
> `docs/execution/reports/han-35/baseline.md` and remain human/external evidence.

## Bundle

- Member issues: HAN-36, HAN-37, HAN-30
- Predecessors closed at bundle start: HAN-27, HAN-28, HAN-29
- Implementation ecosystem: GPT execution flow; Sol coordination/integration, direct Luna xhigh implementation workers, and bounded read-only Sol Phase-A audits
- Date: 2026-08-23

## What was inspected first

- The current uncommitted worktree, `CLAUDE.md`, the execution plan, the GPT agent execution flow, the architecture/DAG documents, current review handoffs, and the current Linear issue/dependency state.
- The real `v0.1.0` tag-run evidence supplied by the human: macOS and Windows built; Linux failed during pytest collection because `PyQt6.QtWidgets` could not load `libEGL.so.1`; Windows built with Python 3.10.11 and PyInstaller 6.22.2 and produced an approximately 422 MB compressed Actions artifact.
- The old Windows artifact's clean-launch behavior: the extracted application had only `hanly-desktop.exe` and `_internal`, no adjacent `runtime.json`, and exited without a visible application or diagnostic after double-click.
- The release workflow's handling of Actions' outer artifact ZIP versus the actual application archives passed to a GitHub Release.

## Finding triage

### Already solved by the current final-bundle work

- **Discovery versus provisioning:** the current worktree creates a per-user runtime configuration, validates the required resources, provisions missing resources through the existing update path, revalidates them, and then enters the existing desktop composition.
- **Normal-user CLI knowledge:** a normal launch needs no `--runtime-config`. The explicit flag remains a power-user/development override and deliberately bypasses bootstrap and remote access.
- **Windowed startup failure visibility:** frozen startup errors reach a Qt critical dialog as well as stderr, and the failure path preserves PaddleOCR-before-Qt ordering. The old `v0.1.0` artifact does not contain this fix and is not evidence for it.
- **Independent resource versions:** resource versions now come from each resource artifact identity rather than being copied from the application tag.
- **Nested Actions artifact:** the build artifact wrapper may contain the project archive. The release workflow recursively selects the inner `hanly-desktop-<platform>` archives and passes those files directly to `gh release create`; it does not publish the Actions wrapper ZIP.

### Still real and fixed in this bundle

- **Linux runner native dependency:** the Ubuntu build job installed Python/PyQt6 but not the system library providing `libEGL.so.1`. The workflow now installs only `libegl1`, only for the Linux matrix member, with `--no-install-recommends`, before tests and packaging. A structural YAML test fixes the condition, command set, uniqueness, and ordering.

### Not pulled into V1

- Broad PyInstaller warning cleanup, package-size optimization, optional dependency pruning, Qt/Paddle collection redesign, benchmarking, native-backend exploration, visual polish, CLI expansion, broad typing/readability cleanup, signing/provenance, and archive-limit hardening remain HAN-35/post-V1 work unless real artifact evidence promotes one into a functional blocker.

## Implemented

### HAN-36 — first-run runtime resource bootstrap

- Added the application-owned bootstrap seam that reuses `ResourceManager`, `GitHubReleaseFetcher`, and `UpdateService`; no parallel resource system was introduced.
- A clean normal launch resolves or creates the per-user `runtime.json` under the existing settings convention, with production Paddle detection, Paddle recognition, and KRDICT resource destinations and the public `ThiagoRoss1/hanly` release coordinates.
- Missing or invalid resources are obtained and activated through the existing HTTPS-only, required-checksum, redirect-safe, staging, validation, safe-extraction, replacement, and rollback boundaries.
- Each successful activation records that artifact's independent `installed_version` atomically before the next resource starts, so partial failure and retry retain completed work.
- A repeat launch with valid resources constructs no fetcher and performs no remote request.
- Runtime composition and provider ownership are unchanged: validated paths/options enter the existing composition, while concrete providers remain worker-owned through factories.
- Frozen startup failures use a native Qt error dialog without changing the production application into a console executable and without regressing PaddleOCR-before-Qt ordering.

### HAN-37 — independent resource artifact versions

- `tools/build_release_manifest.py` derives versions from `hanly-resources-<resource-id>-<version>.<archive>` or accepts equivalent explicit metadata.
- Malformed, ambiguous, mismatched, duplicate, missing, or conflicting version identities fail before manifest publication.
- `release.yml` no longer passes `$RELEASE_TAG` as every resource version and requires exactly one artifact for each approved resource id.
- Mixed Paddle detection, Paddle recognition, and KRDICT versions are accepted by the real `RemoteManifest` consumer while the application tag remains the GitHub release identity.

### HAN-30 — final local/static validation convergence

- Incorporated the first real tag-run evidence without treating the old artifacts as evidence for the current uncommitted candidate.
- Fixed the observed Linux native-loader blocker with the minimum runner dependency.
- Reverified that final publication attaches the actual three application archives directly, not GitHub Actions' outer artifact wrappers.
- Preserved the successful Windows Python 3.10 build as packaging evidence for the preceding commit while requiring a new final-candidate run for the changed worktree.
- Classified the broad Paddle/PaddleX/Qt/PyInstaller warning inventory as non-blocking optional/backend/size noise absent a concrete packaged missing-import failure.

## Clean first-run behavior in the current worktree

On a clean Windows user profile with only a newly built package:

1. Double-click enters the existing frozen application entry point and preloads PaddleOCR before Qt.
2. With no explicit override, Hanly searches beside the executable and in `%LOCALAPPDATA%\Hanly`, then creates `%LOCALAPPDATA%\Hanly\runtime.json` when neither exists.
3. `ResourceManager` evaluates the two model directories and KRDICT database.
4. Missing/invalid artifacts are read from the public latest-release `hanly-resources.json`, downloaded over HTTPS, checksum-verified, safely staged/extracted, validated, and activated through `UpdateService`.
5. The runtime is reloaded and validated before the existing desktop composition starts.
6. A later launch uses the installed resources without reprovisioning while they remain valid.
7. A bootstrap/configuration/resource failure is rendered as a frozen Qt critical dialog with the exact error. stderr remains the development/terminal fallback.

This behavior is established locally with fake transport and composition-boundary tests. It is not yet proven against production resource archives or a newly frozen `console=False` executable. First-run provisioning is synchronous before the normal desktop appears; if real-resource timing makes the lack of progress UI a usability blocker, promote that evidence before RC. Otherwise progress polish remains HAN-35.

## Security and architecture invariants preserved

- `hanly-app -> hanly`; the engine does not acquire remote resources or depend on the desktop lifecycle.
- `ResourceManager` remains the authority for local resource state/compatibility. `UpdateService` obtains and activates remote artifacts.
- Remote resource and release-asset URLs require HTTPS, including redirects.
- Remote installs require checksums before extraction/activation.
- ZIP extraction rejects unsafe paths; staging destinations remain under the configured local resource parent.
- Staged resources are validated before activation; last-known-good backup/rollback behavior is unchanged.
- Public GitHub Releases require no secret in runtime configuration.
- The Windows runtime hook and startup/error paths retain PaddleOCR-before-Qt and native DLL setup.
- HAN-19's settled target-point/token behavior was not reopened. HAN-35 work was not pulled into this bundle.

## Validation evidence

### Focused implementation evidence

- HAN-36 bootstrap/application/runtime convergence: 48 passed; focused Ruff and mypy passed.
- HAN-37 release-manifest/version convergence: 14 passed; focused Ruff and mypy passed; workflow YAML parsed.
- Linux workflow fix: 16 focused workflow tests passed; focused Ruff and diff checks passed.
- Bounded release audit: 51 packaging/workflow/manifest/version tests passed; no new blocker found.
- Packaging command dry-run emitted the expected Windows PyInstaller spec command.
- `python tools/release_version.py --tag v0.1.0` returned `0.1.0` successfully.

### Full bundle-close gates

- `.venv\Scripts\python.exe -m pytest` -> **374 passed** on local Windows/Python 3.13.11.
- `.venv\Scripts\python.exe -m ruff check packages packaging tests tools` -> **passed**.
- `.venv\Scripts\python.exe -m mypy packages packaging tests tools` -> **passed for 88 source files**.
- `git diff --check` -> **clean** (line-ending conversion warnings only).

### Real evidence already available

- The tag-triggered matrix expanded to all three platforms.
- macOS and Windows completed for the old `v0.1.0` commit.
- Windows froze successfully with Python 3.10.11 and PyInstaller 6.22.2.
- The Windows project archive was created and retained inside the expected GitHub Actions artifact wrapper.
- Linux failed before packaging specifically because the runner lacked `libEGL.so.1`; no Hanly Qt-code failure was demonstrated.

## Remaining external/manual evidence before release-candidate approval

The current `v0.1.0` tag still names commit `c0ece45`; its existing artifacts do not contain this final worktree. The human-owned next validation is:

1. Commit and push the approved final tree, then create a new matching version/tag or deliberately replace the still-unpublished test tag according to the established version workflow.
2. Confirm the final tag builds on Python 3.10 for Windows, macOS, and Linux, with Linux now passing Qt test collection and packaging.
3. Produce exactly three correctly laid-out, independently versioned resource artifacts. Model ZIP contents must place Paddle model files at the activated archive root rather than under an extra wrapper directory.
4. On a clean-ish Windows profile, extract the final archive, double-click `hanly-desktop.exe`, verify visible first-run behavior, real HTTPS acquisition, config/resource state, tray, Control Center, OCR, Korean lookup, popup, hover/hotkey, and offline repeat launch.
5. Force a startup/resource failure in the final `console=False` Windows artifact and verify the native error dialog is visible.
6. Smoke-test the macOS and Linux frozen archives and platform lifecycle/backend behavior.
7. Recheck real-terminal Ctrl+C/SIGINT shutdown on Windows; the earlier non-terminal probe remains invalid evidence.
8. Treat the known Chromium DirectComposition message as an external harmless diagnostic unless behavior changes.
9. Manually dispatch `release.yml` only after validation, then inspect that the GitHub Release directly contains the three application archives, three resource assets, `hanly-resources.json`, and `SHA256SUMS`.

No commit, push, merge, tag operation, workflow dispatch, artifact upload, or GitHub Release publication was performed by the implementation agents.

## Deferred findings and owners/triggers preserved

- **HAN-31 / human RC gate:** final tagged three-platform build, production resource delivery, clean frozen launch/lookup, platform lifecycle, and release-asset inspection evidence.
- **HAN-32 / human release gate:** actual V1 release only after HAN-31 approval.
- **HAN-35 / post-V1:** package-size and collection optimization; check-for-updates performance; first-run progress/polish; broader typing/readability cleanup; benchmarking; native backend exploration; CLI expansion; application-version/About/self-update work; signing/provenance; archive extraction limits; and other recorded hardening.
- **Manual platform triggers:** real tray, popup placement, hotkey, hover, multi-monitor, SIGINT, and Windows open-SQLite replacement behavior remain evidence work against produced artifacts.
- **External diagnostic classification:** Chromium DirectComposition remains harmless unless a functional symptom appears.

No remaining implementable pre-V1 blocker was found in the repository. What remains is external resource production, final tagged cross-platform evidence, frozen/manual validation, and the human RC/release gates.

## Applied Deep Review

Deep review ran on human authorization after implementation. The bundle is
sound: the bootstrap reuses the existing seams as claimed, the version contract
holds at the `RemoteManifest` boundary, and no security property regressed. The
findings below are Fixed now, Deferred with a trigger, or Dismissed.

### 1. A mis-packed model archive installs, validates, and fails silently — FIXED

`ResourceManager` validates a `directory` resource as *exists, is a directory,
is readable* (`resource_manager.py:431`). Nothing inspects its contents, and
`spec.configuration` — which already carries `model_name` — is opaque
pass-through never used for validation. A Paddle model ZIP packed as
`PP-OCRv5_mobile_det/<files>` instead of `<files>` therefore:

1. downloads over HTTPS, checksum verified;
2. extracts safely and activates;
3. validates as `VALID`;
4. lets the desktop start;
5. fails only later inside PaddleOCR, with no link back to the packaging error.

Item 3 of the remaining-evidence list already names the correct archive layout as
a manual requirement. The point was that the layer whose job is validation could
not detect the single most likely mistake in a hand-built archive, so the
requirement rested on human care alone.

**Decision taken (human, second review pass): apply the narrow root-file
check.** `_require_model_files_at_root` in `hanly_app/runtime.py` runs inside
`load_runtime`, after the existing all-valid check and before any provider
option is built. It requires each of the two model directories to hold at least
one regular file directly at its root. It is filename-agnostic — no Paddle
naming, no knowledge of `inference.*` — so it rejects an empty directory and a
wrapper-nested archive without encoding any model's layout. It lives in the app
layer, not the engine, so no approved `ResourceSpec` contract changed; because
`load_runtime` runs at every startup and again when bootstrap reloads, it covers
both first run and repeat launch.

The five `test_runtime.py` tests whose fixtures created empty model directories
now go through a single `_model_directories` helper that writes a placeholder
`inference.pdiparams`. The helper's docstring records that the file name is
irrelevant to the check. Two tests were added for the invariant itself: a
wrapper-nested layout and an empty model directory, both asserting the named
startup error rather than a later PaddleOCR failure.

**Still manual (HAN-30):** confirm against a real Paddle model directory that no
valid layout nests its files below the resource root. `packaging/README.md`
records the requirement and now states that startup enforces it.

### 2. Bootstrap ignores a user-configured release channel — DEFERRED

`bootstrap_runtime_config` builds its `GitHubReleaseFetcher` from the module
constants, not from the `updates.github` block of the configuration it just
loaded. On a genuine first run these agree, because bootstrap wrote both. On a
*repeat* run where resources went invalid and the user has since pointed
`updates.github` at a different channel, bootstrap silently uses the hardcoded
coordinates while the in-app updater (`load_update_service`) honours the
configuration. Two sources for one fact.

Not changed: reading the channel from a configuration that may itself be the
reason resources are invalid is a defensible bootstrap decision, and no V1 user
has a second channel. Revisit if a non-default channel is ever supported.

### 3. Bootstrap can try to write into the installation directory — DEFERRED

`discover_runtime_config` prefers `runtime.json` beside the executable. When it
finds one there, `_persist_resource_versions` writes `installed_version` back to
that same path. In a per-machine install (`Program Files`, `/opt`) that path is
not user-writable, so a successful download would be followed by
`RuntimeBootstrapError` from the version write — after the bytes were already
activated. The next launch revalidates and recovers, so this is a confusing
error rather than data loss.

Not changed: V1 ships an extracted archive, not an installer, so no
non-writable location exists yet. Revisit when a real installer lands.

### 4. Startup failure is refused for an unrelated invalid resource — DISMISSED

`_resource_specs` builds specs for every entry under `resources`, so
`manager.all_valid` covers extras a user added. An invalid extra resource fails
bootstrap even though the three required resources are fine. Correct as written:
`load_runtime` applies the same all-valid rule, so bootstrap succeeding where
startup would fail is the worse outcome.

### 5. `ResourceArtifact.version` was typed `str | None` but never None — FIXED

The dataclass declared `version: str | None` so `None` could mean "derive it
from the asset name". `__post_init__` then always produced a string, which left
the field's declared type contradicting its real invariant and forced a dead
guard in `build_manifest` (`if resource.version is None: raise`) plus a manual
`isinstance` check the loop above already performs.

This is the same shape as the `PackageLayout.__post_init__` finding from the
Wave 10 review, and it is fixed the same way: `ResourceArtifact.from_asset_name`
derives the version and passes a real `str`, so `version: str` again. The
explicit-version-versus-asset-name conflict check is unchanged and still tested;
`__post_init__` lost two branches and `build_manifest` lost its unreachable
guard. `_resource_spec_from_name` now calls the factory, and the test that used
the `None` sentinel calls it directly, which reads as what it means.

### 6. `_missing_runtime_config_message` became dead code — FIXED

`main()` no longer has a "no configuration found" branch: it falls back to
`default_runtime_config_path()` and lets bootstrap create the file. The helper
survived the rewrite and was called from nowhere. Removed.

### 7. `cast(Any, ...)` in the new Qt failure dialog — FIXED

`_show_native_startup_error` cast the whole `QApplication.instance()` expression
to `Any` to reach `activeWindow()`, which the typed base class does not expose.
Narrowed to an `isinstance` check that yields a real parent or `None`, so no
broad `Any` enters the failure path. The local binding that keeps a
self-created `QApplication` alive across the modal call is preserved, with the
comment corrected to say why it exists.

### 8. Unreachable guards after the new `find_resource` — FIXED

`find_resource` was hardened to require exactly one match and `return 1`
otherwise. Under `set -euo pipefail`, a failing command substitution in an
assignment aborts the step immediately, so the three following
`test -n "$detection" || …` lines could never run — and they carried the *less*
informative message. Removed after confirming the behaviour in a local bash
harness across zero-match, two-match, and one-match cases.

### Verified, not changed

- `installed_version` is a real `ResourceSpec` field consumed by
  `ResourceManager` (`resource_manager.py:413,428`), not invented metadata.
- `metadata[resource_id]` in `bootstrap_runtime_config` cannot raise `KeyError`:
  `_resource_manager_from_payload` already requires all three ids and its
  `RuntimeConfigError` is caught and wrapped.
- `preload_ocr_runtime` on the failure path is idempotent — it is an
  `importlib.import_module` behind the `sys.modules` cache.
- `check_for_updates` returns every manifest resource regardless of
  availability, so building `remote` from all items is correct.
- Published asset names match the manifest: `gh release create` publishes each
  file under its basename, and `published_asset_name` falls back to
  `path.name` for the same file.
- The `.tar.gz` entry precedes `.zip` in `RESOURCE_ARCHIVE_SUFFIXES`, so a
  `1.0.tar.gz` remainder yields `1.0` rather than stopping at a shorter suffix.
- `libegl1` is installed only for the Linux matrix member, before tests and
  packaging, with `--no-install-recommends`.

### Post-review gates

```text
Local .venv (3.13, full desktop runtime extras)
  python -m pytest                                      375 passed
  python -m ruff check packages packaging tests tools    All checks passed
  python -m mypy packages packaging tests tools          Success: 88 source files
  git diff --check                                       clean

CI-equivalent venv (dev group + editable packages, no runtime extras)
  python -m pytest                                      359 passed, 13 skipped
  python -m ruff check packages packaging tests tools    All checks passed
  python -m mypy packages packaging tests tools          Success: 88 source files

mypy --python-version 3.10 / 3.11 / 3.12 / 3.13          Success: 88 source files each

python tools/build_package.py --dry-run --platform linux  expected spec command
python tools/release_version.py --tag v0.1.0              0.1.0
```

No PyInstaller build, GitHub Actions run, tag, dispatch, or publication was
performed.

## Second review pass

A follow-up review ran on human authorization over the same uncommitted tree.
It settled the one open decision above and applied four further changes. No
security property, architecture boundary, or approved engine contract moved.

### 9. `bootstrap_runtime_config` mixed five responsibilities — FIXED

The function ran to roughly ninety lines covering config creation, manager
loading, target selection, fetcher construction, manifest compatibility checks,
the install loop, version persistence, and the reload/revalidate step. It is now
a readable sequence over named helpers: `_load_manager`, `_install_resources`,
`_require_deliverable_resources`, `_public_release_fetcher`, and
`_persist_resource_version`. `PUBLIC_RELEASE_CHANNEL` replaces four
`f"{PUBLIC_REPOSITORY_OWNER}/{PUBLIC_REPOSITORY_NAME}"` repetitions in error
messages. Behaviour is unchanged and covered by the existing bundle tests.

`_persist_resource_versions(path, remote, [resource_id])` took a mapping and a
one-element list to write one field; it is now
`_persist_resource_version(path, resource_id, version)`, with the JSON
reread/shape validation split into `_runtime_payload_for_update`.

### 10. "remain invalid after provisioning" was reported without provisioning — FIXED

`_invalid_resources_message` was reused for two different situations. On the
path where the three required resources are valid but an unrelated declared
resource is not — finding 4's dismissed-and-intentional case — nothing had been
downloaded, yet the user was told resources "remain invalid after provisioning",
which points at the release channel instead of at their own configuration. The
helper now takes the summary as an argument: "runtime resources are invalid"
before provisioning, "runtime resources remain invalid after provisioning" after
it.

### 11. `main()` branched twice on the same condition — FIXED

`main` tested `args.runtime_config is None` once to pick a path and again inside
the `try` to decide whether to bootstrap. The decision now lives in one place,
`_resolve_runtime_config`, which returns an explicit operator path untouched and
otherwise bootstraps the discovered or default path. The rule that an explicit
`--runtime-config` creates no files and makes no release request is stated once,
where it is applied.

### 12. Finding 5 reintroduced the pattern it removed — FIXED

The `ResourceArtifact.version` fix restored `version: str` and removed a dead
`is None` guard, but added `isinstance(..., str)` guards for `resource_id`,
`kind`, `version`, and `asset_name` in `__post_init__`. With the declared types
restored, no caller can reach them: the CLI parses `str` fields out of a
`split("|")`, and every other construction is typed. They were also untested.
Removed, which matches `ResourceSpec.__post_init__` in the engine — it calls
`.strip()` on a declared `str` with no isinstance guard.

### New coverage added

- Model layout: wrapper-nested archive and empty model directory both rejected
  at startup (`test_runtime.py`).
- A release manifest advertising the wrong `kind` for a required resource is
  refused before any download (`test_resource_bootstrap.py`).
- An invalid *extra* declared resource fails bootstrap with the pre-provisioning
  message and without constructing a fetcher — locking in finding 4's dismissal
  as deliberate behaviour rather than an accident.
- `test_native_startup_reporter_preloads_ocr_before_nonblocking_qt_dialog` was
  renamed: `QMessageBox.critical` is modal, so the name asserted the opposite of
  what the code does.

### Verified again, unchanged

- `preload_ocr_runtime` on the failure path cannot raise: it catches broad
  `Exception` and returns a diagnostic string, so `_show_native_startup_error`
  calling it outside its own `try` cannot escape `main`'s handler.
- An offline first run is reported with context, not as a bare `URLError`:
  `GitHubReleaseFetcher._json` wraps `OSError` in `RemoteManifestError`, which
  `_install_resources` turns into a `RuntimeBootstrapError` naming the channel.
- `_persist_resource_version` skipping an entry that pins `version` is required,
  not cosmetic: `ResourceSpec.required_version` is compared against the observed
  version, so writing a release identity into a pinned entry would mark the
  freshly installed artifact `OUTDATED` and fail the revalidation that follows.
  The comment now says so.

### Second-pass gates

```text
Local .venv (3.13, full desktop runtime extras)
  python -m pytest                                      379 passed
  python -m ruff check packages packaging tests tools    All checks passed
  python -m mypy packages packaging tests tools          Success: 88 source files
  git diff --check                                       clean (line-ending warnings only)

mypy --python-version 3.10 / 3.11 / 3.12 / 3.13          Success: 88 source files each

python tools/build_package.py --dry-run --platform linux  expected spec command
python tools/release_version.py --tag v0.1.0              0.1.0
```

No PyInstaller build, GitHub Actions run, tag, dispatch, or publication was
performed in this pass either.

## Review assignment

HAN-30, HAN-36, and HAN-37 are ready for the existing human review/approval gate. Phase-A implementation and bounded integration checks are complete. Both deep-review passes are applied above and no finding is left open: the model archive layout decision was taken by the human and the check is in the tree. Stopping for human review. No commit, push, merge, tag, dispatch, or publication.

**V1 beta implementation complete; remaining items are validation/release evidence only.**
