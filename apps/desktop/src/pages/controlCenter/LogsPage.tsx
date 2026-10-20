import { useCallback, useEffect, useMemo, useState } from "react";
import type { HanlyState, LogRecord, LogSnapshot } from "../../contracts/desktop.ts";
import { clearLogs, exportDiagnostics, getLogs } from "../../services/desktopBridge.ts";
import { PixelButton } from "../../components/PixelButton.tsx";
import { readinessRows, titleCase, errorText } from "./helpers.ts";
import type { IsPending, RunCommand } from "./types.ts";

export function LogsPage({
  state,
  isPending,
  run,
}: {
  state: HanlyState;
  isPending: IsPending;
  run: RunCommand;
}) {
  const [snapshot, setSnapshot] = useState<LogSnapshot | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [filter, setFilter] = useState("all");
  const [subsystem, setSubsystem] = useState("all");
  const [search, setSearch] = useState("");

  const refreshLogs = useCallback(async () => {
    setError("");
    setNotice("");
    try {
      setSnapshot(await getLogs());
    } catch (reason) {
      setError(errorText(reason));
    }
  }, []);

  useEffect(() => {
    void refreshLogs();
  }, [refreshLogs]);
  const records = useMemo(
    () =>
      (snapshot?.records ?? []).filter(
        (record) =>
          (filter === "all" || record.level === filter) &&
          (subsystem === "all" || record.subsystem === subsystem) &&
          (!search.trim() ||
            record.message
              .toLocaleLowerCase()
              .includes(search.trim().toLocaleLowerCase())),
      ),
    [filter, search, snapshot, subsystem],
  );
  const readiness = readinessRows(state);
  const levels = [
    "all",
    ...(snapshot?.levels ?? []).filter((level) => level !== "all"),
  ];

  async function copyLogs() {
    const text = records
      .map((record) =>
        [record.timestamp, record.level, record.subsystem, record.message].join(
          "\t",
        ),
      )
      .join("\n");
    try {
      await run("copy_text", { text });
      setError("");
      setNotice(
        `Copied ${records.length} visible ${records.length === 1 ? "record" : "records"}.`,
      );
    } catch (reason) {
      setError(errorText(reason));
    }
  }

  async function emptyLogs() {
    try {
      setSnapshot(await clearLogs());
      setError("");
      setNotice("Session log cleared.");
    } catch (reason) {
      setError(errorText(reason));
    }
  }

  async function saveDiagnostics() {
    try {
      const saved = await exportDiagnostics();
      setError("");
      setNotice(`Saved ${saved.records} records to ${saved.path}`);
    } catch (reason) {
      setError(errorText(reason));
    }
  }

  return (
    <div className="page flex max-w-none flex-col gap-6">
      <section className="panel relative min-w-0" data-rise="1">
        <div className="panel-head relative flex min-h-[104px] items-center gap-5 px-[26px] pt-[50px] pb-5">
          <div className="min-w-0">
            <h2 className="panel-title absolute inset-x-[22px] top-0 m-0 flex h-[34px] items-center justify-center text-center">Runtime readiness</h2>
            <p className="panel-note m-0 max-w-[540px] text-[13px] leading-5">
              Readiness and provider residency are separate states.
            </p>
          </div>
          <PixelButton
            className="btn btn-sm ml-auto"
            disabled={isPending("retry_runtime")}
            onClick={() => void run("retry_runtime")}
            type="button"
          >
            Retry runtime
          </PixelButton>
        </div>
        <div className="readiness-stage mx-4 pb-5">
          <div className="readiness-rows flex flex-col divide-y divide-[var(--skin-line)]">
            {readiness.map((row) => (
              <div className="readiness-row flex min-h-11 flex-wrap items-center gap-3 py-3" key={row.label}>
                <span
                  aria-hidden="true"
                  className="dot h-2 w-2 shrink-0"
                  data-tone={row.tone || undefined}
                />
                <span className="readiness-label w-28 flex-none text-[13px] font-semibold">{row.label}</span>
                <span className="readiness-detail min-w-[110px] flex-1 font-mono text-[11.5px] leading-5 text-[var(--skin-ink-muted)] [overflow-wrap:anywhere]">{row.detail}</span>
                <span
                  className="readiness-value shrink-0 font-mono text-xs font-semibold text-[var(--skin-ink)] data-[tone=ok]:text-[var(--success)] data-[tone=warn]:text-[var(--warning)] data-[tone=bad]:text-[var(--danger)]"
                  data-tone={row.tone || undefined}
                >
                  {row.value}
                </span>
              </div>
            ))}
          </div>
        </div>
      </section>
      <section className="panel panel-quiet relative min-w-0" data-rise="2">
        <div className="logs-head relative flex flex-wrap items-center gap-3 px-[26px] pt-[50px] pb-5">
          <h2 className="panel-title absolute inset-x-[22px] top-0 m-0 flex h-[34px] items-center justify-center text-center">Recent records</h2>
          <div aria-label="Filter by log level" className="logs-filters ml-auto flex flex-wrap gap-1.5">
            {levels.map((level) => (
              <PixelButton
                aria-pressed={filter === level}
                className="btn chip"
                key={level}
                onClick={() => setFilter(level)}
                type="button"
              >
                {titleCase(level)}
              </PixelButton>
            ))}
          </div>
          <select
            aria-label="Filter by subsystem"
            className="select h-10 min-h-10 w-[158px] min-w-0 px-3 py-[7px] text-xs leading-[18px]"
            onChange={(event) => setSubsystem(event.target.value)}
            value={subsystem}
          >
            <option value="all">All subsystems</option>
            {(snapshot?.subsystems ?? []).map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
          <input
            aria-label="Search logs"
            className="log-search h-10 min-h-10 w-[180px] min-w-0 px-3 py-[7px] text-xs leading-[18px]"
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search records"
            value={search}
          />
        </div>
        <div aria-live="polite" className="log-list mx-6 border-y border-[var(--skin-line)] px-0 py-1.5">
          {records.length === 0 ? (
            <div className="log-empty py-3 text-[var(--skin-ink-muted)]">{error || "No records match."}</div>
          ) : (
            records.map((record, index) => (
              <LogLine key={`${record.timestamp}-${index}`} record={record} />
            ))
          )}
        </div>
        <div className="logs-foot flex flex-wrap items-center gap-[18px] bg-transparent px-[26px] pt-5 pb-6">
          <span className="logs-summary min-w-0 truncate text-[13px] leading-5 text-[var(--skin-ink-muted)]">
            {snapshot
              ? `${records.length} of ${snapshot.records.length} records · ${snapshot.log_path ?? state.runtime.log_path ?? ""}`
              : "Logs are loading."}
          </span>
          <div className="logs-actions ml-auto flex flex-wrap gap-2.5">
            <PixelButton
              className="btn btn-sm"
              disabled={!snapshot}
              onClick={() => void refreshLogs()}
              type="button"
            >
              Refresh
            </PixelButton>
            <PixelButton
              className="btn btn-sm"
              disabled={isPending("copy_text") || records.length === 0}
              onClick={() => void copyLogs()}
              type="button"
            >
              Copy visible
            </PixelButton>
            <PixelButton
              className="btn btn-sm btn-quiet"
              disabled={!snapshot}
              onClick={() => void emptyLogs()}
              type="button"
            >
              Clear
            </PixelButton>
            <PixelButton
              className="btn btn-sm btn-quiet"
              onClick={() => void saveDiagnostics()}
              type="button"
            >
              Export diagnostics
            </PixelButton>
          </div>
        </div>
      </section>
      {error && (
        <div className="banner" data-tone="bad" role="alert">
          {error}
        </div>
      )}
      {notice && (
        <div className="banner" data-tone="warn" role="status">
          {notice}
        </div>
      )}
    </div>
  );
}

export function LogLine({ record }: { record: LogRecord }) {
  return (
    <div className="log-row flex flex-wrap items-baseline gap-x-3 gap-y-2 py-3 font-mono text-[11.5px] leading-[18px]" data-level={record.level}>
      <span className="log-time shrink-0 text-[var(--skin-ink-muted)]">
        {new Date(record.timestamp).toLocaleTimeString()}
      </span>
      <span className="log-level inline-flex w-[72px] items-baseline gap-[5px] font-semibold text-[var(--skin-ink-muted)] data-[level=warning]:text-[var(--warning)] data-[level=error]:text-[var(--danger)]" data-level={record.level}>{record.level}</span>
      <span className="log-subsystem shrink-0 font-mono text-[11px]">{record.subsystem}</span>
      <span className="log-message min-w-0 flex-1 font-sans text-[13px] leading-5 [overflow-wrap:anywhere]">{record.message}</span>
    </div>
  );
}
