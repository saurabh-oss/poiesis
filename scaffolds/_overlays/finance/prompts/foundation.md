FINANCE CONVENTIONS for the entities you do write:
- An amount is `Float` (`DOUBLE PRECISION`), named `amount`, or `<what>_amount` when a record has
  several (`net_amount`, `tax_amount`). A currency is `String(3)`, named `currency`, default "GBP".
- A reference people quote is `reference`, `String(30)` (`EXP-2026-0412`).
- A person is kept by name as well as by id (`requester_name`, `approver_name`): screens show
  names, and the audit trail has the ids.
- A date that matters to finance is a `Date` (`invoice_date`, `due_date`, `period_start`); a moment
  in a process is a `DateTime(timezone=True)` ending in `_at` (`submitted_at`, `approved_at`).
- A record that belongs to a cost centre, a supplier or a category carries `cost_center_id`,
  `supplier_id`, `spend_category_id`: the filters of every dashboard are those three.
- A lifecycle is one `status` column, its allowed values in the comment, in the order they happen.
