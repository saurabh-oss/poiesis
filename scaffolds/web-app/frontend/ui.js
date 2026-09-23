/* {{project_name}} — the UI kit. Written by Poiesis, and read-only.
 *
 * Screens receive this as `ui` in render(root, { api, h, navigate, params, actions, ui }).
 * Every component returns a DOM element built from the design system in
 * styles.css, so a screen composes finished parts instead of drawing tables and
 * badges by hand. Twelve screens written by twelve separate passes then look
 * like one product, and each one gets search, paging, sorting, keyboard
 * navigation, charts and empty states without writing them.
 *
 *   ui.stats([{ label: "Open tickets", value: 42, hint: "+6 today", tone: "warn" }])
 *   ui.table({ columns, rows, search: true, pageSize: 25, onRow: (row) => ... })
 *   ui.badge("P1")  ui.avatar("Priya Nair")  ui.person("Priya Nair", "Billing")
 *   ui.timeAgo(iso) ui.date(iso)  ui.kv([{ label, value }])  ui.bars([{ label, value }])
 *   ui.timeseries([{ label: "2024-03-01", value: 12 }])  ui.section("Title", ...children)
 *   ui.toolbar(...)  ui.search({ oninput })  ui.select({ options, onchange })
 *   ui.form({ fields, submit, onsubmit })  ui.button("Save", { onclick })
 *   ui.empty("No tickets", "Import a CSV to get started.")  ui.toast("Saved")
 */

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

/* --- text helpers ---------------------------------------------------------- */

const OK = /^(resolved|closed|done|complete(d)?|active|healthy|paid|approved|shipped|green|ok|success(ful)?|online|p4|low|free|monitoring)$/i;
const DOWN = /^(p1|critical|urgent|failed|failing|blocked|outage|error|overdue|down|red|rejected|escalated|breached|sev1|enterprise)$/i;
const WARN = /^(p2|open|new|pending|investigating|identified|in[ -_]progress|waiting|triaged|assigned|amber|warning|medium|high|business|sev2)$/i;

/** A tone for a status word: "ok", "warn", "down" or "" (neutral). */
export function tone(text) {
  const t = String(text ?? "").trim();
  if (OK.test(t)) return "ok";
  if (DOWN.test(t)) return "down";
  if (WARN.test(t)) return "warn";
  return "";
}

export function badge(text, forced) {
  const t = forced === undefined ? tone(text) : forced;
  return h("span", { class: `badge${t ? ` badge-${t}` : ""}` }, String(text ?? "—"));
}

export function initials(name) {
  const words = String(name || "?").trim().split(/\s+/).slice(0, 2);
  return words.map((w) => w[0]).join("").toUpperCase() || "?";
}

function hue(text) {
  let n = 0;
  for (const ch of String(text || "")) n = (n * 31 + ch.charCodeAt(0)) % 360;
  return n;
}

/** A circle of initials, coloured by the name so the same person always looks the same. */
export function avatar(name, opts = {}) {
  const el = h("span", { class: `avatar${opts.size === "lg" ? " avatar-lg" : ""}`, title: name || "" }, initials(name));
  el.style.setProperty("--avatar-h", String(hue(name)));
  return el;
}

/** Avatar plus name and an optional second line. */
export function person(name, sub) {
  return h("span", { class: "person" }, avatar(name),
    h("span", { class: "person-text" }, h("span", { class: "person-name" }, name || "Unassigned"),
      sub ? h("span", { class: "faint" }, sub) : null));
}

export function timeAgo(value) {
  const d = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(d.getTime())) return String(value ?? "");
  const s = Math.round((Date.now() - d.getTime()) / 1000);
  const abs = Math.abs(s);
  const unit = abs < 60 ? [abs, "s"] : abs < 3600 ? [Math.round(abs / 60), "m"] : abs < 86400 ? [Math.round(abs / 3600), "h"]
    : abs < 2592000 ? [Math.round(abs / 86400), "d"] : [Math.round(abs / 2592000), "mo"];
  const text = `${unit[0]}${unit[1]}`;
  return s >= 0 ? `${text} ago` : `in ${text}`;
}

