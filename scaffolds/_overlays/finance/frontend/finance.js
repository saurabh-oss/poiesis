/*
 * The finance and procurement dashboard kit. Written by Poiesis, and read-only.
 *
 * A screen imports it and composes; it never works a fiscal quarter out, formats an
 * amount, or draws a budget bar by hand:
 *
 *     import fin from "../finance.js";
 *
 *     export default {
 *       title: "Spend overview", story: "S3", icon: "pie",
 *       async render(root, ctx) {
 *         await fin.dashboard(root, ctx, fin.blueprints.spend({ targets: { po_coverage: 95 } }));
 *       },
 *     };
 *
 * A work screen is a description too: the records of one job as tabs with their counts, and what
 * this person does to them, each through the record's workflow and its rules:
 *
 *         await fin.workbench(root, ctx, fin.worklists.receiving());
 *
 * A whole dashboard from a description: the period picker, the filters, the headline
 * figures against last year, the charts, the rows behind every number, CSV export and
 * each person's own arrangement. The figures come from the insight API (/api/finance/…),
 * which every application built with the finance pack serves.
 *
 *   Dashboards  dashboard(root, ctx, spec), blueprints.{executive, spend, budget, payables,
 *               procureToPay, suppliers, controls, savings}, widget types (WIDGETS)
 *   Work        workbench(root, ctx, spec), worklists.{requisitions, approvals, ordering, receiving,
 *               invoices, paymentRuns, suppliers, contracts}, what people do (ACTIONS, TOOLS), advice
 *   Data        data(api): calendar, dimensions, kpis, breakdown, trend, budget, waterfall, aging,
 *               funnel, pivot, concentration, cycleTimes, exceptions, accruals, renewals,
 *               controls, scorecard, documents
 *   Controls    periodPicker, filterBar
 *   Figures     kpis, delta, varianceBadge, gauge
 *   Charts      trend, budgetBars, waterfall, pareto, treemap, donut, aging, funnel, pivot, cycleTimes
 *   Records     matchStatus, approvalChain, lifecycle, scorecard, controlList, renewalList
 *   Rows        drill, documents, columnsFor, exportCsv
 *   Text        money, percent, number, days, format, variance, calendar
 *
 * Every component returns a DOM element. None of them shows "null", "NaN" or "undefined":
 * a figure that is not there is a dash. Nothing here touches the page until it is called.
 */
import * as ui from "./ui.js";

const { h } = ui;
const SVG = "http://www.w3.org/2000/svg";

function s(tag, attrs, ...children) {
  const el = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "style" && typeof v === "object") for (const [name, value] of Object.entries(v)) {
      if (name.startsWith("--")) el.style.setProperty(name, String(value ?? "")); else el.style[name] = value;
    }
    else el.setAttribute(k, String(v));
  }
  for (const c of children.flat(Infinity)) if (c !== undefined && c !== null && c !== false) el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return el;
}

function css() {
  if (typeof document === "undefined" || document.getElementById("finance-css")) return;
  document.head.append(h("link", { id: "finance-css", rel: "stylesheet", href: "finance.css" }));
}

/** Replace an element's children, leaving out what is not there (the DOM would write null as "null"). */
function put(el, ...children) {
  el.replaceChildren(...children.flat(Infinity).filter((c) => c !== null && c !== undefined && c !== false));
  return el;
}

const raf = (fn) => (typeof requestAnimationFrame === "function" ? requestAnimationFrame(() => requestAnimationFrame(fn)) : setTimeout(fn, 16));

/* ---------------------------------------------------------------- settings */

const settings = { currency: "GBP", locale: "en-GB", fiscalStartMonth: 4 };

/** fin.configure({ currency: "EUR", locale: "de-DE", fiscalStartMonth: 1 }). dashboard() does it from the API. */
export function configure(opts = {}) {
  for (const k of ["currency", "locale", "fiscalStartMonth"]) if (opts[k]) settings[k] = opts[k];
  return { ...settings };
}

/* ---------------------------------------------------------------- text */

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const SYMBOLS = { GBP: "£", EUR: "€", USD: "$", INR: "₹", JPY: "¥", CNY: "¥", CHF: "CHF ", AUD: "A$", CAD: "C$", SGD: "S$",
  AED: "AED ", SAR: "SAR ", ZAR: "R", SEK: "kr ", NOK: "kr ", DKK: "kr ", PLN: "zł ", BRL: "R$", MXN: "MX$" };
const NO_MINOR = new Set(["JPY", "KRW", "VND", "CLP", "ISK"]);
const DASH = "—";

/** A finite number, or null: "", null, undefined, NaN and text that is not a number are all "not there". */
export function num(value) {
  if (value === null || value === undefined || value === "" || typeof value === "boolean") return null;
  const n = typeof value === "number" ? value : Number(String(value).replace(/,/g, ""));
  return Number.isFinite(n) ? n : null;
}

function grouped(n, digits) {
  return n.toLocaleString(settings.locale, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function short(abs) {
  const [div, suffix] = abs >= 1e9 ? [1e9, "bn"] : abs >= 1e6 ? [1e6, "M"] : [1e3, "k"];
  const v = abs / div;
  const text = v >= 100 ? v.toFixed(0) : v >= 10 ? v.toFixed(1) : v.toFixed(2);
  return text.replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, "") + suffix;
}

/**
 * An amount: fin.money(1234567.5) "£1,234,567.50"; { compact: true } "£1.23M"; { whole: true } "£1,234,568";
 * { accounting: true } writes a negative "(£420.00)"; { signed: true } "+£120.00"; { currency: "EUR" }.
 */
export function money(value, opts = {}) {
  const n = num(value);
  if (n === null) return DASH;
  const currency = opts.currency || settings.currency;
  const symbol = SYMBOLS[currency] ?? `${currency} `;
  const abs = Math.abs(n);
  const digits = opts.whole || NO_MINOR.has(currency) ? 0 : 2;
  const body = symbol + (opts.compact && abs >= 1000 ? short(abs) : grouped(abs, digits));
  if (n < 0 && Number(abs.toFixed(digits)) !== 0) return opts.accounting ? `(${body})` : `-${body}`;
  return opts.signed && n > 0 ? `+${body}` : body;
}

/** fin.percent(12.345) "12.3%"; { digits: 0 }; { signed: true } "+12.3%"; { points: true } "+2.1 pts". */
export function percent(value, opts = {}) {
  const n = num(value);
  if (n === null) return DASH;
  const text = Math.abs(n).toFixed(opts.digits ?? 1);
  const sign = n < 0 && Number(text) !== 0 ? "-" : (opts.signed || opts.points) && n > 0 ? "+" : "";
  return `${sign}${text}${opts.points ? " pts" : "%"}`;
}

export function number(value, digits = 0) {
  const n = num(value);
  return n === null ? DASH : grouped(n, digits);
}

export function days(value) {
  const n = num(value);
  if (n === null) return DASH;
  const text = n >= 100 ? n.toFixed(0) : n.toFixed(1).replace(/\.0$/, "");
  return `${text} ${Number(text) === 1 ? "day" : "days"}`;
}

/** A figure in its unit: "money" | "pct" | "days" | "count". Tiles and axes pass { compact: true }. */
export function format(value, unit, opts = {}) {
  if (unit === "money") return money(value, opts);
  if (unit === "pct") return percent(value, opts);
  if (unit === "days") return days(value);
  return number(value, opts.digits || 0);
}

export function words(value) {
  if (value === null || value === undefined || value === "") return DASH;
  const t = String(value).replace(/_/g, " ").trim();
  return t && t === t.toLowerCase() ? t.charAt(0).toUpperCase() + t.slice(1) : t;
}

/** "25 Sep 2026" from "2026-09-25" or a time on that day: the day as written, whatever the reader's time zone. */
export function date(value) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(value ?? ""));
  if (!m || Number(m[2]) < 1 || Number(m[2]) > 12) return DASH;
  return `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]} ${m[1]}`;
}

/**
 * Actual against budget (FIN-07): { amount, pct, favourable, material }. On a cost, spending less is
 * favourable; pass kind "revenue" where more is. Material: 5% of budget or more, and at least 1,000.
 */
export function variance(actual, budget, kind = "cost") {
  const a = num(actual) ?? 0, b = num(budget) ?? 0;
  const amount = Math.round((a - b) * 100) / 100;
  const pct = b ? Math.round((amount / Math.abs(b)) * 1000) / 10 : null;
  const favourable = kind === "revenue" ? amount >= 0 : amount <= 0;
  const material = Math.abs(amount) >= 1000 && (b === 0 || Math.abs(amount) * 100 >= Math.abs(b) * 5);
  return { amount, pct, favourable, material };
}

/* ---------------------------------------------------------------- the fiscal calendar */

const pad = (n) => String(n).padStart(2, "0");
const ymd = (y, m, d) => `${y}-${pad(m)}-${pad(d)}`;
const parts = (iso) => String(iso).slice(0, 10).split("-").map(Number);
const monthEnd = (y, m) => new Date(Date.UTC(y, m, 0)).getUTCDate();

function addMonths(iso, months) {
  const [y, m, d] = parts(iso);
  const index = y * 12 + (m - 1) + months;
  const year = Math.floor(index / 12), month = (index % 12) + 1;
  return ymd(year, month, Math.min(d, monthEnd(year, month)));
}

function addDays(iso, n) {
  const [y, m, d] = parts(iso);
  return new Date(Date.UTC(y, m - 1, d + n)).toISOString().slice(0, 10);
}

/**
 * The fiscal calendar, on dates written "2026-09-25":
 *   const cal = fin.calendar(4);                  a year that starts in April, named after the year it ends in
 *   cal.fiscalYear("2026-09-25")   2027           cal.quarter(…)  2        cal.period(…)  6
 *   cal.bounds("quarter", d)       ["2026-07-01", "2026-09-30"]           kinds: month, quarter, year
 *   cal.toDate("year", d)          ["2026-04-01", "2026-09-25"]
 *   cal.prior("month", d)          the month before       cal.yearAgo(from, to)   the same range a year earlier
 *   cal.label("quarter", d)        "Q2 FY2027"
 */
export function calendar(startMonth = settings.fiscalStartMonth) {
  const start = Math.min(12, Math.max(1, Number(startMonth) || 1));
  const cal = {
    startMonth: start,
    fiscalYear(iso) {
      const [y, m] = parts(iso);
      const first = m >= start ? y : y - 1;
      return start === 1 ? first : first + 1;
    },
    period(iso) { return ((parts(iso)[1] - start + 12) % 12) + 1; },
    quarter(iso) { return Math.floor((cal.period(iso) - 1) / 3) + 1; },
    yearStart(fiscalYear) { return ymd(start === 1 ? fiscalYear : fiscalYear - 1, start, 1); },
    bounds(kind, iso) {
      const [y, m] = parts(iso);
      if (kind === "month") return [ymd(y, m, 1), ymd(y, m, monthEnd(y, m))];
      let first = cal.yearStart(cal.fiscalYear(iso));
      const span = kind === "quarter" ? 3 : 12;
      if (kind === "quarter") first = addMonths(first, (cal.quarter(iso) - 1) * 3);
      const [ly, lm] = parts(addMonths(first, span - 1));
      return [first, ymd(ly, lm, monthEnd(ly, lm))];
    },
    toDate(kind, iso) { return [cal.bounds(kind, iso)[0], String(iso).slice(0, 10)]; },
    prior(kind, iso) { return cal.bounds(kind, addDays(cal.bounds(kind, iso)[0], -1)); },
    yearAgo(from, to) { return [addMonths(from, -12), addMonths(to, -12)]; },
    label(kind, iso) {
      const [y, m] = parts(iso);
      if (kind === "month") return `${MONTHS[m - 1]} ${y}`;
      return kind === "quarter" ? `Q${cal.quarter(iso)} FY${cal.fiscalYear(iso)}` : `FY${cal.fiscalYear(iso)}`;
    },
  };
  return cal;
}

/* ---------------------------------------------------------------- the insight API */

/** "?a=1&b=x" from an object; what is empty is left out, a list becomes "3,5", false is written "false". */
export function query(params) {
  const out = [];
  for (const [k, v] of Object.entries(params || {})) {
    const value = Array.isArray(v) ? v.join(",") : v;
    if (value === undefined || value === null || value === "") continue;
    out.push(`${encodeURIComponent(k)}=${encodeURIComponent(value)}`);
  }
  return out.length ? `?${out.join("&")}` : "";
}

const once = new WeakMap();

/**
 * The insight API as functions. Each takes the scope and its own parameters as one object:
 *   const data = fin.data(api);
 *   await data.kpis({ period: "this_quarter", compare: "prior_year", cost_center_id: 3 })
 *   await data.breakdown({ measure: "spend", by: "supplier", top: 10, from: "2026-04-01", to: "2026-09-30" })
 *   await data.documents({ entity: "invoice", overdue: true, dated: false })
 *   await data.match(invoice.id)                       three-way match; moves the invoice to matched or exception
 *   await data.receive(order.id, { amount: 1200 })     posts a goods receipt and moves the order
 *   await data.proposeRun({ due_by: "2026-10-09" })    a payment run of what is due, discounts taken
 *   await data.budgetPosition({ cost_center_id: 3, requested: 5000 })      what is left (FIN-02)
 *   await data.advice(requisition.id)                  approver, budget, quotes, supplier, splits
 *   await data.createRequisition({ title, amount, cost_center_id })       a draft, with its reference
 *   await data.raiseOrder(requisition.id, { supplier_id: 12 })            the order of an approved requisition
 *   await data.sendOrder(order.id)                     to the supplier, and into the ERP
 *   await data.approvals()                             what waits for my decision; data.decide(approvalId, true, "note")
 *   await data.worklist({ entity: "invoice" })         how many records are in each state
 *   await data.transition("invoice", id, "approve", { reason: "" })       a step of a record's lifecycle
 * calendar() and dimensions() are asked for once and remembered.
 */
export function data(api) {
  const get = (path, params) => api(`/finance/${path}${query(params)}`);
  const send = (path, body) => api(`/finance/${path}`, { method: "POST", body: body || {} });
  const kept = once.get(api) || {};
  once.set(api, kept);
  const remember = (name) => () => (kept[name] ||= get(name).catch((err) => { delete kept[name]; throw err; }));
  return {
    calendar: remember("calendar"),
    dimensions: remember("dimensions"),
    kpis: (p) => get("kpis", p),
    breakdown: (p) => get("breakdown", p),
    concentration: (p) => get("concentration", p),
    trend: (p) => get("trend", p),
    pivot: (p) => get("pivot", p),
    budget: (p) => get("budget", p),
    waterfall: (p) => get("waterfall", p),
    aging: (p) => get("aging", p),
    funnel: (p) => get("funnel", p),
    cycleTimes: (p) => get("cycle-times", p),
    exceptions: (p) => get("exceptions", p),
    accruals: (p) => get("accruals", p),
    renewals: (p) => get("renewals", p),
    controls: (p) => get("controls", p),
    documents: (p) => get("documents", p),
    scorecard: (id, p) => get(`suppliers/${encodeURIComponent(id)}/scorecard`, p),
    // What people do to their records; each goes through the record's workflow and is refused with its rule.
    matchPreview: (invoiceId) => get(`invoices/${encodeURIComponent(invoiceId)}/match`),
    match: (invoiceId) => send(`invoices/${encodeURIComponent(invoiceId)}/match`),
    receive: (orderId, body) => send(`purchase-orders/${encodeURIComponent(orderId)}/receive`, body),
    payable: (p) => get("payment-runs/payable", p),
    proposeRun: (body) => send("payment-runs/propose", body),
    budgetPosition: (p) => get("budget/position", p),
    advice: (requisitionId) => get(`requisitions/${encodeURIComponent(requisitionId)}/advice`),
    createRequisition: (body) => send("requisitions", body),
    raiseOrder: (requisitionId, body) => send(`requisitions/${encodeURIComponent(requisitionId)}/order`, body),
    sendOrder: (orderId) => send(`purchase-orders/${encodeURIComponent(orderId)}/send`),
    approvals: (p) => get("approvals", p),
    worklist: (p) => get("worklist", p),
    decide: (approvalId, approve, note) => api(`/platform/approvals/${encodeURIComponent(approvalId)}/${approve ? "approve" : "reject"}`, { method: "POST", body: { note: note || "" } }),
    transition: (entity, id, name, body) => api(`/platform/workflows/${encodeURIComponent(entity)}/${encodeURIComponent(id)}/${encodeURIComponent(name)}`, { method: "POST", body: body || {} }),
  };
}

/* ---------------------------------------------------------------- small pieces */

const TONES = { ok: "var(--ok-2)", warn: "var(--warn-2)", down: "var(--down-2)", info: "var(--info-2)", muted: "var(--faint)" };
const PALETTE = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)", "var(--chart-5)", "var(--chart-6)", "var(--chart-7)", "var(--chart-8)"];
const colour = (item, i) => item.color || TONES[item.tone] || PALETTE[i % PALETTE.length];

const STATUS_TONE = {
  over: "down", exceeded: "down", unbudgeted: "down", watch: "warn", warning: "warn", on_track: "ok", ok: "ok",
  matched: "ok", price_variance: "warn", quantity_variance: "warn", no_po: "down", no_receipt: "warn", duplicate_suspect: "down",
  expired: "down", notice_due: "down", expiring: "warn", active: "ok",
  low: "ok", medium: "warn", high: "down",
};
const STATUS_WORDS = { on_track: "On track", over: "Over budget", watch: "Watch", unbudgeted: "No budget", no_po: "No order",
  no_receipt: "No receipt", notice_due: "Notice due", duplicate_suspect: "Possible duplicate" };

/** A status as a badge, in finance's colours: fin.status("price_variance"), fin.status("over"). */
export function status(value, forced) {
  if (value === null || value === undefined || value === "") return h("span", { class: "faint" }, DASH);
  const key = String(value).toLowerCase();
  const tone = forced ?? STATUS_TONE[key];
  return ui.badge(STATUS_WORDS[key] || words(value), tone === undefined ? undefined : tone);
}

function tipFor(wrap) {
  const tip = h("div", { class: "fin-tip", role: "tooltip" });
  wrap.append(tip);
  return {
    /** lines: a title, then [label, value] pairs. */
    show(title, lines, el) {
      const a = el.getBoundingClientRect(), b = wrap.getBoundingClientRect();
      tip.replaceChildren(h("strong", {}, title), ...(lines || []).filter((l) => l && l[1] !== DASH && l[1] !== null && l[1] !== undefined)
        .map(([k, v, tone]) => h("span", { class: `fin-tip-row${tone ? ` fin-${tone}` : ""}` }, h("i", {}, k), h("b", {}, v))));
      const x = Math.max(70, Math.min(b.width - 70, a.left - b.left + a.width / 2));
      tip.style.left = `${x}px`;
      tip.style.top = `${Math.max(0, a.top - b.top)}px`;
      tip.classList.add("on");
    },
    hide() { tip.classList.remove("on"); },
  };
}

