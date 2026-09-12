(function () {
  "use strict";

  const fallbackState = {
    app: { state: "new", activity: "preparing", detail: "", capture_running: false, capture_mode: "full_monitor", target: "cursor", region: null, targets: [] },
    config: { hover_delay_ms: 150, hotkey: "ctrl+shift+space", hover_hotkey: "ctrl+shift+f9", capture_hotkey: "ctrl+shift+f10", hover_activation: "push_to_hover", lookup_preload: "when_capture_starts" },
    runtime: { ocr_provider: "—", resources: [], diagnostics: [], log_path: null, status: { phase: "idle", stage: "", message: "" }, engine: { state: "sleeping", message: "" }, hotkeys: {} },
    updates: { available: false, status: "unavailable", message: "Resource updates are not configured for this runtime.", resources: [], active_resource_id: null, progress: null, application: null, restart_required: false },
    permissions: { supported: false, items: [] }
  };

  // How often the page asks for a new snapshot while something asynchronous
  // is still running.
  const REFRESH_INTERVAL_MS = 500;

  // Runtime phases that are still expected to change without the user doing
  // anything. Naming the unsettled phases rather than the settled ones keeps a
  // phase this page does not know about from polling forever.
  const RUNTIME_PENDING_PHASES = ["preparing", "stopping"];

  // Hanly's own derived activity, which the shell computes from readiness,
  // provider residency and whether capture was actually asked for.
  const ACTIVITY_LABELS = {
    preparing: "Preparing",
    stopped: "Stopped",
    armed: "Armed",
    running: "Running",
    stopping: "Stopping",
    error: "Error"
  };

  // The two activities that still change on their own.
  const ACTIVITY_PENDING = ["preparing", "stopping"];

  // Update statuses that mean an update worker is still running.
  const UPDATE_BUSY_STATUSES = ["checking", "downloading", "verifying", "installing", "validating"];

  // How many refreshes to spend watching for a permission the user just went
  // off to grant. Privacy settings are changed outside this window and nothing
  // tells the page about it, so the page watches for a while and then stops:
  // a permission the user decided not to grant must not poll the system for
  // the rest of the session.
  const PERMISSION_WATCH_TICKS = 60;

  let currentState = fallbackState;
  let refreshTimer = null;
  let permissionWatchTicks = 0;
  // Whether the parent has ever answered this window. Until it has, the page
  // is showing its own placeholder, and saying "new" would be a convincing
  // description of a runtime it has never actually seen.
  let connection = "connecting";

  // pywebview injects its api after the document is parsed, so the bridge has
  // to be resolved per call. Capturing it here would pin it to null forever.
  function bridge() {
    return window.pywebview && window.pywebview.api ? window.pywebview.api : null;
  }

  function byId(id) { return document.getElementById(id); }

  function formatStatus(value) {
    return String(value || "unknown").replace(/_/g, " ");
  }

  function renderTargets(targets, selected) {
    const select = byId("capture-target");
    select.innerHTML = "<option value=\"cursor\">Follow cursor</option>";
    (targets || []).forEach(function (target) {
      const option = document.createElement("option");
      option.value = "monitor:" + target.index;
      option.textContent = target.name || ("Monitor " + target.index);
      select.appendChild(option);
    });
    select.value = selected || "cursor";
  }

  function renderResources(resources) {
    const list = byId("resource-list");
    list.innerHTML = "";
    if (!resources || resources.length === 0) {
      list.innerHTML = "<p class=\"hint\">No local resources have been reported yet.</p>";
      return;
    }
    resources.forEach(function (resource) {
      const row = document.createElement("div");
      row.className = "resource-row";
      row.dataset.status = resource.status;
      const detail = resource.version ? "v" + resource.version : "version not reported";
      row.innerHTML = "<div><div class=\"resource-name\"></div><div class=\"resource-meta\"></div></div><div class=\"resource-state\"></div>";
      row.querySelector(".resource-name").textContent = resource.id;
      row.querySelector(".resource-meta").textContent = resource.kind + " · " + detail + (resource.compatible ? " · compatible" : " · review needed");
      row.querySelector(".resource-state").textContent = resource.status.toLowerCase();
      list.appendChild(row);
    });
  }

  function renderApplicationUpdate(application, busy) {
    const message = byId("application-message");
    const update = byId("update-application");
    const notes = byId("release-notes");
    if (!application) {
      message.textContent = "The installed Hanly version has not been checked yet.";
      update.hidden = true;
      notes.hidden = true;
      return;
    }
    message.textContent = application.message || "";
    // "Update now" is the whole update; the notes are the one thing Hanly
    // cannot show in its own window, so they stay a secondary action.
    update.hidden = !application.installable;
    update.disabled = busy;
    notes.hidden = !application.release_url;
  }

  function updatesBusy(updates) {
    return UPDATE_BUSY_STATUSES.indexOf((updates || {}).status) !== -1;
  }

  function renderUpdates(updates) {
    const updateState = updates || fallbackState.updates;
    const resources = updateState.resources || [];
    const select = byId("update-resource");
    const install = byId("install-update");
    const check = byId("check-updates");
    const progressPanel = byId("update-progress");
    const progressBar = byId("update-progress-bar");
    const progressLabel = byId("update-progress-label");
    const available = resources.filter(function (resource) { return resource.available; });
    select.innerHTML = "";
    if (available.length === 0) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "No updates available";
      select.appendChild(option);
    } else {
      available.forEach(function (resource) {
        const option = document.createElement("option");
        option.value = resource.id;
        option.textContent = resource.id + " · v" + resource.version;
        select.appendChild(option);
      });
      select.value = updateState.active_resource_id || available[0].id;
    }
    const busy = updatesBusy(updateState);
    select.disabled = busy || available.length === 0;
    check.disabled = busy;
    install.disabled = busy || available.length === 0;
    byId("update-status").textContent = formatStatus(updateState.status || "idle");
    byId("update-message").textContent = updateState.message || fallbackState.updates.message;
    renderApplicationUpdate(updateState.application, busy);
    const progress = updateState.progress;
    progressPanel.hidden = !progress || !busy;
    if (progress) {
      progressLabel.textContent = formatStatus(progress.phase);
      progressBar.removeAttribute("value");
      if (progress.fraction !== null && progress.fraction !== undefined) {
        progressBar.value = progress.fraction;
      }
    }
  }

  function permissionStateLabel(permission) {
    if (permission.granted) return "Granted";
    return permission.state === "unknown" ? "Unknown" : "Required";
  }

  // Only macOS gates anything Hanly does, so a platform that reports no
  // permissions gets no heading, no rows, and no reassuring green ticks for
  // grants that do not exist.
  function renderPermissions(permissions) {
    const state = permissions || fallbackState.permissions;
    const panel = byId("permissions");
    const list = byId("permission-list");
    const items = state.items || [];
    // Nothing left to wait for stops the watching even if the countdown had
    // time on it, so a grant ends the polling on the very next render.
    if (!items.some(function (item) { return !item.granted; })) permissionWatchTicks = 0;
    panel.hidden = !state.supported;
    list.innerHTML = "";
    if (!state.supported) return;

    items.forEach(function (permission) {
      const row = document.createElement("div");
      row.className = "permission-row";
      row.dataset.state = permission.state;
      row.dataset.permission = permission.id;

      const text = document.createElement("div");
      const name = document.createElement("div");
      name.className = "permission-name";
      name.textContent = permission.label;
      const detail = document.createElement("div");
      detail.className = "permission-detail";
      detail.textContent = permission.granted
        ? permission.requirement
        : [permission.requirement, permission.restart_note].filter(Boolean).join(" ");
      text.appendChild(name);
      text.appendChild(detail);

      const side = document.createElement("div");
      side.className = "permission-side";
      const badge = document.createElement("span");
      badge.className = "permission-badge";
      badge.textContent = permissionStateLabel(permission);
      side.appendChild(badge);
      if (!permission.granted) {
        const grant = document.createElement("button");
        grant.className = "text-button";
        grant.type = "button";
        grant.dataset.grant = permission.id;
        grant.textContent = "Grant access";
        side.appendChild(grant);
      }

      row.appendChild(text);
      row.appendChild(side);
      list.appendChild(row);
    });
  }

  // The engine is where the memory is, and it is allowed to be asleep while
  // Hanly is perfectly ready: a lookup loads it. Saying so is the difference
  // between "not working" and "not loaded yet".
  const ENGINE_LABELS = {
    sleeping: "Not loaded",
    preparing: "Loading…",
    ready: "Loaded",
    error: "Error"
  };

  function renderEngine(runtime) {
    const engine = runtime.engine || fallbackState.runtime.engine;
    const item = byId("engine-item");
    item.dataset.state = engine.state || "sleeping";
    byId("engine-state").textContent = ENGINE_LABELS[engine.state] || formatStatus(engine.state);
    byId("engine-message").textContent = engine.message || "";
  }

  // What the operating system actually accepted, which is not always what was
  // asked for: a combination another application owns stays with that one.
  function renderRegisteredHotkeys(runtime, app) {
    const registered = runtime.hotkeys || {};
    // Before the session is prepared there is no listener yet, so an absent
    // combination means "not started", not "refused".
    const prepared = (app.state || "new") !== "new";
    const fields = [
      ["hotkey", "push_to_hover"],
      ["hover-hotkey", "toggle_hover"],
      ["capture-hotkey", "toggle_capture"]
    ];
    fields.forEach(function (pair) {
      const hint = byId(pair[0] + "-registered");
      const live = registered[pair[1]];
      const asked = byId(pair[0]).value;
      if (live && live !== asked) {
        hint.textContent = "Registered as " + live;
        hint.classList.remove("hint-error");
        return;
      }
      // An action the user deliberately left unbound is not a failure.
      const missing = prepared && !live && asked !== "";
      hint.textContent = missing
        ? "Not registered. Another application may already use this combination."
        : "";
      hint.classList.toggle("hint-error", missing);
    });
  }

  function renderRuntimeStatus(runtime) {
    const status = runtime.status || fallbackState.runtime.status;
    const item = byId("runtime-item");
    item.dataset.phase = status.phase || "idle";
    byId("runtime-state").textContent = formatStatus(status.phase);
    byId("runtime-message").textContent =
      status.message || (status.stage ? "Working on " + formatStatus(status.stage) + "." : "");
    // Retrying is only meaningful once preparation has actually given up.
    byId("retry-runtime").hidden = status.phase !== "failed";
    // Starting before the runtime is ready would only be refused, so the
    // button says so instead of offering an action that cannot work.
    const start = byId("start-capture");
    start.disabled = status.phase !== "ready";
    start.title = start.disabled ? "Hanly is still preparing its lookup runtime." : "";
    byId("log-path").textContent = runtime.log_path ? "Log: " + runtime.log_path : "V1 / local";
  }

  // A saved region can outlive the monitor it was drawn on. Capture then falls
  // back to the whole monitor, and the page has to say so rather than leave the
  // scope reading "region" over an area nobody chose.
  function regionHint(app) {
    if (app.region) return "A region is selected for focused reading.";
    if (app.capture_mode === "region") {
      return "Region scope is selected but no region is saved, so Hanly reads the whole monitor. Choose a capture area.";
    }
    return "No region selected. Choose a scope to keep capture close to the word.";
  }

  // The bridge is a pipe to another process. When it stops answering, the page
  // says so and offers one explicit retry rather than polling for a parent
  // that may never come back.
  function setConnection(next, detail) {
    connection = next;
    const item = byId("connection-item");
    item.hidden = next === "connected";
    item.dataset.connection = next;
    byId("connection-state").textContent =
      next === "lost" ? "Connection lost" : "Connecting…";
    byId("connection-message").textContent = detail || "";
    byId("reconnect").hidden = next !== "lost";
    if (next !== "connected") {
      byId("status-line").dataset.state = next;
      byId("app-state").textContent =
        next === "lost" ? "Connection lost" : "Connecting…";
    }
  }

  function connectionLost(error) {
    const message = error && error.message ? error.message : String(error || "");
    setConnection("lost", message || "Hanly did not answer this window.");
  }

  function showActionError(error) {
    const line = byId("action-error");
    const message = error && error.message ? error.message : String(error || "");
    line.textContent = message;
    line.hidden = message === "";
  }

  function renderState(state) {
    currentState = state || fallbackState;
    const app = currentState.app || fallbackState.app;
    const config = currentState.config || fallbackState.config;
    const runtime = currentState.runtime || fallbackState.runtime;
    const updates = currentState.updates || fallbackState.updates;
    const activity = app.activity || "preparing";
    byId("status-line").dataset.state = activity;
    byId("app-state").textContent = ACTIVITY_LABELS[activity] || formatStatus(activity);
    byId("app-detail").textContent = app.detail || "";
    byId("capture-state").textContent = app.capture_running ? "Running" : "Stopped";
    byId("ocr-provider").textContent = runtime.ocr_provider || "—";
    byId("resource-count").textContent = (runtime.resources || []).length + " resources";
    const diagnosticCount = (runtime.diagnostics || []).length;
    byId("diagnostic-state").textContent = diagnosticCount === 0 ? "Clear" : diagnosticCount + " reported";
    byId("capture-mode").value = app.capture_mode || "full_monitor";
    byId("hover-delay").value = config.hover_delay_ms || 150;
    byId("hotkey").value = config.hotkey || "";
    byId("hover-hotkey").value = config.hover_hotkey || "";
    byId("capture-hotkey").value = config.capture_hotkey || "";
    byId("hover-activation").value = config.hover_activation || "push_to_hover";
    byId("lookup-preload").value = config.lookup_preload || "when_capture_starts";
    byId("region-hint").textContent = regionHint(app);
    ["left", "top", "width", "height"].forEach(function (field) {
      byId("region-" + field).value = app.region ? app.region[field] : "";
    });
    renderRuntimeStatus(runtime);
    renderEngine(runtime);
    renderRegisteredHotkeys(runtime, app);
    renderUpdates(updates);
    renderTargets(app.targets, app.target);
    renderResources(runtime.resources);
    renderPermissions(currentState.permissions);
    syncRefreshTimer(currentState);
  }

  // Nothing pushes a snapshot to this page; the bridge only answers questions.
  // Runtime preparation and update installation both finish on their own, so
  // one place decides whether the page is still waiting for news. Letting each
  // renderer own the timer meant the idle one cancelled the refresh the other
  // still needed.
  function refreshRequired(state) {
    // A page that has not been answered is showing its own placeholder, and
    // polling for a parent that may never reply is not a recovery strategy.
    if (connection !== "connected") return false;
    const runtime = state.runtime || fallbackState.runtime;
    const status = runtime.status || fallbackState.runtime.status;
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

  // One place turns an answered question into a rendered page, so the window
  // stops claiming a connection it does not have.
  function connected(state) {
    setConnection("connected");
    renderState(state);
  }

  function invoke(name, value) {
    const api = bridge();
    if (!api || typeof api[name] !== "function") return Promise.resolve(currentState);
    showActionError("");
    // A rejected action -- "Hanly is still preparing", an unusable region --
    // has to reach the page, or the button silently does nothing.
    return (value === undefined ? api[name]() : api[name](value))
      .then(renderState)
      .catch(showActionError);
  }

  // A rejected settings change has to put the control back to what is really
  // stored, or the page keeps showing a choice that never took effect.
  function settings(changes) {
    return invoke("update_settings", changes).then(function () { renderState(currentState); });
  }

  byId("start-capture").addEventListener("click", function () { invoke("start_capture"); });
  byId("stop-capture").addEventListener("click", function () { invoke("stop_capture"); });
  byId("capture-mode").addEventListener("change", function (event) { invoke("set_capture_mode", event.target.value); });
  byId("capture-target").addEventListener("change", function (event) { invoke("set_target", event.target.value); });
  byId("apply-region").addEventListener("click", function () {
    const region = {};
    ["left", "top", "width", "height"].forEach(function (field) { region[field] = Number(byId("region-" + field).value); });
    invoke("set_region", region);
  });
  byId("clear-region").addEventListener("click", function () { invoke("set_region", null); });
  byId("select-area").addEventListener("click", function () { invoke("select_capture_area"); });
  byId("retry-runtime").addEventListener("click", function () { invoke("retry_runtime"); });
  // One delegated listener, because the rows are rebuilt on every snapshot and
  // a listener per button per render would accumulate for the whole session.
  byId("permission-list").addEventListener("click", function (event) {
    const permission = event.target && event.target.dataset ? event.target.dataset.grant : null;
    if (!permission) return;
    // The grant happens in System Settings, so the page starts watching for
    // the change it will never be told about.
    permissionWatchTicks = PERMISSION_WATCH_TICKS;
    invoke("grant_permission", permission);
  });
  byId("recheck-permissions").addEventListener("click", function () { invoke("refresh_permissions"); });
  // Coming back from System Settings is the moment the answer changed. This is
  // not a user action on the page, so it must not clear an error the user is
  // still reading, and a platform with no permissions has nothing to recheck.
  window.addEventListener("focus", function () {
    const api = bridge();
    if (!api || !(currentState.permissions || fallbackState.permissions).supported) return;
    if (typeof api.refresh_permissions !== "function") return;
    api.refresh_permissions().then(renderState).catch(function () {});
  });
  // The tray is not a route back on every desktop, so the window the user is
  // already looking at carries the action that always ends the session.
  byId("quit-hanly").addEventListener("click", function () { invoke("quit"); });
  byId("hover-delay").addEventListener("change", function (event) { invoke("set_hover_delay", Number(event.target.value)); });
  byId("hotkey").addEventListener("change", function (event) { invoke("set_hotkey", event.target.value); });
  byId("hover-hotkey").addEventListener("change", function (event) { settings({ hover_hotkey: event.target.value }); });
  byId("capture-hotkey").addEventListener("change", function (event) { settings({ capture_hotkey: event.target.value }); });
  byId("hover-activation").addEventListener("change", function (event) { settings({ hover_activation: event.target.value }); });
  byId("lookup-preload").addEventListener("change", function (event) { settings({ lookup_preload: event.target.value }); });
  byId("check-updates").addEventListener("click", function () { invoke("check_for_updates"); });
  byId("update-application").addEventListener("click", function () { invoke("install_application_update"); });
  byId("release-notes").addEventListener("click", function () { invoke("open_release_notes"); });
  byId("install-update").addEventListener("click", function () {
    const resourceId = byId("update-resource").value;
    invoke("install_update", resourceId || undefined);
  });

  // ---- Logs ------------------------------------------------------------
  // Records render through textContent only: a log line can hold anything a
  // provider or the operating system put in an error message, and none of it
  // is markup.

  let logState = { records: [], subsystems: [] };

  function matchesFilters(record) {
    const level = byId("log-level").value;
    const subsystem = byId("log-subsystem").value;
    const search = byId("log-search").value.trim().toLowerCase();
    if (level !== "all" && level !== "" && record.level !== level) return false;
    if (subsystem !== "all" && subsystem !== "" && record.subsystem !== subsystem) return false;
    if (search && (record.message || "").toLowerCase().indexOf(search) === -1) return false;
    return true;
  }

  function localTime(timestamp) {
    const parsed = new Date(timestamp);
    return isNaN(parsed.getTime()) ? String(timestamp || "") : parsed.toLocaleTimeString();
  }

  function visibleRecords() {
    return (logState.records || []).filter(matchesFilters);
  }

  function renderSubsystems(subsystems) {
    const select = byId("log-subsystem");
    const selected = select.value || "all";
    select.innerHTML = "<option value=\"all\">All</option>";
    (subsystems || []).forEach(function (name) {
      const option = document.createElement("option");
      option.value = name;
      option.textContent = name;
      select.appendChild(option);
    });
    select.value = (subsystems || []).indexOf(selected) === -1 ? "all" : selected;
  }

  function renderLogs() {
    const list = byId("log-list");
    const records = visibleRecords();
    list.innerHTML = "";
    records.forEach(function (record) {
      const row = document.createElement("div");
      row.className = "log-row";
      row.dataset.level = record.level || "info";
      ["log-time", "log-subsystem", "log-message"].forEach(function (className, index) {
        const cell = document.createElement("span");
        cell.className = className;
        cell.textContent = [
          localTime(record.timestamp),
          record.subsystem,
          record.message
        ][index];
        row.appendChild(cell);
      });
      list.appendChild(row);
    });
    const total = (logState.records || []).length;
    byId("log-summary").textContent = total === 0
      ? "No records yet."
      : records.length + " of " + total + " records";
  }

  function loadLogs() {
    const api = bridge();
    if (!api || typeof api.get_logs !== "function") return Promise.resolve();
    return api.get_logs().then(function (state) {
      logState = state || { records: [], subsystems: [] };
      renderSubsystems(logState.subsystems);
      renderLogs();
    }).catch(showActionError);
  }

  function logsAsText() {
    return visibleRecords().map(function (record) {
      return [record.timestamp, record.level, record.subsystem, record.message].join("\t");
    }).join("\n");
  }

  byId("log-level").addEventListener("change", renderLogs);
  byId("log-subsystem").addEventListener("change", renderLogs);
  byId("log-search").addEventListener("input", renderLogs);
  byId("refresh-logs").addEventListener("click", function () { showActionError(""); loadLogs(); });
  byId("copy-logs").addEventListener("click", function () {
    if (!navigator.clipboard) { showActionError("This window cannot reach the clipboard."); return; }
    navigator.clipboard.writeText(logsAsText()).then(function () {
      byId("log-summary").textContent = "Copied " + visibleRecords().length + " records.";
    }).catch(function () { showActionError("The records could not be copied."); });
  });
  byId("clear-logs").addEventListener("click", function () {
    const api = bridge();
    if (!api || typeof api.clear_logs !== "function") return;
    showActionError("");
    api.clear_logs().then(function (state) {
      logState = state || { records: [], subsystems: [] };
      renderSubsystems(logState.subsystems);
      renderLogs();
    }).catch(function (error) { showActionError(error); loadLogs(); });
  });
  byId("export-diagnostics").addEventListener("click", function () {
    const api = bridge();
    if (!api || typeof api.export_diagnostics !== "function") return;
    showActionError("");
    api.export_diagnostics().then(function (saved) {
      byId("log-summary").textContent = "Saved " + saved.records + " records to " + saved.path;
    }).catch(showActionError);
  });

  function load() {
    const api = bridge();
    if (!api || typeof api.get_state !== "function") return;
    setConnection("connecting");
    showActionError("");
    api.get_state().then(connected).catch(connectionLost);
    loadLogs();
  }

  byId("reconnect").addEventListener("click", load);

  window.addEventListener("pywebviewready", load);
  // Hanly itself pushes a nudge when state it owns moved under the page --
  // readiness settling, capture starting from the tray, an update finishing --
  // so a visible window stays current without polling for it.
  window.hanlyRefresh = function () {
    refresh();
    loadLogs();
  };
  renderState(fallbackState);

  // The ready event may already have fired before this script ran.
  if (bridge()) load();
}());
