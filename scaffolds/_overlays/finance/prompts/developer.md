THIS IS A FINANCE AND PROCUREMENT APPLICATION, and it has the finance library. Three parts of it
are already written, tested and read-only. Compose them; do not rebuild them.

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

   On a screen that is not a dashboard, use the pieces: `fin.money(v)`, `fin.money(v, { compact: true })`,
   `fin.percent(v)`, `fin.date(v)`, `fin.days(v)`, `fin.status("price_variance")`, `fin.varianceBadge(actual, budget)`,
   `fin.delta(changePct, { good: "down" })`, `fin.kpis(items)`, `fin.trend(points)`, `fin.budgetBars(rows)`,
   `fin.aging(buckets)`, `fin.pivot(data)`, `fin.documents("invoice", rows, { drawer })`,
   `fin.matchStatus({ status, ordered, received, invoiced })`, `fin.approvalChain(amount, matrix)`,
   `fin.lifecycle(states, current)`, `fin.scorecard(card)`, `fin.exportCsv(name, rows)`. Write every amount
   with `fin.money`, never `"£" + value` or `toFixed(2)`.

2. THE INSIGHT API — already served; write no router for a figure it gives. `const data = fin.data(api);`
       await data.kpis({ period: "fy_to_date", compare: "prior_year", cost_center_id: 3 })   -> { kpis: [{ key, label, unit, value, change_pct, favourable, spark }] }
       await data.breakdown({ measure: "spend", by: "supplier", top: 10 })                  -> { total, items: [{ key, label, value, share_pct, count }] }
       await data.trend({ measure: "spend", kind: "month", periods: 12 })                   -> { points: [{ label, start, end, value, budget, prior }] }
       await data.budget({ by: "cost_center" })       -> { rows: [{ label, budget, actual, variance, status, year_budget, committed, available, forecast }], totals }
       await data.aging()                             -> { buckets: [{ label, value, count, overdue }], total, overdue, suppliers }
       await data.documents({ entity: "invoice", status: "exception", dated: false, sort: "-amount" })  -> { count, amount, rows } with supplier_name, cost_center_name, days_overdue
       also: concentration, pivot, waterfall, funnel, cycleTimes, exceptions, accruals, renewals, controls, scorecard(supplierId)
   Every call takes the same scope: `period` (this_month, last_month, this_quarter, last_quarter, fy_to_date,
   fiscal_year, last_fiscal_year, last_12_months) or `from` and `to`; `compare`; and the filters
   cost_center_id, spend_category_id, supplier_id, family, department, region, country.
   A list of records with its own columns and actions is still `api("/invoices?status=exception")`, the generic data API.

3. THE OPERATIONS — what people do to records, each through the record's workflow, refused with its rule:
       await data.match(invoice.id)                     three-way match (PROC-01), duplicates (PROC-03), no order no pay (PROC-06)
       await data.receive(order.id, { amount: 1200, received_by: me.name })
       await data.proposeRun({ due_by: "2026-10-09" })   approved invoices into a payment run, discounts taken
       await data.budgetPosition({ cost_center_id: 3, requested: 5000 })     -> { status: ok|warning|exceeded, remaining, message }
       await data.advice(requisition.id)                 -> { approver, findings: [{ rule, level, message }] } to show before Submit
   In a router, the database session comes first: `ops.match_invoice(db, invoice_id)`,
   `ops.receive_goods(db, order_id, amount, received_by="")`, `ops.propose_payment_run(db, due_by="2026-10-09")`,
   `ops.budget_position(db, cost_center_id, requested=5000)`, `ops.check_request(db, requisition_id)`.
   The figures of the insight API are functions too, by the same names: `from ..finance import insight`, then
   `insight.budget(db, by="cost_center", period="fy_to_date")`, `insight.kpis(db, keys="spend,overdue")`,
   `insight.documents(db, entity="invoice", status="exception", dated=False)`. Import ONLY these modules from the
   library: `operations as ops`, `insight`, `rules as fin`, `analytics as fa`, `money`, `periods`; nothing from
   `..finance.api`. A route function has no return annotation (`def approve(...):`, never `-> PurchaseOrder`). An amount is summed with
   `money.total(values)` and compared as `money.D(a) > money.D(b)`, never as floats.
   The ERP is `from ..connectors import erp`: `erp().create_purchase_order(reference, supplier_code, amount,
   idempotency_key=reference)`, `erp().post_invoice(...)`, `erp().release_payments(...)`; each returns a Result
   (`.ok .key .mode .error`) and runs in its sandbox until credentials are set.

A record's drawer: `drawer: env.record("invoice")` inside a dashboard widget shows the record, its three-way match
and the workflow panel with what this person may do. Elsewhere, `enterprise.workflow.panel("invoice", row.id, { onChange: reload })`.
