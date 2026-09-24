/* {{project_name}} — the application shell. Written by Poiesis, and read-only.
 *
 * Stories never edit this file. Each story adds its own screen as
 * frontend/screens/<resource>.js; the platform regenerates
 * frontend/screens/index.js to list them, and this shell loads them, draws the
 * navigation and the page header, routes between them and catches their errors.
 *
 * It also gives every application the same finished experience for free: icon
 * navigation, breadcrumbs, a progress bar on every API call, skeleton loading,
 * a command palette (Ctrl K) that finds screens and any record in the
 * database, a light/dark theme toggle, a collapsible sidebar, keyboard
 * shortcuts (? lists them), ripples on buttons, and page transitions.
 *
 * A screen module:
 *
 *   export default {
 *     title: "Leave requests",        // navigation label and page heading
 *     subtitle: "Request time off",   // optional line under the heading
 *     icon: "calendar",               // optional; guessed from the title otherwise (see ui.ICONS)
 *     story: "S1",                    // the story (or "S1, S3") it delivers
 *     async render(root, { api, h, navigate, params, actions, ui }) { ... }
 *   };
 *
 *   api("/items")                                         GET /api/items -> JSON
 *   api("/items", { method: "POST", body: { name: "a" } }) -> JSON
 *   h("button", { onclick: save }, "Save")                -> a DOM element
 *   navigate("#/items/42")                                -> params = ["42"]
 *   ui.table({ columns, rows, search: true, drawer })     -> see ui.js for the kit
 */

import ui from "./ui.js";

const progress = document.getElementById("progress");
let inflight = 0;
function busy(delta) {
  inflight = Math.max(0, inflight + delta);
  if (!progress) return;
  if (inflight > 0) {
    progress.classList.remove("done");
    progress.classList.add("active");
  } else {
    progress.classList.remove("active");
    progress.classList.add("done");
  }
}

/** Call the backend: same-origin /api, JSON in and out, a real error on failure. */
export async function api(first, second, third) {
  let path = first;
  let options = second || {};
  if (typeof first === "string" && /^(GET|POST|PUT|PATCH|DELETE)$/i.test(first)) {
    // Also accept api("POST", "/items", body); models write it that way often enough.
    path = second;
    options = { method: first, body: third };
  }
  path = String(path || "/").trim();
  if (!path.startsWith("/")) path = `/${path}`;
  path = path.replace(/^\/api(?=\/|$)/, "") || "/"; // tolerate a repeated /api prefix
  const method = String(options.method || (options.body !== undefined ? "POST" : "GET")).toUpperCase();
  const init = { method, headers: { "Content-Type": "application/json", ...(options.headers || {}) } };
  if (options.body !== undefined) {
    init.body = typeof options.body === "string" ? options.body : JSON.stringify(options.body);
  }
  busy(1);
  try {
    const response = await fetch(`/api${path}`, init);
    const text = await response.text();
    if (!response.ok) {
      let detail = text;
      try {
        const parsed = JSON.parse(text);
        detail = JSON.stringify(parsed.detail ?? parsed);
      } catch {
        /* keep the raw text */
      }
      throw new Error(`${method} /api${path} failed with ${response.status}: ${detail}`);
    }
    if (!text) return null;
    try {
      return JSON.parse(text);
    } catch {
      return text;
    }
  } finally {
    busy(-1);
  }
}

export const h = ui.h;

export function navigate(hash) {
  location.hash = hash.startsWith("#") ? hash : `#${hash}`;
}

// Read by the platform's browser check, so a broken screen is found by the
// platform rather than by the stakeholder.
const state = (window.__poiesis = { ready: false, screens: [], errors: [], current: null });
const shell = document.getElementById("shell");
const app = document.getElementById("app");
const nav = document.getElementById("nav");
const crumbs = document.getElementById("crumbs");
const pageTitle = document.getElementById("page-title");
const pageSubtitle = document.getElementById("page-subtitle");
const pageActions = document.getElementById("page-actions");
let screens = [];
let token = 0;

function errorPanel(title, err) {
  const message = err && err.message ? err.message : String(err);
  state.errors.push(message);
  console.error(err);
  return h("div", { class: "poiesis-error", role: "alert" }, h("strong", {}, title), h("pre", {}, message));
}

function parseHash() {
  const parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
  return { id: parts[0] || "", params: parts.slice(1) };
}