export function date(value) {
  const d = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(d.getTime())) return String(value ?? "");
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

export function dateTime(value) {
  const d = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(d.getTime())) return String(value ?? "");
  return d.toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function number(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n.toLocaleString() : String(value ?? "—");
}

export function kbd(key) {
  return h("kbd", {}, key);
}

/* --- layout ---------------------------------------------------------------- */

/** A panel with a heading and, optionally, something on the right of it. */
export function section(title, ...children) {
  let right = null;
  if (children.length && children[0] && typeof children[0] === "object" && !(children[0] instanceof Node) && "right" in children[0]) {
    right = children.shift().right;
  }
  return h("section", { class: "panel stack" },
    title ? h("div", { class: "between" }, h("h2", {}, title), right) : null,
    ...children);
}

export function split(left, right) {
  return h("div", { class: "split" }, h("div", { class: "split-main stack" }, left), h("div", { class: "split-side stack" }, right));
}

export function toolbar(...children) {
  return h("div", { class: "toolbar" }, ...children);
}

export function stats(items) {
  return h("div", { class: "stats" }, (items || []).map((it) =>
    h("div", { class: `stat${it.tone ? ` stat-${it.tone}` : ""}` },
      h("div", { class: "stat-label" }, it.label),
      h("div", { class: "stat-value" }, typeof it.value === "number" ? number(it.value) : (it.value ?? "—")),
      it.hint ? h("div", { class: "stat-hint" }, it.hint) : null)));
}

export function empty(title, hint) {
  return h("div", { class: "empty-state" }, h("strong", {}, title || "Nothing here yet"), hint || "");
}

export function notice(text, kind) {
  return h("div", { class: `notice${kind ? ` notice-${kind}` : ""}` }, text);
}

/** Label/value pairs for a detail view. */
export function kv(pairs) {
  return h("dl", { class: "kv" }, (pairs || []).flatMap((p) => [
    h("dt", {}, p.label),
    h("dd", {}, p.value instanceof Node ? p.value : (p.value ?? "—")),
  ]));
}

export function button(label, opts = {}) {
  const cls = opts.tone && opts.tone !== "primary" ? opts.tone : "";
  return h("button", { type: opts.type || "button", class: cls || null, onclick: opts.onclick, disabled: opts.disabled, title: opts.title },
    label, opts.kbd ? [" ", kbd(opts.kbd)] : null);
}

let toastHost = null;
export function toast(text, kind) {
  if (!toastHost || !toastHost.isConnected) {
    toastHost = h("div", { class: "toasts", role: "status", "aria-live": "polite" });
    document.body.append(toastHost);
  }
  const el = h("div", { class: `toast${kind ? ` toast-${kind}` : ""}` }, text);
  toastHost.append(el);
  setTimeout(() => el.classList.add("toast-out"), 2600);
  setTimeout(() => el.remove(), 3000);
  return el;
}

/* --- inputs ---------------------------------------------------------------- */

export function search(opts = {}) {
  const input = h("input", { type: "search", class: "search", placeholder: opts.placeholder || "Search…",
    value: opts.value || "", oninput: opts.oninput, "aria-label": opts.placeholder || "Search" });
  return input;
}

export function select(opts = {}) {
  const el = h("select", { name: opts.name, onchange: opts.onchange, "aria-label": opts.label || opts.name || "Choose" },
    (opts.options || []).map((o) => {
      const value = typeof o === "object" ? o.value : o;
      const label = typeof o === "object" ? o.label : o;
      return h("option", { value, selected: String(value) === String(opts.value) }, label);
    }));
  return el;
}

/**
 * A form from a field list. Values arrive in onsubmit as an object; a thrown
 * error is shown under the buttons, a returned string as a success message.
 *
 *   ui.form({
 *     fields: [
 *       { name: "title", label: "Title", required: true },
 *       { name: "priority", label: "Priority", type: "select", options: ["P1","P2","P3","P4"], value: "P3" },
 *       { name: "body", label: "Details", type: "textarea", hint: "What the customer reported" },
 *     ],
 *     submit: "Create ticket",
 *     onsubmit: async (values) => { await api("/tickets", { method: "POST", body: values }); return "Created."; },
 *   })
 */
