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
// An action entry names a timer step and a permission to click "Grant access"
// for, so the page's own post-grant watching can be observed.

"use strict";

const fs = require("fs");
const vm = require("vm");

const pageSource = fs.readFileSync(process.argv[2], "utf8");
const snapshots = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const actions = process.argv[4] ? JSON.parse(fs.readFileSync(process.argv[4], "utf8")) : [];

const elements = new Map();

function element() {
  const node = {
    dataset: {},
    style: {},
    textContent: "",
    innerHTML: "",
    className: "",
    value: "",
    title: "",
    hidden: false,
    disabled: false,
    // Appended children are kept so a list the page builds element by element
    // can be read back; assigning innerHTML is how the page clears one.
    children: [],
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
    appendChild(child) { this.children.push(child); return child; },
    removeAttribute() {},
    addEventListener(type, handler) { this.listeners.push({ type, handler }); },
    dispatch(type, event) {
      this.listeners
        .filter(function (entry) { return entry.type === type; })
        .forEach(function (entry) { entry.handler(event); });
    },
    querySelector() { return element(); }
  };
  Object.defineProperty(node, "innerHTML", {
    get() { return ""; },
    set() { node.children.length = 0; }
  });
  return node;
}

const document = {
  getElementById(id) {
    if (!elements.has(id)) elements.set(id, element());
    return elements.get(id);
  },
  createElement() { return element(); }
};

// One timer slot, because the page is only ever allowed to own one interval.
let timer = null;
let intervalsCreated = 0;
let clearsRequested = 0;

let served = 0;
const requests = [];

function serveSnapshot() {
  // The last snapshot repeats, so a page that keeps polling after the state
  // settles is visible as extra requests rather than a crash.
  const index = Math.min(served, snapshots.length - 1);
  served += 1;
  requests.push(index);
  const snapshot = snapshots[index];
  // A snapshot may stand in for the parent not answering at all, which is what
  // a dead bridge looks like from the page.
  if (snapshot && snapshot.__reject__) {
    return Promise.reject(new Error(snapshot.__reject__));
  }
  return Promise.resolve(snapshot);
}

const window = {
  addEventListener() {},
  setInterval(callback) {
    intervalsCreated += 1;
    timer = callback;
    return intervalsCreated;
  },
  clearInterval() {
    clearsRequested += 1;
    timer = null;
  },
  pywebview: {
    api: {
      get_state: serveSnapshot,
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
vm.runInContext(pageSource, window);

// The page builds each permission row out of createElement calls, so the row
// is read back through the same structure it appended.
function permissionRows() {
  return document.getElementById("permission-list").children.map(function (row) {
    const text = row.children[0] || element();
    const side = row.children[1] || element();
    return {
      permission: row.dataset.permission,
      state: row.dataset.state,
      label: (text.children[0] || element()).textContent,
      detail: (text.children[1] || element()).textContent,
      badge: (side.children[0] || element()).textContent,
      grant_offered: side.children.length > 1
    };
  });
}

function report(step) {
  return {
    step: step,
    permissions_hidden: document.getElementById("permissions").hidden,
    permission_rows: permissionRows(),
    snapshot_served: served - 1,
    timer_running: timer !== null,
    intervals_created: intervalsCreated,
    clears_requested: clearsRequested,
    runtime_state: document.getElementById("runtime-state").textContent,
    runtime_message: document.getElementById("runtime-message").textContent,
    start_disabled: document.getElementById("start-capture").disabled,
    retry_hidden: document.getElementById("retry-runtime").hidden,
    check_disabled: document.getElementById("check-updates").disabled,
    app_state: document.getElementById("app-state").textContent,
    app_detail: document.getElementById("app-detail").textContent,
    connection_hidden: document.getElementById("connection-item").hidden,
    connection_state: document.getElementById("connection-state").textContent,
    reconnect_hidden: document.getElementById("reconnect").hidden,
    hotkey_hint: document.getElementById("hotkey-registered").textContent
  };
}

function applyActions(step) {
  const due = actions.filter(function (action) { return action.step === step; });
  due
    .forEach(function (action) {
      if (action.click === "reconnect") {
        document.getElementById("reconnect").dispatch("click", {});
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
