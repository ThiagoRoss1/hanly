# Hanly updater: differential installation and visible progress

Date: 2026-09-15. Planner: Codex. Executor: Claude, directly in one session.

## Execution instruction

Implement this plan as one Gate-tier bundle under `05-execution-plan.md`.
The phases below are ordered implementation steps within **Phase A**, not
separate review cycles. Finish implementation, run the tests and local builds,
prepare one Review Handoff, and **STOP for Thiago's final review**.

**DO NOT COMMIT. DO NOT PUSH. DO NOT MERGE. DO NOT TAG OR PUBLISH A RELEASE.**
Do not trigger a publishing workflow to obtain test results. Do not start a
deep review or another work bundle. Leave all changes available for inspection.

This session prepared a plan only; it did not implement the updater. The
technical choices below are the planner's decision for the requested work,
not a silent amendment of the authoritative architecture documents. Keep the
engine boundaries and the single desktop entry point intact. If implementation
actually requires changing an approved invariant, present the specific change
for human decision instead of rewriting the invariant.

Read `CLAUDE.md`, `docs/CODE-MAP.md`, architecture `01`–`04`, execution `05`,
the original [investigation](reports/updater-in-place-differential-2026-09-15.md),
and the [HAN-42 handoff](review-handoffs/han-42-updater-reliability.md).
Inspect current Linear context if available; associate existing relevant issues
without inventing identifiers or expanding the human-authorized scope. Direct
execution is the default; no extra planning or per-task review ceremony.

## 1. Decision and user contract

**Windows gets file-level differential downloads and transactional, in-place
application updates.** The installed directory and executable path stay the
same. An ordinary patch downloads changed/added files and changes only managed
files that differ. Deleted product files are removed. Unchanged libraries,
models, configuration, and user data are not rewritten.

1. Release discovery fetches metadata only. It never downloads application
   payloads, scans the installation, extracts files, or installs anything.
2. Only the user's **Update now** action starts planning and downloading.
   Display that Hanly will restart briefly to finish. One click authorizes that
   normal sequence; do not add a routine second confirmation.
3. Keep the old app usable during preparation. Pause capture and retire its
   lookup process before installation; close all application processes before
   touching their executable/DLL files.
4. Stage only the files needed, then replace/add/remove them in the same
   installation. Use a uniquely owned `.hanly-update/<transaction-id>/` inside
   the installation for payload and rollback data. This is temporary working
   storage, not a second installed app or a versioned sibling folder.
5. Preserve rollback until the installed candidate acknowledges startup.
   Update completion means the new version started successfully, not merely
   that download or extraction reached 100%.
6. Show download size, transferred and remaining bytes, percentage, stage,
   installation counts, and expandable activity details. Keep a small progress
   window visible during the period when the main application must be closed.

Temporary storage is necessary for verification and rollback. The promise is
no full duplicate application on the ordinary differential path, not zero
temporary files. A restart is also necessary for loaded native libraries.

### Bounded scope

- Windows is the target of the reported failure and the differential path in
  this bundle. Linux and macOS retain their existing full-bundle strategies,
  with shared exit/progress/cleanup fixes where applicable and regression tests.
  Clearly label their full download sizes. Do not claim differential support
  for them. Preserve macOS bundle identity, signatures, links, and launch rules.
- Publish one direct Windows delta from the immediately preceding stable
  release, plus the normal full archives. No chains of intermediate updates.
- Use file-level replacement, not bsdiff, chunk hosting, thousands of GitHub
  assets, runtime pip installation, or a new update service.
- Dependency changes may produce a large update. Show the actual size; do not
  promise a 99% reduction or a fixed number of MB.
- No OCR tuning, dependency pruning, permanent background updater, or blanket
  cache cleanup. KRDICT resource updates remain their existing independent path.

## 2. Evidence and corrections to the investigation

