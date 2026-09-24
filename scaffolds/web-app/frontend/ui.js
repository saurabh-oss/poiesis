/* {{project_name}} — the UI kit. Written by Poiesis, and read-only.
 *
 * Screens receive this as `ui` in render(root, { api, h, navigate, params, actions, ui }).
 * Every component returns a DOM element built on the design system in styles.css,
 * already animated, keyboard-friendly and dark-mode aware. A screen composes
 * these; it never draws a table, a chart or a dialog by hand. See
 * screens/example.js for all of it working together.
 *
 *   Layout      hero, section, split, toolbar, tabs, profile
 *   Numbers     stats (count-up, delta, sparkline), ring, meter, donut, bars, timeseries, line, sparkline
 *   Data        table (search, filters, sort, paging, keyboard, CSV export, drawer per row), kanban, timeline, kv
 *   Actions     button, segmented, chips, search, select, form, formModal, modal, confirm, drawer
 *   Feedback    toast, celebrate, notice, empty, badge, skeleton
 *   Text        icon, avatar, avatarGroup, person, timeAgo, date, dateTime, number, money, percent, kbd
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

const SVG_NS = "http://www.w3.org/2000/svg";
function s(tag, attrs, ...children) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else el.setAttribute(k, String(v));
  }
  for (const c of children.flat(Infinity)) if (c !== undefined && c !== null && c !== false) el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return el;
}

const reduced = () => typeof window !== "undefined" && window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const raf = (fn) => (typeof requestAnimationFrame === "function" ? requestAnimationFrame(() => requestAnimationFrame(fn)) : setTimeout(fn, 16));

/* --- icons ------------------------------------------------------------------ */

export const ICONS = {
  home: "M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z",
  dashboard: "M3 3h8v8H3zM13 3h8v5h-8zM13 10h8v11h-8zM3 13h8v8H3z",
  users: "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75",
  user: "M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8",
  box: "M21 8 12 3 3 8v8l9 5 9-5zM3 8l9 5 9-5M12 13v8",
  laptop: "M4 5h16v11H4zM2 20h20",
  phone: "M7 2h10a1 1 0 0 1 1 1v18a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1zM11 18h2",
  monitor: "M3 4h18v12H3zM8 20h8M12 16v4",
  key: "M15.5 7.5a4.5 4.5 0 1 1-4.3 5.8L3 21.5V18h3v-3h3l2.2-2.2A4.5 4.5 0 0 1 15.5 7.5zM16.5 7.5h.01",
  wrench: "M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.4-.6-.6-2.4z",
  shield: "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z",
  alert: "M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0zM12 9v4M12 17h.01",
  check: "M20 6 9 17l-5-5",
  "check-circle": "M22 11.1V12a10 10 0 1 1-5.9-9.1M22 4 12 14l-3-3",
  x: "M18 6 6 18M6 6l12 12",
  plus: "M12 5v14M5 12h14",
  search: "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.3-4.3",
  filter: "M22 3H2l8 9.5V19l4 2v-8.5z",
  download: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3",
  upload: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12",
  calendar: "M3 5h18v16H3zM16 3v4M8 3v4M3 10h18",
  clock: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 6v6l4 2",
  chart: "M3 3v18h18M8 17v-7M13 17V6M18 17v-4",
  pie: "M21.2 15.9A10 10 0 1 1 8 2.8M22 12A10 10 0 0 0 12 2v10z",
  "trend-up": "M22 7 13.5 15.5l-5-5L2 17M16 7h6v6",
  "trend-down": "M22 17l-8.5-8.5-5 5L2 7M16 17h6v-6",
  inbox: "M22 12h-6l-2 3h-4l-2-3H2M5.5 5.1 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.5-6.9A2 2 0 0 0 16.8 4H7.2a2 2 0 0 0-1.7 1.1z",
  tag: "M20.6 13.4 13.4 20.6a2 2 0 0 1-2.8 0L2 12V2h10l8.6 8.6a2 2 0 0 1 0 2.8zM7 7h.01",
  pin: "M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0zM12 13a3 3 0 1 0 0-6 3 3 0 0 0 0 6",
  building: "M4 22V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v18M16 9h2a2 2 0 0 1 2 2v11M2 22h20M8 6h4M8 10h4M8 14h4M8 18h4",
  mail: "M4 4h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2zM22 6l-10 7L2 6",
  settings: "M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6",
  refresh: "M21 12a9 9 0 1 1-2.6-6.4L21 8M21 3v5h-5",
  "arrow-right": "M5 12h14M12 5l7 7-7 7",
  "chevron-right": "M9 18l6-6-6-6",
  "chevron-down": "M6 9l6 6 6-6",
  eye: "M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6",
  edit: "M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z",
  trash: "M3 6h18M8 6V4h8v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6",
  star: "M12 2l3.1 6.3 6.9 1-5 4.9 1.2 6.8L12 17.8 5.8 21l1.2-6.8-5-4.9 6.9-1z",
  bolt: "M13 2 3 14h9l-1 8 10-12h-9z",
  sparkles: "M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9zM19 15l.9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9zM5 3l.6 1.4L7 5l-1.4.6L5 7l-.6-1.4L3 5l1.4-.6z",
  list: "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
  grid: "M3 3h7v7H3zM14 3h7v7h-7zM14 14h7v7h-7zM3 14h7v7H3z",
  kanban: "M3 3h18v18H3zM9 3v18M15 3v18",
  history: "M3 12a9 9 0 1 0 3-6.7L3 8M3 3v5h5M12 7v5l4 2",
  link: "M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7",
  sun: "M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10zM12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4",
  moon: "M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z",
  command: "M18 3a3 3 0 0 0-3 3v12a3 3 0 1 0 3-3H6a3 3 0 1 0 3 3V6a3 3 0 1 0-3 3h12a3 3 0 0 0 0-6z",
  file: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M8 13h8M8 17h5",
  dollar: "M12 1v22M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6",
  activity: "M22 12h-4l-3 9L9 3l-3 9H2",
  layers: "M12 2 2 7l10 5 10-5zM2 17l10 5 10-5M2 12l10 5 10-5",
  ticket: "M2 9a3 3 0 0 0 0 6v3a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-3a3 3 0 0 0 0-6V6a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2zM13 5v2M13 17v2M13 11v2",
  flag: "M4 22V4s1-1 4-1 5 2 8 2 4-1 4-1v11s-1 1-4 1-5-2-8-2-4 1-4 1",
  bell: "M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 0 1-3.4 0",
  info: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 16v-4M12 8h.01",
  sidebar: "M3 3h18v18H3zM9 3v18",
  truck: "M1 3h15v13H1zM16 8h4l3 3v5h-7zM5.5 21a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM18.5 21a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z",
  cart: "M9 22a1 1 0 1 0 0-2 1 1 0 0 0 0 2zM20 22a1 1 0 1 0 0-2 1 1 0 0 0 0 2zM1 1h4l2.7 13.4a2 2 0 0 0 2 1.6h9.7a2 2 0 0 0 2-1.6L23 6H6",
  heart: "M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8z",
  globe: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM2 12h20M12 2a15 15 0 0 1 0 20 15 15 0 0 1 0-20",
  server: "M2 2h20v8H2zM2 14h20v8H2zM6 6h.01M6 18h.01",
  database: "M12 8c5 0 9-1.3 9-3s-4-3-9-3-9 1.3-9 3 4 3 9 3zM21 12c0 1.7-4 3-9 3s-9-1.3-9-3M3 5v14c0 1.7 4 3 9 3s9-1.3 9-3V5",
  keyboard: "M2 6h20v12H2zM6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 14h10",
  logout: "M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9",
};

export function icon(name, opts = {}) {
  const d = ICONS[name] || ICONS[guessIcon(name)] || ICONS.layers;
  const size = opts.size || 18;
  return s("svg", { viewBox: "0 0 24 24", width: size, height: size, fill: "none", stroke: "currentColor",
    "stroke-width": opts.stroke || 2, "stroke-linecap": "round", "stroke-linejoin": "round",
    class: opts.class || "icon", "aria-hidden": "true" }, s("path", { d }));
}

