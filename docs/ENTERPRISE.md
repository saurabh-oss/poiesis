# Enterprise applications

The `mvp` pack builds an application people are impressed by on first open. The
`enterprise` pack builds one an organisation can run its work on: people sign in and act
within their role, records move through lifecycles the server enforces, decisions that need
a second person wait for one, every change is in an audit trail, the brief's business rules
exist once with ids and tests, and the application talks to Jira, ServiceNow, Plane, e-mail,
Slack and Teams.

It does this with two additions to the value stream:

1. **The enterprise overlay** (`scaffolds/_overlays/enterprise/`), copied over the web-app
   scaffold at scaffold time: a platform-owned **kernel** (sign-in, roles, audit, workflows,
   approvals, SLAs, rules, notifications, scheduler), the **connectors**
   ([CONNECTORS.md](CONNECTORS.md)), four platform screens, and a worked-example domain.
2. **The domain stage**, inside foundation: after the data model and before the
   demonstration data, the Developer writes the application's business logic once, from the
   whole backlog, and the platform tests it before any story is built.

Stories then build screens and endpoints on top, importing the domain instead of re-deciding it.

## Why the domain stage exists

The MVP DupeGuard run ([case study](CASE-STUDY-DUPEGUARD.md)) had one duplicate score in its
brief (55/20/15/10, with six named rules) and shipped three: the scan, the ticket view and the
review queue each implemented the score inside their own router, from their own reading of the
brief. Every file was reasonable; the rule had no home. Precision numbers were simulated for the
same reason. The fix after that run was to write one engine by hand (`dedupe.py`) that every
screen called. The domain stage makes that the platform's job.

## Switching to it

```ini
# .env
POIESIS_PACK=packs/enterprise.yaml
```
then `docker compose up -d orchestrator`. The pack is read when a stage asks for it, so it
applies to runs that start afterwards. Gates are automatic except release (as in `mvp`), there is
no Tester loop, and the review weights favour reuse (the domain and connectors) and rule tests.
The Product Owner is told the platform already provides sign-in, approvals, audit, rules and
integrations screens, so stories are the business's own screens, each naming the role that uses it.

## What a generated enterprise application contains

```
backend/app/
  kernel/            platform-owned, read-only: auth, policy, audit, workflow, rules, notify,
                     outbox, jobs, api (everything under /api/platform and /api/auth)
  connectors/        platform-owned, read-only: jira, servicenow, plane, mail, chat (Slack, Teams)
  domain/            the application's business logic, written by the domain stage
    policy.py        roles, demonstration personas, permissions, screen access, notification channels
    rules.py         every business rule, once, with its id and source   (@rule, check)
    workflows.py     each record's lifecycle: states, transitions, approvals, SLAs
    services.py      operations over the database that combine rules, workflows and connectors
    rule_results.json  what the rule tests proved at build time (read by the Business rules screen)
  routers/           story endpoints, as in every app
frontend/
  platform.js        sign-in page, user card and bell, Approvals / Audit trail / Business rules /
  platform.css       Integrations screens, and the helpers story screens receive
tests/test_rules.py  at least two tests per rule, named after it (test_br_04_…)
app.env              written at each deployment, never committed: APP_SECRET, the platform's
                     check token, connector settings
```

`main.py`, `data_main.py`, `routers/resources.py`, `routes.py` and `app.js` are the same files
every app has; each looks for the kernel and uses it when it is there.

## The kernel

### Signing in, roles and permissions

`domain/policy.py` declares roles, demonstration personas and permissions:

```python
ROLES = {"agent": "Support agent", "team_lead": "Team lead", "ops_manager": "Support operations manager", "admin": "Administrator"}
PERSONAS = [{"username": "maya", "full_name": "Maya Chen", "title": "Tier 1 agent", "team": "Support",
             "email": "maya.chen@example.com", "roles": ["agent"]}, …]
PERMISSIONS = {"agent": ["ticket:read", "ticket:update", "cluster:read"],
               "team_lead": ["ticket:*", "cluster:*", "audit:read", "rules:read", "integrations:read"],
               "admin": ["*"]}
SCREENS = {"accuracy_settings": ["ops_manager", "admin"]}
CHANNELS = {"approval_requested": ["email", "teams"], "sla_breached": ["teams"]}
```

