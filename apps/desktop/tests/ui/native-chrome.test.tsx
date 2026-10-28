import { cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NativeChrome, WindowsChrome } from "../../src/components/NativeChrome.tsx";

const { isTauriMock } = vi.hoisted(() => ({
  isTauriMock: vi.fn(),
}));

vi.mock("@tauri-apps/api/core", () => ({
  isTauri: isTauriMock,
}));

const originalPlatform = navigator.platform;
const originalUserAgent = navigator.userAgent;

function setNavigator(platform: string, userAgent: string) {
  Object.defineProperty(navigator, "platform", {
    configurable: true,
    value: platform,
  });
  Object.defineProperty(navigator, "userAgent", {
    configurable: true,
    value: userAgent,
  });
}

beforeEach(() => {
  isTauriMock.mockReturnValue(false);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  Object.defineProperty(navigator, "platform", {
    configurable: true,
    value: originalPlatform,
  });
  Object.defineProperty(navigator, "userAgent", {
    configurable: true,
    value: originalUserAgent,
  });
});

describe("WindowsChrome", () => {
  it("keeps the existing child UI and adds no custom title bar", () => {
    const { container, getByText } = render(
      <WindowsChrome>
        <main className="app skin-village">Control Center</main>
      </WindowsChrome>,
    );

    expect(getByText("Control Center")).toBeTruthy();
    expect(container.querySelector(".app.skin-village")).not.toBeNull();
    expect(container.querySelector("[aria-label='Window controls']")).toBeNull();
    expect(container.querySelector("[data-tauri-drag-region]")).toBeNull();
  });
});

describe("NativeChrome platform selection", () => {
  it("uses only the transparent clipped wrapper for a Tauri Windows client", () => {
    isTauriMock.mockReturnValue(true);
    setNavigator("Win32", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)");

    const { container, getByText } = render(
      <NativeChrome>
        <main className="app skin-village">Control Center</main>
      </NativeChrome>,
    );

    expect(getByText("Control Center")).toBeTruthy();
    expect(container.querySelector(".native-windows-chrome > .app.skin-village")).not.toBeNull();
    expect(container.querySelector(".native-mac-chrome")).toBeNull();
    expect(container.querySelector("[aria-label='Window controls']")).toBeNull();
  });

  it("keeps the macOS overlay branch intact", () => {
    isTauriMock.mockReturnValue(true);
    setNavigator("MacIntel", "Mozilla/5.0 (Macintosh; Intel Mac OS X)");

    const { container, getByText } = render(
      <NativeChrome>
        <main>Control Center</main>
      </NativeChrome>,
    );

    expect(getByText("Control Center")).toBeTruthy();
    expect(container.querySelector(".native-mac-chrome")).not.toBeNull();
    expect(container.querySelector("[data-tauri-drag-region]")).not.toBeNull();
    expect(container.querySelector(".native-windows-chrome")).toBeNull();
  });

  it("leaves Linux and browser rendering unchanged", () => {
    isTauriMock.mockReturnValue(true);
    setNavigator("Linux x86_64", "Mozilla/5.0 (X11; Linux x86_64)");
    const linux = render(
      <NativeChrome>
        <main>Linux Control Center</main>
      </NativeChrome>,
    );
    expect(linux.getByText("Linux Control Center")).toBeTruthy();
    expect(linux.container.querySelector(".native-windows-chrome")).toBeNull();
    expect(linux.container.querySelector(".native-mac-chrome")).toBeNull();
    linux.unmount();

    isTauriMock.mockReturnValue(false);
    setNavigator("Win32", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)");
    const browser = render(
      <NativeChrome>
        <main>Browser Control Center</main>
      </NativeChrome>,
    );
    expect(browser.getByText("Browser Control Center")).toBeTruthy();
    expect(browser.container.querySelector(".native-windows-chrome")).toBeNull();
    expect(browser.container.querySelector(".native-mac-chrome")).toBeNull();
  });
});
