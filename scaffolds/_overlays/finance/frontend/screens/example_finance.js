/* Worked example for finance screens — a reference, and read-only: edits to it are refused.
 *
 * Copy its shape into a NEW file, frontend/screens/<name>.js, for your story. The platform
 * stops listing this one once a real screen exists.
 *
 * A dashboard is a description, not a drawing. Start from the blueprint nearest the story
 * (executive, spend, budget, payables, procureToPay, suppliers, controls, savings) and say
 * what is different: the figures, the targets, the filters, the widgets, a team it is fixed to.
 * The period picker, the comparison, the rows behind every number, CSV export and each
 * person's own arrangement come with it.
 */
import fin from "../finance.js";

export default {
  title: "Finance overview",
  subtitle: "A worked reference the platform removes once real screens exist.",
  icon: "dollar",
  story: "",
  async render(root, ctx) {
    const { api, ui, h, actions } = ctx;
    const data = fin.data(api);
    const calendar = await data.calendar();
    if (!calendar.entities.invoice && !calendar.entities.purchase_order) {
      root.replaceChildren(ui.empty("No finance tables yet",
        "Once the data model has invoices or purchase orders, this screen shows them.", { icon: "dollar" }));
      return;
    }

    // 1. A whole dashboard: a blueprint, and what this story wants different.
    const board = await fin.dashboard(root, ctx, fin.blueprints.executive({
      id: "finance-overview",
      period: { value: "fy_to_date", compare: "prior_year" },
      filters: ["cost_center_id", "family", "supplier_id"],
      kpis: ["spend", "budget_used", "commitments", "payables", "overdue", "po_coverage", "first_time_match", "on_time_payment"],
      targets: { po_coverage: 95, first_time_match: 85, on_time_payment: 95 },
      add: [
        // 2. A widget of the story's own: load what it needs, draw it with the kit.
        { type: "custom", id: "largest-overdue", title: "Largest overdue invoices", icon: "alert", span: 12,
          load: (env) => env.data.documents({ ...env.scope, entity: "invoice", overdue: true, dated: false, sort: "-amount", limit: 25 }),
          draw: (result, env) => fin.documents("invoice", result.rows, {
            pageSize: 5, exportable: "overdue-invoices",
            columns: [
              { key: "reference", label: "Invoice", render: (r) => h("strong", { class: "mono" }, r.reference) },
              { key: "supplier_name", label: "Supplier" },
              { key: "due_date", label: "Due", render: (r) => fin.date(r.due_date) },
              { key: "days_overdue", label: "Overdue", align: "right", render: (r) => fin.days(r.days_overdue) },
              { key: "amount", label: "Amount", align: "right", render: (r) => h("span", { class: "mono" }, fin.money(r.amount)) },
              { key: "status", label: "Status", render: (r) => fin.status(r.status) },
            ],
            drawer: env.record("invoice"),          // the record, its lifecycle, its three-way match and what can be done
          }),
          rows: (result) => result.rows },
      ],
    }));

    // 3. The page's own action, in the header where a product keeps it.
    actions.append(ui.button("Overdue by supplier", { tone: "secondary", icon: "clock", onclick: async () => {
      const aging = await data.aging(board.scope());
      ui.drawer({ title: "Overdue by supplier", subtitle: `As of ${fin.date(aging.as_of)}`, icon: "clock",
        content: [fin.aging(aging.buckets),
          ui.bars(aging.suppliers.filter((s) => s.overdue > 0).map((s) => ({ label: s.label, value: s.overdue, tone: "down" })),
            { format: (v) => fin.money(v, { compact: true }) })] });
    } }));
  },
};