A permission is `<table>:<action>`: `read`, `create`, `update`, `delete` (checked by the generic
data API on every call), a transition's name, or anything a router checks with
`Depends(require("ticket:merge"))`. `<table>:*`, `*:read` and `*` are wildcards; `admin` holds
everything. The platform's own permissions are `audit:read`, `rules:read`, `integrations:read`,
`integrations:manage` and `users:read`.

At start-up the kernel creates an account for every persona. While `AUTH_PERSONAS` is on (the
default) the sign-in page offers them as one-click cards; with `AUTH_PERSONAS=off` people sign in
with a password (`AUTH_ADMIN_PASSWORD` sets the administrators' first one; `POST /api/auth/password`
sets others'). A session is an HMAC-SHA256-signed token (12 hours, `AUTH_TOKEN_HOURS`) keyed by
`APP_SECRET`. Every `/api` request passes a pure ASGI middleware that resolves the person (cached
for a minute, so a deactivated account stops quickly) and answers 401 without one, except the
sign-in endpoints, `/api/status` and `/api/platform/profile`. The data service mounts the same
middleware, so the gateway's fallback never bypasses it.

### Workflows, approvals and SLAs

```python
TICKET = register(Workflow(
    "ticket", Ticket, field="status",
    states={"new": "New", "open": "Open", "pending_review": "In review", "closed": "Closed"},
    initial="new",
    transitions=[
        Transition("close_as_duplicate", ("new", "open"), "closed", roles=("team_lead",),
                   guard=rules_guard, rule="BR-04", fields=("duplicate_of_id",), tone="ok"),
        Transition("promote_cluster", "open", "pending_review", roles=("agent", "team_lead"),
                   approval="team_lead"),
        Transition("reopen", "closed", "open", roles=("team_lead",), requires_reason=True, tone="warn"),
    ],
    sla={"pending_review": 4}, escalate={"pending_review": "team_lead"},
))
```

A governed column moves **only** through `transition()` (the endpoint is
`POST /api/platform/workflows/<table>/<id>/<transition>`). The audit listener refuses any other
write to it before SQL is sent: a PATCH through the generic API, a router assigning
`ticket.status = …`, a job. That refusal is rule `WF-00`; the platform's static check flags the
same thing in a router before it ever runs. A new record starts in the initial state.

What `transition()` enforces, in order: the record is in a state the transition leaves from; the
person holds one of its roles (or the permission `<table>:<transition>`); a reason is given when
required; the guard (a domain rule) allows it. A transition with `approval="<role>"` opens an
approval instead of moving; someone holding that role, and never the requester (four eyes, rule
`WF-02`), approves or rejects it in the Approvals screen, and the move happens on approval.
When the request is itself the record (a proposed threshold change), `on_reject="Rejected"`
ends it on rejection, with an audit entry. When one transition serves several rules (an
automatic close by BR-01 or by BR-12), the caller names the one that took the move:
`transition(db, t, "auto_close", rule=decision.rule)`, and the audit trail records it.
Entering a state with an SLA starts a clock; the scheduler escalates a clock past due to the
`escalate` role.

### Audit trail

A SQLAlchemy listener records every insert, update and delete of an application table made
through the ORM, whoever made it: the actor, the time, the request, and each changed field's
value before and after. Transitions, approvals, SLA breaches, sign-ins and whatever a service
records with `record(db, "rule", "Closed 812 as a duplicate of 790 (score 91)", entity="ticket",
entity_id=812, rule_id="BR-01")` land in the same trail. A status moved by a transition is recorded
once, by the transition, with its name, reason and approver.

### Business rules

```python
@rule("BR-04", "A P1 ticket is never closed automatically", source="BRD §6.2", kind="decision")
def may_auto_close(ticket) -> bool:
    return getattr(ticket, "priority", "") != "P1"

check(amount <= limit, "BR-07", f"£{amount:,.0f} is above your approval limit")
```

A violation is answered as 409 with `{"detail", "rule", "rule_title"}`, and the shell shows the
rule's id with the message. The catalogue (`GET /api/platform/rules`, the Business rules screen)
lists every rule with its source, where it lives, how often it was checked and how often it
refused, and what its tests proved at build time. A rule a workflow transition names keeps the
domain's own title and kind.

### Notifications and the scheduler

`notify(db, title, body, roles=…, users=…, link=…)` writes to each recipient's inbox (the bell)
and, for the kinds `CHANNELS` lists, sends through the e-mail, Slack or Teams connectors **after
the transaction commits** — never inside it, so a rolled-back approval announces nothing. One
thread in the api service (not the data service) wakes every `JOB_SECONDS` (30): it escalates
SLA breaches, replays connector calls that failed with a retryable error once their retry time
comes (at most 8 attempts, within a day), and runs any `@every(minutes=…)` job in `domain/jobs.py`.

### The platform API inside every enterprise app

| Method | Path | |
|---|---|---|
| GET | `/api/platform/profile` | enterprise, auth, check persona, roles, workflows, connector modes, load errors |
| GET | `/api/auth/personas` · POST `/api/auth/sign-in` · GET `/api/auth/me` · POST `/api/auth/password` | signing in |
| GET | `/api/platform/workflows` | every lifecycle |
| GET · POST | `/api/platform/workflows/{table}/{id}` · `…/{transition}` | a record's state, what I may do next and why not, history; perform a move |
| GET · POST | `/api/platform/approvals?status=&scope=` · `…/{id}/approve` · `…/{id}/reject` | approvals |
| GET · POST | `/api/platform/notifications` · `…/{id}/read` · `…/read-all` | the inbox |
| GET | `/api/platform/audit?entity=&entity_id=&actor=&action=&q=&since=` · `/audit/stats` | the trail (a record's own history needs only read on it) |
| GET | `/api/platform/rules` | the rule catalogue, workflows, roles, permissions, test results |
| GET · POST | `/api/platform/integrations` · `/events` · `/{connector}/objects` · `/events/{id}/retry` · `/{connector}/test` | connectors and the outbox |
| GET | `/api/platform/users` | people and their roles |

The kernel's own tables (`sys_user`, `sys_audit`, `sys_approval`, `sys_sla_clock`,
`sys_notification`, `sys_connector_event`, `sys_connector_object`) are created at start-up and are
not served by the generic data API.

## The screens

The sign-in page offers the personas (or a password form); the sidebar gains the signed-in
person's card (their permissions, switch user, sign out) and a notification bell. Four platform
screens follow the story screens under **Governance**, each shown only to people who may use it:

- **Approvals** — what is waiting for me (approve or reject with a note), my requests, history.
- **Audit trail** — every event, filterable by kind, person and table, with a diff of each change
  and the record's own history.
- **Business rules** — every rule as a card (id, kind, source, where it lives, tests, checks and
  refusals), each lifecycle as a state diagram with its transitions, and the role/permission matrix.
- **Integrations** — the connectors and their modes, settings and a test button, the outbox with
  request, response and Retry, and what each sandbox holds (e-mails rendered, Slack and Teams
  messages previewed, sandbox issues and incidents with their comments and state).

Story screens receive `enterprise` in `render()`: `me`, `can(permission)`,
`workflow.panel(table, id, {onChange})` (state, SLA clock, the transitions this person may take,
with the rule that stops the ones they may not, approvals and history), `workflow.actions`,
`workflow.badge`, and `audit.history`.

## The domain stage

Inside `lay_foundation`, between the data model and the demonstration data
(`graph/nodes/domain.py`, prompt `agents/prompts/domain.md`):

1. The Developer (coding model) reads the brief, every story's criteria, `models.py`, the
   `init.sql` tables with their allowed-value comments, the verified imports and the worked
   example, and writes `policy.py`, `rules.py`, `workflows.py`, `services.py` and
   `tests/test_rules.py`.
2. In the sandbox the platform imports the domain and checks it against the data model: every
   role named in permissions, transitions, approvals and escalations exists; every permission's
   table exists; every workflow's column, states, transitions and fields exist; every role has a
   persona; no worked example is left; at least one rule is registered. Then it runs the rule tests
   with a JUnit report.
3. Every problem goes back — import tracebacks, consistency problems, failing tests, rules no
   test is named after — up to `build.domain_repairs` times (3). Attempts are ranked (importing,
   then consistency, then passing tests, then coverage) and the **best** one is kept: a repair can
   make things worse, and in the first enterprise run attempts 2–4 were each worse than the first.
   Each attempt's model call is memoised by what it was told, so a resumed run never replays a
   reply written against different feedback. The rule tests run on their own (`--noconftest`);
   a refusal's text starts with its rule id (`BR-04: …`).
4. Test results are mapped to rules by name (`test_br_04_…` → `BR-04`; longer ids first, so
   `BR-10`'s tests are not taken for `BR-1`'s) and written to `domain/rule_results.json`.
5. A domain that never imports is replaced by the platform's general policy (three generic roles,
   no rules or workflows) so sign-in still works, and the failure stays on the record.

