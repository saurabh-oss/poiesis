/*
 * The enterprise half of the shell. Written by Poiesis, and read-only.
 *
 * app.js loads this module when /api/platform/profile says the application is an
 * enterprise one. It owns:
 *   - signing in (demonstration personas, or a password), the user card and the
 *     notification bell in the sidebar;
 *   - four platform screens: Approvals, Audit trail, Business rules, Integrations;
 *   - the Guide: what the application is for, its process as a diagram, who does what, how a
 *     record moves, written from the application's own roles, lifecycles, rules and screens;
 *   - `enterprise`, the helpers every story screen receives in render():
 *
 *       async render(root, { api, ui, h, enterprise }) {
 *         const { me, can, workflow } = enterprise;
 *         ui.table({ rows, drawer: (t) => ({ title: t.subject,
 *           content: workflow.panel("ticket", t.id, { onChange: reload }) }) });
 *         if (can("ticket:merge")) actions.append(ui.button("Merge", { … }));
 *       }
 *
 *     workflow.panel(entity, id, opts)   state, SLA clock, the transitions this person may take, approvals, history
 *     workflow.actions(entity, id, opts) just the transition buttons, for a row or a card
 *     workflow.badge(entity, state)      the state as a badge with its label
 *     audit.history(entity, id)          the record's audit timeline
 */
import * as ui from "./ui.js";

const { h } = ui;
const TOKEN = "poiesis-token";
let api = null;
let profile = null;
let me = null;
const defs = {};

/* ---------------------------------------------------------------- session */

export function token() {
  try { return localStorage.getItem(TOKEN); } catch { return null; }
}

function setToken(value) {
  try { if (value) localStorage.setItem(TOKEN, value); else localStorage.removeItem(TOKEN); } catch { /* private mode */ }
}

export function signOut() {
  setToken(null);
  location.hash = "";
  location.reload();
}

/** Called by app.js when any request answers 401: the session ended. */
export function expired() {
  if (document.querySelector(".signin")) return;
  setToken(null);
  signInPage("Your session has ended. Sign in again.");
}

function stylesheet() {
  if (!document.getElementById("platform-css")) document.head.append(h("link", { id: "platform-css", rel: "stylesheet", href: "platform.css" }));
}

/** Sign in if needed; returns the signed-in person, or null while the sign-in page shows. */
export async function boot(context) {
  api = context.api;
  profile = context.profile || {};
  stylesheet();
  if (!token()) { await signInPage(); return null; }
  try {
    me = await api("/auth/me");
  } catch (err) {
    setToken(null);
    await signInPage();
    return null;
  }
  chrome();
  return me;
}

/* ---------------------------------------------------------------- permissions */

export function can(permission) {
  if (!me) return false;
  if (me.kind !== "user" || (me.roles || []).includes("admin")) return true;
  const [entity, action] = permission.split(":");
  return (me.permissions || []).some((g) => {
    if (g === "*" || g === permission) return true;
    const [ge, ga] = g.split(":");
    return (ga === "*" && ge === entity) || (ge === "*" && ga === action);
  });
}

export function mayOpen(screenId) {
  const allowed = (me && me.screens && me.screens[screenId]) || null;
  if (!allowed || !allowed.length) return true;
  return (me.roles || []).includes("admin") || (me.roles || []).some((r) => allowed.includes(r));
}

/* ---------------------------------------------------------------- the sign-in page */

const CONNECTOR_NAMES = { jira: "Jira", servicenow: "ServiceNow", plane: "Plane", email: "E-mail", slack: "Slack", teams: "Teams", erp: "ERP" };

async function signInPage(message) {
  stylesheet();
  let people = { mode: "personas", personas: [] };
  try { people = await api("/auth/personas"); } catch (err) { message = message || err.message; }
  const appName = profile.app || document.title;
  const error = h("p", { class: "signin-error", role: "alert" }, message || "");
  const go = async (body, el) => {
    if (el) el.classList.add("busy");
    error.textContent = "";
    try {
      const out = await api("/auth/sign-in", { method: "POST", body });
      setToken(out.token);
      location.reload();
    } catch (err) {
      if (el) el.classList.remove("busy");
      error.textContent = String(err.message || err).replace(/^POST \/api\/auth\/sign-in failed with \d+: /, "").replace(/^"|"$/g, "");
    }
  };
  const password = h("form", { class: "signin-password", onsubmit: (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    go({ username: String(f.get("username") || ""), password: String(f.get("password") || "") }, e.target.querySelector("button"));
  } },
  h("div", { class: "field" }, h("label", {}, "Username"), h("input", { name: "username", autocomplete: "username", required: true })),
  h("div", { class: "field" }, h("label", {}, "Password"), h("input", { name: "password", type: "password", autocomplete: "current-password", required: true })),
  h("button", { type: "submit" }, "Sign in"));
  const cards = (people.personas || []).map((p, i) => {
    const card = h("button", { type: "button", class: "persona", style: { animationDelay: `${i * 60}ms` },
      onclick: () => go({ username: p.username }, card) },
    ui.avatar(p.full_name, { size: "lg" }),
    h("span", { class: "persona-text" }, h("strong", {}, p.full_name), h("span", { class: "faint" }, [p.title, p.team].filter(Boolean).join(" · "))),
    h("span", { class: "persona-roles" }, (p.roles || []).map((r) => h("span", { class: "role-chip" }, r.label))),
    ui.icon("arrow-right", { class: "persona-go" }));
    return card;
  });
  const connectors = Object.entries(profile.connectors || {});
  const live = connectors.filter(([, m]) => m === "live").map(([n]) => CONNECTOR_NAMES[n] || n);
  const points = [
    ["shield", "Roles and approvals", "Each person sees and does what their role allows; big decisions need a second pair of eyes."],
    ["history", "A complete audit trail", "Every change is recorded: who, when, and what it was before."],
    ["link", "Connected", connectors.length
      ? `${connectors.map(([n]) => CONNECTOR_NAMES[n] || n).join(", ")}${live.length ? ` — live: ${live.join(", ")}` : " — in sandbox mode"}`
      : "Works with the systems you already use."],
  ];
  const page = h("div", { class: "signin" },
    h("section", { class: "signin-brand" }, h("span", { class: "signin-glow" }),
      h("div", { class: "brand" }, h("span", { class: "brand-mark" }, ui.initials(appName)), h("span", { class: "brand-name" }, appName)),
      h("div", { class: "signin-pitch" },
        h("h1", {}, "Sign in to ", h("span", { class: "grad-text" }, appName)),
        h("ul", {}, points.map(([ic, t, d]) => h("li", {}, h("span", { class: "signin-ic" }, ui.icon(ic)), h("div", {}, h("strong", {}, t), h("span", {}, d)))))),
      h("p", { class: "signin-foot" }, "Built by Poiesis · enterprise edition")),
    h("section", { class: "signin-panel" },
      h("div", { class: "signin-card" },
        people.mode === "personas" && cards.length
          ? [h("h2", {}, "Who are you today?"),
            h("p", { class: "muted" }, "Demonstration accounts: pick one to see the application as that person, with their role's permissions."),
            h("div", { class: "personas" }, cards),
            h("details", { class: "signin-more" }, h("summary", {}, "Sign in with a password instead"), password)]
          : [h("h2", {}, "Sign in"), h("p", { class: "muted" }, "Use the account your administrator gave you."), password],
        people.policy_error ? ui.notice(`The application's policy did not load: ${people.policy_error}`, "down") : null,
        error)));
  document.getElementById("shell").hidden = true;
  document.querySelector(".signin")?.remove();
  document.body.append(page);
  if (window.__poiesis) { window.__poiesis.ready = true; window.__poiesis.signin = true; }
}

/* ---------------------------------------------------------------- sidebar chrome */