const ICON_WORDS = [
  [/dashboard|overview|home|summary|insight/, "dashboard"], [/metric|report|analytic|kpi|weekly|trend|stat/, "chart"],
  [/leaver|exit|offboard/, "logout"], [/employee|user|staff|people|agent|customer|member|team|directory|contact/, "users"],
  [/laptop|computer/, "laptop"], [/phone|mobile/, "phone"], [/monitor|screen/, "monitor"],
  [/licen|key|subscription|seat/, "key"], [/repair|maint|fix|service/, "wrench"],
  [/warrant|secur|complian|audit|policy|refresh/, "shield"], [/incident|alert|risk|overdue|escalat/, "alert"],
  [/ticket|request|case/, "ticket"], [/queue|triage|inbox/, "inbox"], [/duplicate|link|relat/, "link"],
  [/assign|check.?out|check.?in|hand/, "arrow-right"], [/history|log|timeline|activity/, "history"],
  [/calendar|shift|schedule|leave|booking/, "calendar"], [/order|cart|purchase|procure/, "cart"],
  [/invoice|billing|payment|financ|cost|budget|price|revenue/, "dollar"], [/setting|config|admin/, "settings"],
  [/board|kanban|pipeline|workflow/, "kanban"], [/location|site|office|warehouse|map/, "pin"],
  [/vendor|supplier|compan|organi|account/, "building"], [/mail|message|notif/, "mail"],
  [/import|upload/, "upload"], [/export|download/, "download"], [/asset|inventor|stock|item|product|device|equipment/, "box"],
  [/ship|deliver|freight|truck|fleet/, "truck"], [/server|infra|system/, "server"], [/data|record/, "database"],
];

/** An icon name for a screen or section title ("Software licences" -> "key"). */
export function guessIcon(text) {
  const t = String(text || "").toLowerCase();
  for (const [re, name] of ICON_WORDS) if (re.test(t)) return name;
  return "layers";
}

let defsDone = false;
function ensureDefs() {
  if (defsDone || typeof document === "undefined" || !document.body) return;
  defsDone = true;
  const stop = (offset, color, opacity = 1) => s("stop", { offset, style: { stopColor: color, stopOpacity: opacity } });
  document.body.append(s("svg", { width: 0, height: 0, style: { position: "absolute" }, "aria-hidden": "true" },
    s("defs", {},
      s("linearGradient", { id: "poiesis-grad-v", x1: 0, y1: 0, x2: 0, y2: 1 }, stop("0%", "var(--accent-2)"), stop("100%", "var(--accent)")),
      s("linearGradient", { id: "poiesis-grad-h", x1: 0, y1: 0, x2: 1, y2: 0 }, stop("0%", "var(--accent)"), stop("60%", "var(--accent-2)"), stop("100%", "var(--accent-3)")),
      s("linearGradient", { id: "poiesis-grad-area", x1: 0, y1: 0, x2: 0, y2: 1 }, stop("0%", "var(--accent)", 0.32), stop("100%", "var(--accent)", 0)))));
}

/* --- text helpers ---------------------------------------------------------- */

const OK = /^(resolved|closed|done|complete(d)?|active|healthy|paid|approved|shipped|green|ok|success(ful)?|online|p4|low|free|monitoring|in.?stock|available|returned|delivered|won)$/i;
const DOWN = /^(p1|critical|urgent|failed|failing|blocked|outage|error|overdue|down|red|rejected|escalated|breached|sev1|lost|expired|leaver|cancelled|lost deal)$/i;
const WARN = /^(p2|open|new|pending|investigating|identified|in.?progress|waiting|triaged|assigned|amber|warning|medium|high|sev2|in.?repair|expiring|due|review|draft|on.?hold|with.?vendor)$/i;
const INFO = /^(p3|info|scheduled|planned|business|enterprise|pro|retired)$/i;

/** A tone for a status word: "ok", "warn", "down", "info" or "" (neutral). */
export function tone(text) {
  const t = String(text ?? "").trim().replace(/_/g, " ");
  if (OK.test(t)) return "ok";
  if (DOWN.test(t)) return "down";
  if (WARN.test(t)) return "warn";
  if (INFO.test(t)) return "info";
  return "";
}

export function label(text) {
  const t = String(text ?? "").replace(/_/g, " ").trim();
  return t && t === t.toLowerCase() ? t.charAt(0).toUpperCase() + t.slice(1) : t;
}

export function badge(text, forced) {
  const t = forced === undefined ? tone(text) : forced;
  return h("span", { class: `badge${t ? ` badge-${t}` : ""}` }, text === null || text === undefined || text === "" ? "—" : label(text));
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
  const el = h("span", { class: `avatar${opts.size ? ` avatar-${opts.size}` : ""}`, title: name || "" }, initials(name));
  el.style.setProperty("--avatar-h", String(hue(name)));
  return el;
}

export function avatarGroup(names, max = 4) {
  const list = (names || []).filter(Boolean);
  const shown = list.slice(0, max).map((n) => { const a = avatar(n); a.setAttribute("data-tip", n); return a; });
  if (list.length > max) shown.push(h("span", { class: "avatar", style: { background: "var(--surface-3)", color: "var(--muted)" } }, `+${list.length - max}`));
  return h("span", { class: "avatar-group" }, shown);
}

/** Avatar plus name and an optional second line. */
export function person(name, sub) {
  return h("span", { class: "person" }, avatar(name),
    h("span", { class: "person-text" }, h("span", { class: "person-name" }, name || "Unassigned"),
      sub ? h("span", { class: "faint" }, sub) : null));
}

