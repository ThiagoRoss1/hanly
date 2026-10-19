import { useEffect, useState } from "react";
import type { HanlyState } from "../../contracts/desktop.ts";
import type { DesktopMethod } from "../../services/desktopBridgeCore.ts";
import { PixelButton } from "../../components/PixelButton.tsx";
import { CaptureSetting, TargetOption } from "../../components/controlCenter/Controls.tsx";
import {
  formatHotkey,
  regionLabel,
  settingPendingKey,
  validateHoverDelay,
} from "./helpers.ts";
import type { IsPending } from "./types.ts";

export function CapturePage({
  state,
  isPending,
  run,
  saveSettings,
  onSelectArea,
}: {
  state: HanlyState;
  isPending: IsPending;
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
    <section className="page flex flex-col">
      <div
        className="capture-status relative isolate flex min-h-[76px] flex-wrap items-center gap-x-3 gap-y-2 px-6 py-5"
        data-live={Boolean(app.capture_running)}
        data-rise="1"
      >
        <span
          aria-hidden="true"
          className="dot h-2 w-2 shrink-0"
          data-live={Boolean(app.capture_running)}
          data-tone={app.capture_running ? "ok" : undefined}
        />
        <span className="capture-headline text-sm font-semibold tracking-tight">
          {app.activity === "preparing"
            ? "Preparing capture"
            : app.activity === "error"
              ? "Capture needs attention"
              : app.capture_running
                ? "Reading now"
                : "Not reading"}
        </span>
        <span className="capture-where min-w-[180px] flex-1 text-[13px]">
          {(app.activity === "preparing" || app.activity === "error") &&
          app.detail
            ? app.detail
            : mode === "region"
              ? region
                ? `${targetLabel} · ${region.width} × ${region.height} at ${region.left}, ${region.top}`
                : `${targetLabel} · no region saved, reading the whole monitor`
              : `${targetLabel} · whole screen`}
        </span>
        <span className="capture-hint ml-auto flex items-center gap-[7px] text-xs leading-[18px]">
          {app.activity === "preparing"
            ? "please wait"
            : app.capture_running
              ? config.hover_activation === "push_to_hover" && config.hotkey
                ? `hold ${formatHotkey(config.hotkey).join(" ")}`
                : "hover active"
              : "press start to read"}
        </span>
      </div>

      <div className="capture-stage mt-6 w-full min-w-0 max-w-full">
        <section
          aria-labelledby="target-heading"
          className="panel capture-target-panel relative min-w-0"
          data-rise="2"
        >
          <div className="panel-head relative flex h-[34px] min-h-[34px] items-center justify-center p-0">
            <h2 className="panel-title absolute inset-x-[22px] top-0 m-0 flex h-[34px] items-center justify-center text-center" id="target-heading">
              Reading target
            </h2>
          </div>
          <div
            aria-label="Capture target"
            className="panel-rows target-choices grid grid-cols-2 gap-0 px-4 pt-[14px] pb-4"
            role="radiogroup"
          >
            <TargetOption
              selected={mode !== "region"}
              disabled={isPending("set_capture_mode")}
              label="Current monitor"
              art="/design/media/assets/icons/custom/icon-monitor.svg"
              detail="Follows the display the cursor is on."
              layout="target"
              onSelect={() =>
                void run("set_capture_mode", { mode: "full_monitor" })
              }
            />
            <TargetOption
              selected={mode === "region"}
              disabled={isPending("set_capture_mode")}
              label="Selected region"
              art="/design/media/assets/icons/v2/capture-frame.png"
              detail="A fixed rectangle you draw once."
              layout="target"
              onSelect={() => void run("set_capture_mode", { mode: "region" })}
            />
          </div>
          <div className="capture-guidance mx-6 flex items-center gap-2.5 border-t border-[var(--skin-line)] py-3 pb-6">
            <img className="h-6 w-6 flex-none object-contain [image-rendering:pixelated]" src="/design/media/assets/icons/v2/icon-info.png" alt="" />
            <p className="m-0 text-sm leading-[22px]">Hover over a Korean word to see its meaning.</p>
          </div>
        </section>

        <div
          aria-hidden={mode !== "region"}
          inert={mode !== "region"}
          className="region-collapse grid grid-rows-[0fr] transition-[grid-template-rows] duration-[250ms] ease-out"
          data-open={mode === "region"}
        >
          <div className="collapse-inner">
            <section
              aria-labelledby="region-heading"
              className="panel collapse-gap mt-4 relative min-w-0"
              data-rise="3"
            >
              <div className="region-head flex items-center gap-2.5 px-5 pt-[25px] pb-2.5">
                <h2 className="panel-title" id="region-heading">
                  Region
                </h2>
                <span className="region-coords ml-auto font-mono text-[11px]">{regionLabel(region)}</span>
                <PixelButton
                  className="btn btn-sm btn-quiet"
                  disabled={isPending("select_region")}
                  onClick={onSelectArea}
                  type="button"
                >
                  Select area
                </PixelButton>
              </div>
              <div className="region-body flex flex-col gap-[13px] border-t border-[var(--skin-line)] px-5 pt-1.5 pb-5">
                <div className="region-fields grid grid-cols-2 gap-[10px] sm:grid-cols-4">
                  {(["left", "top", "width", "height"] as const).map((key) => (
                    <label className="field flex min-w-0 flex-col gap-1" key={key}>
                      <span className="field-label text-[11px] leading-[17px] font-bold">{key}</span>
                      <input
                        aria-label={`Region ${key}`}
                        className="input h-10 w-full min-w-0 px-3 py-[7px] text-xs leading-[18px]"
                        disabled={isPending("set_region") || mode !== "region"}
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
                <div className="region-actions flex items-center justify-end gap-2 pt-2.5">
                  <PixelButton
                    className="btn btn-sm btn-text"
                    disabled={isPending("set_region") || mode !== "region"}
                    onClick={() => void run("set_region", { region: null })}
                    type="button"
                  >
                    Clear
                  </PixelButton>
                  <PixelButton
                    className="btn btn-sm btn-primary"
                    disabled={isPending("set_region") || mode !== "region"}
                    onClick={() => void applyRegion()}
                    type="button"
                  >
                    Apply
                  </PixelButton>
                </div>
              </div>
            </section>
          </div>
        </div>

        <details
          aria-labelledby="capture-settings-heading"
          className="settings-card capture-settings relative mt-6 p-0"
          data-rise="4"
        >
          <summary className="capture-settings-summary relative flex min-h-[88px] cursor-pointer list-none items-center gap-3.5 px-6 pt-[47px] pb-[18px]" id="capture-settings-heading">
            <span className="settings-summary-title absolute inset-x-6 top-1 flex h-[34px] items-center justify-center text-center">Capture settings</span>
            <span className="settings-summary-note flex-1 text-center text-[13px] leading-5">Monitor · hover delay · engine</span>
            <span aria-hidden="true" className="settings-chevron shrink-0 text-xl leading-5 transition-transform duration-200">⌄</span>
          </summary>
          <div className="capture-settings-body divide-y divide-[var(--skin-line)] px-6 pb-5">
          <CaptureSetting
            label="Monitor"
            controlId="capture-target"
            help="Which display Hanly reads, in either target."
          >
            <select
              aria-describedby="capture-target-help"
              className="select h-10 min-h-10 w-full min-w-0 px-3 py-[7px] text-xs leading-[18px]"
              id="capture-target"
              disabled={isPending("set_target")}
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
              className="h-11 min-w-[100px] max-w-none flex-1 p-0"
              disabled={isPending("set_hover_delay")}
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
            <span className="delay-value inline-flex flex-none items-center gap-1.5">
              <input
                aria-label="Hover delay value in milliseconds"
                aria-describedby="hover-delay-slider-help"
                className="delay-input h-10 min-h-10 w-[66px] min-w-0 px-3 py-[7px] text-center text-xs leading-[18px]"
                disabled={isPending("set_hover_delay")}
                inputMode="numeric"
                onBlur={(event) => void saveDelay(event.currentTarget.value)}
                onChange={(event) => setDelayDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") event.currentTarget.blur();
                }}
                value={delayDraft}
              />
              <span className="delay-unit text-xs leading-[18px]">ms</span>
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
              className="select h-10 min-h-10 w-full min-w-0 px-3 py-[7px] text-xs leading-[18px]"
              disabled={isPending(settingPendingKey("lookup_preload"))}
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
              className="select h-10 min-h-10 w-full min-w-0 px-3 py-[7px] text-xs leading-[18px]"
              disabled={
                isPending(settingPendingKey("ocr_backend")) ||
                (state.runtime.ocr_backends ?? []).length === 0
              }
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
          </div>
        </details>
      </div>
    </section>
  );
}
