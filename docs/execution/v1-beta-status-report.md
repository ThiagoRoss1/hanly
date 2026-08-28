# Hanly V1 / Beta — Status Report

Snapshot of the **uncommitted worktree** on top of `c0ece45`, written at the end
of the V1 closing review passes (updated after the second pass). Nothing has
been committed, pushed, merged, tagged, dispatched, or published.

Throughout: **Proven** means observed in this repository or a real Actions run.
**Inferred** means reasoned from code and documented behaviour, not executed.

---

## 1. Current V1 status

### Implemented and stable

| Area | State |
| --- | --- |
| Engine (`hanly`) | OCR/morphology/dictionary providers behind seams, `LookupPipeline`, `ResourceManager`, contracts — Waves 1–3, all `Done` in Linear |
| Desktop (`hanly-app`) | Capture, hotkey, hover, popup, tray, Control Center, lifecycle, update coordinator — Waves 4–9, all `Done` |
| Packaging | PyInstaller onedir spec, frozen entrypoint, Windows runtime hook, `tools/build_package.py` |
| CI | `ci.yml` gates on 3.10–3.13; `build.yml` three-platform matrix on tag push / dispatch |
| Release | `release.yml` dispatch-only, tag-resolved build, checksummed manifest, `SHA256SUMS` |
| Versioning | Single product version `0.1.0`, `v{version}` tags, `tools/release_version.py` gate |
| First-run bootstrap | `first_run.py` creates the per-user config and provisions resources |
| Independent resource versions | Derived from the documented artifact name, not the app tag |

### Effectively complete

- **HAN-27 / 28 / 29** (packaging, build matrix, release infra) — `In Review`,
  reviewed in the previous pass, defects fixed.
- **HAN-36** (first-run bootstrap) and **HAN-37** (independent resource
  versions) — `In Review`, implemented and covered by tests.
- **HAN-30** local/static convergence — done to the limit of what is provable
  without real artifacts.

All local gates are green (section 9). The full suite is 379 passing.

**No open code decision remains.** The model archive root-layout question
(section 3) was decided by the human in the second review pass and the check is
in the tree.

### What still blocks calling V1/beta ready

Everything remaining is external evidence, not code:

1. **No green three-platform build exists.** The only real run had Linux
   failing. The Linux fix is in the worktree and has **never run on Actions**.
2. **The current tree has never been frozen.** All packaging evidence comes
   from `c0ece45`, which predates the bootstrap, the Qt error dialog, and the
   resource-version work.
3. **No production resource archives exist.** The first-run path has been
   exercised only against fake transport in tests.
4. **Nothing is committed.** `v0.1.0` still names `c0ece45`; its published
   artifacts do not contain any of this work.

---

## 2. Latest review findings

| # | Finding | Pass | Status |
| --- | --- | --- | --- |
| 1 | Model archive root-layout validation | 1 → 2 | **Fixed** |
| 2 | `ResourceArtifact.version` invariant | 1 | **Fixed** |
| 3 | Dead `_missing_runtime_config_message` | 1 | **Fixed** |
| 4 | Qt dialog `cast(Any, …)` | 1 | **Fixed** |
| 5 | Dead release-workflow guards | 1 | **Fixed** |
| 6 | Bootstrap ignores `updates.github` | 1 | **Deferred** |
| 7 | Exe-adjacent writable config | 1 | **Deferred** |
| 8 | `all_valid` over extra resources | 1 | **Dismissed** |
| 9 | `provision_runtime_config` mixed five responsibilities | 2 | **Fixed** |
| 10 | "remain invalid after provisioning" without provisioning | 2 | **Fixed** |
| 11 | `main()` branched twice on the same condition | 2 | **Fixed** |
| 12 | Finding 2's fix reintroduced dead guards | 2 | **Fixed** |

### 1. Model archive root-layout validation — fixed in the second pass

Full detail in section 3. `hanly/resource_manager.py:431` validates a
`directory` resource as *exists / is a directory / is readable* only. The human
chose the narrow app-layer invariant, and `_require_model_files_at_root` now
runs inside `load_runtime`.

### 2. `ResourceArtifact.version` invariant — fixed

`tools/build_release_manifest.py`. The field was declared `str | None` so
`None` could mean "derive from the asset name", but `__post_init__` always
produced a string. The declared type contradicted the real invariant and forced
a dead guard in `build_manifest` (`if resource.version is None: raise`) plus a
manual `isinstance` check the field loop already performed.