The seed then speaks the domain's language: the Data Designer is told each workflow's states
(spread rows across all of them) and the personas' names (use them for a good share of the
people columns, so each persona finds their own work on first sign-in).

`policy.py`, `rules.py`, `workflows.py` and `tests/test_rules.py` are read-only for stories;
`services.py` stays theirs to extend. The domain is recorded as the run's `domain` artifact and
shown on the run page's **Business logic** card and on the control room's **Enterprise** page.

## Building stories on it

Each story's context adds `agents/prompts/developer_enterprise.md` (how screens and routers use
the kernel, the domain and the connectors) and the domain's summary: its rules and where they
live, its workflows with states and transitions, its services and roles. The verified-imports
block lists `from ..domain.rules import …`, `from ..kernel import …` and `from ..connectors import …`.
The platform's checks add two enterprise ones ([CHECKS.md](CHECKS.md#enterprise-applications)):
a router or service that calls out with `requests`, `httpx`, `urllib`, `smtplib` or `aiohttp`, and
one that writes a governed status column.

## Verification

- The API smoke run uses the platform's service token, so every GET is exercised as before.
- The browser check reads `/api/platform/profile`, screenshots the sign-in page, signs in as the
  profile's check persona (an administrator when there is one, so every screen is visible) the way
  a person does, then opens and uses every screen. The platform screens are opened too; if one
  fails it is reported as a platform problem, never as a story's.
