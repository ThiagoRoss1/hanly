# Resource Delivery and Desktop Convergence Review Handoff

## Bundle

- Member issues: HAN-24, HAN-25, HAN-26
- Implementation ecosystem: GPT execution flow; Sol coordination/integration with Luna xhigh implementation workers
- Date: 2026-08-22

## Implemented

- Added a UI-independent resource update service with a configurable GitHub Releases fetcher, streamed progress, staged validation, atomic activation, last-known-good rollback, and recovery of invalid local resources.
- Extended `ResourceManager` SQLite/KRDICT validation with `PRAGMA quick_check` and definitive `integrity_check` escalation.
- Added a background update coordinator and Control Center update/resource state, actions, selection, progress, success, failure, and diagnostics surfaces.
- Made hotkey, hover delay, capture mode, monitor, and region settings apply to the live shared manual/hover runtime.
- Added the lazy native system tray and wired start/resume, pause, Control Center, status refresh, and quit actions.
- Added the official `hanly-desktop` / `python -m hanly_app` production composition path while preserving worker-owned provider factories.
- Added shared PaddleOCR-before-Qt bootstrap diagnostics and a Qt-aware graceful SIGINT/shutdown bridge used by production and the development alpha.
- Added controlled lookup-runtime teardown and reconstruction around resource activation so Windows does not retain an open KRDICT SQLite handle during atomic replacement.

## Main expected behavior

- A configured desktop runtime can check GitHub release metadata, show update availability, download and validate a selected model or dictionary resource off the UI thread, replace it safely, and revalidate local state.
- The running lookup stack releases worker-owned providers before activation and is rebuilt afterward, preserving its previous running or paused lifecycle state.
- Control Center settings affect both manual and automatic-hover lookup without restarting the application.
- The production app starts through one documented command, exposes tray controls, and closes input listeners, worker providers, SQLite resources, update work, native windows, and signal handling through one idempotent lifecycle.

## Architecture / seams touched

- `UpdateService` obtains bytes; `ResourceManager` remains the local compatibility and integrity authority.
- Update operations are synchronous and UI-independent; `UpdateCoordinator` owns their single background worker and normalized UI snapshot.
- Runtime provider construction remains factory-owned on the lookup worker. The application composition adds concrete wiring without replacing the generic composition seam.
- Resource activation brackets a graceful controller shutdown/rebuild because Windows denies replacement of the open KRDICT SQLite file.
- Native Qt, tray, and signal dependencies remain lazy so OCR preload runs before Qt and lightweight imports/tests do not require native UI packages.

## Relevant files / diff areas

- `packages/hanly/src/hanly/resource_manager.py`
- `packages/hanly-app/src/hanly_app/update_service.py`
- `packages/hanly-app/src/hanly_app/update_coordinator.py`
- `packages/hanly-app/src/hanly_app/control_center.py` and `assets/control_center/`
- `packages/hanly-app/src/hanly_app/application.py`, `__main__.py`, `bootstrap.py`, `signal_bridge.py`, and `tray.py`
- `packages/hanly-app/src/hanly_app/capture.py`, `hotkeys.py`, `hover_controller.py`, `hover_lookup.py`, `manual_lookup.py`, and `desktop_controller.py`
- `tools/dev_alpha.py`, package/tool READMEs, and the corresponding `tests/test_*.py` coverage

## Implementation-side validation already run

- Production entry smoke: `python -m hanly_app --help` exits 0 with no PyQt6 module imported.
- Controlled Windows probe: replacing an open read-only SQLite file raised WinError 5; the
  bundle therefore closes the worker-owned runtime before activation and rebuilds it after.

## Applied Review Fixes

A review ran against the real runtime before closeout. Each finding below was
reproduced by executing the code, fixed, and re-verified the same way.

### 1. Integrity verification is now required for every resource kind — BUG, fixed

`install()` required a checksum only for `sqlite`/`krdict`. A `directory`
delivery — the PaddleOCR models the engine loads and executes — activated on
transport integrity alone. Reproduced: a model directory was replaced with
arbitrary archive content and no checksum.

**Checksum policy.** Every installable remote resource must carry a checksum.
The delivered bytes are verified before anything unpacks or activates them, so
a directory's whole archive is covered before extraction. Staging semantics,
zip-slip protection, and non-destructive failure are unchanged.

