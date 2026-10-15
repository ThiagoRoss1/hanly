import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import type {
  HanlyState,
  LogRecord,
  LogSnapshot,
  PermissionItem,
  RuntimeResource,
  UpdateState,
} from "../contracts/desktop.ts";
import type { DesktopMethod } from "../services/desktopBridgeCore.ts";
import {
  clearLogs,
  exportDiagnostics,
  getLogs,
} from "../services/desktopBridge.ts";
import {
  hotkeyFromKeyboardEvent,
  formatHotkey,
  validateHoverDelay,
} from "../features/settings.ts";
import { useDesktopState } from "../hooks/useDesktopState.ts";

type Section =
  "capture" | "permissions" | "shortcuts" | "appearance" | "updates" | "logs";

const SECTIONS: Array<{ id: Section; label: string }> = [
  { id: "capture", label: "Capture" },
  { id: "permissions", label: "Permissions" },
  { id: "shortcuts", label: "Shortcuts" },
  { id: "appearance", label: "Appearance" },
  { id: "updates", label: "Updates" },
  { id: "logs", label: "Logs" },
];

const PAGE_COPY: Record<
  Section,
  { kicker: string; title: string; description: string }
> = {
  capture: {
    kicker: "Capture",
    title: "읽을 준비",
    description: "Choose where Hanly reads.",
  },
  permissions: {
    kicker: "Permissions",
    title: "접근 권한",
    description: "The grants Hanly needs before it can read.",
  },
  shortcuts: {
    kicker: "Shortcuts",
    title: "단축키",
    description: "What your keyboard does, and what the system accepted.",
  },
  appearance: {
    kicker: "Appearance",
    title: "겉모습",
    description: "How the Control Center and popup look.",
  },
  updates: {
    kicker: "Updates",
    title: "업데이트",
    description: "The app and its resources update separately.",
  },
  logs: {
    kicker: "Logs",
    title: "기록",
    description: "Runtime state and recent activity.",
  },
};

const HOTKEYS = [
  {
    id: "hotkey",
    action: "push_to_hover",
    name: "Push to Hover",
    hint: "Hold to read the word under the cursor.",
  },
  {
    id: "hover_hotkey",
    action: "toggle_hover",
    name: "Pause automatic hover",
    hint: "Mutes hover without stopping capture.",
  },
  {
    id: "capture_hotkey",
    action: "toggle_capture",
    name: "Start / stop capture",
    hint: "Begins and ends the capture session.",
  },
] as const;

const UPDATE_BUSY = new Set([
  "checking",
  "preparing",
  "inspecting",
  "downloading",
  "verifying",
  "unpacking",
  "installing",
  "validating",
]);

function valueText(value: unknown, fallback = "—"): string {
  if (typeof value !== "string" || !value) return fallback;
  return value.replaceAll("_", " ");
}