function chrome() {
  const side = document.querySelector(".sidebar");
  const foot = side && side.querySelector(".sidebar-foot");
  if (!side || !foot || side.querySelector(".user-card")) return;
  const card = h("button", { type: "button", class: "user-card", title: `${me.name} — ${me.role_labels.join(", ")}`, onclick: openMe },
    ui.avatar(me.name, { size: "sm" }),
    h("span", { class: "user-text" }, h("strong", {}, me.name), h("span", {}, me.role_labels.join(", ") || me.title)),
    ui.icon("chevron-down", { class: "user-caret" }));
  const count = h("span", { class: "bell-count", hidden: !me.unread }, String(me.unread || ""));
  const bell = h("button", { type: "button", class: "icon-btn bell", "aria-label": "Notifications", "data-tip": "Notifications", onclick: openInbox },
    ui.icon("bell"), count);
  side.insertBefore(card, foot);
  foot.prepend(bell);
  const refresh = async () => {
    try {
      const n = await api("/platform/notifications?limit=1");
      count.hidden = !n.unread;
      count.textContent = n.unread > 99 ? "99+" : String(n.unread);
    } catch { /* offline for a moment */ }
  };
  setInterval(refresh, 30000);
  window.addEventListener("poiesis:notifications", refresh);
}

function openMe() {
  ui.drawer({
    title: me.name, subtitle: [me.title, me.role_labels.join(", ")].filter(Boolean).join(" · "), icon: "user",
    content: h("div", { class: "stack" },
      ui.kv([{ label: "Username", value: me.username }, { label: "E-mail", value: me.email }, { label: "Roles", value: h("span", { class: "row" }, me.role_labels.map((r) => h("span", { class: "role-chip" }, r))) }]),
      ui.section("What you may do", { icon: "shield" },
        h("div", { class: "perm-list" }, (me.permissions || []).length ? me.permissions.map((p) => h("code", {}, p)) : h("span", { class: "faint" }, "Everything (administrator)")))),
    actions: (close) => [ui.button("Switch user", { icon: "users", tone: "secondary", onclick: () => { close(); signOut(); } }),
      ui.button("Sign out", { icon: "logout", onclick: signOut })],
  });
}

async function openInbox() {
  const data = await api("/platform/notifications?limit=60");
  const list = h("div", { class: "inbox" });
  const paint = (items) => list.replaceChildren(...(items.length ? items.map((n) => h("button", {
    type: "button", class: `inbox-item${n.read ? "" : " unread"} tone-${n.level}`,
    onclick: async () => {
      if (!n.read) { await api(`/platform/notifications/${n.id}/read`, { method: "POST" }); n.read = true; }
      window.dispatchEvent(new Event("poiesis:notifications"));
      if (n.link) { d.close(); location.hash = n.link; } else paint(items);
    } },
  h("span", { class: "inbox-dot" }), h("span", { class: "inbox-text" }, h("strong", {}, n.title), n.body ? h("span", {}, n.body) : null,
    h("span", { class: "faint" }, ui.timeAgo(n.at))))) : [ui.empty("You're all caught up", "Approvals, escalations and decisions about your requests appear here.", { icon: "bell" })]));
  paint(data.items);
  const d = ui.drawer({
    title: "Notifications", subtitle: data.unread ? `${data.unread} unread` : "Nothing unread", icon: "bell", content: list,
    actions: data.unread ? (close) => [ui.button("Mark all read", { icon: "check", tone: "secondary", onclick: async () => {
      await api("/platform/notifications/read-all", { method: "POST" });
      window.dispatchEvent(new Event("poiesis:notifications"));
      close();
    } })] : [],
  });
}

/* ---------------------------------------------------------------- helpers for story screens */

function errorText(err) {
  if (err && err.rule) return `${err.rule}: ${err.detail}`;
  return String((err && (err.detail || err.message)) || err);
}

async function definition(entity) {
  if (!defs.__all) defs.__all = api("/platform/workflows").catch(() => []);
  const all = await defs.__all;
  return all.find((w) => w.entity === entity || w.name === entity) || null;
}

function stateBadge(label, key, final) {
  return h("span", { class: `badge wf-state${final ? " final" : ""}`, "data-state": key }, label);
}

function slaLine(clocks) {
  const open = (clocks || []).filter((c) => !c.left_at).pop();
  if (!open) return null;
  const since = h("span", {}, "In this state ", h("b", {}, ui.timeAgo(open.entered_at).replace(/ ago$/, "")));
  if (!open.due_at) return h("div", { class: "wf-clock faint" }, ui.icon("clock"), since);
  const breached = open.breached_at || new Date(open.due_at) < new Date();
  return h("div", { class: `wf-clock ${breached ? "breached" : ""}` }, ui.icon(breached ? "alert" : "clock"), since, " · ",
    breached ? h("b", {}, "SLA breached") : h("span", {}, "due ", h("b", { "data-tip": ui.dateTime(open.due_at) }, ui.timeAgo(open.due_at).replace("ago", "from now").replace(/^in /, ""))));
}

async function perform(entity, id, t, opts) {
  let body = {};
  // A request for approval always asks for a note: the approver decides on what it says.
  if (t.requires_reason || t.approval || (t.fields || []).length) {
    const fields = [...(t.fields || []).map((f) => ({ name: f, label: ui.label(f), required: true })),
      { name: "reason", label: t.requires_reason ? "Reason" : t.approval ? "Note for the approver" : "Note (optional)",
        type: "textarea", required: t.requires_reason, span: "all" }];
    const values = await ui.formModal({ title: t.label, subtitle: `Moves it to ${t.to_label}${t.approval ? " once approved" : ""}`, icon: "arrow-right", fields,
      submit: t.label, toast: false, onsubmit: async (v) => v });
    if (!values) return null;
    const { reason, ...rest } = values;
    body = { reason: reason || "", fields: rest };
  }
  try {
    const out = await api(`/platform/workflows/${entity}/${id}/${t.name}`, { method: "POST", body });
    ui.toast(out.status === "pending_approval" ? out.message : `${t.label}: done`, out.status === "pending_approval" ? "warn" : "ok");
    window.dispatchEvent(new Event("poiesis:notifications"));
    if (opts && opts.onChange) await opts.onChange(out);
    return out;
  } catch (err) {
    ui.toast(errorText(err), "down");
    return null;
  }
}

function actionButtons(entity, id, data, opts, redraw) {
  const shown = (data.available || []).filter((t) => t.allowed || !(opts && opts.hideDisallowed));
  if (!shown.length) return null;
  return h("div", { class: "wf-actions" }, shown.map((t) => {
    const b = ui.button(t.label, {
      tone: t.tone === "down" ? "danger" : t.tone === "warn" ? "secondary" : undefined,
      icon: t.approval ? "shield" : t.tone === "ok" ? "check" : "arrow-right", size: opts && opts.compact ? "sm" : undefined,
      disabled: !t.allowed, tip: t.allowed ? (t.approval ? "Needs approval" : `Moves it to ${t.to_label}`) : t.why_not,
      onclick: async () => { const out = await perform(entity, id, t, opts); if (out) await redraw(); },
    });
    return b;
  }));
}

