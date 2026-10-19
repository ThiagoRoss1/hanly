import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PopupPage } from "../../src/pages/PopupPage.tsx";

const { invokeMock, eventHandlers } = vi.hoisted(() => ({
  invokeMock: vi.fn(),
  eventHandlers: new Map<
    string,
    (event: { payload: unknown }) => void
  >(),
}));

vi.mock("@tauri-apps/api/core", () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
}));

vi.mock("@tauri-apps/api/event", () => ({
  listen: (
    name: string,
    callback: (event: { payload: unknown }) => void,
  ) => {
    eventHandlers.set(name, callback);
    return Promise.resolve(() => eventHandlers.delete(name));
  },
}));

function popupPayload() {
  return {
    status: "success",
    entry: {
      headword: "학교",
      hanja: "學校",
      part_of_speech: "명사",
      vocabulary_level: "초급",
      senses: [
        {
          gloss: "school",
          definition: "An institution where students learn.",
        },
        {
          gloss: "academy",
          definition: "A place where a subject is taught.",
        },
        {
          gloss: "institution",
          definition: "A public organization.",
        },
      ],
    },
    surface: "학교에",
    lemma: "학교",
    analysis: [
      { text: "학교", role: "noun" },
      { text: "에", role: "particle" },
    ],
    source: "krdict",
    components: [
      { surface: "학교", lemma: "학교", gloss: "school", selected: true },
      { surface: "에", lemma: "에", gloss: "at", grammatical: true },
    ],
    construction: { headword: "-에", gloss: "at; in" },
    other_entries: [
      {
        headword: "學校",
        part_of_speech: "명사",
        senses: [{ gloss: "school" }],
      },
    ],
    technical_details: "full",
    technical_lines: ["KRDICT entry 42"],
  };
}

function emitPopup(
  sequence: number,
  payload: ReturnType<typeof popupPayload> & Record<string, unknown>,
) {
  const handler = eventHandlers.get("desktop-popup");
  if (!handler) throw new Error("The popup event listener is not ready.");

  act(() => {
    handler({ payload: { type: "popup", sequence, payload } });
  });
}

beforeEach(() => {
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
  invokeMock.mockImplementation(
    async (_command: string, args?: { method?: string }) => {
      if (args?.method === "popup_measure") return { room: 560 };
      return {};
    },
  );
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  eventHandlers.clear();
  delete document.documentElement.dataset.popup;
  delete document.documentElement.dataset.popupFont;
});