function toDate(value) {
  if (value instanceof Date) return value;
  if (value === null || value === undefined || value === "") return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function timeAgo(value) {
  const d = toDate(value);
  if (!d) return "—";
  const secs = Math.round((Date.now() - d.getTime()) / 1000);
  const abs = Math.abs(secs);
  const unit = abs < 60 ? [abs, "s"] : abs < 3600 ? [Math.round(abs / 60), "m"] : abs < 86400 ? [Math.round(abs / 3600), "h"]
    : abs < 2592000 ? [Math.round(abs / 86400), "d"] : abs < 31536000 ? [Math.round(abs / 2592000), "mo"] : [Math.round(abs / 31536000), "y"];
  const text = `${unit[0]}${unit[1]}`;
  return secs >= 0 ? `${text} ago` : `in ${text}`;
}

export function date(value) {
  const d = toDate(value);
  return d ? d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "—";
}

export function dateTime(value) {
  const d = toDate(value);
  return d ? d.toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "—";
}

export function number(value, digits) {
  const n = Number(value);
  if (value === null || value === undefined || value === "" || !Number.isFinite(n)) return "—";
  return n.toLocaleString(undefined, digits === undefined ? {} : { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function money(value, currency = "USD") {
  const n = Number(value);
  if (value === null || value === undefined || value === "" || !Number.isFinite(n)) return "—";
  return n.toLocaleString(undefined, { style: "currency", currency, maximumFractionDigits: Math.abs(n) >= 1000 ? 0 : 2 });
}

export function percent(value, digits = 0) {
  const n = Number(value);
  if (value === null || value === undefined || value === "" || !Number.isFinite(n)) return "—";
  return `${n.toFixed(digits)}%`;
}

export function kbd(key) {
  return h("kbd", {}, key);
}

/** Count a number up from zero: "87%", "$12,400" and "4.2h" keep their prefix and suffix. */
export function countUp(el, value, ms = 800) {
  const text = String(value ?? "");
  const m = text.match(/^([^\d-]*)(-?[\d,]*\.?\d+)(.*)$/);
  if (!m || reduced()) { el.textContent = text || "—"; return el; }
  const [, pre, numText, post] = m;
  const target = Number(numText.replace(/,/g, ""));
  if (!Number.isFinite(target)) { el.textContent = text; return el; }
  const decimals = (numText.split(".")[1] || "").length;
  const grouped = numText.includes(",") || Math.abs(target) >= 1000;
  const fmt = (n) => (grouped ? n.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals }) : n.toFixed(decimals));
  const t0 = performance.now();
  const step = (now) => {
    const p = Math.min(1, (now - t0) / ms);
    const eased = 1 - Math.pow(1 - p, 3);
    el.textContent = `${pre}${fmt(target * eased)}${post}`;
    if (p < 1) requestAnimationFrame(step);
  };
  el.textContent = `${pre}${fmt(0)}${post}`;
  requestAnimationFrame(step);
  return el;
}

/* --- layout ---------------------------------------------------------------- */

/** A panel with a heading: ui.section("Open incidents", { right: node, icon: "alert" }, ...children). */
export function section(title, ...children) {
  let opts = {};
  if (children.length && children[0] && typeof children[0] === "object" && !(children[0] instanceof Node) && !Array.isArray(children[0])) {
    opts = children.shift();
  }
  const iconName = opts.icon === undefined ? null : (opts.icon === true ? guessIcon(title) : opts.icon);
  return h("section", { class: "panel stack" },
    title ? h("div", { class: "section-head" }, h("h2", {}, iconName ? icon(iconName) : null, title), opts.right || null) : null,
    ...children);
}

export function split(left, right) {
  return h("div", { class: "split" }, h("div", { class: "split-main stack" }, left), h("div", { class: "split-side stack" }, right));
}

export function toolbar(...children) {
  return h("div", { class: "toolbar" }, ...children);
}

/** The banner a dashboard opens with. */
export function hero(opts = {}) {
  const statsEl = (opts.stats || []).length
    ? h("div", { class: "hero-stats" }, opts.stats.map((st) => {
      const b = h("b");
      countUp(b, st.value);
      return h("div", { class: "hero-stat" }, b, h("span", {}, st.label));
    }))
    : null;
  return h("section", { class: "hero" },
    h("div", { class: "hero-body" },
      h("div", {},
        opts.eyebrow ? h("div", { class: "hero-eyebrow" }, icon(opts.icon || "sparkles"), opts.eyebrow) : null,
        h("h2", {}, opts.title || ""),
        opts.subtitle ? h("p", {}, opts.subtitle) : null),
      (opts.actions || []).length ? h("div", { class: "hero-actions" }, opts.actions) : null),
    statsEl);
}

/** A record's header: big avatar or icon, name, subtitle, badges. */
export function profile(opts = {}) {
  const mark = opts.icon
    ? h("div", { class: "modal-icon", style: { width: "56px", height: "56px", borderRadius: "16px" } }, icon(opts.icon, { size: 26 }))
    : avatar(opts.name, { size: "xl" });
  return h("div", { class: "profile" }, mark,
    h("div", {}, h("h2", {}, opts.name || "—"), opts.subtitle ? h("div", { class: "muted" }, opts.subtitle) : null,
      (opts.badges || []).length ? h("div", { class: "profile-meta" }, opts.badges) : null),
    (opts.actions || []).length ? h("div", { class: "row", style: { marginLeft: "auto" } }, opts.actions) : null);
}

/* --- numbers ----------------------------------------------------------------- */

function deltaEl(delta) {
  if (delta === undefined || delta === null || delta === "") return null;
  const n = typeof delta === "number" ? delta : Number(String(delta).replace(/[^\d.-]/g, ""));
  const dir = !Number.isFinite(n) || n === 0 ? "flat" : n > 0 ? "up" : "down";
  const text = typeof delta === "number" ? `${n > 0 ? "+" : ""}${n}%` : String(delta);
  return h("span", { class: `delta delta-${dir}` }, dir === "flat" ? null : icon(dir === "up" ? "trend-up" : "trend-down"), text);
}

/** Headline numbers: [{ label, value, hint, tone, icon, delta: 12 | "-3%", spark: [numbers], onClick }]. */
export function stats(items) {
  return h("div", { class: "stats" }, (items || []).map((it) => {
    const value = h("div", { class: "stat-value" });
    countUp(value, typeof it.value === "number" ? number(it.value) : (it.value ?? "—"));
    const iconName = it.icon === undefined ? guessIcon(it.label) : it.icon;
    return h("div", { class: `stat${it.tone ? ` stat-${it.tone}` : ""}${it.onClick ? " interactive" : ""}`, onclick: it.onClick },
      h("div", { class: "stat-top" }, iconName ? h("span", { class: "stat-icon" }, icon(iconName)) : null,
        h("span", { class: "stat-label" }, it.label)),
      value,
      h("div", { class: "stat-foot" },
        h("span", { class: "row", style: { gap: "6px" } }, deltaEl(it.delta), it.hint ? h("span", { class: "stat-hint" }, it.hint) : null),
        (it.spark || []).length > 1 ? sparkline(it.spark, { tone: it.tone }) : null));
  }));
}

/** A tiny trend line: ui.sparkline([3, 5, 4, 8, 7, 11]). */
export function sparkline(values, opts = {}) {
  ensureDefs();
  const vals = (values || []).map(Number).filter(Number.isFinite);
  const W = opts.width || 92, H = opts.height || 28;
  if (vals.length < 2) return s("svg", { class: "sparkline", viewBox: `0 0 ${W} ${H}` });
  const min = Math.min(...vals), max = Math.max(...vals);
  const span = max - min || 1;
  const pts = vals.map((v, i) => [(i / (vals.length - 1)) * W, H - 3 - ((v - min) / span) * (H - 6)]);
  const d = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
  let len = 0;
  for (let i = 1; i < pts.length; i++) len += Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
  const color = opts.tone === "down" ? "var(--down-2)" : opts.tone === "ok" ? "var(--ok-2)" : opts.tone === "warn" ? "var(--warn-2)" : "var(--accent)";
  return s("svg", { class: "sparkline", viewBox: `0 0 ${W} ${H}`, width: W, height: H, preserveAspectRatio: "none" },
    s("path", { class: "chart-area", d: `${d} L${W},${H} L0,${H} Z` }),
    s("path", { class: "chart-line", d, style: { "--len": Math.ceil(len), stroke: color } }));
}

/** A progress ring: ui.ring(72, { label: "Utilised" }). */
export function ring(value, opts = {}) {
  ensureDefs();
  const size = opts.size || 120, stroke = opts.stroke || 10, r = (size - stroke) / 2, c = 2 * Math.PI * r;
  const pct = Math.max(0, Math.min(100, Number(value) || 0));
  const arc = s("circle", { class: "ring-value", cx: size / 2, cy: size / 2, r, "stroke-width": stroke, "stroke-dasharray": c, "stroke-dashoffset": c });
  raf(() => arc.setAttribute("stroke-dashoffset", String(c * (1 - pct / 100))));
  const b = h("b");
  countUp(b, `${Math.round(pct)}%`);
  return h("div", { class: "ring", style: { width: `${size}px`, height: `${size}px` } },
    s("svg", { width: size, height: size, viewBox: `0 0 ${size} ${size}` },
      s("circle", { class: "ring-track", cx: size / 2, cy: size / 2, r, "stroke-width": stroke }), arc),
    h("div", { class: "ring-label" }, b, opts.label ? h("span", {}, opts.label) : null));
}

/** A horizontal progress meter with its percentage: ui.meter(357, 400, { tone: "warn" }). */
export function meter(value, max = 100, opts = {}) {
  const pct = max ? Math.max(0, Math.min(100, (Number(value) / Number(max)) * 100)) : 0;
  const fill = h("span");
  raf(() => { fill.style.width = `${pct}%`; });
  const t = opts.tone || (opts.auto ? (pct >= 90 ? "ok" : pct >= 60 ? "warn" : "down") : "");
  return h("div", { class: "meter-row" }, h("div", { class: `meter${t ? ` ${t}` : ""}` }, fill),
    opts.hideLabel ? null : h("span", { class: "faint" }, `${Math.round(pct)}%`));
}

const PALETTE = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)", "var(--chart-5)", "var(--chart-6)", "var(--chart-7)", "var(--chart-8)"];
const TONE_COLOR = { ok: "var(--ok-2)", warn: "var(--warn-2)", down: "var(--down-2)", info: "var(--info-2)" };

/** A donut with a legend: ui.donut([{ label: "Laptop", value: 175 }, …], { center: "320", sub: "assets" }). */
export function donut(items, opts = {}) {
  const list = (items || []).filter((i) => Number(i.value) > 0);
  const total = list.reduce((a, i) => a + Number(i.value), 0) || 1;
  const size = 168, r = 62, c = 2 * Math.PI * r;
  let start = 0;
  const segs = list.map((it, i) => {
    const len = (Number(it.value) / total) * c;
    const color = it.color || TONE_COLOR[it.tone] || PALETTE[i % PALETTE.length];
    const seg = s("circle", { class: "donut-seg", cx: size / 2, cy: size / 2, r, stroke: color,
      "stroke-dasharray": `0 ${c}`, "stroke-dashoffset": -start,
      style: { transition: `stroke-dasharray 1s ${0.08 * i}s cubic-bezier(.16,1,.3,1), stroke-width .2s, opacity .2s` } },
      s("title", {}, `${label(it.label)}: ${number(it.value)} (${Math.round((Number(it.value) / total) * 100)}%)`));
    raf(() => seg.setAttribute("stroke-dasharray", `${Math.max(0, len - 1.5)} ${c}`));
    start += len;
    return { seg, color, it };
  });
  const centerNum = s("text", { class: "donut-center", x: size / 2, y: size / 2 + 4, "text-anchor": "middle" }, opts.center ?? number(total));
  const svgEl = s("svg", { class: "donut", viewBox: `0 0 ${size} ${size}` },
    s("circle", { cx: size / 2, cy: size / 2, r, fill: "none", stroke: "var(--surface-3)", "stroke-width": 18 }),
    segs.map((x) => x.seg), centerNum,
    s("text", { class: "donut-sub", x: size / 2, y: size / 2 + 22, "text-anchor": "middle" }, opts.sub || "total"));
  const focus = (idx) => segs.forEach((x, i) => { x.seg.style.opacity = idx === null || idx === i ? "1" : ".3"; });
  const legend = h("div", { class: "legend" }, segs.map((x, i) =>
    h("div", { class: "legend-item", onmouseenter: () => focus(i), onmouseleave: () => focus(null),
      onclick: opts.onClick ? () => opts.onClick(x.it) : null, style: { cursor: opts.onClick ? "pointer" : null } },
      h("span", { class: "legend-swatch", style: { background: x.color } }), h("span", {}, label(x.it.label)),
      h("b", {}, number(x.it.value)))));
  segs.forEach((x, i) => { x.seg.addEventListener("mouseenter", () => focus(i)); x.seg.addEventListener("mouseleave", () => focus(null)); });
  return h("div", { class: "donut-wrap" }, svgEl, legend);
}

/** Horizontal bars: [{ label, value, tone? }], the longest bar fills the width; opts.onClick(item). */
export function bars(items, opts = {}) {
  const list = items || [];
  const max = opts.max || Math.max(1, ...list.map((i) => Number(i.value) || 0));
  return h("div", { class: "bars" }, list.map((it, i) => {
    const v = Number(it.value) || 0;
    const fill = h("span", { class: `bar-fill${it.tone ? ` bar-${it.tone}` : ""}`, style: { transitionDelay: `${i * 0.05}s` } });
    raf(() => { fill.style.width = `${Math.max(2, Math.round((v / max) * 100))}%`; });
    return h("div", { class: `bar${opts.onClick ? " clickable" : ""}`, onclick: opts.onClick ? () => opts.onClick(it) : null, "data-tip": opts.tips ? `${label(it.label)}: ${number(v)}` : null },
      h("span", { class: "bar-label" }, label(it.label)),
      h("span", { class: "bar-track" }, fill),
      h("span", { class: "bar-value mono" }, opts.format ? opts.format(v) : number(v)));
  }));
}

function chartTip(wrap) {
  const tip = h("div", { class: "chart-tip" });
  wrap.append(tip);
  return {
    show(text, el) {
      const a = el.getBoundingClientRect(), b = wrap.getBoundingClientRect();
      tip.textContent = text;
      tip.style.left = `${a.left - b.left + a.width / 2}px`;
      tip.style.top = `${a.top - b.top}px`;
      tip.classList.add("on");
    },
    hide() { tip.classList.remove("on"); },
  };
}

/** Columns over time: [{ label: "Mar 1", value: 12 }]; opts.type "line" draws a line and area instead. */
export function timeseries(points, opts = {}) {
  if (opts.type === "line") return line(points, opts);
  ensureDefs();
  const pts = points || [];
  const W = 640, H = opts.height || 180, pad = 8, base = H - 18;
  const max = Math.max(1, ...pts.map((p) => Number(p.value) || 0));
  const n = Math.max(1, pts.length), gap = n > 40 ? 1 : 3;
  const bw = Math.max(2, (W - pad * 2) / n - gap);
  const wrap = h("div", { class: "chart-wrap" });
  const tip = chartTip(wrap);
  const grid = [0.25, 0.5, 0.75, 1].map((f) => s("line", { class: "chart-grid", x1: pad, x2: W - pad, y1: base - (base - 10) * f, y2: base - (base - 10) * f }));
  const cols = pts.map((p, i) => {
    const v = Number(p.value) || 0;
    const hgt = Math.max(v ? 2 : 0, ((base - 10) * v) / max);
    const rect = s("rect", { class: "chart-col", x: pad + i * (bw + gap), y: base - hgt, width: bw, height: hgt, rx: Math.min(4, bw / 2),
      style: { animationDelay: `${Math.min(i * 0.02, 0.6)}s` } });
    rect.addEventListener("mouseenter", () => tip.show(`${p.label}: ${number(v)}`, rect));
    rect.addEventListener("mouseleave", () => tip.hide());
    if (opts.onClick) { rect.style.cursor = "pointer"; rect.addEventListener("click", () => opts.onClick(p)); }
    return rect;
  });
  wrap.prepend(s("svg", { class: "chart", viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": opts.label || "Chart" },
    grid, s("line", { class: "chart-axis", x1: pad, x2: W - pad, y1: base, y2: base }), cols));
  wrap.append(h("div", { class: "chart-labels" }, h("span", {}, pts[0] ? pts[0].label : ""),
    h("span", {}, `peak ${number(max)}`), h("span", {}, pts.length ? pts[pts.length - 1].label : "")));
  return wrap;
}

/** A line and area chart: [{ label, value }]. */
export function line(points, opts = {}) {
  ensureDefs();
  const pts = points || [];
  const W = 640, H = opts.height || 180, pad = 10, base = H - 18;
  const vals = pts.map((p) => Number(p.value) || 0);
  const max = Math.max(1, ...vals);
  const xy = vals.map((v, i) => [pad + (pts.length > 1 ? (i / (pts.length - 1)) * (W - pad * 2) : (W - pad * 2) / 2), base - ((base - 12) * v) / max]);
  const d = xy.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
  let len = 0;
  for (let i = 1; i < xy.length; i++) len += Math.hypot(xy[i][0] - xy[i - 1][0], xy[i][1] - xy[i - 1][1]);
  const wrap = h("div", { class: "chart-wrap" });
  const tip = chartTip(wrap);
  const grid = [0.25, 0.5, 0.75, 1].map((f) => s("line", { class: "chart-grid", x1: pad, x2: W - pad, y1: base - (base - 12) * f, y2: base - (base - 12) * f }));
  const dots = xy.map((p, i) => {
    const dot = s("circle", { cx: p[0], cy: p[1], r: 4, fill: "var(--surface)", stroke: "var(--accent)", "stroke-width": 2, opacity: 0 });
    const hit = s("rect", { x: p[0] - (W / Math.max(pts.length, 1)) / 2, y: 0, width: W / Math.max(pts.length, 1), height: H, fill: "transparent" });
    hit.addEventListener("mouseenter", () => { dot.setAttribute("opacity", 1); tip.show(`${pts[i].label}: ${number(vals[i])}`, dot); });
    hit.addEventListener("mouseleave", () => { dot.setAttribute("opacity", 0); tip.hide(); });
    return [hit, dot];
  });
  wrap.prepend(s("svg", { class: "chart", viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": opts.label || "Chart" },
    grid, s("line", { class: "chart-axis", x1: pad, x2: W - pad, y1: base, y2: base }),
    xy.length > 1 ? s("path", { class: "chart-area", d: `${d} L${xy[xy.length - 1][0]},${base} L${xy[0][0]},${base} Z` }) : null,
    xy.length > 1 ? s("path", { class: "chart-line", d, style: { "--len": Math.ceil(len) } }) : null,
    dots));
  wrap.append(h("div", { class: "chart-labels" }, h("span", {}, pts[0] ? pts[0].label : ""),
    h("span", {}, `peak ${number(max)}`), h("span", {}, pts.length ? pts[pts.length - 1].label : "")));
  return wrap;
}

/* --- feedback -------------------------------------------------------------------- */

const EMPTY_ART = "M20 64 48 50l28 14-28 14zM20 64v8l28 14 28-14v-8M48 50V30M38 36l10-8 10 8M30 20h.01M68 22h.01M24 40h.01M74 44h.01";
export function empty(title, hint, opts = {}) {
  const art = s("svg", { class: "empty-art", viewBox: "0 0 96 96", fill: "none", stroke: "currentColor", "stroke-width": 2.4,
    "stroke-linecap": "round", "stroke-linejoin": "round" }, s("path", { d: EMPTY_ART }));
  return h("div", { class: "empty-state" }, opts.icon ? h("div", { class: "modal-icon" }, icon(opts.icon)) : art,
    h("strong", {}, title || "Nothing here yet"), hint ? h("span", {}, hint) : null, opts.action || null);
}

export function notice(text, kind) {
  const ic = { ok: "check-circle", warn: "alert", down: "alert", info: "info" }[kind] || "info";
  return h("div", { class: `notice${kind ? ` notice-${kind}` : ""}` }, icon(ic), h("div", {}, text));
}

/** Label/value pairs for a detail view. */
export function kv(pairs) {
  return h("dl", { class: "kv" }, (pairs || []).flatMap((p) => [
    h("dt", {}, p.label),
    h("dd", {}, p.value instanceof Node ? p.value : (p.value === null || p.value === undefined || p.value === "" ? "—" : p.value)),
  ]));
}

/** ui.button("Save", { onclick, tone: "secondary" | "danger" | "ghost", icon: "plus", kbd: "N", size: "sm" }). */
export function button(text, opts = {}) {
  const cls = [opts.tone && opts.tone !== "primary" ? opts.tone : "", opts.size === "sm" ? "sm" : ""].filter(Boolean).join(" ");
  return h("button", { type: opts.type || "button", class: cls || null, onclick: opts.onclick, disabled: opts.disabled, title: opts.title,
    "data-tip": opts.tip }, opts.icon ? icon(opts.icon) : null, text, opts.kbd ? kbd(opts.kbd) : null);
}

export function iconButton(name, opts = {}) {
  return h("button", { type: "button", class: "icon-btn", onclick: opts.onclick, "aria-label": opts.label || name, "data-tip": opts.label || null }, icon(name));
}

let toastHost = null;
export function toast(text, kind) {
  if (!toastHost || !toastHost.isConnected) {
    toastHost = h("div", { class: "toasts", role: "status", "aria-live": "polite" });
    document.body.append(toastHost);
  }
  const ic = { ok: "check-circle", warn: "alert", down: "alert" }[kind] || "info";
  const el = h("div", { class: `toast${kind ? ` toast-${kind}` : ""}` }, icon(ic), text);
  toastHost.append(el);
  setTimeout(() => el.classList.add("toast-out"), 2800);
  setTimeout(() => el.remove(), 3200);
  return el;
}

/** A confetti burst, from an element or the top of the page. For a real success, once. */
export function celebrate(from) {
  if (reduced() || typeof document === "undefined") return;
  const r = from && from.getBoundingClientRect ? from.getBoundingClientRect() : { left: innerWidth / 2, top: innerHeight * 0.3, width: 0, height: 0 };
  const x = r.left + r.width / 2, y = r.top + r.height / 2;
  const colors = ["#5b5bf6", "#a855f7", "#ec4899", "#f79009", "#16b364", "#2e90fa"];
  for (let i = 0; i < 46; i++) {
    const angle = Math.random() * Math.PI * 2, dist = 90 + Math.random() * 180;
    const p = h("span", { class: "confetti" });
    p.style.background = colors[i % colors.length];
    p.style.setProperty("--x0", `${x}px`); p.style.setProperty("--y0", `${y}px`);
    p.style.setProperty("--dx", `${Math.cos(angle) * dist}px`);
    p.style.setProperty("--dy", `${Math.sin(angle) * dist + 160}px`);
    p.style.setProperty("--rot", `${Math.random() * 720 - 360}deg`);
    p.style.animationDelay = `${Math.random() * 0.08}s`;
    document.body.append(p);
    setTimeout(() => p.remove(), 1500);
  }
}

export function skeleton(kind = "screen") {
  if (kind === "rows") return h("div", { class: "stack" }, [1, 2, 3, 4, 5].map(() => h("div", { class: "skeleton", style: { height: "38px" } })));
  return h("div", { class: "skeleton-screen" },
    h("div", { class: "sk-stats" }, [1, 2, 3, 4].map(() => h("div", { class: "skeleton sk-tile" }))),
    h("div", { class: "skeleton sk-panel" }));
}

/* --- overlays -------------------------------------------------------------------- */

const openStack = [];
if (typeof document !== "undefined") {
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && openStack.length) { e.preventDefault(); openStack[openStack.length - 1](); }
  });
}

