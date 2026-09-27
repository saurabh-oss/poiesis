/* Worked example for a screen people WORK on (a queue, an inbox, a desk) — a reference, and read-only.
 *
 * Copy its shape into a NEW file, frontend/screens/<name>.js. A work screen is a description:
 * start from the worklist nearest the story (requisitions, approvals, ordering, receiving, invoices,
 * paymentRuns, suppliers, contracts) and say what is different. The tabs with their counts, the
 * search, the export, the record with its rules, lifecycle and history, the forms, the refusals
 * with their rule and the permissions come with it. Write no table, form or fetch for them.
 */
import fin from "../finance.js";

export default {
  title: "Goods in",
  subtitle: "A worked reference the platform removes once real screens exist.",
  icon: "truck",
  story: "",
  async render(root, ctx) {
    await fin.workbench(root, ctx, fin.worklists.receiving({
      id: "goods-in",
      // A tab of the story's own, beside the standard ones: what to show, and what can be done to a row.
      add: [{ key: "large", label: "Large orders", icon: "flag", status: "sent,partially_received", actions: ["receive"],
        filter: (row) => row.amount >= 25000,
        empty: { title: "No large order is on its way", hint: "Orders of £25,000 or more appear here." } }],
      remove: ["receipts"],
    }));
  },
};

/* The others, each one line:
 *   fin.worklists.approvals()                        what waits for my decision: Approve and Reject, with the budget and the rules
 *   fin.worklists.requisitions({ mine: true })       raise a request (the form is the library's), submit it, follow it
 *   fin.worklists.ordering()                         approved requests into orders, orders to the supplier and the ERP
 *   fin.worklists.invoices({ remove: ["paid"] })     match, hold, approve, pay
 *   fin.worklists.paymentRuns()                      what is due, and "Propose a payment run"
 * An action of the story's own on a row:
 *   actions: ["receive", { key: "chase", label: "Chase", icon: "mail", when: (row) => row.status === "sent",
 *             run: async (row, env) => { await env.api(`/purchase-orders/${row.id}/chase`, { method: "POST" }); return "Chased"; } }]
 * A step of the record's lifecycle as a button: actions: [{ transition: "approve", label: "Approve for payment" }]
 */
