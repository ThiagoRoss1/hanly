// Runs the packaged Control Center page against a scripted sequence of bridge
// snapshots and reports what the page did with its refresh timer.
//
// The page is written for a browser, so the DOM it touches is stubbed rather
// than emulated: the assertions are about which snapshot the page asked for
// next and what it rendered, not about layout. Invoked by
// tests/test_control_center_refresh.py, which owns the expectations.
//
//   node control_center_harness.js <control_center.js> <snapshots.json> [<actions.json>]
//
// An action entry names a timer step and either a permission to click "Grant
// access" for, or an element id to click, so the page's own post-grant
// watching and its explicit retry can both be observed.

"use strict";

const fs = require("fs");
const vm = require("vm");

const pageSource = fs.readFileSync(process.argv[2], "utf8");
const snapshots = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const actions = process.argv[4] ? JSON.parse(fs.readFileSync(process.argv[4], "utf8")) : [];

const elements = new Map();

// "data-update-mode" is dataset.updateMode; anything else is not a data
// attribute and has no dataset name at all.
function datasetKey(name) {
  if (name.indexOf("data-") !== 0) return null;
  return name.slice(5).replace(/-([a-z])/g, function (_, letter) {
    return letter.toUpperCase();
  });
}

function element(id) {
  const node = {
    id: id || "",
    dataset: {},
    // The page sets custom properties on style; nothing here reads them back
    // except as a record that it did.
    style: {
      setProperty(name, value) { this[name] = value; },
      removeProperty(name) { delete this[name]; }
    },
    attributes: {},
    textContent: "",
    className: "",
    value: "",
    title: "",
    min: "",
    max: "",
    type: "",
    hidden: false,
    disabled: false,
    // Appended children are kept so a list the page builds element by element
    // can be read back; assigning innerHTML is how the page clears one.
    children: [],
    parentNode: null,
    listeners: [],
    // Only the four operations the page actually performs, over a plain set.
    classList: (function () {
      const names = new Set();
      return {
        add(name) { names.add(name); },
        remove(name) { names.delete(name); },
        contains(name) { return names.has(name); },
        toggle(name, on) { return on ? names.add(name) && true : names.delete(name) && false; }
      };
    }()),
    appendChild(child) {
      child.parentNode = this;
      this.children.push(child);
      return child;
    },
    removeChild(child) {
      const at = this.children.indexOf(child);
      if (at !== -1) this.children.splice(at, 1);
      child.parentNode = null;
      return child;
    },
    // A real DOM reflects data-* attributes into dataset and back, and the
    // page uses both spellings for the same value.
    setAttribute(name, value) {
      this.attributes[name] = String(value);
      const key = datasetKey(name);
      if (key) this.dataset[key] = String(value);
    },
    getAttribute(name) {
      const key = datasetKey(name);
      if (key && this.dataset[key] !== undefined) return this.dataset[key];
      return Object.prototype.hasOwnProperty.call(this.attributes, name)
        ? this.attributes[name] : null;
    },
    removeAttribute(name) {
      delete this.attributes[name];
      const key = datasetKey(name);
      if (key) delete this.dataset[key];
    },
    addEventListener(type, handler) { this.listeners.push({ type, handler }); },
    dispatch(type, event) {
      this.listeners
        .filter(function (entry) { return entry.type === type; })
        .forEach(function (entry) { entry.handler(event); });
    },
    blur() {},
    focus() {},
    querySelector() { return element(); }
  };
  Object.defineProperty(node, "innerHTML", {
    get() { return ""; },
    set() {
      node.children.forEach(function (child) { child.parentNode = null; });
      node.children.length = 0;
    }
  });
  return node;
}

const documentElement = element("html");

const document = {
  documentElement: documentElement,
  getElementById(id) {
    if (!elements.has(id)) elements.set(id, element(id));
    return elements.get(id);
  },
  createElement() { return element(); },
  createTextNode(text) {
    const node = element();
    node.textContent = String(text);
    return node;
  }
};

// One timer slot, because the page is only ever allowed to own one interval.
let timer = null;
let intervalsCreated = 0;
let clearsRequested = 0;

let served = 0;

function serveSnapshot() {
  // The last snapshot repeats, so a page that keeps polling after the state
  // settles is visible as extra requests rather than a crash.
  const index = Math.min(served, snapshots.length - 1);
  served += 1;
  const snapshot = snapshots[index];
  // A snapshot may stand in for the parent not answering at all, which is what
  // a dead bridge looks like from the page.
  if (snapshot && snapshot.__reject__) {
    return Promise.reject(new Error(snapshot.__reject__));
  }
  return Promise.resolve(snapshot);
}