Covered by tests for: directory without checksum rejected, wrong checksum
rejected, active directory untouched in both cases, valid checked archive
installs.

### 2. Rollback restores instead of swapping — BUG, fixed

Rollback moved the rejected artifact into the backup slot, so the
"last-known-good" copy became the version that had just been rejected and a
second rollback reinstalled it.

**Rollback state semantics.** The backup is now *copied* to the destination
rather than moved, and the displaced artifact is discarded:

| step | active | last-known-good |
| --- | --- | --- |
| after install | NEW | GOOD |
| after rollback | GOOD | GOOD |
| after second rollback | GOOD | GOOD |

Rollback is idempotent, a rejected artifact never becomes the backup, and the
destination is restored if the replacement fails part-way.

### 3. Remote acquisition is HTTPS-only — BUG, fixed

Manifest URLs went straight to `urllib.request.urlopen`. Reproduced: a
`file://` URL copied a local file into the resource staging path.

**URL scheme policy.** `RemoteResource` rejects any non-HTTPS URL at
construction, so a bad manifest fails before download or staging, and
`GitHubReleaseFetcher._open` applies the same rule to release-asset URLs the
manifest never named. `http://`, `file://`, `ftp://`, and scheme-less URLs are
all rejected. No general networking-policy subsystem was added.

### 4. Shutdown during an active install completes promptly — BUG, fixed

Once the Qt loop stopped, an update worker parked in `_dispatch_sync` waited
the full dispatch timeout while `DesktopApplication.shutdown()` waited for that
worker. Reproduced at 8.01 s with a shortened timeout; the production default
was 60 s.

**Lifecycle decision.** `DesktopApplication` publishes a `closing` event that
it sets *before* tearing anything down. `_dispatch_sync` polls that event and
raises `DesktopShuttingDown` instead of waiting for a callback the dead loop
can never run. `before_install` propagates it, so the install never starts;
`after_install` absorbs it, because the resource is already safely activated
and the rebuilt runtime would be discarded anyway. The timeout was not merely
lowered, and no UI callback is ever run directly from the update worker: the
normal path still marshals through the Qt dispatcher.

Re-verified with the original reproduction: **8.01 s → 0.06 s**.

### 5. The Qt thread no longer joins a running OCR worker — BUG, fixed

`before_install` dispatched a full `controller.shutdown()` to the Qt thread,
which reached `LookupController.stop(wait=True)` and joined the lookup worker.
An in-flight PaddleOCR job froze the popup, tray, and Control Center.

Teardown is now split. `JobExecutor.join()` and `LookupController.join()` wait
for an already-requested shutdown, so requesting and waiting can happen on
different threads. `ManualLookupRuntime.begin_shutdown()` releases UI-owned
resources without waiting and `await_shutdown(timeout)` does the blocking wait;
`DesktopController` exposes the same split. `before_install` dispatches only
`begin_shutdown()` to Qt and then waits on the update worker, and refuses to
activate if providers did not release in time — so replacement still cannot
race live lookup work. Process exit uses the same split with a bounded wait, so
SQLite handles still close without an unbounded hang.

### 6. The required desktop seam is declared, not probed — fixed

`DesktopController` and `ControlCenterBridge` probed for `pause`, `resume`,
`apply_config`, `set_capture_preferences`, and `shutdown_gracefully` with
`getattr`, so a runtime missing one silently ignored a lifecycle action or a
Control Center setting.

**Protocol decision.** Two small cohesive Protocols, each describing only what
its consumer really calls: `desktop_controller.LookupRuntime` (start, pause,
resume, invalidate, shutdown, begin_shutdown, await_shutdown, apply_config,
set_capture_preferences) and `control_center.DesktopLifecycle` (state, start,
pause, resume, apply_config, set_capture_preferences). Every optional-capability
probe for those members is gone; a missing member is now a typing error.

Typing immediately surfaced a real composition inconsistency: `tools/dev_alpha.py`
passed a bare `ManualLookupRuntime` where the bridge expects the controller, so
its Control Center reported an `unknown` lifecycle state. The developer alpha
now wraps the runtime in a `DesktopController`, matching production.

Lazy/optional imports for Qt, tray, and OCR bootstrap were left untouched.

### 7. Repeated local validation — deliberately NOT changed

`check_for_updates()` still calls full local validation including SQLite
`quick_check` with `integrity_check` escalation. None of the fixes above needed
that path. Recorded below as a post-V1 performance concern.