function workflowPanel(entity, id, opts = {}) {
  const box = h("div", { class: "wf-panel stack" }, ui.skeleton("rows"));
  const draw = async () => {
    let data;
    try {
      data = await api(`/platform/workflows/${entity}/${id}`);
    } catch (err) {
      box.replaceChildren(ui.notice(errorText(err), "down"));
      return;
    }
    const def = data.definition;
    const current = def.states.findIndex((s) => s.key === data.state);
    const steps = h("ol", { class: "wf-steps" }, def.states.map((s, i) => h("li", {
      class: `${i < current ? "past" : ""}${i === current ? " now" : ""}${def.final.includes(s.key) ? " final" : ""}`,
      "data-tip": s.sla_hours ? `SLA ${s.sla_hours} h` : null }, h("span", { class: "wf-dot" }), h("span", {}, s.label))));
    const approvals = (opts.approvals === false ? [] : data.approvals || []).map((a) => ui.notice(h("span", {}, h("b", {}, `Waiting for ${a.approver_label}`),
      ` to approve “${a.title}” — asked by ${a.requested_by} ${ui.timeAgo(a.requested_at)}${a.reason ? `: ${a.reason}` : ""}`), "warn"));
    const history = (data.history || []).filter((e) => ["transition", "approval", "create", "sla", "rule", "connector"].includes(e.action)).slice(0, opts.historyLimit || 8)
      .map((e) => ({ title: e.summary, body: `${e.actor}${e.rule ? ` · ${e.rule}` : ""}`, time: e.at,
        tone: e.action === "sla" ? "down" : e.action === "approval" ? "warn" : e.action === "transition" ? "ok" : undefined,
        icon: { transition: "arrow-right", approval: "shield", create: "plus", sla: "alert", rule: "flag", connector: "link" }[e.action] }));
    box.replaceChildren(
      h("div", { class: "wf-head" }, h("span", { class: "faint" }, def.title || "Status"), stateBadge(data.state_label, data.state, data.final), slaLine(data.clocks)),
      steps, ...approvals,
      data.final ? h("p", { class: "faint", style: { margin: 0 } }, "This is a final state.") : actionButtons(entity, id, data, opts, draw),
      opts.history === false ? null : h("div", { class: "stack" }, h("div", { class: "nav-label", style: { padding: 0 } }, "History"), ui.timeline(history)));
  };
  draw();
  return box;
}

function workflowActions(entity, id, opts = {}) {
  const box = h("span", { class: "wf-inline" });
  const draw = async () => {
    try {
      const data = await api(`/platform/workflows/${entity}/${id}`);
      box.replaceChildren(actionButtons(entity, id, data, { ...opts, compact: true, hideDisallowed: true }, draw) || h("span", { class: "faint" }, "—"));
    } catch (err) {
      box.replaceChildren(h("span", { class: "faint" }, "—"));
    }
  };
  draw();
  return box;
}

function badgeFor(entity, state) {
  const el = h("span", { class: "badge wf-state", "data-state": state }, ui.label(state || ""));
  definition(entity).then((def) => {
    const s = def && def.states.find((x) => x.key === state);
    if (s) { el.textContent = s.label; if (def.final.includes(state)) el.classList.add("final"); }
  });
  return el;
}

function historyFor(entity, id) {
  const box = h("div", {}, ui.skeleton("rows"));
  api(`/platform/audit?entity=${encodeURIComponent(entity)}&entity_id=${id}&limit=50`).then((rows) => {
    box.replaceChildren(ui.timeline(rows.map((e) => ({ title: e.summary, body: e.actor, time: e.at, tone: e.action === "delete" ? "down" : undefined }))));
  }).catch((err) => box.replaceChildren(ui.notice(errorText(err), "down")));
  return box;
}

export function helpers() {
  return {
    me, can, mayOpen,
    workflow: { panel: workflowPanel, actions: workflowActions, badge: badgeFor, definition },
    audit: { history: historyFor },
  };
}

/* ---------------------------------------------------------------- platform screens */

function json(value) {
  return h("pre", { class: "json" }, JSON.stringify(value ?? null, null, 2));
}

const approvalsScreen = {
  title: "Approvals", subtitle: "Decisions waiting for you, and the ones you asked for", icon: "check-circle",
  async render(root, { actions }) {
    const [open, all] = await Promise.all([api("/platform/approvals?status=pending&scope=mine"), api("/platform/approvals?status=all&scope=mine&limit=500")]);
    const waiting = open.filter((a) => a.can_decide);
    const mine = all.filter((a) => a.requested_by === me.name);
    const decided = all.filter((a) => a.status !== "pending");
    const reload = async () => { root.replaceChildren(); actions.replaceChildren(); await approvalsScreen.render(root, { actions }); };
    const decide = async (a, approve) => {
      const values = await ui.formModal({
        title: approve ? "Approve" : "Reject", subtitle: a.title, icon: approve ? "check" : "x", submit: approve ? "Approve" : "Reject", toast: false,
        fields: [{ name: "note", label: approve ? "Note (optional)" : "Why?", type: "textarea", required: !approve, span: "all" }],
        onsubmit: async (v) => v,
      });
      if (!values) return;
      try {
        await api(`/platform/approvals/${a.id}/${approve ? "approve" : "reject"}`, { method: "POST", body: { note: values.note || "" } });
        ui.toast(approve ? "Approved" : "Rejected", approve ? "ok" : "warn");
        if (approve) ui.celebrate();
        window.dispatchEvent(new Event("poiesis:notifications"));
        await reload();
      } catch (err) { ui.toast(errorText(err), "down"); }
    };
    const card = (a) => h("div", { class: `card approval-card${a.overdue ? " overdue" : ""}` },
      h("div", { class: "between" }, h("strong", {}, a.title), a.overdue ? ui.badge("Overdue", "down") : ui.badge(a.approver_label)),
      h("div", { class: "row wf-move" }, ui.badge(ui.label(a.from_state)), ui.icon("arrow-right"), ui.badge(ui.label(a.to_state), "ok")),
      a.reason ? h("p", { class: "approval-reason" }, "“", a.reason, "”") : null,
      h("div", { class: "between" }, ui.person(a.requested_by, `asked ${ui.timeAgo(a.requested_at)}`),
        h("div", { class: "row" }, ui.button("Reject", { tone: "secondary", icon: "x", onclick: () => decide(a, false) }),
          ui.button("Approve", { icon: "check", onclick: () => decide(a, true) }))));
    const columns = [
      { key: "title", label: "Request" },
      { key: "approver_label", label: "Approver" },
      { key: "status", label: "Status", badge: true },
      { key: "requested_by", label: "Asked by", render: (a) => ui.person(a.requested_by) },
      { key: "requested_at", label: "Asked", format: "ago" },
      { key: "decided_by", label: "Decided by" },
    ];
    const drawer = (a) => ({ title: a.title, subtitle: `${a.status} · ${a.approver_label}`, icon: "shield",
      content: h("div", { class: "stack" }, ui.kv([
        { label: "Moves", value: `${ui.label(a.from_state)} → ${ui.label(a.to_state)}` }, { label: "Asked by", value: a.requested_by },
        { label: "Asked", value: ui.dateTime(a.requested_at) }, { label: "Reason", value: a.reason },
        { label: "Decided by", value: a.decided_by }, { label: "Decided", value: a.decided_at ? ui.dateTime(a.decided_at) : "" },
        { label: "Note", value: a.decision_note }]), workflowPanel(a.entity, a.entity_id, { onChange: reload })) });
    root.append(
      ui.stats([
        { label: "Waiting for you", value: waiting.length, icon: "inbox", tone: waiting.length ? "warn" : "ok" },
        { label: "Overdue", value: open.filter((a) => a.overdue).length, icon: "alert", tone: open.some((a) => a.overdue) ? "down" : undefined },
        { label: "Your open requests", value: mine.filter((a) => a.status === "pending").length, icon: "clock" },
        { label: "Decided", value: decided.length, icon: "check-circle", tone: "ok" },
      ]),
      ui.tabs([
        { label: "Waiting for you", icon: "inbox", badge: waiting.length,
          content: () => waiting.length ? h("div", { class: "grid-2 approvals-grid" }, waiting.map(card))
            : ui.empty("Nothing waiting for you", "When someone asks for a decision your role makes, it appears here.", { icon: "check-circle" }) },
        { label: "Your requests", icon: "user", badge: mine.length,
          content: () => ui.table({ columns, rows: mine, search: true, drawer, filters: [{ key: "status" }], empty: { title: "You haven't asked for any approvals" } }) },
        { label: "History", icon: "history", badge: decided.length,
          content: () => ui.table({ columns, rows: decided, search: true, drawer, filters: [{ key: "status" }, { key: "approver_label" }], empty: { title: "No decisions yet" } }) },
      ]),
    );
  },
};

const ACTION_TONE = { create: "ok", update: undefined, delete: "down", transition: "info", approval: "warn", sla: "down", sign_in: undefined, connector: "info", rule: "warn" };

