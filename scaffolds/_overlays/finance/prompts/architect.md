THIS IS A FINANCE AND PROCUREMENT APPLICATION. In `data_model`, call the records by their
standard names, singular and snake_case: cost_center, gl_account, spend_category, supplier,
exchange_rate, budget_line, contract, requisition, purchase_order, purchase_order_line,
goods_receipt, invoice, payment_run, payment, savings_initiative, budget_change. The platform
writes those tables itself, with their demonstration data; name only the entities the brief needs
beyond them as new. Dashboards, charts, period pickers, drill-down and CSV export are `reuse`
(the dashboard kit). So are the screens people work on: their requests, the approval queue,
ordering, goods in, the invoice desk, payment runs, the supplier list and contracts (the work
screens). So are the three-way match, approval by amount, budget checks and the other rules of
the finance library, and the ERP connector. What is `build_new` is what this organisation
does differently: its own rules, thresholds, records and screens.
