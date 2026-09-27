THIS IS A FINANCE AND PROCUREMENT APPLICATION, and it has the finance library. Four parts of it
are already written, tested and read-only. Compose them; do not rebuild them.

FIRST DECIDE WHICH KIND OF SCREEN THE STORY IS:
  - people READ figures on it (a dashboard, an overview, a report, an analysis)  -> `fin.dashboard`, part 1
  - people WORK on it (a queue, an inbox, a list to approve, order, receive, match or pay from; "my requests")  -> `fin.workbench`, part 2
Either way the whole screen file is an import, a title and ONE call. A screen written that way needs no router,
no table, no form and no fetch of its own, and it passes the browser check.

1. THE DASHBOARD KIT — `import fin from "../finance.js";` as the first line of a screen file.
   A dashboard is a description. Start from the blueprint nearest the story and say what differs:

       await fin.dashboard(root, ctx, fin.blueprints.spend({
         id: "spend-by-team", period: { value: "this_quarter", compare: "prior_year" },
         filters: ["cost_center_id", "family", "supplier_id"],      // or false; fixed: { department: "Operations" } pins one
         kpis: ["spend", "po_coverage", "maverick_spend"], targets: { po_coverage: 95 },
         widgets: [ { type: "trend", measure: "spend", span: 8 },
                    { type: "breakdown", measure: "spend", by: "supplier", chart: "pareto", span: 6 },
                    { type: "budget", by: "cost_center", span: 6 } ],
       }));                                                        // ctx is what render() received

   Blueprints: executive, spend, budget, payables, procureToPay, suppliers, controls, savings. Each takes
   `add: [widgets]` and `remove: ["pivot"]` instead of a whole `widgets` list.
   Widget types: kpis, trend, breakdown (chart: bars | donut | treemap | pareto), budget, waterfall, aging,
   funnel, pivot (rows, columns), cycle, exceptions, accruals, renewals, controls, documents (entity),
   suppliers, custom ({ type: "custom", title, span, load: async (env) => data, draw: (data, env) => node }).
   Measures: spend, invoiced, payables, paid, orders, commitments, requisitions, receipts, payments, budget,
   savings, realised_savings, contract_value. Dimensions (`by`): supplier, category, family, cost_center,
   department, region, country, status, match_status, risk, buyer, requester, month, quarter, year.
   Figures (`kpis`): spend, budget, budget_used, budget_variance, budget_available, forecast, forecast_pct,
   requisitions, awaiting_approval, orders, commitments, payables, overdue, po_coverage, first_time_match,
   contracted_spend, maverick_spend, on_time_payment, dpo, discount_capture, discounts_missed, invoice_cycle,
   requisition_cycle, otif, price_variance, savings_identified, savings_realised, exceptions, suppliers,
   high_risk, expiring.
   The period picker, the comparison, the filters, the rows behind every number, CSV export and each
   person's own arrangement come with it: never build them.

2. THE WORK SCREENS — a queue, an inbox or a desk is a description too. Start from the worklist nearest the story:

       await fin.workbench(root, ctx, fin.worklists.approvals());                  // an approval queue, whole
       await fin.workbench(root, ctx, fin.worklists.requisitions({ mine: true }));  // my requests, with "New requisition"
       await fin.workbench(root, ctx, fin.worklists.receiving({ remove: ["receipts"],
         add: [{ key: "large", label: "Large orders", status: "sent,partially_received", actions: ["receive"],
                 filter: (row) => row.amount >= 25000 }] }));

   Worklists: requisitions (raise, submit, follow), approvals (approve and reject what waits for me), ordering
   (approved requests into orders, orders to the supplier and the ERP), receiving (goods in, what is late),
   invoices (match, held, to approve, to pay, overdue), paymentRuns (what is due, propose a run), suppliers, contracts.
   Each takes `add: [views]`, `remove: ["key"]`, `mine: true|false`, `create`, `tools`, `columns`.
   A view (a tab): { key, label, icon, entity, status: "a,b", sort, query: { overdue: true }, filter: (row, env) => bool,
   actions: [...], empty: { title, hint } }. Entities: requisition, purchase_order, goods_receipt, invoice, payment_run,
   payment, supplier, contract, budget_change, savings_initiative.
   Actions on a row: "submit", "order", "send", "receive", "match", "approve", "reject", "scorecard"; a step of the
   record's lifecycle, { transition: "approve", label: "Approve for payment" }; or one of the story's own,
   { key, label, icon, when: (row) => bool, run: async (row, env) => "What happened" } (`env.api`, `env.data`, `env.me`).
   The tabs and their counts, search, export, the record with what the rules say, its lifecycle and history, the forms,
   a refusal shown with its rule, and who may do what come with it: never build them.

   On a screen that is neither, use the pieces: `fin.money(v)`, `fin.money(v, { compact: true })`,
   `fin.percent(v)`, `fin.date(v)`, `fin.days(v)`, `fin.status("price_variance")`, `fin.varianceBadge(actual, budget)`,
   `fin.delta(changePct, { good: "down" })`, `fin.kpis(items)`, `fin.trend(points)`, `fin.budgetBars(rows)`,
   `fin.aging(buckets)`, `fin.pivot(data)`, `fin.documents("invoice", rows, { drawer })`,
   `fin.matchStatus({ status, ordered, received, invoiced })`, `fin.approvalChain(amount, matrix)`,
   `fin.lifecycle(states, current)`, `fin.scorecard(card)`, `fin.advice(await data.advice(id))`,
   `fin.exportCsv(name, rows)`. Write every amount with `fin.money`, never `"£" + value` or `toFixed(2)`.

