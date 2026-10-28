import type {
  HanlyState,
  UpdateState,
} from "../../contracts/desktop.ts";
import { hotkeyFromKeyboardEvent, formatHotkey, sharesAppShortcut, validateHoverDelay } from "../../features/settings.ts";

export { hotkeyFromKeyboardEvent, formatHotkey, sharesAppShortcut, validateHoverDelay };

export const HOTKEYS = [
  {
    id: "hotkey",
    action: "push_to_hover",
    name: "Push to Hover",
    hint: "Hold to read the word under the cursor.",
  },
  {
    id: "hover_hotkey",
    action: "toggle_hover",
    name: "Pause automatic hover",
    hint: "Mutes hover without stopping capture.",
  },
  {
    id: "capture_hotkey",
    action: "toggle_capture",
    name: "Start / stop capture",
    hint: "Begins and ends the capture session.",
  },
] as const;

export const UPDATE_BUSY = new Set([
  "checking",
  "preparing",
  "inspecting",
  "downloading",
  "verifying",
  "unpacking",
  "installing",
  "validating",
]);

export function settingPendingKey(setting: string): string {
  return `settings:${setting}`;
}

export function valueText(value: unknown, fallback = "—"): string {
  if (typeof value !== "string" || !value) return fallback;
  return value.replaceAll("_", " ");
}

export function titleCase(value: unknown, fallback = "Unknown"): string {
  return valueText(value, fallback).replace(/\b\w/g, (letter) =>
    letter.toUpperCase(),
  );
}

export function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function regionLabel(
  region?: { left: number; top: number; width: number; height: number } | null,
): string {
  if (!region) return "No region selected";
  return `${region.left}, ${region.top} · ${region.width} × ${region.height}`;
}

export function readinessRows(
  state: HanlyState,
): Array<{ label: string; value: string; detail: string; tone?: string }> {
  const status = state.runtime.status ?? {};
  const engine = state.runtime.engine ?? {};
  const hotkeys = state.runtime.hotkeys ?? {};
  const bound = HOTKEYS.filter((item) => Boolean(state.config[item.id]));
  const active = bound.filter((item) => Boolean(hotkeys[item.action]));
  const rows = [
    {
      label: "Runtime",
      value: titleCase(status.phase),
      detail: status.message || titleCase(status.stage, ""),
      tone:
        status.phase === "ready"
          ? "ok"
          : status.phase === "failed"
            ? "bad"
            : "warn",
    },
    {
      label: "Lookup engine",
      value:
        engine.state === "ready"
          ? "loaded"
          : engine.state === "sleeping"
            ? "sleeping"
            : titleCase(engine.state),
      detail: engine.message ?? "",
      tone: engine.state === "error" ? "bad" : "",
    },
    {
      label: "OCR",
      value: state.runtime.ocr_provider ?? "not reported",
      detail: "",
      tone: "",
    },
    {
      label: "Shortcuts",
      value: `${active.length} / ${HOTKEYS.length}`,
      detail: bound.length === HOTKEYS.length ? "" : "one action is unassigned",
      tone: active.length === HOTKEYS.length ? "ok" : "warn",
    },
  ];
  for (const resource of state.runtime.resources ?? []) {
    rows.push({
      label: resource.id,
      value: resource.version
        ? `v${resource.version}`
        : titleCase(resource.status),
      detail: [
        resource.kind,
        resource.compatible ? "compatible" : "review needed",
        ...(resource.diagnostics ?? []),
      ]
        .filter(Boolean)
        .join(" · "),
      tone: resource.compatible ? "ok" : "warn",
    });
  }
  const permissions = state.permissions.items ?? [];
  if (state.permissions.supported) {
    const granted = permissions.filter((item) => item.granted).length;
    rows.push({
      label: "Permissions",
      value: `${granted} / ${permissions.length}`,
      detail: permissions
        .filter((item) => !item.granted)
        .map((item) => item.label)
        .join(", "),
      tone: granted === permissions.length ? "ok" : "warn",
    });
  }
  return rows;
}

export function formatBytes(bytes?: number): string {
  if (typeof bytes !== "number" || bytes <= 0) return "";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

export function describePlan(plan: UpdateState["plan"]): string {
  if (!plan) return "";
  const kind =
    plan.source === "delta" ? "Differential update" : "Full download";
  const counts = [
    plan.replace_count && `${plan.replace_count} replaced`,
    plan.add_count && `${plan.add_count} added`,
    plan.delete_count && `${plan.delete_count} removed`,
  ]
    .filter(Boolean)
    .join(", ");
  return [kind, formatBytes(plan.download_bytes), counts]
    .filter(Boolean)
    .join(" · ");
}