function setHeader(entry, params) {
  const appName = pageTitle.dataset.app || document.title;
  pageTitle.textContent = entry ? entry.title : appName;
  const subtitle = entry && entry.module.subtitle;
  pageSubtitle.textContent = subtitle || "";
  pageSubtitle.hidden = !subtitle;
  pageActions.replaceChildren();
  crumbs.replaceChildren(...[
    h("a", { href: screens[0] ? `#/${screens[0].id}` : "#/" }, appName),
    entry ? [ui.icon("chevron-right"), entry.id !== (screens[0] && screens[0].id) || params.length
      ? h("a", { href: `#/${entry.id}` }, entry.title) : h("span", {}, entry.title)] : [],
    ...(params || []).map((p) => [ui.icon("chevron-right"), h("span", {}, `#${p}`)]),
  ].flat(Infinity));
  document.title = entry ? `${entry.title} · ${appName}` : appName;
}

async function show() {
  const mine = ++token;
  const { id, params } = parseHash();
  const entry = screens.find((s) => s.id === id) || screens[0];
  if (!entry) {
    setHeader(null, []);
    app.replaceChildren(ui.empty("No screens yet", "Screens appear here as stories are built."));
    state.current = { hash: location.hash, id: "", done: true };
    state.ready = true;
    return;
  }
  state.current = { hash: `#/${entry.id}`, id: entry.id, done: false };
  for (const link of nav.querySelectorAll("a")) link.classList.toggle("active", link.dataset.id === entry.id);
  setHeader(entry, params);

  const root = h("div", { class: "screen" });
  // A skeleton until the screen draws its first element: it replaces the blank
  // pause while data loads with the shape of what is coming.
  const skel = ui.skeleton();
  const stage = h("div", {}, skel, root);
  const observer = new MutationObserver(() => { if (root.childElementCount) { skel.remove(); observer.disconnect(); } });
  observer.observe(root, { childList: true });
  const swap = () => app.replaceChildren(stage);
  if (document.startViewTransition && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) document.startViewTransition(swap);
  else swap();
  window.scrollTo({ top: 0 });
  try {
    // `actions` lets a screen put its primary button in the page header, where a
    // real product keeps it, without knowing anything about the frame around it.
    await entry.module.render(root, { api, h, navigate, params, actions: pageActions, ui });
  } catch (err) {
    if (mine === token) root.replaceChildren(errorPanel(`${entry.title} hit an error`, err));
  }
  if (mine === token) {
    observer.disconnect();
    skel.remove();
    state.current.done = true;
    state.ready = true;
  }
}

/** Proves the whole chain — browser, nginx, API, Postgres — on page load. */
async function showConnectionState() {
  const el = document.getElementById("status");
  const text = el.querySelector(".status-text") || el;
  try {
    const { database } = await api("/status");
    el.dataset.state = "ok";
    text.textContent = "Live";
    el.title = `API reachable · database ${database}`;
  } catch (err) {
    el.dataset.state = "down";
    text.textContent = "API unreachable";
    el.title = err.message;
  }
}

/* --- command palette: screens and every record, one keystroke away ------------ */

let resourcesCache = null;
async function resources() {
  if (resourcesCache) return resourcesCache;
  try {
    const all = (await api("/resources")) || [];
    const real = all.filter((r) => r.table !== "example");
    resourcesCache = real.length ? real : all;
  } catch {
    resourcesCache = [];
  }
  return resourcesCache;
}

function recordTitle(row) {
  const keys = ["name", "full_name", "title", "subject", "label", "tag", "email", "model"];
  for (const k of keys) if (row[k]) return String(row[k]);
  const text = Object.entries(row).find(([k, v]) => typeof v === "string" && v.length > 2 && !k.endsWith("_at") && !/^\d{4}-\d\d/.test(v));
  return text ? String(text[1]) : `#${row.id}`;
}

function recordDrawer(table, row) {
  ui.drawer({
    title: recordTitle(row),
    subtitle: `${ui.label(table.table)} · #${row.id}`,
    icon: ui.guessIcon(table.table),
    content: ui.kv(Object.entries(row).filter(([k]) => k !== "id").map(([k, v]) => ({
      label: ui.label(k),
      value: v === null || v === undefined || v === "" ? "—"
        : (/_at$|_date$|^date$/.test(k) && !Number.isNaN(Date.parse(v))) ? `${ui.dateTime(v)} · ${ui.timeAgo(v)}`
          : (/status|state|priority|plan|tier/.test(k) ? ui.badge(v) : String(v)),
    }))),
  });
}