const auditScreen = {
  title: "Audit trail", subtitle: "Every change, who made it, and what it was before", icon: "history",
  async render(root) {
    const [stats, rows] = await Promise.all([api("/platform/audit/stats?days=30"), api("/platform/audit?limit=1500")]);
    const people = new Set(rows.map((r) => r.actor)).size;
    const byAction = Object.fromEntries(stats.by_action);
    const changesTable = (changes) => {
      const entries = Object.entries(changes || {});
      if (!entries.length) return null;
      return h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Field"), h("th", {}, "Before"), h("th", {}, "After"))),
        h("tbody", {}, entries.map(([k, [a, b]]) => h("tr", {}, h("td", { class: "mono" }, k),
          h("td", { class: "diff-old" }, a === null || a === undefined ? "—" : String(a)), h("td", { class: "diff-new" }, b === null || b === undefined ? "—" : String(b)))))));
    };
    root.append(
      ui.stats([
        { label: "Events recorded", value: stats.total, icon: "history" },
        { label: "Last 30 days", value: stats.per_day.reduce((a, d) => a + d.value, 0), icon: "activity", spark: stats.per_day.map((d) => d.value) },
        { label: "People and systems", value: people, icon: "users" },
        { label: "Workflow moves", value: (byAction.transition || 0) + (byAction.approval || 0), icon: "arrow-right", tone: "ok" },
      ]),
      ui.split(
        ui.section("Activity, last 30 days", { icon: "chart" }, stats.per_day.length ? ui.timeseries(stats.per_day, { height: 150 }) : ui.empty("No activity yet")),
        ui.section("By kind", { icon: "pie" }, ui.donut(stats.by_action.map(([label, value]) => ({ label: ui.label(label), value })), { center: String(stats.total), sub: "events" }))),
      ui.section("Every event", { icon: "list" }, ui.table({
        columns: [
          { key: "at", label: "When", format: "ago" },
          { key: "actor", label: "Who", render: (r) => ui.person(r.actor, r.actor_kind !== "user" ? r.actor_kind : undefined) },
          { key: "action", label: "What", render: (r) => ui.badge(ui.label(r.action), ACTION_TONE[r.action]) },
          { key: "summary", label: "Change" },
          { key: "rule", label: "Rule", render: (r) => r.rule ? h("code", {}, r.rule) : "" },
        ],
        rows, search: true, keyboard: true, pageSize: 30, filters: [{ key: "action" }, { key: "actor" }, { key: "entity" }],
        drawer: (r) => ({ title: ui.label(r.action), subtitle: `${r.actor} · ${ui.dateTime(r.at)}`, icon: "history",
          content: h("div", { class: "stack" }, h("p", { style: { margin: 0 } }, r.summary),
            ui.kv([{ label: "Record", value: r.entity ? `${r.entity} ${r.entity_id ?? ""}` : "" }, { label: "Rule", value: r.rule }, { label: "Who", value: `${r.actor} (${r.actor_kind})` }]),
            changesTable(r.changes),
            r.entity && r.entity_id ? ui.section("This record's history", { icon: "history" }, historyFor(r.entity, r.entity_id)) : null) }),
        empty: { title: "Nothing recorded yet", hint: "Changes appear here the moment they are made." },
      })),
    );
  },
};

const KIND_TONE = { decision: "info", validation: "warn", calculation: "ok", authorisation: "down", workflow: undefined, notification: undefined, integration: "info" };

function flowDiagram(w, roles) {
  const byFrom = {};
  for (const t of w.transitions) for (const f of t.from) (byFrom[f] = byFrom[f] || []).push(t);
  return h("div", { class: "stack" },
    h("div", { class: "wf-flow" }, w.states.map((s, i) => [
      i ? h("span", { class: "wf-arrow" }, ui.icon("arrow-right")) : null,
      h("div", { class: `wf-node${s.key === w.initial ? " start" : ""}${w.final.includes(s.key) ? " final" : ""}` },
        h("strong", {}, s.label), h("span", { class: "faint" }, s.sla_hours ? `SLA ${s.sla_hours} h${s.escalate_to ? ` → ${roles[s.escalate_to] || s.escalate_to}` : ""}` : (w.final.includes(s.key) ? "final" : s.key === w.initial ? "start" : "")))])),
    ui.table({
      columns: [
        { key: "label", label: "Transition" },
        { key: "move", label: "From → to", render: (t) => h("span", { class: "row", style: { gap: "6px" } }, t.from.map((f) => ui.badge(w.states.find((s) => s.key === f)?.label || f)), ui.icon("arrow-right"), ui.badge(w.states.find((s) => s.key === t.to)?.label || t.to, "ok")) },
        { key: "roles", label: "Who", render: (t) => t.roles.length ? t.roles.map((r) => roles[r] || r).join(", ") : "permission holders" },
        { key: "approval", label: "Approved by", render: (t) => t.approval ? ui.badge(roles[t.approval] || t.approval, "warn") : "—" },
        { key: "rule", label: "Rule", render: (t) => t.rule ? h("code", {}, t.rule) : "" },
      ],
      rows: w.transitions.map((t) => ({ ...t, move: t.from.join(",") })), sortable: false, pageSize: 50,
    }));
}

const rulesScreen = {
  title: "Business rules", subtitle: "Every rule the application enforces, where it lives, and what its tests proved", icon: "shield",
  async render(root) {
    const data = await api("/platform/rules");
    const rules = data.rules;
    const tested = rules.filter((r) => r.tests.total > 0);
    const kinds = ["all", ...new Set(rules.map((r) => r.kind))];
    let kind = "all";
    let q = "";
    const grid = h("div", { class: "rule-grid" });
    const paint = () => {
      const shown = rules.filter((r) => (kind === "all" || r.kind === kind) && (!q || `${r.id} ${r.title} ${r.statement} ${r.source}`.toLowerCase().includes(q)));
      grid.replaceChildren(...(shown.length ? shown.map((r, i) => h("div", { class: "card rule-card", style: { animationDelay: `${Math.min(i * 30, 600)}ms` } },
        h("div", { class: "between" }, h("code", { class: "rule-id" }, r.id), ui.badge(r.kind, KIND_TONE[r.kind])),
        h("strong", {}, r.title),
        r.statement && r.statement !== r.title ? h("p", { class: "muted", style: { margin: 0 } }, r.statement) : null,
        h("div", { class: "rule-meta faint" }, r.source ? h("span", {}, ui.icon("file"), r.source) : null, r.where ? h("span", { class: "mono" }, ui.icon("server"), r.where.replace(/^app\./, "")) : null),
        r.tests.total ? h("div", { class: "row", "data-tip": r.tests.names.join("\n") }, h("span", { class: "faint" }, `${r.tests.passed}/${r.tests.total} tests`), ui.meter(r.tests.passed, r.tests.total, { tone: r.tests.passed === r.tests.total ? "ok" : "down", hideLabel: true }))
          : h("span", { class: "faint" }, r.id.startsWith("WF-") ? "Enforced by the platform" : "No tests"),
        h("div", { class: "rule-counts" }, h("span", {}, h("b", {}, ui.number(r.calls)), " checks"), h("span", { class: r.violations ? "refused" : "" }, h("b", {}, ui.number(r.violations)), " refusals")),
      )) : [ui.empty("No rules match", "Try another kind or search.")]));
    };
    paint();
    root.append(
      ui.stats([
        { label: "Rules", value: rules.length, icon: "shield" },
        { label: "Rules with tests", value: tested.length, icon: "check-circle", tone: tested.length ? "ok" : "warn" },
        { label: "Tests passing", value: data.tests.total ? `${data.tests.passed}/${data.tests.total}` : "—", icon: "activity", tone: data.tests.failed ? "down" : "ok",
          hint: data.tests.ran_at ? `ran ${ui.timeAgo(data.tests.ran_at)}` : undefined },
        { label: "Refusals since start", value: rules.reduce((a, r) => a + r.violations, 0), icon: "flag" },
      ]),
      ui.section("Rules", { icon: "shield", right: h("div", { class: "row" },
        ui.search({ placeholder: "Search rules…", oninput: (e) => { q = e.target.value.trim().toLowerCase(); paint(); } }),
        ui.segmented({ options: kinds.map((k) => ({ value: k, label: ui.label(k) })), value: "all", onchange: (v) => { kind = v; paint(); } })) }, grid),
      ...data.workflows.map((w) => ui.section(`${w.title} lifecycle`, { icon: "layers" }, flowDiagram(w, data.roles))),
      ui.section("Roles and permissions", { icon: "users" }, ui.table({
        columns: [{ key: "label", label: "Role" }, { key: "key", label: "Key", render: (r) => h("code", {}, r.key) },
          { key: "perms", label: "May", render: (r) => h("div", { class: "perm-list" }, (data.permissions[r.key] || []).map((p) => h("code", {}, p))) }],
        rows: Object.entries(data.roles).map(([key, label]) => ({ key, label })), sortable: false,
      })),
    );
  },
};