function overlay(panel, opts = {}) {
  const back = h("div", { class: "backdrop" });
  const previous = document.activeElement;
  let closed = false;
  const close = () => {
    if (closed) return;
    closed = true;
    const i = openStack.indexOf(close);
    if (i >= 0) openStack.splice(i, 1);
    back.classList.add("closing");
    panel.classList.add("closing");
    setTimeout(() => { back.remove(); panel.remove(); }, 240);
    if (previous && previous.focus) previous.focus();
    if (opts.onclose) opts.onclose();
  };
  back.addEventListener("click", close);
  document.body.append(back, panel);
  openStack.push(close);
  raf(() => {
    const first = panel.querySelector("input, select, textarea, button:not(.icon-btn)");
    if (first) first.focus();
  });
  return close;
}

function resolveContent(content, close) {
  const c = typeof content === "function" ? content(close) : content;
  if (c && typeof c.then === "function") {
    const holder = h("div", {}, skeleton("rows"));
    c.then((v) => holder.replaceChildren(...[].concat(v).filter(Boolean))).catch((err) => holder.replaceChildren(notice(err.message || String(err), "down")));
    return holder;
  }
  return [].concat(c).filter(Boolean);
}

/** A slide-over panel: ui.drawer({ title, subtitle, content: node | (close) => node, actions: [buttons] }). */
export function drawer(opts = {}) {
  const panel = h("aside", { class: "drawer", role: "dialog", "aria-modal": "true", "aria-label": opts.title || "Details" });
  const close = overlay(panel, opts);
  const actions = typeof opts.actions === "function" ? opts.actions(close) : (opts.actions || []);
  panel.append(...[
    h("div", { class: "drawer-head" },
      opts.icon ? h("div", { class: "modal-icon" }, icon(opts.icon)) : null,
      h("div", {}, h("h2", {}, opts.title || ""), opts.subtitle ? h("div", { class: "muted" }, opts.subtitle) : null),
      iconButton("x", { onclick: close, label: "Close" })),
    h("div", { class: "drawer-body" }, resolveContent(opts.content, close)),
    actions.length ? h("div", { class: "drawer-foot" }, actions) : null,
  ].filter(Boolean));
  return { el: panel, close };
}

