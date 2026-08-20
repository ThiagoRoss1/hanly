# HAN-3 Packaging Feasibility Spike

## Status

`DONE_WITH_CONCERNS`

This is non-blocking Windows evidence for later PyInstaller planning. It is not
production packaging, a release artifact, CI configuration, or a pytest test.
The requested Luna `xhigh` runtime identity/reasoning metadata is unavailable in
this worker context, so it is `UNVERIFIED` (no fallback is inferred).

## Owned files changed

- `spikes/han3_packaging_feasibility.py`
- `docs/execution/reports/han-3-packaging-feasibility-spike.md`
- `.superpowers/sdd/05-execution-plan/han-3-task-report.md`

The harness uses only the Python standard library. Its normal mode probes local
runtime/package/tool availability, native import ordering, model-cache contents,
and a guarded PaddleOCR constructor. `--packaged-probe` is a deliberately
bounded frozen-startup target: it probes Paddle import and explicitly does not
load PaddleOCR models.

## Windows evidence

Observed on Windows 10 (`C:\Hanly\.venv\Scripts\python.exe`, Python 3.13.11):

- `paddleocr` 3.7.0 and `paddlepaddle` 3.3.1 are installed and importable in
  clean child interpreters.
- PyInstaller 6.22.2 and `pyinstaller-hooks-contrib` 2026.6 are installed in
  the project venv; `build` 1.5.0 is available.
- A clean `paddleocr` → `paddle` import succeeds. The reverse order exits 1
  with Windows `WinError 127` while loading `torch\lib\shm.dll`; import order
  and native DLL collection are packaging constraints.
- The local PaddleX cache exposes a complete
  `PP-OCRv5_mobile_det` directory, but the Korean recognizer directory is
  inaccessible/incomplete (`WinError 5`). The harness therefore skipped the
  PaddleOCR constructor rather than allowing a model fallback/download.

## Revision after post-bundle review (2026-08-20)

Two of this report's original conclusions did not survive review.

**1. The Korean recognizer model was never missing.** The original run recorded
`WinError 5` and concluded the model directory was "inaccessible/incomplete", so
PaddleOCR construction "remains unverified". Re-running the harness's own
inventory shows both models complete and readable:

```text
model=PP-OCRv5_mobile_det        files=6 bytes=4,944,306  complete=True
model=korean_PP-OCRv5_mobile_rec files=6 bytes=13,894,248 complete=True
```

The `WinError 5` was environmental to that run (the same access-denied condition
also broke `.pytest_cache` on this machine), not a project constraint.

**2. A 30-second import bound produced a false negative.** `paddleocr` cold
import on Windows exceeds 30 s (warm is roughly 8-13 s), so the probe recorded
`import=ERROR TimeoutExpired` and skipped model loading entirely. The bound is
now `IMPORT_TIMEOUT_SECONDS = 180.0`.

**3. PaddleOCR now constructs and loads the local Korean models, offline:**

```text
module=paddle    import=OK elapsed=3.906s
module=paddleocr import=OK elapsed=8.301s
model_loading=status=OK elapsed=7.076s mode=explicit-local-model-dirs
  Creating model: ('PP-OCRv5_mobile_det', ...\official_models\PP-OCRv5_mobile_det')
  Creating model: ('korean_PP-OCRv5_mobile_rec', ...\official_models\korean_PP-OCRv5_mobile_rec')
```

This required a fix that is itself a finding: **the installed PaddleOCR 3.7.0
defaults to `PP-OCRv6_medium_det`, and passing a v5 model directory without also
passing the model name fails** with

```text
ValueError: Model name mismatch: expected 'PP-OCRv6_medium_det'
            but config has 'PP-OCRv5_mobile_det'.
```

Provider construction and `ResourceManager` validation must therefore pin and
pass the model *name* alongside the directory. A library upgrade can silently
move the default model family ahead of the cached assets.

**4. The frozen-artifact conclusion was weaker than stated.** The original report
presented "a trivial frozen target does not carry the Paddle dependency graph" as
Paddle evidence. The harness imports everything through
`importlib.import_module`, which PyInstaller's static analysis cannot see, so
the same result would occur for any package. It is not Paddle-specific evidence.
Whether `--collect-all paddle` yields a working artifact remains **open** — that
experiment exceeded the 90-second bound and was terminated.

