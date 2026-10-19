import { emit } from "@tauri-apps/api/event";
import { mockIPC } from "@tauri-apps/api/mocks";
import type { HanlyState } from "../src/contracts/desktop.ts";
import {
  popupPayload,
  popupSamples,
  previewLogs,
  previewState,
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

let state: HanlyState = previewState();
state.config.theme = theme;
let popupSequence = 0;

type Params = Record<string, unknown>;

function showPopup(expanded: boolean, replacement: boolean) {
  popupSequence += 1;
  void emit("desktop-popup", {
    type: "popup",
    sequence: popupSequence,
    payload: popupPayload(sample, expanded, replacement, theme),
  });
}

function setState(next: HanlyState): HanlyState {
  state = next;
  void emit("desktop-state", state);
  return state;
}

function controlCenter(method: string, params: Params): unknown {
  switch (method) {
    case "get_state":
    case "refresh_permissions":
      return state;
    case "get_logs":
    case "clear_logs":
      return previewLogs;
    case "start_capture":
    case "stop_capture": {
      const running = method === "start_capture";
      return setState({
        ...state,
        app: { ...state.app, capture_running: running, state: running ? "running" : "stopped", activity: running ? "armed" : "stopped" },
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
    case "export_diagnostics":
      return { path: "~/Library/Logs/Hanly/hanly-diagnostics-preview.json", records: previewLogs.records.length };
    default:
      return state;
  }
}

function popup(method: string, params: Params): unknown {
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
await import("../src/main.tsx");
