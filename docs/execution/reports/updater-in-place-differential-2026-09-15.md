# Updater investigation: the 0.5.0 → 0.5.1 failure, and the case for in-place differential updates

*2026-09-15. Diagnostic report, not an approved plan. Written from a real failed
update on `C:\Users\Thiago\Downloads\hanly050`.*

## Summary

A user-driven update from 0.5.0 to 0.5.1 downloaded 609 MB, unpacked 1.4 GB,
stalled the machine for several minutes, crashed the application with an
`AttributeError`, never replaced the installation, and left a 1.4 GB orphaned
staging directory behind. Three distinct defects, one of which is the root
cause; the third is architectural and is what the user actually wants changed.

| # | Defect | Severity | Independence |
| --- | --- | --- | --- |
| 1 | `_leave` crashes on a windowed build, so the process never exits | **Root cause.** Blocks every update. | Fixable alone, 3 lines |
| 2 | Handoff cleanup silently fails, orphaning the transaction directory | Leaks 1.4 GB per attempt | Fixable alone |
| 3 | Every update ships and rewrites the whole application | The lag, the disk cost, the duplicate folder | The real work |

---

## Defect 1 — the crash, and why it stopped the swap

`packages/hanly-app/src/hanly_app/cli.py:145-152`:

```python
def _leave(status: int) -> NoReturn:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except (OSError, ValueError):
            pass
    _terminate_without_unloading(status)
    os._exit(status)
```

`packaging/hanly-desktop.spec:220` sets `console=False`. In a windowed
PyInstaller build **`sys.stdout` and `sys.stderr` are `None`**. `None.flush()`
raises `AttributeError`, which is not in the caught tuple, so it escapes
`main()` and neither `_terminate_without_unloading()` nor `os._exit()` runs.

The user-visible traceback is the smaller half of the problem. The larger half:
the windowed bootloader catches the unhandled exception and presents a **modal
error dialog**, and the process stays alive holding it. The handoff script is
meanwhile polling `Get-Process -Id $OldProcessId` under
`EXIT_WAIT_SECONDS = 120` (`app_update_handoff.py:36`). It waits two minutes for
a process that is never going to exit, times out, and returns without renaming
anything.

That is the entire explanation for "the hanly-desktop remains at 0.5.0".

This fires on **every** quit of a windowed build. The update path is only where
it does visible damage, because it is the one path where something else is
waiting on the exit.

### Evidence

Disk timestamps in `hanly050`, cross-referenced with
`%LOCALAPPDATA%\Hanly\logs\hanly.log` (log is UTC, disk is UTC-3):

| local | event |
| --- | --- |
| 00:35:56 | session starts (`version hanly-app: 0.5.0`) |
| 00:37:33 | `.hanly-update-efqyhaae` created by `_open_transaction` |
| 00:38:18 | staged `hanly-desktop.exe` written |
| 00:38:41 | `_internal/` appears; extraction underway |
| 00:40:52 | extraction completes, `_place` runs, handoff script written to `%TEMP%\hanly-update.x6xgaqf_`, log records `Control Center: Window 1 is closed (exit 0)` |
| — | **log ends.** No shutdown line, no relaunch, no `--update-ready` session. |
| ~00:42:52 | handoff hits `EXIT_WAIT_SECONDS` and bails |

The staged tree is a complete, checksum-verified 0.5.1 build — it carries
`_internal/hanly_app-0.5.1.dist-info` and `_internal/hanly-0.5.1.dist-info`.
Download, `verify_checksum`, extraction, and `_place` all succeeded. Only the
swap never happened.

### Fix

```python
for stream in (sys.stdout, sys.stderr):
    if stream is None:
        continue
    try:
        stream.flush()
    except (OSError, ValueError, AttributeError):
        pass
```

Skipping `None` is the actual fix; widening the tuple to `AttributeError` guards
any other stream replacement that does not implement `flush`.

Worth a regression test that calls `_leave` with `sys.stdout`/`sys.stderr`
monkeypatched to `None` — this is a one-line condition that the whole update
mechanism rests on, and nothing currently exercises it.

---

## Defect 2 — cleanup fails silently and leaks 1.4 GB

`_WINDOWS_HANDOFF` (`app_update_handoff.py`):

```powershell
function Complete-Handoff {
  Remove-Item -LiteralPath $Transaction -Recurse -Force -ErrorAction SilentlyContinue
  Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
}
```