const CONNECTOR_TONE = { live: "ok", sandbox: "info", off: undefined };

function sandboxView(connector, o) {
  if (connector === "email") {
    const frame = h("iframe", { class: "mail-frame", sandbox: "", title: o.subject || "E-mail" });
    frame.srcdoc = o.html || `<pre style="font:14px/1.5 system-ui;white-space:pre-wrap">${(o.text || "").replace(/[<&]/g, (c) => ({ "<": "&lt;", "&": "&amp;" }[c]))}</pre>`;
    return h("div", { class: "stack" }, ui.kv([{ label: "From", value: o.from }, { label: "To", value: o.to }, { label: "Cc", value: o.cc }, { label: "Subject", value: o.subject },
      { label: "Relayed to a mail catcher", value: o.relayed ? "yes" : "no" }]), frame);
  }
  if (connector === "slack" || connector === "teams") {
    return h("div", { class: `chat-preview ${connector}` },
      h("div", { class: "chat-head" }, h("span", { class: "chat-logo" }, connector === "slack" ? "#" : "T"), h("strong", {}, o.channel || (connector === "teams" ? "Teams channel" : "#general"))),
      h("div", { class: "chat-card" }, h("strong", {}, o.title), o.text ? h("p", {}, o.text) : null,
        (o.facts || []).length ? h("dl", { class: "chat-facts" }, o.facts.flatMap(([k, v]) => [h("dt", {}, k), h("dd", {}, v)])) : null,
        o.link ? h("span", { class: "chat-link" }, o.link[0]) : null));
  }
  const rows = Object.entries(o).filter(([k, v]) => typeof v !== "object" || v === null).map(([k, v]) => ({ label: ui.label(k), value: String(v ?? "") }));
  const lists = ["comments", "work_notes"].filter((k) => (o[k] || []).length);
  return h("div", { class: "stack" }, ui.kv(rows), ...lists.map((k) => ui.section(ui.label(k), { icon: "list" }, ui.timeline(o[k].map((c) => ({ title: c, icon: "edit" }))))));
}

function objectTitle(connector, o) {
  return o.summary || o.short_description || o.name || o.subject || o.title || o.key || o.number || "Record";
}

const integrationsScreen = {
  title: "Integrations", subtitle: "The systems this application talks to, and everything it has sent", icon: "link",
  async render(root, { params, actions }) {
    const manage = can("integrations:manage");
    const [list, events] = await Promise.all([api("/platform/integrations"), api("/platform/integrations/events?limit=800")]);
    const reload = async () => { root.replaceChildren(); actions.replaceChildren(); await integrationsScreen.render(root, { params: [], actions }); };
    const settings = (c) => ui.drawer({
      title: c.title, subtitle: `${c.category} · ${c.mode}`, icon: "settings",
      content: h("div", { class: "stack" },
        h("p", { style: { margin: 0 } }, c.description),
        c.mode === "sandbox" ? ui.notice(`Running in its sandbox: nothing leaves the application, and every call is kept in the outbox below. Set ${c.missing.join(", ")} in the deployment's environment to make it live.`, "info")
          : c.mode === "live" ? ui.notice("Live: calls go to the real system.", "ok") : ui.notice("Switched off.", "warn"),
        h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Setting"), h("th", {}, "Variable"), h("th", {}, "Value"))),
          h("tbody", {}, c.settings.map((s) => h("tr", {}, h("td", {}, s.label, s.required ? h("span", { class: "faint" }, " · required") : null, s.help ? h("div", { class: "faint" }, s.help) : null),
            h("td", { class: "mono" }, s.env), h("td", {}, s.set ? (s.secret ? "•••" : s.value) : h("span", { class: "faint" }, "not set"))))))),
        ui.section("Operations", { icon: "list" }, ui.kv(Object.entries(c.operations).map(([k, v]) => ({ label: h("code", {}, k), value: v })))),
        c.vendor_url ? h("a", { href: c.vendor_url, target: "_blank", rel: "noopener" }, "Vendor API reference") : null),
      actions: manage ? (close) => [ui.button("Send a test", { icon: "bolt", onclick: async () => {
        try {
          const r = await api(`/platform/integrations/${c.name}/test`, { method: "POST" });
          ui.toast(r.ok ? `${c.title}: ${r.key || "sent"} (${r.mode})` : `${c.title}: ${r.error}`, r.ok ? "ok" : "down");
          close(); await reload();
        } catch (err) { ui.toast(errorText(err), "down"); }
      } })] : [],
    });
    const cards = h("div", { class: "connector-grid" }, list.map((c, i) => h("button", {
      type: "button", class: `card connector-card mode-${c.mode}`, style: { animationDelay: `${i * 50}ms` }, onclick: () => settings(c) },
    h("div", { class: "between" }, h("span", { class: `connector-logo logo-${c.name}` }, c.title.slice(0, 1)), ui.badge(c.mode, CONNECTOR_TONE[c.mode])),
    h("strong", {}, c.title), h("span", { class: "faint" }, c.category),
    h("div", { class: "connector-counts" },
      h("span", {}, h("b", {}, ui.number(c.counts.sent || 0)), " sent"),
      h("span", { class: (c.counts.failed || c.counts.deferred) ? "refused" : "" }, h("b", {}, ui.number((c.counts.failed || 0) + (c.counts.deferred || 0))), " failed"),
      c.last_at ? h("span", { class: "faint" }, ui.timeAgo(c.last_at)) : h("span", { class: "faint" }, "unused")))));
    const eventDrawer = (e) => ({
      title: `${ui.label(e.connector)} · ${ui.label(e.operation)}`, subtitle: `${e.status} · ${e.mode} · ${ui.dateTime(e.created_at)}`, icon: "link",
      content: h("div", { class: "stack" },
        e.error ? ui.notice(e.error, "down") : null,
        ui.kv([{ label: "Remote key", value: e.remote_key }, { label: "Record", value: e.ref }, { label: "By", value: e.actor },
          { label: "Attempts", value: String(e.attempts) }, { label: "Retry at", value: e.retry_at ? ui.dateTime(e.retry_at) : "" },
          { label: "Replaced by", value: e.superseded_by ? `event ${e.superseded_by}` : "" }]),
        ui.section("Request", { icon: "upload" }, json(e.request)), ui.section("Response", { icon: "download" }, json(e.response))),
      actions: manage && ["failed", "deferred"].includes(e.status) ? (close) => [ui.button("Retry now", { icon: "refresh", onclick: async () => {
        try { const r = await api(`/platform/integrations/events/${e.id}/retry`, { method: "POST" }); ui.toast(r.ok ? "Sent" : r.error, r.ok ? "ok" : "down"); close(); await reload(); }
        catch (err) { ui.toast(errorText(err), "down"); }
      } })] : [],
    });
    const sandboxBox = h("div", { class: "stack" });
    const showSandbox = async (name, openKey) => {
      sandboxBox.replaceChildren(ui.skeleton("rows"));
      const objects = await api(`/platform/integrations/${name}/objects`);
      const rows = objects.map((o) => ({ ...o, __title: objectTitle(name, o), __key: o.key || o.number || o.id }));
      const open = (o) => ui.drawer({ title: `${o.__key}`, subtitle: o.__title, icon: "link", content: sandboxView(name, o) });
      sandboxBox.replaceChildren(rows.length ? ui.table({
        columns: [{ key: "__key", label: "Key", render: (o) => h("code", {}, o.__key) }, { key: "__title", label: "Title" },
          { key: "status", label: "State", render: (o) => o.status || o.state ? ui.badge(o.status || o.state) : "" }],
        rows, search: true, onRow: open, pageSize: 20,
      }) : ui.empty(`Nothing in the ${ui.label(name)} sandbox yet`, "Calls made while the connector is in sandbox mode are kept here, with their state."));
      if (openKey) { const hit = rows.find((o) => String(o.__key) === openKey); if (hit) open(hit); }
    };
    const sandboxed = list.filter((c) => c.mode !== "live").map((c) => c.name);
    root.append(
      ui.stats([
        { label: "Live connectors", value: list.filter((c) => c.mode === "live").length, icon: "bolt", tone: "ok" },
        { label: "In sandbox", value: list.filter((c) => c.mode === "sandbox").length, icon: "shield" },
        { label: "Calls recorded", value: events.length, icon: "activity", spark: [] },
        { label: "Failed or waiting", value: events.filter((e) => ["failed", "deferred"].includes(e.status)).length, icon: "alert",
          tone: events.some((e) => ["failed", "deferred"].includes(e.status)) ? "down" : undefined },
      ]),
      cards,
      ui.tabs([
        { label: "Outbox", icon: "inbox", badge: events.length, content: () => ui.table({
          columns: [
            { key: "created_at", label: "When", format: "ago" },
            { key: "connector", label: "System", render: (e) => h("span", { class: "row", style: { gap: "8px" } }, h("span", { class: `connector-logo sm logo-${e.connector}` }, e.connector.slice(0, 1).toUpperCase()), ui.label(e.connector)) },
            { key: "operation", label: "Operation", render: (e) => ui.label(e.operation) },
            { key: "status", label: "Status", badge: true },
            { key: "mode", label: "Mode", render: (e) => ui.badge(e.mode, CONNECTOR_TONE[e.mode]) },
            { key: "remote_key", label: "Key", render: (e) => e.remote_key ? h("code", {}, e.remote_key) : "" },
            { key: "actor", label: "By" },
          ],
          rows: events, search: true, pageSize: 25, filters: [{ key: "connector" }, { key: "status" }, { key: "mode" }], drawer: eventDrawer,
          empty: { title: "Nothing sent yet", hint: "Every call to an outside system appears here, live or sandbox." },
        }) },
        { label: "Sandbox records", icon: "layers", content: () => {
          const names = sandboxed.length ? sandboxed : list.map((c) => c.name);
          // Open on the connector used most recently, so the tab never opens on an empty list.
          const recent = (events.find((e) => e.mode === "sandbox" && names.includes(e.connector)) || {}).connector || names[0];
          const pick = ui.segmented({ options: names.map((n) => ({ value: n, label: ui.label(n) })), value: recent, onchange: (v) => showSandbox(v) });
          showSandbox(recent);
          return h("div", { class: "stack" }, pick, sandboxBox);
        } },
      ], { value: params && params[0] ? 1 : 0 }),
    );
    if (params && params[0]) showSandbox(params[0], params[1]);
  },
};

