import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { readFile } from "node:fs/promises";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { HanlyState, LogSnapshot } from "../../src/contracts/desktop.ts";
import { appRoutes } from "../../src/app/router.tsx";
import { isHanlyState } from "../../src/features/desktopState.ts";

const { invokeMock, eventHandlers, deferredListeners, deferListen } = vi.hoisted(() => ({
  invokeMock: vi.fn(),
  eventHandlers: new Map<string, (event: { payload: unknown }) => void>(),
  deferredListeners: new Map<string, () => void>(),
  deferListen: { value: false },
}));

vi.mock("@tauri-apps/api/core", () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
}));

vi.mock("@tauri-apps/api/event", () => ({
  listen: (name: string, callback: (event: { payload: unknown }) => void) => {
    eventHandlers.set(name, callback);
    const dispose = () => eventHandlers.delete(name);
    if (deferListen.value) {
      return new Promise<() => void>((resolve) => {
        deferredListeners.set(name, () => resolve(dispose));
      });
    }
    return Promise.resolve(dispose);
  },
}));

function createState(): HanlyState {
  return {
    app: {
      state: "stopped",
      activity: "stopped",
      detail: "Desktop runtime is not initialized.",
      capture_running: false,
      capture_mode: "full_monitor",
      target: "cursor",
      region: null,
      targets: [],
    },
    config: {
      hover_delay_ms: 80,
      hover_activation: "push_to_hover",
      lookup_preload: "when_capture_starts",
      ocr_backend: "auto",
      theme: "system",
      popup_default_size: "compact",
      technical_details: "off",
      capture_mode: "full_monitor",
      capture_monitor: null,
      capture_region: null,
      hotkey: "",
      hover_hotkey: "",
      capture_hotkey: "",
      popup_enabled: true,
      update_checks_enabled: true,
    },
    runtime: {
      ocr_provider: null,
      ocr_backends: ["auto", "easyocr"],
      app_version: "1.1.0",
      hover_delay_bounds: { min: 20, max: 2000 },
      resources: [],
      status: { phase: "idle", stage: "desktop_composition", message: "Runtime unavailable." },
      engine: { state: "sleeping", message: "Lookup providers are not initialized." },
      hotkeys: {},
      log_path: null,
      diagnostics: [],
    },
    updates: { available: false, status: "unavailable", message: "Updates are not connected." },
    permissions: { supported: false, items: [] },
  };
}

let state: HanlyState;
let logSnapshot: LogSnapshot;
let stateReadError: unknown;

function renderRoute(path: string) {
  const router = createMemoryRouter(appRoutes, { initialEntries: [path] });
  render(<RouterProvider router={router} />);
  return router;
}

