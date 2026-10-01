# Review handoff: benchmarks become the Hanly Lab

Branch `lab/app-health`, on top of `25e143b`. Uncommitted at handoff; nothing pushed.

## Why

The app-health lab (`app-lab run --scenario ...`) orchestrated fixed pytest
selections and produced a pass/fail page. It never ran Hanly the way a person
does and showed nothing about how a hover moved through the processes. The
human asked for the benchmark harness to become a lab: the real app running,
every action recorded, a visual report of where each stage spends time, and an
agent able to drive it.

## What changed

- `benchmarks/dev/` is now the top-level `lab/` package (`benchmarks/fixtures`
  → `lab/fixtures`, `app_lab` → `lab/checks`). Artifacts moved from
  `artifacts/benchmarks/` to `artifacts/lab/`. Every existing command remains;
  `app-lab` is now `check`.
- `python -m lab` (`run`): the real desktop through `run_desktop` with a
  recording trace sink, a diagnostics log that turns startup phases into events,
  and a sampler that knows the shell's children by name. Disposable profile per
  run. No recognized text retained.
- `python -m lab tour`: a full-screen page of lab-authored Korean (minibook
  story plus seeded KRDICT headwords at several sizes, faces and themes); the
  driver presses the real capture shortcut, glides the real pointer, and scores
  each popup against the known answer. Moving the mouse stops it.
- `python -m lab report [run]`: `report.html` (findings, annotated system map,
  time breakdown, funnel, timeline with memory and CPU, hover explorer with
  per-hover waterfall and cross-process event trail, tour accuracy, startup,
  processes), `report.json` and `summary.md`, all rebuilt from the run files.
- Production, one opt-in field: `encode_result_evidence` and `result_evidence`
  on the `total_pipeline` stage event, emitted only to a sink with
  `retain_evidence`, like the four existing evidence fields. Test:
  `tests/test_lookup_evidence.py`.

## Privacy

A tour retains recognized text so failures can be explained. Before each hover
the driver asks the window server (`lab/session/ownership.py`) who owns the
capture region's centre and corners. Any foreign owner means the target is
skipped and never read. Evidence is kept only while a verified hover is open.
The first spike exposed exactly this risk: a `Tool` page window hid when the
Control Center activated, and OCR read the Control Center. Fixed, and guarded.
A human `run` persists no evidence; `tests` assert both.

## Evidence (macOS 26, Vision)

- 303-hover tour: 231 scored, 96.1% correct. Uncached answer median 156 ms after
  an 80 ms dwell: OCR 37 ms, screen capture 27.5 ms, language 2.4 ms. Kiwi
  prewarm 1.1 s of a 1.2 s engine prewarm. Lookup child peak 730 MiB.
- Failures it found: five language-layer misses (`손님이`→`손`,
  `비밀번호는`→`비밀`, `뭉클해졌습니다`→`뭉클`, `드릴`→noun 드릴,
  `누군가는`→`누이다`), two resolver misses (text read, no word chosen), one
  OCR misread, one empty read at 16 px.
- 72 hovers were skipped because a macOS Screen Recording dialog was open over
  the page; the guard refused them as designed.
- Gates: portable 2,408 passed / 2 skipped, native 125 passed, ruff and mypy
  clean on 323 files.

## Open

- Windows: ownership uses `WindowFromPoint`, untested; the tour page and pointer
  driving have not run there. Linux cannot verify ownership and skips every target.
- Shell RSS includes the in-process recorder.
- The Codex Phase B items in `app-health-lab-mac-2026-10-01.md` (frozen
  Control Center identity, Windows updater) are untouched by this work.
