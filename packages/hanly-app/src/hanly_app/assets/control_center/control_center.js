(function () {
  "use strict";

  const fallbackState = {
    app: { state: "new", capture_running: false, capture_mode: "full_monitor", target: "cursor", region: null, targets: [] },
    config: { hover_delay_ms: 150, hotkey: "ctrl+shift+space" },
    runtime: { ocr_provider: "—", resources: [], diagnostics: [] },
    updates: { available: false, status: "unavailable", message: "Resource updates are not configured for this runtime.", resources: [], active_resource_id: null, progress: null }
  };

  let currentState = fallbackState;
  let refreshTimer = null;

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
    const busy = ["checking", "downloading", "validating"].indexOf(updateState.status) !== -1;
    select.disabled = busy || available.length === 0;
    check.disabled = busy;
    install.disabled = busy || available.length === 0;
    byId("update-status").textContent = formatStatus(updateState.status || "idle");
    byId("update-message").textContent = updateState.message || fallbackState.updates.message;
    const progress = updateState.progress;
    progressPanel.hidden = !progress || !busy;
    if (progress) {
      progressLabel.textContent = formatStatus(progress.phase);
      progressBar.removeAttribute("value");
      if (progress.fraction !== null && progress.fraction !== undefined) {
        progressBar.value = progress.fraction;
      }
    }
    if (busy) {
      if (refreshTimer === null) {
        refreshTimer = window.setInterval(function () { invoke("get_state"); }, 500);
      }
    } else if (refreshTimer !== null) {
      window.clearInterval(refreshTimer);
      refreshTimer = null;
    }
  }

  function renderState(state) {
    currentState = state || fallbackState;
    const app = currentState.app || fallbackState.app;
    const config = currentState.config || fallbackState.config;
    const runtime = currentState.runtime || fallbackState.runtime;
    const updates = currentState.updates || fallbackState.updates;
    const stateName = formatStatus(app.state);
    byId("status-line").dataset.state = app.state || "unknown";
    byId("app-state").textContent = stateName;
    byId("capture-state").textContent = app.capture_running ? "Running" : "Stopped";
    byId("ocr-provider").textContent = runtime.ocr_provider || "—";
    byId("resource-count").textContent = (runtime.resources || []).length + " resources";
    const diagnosticCount = (runtime.diagnostics || []).length;
    byId("diagnostic-state").textContent = diagnosticCount === 0 ? "Clear" : diagnosticCount + " reported";
    byId("capture-mode").value = app.capture_mode || "full_monitor";
    byId("hover-delay").value = config.hover_delay_ms || 150;
    byId("hotkey").value = config.hotkey || "";
    byId("region-hint").textContent = app.region ? "A region is selected for focused reading." : "No region selected. Choose a scope to keep capture close to the word.";
    ["left", "top", "width", "height"].forEach(function (field) {
      byId("region-" + field).value = app.region ? app.region[field] : "";
    });
    renderUpdates(updates);
    renderTargets(app.targets, app.target);
    renderResources(runtime.resources);
  }

  function invoke(name, value) {
    const api = bridge();
    if (!api || typeof api[name] !== "function") return Promise.resolve(currentState);
    return (value === undefined ? api[name]() : api[name](value)).then(renderState);
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
  byId("hover-delay").addEventListener("change", function (event) { invoke("set_hover_delay", Number(event.target.value)); });
  byId("hotkey").addEventListener("change", function (event) { invoke("set_hotkey", event.target.value); });
  byId("check-updates").addEventListener("click", function () { invoke("check_for_updates"); });
  byId("install-update").addEventListener("click", function () {
    const resourceId = byId("update-resource").value;
    invoke("install_update", resourceId || undefined);
  });

  window.addEventListener("pywebviewready", function () {
    invoke("get_state");
  });
  renderState(fallbackState);

  // The ready event may already have fired before this script ran.
  if (bridge()) invoke("get_state");
}());