| Finding | Evidence and consequence |
|---|---|
| Windowed exit crashes | Confirmed against the current `_leave()` using `.venv/Scripts/python.exe`, with both streams set to `None` and both exit functions mocked. Result: `AttributeError("'NoneType' object has no attribute 'flush'")`; neither termination function was called. Add a regression at this seam and a real frozen-windowed exit test. |
| Full downloads and extraction | `ApplicationInstaller.stage()` always fetches the platform archive, verifies it, unpacks a complete bundle, and hands a directory swap to the script. There is no manifest/delta path. |
| Cleanup loses diagnostics | Both application `_remove()` and native handoff cleanup suppress failures; script parent directories are not removed. Long paths are a plausible specific trigger, not proven by timestamps alone. Test locks and permissions too. |
| Progress is incomplete | The coordinator has byte counters, but the page renders only a phase label/bar. `_progress_message()` labels application phases as resource updates. Staging emits `complete` before application success. |
| Machine load | The report records 609 MB downloaded and roughly 1.4 GB extracted. These historical totals were not remeasured by this planning run. Archive writes, hashing, decompression, antivirus, and concurrent resident children are separate contributors to measure. Defender dominance remains a hypothesis. |
| Delta size is unknown | Both old and staged trees still exist in the reported Downloads location. Their executable lengths are 33,861,949 and 33,863,498 bytes. The spec embeds a PYZ in the executable, so a small source edit can replace a sizable binary. Compressed delta size must be measured. |

