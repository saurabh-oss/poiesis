THIS IS AN ENTERPRISE APPLICATION. People sign in and act within their role; records move
through server-enforced workflows; every change is audited; the business rules exist once in
backend/app/domain/. The platform already provides the sign-in page, the Approvals, Audit
trail, Business rules and Integrations screens, and notifications — never build those.

In a screen, `render(root, { api, ui, h, navigate, params, actions, enterprise })`:
- `enterprise.me` is the signed-in person (`.name`, `.roles`, `.username`); `enterprise.can("ticket:merge")`
  says whether they hold a permission. Show a control only to people who may use it.
- A record's status is moved ONLY through its workflow. In a drawer or detail view use
  `enterprise.workflow.panel("ticket", t.id, { onChange: reload })`: it shows the state, the SLA
  clock, the transitions this person may take (with the rule that stops them when they may not),
  pending approvals and the history. In a table cell or card, `enterprise.workflow.actions("ticket", t.id,
  { onChange: reload })` gives just the buttons; `enterprise.workflow.badge("ticket", t.status)` the state.
- `enterprise.audit.history("ticket", t.id)` is a record's change history.
- A refused call throws an Error with `.rule` (e.g. "BR-04") and `.detail`: show both with `ui.toast`.

In a router:
- Never write a governed status column, not even with PATCH to the generic API: the server refuses
  it (409, rule WF-00). Call `transition(db, row, "approve", reason=…)` from `..kernel`, or let the
  screen use the workflow panel. `POST /api/platform/workflows/<table>/<id>/<transition>` is the
  endpoint, body `{"reason": "", "fields": {}}`.
- Decisions, scores and validations come from `..domain.rules` and `..domain.services`; never
  compute a rule inline. If your story needs an operation the services lack, add it to
  `backend/app/domain/services.py` (return that file complete) and call the rules from it.
- Guard every endpoint that changes data: `@router.post("/tickets/{ticket_id}/merge",
  dependencies=[Depends(require("ticket:merge"))])` with `from ..kernel import require`. The
  generic data API already checks `<table>:read|create|update|delete` by itself.
- Talk to other systems only through `from ..connectors import jira, servicenow, plane, email, slack,
  teams` — never `requests`, `httpx`, `urllib` or `smtplib`. Each call returns a Result
  (`.ok .key .url .mode .error`) and never raises for a remote failure; pass an `idempotency_key`
  for anything that creates something. Without credentials they run in their sandbox, which is
  the normal state of a demonstration: treat `mode == "sandbox"` as success.
- Explain an automatic decision in the audit trail: `record(db, "rule", "Closed 812 as a duplicate
  of 790 (score 91)", entity="ticket", entity_id=812, rule_id="BR-01")`; tell people with
  `notify(db, title, body, roles=("team_lead",), link="#/review_queue")`.
