/* Worked example — a reference, and read-only: edits to it are refused.
 *
 * Copy this shape into a NEW file, frontend/screens/<resource>.js, for your
 * story. Once any real screen exists the platform stops listing this one, so it
 * never appears in the delivered application.
 *
 * The shell already drew the sidebar, the page title and the subtitle from this
 * module's own fields, so a screen renders content sections only. The parts come
 * from the UI kit (`ui`): headline numbers, a searchable, sortable, paged table
 * with keyboard navigation, badges, people, relative times, a form, a detail
 * panel. Compose them; do not draw tables or badges by hand.
 */
export default {
  title: "Examples",
  subtitle: "A worked reference the platform removes once real screens exist.",
  story: "",
  async render(root, { api, h, navigate, actions, ui }) {
    // 1. Load the data first. A screen must open showing its real rows.
    let items = await api("/examples");

    // 2. Headline numbers above the fold.
    const summary = ui.stats([
      { label: "Examples", value: items.length },
      { label: "Added today", value: items.filter((i) => ui.timeAgo(i.created_at).endsWith("h ago") || ui.timeAgo(i.created_at).endsWith("m ago")).length, tone: "ok" },
    ]);

    // 3. A detail panel that follows the selected row.
    const detail = h("div", {}, ui.empty("Select an example", "Use ↑ ↓ and Enter, or click a row."));
    function showDetail(item) {
      detail.replaceChildren(
        h("div", { class: "between" }, h("h3", {}, item.label), ui.badge("Active", "ok")),
        ui.kv([
          { label: "Reference", value: h("span", { class: "mono" }, `EX-${item.id}`) },
          { label: "Created", value: `${ui.date(item.created_at)} · ${ui.timeAgo(item.created_at)}` },
        ]),
        h("div", { class: "form-actions" },
          ui.button("Open", { tone: "secondary", onclick: () => navigate(`#/examples/${item.id}`) })),
      );
    }

    // 4. The table: search, sort, paging and keyboard navigation come for free.
    const table = ui.table({
      columns: [
        { key: "label", label: "Label", render: (i) => h("strong", {}, i.label) },
        { key: "id", label: "Reference", mono: true, render: (i) => `EX-${i.id}` },
        { key: "created_at", label: "Created", render: (i) => ui.timeAgo(i.created_at) },
        { label: "Status", render: () => ui.badge("Active", "ok") },
      ],
      rows: items,
      search: true,
      keyboard: true,
      pageSize: 25,
      sort: { key: "created_at", dir: "desc" },
      onSelect: showDetail,
      empty: { title: "No examples yet", hint: "Add the first one with the form." },
    });

    // 5. A form that creates a row through the API and redraws without a reload.
    const form = ui.form({
      fields: [{ name: "label", label: "Label", required: true, placeholder: "e.g. Quarterly budget review", hint: "Shown in the list." }],
      submit: "Add example",
      onsubmit: async (values) => {
        await api("/examples", { method: "POST", body: values });
        items = await api("/examples");
        table.update(items);
        ui.toast("Example added", "ok");
        return "Saved.";
      },
    });

    // 6. The primary action sits in the page header, where a product keeps it.
    actions.append(ui.button("Refresh", { tone: "secondary", onclick: async () => table.update(items = await api("/examples")) }));

    root.append(
      summary,
      ui.split(
        [ui.section("All examples", table)],
        [ui.section("Details", detail), ui.section("Add an example", form)],
      ),
    );
    table.focus();
  },
};