/** A centred dialog: ui.modal({ title, subtitle, icon, content, actions, size: "lg" }). */
export function modal(opts = {}) {
  const panel = h("div", { class: `modal${opts.size === "lg" ? " lg" : ""}`, role: "dialog", "aria-modal": "true", "aria-label": opts.title || "Dialog" });
  const close = overlay(panel, opts);
  const actions = typeof opts.actions === "function" ? opts.actions(close) : (opts.actions || []);
  panel.append(...[
    h("div", { class: "modal-head" },
      opts.icon ? h("div", { class: `modal-icon${opts.danger ? " danger" : ""}` }, icon(opts.icon)) : null,
      h("div", {}, h("h2", {}, opts.title || ""), opts.subtitle ? h("div", { class: "muted" }, opts.subtitle) : null),
      iconButton("x", { onclick: close, label: "Close" })),
    h("div", { class: "modal-body" }, resolveContent(opts.content, close)),
    actions.length ? h("div", { class: "modal-foot" }, actions.filter(Boolean)) : null,
  ].filter(Boolean));
  return { el: panel, close };
}

/** await ui.confirm("Retire this laptop?", { danger: true, confirmLabel: "Retire" }) -> true | false. */
export function confirm(message, opts = {}) {
  return new Promise((resolve) => {
    let answered = false;
    const done = (v, close) => { answered = true; close(); resolve(v); };
    modal({
      title: opts.title || "Are you sure?", icon: opts.danger ? "alert" : "info", danger: opts.danger,
      content: h("p", { style: { margin: 0 } }, message),
      actions: (close) => [
        button(opts.cancelLabel || "Cancel", { tone: "secondary", onclick: () => done(false, close) }),
        h("button", { class: opts.danger ? "danger solid" : null, onclick: () => done(true, close) }, opts.confirmLabel || "Confirm"),
      ],
      onclose: () => { if (!answered) resolve(false); },
    });
  });
}

