/* Worked example — a reference, and read-only: edits to it are refused.
 *
 * Copy this shape into a NEW file, frontend/screens/<resource>.js, for your
 * story. Once any real screen exists the platform stops listing this one, so it
 * never appears in the delivered application.
 *
 * It also shows the layout the design system expects: the shell already drew the
 * sidebar, the page title and the subtitle from this module's own fields, so a
 * screen renders content sections only — never its own page chrome. The primary
 * action goes in the header via `actions`, where a product keeps it.
 */
export default {
  title: "Examples",
  subtitle: "A worked reference the platform removes once real screens exist.",
  story: "",
  async render(root, { api, h, actions }) {
    const rows = h("tbody");
    const message = h("p", { class: "faint" });
    const label = h("input", { name: "label", required: true, maxlength: 200,
                               placeholder: "e.g. Quarterly budget review" });
    const count = h("span", { class: "badge" }, "…");

    function draw(items) {
      count.textContent = `${items.length} total`;
      rows.replaceChildren(...items.map((item) =>
        h("tr",
          {},
          h("td", {}, h("strong", {}, item.label)),
          h("td", { class: "faint mono" }, item.id),
          h("td", {}, h("span", { class: "badge badge-ok" }, "Active")))));
    }

    async function refresh() {
      const items = await api("/examples");
      if (!items.length) {
        table.hidden = true;
        empty.hidden = false;
        count.textContent = "0 total";
        return;
      }
      table.hidden = false;
      empty.hidden = true;
      draw(items);
    }

    async function save(event) {
      event.preventDefault();
      if (!label.value.trim()) return;
      submit.disabled = true;
      try {
        await api("/examples", { method: "POST", body: { label: label.value } });
        label.value = "";
        message.textContent = "Saved.";
        await refresh();
      } catch (err) {
        message.className = "error-text";
        message.textContent = err.message; // on the page, where the user is looking
      } finally {
        submit.disabled = false;
      }
    }

    const submit = h("button", { type: "submit" }, "Add example");
    const table = h("div", { class: "table-wrap" },
      h("table", {},
        h("thead", {}, h("tr", {},
          h("th", {}, "Label"), h("th", {}, "Reference"), h("th", {}, "Status"))),
        rows));
    const empty = h("div", { class: "empty-state", hidden: true },
      h("strong", {}, "Nothing here yet"),
      "Add the first example using the form above.");

    // The header's action slot belongs to the screen; the header itself does not.
    actions.append(h("button", { class: "secondary", onclick: refresh }, "Refresh"));

    root.append(
      h("section", { class: "panel stack" },
        h("h2", {}, "Add an example"),
        h("form", { class: "stack", onsubmit: save },
          h("div", { class: "form-grid" },
            h("div", { class: "field" },
              h("label", {}, "Label"),
              label,
              h("span", { class: "hint" }, "Shown in the list below."))),
          h("div", { class: "form-actions" }, submit, message))),
      h("section", { class: "panel stack" },
        h("div", { class: "between" }, h("h2", {}, "Examples"), count),
        table,
        empty),
    );

    table.hidden = true;
    await refresh();
  },
};
