/* Worked example — a reference, and read-only: edits to it are refused.
 *
 * Copy this shape into a NEW file, frontend/screens/<resource>.js, for your
 * story. Once any real screen exists the platform stops listing this one, so it
 * never appears in the delivered application. It also demonstrates the design
 * system in styles.css — the badge, empty-state and loading patterns here are
 * what a polished screen looks like; reuse them rather than inventing new CSS.
 */
export default {
  title: "Examples",
  story: "",
  async render(root, { api, h }) {
    const count = h("span", { class: "badge" }, "…");
    const list = h("ul", { class: "list" });
    const message = h("p", { class: "muted" });
    const label = h("input", { name: "label", required: true, maxlength: 200 });

    function renderRows(rows) {
      count.textContent = `${rows.length} total`;
      list.replaceChildren(
        ...(rows.length
          ? rows.map((row) => h("li", {}, row.label))
          : [h("div", { class: "empty-state" }, "Nothing here yet — add the first one below.")]),
      );
    }

    async function refresh() {
      renderRows(await api("/examples"));
    }

    async function save(event) {
      event.preventDefault();
      try {
        await api("/examples", { method: "POST", body: { label: label.value } });
        label.value = "";
        message.textContent = "Saved.";
        await refresh();
      } catch (err) {
        message.className = "error-text";
        message.textContent = err.message; // shown on the page, where the user is looking
      }
    }

    root.append(
      h("section", { class: "panel stack" },
        h("div", { class: "row", style: { alignItems: "center", justifyContent: "space-between" } },
          h("h2", {}, "Examples"),
          count),
        h("form", { class: "row", onsubmit: save },
          h("label", {}, "Label", label),
          h("button", { type: "submit" }, "Add")),
        message,
        list),
    );
    list.replaceChildren(h("div", { class: "skeleton" }, "Loading…"));
    await refresh();
  },
};