### 8. Corrected SIGINT evidence

The earlier Git Bash `kill -INT` result was **invalid**. A control process
using an ordinary Python `SIGINT` handler survived the same signal, so that
harness cannot deliver SIGINT to a native Windows process and cannot prove or
disprove anything about Ctrl+C.

- No claim is made that Ctrl+C is broken. The previous "SIGINT does not stop the
  alpha" finding was **not validly measured** and should not be treated as
  evidence.
- Real-terminal Ctrl+C stays **manual validation pending**.
- No SIGINT fix was implemented, because there is no valid evidence to act on.
- The quit-during-install probe in finding 4 is **a separate, valid** in-process
  lifecycle measurement. It used no signals and must not be conflated with the
  invalid SIGINT probe.

### Verified preserved behavior

Re-checked after the fixes, all unchanged: zip-slip blocking; corrupt payload
refusal with the active database intact; checksum mismatch refusal; no staging
leftovers on failure; Qt-thread marshaling for the normal before/after install
callbacks; SQLite `quick_check` → `integrity_check` escalation; `hanly-desktop`
console script; `python -m hanly_app` starting and building both real PaddleOCR
models; and `--help` exiting 0 with **no PyQt6 module imported**.

## Final gates

```text
python -m pytest                            309 passed
python -m ruff check packages tests tools    All checks passed
python -m mypy packages tests tools          Success: 77 source files
git diff --check                             clean
python -m hanly_app --help                   exit 0, PyQt6 not imported
python -m hanly_app --runtime-config ...      started, real models constructed
```

Re-validated after the CI matrix fix; see *CI Matrix Compatibility Pass* below
for the per-environment results.

## Closeout Cleanup Pass

A focused cleanup/typing/security pass ran after the review fixes. Behavior is
unchanged except where noted; every suppression and capability probe in the
desktop/update scope was reviewed individually.

### Bootstrap / PaddleOCR preload — KEPT, implementation cleaned

The Paddle-before-Qt ordering is still required. Re-verified with isolated
per-process probes after the change: no preload -> `PROVIDERS_FAIL` (WinError
1114 on `torch/lib/c10.dll`); with preload -> `PROVIDERS_OK`.

`import paddleocr  # noqa: F401` became `importlib.import_module("paddleocr")`,
which states the side-effect intent directly and removes the suppression
naturally. The broad `except Exception` is **retained and documented**: this
boundary fails as `ImportError`, as `OSError`/WinError from the native loader,
and as assorted `RuntimeError`s raised inside Paddle's own import, and none of
them should stop the desktop from starting with a reported diagnostic.

### QtSignalBridge — KEPT, wired, narrowed

Both `signal_bridge.py` and `tray.py` are new in this bundle, and the bridge
was added in response to the earlier (invalid) SIGINT probe. It is nevertheless
**genuinely wired into production** (`run_desktop` builds it and
`DesktopApplication.attach_signal_bridge` installs it) and into the developer
alpha, so it is classified on current use, not on that probe.

The QTimer pulse is required for a real reason, now documented in the module:
Qt's loop runs in C++, so a Python-level `SIGINT` handler only runs when the
interpreter next executes bytecode. The periodic no-op timer provides that
boundary; without it Ctrl+C is deferred while the loop is idle.

Narrowed: `signal_module: Any` became a `SignalModule` Protocol over the three
members actually used, with a `SignalHandler` alias matching what
`signal.signal` really accepts and returns. A redundant
`getattr(application, "exit", None)` guard was dropped — the Protocol covers
it. `_signum`/`_frame` are **required by Python's signal-handler contract** and
are kept, now with a comment saying so.

One `cast` remains at `_qt_timer`: `QTimer.timeout` is a `pyqtBoundSignal`
whose stubbed `connect` cannot satisfy a structural Protocol. Asserting the
match once there is preferable to spreading PyQt types through the module.

### Hotkey service — contract declared, probes removed

`join` is part of the real listener seam, not an optional extra: the concrete
backend runs on its own thread and shutdown must be bounded. `HotkeyListener`
now declares `start`, `stop`, and `join(timeout)`, and the
`getattr(listener, "start"/"stop")` guards and the `TypeError` fallback around
`join` are gone. Test doubles were corrected to the declared positional
`join(timeout)` signature.

