# Connectors

Six reusable connectors ship inside every enterprise application
(`backend/app/connectors/`, from `scaffolds/_overlays/enterprise/`). They are platform-owned
and read-only: a story calls them and never writes HTTP, SMTP or webhook code of its own. They
use only the Python standard library, so they add nothing to an image and behave the same in
tests, in the sandbox and in production.

| Connector | Category | Operations | Live when set |
|---|---|---|---|
| `jira()` | Ticketing | `create_issue`, `get_issue`, `add_comment`, `transition`, `search` | `JIRA_BASE_URL`, `JIRA_PROJECT`, and `JIRA_EMAIL` + `JIRA_API_TOKEN` (Cloud) or `JIRA_PAT` (Data Center) |
| `servicenow()` | Ticketing | `create_incident`, `get_incident`, `update_incident`, `add_work_note`, `resolve_incident`, `query` | `SERVICENOW_INSTANCE`, and `SERVICENOW_USERNAME` + `SERVICENOW_PASSWORD` or `SERVICENOW_TOKEN` |
| `plane()` | Ticketing | `create_work_item`, `get_work_item`, `add_comment`, `move`, `list_work_items` | `PLANE_BASE_URL`, `PLANE_API_KEY`, `PLANE_WORKSPACE`, `PLANE_PROJECT_ID` |
| `email()` | Messaging | `send` | `SMTP_HOST`, `SMTP_FROM` (+ `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_PORT`, `SMTP_SECURITY`) |
| `slack()` | Messaging | `post` | `SLACK_WEBHOOK_URL`, or `SLACK_BOT_TOKEN` + `SLACK_CHANNEL` |
| `teams()` | Messaging | `post` | `TEAMS_WEBHOOK_URL` (a Workflows or incoming webhook) |

```python
from ..connectors import jira, servicenow, email, teams

r = jira().create_issue("Checkout fails for EU cards", "14 reports since 09:10",
                        priority="High", labels=["known-issue"], idempotency_key=f"issue-{issue.id}")
if r.ok:
    issue.jira_key, issue.jira_url = r.key, r.url        # SUP-104 — sandbox or live
else:
    log.warning(r.error)                                  # a readable reason; nothing was raised
```

## The contract every connector keeps

Every operation goes through one method (`Connector._call`, in `connectors/base.py`), so all of
them behave the same way.

- **Mode.** `live` when the connector's required settings are present, `sandbox` when they are
  not, `off` when `<NAME>_MODE=off`. `<NAME>_MODE=sandbox` forces the sandbox even with
  credentials (a demonstration on a machine that has them).
- **Sandbox.** Nothing leaves the application. The call is recorded and answered by a stand-in
  that keeps state: an issue created in the Jira sandbox (`SUP-101`, `SUP-102`… from the project
  key, `SBX` without one) can be read, commented on and transitioned afterwards; ServiceNow
  incidents are numbered `INC0010001` onwards and move through New, In Progress, Resolved; an
  e-mail is built exactly as it would be sent. A demonstration works end to end on a laptop.
- **Outbox.** Every call, live or sandbox, is one event in `sys_connector_event`: the operation,
  the request (secrets removed), the response, the remote key and link, attempts, the error, who
  made it. The Integrations screen shows it.
- **Retries.** A timeout, a refused connection, 429 or 5xx is retried in the request with
  backoff (Retry-After honoured, capped at 10 s), up to three attempts. A call that still fails is
  kept as `failed` with a `retry_at`, and the application's scheduler replays it later (at most
  eight attempts in all, within a day). Retry now from the Integrations screen needs
  `integrations:manage`.
- **Idempotency.** An operation given an `idempotency_key` runs once: asking again returns the
  first result (`replayed=True`) instead of creating a second ticket.
- **Breaker.** After five consecutive failures a connector stops calling out for a minute and
  records calls as `deferred`, so one dead system does not slow every request that touches it.
- **Never raises for a remote failure.** Every operation returns a `Result`:
  `ok`, `key`, `url`, `mode`, `data`, `error`, `event_id`, `replayed`.
- **Redaction.** Any field whose name looks like a password, secret, token, API key,
  authorisation, cookie or webhook is replaced with `•••` before it is recorded or shown.

## Each connector