3. THE INSIGHT API — already served; write no router for a figure it gives. `const data = fin.data(api);`
       await data.kpis({ period: "fy_to_date", compare: "prior_year", cost_center_id: 3 })   -> { kpis: [{ key, label, unit, value, change_pct, favourable, spark }] }
       await data.breakdown({ measure: "spend", by: "supplier", top: 10 })                  -> { total, items: [{ key, label, value, share_pct, count }] }
       await data.trend({ measure: "spend", kind: "month", periods: 12 })                   -> { points: [{ label, start, end, value, budget, prior }] }
       await data.budget({ by: "cost_center" })       -> { rows: [{ label, budget, actual, variance, status, year_budget, committed, available, forecast }], totals }
       await data.aging()                             -> { buckets: [{ label, value, count, overdue }], total, overdue, suppliers }
       await data.documents({ entity: "invoice", status: "exception", dated: false, sort: "-amount" })  -> { count, amount, rows } with supplier_name, cost_center_name, days_overdue
       await data.documents({ entity: "requisition", mine: true, dated: false })            -> the ones I raised
       await data.worklist({ entity: "invoice" })     -> { count, amount, statuses: [{ key, label, count, amount }] }
       await data.approvals()                         -> { count, amount, overdue, rows: [{ approval_id, entity, id, reference, title, amount, requested_by, approver, can_decide }] }
       also: concentration, pivot, waterfall, funnel, cycleTimes, exceptions, accruals, renewals, controls, scorecard(supplierId)
   Every figure takes the same scope: `period` (this_month, last_month, this_quarter, last_quarter, fy_to_date,
   fiscal_year, last_fiscal_year, last_12_months) or `from` and `to`; `compare`; and the filters
   cost_center_id, spend_category_id, supplier_id, family, department, region, country.
   A list of records with its own columns and actions is still `api("/invoices?status=exception")`, the generic data API.

4. THE OPERATIONS — what people do to records, each through the record's workflow, refused with its rule:
       await data.createRequisition({ title, amount, cost_center_id })   a draft with its reference (PROC-02)
       await data.transition("requisition", id, "submit", { reason })    a step of any record's lifecycle
       await data.decide(row.approval_id, true, "note")                  approve (false: reject) what waits for me
       await data.raiseOrder(requisition.id, { supplier_id })            the order of an approved requisition (PROC-09)
       await data.sendOrder(order.id)                   to the supplier, and into the ERP
       await data.match(invoice.id)                     three-way match (PROC-01), duplicates (PROC-03), no order no pay (PROC-06)
       await data.receive(order.id, { amount: 1200, received_by: me.name })
       await data.proposeRun({ due_by: "2026-10-09" })   approved invoices into a payment run, discounts taken
       await data.budgetPosition({ cost_center_id: 3, requested: 5000 })     -> { status: ok|warning|exceeded, remaining, message }
       await data.advice(requisition.id)                 -> { approver, findings: [{ rule, level, message }] } to show before Submit
   In a router, the database session comes first: `ops.match_invoice(db, invoice_id)`,
   `ops.receive_goods(db, order_id, amount, received_by="")`, `ops.propose_payment_run(db, due_by="2026-10-09")`,
   `ops.budget_position(db, cost_center_id, requested=5000)`, `ops.check_request(db, requisition_id)`,
   `ops.create_requisition(db, {"title": …, "amount": …})`, `ops.raise_order(db, requisition_id, supplier_id=12)`,
   `ops.send_order(db, order_id)`, `ops.waiting(db)`. NEVER set a record's `status` yourself (`order.status = "sent"` is
   refused): a status moves through its workflow, `transition(db, record, "send")` from `..kernel`, or one of these operations.
   The figures of the insight API are functions too, by the same names: `from ..finance import insight`, then
   `insight.budget(db, by="cost_center", period="fy_to_date")`, `insight.kpis(db, keys="spend,overdue")`,
   `insight.documents(db, entity="invoice", status="exception", dated=False)`, `insight.approvals(db)`. Import ONLY these
   modules from the library: `operations as ops`, `insight`, `rules as fin`, `analytics as fa`, `money`, `periods`; nothing from
   `..finance.api`. A route function has no return annotation (`def approve(...):`, never `-> PurchaseOrder`). An amount is summed with
   `money.total(values)` and compared as `money.D(a) > money.D(b)`, never as floats.
   The ERP is `from ..connectors import erp`: `erp().create_purchase_order(reference, supplier_code, amount,
   idempotency_key=reference)`, `erp().post_invoice(...)`, `erp().release_payments(...)`; each returns a Result
   (`.ok .key .mode .error`) and runs in its sandbox until credentials are set.

A record's drawer: `drawer: env.record("invoice")` inside a dashboard widget shows the record, its three-way match
and the workflow panel with what this person may do. Elsewhere, `enterprise.workflow.panel("invoice", row.id, { onChange: reload })`.