Lifecycle safety is unchanged: the self-join `RuntimeError` catch stays (a
pynput callback can shut the service down from the listener thread), the join
stays bounded by a named `_STOP_JOIN_SECONDS`, and callbacks still run outside
the service lock. The `lambda action=action:` closures were reviewed and
**kept** — they are legitimate per-iteration binding, not signature adapters.

### Tray service — honest seams, normalization removed

`TrayIcon` now describes the pystray `Icon` surface actually used — `menu`,
`title`, `run_detached()`, `update_menu()`, `stop()` — which removed both
`type: ignore[attr-defined]` lines and the `update_menu` capability probe. A
new `TrayBackend` Protocol replaced `backend: object` plus
`getattr(backend, "MenuItem"/"Menu"/"Icon")`.

`TrayStatusProvider` narrowed from `Callable[[], object]` to
`Callable[[], DesktopState]`. Every caller is Hanly's own composition root, so
`normalize_status` became a direct state-to-label lookup; the alias table, the
`Mapping` branch, the `getattr` state/detail sniffing, and the enum unwrapping
were deleted. `tray.py` has zero `getattr` calls left.

`import pystray  # type: ignore[import-untyped]` is **retained**: pystray ships
no `py.typed` marker (verified). It is one localized external-boundary
suppression, and `TrayBackend` documents what is used from it.

### UpdateService / UpdateCoordinator typing

`UpdateService(resource_manager: object)` became
`UpdateService(resource_manager: ResourceManager)`. `ResourceManager.manifest`,
`.statuses`, `.base_path`, and `.validate()` are all real public members, so
the whole `getattr` ladder collapsed into direct attribute access, and
`_spec`/`_destination`/`_validate_staged` now speak `ResourceSpec` and
`ResourceMetadata`. `UpdateResult.validation` is typed rather than `object`.

`UpdateCoordinator` likewise takes `ResourceManager | None`, its
`UpdateServicePort.install` is typed with `ProgressCallback`/`UpdateResult`,
and `_submit_locked` uses real `Callable`/`Future` types instead of `Any`.

One probe remains in `update_service`: `getattr(response, "headers", None)`.
That is an external HTTP-response boundary — the urllib response and injected
openers do not all expose `headers` — and it only affects progress totals.

### Callback and injection parameters — reviewed, kept

`before_install(_resource_id)` / `after_install(_resource_id)` implement a
`Callable[[str], None]` contract that `UpdateCoordinator` calls with the
resource id. The parameter is part of the contract; the underscore correctly
marks it unused by this implementation. Kept.

`default_app_config_path(environment=...)` is deliberate dependency injection
for `LOCALAPPDATA`/`XDG_CONFIG_HOME` and is exercised by
`tests/test_application.py` without mutating process environment. Kept, not
renamed.

### Readability

`load_update_service` was a single wall of configuration parsing. It now reads
as three conceptual units — `_runtime_payload` (read and shape-check the file),
`_github_fetcher` (build the release adapter from public coordinates), and the
enable/disable decision in `load_update_service` itself — with blank lines
separating validation phases. No behavior change, no configuration classes, no
broader reorganization.

## Runtime GitHub Update Configuration — status

**Remote updates are currently disabled.** Verified against the real files:
`resources/dev/runtime.json` and `resources/dev/runtime-local.json` contain
only `manifest_version`, `resources`, and `paddle`. With no `updates` block,
`load_update_service()` returns `None`, so no `UpdateService` and no
`UpdateCoordinator` are constructed and the Control Center reports updates as
unavailable.

Enabling it later requires adding a block of this shape to the runtime
configuration — public release coordinates only, **no secret material**:

```json
{
  "updates": {
    "enabled": true,
    "github": {
      "owner": "<owner>",
      "repository": "<repository>",
      "tag": "latest",
      "manifest_asset": "hanly-resources.json"
    }
  }
}
```

No owner or repository was guessed or added. The release must also publish a
`hanly-resources.json` manifest asset carrying a `checksum` for **every**
advertised resource, since activation now refuses a resource without one.
Producing that release and its assets is **HAN-29 (Release Infrastructure)**
with **HAN-27 (Packaging)**; wiring the values into shipped configuration
belongs to HAN-26/HAN-27. No `.env` or secret store is required.

## Security Review

Static repository inspection plus safe local probes. Nothing was uploaded, no
release was created, and no remote GitHub state was touched.

### Secrets / repository hygiene — clean