/* ---------------------------------------------------------------- the guide */

const SVGNS = "http://www.w3.org/2000/svg";
function sv(tag, attrs, ...children) {
  const el = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
    else el.setAttribute(k, String(v));
  }
  for (const c of children.flat(Infinity)) if (c !== undefined && c !== null && c !== false) el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return el;
}

/** Words on at most `lines` lines of about `width` characters. */
function wrapped(text, width, lines = 2) {
  const out = [];
  let line = "";
  for (const word of String(text || "").split(/\s+/).filter(Boolean)) {
    if (line && (line + " " + word).length > width) { out.push(line); line = word; } else line = line ? `${line} ${word}` : word;
  }
  if (line) out.push(line);
  if (out.length > lines) { out.length = lines; out[lines - 1] = `${out[lines - 1].replace(/[\s,;:.]+\S*$/, "")}…`; }
  return out;
}

/** The screens this person can open, each with which of a library's screens it is and what it is for. */
async function knownScreens(guide) {
  let registry = [];
  try { registry = (await import("./screens/index.js")).default || []; } catch { registry = []; }
  const recorded = Object.fromEntries((guide.screens || []).map((s) => [s.id, s]));
  const stories = Object.fromEntries((guide.stories || []).map((s) => [s.id, s]));
  const real = registry.filter((r) => r && r.module && typeof r.module.render === "function");
  const shown = real.some((r) => !r.example) ? real.filter((r) => !r.example) : real;
  return shown.filter((r) => mayOpen(r.id)).map((r) => {
    const source = String(r.module.render);
    let uses = (recorded[r.id] || {}).uses || "";
    for (const u of guide.uses || []) {
      let found = null;
      try { found = new RegExp(u.pattern).exec(source); } catch { found = null; }
      if (found) { uses = `${u.kind}:${found[1]}`; break; }
    }
    const story = stories[r.module.story] || {};
    return { id: r.id, title: r.module.title || ui.label(r.id), icon: r.module.icon || ui.guessIcon(r.module.title || r.id), story: r.module.story || "",
      uses, narrative: story.narrative || "",
      what: (guide.library_screens || {})[uses] || story.narrative || r.module.subtitle || (recorded[r.id] || {}).subtitle || "" };
  });
}

const screensOf = (step, screens) => screens.filter((s) => s.uses && (step.uses || []).includes(s.uses));

/** The process as lanes: a lane for each role, a box for each step, in the order the work is done. */
function processDiagram(proc, screens, mine, onPick) {
  const steps = proc.steps || [];
  const lanes = [...new Set(steps.map((s) => (s.role_labels || [])[0] || "Anyone"))];
  const LABEL = 132, COL = 148, LANE = 92, BOX_W = 128, BOX_H = 58, TOP = 10;
  const width = LABEL + steps.length * COL + 12, height = TOP + lanes.length * LANE + 8;
  const svg = sv("svg", { class: "guide-flow", viewBox: `0 0 ${width} ${height}`, role: "img",
    "aria-label": `${proc.title}: ${steps.map((s, i) => `${i + 1}. ${s.title}, by ${(s.role_labels || ["anyone"]).join(" or ")}`).join("; ")}` });
  svg.style.minWidth = `${Math.round(width * 0.78)}px`;
  svg.append(sv("defs", {}, sv("marker", { id: "guide-arrow", viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" },
    sv("path", { d: "M0 0 L10 5 L0 10 z", class: "guide-arrowhead" }))));
  lanes.forEach((lane, i) => {
    const y = TOP + i * LANE;
    const yours = mine.has(lane);
    svg.append(sv("rect", { x: 0, y, width, height: LANE - 6, rx: 10, class: `guide-lane${yours ? " yours" : ""}` }));
    wrapped(lane, 17, 2).forEach((line, k, all) => svg.append(sv("text", { x: 14, y: y + (LANE - 6) / 2 + (k - (all.length - 1) / 2) * 15 + 4, class: "guide-lane-label" }, line)));
    if (yours) svg.append(sv("text", { x: 14, y: y + LANE - 16, class: "guide-you" }, "you"));
  });
  const at = steps.map((s, i) => {
    const lane = lanes.indexOf((s.role_labels || [])[0] || "Anyone");
    return { x: LABEL + i * COL + (COL - BOX_W) / 2, y: TOP + lane * LANE + (LANE - 6 - BOX_H) / 2 };
  });
  for (let i = 0; i + 1 < steps.length; i += 1) {
    const a = at[i], b = at[i + 1];
    const x1 = a.x + BOX_W, y1 = a.y + BOX_H / 2, x2 = b.x, y2 = b.y + BOX_H / 2, mid = (x1 + x2) / 2;
    svg.append(sv("path", { d: y1 === y2 ? `M${x1} ${y1} H${x2 - 2}` : `M${x1} ${y1} H${mid} V${y2} H${x2 - 2}`, class: "guide-link", "marker-end": "url(#guide-arrow)" }));
  }
  steps.forEach((s, i) => {
    const { x, y } = at[i];
    const has = screensOf(s, screens).length > 0;
    const g = sv("g", { class: `guide-step${s.decides ? " decides" : ""}${has ? "" : " absent"}`, tabindex: 0, role: "link",
      "aria-label": `Step ${i + 1}: ${s.title}`, onclick: () => onPick(s),
      onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onPick(s); } } });
    g.append(sv("rect", { x, y, width: BOX_W, height: BOX_H, rx: 10 }));
    g.append(sv("circle", { cx: x + 2, cy: y + 2, r: 11, class: "guide-no" }), sv("text", { x: x + 2, y: y + 6, class: "guide-no-text", "text-anchor": "middle" }, String(i + 1)));
    wrapped(s.title, 19, 2).forEach((line, k, all) => g.append(sv("text", { x: x + BOX_W / 2, y: y + BOX_H / 2 + (k - (all.length - 1) / 2) * 15 + 4.5,
      "text-anchor": "middle", class: "guide-step-text" }, line)));
    svg.append(g);
  });
  return h("div", { class: "guide-flow-wrap" }, svg);
}

