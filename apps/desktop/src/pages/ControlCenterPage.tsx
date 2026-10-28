import { useCallback, useEffect, useState, type MouseEvent } from "react";
import type { ReactNode } from "react";
import { PixelButton } from "../components/PixelButton.tsx";
import { SidebarShell } from "../components/controlCenter/SidebarShell.tsx";
import { Brand, CaptureChoiceDialog, LiveCard, LoadingPanel } from "../components/controlCenter/Shared.tsx";
import { AppearancePage } from "./controlCenter/AppearancePage.tsx";
import { CapturePage } from "./controlCenter/CapturePage.tsx";
import { LogsPage } from "./controlCenter/LogsPage.tsx";
import { PermissionsPage } from "./controlCenter/PermissionsPage.tsx";
import { ShortcutsPage } from "./controlCenter/ShortcutsPage.tsx";
import { UpdatesPage } from "./controlCenter/UpdatesPage.tsx";
import { useDesktopState } from "../hooks/useDesktopState.ts";
import {
  PAGE_COPY,
  SECTIONS,
  sectionIcon,
  type Section,
} from "./controlCenter/constants.ts";
import { errorText, settingPendingKey } from "./controlCenter/helpers.ts";
import type { RunCommand } from "./controlCenter/types.ts";

const windowsWebView =
  typeof navigator !== "undefined" && /Windows/i.test(navigator.userAgent);

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
  const [pendingCommands, setPendingCommands] = useState<Record<string, number>>(
    {},
  );
  const [actionError, setActionError] = useState("");
  const [quitAsking, setQuitAsking] = useState(false);
  const [choosingArea, setChoosingArea] = useState(false);

  const isPending = useCallback(
    (key: string) => Boolean(pendingCommands[key]),
    [pendingCommands],
  );

  const run = useCallback<RunCommand>(
    async (method, params = {}, pendingKey = method) => {
      setPendingCommands((current) => ({
        ...current,
        [pendingKey]: (current[pendingKey] ?? 0) + 1,
      }));
      setActionError("");
      try {
        return await runCommand(method, params);
      } catch (error) {
        setActionError(errorText(error));
        return undefined;
      } finally {
        setPendingCommands((current) => {
          const count = current[pendingKey] ?? 0;
          if (count <= 1) {
            const next = { ...current };
            delete next[pendingKey];
            return next;
          }
          return { ...current, [pendingKey]: count - 1 };
        });
      }
    },
    [runCommand],
  );

  const saveSettings = useCallback(
    (changes: Record<string, unknown>) => {
      const [setting] = Object.keys(changes);
      const pendingKey = setting
        ? settingPendingKey(setting)
        : "update_settings";
      return run("update_settings", { changes }, pendingKey);
    },
    [run],
  );

  const selectArea = useCallback((event: MouseEvent<HTMLButtonElement>) => {
    // Safari does not focus buttons on pointer activation.
    event.currentTarget.focus();
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

  const [dark, setDark] = useState(false);

  useEffect(() => {
    const theme = state?.config.theme ?? "system";
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      const mode = theme === "system" ? (media.matches ? "dark" : "light") : theme;
      document.documentElement.dataset.mode = mode;
      setDark(mode === "dark");
    };
    apply();
    media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  }, [state?.config.theme]);

  if (!state) {
    return (
      <div
        className="app skin-village flex h-full min-h-0"
        data-app-font="pixel"
        data-rendering-platform={windowsWebView ? "windows" : undefined}
      >
        <SidebarShell
          dark={dark}
          disabled
          onToggleTheme={() => void saveSettings({ theme: dark ? "light" : "dark" })}
        >
          <Brand />
          <div className="sidebar-foot relative z-[1] mt-auto flex flex-none flex-col gap-2 px-0 pt-[9px]">
            <LiveCard activity={activity} engine={engine} runtime={runtime} />
          </div>
        </SidebarShell>
        <main className="main flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden px-0 py-3">
          <header className="page-head mx-auto flex min-h-[140px] w-full max-w-[1024px] flex-none items-center justify-between gap-6 border-0 px-8 py-6">
            <div className="flex min-w-0 flex-1 items-center gap-4">
              <div className="min-w-0">
                <h1 className="page-title m-0 text-2xl font-normal leading-8 tracking-normal">
                  Hanly
                </h1>
                <p className="page-desc mt-1.5 max-w-[370px] text-sm leading-[22px]">
                  Desktop status and settings.
                </p>
              </div>
            </div>
          </header>
          <div className="page-body mx-auto min-h-0 w-full max-w-[1024px] flex-1 overflow-x-hidden overflow-y-auto px-8 pt-1 pb-10">
            {(connectionError || serviceStatus?.state === "failed") && (
              <div className="banner" data-tone="bad" role="alert">
                <span className="banner-text">
                  {connectionError ||
                    serviceStatus?.message ||
                    "The Hanly desktop service is unavailable."}
                </span>
                <PixelButton
                  className="btn btn-sm btn-quiet"
                  disabled={refreshing}
                  onClick={() =>
                    void run("retry_runtime").then(() => refresh())
                  }
                  type="button"
                >
                  Try again
                </PixelButton>
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
        isPending={isPending}
        run={run}
        saveSettings={saveSettings}
        onSelectArea={selectArea}
      />
    );
  } else if (section === "permissions") {
    content = <PermissionsPage state={state} isPending={isPending} run={run} />;
  } else if (section === "shortcuts") {
    content = (
      <ShortcutsPage
        state={state}
        isPending={isPending}
        run={run}
        saveSettings={saveSettings}
      />
    );
  } else if (section === "appearance") {
    content = (
      <AppearancePage
        state={state}
        isPending={isPending}
        saveSettings={saveSettings}
      />
    );
  } else if (section === "updates") {
    content = <UpdatesPage state={state} isPending={isPending} run={run} />;
  } else {
    content = <LogsPage state={state} isPending={isPending} run={run} />;
  }

  return (
    <div
      className="app skin-village flex h-full min-h-0"
      data-app-font={state.config.app_font ?? "pixel"}
      data-rendering-platform={windowsWebView ? "windows" : undefined}
    >
      <SidebarShell
        compact={state.config.sidebar_layout === "compact"}
        dark={dark}
        disabled={isPending(settingPendingKey("theme"))}
        onToggleTheme={() => void saveSettings({ theme: dark ? "light" : "dark" })}
      >
        <Brand />
        <nav aria-label="Sections" className="nav relative z-[1] mt-0 flex flex-none flex-col gap-2">
          {SECTIONS.map((item) => (
            <PixelButton
              aria-current={section === item.id ? "page" : undefined}
              className="nav-item"
              aria-label={item.label}
              title={item.label}
              key={item.id}
              onClick={() => {
                setActionError("");
                setSection(item.id);
              }}
              type="button"
            >
              <span className="nav-content flex w-full min-w-0 items-center justify-center gap-[10px]">
                <span aria-hidden="true" className="nav-dot grid h-8 w-8 flex-none place-items-center bg-transparent">
                  <img src={sectionIcon(item.id)} alt="" />
                </span>
                <span className="nav-label">{item.label}</span>
              </span>
            </PixelButton>
          ))}
        </nav>
        <div className="sidebar-foot relative z-[1] mt-auto flex flex-none flex-col gap-2 px-0 pt-[9px]">
          <LiveCard
            activity={activity}
            engine={engine}
            runtime={runtime}
            version={state.runtime.app_version}
            detail={state.app.detail}
          />
          {quitAsking ? (
            <div className="quit-confirm flex flex-col gap-[7px] p-[10px]">
              <span className="quit-note">
                Capture stops and the tray icon goes away.
              </span>
              <div className="quit-row flex flex-wrap gap-[6px]">
                <PixelButton
                  className="btn btn-sm btn-exit"
                  disabled={isPending("quit")}
                  onClick={() => void run("quit")}
                  type="button"
                >
                  Quit
                </PixelButton>
                <PixelButton
                  autoFocus
                  className="btn btn-sm btn-quiet"
                  onClick={() => setQuitAsking(false)}
                  type="button"
                >
                  Cancel
                </PixelButton>
              </div>
            </div>
          ) : (
            <PixelButton
              className="btn btn-sm btn-exit-quiet"
              aria-label="Quit Hanly"
              title="Quit Hanly"
              onClick={() => setQuitAsking(true)}
              type="button"
            >
              Quit Hanly
            </PixelButton>
          )}
        </div>
      </SidebarShell>

      <main className="main flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden px-0 py-3">
        <header className="page-head mx-auto flex min-h-[140px] w-full max-w-[1024px] flex-none items-center justify-between gap-6 border-0 px-8 py-6">
          <div className="flex min-w-0 flex-1 items-center gap-4" data-anim="a">
            <img
              aria-hidden="true"
              className="page-icon h-11 w-11 flex-none object-contain [image-rendering:pixelated]"
              src={sectionIcon(section)}
              alt=""
            />
            <div className="min-w-0">
              <h1 className="page-title m-0 text-2xl font-normal leading-8 tracking-normal">
                {page.kicker}
              </h1>
              <p className="page-desc mt-1.5 max-w-[370px] text-sm leading-[22px]">
                {page.description}
              </p>
            </div>
          </div>
          {target && (
            <div className="head-actions flex flex-none items-center gap-3">
              <PixelButton
                className="btn"
                icon="/design/media/assets/icons/v2/capture-frame.png"
                onClick={selectArea}
                type="button"
              >
                Select area
              </PixelButton>
              <PixelButton
                className="btn btn-primary btn-capture"
                icon={sectionIcon("capture")}
                data-art-role={state.app.capture_running ? "danger" : "primary"}
                disabled={
                  isPending(
                    state.app.capture_running ? "stop_capture" : "start_capture",
                  ) ||
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
              </PixelButton>
            </div>
          )}
        </header>
        <div key={section} className="page-body mx-auto min-h-0 w-full max-w-[1024px] flex-1 overflow-x-hidden overflow-y-auto px-8 pt-1 pb-10" data-anim="a">
          {connectionError && (
            <div className="banner" data-tone="warn" role="status">
              <span className="banner-text">{connectionError}</span>
              <PixelButton
                className="btn btn-sm btn-quiet"
                disabled={refreshing}
                onClick={() => void refresh()}
                type="button"
              >
                Reconnect
              </PixelButton>
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
              busy={
                isPending("set_capture_mode") || isPending("select_region")
              }
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
