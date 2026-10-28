import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { isAbsolute } from "node:path";
import { PopupPage } from "../../src/pages/PopupPage.tsx";
import type { PopupContent, PopupPayload } from "../../src/contracts/desktop.ts";

const { invokeMock, eventHandlers } = vi.hoisted(() => ({
  invokeMock: vi.fn(),
  eventHandlers: new Map<
    string,
    (event: { payload: unknown }) => void
  >(),
}));

const campaignResultsPath = process.env.HANLY_LAB_POPUP_CONTENT_RESULTS;

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
  payload: PopupPayload,
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
    expect(document.documentElement.dataset.popupFont).toBe("normal");
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

describe.skipIf(!campaignResultsPath)("real popup-content campaign payloads", () => {
  it("renders observed presentation data from the language campaign", async () => {
    if (!campaignResultsPath || !isAbsolute(campaignResultsPath)) {
      throw new Error("HANLY_LAB_POPUP_CONTENT_RESULTS must be an absolute path.");
    }

    const rows = JSON.parse(readFileSync(campaignResultsPath, "utf8")) as Array<{
      id: string;
      popup_content: PopupContent;
    }>;
    const selectedIds = ["PC-001", "PC-102", "PC-104", "PC-107", "PC-002", "PC-003b"];
    const selectedRows = selectedIds.map((id) => {
      const row = rows.find((candidate) => candidate.id === id);
      if (!row?.popup_content) throw new Error(`Missing serialized popup content for ${id}.`);
      return row;
    });

    for (const [index, row] of selectedRows.entries()) {
      const content = row.popup_content;
      render(<PopupPage />);
      await waitFor(() => expect(eventHandlers.has("desktop-popup")).toBe(true));
      emitPopup(index + 10, { ...content, expanded: true });

      await screen.findByRole("heading", { name: content.entry?.headword ?? "" });
      const partOfSpeech = content.entry?.part_of_speech;
      const englishPartOfSpeech: Record<string, string> = {
        "명사": "Noun",
        "동사": "Verb",
      };
      expect(partOfSpeech).toBeTruthy();
      expect(screen.getByText(partOfSpeech!)).toBeTruthy();
      expect(screen.getByText(englishPartOfSpeech[partOfSpeech!] ?? "")).toBeTruthy();

      expect(screen.getByText("Read as")).toBeTruthy();
      const analysisText = (content.analysis ?? [])
        .map((piece) => piece.text)
        .join("  +  ");
      const analysisRoles = (content.analysis ?? [])
        .map((piece) => piece.role)
        .filter(Boolean);
      expect(screen.getByText(analysisText.replaceAll(/\s+/g, " "))).toBeTruthy();
      expect(analysisRoles.join(" · ")).toBeTruthy();
      expect(screen.getByText(analysisRoles.join(" · "))).toBeTruthy();
      expect(analysisRoles).not.toContain("XSV");
      expect(analysisRoles).not.toContain("VX");

      if ((content.components ?? []).length > 0) {
        expect(screen.getByText("How this form is built")).toBeTruthy();
        for (const component of content.components ?? []) {
          expect(screen.getAllByText(component.surface).length).toBeGreaterThan(0);
          const label = component.gloss ?? (
            component.grammatical ? "grammatical" : "no dictionary entry"
          );
          expect(screen.getAllByText(label).length).toBeGreaterThan(0);
        }
      }

      if (content.construction) {
        expect(screen.getByText("Grammar pattern")).toBeTruthy();
        expect(screen.getByText(content.construction.headword)).toBeTruthy();
        const gloss = content.construction.gloss ?? content.construction.definition;
        if (gloss) expect(screen.getByText(gloss)).toBeTruthy();
      }

      cleanup();
      eventHandlers.clear();
    }
  });
});
