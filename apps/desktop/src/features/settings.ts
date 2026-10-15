export interface NumericBounds {
  min: number;
  max: number;
}

export type HoverDelayValidation =
  { valid: true; value: number } | { valid: false; message: string };

export function validateHoverDelay(
  raw: string,
  bounds: NumericBounds,
): HoverDelayValidation {
  const value = Number(raw);
  if (!Number.isInteger(value) || value < bounds.min || value > bounds.max) {
    return {
      valid: false,
      message: `Hover delay must be between ${bounds.min} and ${bounds.max} ms.`,
    };
  }
  return { valid: true, value };
}

export function formatHotkey(
  binding: string | undefined,
  platform = typeof navigator === "undefined" ? "" : navigator.platform,
): string[] {
  const mac = /mac/i.test(platform);
  const symbols: Record<string, string> = {
    ctrl: "⌃", control: "⌃", cmd: "⌘", meta: "⌘", super: "⌘",
    alt: "⌥", option: "⌥", shift: "⇧", space: "Space",
  };
  return (binding ?? "")
    .split("+")
    .map((part) => part.replace(/^<|>$/g, "").trim())
    .filter(Boolean)
    .map((part) => mac ? (symbols[part.toLowerCase()] ?? part.toUpperCase()) : part);
}

const MODIFIER_KEYS = new Set(["control", "shift", "alt", "meta", "os"]);
const KEY_NAMES: Record<string, string> = {
  " ": "space",
  arrowup: "up",
  arrowdown: "down",
  arrowleft: "left",
  arrowright: "right",
  pageup: "pageup",
  pagedown: "pagedown",
};

export function hotkeyFromKeyboardEvent(
  event: Pick<
    KeyboardEvent,
    "key" | "ctrlKey" | "shiftKey" | "altKey" | "metaKey"
  >,
): string | null {
  const key = event.key.toLowerCase();
  if (MODIFIER_KEYS.has(key)) return null;

  const parts: string[] = [];
  if (event.ctrlKey) parts.push("ctrl");
  if (event.shiftKey) parts.push("shift");
  if (event.altKey) parts.push("alt");
  if (event.metaKey) parts.push("cmd");
  parts.push(KEY_NAMES[key] ?? key);
  return parts.join("+");
}