function titleCase(value: unknown, fallback = "Unknown"): string {
  return valueText(value, fallback).replace(/\b\w/g, (letter) =>
    letter.toUpperCase(),
  );
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function regionLabel(
  region?: { left: number; top: number; width: number; height: number } | null,
): string {
  if (!region) return "No region selected";
  return `${region.left}, ${region.top} · ${region.width} × ${region.height}`;
}

export function ControlCenterPage() {
  const {
    state,
    connectionError,
    serviceStatus,
    refreshing,
    refresh,
    runCommand,
  } = useDesktopState("control_center");
  const [section, setSection] = useState<Section>("capture");
  const [busy, setBusy] = useState("");
  const [actionError, setActionError] = useState("");
  const [quitAsking, setQuitAsking] = useState(false);
  const [choosingArea, setChoosingArea] = useState(false);

  const run = useCallback(
    async (method: DesktopMethod, params: Record<string, unknown> = {}) => {
      setBusy(method);
      setActionError("");
      try {
        return await runCommand(method, params);
      } catch (error) {
        setActionError(errorText(error));
        return undefined;
      } finally {
        setBusy("");
      }
    },
    [runCommand],
  );

  const saveSettings = useCallback(
    (changes: Record<string, unknown>) => run("update_settings", { changes }),
    [run],
  );

  const selectArea = useCallback(() => {
    setActionError("");
    setChoosingArea(true);
  }, []);

  const page = PAGE_COPY[section];
  const activity =
    state?.app.activity ??
    state?.app.state ??
    serviceStatus?.state ??
    "preparing";
  const engine = state?.runtime.engine?.state ?? "unknown";
  const runtime = state?.runtime.status?.phase ?? "unavailable";

  useEffect(() => {
    const theme = state?.config.theme ?? "system";
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      document.documentElement.dataset.mode =
        theme === "system" ? (media.matches ? "dark" : "light") : theme;
    };
    apply();
    media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  }, [state?.config.theme]);

  if (!state) {
    return (
      <div className="app">
        <aside className="sidebar">
          <Brand />
          <div className="sidebar-foot">
            <LiveCard activity={activity} engine={engine} runtime={runtime} />
          </div>
        </aside>
        <main className="main">
          <header className="page-head">
            <div>
              <div className="page-kicker">Control Center</div>
              <h1 className="page-title">Hanly</h1>
              <p className="page-desc">Desktop status and settings.</p>
            </div>
          </header>
          <div className="page-body">
            {(connectionError || serviceStatus?.state === "failed") && (
              <div className="banner" data-tone="bad" role="alert">
                <span className="banner-text">
                  {connectionError ||
                    serviceStatus?.message ||
                    "The Hanly desktop service is unavailable."}
                </span>
                <button
                  className="btn btn-sm btn-quiet"
                  disabled={refreshing}
                  onClick={() =>
                    void run("retry_runtime").then(() => refresh())
                  }
                  type="button"
                >
                  Try again
                </button>
              </div>
            )}
            <LoadingPanel
              message={
                connectionError
                  ? "The desktop service did not provide runtime state."
                  : "Connecting to Hanly…"
              }
            />
          </div>
        </main>
      </div>
    );
  }

  const target = section === "capture";
  let content: ReactNode;
  if (section === "capture") {
    content = (
      <CapturePage
        state={state}
        busy={Boolean(busy)}
        run={run}
        saveSettings={saveSettings}
        onSelectArea={selectArea}
      />
    );
  } else if (section === "permissions") {
    content = <PermissionsPage state={state} busy={Boolean(busy)} run={run} />;
  } else if (section === "shortcuts") {
    content = (
      <ShortcutsPage
        state={state}
        busy={Boolean(busy)}
        run={run}
        saveSettings={saveSettings}
      />
    );
  } else if (section === "appearance") {
    content = (
      <AppearancePage
        state={state}
        busy={Boolean(busy)}
        saveSettings={saveSettings}
      />
    );
  } else if (section === "updates") {
    content = <UpdatesPage state={state} busy={Boolean(busy)} run={run} />;
  } else {
    content = <LogsPage state={state} busy={Boolean(busy)} run={run} />;
  }

  return (
    <div className="app">
      <aside className="sidebar">
        <Brand />
        <nav aria-label="Sections" className="nav">
          <div
            aria-hidden="true"
            className="nav-bubble"
            style={{
              transform: `translate3d(0, ${SECTIONS.findIndex((item) => item.id === section) * 40}px, 0)`,
            }}
          />
          {SECTIONS.map((item) => (
            <button
              aria-current={section === item.id ? "page" : undefined}
              className="nav-item"
              key={item.id}
              onClick={() => {
                setActionError("");
                setSection(item.id);
              }}
              type="button"
            >
              <span aria-hidden="true" className="nav-dot" />
              {item.label}
            </button>
          ))}
        </nav>
        <div className="sidebar-foot">
          <LiveCard
            activity={activity}
            engine={engine}
            runtime={runtime}
            version={state.runtime.app_version}
          />
          {quitAsking ? (
            <div className="quit-confirm">
              <span className="quit-note">
                Capture stops and the tray icon goes away.
              </span>
              <div className="quit-row">
                <button
                  className="btn btn-sm btn-exit"
                  disabled={Boolean(busy)}
                  onClick={() => void run("quit")}
                  type="button"
                >
                  Quit
                </button>
                <button
                  className="btn btn-sm btn-quiet"
                  onClick={() => setQuitAsking(false)}
                  type="button"
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <button
              className="btn btn-sm btn-exit-quiet"
              onClick={() => setQuitAsking(true)}
              type="button"
            >
              Quit Hanly
            </button>
          )}
        </div>
      </aside>

      <main className="main">
        <header className="page-head">
          <div data-anim="a">
            <div className="page-kicker">{page.kicker}</div>
            <h1 className="page-title">{page.title}</h1>
            <p className="page-desc">{page.description}</p>
          </div>
          {target && (
            <div className="head-actions">
              <button
                className="btn"
                disabled={Boolean(busy)}
                onClick={selectArea}
                type="button"
              >
                Select area
              </button>
              <button
                className="btn btn-primary btn-capture"
                disabled={
                  Boolean(busy) ||
                  (!state.app.capture_running &&
                    state.runtime.status.phase !== "ready")
                }
                title={
                  !state.app.capture_running &&
                  state.runtime.status.phase !== "ready"
                    ? "Hanly is still preparing its lookup runtime."
                    : undefined
                }
                onClick={() =>
                  void run(
                    state.app.capture_running
                      ? "stop_capture"
                      : "start_capture",
                  )
                }
                type="button"
              >
                {state.app.capture_running ? "Stop capture" : "Start capture"}
              </button>
            </div>
          )}
        </header>
        <div className="page-body" data-anim="a">
          {connectionError && (
            <div className="banner" data-tone="warn" role="status">
              <span className="banner-text">{connectionError}</span>
              <button
                className="btn btn-sm btn-quiet"
                disabled={refreshing}
                onClick={() => void refresh()}
                type="button"
              >
                Reconnect
              </button>
            </div>
          )}
          {actionError && (
            <div className="banner" data-tone="bad" role="alert">
              <span className="banner-text">{actionError}</span>
            </div>
          )}
          {content}
          {choosingArea && (
            <CaptureChoiceDialog
              busy={Boolean(busy)}
              onCancel={() => setChoosingArea(false)}
              onChooseMonitor={() => {
                setChoosingArea(false);
                void run("set_capture_mode", { mode: "full_monitor" });
              }}
              onChooseRegion={() => {
                setChoosingArea(false);
                void run("select_region");
              }}
            />
          )}
        </div>
      </main>
    </div>
  );
}

function Brand() {
  return (
    <div className="brand">
      <div aria-hidden="true" className="brand-mark">
        한
      </div>
      <div className="brand-words">
        <div className="brand-name">Hanly</div>
        <div className="brand-sub">Control Center</div>
      </div>
    </div>
  );
}

function LiveCard({
  activity,
  engine,
  runtime,
  version,
}: {
  activity: string;
  engine: string;
  runtime: string;
  version?: string | null;
}) {
  const tone =
    activity === "running" ? "ok" : activity === "error" ? "bad" : "";
  const runtimeTone =
    runtime === "ready" ? "ok" : runtime === "failed" ? "bad" : "warn";
  const engineTone =
    engine === "ready" ? "ok" : engine === "error" ? "bad" : "";
  return (
    <div className="live-card">
      <div className="live-head">
        <span
          aria-hidden="true"
          className="dot"
          data-tone={tone || undefined}
        />
        <span className="live-label">{titleCase(activity, "Preparing")}</span>
      </div>
      <div aria-live="polite" className="live-facts" role="status">
        <div className="live-fact" data-tone={runtimeTone}>
          <span>runtime</span>
          <span>{valueText(runtime)}</span>
        </div>
        <div className="live-fact" data-tone={engineTone}>
          <span>engine</span>
          <span>{valueText(engine)}</span>
        </div>
        {version && (
          <div className="live-fact">
            <span>version</span>
            <span>{version}</span>
          </div>
        )}
      </div>
    </div>
  );
}

function LoadingPanel({ message }: { message: string }) {
  return (
    <section className="panel">
      <div className="panel-head">
        <h2 className="panel-title">Hanly</h2>
      </div>
      <div className="panel-rows">
        <div className="readiness-row">
          <span className="readiness-detail">{message}</span>
        </div>
      </div>
    </section>
  );
}

