"""Write a resource experiment's compact ``summary.md``."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

METHOD = """\
## Method and limits

- Each experiment is a fresh interpreter. The parent reads it at every stage
  boundary while the child waits (`proc_pid_rusage` and `psutil`) and samples
  it every 20 ms in between, so `peak` is a sampled peak and short spikes can
  be missed.
- Attribution is the difference between boundaries: an **estimate**, not
  allocation accounting. Shared libraries, native allocators that keep freed
  pages, memory compression and initialization order all move it.
- The primary figure (`after`, `peak`) is the macOS physical footprint;
  elsewhere it is RSS. RSS is shown in its own columns: it also counts clean
  shared pages and falls when idle pages are compressed, so it can hide or
  invent cost. The two are never mixed in one figure.
- Providers are built, used and closed on a `hanly-lookup-worker` thread, as
  in the lookup child. `OCR calls` counts recognitions that really reached the
  recognizer, beneath every cache; a lookup answered from the cache is not one.
- `released_by_unload` is what closing the providers returned to the system.
  What stays after unloading leaves only when the process exits; the lookup
  child's retirement is that exit.
- The `calibration` experiment maps and releases a known 64 MiB. When it is
  not attributed and released, distrust the rest of the run.
- Unavailable metrics are `n/a`, never zero. GPU memory is always unavailable.
"""


def write_summary(run_dir: Path, metadata: Mapping[str, Any], summary: Mapping[str, Any]) -> Path:
    lines = [f"# Resource attribution `{run_dir.name}`", ""]
    lines += _provenance(metadata, summary)
    lines += ["", METHOD]
    for label, experiment in summary["experiments"].items():
        lines += _experiment(label, experiment)
    if summary.get("interaction"):
        lines += _interaction(summary["interaction"])
    lines += _correctness(summary.get("correctness") or {})
    lines += _ocr_readings(summary.get("ocr"))
    lines += _lazy_loading(summary)
    lines += ["", "## Unavailable in this run", ""]
    lines += [f"- `{name}`: {reason}" for name, reason in summary["unavailable"].items()]
    path = run_dir / "summary.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _provenance(metadata: Mapping[str, Any], summary: Mapping[str, Any]) -> list[str]:
    source = (metadata.get("lab_provenance") or {}).get("source") or {}
    config = metadata.get("config") or {}
    plan = summary["plan"]
    versions = metadata.get("versions") or {}
    known = ", ".join(f"{name} {version}" for name, version in versions.items() if version)
    return [
        "## Provenance",
        "",
        f"- Commit `{source.get('commit', 'unknown')}` ({source.get('state', 'unknown')} checkout)",
        f"- Protocol `{summary['protocol']}`, primary memory `{summary['primary_memory']}`",
        f"- Recognizer `{plan['ocr_backend']}`; {plan['lookups']} lookups per repeated stage; "
        f"{plan['idle_seconds']:g} s idle; {plan['repeats']} repeats",
        f"- Inputs `{config.get('input_digest') or 'none'}` "
        f"in `{config.get('input_face') or 'n/a'}`",
        f"- Recognizer variant `{plan.get('ocr_variant', 'product')}`; "
        f"whole-lookup sequence {'run' if plan.get('sequence', True) else 'skipped'}",
        f"- Source diff: {_diff_line(config.get('source_diff') or {})}",
        f"- Versions: {known}",
    ]


def _diff_line(diff: Mapping[str, Any]) -> str:
    if not diff.get("available"):
        return "unavailable"
    untracked = len(diff.get("untracked") or ())
    if not diff.get("sha256"):
        return f"none against the commit; {untracked} untracked file(s)"
    return (
        f"`{diff['sha256'][:16]}` ({diff['bytes']} bytes, kept as `source.diff`); "
        f"{untracked} untracked file(s)"
    )


def _experiment(label: str, experiment: Mapping[str, Any]) -> list[str]:
    aggregate = experiment["aggregate"]
    errors = [run["error"] for run in experiment["repeats"] if run.get("error")]
    lines = ["", f"## `{label}` ({aggregate['repeats']} repeats)", ""]
    if errors:
        lines += [f"- **Error:** {error}" for error in errors] + [""]
    lines += [
        "| stage | after | delta | peak | transient | RSS after | RSS peak | time | CPU s "
        "| threads | read | OCR calls | p50 | p95 | growth/op |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for stage, values in aggregate["stages"].items():
        lines.append(
            f"| {stage} | {_mib(values['memory_after'])} | {_mib(values['delta'], signed=True)} "
            f"| {_mib(values['sampled_peak'])} | {_mib(values['transient_above_boundary'])} "
            f"| {_mib(values.get('rss_after'))} | {_mib(values.get('sampled_peak_rss'))} "
            f"| {_ms(values['duration_ms'])} | {_plain(values['cpu_seconds'], 2)} "
            f"| {_plain(values['threads_after'], 0)} | {_mib(values['read_bytes'])} "
            f"| {_plain(values.get('ocr_calls'), 0)} "
            f"| {_ms(values['latency_p50'])} | {_ms(values.get('latency_p95'))} "
            f"| {_kib(values['growth_per_operation'])} |"
        )
    derived = aggregate["derived"]
    lines += ["", "| derived | median (min–max) |", "|---|---|"]
    for name, spread in derived.items():
        formatter = _ms if name.endswith("_ms") else _seconds if name.endswith("seconds") else _mib
        lines.append(f"| {name} | {formatter(spread)} |")
    return lines


def _interaction(interaction: Mapping[str, Any]) -> list[str]:
    lines = [
        "", "## Isolated against together", "",
        "Cost from validated runtime to the first real operation (`ready_cost`). Loading",
        "components in one process shares libraries and changes initialization order; the",
        "difference is reported, never redistributed onto a component.", "",
        "| component | alone |", "|---|---|",
    ]
    for name, value in interaction["components"].items():
        lines.append(f"| {name} | {_value_mib(value)} |")
    lines += [
        f"| **sum of isolated** | {_value_mib(interaction['isolated_sum'])} |",
        f"| **whole sequence** | {_value_mib(interaction['sequence'])} |",
    ]
    return lines


def _lazy_loading(summary: Mapping[str, Any]) -> list[str]:
    """Name the components whose constructor costs little and first use a lot."""

    found: list[str] = []
    for label, experiment in summary["experiments"].items():
        if not label.startswith("component:"):
            continue
        stages = experiment["aggregate"]["stages"]
        load = (stages.get("load", {}).get("delta") or {}).get("median")
        first = (stages.get("first_use", {}).get("delta") or {}).get("median")
        if load is not None and first is not None and first > max(4 * load, 8 * 2**20):
            found.append(
                f"- `{label.split(':', 1)[1]}` defers its load: construction "
                f"{load / 2**20:+.1f} MiB, first use {first / 2**20:+.1f} MiB."
            )
    if not found:
        return []
    return ["", "## Deferred loading", "",
            "A constructor that costs little does not mean a cheap component:", "", *found]


def _ocr_readings(ocr: Mapping[str, Any] | None) -> list[str]:
    if not ocr:
        return []
    return [
        "", "## Recognizer readings", "",
        f"- Inputs read: {len(ocr['records'])}; every region's order, text digest, "
        "confidence and corners are kept (no text).",
        f"- Same reading for the same input within each run: "
        f"**{'yes' if ocr['stable_within_runs'] else 'no'}**"
        + (f" (unstable: {ocr['unstable_inputs']})" if ocr["unstable_inputs"] else ""),
        f"- Same readings across repeats: **{'yes' if ocr['stable_across_repeats'] else 'no'}**"
        + (f" (differing: {ocr['differing_inputs']})" if ocr["differing_inputs"] else ""),
    ]


def _correctness(correctness: Mapping[str, Any]) -> list[str]:
    if not correctness or correctness.get("signature") is None:
        return []
    stable = correctness.get("stable_across_repeats")
    return [
        "", "## Behaviour", "",
        f"- Lookup decisions stable across repeats: **{'yes' if stable else 'no'}**",
        f"- Statuses seen: {', '.join(correctness.get('statuses') or []) or 'none'}",
        "- Decisions are compared by digest of status and entry identifiers; no text is kept.",
    ]


def _median(spread: Mapping[str, Any] | None) -> float | None:
    return None if not spread else spread["median"]


def _range(spread: Mapping[str, Any] | None, scale: float, digits: int) -> str:
    if not spread or spread["n"] < 2 or spread["min"] == spread["max"]:
        return ""
    return f" ({spread['min'] / scale:.{digits}f}–{spread['max'] / scale:.{digits}f})"


def _mib(spread: Mapping[str, Any] | None, *, signed: bool = False) -> str:
    median = _median(spread)
    if median is None:
        return "n/a"
    sign = "+" if signed and median > 0 else ""
    return f"{sign}{median / 2**20:.1f} MiB{_range(spread, 2**20, 1)}"


def _kib(spread: Mapping[str, Any] | None) -> str:
    median = _median(spread)
    return "n/a" if median is None else f"{median / 1024:+.1f} KiB"


def _ms(spread: Mapping[str, Any] | None) -> str:
    median = _median(spread)
    return "n/a" if median is None else f"{median:.1f} ms{_range(spread, 1, 1)}"


def _seconds(spread: Mapping[str, Any] | None) -> str:
    median = _median(spread)
    return "n/a" if median is None else f"{median:.2f} s"


def _plain(spread: Mapping[str, Any] | None, digits: int) -> str:
    median = _median(spread)
    return "n/a" if median is None else f"{median:.{digits}f}"


def _value_mib(value: float | None) -> str:
    return "n/a" if value is None else f"{value / 2**20:.1f} MiB"
