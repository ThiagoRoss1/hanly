import { cleanup, render } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { SidebarShell } from "../../src/components/controlCenter/SidebarShell.tsx";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

it("covers overflowing sidebar controls without measuring its own painted overflow", () => {
  vi.useFakeTimers();
  vi.stubGlobal("matchMedia", vi.fn(() => ({
    matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn(),
  })));
  const observers: Array<{ callback: () => void; targets: Element[] }> = [];
  vi.stubGlobal("ResizeObserver", class {
    targets: Element[] = [];
    constructor(callback: () => void) {
      observers.push({ callback, targets: this.targets });
    }
    observe(target: Element) { this.targets.push(target); }
    disconnect() {}
  });
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
    clearRect: vi.fn(), fillRect: vi.fn(), drawImage: vi.fn(),
  } as unknown as CanvasRenderingContext2D);

  const { container } = render(
    <SidebarShell dark={false} onToggleTheme={() => undefined}>
      <button>Capture</button><button>Quit Hanly</button>
    </SidebarShell>,
  );
  const sidebar = container.querySelector("aside")!;
  const content = container.querySelector<HTMLElement>(".sidebar-content")!;
  const scene = container.querySelector<HTMLElement>(".village-scene")!;
  sidebar.style.padding = "14px 12px";
  Object.defineProperty(sidebar, "clientHeight", { value: 560 });
  Object.defineProperty(sidebar, "scrollHeight", { value: 100_000 });
  let controlsHeight = 720;
  Object.defineProperty(content, "offsetHeight", { get: () => controlsHeight });
  Object.defineProperty(scene, "clientWidth", { value: 88 });
  Object.defineProperty(scene, "clientHeight", { get: () => parseFloat(scene.style.height) });
  const observer = observers.find(({ targets }) => targets.includes(content))!;

  observer.callback();
  expect(scene.style.height).not.toBe("748px");
  vi.advanceTimersToNextFrame();
  expect(scene.style.height).toBe("748px");
  controlsHeight = 840;
  observer.callback();
  vi.advanceTimersToNextFrame();
  expect(scene.style.height).toBe("868px");
  controlsHeight = 100;
  observer.callback();
  vi.advanceTimersToNextFrame();
  expect(scene.style.height).toBe("560px");
});