function openPalette() {
  if (document.querySelector(".palette")) return;
  const input = h("input", { type: "text", placeholder: "Search screens and records…", "aria-label": "Search" });
  const list = h("div", { class: "palette-list" });
  let items = [];
  let cursor = 0;
  let seq = 0;
  const m = ui.modal({
    title: "", content: h("div", {}), actions: [],
  });
  m.el.classList.add("palette");
  m.el.replaceChildren(
    h("div", { class: "palette-input" }, ui.icon("search"), input, h("kbd", {}, "Esc")),
    list,
    h("div", { class: "palette-foot" }, h("span", {}, h("kbd", {}, "↑"), " ", h("kbd", {}, "↓"), " to move"),
      h("span", {}, h("kbd", {}, "Enter"), " to open"), h("span", {}, h("kbd", {}, "?"), " shortcuts")),
  );
  const paint = () => {
    list.replaceChildren();
    if (!items.length) { list.append(h("div", { class: "palette-empty" }, "No matches")); return; }
    let group = null;
    items.forEach((it, i) => {
      if (it.group !== group) { group = it.group; list.append(h("div", { class: "palette-group" }, group)); }
      const row = h("div", { class: `palette-item${i === cursor ? " on" : ""}`, onmouseenter: () => { cursor = i; paint(); }, onclick: () => choose(i) },
        ui.icon(it.icon), h("span", {}, it.label), it.meta ? h("span", { class: "palette-meta" }, it.meta) : null);
      list.append(row);
      if (i === cursor) row.scrollIntoView({ block: "nearest" });
    });
  };
  const choose = (i) => {
    const it = items[i];
    if (!it) return;
    m.close();
    setTimeout(() => it.run(), 120);
  };
  const refresh = async () => {
    const q = input.value.trim().toLowerCase();
    const mine = ++seq;
    const screenHits = screens.filter((s) => !q || s.title.toLowerCase().includes(q))
      .map((s) => ({ group: "Screens", label: s.title, icon: s.icon, meta: s.story, run: () => navigate(`#/${s.id}`) }));
    const actionHits = [
      { group: "Actions", label: "Switch light / dark theme", icon: "moon", run: toggleTheme },
      { group: "Actions", label: "Keyboard shortcuts", icon: "keyboard", run: showShortcuts },
    ].filter((a) => !q || a.label.toLowerCase().includes(q));
    items = [...screenHits, ...actionHits];
    cursor = 0;
    paint();
    if (q.length < 2) return;
    const tables = (await resources()).slice(0, 8);
    const found = await Promise.all(tables.map(async (t) => {
      try {
        const rows = await api(`${t.path}?q=${encodeURIComponent(q)}&limit=4`);
        return (rows || []).map((r) => ({ group: `Records · ${ui.label(t.table)}`, label: recordTitle(r), icon: ui.guessIcon(t.table),
          meta: `#${r.id}`, run: () => recordDrawer(t, r) }));
      } catch {
        return [];
      }
    }));
    if (mine !== seq) return;
    items = [...screenHits, ...found.flat(), ...actionHits];
    paint();
  };
  let timer = null;
  input.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(refresh, 160); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { cursor = Math.min(items.length - 1, cursor + 1); paint(); e.preventDefault(); }
    else if (e.key === "ArrowUp") { cursor = Math.max(0, cursor - 1); paint(); e.preventDefault(); }
    else if (e.key === "Enter") { choose(cursor); e.preventDefault(); }
  });
  refresh();
  setTimeout(() => input.focus(), 30);
}

function showShortcuts() {
  const row = (keys, text) => [h("span", {}, text), h("span", {}, keys.map((k) => [h("kbd", {}, k), " "]))];
  ui.modal({
    title: "Keyboard shortcuts", icon: "keyboard",
    content: h("div", { class: "shortcuts" },
      row(["Ctrl", "K"], "Search screens and records"), row(["/"], "Search"),
      row(["↑", "↓", "Enter"], "Move through a table and open a row"),
      row(["g", "then 1–9"], "Go to the nth screen"), row(["t"], "Switch light / dark theme"),
      row(["["], "Collapse or expand the sidebar"), row(["Esc"], "Close a dialog or panel"), row(["?"], "This list")),
  });
}

/* --- theme, sidebar ---------------------------------------------------------- */

function currentTheme() {
  const set = document.documentElement.dataset.theme;
  if (set) return set;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}
function paintThemeButton() {
  const b = document.getElementById("theme-toggle");
  if (b) b.replaceChildren(ui.icon(currentTheme() === "dark" ? "sun" : "moon"));
}
function toggleTheme() {
  const next = currentTheme() === "dark" ? "light" : "dark";
  const apply = () => { document.documentElement.dataset.theme = next; paintThemeButton(); };
  if (document.startViewTransition) document.startViewTransition(apply); else apply();
  try { localStorage.setItem("theme", next); } catch { /* private mode */ }
}
function toggleSidebar() {
  shell.classList.toggle("collapsed");
  try { localStorage.setItem("sidebar", shell.classList.contains("collapsed") ? "collapsed" : "open"); } catch { /* private mode */ }
}

