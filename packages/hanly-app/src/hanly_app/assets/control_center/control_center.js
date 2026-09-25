(function () {
  "use strict";

  // What the page shows before the bridge has answered once. Every field is a
  // placeholder the renderers can read, never a claim about the runtime.
  const fallbackState = {
    app: {
      state: "new", activity: "preparing", detail: "", capture_running: false,
      capture_mode: "full_monitor", target: "cursor", region: null, targets: []
    },
    config: {
      hover_delay_ms: 80, hotkey: "", hover_hotkey: "", capture_hotkey: "",
      hover_activation: "push_to_hover", lookup_preload: "when_capture_starts", ocr_backend: "auto",
      theme: "system", popup_default_size: "compact", technical_details: "off"
    },
    runtime: {
      ocr_provider: "", resources: [], diagnostics: [], log_path: null,
      status: { phase: "idle", stage: "", message: "" },
      engine: { state: "sleeping", message: "" },
      hotkeys: {}, app_version: null,
      hover_delay_bounds: { min: 20, max: 2000 }
    },
    updates: {
      available: false, status: "unavailable", message: "", resources: [],
      active_resource_id: null, progress: null, application: null,
      restart_required: false, plan: null, awaiting_confirmation: false,
      cancellable: false, activity: [], outcome: null
    },
    permissions: { supported: false, items: [] }
  };

  // How often the page asks for a new snapshot while something asynchronous is
  // still running.
  const REFRESH_INTERVAL_MS = 500;

  // Runtime phases still expected to change without the user doing anything.
  const RUNTIME_PENDING_PHASES = ["preparing", "stopping"];

  // Hanly's own derived activity, computed by the shell from readiness,
  // provider residency, and whether capture was actually asked for.
  const ACTIVITY_LABELS = {
    preparing: "Preparing", stopped: "Stopped", armed: "Armed",
    running: "Running", stopping: "Stopping", error: "Error"
  };

  const ACTIVITY_PENDING = ["preparing", "stopping"];

  const UPDATE_BUSY_STATUSES = [
    "checking", "preparing", "inspecting", "downloading", "verifying",
    "unpacking", "installing", "validating"
  ];

  // The engine is where the memory is, and it may sleep while Hanly is ready:
  // a lookup loads it. Saying so is the difference between "not working" and
  // "not loaded yet".
  const ENGINE_LABELS = {
    sleeping: "sleeping", preparing: "loading", ready: "loaded", error: "error"
  };

  // How many refreshes to spend watching for a permission the user went off to
  // grant. Privacy settings change outside this window and nothing tells the
  // page, so it watches for a while and then stops rather than polling the
  // system for the rest of the session.
  const PERMISSION_WATCH_TICKS = 60;

  const NAV = [
    { id: "capture", label: "Capture", kicker: "Capture", title: "읽을 준비",
      desc: "Choose where Hanly reads." },
    { id: "permissions", label: "Permissions", kicker: "Permissions", title: "접근 권한",
      desc: "The grants Hanly needs before it can read." },
    { id: "shortcuts", label: "Shortcuts", kicker: "Shortcuts", title: "단축키",
      desc: "What your keyboard does, and what the system accepted." },
    { id: "appearance", label: "Appearance", kicker: "Appearance", title: "겉모습",
      desc: "How the Control Center and the popup look." },
    { id: "updates", label: "Updates", kicker: "Updates", title: "업데이트",
      desc: "The app and its resources update separately." },
    { id: "logs", label: "Logs", kicker: "Logs", title: "기록",
      desc: "Runtime state and recent activity." }
  ];

  const NAV_SLOT = 38;
  const NAV_GAP = 2;

  // Three actions, and the key each is registered under by the desktop
  // listener. Stored intent and registered reality are separate columns.
  const SHORTCUTS = [
    { id: "hotkey", action: "push_to_hover", name: "Push to Hover",
      hint: "Hold to read the word under the cursor." },
    { id: "hover_hotkey", action: "toggle_hover", name: "Pause automatic hover",
      hint: "Mutes hover without stopping capture." },
    { id: "capture_hotkey", action: "toggle_capture", name: "Start / stop capture",
      hint: "Begins and ends the capture session." }
  ];

  // The two activation modes, said in the words the model actually means.
  // "Deactivated" would claim hover is off, which always_active is not.
  const HOVER_MODES = [
    { id: "push_to_hover", label: "Only while held",
      desc: "Hover reads while the Push to Hover shortcut is held down, and nothing is watched when the keys are up." },
    { id: "always_active", label: "Whenever capture is running",
      desc: "Hover reads for the whole capture session, subject to the permissions hover needs." }
  ];

  const PRELOAD_HELP = {
    when_capture_starts: "Loaded while watching the screen, retired on pause.",
    always: "Loaded at launch and kept loaded, including through pause.",
    on_demand: "Nothing is loaded until a lookup needs it."
  };

  const OCR_LABELS = {
    auto: "Automatic (recommended)",
    vision: "Apple Vision",
    easyocr: "EasyOCR"
  };

  const OCR_HELP = {
    auto: "Picks the best recognizer this machine has.",
    vision: "Built into macOS. Reads Korean verb endings most accurately.",
    easyocr: "Bundled model. Works everywhere, less accurate on conjugations."
  };

  const THEMES = [
    { id: "light", label: "Light" },
    { id: "dark", label: "Dark" },
    { id: "system", label: "System" }
  ];

  const POPUP_SIZES = [
    { id: "compact", label: "Compact" },
    { id: "expanded", label: "Expanded" }
  ];

  const TECHNICAL_DETAILS = [
    { id: "off", label: "Off" },
    { id: "basic", label: "Basic" },
    { id: "full", label: "Full" }
  ];

  const LOG_LEVELS = [
    { id: "all", label: "All" },
    { id: "info", label: "Info" },
    { id: "warning", label: "Warnings" },
    { id: "error", label: "Errors" }
  ];

  // Browser key names that are not the spelling Hanly's canonicalizer knows.
  const KEY_NAMES = {
    " ": "space", arrowup: "up", arrowdown: "down", arrowleft: "left",
    arrowright: "right", pageup: "pageup", pagedown: "pagedown"
  };

  const MODIFIER_KEYS = ["control", "shift", "alt", "meta", "os"];

  // ---- state -------------------------------------------------------------
  // The bridge snapshot is the product state. What lives here is only what the
  // backend has no opinion about: which page is open, which disclosure is
  // expanded, and the half-typed values a control is holding before Apply.

  let currentState = fallbackState;
  let logState = { records: [], levels: [], subsystems: [], log_path: null };
  let page = "capture";
  let anim = "a";
  let refreshTimer = null;
  let navMoveTimer = null;
  let permissionWatchTicks = 0;
  let connection = "connecting";
  let quitAsking = false;
  let recording = null;
  let regionDirty = false;
  let delayEditing = false;
  let readinessLoading = true;
  let logFilters = { level: "all", subsystem: "all", search: "" };
  let thinkTick = "a";
  let thinkText = "";
  let darkMedia = null;

  // pywebview injects its api after the document is parsed, so the bridge is
  // resolved per call. Capturing it here would pin it to null forever.
  function bridge() {
    return window.pywebview && window.pywebview.api ? window.pywebview.api : null;
  }

  // ---- dom helpers -------------------------------------------------------

  function byId(id) { return document.getElementById(id); }

  function setText(id, value) {
    const node = byId(id);
    if (node) node.textContent = value === null || value === undefined ? "" : String(value);
  }

  function setHidden(id, hidden) {
    const node = byId(id);
    if (node) node.hidden = !!hidden;
  }

  function clear(node) {
    if (node) node.innerHTML = "";
  }

  // Every dynamic string reaches the page through here. A log line, an error,
  // or a release message can hold anything a provider or the operating system
  // put in it, and none of it is markup.
  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function attr(node, name, value) {
    if (value === null || value === undefined) node.removeAttribute(name);
    else node.setAttribute(name, String(value));
    return node;
  }

  // ---- combobox ----------------------------------------------------------

  // One accessible choice list for every <select>. The native select stays in
  // the document as the value the rest of the page reads, writes, and listens
  // to; this only replaces what the user sees and touches. Setting the value
  // or rebuilding the options through the select keeps the two in step.
  function combobox(select) {
    if (!select || typeof select.insertAdjacentElement !== "function") return;
    if (select.dataset.combobox) return;
    select.dataset.combobox = "1";
    comboCount += 1;
    const listId = "combo-list-" + comboCount;

    const root = el("div", "combo");
    if (select.id) root.id = select.id + "-combo";
    const button = el("button", "combo-button");
    button.type = "button";
    attr(button, "role", "combobox");
    attr(button, "aria-haspopup", "listbox");
    attr(button, "aria-expanded", "false");
    attr(button, "aria-controls", listId);
    ["aria-labelledby", "aria-label"].forEach(function (name) {
      const value = select.getAttribute(name);
      if (value) attr(button, name, value);
    });
    const label = el("span", "combo-label");
    button.appendChild(label);
    button.insertAdjacentHTML("beforeend",
      '<svg class="combo-chevron" viewBox="0 0 10 10" aria-hidden="true">' +
      '<path d="M2 3.5 5 6.5 8 3.5" fill="none" stroke="currentColor" ' +
      'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>');
    const list = el("ul", "combo-list");
    list.id = listId;
    attr(list, "role", "listbox");
    attr(list, "tabindex", "-1");

    select.insertAdjacentElement("beforebegin", root);
    root.appendChild(button);
    root.appendChild(list);
    root.appendChild(select);
    select.classList.add("combo-native");
    attr(select, "tabindex", "-1");
    attr(select, "aria-hidden", "true");

    let active = -1;

    function options() { return Array.prototype.slice.call(select.options); }
    function isOpen() { return root.hasAttribute("data-open"); }

    function sync() {
      const chosen = select.options[select.selectedIndex];
      label.textContent = chosen ? chosen.textContent : "";
      button.disabled = !!select.disabled;
      clear(list);
      options().forEach(function (option, index) {
        const item = el("li", "combo-option", option.textContent);
        item.id = listId + "-" + index;
        attr(item, "role", "option");
        attr(item, "aria-selected", index === select.selectedIndex ? "true" : "false");
        if (option.disabled) attr(item, "aria-disabled", "true");
        if (index === active) item.setAttribute("data-active", "");
        item.addEventListener("mousemove", function () { highlight(index); });
        item.addEventListener("click", function () { choose(index); });
        list.appendChild(item);
      });
    }

    function highlight(index) {
      active = index;
      Array.prototype.forEach.call(list.children, function (item, position) {
        if (position === index) item.setAttribute("data-active", "");
        else item.removeAttribute("data-active");
      });
      const current = list.children[index];
      attr(button, "aria-activedescendant", current ? current.id : null);
      if (current && typeof current.scrollIntoView === "function") {
        current.scrollIntoView({ block: "nearest" });
      }
    }

    function step(from, delta) {
      const all = options();
      for (let index = from + delta; index >= 0 && index < all.length; index += delta) {
        if (!all[index].disabled) return index;
      }
      return from;
    }

    function open() {
      if (select.disabled || isOpen()) return;
      closeOtherCombos(root);
      const rect = root.getBoundingClientRect();
      const below = window.innerHeight - rect.bottom;
      attr(root, "data-placement", below < 180 && rect.top > below ? "top" : null);
      root.setAttribute("data-open", "");
      attr(button, "aria-expanded", "true");
      highlight(select.selectedIndex >= 0 ? select.selectedIndex : step(-1, 1));
    }

    function close() {
      if (!isOpen()) return;
      root.removeAttribute("data-open");
      attr(button, "aria-expanded", "false");
      attr(button, "aria-activedescendant", null);
      active = -1;
    }

    function choose(index) {
      const option = select.options[index];
      if (!option || option.disabled) return;
      close();
      button.focus();
      if (select.selectedIndex === index) return;
      select.selectedIndex = index;
      sync();
      select.dispatchEvent(new Event("change", { bubbles: true }));
    }

    button.addEventListener("click", function () { if (isOpen()) close(); else open(); });
    button.addEventListener("keydown", function (event) {
      const key = event.key;
      if (!isOpen()) {
        if (key === "ArrowDown" || key === "ArrowUp" || key === "Enter" || key === " ") {
          event.preventDefault();
          open();
        }
        return;
      }
      if (key === "ArrowDown") { event.preventDefault(); highlight(step(active, 1)); }
      else if (key === "ArrowUp") { event.preventDefault(); highlight(step(active, -1)); }
      else if (key === "Home") { event.preventDefault(); highlight(step(-1, 1)); }
      else if (key === "End") { event.preventDefault(); highlight(step(select.options.length, -1)); }
      else if (key === "Enter" || key === " ") { event.preventDefault(); choose(active); }
      else if (key === "Escape") { event.preventDefault(); close(); }
      else if (key === "Tab") { close(); }
    });
    root.combobox = { close: close };

    // The page writes the value and rebuilds the options through the select;
    // both have to reach what is shown.
    const descriptor = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value");
    Object.defineProperty(select, "value", {
      configurable: true,
      get: function () { return descriptor.get.call(select); },
      set: function (value) { descriptor.set.call(select, value); sync(); }
    });
    new MutationObserver(sync).observe(select, {
      childList: true, subtree: true, characterData: true, attributes: true,
      attributeFilter: ["disabled"]
    });
    sync();
  }

  let comboCount = 0;

  function closeOtherCombos(keep) {
    Array.prototype.forEach.call(document.querySelectorAll(".combo[data-open]"), function (node) {
      if (node !== keep && node.combobox) node.combobox.close();
    });
  }

  function enhanceSelects() {
    if (typeof document.querySelectorAll !== "function") return;
    Array.prototype.forEach.call(document.querySelectorAll("select.select"), combobox);
    // Outside the open list, a press closes it without choosing anything.
    document.addEventListener("pointerdown", function (event) {
      const inside = closest(event.target, function (node) {
        return node.classList && node.classList.contains("combo");
      });
      closeOtherCombos(inside);
    });
  }

  function formatStatus(value) {
    return String(value || "unknown").replace(/_/g, " ");
  }

  // Sizes are shown the way a download manager shows them, always in the same
  // unit family, so 900 MB and 1.2 GB never appear as 900 and 1.2.
  function formatBytes(value) {
    if (typeof value !== "number" || !isFinite(value) || value < 0) return "";
    if (value >= 1e9) return (value / 1e9).toFixed(1) + " GB";
    if (value >= 1e6) return (value / 1e6).toFixed(1) + " MB";
    if (value >= 1e3) return Math.round(value / 1e3) + " kB";
    return value + " B";
  }

  function localTime(timestamp) {
    const parsed = new Date(timestamp);
    return isNaN(parsed.getTime()) ? String(timestamp || "") : parsed.toLocaleTimeString();
  }

  // ---- theme -------------------------------------------------------------

  function systemMode() {
    if (!window.matchMedia) return "light";
    if (!darkMedia) darkMedia = window.matchMedia("(prefers-color-scheme: dark)");
    return darkMedia.matches ? "dark" : "light";
  }

  // "system" is a stored preference, not a rendered mode: it is resolved here
  // and the preference itself is never rewritten.
  function applyTheme(theme) {
    const mode = theme === "dark" || theme === "light" ? theme : systemMode();
    const root = document.documentElement;
    if (root) root.setAttribute("data-mode", mode);
    // The native title bar follows the page where the window can colour it.
    const api = bridge();
    if (mode !== frameMode && api && typeof api.frame_theme === "function") {
      frameMode = mode;
      api.frame_theme(mode);
    }
  }

  let frameMode = null;

  function watchSystemTheme() {
    if (!window.matchMedia) return;
    if (!darkMedia) darkMedia = window.matchMedia("(prefers-color-scheme: dark)");
    const follow = function () { applyTheme(config().theme); };
    if (typeof darkMedia.addEventListener === "function") {
      darkMedia.addEventListener("change", follow);
    } else if (typeof darkMedia.addListener === "function") {
      darkMedia.addListener(follow);
    }
  }

  // ---- snapshot accessors ------------------------------------------------

  function app() { return currentState.app || fallbackState.app; }
  function config() { return currentState.config || fallbackState.config; }
  function runtime() { return currentState.runtime || fallbackState.runtime; }
  function updates() { return currentState.updates || fallbackState.updates; }
  function permissions() { return currentState.permissions || fallbackState.permissions; }

  function permissionsSupported() { return !!permissions().supported; }

  function visibleNav() {
    return NAV.filter(function (item) {
      return item.id !== "permissions" || permissionsSupported();
    });
  }

  // ---- navigation --------------------------------------------------------

  function renderNav() {
    const nav = byId("nav");
    const bubble = byId("nav-bubble");
    if (!nav) return;
    const items = visibleNav();
    // A platform that stops reporting permissions must not leave the page on a
    // section that no longer exists.
    if (!items.some(function (item) { return item.id === page; })) page = "capture";

    Array.prototype.slice.call(nav.children).forEach(function (child) {
      if (child !== bubble) nav.removeChild(child);
    });

    items.forEach(function (item) {
      const button = el("button", "nav-item");
      button.type = "button";
      button.dataset.page = item.id;
      if (item.id === page) attr(button, "aria-current", "page");
      button.appendChild(el("span", "nav-dot"));
      button.appendChild(el("span", "nav-label", item.label));
      nav.appendChild(button);
    });

    const index = Math.max(0, items.findIndex(function (item) { return item.id === page; }));
    if (bubble) {
      bubble.style.transform = "translate3d(0," + (index * (NAV_SLOT + NAV_GAP)) + "px,0)";
    }
  }

  function renderPageChrome() {
    const item = visibleNav().filter(function (entry) { return entry.id === page; })[0] || NAV[0];
    setText("page-kicker", item.kicker);
    setText("page-title", item.title);
    setText("page-desc", item.desc);
    setHidden("capture-actions", page !== "capture");
    NAV.forEach(function (entry) { setHidden("page-" + entry.id, entry.id !== page); });
  }

  function goToPage(next) {
    if (next === page) return;
    page = next;
    anim = anim === "a" ? "b" : "a";
    const intro = byId("page-intro");
    const body = byId("page-body");
    if (intro) intro.dataset.anim = anim;
    if (body) body.dataset.anim = anim;
    const bubble = byId("nav-bubble");
    if (bubble) {
      bubble.dataset.moving = "true";
      window.clearTimeout(navMoveTimer);
      navMoveTimer = window.setTimeout(function () { bubble.dataset.moving = "false"; },
        NAV_SLOT * 8);
    }
    // Readiness is read from the snapshot the page already has, so opening the
    // section reveals it rather than simulating a load.
    if (next === "logs") loadLogs();
    renderState(currentState);
  }

  // ---- capture -----------------------------------------------------------

  function targetLabel() {
    const monitor = app().target;
    if (!monitor || monitor === "cursor") return "the display under the cursor";
    const entry = (app().targets || []).filter(function (item) {
      return "monitor:" + item.index === monitor;
    })[0];
    return entry ? (entry.name || "Monitor " + entry.index) : formatStatus(monitor);
  }

  function regionText() {
    const region = app().region;
    if (!region) return "";
    return region.width + " × " + region.height + " at " + region.left + ", " + region.top;
  }

  function renderCapture() {
    const state = app();
    const running = !!state.capture_running;
    const isRegion = state.capture_mode === "region";

    const status = byId("capture-status");
    if (status) status.dataset.live = running ? "true" : "false";
    const dot = byId("capture-dot");
    if (dot) {
      dot.dataset.tone = running ? "ok" : "";
      dot.dataset.live = running ? "true" : "false";
    }
    setText("capture-headline", running ? "Reading now" : "Not reading");

    // A saved region can outlive the monitor it was drawn on. Capture then
    // falls back to the whole monitor, and the page says so rather than
    // describing an area nobody chose.
    const where = isRegion
      ? (state.region
        ? targetLabel() + " · " + regionText()
        : targetLabel() + " · no region saved, reading the whole monitor")
      : targetLabel() + " · whole screen";
    // While Hanly is still preparing or has failed, what it is doing matters
    // more than where it would read.
    const activity = state.activity || "preparing";
    setText("capture-where",
      (activity === "preparing" || activity === "error") && state.detail
        ? state.detail
        : where);

    const held = config().hover_activation === "push_to_hover";
    const chord = config().hotkey || "";
    setText("capture-hint", running
      ? (held && chord ? "hold " + chord.split("+").join(" ") : "hover active")
      : "press start to read");

    const toggle = byId("toggle-capture");
    if (toggle) {
      toggle.textContent = running ? "Stop capture" : "Start capture";
      // Starting before the runtime is ready would only be refused, so the
      // button says so instead of offering an action that cannot work.
      const ready = (runtime().status || {}).phase === "ready";
      toggle.disabled = !running && !ready;
      toggle.title = toggle.disabled ? "Hanly is still preparing its lookup runtime." : "";
    }

    attr(byId("target-monitor"), "aria-checked", isRegion ? "false" : "true");
    attr(byId("target-region"), "aria-checked", isRegion ? "true" : "false");
    const collapse = byId("region-collapse");
    if (collapse) collapse.dataset.open = isRegion ? "true" : "false";
    attr(byId("region-panel"), "aria-hidden", isRegion ? null : "true");
    setText("region-coords", regionText());

    if (!regionDirty) {
      [["region-left", "left"], ["region-top", "top"],
       ["region-width", "width"], ["region-height", "height"]].forEach(function (pair) {
        const node = byId(pair[0]);
        if (node) node.value = state.region ? String(state.region[pair[1]]) : "";
      });
    }

    renderTargets(state.targets, state.target);
    renderHoverDelay();

    const preload = byId("lookup-preload");
    if (preload) preload.value = config().lookup_preload || "when_capture_starts";
    setText("preload-help", PRELOAD_HELP[config().lookup_preload] || "");

    renderRecognizers();
  }

  // Only what this machine can run is offered: Apple Vision exists on macOS
  // alone, and Automatic names the recognizer it really resolves to.
  function renderRecognizers() {
    const select = byId("ocr-backend");
    const chosen = config().ocr_backend || "auto";
    const offered = runtime().ocr_backends || ["auto", "easyocr"];
    if (select) {
      const current = Array.prototype.map.call(select.options || [], function (o) { return o.value; });
      if (current.join() !== offered.join()) {
        clear(select);
        offered.forEach(function (id) {
          const option = el("option", null, OCR_LABELS[id] || id);
          option.value = id;
          select.appendChild(option);
        });
      }
      select.value = offered.indexOf(chosen) >= 0 ? chosen : "auto";
    }
    const resolved = runtime().ocr_provider;
    setText("ocr-help", chosen === "auto" && resolved
      ? "Uses " + resolved + " on this machine."
      : OCR_HELP[chosen] || "");
  }

  function renderTargets(targets, selected) {
    const select = byId("capture-target");
    if (!select) return;
    clear(select);
    const cursor = el("option", null, "Follow cursor");
    cursor.value = "cursor";
    select.appendChild(cursor);
    (targets || []).forEach(function (target) {
      const option = el("option", null, target.name || "Monitor " + target.index);
      option.value = "monitor:" + target.index;
      select.appendChild(option);
    });
    select.value = selected || "cursor";
  }

  function delayBounds() {
    const bounds = runtime().hover_delay_bounds || fallbackState.runtime.hover_delay_bounds;
    return {
      min: typeof bounds.min === "number" ? bounds.min : 20,
      max: typeof bounds.max === "number" ? bounds.max : 2000
    };
  }

  function renderHoverDelay() {
    const bounds = delayBounds();
    const value = config().hover_delay_ms || bounds.min;
    const slider = byId("hover-delay-slider");
    if (slider) {
      slider.min = String(bounds.min);
      slider.max = String(bounds.max);
      slider.value = String(value);
      const span = Math.max(1, bounds.max - bounds.min);
      slider.style.setProperty("--fill", (((value - bounds.min) / span) * 100).toFixed(1) + "%");
    }
    // A value being typed is the user's, not the snapshot's, until it commits.
    const input = byId("hover-delay-value");
    if (input && !delayEditing) input.value = String(value);
  }

  function slideDelay(raw) {
    const bounds = delayBounds();
    const value = Math.min(bounds.max, Math.max(bounds.min, Number(raw) || bounds.min));
    const slider = byId("hover-delay-slider");
    const input = byId("hover-delay-value");
    const span = Math.max(1, bounds.max - bounds.min);
    if (slider) slider.style.setProperty("--fill", (((value - bounds.min) / span) * 100).toFixed(1) + "%");
    if (input) input.value = String(value);
    return value;
  }

  // Python owns the bounds and the rejection. Rounding here only keeps the
  // slider and the field from disagreeing about the same number.
  function commitDelay(raw) {
    delayEditing = false;
    const parsed = parseInt(raw, 10);
    if (!isFinite(parsed)) {
      renderHoverDelay();
      return;
    }
    invoke("set_hover_delay", Math.round(parsed));
  }

  // ---- permissions -------------------------------------------------------

  function renderPermissions() {
    const state = permissions();
    const items = state.items || [];
    // Nothing left to wait for stops the watching even with time on the clock,
    // so a grant ends the polling on the very next render.
    if (!items.some(function (item) { return !item.granted; })) permissionWatchTicks = 0;

    const list = byId("permission-list");
    if (!list) return;
    clear(list);
    if (!state.supported) return;

    items.forEach(function (permission) {
      const row = el("div", "permission");
      row.dataset.rise = "1";
      row.dataset.granted = permission.granted ? "true" : "false";
      row.appendChild(attr(el("span", "dot"), "data-tone", permission.granted ? "ok" : "info"));

      const body = el("div");
      body.style.flex = "1";
      body.style.minWidth = "0";
      const head = el("div", "permission-head");
      head.appendChild(el("span", "permission-name", permission.label));
      const tag = el("span", "tag", permission.granted
        ? "granted"
        : (permission.state === "unknown" ? "unknown" : "required"));
      attr(tag, "data-tone", permission.granted ? "ok" : "");
      head.appendChild(tag);
      body.appendChild(head);
      body.appendChild(el("div", "permission-why", permission.granted
        ? permission.requirement
        : [permission.requirement, permission.restart_note].filter(Boolean).join(" ")));
      row.appendChild(body);

      if (!permission.granted) {
        const grant = el("button", "btn btn-sm btn-primary", "Open settings");
        grant.type = "button";
        grant.dataset.grant = permission.id;
        row.appendChild(grant);
      }
      list.appendChild(row);
    });

    setText("permission-note", items.length
      ? "Granted permissions stay listed so you can see what Hanly is using."
      : "");
  }

  // ---- shortcuts ---------------------------------------------------------

  function keyCaps(binding) {
    return String(binding || "").split("+")
      .map(function (part) { return part.replace(/^<|>$/g, "").trim(); })
      .filter(Boolean);
  }

  // Stored intent and registered reality are different columns, and a refused
  // registration is never hidden behind the preference that failed.
  function shortcutNote(stored, live, prepared) {
    if (recording) return null;
    if (!stored) {
      return { tone: "warn", title: "Unassigned.",
        text: "No free combination was left for this action. Choose one." };
    }
    if (live && live !== stored) {
      return { tone: "warn", title: "Registered as " + live + ".",
        text: "The stored shortcut was not the one the system accepted." };
    }
    if (prepared && !live) {
      return { tone: "bad", title: "Not registered.",
        text: "Another application may already own this combination, so your keyboard does not do this yet." };
    }
    return null;
  }

  function renderShortcuts() {
    const list = byId("shortcut-list");
    if (!list) return;
    const registered = runtime().hotkeys || {};
    // Before the session is prepared there is no listener, so an absent
    // combination means "not started", not "refused".
    const prepared = (app().state || "new") !== "new";
    clear(list);

    SHORTCUTS.forEach(function (entry) {
      const stored = config()[entry.id] || "";
      const live = registered[entry.action] || "";
      const isRecording = recording === entry.id;
      const note = shortcutNote(stored, live, prepared);

      const panel = el("section", "panel");
      panel.dataset.rise = "1";
      panel.dataset.recording = isRecording ? "true" : "false";

      const row = el("div", "shortcut-row");
      const text = el("div", "shortcut-text");
      text.appendChild(el("div", "shortcut-name", entry.name));
      text.appendChild(el("div", "shortcut-hint", entry.hint));
      row.appendChild(text);

      const keys = el("div", "shortcut-keys");
      if (isRecording) {
        keys.appendChild(attr(el("span", "key", "Press keys… Esc cancels"), "data-kind", "recording"));
      } else if (!stored) {
        keys.appendChild(attr(el("span", "key", "unassigned"), "data-kind", "empty"));
      } else {
        keyCaps(stored).forEach(function (cap) { keys.appendChild(el("span", "key", cap)); });
      }
      row.appendChild(keys);

      const action = el("button", "btn btn-sm btn-fixed" + (!stored && !isRecording ? " btn-primary" : ""),
        isRecording ? "Cancel" : (stored ? "Change" : "Assign"));
      action.type = "button";
      action.dataset.record = entry.id;
      row.appendChild(action);
      panel.appendChild(row);

      if (note) {
        const line = attr(el("div", "shortcut-note"), "data-tone", note.tone);
        line.appendChild(el("span", "dot"));
        const message = el("span");
        message.appendChild(el("span", "shortcut-note-title", note.title));
        message.appendChild(document.createTextNode(" " + note.text));
        line.appendChild(message);
        panel.appendChild(line);
      }
      list.appendChild(panel);
    });

    renderHoverModes();
  }

  function renderHoverModes() {
    const rows = byId("hover-mode-rows");
    if (!rows) return;
    const active = config().hover_activation || "push_to_hover";
    clear(rows);
    HOVER_MODES.forEach(function (mode) {
      const button = el("button", "option");
      button.type = "button";
      attr(button, "role", "radio");
      attr(button, "aria-checked", mode.id === active ? "true" : "false");
      button.dataset.activation = mode.id;
      button.appendChild(el("span", "option-radio"));
      const text = el("span", "option-text");
      text.appendChild(el("span", "option-label", mode.label));
      text.appendChild(el("span", "option-desc", mode.desc));
      button.appendChild(text);
      rows.appendChild(button);
    });
  }

  function recordedBinding(event) {
    const parts = [];
    if (event.ctrlKey) parts.push("ctrl");
    if (event.shiftKey) parts.push("shift");
    if (event.altKey) parts.push("alt");
    if (event.metaKey) parts.push("cmd");
    const raw = String(event.key || "").toLowerCase();
    if (MODIFIER_KEYS.indexOf(raw) !== -1) return null;
    parts.push(KEY_NAMES[raw] || raw);
    return parts.join("+");
  }

  // ---- appearance --------------------------------------------------------

  function renderAppearance() {
    renderSegments("theme-choices", THEMES, config().theme || "system", "theme");
    renderSegments(
      "popup-size-choices", POPUP_SIZES,
      config().popup_default_size || "compact", "popupSize"
    );
    renderSegments(
      "technical-detail-choices", TECHNICAL_DETAILS,
      config().technical_details || "off", "technicalDetails"
    );
  }

  function renderSegments(id, options, active, dataKey) {
    const choices = byId(id);
    if (!choices) return;
    clear(choices);
    options.forEach(function (option) {
      const button = el("button", "segment", option.label);
      button.type = "button";
      button.dataset[dataKey] = option.id;
      attr(button, "aria-pressed", option.id === active ? "true" : "false");
      choices.appendChild(button);
    });
  }

  // ---- updates -----------------------------------------------------------

  function updatesBusy(state) {
    return UPDATE_BUSY_STATUSES.indexOf((state || {}).status) !== -1;
  }

  function describePlan(plan) {
    if (!plan) return "";
    const size = formatBytes(plan.download_bytes);
    const kind = plan.source === "delta" ? "Differential update" : "Full download";
    const counts = [];
    if (plan.replace_count) counts.push(plan.replace_count + " replaced");
    if (plan.add_count) counts.push(plan.add_count + " added");
    if (plan.delete_count) counts.push(plan.delete_count + " removed");
    const files = counts.length ? " · " + counts.join(", ") : "";
    return size ? kind + " · " + size + files : kind + files;
  }

  // A download that has reached 100% is not a finished update, so the detail
  // line says what is left and the stage says which step is actually running.
  function describeTransfer(progress) {
    if (!progress) return "";
    const total = progress.total;
    const done = progress.completed || 0;
    if (progress.phase === "downloading" && typeof total === "number" && total > 0) {
      return formatBytes(done) + " / " + formatBytes(total) +
        " · " + formatBytes(Math.max(0, total - done)) + " remaining";
    }
    if (typeof total === "number" && total > 0) return done + " / " + total;
    return "";
  }

  // The stage label swaps because the coordinator's snapshot changed, never on
  // a timer this page owns.
  function sayStage(text) {
    if (text === thinkText) return;
    thinkText = text;
    thinkTick = thinkTick === "a" ? "b" : "a";
  }

  function matrix(container) {
    const grid = el("span", "matrix");
    for (let index = 0; index < 9; index += 1) {
      const cell = el("span");
      cell.dataset.mdot = "1";
      cell.style.animationDelay = (index * 90) + "ms";
      grid.appendChild(cell);
    }
    container.appendChild(grid);
  }

  function thinkNode(text, sizer) {
    const wrapper = el("span", "think");
    wrapper.appendChild(el("span", "think-sizer", sizer || text));
    const live = el("span", "think-text", text);
    live.dataset.think = thinkTick;
    wrapper.appendChild(live);
    return wrapper;
  }

  function actionButton(label, className, action, argument) {
    const button = el("button", className, label);
    button.type = "button";
    button.dataset.action = action;
    if (argument !== undefined) button.dataset.argument = String(argument);
    return button;
  }

  function renderUpdates() {
    const state = updates();
    const panel = byId("update-panel");
    if (!panel) return;
    const application = state.application;
    const busy = updatesBusy(state);
    const status = state.status || "idle";

    clear(panel);
    attr(panel, "data-tone",
      status === "failed" || status === "cancelled" ? "bad"
        : ((application && application.installable) || status === "restart" ||
           state.awaiting_confirmation ? "accent" : null));

    // One attribute names which of the five panel states is showing, so the
    // mode is observable rather than inferred from whichever button exists.
    if (busy) {
      panel.dataset.updateMode = "busy";
      panel.appendChild(busyBlock(state));
    } else if (status === "restart" || state.restart_required) {
      panel.dataset.updateMode = "staged";
      panel.appendChild(stagedBlock(state));
    } else if (state.awaiting_confirmation) {
      panel.dataset.updateMode = "confirm";
      panel.appendChild(confirmBlock(state));
    } else if (application && application.installable) {
      panel.dataset.updateMode = "available";
      panel.appendChild(availableBlock(state));
    } else {
      panel.dataset.updateMode = "idle";
      panel.appendChild(idleBlock(state));
    }

    renderResources(state);
    renderActivity(state);
  }

  function busyBlock(state) {
    const progress = state.progress;
    const block = el("div", "update-busy");
    const line = el("div", "update-busy-line");
    matrix(line);
    sayStage(state.message || formatStatus(state.status));
    // The sizer holds the widest message this panel can show, so the box does
    // not resize as the stage changes.
    line.appendChild(thinkNode(thinkText, "Checking installed files…………"));
    line.appendChild(el("span", "update-detail", describeTransfer(progress)));
    const fraction = progress && typeof progress.fraction === "number" ? progress.fraction : null;
    line.appendChild(el("span", "update-percent",
      fraction === null ? "" : Math.round(fraction * 100) + "%"));
    block.appendChild(line);

    const track = el("div", "track");
    attr(track, "data-indeterminate", fraction === null ? "true" : "false");
    const fill = el("div", "track-fill");
    if (fraction !== null) fill.style.width = (fraction * 100).toFixed(1) + "%";
    track.appendChild(fill);
    block.appendChild(track);

    if (state.cancellable) {
      const actions = el("div", "update-actions");
      actions.appendChild(actionButton("Cancel", "btn btn-sm btn-quiet", "cancel_update"));
      block.appendChild(actions);
    }
    return block;
  }

  function idleBlock(state) {
    const application = state.application;
    const version = runtime().app_version;
    const line = el("div", "update-line");
    const text = el("div");
    text.style.minWidth = "0";
    text.appendChild(el("div", "update-strong",
      version ? "Hanly " + version : "Hanly"));
    text.appendChild(el("div", "update-sub",
      state.message || (application ? application.message : "No update check has been run.")));
    line.appendChild(text);
    const check = actionButton("Check now", "btn", "check_for_updates");
    check.style.marginLeft = "auto";
    line.appendChild(check);
    return line;
  }

  function availableBlock(state) {
    const application = state.application;
    const block = el("div", "update-block");
    const versions = el("div", "update-versions");
    if (application.current_version) {
      versions.appendChild(el("span", "update-from", application.current_version));
      versions.appendChild(el("span", "update-from", "→"));
    }
    versions.appendChild(el("span", "update-to", application.latest_version || ""));
    const plan = describePlan(state.plan);
    if (plan) versions.appendChild(el("span", "update-size", "· " + plan));
    block.appendChild(versions);

    if (application.message) {
      const message = el("p", "update-sub", application.message);
      message.style.margin = "0";
      block.appendChild(message);
    }

    const actions = el("div", "update-actions");
    // "Install update" is the whole update. The notes are the one thing Hanly
    // cannot show in its own window, so they stay a secondary action.
    actions.appendChild(actionButton("Install update", "btn btn-primary",
      "install_application_update", "false"));
    if (application.release_url) {
      actions.appendChild(actionButton("View release notes", "btn btn-quiet", "open_release_notes"));
    }
    block.appendChild(actions);
    return block;
  }

  function confirmBlock(state) {
    const size = formatBytes((state.plan || {}).download_bytes);
    const block = el("div", "update-block");
    block.appendChild(el("div", "update-strong", "This installation needs the full download"));
    block.appendChild(el("div", "update-sub", state.message || describePlan(state.plan)));
    const actions = el("div", "update-actions");
    actions.appendChild(actionButton(
      size ? "Download full update — " + size : "Download full update",
      "btn btn-primary", "install_application_update", "true"));
    actions.appendChild(actionButton("Not now", "btn btn-quiet", "cancel_update"));
    block.appendChild(actions);
    return block;
  }

  function stagedBlock(state) {
    const line = el("div", "update-line");
    const text = el("div");
    text.style.minWidth = "0";
    text.appendChild(el("div", "update-strong", "Ready to restart"));
    text.appendChild(el("div", "update-sub", state.message ||
      "Hanly restarts into the new build. Your settings stay."));
    line.appendChild(text);
    return line;
  }

  function renderResources(state) {
    const list = byId("resource-list");
    if (!list) return;
    const local = runtime().resources || [];
    const offered = {};
    (state.resources || []).forEach(function (item) { offered[item.id] = item; });
    clear(list);

    if (local.length === 0) {
      list.appendChild(el("p", "resource-foot", "No local resources have been reported yet."));
      setText("resources-summary", "");
      return;
    }

    let available = 0;
    local.forEach(function (resource) {
      const update = offered[resource.id];
      const canInstall = !!(update && update.available);
      if (canInstall) available += 1;

      const row = el("div", "resource-row");
      const text = el("div", "resource-text");
      text.appendChild(el("div", "resource-name", resource.id));
      const detail = [
        resource.kind,
        resource.version ? "v" + resource.version : "version not reported",
        resource.compatible ? "compatible" : "review needed"
      ];
      if (canInstall && update.version) detail.push("→ v" + update.version);
      text.appendChild(el("div", "resource-detail", detail.join(" · ")));
      row.appendChild(text);

      const tag = el("span", "tag", canInstall ? "update available" : formatStatus(resource.status));
      attr(tag, "data-tone", canInstall ? "accent" : (resource.compatible ? "ok" : "warn"));
      row.appendChild(tag);

      if (canInstall) {
        const install = actionButton("Install", "btn btn-sm", "install_update", resource.id);
        install.disabled = updatesBusy(state);
        row.appendChild(install);
      }
      list.appendChild(row);
    });

    setText("resources-summary", available === 0
      ? local.length + (local.length === 1 ? " current" : " current")
      : available + (available === 1 ? " update available" : " updates available"));
  }

  function renderActivity(state) {
    const list = byId("activity-list");
    if (!list) return;
    const entries = state.activity || [];
    setHidden("activity-toggle", false);
    setText("activity-summary", entries.length
      ? entries.length + (entries.length === 1 ? " entry" : " entries") : "nothing yet");
    // Rebuilt from a bounded tail rather than appended to, so a long update
    // never grows the page without limit.
    clear(list);
    entries.forEach(function (entry) {
      const row = el("div", "log-row");
      row.appendChild(el("span", "log-time", localTime((entry.at || 0) * 1000)));
      row.appendChild(el("span", "log-message", entry.message || ""));
      list.appendChild(row);
    });
  }

  // ---- readiness ---------------------------------------------------------

  function readinessRows() {
    const status = runtime().status || {};
    const engine = runtime().engine || {};
    const registered = runtime().hotkeys || {};
    const bound = SHORTCUTS.filter(function (entry) { return !!config()[entry.id]; });
    const live = bound.filter(function (entry) { return !!registered[entry.action]; });

    const rows = [
      { label: "Runtime", value: formatStatus(status.phase),
        detail: status.message || (status.stage ? formatStatus(status.stage) : ""),
        tone: status.phase === "ready" ? "ok" : (status.phase === "failed" ? "bad" : "") },
      { label: "Lookup engine", value: ENGINE_LABELS[engine.state] || formatStatus(engine.state),
        detail: engine.message || "", tone: engine.state === "error" ? "bad" : "" },
      { label: "OCR", value: runtime().ocr_provider || "not reported", detail: "", tone: "" },
      { label: "Shortcuts", value: live.length + " / " + SHORTCUTS.length,
        detail: bound.length === SHORTCUTS.length ? "" : "one action is unassigned",
        tone: live.length === SHORTCUTS.length ? "ok" : "warn" }
    ];

    (runtime().resources || []).forEach(function (resource) {
      rows.push({
        label: resource.id,
        value: resource.version ? "v" + resource.version : formatStatus(resource.status),
        detail: [resource.kind, resource.compatible ? "compatible" : "review needed"]
          .concat(resource.diagnostics || []).join(" · "),
        tone: resource.compatible ? "ok" : "warn"
      });
    });

    if (permissionsSupported()) {
      const items = permissions().items || [];
      const granted = items.filter(function (item) { return item.granted; });
      rows.push({
        label: "Permissions", value: granted.length + " / " + items.length,
        detail: items.filter(function (item) { return !item.granted; })
          .map(function (item) { return item.label; }).join(", "),
        tone: granted.length === items.length ? "ok" : "warn"
      });
    }
    return rows;
  }

  function renderReadiness() {
    const stage = byId("readiness-stage");
    const rows = byId("readiness-rows");
    if (!stage || !rows) return;
    stage.dataset.loading = readinessLoading ? "true" : "false";

    clear(rows);
    readinessRows().forEach(function (entry) {
      const row = el("div", "readiness-row");
      row.appendChild(attr(el("span", "dot"), "data-tone", entry.tone || ""));
      row.appendChild(el("span", "readiness-label", entry.label));
      row.appendChild(el("span", "readiness-detail", entry.detail));
      row.appendChild(attr(el("span", "readiness-value", entry.value), "data-tone", entry.tone || ""));
      rows.appendChild(row);
    });

    const skeleton = byId("readiness-skeleton");
    if (skeleton && skeleton.children.length === 0) {
      [200, 170, 150, 190, 160].forEach(function (width, index) {
        const row = el("div", "readiness-row");
        const delay = function (offset) { return (index * 90 + offset) + "ms"; };
        const dot = el("span", "skel-dot");
        dot.dataset.skel = "1";
        dot.style.animationDelay = delay(0);
        row.appendChild(dot);
        const label = el("span", "skel-bar");
        label.dataset.skel = "1";
        label.style.width = "88px";
        label.style.animationDelay = delay(40);
        row.appendChild(label);
        const detail = el("span", "skel-bar");
        detail.dataset.skel = "1";
        detail.style.flex = "1";
        detail.style.maxWidth = width + "px";
        detail.style.animationDelay = delay(80);
        row.appendChild(detail);
        const value = el("span", "skel-bar");
        value.dataset.skel = "1";
        value.style.width = "54px";
        value.style.animationDelay = delay(120);
        row.appendChild(value);
        skeleton.appendChild(row);
      });
    }
  }

  // ---- logs --------------------------------------------------------------

  function matchesFilters(record) {
    if (logFilters.level !== "all" && record.level !== logFilters.level) return false;
    if (logFilters.subsystem !== "all" && record.subsystem !== logFilters.subsystem) return false;
    const search = logFilters.search.trim().toLowerCase();
    if (search && (record.message || "").toLowerCase().indexOf(search) === -1) return false;
    return true;
  }

  function visibleRecords() {
    return (logState.records || []).filter(matchesFilters);
  }

  function renderLogFilters() {
    const group = byId("log-levels");
    if (!group) return;
    // Levels come from the log's own vocabulary; the page never invents one.
    const known = logState.levels || [];
    const offered = LOG_LEVELS.filter(function (level) {
      return level.id === "all" || known.indexOf(level.id) !== -1;
    });
    clear(group);
    offered.forEach(function (level) {
      const chip = el("button", "chip", level.label);
      chip.type = "button";
      chip.dataset.level = level.id;
      attr(chip, "aria-pressed", logFilters.level === level.id ? "true" : "false");
      group.appendChild(chip);
    });

    const select = byId("log-subsystem");
    if (!select) return;
    clear(select);
    const all = el("option", null, "All subsystems");
    all.value = "all";
    select.appendChild(all);
    (logState.subsystems || []).forEach(function (name) {
      const option = el("option", null, name);
      option.value = name;
      select.appendChild(option);
    });
    if ((logState.subsystems || []).indexOf(logFilters.subsystem) === -1) logFilters.subsystem = "all";
    select.value = logFilters.subsystem;
  }

  function renderLogs() {
    const list = byId("log-list");
    if (!list) return;
    const records = visibleRecords();
    clear(list);
    if (records.length === 0) {
      list.appendChild(el("div", "log-empty", "No records match."));
    }
    records.forEach(function (record) {
      const row = el("div", "log-row");
      row.dataset.level = record.level || "info";
      row.appendChild(el("span", "log-time", localTime(record.timestamp)));
      row.appendChild(el("span", "log-level", record.level || "info"));
      row.appendChild(el("span", "log-subsystem", record.subsystem || ""));
      row.appendChild(el("span", "log-message", record.message || ""));
      list.appendChild(row);
    });

    const total = (logState.records || []).length;
    setText("log-summary", total === 0
      ? "No records yet."
      : records.length + " of " + total + " records");
    setText("log-path", logState.log_path || runtime().log_path || "");
  }

  function loadLogs() {
    const api = bridge();
    if (!api || typeof api.get_logs !== "function") return Promise.resolve();
    return api.get_logs().then(function (state) {
      logState = state || { records: [], levels: [], subsystems: [], log_path: null };
      renderLogFilters();
      renderLogs();
    }).catch(showActionError);
  }

  function logsAsText() {
    return visibleRecords().map(function (record) {
      return [record.timestamp, record.level, record.subsystem, record.message].join("\t");
    }).join("\n");
  }

  // ---- sidebar status ----------------------------------------------------

  function renderSidebar() {
    const activity = app().activity || "preparing";
    const running = !!app().capture_running;
    if (connection === "connected") {
      setText("live-label",
        running ? "Capture running" : (ACTIVITY_LABELS[activity] || formatStatus(activity)));
    }
    const dot = byId("live-dot");
    if (dot) {
      dot.dataset.tone = running ? "ok" : (activity === "error" ? "bad" : "");
      dot.dataset.live = running ? "true" : "false";
    }

    const status = runtime().status || {};
    setText("live-runtime", formatStatus(status.phase));
    attr(byId("fact-runtime"), "data-tone",
      status.phase === "ready" ? "ok" : (status.phase === "failed" ? "bad" : ""));

    const engine = runtime().engine || {};
    setText("live-engine", ENGINE_LABELS[engine.state] || formatStatus(engine.state));
    attr(byId("fact-engine"), "data-tone", engine.state === "error" ? "bad" : "");

    // A build that cannot report its own version shows no version row at all.
    const version = runtime().app_version;
    setHidden("fact-version", !version);
    setText("live-version", version || "");

    setHidden("quit-ask", quitAsking);
    setHidden("quit-confirm", !quitAsking);
  }

  // Preparation that has actually given up is the one runtime state worth
  // interrupting whichever page the user is on; retrying is only meaningful
  // once it has.
  function renderRuntimeFailure() {
    const status = runtime().status || {};
    const failed = status.phase === "failed";
    setHidden("runtime-error", !failed);
    setText("runtime-error-text", failed
      ? (status.message || "Hanly could not prepare its lookup runtime.")
      : "");
  }

  // ---- connection and errors ---------------------------------------------

  // The bridge is a pipe to another process. When it stops answering the page
  // says so and offers one explicit retry, rather than polling for a parent
  // that may never come back.
  function setConnection(next, detail) {
    connection = next;
    attr(byId("connection-banner"), "data-connection", next);
    attr(byId("connection-banner"), "data-tone", next === "lost" ? "bad" : "warn");
    setHidden("connection-banner", next === "connected");
    setText("connection-text", next === "lost"
      ? "Connection lost. " + (detail || "Hanly did not answer this window.")
      : "Connecting to Hanly…");
    setHidden("reconnect", next !== "lost");
    // A page that has not been answered is showing its own placeholder, and
    // calling that "stopped" would describe a runtime it has never seen.
    if (next !== "connected") {
      setText("live-label", next === "lost" ? "Connection lost" : "Connecting…");
    }
    if (next !== "connected") {
      // A bridge that is not answering can only stop a poll, so that follows
      // the state change itself. A restored one cannot decide here: the
      // snapshot it is about to render is what the timer depends on.
      syncRefreshTimer(currentState);
    }
  }

  function connectionLost(error) {
    const message = error && error.message ? error.message : String(error || "");
    setConnection("lost", message);
  }

  function showActionError(error) {
    const message = error && error.message ? error.message : String(error || "");
    setText("action-error-text", message);
    setHidden("action-error", message === "");
  }

  // ---- render ------------------------------------------------------------

  function renderState(state) {
    currentState = state || fallbackState;
    applyTheme(config().theme);
    // Readiness is pending only while preparation is, never on a timer.
    readinessLoading = connection !== "connected" ||
      RUNTIME_PENDING_PHASES.indexOf((runtime().status || {}).phase) !== -1;

    renderNav();
    renderPageChrome();
    renderSidebar();
    renderRuntimeFailure();
    renderCapture();
    renderPermissions();
    renderShortcuts();
    renderAppearance();
    renderUpdates();
    renderReadiness();
    syncRefreshTimer(currentState);
  }

  // Nothing pushes a snapshot to this page; the bridge only answers questions.
  // One place decides whether the page is still waiting for news, because
  // letting each renderer own the timer meant the idle one cancelled the
  // refresh the other still needed.
  function refreshRequired(state) {
    if (connection !== "connected") return false;
    const status = (state.runtime || fallbackState.runtime).status || {};
    const activity = (state.app || fallbackState.app).activity || "preparing";
    return (
      ACTIVITY_PENDING.indexOf(activity) !== -1 ||
      RUNTIME_PENDING_PHASES.indexOf(status.phase) !== -1 ||
      updatesBusy(state.updates || fallbackState.updates) ||
      permissionWatchTicks > 0
    );
  }

  function syncRefreshTimer(state) {
    const required = refreshRequired(state);
    if (required === (refreshTimer !== null)) return;
    if (required) {
      refreshTimer = window.setInterval(refresh, REFRESH_INTERVAL_MS);
      return;
    }
    window.clearInterval(refreshTimer);
    refreshTimer = null;
  }

  // A poll is not a user action: it must not clear an error the user is still
  // reading, and a failed one is not worth reporting because the next tick
  // asks again.
  function refresh() {
    if (permissionWatchTicks > 0) permissionWatchTicks -= 1;
    const api = bridge();
    if (!api || typeof api.get_state !== "function") return;
    api.get_state().then(connected).catch(connectionLost);
  }

  function connected(state) {
    setConnection("connected");
    renderState(state);
  }

  function invoke(name, value) {
    const api = bridge();
    if (!api || typeof api[name] !== "function") return Promise.resolve(currentState);
    showActionError("");
    // A rejected action -- "Hanly is still preparing", an unusable region, a
    // shortcut the system refused -- has to reach the page, or the button
    // silently does nothing. An operation answering with no snapshot leaves
    // the page as it is: Quit is answered by Hanly exiting, and a fallback
    // repaint would flash "Preparing" on the way out.
    return (value === undefined ? api[name]() : api[name](value))
      .then(function (state) { if (state) renderState(state); })
      .catch(showActionError);
  }

  // A rejected settings change has to put the control back to what is really
  // stored, or the page keeps showing a choice that never took effect.
  function settings(changes) {
    return invoke("update_settings", changes).then(function () { renderState(currentState); });
  }

  // ---- events ------------------------------------------------------------

  function closest(node, test) {
    let current = node;
    while (current) {
      if (test(current)) return current;
      current = current.parentNode;
    }
    return null;
  }

  function dataOf(node, key) {
    return node && node.dataset ? node.dataset[key] : undefined;
  }

  // One delegated listener per rebuilt region, because every row is recreated
  // on each snapshot and a listener per button would accumulate for the whole
  // session.
  function delegate(id, handler) {
    const node = byId(id);
    if (node) node.addEventListener("click", handler);
  }

  function on(id, type, handler) {
    const node = byId(id);
    if (node) node.addEventListener(type, handler);
  }

  delegate("nav", function (event) {
    const button = closest(event.target, function (node) { return dataOf(node, "page"); });
    if (button) goToPage(button.dataset.page);
  });

  on("toggle-capture", "click", function () {
    invoke(app().capture_running ? "stop_capture" : "start_capture");
  });
  on("select-area", "click", function () { regionDirty = false; invoke("select_capture_area"); });
  on("region-select-area", "click", function () { regionDirty = false; invoke("select_capture_area"); });

  on("target-monitor", "click", function () {
    regionDirty = false;
    invoke("set_capture_mode", "full_monitor");
  });
  on("target-region", "click", function () {
    regionDirty = false;
    invoke("set_capture_mode", "region");
  });

  ["region-left", "region-top", "region-width", "region-height"].forEach(function (id) {
    on(id, "input", function () { regionDirty = true; });
  });

  on("region-apply", "click", function () {
    const region = {};
    [["left", "region-left"], ["top", "region-top"],
     ["width", "region-width"], ["height", "region-height"]].forEach(function (pair) {
      const node = byId(pair[1]);
      region[pair[0]] = Math.round(Number(node ? node.value : 0));
    });
    regionDirty = false;
    invoke("set_region", region);
  });
  on("region-clear", "click", function () { regionDirty = false; invoke("set_region", null); });

  on("capture-target", "change", function (event) { invoke("set_target", event.target.value); });
  on("lookup-preload", "change", function (event) {
    settings({ lookup_preload: event.target.value });
  });
  on("ocr-backend", "change", function (event) {
    settings({ ocr_backend: event.target.value });
  });

  on("hover-delay-slider", "input", function (event) { slideDelay(event.target.value); });
  on("hover-delay-slider", "change", function (event) {
    invoke("set_hover_delay", slideDelay(event.target.value));
  });
  on("hover-delay-value", "focus", function () { delayEditing = true; });
  on("hover-delay-value", "blur", function (event) {
    if (delayEditing) commitDelay(event.target.value);
  });
  on("hover-delay-value", "keydown", function (event) {
    if (event.key === "Enter") {
      event.preventDefault();
      commitDelay(event.target.value);
      event.target.blur();
    }
    if (event.key === "Escape") {
      event.preventDefault();
      delayEditing = false;
      renderHoverDelay();
      event.target.blur();
    }
  });

  delegate("permission-list", function (event) {
    const button = closest(event.target, function (node) { return dataOf(node, "grant"); });
    if (!button) return;
    // The grant happens in System Settings, so the page starts watching for a
    // change it will never be told about.
    permissionWatchTicks = PERMISSION_WATCH_TICKS;
    invoke("grant_permission", button.dataset.grant);
  });
  on("recheck-permissions", "click", function () { invoke("refresh_permissions"); });

  delegate("shortcut-list", function (event) {
    const button = closest(event.target, function (node) { return dataOf(node, "record"); });
    if (!button) return;
    recording = recording === button.dataset.record ? null : button.dataset.record;
    renderShortcuts();
  });

  delegate("hover-mode-rows", function (event) {
    const button = closest(event.target, function (node) { return dataOf(node, "activation"); });
    if (button) settings({ hover_activation: button.dataset.activation });
  });

  delegate("theme-choices", function (event) {
    const button = closest(event.target, function (node) { return dataOf(node, "theme"); });
    if (button) settings({ theme: button.dataset.theme });
  });

  delegate("popup-size-choices", function (event) {
    const button = closest(event.target, function (node) { return dataOf(node, "popupSize"); });
    if (button) settings({ popup_default_size: button.dataset.popupSize });
  });

  delegate("technical-detail-choices", function (event) {
    const button = closest(event.target, function (node) { return dataOf(node, "technicalDetails"); });
    if (button) settings({ technical_details: button.dataset.technicalDetails });
  });

  // Python validates the spelling and registers with the operating system; a
  // refusal comes back as an error and the stored binding is what renders.
  window.addEventListener("keydown", function (event) {
    if (!recording) return;
    event.preventDefault();
    if (event.key === "Escape") {
      recording = null;
      renderShortcuts();
      return;
    }
    const binding = recordedBinding(event);
    if (!binding) return;
    const field = recording;
    recording = null;
    const change = {};
    change[field] = binding;
    settings(change);
  });

  function collapseToggle(toggleId, collapseId) {
    on(toggleId, "click", function () {
      const toggle = byId(toggleId);
      const collapse = byId(collapseId);
      const open = toggle.getAttribute("aria-expanded") !== "true";
      attr(toggle, "aria-expanded", open ? "true" : "false");
      if (collapse) collapse.dataset.open = open ? "true" : "false";
    });
  }

  collapseToggle("resources-toggle", "resources-collapse");
  collapseToggle("activity-toggle", "activity-collapse");

  delegate("update-panel", function (event) {
    const button = closest(event.target, function (node) { return dataOf(node, "action"); });
    if (!button) return;
    const argument = button.dataset.argument;
    if (argument === undefined) invoke(button.dataset.action);
    else if (argument === "true" || argument === "false") invoke(button.dataset.action, argument === "true");
    else invoke(button.dataset.action, argument);
  });

  delegate("resource-list", function (event) {
    const button = closest(event.target, function (node) { return dataOf(node, "action"); });
    if (button) invoke(button.dataset.action, button.dataset.argument);
  });

  on("retry-runtime", "click", function () { invoke("retry_runtime"); });
  on("recheck-readiness", "click", function () { invoke("refresh_permissions"); refresh(); });

  delegate("log-levels", function (event) {
    const chip = closest(event.target, function (node) { return dataOf(node, "level"); });
    if (!chip) return;
    logFilters.level = chip.dataset.level;
    renderLogFilters();
    renderLogs();
  });
  on("log-subsystem", "change", function (event) {
    logFilters.subsystem = event.target.value;
    renderLogs();
  });
  on("log-search", "input", function (event) {
    logFilters.search = event.target.value;
    renderLogs();
  });
  on("refresh-logs", "click", function () { showActionError(""); loadLogs(); });
  on("copy-logs", "click", function () {
    if (!navigator.clipboard) {
      showActionError("This window cannot reach the clipboard.");
      return;
    }
    navigator.clipboard.writeText(logsAsText()).then(function () {
      setText("log-summary", "Copied " + visibleRecords().length + " records.");
    }).catch(function () { showActionError("The records could not be copied."); });
  });
  on("clear-logs", "click", function () {
    const api = bridge();
    if (!api || typeof api.clear_logs !== "function") return;
    showActionError("");
    api.clear_logs().then(function (state) {
      logState = state || { records: [], levels: [], subsystems: [], log_path: null };
      renderLogFilters();
      renderLogs();
    }).catch(function (error) { showActionError(error); loadLogs(); });
  });
  on("export-diagnostics", "click", function () {
    const api = bridge();
    if (!api || typeof api.export_diagnostics !== "function") return;
    showActionError("");
    api.export_diagnostics().then(function (saved) {
      setText("log-summary", "Saved " + saved.records + " records to " + saved.path);
    }).catch(showActionError);
  });

  // The tray is not a route back on every desktop, so the window the user is
  // already looking at carries the action that always ends the session.
  on("quit-ask", "click", function () { quitAsking = true; renderSidebar(); });
  on("quit-confirm-no", "click", function () { quitAsking = false; renderSidebar(); });
  on("quit-confirm-yes", "click", function () { invoke("quit"); });

  // Coming back from System Settings is the moment the answer changed. This is
  // not a user action on the page, so it must not clear an error the user is
  // still reading, and a platform with no permissions has nothing to recheck.
  window.addEventListener("focus", function () {
    const api = bridge();
    if (!api || !permissionsSupported()) return;
    if (typeof api.refresh_permissions !== "function") return;
    api.refresh_permissions().then(renderState).catch(function () {});
  });

  function load() {
    const api = bridge();
    if (!api || typeof api.get_state !== "function") return;
    setConnection("connecting");
    showActionError("");
    api.get_state().then(connected).catch(connectionLost);
    loadLogs();
  }

  on("reconnect", "click", load);

  window.addEventListener("pywebviewready", load);
  // Hanly pushes a nudge when state it owns moved under the page -- readiness
  // settling, capture starting from the tray, an update finishing -- so a
  // visible window stays current without polling for it.
  window.hanlyRefresh = function () {
    refresh();
    loadLogs();
  };

  watchSystemTheme();
  enhanceSelects();
  renderState(fallbackState);

  // The ready event may already have fired before this script ran.
  if (bridge()) load();
}());
