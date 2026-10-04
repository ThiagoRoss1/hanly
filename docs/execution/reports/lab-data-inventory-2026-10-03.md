# Lab data inventory (Windows, 2026-10-03)

What the Windows lab has recorded under the gitignored `artifacts/`, what each set
is good for, and what was removed to recover disk space. Everything here lives
only on this machine; nothing below is committed. Corpus scores are scores on the
lab's own pages, not general accuracy. Timings recorded before `24ac332` are
inflated by the lab itself (its sampler ran inside the shell).

## Datasets worth keeping

### 1. Text-acquisition stress campaigns (`artifacts/lab/runs/*-stress`)

Each full run is 1,158 seeded hovers (seed 11) with a known answer per hover.
Files per run: `events.jsonl` (every trace event), `metadata.json`,
`processes.jsonl`, `campaign.html|json|md`, `report.html|json`, `summary.md`,
`replay/` (the re-captured region of every hover the app failed, PNG) and
`replay.json` (offline replay through the production lookup worker).

| Run | Code | Score | Use it for |
|---|---|---|---|
| **`20261003-202512-stress`** | `762c1c4` | **998/1,123**, 0/210 false positives | **The baseline.** 123 misread regions with ground truth (the OCR evaluation set), clean timings, UIA 39/40 |
| `20261003-201036-stress` | `16dde15` | 995/1,123 | Shows the undrawn-browser race (u001–u003 white frames); 126 regions |
| `20261002-192328-stress` | `ab7110c` | 997/1,123 | Phase 2 final; **inflated timings and UIA timeouts** (in-shell sampler); 124 regions and replay |
| `20261002-191054`, `-185509`, `-184134-stress` | `0f599dc`, `b40e11d`, `f3e8329` | 996, 949, 948 | Phase 2 before/after for the lab races; 122–124 regions each |
| `20261002-190545-stress`, `-165224-stress` | `b40e11d`, `b7dfd40` | partial (277, 60 hovers) | Development smoke runs |
| `20261002-183211` … `-184014-stress` | `fe2dcce` | small | Early development runs of the campaign itself |

**For OCR work:** the 123 regions in the baseline run are labelled crops of
lab-rendered screen text that EasyOCR misreads (worst: Batang and Malgun Gothic,
story text at 18 px; typical confusions 요→오, final ㄹ/ㅁ/ㅂ, 았/었→앗/없,
ㄷ/ㅁ initials). Replay them with `python -m lab stress-replay <run>` after any OCR
change. They are synthetic: they do not replace the real-world crops the OCR
roadmap's evaluation corpus (§8 of `ocr-latency-and-roadmap.md`) asks for.

**For dictionary work:** the plan draws its words from KRDICT, so these runs cannot
measure KRDICT coverage. The only language-stage misses are 누군가는 → 누구 (two
sizes), a word-splitting case.

### 2. Short campaigns: the sampler experiment (`--per-family 14`, 277 hovers)

| Run | Sampler | Direct-text timeouts |
|---|---|---|
| `20261002-213916-stress` | in shell | 79 |
| `20261002-214409-stress` | stubbed off | 6 |
| `20261002-214715-stress` | in shell | 111 |
| `20261002-215136-stress` | stubbed off | 1 |
| `20261002-215759`, `-220030-stress` | own process (`24ac332`) | 0, 0 |
| `20261003-202228-stress` | own process, paint wait (`762c1c4`) | — (UIA 14/14 Korean read, 13 correct) |

The evidence behind attributing the UIA deadline misses to the lab.

### 3. Tours (`*-tour`)

| Run | Code | Score |
|---|---|---|
| `20261002-160242-tour` | `83d040b` | 0/24 (the capture-session defect fixed in `9fe7c41`) |
| `20261002-160854`, `-161332`, `-161430-tour` | `83d040b` | 22/24 quick tours |
| `20261002-160956-tour` | `83d040b` | 408/453 standard tour |
| `20261002-161813-tour` | `9fe7c41` | 409/453 standard tour rerun |
| `20261002-161549`, `-161615`, `-161731-tour` | | short checks (unscored, 4/6, 11/12) |