function CaptureChoiceDialog({
  busy,
  onCancel,
  onChooseMonitor,
  onChooseRegion,
}: {
  busy: boolean;
  onCancel: () => void;
  onChooseMonitor: () => void;
  onChooseRegion: () => void;
}) {
  const dialogRef = useRef<HTMLElement>(null);
  useEffect(() => dialogRef.current?.focus(), []);

  return (
    <div
      className="choice-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onCancel();
      }}
    >
      <section
        aria-labelledby="capture-choice-title"
        aria-modal="true"
        className="choice-dialog panel"
        onKeyDown={(event) => {
          if (event.key === "Escape") onCancel();
        }}
        ref={dialogRef}
        role="dialog"
        tabIndex={-1}
      >
        <h2 className="panel-title" id="capture-choice-title">
          Where should Hanly read?
        </h2>
        <p className="panel-note">
          Choose the area Hanly should watch. This is saved as a setting.
        </p>
        <div className="choice-actions">
          <button
            className="btn"
            disabled={busy}
            onClick={onChooseMonitor}
            type="button"
          >
            Whole monitor
          </button>
          <button
            className="btn btn-primary"
            disabled={busy}
            onClick={onChooseRegion}
            type="button"
          >
            Select an area
          </button>
          <button
            className="btn btn-quiet"
            disabled={busy}
            onClick={onCancel}
            type="button"
          >
            Cancel
          </button>
        </div>
      </section>
    </div>
  );
}

