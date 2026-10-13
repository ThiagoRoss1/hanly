export interface CaptureRegion {
  left: number;
  top: number;
  width: number;
  height: number;
}

export interface CaptureTarget {
  index: number;
  name: string;
  bounds: CaptureRegion;
}

export interface RuntimeResource {
  id: string;
  kind?: string;
  status?: string;
  version?: string | null;
  compatible?: boolean;
  diagnostics?: string[];
}

export interface PermissionItem {
  id: string;
  label: string;
  state: string;
  granted: boolean;
  requirement: string;
  restart_note?: string;
}

export interface HanlyState {
  app: {
    state: string;
    activity: string;
    detail: string;
    capture_running: boolean;
    capture_mode: string;
    target: string;
    region: CaptureRegion | null;
    targets: CaptureTarget[];
  };
  config: {
    capture_hotkey: string;
    capture_mode: string;
    capture_monitor: number | null;
    capture_region: CaptureRegion | null;
    hotkey: string;
    hover_activation: string;
    hover_delay_ms: number;
    hover_hotkey: string;
    lookup_preload: string;
    ocr_backend: string;
    popup_enabled: boolean;
    popup_default_size: string;
    technical_details: string;
    theme: string;
    update_checks_enabled: boolean;
  };
  runtime: {
    ocr_provider: string | null;
    ocr_backends: string[];
    app_version: string | null;
    hover_delay_bounds: { min: number; max: number };
    resources: RuntimeResource[];
    status: { phase: string; stage: string; message: string };
    engine: { state: string; message: string; preparing_sequence?: number };
    hotkeys: Record<string, string>;
    log_path: string | null;
    diagnostics: string[];
  };
  updates: UpdateState;
  permissions: {
    available?: boolean;
    message?: string;
    supported: boolean;
    items: PermissionItem[];
  };
}

export interface UpdatePlan {
  source?: string;
  download_bytes?: number;
  replace_count?: number;
  add_count?: number;
  delete_count?: number;
}

export interface UpdateProgress {
  phase?: string;
  completed?: number;
  total?: number;
  fraction?: number;
}

export interface UpdateApplication {
  installable?: boolean;
  current_version?: string;
  latest_version?: string;
  message?: string;
  release_url?: string;
}

export interface UpdateResource {
  id: string;
  available?: boolean;
  version?: string;
}

export interface UpdateState {
  available: boolean;
  status: string;
  message: string;
  resources?: UpdateResource[];
  progress?: UpdateProgress | null;
  application?: UpdateApplication | null;
  restart_required?: boolean;
  plan?: UpdatePlan | null;
  awaiting_confirmation?: boolean;
  cancellable?: boolean;
  activity?: Array<{ at?: number; message?: string }>;
}

export interface PopupSense {
  gloss?: string | null;
  definition?: string;
}

export interface PopupEntry {
  headword: string;
  definitions?: string[];
  part_of_speech?: string | null;
  hanja?: string | null;
  vocabulary_level?: string | null;
  senses?: PopupSense[];
}

export interface PopupAnalysisPiece {
  text: string;
  role?: string;
}

export interface PopupComponent {
  surface: string;
  lemma: string;
  gloss?: string | null;
  grammatical?: boolean;
  selected?: boolean;
}

export interface PopupContent {
  status?: string;
  title?: string;
  body?: string;
  tip?: string;
  entry?: PopupEntry | null;
  surface?: string | null;
  lemma?: string | null;
  analysis?: PopupAnalysisPiece[];
  components?: PopupComponent[];
  other_entries?: PopupEntry[];
  confidence?: number | null;
  source?: string | null;
  technical_lines?: string[];
}

export interface PopupPayload extends PopupContent {
  content?: PopupContent;
  position?: { x: number; y: number };
  size?: { width: number; height: number };
  expanded?: boolean;
  technical_details?: string;
  theme?: string;
  config?: { technical_details?: string; theme?: string; popup_default_size?: string };
}

export interface DesktopRegionEvent {
  image?: string;
  bounds: CaptureRegion;
  monitors: CaptureTarget[];
}

export type DesktopPopupEvent =
  | { type: "popup"; sequence: number; payload: PopupPayload }
  | { type: "popup_hide"; sequence: number };

export interface DesktopServiceStatus {
  state: "starting" | "ready" | "failed" | "stopped";
  code?: string;
  message?: string;
}

export interface LogRecord {
  timestamp: string;
  level: string;
  subsystem: string;
  message: string;
}

export interface LogSnapshot {
  records: LogRecord[];
  levels: string[];
  subsystems: string[];
  log_path: string | null;
}

export interface DiagnosticsExport {
  path: string;
  records: number;
}