131 tracked non-binary files scanned for GitHub tokens, generic
key/secret/password assignments, AWS keys, private-key blocks, bearer headers,
credentials embedded in URLs, and webhook URLs: **zero matches**. No `.env`,
key, credential, or token files are tracked. Every URL in tracked source and
configuration is either the GitHub API template, a `example.test` fixture, or
the pip bootstrap URL. **No API keys or tokens exist in the repository.**

### Update path — verified properties

- GitHub Releases are read **unauthenticated by design**; public release
  metadata needs no token, and none is sent. No custom headers are added.
- HTTPS-only, enforced at `RemoteResource` construction (before download or
  staging) and again in `GitHubReleaseFetcher._open`.
- **Redirect downgrade closed (fixed this pass).** urllib blocks a redirect to
  `file:` but still follows `http:` and `ftp:`, so validating only the first
  URL was insufficient. Verified empirically, then fixed with an
  `_HTTPSOnlyRedirectHandler` that re-applies the policy on every hop.
- Checksum verified on the delivered bytes **before** unpack and activation,
  and now required for every resource kind including directory/model archives.
- Zip-slip blocked by resolving each member against the staging root before
  extraction. Symlink members are extracted by `zipfile` as ordinary files
  (verified), so an archive cannot plant a symlink escape.
- Corrupt artifacts leave the active resource intact, with no staging
  leftovers; a failed checksum is refused before anything is replaced.
- Rollback restores the known-good copy and cannot reactivate a rejected
  artifact.
- **Destinations cannot be redirected by remote metadata.** `_destination()`
  reads only the local `ResourceSpec`; remote metadata contributes only
  `resource_id` (to select an existing local spec), `url`, `asset_name`,
  `kind`, `version`, and `checksum`. Manifest-controlled values are separated
  from the trusted local specs.
- Bounded 30 s network timeout on every read.
- No `subprocess`, `os.system`, `shell=True`, `eval`, or `exec` anywhere in the
  packages; no command is constructed from remote metadata.
- Activation still brackets a controlled runtime teardown because Windows
  denies replacing the open KRDICT SQLite file.
- Diagnostics carry only public owner/repository/tag values, which are not
  secrets. If authentication is ever added, the diagnostic log must be
  revisited before credentials pass through it.

### Supply-chain boundary — recorded, not addressed

SHA-256 gives integrity **relative to the manifest**, not authenticity. An
attacker who controls both the release artifact and the manifest can publish a
self-consistent malicious update, because the manifest supplies the checksum it
is checked against. Artifact signing or provenance attestation is the real
mitigation and is **post-V1 hardening**, deliberately not introduced here.

### Remaining security findings, by severity

1. **Medium — manifest authenticity.** As above; needs signing/provenance.
2. **Low — unbounded extraction.** `extractall` applies no size or entry-count
   cap, so a pathological archive could exhaust disk. Bounded in practice by
   the mandatory checksum and trusted manifest. Post-V1 hardening.
3. **Informational — pywebview host probes.** `control_center` still uses
   `getattr` for `create_window`/`start`/`destroy`. pywebview *does* ship
   `py.typed`, so these can be typed away; listed below as a future
   simplification rather than a justified boundary.

## Post-V1 Suppression / Type-Safety Inventory

The single place to look when hardening the desktop/update scope. Nothing in
this table is a defect today; each entry is either a justified boundary or a
recorded simplification target. **No broad `Any` introduced for convenience in
JSON/config parsing may survive final hardening without an explicit reason.**

### FUTURE SIMPLIFICATION — external JSON parsed as `Any`

Introduced during the closeout cleanup pass while splitting the update
configuration parser. It is honest about the dynamic origin but avoidable, and
was added in the same pass that removed `Any` elsewhere, so it is recorded
rather than left implicit.

| Location | Item |
| --- | --- |
| `application.py:481` | `_runtime_payload(...) -> Mapping[str, Any]` |
| `application.py:495` | `_github_fetcher(updates: Mapping[str, Any])` |

Target shape:

```text
external JSON -> object -> isinstance / shape validation -> typed values
```

not:

```text
external JSON -> Any -> unchecked propagation
```

If a cast is still needed after proving the payload is a string-keyed mapping,
keep it at that one boundary and justify it inline. Do **not** add a
configuration framework to remove two `Any` occurrences.