function emptyLogs() {
  return Promise.resolve({ records: [], levels: [], subsystems: [], log_path: null });
}

const window = {
  addEventListener() {},
  // The theme control resolves "system" through this; the harness is always a
  // light desktop, which is one real answer.
  matchMedia() {
    return { matches: false, addEventListener() {}, addListener() {} };
  },
  setInterval(callback) {
    intervalsCreated += 1;
    timer = callback;
    return intervalsCreated;
  },
  clearInterval() {
    clearsRequested += 1;
    timer = null;
  },
  setTimeout() { return 0; },
  clearTimeout() {},
  pywebview: {
    api: {
      get_state: serveSnapshot,
      get_logs: emptyLogs,
      // Permission actions answer with a snapshot exactly as the bridge does,
      // so a page that acts on their reply is exercised the same way.
      grant_permission: serveSnapshot,
      refresh_permissions: serveSnapshot
    }
  }
};

vm.createContext(window);
window.window = window;
window.document = document;
window.navigator = {};
vm.runInContext(pageSource, window);

// Each permission row is built out of createElement calls, so it is read back
// through the same structure the page appended:
//   row > [dot, body > [head > [name, tag], why], grant?]
function permissionRows() {
  return document.getElementById("permission-list").children.map(function (row) {
    const body = row.children[1] || element();
    const head = body.children[0] || element();
    return {
      permission: row.children[2] ? row.children[2].dataset.grant : undefined,
      granted: row.dataset.granted === "true",
      label: (head.children[0] || element()).textContent,
      badge: (head.children[1] || element()).textContent,
      detail: (body.children[1] || element()).textContent,
      grant_offered: row.children.length > 2
    };
  });
}

// The page sections a platform actually offers, which is how a build with no
// privacy gates is seen to have no Permissions section at all.
function navPages() {
  return document.getElementById("nav").children
    .map(function (child) { return child.dataset.page; })
    .filter(Boolean);
}

function report(step) {
  return {
    step: step,
    nav_pages: navPages(),
    permission_rows: permissionRows(),
    timer_running: timer !== null,
    intervals_created: intervalsCreated,
    clears_requested: clearsRequested,
    runtime_state: document.getElementById("live-runtime").textContent,
    engine_state: document.getElementById("live-engine").textContent,
    runtime_message: document.getElementById("runtime-error-text").textContent,
    retry_hidden: document.getElementById("runtime-error").hidden,
    start_disabled: document.getElementById("toggle-capture").disabled,
    update_mode: document.getElementById("update-panel").dataset.updateMode,
    app_state: document.getElementById("live-label").textContent,
    connection_hidden: document.getElementById("connection-banner").hidden,
    connection: document.getElementById("connection-banner").dataset.connection,
    reconnect_hidden: document.getElementById("reconnect").hidden,
    theme_mode: documentElement.getAttribute("data-mode")
  };
}

function applyActions(step) {
  const due = actions.filter(function (action) { return action.step === step; });
  due.forEach(function (action) {
    if (action.click) {
      document.getElementById(action.click).dispatch("click", {});
      return;
    }
    document
      .getElementById("permission-list")
      .dispatch("click", { target: { dataset: { grant: action.grant } } });
  });
  return due.length > 0;
}

async function main() {
  const trace = [];
  // The first answer travels through a resolve and a rejection handler, so the
  // page needs more than one microtask turn before it has rendered anything.
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
  trace.push(report(0));

  // Each step is one timer tick. Without a running timer the page has decided
  // it is done, and nothing else can advance it.
  for (let step = 1; step < snapshots.length + 1; step += 1) {
    // A scripted click lands between renders, exactly as a user's would, and
    // its own reply has to settle before the page's timer state is read.
    const acted = applyActions(step - 1);
    await Promise.resolve();
    await Promise.resolve();
    if (timer === null) {
      // A page with no timer has decided it is done; a click is still worth
      // one final report, because that is the only way its effect is visible.
      if (acted) trace.push(report(step));
      break;
    }
    timer();
    await Promise.resolve();
    await Promise.resolve();
    trace.push(report(step));
  }
  process.stdout.write(JSON.stringify(trace));
}

main();