function CapturePage({
  state,
  busy,
  run,
  saveSettings,
  onSelectArea,
}: {
  state: HanlyState;
  busy: boolean;
  run: (
    method: DesktopMethod,
    params?: Record<string, unknown>,
  ) => Promise<unknown>;
  saveSettings: (changes: Record<string, unknown>) => Promise<unknown>;
  onSelectArea: () => void;
}) {
  const config = state.config;
  const app = state.app;
  const bounds = state.runtime.hover_delay_bounds ?? { min: 20, max: 2000 };
  const delay = config.hover_delay_ms ?? 80;
  const [delayDraft, setDelayDraft] = useState(String(delay));
  const [regionDraft, setRegionDraft] = useState({
    left: "",
    top: "",
    width: "",
    height: "",
  });
  const [formError, setFormError] = useState("");
  const region = app.region ?? config.capture_region ?? null;
  const mode = config.capture_mode ?? app.capture_mode ?? "full_monitor";
  const selectedTarget =
    app.target ||
    (config.capture_monitor == null
      ? "cursor"
      : `monitor:${config.capture_monitor}`);
  const selectedMonitor = app.targets.find(
    (monitor) => `monitor:${monitor.index}` === selectedTarget,
  );
  const targetLabel =
    selectedTarget === "cursor"
      ? "the display under the cursor"
      : (selectedMonitor?.name ??
        selectedTarget.replace("monitor:", "Monitor "));

  useEffect(() => {
    setDelayDraft(String(delay));
  }, [delay]);
  useEffect(() => {
    if (!region) return;
    setRegionDraft({
      left: String(region.left),
      top: String(region.top),
      width: String(region.width),
      height: String(region.height),
    });
  }, [region?.left, region?.top, region?.width, region?.height]);

  async function saveDelay(raw: string) {
    const result = validateHoverDelay(raw, bounds);
    if (!result.valid) {
      setFormError(result.message);
      setDelayDraft(String(delay));
      return;
    }
    setFormError("");
    setDelayDraft(String(result.value));
    await run("set_hover_delay", { delay_ms: result.value });
  }

  async function applyRegion() {
    const values = Object.fromEntries(
      Object.entries(regionDraft).map(([key, value]) => [key, Number(value)]),
    );
    if (Object.values(values).some((value) => !Number.isInteger(value))) {
      setFormError("Enter whole numbers for each region coordinate.");
      return;
    }
    const next = values as {
      left: number;
      top: number;
      width: number;
      height: number;
    };
    if (next.width < 2 || next.height < 2) {
      setFormError("The region must be at least 2 × 2 pixels.");
      return;
    }
    setFormError("");
    await run("set_region", { region: next });
  }

  return (
    <section className="page">
      <div
        className="capture-status"
        data-live={Boolean(app.capture_running)}
        data-rise="1"
      >
        <span
          aria-hidden="true"
          className="dot"
          data-live={Boolean(app.capture_running)}
          data-tone={app.capture_running ? "ok" : undefined}
        />
        <span className="capture-headline">
          {app.activity === "preparing"
            ? "Preparing capture"
            : app.activity === "error"
              ? "Capture needs attention"
              : app.capture_running
                ? "Reading now"
                : "Not reading"}
        </span>
        <span className="capture-where">
          {(app.activity === "preparing" || app.activity === "error") &&
          app.detail
            ? app.detail
            : mode === "region"
              ? region
                ? `${targetLabel} · ${region.width} × ${region.height} at ${region.left}, ${region.top}`
                : `${targetLabel} · no region saved, reading the whole monitor`
              : `${targetLabel} · whole screen`}
        </span>
        <span className="capture-hint">
          {app.activity === "preparing"
            ? "please wait"
            : app.capture_running
              ? config.hover_activation === "push_to_hover" && config.hotkey
                ? `hold ${formatHotkey(config.hotkey).join(" ")}`
                : "hover active"
              : "press start to read"}
        </span>
      </div>

      <div className="capture-stage">
        <section
          aria-labelledby="target-heading"
          className="panel"
          data-rise="2"
        >
          <div className="panel-head">
            <h2 className="panel-title" id="target-heading">
              Reading target
            </h2>
          </div>
          <div
            aria-label="Capture target"
            className="panel-rows"
            role="radiogroup"
          >
            <TargetOption
              selected={mode !== "region"}
              disabled={busy}
              label="Current monitor"
              detail="Follows the display the cursor is on."
              onSelect={() =>
                void run("set_capture_mode", { mode: "full_monitor" })
              }
            />
            <TargetOption
              selected={mode === "region"}
              disabled={busy}
              label="Selected region"
              detail="A fixed rectangle you draw once."
              onSelect={() => void run("set_capture_mode", { mode: "region" })}
            />
          </div>
        </section>

        <div
          aria-hidden={mode !== "region"}
          inert={mode !== "region"}
          className="region-collapse"
          data-open={mode === "region"}
        >
          <div className="collapse-inner">
            <section
              aria-labelledby="region-heading"
              className="panel collapse-gap"
              data-rise="3"
            >
              <div className="region-head">
                <h2 className="panel-title" id="region-heading">
                  Region
                </h2>
                <span className="region-coords">{regionLabel(region)}</span>
                <button
                  className="btn btn-sm btn-quiet"
                  disabled={busy}
                  onClick={onSelectArea}
                  type="button"
                >
                  Select area
                </button>
              </div>
              <div className="region-body">
                <div className="region-fields">
                  {(["left", "top", "width", "height"] as const).map((key) => (
                    <label className="field" key={key}>
                      <span className="field-label">{key}</span>
                      <input
                        aria-label={`Region ${key}`}
                        className="input"
                        disabled={busy || mode !== "region"}
                        inputMode="numeric"
                        onChange={(event) =>
                          setRegionDraft((current) => ({
                            ...current,
                            [key]: event.target.value,
                          }))
                        }
                        value={regionDraft[key]}
                      />
                    </label>
                  ))}
                </div>
                <div className="region-actions">
                  <button
                    className="btn btn-sm btn-text"
                    disabled={busy || mode !== "region"}
                    onClick={() => void run("set_region", { region: null })}
                    type="button"
                  >
                    Clear
                  </button>
                  <button
                    className="btn btn-sm btn-primary"
                    disabled={busy || mode !== "region"}
                    onClick={() => void applyRegion()}
                    type="button"
                  >
                    Apply
                  </button>
                </div>
              </div>
            </section>
          </div>
        </div>

        <section
          aria-labelledby="capture-settings-heading"
          className="settings-card"
          data-rise="4"
        >
          <div className="settings-head">
            <h2 className="panel-title" id="capture-settings-heading">
              Capture settings
            </h2>
            <span className="settings-aside">Applies to both targets.</span>
          </div>
          <CaptureSetting
            label="Monitor"
            controlId="capture-target"
            help="Which display Hanly reads, in either target."
          >
            <select
              aria-describedby="capture-target-help"
              className="select"
              id="capture-target"
              disabled={busy}
              onChange={(event) =>
                void run("set_target", { target: event.target.value })
              }
              value={selectedTarget}
            >
              <option value="cursor">Follow cursor</option>
              {app.targets.map((monitor) => (
                <option key={monitor.index} value={`monitor:${monitor.index}`}>
                  {monitor.name}
                </option>
              ))}
            </select>
          </CaptureSetting>
          <CaptureSetting
            label="Hover delay"
            controlId="hover-delay-slider"
            help="How long the cursor rests before Hanly reads."
          >
            <input
              aria-label="Hover delay in milliseconds"
              aria-describedby="hover-delay-slider-help"
              disabled={busy}
              id="hover-delay-slider"
              max={bounds.max}
              min={bounds.min}
              onChange={(event) => setDelayDraft(event.target.value)}
              onPointerUp={(event) => void saveDelay(event.currentTarget.value)}
              onKeyUp={(event) => {
                if (event.key.startsWith("Arrow"))
                  void saveDelay(event.currentTarget.value);
              }}
              step="10"
              type="range"
              value={delayDraft}
            />
            <span className="delay-value">
              <input
                aria-label="Hover delay value in milliseconds"
                aria-describedby="hover-delay-slider-help"
                className="delay-input"
                disabled={busy}
                inputMode="numeric"
                onBlur={(event) => void saveDelay(event.currentTarget.value)}
                onChange={(event) => setDelayDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") event.currentTarget.blur();
                }}
                value={delayDraft}
              />
              <span className="delay-unit">ms</span>
            </span>
          </CaptureSetting>
          <CaptureSetting
            label="Lookup engine"
            controlId="lookup-preload"
            help={
              config.lookup_preload === "always"
                ? "Loaded at launch and kept loaded, including through pause."
                : config.lookup_preload === "on_demand"
                  ? "Nothing is loaded until a lookup needs it."
                  : "Loaded while watching the screen, retired on pause."
            }
          >
            <select
              aria-describedby="lookup-preload-help"
              className="select"
              disabled={busy}
              id="lookup-preload"
              onChange={(event) =>
                void saveSettings({ lookup_preload: event.target.value })
              }
              value={String(config.lookup_preload ?? "when_capture_starts")}
            >
              <option value="when_capture_starts">
                Load while watching the screen
              </option>
              <option value="always">Keep loaded</option>
              <option value="on_demand">Load only for a lookup</option>
            </select>
          </CaptureSetting>
          <CaptureSetting
            label="Text recognizer"
            controlId="ocr-backend"
            help={
              state.runtime.ocr_provider
                ? `In use: ${state.runtime.ocr_provider}`
                : "Recognizer availability has not been reported."
            }
          >
            <select
              aria-describedby="ocr-backend-help"
              className="select"
              disabled={busy || (state.runtime.ocr_backends ?? []).length === 0}
              id="ocr-backend"
              onChange={(event) =>
                void saveSettings({ ocr_backend: event.target.value })
              }
              value={String(config.ocr_backend ?? "auto")}
            >
              <option value="auto">Automatic (recommended)</option>
              {(state.runtime.ocr_backends ?? [])
                .filter((backend) => backend !== "auto")
                .map((backend) => (
                  <option key={backend} value={backend}>
                    {backend === "vision" ? "Apple Vision" : "EasyOCR"}
                  </option>
                ))}
            </select>
          </CaptureSetting>
          {formError && (
            <div className="banner" data-tone="bad" role="alert">
              {formError}
            </div>
          )}
        </section>
      </div>
    </section>
  );
}

function CaptureSetting({
  label,
  controlId,
  help,
  children,
}: {
  label: string;
  controlId: string;
  help: string;
  children: ReactNode;
}) {
  return (
    <div className="settings-row">
      <label className="settings-name" htmlFor={controlId}>
        {label}
      </label>
      <div className="settings-control">{children}</div>
      <span className="settings-help" id={`${controlId}-help`}>
        {help}
      </span>
    </div>
  );
}

function TargetOption({
  selected,
  disabled,
  label,
  detail,
  onSelect,
}: {
  selected: boolean;
  disabled: boolean;
  label: string;
  detail: string;
  onSelect: () => void;
}) {
  return (
    <button
      aria-checked={selected}
      className="option"
      disabled={disabled}
      onClick={onSelect}
      role="radio"
      type="button"
    >
      <span aria-hidden="true" className="option-radio" />
      <span className="option-text">
        <span className="option-label">{label}</span>
        <span className="option-desc">{detail}</span>
      </span>
    </button>
  );
}