function chips(items, cls = "role-chip") {
  return h("span", { class: "row guide-chips" }, items.map((t) => h("span", { class: cls }, t)));
}

/** A record's states in order, and every move between them. */
function lifecycleView(flow, labels) {
  const states = flow.states || [];
  const name = Object.fromEntries(states.map((s) => [s.key, s.label]));
  const chain = h("ol", { class: "wf-steps guide-states" }, states.map((s) => h("li", {
    class: `${flow.initial === s.key ? "now" : ""}${(flow.final || []).includes(s.key) ? " final" : ""}`,
    "data-tip": s.sla_hours ? `May wait ${s.sla_hours} hours` : null }, h("span", { class: "wf-dot" }), h("span", {}, s.label))));
  const who = (keys) => (keys || []).map((k) => labels[k] || ui.label(k)).join(", ");
  const rows = (flow.transitions || []).map((t) => h("tr", {},
    h("td", {}, h("strong", {}, t.label)),
    h("td", {}, (t.from || []).map((s) => name[s] || ui.label(s)).join(", ")),
    h("td", {}, t.pending && !(t.from || []).includes(t.pending) ? `${name[t.pending] || ui.label(t.pending)}, then ${name[t.to] || ui.label(t.to)}` : (name[t.to] || ui.label(t.to))),
    h("td", {}, who(t.roles) || h("span", { class: "faint" }, "—")),
    h("td", {}, (t.approvers || []).length ? who(t.approvers) : h("span", { class: "faint" }, "—")),
    h("td", {}, t.rule ? h("code", { class: "rule-id" }, t.rule) : h("span", { class: "faint" }, "—"))));
  return h("div", { class: "stack" }, chain,
    h("div", { class: "table-wrap" }, h("table", { class: "guide-moves" },
      h("thead", {}, h("tr", {}, ["Move", "From", "To", "Who", "Approved by", "Rule"].map((t) => h("th", {}, t)))),
      h("tbody", {}, rows))));
}

