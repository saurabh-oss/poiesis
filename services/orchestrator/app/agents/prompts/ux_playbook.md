
# UX PLAYBOOK — how a screen earns the "wow"

The people who open this application decide in ten seconds whether it is a real product.
They should see it full of their data, alive with motion, and answering every click. The
shell and the UI kit (`ui`, passed to `render`) already do the hard parts — themes, motion,
skeleton loading, a command palette, toasts, drawers, dialogs, animated charts. Your job is
to **compose them into the right shape for the story**. `screens/example.js` shows every
recipe below working together; copy its structure.

## The bar every screen clears

1. **Opens full.** `render()` loads its data first (in parallel with `Promise.all`) and draws
   real rows, numbers and charts. No screen opens on an empty form or a sentence.
2. **Leads with the headline.** A `ui.hero` (dashboards) or a `ui.stats` row (every other
   list screen) comes first: 3–5 numbers that matter, with icons, a `delta` or a `spark` trend
   where the data allows.
3. **Shows, not tells.** Anything countable by category gets a `ui.donut` or `ui.bars`;
   anything over time gets `ui.line` or `ui.timeseries`; any percentage gets `ui.ring` or
   `ui.meter`. A number in a sentence is a missed chart.
4. **Every row opens something.** Tables pass `drawer: (row) => ({ … })` so a click slides the
   whole record in from the right, with its related rows and its actions. Cards and bars
   take `onClick`/`onCard`.
5. **Every action answers.** Create and edit open `ui.formModal`; destructive steps ask
   `ui.confirm`; success says so with `ui.toast(…, "ok")` and the screen redraws with the new
   state. A genuinely good outcome (resolved, approved, done) adds `ui.celebrate()`.
6. **Reads like a product, not a database.** People, not ids: `ui.person(name)`. Words, not
   snake_case: `ui.badge(status)` and `ui.label(key)`. Time as people say it:
   `ui.timeAgo(iso)`, with `ui.dateTime` in the drawer. Money as money: `ui.money(n)`.
   Never show `null`, `undefined`, `NaN` or a raw ISO timestamp.

## The kit, at a glance

| For | Call |
|---|---|
| Dashboard banner | `ui.hero({ eyebrow, title, subtitle, stats: [{ label, value }], actions: [buttons] })` |
| Headline numbers | `ui.stats([{ label, value, icon, tone, hint, delta: 12, spark: [..], onClick }])` — values count up |
| Section with a heading | `ui.section("Title", { icon: "pie", right: node }, ...children)` |
| Two-up / three-up layout | `h("div", { class: "grid-2" }, a, b)`, `grid-3`; list + side panel: `ui.split([main], [side])` |
| Tabs | `ui.tabs([{ label, icon, badge, content: () => node }])` — content built when first opened |
| Data table | `ui.table({ columns, rows, search, keyboard, pageSize, sort, filters: [{ key }], exportable: "name", drawer, empty })` |
| Column shortcuts | `{ key, label, badge: true }`, `format: "ago" \| "date" \| "money" \| "number"`, `align: "right"`, `render: (row) => node` |
| Status board | `ui.kanban({ columns: [{ key, label, tone }], items, field: "status", card: (x) => nodes, onMove: async (x, to) => …, onCard })` |
| History | `ui.timeline([{ title, time, body, tone, icon }])` |
| Record header | `ui.profile({ name, subtitle, badges: [..], icon?, actions: [..] })` |
| Details | `ui.kv([{ label, value }])` |
| Charts | `ui.donut(items, { center, sub, onClick })`, `ui.bars(items, { onClick })`, `ui.line(points)`, `ui.timeseries(points)`, `ui.sparkline(values)`, `ui.ring(pct, { label })`, `ui.meter(value, max, { auto: true })` |
| Slide-over | `ui.drawer({ title, subtitle, icon, content: [nodes] \| async () => node, actions: (close) => [buttons] })` |
| Dialogs | `await ui.formModal({ title, fields, submit, onsubmit })`, `await ui.confirm(text, { danger: true })`, `ui.modal({ title, content, actions })` |
| Controls | `ui.button(text, { icon, tone, onclick, tip })`, `ui.segmented({ options, onchange })`, `ui.chips({ options, multi, onchange })`, `ui.search({ oninput })`, `ui.select({ options, value, onchange })` |
| Feedback | `ui.toast(text, "ok" \| "warn" \| "down")`, `ui.celebrate(el?)`, `ui.notice(text, kind)`, `ui.empty(title, hint, { action })` |
| People & text | `ui.person(name, sub)`, `ui.avatar(name)`, `ui.avatarGroup(names)`, `ui.badge(text)`, `ui.label(key)`, `ui.icon(name)` |
| Formatting | `ui.timeAgo`, `ui.date`, `ui.dateTime`, `ui.number`, `ui.money`, `ui.percent` |