function nice(max) {
  if (!(max > 0)) return 1;
  const pow = 10 ** Math.floor(Math.log10(max));
  for (const step of [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (step * pow >= max) return step * pow;
  return 10 * pow;
}

function clip(text, max) {
  const t = String(text ?? "");
  return t.length > max ? `${t.slice(0, Math.max(1, max - 1)).trimEnd()}…` : t;
}

function nothing(title, hint) {
  return h("div", { class: "fin-empty" }, ui.icon("inbox", { size: 22 }), h("strong", {}, title || "Nothing to show"),
    hint ? h("span", {}, hint) : null);
}

function legend(items) {
  return h("div", { class: "fin-legend" }, items.filter(Boolean).map((i) =>
    h("span", { class: "fin-legend-item" }, h("i", { class: `fin-swatch${i.line ? ` fin-swatch-${i.line}` : ""}`, style: { background: i.line ? null : i.color, color: i.color } }), i.label)));
}

/**
 * How a figure moved, coloured by whether that is good: fin.delta(4.2, { good: "down" }) is red, up and "+4.2%".
 * opts: good "up" | "down" | "" (neither), points (a percentage's change, in points), favourable (decided already), label.
 */
export function delta(change, opts = {}) {
  css();
  const n = num(change);
  if (n === null) return h("span", { class: "fin-delta fin-flat" }, opts.empty || "no comparison");
  const dir = n > 0 ? "up" : n < 0 ? "down" : "flat";
  let fav = opts.favourable;
  if (fav === undefined || fav === null) fav = !opts.good || dir === "flat" ? null : (dir === opts.good);
  const cls = dir === "flat" || fav === null ? "fin-flat" : fav ? "fin-good" : "fin-bad";
  return h("span", { class: `fin-delta ${cls}`, title: fav === null ? null : fav ? "Favourable" : "Adverse" },
    dir === "flat" ? null : ui.icon(dir === "up" ? "trend-up" : "trend-down", { size: 12 }),
    percent(n, { signed: true, points: opts.points }), opts.label ? h("em", {}, opts.label) : null);
}

/** Actual against budget as a badge: "+£12.4k (4.1%) over" in red, "£8k (2%) under" in green. */
export function varianceBadge(actual, budget, opts = {}) {
  css();
  if (num(actual) === null || num(budget) === null) return h("span", { class: "faint" }, DASH);
  const v = variance(actual, budget, opts.kind);
  if (v.amount === 0) return h("span", { class: "fin-delta fin-flat" }, "on budget");
  const word = v.amount > 0 ? "over" : "under";
  return h("span", { class: `fin-delta ${v.favourable ? "fin-good" : "fin-bad"}`, title: v.material ? "Material: 5% of budget or more" : null },
    `${money(Math.abs(v.amount), { compact: true, currency: opts.currency })}${v.pct === null ? "" : ` (${percent(Math.abs(v.pct))})`} ${word}`);
}

/* ---------------------------------------------------------------- headline figures */

/**
 * Headline figures, as /api/finance/kpis returns them:
 *   fin.kpis(result.kpis, { compare: "vs last year", targets: { po_coverage: 95 }, onClick: (kpi) => … })
 * An item: { key, label, unit, value, change_pct, favourable, good, spark: [{ label, value }], about, icon, target }.
 */
export function kpis(items, opts = {}) {
  css();
  const list = (items || []).filter(Boolean);
  if (!list.length) return nothing("No figures for this period");
  return h("div", { class: "fin-kpis" }, list.map((k) => kpi(k, opts)));
}

export function kpi(k, opts = {}) {
  css();
  const target = num(k.target ?? (opts.targets || {})[k.key]);
  const value = h("div", { class: "fin-kpi-value" });
  ui.countUp(value, format(k.value, k.unit, { compact: true }));
  const points = (k.spark || []).map((p) => num(typeof p === "object" && p !== null ? p.value : p)).filter((v) => v !== null);
  let sparkTone;
  if (k.good && points.length > 1 && points[points.length - 1] !== points[0]) {
    sparkTone = (points[points.length - 1] > points[0]) === (k.good === "up") ? "ok" : "down";
  }
  let goal = null;
  if (target !== null && num(k.value) !== null) {
    const met = k.good === "down" ? k.value <= target : k.value >= target;
    const fill = h("span", { class: met ? "fin-met" : "fin-short" });
    const share = k.good === "down" ? (k.value ? target / k.value : 1) : (target ? k.value / target : 1);
    raf(() => { fill.style.width = `${Math.max(3, Math.min(100, share * 100))}%`; });
    goal = h("div", { class: "fin-goal", title: `Target ${format(target, k.unit, { compact: true })}` },
      h("div", { class: "fin-goal-track" }, fill),
      h("span", { class: met ? "fin-good-text" : "fin-bad-text" }, `${met ? "On" : "Off"} target ${format(target, k.unit, { compact: true })}`));
  }
  const click = opts.onClick && (k.drill || opts.always) ? () => opts.onClick(k) : null;
  return h("div", { class: `fin-kpi${click ? " interactive" : ""}`, title: k.about || null, onclick: click,
    tabindex: click ? 0 : null, role: click ? "button" : null,
    onkeydown: click ? (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); click(); } } : null },
    h("div", { class: "fin-kpi-top" }, h("span", { class: "stat-icon" }, ui.icon(k.icon || ui.guessIcon(k.label))),
      h("span", { class: "fin-kpi-label" }, k.label)),
    value,
    h("div", { class: "fin-kpi-foot" },
      k.position
        ? h("span", { class: "fin-delta fin-flat" }, "as of today")
        : delta(k.change_pct, { good: k.good, favourable: k.favourable, points: k.unit === "pct", label: opts.compare, empty: "no comparison" }),
      points.length > 1 ? ui.sparkline(points, { tone: sparkTone }) : null),
    goal);
}

/** A half-circle gauge 0–100 with bands: fin.gauge(42.5, { label: "Risk", bands: [[34, "ok"], [67, "warn"], [100, "down"]] }). */
export function gauge(value, opts = {}) {
  css();
  const n = num(value);
  const bands = opts.bands || [[34, "ok"], [67, "warn"], [100, "down"]];
  const W = 200, R = 80, cx = 100, cy = 96, width = 16;
  const at = (pct) => {
    const a = Math.PI * (1 - Math.max(0, Math.min(100, pct)) / 100);
    return [cx + R * Math.cos(a), cy - R * Math.sin(a)];
  };
  const arc = (from, to) => {
    const [x1, y1] = at(from), [x2, y2] = at(to);
    return `M${x1.toFixed(1)},${y1.toFixed(1)} A${R},${R} 0 0 1 ${x2.toFixed(1)},${y2.toFixed(1)}`;
  };
  let from = 0;
  const segments = bands.map(([to, tone]) => {
    const seg = s("path", { d: arc(from + 0.6, to - 0.6), fill: "none", stroke: TONES[tone] || tone, "stroke-width": width, opacity: 0.28 });
    from = to;
    return seg;
  });
  const tone = n === null ? "muted" : (bands.find(([to]) => n < to) || bands[bands.length - 1])[1];
  const needle = n === null ? null : s("path", { d: arc(0, Math.max(1, n)), fill: "none", stroke: TONES[tone] || tone,
    "stroke-width": width, "stroke-linecap": "round", class: "fin-gauge-value" });
  return h("div", { class: "fin-gauge" },
    s("svg", { viewBox: `0 0 ${W} 112`, role: "img", "aria-label": `${opts.label || "Score"} ${n === null ? "not known" : n}` }, segments, needle),
    h("div", { class: "fin-gauge-label" }, h("b", {}, n === null ? DASH : number(n, opts.digits ?? 0)),
      h("span", {}, opts.label || ""), opts.caption ? status(opts.caption, tone === "muted" ? "" : tone) : null));
}

/* ---------------------------------------------------------------- charts */

/**
 * A share of a whole, with the amounts written as amounts: fin.donut([{ label, value }], { unit: "money", sub: "spend", onClick }).
 * (ui.donut counts things; this one is for money and percentages.)
 */
export function donut(items, opts = {}) {
  css();
  const list = (items || []).filter((i) => i && (num(i.value) ?? 0) > 0);
  if (!list.length) return nothing("Nothing in this period");
  const unit = opts.unit || "money";
  const whole = list.reduce((a, i) => a + i.value, 0);
  const size = 168, r = 62, c = 2 * Math.PI * r;
  let start = 0;
  const segs = list.map((it, i) => {
    const len = (it.value / whole) * c;
    const seg = s("circle", { class: "donut-seg", cx: size / 2, cy: size / 2, r, stroke: colour(it, i), "stroke-dasharray": `0 ${c}`, "stroke-dashoffset": -start,
      style: { transition: `stroke-dasharray 1s ${0.08 * i}s cubic-bezier(.16,1,.3,1), stroke-width .2s, opacity .2s` } },
      s("title", {}, `${it.label}: ${format(it.value, unit)} (${percent((it.value / whole) * 100, { digits: 0 })})`));
    raf(() => seg.setAttribute("stroke-dasharray", `${Math.max(0, len - 1.5)} ${c}`));
    start += len;
    return seg;
  });
  const focus = (at) => segs.forEach((seg, i) => { seg.style.opacity = at === null || at === i ? "1" : ".3"; });
  const open = (it) => (opts.onClick && !it.other && it.key !== null && it.key !== undefined ? () => opts.onClick(it) : null);
  segs.forEach((seg, i) => {
    seg.addEventListener("mouseenter", () => focus(i));
    seg.addEventListener("mouseleave", () => focus(null));
    if (open(list[i])) { seg.style.cursor = "pointer"; seg.addEventListener("click", open(list[i])); }
  });
  return h("div", { class: "donut-wrap fin-donut" },
    s("svg", { class: "donut", viewBox: `0 0 ${size} ${size}`, role: "img", "aria-label": opts.label || "Shares" },
      s("circle", { cx: size / 2, cy: size / 2, r, fill: "none", stroke: "var(--surface-3)", "stroke-width": 18 }), segs,
      s("text", { class: "donut-center", x: size / 2, y: size / 2 + 4, "text-anchor": "middle" }, opts.center ?? format(whole, unit, { compact: true })),
      s("text", { class: "donut-sub", x: size / 2, y: size / 2 + 22, "text-anchor": "middle" }, opts.sub || "total")),
    h("div", { class: "legend" }, list.map((it, i) => h("div", { class: "legend-item", onmouseenter: () => focus(i), onmouseleave: () => focus(null),
      onclick: open(it), style: { cursor: open(it) ? "pointer" : null } },
      h("span", { class: "legend-swatch", style: { background: colour(it, i) } }), h("span", {}, it.label),
      h("b", {}, format(it.value, unit, { compact: true }), h("span", { class: "faint fin-share" }, percent((it.value / whole) * 100, { digits: 0 })))))));
}

/**
 * A chart drawn at the width it is given, in real pixels, and again when that width changes: text
 * stays the size it was written at, and a narrow widget shows fewer labels rather than smaller ones.
 * draw(svg, W, tip) fills the drawing.
 */
function chart(label, H, draw) {
  const wrap = h("div", { class: "fin-chart" });
  const holder = h("div", { class: "fin-chart-svg", style: { minHeight: `${H}px` } });
  wrap.append(holder);
  const tip = tipFor(wrap);
  let drawn = 0;
  const render = (width) => {
    const W = Math.max(260, Math.round(width));
    if (!(width > 0) || Math.abs(W - drawn) < 6) return;
    const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img", "aria-label": label || "Chart",
      class: drawn ? "fin-still" : null });
    drawn = W;
    tip.hide();
    draw(svg, W, tip);
    holder.replaceChildren(svg);
  };
  if (typeof ResizeObserver === "function") new ResizeObserver((entries) => render(entries[0].contentRect.width)).observe(holder);
  else render(760);
  return wrap;
}

function axis(svg, { left, right, top, base, max, min = 0, unit, steps = 4 }) {
  for (let i = 0; i <= steps; i++) {
    const v = min + ((max - min) * i) / steps;
    const y = base - ((base - top) * i) / steps;
    svg.append(s("line", { class: i ? "chart-grid" : "chart-axis", x1: left, x2: right, y1: y, y2: y }),
      s("text", { class: "fin-axis", x: left - 8, y: y + 4, "text-anchor": "end" }, format(v, unit, { compact: true, digits: 0 })));
  }
}

/**
 * A measure over time with what it is compared with: bars for the actual, a line for the budget,
 * a dashed line for last year. Points as /api/finance/trend returns them:
 *   fin.trend(result.points, { unit: "money", series: ["value", "budget", "prior"], cumulative: false, onClick: (point) => … })
 */
export function trend(points, opts = {}) {
  css();
  const pts = (points || []).filter(Boolean);
  if (!pts.length) return nothing("Nothing in this period");
  const unit = opts.unit || "money";
  const names = { value: "Actual", budget: "Budget", prior: "Last year", ...(opts.labels || {}) };
  const keys = opts.cumulative ? { value: "cumulative", budget: "cumulative_budget" } : { value: "value", budget: "budget", prior: "prior" };
  const wanted = (opts.series || ["value", "budget", "prior"]).filter((k) => keys[k] && pts.some((p) => num(p[keys[k]]) !== null));
  const H = opts.height || 280, left = 62, top = 16, base = H - 34;
  const all = wanted.flatMap((k) => pts.map((p) => num(p[keys[k]]) ?? 0));
  const max = nice(Math.max(1, ...all));
  const wrap = chart(opts.label || "Trend", H, (svg, W, tip) => {
  const right = W - 14;
  axis(svg, { left, right, top, base, max, unit });
  const slot = (right - left) / pts.length;
  const bw = Math.max(4, Math.min(44, slot * 0.58));
  const x = (i) => left + slot * i + slot / 2;
  const y = (v) => base - ((base - top) * Math.max(0, v)) / max;
  const every = Math.max(1, Math.ceil((pts.length * 64) / (right - left)));
  pts.forEach((p, i) => {
    if (i % every === 0) svg.append(s("text", { class: "fin-axis", x: x(i), y: H - 12, "text-anchor": "middle" }, clip(p.label, 12)));
  });
  if (wanted.includes("value")) {
    pts.forEach((p, i) => {
      const v = num(p[keys.value]);
      if (v === null || p.future) return;
      const hgt = Math.max(v ? 2 : 0, base - y(v));
      svg.append(s("rect", { class: `chart-col fin-col${p.partial ? " fin-partial" : ""}`, x: x(i) - bw / 2, y: base - hgt, width: bw, height: hgt,
        rx: Math.min(4, bw / 2), style: { animationDelay: `${Math.min(i * 0.03, 0.6)}s` } }));
    });
  }
  const path = (key, cls) => {
    const usable = pts.map((p, i) => [x(i), num(p[key]), p]).filter(([, v, p]) => v !== null && !(key === keys.value && p.future));
    if (usable.length < 2) return;
    const d = usable.map(([px, v], i) => `${i ? "L" : "M"}${px.toFixed(1)},${y(v).toFixed(1)}`).join(" ");
    svg.append(s("path", { class: `fin-line ${cls}`, d }));
    if (usable.length <= 24) usable.forEach(([px, v]) => svg.append(s("circle", { class: `fin-dot ${cls}`, cx: px, cy: y(v), r: 3 })));
  };
  if (wanted.includes("prior")) path(keys.prior, "fin-prior");
  if (wanted.includes("budget")) path(keys.budget, "fin-budget");
  pts.forEach((p, i) => {
    const hit = s("rect", { class: "fin-hit", x: left + slot * i, y: top, width: slot, height: base - top });
    const v = num(p[keys.value]), b = num(p[keys.budget]);
    const gap = v !== null && b !== null && !p.future ? variance(v, b, opts.kind) : null;
    hit.addEventListener("mouseenter", () => tip.show(`${p.label}${p.partial ? " (so far)" : ""}`, [
      wanted.includes("value") && !p.future ? [names.value, format(v, unit)] : null,
      wanted.includes("budget") ? [names.budget, format(b, unit)] : null,
      wanted.includes("prior") ? [names.prior, format(p[keys.prior], unit)] : null,
      gap && wanted.includes("budget") ? ["Variance", `${format(gap.amount, unit, { signed: true })}${gap.pct === null ? "" : ` (${percent(gap.pct, { signed: true })})`}`, gap.favourable ? "good-text" : "bad-text"] : null,
    ], hit));
    hit.addEventListener("mouseleave", () => tip.hide());
    if (opts.onClick && !p.future) { hit.style.cursor = "pointer"; hit.addEventListener("click", () => opts.onClick(p)); }
    svg.append(hit);
  });
  });
  wrap.prepend(legend([
    wanted.includes("value") ? { label: names.value, color: "var(--accent)" } : null,
    wanted.includes("budget") ? { label: names.budget, color: "var(--warn-2)", line: "solid" } : null,
    wanted.includes("prior") ? { label: names.prior, color: "var(--faint)", line: "dashed" } : null,
  ]));
  return wrap;
}

/**
 * Budget against actual, a bar per group with the budget as a marker, as /api/finance/budget returns rows:
 *   fin.budgetBars(result.rows, { view: "period" | "year", limit: 8, elapsed: result.totals.elapsed_pct, onClick: (row) => … })
 * "period": what was spent against the period's budget. "year": spent and committed against the year's budget,
 * with a line where the year is today.
 */
export function budgetBars(rows, opts = {}) {
  css();
  const list = (rows || []).filter(Boolean);
  if (!list.length) return nothing("No budget for this period", "Budget lines appear here once they are loaded.");
  const year = opts.view === "year";
  const limit = opts.limit || 8;
  const SCALE = 1.35;                               // the budget sits at 100 / 135 of the track, so an overspend has room
  const holder = h("div", { class: "fin-budget" });
  let open = false;
  const draw = () => {
    const shown = open ? list : list.slice(0, limit);
    put(holder, shown.map((r, i) => {
      const budget = num(year ? r.year_budget : r.budget) ?? 0;
      const actual = num(year ? r.year_actual : r.actual) ?? 0;
      const committed = year ? (num(r.committed) ?? 0) : 0;
      const tone = STATUS_TONE[year ? r.position : r.status] || "info";
      const share = (v) => (budget > 0 ? Math.min(SCALE, v / budget) / SCALE : v > 0 ? 1 : 0) * 100;
      const fill = h("span", { class: `fin-fill fin-fill-${tone}`, style: { transitionDelay: `${i * 0.04}s` } });
      const hatch = committed ? h("span", { class: "fin-fill fin-committed", style: { transitionDelay: `${i * 0.04 + 0.2}s` } }) : null;
      raf(() => {
        fill.style.width = `${share(actual)}%`;
        if (hatch) { hatch.style.left = `${share(actual)}%`; hatch.style.width = `${Math.max(0, share(actual + committed) - share(actual))}%`; }
      });
      const click = opts.onClick ? () => opts.onClick(r) : null;
      return h("div", { class: `fin-budget-row${click ? " clickable" : ""}`, onclick: click,
        title: year ? `${r.label}: ${money(actual, { whole: true })} spent and ${money(committed, { whole: true })} committed of ${money(budget, { whole: true })}; ${money(r.available, { whole: true })} left`
          : `${r.label}: ${money(actual, { whole: true })} of ${money(budget, { whole: true })}` },
        h("span", { class: "fin-budget-label" }, r.label),
        h("span", { class: "fin-track" }, fill, hatch,
          budget > 0 ? h("i", { class: "fin-marker", style: { left: `${100 / SCALE}%` } }) : null,
          year && num(opts.elapsed) !== null ? h("i", { class: "fin-today", style: { left: `${(opts.elapsed / SCALE)}%` } }) : null),
        h("span", { class: "fin-budget-figures" },
          h("b", {}, money(actual, { compact: true })), h("span", { class: "faint" }, ` of ${money(budget, { compact: true })}`)),
        year ? h("span", { class: `fin-delta ${(num(r.available) ?? 0) < 0 ? "fin-bad" : "fin-flat"}` }, `${money(r.available, { compact: true })} left`)
          : varianceBadge(actual, budget));
    }),
    list.length > limit ? h("button", { class: "ghost sm fin-more", type: "button", onclick: () => { open = !open; draw(); } },
      open ? "Show fewer" : `Show all ${list.length}`) : null);
  };
  draw();
  return h("div", { class: "fin-budget-wrap" }, legend([
    { label: year ? "Spent" : "Actual", color: "var(--accent)" },
    year ? { label: "Committed", color: "var(--accent)", line: "hatch" } : null,
    { label: "Budget", color: "var(--ink)", line: "marker" },
    year && num(opts.elapsed) !== null ? { label: "Today", color: "var(--faint)", line: "dashed" } : null,
  ]), holder);
}

/**
 * The walk from one figure to another, as /api/finance/waterfall returns it:
 *   fin.waterfall({ start: { label: "Budget", value }, steps: [{ label, value, favourable }], end: { label: "Actual", value } })
 */