function PermissionsPage({
  state,
  busy,
  run,
}: {
  state: HanlyState;
  busy: boolean;
  run: (
    method: DesktopMethod,
    params?: Record<string, unknown>,
  ) => Promise<unknown>;
}) {
  const permissions = state.permissions;
  const items = permissions.items ?? [];
  const missing = items.filter((item) => !item.granted);
  useEffect(() => {
    if (!permissions.supported) return;
    const refresh = () => void run("refresh_permissions");
    window.addEventListener("focus", refresh);
    return () => window.removeEventListener("focus", refresh);
  }, [permissions.supported, run]);

  return (
    <div className="page stack stack-wide narrow">
      <section className="panel panel-quiet" data-rise="1">
        <div className="panel-head">
          <div>
            <h2 className="panel-title">Desktop access</h2>
            <p className="panel-note">
              Permission grants are checked by Hanly before capture begins.
            </p>
          </div>
          <button
            className="btn btn-sm"
            disabled={busy || !permissions.supported}
            onClick={() => void run("refresh_permissions")}
            type="button"
          >
            Recheck
          </button>
        </div>
        {!permissions.supported ? (
          <div className="panel-rows">
            <div className="readiness-row">
              <span className="readiness-detail">
                {permissions.available === false
                  ? permissions.message ||
                    "Permission checks are not connected in this build."
                  : "This platform does not require a separate permission check."}
              </span>
            </div>
          </div>
        ) : (
          <>
            {missing.length > 0 && (
              <div
                aria-live="polite"
                className="permission-onboarding"
                role="status"
              >
                <strong>Before Hanly can read</strong>
                <span>
                  Grant the required desktop access, then return here and
                  recheck.
                </span>
                <span>
                  Already switched on in System Settings? That entry belongs
                  to an earlier copy of Hanly. Remove it with −, then use Grant
                  access again.
                </span>
              </div>
            )}
            <div className="panel-rows">
              {items.map((item) => (
                <PermissionCard
                  key={item.id}
                  item={item}
                  busy={busy}
                  onGrant={() =>
                    void run("grant_permission", { permission: item.id })
                  }
                />
              ))}
            </div>
          </>
        )}
        <p className="panel-note" style={{ padding: "0 14px 12px" }}>
          Granted permissions stay listed so you can see what Hanly is using.
        </p>
      </section>
    </div>
  );
}

function PermissionCard({
  item,
  busy,
  onGrant,
}: {
  item: PermissionItem;
  busy: boolean;
  onGrant: () => void;
}) {
  const tone = item.granted ? "ok" : item.state === "unknown" ? "warn" : "bad";
  return (
    <div className="permission" data-granted={item.granted}>
      <span
        aria-hidden="true"
        className="dot"
        data-tone={item.granted ? "ok" : "info"}
      />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="permission-head">
          <span className="permission-name">{item.label}</span>
          <span className="tag" data-tone={tone}>
            {item.granted
              ? "granted"
              : item.state === "unknown"
                ? "unknown"
                : "required"}
          </span>
        </div>
        <div className="permission-why">
          {item.requirement} {item.granted ? "" : item.restart_note}
        </div>
      </div>
      {!item.granted && (
        <button
          className="btn btn-sm btn-primary"
          disabled={busy}
          onClick={onGrant}
          type="button"
        >
          Grant access
        </button>
      )}
    </div>
  );
}

function ShortcutsPage({
  state,
  busy,
  run,
  saveSettings,
}: {
  state: HanlyState;
  busy: boolean;
  run: (
    method: DesktopMethod,
    params?: Record<string, unknown>,
  ) => Promise<unknown>;
  saveSettings: (changes: Record<string, unknown>) => Promise<unknown>;
}) {
  const [recording, setRecording] = useState<string | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!recording) return;
    const onKeyDown = (event: KeyboardEvent) => {
      event.preventDefault();
      if (event.key === "Escape") {
        setRecording(null);
        return;
      }
      const binding = hotkeyFromKeyboardEvent(event);
      if (!binding) return;
      const field = recording;
      setRecording(null);
      setError("");
      const update =
        field === "hotkey"
          ? run("set_hotkey", { hotkey: binding })
          : saveSettings({ [field]: binding });
      void update.catch((reason: unknown) => setError(errorText(reason)));
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [recording, run, saveSettings]);

  const registered = state.runtime.hotkeys ?? {};
  const prepared = (state.app.state ?? "new") !== "new";
  return (
    <div className="page stack stack-wide narrow">
      {HOTKEYS.map((item, index) => {
        const stored = String(state.config[item.id] ?? "");
        const live = registered[item.action] ?? "";
        const isRecording = recording === item.id;
        const note =
          !isRecording &&
          (!stored
            ? {
                tone: "warn",
                title: "Unassigned.",
                text: "No free combination was left for this action. Choose one.",
              }
            : live && live !== stored
              ? {
                  tone: "warn",
                  title: `Registered as ${live}.`,
                  text: "The stored shortcut was not the one the system accepted.",
                }
              : prepared && stored && !live
                ? {
                    tone: "bad",
                    title: "Not registered.",
                    text: "Another application may already own this combination, so your keyboard does not do this yet.",
                  }
                : null);
        return (
          <section
            className="panel"
            data-recording={isRecording}
            data-rise={index + 1}
            key={item.id}
          >
            <div className="shortcut-row">
              <div className="shortcut-text">
                <div className="shortcut-name">{item.name}</div>
                <div className="shortcut-hint">{item.hint}</div>
              </div>
              <div
                aria-label={`${item.name} shortcut`}
                className="shortcut-keys"
              >
                {isRecording ? (
                  <span className="key" data-kind="recording">
                    Press keys… Esc cancels
                  </span>
                ) : !stored ? (
                  <span className="key" data-kind="empty">
                    unassigned
                  </span>
                ) : (
                  formatHotkey(stored).map((key, keyIndex) => (
                    <span className="key" key={`${key}-${keyIndex}`}>
                      {key}
                    </span>
                  ))
                )}
              </div>
              <button
                className={`btn btn-sm btn-fixed${!stored && !isRecording ? " btn-primary" : ""}`}
                disabled={busy}
                onClick={() => setRecording(isRecording ? null : item.id)}
                type="button"
              >
                {isRecording ? "Cancel" : stored ? "Change" : "Assign"}
              </button>
            </div>
            {note && (
              <div className="shortcut-note" data-tone={note.tone}>
                <span aria-hidden="true" className="dot" />
                <span>
                  <span className="shortcut-note-title">{note.title}</span>{" "}
                  {note.text}
                </span>
              </div>
            )}
          </section>
        );
      })}
      {error && (
        <div className="banner" data-tone="bad" role="alert">
          {error}
        </div>
      )}
      <section className="panel" data-rise="4">
        <div className="panel-head">
          <div>
            <h2 className="panel-title">Automatic hover</h2>
            <p className="panel-note">
              Choose when the Push to Hover action is active.
            </p>
          </div>
        </div>
        <div className="panel-rows" role="radiogroup">
          {[
            {
              value: "push_to_hover",
              label: "Only while held",
              desc: "Hover reads while the Push to Hover shortcut is held down.",
            },
            {
              value: "always_active",
              label: "Whenever capture is running",
              desc: "Hover reads for the whole capture session, subject to permissions.",
            },
          ].map((mode) => (
            <TargetOption
              key={mode.value}
              selected={state.config.hover_activation === mode.value}
              disabled={busy}
              label={mode.label}
              detail={mode.desc}
              onSelect={() =>
                void saveSettings({ hover_activation: mode.value })
              }
            />
          ))}
        </div>
      </section>
    </div>
  );
}

