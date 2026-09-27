THE FINANCE LIBRARY (backend/app/finance/, read-only) already holds the business logic every
finance and procurement application shares. Build on it; never restate what it decides.

  from ..finance import rules as fin          the rules, each registered with its id and proven by its own tests
  from ..finance import workflows as flows    the lifecycles, as factories over your models
  from ..finance import money, periods        exact amounts (Decimal), the fiscal calendar, ageing
  from ..finance import operations as ops     match_invoice, receive_goods, propose_payment_run, budget_position, check_request
  from ..finance import personas              the roles of the function, a persona for each, their permissions

THE LIBRARY'S RULES (already in the catalogue; do not register them again):
  FIN-01 segregation of duties           fin.check_segregation({"request": name, "approve": name})
  FIN-02 budget availability             fin.budget_position(budget, actual, committed, requested) -> .status ok|warning|exceeded; fin.check_budget(...)
  FIN-03 payment terms and due date      fin.due_date(invoice_date, "NET30" | "2/10NET30" | "EOM30")
  FIN-04 early payment discount          fin.early_payment_discount(amount, invoice_date, terms, as_of) -> .available .amount .pay
  FIN-05 late payment interest           fin.late_interest(amount, due_date, as_of, annual_rate_pct=8)
  FIN-06 tax                             fin.tax(net, rate="standard") -> .net .tax .gross; fin.check_tax(net, tax, gross)
  FIN-07 variance and materiality        fin.variance(actual, budget, kind="cost") -> .amount .pct .favourable .material
  FIN-08 accruals                        fin.grni(received_amount, invoiced_amount); fin.accruals(orders)
  FIN-09 allocation                      fin.allocate(amount, {"CC-100": 60, "CC-200": 40})
  FIN-10 closed periods                  fin.check_period_open(posting_date, closed_through)
  FIN-11 exchange differences            fin.fx_difference(amount, booking_rate, settlement_rate)
  PROC-01 three-way match                fin.three_way_match(order, receipts, invoice, fin.Tolerance(price_pct=2, amount_abs=50)) -> .status .ok .discrepancies
  PROC-02 delegation of authority        fin.approver_for(amount, matrix); fin.check_authority(amount, role, matrix)
  PROC-03 duplicate invoices             fin.duplicate_invoices(invoice, others)
  PROC-04 savings                        fin.saving(baseline_price, negotiated_price, quantity)
  PROC-05 supplier risk                  fin.supplier_risk(otif_pct, quality_pct, financial_health_pct, compliance_pct, spend_share_pct)
  PROC-06 no order, no pay               fin.po_required(amount); fin.check_po(invoice)
  PROC-07 contract renewal               fin.renewal(end_date, as_of, notice_days, auto_renew) -> .status .days_left .decide_by
  PROC-08 purchase price variance        fin.price_variance(standard_price, actual_price, quantity)
  PROC-09 approved suppliers only        fin.check_supplier(supplier)
  PROC-10 quotes by value                fin.quotes_needed(amount); fin.check_quotes(amount, quotes)
  PROC-11 split orders                   fin.split_orders(requests, limit)

WHAT YOU DO WITH THE FIVE FILES. Return each complete.
- rules.py: keep its imports and its `fin.configure(...)` call, and set in it the numbers the brief states:
      fin.configure(
          doa=[(2_000, "budget_holder"), (20_000, "head_of_department"), (None, "cfo")],      # BR-01: who approves up to which amount
          tolerance=fin.Tolerance(price_pct=1, quantity_pct=0, amount_abs=25),                 # BR-05: within 1% and 25
          po_required_above=500,                                                                # BR-06
      )
  Its settings: doa, tolerance, po_required_above, po_exempt_categories, quote_bands [(up to, quotes, tender)],
  budget_warning_pct, material_pct, material_amount, expiring_days, duplicate_days, split_days, orderable,
  late_interest_pct, tax_rates. The last entry of `doa` is `(None, role)`: someone approves any amount. The
  library's rules, the lifecycles, the operations and the dashboards all read these, so set them ONCE, here.
  Then register EVERY rule the brief states under the brief's own id. Where the library decides the
  matter, the brief's rule calls it, without repeating the number:
      @rule("BR-05", "An invoice matches within 1% and 25", source="BRD 4", kind="validation")
      def match(order, receipts, invoice):
          return fin.three_way_match(order, receipts, invoice)
  A rule the library does not have is written as any rule is: pure, amounts through `money.D(...)`,
  never float arithmetic on money (`0.1 + 0.2` is not `0.3`).
- workflows.py: keep each `register(flows.<record>(Model, …))` for a record the brief has. Approval by
  amount follows `fin.configure(doa=…)`; pass only what else the brief says: its own role names
  (`requester=("employee",)`, `buyer=("procurement_officer",)`, `clerk=("ap_specialist",)`),
  `approval_hours=24`, `exception_hours=72`, `escalate_to="finance_controller"`, one fixed approver
  (`doa="finance_controller"`). Every role you name there or in `doa` must be in policy.py's ROLES. A
  record the library has no lifecycle for gets its own `Workflow(...)`, as the kernel's API below describes.
- policy.py: keep the roles the brief uses and rename or add the brief's own; every role named by a
  workflow or by `doa` stays in ROLES with a persona. Permissions name tables that exist.
- services.py: keep the operations it has; add the brief's own, each calling the rules.
- tests/test_rules.py: tests for the BRIEF's rules only, named `test_<id>_…` (`test_br_05_inside_tolerance`),
  on both sides of every threshold, with the brief's numbers written in the test. Records are
  `SimpleNamespace(amount=2_000)`; amounts compare as `Decimal("1250.00")` or through `float(...)`.
  The library's rules are tested in tests/test_finance_library.py: do not test them again.