The same treatment applies to the other external-JSON entry points, which
predate this bundle: `config.AppConfig.from_dict`,
`update_service.RemoteManifest.from_payload`, and the `runtime.py`
`_mapping_field` / configuration helpers.

### FUTURE SIMPLIFICATION — JSON-out snapshots typed as `dict[str, Any]`

`control_center` and `update_coordinator` return heterogeneous JSON snapshots
to the web UI. The `Any` describes real JSON value variance rather than
unchecked input, so it is lower risk than the parsing case, but a shared
recursive `JSONValue` alias would express it honestly.

### FUTURE SIMPLIFICATION — `object` where a real seam exists

| Location | Item |
| --- | --- |
| `control_center.py:176` | `update_service: object \| None` |
| `control_center.py:514,524` | `webview_module` / `_window` as `object` |
| `capture.py:440` | `ConfiguredCaptureService(capture_service: object)` |
| `tray.py:113` | `icon_image: object \| None` (a Pillow image) |

### FUTURE SIMPLIFICATION — capability `getattr`

| Location | Item |
| --- | --- |
| `control_center.py:544,545,573` | pywebview `create_window` / `start` / `destroy` probes. pywebview **does** ship `py.typed`, so a small typed host seam removes these. |

### FUTURE SIMPLIFICATION — side-effect import style

| Location | Item |
| --- | --- |
| `control_center.py:58` | `__import__(module_name)` for the Qt WebEngine preparation. `bootstrap.py` now uses `importlib.import_module`; these two side-effect imports should read the same way. |

### JUSTIFIED EXTERNAL/RUNTIME BOUNDARY — keep unless the dependency changes

| Location | Item | Reason |
| --- | --- | --- |
| `pyproject.toml` mypy overrides | `pystray.*`, `webview.*` in `ignore_missing_imports` | Desktop runtime extras absent from the static-analysis environment. pystray also ships no `py.typed` (verified); pywebview does ship `py.typed`, so it is still checked normally wherever it is installed. `TrayBackend` documents the pystray surface used. |
| `signal_bridge.py` `_qt_timer` | `cast(SignalTimer, QTimer())` | `QTimer.timeout` is a `pyqtBoundSignal` whose stubbed `connect` cannot satisfy a structural Protocol. Asserted once instead of spreading PyQt types. |
| `update_service.py:284` | `getattr(response, "headers", None)` | urllib responses and injected openers do not all expose `headers`; affects only progress totals. |
| `qt_popup.py:38` | `# type: ignore[call-arg]` | PyQt signal-connect stub; predates this bundle. |
| `bootstrap.py` | broad `except Exception` | The native import fails as `ImportError`, `OSError`/WinError, and Paddle's own `RuntimeError`s; none should block startup. |

### INTENTIONAL CONTRACT/ADAPTER PARAMETER — do not "simplify"

`before_install(_resource_id)` / `after_install(_resource_id)`;
`_signum` / `_frame` (Python signal-handler contract); `*_args: object` in the
tray menu callbacks (pystray passes icon and item); `object`-typed Control
Center setters such as `set_hover_delay(delay_ms: object)`, which are the
**preferred** untrusted-input pattern (`object` -> `isinstance` -> typed);
`default_app_config_path(environment=...)` dependency injection.

### Dev-tooling suppression — accepted for V1

`tools/dev_alpha.py:23` `# noqa: E402`, required by the direct
`python tools/dev_alpha.py` execution path.

## Remaining Known Issues

### BUG

None outstanding from this review.

### Runtime / platform constraint

- **Windows Qt/PaddleOCR bootstrap order.** PaddleOCR must be imported before
  Qt or provider construction fails with `WinError 1114` loading
  `torch/lib/c10.dll`. Plain PyQt6 is enough to reproduce it; Qt WebEngine is
  not required. HAN-26 implements the order in production and the developer
  alpha with a non-fatal missing-preload diagnostic. **HAN-27 must re-verify it
  on the packaged build**, because packagers change DLL resolution.
- **Windows file replacement.** Windows denies replacing the open KRDICT SQLite
  file, so activation brackets a controlled runtime teardown and rebuild. The
  update worker now refuses to activate if providers did not release in time.

### External warning

- Chromium/DirectComposition `IDCompositionDevice4` message from Qt WebEngine.
  Reproducible, harmless, neither filtered nor treated as a Hanly defect.

### Manual validation pending