beforeEach(() => {
  state = createState();
  stateReadError = null;
  logSnapshot = {
    records: [{ timestamp: "2026-10-13T03:00:00+00:00", level: "info", subsystem: "Service", message: "Desktop service started." }],
    levels: ["info", "warning", "error"],
    subsystems: ["Service"],
    log_path: null,
  };
  eventHandlers.clear();
  deferredListeners.clear();
  deferListen.value = false;
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  });
  Object.defineProperty(window, "devicePixelRatio", { configurable: true, value: 2 });
  if (!Element.prototype.setPointerCapture) {
    Object.defineProperty(Element.prototype, "setPointerCapture", { configurable: true, value: vi.fn() });
  }
  invokeMock.mockImplementation(async (command: string, args: { method?: string; params?: Record<string, unknown> }) => {
    if (command !== "desktop_request") throw new Error(`Unexpected Tauri command ${command}`);
    const method = args.method;
    const params = args.params ?? {};
    if (method === "frontend_ready") return {};
    if (method === "get_state") {
      if (stateReadError) throw stateReadError;
      return state;
    }
    if (method === "update_settings") {
      const changes = params.changes as Record<string, unknown>;
      state = {
        ...state,
        config: { ...state.config, ...changes },
        app: changes.capture_mode ? { ...state.app, capture_mode: String(changes.capture_mode) } : state.app,
      };
      return state;
    }
    if (method === "set_capture_mode") {
      state = { ...state, app: { ...state.app, capture_mode: String(params.mode) }, config: { ...state.config, capture_mode: String(params.mode) } };
      return state;
    }
    if (method === "set_hover_delay") {
      state = { ...state, config: { ...state.config, hover_delay_ms: Number(params.delay_ms) } };
      return state;
    }
    if (method === "set_hotkey") {
      state = { ...state, config: { ...state.config, hotkey: String(params.hotkey) } };
      return state;
    }
    if (method === "set_target") {
      state = { ...state, app: { ...state.app, target: String(params.target) }, config: { ...state.config, capture_monitor: params.target === "cursor" ? null : Number(String(params.target).split(":")[1]) } };
      return state;
    }
    if (method === "set_region") {
      state = { ...state, app: { ...state.app, region: params.region as HanlyState["app"]["region"] }, config: { ...state.config, capture_region: params.region as HanlyState["config"]["capture_region"] } };
      return state;
    }
    if (method === "grant_permission") {
      state = { ...state, permissions: { ...state.permissions, items: state.permissions.items.map((item) => item.id === params.permission ? { ...item, state: "granted", granted: true } : item) } };
      return state;
    }
    if (method === "refresh_permissions") return state;
    if (method === "retry_runtime") return {};
    if (method === "install_application_update") {
      state = { ...state, updates: { ...state.updates, awaiting_confirmation: false, status: "downloading", cancellable: true, progress: { phase: "downloading", completed: 50, total: 100, fraction: 0.5 } } };
      return state;
    }
    if (method === "cancel_update") {
      state = { ...state, updates: { ...state.updates, awaiting_confirmation: false, status: "unavailable", cancellable: false, progress: null } };
      return state;
    }
    if (method === "quit") return {};
    if (method === "get_logs") return logSnapshot;
    if (method === "copy_text") return {};
    if (method === "clear_logs") return { records: [], levels: ["info", "warning", "error"], subsystems: [], log_path: null };
    if (method === "export_diagnostics") return { path: "/tmp/hanly-report.json", records: 1 };
    if (method === "popup_geometry" || method === "popup_expand" || method === "popup_close" || method === "popup_pressed") return {};
    if (method === "select_region" || method === "cancel_region" || method === "confirm_region") return {};
    throw { code: "unavailable", message: "Capture area selection is not ready in this build." };
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("desktop React routes", () => {
  it("uses a complete desktop-state snapshot in the page fixture", () => {
    expect(isHanlyState(createState())).toBe(true);
  });

  it("renders the native shell navigation, capture action, and quit control", async () => {
    renderRoute("/");

    await waitFor(() => expect(eventHandlers.has("desktop-state")).toBe(true));
    await waitFor(() => expect(invokeMock).toHaveBeenCalledWith("desktop_request", {
      method: "get_state",
      params: {},
    }));
    expect(await screen.findByRole("navigation", { name: "Sections" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Start capture" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Quit Hanly" })).toBeTruthy();
  });

  it("persists an appearance setting and reflects the acknowledged state", async () => {
    const user = userEvent.setup();
    renderRoute("/");

    await screen.findByRole("button", { name: "Start capture" });
    await user.click(screen.getByRole("button", { name: "Appearance" }));
    const theme = screen.getByRole("group", { name: "Theme" });
    const dark = within(theme).getByRole("button", { name: "Dark" });
    await user.click(dark);

    await waitFor(() => {
      expect(invokeMock).toHaveBeenCalledWith("desktop_request", {
        method: "update_settings",
        params: { changes: { theme: "dark" } },
      });
      expect(dark.getAttribute("aria-pressed")).toBe("true");
    });
  });

  it("persists popup size and technical-detail preferences through React controls", async () => {
    const user = userEvent.setup();
    renderRoute("/");
    await screen.findByRole("button", { name: "Start capture" });
    await user.click(screen.getByRole("button", { name: "Appearance" }));

    const size = screen.getByRole("group", { name: "Default popup size" });
    await user.click(within(size).getByRole("button", { name: "Expanded" }));
    await waitFor(() => expect(invokeMock).toHaveBeenCalledWith("desktop_request", {
      method: "update_settings",
      params: { changes: { popup_default_size: "expanded" } },
    }));
    const detail = screen.getByRole("group", { name: "Technical details" });
    await user.click(within(detail).getByRole("button", { name: "Full" }));
    await waitFor(() => expect(invokeMock).toHaveBeenCalledWith("desktop_request", {
      method: "update_settings",
      params: { changes: { technical_details: "full" } },
    }));
  });

  it("requires an explicit quit confirmation and uses the semantic exit action", async () => {
    const user = userEvent.setup();
    renderRoute("/");
    await screen.findByRole("button", { name: "Start capture" });
    await user.click(screen.getByRole("button", { name: "Quit Hanly" }));

    const confirm = screen.getByRole("button", { name: "Quit" });
    expect(confirm.classList.contains("btn-exit")).toBe(true);
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(invokeMock).not.toHaveBeenCalledWith("desktop_request", { method: "quit", params: {} });

    await user.click(screen.getByRole("button", { name: "Quit Hanly" }));
    await user.click(screen.getByRole("button", { name: "Quit" }));
    await waitFor(() => expect(invokeMock).toHaveBeenCalledWith("desktop_request", { method: "quit", params: {} }));
  });

  it("shows native unavailability instead of pretending capture started", async () => {
    const user = userEvent.setup();
    state = { ...state, runtime: { ...state.runtime, status: { ...state.runtime.status, phase: "ready" } } };
    renderRoute("/");

    const start = await screen.findByRole("button", { name: "Start capture" });
    await user.click(start);

    expect((await screen.findByRole("alert")).textContent).toContain("Capture area selection is not ready in this build.");
    expect(invokeMock).toHaveBeenCalledWith("desktop_request", { method: "start_capture", params: {} });
  });

  it("keeps capture visibly preparing until the runtime state changes", async () => {
    state = {
      ...state,
      app: { ...state.app, activity: "preparing", detail: "Loading the lookup runtime." },
      runtime: { ...state.runtime, status: { ...state.runtime.status, phase: "preparing", message: "Loading the lookup runtime." } },
    };
    renderRoute("/");

    expect(await screen.findByText("Preparing capture")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Start capture" }).hasAttribute("disabled")).toBe(true);
    expect(screen.getByText("Loading the lookup runtime.")).toBeTruthy();
  });

  it("polls through readiness and continues polling while update work remains active", async () => {
    const callbacks: Array<() => void> = [];
    const clearIntervalSpy = vi.spyOn(window, "clearInterval").mockImplementation(() => undefined);
    vi.spyOn(window, "setInterval").mockImplementation(((handler: TimerHandler, timeout?: number) => {
      if (timeout === 900 && typeof handler === "function") callbacks.push(handler as () => void);
      return callbacks.length;
    }) as typeof window.setInterval);
    state = {
      ...state,
      app: { ...state.app, activity: "preparing", detail: "Loading." },
      runtime: { ...state.runtime, status: { ...state.runtime.status, phase: "preparing" } },
      updates: { ...state.updates, status: "downloading", cancellable: true },
    };
    renderRoute("/");
    await screen.findByText("Preparing capture");
    await waitFor(() => expect(callbacks.length).toBe(1));

    state = {
      ...state,
      app: { ...state.app, activity: "stopped", detail: "Runtime ready." },
      runtime: { ...state.runtime, status: { ...state.runtime.status, phase: "ready" } },
    };
    await act(async () => {
      callbacks[0]!();
      await Promise.resolve();
    });
    expect(await screen.findByText("Not reading")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Start capture" }).hasAttribute("disabled")).toBe(false);
    await waitFor(() => expect(callbacks.length).toBe(2));

    state = { ...state, updates: { ...state.updates, status: "success", cancellable: false } };
    await act(async () => {
      callbacks[1]!();
      await Promise.resolve();
    });
    expect(clearIntervalSpy).toHaveBeenCalled();
  });

  it("stops polling after a failed state read and resumes after an explicit reconnect", async () => {
    const user = userEvent.setup();
    const callbacks: Array<() => void> = [];
    const clearIntervalSpy = vi.spyOn(window, "clearInterval").mockImplementation(() => undefined);
    vi.spyOn(window, "setInterval").mockImplementation(((handler: TimerHandler, timeout?: number) => {
      if (timeout === 900 && typeof handler === "function") callbacks.push(handler as () => void);
      return callbacks.length;
    }) as typeof window.setInterval);
    state = {
      ...state,
      app: { ...state.app, activity: "preparing" },
      runtime: { ...state.runtime, status: { ...state.runtime.status, phase: "preparing" } },
    };
    renderRoute("/");
    await screen.findByText("Preparing capture");
    await waitFor(() => expect(callbacks.length).toBe(1));

    stateReadError = new Error("Service did not answer.");
    await act(async () => {
      callbacks[0]!();
      await Promise.resolve();
    });
    expect(await screen.findByText("Service did not answer.")).toBeTruthy();
    expect(clearIntervalSpy).toHaveBeenCalled();

    stateReadError = null;
    state = {
      ...state,
      app: { ...state.app, activity: "stopped" },
      runtime: { ...state.runtime, status: { ...state.runtime.status, phase: "ready" } },
    };
    await user.click(screen.getByRole("button", { name: "Reconnect" }));
    await waitFor(() => expect(screen.queryByText("Service did not answer.")).toBeNull());
    expect(screen.getByRole("button", { name: "Start capture" }).hasAttribute("disabled")).toBe(false);
  });

  it("offers a startup retry when the first service snapshot is unavailable", async () => {
    const user = userEvent.setup();
    stateReadError = new Error("The desktop service did not start.");
    renderRoute("/");
    expect(await screen.findByText("The desktop service did not start.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Start capture" })).toBeNull();

    stateReadError = null;
    state = {
      ...state,
      runtime: { ...state.runtime, status: { ...state.runtime.status, phase: "ready" } },
    };
    await user.click(screen.getByRole("button", { name: "Try again" }));
    await screen.findByRole("button", { name: "Start capture" });
    expect(invokeMock).toHaveBeenCalledWith("desktop_request", { method: "retry_runtime", params: {} });
    expect(invokeMock).toHaveBeenCalledWith("desktop_request", { method: "get_state", params: {} });
  });

  it("keeps settled runtime state free of background polling", async () => {
    const setIntervalSpy = vi.spyOn(window, "setInterval");
    renderRoute("/");
    await screen.findByRole("button", { name: "Start capture" });

    expect(setIntervalSpy).not.toHaveBeenCalledWith(expect.any(Function), 900);
  });

  it("uses the service region mode and explains when its saved rectangle is missing", async () => {
    state = {
      ...state,
      app: { ...state.app, capture_mode: "region" },
      config: { ...state.config, capture_mode: "region" },
    };
    renderRoute("/");
    expect(await screen.findByText("the display under the cursor · no region saved, reading the whole monitor")).toBeTruthy();
  });

  it("replaces stale UI state after a service failure and reconnect", async () => {
    const user = userEvent.setup();
    renderRoute("/");
    await screen.findByRole("button", { name: "Start capture" });
    await waitFor(() => expect(eventHandlers.has("desktop-service-status")).toBe(true));
    eventHandlers.get("desktop-service-status")?.({
      payload: { state: "failed", code: "WORKER_EXITED", message: "The desktop service stopped." },
    });
    expect(await screen.findByText("The desktop service stopped.")).toBeTruthy();

    state = { ...state, config: { ...state.config, theme: "dark" } };
    await user.click(screen.getByRole("button", { name: "Reconnect" }));
    await waitFor(() => expect(screen.queryByText("The desktop service stopped.")).toBeNull());
    await user.click(screen.getByRole("button", { name: "Appearance" }));
    expect(screen.getByRole("button", { name: "Dark" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("preserves navigation focus through a snapshot update and shows current engine state", async () => {
    const user = userEvent.setup();
    renderRoute("/");
    await screen.findByRole("button", { name: "Start capture" });
    const logsTab = screen.getByRole("button", { name: "Logs" });
    await user.click(logsTab);
    logsTab.focus();

    state = {
      ...state,
      runtime: {
        ...state.runtime,
        ocr_provider: "Apple Vision",
        engine: { state: "ready", message: "Providers loaded." },
      },
    };
    await waitFor(() => expect(eventHandlers.has("desktop-state")).toBe(true));
    await act(async () => eventHandlers.get("desktop-state")?.({ payload: state }));

    expect(document.activeElement).toBe(logsTab);
    expect(screen.getByText("loaded")).toBeTruthy();
    expect(screen.getByText("Apple Vision")).toBeTruthy();
  });

  it("renders the service's ISO diagnostics timestamp", async () => {
    const user = userEvent.setup();
    renderRoute("/");
    await screen.findByRole("button", { name: "Start capture" });
    await user.click(screen.getByRole("button", { name: "Logs" }));
    await screen.findByText("Desktop service started.");
    expect(screen.queryByText("Invalid Date")).toBeNull();
    expect(screen.getByText(new Date("2026-10-13T03:00:00+00:00").toLocaleTimeString())).toBeTruthy();
  });

  it("selects the popup route and renders only dictionary events delivered by Tauri", async () => {
    renderRoute("/popup");
    await waitFor(() => expect(invokeMock).toHaveBeenCalledWith("desktop_request", {
      method: "frontend_ready",
      params: { view: "popup" },
    }));
    expect(screen.queryByRole("heading", { name: "학교" })).toBeNull();

    await waitFor(() => expect(eventHandlers.has("desktop-popup")).toBe(true));
    eventHandlers.get("desktop-popup")?.({
      payload: {
        type: "popup",
        sequence: 1,
        payload: { status: "success", entry: { headword: "학교", senses: [{ gloss: "school" }] } },
      },
    });

    expect(await screen.findByRole("heading", { name: "학교" })).toBeTruthy();
    expect(screen.getByText("school")).toBeTruthy();
  });

  it("keeps the popup context menu for a selection only", async () => {
    renderRoute("/popup");
    await waitFor(() => expect(eventHandlers.has("desktop-popup")).toBe(true));
    eventHandlers.get("desktop-popup")?.({
      payload: {
        type: "popup",
        sequence: 1,
        payload: { status: "success", entry: { headword: "학교", senses: [{ gloss: "school" }] } },
      },
    });
    const gloss = await screen.findByText("school");

    window.getSelection()?.removeAllRanges();
    expect(fireEvent.contextMenu(gloss)).toBe(false);

    const range = document.createRange();
    range.selectNodeContents(gloss);
    window.getSelection()?.addRange(range);
    expect(fireEvent.contextMenu(gloss)).toBe(true);
    window.getSelection()?.removeAllRanges();
  });

  it.each([
    ["/popup", "desktop-popup", "popup"],
    ["/region-selector", "desktop-region", "region_selector"],
  ] as const)("waits for the %s event listener before marking its window ready", async (path, eventName, view) => {
    deferListen.value = true;
    renderRoute(path);

    await waitFor(() => expect(deferredListeners.has(eventName)).toBe(true));
    expect(invokeMock).not.toHaveBeenCalledWith("desktop_request", {
      method: "frontend_ready",
      params: { view },
    });

    await act(async () => deferredListeners.get(eventName)?.());
    await waitFor(() => expect(invokeMock).toHaveBeenCalledWith("desktop_request", {
      method: "frontend_ready",
      params: { view },
    }));
  });

  it("routes region selection cancellation through the native command", async () => {
    const user = userEvent.setup();
    renderRoute("/region-selector");

    expect(await screen.findByLabelText("Select a screen region")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(invokeMock).toHaveBeenCalledWith("desktop_request", { method: "cancel_region", params: {} });
  });

  it("lets a user cancel the capture-scope dialog without changing settings", async () => {
    const user = userEvent.setup();
    renderRoute("/");
    await screen.findByRole("button", { name: "Start capture" });
    await user.click(screen.getAllByRole("button", { name: "Select area" })[0]!);
    expect(screen.getByRole("dialog", { name: "Where should Hanly read?" })).toBeTruthy();
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("dialog", { name: "Where should Hanly read?" })).toBeNull();
    expect(invokeMock).not.toHaveBeenCalledWith("desktop_request", { method: "select_region", params: {} });
    expect(invokeMock).not.toHaveBeenCalledWith("desktop_request", { method: "set_capture_mode", params: { mode: "full_monitor" } });
  });

  it("submits logical selector coordinates with the overlay scale metadata", async () => {
    renderRoute("/region-selector");
    await waitFor(() => expect(eventHandlers.has("desktop-region")).toBe(true));
    eventHandlers.get("desktop-region")?.({
      payload: {
        bounds: { left: -1920, top: 0, width: 3840, height: 1080 },
        monitors: [
          { index: 0, name: "Primary", bounds: { left: 0, top: 0, width: 1920, height: 1080 } },
          { index: 1, name: "Secondary", bounds: { left: -1920, top: 0, width: 1920, height: 1080 } },
        ],
      },
    });
    expect(await screen.findByText("Drag across 2 displays · Esc or right-click to cancel")).toBeTruthy();

    const overlay = screen.getByLabelText("Select a screen region");
    fireEvent.pointerDown(overlay, { button: 0, pointerId: 1, clientX: 10, clientY: 20 });
    fireEvent.pointerMove(overlay, { pointerId: 1, clientX: 110, clientY: 80 });
    fireEvent.pointerUp(overlay, { pointerId: 1, clientX: 110, clientY: 80 });

    await waitFor(() => expect(invokeMock).toHaveBeenCalledWith("desktop_request", {
      method: "confirm_region",
      params: {
        region: { left: 10, top: 20, width: 100, height: 60 },
        coordinate_space: "overlay_logical",
        scale_factor: 2,
      },
    }));
  });

  it("keeps target mode and region selection as separate acknowledged actions", async () => {
    const user = userEvent.setup();
    renderRoute("/");

    await screen.findByRole("button", { name: "Start capture" });
    await user.click(screen.getByRole("radio", { name: /Selected region/ }));
    await waitFor(() => expect(invokeMock).toHaveBeenCalledWith("desktop_request", {
      method: "set_capture_mode",
      params: { mode: "region" },
    }));
    expect(screen.getByRole("heading", { name: "Region" })).toBeTruthy();

    await user.click(screen.getAllByRole("button", { name: "Select area" })[0]!);
    expect(screen.getByRole("dialog", { name: "Where should Hanly read?" })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Select an area" }));
    await waitFor(() => expect(invokeMock).toHaveBeenCalledWith("desktop_request", {
      method: "select_region",
      params: {},
    }));
  });

  it("validates and persists the hover delay through its native service action", async () => {
    const user = userEvent.setup();
    renderRoute("/");
    await screen.findByRole("button", { name: "Start capture" });

    const delay = screen.getByRole("textbox", { name: "Hover delay value in milliseconds" });
    await user.clear(delay);
    await user.type(delay, "250");
    await user.keyboard("{Enter}");

    await waitFor(() => expect(invokeMock).toHaveBeenCalledWith("desktop_request", {
      method: "set_hover_delay",
      params: { delay_ms: 250 },
    }));
    expect((delay as HTMLInputElement).value).toBe("250");
  });

  it("persists lookup preload and recognizer selections from the capture page", async () => {
    const user = userEvent.setup();
    renderRoute("/");
    await screen.findByRole("button", { name: "Start capture" });

    await user.selectOptions(screen.getByRole("combobox", { name: "Lookup engine" }), "on_demand");
    await waitFor(() => expect(invokeMock).toHaveBeenCalledWith("desktop_request", {
      method: "update_settings",
      params: { changes: { lookup_preload: "on_demand" } },
    }));
    await user.selectOptions(screen.getByRole("combobox", { name: "Text recognizer" }), "easyocr");
    await waitFor(() => expect(invokeMock).toHaveBeenCalledWith("desktop_request", {
      method: "update_settings",
      params: { changes: { ocr_backend: "easyocr" } },
    }));
  });

  it("rejects a delay outside the service-provided range without saving it", async () => {
    const user = userEvent.setup();
    renderRoute("/");
    await screen.findByRole("button", { name: "Start capture" });

    const delay = screen.getByRole("textbox", { name: "Hover delay value in milliseconds" });
    await user.clear(delay);
    await user.type(delay, "19");
    await user.tab();

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(invokeMock).not.toHaveBeenCalledWith("desktop_request", expect.objectContaining({ method: "set_hover_delay" }));
    expect((delay as HTMLInputElement).value).toBe("80");
  });

  it("keeps an in-progress delay edit through a redundant state snapshot", async () => {
    const user = userEvent.setup();
    state = {
      ...state,
      app: { ...state.app, activity: "preparing" },
      runtime: { ...state.runtime, status: { ...state.runtime.status, phase: "preparing" } },
    };
    renderRoute("/");
    await screen.findByRole("button", { name: "Start capture" });
    const delay = screen.getByRole("textbox", { name: "Hover delay value in milliseconds" });
    await user.clear(delay);
    await user.type(delay, "480");
    await waitFor(() => expect(eventHandlers.has("desktop-state")).toBe(true));
    await act(async () => eventHandlers.get("desktop-state")?.({ payload: { ...state, config: { ...state.config } } }));

    expect((delay as HTMLInputElement).value).toBe("480");
    expect(invokeMock).not.toHaveBeenCalledWith("desktop_request", expect.objectContaining({ method: "set_hover_delay" }));
  });

  it("captures only valid modified shortcut combinations and keeps Escape as cancel", async () => {
    const user = userEvent.setup();
    renderRoute("/");
    await screen.findByRole("button", { name: "Start capture" });
    await user.click(screen.getByRole("button", { name: "Shortcuts" }));
    const shortcut = screen.getByText("Push to Hover").closest("section");
    expect(shortcut).toBeTruthy();
    await user.click(within(shortcut as HTMLElement).getByRole("button", { name: "Assign" }));

    fireEvent.keyDown(window, { key: "Shift", shiftKey: true });
    expect(invokeMock).not.toHaveBeenCalledWith("desktop_request", expect.objectContaining({ method: "set_hotkey" }));
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByText(/Press keys/)).toBeNull();

    await user.click(within(shortcut as HTMLElement).getByRole("button", { name: "Assign" }));
    fireEvent.keyDown(window, { key: "k", ctrlKey: true, shiftKey: true });
    await waitFor(() => expect(invokeMock).toHaveBeenCalledWith("desktop_request", {
      method: "set_hotkey",
      params: { hotkey: "ctrl+shift+k" },
    }));
  });

  it("warns when a registered shortcut is an ordinary application shortcut", async () => {
    const user = userEvent.setup();
    state = {
      ...state,
      config: { ...state.config, capture_hotkey: "ctrl+r", hover_hotkey: "ctrl+shift+p" },
      runtime: {
        ...state.runtime,
        hotkeys: { toggle_capture: "ctrl+r", toggle_hover: "ctrl+shift+p" },
      },
    };
    renderRoute("/");
    await screen.findByRole("button", { name: "Start capture" });
    await user.click(screen.getByRole("button", { name: "Shortcuts" }));

    const capture = screen.getByText("Start / stop capture").closest("section") as HTMLElement;
    expect(within(capture).getByText("Used by other apps.")).toBeTruthy();
    const pause = screen.getByText("Pause automatic hover").closest("section") as HTMLElement;
    expect(within(pause).queryByText("Used by other apps.")).toBeNull();
  });

  it("saves pause and capture shortcut bindings as settings", async () => {
    const user = userEvent.setup();
    renderRoute("/");
    await screen.findByRole("button", { name: "Start capture" });
    await user.click(screen.getByRole("button", { name: "Shortcuts" }));

    const pause = screen.getByText("Pause automatic hover").closest("section") as HTMLElement;
    await user.click(within(pause).getByRole("button", { name: "Assign" }));
    fireEvent.keyDown(window, { key: "p", ctrlKey: true, shiftKey: true });
    await waitFor(() => expect(invokeMock).toHaveBeenCalledWith("desktop_request", {
      method: "update_settings",
      params: { changes: { hover_hotkey: "ctrl+shift+p" } },
    }));

    const capture = screen.getByText("Start / stop capture").closest("section") as HTMLElement;
    await user.click(within(capture).getByRole("button", { name: "Assign" }));
    fireEvent.keyDown(window, { key: "f", ctrlKey: true, shiftKey: true });
    await waitFor(() => expect(invokeMock).toHaveBeenCalledWith("desktop_request", {
      method: "update_settings",
      params: { changes: { capture_hotkey: "ctrl+shift+f" } },
    }));

    await user.click(screen.getByRole("radio", { name: /Whenever capture is running/ }));
    await waitFor(() => expect(invokeMock).toHaveBeenCalledWith("desktop_request", {
      method: "update_settings",
      params: { changes: { hover_activation: "always_active" } },
    }));
  });

  it("shows onboarding guidance and refreshes acknowledged permission grants", async () => {
    const user = userEvent.setup();
    state = {
      ...state,
      permissions: {
        supported: true,
        items: [{
          id: "screen_recording",
          label: "Screen Recording",
          state: "denied",
          granted: false,
          requirement: "Read text from the screen.",
          restart_note: "Restart Hanly after changing this permission.",
        }],
      },
    };
    renderRoute("/");
    await screen.findByRole("button", { name: "Start capture" });
    await user.click(screen.getByRole("button", { name: "Permissions" }));

    expect(screen.getByText("Before Hanly can read")).toBeTruthy();
    expect(screen.getByText(/switch Hanly on there/)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Grant access" }));

    await waitFor(() => expect(invokeMock).toHaveBeenCalledWith("desktop_request", {
      method: "grant_permission",
      params: { permission: "screen_recording" },
    }));
    expect(await screen.findByText("granted")).toBeTruthy();
  });

  it("rechecks permissions when focus returns from operating-system settings", async () => {
    const user = userEvent.setup();
    state = {
      ...state,
      permissions: {
        supported: true,
        items: [{ id: "screen_recording", label: "Screen Recording", state: "denied", granted: false, requirement: "Read screen text.", restart_note: "Restart Hanly." }],
      },
    };
    renderRoute("/");
    await screen.findByRole("button", { name: "Start capture" });
    await user.click(screen.getByRole("button", { name: "Permissions" }));
    fireEvent.focus(window);

    await waitFor(() => expect(invokeMock).toHaveBeenCalledWith("desktop_request", { method: "refresh_permissions", params: {} }));
  });

  it("explains when the current platform does not expose permission actions", async () => {
    const user = userEvent.setup();
    renderRoute("/");
    await screen.findByRole("button", { name: "Start capture" });
    await user.click(screen.getByRole("button", { name: "Permissions" }));

    expect(screen.getByText("This platform does not require a separate permission check.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Recheck" }).hasAttribute("disabled")).toBe(true);
    expect(screen.queryByRole("button", { name: "Grant access" })).toBeNull();
  });

  it("confirms full application downloads, shows progress, and expands resource activity", async () => {
    const user = userEvent.setup();
    state = {
      ...state,
      runtime: {
        ...state.runtime,
        resources: [{ id: "krdict", kind: "dictionary", status: "ready", version: "2026.1", compatible: true }],
      },
      updates: {
        available: true,
        status: "awaiting_confirmation",
        message: "A full download is required.",
        awaiting_confirmation: true,
        cancellable: false,
        activity: [{ at: 1_791_842_400, message: "Full download requested." }],
      },
    };
    renderRoute("/");
    await screen.findByRole("button", { name: "Start capture" });
    await user.click(screen.getByRole("button", { name: "Updates" }));
    await user.click(screen.getByRole("button", { name: "Download full update" }));

    await waitFor(() => expect(invokeMock).toHaveBeenCalledWith("desktop_request", {
      method: "install_application_update",
      params: { confirm_full: true },
    }));
    expect(screen.getByRole("progressbar", { name: "Update progress" })).toBeTruthy();
    expect(screen.getByText("50%", { selector: ".update-percent" })).toBeTruthy();

    await user.click(screen.getByRole("button", { name: /Dictionary and resources/ }));
    expect(screen.getByText("krdict")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: /Update activity/ }));
    expect(screen.getByText("Full download requested.")).toBeTruthy();
  });

  it("cancels a pending full-download confirmation without starting an install", async () => {
    const user = userEvent.setup();
    state = {
      ...state,
      updates: { available: true, status: "awaiting_confirmation", message: "A full download is required.", awaiting_confirmation: true, cancellable: false },
    };
    renderRoute("/");
    await screen.findByRole("button", { name: "Start capture" });
    await user.click(screen.getByRole("button", { name: "Updates" }));
    await user.click(screen.getByRole("button", { name: "Not now" }));

    await waitFor(() => expect(invokeMock).toHaveBeenCalledWith("desktop_request", { method: "cancel_update", params: {} }));
    expect(invokeMock).not.toHaveBeenCalledWith("desktop_request", expect.objectContaining({ method: "install_application_update" }));
  });

  it("offers cancellation while an update is downloading", async () => {
    const user = userEvent.setup();
    state = {
      ...state,
      updates: {
        available: true,
        status: "downloading",
        message: "Downloading application files.",
        cancellable: true,
        progress: { phase: "downloading", completed: 25, total: 100, fraction: 0.25 },
      },
    };
    renderRoute("/");
    await screen.findByRole("button", { name: "Start capture" });
    await user.click(screen.getByRole("button", { name: "Updates" }));
    expect(screen.getByRole("progressbar", { name: "Update progress" })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(invokeMock).toHaveBeenCalledWith("desktop_request", { method: "cancel_update", params: {} }));
  });

  it("keeps the install active at full transfer progress until the service advances its phase", async () => {
    const user = userEvent.setup();
    state = {
      ...state,
      updates: {
        available: true,
        status: "downloading",
        message: "Download complete; validating files.",
        cancellable: true,
        progress: { phase: "downloading", completed: 100, total: 100, fraction: 1 },
      },
    };
    renderRoute("/");
    await screen.findByRole("button", { name: "Start capture" });
    await user.click(screen.getByRole("button", { name: "Updates" }));

    expect(screen.getByRole("progressbar", { name: "Update progress" }).getAttribute("aria-valuenow")).toBe("100");
    expect(screen.getByText("Download complete; validating files.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeTruthy();
  });

  it("updates transfer progress in place and keeps reduced-motion rules", async () => {
    state = {
      ...state,
      updates: {
        available: true,
        status: "downloading",
        message: "Downloading application files.",
        cancellable: true,
        progress: { phase: "downloading", completed: 10, total: 100, fraction: 0.1 },
      },
    };
    renderRoute("/");
    await waitFor(() => expect(eventHandlers.has("desktop-state")).toBe(true));
    await act(async () => eventHandlers.get("desktop-state")?.({ payload: state }));
    fireEvent.click(screen.getByRole("button", { name: "Updates" }));

    const progress = screen.getByRole("progressbar", { name: "Update progress" });
    const stageLabel = screen.getByText("Downloading application files.");
    const fill = progress.querySelector(".track-fill");
    expect(fill?.getAttribute("style")).toContain("10%");

    const next = {
      ...state,
      updates: {
        ...state.updates,
        progress: { phase: "downloading", completed: 40, total: 100, fraction: 0.4 },
      },
    };
    state = next;
    await act(async () => eventHandlers.get("desktop-state")?.({ payload: next }));

    await waitFor(() => expect(progress.getAttribute("aria-valuenow")).toBe("40"));
    expect(screen.getByText("Downloading application files.")).toBe(stageLabel);
    expect(screen.getByRole("progressbar", { name: "Update progress" })).toBe(progress);
    expect(fill?.getAttribute("style")).toContain("40%");

    const css = await readFile(`${process.cwd()}/src/styles/controlCenter.css`, "utf8");
    expect(css).toMatch(/\.track-fill\s*\{[^}]*transition:\s*width\s+var\(--motion-normal\)\s+linear/s);
    expect(css).toMatch(/@media\s*\(prefers-reduced-motion:\s*reduce\)[\s\S]*?animation-duration:\s*\.01ms\s*!important;[\s\S]*?transition-duration:\s*\.01ms\s*!important;/);
  });

  it("copies, clears, and exports only through the desktop diagnostics commands", async () => {
    const user = userEvent.setup();
    renderRoute("/");
    await screen.findByRole("button", { name: "Start capture" });
    await user.click(screen.getByRole("button", { name: "Logs" }));
    await screen.findByText("Desktop service started.");

    await user.click(screen.getByRole("button", { name: "Copy visible" }));
    await waitFor(() => expect(invokeMock).toHaveBeenCalledWith("desktop_request", {
      method: "copy_text",
      params: { text: "2026-10-13T03:00:00+00:00\tinfo\tService\tDesktop service started." },
    }));
    expect(await screen.findByText("Copied 1 visible record.")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "Export diagnostics" }));
    expect(await screen.findByText("Saved 1 records to /tmp/hanly-report.json")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Clear" }));
    await waitFor(() => expect(invokeMock).toHaveBeenCalledWith("desktop_request", { method: "clear_logs", params: {} }));
    expect(await screen.findByText("No records match.")).toBeTruthy();
  });

  it("filters logs by level, subsystem, and search before copying visible records", async () => {
    const user = userEvent.setup();
    logSnapshot = {
      records: [
        { timestamp: "2026-10-13T03:00:00+00:00", level: "info", subsystem: "Service", message: "Desktop service started." },
        { timestamp: "2026-10-13T03:01:00+00:00", level: "warning", subsystem: "Capture", message: "Permission is missing." },
        { timestamp: "2026-10-13T03:02:00+00:00", level: "error", subsystem: "Lookup", message: "Lookup engine crashed." },
      ],
      levels: ["info", "warning", "error"],
      subsystems: ["Capture", "Lookup", "Service"],
      log_path: null,
    };
    renderRoute("/");
    await screen.findByRole("button", { name: "Start capture" });
    await user.click(screen.getByRole("button", { name: "Logs" }));
    await screen.findByText("Lookup engine crashed.");

    await user.click(screen.getByRole("button", { name: "Error" }));
    expect(screen.getByText("Lookup engine crashed.")).toBeTruthy();
    expect(screen.queryByText("Permission is missing.")).toBeNull();
    await user.selectOptions(screen.getByRole("combobox", { name: "Filter by subsystem" }), "Lookup");
    await user.type(screen.getByRole("textbox", { name: "Search logs" }), "crashed");
    await user.click(screen.getByRole("button", { name: "Copy visible" }));

    await waitFor(() => expect(invokeMock).toHaveBeenCalledWith("desktop_request", {
      method: "copy_text",
      params: { text: "2026-10-13T03:02:00+00:00\terror\tLookup\tLookup engine crashed." },
    }));
    expect(await screen.findByText("Copied 1 visible record.")).toBeTruthy();
  });

  it("renders diagnostic messages as text rather than interpreting markup", async () => {
    const unsafeMessage = "<img src=x onerror=alert(1)>";
    logSnapshot = {
      records: [{ timestamp: "2026-10-13T03:00:00+00:00", level: "error", subsystem: "Service", message: unsafeMessage }],
      levels: ["error"],
      subsystems: ["Service"],
      log_path: null,
    };
    const router = createMemoryRouter(appRoutes, { initialEntries: ["/"] });
    const { container } = render(<RouterProvider router={router} />);
    await screen.findByRole("button", { name: "Start capture" });
    await userEvent.setup().click(screen.getByRole("button", { name: "Logs" }));

    expect(await screen.findByText(unsafeMessage)).toBeTruthy();
    expect(container.querySelector("img")).toBeNull();
  });

  it("names a dictionary-listed grammar pattern beside the word", async () => {
    renderRoute("/popup");
    await waitFor(() => expect(eventHandlers.has("desktop-popup")).toBe(true));
    eventHandlers.get("desktop-popup")?.({
      payload: {
        type: "popup",
        sequence: 9,
        payload: {
          status: "success",
          entry: { headword: "먹다", senses: [{ gloss: "eat" }] },
          construction: { headword: "-고 있다", gloss: "be doing" },
        },
      },
    });

    expect(await screen.findByText("Grammar pattern")).toBeTruthy();
    expect(screen.getByText("-고 있다")).toBeTruthy();
    expect(screen.getByText("be doing")).toBeTruthy();
  });

  it("reports a press on the popup so the native host can hand activation back", async () => {
    renderRoute("/popup");
    await waitFor(() => expect(eventHandlers.has("desktop-popup")).toBe(true));
    fireEvent.mouseDown(window);

    await waitFor(() => expect(invokeMock).toHaveBeenCalledWith("desktop_request", {
      method: "popup_pressed", params: {},
    }));
  });

  it("caps the card to the room the native host reports beside the word", async () => {
    const rectangle = vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({
      x: 0, y: 0, top: 0, left: 0, right: 340, bottom: 520,
      width: 340, height: 520, toJSON: () => ({}),
    });
    const fallback = invokeMock.getMockImplementation();
    invokeMock.mockImplementation(async (command: string, args?: { method?: string }) =>
      command === "desktop_request" && args?.method === "popup_geometry"
        ? { sequence: 7, room: 300 }
        : fallback?.(command, args),
    );
    renderRoute("/popup");
    await waitFor(() => expect(eventHandlers.has("desktop-popup")).toBe(true));
    eventHandlers.get("desktop-popup")?.({
      payload: {
        type: "popup",
        sequence: 7,
        payload: { status: "success", entry: { headword: "학교", senses: [{ gloss: "school" }] } },
      },
    });

    const card = await screen.findByRole("main", { name: "Hanly dictionary result" });
    await waitFor(() => expect(card.style.maxHeight).toBe("300px"));
    rectangle.mockRestore();
  });

  it("ignores stale popup events and reports measured geometry for the current entry", async () => {
    // Hidden WKWebView animation callbacks may never run until it is shown.
    const animationFrame = vi.spyOn(window, "requestAnimationFrame").mockReturnValue(1);
    const rectangle = vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({
      x: 0, y: 0, top: 0, left: 0, right: 340.25, bottom: 218.5,
      width: 340.25, height: 218.5, toJSON: () => ({}),
    });
    renderRoute("/popup");
    await waitFor(() => expect(eventHandlers.has("desktop-popup")).toBe(true));
    const emit = (sequence: number, headword: string, expanded = false) => eventHandlers.get("desktop-popup")?.({
      payload: {
        type: "popup",
        sequence,
        payload: {
          status: "success",
          entry: { headword, senses: [{ gloss: "school" }, { gloss: "academy" }, { gloss: "institution" }] },
          analysis: [{ text: "학", role: "noun" }],
          other_entries: [{ headword: "學校", part_of_speech: "noun", senses: [{ gloss: "school" }] }],
          expanded,
          technical_details: "full",
          technical_lines: ["source: test"],
        },
      },
    });
    emit(5, "학교");
    emit(4, "stale");

    expect(await screen.findByRole("heading", { name: "학교" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "stale" })).toBeNull();
    await waitFor(() => expect(invokeMock).toHaveBeenCalledWith("desktop_request", expect.objectContaining({ method: "popup_geometry" })));
    expect(invokeMock).toHaveBeenCalledWith("desktop_request", {
      method: "popup_geometry", params: { sequence: 5, width: 341, height: 219 },
    });
    await userEvent.setup().click(screen.getByRole("button", { name: "Expand" }));
    expect(invokeMock).toHaveBeenCalledWith("desktop_request", expect.objectContaining({ method: "popup_expand", params: { sequence: 5, expanded: true } }));
    expect(screen.queryByText("institution")).toBeNull();
    emit(6, "학교", true);
    expect(await screen.findByText("institution")).toBeTruthy();
    expect(screen.getByText("學校 · noun · school")).toBeTruthy();
    animationFrame.mockRestore();
    rectangle.mockRestore();
  });
});