Fixed with a `ResourceArtifact.from_asset_name()` classmethod that derives the
version and passes a real `str`, restoring `version: str`. Two branches left
`__post_init__`, the unreachable guard left `build_manifest`, and
`_resource_spec_from_name` now calls the factory. The explicit-version vs
asset-name conflict check is unchanged and still tested. Same shape as the
`PackageLayout.__post_init__` finding from the Wave 10 pass, fixed the same way.

### 3. Dead `_missing_runtime_config_message` — fixed

`hanly_app/application.py`. `main()` no longer has a "no configuration found"
branch — it falls back to `default_runtime_config_path()` and lets bootstrap
create the file. The helper survived the rewrite with no caller. Removed.

### 4. Qt dialog `cast(Any, …)` — fixed

`hanly_app/application.py:_show_native_startup_error`. The whole
`QApplication.instance()` expression was cast to `Any` to reach
`activeWindow()`, which the typed base class does not expose. Narrowed to an
`isinstance` check yielding a real parent or `None`, so no broad `Any` enters
the failure path. The local binding that keeps a self-created `QApplication`
alive across the modal call is preserved; its comment was inaccurate and was
corrected.

### 5. Dead release-workflow guards — fixed

`.github/workflows/release.yml`. `find_resource` was hardened to require
exactly one match and `return 1` otherwise. Under `set -euo pipefail` a failing
command substitution in an assignment aborts the step immediately, so the three
following `test -n "$detection" || …` lines could never execute — and they
carried the *less* informative message. Removed.

