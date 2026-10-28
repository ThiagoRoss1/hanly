import { emit } from "@tauri-apps/api/event";
import { mockIPC } from "@tauri-apps/api/mocks";
import type { HanlyState } from "../src/contracts/desktop.ts";
import {
  popupPayload,
  popupSamples,
  previewLogs,
  previewState,
  previewUpdateState,
  previewWindowsState,
  type PopupSample,
} from "./fixtures.ts";

// Development-only browser preview of the React views. It replaces the native
// bridge with fixtures; native frames, focus, shortcuts and permissions still
// need the real desktop app.

const query = new URLSearchParams(window.location.search);
const view = query.get("view") ?? "control_center";
const theme = query.get("theme") ?? "system";
const requested = query.get("sample") ?? "school";
const sample: PopupSample = requested in popupSamples ? (requested as PopupSample) : "school";

const windowsPreview = query.get("platform") === "windows";
let state: HanlyState = windowsPreview ? previewWindowsState() : previewState();
state.config.theme = theme;
state.config.popup_font = query.get("font") === "pixel" ? "pixel" : "normal";
state.config.app_font = query.get("app_font") === "normal" ? "normal" : "pixel";
state.config.sidebar_layout = query.get("navigation") === "compact" ? "compact" : "normal";
const requestedOcr = query.get("ocr");
if (requestedOcr && state.runtime.ocr_backends.includes(requestedOcr)) {
  state.config.ocr_backend = requestedOcr;
}
const activity = query.get("activity");
if (activity && ["stopped", "armed", "running", "preparing", "error"].includes(activity)) {
  state.app.activity = activity;
  state.app.detail = activity === "error" ? "The lookup engine could not start. Retry to continue." : `Capture is ${activity}.`;
  state.app.capture_running = activity === "running" || activity === "armed";
}
if (query.get("permissions") === "missing") {
  state.permissions.items = state.permissions.items.map(item => ({ ...item, granted: false, state: "required" }));
}
if (query.get("permissions") === "unsupported") {
  state.permissions = {
    supported: false,
    available: true,
    items: [],
  };
}
const update = query.get("update");
if (update && ["checking", "available", "installing", "completed", "cancelled", "downloading", "failed"].includes(update)) {
  state.updates = previewUpdateState(update);
}
let popupSequence = 0;

type Params = Record<string, unknown>;

function showPopup(expanded: boolean, replacement: boolean) {
  popupSequence += 1;
  void emit("desktop-popup", {
    type: "popup",
    sequence: popupSequence,
    payload: { ...popupPayload(sample, expanded, replacement, theme), popup_font: state.config.popup_font, technical_details: query.get("details") ?? "off" },
  });
}

function setState(next: HanlyState): HanlyState {
  state = next;
  void emit("desktop-state", state);
  return state;
}

function advanceUpdatePreview(expectedStatus: string, nextStage: string, delayMs: number) {
  window.setTimeout(() => {
    if (state.updates.status !== expectedStatus) return;
    setState({ ...state, updates: previewUpdateState(nextStage) });
  }, delayMs);
}

function controlCenter(method: string, params: Params): unknown {
  switch (method) {
    case "get_state":
    case "refresh_permissions":
      return state;
    case "get_logs":
      return { ...previewLogs, log_path: state.runtime.log_path };
    case "clear_logs":
      return { ...previewLogs, records: [], log_path: state.runtime.log_path };
    case "start_capture":
    case "stop_capture": {
      const running = method === "start_capture";
      return setState({
        ...state,
        app: {
          ...state.app,
          capture_running: running,
          state: running ? "running" : "stopped",
          activity: running ? "armed" : "stopped",
          detail: running ? "Waiting for a Korean word under the cursor." : "Capture is stopped.",
        },
      });
    }
    case "update_settings":
      return setState({ ...state, config: { ...state.config, ...(params.changes as Params) } });
    case "set_hover_delay":
      return setState({ ...state, config: { ...state.config, hover_delay_ms: Number(params.delay_ms) } });
    case "set_hotkey":
      return setState({ ...state, config: { ...state.config, hotkey: String(params.hotkey) } });
    case "set_capture_mode":
      return setState({ ...state, config: { ...state.config, capture_mode: String(params.mode) } });
    case "check_for_updates": {
      const checking = setState({ ...state, updates: previewUpdateState("checking") });
      advanceUpdatePreview("checking", "available", 1_200);
      return checking;
    }
    case "install_application_update": {
      const downloading = setState({ ...state, updates: previewUpdateState("downloading") });
      advanceUpdatePreview("downloading", "installing", 3_000);
      advanceUpdatePreview("installing", "completed", 6_000);
      return downloading;
    }
    case "cancel_update":
      return setState({ ...state, updates: previewUpdateState("cancelled") });
    case "export_diagnostics":
      return { path: "~/Library/Logs/Hanly/hanly-diagnostics-preview.json", records: previewLogs.records.length };
    default:
      return state;
  }
}

function popup(method: string, params: Params): unknown {
  if (method === "popup_measure") return { sequence: popupSequence, room: Math.min(560, window.innerHeight) };
  if (method === "popup_geometry") {
    // The measured card is what the native host would present.
    const size = `${String(params.width)}×${String(params.height)}`;
    document.title = `Hanly popup ${size}`;
    console.info(`popup_geometry #${String(params.sequence)}: ${size}`);
  } else if (method === "popup_expand") {
    showPopup(params.expanded === true, false);
  } else if (method === "popup_close") {
    void emit("desktop-popup", { type: "popup_hide", sequence: popupSequence });
  }
  return { sequence: popupSequence };
}

mockIPC(
  (command, payload) => {
    if (command !== "desktop_request") throw new Error(`Unexpected command ${command}`);
    const { method, params = {} } = payload as { method: string; params?: Params };
    if (method === "frontend_ready") {
      // Deliver after the view's listeners are attached, as the native host does.
      if (view === "popup") window.setTimeout(() => showPopup(false, true));
      if (view === "region_selector") {
        window.setTimeout(() => void emit("desktop-region", { bounds: { left: 0, top: 0, width: window.innerWidth, height: window.innerHeight }, monitors: state.app.targets }));
      }
      return {};
    }
    if (method.startsWith("popup_")) return popup(method, params);
    return controlCenter(method, params);
  },
  { shouldMockEvents: true },
);

if (view === "popup") document.documentElement.dataset.preview = "popup";
if (query.get("platform") === "windows") {
  const root = document.getElementById("root");

  const markWindowsView = () => {
    document
      .querySelectorAll<HTMLElement>(".app.skin-village")
      .forEach((app) => app.setAttribute("data-rendering-platform", "windows"));
  };
  const observer = new MutationObserver(() => {
    if (document.querySelector(".app.skin-village")) {
      markWindowsView();
      observer.disconnect();
    }
  });
  if (root) observer.observe(root, { childList: true, subtree: true });
  markWindowsView();
}
if (view === "control_center" && query.get("platform") === "windows") {
  const root = document.getElementById("root");
  root?.classList.add("native-windows-chrome");
}
await import("../src/main.tsx");