/* --- inputs ---------------------------------------------------------------------- */

export function search(opts = {}) {
  return h("input", { type: "search", class: "search", placeholder: opts.placeholder || "Search…",
    value: opts.value || "", oninput: opts.oninput, "aria-label": opts.placeholder || "Search" });
}

export function select(opts = {}) {
  return h("select", { name: opts.name, onchange: opts.onchange, "aria-label": opts.label || opts.name || "Choose" },
    (opts.options || []).map((o) => {
      const value = typeof o === "object" ? o.value : o;
      const text = typeof o === "object" ? o.label : label(o);
      return h("option", { value, selected: String(value) === String(opts.value) }, text);
    }));
}

/** A segmented control with a sliding thumb: ui.segmented({ options: ["All", "Open", …] | [{ value, label, count }], value, onchange(value) }). */
export function segmented(opts = {}) {
  const options = (opts.options || []).map((o) => (typeof o === "object" ? o : { value: o, label: label(o) }));
  let value = opts.value === undefined && options.length ? options[0].value : opts.value;
  const thumb = h("span", { class: "seg-thumb" });
  const el = h("div", { class: "segmented", role: "tablist" }, thumb);
  const place = () => {
    const on = el.querySelector("button.on");
    if (on) { thumb.style.left = `${on.offsetLeft}px`; thumb.style.width = `${on.offsetWidth}px`; }
  };
  const buttons = options.map((o) => h("button", { type: "button", role: "tab", class: String(o.value) === String(value) ? "on" : null,
    onclick: () => {
      value = o.value;
      buttons.forEach((b, i) => b.classList.toggle("on", String(options[i].value) === String(value)));
      place();
      if (opts.onchange) opts.onchange(value);
    } }, o.icon ? icon(o.icon) : null, o.label, o.count !== undefined ? h("span", { class: "count-pill" }, number(o.count)) : null));
  el.append(...buttons);
  raf(place);
  if (typeof ResizeObserver === "function") new ResizeObserver(place).observe(el);
  el.value = () => value;
  return el;
}

/** Toggle chips: ui.chips({ options, value: [..], multi: true, onchange(values) }). */
export function chips(opts = {}) {
  const options = (opts.options || []).map((o) => (typeof o === "object" ? o : { value: o, label: label(o) }));
  let chosen = new Set([].concat(opts.value ?? []).map(String));
  const el = h("div", { class: "chips" });
  const draw = () => el.replaceChildren(...options.map((o) => h("button", { type: "button", class: `chip${chosen.has(String(o.value)) ? " on" : ""}`,
    onclick: () => {
      const k = String(o.value);
      if (opts.multi) { if (chosen.has(k)) chosen.delete(k); else chosen.add(k); } else chosen = new Set(chosen.has(k) ? [] : [k]);
      draw();
      if (opts.onchange) opts.onchange(opts.multi ? [...chosen] : ([...chosen][0] ?? null));
    } }, o.label, o.count !== undefined ? h("span", { class: "count-pill" }, number(o.count)) : null)));
  draw();
  return el;
}

/** Tabs with a sliding underline: ui.tabs([{ label, icon, badge, content: node | () => node | Promise<node> }]). */
export function tabs(items, opts = {}) {
  const list = items || [];
  const ink = h("span", { class: "tab-ink" });
  const bar = h("div", { class: "tabs", role: "tablist" }, ink);
  const panel = h("div", { class: "tab-panel", role: "tabpanel" });
  const cache = new Map();
  const place = () => {
    const on = bar.querySelector("button.on");
    if (on) { ink.style.left = `${on.offsetLeft}px`; ink.style.width = `${on.offsetWidth}px`; }
  };
  const open = (i) => {
    buttons.forEach((b, j) => b.classList.toggle("on", i === j));
    place();
    if (!cache.has(i)) {
      const c = list[i].content;
      cache.set(i, resolveContent(typeof c === "function" ? () => c() : c, () => {}));
    }
    panel.replaceChildren(...[].concat(cache.get(i)));
    panel.style.animation = "none";
    void panel.offsetWidth;
    panel.style.animation = "";
    if (opts.onchange) opts.onchange(i);
  };
  const buttons = list.map((t, i) => h("button", { type: "button", role: "tab", onclick: () => open(i) },
    t.icon ? icon(t.icon) : null, t.label, t.badge !== undefined ? h("span", { class: "count-pill" }, t.badge) : null));
  bar.append(...buttons);
  if (list.length) open(opts.value || 0);
  raf(place);
  return h("div", {}, bar, panel);
}

/**
 * A form from a field list. Values arrive in onsubmit as an object; a thrown
 * error is shown under the buttons, a returned string as a success message.
 * Required fields are checked first and marked in place.
 *
 *   ui.form({
 *     fields: [
 *       { name: "title", label: "Title", required: true },
 *       { name: "priority", label: "Priority", type: "select", options: ["P1","P2","P3","P4"], value: "P3" },
 *       { name: "body", label: "Details", type: "textarea", span: "all" },
 *     ],
 *     submit: "Create ticket", celebrate: true,
 *     onsubmit: async (values) => { await api("/tickets", { method: "POST", body: values }); return "Created."; },
 *   })
 */