describe("PopupPage", () => {
  it("shows the classic compact result and expands all dictionary information", async () => {
    const user = userEvent.setup();
    render(<PopupPage />);

    await waitFor(() => expect(eventHandlers.has("desktop-popup")).toBe(true));
    emitPopup(1, popupPayload());

    const card = await screen.findByRole("main", {
      name: "Hanly dictionary result",
    });
    expect(card.style.width).toBe("380px");
    expect(await screen.findByRole("heading", { name: "학교" })).toBeTruthy();
    expect(screen.getByText("學校")).toBeTruthy();
    expect(screen.getByText("명사")).toBeTruthy();
    expect(screen.getByText("Noun")).toBeTruthy();
    expect(screen.getByText("school")).toBeTruthy();
    expect(screen.getByText("An institution where students learn.")).toBeTruthy();
    expect(screen.getByText("academy")).toBeTruthy();
    expect(screen.getByText("A place where a subject is taught.")).toBeTruthy();
    expect(screen.queryByText("institution")).toBeNull();
    expect(screen.queryByText("Read as")).toBeNull();

    const details = screen.getByRole("button", { name: "Details" });
    await user.click(details);
    expect(screen.queryByText("institution")).toBeNull();
    emitPopup(2, { ...popupPayload(), expanded: true });

    expect(
      await screen.findByRole("button", { name: "Less detail" }),
    ).toBeTruthy();
    expect(screen.getByText("institution")).toBeTruthy();
    expect(screen.getByText("Read as")).toBeTruthy();
    expect(screen.getByText("KRDICT")).toBeTruthy();
    expect(screen.getByText(/학교에/)).toBeTruthy();
    expect(screen.getByText(/학교\s+\+\s+에/)).toBeTruthy();
    expect(screen.getByText("noun · particle")).toBeTruthy();
    expect(screen.getByText("How this form is built")).toBeTruthy();
    expect(screen.getByText("-에")).toBeTruthy();
    expect(screen.getByText("Grammar pattern")).toBeTruthy();
    expect(screen.getByText("Other entries")).toBeTruthy();
    expect(screen.getByText("Vocabulary level: 초급")).toBeTruthy();
    expect(screen.getByText("KRDICT entry 42")).toBeTruthy();
    expect(invokeMock).toHaveBeenCalledWith(
      "desktop_request",
      expect.objectContaining({
        method: "popup_expand",
        params: { sequence: 1, expanded: true },
      }),
    );

    const methods = invokeMock.mock.calls
      .map(([, args]) => (args as { method?: string }).method)
      .filter(Boolean);
    expect(methods.indexOf("popup_measure")).toBeLessThan(
      methods.indexOf("popup_geometry"),
    );
  });

  it("uses the saved typeface and remeasures after fonts load and a font change", async () => {
    let resolveFonts: () => void = () => undefined;
    const fontsReady = new Promise<void>((resolve) => {
      resolveFonts = resolve;
    });
    Object.defineProperty(document, "fonts", {
      configurable: true,
      value: { ready: fontsReady },
    });

    render(<PopupPage />);
    await waitFor(() => expect(eventHandlers.has("desktop-popup")).toBe(true));
    emitPopup(2, {
      ...popupPayload(),
      config: { popup_font: "pixel" },
    });

    await screen.findByRole("heading", { name: "학교" });
    await waitFor(() => {
      expect(
        invokeMock.mock.calls.some(
          ([, args]) => (args as { method?: string }).method === "popup_geometry",
        ),
      ).toBe(true);
    });
    expect(document.documentElement.dataset.popupFont).toBe("pixel");

    const geometryCountBeforeFonts = invokeMock.mock.calls.filter(
      ([, args]) => (args as { method?: string }).method === "popup_geometry",
    ).length;
    await act(async () => {
      resolveFonts();
      await fontsReady;
    });
    await waitFor(() => {
      const geometryCount = invokeMock.mock.calls.filter(
        ([, args]) => (args as { method?: string }).method === "popup_geometry",
      ).length;
      expect(geometryCount).toBeGreaterThan(geometryCountBeforeFonts);
    });

    const geometryCountBeforeChange = invokeMock.mock.calls.filter(
      ([, args]) => (args as { method?: string }).method === "popup_geometry",
    ).length;
    emitPopup(2, {
      ...popupPayload(),
      config: { popup_font: "normal" },
    });

    await waitFor(() =>
      expect(document.documentElement.dataset.popupFont).toBe("normal"),
    );
    await waitFor(() => {
      const geometryCount = invokeMock.mock.calls.filter(
        ([, args]) => (args as { method?: string }).method === "popup_geometry",
      ).length;
      expect(geometryCount).toBeGreaterThan(geometryCountBeforeChange);
    });
  });

  it("closes through the native popup command", async () => {
    render(<PopupPage />);
    await waitFor(() => expect(eventHandlers.has("desktop-popup")).toBe(true));
    emitPopup(3, popupPayload());

    await screen.findByRole("heading", { name: "학교" });
    fireEvent.click(screen.getByRole("button", { name: "Close dictionary" }));

    await waitFor(() =>
      expect(invokeMock).toHaveBeenCalledWith(
        "desktop_request",
        expect.objectContaining({
          method: "popup_close",
          params: { sequence: 3 },
        }),
      ),
    );
  });
});