export function form(opts = {}) {
  const controls = {};
  const message = h("p", { class: "faint" });
  const submit = h("button", { type: "submit" }, opts.submit || "Save");
  const fieldsEl = h("div", { class: opts.inline ? "row" : "form-grid" },
    (opts.fields || []).map((f) => {
      let control;
      if (f.type === "select") control = select({ name: f.name, options: f.options || [], value: f.value, label: f.label });
      else if (f.type === "textarea") control = h("textarea", { name: f.name, placeholder: f.placeholder || "", required: f.required }, f.value || "");
      else control = h("input", { type: f.type || "text", name: f.name, placeholder: f.placeholder || "", required: f.required,
        value: f.value ?? "", min: f.min, max: f.max, step: f.step });
      controls[f.name] = control;
      return h("div", { class: "field" }, h("label", {}, f.label || f.name), control,
        f.hint ? h("span", { class: "hint" }, f.hint) : null);
    }));
  const el = h("form", { class: "stack", onsubmit: async (event) => {
    event.preventDefault();
    const values = {};
    for (const [name, control] of Object.entries(controls)) {
      const raw = control.value;
      const spec = (opts.fields || []).find((f) => f.name === name) || {};
      values[name] = spec.type === "number" ? (raw === "" ? null : Number(raw)) : raw;
    }
    submit.disabled = true;
    message.className = "faint";
    message.textContent = "";
    try {
      const result = opts.onsubmit ? await opts.onsubmit(values, el) : null;
      if (typeof result === "string") message.textContent = result;
      if (opts.reset !== false && result !== false) el.reset();
    } catch (err) {
      message.className = "error-text";
      message.textContent = err && err.message ? err.message : String(err);
    } finally {
      submit.disabled = false;
    }
  } }, fieldsEl, h("div", { class: "form-actions" }, submit, ...(opts.extra || []), message));
  el.controls = controls;
  return el;
}

/* --- table ----------------------------------------------------------------- */

function cellValue(row, col) {
  if (typeof col.render === "function") return col.render(row);
  const v = col.key ? row[col.key] : "";
  if (v === null || v === undefined) return h("span", { class: "faint" }, "—");
  return v;
}

function searchable(row) {
  return Object.values(row || {}).filter((v) => typeof v === "string" || typeof v === "number").join(" ").toLowerCase();
}

/**
 * A data table with search, sorting, paging, row selection and keyboard
 * navigation. Returns the element; call `.update(rows)` to redraw after a change.
 *
 *   const table = ui.table({
 *     columns: [
 *       { key: "subject", label: "Subject", render: (t) => h("strong", {}, t.subject) },
 *       { key: "customer", label: "Customer" },
 *       { key: "priority", label: "Priority", render: (t) => ui.badge(t.priority) },
 *       { key: "created_at", label: "Arrived", render: (t) => ui.timeAgo(t.created_at) },
 *     ],
 *     rows: tickets, search: true, pageSize: 25, keyboard: true,
 *     onRow: (t) => navigate(`#/tickets/${t.id}`),
 *     empty: { title: "No tickets", hint: "New tickets appear here as they arrive." },
 *   });
 *
 * With `keyboard: true`, ↑/↓ (or j/k) move the selection and Enter opens the
 * row; `onSelect(row)` fires as the selection moves, so a side panel can follow.
 */
