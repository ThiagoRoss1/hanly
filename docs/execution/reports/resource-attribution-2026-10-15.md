# Resource attribution — first evidence (2026-10-15)

Developer evidence from `python -m lab resources` (protocol `resources-v1`) on
one Apple Silicon Mac, with the Apple Vision recognizer and Python 3.13.11.
Package versions:
- kiwipiepy 0.23.2;
- easyocr 1.7.2;
- torch 2.13.0.

The runs are under the gitignored `artifacts/lab/runs/`. Each `summary.md` holds
provenance, method and limits. This is future work and blocks nothing. The
1.2 GB figure is a **proposed** product budget, not a guarantee.

## How to read the numbers

- **Primary figure:** the macOS physical footprint, read at stage boundaries
  while the child waits.
- **Peaks:** sampled every 20 ms; each stage's window starts at the previous
  boundary.
- **Deltas:** estimates. Shared libraries, allocators that keep freed pages,
  compression and initialization order move them.
- **Calibration:** every run maps and releases a known 64 MiB. Every run here
  attributed +64.1 MiB and released −64.0 MiB.
- **RSS is not used for attribution.** It fell to 16 MiB while a process held
  81 MiB of footprint once idle pages were compressed.

## What costs what (`20261015-230644-resources`; 3 repeats, 12 lookups, 8 inputs)

| | ready cost (validated runtime → first answer) | sampled startup peak | after idle | released by unloading | left until process exit |
|---|---|---|---|---|---|
| whole lookup pipeline | 494 MiB (493–509) | 564 MiB (561–567) | 521 MiB | 108 MiB | 270 MiB (270–385) |
| Kiwi alone | 426–456 MiB | 553–581 MiB | 484 MiB | 105 MiB | 236 MiB |
| Vision alone | 57 MiB | 85 MiB | 61 MiB | 0 MiB | 33 MiB |
| KRDICT alone | 0.3 MiB | 31 MiB | 27 MiB | 0 MiB | 0 MiB |

**Findings:**
- **Kiwi is about 85 % of the lookup child's cost.** It also adds a transient
  peak of about 97 MiB while its model loads. The isolated sum (513 MiB) matches
  the whole sequence (494–512 MiB), so loading components together creates no
  duplication.
- **Every provider defers its load to first use or prewarm.** Construction
  costs ≤ 0.2 MiB, so measuring constructors would miss nearly everything. The
  report names deferred loading explicitly.
- **Unloading in process returns only about 108 of 494 MiB.** The rest stays
  with the native allocators until the process exits. Retiring the lookup child
  is therefore the release mechanism that works, which supports the existing
  design. Unloading in process would not deliver it.
- **No duplicate provider instances.** Live-object counts at assembly, idle and
  unload show one of each provider.
- **Cache hits are free and fresh work is cheap.** Repeating the same input
  hits the worker cache: 0 MiB and about 0.03 ms. Varied inputs grow by about
  0.4 KiB per lookup over 150 operations, once the bounded cache has filled.
- **Runtime validation reads 89–123 MiB from disk in 0.1–0.5 s.** It isn't
  attributed yet. The dictionary check uses a size-and-mtime identity, so
  library page-ins are the leading suspect. It's measured, not explained.

## Whole application (recorded debug session `20261015-051224-run`)

RSS totalled per role per sample, with process-tree attribution. Totals across
processes double-count shared pages and understate idle compressed memory.

| phase | family peak | family median |
|---|---|---|
| startup | 131 MiB | 90 MiB |
| engine warm-up | 364 MiB | 364 MiB |
| active lookups | 586 MiB | 158 MiB |
| idle | 519 MiB | 66 MiB |

- No duplicate processes appeared in any role.
- Nothing kept running after `desktop_stopped`.
- Growth from ready to stop was negative for both roles.

The stage experiments' 564–582 MiB lookup peak is therefore most of the
whole-app peak. On this evidence the proposed 1.2 GB budget has headroom.
Confirming that needs a footprint-sampled session of the packaged app.

## Unbounded growth: Vision without an autorelease pool

**Observation:** Vision alone grows steadily, by 13–21 KiB per recognition.
- That's 4.8 MiB over 150 and 10.7 MiB over 600 varied recognitions.
- It grows even on the same image.
- `VisionProvider._run` has no autorelease pool. The worker thread has none
  either, so what Vision autoreleases per request is never drained.

**Candidate (not applied):** wrap `_run` in `objc.autorelease_pool()`, return
a tuple of results, and change nothing else. Both sides used an identical
plan: 600 recognitions, 5 repeats a side, one warm-up, the same inputs and
the same versions. Runs `20261015-232631-resources` (baseline) and
`20261015-231746-resources` (candidate):

| | baseline | candidate | label |
|---|---|---|---|
| decisions (digest) | — | identical | unchanged |
| growth, same image | 19.1 KiB/op | 7.4 KiB/op | improved |
| growth, varied images | 13.0 KiB/op | 6.6 KiB/op | inconclusive (ranges overlap) |
| footprint after 1,200 recognitions | 106 MiB | 96 MiB | within band |
| median recognition latency | 57.3 ms | 57.1 ms | unchanged |

**Verdict:** the candidate is promising, with no measured downside, but it is
**not proven complete**. It halves growth, yet the candidate still grows by
about 7 KiB per recognition. Something else retains memory too, and the
absolute saving is about 10 MiB per 1,200 recognitions.

Accepting it needs:
- human approval of the product change;
- a regression test that the request runs inside a pool;
- the same comparison through the full lookup child (worker thread) over a
  long session.

The remaining growth should be attributed before claiming that Vision is
bounded.

## Comparison discipline (A/A)

Two runs of identical code with three repeats each:
- Memory produced no false label.
- Timing produced six false "improved" labels on a busy machine. A cold disk
  cache on the first run accounted for some of them.

Two fixes followed:
- one unrecorded warm-up child per experiment;
- a timing change now needs five repeats a side.

Re-running the same pair then gave **0** improved or regressed labels and 25
inconclusive ones.

## Next steps

1. **Human decision:** the Vision autorelease candidate, using the evidence
   above.
2. **Attribute the remaining Vision growth:** a longer run, and a
   worker-thread variant in the experiment child.
3. **Explain runtime validation's disk reads.** Do this before any change.
4. **A packaged-app session with footprint sampling.** The session sampler
   records RSS only; adding footprint would change `processes.jsonl` and
   needs its own small protocol bump.
5. **Kiwi:** any model or option change needs correctness and latency
   evaluation through `lab tour` and `lab resources compare`. Kiwi stays a core
   dependency.