export function form(opts = {}) {
  const controls = {};
  const wrappers = {};
  const message = h("p", { class: "faint", style: { margin: 0 } });
  const submit = h("button", { type: "submit" }, opts.submitIcon ? icon(opts.submitIcon) : null, opts.submit || "Save");
  const fieldsEl = h("div", { class: opts.inline ? "row" : "form-grid" },
    (opts.fields || []).map((f) => {
      let control;
      if (f.type === "select") control = select({ name: f.name, options: f.options || [], value: f.value, label: f.label });
      else if (f.type === "textarea") control = h("textarea", { name: f.name, placeholder: f.placeholder || "", required: f.required }, f.value || "");
      else control = h("input", { type: f.type || "text", name: f.name, placeholder: f.placeholder || "", required: f.required,
        value: f.value ?? "", min: f.min, max: f.max, step: f.step });
      control.addEventListener("input", () => wrappers[f.name].classList.remove("invalid"));
      controls[f.name] = control;
      wrappers[f.name] = h("div", { class: `field${f.span === "all" || f.type === "textarea" ? " span-all" : ""}` },
        h("label", {}, f.label || label(f.name), f.required ? h("span", { style: { color: "var(--down)" } }, " *") : null), control,
        f.hint ? h("span", { class: "hint" }, f.hint) : null);
      return wrappers[f.name];
    }));
  const el = h("form", { class: "stack", novalidate: true, onsubmit: async (event) => {
    event.preventDefault();
    let firstBad = null;
    for (const f of opts.fields || []) {
      const w = wrappers[f.name];
      w.querySelector(".field-error")?.remove();
      w.classList.remove("invalid");
      if (f.required && !String(controls[f.name].value || "").trim()) {
        w.classList.add("invalid");
        w.append(h("span", { class: "field-error" }, `${f.label || label(f.name)} is required`));
        firstBad = firstBad || controls[f.name];
      }
    }
    if (firstBad) { firstBad.focus(); return; }
    const values = {};
    for (const [name, control] of Object.entries(controls)) {
      const spec = (opts.fields || []).find((f) => f.name === name) || {};
      const raw = control.value;
      values[name] = spec.type === "number" ? (raw === "" ? null : Number(raw)) : raw;
    }
    submit.disabled = true;
    const spin = h("span", { class: "spinner" });
    submit.prepend(spin);
    message.className = "faint";
    message.textContent = "";
    try {
      const result = opts.onsubmit ? await opts.onsubmit(values, el) : null;
      if (typeof result === "string") { message.className = "faint"; message.textContent = result; }
      if (opts.celebrate) celebrate(submit);
      if (opts.reset !== false && result !== false) el.reset();
      if (opts.onsuccess) opts.onsuccess(result, values);
    } catch (err) {
      message.className = "error-text";
      message.textContent = err && err.message ? err.message : String(err);
    } finally {
      spin.remove();
      submit.disabled = false;
    }
  } }, fieldsEl, h("div", { class: "form-actions" }, submit, ...(opts.extra || []), message));
  el.controls = controls;
  return el;
}

/** A form in a dialog, the way a "New …" button should open one. Resolves with onsubmit's result, or null if dismissed. */
export function formModal(opts = {}) {
  return new Promise((resolve) => {
    let done = false;
    const m = modal({
      title: opts.title, subtitle: opts.subtitle, icon: opts.icon || "plus", size: opts.size,
      content: (close) => form({ ...opts, reset: false, onsuccess: (result, values) => {
        done = true;
        close();
        if (opts.toast !== false) toast(typeof result === "string" ? result : (opts.successMessage || "Saved"), "ok");
        resolve(result ?? values);
      } }),
      onclose: () => { if (!done) resolve(null); },
    });
    return m;
  });
}

/* --- data ---------------------------------------------------------------------- */

function cellValue(row, col) {
  if (typeof col.render === "function") return col.render(row);
  const v = col.key ? row[col.key] : "";
  if (v === null || v === undefined || v === "") return h("span", { class: "faint" }, "—");
  if (col.badge) return badge(v);
  if (col.format === "date") return date(v);
  if (col.format === "ago") return timeAgo(v);
  if (col.format === "money") return money(v, col.currency);
  if (col.format === "number") return number(v);
  return v;
}

function searchable(row) {
  return Object.values(row || {}).filter((v) => typeof v === "string" || typeof v === "number").join(" ").toLowerCase();
}

