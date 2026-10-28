import type {
  PopupContent,
  PopupEntry,
  PopupPayload,
} from "../../contracts/desktop.ts";

export const POPUP_MAX_HEIGHT = 560;
export const COMPACT_POPUP_WIDTH = 380;
export const EXPANDED_POPUP_WIDTH = 460;

export type PopupFont = "pixel" | "normal";

export function popupContent(payload: PopupPayload): PopupContent {
  return payload.content ?? payload;
}

export function initiallyExpanded(payload: PopupPayload): boolean {
  if (typeof payload.expanded === "boolean") return payload.expanded;
  return payload.config?.popup_default_size === "expanded";
}

export function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

export function numberValue(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) && value > 0
    ? value
    : fallback;
}

export function maximumPopupWidth(): number {
  const available = window.screen.availWidth;
  return available > 0 ? Math.max(280, available - 16) : EXPANDED_POPUP_WIDTH;
}

export function popupFont(payload: PopupPayload | undefined): PopupFont {
  if (!payload) return "normal";

  const withFont = payload as PopupPayload & {
    popup_font?: unknown;
    config?: PopupPayload["config"] & { popup_font?: unknown };
  };
  const configured = withFont.config?.popup_font ?? withFont.popup_font;

  return configured === "pixel" ? "pixel" : "normal";
}

export function entryGloss(entry: PopupEntry): string {
  const sense = entry.senses?.find((item) => item.gloss || item.definition);
  return text(sense?.gloss || sense?.definition || entry.definitions?.[0]);
}

export function wordTypes(raw?: string | null): [string, string] {
  const pairs: Array<[string, string]> = [
    ["명사", "Noun"],
    ["대명사", "Pronoun"],
    ["동사", "Verb"],
    ["형용사", "Adjective"],
    ["부사", "Adverb"],
    ["관형사", "Determiner"],
    ["수사", "Numeral"],
    ["조사", "Particle"],
    ["감탄사", "Interjection"],
    ["의존 명사", "Bound noun"],
  ];
  const normalized = (raw ?? "").replaceAll(" ", "").toLowerCase();

  return (
    pairs.find((pair) =>
      pair.some((name) => name.replaceAll(" ", "").toLowerCase() === normalized),
    ) ?? [raw ?? "", ""]
  );
}
