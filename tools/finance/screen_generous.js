/* A description written the way a model wrote one in the first finance run: something to press
 * put among the tabs, an action named by its key with no `run`, one the library does not have, and
 * a form of its own for raising a record the library already has the form for.
 * The kit reads it for what was meant. browse_work.py checks that it does. */
import fin from "../finance.js";

export default {
  title: "Requisitions, as described",
  icon: "inbox",
  story: "S17",
  async render(root, ctx) {
    await fin.workbench(root, ctx, fin.worklists.requisitions({
      id: "generous",
      mine: true,
      create: {
        title: "New requisition", icon: "plus",
        fields: [{ name: "title", label: "Title", required: true }, { name: "amount", label: "Amount", type: "number", required: true }],
        async onsubmit(values, env) { await env.api("/finance/requisitions", { method: "POST", body: values }); },
      },
      add: [
        { key: "new", label: "New Requisition", icon: "plus", run: async (env) => { env.ctx.ui.toast("pressed", "ok"); } },
        { key: "policy", label: "Buying policy", icon: "info", run: async () => "The buying policy is on the intranet" },
      ],
      actions: [
        { key: "preview", label: "Preview Approval", icon: "eye", when: (row) => row.status === "draft" },
        { key: "submit", label: "Send for approval", icon: "arrow-right", when: (row) => row.status === "draft" },
      ],
    }));
  },
};