- Real-terminal Ctrl+C on Windows (see corrected SIGINT evidence above).
- Native tray menu and window behavior under real interaction.
- A real GitHub release artifact and packaged update end to end; revisit when
  HAN-29 provides release infrastructure and HAN-27 packaged artifacts.
- Popup placement during hover over real Korean text.
- macOS and Linux: unexercised. HAN-30 owns final platform validation.

### Post-V1

- **`check_for_updates()` runs full local validation** including SQLite
  `quick_check` with possible `integrity_check` escalation, so every
  availability check does full-file I/O over the dictionary. Deliberately not
  optimized in this pass; belongs to benchmark-driven work under HAN-35.
- Typing/suppression debt is consolidated in the Post-V1 Suppression /
  Type-Safety Inventory above, including the external-JSON `Any` in
  `application.py` introduced during the cleanup pass, the pywebview
  capability probes, and the remaining broad `object` seams.
- Archive extraction has no size or entry-count cap (see security findings).
- Artifact signing / provenance for update authenticity.
- Broader hover failure recovery, optimization, visual polish, benchmarking,
  native-backend exploration, and CLI expansion remain post-V1 under their
  recorded triggers.
- The HAN-19 proportional target-mapping limitation remains settled; revisit
  only on new functional evidence.

## CI Matrix Compatibility Pass

A follow-up compatibility pass fixed CI failures that local validation could
not see. No feature work, no behavior change, no commit.

### Root cause 1 — Python 3.10: `hashlib.file_digest` does not exist

`update_service._verify_checksum` hashed the staged artifact with
`hashlib.file_digest(stream, algorithm)`. That helper was added in **Python
3.11**, while both packages declare `requires-python = ">=3.10"` and CI runs a
3.10 job. Every update-service test that reaches artifact verification failed
on 3.10 only: staged artifact validation/install, failed SQLite validation,
directory extraction/install, wrong-checksum rejection, valid-checksum install,
and rollback idempotency. The failing tests were a symptom; the defect was that
the declared floor was never actually exercised locally.

The floor was **not** raised. `resource_manager._digest` already hashed
incrementally with the same streaming idiom, so `_verify_checksum` was aligned
to it:

```python
hasher = hashlib.new(algorithm)
with path.open("rb") as stream:
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        hasher.update(chunk)
actual = hasher.hexdigest()
```

Preserved unchanged: file-based streaming at a 1 MiB chunk (no artifact is read
whole into memory), the `algorithm:digest` / bare-digest syntax, the
`hashlib.algorithms_available` rejection of unknown algorithms, `OSError` and
`ValueError` both surfacing as `ResourceUpdateError("could not hash staged
artifact: ...")`, and the `hmac.compare_digest` comparison. `hashlib.new` was
moved inside the `try` so an algorithm that is listed but unusable still
reports through the same error path.

Two focused tests in `tests/test_update_service.py` now pin the contract rather
than the interpreter version: one hashes a 2 MiB payload (larger than one read
chunk) across `sha256:`, bare-digest, and `sha512:` forms plus a mismatch, and
one covers the unsupported-algorithm and unreadable-path error semantics.

A repository-wide scan for other post-3.10 stdlib APIs (`tomllib`,
`ExceptionGroup`, `StrEnum`, `datetime.UTC`, `TaskGroup`, `typing.Self` /
`override`, `itertools.batched`, `contextlib.chdir`, ...) found no further
occurrences. `file_digest` was the only one.

### Root cause 2 — mypy `import-not-found` for pystray and webview

CI installs only `--group dev` plus the two packages **without extras**, so no
desktop runtime distribution is present when mypy runs. `pystray` and
`pywebview` were the only two such imports not covered by the existing
per-module mypy override, so they failed as `import-not-found` on 3.11/3.12/3.13.

`tray.py` carried `# type: ignore[import-untyped]`, which is the code emitted
when a package *is* installed without `py.typed` — the wrong code for an absent
package, so CI additionally reported `Error code "import-not-found" not covered
by "type: ignore[import-untyped]" comment`.

**CI dependency installation was not changed.** The static-analysis environment
is deliberately free of desktop runtime distributions: `paddleocr`, `kiwipiepy`,
`PIL`, `mss`, and `PyQt6` are already modeled as per-module
`ignore_missing_imports` overrides, and `pynput` typing is supplied by the
`types-pynput` stub package in the dev group rather than by installing `pynput`.
Installing the runtime extras for CI would pull `paddlepaddle`, `PyQt6`, and
`PyQt6-WebEngine` on four interpreters to satisfy static analysis alone.