The `None` behavior is documented by
[PyInstaller](https://pyinstaller.org/en/latest/common-issues-and-pitfalls.html#sys-stdin-sys-stdout-and-sys-stderr-in-noconsole-windowed-applications-windows-only).
Windows long-path support depends on the API and application configuration;
do not assume a global setting fixes every cleanup route. See
[Microsoft's path documentation](https://learn.microsoft.com/en-us/windows/win32/fileio/maximum-file-path-limitation).

Do not carry forward these claims from the report:

- A base-version delta plus an arbitrary disk diff is not automatically
  self-healing: the delta may omit the missing/corrupted unchanged library.
- `.bak` files alone are not a recoverable transaction. Recovery needs a durable
  operation journal and a runner independent of the files being replaced.
- Startup code cannot recover an executable/interpreter that cannot start.
- A signed app is not inherently incompatible with differential delivery;
  reproducing its exact signed target matters. macOS optimization is deferred
  here to bound this Windows fix, not declared impossible.
- Another application's familiar update UX does not establish how it stores
  versions internally. Hanly's decision follows its own constraints.

## 3. Delivery and installation design

### Release artifacts

Generate a versioned Windows file manifest from the **final frozen output**:

```text
hanly-desktop-windows.manifest.json
  schema_version, product, platform, architecture, version, build identity
  files: relative path -> sha256, uncompressed size, component label

hanly-desktop-windows-from-<base>-to-<target>.delta.zip
  changed and added target files only

hanly-desktop-windows.update.json
  schema_version, exact target manifest digest, full asset identity/size/hash
  optional delta: exact base manifest digest/version/build identity,
                  payload identity/size/hash, explicit deletion list
```

Choose canonical schemas once, validate them strictly, and version them. Bind
the metadata, manifest, and delta to the same release/build/architecture, not
just a displayed version. Manifest inventory excludes itself and reserved
updater working files; the release checksums cover the manifest and update
metadata. Include a copy of the installed inventory in new full distributions.
Generate component labels from known package inventory; labels are display
data, never commands or filesystem policy.

Delta production uses the exact previous **published artifact**, verified
against that release's checksums; never rebuild a tag and assume equivalence.
Compare per-file content, not mtimes. Include package metadata removals and
all changed executable/data files. If no valid previous inventory exists, omit
the delta with a recorded reason and publish full delivery plus the new
manifest. Absence of a delta must not block the first transition release.

Keep the current HTTPS/GitHub release trust boundary. Checksums provide
integrity against the selected metadata; they are not independent publisher
signatures. Do not describe them as such or weaken existing verification.

### Client selection and fallback

After Update now, pin the checked release identity. Obtain and verify bounded
metadata, then inspect only managed paths. Stream hashes once in a single
worker; avoid whole-file reads and hash-worker fanout. Show preparation progress.
Do not hash the installation on each check/startup. Reuse the resulting plan
through staging; after processes stop, revalidate mutation preconditions and
detect changes since planning before touching files.

Use the N-1 delta when its verified payload covers every changed/missing target
file required by the actual installation. A wrong base, skipped release,
missing manifest, or uncovered corruption uses a verified full archive as a
**source of files**. On Windows, inspect it and extract only needed target files;
do not extract an entire replacement tree or switch back to directory swapping.
Existing unmanaged files are preserved; a collision with a new managed path
must be reported, not silently overwritten. Delete only paths owned by the
verified old manifest and absent from the target. Do not infer deletion from
"everything not in the new manifest".

If full delivery was known at discovery, show its size with Update now. If
planning discovers that the advertised small delta cannot be used, stop before
the large payload and offer **Download full update — <size>**, with the reason.
This is a material change in download scope, not a routine extra confirmation.
Checksum failure is an error, not permission to ignore integrity or loop through
repeated downloads. Bound retries and timeouts; cancel preparation safely.

Preflight available disk using the selected compressed payload, changed-file
staging, backups of replaced/deleted files, journal overhead and a margin.
Account for both volumes if the helper/log area is elsewhere. Avoid claiming
the disk requirement is just the download size.

### Durable apply and recovery

Extend the existing detached Windows PowerShell handoff rather than adding a
second desktop executable entry point. Its transaction-specific script, journal
reader and small progress UI must run with Windows/.NET alone: no Python,
Hanly, Torch, Qt, or install-directory DLL dependencies. Keep a verified copy
under an owned per-user recovery location, independent of the mutable bundle.
Pass values as arguments/data; never interpolate downloaded text into commands.

Before quitting, ensure the helper is alive and has acknowledged ownership.
Maintain a per-installation lock across processes, not only the coordinator's
in-process lock. Identify processes by PID plus identity/start information;
wait for the shell, lookup and Control Center children to release files.
Never kill unrelated processes by name. Timeouts before mutation leave the old
app intact and report the failed update.

Use a durable journal recording the validated root, transaction ID, base/target
identities, planned operations, original state/hashes, and per-operation intent
and completion. Flush the intent before each mutation. Store backup paths in
the transaction instead of scattering `.bak` siblings through the product.
Use same-volume atomic replacement/rename for each file, with bounded lock
retries and long-path-capable native operations. Handle file/directory type
changes in dependency order. Reject traversal, absolute/UNC/drive paths, ADS,
reserved names, case-fold collisions, reparse-point parents and archive bombs;
check containment again at the write boundary. Do not follow local junctions.

```text
prepared -> helper-ready -> waiting-for-exit -> applying -> awaiting-startup
                                                      -> committed -> cleanup
                                     failure -> rolling-back -> restored
                                             -> recovery-required
```

Every apply and rollback operation must be replayable after interruption,
including an interruption between filesystem success and journal completion.
Rollback restores replaced and deleted files, removes newly added files, and
restores the old installed manifest. Keep backups when restoration fails.
Never launch a known mixed tree or let `owned_cleanup` reap unresolved journals.

Launch the candidate at the same path and require a fresh transaction-bound
acknowledgement of the expected version. Preserve the existing shell-startup
milestone; do not block success on a network dictionary download or OCR warmup.
Write acknowledgement atomically. Stop all candidate children before rollback.
After success, persist a bounded result/log record before removing scratch data.

**Power-loss limit:** this is not an atomic whole-tree update. Before mutation,
provide a durable, discoverable recovery shortcut to the standalone helper.
If the main executable is unlaunchable after a reboot, that helper can restore
the journal without running Hanly or downloading anything. When Hanly can start,
detect pending recovery before normal application initialization. Do not claim
automatic normal-shortcut recovery of an unlaunchable executable; that would
require a separate stable bootstrap and is outside this bundle. Show the
recovery location in pre-install details and preserve it on failure.

## 4. UX and resource-use requirements

Use the existing Control Center styling, spacing, theme and accessibility
patterns. Limit the redesign to Updates. The Windows handoff uses a small
WinForms progress window from the independent helper, with a hidden console;
its presentation must not own transaction correctness. Closing that window
during apply must not kill the transaction. Never keep Qt/WebEngine processes
running from the tree being patched merely to display progress.

| Stage | Required presentation |
|---|---|
| Available | Installed → target version, release notes, delta/full label and known download size; Update now; brief restart explanation. |
| Preparing | Checking installed files, meaningful file/byte counters; cancel available. |
| Downloading | `42% downloaded · 18.4 MB / 43.8 MB · 25.4 MB remaining`, measured speed and ETA only when stable; cancel. Values here are an example, never defaults. |
| Verifying/preparing files | Actual stage and byte/file counts; indeterminate when the denominator is unknown. |
| Installing | Small helper window; `Replacing files 12 / 37`; component and current relative path in Details; explain why cancel is unavailable. |
| Starting | `Starting Hanly <version>…`; no success checkmark yet. |
| Complete | Target version confirmed; concise summary in the reopened app. |
| Failure/rollback | Actionable reason, restoring progress, final restored/recovery-required result, Retry when safe and Open logs/recovery action. |

Use stage-specific percentages; do not fabricate one smooth percentage across
network, extraction and restart. Explain when a download reaches 100% but the
update is still installing. Unknown byte totals never render NaN or 0% forever.
Use consistent MB/GB formatting. Details include timestamped verification,
component update, file add/replace/delete and rollback events, with a bounded
visible tail and persisted diagnostic log. These are bundled-file operations,
not invented pip/package installation logs. Render remote strings as text.

Keep UI updates coalesced (at most about 5 per second), snapshots bounded, and
log tails incremental. Do not rebuild the whole page or resend an ever-growing
log on every chunk. Adapt the existing busy-state/polling rules for every new
stage and ensure late callbacks cannot overwrite newer results. Reopening the
Control Center must recover current progress. Cancel before mutation cleans
only this transaction and retains the running installation.

For performance, reduce work first: no unchanged-file writes, no full duplicate
extraction, no parallel hashing/extraction storm, no whole-archive RAM buffers.
Use one sequential disk worker with cooperative yielding; helper work below
normal CPU priority where supported. Measure before introducing arbitrary
throttles. Do not disable Defender or request antivirus exclusions.

## 5. One-session implementation order

### Phase 1 — Lock down failure and artifact contract

- Preserve the existing uncommitted investigation and other user changes.
- Fix `_leave()` for absent/non-flushable streams without undoing the native
  termination strategy. Add focused regression and real GUI-process exit proof.
- Define manifest/update metadata, plan and progress contracts in app-owned
  modules. Keep runtime modules independent of `tools/`.
- Add the deterministic producer and small fixtures covering replace/add/delete,
  unchanged large dependencies and fallback. Measure actual artifact differences
  before publishing any savings claim.

Exit: exit regression passes; producer and consumer agree on one validated schema.

### Phase 2 — Prepare only needed files

- Implement release pinning, disk inspection, delta selection, explicit full
  fallback, selective extraction, hash/size validation, cancellation and disk
  preflight in/alongside `app_update.py`.
- Reuse bounded delivery primitives from `update_service.py`; keep the resource
  updater's behavior and errors separate.
- Reject unsafe inputs before touching live files. Tests assert unchanged files
  are neither staged nor written and unmanaged/user data survive.

Exit: a verified operation plan and minimal payload exist; the running tree is untouched.

### Phase 3 — Apply, rollback, and surviving progress

- Implement the independent handoff, durable journal, install lock, child exit
  coordination, recovery invocation, and transaction-bound startup result.
- Integrate `owned_cleanup.py`, `cli.py`, `application.py`, and acknowledgement.
  Do not rely on app startup as the only recovery route.
- Exercise a real native helper on a disposable install, including failure and
  interrupted apply. Never run destructive probes on the user's Downloads app.

Exit: success keeps the same install path; failure restores the previous tree
or retains a usable standalone recovery route with all necessary backups.

### Phase 4 — Integrate UI and release lane

- Extend `update_coordinator.py`, the Control Center bridge/process allowlist,
  and `assets/control_center/` HTML/CSS/JS. Implement the stage table and real
  activity details, including the handoff window and post-launch outcome.
- Update `tools/build_package.py`, `.github/workflows/build.yml`,
  `.github/workflows/release.yml`, relevant release tooling/tests and packaging
  docs. Both stage and finalize currently enumerate exactly four application
  archives/seven final assets: update every validator/upload/checksum/inventory
  step for the new explicitly allowed metadata/delta assets. Do not replace
  strict validation with arbitrary wildcard uploads.
- Generate the manifest after the frozen tree is finalized and before archiving.
  Assemble the optional delta from verified base and target artifacts. Include
  new products in build reports, uploads and final checksum verification.
- Preserve tag/build provenance, repeat-run idempotency, KRDICT carry-forward,
  validate-only non-mutation, and the human publication gate.
- Update `docs/CODE-MAP.md` and `packaging/README.md` to describe actual behavior,
  platform scope, recovery and transition. No unrelated architecture edits.

Exit: release fixtures prove a new client can discover and consume the produced
assets; old clients still find the unchanged full-archive asset names.

### Phase 5 — Convergence validation and handoff

Run focused tests during implementation as needed; run broad gates once at
convergence and repeat only for relevant subsequent fixes. This is implementation
validation, not a separately commissioned deep review.

Required focused coverage:

- Metadata-only discovery and explicit-click payload start; repeated clicks and
  concurrent app instances cannot start competing transactions.
- Correct base delta; skipped/mismatched base; corrupt unchanged file absent from
  delta; full-fallback size disclosure; tampered metadata/payload; stale release.
- Add/replace/delete, package metadata removal, unmanaged files, path collisions,
  insufficient space, cancellation, locked file, long/space/Hangul paths.
- Actual Windows helper success, child locks, wrong/missing startup ack, rollback,
  interruption during replace and rollback, recovery with a broken app executable,
  cleanup failure without loss of backups. Use deterministic fault injection at
  journal boundaries; do not cut machine power.
- UI progress units, unknown totals, truthful completion, cancellation state,
  bounded details, error/retry, keyboard access and narrow/high-DPI layout.
- Existing Linux/macOS handoff behavior remains covered by their native lanes.
- Release producer/consumer integration and all added asset allowlists; missing
  optional delta versus incomplete/corrupt advertised delta are distinguished.

Run from the authoritative environment:

```powershell
.venv/Scripts/python.exe -m pytest
.venv/Scripts/python.exe -m ruff check packages packaging tests tools benchmarks
.venv/Scripts/python.exe -m mypy packages packaging tests tools benchmarks
.venv/Scripts/python.exe tools/build_package.py --platform windows
```

Follow `packaging/README.md` and current `build.yml` for model preparation,
the smoke KRDICT, inventory/worker/window smokes and required packaged tests.
Set `HANLY_PACKAGED_APP` to the newly built app and `HANLY_REQUIRE_PACKAGED=1`
for the packaged gate so a missing artifact cannot turn into a green skip.
Record interpreter/runtime versions; local Python 3.13 is not proof of the
release matrix's Python 3.10 compatibility.

In disposable copies, run a **real frozen old → new Windows update** using the
same produced manifest/delta and normal click/handoff path. Exercise a failed
candidate and restoration too. Small fake fixtures are useful but cannot replace
this windowed-executable/NTFS proof. Preserve an old artifact before a clean
build overwrites build output. A baseline containing this updater and a target
with controlled version/content changes may be built for the probe without
committing; keep fixture version changes out of the final product diff.

Measure one controlled before/after comparison with the same target content,
machine, antivirus setting, and app residency state. Record selected payload
bytes, files/bytes hashed and written, peak scratch disk, per-stage elapsed
time, app/helper peak memory and CPU, and UI responsiveness. Observe disk and
antimalware activity where available. Use a single baseline run; do not repeatedly
stress the user's PC. Historical 609 MB figures may be context, not a controlled
baseline. Acceptance: identical target managed content, zero unchanged-file
writes, substantially reduced payload/writes on a dependency-stable patch, no
unbounded memory/log growth and no updater work on the UI thread. Report actual
numbers and unresolved bottlenecks instead of claiming the stall disappeared.

**CI/CD with no push:** run local equivalents and validate workflow changes.
Remote Actions cannot test uncommitted changes by dispatching the existing ref.
Do not push to make CI run, and do not report an old-ref build as evidence for
this diff. If suitable native runners are already available, use them without
publishing; otherwise label the Linux/macOS/remote release gates NOT RUN with
the exact reason and command/lane still required. A dry-run command is not a
build. Infrastructure blockers do not justify claiming all CI passed.

Write exactly one implementation handoff:
`docs/execution/review-handoffs/updater-differential-2026-09-15.md`, using the
existing template. Include changed areas, test/build results, real update and
performance evidence, artifact locations, migration/recovery instructions,
limitations and unrun gates. Move associated work to In Review, not Done.
Then **STOP AND WAIT FOR THIAGO'S FINAL REVIEW. NO COMMIT OR PUSH.**

## 6. Existing-install migration

The new code cannot retroactively repair `_leave()` in an already running
0.5.0/0.5.1 executable. Merely publishing a fixed target does not make that old
updater exit correctly. Do not advertise a seamless differential first update
from those versions.

Deliver the first fixed build with normal full archives and a documented
one-time replacement/recovery procedure that preserves the installation path
and user data. Execute that procedure only when separately asked to modify the
user's actual install; this bundle tests it on copies. Preserve the known
staged Downloads artifact as evidence, not something implementation may delete.
The first manifest-aware build becomes the baseline for ordinary N-1 deltas.
Legacy installs without trustworthy file ownership do not get guessed deletion
lists. Their migration establishes the inventory before differential updates.

## 7. Platform strategy: is macOS and Linux doing the right thing?

Asked after Phase A: are the macOS and Linux paths the best available, and is
what they do what Apple and the ecosystem recommend? Short answer: **Linux is
not, macOS is half right, and neither was changed because §1 bounded this
bundle to Windows.** That was a written scope decision, not an oversight.

### macOS

Apple publishes **no** auto-update mechanism for directly distributed apps; the
App Store updates store apps and that is the whole of Apple's provision. What
Apple *does* impose is the constraint that matters here: an app is signed and
notarized **as a bundle**. `Contents/_CodeSignature/CodeResources` seals every
file with its digest, and the notarization ticket is stapled to the bundle.

**So patching files inside an installed `.app` is wrong on macOS.** It breaks
the seal, `codesign --verify` fails, and Gatekeeper refuses to launch what is
left. Our whole-bundle replacement is therefore the *correct* half, and must
stay.

What is not optimal is the *download*. Sparkle - the de-facto standard, used by
most directly distributed Mac apps - ships binary **delta** updates: a patch
between two published versions is applied to a staged copy, producing a bundle
byte-identical to the new signed one, which is then swapped in atomically with
`NSFileManager.replaceItemAt`. The seal survives because the patched result *is*
the signed build.

The right macOS design, then:

1. Publish a delta between two published bundles, as Windows now does.
2. Clone the installed bundle into staging. On APFS `clonefile` makes this
   nearly free in space and time, so the copy this strategy needs is not the
   cost it would have been on HFS+.
3. Apply the changed files into the clone.
4. Verify the result's signature **before** anything is swapped.
5. Atomically replace the whole bundle, exactly as today.

That keeps every existing guarantee and removes the full download. It is more
work than Linux and should not be attempted without the signing question
settled first.

### Linux

Ours is **not** the best available, and Linux is the easier of the two.

There is no bundle-signing constraint, and POSIX lets a running program's file
be renamed over - the running inode survives - so per-file replacement needs
neither the locked-file dance nor the stop-the-app step Windows requires. The
Windows design in §3 applies almost unchanged, and is simpler there.

What the ecosystem does, for reference: Flatpak/OSTree is the modern answer
(content-addressed, file-level dedup, true deltas), AppImage uses zsync for
block-level delta downloads, and Snap ships xdelta3 deltas. If Hanly keeps its
plain tarball rather than adopting one of those, the file-manifest design is
the correct thing to build.

### Recommendation

| Platform | Today | Should be | Effort |
|---|---|---|---|
| Windows | file-level, in place | done | - |
| Linux | full archive, directory swap | the same design as Windows | small; no signing, no locked files |
| macOS | full archive, bundle swap | delta applied to an APFS clone, signature verified, bundle swapped | larger; signing must be settled first |

Neither is a defect in what shipped. Both are the next bundle.

## 8. Updates

**2026-09-15 — Phase A complete, Windows only.** Handoff at
`review-handoffs/updater-differential-2026-09-15.md`. Two defects fixed that
each independently prevented the reported update: `cli._leave` crashing on a
windowed build's absent streams, and `spawn_detached` passing
`DETACHED_PROCESS`, under which PowerShell exits zero having run none of its
script. Measured on a real frozen 0.5.1 to 0.5.2 update: 1,062,979 bytes
downloaded against 648,557,160, and 17 files written against 6,118.

**Known outstanding, in priority order.**

1. **Linux differential update.** As above. The design already exists.
2. **macOS differential download.** As above, behind the signing question.
3. **The packaged worker check fails** loading `torch/lib/c10.dll`
   (WinError 1114), deterministically, on this host. Not attributed to this
   work - nothing in the diff touches the spec, constraints, hooks, or any
   import torch depends on - and not claimed to pass. Needs a machine with
   room, ideally against a build from before the branch.
4. **Two defects found after the handoff and deliberately left in place**, at
   the human's instruction, because they were found by unrequested work:
   - the Control Center offers a Cancel action on the whole-bundle path, where
     no installer observes it, so the click does nothing while the download
     continues. macOS and Linux only.
   - the disk preflight counts backups as new space. Moving an original aside
     is a rename on the installation's own volume and costs nothing, so the
     requirement is inflated by the size of every replaced file on top of a
     fixed 256 MB margin. It refuses some updates a volume could hold.
5. **The helper's progress window and the new Control Center panel have never
   been looked at.** Every native run passes `-Quiet`, and the UI tests assert
   on asset contents rather than a rendered page. The logic is exercised; the
   pixels are not.
6. **CI has not run this diff** and cannot while it is uncommitted. The Linux
   and macOS release lanes are NOT RUN.

## Completion checklist

- [ ] Same Windows install path; changed/added/deleted managed files only.
- [ ] No application payload fetched before Update now.
- [ ] Full fallback is explicit and its size is visible.
- [ ] Windowed exit, child shutdown, helper apply and rollback work natively.
- [ ] Interrupted update recoverable independently of the main executable.
- [ ] Progress, remaining bytes and genuine activity details survive handoff.
- [ ] Reduced work measured; no unsupported Defender or delta-size claims.
- [ ] New release assets validated end to end; legacy archives preserved.
- [ ] Tests and Windows build/smokes run; unavailable CI/native gates explicit.
- [ ] One Review Handoff; waiting for human review; no commit, push or publication.