### 4. Isolated Windows update checks (`*-windows-update`)

Each run unpacked the published v0.9.0 into its own folder and updated it with the
checkout's updater against the real release. **Kept:** each run's
`summary.json` (mode, outcome, helper result, remnants, and from `38d9203` on, the
path-free failure message). **Removed:** the per-run `install/`, `release/`,
`profile/` and `temp/` (about 2 GB each: an unpacked 0.9.0 plus the downloaded
1.0.0), which `python -m lab check windows-update` recreates on demand.

| Run | Mode | Outcome | Note |
|---|---|---|---|
| `20261002-152409`, `-152622`, `-154548` | cancel, install, rollback | pass | Phase 1 (`e8f51e0` fix) |
| `20261002-153114` | rollback | fail | Phase 1: restored correctly, but the check recorded no re-offer result; passed at `-154548` |
| `20261002-223240`, `-223936` | install, cancel | pass | Phase B at `12b052c` |
| `20261002-224157`, `-224803` | rollback | fail | helper claim missed the 30 s deadline (fixed in `0046cbc`) |
| `20261002-225328`, `-231221` | rollback, install | pass | diagnostic wrapper with a longer claim wait (not unmodified passes) |
| `20261003-180539` | rollback | pass | timeline run: helper first line at 8.0 s |
| `20261003-190036` | install | fail | live GitHub 503 misreported as "install by hand" (fixed in `16dde15`) |
| `20261003-190439`, `-190443`, `-190445` | cancel, rollback ×2 | no result | GitHub 502/503 before the check began |
| **`20261003-194338`, `-195145`, `-195402`, `-200154`** | install, cancel, rollback ×2 | **pass** | **final, at `16dde15`, unmodified** |

### 5. Bundle checks (`artifacts/lab/runs/<uuid>`)

`python -m lab check run` evidence for BUNDLE-IDENTITY, -WINDOW, -WORKER and
-LAUNCH-IDENTITY-WIN at `9fe7c41`, `12b052c`, `38d9203` and `16dde15`, plus one
app-lab scenario set at `05faed3`. A few KB each.

### 6. Driven sessions (`*-run`)

`20261002-143134`, `-143211`, `-143310` (`65e4968`, Windows baseline) and
`20261002-153540` (`05faed3`). Structural traces only.

### 7. Older material

- `artifacts/benchmarks/` (78 MB): desktop-capture, hover-invocation-rate (100,
  125 and 150 ms), package composition, and benchmark runs and evidence from
  before the lab existed.
- `artifacts/investigation-2026-09-05/`: the Control Center / worker probes and
  their outputs from that investigation.

## Removed on 2026-10-03

- From every `*-windows-update` run: `install/`, `release/`, `profile/`, `temp/`.
- Two interrupted update runs with no summary: `20261002-232003`, `20261003-182206`.
- Fifteen broken stress runs from 2026-10-02 21:29–21:36 (0–8 results each): a
  first attempt at the sampler experiment that re-entered the campaign in spawned
  children. The clean repeats are in §2.
- `browser/` (Edge's temporary InPrivate profile) from every stress run.
- In `dist/`: the archived builds `archive-{cbdebc5,9fe7c41,12b052c,38d9203}-windows`,
  every `review-*` folder, log and script from 2026-09-30, the reconstructed ZIP
  check folder, the docstring-audit leftovers and the superseded Phase B build
  logs. Kept: `dist/windows`, `dist/release`, the `hanly-desktop-windows.*`
  products of the `16dde15` build and its build log, `dist/.pyinstaller` (build cache)
  and `dist/reports`.
- `.venv-final-validation`, the earlier validation interpreter. Its creation
  steps are in `final-windows-release-evidence-2026-09-23.md`; the app and the
  normal `.venv` do not use it.