Icons (`icon:` anywhere, or `ui.icon(name)`): dashboard, users, user, box, laptop, phone,
monitor, key, wrench, shield, alert, check, check-circle, plus, search, filter, download,
upload, calendar, clock, chart, pie, trend-up, trend-down, inbox, tag, pin, building, mail,
settings, refresh, arrow-right, eye, edit, trash, star, bolt, sparkles, list, grid, kanban,
history, link, file, dollar, activity, layers, ticket, flag, bell, info, truck, cart, globe,
server, database, logout. A screen module may declare `icon: "key"` for its menu entry.

## Recipes — pick the one that matches the story

**Dashboard / overview / metrics** ("see", "monitor", "at a glance", "weekly review")
```js
const [assets, repairs] = await Promise.all([api("/assets?limit=2000"), api("/repairs?limit=2000")]);
root.append(
  ui.hero({ eyebrow: "IT estate", title: `${assets.length} assets under management`, subtitle: "…",
            stats: [{ label: "Assigned", value: String(assigned) }, { label: "Utilisation", value: `${pct}%` }] }),
  ui.stats([{ label: "In repair", value: inRepair, icon: "wrench", tone: "warn", spark: repairsPerWeek }, …]),
  h("div", { class: "grid-2" },
    ui.section("By category", { icon: "pie" }, ui.donut(countBy(assets, "category"), { sub: "assets" })),
    ui.section("Assignments per week", { icon: "activity" }, ui.line(perWeek))),
  ui.section("Needs attention", { icon: "alert" }, ui.table({ columns, rows: urgent, drawer: details })));
```

**Register / list** ("list", "browse", "search", "filter", "view all")
`ui.stats` (counts per status) → `ui.section` with `ui.table({ search: true, keyboard: true,
filters: [{ key: "status" }], exportable: "assets", drawer: details })` → header action
`actions.append(ui.button("New asset", { icon: "plus", onclick: create }))` where `create`
is a `ui.formModal`. The drawer shows `ui.profile`, `ui.kv`, a `ui.timeline` of the record's
history, related rows in a small `ui.table`, and `actions` for what can be done next.

**Detail** (a screen for one record — it takes `params[0]`)
With an id: `ui.profile` + `ui.tabs([{ label: "Overview", content: kv }, { label: "History",
content: timeline }, { label: "Related", content: table }])`. **Without an id** (it is opened
from the menu): show the list to choose from — `ui.table({ rows, onRow: (r) =>
navigate(`#/this_screen/${r.id}`) })` — never a sentence asking for an id.

**Workflow / status** ("move", "progress", "resolve", "approve", "assign", "triage")
`ui.stats` per status → `ui.tabs([{ label: "Board", content: ui.kanban({ …, onMove: PATCH }) },
{ label: "Table", content: ui.table({ …, filters: [{ key: "status" }], drawer }) }])`. Moving a
card PATCHes the record; reaching the final state celebrates.

**Assignment** ("assign X to Y", "check out", "hand over")
A table of what can be assigned (filtered to the available ones), each row's drawer holding a
`ui.form` with a `select` of people (`options: people.map((p) => ({ value: p.id, label:
p.name }))`) → PATCH → toast → redraw. Show the assignee as `ui.person` everywhere.

**Utilisation / capacity** ("seats", "workload", "usage", "coverage")
A `ui.bars` or a table whose column renders `ui.meter(used, total, { auto: true })`, sorted by
the tightest first; a `ui.ring` of the overall percentage in the header row.

## Joining related data — show names, never ids

Load the related tables once and join in the screen:
```js
const [seats, licences, people] = await Promise.all([api("/license-seats?limit=5000"), api("/licenses"), api("/employees?limit=5000")]);
const byId = (rows) => Object.fromEntries(rows.map((r) => [r.id, r]));
const L = byId(licences), P = byId(people);
const rows = seats.map((s) => ({ ...s, licence: L[s.license_id]?.name, holder: P[s.employee_id]?.full_name }));
```
Count per parent the same way (`seats.filter((s) => s.license_id === l.id).length`). Ask the
generic API for enough rows (`?limit=5000`) when you aggregate; its default is 500.

## Never

Hand-draw a `<table>`, chart, badge or dialog when the kit has one. Put a form on the page
where a `formModal` from a header button belongs. Show a bare id, snake_case, `null` or an
ISO string. Leave a screen with no chart when it has anything to count. Use `alert`,
`confirm` or `prompt` (the kit has `ui.toast`, `ui.confirm`, `ui.formModal`). Write inline
styles, `<style>` tags or colours: the design system already has them. Render your own page
title, sidebar or header: the shell draws them.

## Before you return the screen, check

- It opens full on the demonstration data, with a hero or stats row first.
- There is at least one chart or meter, and the table rows open a drawer or a detail screen.
- Every action opens a dialog or drawer, gives a toast and redraws.
- Names, labels, money and times are formatted; nothing prints `null` or `undefined`.
- It uses only paths the API serves and fields those responses contain.