const guideScreen = {
  title: "Guide", subtitle: "What this application is for, who does what, and how a record moves", icon: "info", group: "Help",
  async render(root, { actions, navigate }) {
    const guide = await api("/platform/guide");
    const screens = await knownScreens(guide);
    const labels = Object.fromEntries((guide.roles || []).map((r) => [r.key, r.label]));
    const myRoles = (me.roles || []).filter((r) => r !== "admin");
    const myLabels = new Set(myRoles.map((r) => labels[r] || ui.label(r)));
    const isAdmin = (me.roles || []).includes("admin");
    const go = (id) => { if (typeof navigate === "function") navigate(`#/${id}`); else location.hash = `#/${id}`; };
    const open = (s) => ui.button(s.title, { tone: "secondary", size: "sm", icon: s.icon || "arrow-right", onclick: () => go(s.id) });

    // Which screens are whose: the ones a step of the process names for a role, the ones the policy
    // keeps to a role, and the ones a story was written for ("As a budget holder, I want…").
    const screensByRole = Object.fromEntries((guide.roles || []).map((r) => [r.key, new Set(r.screens || [])]));
    for (const proc of guide.processes || []) {
      for (const step of [...(proc.steps || []), ...(proc.alongside || [])]) {
        for (const s of screensOf(step, screens)) for (const key of [...(step.roles || []), ...(step.decides ? [] : [])]) if (screensByRole[key]) screensByRole[key].add(s.id);
      }
    }
    for (const s of screens) {
      const first = String(s.narrative || "").split(",")[0].toLowerCase();
      for (const r of guide.roles || []) if (first && first.includes(String(r.label).toLowerCase())) screensByRole[r.key].add(s.id);
    }
    const byId = Object.fromEntries(screens.map((s) => [s.id, s]));
    const mineScreens = [...new Set(myRoles.flatMap((r) => [...(screensByRole[r] || [])]))].map((id) => byId[id]).filter(Boolean);

    const doc = h("div", { class: "guide stack" });

    // ---- what it is for, and your part in it
    const purpose = (guide.about || {}).purpose;
    const mySteps = (guide.processes || []).flatMap((p) => (p.steps || []).map((s, i) => ({ ...s, no: i + 1 })))
      .filter((s) => (s.roles || []).some((r) => myRoles.includes(r)));
    const myMoves = (guide.roles || []).filter((r) => myRoles.includes(r.key));
    doc.append(h("section", { class: "panel guide-hero" },
      h("div", { class: "guide-hero-text" },
        h("span", { class: "nav-label", style: { padding: 0 } }, "What it is for"),
        h("h2", {}, guide.app || profile.app || "This application"),
        purpose ? h("p", {}, purpose) : h("p", { class: "muted" }, "An application built by Poiesis. This guide is written from its own roles, lifecycles, rules and screens."),
        (guide.about || {}).increment ? h("p", { class: "faint" }, guide.about.increment) : null),
      h("div", { class: "guide-me" },
        h("div", { class: "row" }, ui.avatar(me.name, { size: "lg" }), h("div", {}, h("strong", {}, me.name),
          h("div", { class: "muted" }, isAdmin ? "Administrator: may open and do everything" : [...myLabels].join(", ") || me.title || ""))),
        mySteps.length ? h("div", {}, h("div", { class: "guide-me-h" }, "Your part in the process"),
          h("ul", { class: "guide-me-steps" }, mySteps.map((s) => h("li", {}, h("span", { class: "guide-no-chip" }, String(s.no)),
            h("a", { href: `#guide-step-${s.key}`, onclick: (e) => { e.preventDefault(); pick(s); } }, s.title))))) : null,
        mineScreens.length ? h("div", {}, h("div", { class: "guide-me-h" }, "Your screens"), h("div", { class: "row guide-chips" }, mineScreens.map(open))) : null,
        !mySteps.length && !mineScreens.length && !isAdmin && myMoves.every((r) => !(r.does || []).length && !(r.approves || []).length)
          ? h("p", { class: "muted", style: { margin: 0 } }, "Your role reads what the application holds; it changes nothing.") : null)));

    // ---- the process
    const cards = {};
    function pick(step) {
      const el = cards[step.key];
      if (!el) return;
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      el.classList.remove("flash");
      void el.offsetWidth;
      el.classList.add("flash");
    }
    for (const proc of guide.processes || []) {
      const steps = proc.steps || [];
      doc.append(ui.section(`The process: ${proc.title}`, { icon: "activity" },
        proc.about ? h("p", { class: "muted guide-lede" }, proc.about) : null,
        processDiagram(proc, screens, myLabels, pick),
        h("p", { class: "faint guide-key" }, h("span", { class: "guide-key-box" }), "a step ", h("span", { class: "guide-key-box decides" }), "a decision ",
          h("span", { class: "guide-key-box absent" }), "not in this application yet. Choose a step for how it is done."),
        h("div", { class: "guide-steps" }, steps.map((s, i) => {
          const where = screensOf(s, screens);
          const yours = (s.roles || []).some((r) => myRoles.includes(r));
          cards[s.key] = h("article", { class: `guide-card${yours ? " yours" : ""}${where.length || !(s.uses || []).length ? "" : " absent"}`, id: `guide-step-${s.key}` },
            h("header", {}, h("span", { class: "guide-no-chip" }, String(i + 1)), h("h3", {}, s.title), yours ? ui.badge("You", "info") : null),
            h("p", {}, s.what),
            h("div", { class: "guide-who" }, h("span", { class: "faint" }, s.decides ? "Decided by" : "Done by"), chips(s.role_labels && s.role_labels.length ? s.role_labels : ["Anyone"]),
              (s.approver_labels || []).length ? [h("span", { class: "faint" }, "approved by"), chips(s.approver_labels), s.approver_labels.length > 1 ? h("span", { class: "faint" }, "by the amount") : null] : null),
            (s.how || []).length ? h("ol", { class: "guide-how" }, s.how.map((line) => h("li", {}, line))) : null,
            s.leaves ? h("p", { class: "guide-leaves" }, ui.icon("arrow-right"), h("span", {}, s.leaves)) : null,
            h("footer", {},
              where.length ? h("span", { class: "row guide-chips" }, where.map(open))
                : h("span", { class: "faint" }, "This application has no screen for this step yet."),
              (s.rules || []).length ? h("span", { class: "row guide-rules" }, s.rules.map((r) => h("code", { class: "rule-id" }, r))) : null));
          return cards[s.key];
        })),
        (proc.alongside || []).length ? h("div", { class: "guide-beside" }, h("div", { class: "nav-label", style: { padding: 0 } }, "Alongside"),
          proc.alongside.map((a) => h("div", { class: "guide-beside-row" }, h("strong", {}, a.title), h("span", {}, a.what),
            h("span", { class: "row guide-chips" }, screensOf(a, screens).map(open))))) : null));
    }

    // ---- who does what
    const people = (guide.roles || []).filter((r) => (r.people || []).length || (r.does || []).length || (r.approves || []).length);
    doc.append(ui.section("Who does what", { icon: "users" },
      h("p", { class: "muted guide-lede" }, "Each person holds a role. A role sees the screens below and may make the moves listed; every move is recorded in the audit trail."),
      h("div", { class: "guide-roles" }, people.map((r) => {
        const theirs = [...(screensByRole[r.key] || [])].map((id) => byId[id]).filter(Boolean);
        const moves = {};
        for (const m of r.does || []) (moves[m.workflow] ||= []).push(m.move);
        const approves = [...new Set((r.approves || []).map((m) => `${m.move} (${m.workflow.toLowerCase()})`))];
        const may = r.may || {};
        return h("article", { class: `guide-role${myRoles.includes(r.key) ? " yours" : ""}` },
          h("header", {}, (r.people || []).length ? ui.avatarGroup(r.people.map((p) => p.full_name), 3) : ui.avatar(r.label),
            h("div", {}, h("h3", {}, r.label), h("span", { class: "faint" }, (r.people || []).map((p) => [p.full_name, p.title].filter(Boolean).join(", ")).join(" · ") || "Nobody holds it yet")),
            myRoles.includes(r.key) ? ui.badge("You", "info") : null),
          theirs.length ? h("div", { class: "guide-line" }, h("span", { class: "faint" }, "Works on"), h("span", { class: "row guide-chips" }, theirs.map(open))) : null,
          Object.keys(moves).length ? h("div", { class: "guide-line" }, h("span", { class: "faint" }, "Does"),
            h("ul", {}, Object.entries(moves).map(([flow, list]) => h("li", {}, h("b", {}, flow), ": ", [...new Set(list)].join(", "))))) : null,
          approves.length ? h("div", { class: "guide-line" }, h("span", { class: "faint" }, "Approves"), h("span", {}, approves.join("; "))) : null,
          h("div", { class: "guide-line" }, h("span", { class: "faint" }, "Reads"),
            h("span", {}, typeof may.reads === "string" ? ui.label(may.reads) : ((may.reads || []).join(", ") || "Nothing"),
              (may.oversight || []).length ? `; and ${may.oversight.join(", ")}` : "")));
      }))));

    // ---- the screens
    if (screens.length) {
      doc.append(ui.section("The screens", { icon: "grid" },
        h("div", { class: "guide-screens" }, [...screens, ...(guide.platform || []).filter((p) => state_has(p.id)).map((p) => ({ ...p, platform: true }))].map((s) =>
          h("button", { type: "button", class: "guide-screen", onclick: () => go(s.id) },
            h("span", { class: "stat-icon" }, ui.icon(s.icon || ui.guessIcon(s.title))),
            h("span", {}, h("strong", {}, s.title), h("span", { class: "muted" }, s.what || (s.platform ? "" : "A screen of this application."))))))));
    }

    // ---- how a record moves
    if ((guide.lifecycles || []).length) {
      doc.append(ui.section("How a record moves", { icon: "layers" },
        h("p", { class: "muted guide-lede" }, "A record's status changes only through the moves below, by the people whose role allows them. Where a move needs an approval, the record waits until someone holding the approving role, never the person who asked, decides."),
        ui.tabs(guide.lifecycles.map((f) => ({ label: f.title, content: () => lifecycleView(f, labels) })))));
    }

    // ---- the numbers, and the rules
    if ((guide.numbers || []).length) {
      doc.append(ui.section("The numbers this organisation works to", { icon: "flag" },
        h("dl", { class: "guide-numbers" }, guide.numbers.map((n) => [h("dt", {}, n.label, n.rule ? h("code", { class: "rule-id" }, n.rule) : null), h("dd", {}, n.value)]))));
    }
    const rules = guide.rules || [];
    if (rules.length) {
      doc.append(ui.section(`The rules (${rules.length})`, { icon: "shield", right: can("rules:read") ? ui.button("All rules, with their tests", { tone: "secondary", size: "sm", icon: "arrow-right", onclick: () => go("business_rules") }) : null },
        h("div", { class: "guide-rulelist" }, rules.slice(0, 60).map((r) => h("div", { title: r.statement || null }, h("code", { class: "rule-id" }, r.id), h("span", {}, r.title))))));
    }

    root.replaceChildren(doc);
    if (actions) {
      actions.append(
        ui.button("Print", { tone: "secondary", icon: "file", onclick: () => window.print() }),
        ui.button("Download", { icon: "download", onclick: async () => {
          try {
            const text = await api("/platform/guide.md");
            const a = h("a", { href: URL.createObjectURL(new Blob([typeof text === "string" ? text : JSON.stringify(text, null, 2)], { type: "text/markdown" })), download: "USER-GUIDE.md" });
            document.body.append(a); a.click(); a.remove();
            ui.toast("The guide, as a document", "ok");
          } catch (err) { ui.toast(errorText(err), "down"); }
        } }));
    }
  },
};

function state_has(id) {
  return screens().some((s) => s.id === id);
}

/** The platform's own screens, for this person. */
export function screens() {
  const out = [{ id: "guide", module: guideScreen, group: "Help" }, { id: "approvals", module: approvalsScreen }];
  if (can("audit:read")) out.push({ id: "audit_trail", module: auditScreen });
  if (can("rules:read")) out.push({ id: "business_rules", module: rulesScreen });
  if (can("integrations:read")) out.push({ id: "integrations", module: integrationsScreen });
  return out;
}
