/* {{project_name}} — the application shell. Written by Poiesis, and read-only.
 *
 * Stories never edit this file. Each story adds its own screen as
 * frontend/screens/<resource>.js; the platform regenerates
 * frontend/screens/index.js to list them, and this shell loads them, draws the
 * navigation, routes between them and catches their errors.
 *
 * It exists because a story that rewrote the old single app.js deleted the
 * api() helper it then called: the page threw "api is not defined" on load and
 * showed nothing but the scaffold placeholder. A shell no story can touch cannot
 * lose its helpers, and one story's screen cannot overwrite another's.
 *
 * A screen module:
 *
 *   export default {
 *     title: "Leave requests",   // the navigation label
 *     story: "S1",               // the story (or "S1, S3") it delivers
 *     async render(root, { api, h, navigate, params }) { ... }
 *   };
 *
 *   api("/items")                                         GET /api/items -> JSON
 *   api("/items", { method: "POST", body: { name: "a" } }) -> JSON
 *   h("button", { onclick: save }, "Save")                -> a DOM element
 *   navigate("#/items/42")                                -> params = ["42"]
 */

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
}

/** Build a DOM element: h("a", { href: "#/x", onclick: go }, "Open"). */
export function h(tag, props, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class" || key === "className") el.className = value;
    else if (key === "style" && typeof value === "object") Object.assign(el.style, value);
    else if (key.startsWith("on") && typeof value === "function") el.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key === "value" || key === "checked" || key === "selected") el[key] = value;
    else if (value === true) el.setAttribute(key, "");
    else el.setAttribute(key, String(value));
  }
  for (const child of children.flat(Infinity)) {
    if (child === undefined || child === null || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

export function navigate(hash) {
  location.hash = hash.startsWith("#") ? hash : `#${hash}`;
}

// Read by the platform's browser check, so a broken screen is found by the
// platform rather than by the stakeholder.
const state = (window.__poiesis = { ready: false, screens: [], errors: [], current: null });
const app = document.getElementById("app");
const nav = document.getElementById("nav");
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

async function show() {
  const mine = ++token;
  const { id, params } = parseHash();
  const entry = screens.find((s) => s.id === id) || screens[0];
  if (!entry) {
    app.replaceChildren(
      h("section", { class: "panel" },
        h("h2", {}, "No screens yet"),
        h("p", { class: "muted" }, "Screens appear here as stories are built.")),
    );
    state.current = { hash: location.hash, id: "", done: true };
    state.ready = true;
    return;
  }
  state.current = { hash: `#/${entry.id}`, id: entry.id, done: false };
  for (const link of nav.querySelectorAll("a")) link.classList.toggle("active", link.dataset.id === entry.id);
  const root = h("div", { class: "screen" });
  app.replaceChildren(root);
  try {
    await entry.module.render(root, { api, h, navigate, params });
  } catch (err) {
    if (mine === token) root.replaceChildren(errorPanel(`${entry.title} hit an error`, err));
  }
  if (mine === token) {
    state.current.done = true;
    state.ready = true;
  }
}

/** Proves the whole chain — browser, nginx, API, Postgres — on page load. */
async function showConnectionState() {
  const el = document.getElementById("status");
  try {
    const { database } = await api("/status");
    el.dataset.state = "ok";
    el.textContent = `API ok · database ${database}`;
  } catch (err) {
    el.dataset.state = "down";
    el.textContent = `API unreachable — ${err.message}`;
  }
}

async function start() {
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
    .filter((r) => r && r.module && typeof r.module.render === "function")
    .map((r) => ({
      id: r.id,
      example: Boolean(r.example),
      title: r.module.title || r.id,
      story: r.module.story || "",
      module: r.module,
    }));
  state.screens = screens.map(({ id, title, story, example }) => ({ id, title, story, example, hash: `#/${id}` }));
  nav.replaceChildren(...screens.map((s) => h("a", { href: `#/${s.id}`, "data-id": s.id }, s.title)));
  nav.hidden = screens.length < 2;
  window.addEventListener("hashchange", show);
  await show();
}

// Errors from event handlers (a failed save, say) land on the page, not in the console alone.
window.addEventListener("unhandledrejection", (event) => app.prepend(errorPanel("Something went wrong", event.reason)));
window.addEventListener("error", (event) => {
  if (event.error) app.prepend(errorPanel("Something went wrong", event.error));
});

start();