- `python -m app.selftest_enterprise` in the orchestrator proves the connectors against local
  stand-ins, the kernel end to end on SQLite through three personas, and the domain stage's checks
  (78 checks, no model calls).

## Security notes

- Generated apps bind to `127.0.0.1` unless `POIESIS_DEPLOY_BIND` says otherwise.
- `app.env` holds `APP_SECRET`, the check token and connector credentials; it is written at every
  deployment and ignored by Git.
- One-click personas are for demonstrations. Before real use set `AUTH_PERSONAS=off` and
  `AUTH_ADMIN_PASSWORD` (through `APPS_AUTH_…` in the platform's `.env`, or in the app's own
  environment), and give people passwords.
- SSO (OIDC, SAML) and LDAP directories are not part of this release.

## Settings inside a generated enterprise app

| Variable | Default | |
|---|---|---|
| `APP_SECRET` | derived from the database URL | signs session tokens; set per deployment by Poiesis |
| `AUTH_REQUIRED` | on | off serves the API without sign-in (not recommended) |
| `AUTH_PERSONAS` | on | one-click demonstration personas |
| `AUTH_ADMIN_PASSWORD` | — | administrators' first password |
| `AUTH_TOKEN_HOURS` | 12 | session length |
| `JOB_SECONDS` | 30 | how often the scheduler wakes |
| `POIESIS_SERVICE_TOKEN` | per run | the platform's own checks |
| connector settings | — | see [CONNECTORS.md](CONNECTORS.md) |

The platform passes any `APPS_<NAME>` variable in its own `.env` whose name starts with
`JIRA_`, `SERVICENOW_`, `PLANE_`, `SMTP_`, `EMAIL_`, `SLACK_`, `TEAMS_`, `AUTH_` or is
`JOB_SECONDS` into every enterprise app as `<NAME>`.