export function table(opts = {}) {
  const columns = opts.columns || [];
  const pageSize = opts.pageSize || 25;
  let all = opts.rows || [];
  let query = "";
  let page = 0;
  let sortKey = opts.sort ? opts.sort.key : null;
  let sortDir = opts.sort && opts.sort.dir === "desc" ? -1 : 1;
  let selected = -1;

  const tbody = h("tbody");
  const count = h("span", { class: "faint" });
  const pager = h("div", { class: "pager" });
  const emptyEl = h("div", { class: "empty-state", hidden: true },
    h("strong", {}, (opts.empty && opts.empty.title) || "Nothing to show"), (opts.empty && opts.empty.hint) || "");
  const wrap = h("div", { class: "table-wrap", tabindex: opts.keyboard ? 0 : null, role: opts.keyboard ? "listbox" : null });

  const thead = h("thead", {}, h("tr", {}, columns.map((c) =>
    h("th", { class: `${c.align === "right" ? "right" : ""}${c.key && opts.sortable !== false ? " sortable" : ""}`,
      onclick: c.key && opts.sortable !== false ? () => { if (sortKey === c.key) sortDir = -sortDir; else { sortKey = c.key; sortDir = 1; } draw(); } : null },
      c.label, c.key && opts.sortable !== false ? h("span", { class: "sort-mark" }) : null))));

  function visible() {
    let rows = all;
    if (query) rows = rows.filter((r) => searchable(r).includes(query));
    if (typeof opts.filter === "function") rows = rows.filter(opts.filter);
    if (sortKey) {
      rows = [...rows].sort((a, b) => {
        const x = a[sortKey], y = b[sortKey];
        if (x === y) return 0;
        if (x === null || x === undefined) return 1;
        if (y === null || y === undefined) return -1;
        return (x > y ? 1 : -1) * sortDir;
      });
    }
    return rows;
  }

  function draw() {
    const rows = visible();
    const pages = Math.max(1, Math.ceil(rows.length / pageSize));
    if (page >= pages) page = pages - 1;
    const start = page * pageSize;
    const slice = rows.slice(start, start + pageSize);
    for (const th of thead.querySelectorAll("th")) {
      const col = columns[[...thead.querySelectorAll("th")].indexOf(th)];
      const mark = th.querySelector(".sort-mark");
      if (mark) mark.textContent = col && col.key === sortKey ? (sortDir > 0 ? " ↑" : " ↓") : "";
    }
    tbody.replaceChildren(...slice.map((row, i) =>
      h("tr", { class: `${opts.onRow || opts.keyboard ? "clickable" : ""}${i === selected ? " selected" : ""}`,
        "aria-selected": i === selected ? "true" : null,
        onclick: () => { selected = i; if (opts.onSelect) opts.onSelect(row); if (opts.onRow) opts.onRow(row); else draw(); } },
        columns.map((c) => h("td", { class: `${c.mono ? "mono" : ""}${c.align === "right" ? " right" : ""}` }, cellValue(row, c))))));
    const none = rows.length === 0;
    wrap.hidden = none;
    emptyEl.hidden = !none;
    if (none && query) emptyEl.replaceChildren(h("strong", {}, "No matches"), `Nothing matches "${query}".`);
    else if (none) emptyEl.replaceChildren(h("strong", {}, (opts.empty && opts.empty.title) || "Nothing to show"), (opts.empty && opts.empty.hint) || "");
    count.textContent = none ? "" : `${start + 1}–${Math.min(rows.length, start + pageSize)} of ${number(rows.length)}`;
    pager.replaceChildren(
      pages > 1 ? h("button", { class: "ghost", disabled: page === 0, onclick: () => { page -= 1; selected = -1; draw(); } }, "‹ Prev") : null,
      pages > 1 ? h("span", { class: "faint" }, `Page ${page + 1} of ${pages}`) : null,
      pages > 1 ? h("button", { class: "ghost", disabled: page >= pages - 1, onclick: () => { page += 1; selected = -1; draw(); } }, "Next ›") : null);
    return slice;
  }

  const searchEl = opts.search ? search({ placeholder: opts.searchPlaceholder || "Search…", oninput: (e) => { query = e.target.value.trim().toLowerCase(); page = 0; selected = -1; draw(); } }) : null;
  const head = h("div", { class: "toolbar" }, searchEl, ...(opts.tools || []), h("span", { class: "toolbar-right" }, count));

  if (opts.keyboard) {
    wrap.addEventListener("keydown", (e) => {
      const rows = visible();
      const start = page * pageSize;
      const slice = rows.slice(start, start + pageSize);
      if (!slice.length) return;
      if (e.key === "ArrowDown" || e.key === "j") { selected = Math.min(slice.length - 1, selected + 1); e.preventDefault(); }
      else if (e.key === "ArrowUp" || e.key === "k") { selected = Math.max(0, selected - 1); e.preventDefault(); }
      else if (e.key === "Enter" && selected >= 0) { if (opts.onRow) opts.onRow(slice[selected]); e.preventDefault(); return; }
      else return;
      draw();
      const tr = tbody.children[selected];
      if (tr) tr.scrollIntoView({ block: "nearest" });
      if (opts.onSelect) opts.onSelect(slice[selected]);
    });
  }

  const el = h("div", { class: "stack table-kit" }, head, h("div", { class: "table-wrap-outer" }, wrap, emptyEl), pager);
  wrap.append(h("table", {}, thead, tbody));
  el.update = (rows) => { all = rows || []; draw(); };
  el.selected = () => { const rows = visible(); return rows[page * pageSize + selected] || null; };
  el.focus = () => wrap.focus();
  draw();
  return el;
}

