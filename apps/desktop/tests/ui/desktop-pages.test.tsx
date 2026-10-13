import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { HanlyState } from "../../src/contracts/desktop.ts";
import { appRoutes } from "../../src/app/router.tsx";

const { invokeMock, eventHandlers } = vi.hoisted(() => ({
  invokeMock: vi.fn(),
  eventHandlers: new Map<string, (event: { payload: unknown }) => void>(),
}));

vi.mock("@tauri-apps/api/core", () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
}));

vi.mock("@tauri-apps/api/event", () => ({
  listen: async (name: string, callback: (event: { payload: unknown }) => void) => {
    eventHandlers.set(name, callback);
    return () => eventHandlers.delete(name);
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
    },
    updates: { available: false, status: "unavailable", message: "Updates are not connected." },
    permissions: { supported: false, items: [] },
  };
}

let state: HanlyState;

function renderRoute(path: string) {
  const router = createMemoryRouter(appRoutes, { initialEntries: [path] });
  render(<RouterProvider router={router} />);
  return router;
}

beforeEach(() => {
  state = createState();
  eventHandlers.clear();
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  });
  invokeMock.mockImplementation(async (command: string, args: { method?: string; params?: Record<string, unknown> }) => {
    if (command !== "desktop_request") throw new Error(`Unexpected Tauri command ${command}`);
    const method = args.method;
    const params = args.params ?? {};
    if (method === "frontend_ready") return {};
    if (method === "get_state") return state;
    if (method === "update_settings") {
      state = { ...state, config: { ...state.config, ...(params.changes as Record<string, unknown>) } };
      return state;
    }
    if (method === "get_logs") return {
      records: [{timestamp: "2026-10-13T03:00:00+00:00", level: "info", subsystem: "Service", message: "Desktop service started."}],
      levels: ["info", "warning", "error"], subsystems: ["Service"], log_path: null,
    };
    throw { code: "unavailable", message: "Capture area selection is not ready in this build." };
  });
});

afterEach(() => {
  cleanup();
});

describe("desktop React routes", () => {
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

  it("shows native unavailability instead of pretending capture started", async () => {
    const user = userEvent.setup();
    renderRoute("/");

    const start = await screen.findByRole("button", { name: "Start capture" });
    await user.click(start);

    expect((await screen.findByRole("alert")).textContent).toContain("Capture area selection is not ready in this build.");
    expect(invokeMock).toHaveBeenCalledWith("desktop_request", { method: "start_capture", params: {} });
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

  it("routes region selection and exposes a refused native action", async () => {
    const user = userEvent.setup();
    renderRoute("/region-selector");

    expect(await screen.findByLabelText("Select a screen region")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(await screen.findByText("Capture area selection is not ready in this build.")).toBeTruthy();
    expect(invokeMock).toHaveBeenCalledWith("desktop_request", { method: "cancel_region", params: {} });
  });
});