export function waterfall(data, opts = {}) {
  css();
  if (!data || !data.start || !data.end) return nothing("Nothing to compare");
  const unit = opts.unit || "money";
  const steps = (data.steps || []).filter((st) => num(st.value));
  const bars = [{ ...data.start, total: true }];
  let level = num(data.start.value) ?? 0;
  for (const st of steps) {
    const from = level;
    level += num(st.value);
    bars.push({ ...st, from, to: level });
  }
  bars.push({ ...data.end, total: true });
  const levels = bars.flatMap((b) => (b.total ? [num(b.value) ?? 0] : [b.from, b.to]));
  const hi = Math.max(...levels), lo = Math.min(...levels);
  // When the steps are small beside the totals, the axis starts near them, and says so.
  const cut = lo > 0 && (hi - lo) < hi * 0.35 ? Math.max(0, lo - (hi - lo) * 0.6) : 0;
  const floor = cut ? Math.floor(cut / nice((hi - cut) / 4)) * nice((hi - cut) / 4) : 0;
  const max = floor + nice(hi - floor);
  const H = opts.height || 320, left = 62, top = 22;
  const wrap = chart(opts.label || "Waterfall", H, (svg, W, tip) => {
  const right = W - 14;
  const slot = (right - left) / bars.length;
  const slant = slot < 92;
  const base = H - (slant ? 84 : 40);
  axis(svg, { left, right, top, base, max, min: floor, unit });
  const bw = Math.min(64, slot * 0.62);
  const y = (v) => base - ((base - top) * (Math.max(floor, v) - floor)) / (max - floor);
  bars.forEach((b, i) => {
    const x = left + slot * i + (slot - bw) / 2;
    const a = b.total ? floor : b.from, z = b.total ? (num(b.value) ?? 0) : b.to;
    const topY = Math.min(y(a), y(z)), hgt = Math.max(2, Math.abs(y(a) - y(z)));
    const cls = b.total ? "fin-wf-total" : (b.favourable ?? num(b.value) <= 0) ? "fin-wf-good" : "fin-wf-bad";
    const rect = s("rect", { class: `fin-wf ${cls}`, x, y: topY, width: bw, height: hgt, rx: 3, style: { animationDelay: `${i * 0.07}s` } });
    rect.addEventListener("mouseenter", () => tip.show(b.label, b.total ? [["Total", format(b.value, unit)]]
      : [["Change", format(b.value, unit, { signed: true }), (b.favourable ?? b.value <= 0) ? "good-text" : "bad-text"], ["Running total", format(b.to, unit)]], rect));
    rect.addEventListener("mouseleave", () => tip.hide());
    if (opts.onClick && !b.total && b.key !== null && b.key !== undefined) { rect.style.cursor = "pointer"; rect.addEventListener("click", () => opts.onClick(b)); }
    svg.append(rect,
      slot >= 58 || b.total ? s("text", { class: "fin-value", x: x + bw / 2, y: topY - 6, "text-anchor": i === 0 && slot < 58 ? "start" : i === bars.length - 1 && slot < 58 ? "end" : "middle" },
        format(b.value, unit, { compact: true, signed: !b.total })) : null,
      slant ? s("text", { class: "fin-axis fin-slant", x: x + bw / 2 + 4, y: base + 14, "text-anchor": "end",
        transform: `rotate(-35 ${x + bw / 2 + 4} ${base + 14})` }, clip(b.label, 15))
        : s("text", { class: "fin-axis", x: x + bw / 2, y: base + 16, "text-anchor": "middle" }, clip(b.label, Math.floor(slot / 6.6))));
    if (i < bars.length - 1) {
      const next = b.total ? (num(b.value) ?? 0) : b.to;
      svg.append(s("line", { class: "fin-wf-link", x1: x + bw, x2: x + slot, y1: y(next), y2: y(next) }));
    }
  });
  });
  if (floor) wrap.append(h("div", { class: "fin-note" }, `The axis starts at ${format(floor, unit, { compact: true })} so the steps can be seen.`));
  wrap.prepend(legend([{ label: "Favourable", color: "var(--ok-2)" }, { label: "Adverse", color: "var(--down-2)" }, { label: "Total", color: "var(--accent)" }]));
  return wrap;
}

/**
 * The largest first with the running share: which few make up most of it. Items as
 * /api/finance/concentration returns them ({ label, value, cumulative_pct }), or any { label, value } list.
 *   fin.pareto(result.items, { top: 12, cut: 80, onClick: (item) => … })
 */