**Still valid and important:** importing `paddle` before `paddleocr` reproduces
`OSError: [WinError 127]` loading `torch\lib\shm.dll`. Import order is a real
Windows constraint. `paddleocr` first, then `paddle`, succeeds.

Model payload for resource-delivery planning: **~18.8 MB** for the two models.


## Bounded PyInstaller build and launch

The following disposable onedir build was run with a 90-second watchdog. The
temporary directory was removed after capture; no release artifact remains.

```powershell
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onedir `
  --name han3_packaged_probe `
  --distpath C:\Users\Thiago\AppData\Local\Temp\han3-packaging-final-b31937bb97174cae92036fd6b3cb41e0\dist `
  --workpath C:\Users\Thiago\AppData\Local\Temp\han3-packaging-final-b31937bb97174cae92036fd6b3cb41e0\work `
  --specpath C:\Users\Thiago\AppData\Local\Temp\han3-packaging-final-b31937bb97174cae92036fd6b3cb41e0\spec `
  .\spikes\han3_packaging_feasibility.py
```

Recorded wrapper/build/launch output and statuses:

```text
build_timeout=false
build_exit=0
Build complete! The results are available in: ...\dist
temp_file_count=35 temp_bytes=22832333
HAN-3 PACKAGED STARTUP PROBE
frozen=True
paddle_import=status=ERROR elapsed=0.000s error=ModuleNotFoundError: No module named 'paddle'
paddleocr_import=status=NOT_ATTEMPTED reason=bounded-Paddle-only-probe
model_loading=status=NOT_ATTEMPTED reason=probe does not bundle or download models
launch_exit=1
cleanup_exists=False
```

The 22,832,333-byte temporary artifact built successfully and launched. Its
failure to import Paddle is the intended evidence that a trivial frozen target
does not carry the Paddle native/runtime dependency graph; a later packaging
spike must explicitly collect and validate those dependencies. A broader
`--collect-all paddle` experiment exceeded the same 90-second bound while
traversing torch/numpy/scipy/PyInstaller hooks and was terminated, reinforcing
that collection scope must be designed deliberately.

## Exact focused commands and output

Compile-only syntax check (no `.pyc` write):

```powershell
& .\.venv\Scripts\python.exe -c "from pathlib import Path; compile(Path('spikes/han3_packaging_feasibility.py').read_text(encoding='utf-8'), 'spikes/han3_packaging_feasibility.py', 'exec'); print('compile_ok')"
compile_ok
compile_exit=0
```

Focused Ruff check:

```powershell
& .\.venv\Scripts\python.exe -m ruff check .\spikes\han3_packaging_feasibility.py
All checks passed!
ruff_exit=0
```

Harness command and complete observed output (exit 0):

```text
& .\.venv\Scripts\python.exe .\spikes\han3_packaging_feasibility.py
HAN-3 PACKAGING FEASIBILITY SPIKE
scope=local-only observation; harness does not create packaging artifacts, install, download, or run CI
platform=Windows release=10 python=3.13.11 executable=C:\Hanly\.venv\Scripts\python.exe
platform_scope=Windows exercised
[dependencies]
distribution=paddleocr version=3.7.0
distribution=paddlepaddle version=3.3.1
distribution=pyinstaller version=6.22.2
distribution=pyinstaller-hooks-contrib version=2026.6
distribution=build version=1.5.0
distribution=setuptools version=84.0.0
[imports]
module=paddle spec=FOUND import=OK elapsed=2.148s origin='C:\\Hanly\\.venv\\Lib\\site-packages\\paddle\\__init__.py' error=''
module=paddleocr spec=FOUND import=OK elapsed=4.725s origin='C:\\Hanly\\.venv\\Lib\\site-packages\\paddleocr\\__init__.py' error=''
module=PyInstaller spec=FOUND import=OK elapsed=0.210s origin='C:\\Hanly\\.venv\\Lib\\site-packages\\PyInstaller\\__init__.py' error=''
module=build spec=FOUND import=OK elapsed=0.141s origin='C:\\Hanly\\.venv\\Lib\\site-packages\\build\\__init__.py' error=''
import_order=paddleocr_then_paddle exit=0 elapsed=6.371s output='import_order_ok'
import_order=paddle_then_paddleocr exit=1 elapsed=2.453s output='OSError: [WinError 127] N�o foi poss�vel encontrar o procedimento especificado. Error loading "C:\\Hanly\\.venv\\Lib\\site-packages\\torch\\lib\\shm.dll" or one of its dependencies.'
[packaging_tools]
path_tool=pyinstaller path=C:\Users\Thiago\AppData\Local\Programs\Python\Python313\Scripts\pyinstaller.EXE
command=C:\Users\Thiago\AppData\Local\Programs\Python\Python313\Scripts\pyinstaller.EXE --version exit=0 stdout='6.14.0'
command=C:\Hanly\.venv\Scripts\python.exe -m PyInstaller --version exit=0 stdout='6.22.2'
command=C:\Hanly\.venv\Scripts\python.exe -m build --version exit=0 stdout='build 1.5.0 (C:\\Hanly\\.venv\\Lib\\site-packages\\build)'
command=C:\Hanly\.venv\Scripts\python.exe -m pip --version exit=0 stdout='pip 26.2.1 from C:\\Hanly\\.venv\\Lib\\site-packages\\pip (python 3.13)'
artifact_creation=NOT_ATTEMPTED reason=release artifacts are out of spike scope
[model_cache]
existing_roots=['C:\\Users\\Thiago\\.paddlex']
model=PP-OCRv5_mobile_det files=6 bytes=4944306 required=('inference.yml', 'inference.pdiparams') complete=True
model=korean_PP-OCRv5_mobile_rec files=ERROR bytes=ERROR required=() complete=False error="PermissionError: [WinError 5] Acesso negado"
[startup_and_model_loading]
startup_constraint=module imports are measurable; PaddleOCR construction is guarded by complete local model assets
model_loading=status=SKIPPED_NO_COMPLETE_LOCAL_MODELS missing_or_incomplete=korean_PP-OCRv5_mobile_rec reason=explicit local model dirs are required; no fallback/download is allowed
network_and_install_actions=NONE (version probes only; no pip/install/download/build)
result=EVIDENCE_CAPTURED_WITH_LIMITATIONS
script_exit=0
```

## Platform and action limitations

- Windows is the only exercised platform. macOS/Linux are explicitly
  **unexercised**.
- No dependency was installed; no network request, model download, release
  artifact, CI configuration, or package metadata change was made.
- The disposable PyInstaller smoke artifact was created only for this bounded
  evidence run and removed after launch/output capture.
- Model loading was not exercised because a complete local Korean model bundle
  was not available. The harness never calls a fallback path that could fetch
  weights.

## TDD applicability

TDD RED/GREEN is not applicable: this task adds no production behavior or
pytest test. Reproducibility is provided by the directly executable harness,
compile/Ruff checks, and the exact bounded build/launch commands above.

## Self-review

- Scope is limited to the three HAN-3-owned paths listed above; no architecture,
  package, CI, or production source was edited.
- The harness is standard-library-only, directly executable, and exits cleanly
  after reporting limitations.
- Model construction is gated on explicit local model files; absent/inaccessible
  assets produce a recorded skip, never a download.
- The frozen probe deliberately avoids bundling PaddleOCR/models so it remains
  bounded; its missing Paddle import is recorded as a packaging concern rather
  than presented as success.

## Concerns for later packaging work

1. Paddle/PaddleOCR native dependencies are not carried into a frozen artifact
   by default; explicit collection and a real local-model bundle are required.
   Note the evidence limit recorded in the revision section: this harness imports
   dynamically, so its frozen probe cannot demonstrate anything Paddle-specific.
   A bounded `--collect-all paddle` experiment is still owed.
2. Importing `paddle` before `paddleocr` reproduced a Windows `shm.dll`
   `WinError 127`; startup import order and DLL search paths need a dedicated
   follow-up.
3. ~~The Korean recognizer model directory was inaccessible/incomplete, so actual
   PaddleOCR constructor/model-load behavior remains unverified.~~ **Resolved on
   re-run:** both models are complete and PaddleOCR constructs and loads them
   offline in ~7 s. See the revision section above. The replacement concern is
   that the model *name* must be pinned and passed explicitly.
4. macOS/Linux packaging behavior remains unexercised.