/* --- keyboard ------------------------------------------------------------------ */

let gPending = false;
document.addEventListener("keydown", (e) => {
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement && document.activeElement.tagName);
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); openPalette(); return; }
  if (typing || e.ctrlKey || e.metaKey || e.altKey || document.querySelector(".modal, .drawer")) return;
  if (e.key === "/") { e.preventDefault(); openPalette(); }
  else if (e.key === "?") { e.preventDefault(); showShortcuts(); }
  else if (e.key === "t") toggleTheme();
  else if (e.key === "[") toggleSidebar();
  else if (e.key === "g") { gPending = true; setTimeout(() => { gPending = false; }, 900); }
  else if (gPending && /^[1-9]$/.test(e.key)) {
    const s = screens[Number(e.key) - 1];
    if (s) navigate(`#/${s.id}`);
    gPending = false;
  }
});

// A ripple from where the button was pressed.
document.addEventListener("pointerdown", (e) => {
  const b = e.target.closest && e.target.closest("button");
  if (!b || b.disabled || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const r = b.getBoundingClientRect();
  const d = Math.max(r.width, r.height);
  const dot = h("span", { class: "ripple" });
  Object.assign(dot.style, { width: `${d}px`, height: `${d}px`, left: `${e.clientX - r.left - d / 2}px`, top: `${e.clientY - r.top - d / 2}px` });
  b.append(dot);
  setTimeout(() => dot.remove(), 620);
});

async function start() {
  pageTitle.dataset.app = document.title;
  document.getElementById("brand-mark").textContent = ui.initials(document.title);
  if (document.documentElement.dataset.sidebar === "collapsed") shell.classList.add("collapsed");
  document.getElementById("search-trigger").replaceChildren(ui.icon("search"), h("span", {}, "Search…"), h("kbd", {}, "Ctrl K"));
  document.getElementById("search-trigger").addEventListener("click", openPalette);
  document.getElementById("theme-toggle").addEventListener("click", toggleTheme);
  document.getElementById("collapse-toggle").replaceChildren(ui.icon("sidebar"));
  document.getElementById("collapse-toggle").addEventListener("click", toggleSidebar);
  paintThemeButton();
  showConnectionState();
  let registry = [];
  try {
    registry = (await import("./screens/index.js")).default || [];
  } catch (err) {
    app.replaceChildren(errorPanel("The screens could not be loaded", err));
    state.current = { hash: location.hash, id: "", done: true };
    state.ready = true;
    return;
  }
  screens = registry
    .filter((r) => r && ((r.module && typeof r.module.render === "function") || r.error))
    .map((r) => (r.error
      ? {
        // The file did not load (a syntax error, usually). Keep its place in the
        // navigation with a card that says so, so the fault is visible on its own
        // screen and every other screen still works.
        id: r.id,
        example: Boolean(r.example),
        title: r.id.replace(/[_-]+/g, " "),
        story: "",
        icon: "alert",
        broken: r.error,
        module: {
          title: r.id.replace(/[_-]+/g, " "),
          render(root) { root.append(errorPanel(`The ${r.id} screen failed to load`, new Error(r.error))); },
        },
      }
      : {
        id: r.id,
        example: Boolean(r.example),
        title: r.module.title || r.id,
        story: r.module.story || "",
        icon: r.module.icon || ui.guessIcon(`${r.module.title || ""} ${r.id}`),
        module: r.module,
      }));
  for (const s of screens) if (s.broken) state.errors.push(`screen ${s.id} failed to load: ${s.broken}`);
  state.screens = screens.map(({ id, title, story, example, broken }) => ({ id, title, story, example, broken: broken || "", hash: `#/${id}` }));
  nav.replaceChildren(
    h("div", { class: "nav-label" }, "Workspace"),
    ...screens.map((s) =>
      h("a", { href: `#/${s.id}`, "data-id": s.id, title: s.title },
        ui.icon(s.icon, { class: "nav-icon" }),
        h("span", { class: "nav-text" }, s.title))),
  );
  window.addEventListener("hashchange", show);
  await show();
}

// Errors from event handlers (a failed save, say) are shown where the user is looking.
window.addEventListener("unhandledrejection", (event) => {
  const err = event.reason;
  state.errors.push(err && err.message ? err.message : String(err));
  console.error(err);
  ui.toast(err && err.message ? err.message : String(err), "down");
});
window.addEventListener("error", (event) => {
  if (!event.error) return;
  state.errors.push(event.error.message || String(event.error));
  ui.toast(event.error.message || String(event.error), "down");
});

start();