export function pareto(items, opts = {}) {
  css();
  let list = (items || []).filter((i) => i && (num(i.value) ?? 0) > 0).sort((a, b) => b.value - a.value);
  if (!list.length) return nothing("Nothing in this period");
  const whole = list.reduce((a, i) => a + i.value, 0);
  let running = 0;
  list = list.map((i) => { running += i.value; return { ...i, cumulative_pct: num(i.cumulative_pct) ?? Math.round((running / whole) * 1000) / 10 }; });
  const cutPct = opts.cut || 80;
  const cutAt = list.findIndex((i) => i.cumulative_pct >= cutPct) + 1;
  const all = list.length;
  const ranked = list;
  const unit = opts.unit || "money";
  const H = opts.height || 320, left = 62, top = 16, base = H - 84;
  const max = nice(ranked[0].value);
  const note = h("div", { class: "fin-note" });
  const wrap = chart(opts.label || "Pareto", H, (svg, W, tip) => {
  const right = W - 46;
  list = ranked.slice(0, Math.max(3, Math.min(opts.top || 12, Math.floor((right - left) / 38))));
  note.textContent = `${number(cutAt)} of ${number(all)} make up ${cutPct}% of the total`
    + (all > list.length ? `; the largest ${list.length} are shown.` : ".");
  axis(svg, { left, right, top, base, max, unit });
  const slot = (right - left) / list.length, bw = Math.min(46, slot * 0.64);
  const yp = (pct) => base - ((base - top) * pct) / 100;
  for (const pct of [50, 100]) svg.append(s("text", { class: "fin-axis", x: right + 6, y: yp(pct) + 4 }, `${pct}%`));
  svg.append(s("line", { class: "fin-cut", x1: left, x2: right, y1: yp(cutPct), y2: yp(cutPct) }),
    s("text", { class: "fin-axis fin-cut-text", x: right + 6, y: yp(cutPct) + 4 }, `${cutPct}%`));
  const line = [];
  list.forEach((it, i) => {
    const x = left + slot * i + (slot - bw) / 2;
    const hgt = Math.max(2, ((base - top) * it.value) / max);
    const rect = s("rect", { class: `chart-col fin-col${i < cutAt ? "" : " fin-tail"}`, x, y: base - hgt, width: bw, height: hgt, rx: 3,
      style: { animationDelay: `${Math.min(i * 0.04, 0.6)}s` } });
    rect.addEventListener("mouseenter", () => tip.show(it.label, [[opts.measure || "Value", format(it.value, unit)],
      ["Share", percent(it.share_pct ?? (it.value / whole) * 100)], ["Running share", percent(it.cumulative_pct)],
      it.count ? ["Documents", number(it.count)] : null], rect));
    rect.addEventListener("mouseleave", () => tip.hide());
    if (opts.onClick && it.key !== null && it.key !== undefined) { rect.style.cursor = "pointer"; rect.addEventListener("click", () => opts.onClick(it)); }
    svg.append(rect);
    svg.append(s("text", { class: "fin-axis fin-slant", x: x + bw / 2 + 4, y: base + 14, "text-anchor": "end",
      transform: `rotate(-35 ${x + bw / 2 + 4} ${base + 14})` }, clip(it.label, 15)));
    line.push([x + bw / 2, yp(it.cumulative_pct)]);
  });
  if (line.length > 1) {
    svg.append(s("path", { class: "fin-line fin-cumulative", d: line.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ") }));
    line.forEach((p) => svg.append(s("circle", { class: "fin-dot fin-cumulative", cx: p[0], cy: p[1], r: 3 })));
  }
  });
  wrap.append(note);
  return wrap;
}

function squarify(items, W, H) {
  const total = items.reduce((a, i) => a + i.value, 0) || 1;
  const rest = items.map((i) => ({ item: i, area: (i.value / total) * W * H }));
  const out = [];
  let box = { x: 0, y: 0, w: W, h: H };
  let row = [];
  const sum = (r) => r.reduce((a, i) => a + i.area, 0);
  const worst = (r, side) => {
    const total_ = sum(r);
    const big = Math.max(...r.map((i) => i.area)), small = Math.min(...r.map((i) => i.area));
    return Math.max((side * side * big) / (total_ * total_), (total_ * total_) / (side * side * small));
  };
  const place = () => {
    const area = sum(row);
    if (box.w >= box.h) {
      const w = area / box.h;
      let y = box.y;
      for (const r of row) { const hh = r.area / w; out.push({ ...r, x: box.x, y, w, h: hh }); y += hh; }
      box = { x: box.x + w, y: box.y, w: box.w - w, h: box.h };
    } else {
      const hh = area / box.w;
      let x = box.x;
      for (const r of row) { const w = r.area / hh; out.push({ ...r, x, y: box.y, w, h: hh }); x += w; }
      box = { x: box.x, y: box.y + hh, w: box.w, h: box.h - hh };
    }
    row = [];
  };
  while (rest.length) {
    const side = Math.min(box.w, box.h);
    if (!row.length || worst([...row, rest[0]], side) <= worst(row, side)) row.push(rest.shift());
    else place();
  }
  if (row.length) place();
  return out;
}

/** Spend as areas: fin.treemap([{ label, value, share_pct }], { onClick }). What is too small to read goes into "Other". */
export function treemap(items, opts = {}) {
  css();
  let list = (items || []).filter((i) => i && (num(i.value) ?? 0) > 0).sort((a, b) => b.value - a.value);
  if (!list.length) return nothing("Nothing in this period");
  const whole = list.reduce((a, i) => a + i.value, 0);
  const keep = opts.top || 14;
  const small = list.filter((i, n) => n >= keep || i.value / whole < 0.012);
  if (small.length > 1) {
    list = list.filter((i) => !small.includes(i));
    list.push({ label: `Other (${small.length})`, value: small.reduce((a, i) => a + i.value, 0), key: null, other: true });
  }
  const unit = opts.unit || "money";
  const H = opts.height || 320;
  return chart(opts.label || "Treemap", H, (svg, W, tip) => squarify(list, W, H).forEach((cell, i) => {
    const it = cell.item;
    const g = s("g", { class: "fin-cell", style: { animationDelay: `${Math.min(i * 0.03, 0.5)}s` } });
    const rect = s("rect", { x: cell.x + 1.5, y: cell.y + 1.5, width: Math.max(0, cell.w - 3), height: Math.max(0, cell.h - 3), rx: 5,
      fill: it.other ? "var(--surface-3)" : colour(it, i) });
    g.append(rect);
    if (cell.w > 62 && cell.h > 30) {
      g.append(s("text", { class: `fin-cell-label${it.other ? " fin-dark" : ""}`, x: cell.x + 11, y: cell.y + 23 }, clip(it.label, Math.floor((cell.w - 16) / 7.4))));
      if (cell.h > 50 && cell.w > 96) g.append(s("text", { class: `fin-cell-value${it.other ? " fin-dark" : ""}`, x: cell.x + 11, y: cell.y + 42 },
        `${format(it.value, unit, { compact: true })} · ${percent((it.value / whole) * 100, { digits: 0 })}`));
    }
    g.addEventListener("mouseenter", () => tip.show(it.label, [[opts.measure || "Value", format(it.value, unit)],
      ["Share", percent((it.value / whole) * 100)], it.count ? ["Documents", number(it.count)] : null], rect));
    g.addEventListener("mouseleave", () => tip.hide());
    if (opts.onClick && !it.other && it.key !== null && it.key !== undefined) { g.style.cursor = "pointer"; g.addEventListener("click", () => opts.onClick(it)); }
    svg.append(g);
  }));
}

const AGE_TONES = ["var(--ok-2)", "var(--chart-7)", "var(--warn-2)", "var(--chart-3)", "var(--down-2)"];

/** What is owed by how overdue it is, as /api/finance/aging returns buckets: fin.aging(result.buckets, { onClick: (bucket) => … }). */
export function aging(buckets, opts = {}) {
  css();
  const list = (buckets || []).filter(Boolean);
  const whole = list.reduce((a, b) => a + (num(b.value) ?? 0), 0);
  if (!list.length || !whole) return nothing("Nothing is owed", "Open invoices appear here by how overdue they are.");
  const late = list.filter((b) => b.overdue).reduce((a, b) => a + (num(b.value) ?? 0), 0);
  const bar = h("div", { class: "fin-stack", role: "img", "aria-label": "Open payables by age" }, list.map((b, i) => {
    const seg = h("span", { class: "fin-seg", style: { background: AGE_TONES[i % AGE_TONES.length] },
      title: `${b.label}: ${money(b.value, { whole: true })} (${percent(b.share_pct ?? ((b.value || 0) / whole) * 100)})`,
      onclick: opts.onClick ? () => opts.onClick(b) : null });
    raf(() => { seg.style.flexGrow = String(Math.max(0, num(b.value) ?? 0)); });
    if (opts.onClick) seg.style.cursor = "pointer";
    return seg;
  }));
  return h("div", { class: "fin-aging" },
    h("div", { class: "fin-aging-head" },
      h("div", {}, h("b", {}, money(whole, { compact: true })), h("span", { class: "faint" }, " owed")),
      h("div", {}, h("b", { class: late ? "fin-bad-text" : "fin-good-text" }, money(late, { compact: true })),
        h("span", { class: "faint" }, ` overdue (${percent((late / whole) * 100, { digits: 0 })})`))),
    bar,
    h("div", { class: "fin-aging-rows" }, list.map((b, i) =>
      h("div", { class: `fin-aging-row${opts.onClick ? " clickable" : ""}`, onclick: opts.onClick ? () => opts.onClick(b) : null },
        h("i", { class: "fin-swatch", style: { background: AGE_TONES[i % AGE_TONES.length] } }),
        h("span", {}, b.label === "Not due" ? "Not due" : `${b.label} days`),
        h("span", { class: "faint" }, `${number(b.count)} ${b.count === 1 ? "invoice" : "invoices"}`),
        h("b", { class: "mono" }, money(b.value, { whole: true })),
        h("span", { class: "faint right" }, percent(b.share_pct ?? ((b.value || 0) / whole) * 100, { digits: 0 }))))));
}

/** The steps of a process and how many reach each: fin.funnel(result.stages, { onClick }). A stage: { label, count, value, of_first_pct, of_previous_pct }. */
export function funnel(stages, opts = {}) {
  css();
  const list = (stages || []).filter(Boolean);
  const first = list.length ? (num(list[0].count) ?? 0) : 0;
  if (!first) return nothing("Nothing was requested in this period");
  return h("div", { class: "fin-funnel" }, list.map((st, i) => {
    const bar = h("span", { class: "fin-funnel-bar", style: { background: PALETTE[i % PALETTE.length], transitionDelay: `${i * 0.08}s` } });
    raf(() => { bar.style.width = `${Math.max(4, ((num(st.count) ?? 0) / first) * 100)}%`; });
    const kept = num(st.of_previous_pct);
    return [
      i ? h("div", { class: "fin-funnel-step" }, ui.icon("chevron-down", { size: 13 }),
        kept === null ? "" : `${percent(kept, { digits: 0 })} go on`,
        kept !== null && kept < 100 ? h("span", { class: "faint" }, ` · ${number(list[i - 1].count - st.count)} have not yet`) : null) : null,
      h("div", { class: `fin-funnel-row${opts.onClick ? " clickable" : ""}`, onclick: opts.onClick ? () => opts.onClick(st) : null },
        h("span", { class: "fin-funnel-label" }, st.label),
        h("span", { class: "fin-funnel-track" }, bar),
        h("span", { class: "fin-funnel-figures" }, h("b", {}, number(st.count)),
          num(st.value) !== null ? h("span", { class: "faint" }, ` · ${money(st.value, { compact: true })}`) : null)),
    ];
  }));
}

/**
 * A cross-tab with totals, shaded by value, as /api/finance/pivot returns it:
 *   fin.pivot(result, { unit: "money", heat: true, exportable: "spend-by-cost-centre", onClick: (row, column, value) => … })
 */
export function pivot(data, opts = {}) {
  css();
  const rows = (data && data.rows) || [], columns = (data && data.columns) || [];
  if (!rows.length || !columns.length) return nothing("Nothing in this period");
  const unit = opts.unit || "money";
  const peak = Math.max(1, ...rows.flatMap((r) => r.cells.map((c) => Math.abs(num(c) ?? 0))));
  const cell = (value, r, c) => {
    const v = num(value) ?? 0;
    const shade = opts.heat === false || !v ? null : `color-mix(in srgb, var(--accent) ${Math.round(6 + (Math.abs(v) / peak) * 46)}%, transparent)`;
    const click = opts.onClick && r.key !== null && r.key !== undefined ? () => opts.onClick(r, c, v) : null;
    return h("td", { class: `right mono${click ? " clickable" : ""}`, style: { background: shade }, onclick: click,
      title: `${r.label} · ${c.label}: ${format(v, unit)}` }, v ? format(v, unit, { compact: true }) : h("span", { class: "faint" }, DASH));
  };
  const table = h("table", { class: "fin-pivot" },
    h("thead", {}, h("tr", {}, h("th", {}, opts.rowLabel || words(data.row_by) || ""), columns.map((c) => h("th", { class: "right" }, c.label)),
      h("th", { class: "right" }, "Total"))),
    h("tbody", {}, rows.map((r) => h("tr", {}, h("th", { scope: "row" }, r.label), r.cells.map((v, i) => cell(v, r, columns[i])),
      h("td", { class: "right mono fin-total" }, format(r.total, unit, { compact: true }))))),
    h("tfoot", {}, h("tr", {}, h("th", { scope: "row" }, "Total"),
      (data.totals || []).map((v) => h("td", { class: "right mono" }, format(v, unit, { compact: true }))),
      h("td", { class: "right mono fin-total" }, format(data.total, unit, { compact: true })))));
  const tools = opts.exportable ? h("div", { class: "toolbar" }, h("span", { class: "toolbar-right" },
    ui.button("Export", { tone: "secondary", icon: "download", size: "sm", onclick: () => exportCsv(
      typeof opts.exportable === "string" ? opts.exportable : "pivot", pivotRows(data)) }))) : null;
  return h("div", { class: "stack" }, tools, h("div", { class: "table-wrap fin-pivot-wrap" }, table));
}

function pivotRows(data) {
  const head = [words(data.row_by) || "Row", ...data.columns.map((c) => c.label), "Total"];
  const body = data.rows.map((r) => [r.label, ...r.cells, r.total]);
  return [head, ...body, ["Total", ...(data.totals || []), data.total]];
}

/** How long each step takes, as /api/finance/cycle-times returns steps: average, median and the slowest tenth. */
export function cycleTimes(steps, opts = {}) {
  css();
  const list = (steps || []).filter((st) => st && num(st.average_days) !== null);
  if (!list.length) return nothing("No completed steps in this period");
  const max = Math.max(1, ...list.map((st) => num(st.p90_days) ?? num(st.average_days) ?? 0));
  return h("div", { class: "fin-cycle" }, list.map((st, i) => {
    const avg = h("span", { class: "fin-cycle-avg", style: { transitionDelay: `${i * 0.06}s` } });
    const tail = h("span", { class: "fin-cycle-p90", style: { transitionDelay: `${i * 0.06}s` } });
    raf(() => { avg.style.width = `${(st.average_days / max) * 100}%`; tail.style.width = `${((num(st.p90_days) ?? st.average_days) / max) * 100}%`; });
    const before = num(st.prior_average_days);
    const change = before ? ((st.average_days - before) / before) * 100 : null;
    const target = num((opts.targets || {})[st.label]);
    return h("div", { class: "fin-cycle-row", title: `${number(st.count)} completed · median ${days(st.median_days)} · slowest tenth over ${days(st.p90_days)}` },
      h("span", { class: "fin-cycle-label" }, st.label),
      h("span", { class: "fin-track" }, tail, avg, target !== null ? h("i", { class: "fin-marker", style: { left: `${Math.min(100, (target / max) * 100)}%` } }) : null),
      h("b", {}, days(st.average_days)),
      change === null ? h("span", { class: "faint" }, "") : delta(change, { good: "down" }));
  }), h("div", { class: "fin-note" }, "The bar is the average; the pale bar reaches the slowest tenth."));
}

/* ---------------------------------------------------------------- records */

/**
 * The three-way match of an invoice (PROC-01): what was ordered, received and invoiced, and where they differ.
 *   fin.matchStatus({ status: "price_variance", ordered: 10000, received: 10000, invoiced: 10420, discrepancies: ["…"] })
 */
export function matchStatus(match, opts = {}) {
  css();
  const m = match || {};
  const key = String(m.status || m.match_status || "").toLowerCase();
  const o = num(m.ordered), r = num(m.received), v = num(m.invoiced);
  const box = (label, amount, icon, missing) => h("div", { class: `fin-match-box${missing ? " fin-missing" : ""}` },
    h("span", { class: "stat-icon" }, ui.icon(icon)), h("span", { class: "faint" }, label),
    h("b", {}, missing ? "None" : money(amount, { currency: opts.currency })));
  const link = (a, b) => {
    if (a === null || b === null) return h("div", { class: "fin-match-link fin-match-open" }, ui.icon("x", { size: 14 }));
    const gap = Math.round((b - a) * 100) / 100;
    return h("div", { class: `fin-match-link ${gap > 0 ? "fin-match-off" : "fin-match-ok"}` },
      ui.icon(gap > 0 ? "alert" : "check", { size: 14 }), gap ? h("span", {}, money(gap, { signed: true, currency: opts.currency })) : null);
  };
  return h("div", { class: "fin-match" },
    h("div", { class: "fin-match-head" }, h("strong", {}, "Three-way match"), key ? status(key) : null),
    h("div", { class: "fin-match-row" },
      box("Ordered", o, "cart", key === "no_po" || o === null), link(o, r),
      box("Received", r, "truck", key === "no_receipt" || r === null), link(r, v),
      box("Invoiced", v, "file", v === null)),
    (m.discrepancies || []).length ? h("ul", { class: "fin-match-notes" }, m.discrepancies.map((d) => h("li", {}, d))) : null);
}

/**
 * Who approves an amount under the delegation of authority (PROC-02):
 *   fin.approvalChain(18400, [{ up_to: 5000, role: "budget_holder" }, …, { up_to: null, role: "cfo" }],
 *                     { roles: { budget_holder: "Budget holder" }, decided: [{ role, by, status: "approved" }] })
 */
export function approvalChain(amount, matrix, opts = {}) {
  css();
  const value = num(amount);
  const steps = (matrix || []).map((m) => (Array.isArray(m) ? { up_to: m[0], role: m[1] } : m));
  const at = value === null ? -1 : steps.findIndex((st) => st.up_to === null || st.up_to === undefined || value <= st.up_to);
  const decided = Object.fromEntries((opts.decided || []).map((d) => [d.role, d]));
  return h("div", { class: "fin-chain" },
    value === null ? null : h("div", { class: "fin-chain-head" }, h("b", {}, money(value, { currency: opts.currency })),
      at >= 0 ? h("span", { class: "faint" }, ` needs ${(opts.roles || {})[steps[at].role] || words(steps[at].role)}`) : null),
    h("ol", { class: "fin-chain-steps" }, steps.map((st, i) => {
      const done = decided[st.role];
      const state = done ? (done.status === "rejected" ? "down" : "ok") : i === at ? "on" : i < at ? "skip" : "off";
      return h("li", { class: `fin-chain-step fin-chain-${state}` },
        h("span", { class: "fin-chain-dot" }, state === "ok" ? ui.icon("check", { size: 12 }) : state === "down" ? ui.icon("x", { size: 12 }) : String(i + 1)),
        h("span", { class: "fin-chain-role" }, (opts.roles || {})[st.role] || words(st.role)),
        h("span", { class: "faint" }, st.up_to === null || st.up_to === undefined ? "any amount above" : `up to ${money(st.up_to, { whole: true, currency: opts.currency })}`),
        done ? h("span", { class: "faint" }, `${words(done.status || "approved")}${done.by ? ` by ${done.by}` : ""}`) : null);
    })));
}

/**
 * Where a record is in its lifecycle: fin.lifecycle(["draft", "submitted", "approved", "ordered"], "approved",
 *   { labels: { draft: "Draft" }, aside: ["rejected", "cancelled"] }). A state in `aside` ends the path where it stands.
 */
export function lifecycle(states, current, opts = {}) {
  css();
  const aside = new Set(opts.aside || ["rejected", "cancelled", "exception", "suspended", "retired", "terminated", "failed", "expired"]);
  const all = (states || []).map((st) => (typeof st === "object" ? st : { key: st, label: (opts.labels || {})[st] || words(st) }));
  const path = all.filter((st) => !aside.has(st.key) || st.key === current);
  const off = aside.has(current);
  const at = path.findIndex((st) => st.key === current);
  return h("ol", { class: "fin-life" }, path.filter((st) => !aside.has(st.key) || st.key === current).map((st, i) => {
    const state = st.key === current ? (off ? "down" : "on") : at >= 0 && i < at && !off ? "ok" : "off";
    return h("li", { class: `fin-life-step fin-life-${state}`, "aria-current": st.key === current ? "step" : null },
      h("span", { class: "fin-life-dot" }, state === "ok" ? ui.icon("check", { size: 11 }) : null), h("span", {}, st.label));
  }));
}

/** The controls a finance team watches, as /api/finance/controls returns them: fin.controlList(result.controls, { onClick: (control) => … }). */
export function controlList(controls, opts = {}) {
  css();
  const list = (controls || []).filter(Boolean);
  if (!list.length) return nothing("No controls to report");
  return h("div", { class: "fin-controls" }, list.map((c) => {
    const tone = c.count ? (c.severity === "down" ? "down" : "warn") : "ok";
    const click = opts.onClick && c.count ? () => opts.onClick(c) : null;
    return h("div", { class: `fin-control fin-control-${tone}${click ? " clickable" : ""}`, onclick: click, title: c.about || null },
      h("span", { class: "fin-control-icon" }, ui.icon(c.count ? "alert" : "check-circle", { size: 17 })),
      h("div", { class: "fin-control-text" }, h("strong", {}, c.label), h("span", { class: "faint" }, c.about || "")),
      h("span", { class: "badge" }, c.rule),
      h("b", { class: "fin-control-count" }, c.count ? number(c.count) : "Clear"),
      h("span", { class: "faint mono right" }, c.count && num(c.amount) !== null ? money(c.amount, { compact: true }) : ""));
  }));
}

/** Contracts to decide on, as /api/finance/renewals returns rows: fin.renewalList(result.rows, { limit: 8, onClick }). */
export function renewalList(rows, opts = {}) {
  css();
  const list = (rows || []).filter(Boolean).slice(0, opts.limit || 8);
  if (!list.length) return nothing("No contracts to decide on", "Contracts appear here 90 days before they end.");
  return h("div", { class: "fin-renewals" }, list.map((c) => {
    const left = num(c.days_left);
    return h("div", { class: `fin-renewal${opts.onClick ? " clickable" : ""}`, onclick: opts.onClick ? () => opts.onClick(c) : null, title: c.note || null },
      h("div", { class: "fin-renewal-text" }, h("strong", {}, c.title || c.reference), h("span", { class: "faint" }, [c.supplier_name, c.reference].filter(Boolean).join(" · "))),
      status(c.renewal),
      h("span", { class: "fin-renewal-when" }, h("b", {}, left === null ? DASH : left < 0 ? `${number(-left)} days ago` : `${number(left)} days`),
        h("span", { class: "faint" }, `decide by ${date(c.decide_by)}`)),
      h("span", { class: "mono right" }, money(c.annual_value ?? c.value, { compact: true })));
  }));
}

const RISK_NAMES = { delivery: "Delivery", quality: "Quality", financial: "Financial health", compliance: "Compliance", dependency: "Dependency" };

/** One supplier on a page, as /api/finance/suppliers/{id}/scorecard returns it: fin.scorecard(result, { onDocuments: () => … }). */
export function scorecard(card, opts = {}) {
  css();
  if (!card || !card.supplier) return nothing("No such supplier");
  const sup = card.supplier, k = card.kpis || {}, risk = card.risk || {};
  const change = num(k.prior_spend) ? ((k.spend - k.prior_spend) / k.prior_spend) * 100 : null;
  const figure = (label, value, tone) => h("div", { class: "fin-figure" }, h("span", { class: "faint" }, label), h("b", { class: tone ? `fin-${tone}-text` : null }, value));
  const weights = risk.weights || {};
  return h("div", { class: "fin-scorecard stack" },
    ui.profile({ name: sup.name, icon: "building", subtitle: [sup.code, sup.city, sup.country].filter(Boolean).join(" · "),
      badges: [status(sup.status), sup.is_preferred ? ui.badge("Preferred", "info") : null,
        sup.payment_terms ? ui.badge(sup.payment_terms, "") : null].filter(Boolean) }),
    h("div", { class: "fin-scorecard-top" },
      gauge(risk.score, { label: "Risk score", caption: risk.rating ? `${risk.rating} risk` : null, digits: 1 }),
      h("div", { class: "fin-parts" }, Object.entries(risk.parts || {}).map(([name, pts]) => {
        const fill = h("span", {});
        const of = num(weights[name]) || 25;
        raf(() => { fill.style.width = `${Math.min(100, ((num(pts) ?? 0) / of) * 100)}%`; });
        return h("div", { class: "fin-part", title: `${number(pts, 1)} of ${of} points` }, h("span", {}, RISK_NAMES[name] || words(name)),
          h("span", { class: "fin-part-track" }, fill), h("b", { class: "mono" }, number(pts, 1)));
      }))),
    h("div", { class: "fin-figures" },
      figure("Spend", money(k.spend, { compact: true })),
      figure("Against last year", change === null ? DASH : percent(change, { signed: true })),
      figure("Share of its category", percent(k.share_of_category_pct)),
      figure("Open payables", money(k.open_payables, { compact: true })),
      figure("Overdue", money(k.overdue, { compact: true }), (num(k.overdue) ?? 0) > 0 ? "bad" : null),
      figure("On time, in full", percent(k.otif_pct)),
      figure("Quality", percent(k.quality_pct)),
      figure("First-time match", percent(k.first_time_match_pct)),
      figure("Paid on time", percent(k.on_time_payment_pct)),
      figure("On a purchase order", percent(k.po_coverage_pct))),
    (card.trend || []).some((p) => p.value) ? ui.section("Spend, last 12 months", { icon: "activity" },
      trend(card.trend, { series: ["value"], height: 200, label: "Spend by month" })) : null,
    (card.contracts || []).length ? ui.section("Contracts", { icon: "file" }, renewalList(card.contracts.map((c) => ({
      ...c, days_left: c.end_date ? Math.round((new Date(`${c.end_date}T00:00:00`) - new Date(`${(card.scope || {}).as_of || new Date().toISOString().slice(0, 10)}T00:00:00`)) / 86400000) : null,
      decide_by: c.end_date, renewal: c.renewal || c.status })))) : null,
    opts.onDocuments ? ui.button("See its invoices", { tone: "secondary", icon: "list", onclick: opts.onDocuments }) : null);
}

/* ---------------------------------------------------------------- rows */

function csvCell(v) {
  const t = v === null || v === undefined ? "" : String(v);
  return /[",\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t;
}

/**
 * Download rows as CSV: fin.exportCsv("spend-by-supplier", rows, [{ key: "label", label: "Supplier" }, { key: "value", label: "Spend" }]).
 * Without columns, every key of the first row. Rows may also be arrays, the first being the heading.
 */
export function exportCsv(name, rows, columns) {
  const list = rows || [];
  let lines;
  if (list.length && Array.isArray(list[0])) lines = list.map((r) => r.map(csvCell).join(","));
  else {
    const cols = columns || Object.keys(list[0] || {}).filter((k) => typeof (list[0] || {})[k] !== "object" || (list[0] || {})[k] === null)
      .map((k) => ({ key: k, label: words(k) }));
    lines = [cols.map((c) => csvCell(c.label)).join(","), ...list.map((r) => cols.map((c) => csvCell(r[c.key])).join(","))];
  }
  const a = h("a", { href: URL.createObjectURL(new Blob([`﻿${lines.join("\n")}`], { type: "text/csv;charset=utf-8" })), download: `${name || "export"}.csv` });
  document.body.append(a);
  a.click();
  a.remove();
  ui.toast(`Exported ${number(Math.max(0, lines.length - 1))} rows`, "ok");
}

const amountCol = (key, label) => ({ key, label, align: "right", render: (r) => h("span", { class: "mono" }, money(r[key])) });
const dateCol = (key, label) => ({ key, label, render: (r) => date(r[key]) });
const statusCol = (key, label) => ({ key, label, render: (r) => status(r[key]) });
const refCol = (key = "reference", label = "Reference") => ({ key, label, render: (r) => h("strong", { class: "mono" }, r[key] ?? DASH) });

const COLUMNS = {
  invoice: [refCol(), { key: "supplier_name", label: "Supplier" }, dateCol("invoice_date", "Dated"), dateCol("due_date", "Due"),
    amountCol("amount", "Amount"), statusCol("status", "Status"), statusCol("match_status", "Match")],
  purchase_order: [refCol(), { key: "supplier_name", label: "Supplier" }, { key: "cost_center_name", label: "Cost centre" },
    dateCol("order_date", "Ordered"), amountCol("amount", "Amount"), statusCol("status", "Status")],
  requisition: [refCol(), { key: "title", label: "Request" }, { key: "requester_name", label: "Requested by" },
    { key: "cost_center_name", label: "Cost centre" }, amountCol("amount", "Amount"), statusCol("status", "Status"), dateCol("created_at", "Raised")],
  goods_receipt: [refCol(), { key: "purchase_order_reference", label: "Order" }, dateCol("received_at", "Received"),
    amountCol("amount", "Value"), statusCol("status", "Status")],
  payment: [refCol(), { key: "supplier_name", label: "Supplier" }, amountCol("amount", "Amount"), { key: "method", label: "Method", render: (r) => words(r.method) },
    statusCol("status", "Status"), dateCol("paid_at", "Paid")],
  payment_run: [refCol(), dateCol("run_date", "Run date"), amountCol("total_amount", "Total"), { key: "payment_count", label: "Payments", align: "right" }, statusCol("status", "Status")],
  contract: [refCol(), { key: "title", label: "Contract" }, { key: "supplier_name", label: "Supplier" }, dateCol("end_date", "Ends"),
    amountCol("annual_value", "A year"), statusCol("status", "Status")],
  supplier: [refCol("code", "Code"), { key: "name", label: "Supplier", render: (r) => h("strong", {}, r.name ?? DASH) }, { key: "country", label: "Country" },
    statusCol("status", "Status"), statusCol("risk_rating", "Risk"), { key: "payment_terms", label: "Terms" }],
  budget_line: [{ key: "cost_center_name", label: "Cost centre" }, { key: "fiscal_year", label: "Year" }, { key: "period", label: "Period" }, amountCol("amount", "Budget")],
  savings_initiative: [{ key: "title", label: "Initiative" }, { key: "supplier_name", label: "Supplier" }, { key: "saving_type", label: "Type", render: (r) => words(r.saving_type) },
    amountCol("identified_saving", "Identified"), amountCol("realised_saving", "Realised"), statusCol("status", "Status")],
  budget_change: [{ key: "cost_center_name", label: "Cost centre" }, amountCol("amount_delta", "Change"), { key: "requested_by", label: "Requested by" }, statusCol("status", "Status")],
};

/** The columns of a standard entity's table, for ui.table: fin.columnsFor("invoice"). */
export function columnsFor(entity, rows) {
  if (COLUMNS[entity]) {
    const first = (rows || [])[0];
    return first ? COLUMNS[entity].filter((c) => c.key in first) : COLUMNS[entity];
  }
  return Object.keys((rows || [])[0] || {}).filter((k) => k !== "id" && !k.endsWith("_id")).slice(0, 7).map((k) => ({ key: k, label: words(k) }));
}

/** A table of a standard entity's rows: fin.documents("invoice", rows, { pageSize: 10, drawer: (row) => ({ … }) }). */
export function documents(entity, rows, opts = {}) {
  css();
  return tagged("fin-table", ui.table({ columns: opts.columns || columnsFor(entity, rows), rows: rows || [], search: opts.search !== false, keyboard: true,
    pageSize: opts.pageSize || 10, exportable: opts.exportable === undefined ? entity : opts.exportable, filters: opts.filters,
    sort: opts.sort, drawer: opts.drawer, onRow: opts.onRow,
    empty: opts.empty || { title: `No ${words(entity).toLowerCase()} records`, hint: "Nothing matches this period and these filters." } }));
}

function tagged(name, el) {
  el.classList.add(name);
  return el;
}

/**
 * The rows behind a number, in a slide-over:
 *   fin.drill({ title: "Overdue invoices", subtitle: "As of today", entity: "invoice", rows, amount })
 *   fin.drill({ title, load: () => data.documents({ entity: "invoice", supplier_id: 7 }) })       asked for when it opens
 */
export function drill(opts = {}) {
  css();
  const show = (result) => {
    const rows = result.rows || [];
    const entity = result.entity || opts.entity;
    return [
      h("div", { class: "fin-drill-head" },
        h("div", {}, h("b", {}, number(result.count ?? rows.length)), h("span", { class: "faint" }, ` ${rows.length === 1 ? "row" : "rows"}`)),
        num(result.amount) !== null ? h("div", {}, h("b", {}, money(result.amount)), h("span", { class: "faint" }, " in all")) : null,
        (result.shown ?? rows.length) < (result.count ?? rows.length) ? h("span", { class: "faint" }, `the first ${number(result.shown)} are listed`) : null),
      documents(entity, rows, { columns: opts.columns, drawer: opts.drawer, onRow: opts.onRow, exportable: opts.exportable ?? entity }),
    ];
  };
  return ui.drawer({ title: opts.title || "Details", subtitle: opts.subtitle, icon: opts.icon || "list",
    content: () => (opts.load ? Promise.resolve(opts.load()).then(show) : show({ rows: opts.rows || [], amount: opts.amount, entity: opts.entity })) });
}

/* ---------------------------------------------------------------- controls */

const COMPARISONS = [{ value: "prior_year", label: "against last year" }, { value: "prior_period", label: "against the period before" },
  { value: "none", label: "no comparison" }];
const COMPARE_WORDS = { prior_year: "vs last year", prior_period: "vs period before", none: "" };

/**
 * The period a dashboard shows and what it is compared with:
 *   fin.periodPicker({ presets: calendar.presets, value: { period: "fy_to_date", compare: "prior_year" }, onchange: (value) => … })
 * value: { period, compare } or, for a range of one's own, { period: "custom", from, to, compare }.
 */
export function periodPicker(opts = {}) {
  css();
  const presets = opts.presets || [];
  let value = { period: "fy_to_date", compare: "prior_year", ...(opts.value || {}) };
  const from = h("input", { type: "date", "aria-label": "From", value: value.from || "" });
  const to = h("input", { type: "date", "aria-label": "To", value: value.to || "" });
  const range = h("span", { class: "fin-range", hidden: value.period !== "custom" }, from, h("span", { class: "faint" }, "to"), to);
  const changed = () => { if (opts.onchange) opts.onchange({ ...value }); };
  const pick = ui.select({ label: "Period", value: value.period, options: [...presets.map((p) => ({ value: p.key, label: p.label })),
    { value: "custom", label: "A range of dates…" }],
  onchange: (e) => {
    value = { ...value, period: e.target.value };
    range.hidden = value.period !== "custom";
    if (value.period === "custom") {
      const like = presets.find((p) => p.key === "fy_to_date") || presets[0] || {};
      from.value = value.from || like.from || ""; to.value = value.to || like.to || "";
      value = { ...value, from: from.value, to: to.value };
    } else { delete value.from; delete value.to; }
    changed();
  } });
  const dates = () => {
    if (!from.value || !to.value || from.value > to.value) return;
    value = { ...value, period: "custom", from: from.value, to: to.value };
    changed();
  };
  from.addEventListener("change", dates);
  to.addEventListener("change", dates);
  const compare = opts.compare === false ? null : ui.select({ label: "Compared with", value: value.compare, options: COMPARISONS,
    onchange: (e) => { value = { ...value, compare: e.target.value }; changed(); } });
  const el = h("div", { class: "fin-period" }, h("span", { class: "fin-control-icon" }, ui.icon("calendar", { size: 16 })), pick, range, compare);
  el.value = () => ({ ...value });
  return el;
}

/**
 * The filters of a dashboard, from /api/finance/dimensions:
 *   fin.filterBar({ dimensions: result.dimensions, show: ["cost_center_id", "family", "supplier_id"], value: {}, onchange: (value) => … })
 */
export function filterBar(opts = {}) {
  css();
  const dims = opts.dimensions || {};
  const show = (opts.show || Object.keys(dims)).filter((k) => dims[k] && (dims[k].options || []).length);
  let value = { ...(opts.value || {}) };
  const el = h("div", { class: "fin-filters" });
  const changed = () => { draw(); if (opts.onchange) opts.onchange({ ...value }); };
  const draw = () => {
    const active = show.filter((k) => value[k] !== undefined && value[k] !== "");
    put(el, h("span", { class: "fin-control-icon" }, ui.icon("filter", { size: 16 })),
      show.map((k) => {
        const d = dims[k];
        const groups = [...new Set(d.options.map((o) => o.group || ""))];
        const option = (o) => h("option", { value: o.value, selected: String(o.value) === String(value[k] ?? "") }, o.label);
        const grouped_ = groups.length > 1 && groups.length < d.options.length && d.options.length > 8;
        return h("select", { "aria-label": d.label, class: value[k] !== undefined && value[k] !== "" ? "fin-on" : null,
          onchange: (e) => { if (e.target.value === "") delete value[k]; else value[k] = e.target.value; changed(); } },
          h("option", { value: "" }, `All ${pluralWord(d.label)}`),
          grouped_ ? groups.map((g) => h("optgroup", { label: g || "Other" }, d.options.filter((o) => (o.group || "") === g).map(option)))
            : d.options.map(option));
      }),
      active.length ? ui.button(`Clear ${active.length === 1 ? "filter" : `${active.length} filters`}`, { tone: "ghost", size: "sm", icon: "x",
        onclick: () => { value = {}; changed(); } }) : null);
  };
  draw();
  el.value = () => ({ ...value });
  return el;
}

function pluralWord(label) {
  const t = String(label || "").toLowerCase();
  if (t.endsWith("y") && !/[aeiou]y$/.test(t)) return `${t.slice(0, -1)}ies`;
  return t.endsWith("s") ? t : `${t}s`;
}

/* ---------------------------------------------------------------- widgets */

const measureWord = (env, key) => ((env.calendar.measures || []).find((m) => m.key === key) || {}).label || words(key);
const DIMENSION_FILTER = { supplier: "supplier_id", category: "spend_category_id", cost_center: "cost_center_id", family: "family",
  department: "department", region: "region", country: "country" };
const DIMENSION_WORDS = { supplier: "supplier", category: "category", cost_center: "cost centre", family: "category family", department: "department",
  region: "region", country: "supplier country", status: "status", match_status: "match result", risk: "supplier risk", buyer: "buyer",
  requester: "requester", month: "month", quarter: "quarter", year: "fiscal year", currency: "currency" };
const ENTITY_OF = { spend: "invoice", invoiced: "invoice", payables: "invoice", paid: "invoice", orders: "purchase_order", commitments: "purchase_order",
  requisitions: "requisition", receipts: "goods_receipt", payments: "payment", budget: "budget_line", savings: "savings_initiative",
  realised_savings: "savings_initiative", contract_value: "contract" };
const MEASURE_STATUS = { payables: { status: "received,matched,exception,approved,scheduled", dated: false }, paid: { status: "paid", date: "paid_at" },
  commitments: { status: "approved,sent,partially_received,received", dated: false }, payments: { status: "completed" } };

/** The /documents question that lists what is behind one slice of a breakdown. */
function behind(measure, by, item) {
  const entity = ENTITY_OF[measure] || "invoice";
  const q = { entity, ...(MEASURE_STATUS[measure] || {}) };
  if (by === "month" || by === "quarter" || by === "year") {
    if (item.start && item.end) { q.from = item.start; q.to = item.end; q.period = ""; } else if (item.key) q.from = item.key;
  } else if (DIMENSION_FILTER[by]) q[DIMENSION_FILTER[by]] = item.key;
  else if (by === "status" || by === "match_status") q[by] = item.key;
  else q.where = `${by}:${item.key}`;
  return q;
}

/**
 * The kinds of widget a dashboard is made of. Each has: title (the default), span (columns of 12), load(env, w)
 * returning its data, draw(result, env, w) returning an element, and rows(result) for the export.
 * env: { data, scope, calendar, compare, drill(title, question), openSupplier(id), ctx }.
 * An application adds its own: fin.WIDGETS.mine = { title: "…", load: async (env) => …, draw: (result) => node }.
 */
export const WIDGETS = {
  kpis: {
    title: "Headline figures", span: 12, bare: true,
    load: (env, w) => env.data.kpis({ ...env.scope, keys: w.keys }),
    draw: (r, env, w) => kpis(r.kpis, { compare: env.compare, targets: { ...(env.spec.targets || {}), ...(w.targets || {}) },
      onClick: (k) => env.drill(k.label, { ...k.drill })}),
    rows: (r) => r.kpis.map((k) => ({ figure: k.label, value: k.value, unit: k.unit, compared_with: k.prior, change_pct: k.change_pct })),
  },
  trend: {
    title: (w, env) => `${measureWord(env, w.measure || "spend")} by ${w.kind || "month"}`, span: 8, icon: "activity",
    load: (env, w) => env.data.trend({ ...env.scope, measure: w.measure || "spend", kind: w.kind || "month", periods: w.periods || 12, span: w.range ? "range" : "" }),
    draw: (r, env, w) => trend(r.points, { series: w.series, cumulative: w.cumulative, labels: { value: r.label, ...(w.labels || {}) },
      onClick: (p) => env.drill(`${r.label}, ${p.label}`, behind(r.measure, r.kind, p)) }),
    rows: (r) => r.points.map((p) => ({ period: p.label, from: p.start, to: p.end, value: p.value, budget: p.budget, last_year: p.prior, documents: p.count })),
  },
  breakdown: {
    title: (w, env) => `${measureWord(env, w.measure || "spend")} by ${DIMENSION_WORDS[w.by || "supplier"] || words(w.by)}`, span: 6, icon: "pie",
    load: (env, w) => env.data.breakdown({ ...env.scope, measure: w.measure || "spend", by: w.by || "supplier",
      top: w.chart === "treemap" || w.chart === "pareto" ? 0 : (w.top ?? 8) }),
    draw: (r, env, w) => {
      if (!r.items.length) return nothing("Nothing in this period");
      const open = (it) => (it.other || it.key === null || it.key === undefined ? null
        : r.by === "supplier" ? env.openSupplier(it.key) : env.drill(`${r.label}: ${it.label}`, behind(r.measure, r.by, it)));
      if (w.chart === "treemap") return treemap(r.items, { measure: r.label, top: w.top, onClick: open });
      if (w.chart === "pareto") return pareto(r.items, { measure: r.label, top: w.top, onClick: open });
      if (w.chart === "donut") return donut(r.items.map((i) => ({ ...i, tone: STATUS_TONE[String(i.key).toLowerCase()] })),
        { sub: r.label.toLowerCase(), onClick: open });
      return ui.bars(r.items.map((i) => ({ ...i, tone: STATUS_TONE[String(i.key).toLowerCase()] })), { format: (v) => money(v, { compact: true }), onClick: open, tips: true });
    },
    rows: (r) => r.items.map((i) => ({ [r.by]: i.label, value: i.value, share_pct: i.share_pct, documents: i.count, compared_with: i.prior, change_pct: i.change_pct })),
  },
  budget: {
    title: (w) => `Budget against actual by ${DIMENSION_WORDS[w.by || "cost_center"] || words(w.by)}`, span: 7, icon: "dollar",
    load: (env, w) => env.data.budget({ ...env.scope, by: w.by || "cost_center" }),
    draw: (r, env, w) => {
      const body = h("div", {});
      const open = (row) => env.drill(`Spend: ${row.label}`, behind("spend", r.by, row));
      const show = (view) => put(body, budgetBars(r.rows, { view, limit: w.limit, elapsed: r.totals.elapsed_pct, onClick: open }));
      show(w.view || "period");
      const t = r.totals;
      return h("div", { class: "stack" },
        h("div", { class: "between" },
          h("div", { class: "fin-figures fin-figures-tight" },
            h("div", { class: "fin-figure" }, h("span", { class: "faint" }, "Spent"), h("b", {}, money(t.actual, { compact: true }))),
            h("div", { class: "fin-figure" }, h("span", { class: "faint" }, "Budget"), h("b", {}, money(t.budget, { compact: true }))),
            h("div", { class: "fin-figure" }, h("span", { class: "faint" }, `${t.fiscal_year} forecast`),
              h("b", { class: (num(t.forecast_variance) ?? 0) > 0 ? "fin-bad-text" : "fin-good-text" }, percent(t.forecast_pct, { digits: 0 })), h("span", { class: "faint" }, " of budget")),
            h("div", { class: "fin-figure" }, h("span", { class: "faint" }, "Over budget"), h("b", { class: t.over ? "fin-bad-text" : null }, number(t.over)))),
          ui.segmented({ options: [{ value: "period", label: "This period" }, { value: "year", label: "Full year" }], value: w.view || "period", onchange: show })),
        body);
    },
    rows: (r) => r.rows.map(({ key, ...rest }) => rest),
  },
  waterfall: {
    title: "From budget to actual", span: 5, icon: "chart",
    load: (env, w) => env.data.waterfall({ ...env.scope, by: w.by || "cost_center", top: w.top || 6 }),
    draw: (r, env) => (r.totals.budget || r.totals.actual ? waterfall(r, { onClick: (st) => env.drill(`Spend: ${st.label}`, behind("spend", r.by, st)) })
      : nothing("No budget for this period")),
    rows: (r) => [{ step: r.start.label, value: r.start.value }, ...r.steps.map((st) => ({ step: st.label, value: st.value })), { step: r.end.label, value: r.end.value }],
  },
  aging: {
    title: "Open payables by age", span: 6, icon: "clock",
    load: (env) => env.data.aging({ ...env.scope }),
    draw: (r, env, w) => h("div", { class: "stack" },
      aging(r.buckets, { onClick: (b) => env.drill(`Owed: ${b.label === "Not due" ? "not due" : `${b.label} days overdue`}`,
        { entity: "invoice", bucket: b.label, dated: false, sort: "-amount" }) }),
      w.suppliers === false || !r.suppliers.some((x) => x.overdue > 0) ? null : h("div", { class: "fin-sub" }, h("h3", {}, "Owed the most overdue"),
        ui.bars(r.suppliers.filter((x) => x.overdue > 0).slice(0, 5).map((x) => ({ label: x.label, value: x.overdue, key: x.key, tone: "down" })),
          { format: (v) => money(v, { compact: true }), onClick: (it) => env.drill(`Overdue: ${it.label}`, { entity: "invoice", supplier_id: it.key, overdue: true, dated: false }) }))),
    rows: (r) => r.buckets,
  },
  funnel: {
    title: "Purchase to pay", span: 6, icon: "filter",
    load: (env) => env.data.funnel({ ...env.scope }),
    draw: (r) => funnel(r.stages),
    rows: (r) => r.stages,
  },
  pivot: {
    title: (w, env) => `${measureWord(env, w.measure || "spend")}: ${DIMENSION_WORDS[w.rows || "cost_center"] || words(w.rows)} by ${DIMENSION_WORDS[w.columns || "month"] || words(w.columns)}`,
    span: 12, icon: "grid",
    load: (env, w) => env.data.pivot({ ...env.scope, measure: w.measure || "spend", rows: w.rows || "cost_center", columns: w.columns || "month", top: w.top || 12 }),
    draw: (r, env, w) => pivot(r, { heat: w.heat, onClick: (row, col) => env.drill(`${r.label}: ${row.label}, ${col.label}`,
      { ...behind(r.measure, r.row_by, row), ...(["month", "quarter", "year"].includes(r.column_by) ? periodOf(env, r.column_by, col.key) : behindColumn(r.column_by, col)) }) }),
    rows: (r) => pivotRows(r),
  },
  cycle: {
    title: "How long each step takes", span: 6, icon: "history",
    load: (env) => env.data.cycleTimes({ ...env.scope }),
    draw: (r, env, w) => cycleTimes(r.steps, { targets: w.targets }),
    rows: (r) => r.steps,
  },
  exceptions: {
    title: "Invoices held", span: 6, icon: "alert",
    load: (env) => env.data.exceptions({ ...env.scope }),
    draw: (r, env, w) => (r.count ? h("div", { class: "stack" },
      h("div", { class: "fin-figures fin-figures-tight" },
        h("div", { class: "fin-figure" }, h("span", { class: "faint" }, "Held"), h("b", {}, number(r.count))),
        h("div", { class: "fin-figure" }, h("span", { class: "faint" }, "Worth"), h("b", {}, money(r.amount, { compact: true }))),
        h("div", { class: "fin-figure" }, h("span", { class: "faint" }, "Oldest"), h("b", { class: r.oldest_days > 30 ? "fin-bad-text" : null }, days(r.oldest_days)))),
      ui.bars(r.reasons.map((x) => ({ ...x, tone: STATUS_TONE[x.key] || "warn" })), { format: (v) => money(v, { compact: true }),
        onClick: (it) => env.drill(`Held: ${it.label}`, { entity: "invoice", status: "exception", match_status: it.key, dated: false }) }),
      w.list === false ? null : documents("invoice", r.rows, { pageSize: w.pageSize || 5, search: false, exportable: false, drawer: env.record("invoice"),
        columns: [refCol(), { key: "supplier_name", label: "Supplier" }, amountCol("amount", "Amount"), statusCol("match_status", "Why"),
          { key: "days_held", label: "Held", align: "right", render: (x) => days(x.days_held) }] }))
      : nothing("No invoices are held", "Every invoice matched, or its exception was resolved.")),
    rows: (r) => r.rows,
  },
  accruals: {
    title: "Received, not invoiced", span: 6, icon: "layers",
    load: (env) => env.data.accruals({ ...env.scope }),
    draw: (r, env, w) => (r.count ? h("div", { class: "stack" },
      h("div", { class: "fin-figures fin-figures-tight" },
        h("div", { class: "fin-figure" }, h("span", { class: "faint" }, "To accrue"), h("b", {}, money(r.amount, { compact: true }))),
        h("div", { class: "fin-figure" }, h("span", { class: "faint" }, "Orders"), h("b", {}, number(r.count)))),
      ui.table({ rows: r.rows, pageSize: w.pageSize || 6, exportable: "accruals", sort: { key: "accrual", dir: "desc" },
        columns: [refCol(), { key: "supplier_name", label: "Supplier" }, { key: "cost_center_name", label: "Cost centre" },
          amountCol("received", "Received"), amountCol("invoiced", "Invoiced"), amountCol("accrual", "Accrual")] }))
      : nothing("Nothing to accrue", "Everything received has been invoiced.")),
    rows: (r) => r.rows,
  },
  renewals: {
    title: "Contracts to decide on", span: 6, icon: "file",
    load: (env, w) => env.data.renewals({ ...env.scope, within: w.within || 180 }),
    draw: (r, env, w) => renewalList(r.rows, { limit: w.limit || 7, onClick: (c) => ui.drawer(env.record("contract")(c)) }),
    rows: (r) => r.rows,
  },
  controls: {
    title: "Controls", span: 6, icon: "shield",
    load: (env, w) => env.data.controls({ ...env.scope, days: w.days || 90 }),
    draw: (r, env) => controlList(r.controls, { onClick: (c) => drill({ title: c.label, subtitle: `${c.rule} · ${c.about}`, icon: "shield",
      rows: c.rows, amount: c.amount, entity: CONTROL_ENTITY[c.key], columns: CONTROL_COLUMNS[c.key], exportable: c.key }) }),
    rows: (r) => r.controls.map(({ rows, ...rest }) => rest),
  },
  documents: {
    title: (w) => `${words(w.entity || "invoice")}s`, span: 12, icon: "list",
    load: (env, w) => env.data.documents({ ...env.scope, entity: w.entity || "invoice", status: w.status, match_status: w.match_status, overdue: w.overdue,
      dated: w.dated, date: w.date, sort: w.sort, where: w.where, limit: w.limit || 500 }),
    draw: (r, env, w) => documents(r.entity, r.rows, { columns: w.columns, pageSize: w.pageSize || 10, filters: w.filters || (r.rows.some((x) => x.status) ? [{ key: "status" }] : undefined),
      drawer: w.drawer || env.record(r.entity), onRow: r.entity === "supplier" ? (row) => env.openSupplier(row.id) : undefined }),
    rows: (r) => r.rows,
  },
  suppliers: {
    title: "Suppliers", span: 12, icon: "building",
    load: async (env, w) => {
      const [spend, list] = await Promise.all([env.data.breakdown({ ...env.scope, measure: "spend", by: "supplier" }),
        env.data.documents({ ...env.scope, entity: "supplier", dated: false, limit: 2000, sort: "name" })]);
      const bySupplier = Object.fromEntries(spend.items.map((i) => [i.key, i]));
      const rows = list.rows.map((x) => ({ ...x, spend: (bySupplier[x.id] || {}).value || 0, share_pct: (bySupplier[x.id] || {}).share_pct ?? 0,
        invoices: (bySupplier[x.id] || {}).count || 0 }));
      return { rows: w.all ? rows : rows.filter((x) => x.spend > 0 || !["retired", "prospective"].includes(x.status)) };
    },
    draw: (r, env, w) => ui.table({ rows: r.rows, search: true, keyboard: true, pageSize: w.pageSize || 10, exportable: "suppliers",
      sort: { key: "spend", dir: "desc" }, filters: [{ key: "risk_rating", all: "Any risk" }], onRow: (row) => env.openSupplier(row.id),
      columns: [{ key: "name", label: "Supplier", render: (x) => h("span", { class: "person-text" }, h("strong", {}, x.name), h("span", { class: "faint" }, [x.code, x.country].filter(Boolean).join(" · "))) },
        statusCol("status", "Status"), statusCol("risk_rating", "Risk"),
        { key: "otif_pct", label: "On time, in full", align: "right", render: (x) => percent(x.otif_pct, { digits: 0 }) },
        { key: "invoices", label: "Invoices", align: "right", render: (x) => number(x.invoices) },
        amountCol("spend", "Spend"),
        { key: "share_pct", label: "Share", align: "right", render: (x) => percent(x.share_pct) }],
      empty: { title: "No suppliers", hint: "Suppliers appear here once they are set up." } }),
    rows: (r) => r.rows,
  },
};

const CONTROL_ENTITY = { duplicates: "invoice", no_order: "invoice", self_approval: "requisition", unapproved_supplier: "purchase_order" };
const CONTROL_COLUMNS = {
  duplicates: [refCol(), { key: "supplier_name", label: "Supplier" }, amountCol("amount", "Amount"), dateCol("invoice_date", "Dated"),
    { key: "other_reference", label: "May duplicate", render: (r) => h("span", { class: "mono" }, r.other_reference || DASH) },
    { key: "confidence", label: "How sure", render: (r) => status(r.confidence, r.confidence === "exact" ? "down" : "warn") }],
  splits: [{ key: "requester_name", label: "Requested by" }, { key: "supplier_name", label: "Supplier" }, { key: "count", label: "Requests", align: "right" },
    amountCol("total", "Together"), { key: "references", label: "References", render: (r) => h("span", { class: "mono" }, (r.references || []).join(", ")) }],
  unapproved_supplier: [refCol(), { key: "supplier_name", label: "Supplier" }, statusCol("supplier_status", "Supplier is"), amountCol("amount", "Amount"), statusCol("status", "Order")],
  over_budget: [{ key: "label", label: "Cost centre" }, amountCol("budget", "Budget"), amountCol("actual", "Actual"), amountCol("variance", "Over by"),
    { key: "variance_pct", label: "%", align: "right", render: (r) => percent(r.variance_pct, { signed: true }) }],
};

function behindColumn(by, col) {
  if (DIMENSION_FILTER[by]) return { [DIMENSION_FILTER[by]]: col.key };
  if (by === "status" || by === "match_status") return { [by]: col.key };
  return {};
}

function periodOf(env, kind, first) {
  const [from, to] = calendar(env.calendar.fiscal_year_start_month).bounds(kind, first);
  return { from, to, period: "" };
}

/* ---------------------------------------------------------------- the dashboard */

function memory(key) {
  return {
    read() { try { return JSON.parse(localStorage.getItem(key) || "{}") || {}; } catch { return {}; } },
    write(value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* private mode: nothing is kept */ } },
  };
}

const slug = (text) => String(text || "dashboard").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

/**
 * A dashboard from a description. Draws into `root` and returns { reload, scope() }.
 *
 *   await fin.dashboard(root, ctx, {
 *     id: "operations-spend",                       // names what this person's arrangement is kept under
 *     period: { value: "fy_to_date", compare: "prior_year" },
 *     filters: ["cost_center_id", "family", "supplier_id"],     // false for none
 *     fixed: { department: "Operations" },          // always applied, not offered: one team's own dashboard
 *     kpis: ["spend", "budget_used", "po_coverage", "overdue"],  // false for none; left out, every figure there is
 *     targets: { po_coverage: 95, first_time_match: 85 },
 *     widgets: [
 *       { type: "trend", measure: "spend", span: 8 },
 *       { type: "breakdown", measure: "spend", by: "family", chart: "donut", span: 4 },
 *       { type: "budget", by: "cost_center" },
 *       { type: "custom", title: "Notes", span: 4, load: async (env) => …, draw: (result, env) => node },
 *     ],
 *   });
 *
 * A widget: { type, title?, span? (of 12), id?, hint?, … its own parameters }. `ctx` is what render() received.
 * A widget of any type may bring its own `draw(result, env)` (the type's figures, shown its own way) or its own
 * `load(env)` as well; its title is the widget's, so what it draws needs no heading of its own.
 * People choose the period and the filters, hide and reorder widgets; their choice is remembered on their device.
 */
export async function dashboard(root, ctx, spec = {}) {
  css();
  const { api } = ctx;
  const source = data(api);
  const me = ctx.enterprise && ctx.enterprise.me ? (typeof ctx.enterprise.me === "function" ? ctx.enterprise.me() : ctx.enterprise.me) : null;
  const store = memory(`fin:${slug(spec.id || spec.title || "dashboard")}:${(me && (me.username || me.id)) || "anyone"}`);
  const kept = store.read();
  root.replaceChildren(ui.skeleton());
  let cal, dims;
  try {
    [cal, dims] = await Promise.all([source.calendar(), spec.filters === false ? { dimensions: {} } : source.dimensions()]);
  } catch (err) {
    root.replaceChildren(ui.notice(`The figures could not be loaded: ${(err && err.message) || err}`, "down"));
    return { reload() {}, scope: () => ({}) };
  }
  configure({ currency: cal.currency, fiscalStartMonth: cal.fiscal_year_start_month });

  const asked = spec.period || {};
  const known = new Set((cal.presets || []).map((p) => p.key).concat("custom"));
  let period = { period: asked.value || cal.default_period || "fy_to_date", compare: asked.compare || "prior_year", ...(kept.period || {}) };
  if (!known.has(period.period) || (period.period === "custom" && !(period.from && period.to))) period = { period: asked.value || "fy_to_date", compare: period.compare };
  const offered = (spec.filters === false ? [] : spec.filters || ["cost_center_id", "family", "supplier_id"]).filter((k) => !(spec.fixed || {})[k]);
  let filters = Object.fromEntries(Object.entries(kept.filters || {}).filter(([k, v]) => offered.includes(k)
    && ((dims.dimensions[k] || {}).options || []).some((o) => String(o.value) === String(v))));

  const all = [];
  if (spec.kpis !== false) all.push({ type: "kpis", id: "kpis", keys: Array.isArray(spec.kpis) ? spec.kpis.join(",") : undefined });
  for (const [i, w] of (spec.widgets || []).entries()) all.push({ ...w, id: w.id || `${w.type}-${w.measure || w.entity || ""}-${w.by || w.rows || ""}-${i}` });
  let hidden = new Set((kept.hidden || []).filter((id) => all.some((w) => w.id === id)));
  let order = (kept.order || []).filter((id) => all.some((w) => w.id === id));

  const scope = () => {
    const out = { ...(spec.fixed || {}), ...filters, compare: period.compare };
    if (period.period === "custom") { out.from = period.from; out.to = period.to; } else out.period = period.period;
    return out;
  };
  const save = () => store.write({ period, filters, hidden: [...hidden], order });
  const label = () => (period.period === "custom" ? `${date(period.from)} to ${date(period.to)}`
    : ((cal.presets || []).find((p) => p.key === period.period) || {}).label || "");

  const record = (entity) => (typeof spec.record === "function" ? (row) => spec.record(entity, row, env) : (row) => recordDrawer(entity, row, env));
  const env = {
    data: source, ctx, spec, calendar: cal, dimensions: dims.dimensions, record,
    get scope() { return scope(); },
    get compare() { return COMPARE_WORDS[period.compare] || ""; },
    drill(title, question) {
      if (!question || !question.entity) return null;
      const q = { ...scope(), ...question };
      if (q.dated === "false") q.dated = false;
      if (q.from && q.to) delete q.period;
      return drill({ title, subtitle: q.dated === false ? "As of today" : q.from ? `${date(q.from)} to ${date(q.to)}` : label(),
        load: () => source.documents(q), drawer: record(q.entity), onRow: q.entity === "supplier" ? (row) => env.openSupplier(row.id) : undefined });
    },
    openSupplier(id) {
      if (id === null || id === undefined) return null;
      return ui.drawer({ title: "Supplier", subtitle: label(), icon: "building",
        content: () => source.scorecard(id, { ...scope(), supplier_id: undefined }).then((card) => scorecard(card, {
          onDocuments: () => env.drill(`Invoices: ${card.supplier.name}`, { entity: "invoice", supplier_id: id }) })) });
    },
  };

  const grid = h("div", { class: "fin-grid" });
  let generation = 0;

  function arranged() {
    const shown = all.filter((w) => !hidden.has(w.id));
    const rank = (w) => { const i = order.indexOf(w.id); return i < 0 ? 1000 + all.indexOf(w) : i; };
    return order.length ? [...shown].sort((a, b) => rank(a) - rank(b)) : shown;
  }

  function widget(w, mine) {
    // A widget that brings its own load or draw is drawn its own way, whatever type it names:
    // { type: "aging", draw: (result) => … } is the standard figures, shown differently.
    const own = Object.fromEntries(["load", "draw", "rows"].filter((k) => typeof w[k] === "function").map((k) => [k, w[k]]));
    const kind = w.type === "custom" ? w : (WIDGETS[w.type] || own.load) ? { ...(WIDGETS[w.type] || {}), ...own } : null;
    if (!kind || typeof kind.load !== "function" || typeof kind.draw !== "function") {
      return h("section", { class: "panel fin-widget", style: { gridColumn: "span 12" } }, ui.notice(`There is no widget of type "${w.type}". There are: ${Object.keys(WIDGETS).join(", ")}, custom.`, "warn"));
    }
    const title = w.title || (typeof kind.title === "function" ? kind.title(w, env) : kind.title) || words(w.type);
    const body = h("div", { class: "fin-widget-body" }, ui.skeleton("rows"));
    let result = null;
    const exportBtn = ui.iconButton("download", { label: "Export as CSV", onclick: () => {
      if (!result) return;
      const rows = typeof (w.rows || kind.rows) === "function" ? (w.rows || kind.rows)(result) : [];
      if (rows && rows.length) exportCsv(slug(title), rows); else ui.toast("There is nothing to export", "warn");
    } });
    exportBtn.hidden = true;
    const span = Math.max(3, Math.min(12, Number(w.span || kind.span || 6)));
    const bare = kind.bare && !w.title;
    const el = h("section", { class: `${bare ? "fin-bare" : "panel"} fin-widget fin-span-${span}`, "data-widget": w.id, style: { gridColumn: `span ${span}` } },
      bare ? null : h("div", { class: "section-head" }, h("h2", {}, ui.icon(w.icon || kind.icon || ui.guessIcon(title)), title),
        h("span", { class: "row fin-widget-tools" }, w.hint ? h("span", { class: "faint" }, w.hint) : null, exportBtn)),
      body);
    Promise.resolve().then(() => kind.load(env, w)).then((r) => {
      if (mine !== generation) return;
      result = r;
      const drawn = kind.draw(r, env, w);
      put(body, drawn);
      exportBtn.hidden = !(w.rows || kind.rows);
    }).catch((err) => {
      if (mine !== generation) return;
      const message = (err && err.message) || String(err);
      put(body, /\b(403|may not|permission)\b/i.test(message)
        ? nothing("Not for your role", "Your role does not include these records.")
        : ui.notice(`This could not be loaded: ${message}`, "down"));
    });
    return el;
  }

  function draw() {
    generation += 1;
    const mine = generation;
    const list = arranged();
    put(grid, list.length ? list.map((w) => widget(w, mine))
      : h("section", { class: "panel", style: { gridColumn: "span 12" } }, nothing("Everything is hidden", "Choose Customise to bring widgets back.")));
  }

  function customise() {
    let draftHidden = new Set(hidden);
    let draftOrder = arranged().map((w) => w.id).concat(all.filter((w) => hidden.has(w.id)).map((w) => w.id));
    const listEl = h("div", { class: "fin-custom" });
    const name = (w) => w.title || (typeof (WIDGETS[w.type] || {}).title === "function" ? WIDGETS[w.type].title(w, env) : (WIDGETS[w.type] || {}).title) || words(w.type);
    const render = () => put(listEl, draftOrder.map((id, i) => {
      const w = all.find((x) => x.id === id);
      const move = (by) => { const j = i + by; if (j < 0 || j >= draftOrder.length) return; [draftOrder[i], draftOrder[j]] = [draftOrder[j], draftOrder[i]]; render(); };
      return h("div", { class: `fin-custom-row${draftHidden.has(id) ? " fin-custom-off" : ""}` },
        h("label", {}, h("input", { type: "checkbox", checked: !draftHidden.has(id),
          onchange: (e) => { if (e.target.checked) draftHidden.delete(id); else draftHidden.add(id); render(); } }), h("span", {}, name(w))),
        h("span", { class: "row" }, flipped(ui.iconButton("chevron-down", { label: `Move ${name(w)} up`, onclick: () => move(-1) })),
          ui.iconButton("chevron-down", { label: `Move ${name(w)} down`, onclick: () => move(1) })));
    }));
    render();
    ui.modal({ title: "Customise this dashboard", subtitle: "Choose what is shown and in what order. It is remembered on this device.", icon: "settings",
      content: listEl,
      actions: (close) => [
        ui.button("Reset", { tone: "ghost", onclick: () => { hidden = new Set(); order = []; save(); close(); draw(); ui.toast("Back to the standard arrangement", "ok"); } }),
        ui.button("Cancel", { tone: "secondary", onclick: close }),
        ui.button("Save", { icon: "check", onclick: () => { hidden = draftHidden; order = draftOrder; save(); close(); draw(); ui.toast("Your arrangement is saved", "ok"); } }),
      ] });
  }

  const fixedNote = Object.keys(spec.fixed || {}).length ? h("span", { class: "fin-fixed" }, ui.icon("pin", { size: 13 }),
    Object.entries(spec.fixed).map(([k, v]) => {
      const option = ((dims.dimensions[k] || {}).options || []).find((o) => String(o.value) === String(v));
      return option ? option.label : String(v);
    }).join(" · ")) : null;
  const bar = h("div", { class: "fin-bar" },
    periodPicker({ presets: (cal.presets || []).filter((p) => !asked.presets || asked.presets.includes(p.key)), value: period, compare: asked.compare !== false,
      onchange: (v) => { period = v; save(); draw(); } }),
    offered.length ? filterBar({ dimensions: dims.dimensions, show: offered, value: filters, onchange: (v) => { filters = v; save(); draw(); } }) : null,
    h("span", { class: "fin-bar-right" }, fixedNote,
      h("span", { class: "faint fin-asof" }, `As of ${date(cal.today)}`),
      ui.iconButton("refresh", { label: "Refresh", onclick: () => draw() }),
      spec.customise === false ? null : ui.button("Customise", { tone: "secondary", size: "sm", icon: "settings", onclick: customise })));

  env.reload = () => draw();
  put(root, bar, grid);
  draw();
  return { reload: draw, scope, env };
}

const RECORD_FIELDS = {
  invoice: [["Supplier", "supplier_name"], ["Supplier's number", "supplier_invoice_number"], ["Order", "purchase_order_reference"], ["Cost centre", "cost_center_name"],
    ["Category", "spend_category_name"], ["Net", "net_amount", "money"], ["Tax", "tax_amount", "money"], ["Gross", "amount", "money"], ["Dated", "invoice_date", "date"],
    ["Due", "due_date", "date"], ["Terms", "payment_terms"], ["Overdue", "days_overdue", "days"], ["Held because", "exception_reason"], ["Approved by", "approver_name"],
    ["Paid", "paid_at", "date"], ["Discount on offer", "discount_available", "some"], ["Discount taken", "discount_taken", "some"]],
  purchase_order: [["Supplier", "supplier_name"], ["Cost centre", "cost_center_name"], ["Category", "spend_category_name"], ["Buyer", "buyer_name"], ["Contract", "contract_reference"],
    ["Ordered", "order_date", "date"], ["Expected", "expected_delivery", "date"], ["Delivered", "delivered_at", "date"], ["Amount", "amount", "money"],
    ["Received", "received_amount", "money"], ["Invoiced", "invoiced_amount", "money"], ["Terms", "payment_terms"]],
  requisition: [["Requested by", "requester_name"], ["Cost centre", "cost_center_name"], ["Category", "spend_category_name"], ["Suggested supplier", "supplier_name"],
    ["Amount", "amount", "money"], ["Needed by", "needed_by", "date"], ["Raised", "created_at", "date"], ["Approved by", "approver_name"], ["Approved", "approved_at", "date"],
    ["Order", "purchase_order_reference"], ["Why", "justification"]],
  contract: [["Supplier", "supplier_name"], ["Category", "spend_category_name"], ["Owner", "owner_name"], ["Starts", "start_date", "date"], ["Ends", "end_date", "date"],
    ["Value", "value", "money"], ["A year", "annual_value", "money"], ["Notice", "notice_days", "days"], ["Renews by itself", "auto_renew", "yes"], ["Decide by", "decide_by", "date"], ["Note", "note"]],
  payment: [["Supplier", "supplier_name"], ["Amount", "amount", "money"], ["Method", "method", "words"], ["Scheduled for", "scheduled_for", "date"], ["Paid", "paid_at", "date"],
    ["Discount taken", "discount_taken", "some"]],
};

/** What a row opens when the application says nothing else: the record, its lifecycle and, for an invoice, its match. */
function recordDrawer(entity, row, env, opts = {}) {
  const fields = RECORD_FIELDS[entity] || Object.keys(row).filter((k) => k !== "id" && !k.endsWith("_id") && typeof row[k] !== "object").map((k) => [words(k), k]);
  const show = (value, kind) => (value === null || value === undefined || value === "" ? null
    : kind === "some" ? (num(value) ? money(value) : null) : kind === "money" ? money(value) : kind === "date" ? date(value) : kind === "days" ? days(value) : kind === "words" ? words(value)
      : kind === "yes" ? (value ? "Yes" : "No") : String(value));
  const pairs = fields.map(([label_, key, kind]) => ({ label: label_, value: show(row[key], kind) })).filter((p) => p.value !== null);
  const states = (env.calendar.states || {})[entity];
  // Where the application runs the record's lifecycle, its own panel shows the state, what this person may do and the history.
  const governed = (env.calendar.workflows || []).includes(entity) && row.id;
  const workflow = governed && env.ctx.enterprise && env.ctx.enterprise.workflow;
  let order = null;
  if (entity === "invoice" && row.purchase_order_id && env.data) {
    order = h("div", {}, ui.skeleton("rows"));
    env.data.documents({ entity: "purchase_order", dated: false, where: `reference:${row.purchase_order_reference || ""}`, limit: 1 })
      .then((r) => {
        const po = r.rows[0];
        put(order, po ? matchStatus({ status: row.match_status, ordered: po.amount, received: po.received_amount, invoiced: row.net_amount,
          discrepancies: row.exception_reason ? [row.exception_reason] : [] }) : null);
      }).catch(() => put(order));
  }
  return {
    title: row.reference || row.title || row.name || `${words(entity)} ${row.id}`,
    subtitle: [standardTitle(entity), row.supplier_name].filter(Boolean).join(" · "), icon: ui.guessIcon(entity),
    content: [
      states && row.status && !workflow ? lifecycle(states, row.status) : null,
      entity === "requisition" || entity === "purchase_order" ? approvalChain(row.amount, env.calendar.approval_matrix, { roles: roleNames(env) }) : null,
      order,
      ui.kv(pairs),
      workflow && typeof workflow.panel === "function" ? guarded(() => workflow.panel(entity, row.id, { onChange: () => env.reload(), ...(opts.panel || {}) })) : null,
    ].filter(Boolean),
  };
}

function flipped(el) {
  el.classList.add("fin-flip");
  return el;
}

function guarded(make) {
  try { return make(); } catch { return null; }
}

function roleNames(env) {
  return env.calendar.roles || {};
}

const TITLES = { invoice: "Supplier invoice", purchase_order: "Purchase order", requisition: "Purchase requisition", contract: "Contract", payment: "Payment",
  supplier: "Supplier", goods_receipt: "Goods receipt", payment_run: "Payment run", budget_line: "Budget line", savings_initiative: "Savings initiative",
  budget_change: "Budget change" };
const standardTitle = (entity) => TITLES[entity] || words(entity);

/* ---------------------------------------------------------------- blueprints */

function blueprint(base) {
  return (over = {}) => {
    const out = { ...base, ...over };
    if (over.widgets === undefined && (over.add || over.remove)) {
      out.widgets = base.widgets.filter((w) => !(over.remove || []).includes(w.type) && !(over.remove || []).includes(w.id)).concat(over.add || []);
    }
    delete out.add;
    delete out.remove;
    return out;
  };
}

/**
 * Dashboards ready to use, each a description to change rather than write. Every one takes what dashboard() takes,
 * and replaces that part: fin.blueprints.spend({ fixed: { department: "Operations" }, kpis: ["spend", "orders"] }).
 * { add: [widgets] } and { remove: ["pivot"] } change the widgets without restating them.
 */
export const blueprints = {
  /** A finance director's page: the figures that matter, the budget, what is owed, who the money goes to. */
  executive: blueprint({ id: "executive",
    kpis: ["spend", "budget_used", "commitments", "payables", "overdue", "po_coverage", "on_time_payment", "savings_realised"],
    widgets: [{ type: "trend", measure: "spend", span: 8 }, { type: "breakdown", measure: "spend", by: "family", chart: "donut", span: 4 },
      { type: "budget", by: "cost_center", span: 7 }, { type: "aging", span: 5, suppliers: false },
      { type: "breakdown", measure: "spend", by: "supplier", chart: "pareto", span: 7, title: "Where the money goes" }, { type: "controls", span: 5 }] }),
  /** Spend analysis: by time, category, supplier and cost centre, down to the invoice. */
  spend: blueprint({ id: "spend",
    kpis: ["spend", "orders", "commitments", "suppliers", "po_coverage", "contracted_spend", "maverick_spend", "price_variance"],
    widgets: [{ type: "trend", measure: "spend", span: 8 }, { type: "breakdown", measure: "spend", by: "family", chart: "donut", span: 4 },
      { type: "breakdown", measure: "spend", by: "supplier", chart: "pareto", span: 6 }, { type: "breakdown", measure: "spend", by: "category", chart: "treemap", span: 6 },
      { type: "pivot", measure: "spend", rows: "cost_center", columns: "month" },
      { type: "documents", entity: "invoice", title: "Invoices", sort: "-amount" }] }),
  /** Budget control: who is over, what is left of the year, and where the variance comes from. */
  budget: blueprint({ id: "budget", filters: ["cost_center_id", "department", "family"],
    kpis: ["budget_used", "spend", "commitments", "orders"],
    widgets: [{ type: "budget", by: "cost_center", span: 7, limit: 10 }, { type: "waterfall", by: "cost_center", span: 5 },
      { type: "trend", measure: "spend", cumulative: true, range: true, series: ["value", "budget"], span: 6, title: "Spend against budget, running total" },
      { type: "budget", by: "family", span: 6, id: "budget-family" },
      { type: "pivot", measure: "spend", rows: "family", columns: "month" }] }),
  /** Accounts payable: what is owed and overdue, what is held, how quickly invoices are approved and paid. */
  payables: blueprint({ id: "payables", filters: ["supplier_id", "cost_center_id", "family"],
    kpis: ["payables", "overdue", "exceptions", "first_time_match", "on_time_payment", "dpo", "invoice_cycle", "discount_capture", "discounts_missed"],
    widgets: [{ type: "aging", span: 6 }, { type: "exceptions", span: 6 },
      { type: "trend", measure: "paid", series: ["value", "prior"], span: 6, title: "Paid by month" }, { type: "cycle", span: 6 },
      { type: "documents", entity: "invoice", title: "Open invoices", status: "received,matched,exception,approved,scheduled", dated: false, date: "due_date", sort: "due_date" }] }),
  /** Purchase to pay: how requests become orders, receipts, invoices and payments, and where they wait. */
  procureToPay: blueprint({ id: "procure-to-pay",
    kpis: ["orders", "po_coverage", "first_time_match", "otif", "requisition_cycle", "invoice_cycle", "price_variance", "maverick_spend"],
    widgets: [{ type: "funnel", span: 6 }, { type: "cycle", span: 6 },
      { type: "breakdown", measure: "requisitions", by: "status", chart: "donut", span: 4, title: "Requests by status" },
      { type: "breakdown", measure: "orders", by: "buyer", span: 4, title: "Orders by buyer" },
      { type: "breakdown", measure: "invoiced", by: "match_status", chart: "donut", span: 4, title: "Invoices by match" },
      { type: "accruals", span: 6 }, { type: "controls", span: 6 },
      { type: "documents", entity: "purchase_order", title: "Purchase orders" }] }),
  /** Suppliers: concentration, risk, delivery and the contracts coming up. */
  suppliers: blueprint({ id: "suppliers", filters: ["family", "spend_category_id", "country"],
    kpis: ["suppliers", "contracted_spend", "maverick_spend", "otif", "high_risk", "expiring"],
    widgets: [{ type: "breakdown", measure: "spend", by: "supplier", chart: "pareto", span: 8, title: "Supplier concentration" },
      { type: "breakdown", measure: "spend", by: "risk", chart: "donut", span: 4, title: "Spend by supplier risk" },
      { type: "renewals", span: 6 }, { type: "breakdown", measure: "spend", by: "country", span: 6, title: "Spend by supplier country" },
      { type: "suppliers" }] }),
  /** Controls: what the rules found, what is held, what is to accrue. */
  controls: blueprint({ id: "controls", kpis: ["exceptions", "overdue", "po_coverage", "first_time_match", "high_risk", "expiring"],
    widgets: [{ type: "controls", span: 7 }, { type: "exceptions", span: 5, list: false }, { type: "accruals", span: 6 }, { type: "renewals", span: 6 }] }),
  /** Savings: what procurement found and what has landed. */
  savings: blueprint({ id: "savings", filters: ["family", "spend_category_id", "supplier_id"],
    kpis: ["savings_identified", "savings_realised", "price_variance", "contracted_spend"],
    widgets: [{ type: "breakdown", measure: "savings", by: "type", chart: "donut", span: 5, title: "Savings by lever" },
      { type: "breakdown", measure: "savings", by: "status", span: 7, title: "Savings by stage" },
      { type: "trend", measure: "savings", series: ["value"], span: 12, title: "Savings identified by month" },
      { type: "documents", entity: "savings_initiative", title: "Initiatives", dated: false }] }),
};

/* ---------------------------------------------------------------- work screens */

const LEVEL_ICON = { ok: "check-circle", warn: "alert", down: "alert", info: "info" };
const said = (err) => (err && err.rule ? `${err.rule}: ${err.detail || err.message}` : String((err && (err.detail || err.message)) || err));
const OWNED = { requisition: "requester_name", purchase_order: "buyer_name", contract: "owner_name", goods_receipt: "received_by",
  savings_initiative: "owner_name", budget_change: "requested_by" };
const MINE_WORDS = { requisition: "My requests", purchase_order: "My orders", contract: "My contracts", goods_receipt: "My receipts",
  savings_initiative: "My initiatives", budget_change: "My requests" };

/**
 * What the rules say about a request, before it is submitted: fin.advice(await data.advice(requisition.id)).
 * Each finding is { rule, level: ok | info | warn | down, message }.
 */
export function advice(result, opts = {}) {
  css();
  const list = ((result && result.findings) || []).filter(Boolean);
  if (!list.length) return opts.empty === false ? null : nothing("Nothing to flag", "No rule has anything to say about this.");
  return h("div", { class: "fin-advice" }, list.map((f) => h("div", { class: `fin-finding fin-finding-${LEVEL_ICON[f.level] ? f.level : "info"}` },
    h("span", { class: "fin-finding-icon" }, ui.icon(LEVEL_ICON[f.level] || "info", { size: 16 })),
    h("span", { class: "fin-finding-text" }, f.message),
    f.rule ? h("span", { class: "fin-rule mono", title: "The rule that says so" }, f.rule) : null)));
}

/** A form in a dialog whose answer is what `send` returns; a refusal is shown in the dialog, with its rule. */
function ask(opts) {
  return new Promise((resolve) => {
    let done = false;
    const form = ui.form({ fields: opts.fields || [], submit: opts.submit || "Save", submitIcon: opts.submitIcon, reset: false,
      onsubmit: async (values) => {
        try { return await opts.send(values); } catch (err) { throw new Error(said(err)); }
      },
      onsuccess: (result) => { done = true; dialog.close(); resolve(result === undefined || result === null ? true : result); } });
    const above = typeof opts.above === "function" ? opts.above(form) : opts.above;
    const below = typeof opts.below === "function" ? opts.below(form) : opts.below;
    // What the form is told as it is filled in stands above its button, where it is read before pressing.
    if (below) form.insertBefore(below, form.querySelector(".form-actions"));
    const dialog = ui.modal({ title: opts.title, subtitle: opts.subtitle, icon: opts.icon || "edit", size: opts.size,
      content: h("div", { class: "stack fin-ask" }, [above, form].filter(Boolean)), onclose: () => { if (!done) resolve(null); } });
  });
}

const optionsOf = (env, key, none) => [{ value: "", label: none }, ...(((env.dimensions || {})[key] || {}).options || []).map((o) => ({ value: o.value, label: o.label }))];
const blank = (values) => Object.fromEntries(Object.entries(values).map(([k, v]) => [k, v === "" ? null : v]));

async function newRequisition(env, defaults = {}) {
  const live = h("div", { class: "fin-live" });
  let asked = 0;
  const watch = (form) => {
    const tell = async () => {
      const amount = num(form.controls.amount.value);
      const centre = form.controls.cost_center_id.value;
      asked += 1;
      const mine = asked;
      if (amount === null || amount <= 0) { put(live); return; }
      const chain = approvalChain(amount, env.calendar.approval_matrix, { roles: env.calendar.roles || {} });
      put(live, chain);
      if (!centre) return;
      try {
        const position = await env.data.budgetPosition({ cost_center_id: centre, requested: amount });
        if (mine !== asked) return;
        put(live, chain, position.has_budget === false ? null : advice({ findings: [{ rule: "FIN-02", message: position.message,
          level: { ok: "ok", warning: "warn", exceeded: "down" }[position.status] || "info" }] }));
      } catch { /* the budget is not this person's to see: the approver is still shown */ }
    };
    let timer = null;
    const soon = () => { clearTimeout(timer); timer = setTimeout(tell, 350); };
    form.controls.amount.addEventListener("input", soon);
    form.controls.cost_center_id.addEventListener("change", soon);
    if (defaults.amount) soon();
    return live;
  };
  return ask({ title: "New purchase requisition", subtitle: "A draft: you submit it for approval once it says what you need", icon: "plus",
    submit: "Save as draft", size: "lg", below: watch,
    fields: [
      { name: "title", label: "What is needed", required: true, span: "all", value: defaults.title, placeholder: "Twelve laptops for the analytics team" },
      { name: "amount", label: `Amount (${settings.currency})`, type: "number", required: true, min: 0, step: "0.01", value: defaults.amount },
      { name: "cost_center_id", label: "Cost centre", type: "select", required: true, options: optionsOf(env, "cost_center_id", "Choose a cost centre"), value: defaults.cost_center_id },
      { name: "spend_category_id", label: "Category", type: "select", options: optionsOf(env, "spend_category_id", "Choose a category"), value: defaults.spend_category_id },
      { name: "supplier_id", label: "Suggested supplier", type: "select", options: optionsOf(env, "supplier_id", "No preference"), value: defaults.supplier_id },
      { name: "needed_by", label: "Needed by", type: "date", value: defaults.needed_by },
      { name: "justification", label: "Why it is needed", type: "textarea", span: "all", value: defaults.justification },
    ],
    send: (values) => env.data.createRequisition({ ...blank(values), justification: values.justification || "" }) });
}

const outstanding = (row) => Math.max(0, Math.round(((num(row.amount) || 0) - (num(row.received_amount) || 0)) * 100) / 100);

/**
 * What people do to the records of a work screen. A view names them: actions: ["receive"]. Each is offered on the
 * rows it applies to, to the people whose role allows it, and says what happened. An action of one's own:
 *   { key: "chase", label: "Chase", icon: "mail", permission: "purchase_order:update", when: (row) => row.days_late > 0,
 *     run: async (row, env) => { await env.api(`/purchase-orders/${row.id}/chase`, { method: "POST" }); return "Chased"; } }
 * or a step of the record's lifecycle: { transition: "approve", label: "Approve for payment", when: (row) => row.status === "matched" }.
 */
export const ACTIONS = {
  submit: { label: "Submit", icon: "arrow-right", entity: "requisition", permission: "requisition:submit", when: (r) => r.status === "draft",
    async run(row, env) {
      let findings = null;
      try { findings = await env.data.advice(row.id); } catch { /* the advice is a help, not a condition */ }
      const out = await ask({ title: `Submit ${row.reference || "the request"}`, subtitle: `${money(row.amount)} · ${row.title || ""}`, icon: "arrow-right",
        submit: "Submit for approval", above: findings ? advice(findings, { empty: false }) : null,
        fields: [{ name: "reason", label: "Note for the approver", type: "textarea", span: "all", value: row.justification || "" }],
        send: (v) => env.data.transition("requisition", row.id, "submit", { reason: v.reason || "" }) });
      return out ? (out.message || "Submitted for approval") : null;
    } },
  order: { label: "Raise the order", icon: "cart", entity: "requisition", permission: "requisition:order", when: (r) => r.status === "approved",
    async run(row, env) {
      const out = await ask({ title: `Order for ${row.reference || "the request"}`, subtitle: `${money(row.amount)} · ${row.title || ""}`, icon: "cart",
        submit: "Raise the order",
        fields: [{ name: "supplier_id", label: "Supplier", type: "select", required: true, options: optionsOf(env, "supplier_id", "Choose a supplier"), value: row.supplier_id ?? "", span: "all" },
          { name: "expected_delivery", label: "Expected delivery", type: "date", value: String(row.needed_by || "").slice(0, 10) }],
        send: (v) => env.data.raiseOrder(row.id, blank(v)) });
      return out ? `${out.reference} raised${out.supplier ? ` with ${out.supplier}` : ""}` : null;
    } },
  send: { label: "Send to supplier", icon: "mail", entity: "purchase_order", permission: "purchase_order:send", when: (r) => r.status === "approved",
    async run(row, env) {
      if (!(await ui.confirm(`Send ${row.reference || "this order"} for ${money(row.amount)} to ${row.supplier_name || "the supplier"}?`, { title: "Send the order", confirmLabel: "Send" }))) return null;
      const out = await env.data.sendOrder(row.id);
      const erp = out.erp || null;
      return `${out.reference} sent${erp && erp.ok ? ` · in the ERP as ${erp.key}${erp.mode === "sandbox" ? " (sandbox)" : ""}` : ""}`;
    } },
  receive: { label: "Receive", icon: "truck", entity: "purchase_order", permission: "goods_receipt:create", when: (r) => ["sent", "partially_received"].includes(r.status),
    async run(row, env) {
      const left = outstanding(row);
      const out = await ask({ title: `Receive ${row.reference || "the order"}`, icon: "truck", submit: "Post the receipt",
        subtitle: `${row.supplier_name || "Supplier"} · ${money(left)} of ${money(row.amount)} still to come`,
        fields: [{ name: "amount", label: `Value received (${settings.currency})`, type: "number", required: true, min: 0, step: "0.01", value: left || "" },
          { name: "quantity", label: "Quantity (optional)", type: "number", min: 0, step: "any" },
          { name: "received_by", label: "Received by", value: (env.me && (env.me.name || env.me.full_name)) || "", span: "all" },
          { name: "note", label: "Note", type: "textarea", span: "all" }],
        send: (v) => env.data.receive(row.id, blank(v)) });
      return out ? `${row.reference || "Order"} ${out.in_full ? "received in full" : "partly received"}${out.on_time === false ? " · late" : ""}` : null;
    } },
  match: { label: "Match", icon: "layers", entity: "invoice", permission: "invoice:match", when: (r) => r.status === "received",
    async run(row, env) {
      const seen = await env.data.matchPreview(row.id);
      const go = await new Promise((resolve) => {
        let chosen = false;
        ui.modal({ title: `Match ${row.reference || "the invoice"}`, subtitle: [row.supplier_name, money(row.amount)].filter(Boolean).join(" · "), icon: "layers",
          content: h("div", { class: "stack" }, matchStatus(seen),
            h("p", { class: "faint", style: { margin: 0 } }, seen.ok ? "It agrees with its order and receipt: matching moves it on to approval."
              : "It does not agree: matching holds it as an exception, with the reason.")),
          actions: (close) => [ui.button("Cancel", { tone: "secondary", onclick: close }),
            ui.button(seen.ok ? "Match" : "Hold as an exception", { icon: seen.ok ? "check" : "flag", onclick: () => { chosen = true; close(); resolve(true); } })],
          onclose: () => { if (!chosen) resolve(false); } });
      });
      if (!go) return null;
      const out = await env.data.match(row.id);
      return { text: out.ok ? `${row.reference || "Invoice"} matched` : `${row.reference || "Invoice"} held: ${words(out.status)}`, tone: out.ok ? "ok" : "warn" };
    } },
  approve: { label: "Approve", icon: "check", when: (r) => Boolean(r.approval_id && r.can_decide), run: (row, env) => decide(row, env, true) },
  reject: { label: "Reject", icon: "x", tone: "secondary", when: (r) => Boolean(r.approval_id && r.can_decide), run: (row, env) => decide(row, env, false) },
  scorecard: { label: "Scorecard", icon: "chart", entity: "supplier", quiet: true, when: () => true, run: (row, env) => { env.openSupplier(row.id); return null; } },
};

async function decide(row, env, yes) {
  const out = await ask({ title: yes ? "Approve" : "Reject", subtitle: [row.reference, row.title, num(row.amount) !== null ? money(row.amount) : null].filter(Boolean).join(" · "),
    icon: yes ? "check" : "x", submit: yes ? "Approve" : "Reject",
    fields: [{ name: "note", label: yes ? "Note (optional)" : "Why?", type: "textarea", required: !yes, span: "all" }],
    send: (v) => env.data.decide(row.approval_id, yes, v.note || "") });
  if (!out) return null;
  if (typeof window !== "undefined") window.dispatchEvent(new Event("poiesis:notifications"));
  return { text: yes ? `${row.reference || "Request"} approved` : `${row.reference || "Request"} rejected`, tone: yes ? "ok" : "warn" };
}

/** What a work screen offers above its rows: tools: ["propose_run"], or { label, icon, permission, run: async (env) => "Done" }. */
export const TOOLS = {
  propose_run: { label: "Propose a payment run", icon: "dollar", permission: "payment_run:create",
    async run(env) {
      const day = env.calendar.today;
      const out = await ask({ title: "Propose a payment run", subtitle: "Approved invoices due by a date, and the discounts worth taking", icon: "dollar", submit: "Propose the run",
        fields: [{ name: "due_by", label: "Pay what is due by", type: "date", required: true, value: addDays(day, 7) },
          { name: "run_date", label: "Pay on", type: "date", value: addDays(day, 1) }],
        send: (v) => env.data.proposeRun(blank(v)) });
      return out ? `${out.reference || "A run"} proposed: ${number(out.invoices)} invoices, ${money(out.total_amount)}` : null;
    } },
};

const SOURCES = {
  documents: (view, env, state) => env.data.documents({ entity: view.entity, status: view.status, dated: false, sort: view.sort, limit: view.limit || 500,
    mine: state.mine && OWNED[view.entity] ? true : undefined, ...(view.query || {}) }),
  approvals: (view, env) => env.data.approvals({ entity: view.of, ...(view.query || {}) }),
  payable: (view, env) => env.data.payable(view.query || {}).then((r) => ({ ...r, rows: (r.rows || []).map((x) => ({ ...x, id: x.invoice_id })) })),
  renewals: (view, env) => env.data.renewals({ within: 180, ...(view.query || {}) }).then((r) => ({ ...r, amount: r.annual_value })),
};

const VIEW_COLUMNS = {
  approvals: [refCol(), { key: "entity", label: "What", render: (r) => standardTitle(r.entity) },
    { key: "title", label: "For", render: (r) => r.title || r.name || r.supplier_name || r.approval_title || DASH }, { key: "requested_by", label: "Asked by" },
    amountCol("amount", "Amount"), { key: "approver", label: "Approver" },
    { key: "requested_at", label: "Asked", render: (r) => h("span", { class: r.overdue ? "fin-bad-text" : null }, r.overdue ? `${date(r.requested_at)} · overdue` : date(r.requested_at)) }],
  payable: [refCol(), { key: "supplier_name", label: "Supplier" }, dateCol("due_date", "Due"), amountCol("amount", "Invoice"), amountCol("discount", "Discount"),
    amountCol("pay", "To pay"), { key: "why", label: "Why now", render: (r) => words(r.why) }],
  renewals: [refCol(), { key: "title", label: "Contract" }, { key: "supplier_name", label: "Supplier" }, dateCol("decide_by", "Decide by"),
    { key: "days_left", label: "Days left", align: "right" }, amountCol("annual_value", "A year"), statusCol("renewal", "Renewal")],
};

/**
 * A work screen from a description: the records of one job as tabs, each with its count, and what this person does to them.
 * Draws into `root` and returns { reload, env, view() }.
 *
 *   await fin.workbench(root, ctx, fin.worklists.receiving());             // start from the worklist nearest the story
 *
 *   await fin.workbench(root, ctx, {
 *     id: "goods-in",                                   // names what this person's choice of tab is kept under
 *     entity: "purchase_order",                         // of every view that names none
 *     views: [
 *       { key: "due", label: "To receive", status: "sent,partially_received", sort: "expected_delivery", actions: ["receive"] },
 *       { key: "late", label: "Late", status: "sent,partially_received", filter: (row, env) => row.expected_delivery < env.calendar.today },
 *       { key: "receipts", label: "Receipts", entity: "goods_receipt" },
 *     ],
 *     mine: true,                                       // starts with this person's own records, and offers everyone's; left out, no such choice
 *     create: "requisition",                            // a "New" button: the library's requisition form, or { label, permission, run: async (env) => … }
 *     tools: ["propose_run"],                           // buttons above the rows (TOOLS), or { label, icon, run: async (env) => "Done" }
 *     columns: { purchase_order: [...] },               // columns of one's own for an entity; left out, the standard ones
 *   });
 *
 * A view: { key, label, icon?, entity?, status?: "a,b", sort?, query?: { overdue: true }, filter?: (row, env) => bool,
 *   source?: "documents" | "approvals" | "payable" | "renewals", load?: async (env) => ({ rows, count, amount }),
 *   actions?: [names of ACTIONS | { key, label, run } | { transition }], columns?, empty?: { title, hint } }.
 * A row opens the record: what it holds, what the rules say about it, its lifecycle with what this person may do, its history.
 */
export async function workbench(root, ctx, spec = {}) {
  css();
  const { api } = ctx;
  const source = data(api);
  const helpers = ctx.enterprise || {};
  const me = helpers.me ? (typeof helpers.me === "function" ? helpers.me() : helpers.me) : null;
  const store = memory(`fin:work:${slug(spec.id || spec.title || spec.entity || "work")}:${(me && (me.username || me.id)) || "anyone"}`);
  const kept = store.read();
  root.replaceChildren(ui.skeleton());
  let cal, dims;
  try {
    [cal, dims] = await Promise.all([source.calendar(), source.dimensions()]);
  } catch (err) {
    root.replaceChildren(ui.notice(`The records could not be loaded: ${said(err)}`, "down"));
    return { reload() {}, env: null, view: () => null };
  }
  configure({ currency: cal.currency, fiscalStartMonth: cal.fiscal_year_start_month });

  const views = (spec.views && spec.views.length ? spec.views : [{ key: "all", label: "All" }]).map((v, i) => {
    const kind = typeof v.load === "function" ? "custom" : v.source || "documents";
    return { ...v, key: v.key || `view-${i}`, kind, entity: v.entity || (kind === "payable" ? "invoice" : kind === "renewals" ? "contract" : spec.entity) };
  });
  const state = { view: views.some((v) => v.key === (spec.view || kept.view)) ? (spec.view || kept.view) : views[0].key,
    mine: spec.mine === undefined ? false : (kept.mine === undefined ? Boolean(spec.mine) : Boolean(kept.mine)) };
  const found = new Map();          // what each view's rows came to, once they are known
  let generation = 0;

  const env = {
    data: source, ctx, api, spec, calendar: cal, dimensions: dims.dimensions, me,
    can: typeof helpers.can === "function" ? (permission) => helpers.can(permission) : () => true,
    get scope() { return { compare: "none" }; },
    get compare() { return ""; },
    record: (entity) => (row) => opened(views.find((v) => v.key === state.view), { ...row, entity: row.entity || entity }),
    drill(title, question) {
      if (!question || !question.entity) return null;
      return drill({ title, subtitle: "As of today", load: () => source.documents({ dated: false, ...question }), drawer: (row) => recordDrawer(question.entity, row, env) });
    },
    openSupplier(id) {
      if (id === null || id === undefined) return null;
      return ui.drawer({ title: "Supplier", subtitle: "This fiscal year to date", icon: "building",
        content: () => source.scorecard(id, { period: "fy_to_date" }).then((card) => scorecard(card, {
          onDocuments: () => env.drill(`Invoices: ${card.supplier.name}`, { entity: "invoice", supplier_id: id }) })) });
    },
    reload: () => draw(),
  };

  const named = (a) => {
    if (typeof a === "string") return ACTIONS[a] ? { key: a, ...ACTIONS[a] } : null;
    if (a && a.transition) {
      return { key: a.transition, label: a.label || words(a.transition), icon: a.icon || "arrow-right", tone: a.tone, when: a.when || (() => true),
        permission: a.permission, async run(row, env_) {
          const entity = row.entity || a.entity || views.find((v) => v.key === state.view).entity;
          const out = a.note === false ? await env_.data.transition(entity, row.id, a.transition, {})
            : await ask({ title: a.label || words(a.transition), subtitle: row.reference || row.title || row.name, icon: a.icon || "arrow-right", submit: a.label || words(a.transition),
              fields: [{ name: "reason", label: a.reason ? "Reason" : "Note (optional)", type: "textarea", required: Boolean(a.reason), span: "all" }],
              send: (v) => env_.data.transition(entity, row.id, a.transition, { reason: v.reason || "" }) });
          return out ? (out.status === "pending_approval" ? { text: out.message || "Sent for approval", tone: "warn" } : `${a.label || words(a.transition)}: done`) : null;
        } };
    }
    return a && typeof a.run === "function" ? { key: a.key || slug(a.label), when: () => true, ...a } : null;
  };
  const offered = (view, row) => (view.actions || spec.actions || []).map(named).filter(Boolean)
    .filter((a) => (!a.permission || env.can(a.permission)) && guardedTruth(() => a.when(row, env)));

  async function perform(action, row, after) {
    try {
      const out = await action.run(row, env);
      if (out === null || out === undefined || out === false) return;
      const told = typeof out === "object" ? out : { text: String(out), tone: "ok" };
      if (told.text && !action.quiet) ui.toast(told.text, told.tone || "ok");
      if (after) after();
      await draw();
    } catch (err) {
      ui.toast(said(err), "down");
    }
  }

  function opened(view, row) {
    const entity = row.entity && view.kind === "approvals" ? row.entity : (row.entity && !view.entity ? row.entity : view.entity);
    const base = typeof spec.record === "function" ? spec.record(entity, row, env) : recordDrawer(entity, row, env, { panel: { approvals: !row.approval_id } });
    const first = [];
    if (row.approval_id) {
      first.push(ui.notice(h("span", {}, h("b", {}, `Waiting for the ${String(row.approver || "approver").toLowerCase()}`),
        ` · asked by ${row.requested_by || "someone"} on ${date(row.requested_at)}${row.reason ? `: ${row.reason}` : ""}`), row.overdue ? "down" : "warn"));
    }
    if (entity === "requisition" && ["draft", "submitted", "rejected"].includes(row.status) && row.id) {
      const box = h("div", {}, ui.skeleton("rows"));
      source.advice(row.id).then((r) => put(box, advice(r, { empty: false }))).catch(() => put(box));
      first.push(box);
    }
    const acts = offered(view, row);
    return { ...base, content: [...first, ...[].concat(base.content || [])],
      actions: acts.length ? (close) => acts.map((a, i) => ui.button(a.label, { icon: a.icon, tone: a.tone || (i ? "secondary" : undefined),
        onclick: () => perform(a, row, close) })) : base.actions };
  }

  const columnsOf = (view, rows) => {
    const own = view.columns || (spec.columns && !Array.isArray(spec.columns) ? spec.columns[view.entity] : spec.columns);
    const base = own || VIEW_COLUMNS[view.kind] || columnsFor(view.entity, rows);
    if (!(view.actions || spec.actions || []).length) return base;
    return [...base, { label: "", align: "right", render: (row) => {
      const acts = offered(view, row).slice(0, 2);
      return acts.length ? h("span", { class: "fin-row-actions" }, acts.map((a, i) => h("button", { type: "button", class: `sm${i || a.tone === "secondary" ? " secondary" : ""}`,
        "data-action": a.key, onclick: (e) => { e.stopPropagation(); perform(a, row); } }, ui.icon(a.icon || "arrow-right"), h("span", {}, a.label)))) : null;
    } }];
  };

  const tabs = h("div", { class: "fin-views", role: "tablist" });
  const body = h("section", { class: "panel fin-work-body" });
  const bar = h("div", { class: "fin-bar fin-work-bar" });

  // A tab counts from the tally of states where that says it all; a view with a question of its own is asked for.
  const tallied = (view) => view.kind === "documents" && !view.filter && !(view.query && Object.keys(view.query).some((k) => k !== "limit"));

  function counted(view, tally) {
    if (found.has(view.key)) return found.get(view.key);
    const t = tally[view.entity];
    if (!tallied(view) || !t) return null;
    if (t.available === false) return { count: 0, amount: null };
    const wanted = view.status ? new Set(String(view.status).split(",").map((x) => x.trim())) : null;
    const rows = (t.statuses || []).filter((x) => !wanted || wanted.has(x.key));
    return { count: rows.reduce((n, x) => n + x.count, 0), amount: rows.some((x) => x.amount !== null) ? rows.reduce((n, x) => n + (x.amount || 0), 0) : null };
  }

  function drawTabs(tally) {
    put(tabs, views.map((v) => {
      const c = counted(v, tally);
      return h("button", { type: "button", role: "tab", class: `fin-view${v.key === state.view ? " on" : ""}`, "data-view": v.key, "aria-selected": v.key === state.view ? "true" : "false",
        onclick: () => { if (state.view === v.key) return; state.view = v.key; store.write({ view: state.view, mine: state.mine }); draw(); } },
        h("span", { class: "fin-view-label" }, v.icon ? ui.icon(v.icon, { size: 15 }) : null, v.label || words(v.key)),
        h("span", { class: "fin-view-count" }, c ? number(c.count) : DASH),
        h("span", { class: "fin-view-amount faint" }, c && c.amount !== null && c.amount !== undefined ? money(c.amount, { compact: true }) : " "));
    }));
  }

  function shaped(view, result) {
    const given = Array.isArray(result) ? { rows: result } : (result || {});
    const filtered = typeof view.filter === "function";
    const rows = filtered ? (given.rows || []).filter((r) => guardedTruth(() => view.filter(r, env))) : (given.rows || []);
    const amountKey = view.kind === "payable" ? "pay" : view.kind === "renewals" ? "annual_value" : "amount";
    return { ...given, rows, filtered, count: filtered ? rows.length : (given.count ?? rows.length), shown: filtered ? rows.length : (given.shown ?? rows.length),
      amount: filtered ? (rows.some((r) => num(r[amountKey]) !== null) ? rows.reduce((n, r) => n + (num(r[amountKey]) || 0), 0) : null) : (given.amount ?? null) };
  }

  async function draw() {
    generation += 1;
    const mine = generation;
    const view = views.find((v) => v.key === state.view);
    if (!body.childElementCount) put(body, ui.skeleton("rows"));
    const entities = [...new Set(views.filter((v) => tallied(v) && v.entity).map((v) => v.entity))];
    const tallies = Promise.all(entities.map((e) => source.worklist({ entity: e, mine: state.mine && OWNED[e] ? true : undefined }).catch(() => null)));
    const asked = views.filter((v) => v.key === view.key || !tallied(v));
    const answers = await Promise.all(asked.map((v) => Promise.resolve()
      .then(() => (v.kind === "custom" ? v.load(env, state) : SOURCES[v.kind](v, env, state)))
      .then((r) => shaped(v, r), (err) => ({ failure: err }))));
    const tally = Object.fromEntries((await tallies).map((t, i) => [entities[i], t]));
    if (mine !== generation) return;
    found.clear();
    asked.forEach((v, i) => { if (!answers[i].failure) found.set(v.key, { count: answers[i].count, amount: answers[i].amount }); });
    drawTabs(tally);
    const result = answers[asked.indexOf(view)];
    if (result.failure) {
      const text = said(result.failure);
      put(body, /\b(403|may not|permission)\b/i.test(text) ? nothing("Not for your role", "Your role does not include these records.") : ui.notice(`This could not be loaded: ${text}`, "down"));
      return;
    }
    const entityWords = pluralWord(standardTitle(view.entity || "record"));
    const empty = view.empty || (result.available === false
      ? { title: `This application keeps no ${entityWords}`, hint: "Its data model has no such records." }
      : { title: `Nothing under ${String(view.label || words(view.key)).toLowerCase()}`, hint: state.mine && OWNED[view.entity] ? "Nothing of yours is here. Choose Everyone to see the rest." : "When there is something to do here, it appears." });
    put(body,
      result.count > result.shown ? h("p", { class: "faint fin-work-note" }, `The first ${number(result.shown)} of ${number(result.count)} are listed; search narrows them.`) : null,
      documents(view.entity, result.rows, { columns: columnsOf(view, result.rows), drawer: (row) => opened(view, row), exportable: `${slug(spec.id || view.entity)}-${view.key}`,
        pageSize: spec.pageSize || 12, empty, onRow: view.kind === "documents" && view.entity === "supplier" && !(view.actions || spec.actions || []).length ? (row) => env.openSupplier(row.id) : undefined }));
  }

  const owners = views.some((v) => v.kind === "documents" && OWNED[v.entity]);
  const create = spec.create === true ? spec.entity : spec.create;
  const creator = create === "requisition" ? { label: "New requisition", icon: "plus", permission: "requisition:create",
    run: async (env_) => {
      const made = await newRequisition(env_, spec.defaults || {});
      if (!made) return null;
      const drafts = views.find((v) => v.entity === "requisition" && (!v.status || String(v.status).split(",").includes("draft")));
      if (drafts && state.view !== drafts.key) { state.view = drafts.key; store.write({ view: state.view, mine: state.mine }); }
      raf(() => ui.drawer(opened(drafts || views[0], { ...made, entity: "requisition" })));
      return `${made.reference || "The requisition"} saved as a draft`;
    } } : (create && typeof create.run === "function" ? { icon: "plus", label: "New", ...create } : null);
  const tools = (spec.tools || []).map((t) => (typeof t === "string" ? (TOOLS[t] ? { key: t, ...TOOLS[t] } : null) : (t && typeof t.run === "function" ? t : null)))
    .filter(Boolean).filter((t) => !t.permission || env.can(t.permission));
  const press = (tool) => async () => {
    try {
      const out = await tool.run(env);
      if (out === null || out === undefined || out === false) return;
      const told = typeof out === "object" && out.text ? out : { text: String(out), tone: "ok" };
      ui.toast(told.text, told.tone || "ok");
      await draw();
    } catch (err) { ui.toast(said(err), "down"); }
  };
  put(bar,
    spec.mine !== undefined && owners ? ui.segmented({ options: [{ value: "mine", label: MINE_WORDS[spec.entity] || "Mine" }, { value: "all", label: "Everyone" }], value: state.mine ? "mine" : "all",
      onchange: (v) => { state.mine = v === "mine"; store.write({ view: state.view, mine: state.mine }); draw(); } }) : h("span", { class: "faint fin-asof" }, `As of ${date(cal.today)}`),
    h("span", { class: "fin-bar-right" },
      ui.iconButton("refresh", { label: "Refresh", onclick: () => draw() }),
      tools.map((t) => ui.button(t.label, { tone: "secondary", size: "sm", icon: t.icon, onclick: press(t) })),
      creator && (!creator.permission || env.can(creator.permission)) ? ui.button(creator.label, { icon: creator.icon || "plus", onclick: press(creator) }) : null));

  put(root, h("div", { class: "fin-work" }, bar, tabs, body));
  await draw();
  return { reload: draw, env, view: () => state.view };
}

function guardedTruth(test) {
  try { return Boolean(test()); } catch { return false; }
}

function worklist(base) {
  return (over = {}) => {
    const out = { ...base, ...over };
    if (over.views === undefined && (over.add || over.remove)) {
      out.views = base.views.filter((v) => !(over.remove || []).includes(v.key)).concat(over.add || []);
    }
    delete out.add;
    delete out.remove;
    return out;
  };
}

/**
 * Work screens ready to use, each a description to change rather than write. Every one takes what workbench() takes and
 * replaces that part; { add: [views] } and { remove: ["cancelled"] } change the tabs without restating them.
 *   fin.worklists.requisitions({ mine: false })        fin.worklists.invoices({ remove: ["paid"] })
 */
export const worklists = {
  /** A requester's page: raise a request, see what the rules say, submit it, follow it to the order. */
  requisitions: worklist({ id: "requisitions", entity: "requisition", mine: true, create: "requisition",
    views: [{ key: "draft", label: "Drafts", icon: "edit", status: "draft,rejected", actions: ["submit"],
      empty: { title: "No drafts", hint: "Choose New requisition to ask for something." } },
    { key: "waiting", label: "Waiting for approval", icon: "clock", status: "submitted" },
    { key: "approved", label: "Approved", icon: "check-circle", status: "approved" },
    { key: "ordered", label: "Ordered", icon: "cart", status: "ordered" },
    { key: "cancelled", label: "Cancelled", icon: "x", status: "cancelled" }] }),
  /** An approver's page: what waits for their decision, with the budget and the rules beside it. */
  approvals: worklist({ id: "approvals",
    views: [{ key: "mine", label: "Waiting for me", icon: "inbox", source: "approvals", actions: ["approve", "reject"],
      empty: { title: "Nothing waits for you", hint: "When someone asks for a decision your role makes, it appears here." } },
    { key: "all", label: "Everything waiting", icon: "list", source: "approvals", query: { mine: false }, actions: ["approve", "reject"],
      empty: { title: "Nothing is waiting", hint: "No request is waiting for anyone's decision." } }] }),
  /** A buyer's page: approved requests to turn into orders, orders to send, orders with suppliers. */
  ordering: worklist({ id: "ordering", entity: "purchase_order",
    views: [{ key: "to_order", label: "To order", icon: "inbox", entity: "requisition", status: "approved", actions: ["order"],
      empty: { title: "Nothing to order", hint: "Approved requisitions appear here." } },
    { key: "to_send", label: "To send", icon: "mail", status: "approved", actions: ["send"] },
    { key: "in_approval", label: "Drafts and in approval", icon: "clock", status: "draft,pending_approval" },
    { key: "with_suppliers", label: "With suppliers", icon: "truck", status: "sent,partially_received", sort: "expected_delivery" },
    { key: "received", label: "Received", icon: "check-circle", status: "received,closed" }] }),
  /** Goods in: what is expected, what is late, what has arrived. */
  receiving: worklist({ id: "receiving", entity: "purchase_order",
    views: [{ key: "due", label: "To receive", icon: "truck", status: "sent,partially_received", sort: "expected_delivery", actions: ["receive"],
      empty: { title: "Nothing to receive", hint: "Orders sent to suppliers appear here until they arrive." } },
    { key: "late", label: "Late", icon: "alert", status: "sent,partially_received", sort: "expected_delivery", actions: ["receive"],
      filter: (row, env) => Boolean(row.expected_delivery) && String(row.expected_delivery).slice(0, 10) < env.calendar.today,
      empty: { title: "Nothing is late", hint: "Every order still to come is within its date." } },
    { key: "received", label: "Received", icon: "check-circle", status: "received" },
    { key: "receipts", label: "Receipts", icon: "file", entity: "goods_receipt", query: { limit: 300 } }] }),
  /** Accounts payable: invoices to match, held, to approve, to pay. */
  invoices: worklist({ id: "invoices", entity: "invoice",
    views: [{ key: "to_match", label: "To match", icon: "layers", status: "received", sort: "due_date", actions: ["match"],
      empty: { title: "Nothing to match", hint: "Invoices appear here as they arrive." } },
    { key: "held", label: "Held", icon: "flag", status: "exception", sort: "due_date" },
    { key: "to_approve", label: "To approve", icon: "shield", status: "matched", sort: "due_date" },
    { key: "to_pay", label: "To pay", icon: "dollar", status: "approved,scheduled", sort: "due_date" },
    { key: "overdue", label: "Overdue", icon: "alert", query: { overdue: true }, sort: "due_date" },
    { key: "paid", label: "Paid", icon: "check-circle", status: "paid", query: { limit: 300 } }] }),
  /** Payment runs: what is due, propose a run, follow it to the bank. */
  paymentRuns: worklist({ id: "payment-runs", entity: "payment_run", tools: ["propose_run"],
    views: [{ key: "payable", label: "Due to pay", icon: "dollar", source: "payable",
      empty: { title: "Nothing is due", hint: "Approved invoices appear here as they fall due." } },
    { key: "proposed", label: "Proposed", icon: "clock", status: "proposed" },
    { key: "approved", label: "Approved", icon: "shield", status: "approved" },
    { key: "released", label: "Released", icon: "check-circle", status: "released,completed" }] }),
  /** Supplier management: onboarding, the approved list, who is suspended. */
  suppliers: worklist({ id: "supplier-list", entity: "supplier", actions: ["scorecard"],
    views: [{ key: "onboarding", label: "Onboarding", icon: "clock", status: "prospective,under_review" },
      { key: "active", label: "Approved", icon: "check-circle", status: "approved,active" },
      { key: "suspended", label: "Suspended", icon: "alert", status: "suspended" },
      { key: "retired", label: "Retired", icon: "x", status: "retired" }] }),
  /** Contracts: the ones to decide on, in force, in negotiation, ended. */
  contracts: worklist({ id: "contracts", entity: "contract",
    views: [{ key: "decide", label: "To decide", icon: "alert", source: "renewals",
      empty: { title: "No contract to decide on", hint: "Contracts appear here ahead of their notice date." } },
    { key: "in_force", label: "In force", icon: "check-circle", status: "signed,active,expiring", sort: "end_date" },
    { key: "negotiation", label: "In negotiation", icon: "edit", status: "draft,in_negotiation" },
    { key: "ended", label: "Ended", icon: "x", status: "expired,terminated" }] }),
};

const fin = {
  configure, num, money, percent, number, days, format, words, date, variance, calendar, query, data, status, delta, varianceBadge,
  kpis, kpi, gauge, trend, budgetBars, waterfall, pareto, treemap, donut, aging, funnel, pivot, cycleTimes, matchStatus, approvalChain, lifecycle,
  controlList, renewalList, scorecard, exportCsv, columnsFor, documents, drill, periodPicker, filterBar, dashboard, blueprints, WIDGETS,
  workbench, worklists, advice, ACTIONS, TOOLS,
};
export default fin;