**Jira** uses REST API v2 because Cloud and Data Center both accept it with plain-text
descriptions. `transition(key, "Done")` finds the transition whose target status (or own name)
matches, case-insensitively, and says which moves exist when none does. Labels are sent without
spaces. `browse_url(key)` is `<site>/browse/<key>`.

**ServiceNow** uses the Table API. `create_incident` takes urgency and impact (1–3) and an
optional category, caller and assignment group (`SERVICENOW_ASSIGNMENT_GROUP` by default);
`add_work_note(number, text, customer_visible=False)` writes a work note or, when visible, a
comment; `resolve_incident(number, close_notes)` sets state 6 with a close code. `query(table,
encoded_query)` reads any table the account may read.

**Plane** uses API v1 work items, as the platform's own Plane integration does. `r.key` is the
human key (`SUP-12`); later calls take the item's id, `r.data["id"]` (the same string in the
sandbox). `move(id, "Done")` matches a state by name or by group. A self-hosted Plane on the same
machine is reached from an app's containers at `http://host.docker.internal:<port>`.

**E-mail** sends through any SMTP server (Microsoft 365, Gmail, SES, Postfix); `SMTP_SECURITY`
is `starttls` (587, the default), `ssl` (465) or `none`. `EMAIL_REDIRECT_TO` sends every message
to one inbox instead, keeping the original recipients in `X-Original-To`, for a test environment
with real people in its data. In the sandbox, `EMAIL_SANDBOX_RELAY=host:port` also hands each
message to a local mail catcher such as Mailpit, where it opens as a real e-mail.

**Slack and Teams** take the same message — a title, text, up to ten facts and a link — and
render it the way each shows it best: Block Kit (header, section, fields, a button) for Slack, an
Adaptive Card 1.4 (text blocks, a FactSet, an OpenUrl action) for Teams. Slack posts through an
incoming webhook, or with a bot token to any channel the bot is in and in threads. Teams posts to
a Workflows "post to a channel when a webhook request is received" URL, or a classic incoming webhook.

## Going live

For every enterprise app, put the settings in the platform's `.env` with an `APPS_` prefix and
restart the orchestrator:

```ini
APPS_JIRA_BASE_URL=https://your-company.atlassian.net
APPS_JIRA_PROJECT=SUP
APPS_JIRA_EMAIL=bot@your-company.com
APPS_JIRA_API_TOKEN=…
APPS_TEAMS_WEBHOOK_URL=https://prod-00.westeurope.logic.azure.com/workflows/…
```

Each deployment writes them into the app's `app.env` (never committed) as `JIRA_BASE_URL` and so
on; the deployment's detail names the settings it passed, never their values. The control room's
**Enterprise** page shows each connector as it would run for apps, and which `APPS_` settings are
present. Inside a running app, the Integrations screen shows the same and has a **Send a test**
button per connector.

## Using them elsewhere

The package is plain Python 3.10+ with no dependencies. Copy
`scaffolds/_overlays/enterprise/backend/app/connectors/` into any project; without a database it
records to an in-memory outbox (`MemoryStore`), and `set_store()` attaches any object with the
`Store` methods in `base.py`. Every connector also takes `env={…}` to read settings from a dict
instead of the environment.

## Adding a connector

1. A module in `connectors/` with a `Connector` subclass: `name`, `title`, `category`,
   `description`, `settings` (`Setting(env, label, required=, secret=, default=, help=)`),
   `live_when_any` when there is more than one way to be configured, and `operations`.
2. Each operation builds its request, then returns
   `self._call(op, payload, live=…, sandbox=…, idempotency_key=…, ref=…)`. `live` makes the call
   with `http_json` (which raises `ConnectorError`, retryable for 429, 5xx and network errors);
   `sandbox` answers from `self._remember` / `self._recall` / `self.store.next_number`.
3. Register it in `CONNECTORS` and add a factory function in `connectors/__init__.py`, and teach
   `replay()` its operations so the scheduler can retry them.
4. Prove it in `selftest_enterprise.py`: sandbox state, then live against the local `Vendor`
   stand-in (add its endpoints), including a retried 5xx.
5. Tell the Developer it exists: `agents/prompts/developer_enterprise.md` and the KERNEL API
   block of `agents/prompts/domain.md`.