/* --- charts ---------------------------------------------------------------- */

/** Horizontal bars: [{ label, value, tone? }], longest bar fills the width. */
export function bars(items, opts = {}) {
  const max = opts.max || Math.max(1, ...(items || []).map((i) => Number(i.value) || 0));
  return h("div", { class: "bars" }, (items || []).map((it) => {
    const v = Number(it.value) || 0;
    const fill = h("span", { class: `bar-fill${it.tone ? ` bar-${it.tone}` : ""}` });
    fill.style.width = `${Math.max(2, Math.round((v / max) * 100))}%`;
    return h("div", { class: "bar" },
      h("span", { class: "bar-label" }, it.label),
      h("span", { class: "bar-track" }, fill),
      h("span", { class: "bar-value mono" }, opts.format ? opts.format(v) : number(v)));
  }));
}

/** Columns over time: [{ label: "2024-03-01", value: 12 }] in order. Pure SVG. */
export function timeseries(points, opts = {}) {
  const pts = points || [];
  const W = 640, H = opts.height || 160, pad = 24;
  const max = Math.max(1, ...pts.map((p) => Number(p.value) || 0));
  const n = Math.max(1, pts.length);
  const gap = 2;
  const bw = Math.max(2, (W - pad * 2) / n - gap);
  const svgNS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(svgNS, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("class", "chart");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", opts.label || "Chart");
  const base = H - pad;
  const axis = document.createElementNS(svgNS, "line");
  axis.setAttribute("x1", pad); axis.setAttribute("x2", W - pad); axis.setAttribute("y1", base); axis.setAttribute("y2", base);
  axis.setAttribute("class", "chart-axis");
  svg.append(axis);
  pts.forEach((p, i) => {
    const v = Number(p.value) || 0;
    const hgt = Math.round(((base - pad) * v) / max);
    const rect = document.createElementNS(svgNS, "rect");
    rect.setAttribute("x", pad + i * (bw + gap));
    rect.setAttribute("y", base - hgt);
    rect.setAttribute("width", bw);
    rect.setAttribute("height", hgt);
    rect.setAttribute("rx", 2);
    rect.setAttribute("class", "chart-col");
    const title = document.createElementNS(svgNS, "title");
    title.textContent = `${p.label}: ${number(v)}`;
    rect.append(title);
    svg.append(rect);
  });
  const first = pts[0] ? String(pts[0].label) : "";
  const last = pts[pts.length - 1] ? String(pts[pts.length - 1].label) : "";
  return h("div", { class: "chart-wrap" }, svg,
    h("div", { class: "between faint" }, h("span", {}, first), h("span", {}, `peak ${number(max)}`), h("span", {}, last)));
}

const ui = {
  h, tone, badge, initials, avatar, person, timeAgo, date, dateTime, number, kbd,
  section, split, toolbar, stats, empty, notice, kv, button, toast,
  search, select, form, table, bars, timeseries,
};
export default ui;