function AppearancePage({
  state,
  busy,
  saveSettings,
}: {
  state: HanlyState;
  busy: boolean;
  saveSettings: (changes: Record<string, unknown>) => Promise<unknown>;
}) {
  const config = state.config;
  const groups = [
    {
      key: "theme",
      label: "Theme",
      note: "System follows the desktop setting.",
      options: [
        ["system", "System"],
        ["light", "Light"],
        ["dark", "Dark"],
      ],
    },
    {
      key: "popup_default_size",
      label: "Default popup size",
      note: "How each new dictionary popup opens.",
      options: [
        ["compact", "Compact"],
        ["expanded", "Expanded"],
      ],
    },
    {
      key: "technical_details",
      label: "Technical details",
      note: "Off keeps the popup focused on reading.",
      options: [
        ["off", "Off"],
        ["basic", "Basic"],
        ["full", "Full"],
      ],
    },
  ] as const;

  return (
    <div className="page stack stack-wide narrow">
      {groups.map((group, index) => (
        <section
          className="panel"
          data-rise={index + 1}
          key={group.key}
          aria-labelledby={`${group.key}-heading`}
        >
          <div className="panel-head">
            <div>
              <h2 className="panel-title" id={`${group.key}-heading`}>
                {group.label}
              </h2>
              <p className="panel-note">{group.note}</p>
            </div>
            <div aria-label={group.label} className="segmented" role="group">
              {group.options.map(([value, label]) => (
                <button
                  aria-pressed={config[group.key] === value}
                  className="segment"
                  disabled={busy}
                  key={value}
                  onClick={() => void saveSettings({ [group.key]: value })}
                  type="button"
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        </section>
      ))}
    </div>
  );
}

function UpdatesPage({
  state,
  busy,
  run,
}: {
  state: HanlyState;
  busy: boolean;
  run: (
    method: DesktopMethod,
    params?: Record<string, unknown>,
  ) => Promise<unknown>;
}) {
  const updates = state.updates;
  const [resourcesOpen, setResourcesOpen] = useState(false);
  const [activityOpen, setActivityOpen] = useState(false);
  const application = updates.application;
  const isBusy = UPDATE_BUSY.has(updates.status ?? "");
  const availableResources = new Map(
    (updates.resources ?? [])
      .filter((resource) => resource.available)
      .map((item) => [item.id, item]),
  );
  const resources = state.runtime.resources;
  const activity = updates.activity ?? [];
  const progress = updates.progress;
  const fraction =
    typeof progress?.fraction === "number"
      ? Math.max(0, Math.min(1, progress.fraction))
      : progress?.total
        ? Math.max(0, Math.min(1, (progress.completed ?? 0) / progress.total))
        : null;
  const bytesLine = progress?.total
    ? `${formatBytes(progress.completed ?? 0)} / ${formatBytes(progress.total)}`
    : "";

  return (
    <div className="page stack stack-wide">
      <section
        className="panel"
        data-tone={
          updates.status === "failed"
            ? "bad"
            : application?.installable || updates.awaiting_confirmation
              ? "accent"
              : undefined
        }
        data-rise="1"
      >
        <div className="panel-head">
          <div>
            <h2 className="panel-title">Hanly application</h2>
            <p className="panel-note">
              Application files update separately from dictionary resources.
            </p>
          </div>
          <span
            className="tag"
            data-tone={
              updates.status === "failed"
                ? "bad"
                : application?.installable
                  ? "accent"
                  : "ok"
            }
          >
            {valueText(updates.status, "not checked")}
          </span>
        </div>
        {isBusy ? (
          <div className="update-busy">
            <div className="update-busy-line">
              <span className="update-strong">
                {updates.message || titleCase(updates.status)}
              </span>
              <span className="update-detail">{bytesLine}</span>
              <span className="update-percent">
                {fraction === null ? "" : `${Math.round(fraction * 100)}%`}
              </span>
            </div>
            <div
              aria-label="Update progress"
              aria-valuemax={100}
              aria-valuemin={0}
              aria-valuenow={
                fraction === null ? undefined : Math.round(fraction * 100)
              }
              className="track"
              data-indeterminate={fraction === null}
              role="progressbar"
            >
              <div
                className="track-fill"
                style={{
                  width: fraction === null ? undefined : `${fraction * 100}%`,
                }}
              />
            </div>
            {updates.cancellable && (
              <div className="update-actions">
                <button
                  className="btn btn-sm btn-quiet"
                  disabled={busy}
                  onClick={() => void run("cancel_update")}
                  type="button"
                >
                  Cancel
                </button>
              </div>
            )}
          </div>
        ) : updates.restart_required || updates.status === "restart" ? (
          <div className="update-line">
            <div>
              <div className="update-strong">Ready to restart</div>
              <div className="update-sub">
                {updates.message ||
                  "Hanly restarts into the new build. Your settings stay."}
              </div>
            </div>
          </div>
        ) : updates.awaiting_confirmation ? (
          <div className="update-block">
            <div className="update-strong">
              This installation needs the full download
            </div>
            <div className="update-sub">{updates.message}</div>
            <div className="update-actions">
              <button
                className="btn btn-primary"
                disabled={busy}
                onClick={() =>
                  void run("install_application_update", { confirm_full: true })
                }
                type="button"
              >
                Download full update
              </button>
              <button
                className="btn btn-quiet"
                disabled={busy}
                onClick={() => void run("cancel_update")}
                type="button"
              >
                Not now
              </button>
            </div>
          </div>
        ) : application?.installable ? (
          <div className="update-block">
            <div className="update-versions">
              <span className="update-from">
                {application.current_version ?? "Current"}
              </span>
              <span className="update-from">→</span>
              <span className="update-to">{application.latest_version}</span>
              {updates.plan && (
                <span className="update-size">
                  · {describePlan(updates.plan)}
                </span>
              )}
            </div>
            {application.message && (
              <p className="update-sub">{application.message}</p>
            )}
            <div className="update-actions">
              <button
                className="btn btn-primary"
                disabled={busy}
                onClick={() =>
                  void run("install_application_update", {
                    confirm_full: false,
                  })
                }
                type="button"
              >
                Install update
              </button>
              {application.release_url && (
                <button
                  className="btn btn-quiet"
                  disabled={busy}
                  onClick={() => void run("open_release_notes")}
                  type="button"
                >
                  View release notes
                </button>
              )}
            </div>
          </div>
        ) : updates.status === "failed" ? (
          <div className="update-line">
            <div>
              <div className="update-strong">Update check failed</div>
              <div className="update-sub" role="alert">
                {updates.message ||
                  application?.message ||
                  "Hanly could not check for updates."}
              </div>
            </div>
            <button
              className="btn"
              disabled={busy}
              onClick={() => void run("check_for_updates")}
              type="button"
            >
              Try again
            </button>
          </div>
        ) : (
          <div className="update-line">
            <div>
              <div className="update-strong">
                Hanly {state.runtime.app_version ?? ""}
              </div>
              <div className="update-sub">
                {updates.message ||
                  application?.message ||
                  "No update check has been run."}
              </div>
            </div>
            <button
              className="btn"
              disabled={busy}
              onClick={() => void run("check_for_updates")}
              type="button"
            >
              Check now
            </button>
          </div>
        )}
      </section>

      <section className="panel" data-rise="2">
        <button
          aria-controls="resource-collapse"
          aria-expanded={resourcesOpen}
          className="disclosure"
          onClick={() => setResourcesOpen((open) => !open)}
          type="button"
        >
          <span aria-hidden="true" className="disclosure-caret">
            ▾
          </span>
          Dictionary and resources
          <span className="disclosure-summary">{resources.length}</span>
        </button>
        <div
          aria-hidden={!resourcesOpen}
          inert={!resourcesOpen}
          className="region-collapse"
          data-open={resourcesOpen}
          id="resource-collapse"
        >
          <div className="collapse-inner">
            <div className="panel-rows">
              {resources.length === 0 ? (
                <p className="resource-foot">
                  No local resources have been reported yet.
                </p>
              ) : (
                resources.map((resource) => (
                  <ResourceRow
                    key={resource.id}
                    resource={resource}
                    offered={availableResources.get(resource.id)}
                    busy={busy || isBusy}
                    install={() =>
                      void run("install_update", { resource_id: resource.id })
                    }
                  />
                ))
              )}
            </div>
            <p className="resource-foot">
              Resources swap without restarting. Lookups pause for a moment
              during the swap.
            </p>
          </div>
        </div>
      </section>
      <section className="panel panel-quiet" data-rise="3">
        <button
          aria-controls="activity-collapse"
          aria-expanded={activityOpen}
          className="disclosure"
          onClick={() => setActivityOpen((open) => !open)}
          type="button"
        >
          <span aria-hidden="true" className="disclosure-caret">
            ▾
          </span>
          Update activity
          <span className="disclosure-summary">{activity.length}</span>
        </button>
        <div
          aria-hidden={!activityOpen}
          inert={!activityOpen}
          className="region-collapse"
          data-open={activityOpen}
          id="activity-collapse"
        >
          <div className="collapse-inner">
            <div
              className="panel-rows"
              style={{ borderTop: "1px solid var(--border)" }}
            >
              {activity.length ? (
                activity.map((item, index) => (
                  <div className="log-row" key={`${item.at ?? index}-${index}`}>
                    <span className="log-time">
                      {item.at
                        ? new Date(item.at * 1000).toLocaleTimeString()
                        : ""}
                    </span>
                    <span className="log-message">{item.message}</span>
                  </div>
                ))
              ) : (
                <p className="resource-foot">
                  No update activity has been reported.
                </p>
              )}
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}

function ResourceRow({
  resource,
  offered,
  busy,
  install,
}: {
  resource: RuntimeResource;
  offered?: { id: string; available?: boolean; version?: string };
  busy: boolean;
  install: () => void;
}) {
  return (
    <div className="resource-row">
      <div className="resource-text">
        <div className="resource-name">{resource.id}</div>
        <div className="resource-detail">
          {[
            resource.kind,
            resource.version ? `v${resource.version}` : "version not reported",
            resource.compatible ? "compatible" : "review needed",
            offered?.version ? `→ v${offered.version}` : "",
          ]
            .filter(Boolean)
            .join(" · ")}
        </div>
      </div>
      <span
        className="tag"
        data-tone={
          offered?.available ? "accent" : resource.compatible ? "ok" : "warn"
        }
      >
        {offered?.available ? "update available" : valueText(resource.status)}
      </span>
      {offered?.available && (
        <button
          className="btn btn-sm"
          disabled={busy}
          onClick={install}
          type="button"
        >
          Install
        </button>
      )}
    </div>
  );
}

function LogsPage({
  state,
  busy,
  run,
}: {
  state: HanlyState;
  busy: boolean;
  run: (
    method: DesktopMethod,
    params?: Record<string, unknown>,
  ) => Promise<unknown>;
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
    <div className="page stack stack-wide">
      <section className="panel" data-rise="1">
        <div className="panel-head">
          <div>
            <h2 className="panel-title">Runtime readiness</h2>
            <p className="panel-note">
              Readiness and provider residency are separate states.
            </p>
          </div>
          <button
            className="btn btn-sm"
            disabled={busy}
            onClick={() => void run("retry_runtime")}
            type="button"
          >
            Retry runtime
          </button>
        </div>
        <div className="readiness-stage">
          <div className="readiness-rows">
            {readiness.map((row) => (
              <div className="readiness-row" key={row.label}>
                <span
                  aria-hidden="true"
                  className="dot"
                  data-tone={row.tone || undefined}
                />
                <span className="readiness-label">{row.label}</span>
                <span className="readiness-detail">{row.detail}</span>
                <span
                  className="readiness-value"
                  data-tone={row.tone || undefined}
                >
                  {row.value}
                </span>
              </div>
            ))}
          </div>
        </div>
      </section>
      <section className="panel panel-quiet" data-rise="2">
        <div className="logs-head">
          <h2 className="panel-title">Recent records</h2>
          <div aria-label="Filter by log level" className="logs-filters">
            {levels.map((level) => (
              <button
                aria-pressed={filter === level}
                className="chip"
                key={level}
                onClick={() => setFilter(level)}
                type="button"
              >
                {titleCase(level)}
              </button>
            ))}
          </div>
          <select
            aria-label="Filter by subsystem"
            className="select"
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
            className="log-search"
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search records"
            value={search}
          />
        </div>
        <div aria-live="polite" className="log-list">
          {records.length === 0 ? (
            <div className="log-empty">{error || "No records match."}</div>
          ) : (
            records.map((record, index) => (
              <LogLine key={`${record.timestamp}-${index}`} record={record} />
            ))
          )}
        </div>
        <div className="logs-foot">
          <span className="logs-summary">
            {snapshot
              ? `${records.length} of ${snapshot.records.length} records · ${snapshot.log_path ?? state.runtime.log_path ?? ""}`
              : "Logs are loading."}
          </span>
          <div className="logs-actions">
            <button
              className="btn btn-sm"
              disabled={busy || !snapshot}
              onClick={() => void refreshLogs()}
              type="button"
            >
              Refresh
            </button>
            <button
              className="btn btn-sm"
              disabled={busy || records.length === 0}
              onClick={() => void copyLogs()}
              type="button"
            >
              Copy visible
            </button>
            <button
              className="btn btn-sm btn-quiet"
              disabled={busy || !snapshot}
              onClick={() => void emptyLogs()}
              type="button"
            >
              Clear
            </button>
            <button
              className="btn btn-sm btn-quiet"
              disabled={busy}
              onClick={() => void saveDiagnostics()}
              type="button"
            >
              Export diagnostics
            </button>
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

function LogLine({ record }: { record: LogRecord }) {
  return (
    <div className="log-row" data-level={record.level}>
      <span className="log-time">
        {new Date(record.timestamp).toLocaleTimeString()}
      </span>
      <span className="log-level">{record.level}</span>
      <span className="log-subsystem">{record.subsystem}</span>
      <span className="log-message">{record.message}</span>
    </div>
  );
}

function readinessRows(
  state: HanlyState,
): Array<{ label: string; value: string; detail: string; tone?: string }> {
  const status = state.runtime.status ?? {};
  const engine = state.runtime.engine ?? {};
  const hotkeys = state.runtime.hotkeys ?? {};
  const bound = HOTKEYS.filter((item) => Boolean(state.config[item.id]));
  const active = bound.filter((item) => Boolean(hotkeys[item.action]));
  const rows = [
    {
      label: "Runtime",
      value: titleCase(status.phase),
      detail: status.message || titleCase(status.stage, ""),
      tone:
        status.phase === "ready"
          ? "ok"
          : status.phase === "failed"
            ? "bad"
            : "warn",
    },
    {
      label: "Lookup engine",
      value:
        engine.state === "ready"
          ? "loaded"
          : engine.state === "sleeping"
            ? "sleeping"
            : titleCase(engine.state),
      detail: engine.message ?? "",
      tone: engine.state === "error" ? "bad" : "",
    },
    {
      label: "OCR",
      value: state.runtime.ocr_provider ?? "not reported",
      detail: "",
      tone: "",
    },
    {
      label: "Shortcuts",
      value: `${active.length} / ${HOTKEYS.length}`,
      detail: bound.length === HOTKEYS.length ? "" : "one action is unassigned",
      tone: active.length === HOTKEYS.length ? "ok" : "warn",
    },
  ];
  for (const resource of state.runtime.resources ?? []) {
    rows.push({
      label: resource.id,
      value: resource.version
        ? `v${resource.version}`
        : titleCase(resource.status),
      detail: [
        resource.kind,
        resource.compatible ? "compatible" : "review needed",
        ...(resource.diagnostics ?? []),
      ]
        .filter(Boolean)
        .join(" · "),
      tone: resource.compatible ? "ok" : "warn",
    });
  }
  const permissions = state.permissions.items ?? [];
  if (state.permissions.supported) {
    const granted = permissions.filter((item) => item.granted).length;
    rows.push({
      label: "Permissions",
      value: `${granted} / ${permissions.length}`,
      detail: permissions
        .filter((item) => !item.granted)
        .map((item) => item.label)
        .join(", "),
      tone: granted === permissions.length ? "ok" : "warn",
    });
  }
  return rows;
}

function formatBytes(bytes?: number): string {
  if (typeof bytes !== "number" || bytes <= 0) return "";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

function describePlan(plan: UpdateState["plan"]): string {
  if (!plan) return "";
  const kind =
    plan.source === "delta" ? "Differential update" : "Full download";
  const counts = [
    plan.replace_count && `${plan.replace_count} replaced`,
    plan.add_count && `${plan.add_count} added`,
    plan.delete_count && `${plan.delete_count} removed`,
  ]
    .filter(Boolean)
    .join(", ");
  return [kind, formatBytes(plan.download_bytes), counts]
    .filter(Boolean)
    .join(" · ");
}
