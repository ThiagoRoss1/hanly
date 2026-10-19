# Windows word-selection and resource acceptance — continuation plan

Status: **prepared, not run.** This session ran on one Apple Silicon Mac. No
result here comes from Windows, and none may be reported as Windows evidence.
Windows is the primary target, and its native acceptance is required before
merge.

## What is already portable and was run on the Mac

| Area | Command | Mac evidence | What it does not prove on Windows |
|---|---|---|---|
| Language stage (Kiwi, KRDICT) | `python -m lab grammar` | 108 cases, 688 hovers; see the resource report | Nothing platform-specific; this runs the same on Windows and should be repeated there once |
| OCR word selection | `python -m lab word-selection --ocr-backend easyocr` | EasyOCR on macOS CPU | Windows capture (MSS/DXGI), DPI virtualization, ClearType rendering, real Torch thread counts |
| Resource attribution | `python -m lab resources stages --components ocr,kiwi,dictionary` | Vision and EasyOCR on macOS | Windows working set versus private bytes; no physical-footprint metric exists there |

## Windows runs to perform, in order

Use the repository venv on a Windows 10 or 11 machine with the full KRDICT
database. Record each run's provenance block as the Lab writes it.

1. **Portable gates on Windows:**
   - `python -m pytest --suite portable`;
   - `python -m lab grammar`.

   Compare grammar outcomes only with identical source, corpus, Kiwi/model,
   dictionary and configuration. Record those identities first. A difference
   with matching inputs needs investigation; differing dependencies make the
   pair incompatible, rather than proving a platform defect.
2. **EasyOCR word selection:**
   - command: `python -m lab word-selection --ocr-backend easyocr --stride 2`;
   - fonts: rerun at least twice with `HANLY_LAB_FACE`, once with Malgun Gothic
     and once with a Nanum face if installed;
   - record baseline and candidate on the same Windows host, with matching
     font file/hash, corpus, stride, limit, model and dependency identities;
   - compare the category table with that Windows baseline. The Mac EasyOCR
     run used stride 3 and a different rasterizer/font, so it is reference
     context, not a numerical acceptance threshold;
   - expect identical inputs to give similar OCR but not identical rasters,
     since font hinting differs.
3. **Resources:**
   - command: `python -m lab resources stages --ocr-backend easyocr --components ocr,kiwi,dictionary --repeats 5`;
   - then a long recognizer-only run: `--no-sequence --lookups 2500 --repeats 2 --components ocr`;
   - working set is the Lab's primary metric on Windows. Also record private
     committed bytes when investigating growth; working set alone can fall
     because pages leave RAM without being released.
4. **Native acceptance** (needs a person at the machine; ask before starting
   any cursor-driving run):
   - **Display scaling:** 100 %, 125 %, 150 % and 200 %, each with
     `python -m lab tour`. Check that the hovered word's crop contains the
     pointer: for a successful OCR selection, the trace's
     `capture_plan.target` must fall inside the selected OCR quad. Direct UIA
     answers and ordinary OCR refusals need not have a selected quad.
   - **Mixed displays:** if available, one display at 100 % and one at 150 %,
     with the pointer crossing between them.
   - **UIA path:** Edge or Chrome, and Notepad (RichEdit). Hover words at the
     start, middle and end. Check UTF-16 offsets around emoji
     (😀안녕하세요), and that `cursor_index` lands in the same word as on the
     Mac.
   - **EasyOCR path:** a canvas or image page, so UIA declines.
   - **Interaction:** native shortcuts, popup Expand/Collapse/Close keeping
     the reader's app in front, tray Quit, and the packaged runtime from the
     installer.

## Acceptance criteria to apply

- **Full-word selection:** compare the candidate with a compatible Windows
  baseline, per category, and investigate every regression. Every `clipped_by_roi`,
  `ocr_false_space` and `neighbor_word` case is listed and explained.
- **Refusals:** the refusal (`no_result`) rate does not rise against the
  current build. Improvements may not come from refusing more.
- **Latency:** fresh-lookup p50 and p95 are recorded, and cold start is
  recorded separately.
- **Memory:** working set over the long run, with growth per recognition
  computed only from genuine OCR calls.

## Not to do

- Do not report Mac Vision or Mac EasyOCR numbers as Windows results.
- Do not mark Windows acceptance passed from simulated input. A cursor-driven
  run must be native, with a person present.

## Blocking coordinate finding from the Mac code review

`apps/desktop/src-tauri/src/platform/mod.rs::context` divides display bounds
and cursor positions by scale factors. `service/application.py` then uses
those logical bounds alongside pynput mouse events and MSS capture rectangles.
On Windows a listener reports physical coordinates (see
[pynput's Windows DPI contract](https://pynput.readthedocs.io/en/latest/mouse.html)).
The popup and selector also use logical Tauri positions. For example, a
2560 × 1440 display at 150 % becomes approximately 1707 × 960 in the host
context, while a physical cursor can still be at (2400, 1200).

Treat this as a **P1 integration finding**, not just missing test evidence.
Before Windows acceptance, align native context, event coordinates, UIA,
capture, selector, popup placement and popup feedback in one explicit
coordinate contract, with platform conversion at its boundaries. Validate
100/125/150/200 %, negative origins and mixed DPI on Windows. No speculative
cross-platform conversion was shipped from this Mac review.
