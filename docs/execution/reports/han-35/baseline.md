# HAN-30 Reconciliation and HAN-35 Baseline

Date: 2026-08-23  
Commit: `24ed285bd8cc33390875917d602a3a8526e77128` (`v0.1.0`)  
Evidence environment: Windows 10 `10.0.19045`, AMD64, Python 3.13.11,
8 physical/logical CPUs, 17,111,166,976 bytes RAM.

## HAN-30 compact reconciliation

| Area | Proven locally | Proven by real GitHub Actions | Still human/frozen-artifact evidence | Blocked/unavailable here |
| --- | --- | --- | --- | --- |
| Build matrix | Workflow/static tests and local Windows package snapshot | macOS, Linux, Windows packaging jobs completed | Inspect/download final artifacts and verify expected inner archive layout | No Actions log/artifact connector evidence beyond the human result |
| First-run bootstrap | Fake-transport bootstrap, config creation, activation/revalidation tests | Build includes current code | Clean-profile frozen launch with real HTTPS resources and visible progress/failure | Production resource artifacts unavailable locally |
| Runtime config creation | Automated local tests | Code packaged on all three platforms | Verify per-user `runtime.json` created by frozen Windows app | Frozen artifacts not launched |
| Resource provisioning/update | HTTPS/checksum/staging/rollback and local runtime validation tests | Packaging completed | Real assets, offline repeat launch, update/release delivery | Final resource assets/release unavailable |
| Frozen GUI startup | Local static PyInstaller snapshot only | Packaging jobs completed | Launch each platform artifact; Windows must not silently exit | macOS/Linux hosts unavailable; Actions success is not launch proof |
| Tray / Control Center | Windows development/runtime and automated tests | Packaging only | Real frozen interaction and lifecycle | macOS/Linux desktop unavailable |
| OCR / lookup / popup / hover | Fresh real Windows development lookup plus automated coverage | Packaging only | Frozen OCR/manual/hover/popup correctness | Human screen interaction and non-Windows hosts |
| Release flow | Static tests verify tag/version, archive selection, manifest/checksums | Build artifacts exist | Human dispatch and final release-asset inspection before publication | Publication intentionally not authorized |

HAN-30 remains **In Review**. This pass does not mark HAN-30, HAN-31, HAN-32,
or HAN-35 Done.

## Fresh local automated evidence

Commands run from the repository root with `.venv`:

```text
.venv\Scripts\python.exe -m pytest
379 passed in 16.33s

.venv\Scripts\python.exe -m ruff check packages packaging tests tools
All checks passed!

.venv\Scripts\python.exe -m mypy packages packaging tests tools
Success: no issues found in 88 source files
```

Evidence class: **local automated-test evidence**. These results do not prove a
frozen executable or another platform.

## Fresh real development-runtime evidence

The existing `tools/dev_lookup.py` composition ran with real configured local
Paddle models, PaddleOCR 3.7.0, PaddlePaddle 3.3.1, Kiwi 0.23.2, and the local
KRDICT SQLite database:

```text
input: tests/hanly_fixtures/assets/korean_reading_roi.png
target: (100, 24)
OCR text: 책을 읽습니다.
OCR confidence: 0.9820699691772461
selected text: 읽습니다.
lemma / key: 읽다
dictionary: 읽다 — to read
status: SUCCESS
```

The first sandboxed attempt failed before OCR because access to the configured
model directory under the user profile was denied. The same existing command
was rerun with authorized filesystem access and succeeded. This is classified
as **development-runtime evidence**, not frozen-package evidence. The committed
Korean ROI is a deterministic correctness fixture and is not an OCR accuracy or
representative performance corpus.

## Local package/static baseline

Snapshot: `dist/windows/hanly-desktop` built locally with Python 3.13. This
directory is untracked and its exact build provenance is not encoded, so the
figures are local static composition evidence only.

| Metric | Value |
| --- | ---: |
| Files | 10,530 |
| Uncompressed bytes | 1,771,099,850 (1,689.05 MiB) |
| ZIP bytes | 642,199,500 (612.45 MiB) |
| PyQt6 | 557,091,478 bytes (531.28 MiB) |
| torch | 378,355,218 bytes (360.83 MiB) |
| paddle | 376,927,670 bytes (359.47 MiB) |
| cv2 | 147,108,040 bytes (140.29 MiB) |
| scipy + scipy.libs | 73,720,832 bytes (70.30 MiB) |
| numpy + numpy.libs | 27,864,144 bytes (26.58 MiB) |
| pandas + pandas.libs | 13,676,772 bytes (13.04 MiB) |
| PaddleX package directory | 6,951,496 bytes (6.63 MiB) |

PyQt6, Torch, Paddle, and OpenCV account for approximately 1.39 GB before
metadata/overlap analysis. This identifies where to investigate; it does not
show that any component is safe to exclude.

## Exact external/human checklist still required

1. Download the current Windows Actions artifact.
2. Extract the Actions wrapper, then the application archive.
3. Launch `hanly-desktop.exe`; confirm it no longer silently exits.
4. Confirm per-user runtime config creation.
5. Confirm real first-run resource provisioning and usable progress behavior.
6. Force provisioning/startup failure and confirm a visible actionable dialog.
7. Confirm tray and Control Center interaction.
8. Confirm real OCR, manual lookup, hover, popup placement, latest-wins, and
   repeated hotkey behavior.
9. Confirm repeat/offline launch uses installed resources.
10. Exercise Windows open-SQLite update replacement and real-terminal SIGINT.
11. Smoke-test the macOS and Linux frozen desktops on actual hosts, including
    permissions/backends; record Wayland separately if available.
12. Inspect the final application/resource artifacts, manifest, checksums, and
    direct release asset layout before any publication.
13. Validate the human release flow without treating a build as release proof.

## Evidence-class boundary

- Current Actions result: **real GitHub Actions build evidence** for all three
  packaging jobs.
- Local package tree: **local packaging/static evidence**.
- Fresh real lookup: **development-runtime evidence**.
- Full suite: **local automated-test evidence**.
- Frozen-package runtime evidence: **missing**.
- Cross-platform/manual-human runtime evidence: **missing** except historical
  Windows development checks explicitly cited in handoffs.