**Proven:** verified in a local bash harness across zero-match (aborts,
function's message shown), two-match (aborts, lists both paths), and one-match
(resolves correctly) cases.

### 6. Bootstrap ignores a user-configured release channel — deferred

`hanly_app/first_run.py:provision_runtime_config` builds its
`GitHubReleaseFetcher` from the module constants
(`PUBLIC_REPOSITORY_OWNER`/`NAME`), not from the `updates.github` block of the
configuration it just loaded. On a genuine first run these agree because
bootstrap wrote both. On a *repeat* run where resources went invalid and the
user has since repointed `updates.github`, bootstrap silently uses the
hardcoded coordinates while the in-app updater (`load_update_service`) honours
the configuration — two sources for one fact.

**Not changed:** reading the channel from a configuration that may itself be the
reason resources are invalid is a defensible bootstrap decision, and no V1 user
has a second channel. **Trigger:** any support for a non-default channel.

### 7. Exe-adjacent writable config — deferred

`discover_runtime_config` prefers `runtime.json` beside the executable. When it
finds one there, `_persist_resource_versions` writes `installed_version` back
to that same path. In a per-machine install (`Program Files`, `/opt`) that path
is not user-writable, so a successful download would be followed by a
`FirstRunError` from the version write — *after* the bytes were
activated. The next launch revalidates and recovers, so this is a confusing
error rather than data loss.

**Not changed:** V1 ships an extracted archive, not an installer, so no
non-writable location exists yet. **Trigger:** a real installer.

### 8. `all_valid` over extra resources — dismissed

`_resource_specs` builds specs for every entry under `resources`, so
`manager.all_valid` covers extras a user added, and an invalid extra fails
bootstrap even when the three required resources are fine. Correct as written:
`load_runtime` applies the same all-valid rule, so bootstrap succeeding where
startup would then fail is the worse outcome.

### Verified during review, unchanged

- `installed_version` is a real `ResourceSpec` field consumed by
  `ResourceManager` (`resource_manager.py:413,428`) — not invented metadata.
- `metadata[resource_id]` in `provision_runtime_config` cannot raise
  `KeyError`: `_resource_manager_from_payload` requires all three ids first and
  its `RuntimeConfigError` is caught and wrapped.
- `preload_ocr_runtime` on the failure path is idempotent — it is an
  `importlib.import_module` behind the `sys.modules` cache.
- Published asset names match the manifest: `gh release create` publishes each
  file under its basename, and `published_asset_name` falls back to `path.name`
  for the same file.
- `.tar.gz` precedes `.zip` in `RESOURCE_ARCHIVE_SUFFIXES`, so a `1.0.tar.gz`
  remainder yields `1.0` rather than stopping at a shorter suffix.

---

## 3. Model archive validation — resolved

**Status: decided and applied.** The human chose option 1 below in the second
review pass.

### The gap

`hanly/resource_manager.py:431` validates a `directory` resource only as
*exists / is a directory / is readable*. Nothing inspects contents, and
`ResourceSpec.configuration` — which already carries `model_name` — is opaque
pass-through never used for validation.

A Paddle model ZIP packed as `PP-OCRv5_mobile_det/<files>` rather than
`<files>` therefore proceeded:

```
download -> checksum pass -> safe extraction -> ResourceManager VALID
         -> desktop starts -> PaddleOCR fails later
```

with no link from the runtime failure back to the packaging mistake. The layer
whose *job* is validation could not detect the single most likely mistake in a
hand-built archive, so the requirement rested on human care alone.

### What was applied

`_require_model_files_at_root` in `hanly_app/runtime.py`, called from
`load_runtime` after the existing all-valid check and before any provider option
is built:

- Each of the two model directories must contain **at least one regular file at
  its root**.
- **Filename-agnostic** — no Paddle-specific names, no knowledge of
  `inference.*` or any other layout.
- **Empty directories rejected**; **nested-only archive layouts rejected**.
- App layer, not the engine — no approved `ResourceSpec` contract changed. It
  runs at every startup and again when bootstrap reloads, so it covers both
  first run and repeat launch.

### Cost, paid

The five `test_runtime.py` tests whose fixtures created empty model directories
now share a `_model_directories` helper that writes a placeholder
`inference.pdiparams`; its docstring records that the file name is irrelevant to
the check. Two tests were added for the invariant itself — a wrapper-nested
archive and an empty model directory — both asserting the named startup error.

### Options not taken

- **Extend `ResourceSpec`** with optional required entries. More general, but it
  changes an approved engine contract and would need architecture approval
  first. Still available post-V1 if a second consumer wants it.
- **Accept the gap for beta.** Rejected: it left a packaging mistake surfacing
  as silent broken OCR on a user's machine.

### Still manual

Confirm during HAN-30, against a real Paddle model directory, that no valid
layout nests its files below the resource root. `packaging/README.md` records
the archive requirement and now states that startup enforces it.

## 4. Real packaging evidence from `v0.1.0`

**Proven** (real tag-triggered Actions run on commit `c0ece45`):

| Platform | Result |
| --- | --- |
| macOS | **PASS** |
| Windows | **PASS** |
| Linux | **FAIL** (section 5) |

Windows evidence:

- Python **3.10.11**, PyInstaller **6.22.2**
- `hanly-desktop.exe` built successfully
- `dist/hanly-desktop-windows.zip` produced
- downloaded artifact ≈ **422 MB compressed**

The tag-triggered matrix expanded to all three platforms, confirming the
Wave 10 matrix fix.

### Runtime manual test on the Windows artifact

**Proven:** the extracted package contained only `hanly-desktop.exe` and
`_internal/`; there was **no `runtime.json` beside the executable**; and
double-clicking produced **no visible UI and no visible error** after the
Windows execution prompt.

### Does the current worktree address this?

**Yes — and the cause is now confirmed exactly.**

At `c0ece45`, `--runtime-config` was already optional (that came from the
Wave 10 pass), so this was *not* an argparse failure. The actual code was:

```python
runtime_config = args.runtime_config or discover_runtime_config()
if runtime_config is None:
    print(_missing_runtime_config_message(), file=sys.stderr)
    return 2
```

With no `runtime.json` beside the exe and none in `%LOCALAPPDATA%\Hanly`,
`discover_runtime_config()` returned `None`, the message went to **stderr**, and
`console=False` meant stderr was attached to nothing. Silent exit code 2 —
precisely the observed symptom.

The current worktree changes both halves:

1. **No configuration is no longer fatal.** `main()` falls back to
   `default_runtime_config_path()` and calls `provision_runtime_config()`, which
   creates `%LOCALAPPDATA%\Hanly\runtime.json` and provisions resources.
   `_missing_runtime_config_message` is gone (finding 3).
2. **Failures become visible.** `_report_startup_error` prints to stderr *and*,
   when `sys.frozen` is set, calls `_show_native_startup_error`, which shows a
   `QMessageBox.critical` — preserving PaddleOCR-before-Qt ordering by calling
   `preload_ocr_runtime()` first.

**Inferred, not proven:** this has only been exercised locally and unfrozen. No
`console=False` build of the current tree exists, so the dialog has never been
seen in a frozen process. That is item 5 of the manual checklist.

---

## 5. Linux failure

**Proven** — the real Actions failure was:

```
tests/test_qt_hover_scheduler.py:10
    pytest.importorskip("PyQt6.QtWidgets")
ImportError: libEGL.so.1: cannot open shared object file: No such file or directory
```

### Why it failed instead of skipping

**Proven by local experiment:** `pytest.importorskip` skips only on
`ModuleNotFoundError`. A plain `ImportError` — which is what a missing shared
library produces — is re-raised as a hard failure. The Ubuntu job installs
`PyQt6` successfully, so the module *is* present; it simply cannot load,
so the guard does not protect it. (This is also why the local CI-equivalent
environment reports 13 *skips*: there PyQt6 is genuinely absent.)

### Current fix

`.github/workflows/build.yml:47-51` — present in the worktree:

```yaml
- name: Install Linux packaging dependencies
  if: matrix.platform == 'linux'
  run: |
    sudo apt-get update
    sudo apt-get install --yes --no-install-recommends libegl1
```

Only `libegl1`, only for the Linux matrix member, `--no-install-recommends`,
placed before the dependency install, tests, and packaging. A structural YAML
test in `tests/test_ci_workflows.py` fixes the condition, command set, and
ordering.

**Status: local/static only. Real Actions validation is still pending.** Whether
`libegl1` alone is sufficient — as opposed to also needing `libgl1`,
`libxkbcommon-x11-0`, `libdbus-1-3` or other Qt platform libraries — is
**inference**. Only a real Linux job can confirm it, and it may reveal a second
missing library on the next run.

---

## 6. First-run / bootstrap flow

Current end-to-end clean-user path:

```
extracted release
  -> hanly-desktop.exe (frozen entrypoint)
  -> runtime_hook.py: Windows DLL dirs + preload_ocr_runtime()   [Paddle before Qt]
  -> application.main()
  -> discover_runtime_config() or default_runtime_config_path()
  -> provision_runtime_config()
       - creates runtime.json if absent
       - load_resource_manager() -> validate()
       - all valid?  -> return immediately, no fetcher, no network
       - otherwise   -> GitHubReleaseFetcher -> check_for_updates()
                        -> UpdateService.install() per missing resource
                           download (HTTPS) -> checksum -> safe extract
                           -> validate staged -> activate -> backup
                        -> persist installed_version after each activation
       - reload config, revalidate, require all valid
  -> run_desktop() -> load_runtime() -> composition -> Qt event loop
  -> UI ready (tray, hotkey, hover, popup, Control Center)
```

**Where `runtime.json` lives.** Discovery order: beside the executable, then
`%LOCALAPPDATA%\Hanly\runtime.json` (Windows) or
`~/.config/hanly/runtime.json` (XDG). If neither exists, bootstrap creates the
**per-user** one. Resource paths inside it are relative and resolve against the
config file's directory, so a default Windows install puts models and the
dictionary under `%LOCALAPPDATA%\Hanly\resources\`.

**Does the user need `--runtime-config`?** No. It is a power-user/development
override, and passing it deliberately **bypasses bootstrap entirely** — no file
creation, no network — because an explicit path is an operator choice.

**Clean first-run provisioning.** `%LOCALAPPDATA%\Hanly\runtime.json` is
written with the three production resource entries, the Paddle model options,
and public `ThiagoRoss1/hanly` release coordinates. `ResourceManager` reports
the three as `MISSING`; each is fetched from the latest release's
`hanly-resources.json` and installed through `UpdateService`. Each activation
records its `installed_version` **before the next resource starts**, so a
partial failure retains completed work and a retry resumes.

**Repeat launch.** If all resources validate, bootstrap returns before
constructing a fetcher — no remote request at all.

**On failure.** `FirstRunError` / `RuntimeConfigError` /
`DesktopApplicationError` / `OSError` / `ValueError` are caught, reported, and
`main()` returns 2. Messages name the exact resource and the underlying cause.

**Are GUI failures visible?** Mostly, with two residual silent paths —
both **inferred**, neither proven in a frozen build:

1. **Uncaught exception types.** Only the five types above reach
   `_report_startup_error`. Anything else — for example a bare `RuntimeError`
   from Qt — propagates out of `main()` and, in a `console=False` build, is not
   guaranteed to be visible.
2. **`argparse` errors.** `parse_args` raises `SystemExit` *before* the
   `try`, writing usage to a stderr that a windowed build does not have. Not
   reachable by double-click (no arguments), only by a bad explicit invocation.

**Paddle-before-Qt ordering.** Preserved in three places: the PyInstaller
runtime hook (before any application import), `run_desktop` (first statement,
before the `PyQt6` import), and `_show_native_startup_error` (calls
`preload_ocr_runtime()` before importing `QApplication`), so even the failure
dialog cannot invert the ordering.

---

## 7. Release / version flow

**Version source of truth.** `packages/hanly-app/pyproject.toml`
`[project] version` = `0.1.0`. `packages/hanly/pyproject.toml` carries the same
value and `hanly-app` pins `hanly==0.1.0`. Read at runtime through
`importlib.metadata`, not TOML parsing. Tags are `v{version}`.

**Tag/version validation.** `tools/release_version.py`:

```
python tools/release_version.py                # 0.1.0
python tools/release_version.py --tag v0.1.0   # 0.1.0, exit 0
python tools/release_version.py --tag v0.1.1   # explains mismatch, exit 1
```

Rejects a mismatched version, a non-`vMAJOR.MINOR.PATCH` shape, and engine/
product drift. Called by `build.yml` on tag push (before any artifact is
produced) and by `release.yml` before publishing. A test guards against stale
editable installs reporting a stale version.

**Artifact names.**

| Platform | Archive | Actions artifact |
| --- | --- | --- |
| Windows | `hanly-desktop-windows.zip` | `hanly-desktop-windows` |
| macOS | `hanly-desktop-macos.tar.gz` | `hanly-desktop-macos` |
| Linux | `hanly-desktop-linux.tar.gz` | `hanly-desktop-linux` |

Only the archive is retained — not the onedir tree beside it, which is the same
payload again.

**How `release.yml` resolves the app build.** No copied run id:

```bash
gh run list --workflow build.yml --branch "$RELEASE_TAG" --status success --limit 1
```

The build workflow runs *on the tag*, so selecting by tag ties published
binaries to the commit that tag names.

**`resource_run_id`.** Still a required manual input. Resource archives are
produced and versioned **outside this repository**, so a tag push cannot supply
them. `find_resource` now requires **exactly one** artifact per approved
resource id and fails with both paths listed otherwise.

**Resource version independence.** Versions come from
`hanly-resources-<resource-id>-<version>.<archive>` via
`--resource-from-name`, no longer from `$RELEASE_TAG`. Malformed, ambiguous,
conflicting, or duplicate identities fail before publication. A cross-boundary
test confirms mixed resource versions are accepted by the real `RemoteManifest`
consumer.

**Manifest and checksums.** `hanly-resources.json` carries `asset_name`,
`sha256:` checksum, `kind`, HTTPS `url`, and independent `version` per
resource. `SHA256SUMS` records every asset under its **published basename**, so
a downloader can verify with `sha256sum -c`.

**Publication.** `gh release create "$TAG"` with the three application
archives, three resource assets, `hanly-resources.json`, and `SHA256SUMS`;
title `Hanly Desktop v0.1.0`; GitHub-generated notes. The tag must already
exist — verified via `gh api` first, so `gh` cannot invent one at
default-branch HEAD.

### Automated vs manual

| Automated on tag push | Manual human step | Not remotely validated |
| --- | --- | --- |
| Tag/version check | Edit version, commit, push | The Linux build job |
| Three-platform build | Create and push the tag | Any build of the current tree |
| Archive creation and retention | Produce resource archives | The whole release workflow |
| Manifest, checksums, publication (once dispatched) | Dispatch `release.yml` with tag + `resource_run_id` | Resource download by a real client |

**The entire `release.yml` has never executed.** Every statement about its
behaviour is inference from the YAML plus structural tests.

---

## 8. Security / integrity guarantees

Currently in place and preserved through this pass:

- **HTTPS-only** for manifests, release assets, and resource URLs.
- **Redirect downgrade protection** — `_HTTPSOnlyRedirectHandler` re-applies the
  scheme policy on every hop, because urllib blocks `file:` but still follows
  `http:` and `ftp:`.
- **Mandatory checksums** — no resource kind activates on transport integrity
  alone; a manifest without a checksum is rejected.
- **Validation before activation** — staged bytes are checksum-verified, then
  unpacked, then validated by `ResourceManager` before anything is moved into
  place.
- **Zip-slip protection** — every archive member is resolved and rejected if it
  escapes the extraction root.
- **Staging / activation / rollback** — downloads stage beside their
  destination, activation is atomic, and the previous copy is kept as
  last-known-good.
- **No secrets** — public GitHub Releases need no token in runtime config;
  `updates.github` carries only owner/repo/tag/asset name.
- **Release-side** — tag must pre-exist, tag must match the product version,
  exactly one artifact per resource id, `directory` resources must be `.zip`.
- **Engine independence** — `hanly` never acquires remote resources;
  `ResourceManager` stays the local authority and works with no network.

### Intentionally deferred to post-V1

- **Manifest authenticity / signing / provenance.** Integrity is verified;
  *authenticity* rests on HTTPS and GitHub. Nothing verifies that the build run
  producing the binaries corresponds to the tag's commit SHA.
- **Archive size / entry-count limits.** Extraction has no cap; a hostile or
  corrupt archive could exhaust disk.
- **Repeated validation performance.** `check_for_updates()` runs full local
  validation including SQLite `quick_check`, so every availability check does
  full-file I/O over the dictionary.

---

## 9. Gates and evidence

Latest run, current worktree:

```text
Local .venv (Python 3.13, full desktop runtime extras)
  python -m pytest                                      379 passed
  python -m ruff check packages packaging tests tools    All checks passed
  python -m mypy packages packaging tests tools          Success: 88 source files
  git diff --check                                       clean (line-ending warnings only)

CI-equivalent venv (dev group + editable packages, no runtime extras)
  python -m pytest                            not re-run in the second pass
  python -m ruff check packages packaging tests tools    All checks passed
  python -m mypy packages packaging tests tools          Success: 88 source files

mypy --python-version 3.10                              Success: 88 source files
mypy --python-version 3.11                              Success: 88 source files
mypy --python-version 3.12                              Success: 88 source files
mypy --python-version 3.13                              Success: 88 source files

python tools/build_package.py --dry-run --platform linux   expected spec command
python tools/release_version.py --tag v0.1.0               0.1.0
packaging/hanly-desktop.spec                               compiles
```

The CI-equivalent environment was measured in the first pass only; the four
tests added in the second pass import neither PyQt6 nor the runtime extras, so
the expected count there is 363 passed / 13 skipped — **inferred**, not re-run.
The **13 skips** in that environment are the PyQt6-dependent tests
skipping correctly when PyQt6 is genuinely absent — distinct from the Linux CI
failure, where PyQt6 was installed but could not load (section 5).

Focused suites within the 379: `test_ci_workflows.py`,
`test_release_manifest.py`, `test_release_version.py`, `test_packaging.py`,
`test_first_run.py`, `test_application.py`, `test_runtime.py`.

**No** PyInstaller build, Actions run, tag operation, dispatch, artifact
upload, or release publication was performed in this pass.

---

## 10. Remaining manual validation

### A. Before committing

- [x] **Decide the model archive validation question** (section 3) — decided:
      narrow app-layer invariant applied, five fixtures updated, two tests added.
- [ ] **Code review** of the uncommitted worktree — the three new files
      (`first_run.py`, `test_first_run.py`, the handoff) and
      the modified files.
- [ ] **Commit and push** — human authority. Currently on `main`; consider a
      branch.

### B. Tag handling

- [ ] Decide between a new version (`0.1.1` / `0.2.0`, editing
      `packages/hanly-app/pyproject.toml` and both `hanly` pins) or deliberately
      moving the unpublished `v0.1.0` tag. **`v0.1.0` currently names `c0ece45`
      and its artifacts predate all of this work.**
- [ ] If bumping, confirm `python tools/release_version.py --tag vX.Y.Z` passes
      before pushing the tag.

### C. Real CI

- [ ] Push the tag and confirm the build workflow expands to **three** jobs.
- [ ] **Linux** — confirm `libegl1` is sufficient for Qt test collection *and*
      packaging. If a second library is missing, add it the same way.
- [ ] **macOS** — confirm the archive is produced.
- [ ] **Windows** — confirm the archive is produced.
- [ ] Confirm the tag/version check fails a deliberately mismatched tag.

### D. Windows frozen validation

- [ ] Download `hanly-desktop-windows.zip` from the new run and extract on a
      clean-ish profile.
- [ ] **Clean first run** — double-click with no `runtime.json` anywhere;
      confirm visible behaviour rather than silent exit.
- [ ] Confirm `%LOCALAPPDATA%\Hanly\runtime.json` is created with the expected
      contents.
- [ ] Confirm real HTTPS resource acquisition, checksum, extraction, activation.
- [ ] **Force a failure** (delete a resource / block the network) and confirm the
      Qt critical dialog is **visible** in the `console=False` build.
- [ ] Confirm a repeat launch reprovisions nothing and makes no network request.
- [ ] **Tray** — menu, status, quit.
- [ ] **Control Center** — opens, settings apply.
- [ ] **OCR** — real Korean text recognised.
- [ ] **Manual lookup** (hotkey) and **hover lookup** — popup content and
      placement, multi-monitor.
- [ ] Real-terminal **Ctrl+C / SIGINT** shutdown (the earlier non-terminal probe
      is invalid evidence).

### E. Resources

- [ ] Produce exactly three resource archives named
      `hanly-resources-<id>-<version>.<ext>`.
- [ ] **Verify model ZIP layout**: files at the archive root, not under a
      wrapper directory. Startup now rejects a nested layout with a named error
      (section 3), so this is confirming the archives, not catching a silent
      failure.
- [ ] Upload them via a run whose id can be passed as `resource_run_id`.

### F. Release

- [ ] Dispatch `release.yml` **only after** the above passes.
- [ ] Inspect that the Release directly contains three application archives,
      three resource assets, `hanly-resources.json`, and `SHA256SUMS` — not
      Actions' outer artifact wrappers.
- [ ] Verify `SHA256SUMS` matches the downloaded assets.
- [ ] Confirm a fresh client resolves the manifest and installs from it.
- [ ] **Final human release decision** (HAN-31 → HAN-32).

### G. Platform smoke

- [ ] macOS frozen archive — launch, lifecycle, backend behaviour.
- [ ] Linux frozen archive — launch, lifecycle, backend behaviour.

---

## 11. Post-V1 only — do not pull into V1

Owned by **HAN-35** unless real artifact evidence promotes an item into a
functional blocker:

- **Architecture simplification / readability** — broader typing and readability
  cleanup, remaining `object`-typed seams, external-JSON `Any` in
  `application.py`, JSON-out snapshots typed as `dict[str, Any]`.
- **Package size / dependency optimization** — the ~422 MB compressed Windows
  artifact should trigger *measurement*, not speculative trimming: Paddle /
  PaddleOCR / PaddleX contribution, Qt and QtWebEngine contribution,
  `collect_dynamic_libs("PyQt6")`, duplicated binaries or data. Also optional
  dependency pruning and Qt/Paddle collection redesign.
- **Performance benchmarking** — `check_for_updates()` doing full local
  validation on every availability check; hover-delay tuning; cold start.
- **Type-safety / suppression inventory** — the recorded packaging boundaries
  (`_DLL_DIRECTORIES: list[object]`, `getattr(sys, "_MEIPASS", …)`, PyInstaller
  spec globals) are legitimate framework boundaries and should **not** be
  narrowed for their own sake.
- **Signing / provenance** — manifest authenticity, artifact signing, build-run
  SHA verification against the tag.
- **Archive limits** — extraction size and entry-count caps.
- **Deeper UX / polish** — first-run progress UI (provisioning is currently
  synchronous before the desktop appears), popup placement polish, CLI
  expansion, application-version / About / self-update.
- **Broad failure-injection and manual system testing** — beyond the HAN-30
  matrix.
- **Native backend exploration**, **HanlyOCR** research (HAN-33, non-blocking).
- **Broad PyInstaller warning cleanup** — classified as optional/backend/size
  noise absent a concrete packaged missing-import failure.

Also still recorded: Chromium/DirectComposition diagnostic is **external and
harmless** unless a functional symptom appears; the HAN-19 target-mapping
limitation stays settled.

---

## Next recommended action

1. **Review and commit the worktree**, then decide the version/tag question
   (section 10.B) — `v0.1.0` currently names `c0ece45` and cannot be reused as-is.
2. **Push the tag and get one green three-platform run**, with Linux confirming
   `libegl1` is sufficient. Everything downstream — resources, release, RC —
   is blocked on that build existing.
3. **Produce the three resource archives** with their files at the archive root.
   Startup now fails a wrapper-nested model directory by name, so a mistake here
   surfaces on the first launch rather than as broken OCR.
