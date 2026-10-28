import type {
  HanlyState,
  LogSnapshot,
  PopupPayload,
  UpdateState,
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
      app_font: "pixel",
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

/** Return the native-looking Windows profile used by the local browser preview. */
export function previewWindowsState(): HanlyState {
  const state = previewState();
  const hotkeys = {
    push_to_hover: "ctrl+alt+h",
    toggle_hover: "ctrl+alt+p",
    toggle_capture: "ctrl+alt+r",
  };

  return {
    ...state,
    app: {
      ...state.app,
      target: "monitor:2",
      targets: [
        {
          index: 1,
          name: "Built-in Display",
          bounds: { left: 0, top: 0, width: 1920, height: 1080 },
        },
        {
          index: 2,
          name: "External Display",
          bounds: { left: 1920, top: 0, width: 2560, height: 1440 },
        },
      ],
    },
    config: {
      ...state.config,
      capture_monitor: 2,
      ocr_backend: "auto",
      hotkey: hotkeys.push_to_hover,
      hover_hotkey: hotkeys.toggle_hover,
      capture_hotkey: hotkeys.toggle_capture,
    },
    runtime: {
      ...state.runtime,
      ocr_provider: "EasyOCR",
      ocr_backends: ["auto", "easyocr"],
      hotkeys,
      log_path: "C:\\Users\\Preview\\AppData\\Local\\Hanly\\Logs\\hanly.log",
    },
  };
}

const previewApplicationUpdate: NonNullable<UpdateState["application"]> = {
  current_version: "1.1.0",
  latest_version: "1.2.0",
  installable: true,
  message: "A smaller update is ready to install.",
};

/** Return a local update state for the browser preview without contacting a release server. */
export function previewUpdateState(stage: string): UpdateState {
  const application = { ...previewApplicationUpdate };

  if (stage === "checking") {
    return { available: false, status: "checking", message: "Checking for updates", application };
  }
  if (stage === "available") {
    return {
      available: true,
      status: "available",
      message: "A Hanly update is available.",
      application,
      plan: { source: "delta", download_bytes: 4_200_000, replace_count: 8, add_count: 2 },
    };
  }
  if (stage === "installing") {
    return {
      available: true,
      status: "installing",
      message: "Applying the verified update.",
      application,
      cancellable: true,
      progress: { phase: "installing", fraction: 0.76 },
    };
  }
  if (stage === "completed") {
    return {
      available: false,
      status: "restart",
      message: "Hanly 1.2.0 is staged. Restarting to finish the update.",
      application,
      restart_required: true,
    };
  }
  if (stage === "cancelled") {
    return {
      available: true,
      status: "cancelled",
      message: "The update was not installed. Nothing was changed.",
      application: {
        ...application,
        message: "The update was not installed. You can try again whenever you’re ready.",
      },
    };
  }
  if (stage === "downloading") {
    return {
      available: true,
      status: "downloading",
      message: "Downloading Hanly application files.",
      application,
      cancellable: true,
      progress: { phase: "downloading", fraction: 0.42, completed: 4_200_000, total: 10_000_000 },
    };
  }
  if (stage === "failed") {
    return { available: false, status: "failed", message: "The download could not finish. Try again." };
  }

  return { available: false, status: "idle", message: "Hanly is up to date." };
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