function csvCell(v) {
  const t = v === null || v === undefined ? "" : String(v);
  return /[",\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t;
}

/**
 * A data table with search, segmented filters, sorting, paging, keyboard
 * navigation, CSV export and a slide-over drawer per row. Returns the element;
 * call `.update(rows)` to redraw after a change.
 *
 *   const table = ui.table({
 *     columns: [
 *       { key: "subject", label: "Subject", render: (t) => h("strong", {}, t.subject) },
 *       { key: "status", label: "Status", badge: true },
 *       { key: "created_at", label: "Arrived", format: "ago" },
 *     ],
 *     rows, search: true, keyboard: true, pageSize: 25, sort: { key: "created_at", dir: "desc" },
 *     filters: [{ key: "status" }],                 // a segmented control with counts per value
 *     exportable: "tickets",                        // a CSV export button, this file name
 *     drawer: (t) => ({ title: t.subject, content: ui.kv([...]), actions: [...] }),   // row click opens it
 *     empty: { title: "No tickets", hint: "New tickets appear here as they arrive." },
 *   });
 *
 * Use `onRow(row)` instead of `drawer` to navigate; `onSelect(row)` fires as the keyboard selection moves.
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
  let animate = true;
  const active = {};
  const clickable = Boolean(opts.onRow || opts.drawer || opts.onSelect);

  const tbody = h("tbody");
  const count = h("span", { class: "faint" });
  const pager = h("div", { class: "pager" });
  const emptyEl = h("div", { hidden: true });
  const wrap = h("div", { class: "table-wrap", tabindex: opts.keyboard ? 0 : null });

  const ths = columns.map((c) => h("th", { class: `${c.align === "right" ? "right" : ""}${c.key && opts.sortable !== false ? " sortable" : ""}`,
    onclick: c.key && opts.sortable !== false ? () => { if (sortKey === c.key) sortDir = -sortDir; else { sortKey = c.key; sortDir = 1; } animate = true; draw(); } : null },
    c.label, c.key && opts.sortable !== false ? h("span", { class: "sort-mark" }) : null));
  const thead = h("thead", {}, h("tr", {}, ths, clickable ? h("th", { class: "row-go" }) : null));

  function visible() {
    let rows = all;
    for (const [k, v] of Object.entries(active)) if (v !== "__all__") rows = rows.filter((r) => String(r[k]) === String(v));
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

  function openRow(row, i) {
    selected = i;
    if (opts.onSelect) opts.onSelect(row);
    if (opts.onRow) opts.onRow(row);
    else if (opts.drawer) {
      const spec = opts.drawer(row);
      if (spec) drawer(spec);
    }
    draw();
  }

  function draw() {
    const rows = visible();
    const pages = Math.max(1, Math.ceil(rows.length / pageSize));
    if (page >= pages) page = pages - 1;
    const start = page * pageSize;
    const slice = rows.slice(start, start + pageSize);
    ths.forEach((th, i) => {
      const mark = th.querySelector(".sort-mark");
      if (mark) mark.textContent = columns[i].key === sortKey ? (sortDir > 0 ? " ↑" : " ↓") : "";
    });
    tbody.replaceChildren(...slice.map((row, i) => {
      const tr = h("tr", { class: `${clickable ? "clickable" : ""}${i === selected ? " selected" : ""}${animate ? " enter" : ""}`,
        "aria-selected": i === selected ? "true" : null, onclick: () => openRow(row, i) },
        columns.map((c) => h("td", { class: `${c.mono ? "mono" : ""}${c.align === "right" ? " right" : ""}` }, cellValue(row, c))),
        clickable ? h("td", { class: "row-go" }, icon("chevron-right")) : null);
      if (animate) tr.style.animationDelay = `${Math.min(i * 0.022, 0.5)}s`;
      return tr;
    }));
    animate = false;
    const none = rows.length === 0;
    wrap.hidden = none;
    emptyEl.hidden = !none;
    emptyEl.replaceChildren(none && (query || Object.values(active).some((v) => v !== "__all__"))
      ? empty("No matches", "Nothing matches the search or filters.", { icon: "search" })
      : empty((opts.empty && opts.empty.title) || "Nothing to show", (opts.empty && opts.empty.hint) || ""));
    count.textContent = none ? "" : `${number(start + 1)}–${number(Math.min(rows.length, start + pageSize))} of ${number(rows.length)}`;
    pager.replaceChildren(...(pages > 1 ? [
      h("button", { class: "ghost sm", disabled: page === 0, onclick: () => { page -= 1; selected = -1; animate = true; draw(); } }, "‹ Prev"),
      h("span", { class: "faint" }, `Page ${page + 1} of ${pages}`),
      h("button", { class: "ghost sm", disabled: page >= pages - 1, onclick: () => { page += 1; selected = -1; animate = true; draw(); } }, "Next ›"),
    ] : []));
    return slice;
  }

  const searchEl = opts.search ? search({ placeholder: opts.searchPlaceholder || "Search…",
    oninput: (e) => { query = e.target.value.trim().toLowerCase(); page = 0; selected = -1; animate = true; draw(); } }) : null;

  const filterEls = (opts.filters || []).map((f) => {
    const values = [...new Set(all.map((r) => r[f.key]).filter((v) => v !== null && v !== undefined && v !== ""))].sort();
    active[f.key] = "__all__";
    const options = [{ value: "__all__", label: f.all || "All", count: all.length },
      ...(f.options || values).map((v) => ({ value: v, label: label(v), count: all.filter((r) => String(r[f.key]) === String(v)).length }))];
    return segmented({ options: options.slice(0, 7), value: "__all__", onchange: (v) => { active[f.key] = v; page = 0; selected = -1; animate = true; draw(); } });
  });

  const exportBtn = opts.exportable ? button("Export", { tone: "secondary", icon: "download", size: "sm", onclick: () => {
    const rows = visible();
    const keys = columns.filter((c) => c.key).map((c) => c.key);
    const csv = [columns.filter((c) => c.key).map((c) => csvCell(c.label)).join(","),
      ...rows.map((r) => keys.map((k) => csvCell(r[k])).join(","))].join("\n");
    const a = h("a", { href: URL.createObjectURL(new Blob([csv], { type: "text/csv" })),
      download: `${typeof opts.exportable === "string" ? opts.exportable : "export"}.csv` });
    document.body.append(a); a.click(); a.remove();
    toast(`Exported ${number(rows.length)} rows`, "ok");
  } }) : null;

  const head = h("div", { class: "toolbar" }, searchEl, ...filterEls, ...(opts.tools || []), h("span", { class: "toolbar-right" }, count, exportBtn));

  if (opts.keyboard) {
    wrap.addEventListener("keydown", (e) => {
      const slice = visible().slice(page * pageSize, page * pageSize + pageSize);
      if (!slice.length) return;
      if (e.key === "ArrowDown" || e.key === "j") { selected = Math.min(slice.length - 1, selected + 1); e.preventDefault(); }
      else if (e.key === "ArrowUp" || e.key === "k") { selected = Math.max(0, selected - 1); e.preventDefault(); }
      else if (e.key === "Enter" && selected >= 0) { openRow(slice[selected], selected); e.preventDefault(); return; }
      else return;
      draw();
      const tr = tbody.children[selected];
      if (tr) tr.scrollIntoView({ block: "nearest" });
      if (opts.onSelect) opts.onSelect(slice[selected]);
    });
  }

  const el = h("div", { class: "stack table-kit" }, head, wrap, emptyEl, pager);
  wrap.append(h("table", {}, thead, tbody));
  el.update = (rows) => { all = rows || []; animate = true; draw(); };
  el.selected = () => visible()[page * pageSize + selected] || null;
  el.focus = () => wrap.focus();
  draw();
  return el;
}

/** History as a vertical timeline: [{ title, time, body, tone, icon }]. */
export function timeline(items) {
  const list = items || [];
  if (!list.length) return empty("No history yet", "Changes appear here as they happen.", { icon: "history" });
  return h("ol", { class: "timeline" }, list.map((it, i) => {
    const li = h("li", { class: `tl-item${it.tone ? ` tl-${it.tone}` : ""}` },
      h("span", { class: "tl-dot" }, icon(it.icon || (it.tone === "ok" ? "check" : it.tone === "down" ? "alert" : "activity"))),
      h("div", {}, h("div", { class: "tl-head" }, h("span", { class: "tl-title" }, it.title),
        it.time ? h("span", { class: "tl-time", "data-tip": dateTime(it.time) }, timeAgo(it.time)) : null),
      it.body ? h("div", { class: "tl-body" }, it.body) : null));
    li.style.animationDelay = `${Math.min(i * 0.05, 0.6)}s`;
    return li;
  }));
}

/**
 * A drag-and-drop status board.
 *
 *   ui.kanban({
 *     columns: [{ key: "open", label: "Open" }, { key: "with_vendor", label: "With vendor" }, { key: "closed", label: "Closed", tone: "ok" }],
 *     items: repairs, field: "status",
 *     card: (r) => [h("strong", {}, r.fault_description), h("div", { class: "faint" }, r.vendor)],
 *     onMove: async (r, to) => api(`/repairs/${r.id}`, { method: "PATCH", body: { status: to } }),
 *     onCard: (r) => ui.drawer({ title: …, content: … }),
 *   })
 */
export function kanban(opts = {}) {
  const field = opts.field || "status";
  const limit = opts.limit || 60;
  let items = [...(opts.items || [])];
  let dragged = null;
  const board = h("div", { class: "kanban" });
  const draw = (landedId) => {
    board.replaceChildren(...(opts.columns || []).map((col) => {
      const mine = items.filter((it) => String(it[field]) === String(col.key));
      const cards = h("div", { class: "kanban-cards" }, mine.slice(0, limit).map((it, i) => {
        const card = h("div", { class: `kanban-card${landedId !== undefined && it.id === landedId ? " landed" : ""}`, draggable: "true",
          onclick: opts.onCard ? () => opts.onCard(it) : null,
          ondragstart: (e) => { dragged = it; card.classList.add("dragging"); e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", String(it.id)); },
          ondragend: () => card.classList.remove("dragging") },
        [].concat(opts.card ? opts.card(it) : String(it.name || it.title || it.id)));
        card.style.animationDelay = `${Math.min(i * 0.03, 0.4)}s`;
        return card;
      }), mine.length > limit ? h("div", { class: "kanban-more" }, `+${number(mine.length - limit)} more`) : null);
      const colEl = h("div", { class: "kanban-col",
        ondragover: (e) => { e.preventDefault(); colEl.classList.add("over"); },
        ondragleave: () => colEl.classList.remove("over"),
        ondrop: async (e) => {
          e.preventDefault();
          colEl.classList.remove("over");
          if (!dragged || String(dragged[field]) === String(col.key)) return;
          const item = dragged, from = item[field];
          item[field] = col.key;
          draw(item.id);
          try {
            if (opts.onMove) await opts.onMove(item, col.key, from);
            toast(`Moved to ${col.label}`, "ok");
          } catch (err) {
            item[field] = from;
            draw();
            toast(err && err.message ? err.message : String(err), "down");
          }
        } },
      h("div", { class: "kanban-head" }, badge(col.label, col.tone === undefined ? tone(col.key) : col.tone), h("span", { class: "count-pill" }, number(mine.length))),
      cards);
      return colEl;
    }));
  };
  draw();
  board.update = (rows) => { items = [...(rows || [])]; draw(); };
  return board;
}

const ui = {
  h, icon, ICONS, guessIcon, tone, label, badge, initials, avatar, avatarGroup, person, timeAgo, date, dateTime, number, money, percent,
  kbd, countUp, section, split, toolbar, hero, profile, stats, sparkline, ring, meter, donut, bars, timeseries, line,
  empty, notice, kv, button, iconButton, toast, celebrate, skeleton, drawer, modal, confirm,
  search, select, segmented, chips, tabs, form, formModal, table, timeline, kanban,
};
export default ui;