`.hanly-update-efqyhaae` still has an mtime of 00:40:52 — the timestamp of the
last *staging* write. The 00:42:52 delete touched nothing at all. PowerShell
5.1's `Remove-Item -Recurse` fails on the >260-character paths inside
`_internal` (the torch and scipy trees), and `-ErrorAction SilentlyContinue`
swallows the failure completely, so the handoff reports nothing and exits 1.

Four orphaned `%TEMP%\hanly-update.*` directories are also present, from
successive attempts at 23:52, 00:35, and 00:40. `Complete-Handoff` removes
`$PSCommandPath` but never its parent directory, so even a *successful* handoff
leaks an empty directory each time. One of the four contains a
`hanly-update.sh`, meaning a POSIX script was rendered on Windows at some point
— worth a glance, though it is most likely a test artifact rather than a
product path.

### Fix

- Delete through a long-path-safe route (`\\?\`-prefixed .NET calls, or
  `cmd /c rd /s /q`, or hand the removal to the relaunched Python process which
  already handles this correctly via `shutil.rmtree`).
- Remove the script's parent temp directory, not just the script.
- Do not silence the result. A cleanup failure should reach the diagnostics log
  on the next launch, otherwise this leaks a gigabyte per failed attempt with no
  signal anywhere.

---

## Defect 3 — the update ships the whole application

This is the one the user is actually complaining about, and it is a design
choice rather than a bug.

`v0.5.1` release assets:

```
hanly-desktop-windows.zip      609.0 MB
hanly-desktop-linux.tar.gz     734.2 MB
hanly-desktop-macos.zip        562.0 MB
hanly-desktop-macos.dmg        648.3 MB
```

The Windows zip unpacks to **1.4 GB across 5,560 files**. What dominates:

```
PyQt6            440M
torch            371M
cv2              112M
kiwipiepy_model  105M
hanly_app         95M
scipy             63M
_kiwipiepy.pyd    24M
numpy.libs        21M
scipy.libs        20M
```

Roughly **1.09 GB of that is byte-identical between 0.5.0 and 0.5.1.** A patch
release changes Hanly's own code and little else; PyQt6, torch, cv2, the
kiwipiepy model, and scipy do not move.

### What the cost actually is

Per update, on the user's machine:

- 609 MB downloaded
- SHA-256 computed over all 609 MB (`verify_checksum`, 1 MiB chunks — the
  implementation is fine, the volume is not)
- `zipfile.extractall` writing 5,560 files single-threaded, preceded by a
  `Path.resolve()` per member in `_require_contained`
- peak disk of 609 MB zip + 1.4 GB staged + 1.4 GB installed ≈ **3.4 GB**
- Windows Defender real-time scanning every one of 5,560 freshly written DLLs
  and executables as they land

The last item is almost certainly the dominant cause of "my whole PC is
lagging". It is not Hanly's CPU; it is the antimalware service doing 1.4 GB of
on-write scanning against the same disk the extraction is writing to.

### The staging directory is not a bug in itself

`_open_transaction` creates `.hanly-update-*` beside the installation
deliberately — the swap that follows is then a rename on one filesystem rather
than a copy that can half-finish, and the whole transaction is reversible by
removing one directory. That reasoning is sound for a whole-bundle replacement.
It stops being necessary once the update stops being a whole-bundle
replacement.

---

## How shipped desktop apps do this

None of the applications the user named ship the whole product on a patch
release.

- **Steam, Epic, Riot** — content-addressed *chunk manifests*. The client holds
  a manifest of its installed content; the new release publishes its own; the
  client downloads only the chunks whose hashes differ and patches files in
  place.
- **Chrome, Figma** — binary deltas (bsdiff, and Chrome's Courgette, which
  understands executable relocation tables and gets far smaller diffs than
  bsdiff on native code).
- **Electron apps (`electron-updater`)** — a `.blockmap` published beside the
  installer; the client range-requests only the differing blocks. This is the
  cheap version of the same idea.
- **Blender** — genuinely does ship full builds, but is a manual download, not
  an in-app updater, which is why nobody experiences it as a stall.

The common shape across all of them: **a per-file or per-block hash manifest
published with the release, and a client that fetches only what changed.**

---

## Proposed direction

Three pieces, in this order. A is independent and can ship immediately; B is
the real work; C is small and can ride along with either.

### A. Fix the crash

As in Defect 1. Three lines plus a regression test. This alone makes the
*current* updater work end to end — the user's 0.5.1 would have installed.

### B. In-place differential update

Constraint stated by the user: **no second folder. Patch the files that are
already there, in the same folder.**

**Build side** — `tools/build_package.py` additionally emits, per release:

- `hanly-desktop-<platform>.manifest.json` — `{path: {sha256, size}}` for every
  file in the bundle.
- One delta asset per supported previous version, containing only
  changed-or-added files plus an explicit delete list.

For 0.5.0 → 0.5.1 that delta is a few MB against 609 MB.

**Client side:**

1. Fetch the new manifest first (small).
2. Diff it against what is actually on disk by hashing the installed tree. This
   is strictly better than trusting a recorded version: it self-heals files
   corrupted or removed since install, and it means a mismatched local state
   degrades to "download more" rather than "install a broken build".
3. Download the delta whose base version matches. Fall back to the full archive
   only when no usable delta exists.
4. Verify the delta against `SHA256SUMS` exactly as today, then verify each
   extracted file against the manifest's per-file digest.

**Apply, in place:**

- Stage the changed files into `hanly-desktop\.hanly-staging\` — *inside* the
  installation, as specified.
- The handoff does per-file replacement (`MoveFileEx` / `os.replace`) into
  `hanly-desktop\`, not one directory-level swap.
- Each replaced file keeps a `.bak` sibling until the new build confirms startup
  through the existing `--update-ready` acknowledgement, then the `.bak` files
  and the staging directory are dropped.

**The honest trade-off, stated plainly:** per-file replacement is not atomic the
way the current directory rename is. A power loss mid-apply leaves a mixed
tree. The `.bak` sidecars make that recoverable rather than fatal — the handoff
can roll each one back on the next launch — but it is weaker than what exists
today. It is the cost of the in-place requirement, and it is the same trade
Steam and Chrome make. Worth confirming the user accepts it before building.

**What this buys:** a few MB instead of 609, a few dozen files written instead
of 5,560, no 1.4 GB duplicate, no 3.4 GB peak, and Defender scanning a handful
of files instead of a gigabyte. The stall disappears because the work
disappears.

### C. Cleanup hardening

As in Defect 2. Long-path-safe removal, remove the script's parent directory,
and surface cleanup failures to diagnostics instead of swallowing them.

---

## Open questions for planning

1. **How many previous versions carry a delta?** One (N-1 only) is simplest and
   covers the common case; three or four covers users who skipped releases. Full
   archive is always the fallback either way.
2. **File-level or block-level deltas?** File-level is far simpler and already
   wins ~99% here, because the huge dependencies are untouched between patch
   releases. Block-level (bsdiff per file) only starts to matter if a large
   dependency like torch or PyQt6 is itself bumped — at which point that one
   file is 371 MB and a binary diff would still help. Recommend starting
   file-level and revisiting only if dependency bumps prove common.
3. **Is the non-atomic in-place apply acceptable?** See the trade-off above.
4. **Does the same shape hold on macOS?** A `.app` bundle is signed as a unit;
   per-file replacement inside `Contents/` invalidates `_CodeSignature`.
   The macOS path likely has to keep whole-bundle replacement, which means the
   updater carries two apply strategies rather than one. Windows and Linux get
   the in-place path.

---

## Immediate recovery for the affected install

The staged build is intact and verified. With Hanly closed:

1. Rename `hanly050\hanly-desktop` to `hanly-desktop-old`.
2. Move `hanly050\.hanly-update-efqyhaae\hanly-desktop` up into `hanly050\`.
3. Launch it, confirm it reports 0.5.1.
4. Delete `hanly-desktop-old`, the now-empty `.hanly-update-efqyhaae`, and the
   four `%TEMP%\hanly-update.*` directories.

---

## Files involved

| Path | Role |
| --- | --- |
| `packages/hanly-app/src/hanly_app/cli.py` | `_leave`, the crash |
| `packages/hanly-app/src/hanly_app/app_update.py` | check, download, verify, unpack, stage |
| `packages/hanly-app/src/hanly_app/app_update_handoff.py` | the detached swap script, both platforms |
| `packages/hanly-app/src/hanly_app/update_service.py` | shared download / `verify_checksum` / `extract_archive` |
| `packages/hanly-app/src/hanly_app/update_coordinator.py` | off-UI-thread orchestration, `restart_required` |
| `packaging/hanly-desktop.spec` | `console=False`, the windowed build |
| `tools/build_package.py` | where a manifest and delta assets would be produced |
| `docs/execution/review-handoffs/han-42-updater-reliability.md` | prior work on this subsystem |
