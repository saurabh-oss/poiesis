/* Worked example — a reference, and read-only: edits to it are refused.
 *
 * Copy its shape into a NEW file, frontend/screens/<resource>.js, for your
 * story. Once any real screen exists the platform stops listing this one, so it
 * never appears in the delivered application.
 *
 * It shows what a finished screen feels like, using only the UI kit (`ui`):
 *   1. load the data first, in render(), so the screen opens full;
 *   2. a hero and headline numbers that count up, with trends;
 *   3. charts that draw themselves (a donut you can hover, a line with tooltips);
 *   4. tabs: a searchable, filterable table whose rows open a slide-over drawer,
 *      and a board you can drag cards across;
 *   5. every action (create, advance, delete) in a dialog or drawer, confirmed
 *      with a toast, a celebration for a real success, and the screen redrawn.
 * The shell already drew the sidebar, the page title and the subtitle.
 */
export default {
  title: "Examples",
  subtitle: "A worked reference the platform removes once real screens exist.",
  icon: "sparkles",
  story: "",
  async render(root, { api, h, actions, ui }) {
    const STATUSES = [
      { key: "open", label: "Open" },
      { key: "in_progress", label: "In progress" },
      { key: "review", label: "Review" },
      { key: "done", label: "Done", tone: "ok" },
    ];
    let items = [];

    async function load() {
      items = await api("/examples?limit=500&sort=-created_at");
    }

    // Counts per day for the last 14 days, oldest first, for the line chart.
    function perDay(rows, days) {
      const out = [];
      for (let d = days - 1; d >= 0; d--) {
        const day = new Date(Date.now() - d * 86400000);
        const key = day.toISOString().slice(0, 10);
        out.push({ label: day.toLocaleDateString(undefined, { day: "numeric", month: "short" }),
                   value: rows.filter((r) => String(r.created_at).slice(0, 10) === key).length });
      }
      return out;
    }

    async function create() {
      const saved = await ui.formModal({
        title: "New example", subtitle: "It appears on the board straight away.", icon: "plus",
        fields: [
          { name: "label", label: "Label", required: true, placeholder: "e.g. Quarterly budget review", span: "all" },
          { name: "owner", label: "Owner", placeholder: "Who is doing it" },
          { name: "status", label: "Status", type: "select", options: STATUSES.map((s) => ({ value: s.key, label: s.label })), value: "open" },
          { name: "amount", label: "Amount (USD)", type: "number", min: 0, value: 0 },
        ],
        submit: "Create example", submitIcon: "check",
        onsubmit: async (values) => { await api("/examples", { method: "POST", body: values }); return "Example created"; },
      });
      if (saved) { await load(); draw(); }
    }

    async function advance(item, to) {
      await api(`/examples/${item.id}`, { method: "PATCH", body: { status: to } });
      if (to === "done") ui.celebrate();
      ui.toast(`"${item.label}" moved to ${ui.label(to)}`, "ok");
      await load();
      draw();
    }

    async function remove(item, close) {
      if (!(await ui.confirm(`Delete "${item.label}"? This cannot be undone.`, { danger: true, confirmLabel: "Delete" }))) return;
      await api(`/examples/${item.id}`, { method: "DELETE" });
      close();
      ui.toast("Example deleted", "ok");
      await load();
      draw();
    }

    // What a row opens: the whole record, its history, and what can be done to it.
    function details(item) {
      const next = STATUSES[STATUSES.findIndex((s) => s.key === item.status) + 1];
      return {
        title: item.label,
        subtitle: `EX-${item.id} · created ${ui.timeAgo(item.created_at)}`,
        icon: "sparkles",
        content: [
          ui.profile({ name: item.owner || "Unassigned", subtitle: "Owner", badges: [ui.badge(item.status), ui.badge(ui.money(item.amount), "info")] }),
          ui.kv([
            { label: "Reference", value: h("span", { class: "mono" }, `EX-${item.id}`) },
            { label: "Amount", value: ui.money(item.amount) },
            { label: "Created", value: `${ui.dateTime(item.created_at)} · ${ui.timeAgo(item.created_at)}` },
          ]),
          ui.timeline([
            { title: `Moved to ${ui.label(item.status)}`, time: item.created_at, tone: ui.tone(item.status), icon: "arrow-right" },
            { title: "Created", time: item.created_at, body: `By ${item.owner || "someone"}`, icon: "plus" },
          ]),
        ],
        actions: (close) => [
          ui.button("Delete", { tone: "danger", icon: "trash", onclick: () => remove(item, close) }),
          next ? ui.button(`Move to ${next.label}`, { icon: "arrow-right", onclick: () => { close(); advance(item, next.key); } }) : null,
        ].filter(Boolean),
      };
    }

    function draw() {
      const done = items.filter((i) => i.status === "done").length;
      const pipeline = items.filter((i) => i.status !== "done").reduce((a, i) => a + (Number(i.amount) || 0), 0);
      const daily = perDay(items, 14);

      root.replaceChildren(
        ui.hero({
          eyebrow: "This week", title: `${items.length - done} examples in flight`,
          subtitle: "Everything the team is working on, what it is worth and where it is stuck.",
          stats: [
            { label: "Pipeline value", value: ui.money(pipeline) },
            { label: "Completed", value: String(done) },
            { label: "Completion rate", value: `${items.length ? Math.round((done / items.length) * 100) : 0}%` },
          ],
          actions: [ui.button("Open the board", { tone: "secondary", icon: "kanban", onclick: () => root.querySelector(".tabs button:nth-of-type(2)").click() })],
        }),

        ui.stats(STATUSES.map((s) => ({
          label: s.label,
          value: items.filter((i) => i.status === s.key).length,
          tone: s.tone,
          icon: s.key === "done" ? "check-circle" : s.key === "review" ? "eye" : s.key === "open" ? "inbox" : "activity",
          spark: perDay(items.filter((i) => i.status === s.key), 14).map((d) => d.value),
        }))),

        h("div", { class: "grid-2" },
          ui.section("By status", { icon: "pie" },
            ui.donut(STATUSES.map((s) => ({ label: s.label, value: items.filter((i) => i.status === s.key).length, tone: s.tone })),
              { center: String(items.length), sub: "examples" })),
          ui.section("Created per day", { icon: "activity", right: h("span", { class: "faint" }, "last 14 days") },
            ui.line(daily))),

        ui.section("All examples", { icon: "list" },
          ui.tabs([
            {
              label: "Table", icon: "list", badge: items.length,
              content: () => ui.table({
                columns: [
                  { key: "label", label: "Label", render: (i) => h("strong", {}, i.label) },
                  { key: "owner", label: "Owner", render: (i) => ui.person(i.owner) },
                  { key: "status", label: "Status", badge: true },
                  { key: "amount", label: "Amount", format: "money", align: "right" },
                  { key: "created_at", label: "Created", format: "ago" },
                ],
                rows: items, search: true, keyboard: true, pageSize: 10,
                filters: [{ key: "status" }], exportable: "examples",
                sort: { key: "created_at", dir: "desc" },
                drawer: details,
                empty: { title: "No examples yet", hint: "Create the first one with New example." },
              }),
            },
            {
              label: "Board", icon: "kanban",
              content: () => ui.kanban({
                columns: STATUSES, items, field: "status",
                card: (i) => [h("strong", {}, i.label),
                  h("div", { class: "between", style: { marginTop: "8px" } }, ui.person(i.owner), h("span", { class: "faint" }, ui.money(i.amount)))],
                onMove: (i, to) => api(`/examples/${i.id}`, { method: "PATCH", body: { status: to } }).then(() => { if (to === "done") ui.celebrate(); }),
                onCard: (i) => ui.drawer(details(i)),
              }),
            },
          ])),
      );
    }

    // The primary action lives in the page header, where a product keeps it.
    actions.append(ui.button("New example", { icon: "plus", onclick: create }));
    await load();
    draw();
  },
};