The fix extends that existing, narrow boundary with the two missing modules:

```toml
[[tool.mypy.overrides]]
module = ["paddleocr.*", "kiwipiepy.*", "PIL.*", "mss.*", "PyQt6.*", "pystray.*", "webview.*"]
ignore_missing_imports = true
```

No global `ignore_missing_imports`, no file-level ignore, no new `Any` /
`object` / `getattr` in application code. The stale inline
`# type: ignore[import-untyped]` in `_load_pystray` was removed — the override
covers both the absent and the installed-but-untyped case — and its docstring
now records both halves of the boundary. `cast(TrayBackend, pystray)` and the
`TrayBackend` / `TrayIcon` contracts are unchanged.

`ignore_missing_imports` degrades a module to `Any` **only when it cannot be
resolved**. `pywebview` ships `py.typed` (verified in the local venv), so where
it is installed mypy still checks it normally; the override does not discard
that typing. `ControlCenterHost` binds the module to `object` and duck-types via
`getattr` regardless — that pre-existing seam is already recorded in the
Post-V1 inventory and was deliberately not touched here.

### Root cause 3 — why local mypy passed while Linux CI failed

The environment difference, now recorded explicitly:

| | Local `.venv` | CI job |
| --- | --- | --- |
| Install | full desktop runtime extras | `--group dev` + both packages, no extras |
| `pystray` | installed, no `py.typed` -> `import-untyped` (matched the inline ignore) | absent -> `import-not-found` |
| `webview` | installed **with** `py.typed` -> checked, no error at all | absent -> `import-not-found` |
| Interpreter | 3.13 only | 3.10 / 3.11 / 3.12 / 3.13 |

So local validation exercised neither the failing import resolution nor the
3.10 interpreter. Both gaps were structural, not incidental.

To close the first gap, an ephemeral CI-equivalent virtualenv was built for this
pass (`python -m venv`, `pip install --group dev`, both packages editable, no
extras) and reproduced both mypy errors byte-for-byte before the fix. All gates
now run in that environment as well as the local one.

### Validation

Both environments, Python 3.13:

```text
CI-equivalent venv (dev group + editable packages, no runtime extras)
  python -m pytest                            293 passed, 13 skipped
  python -m ruff check packages tests tools    All checks passed
  python -m mypy packages tests tools          Success: 77 source files

Local .venv (full desktop runtime extras)
  python -m pytest                            309 passed
  python -m ruff check packages tests tools    All checks passed
  python -m mypy packages tests tools          Success: 77 source files
  git diff --check                             clean
```

Before the fix, the CI-equivalent environment reproduced exactly the two CI
errors:

```text
tray.py:258: error: Cannot find implementation or library stub for module named "pystray"  [import-not-found]
tray.py:258: note: Error code "import-not-found" not covered by "type: ignore[import-untyped]" comment
control_center.py:583: error: Cannot find implementation or library stub for module named "webview"  [import-not-found]
```

### Not verified locally

No Python 3.10 interpreter is available on this machine (3.12, 3.13, 3.14 only;
no `uv`). The 3.10 fix is verified by construction — `hashlib.new` +
incremental `update()` is available in every supported version, the scan found
no other post-3.10 API, and the new tests pin the behavior on 3.13 — but the
3.10 job itself remains unverified until CI runs.

### Preserved cleanup decisions

`ResourceManager` typing, the `TrayBackend` / `TrayIcon` contracts, the hotkey
listener join contract, the importlib-based Paddle preload in `bootstrap.py`,
and `SignalModule` typing are all unchanged. Nothing was widened to `Any`,
`object`, or `getattr` to satisfy CI.

## Suggested review targets

- Inspect interrupted/corrupt KRDICT delivery for preservation of the active database and last-known-good path.
- Verify the update coordinator never mutates Qt/UI state directly from its worker and that lifecycle hooks restore running versus paused state correctly.
- Check that live settings still drive the same capture/lookup stack for both hotkey and hover triggers.
- Inspect shutdown idempotency and the PaddleOCR-before-Qt import boundary in both production and development entry points.

## Review assignment

Human-selected after implementation. Review applied; stopping for human review. No commit, push, or merge.
