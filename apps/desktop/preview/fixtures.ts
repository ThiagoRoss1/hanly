import type {
  HanlyState,
  LogSnapshot,
  PopupPayload,
} from "../src/contracts/desktop.ts";

/** A ready Mac profile with both grants, capture stopped. */
export function previewState(): HanlyState {
  return {
    app: {
      state: "stopped",
      activity: "stopped",
      detail: "Capture is stopped.",
      capture_running: false,
      capture_mode: "full_monitor",
      target: "cursor",
      region: null,
      targets: [
        {
          index: 1,
          name: "Built-in Retina Display",
          bounds: { left: 0, top: 0, width: 1440, height: 900 },
        },
      ],
    },
    config: {
      hover_delay_ms: 80,
      hover_activation: "always_active",
      lookup_preload: "when_capture_starts",
      ocr_backend: "auto",
      theme: "system",
      popup_font: "pixel",
      sidebar_layout: "normal",
      popup_default_size: "compact",
      technical_details: "off",
      capture_mode: "full_monitor",
      capture_monitor: null,
      capture_region: null,
      hotkey: "ctrl+cmd+h",
      hover_hotkey: "ctrl+cmd+p",
      capture_hotkey: "ctrl+cmd+r",
      popup_enabled: true,
      update_checks_enabled: true,
    },
    runtime: {
      ocr_provider: "Apple Vision",
      ocr_backends: ["auto", "vision", "easyocr"],
      app_version: "1.1.0",
      hover_delay_bounds: { min: 20, max: 2000 },
      resources: [
        { id: "krdict", kind: "dictionary", status: "installed", version: "2026.09", compatible: true },
      ],
      status: { phase: "ready", stage: "desktop service", message: "Hanly is ready." },
      engine: { state: "sleeping", message: "Lookup providers are not loaded." },
      hotkeys: {
        push_to_hover: "ctrl+cmd+h",
        toggle_hover: "ctrl+cmd+p",
        toggle_capture: "ctrl+cmd+r",
      },
      log_path: "~/Library/Logs/Hanly/hanly.log",
      diagnostics: [],
    },
    updates: { available: false, status: "idle", message: "Hanly is up to date." },
    permissions: {
      supported: true,
      items: [
        {
          id: "screen_recording",
          label: "Screen Recording",
          state: "granted",
          granted: true,
          requirement: "Reads the small area under the pointer when text is not accessible.",
        },
        {
          id: "accessibility",
          label: "Accessibility",
          state: "granted",
          granted: true,
          requirement: "Reads accessible text directly before falling back to screen capture.",
        },
      ],
    },
  };
}

export const previewLogs: LogSnapshot = {
  records: [
    { timestamp: "2026-10-15T09:00:00+00:00", level: "info", subsystem: "Service", message: "Hanly desktop service started." },
    { timestamp: "2026-10-15T09:00:04+00:00", level: "info", subsystem: "Runtime", message: "Hanly is ready." },
    { timestamp: "2026-10-15T09:02:11+00:00", level: "warning", subsystem: "Keyboard shortcuts", message: "Push to Hover was ignored because the cursor position was unavailable." },
  ],
  levels: ["info", "warning", "error"],
  subsystems: ["Service", "Runtime", "Keyboard shortcuts"],
  log_path: "~/Library/Logs/Hanly/hanly.log",
};

const school: PopupPayload["content"] = {
  status: "SUCCESS",
  surface: "학교",
  lemma: "학교",
  source: "krdict",
  entry: {
    headword: "학교",
    hanja: "學校",
    part_of_speech: "Noun",
    vocabulary_level: "Beginner",
    senses: [
      {
        gloss: "school",
        definition: "An institution where teachers educate students according to a set curriculum.",
      },
    ],
  },
  analysis: [{ text: "학교", role: "noun" }],
  technical_lines: ["Vision", "accessible text: no", "57 ms"],
};

const long: PopupPayload["content"] = {
  status: "SUCCESS",
  surface: "드렸습니다",
  lemma: "드리다",
  source: "krdict",
  entry: {
    headword: "드리다",
    part_of_speech: "Verb",
    vocabulary_level: "Intermediate",
    senses: [
      { gloss: "give; offer", definition: "To give something to a person of higher status; the honorific form of 주다." },
      { gloss: "do for", definition: "Used after a verb to indicate doing something for a superior." },
      { gloss: "offer a prayer", definition: "To present a prayer, a bow, or a greeting to a god or an elder." },
      { gloss: "hold a ceremony", definition: "To perform a ritual or a ceremony in a formal manner." },
    ],
  },
  analysis: [
    { text: "드리", role: "verb stem" },
    { text: "었", role: "past" },
    { text: "습니다", role: "formal polite ending" },
  ],
  components: [
    { surface: "드리", lemma: "드리다", gloss: "give (honorific)", selected: true },
    { surface: "었", lemma: "었", grammatical: true },
    { surface: "습니다", lemma: "습니다", grammatical: true },
  ],
  other_entries: [
    { headword: "드리다", part_of_speech: "Verb", senses: [{ gloss: "hang down; dangle" }] },
    { headword: "들이다", part_of_speech: "Verb", senses: [{ gloss: "let in; bring in" }] },
  ],
  technical_lines: ["Vision", "accessible text: yes", "135 ms"],
};

const refusal: PopupPayload["content"] = {
  status: "NOT_FOUND",
  surface: "갸뷁",
  title: "No dictionary entry",
  body: "Hanly read this text but found no matching Korean dictionary entry.",
  tip: "Move the pointer onto a single word and hold it still.",
};

export const popupSamples = { school, long, refusal } as const;
export type PopupSample = keyof typeof popupSamples;

export function popupPayload(
  sample: PopupSample,
  expanded: boolean,
  replacement: boolean,
  theme: string,
): PopupPayload {
  return {
    content: popupSamples[sample],
    position: { x: 100, y: 120 },
    band: { top: 94, bottom: 120 },
    size: expanded ? { width: 460, height: 420 } : { width: 340, height: 180 },
    expanded,
    replacement,
    technical_details: "basic",
    theme,
  };
}
