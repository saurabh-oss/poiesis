# Plane boards

Every idea submitted to Poiesis gets its own project, board and sprint in
[Plane](https://plane.so), an open-source tracker that works like Jira and runs on this
machine. Stakeholders see the backlog the agents planned as work items on a board, and the
cards move as the agents build, pass or fail each story.

Plane was chosen over Jira Cloud (free, but in Atlassian's cloud) and Taiga (closer to our
backlog model, older interface) because it keeps everything local and looks like the tool
people already know. The Jira mirror still exists (`README.md`, "Jira") and both can run at
once.

- Every idea's board: http://localhost:3000/boards (the **Boards** page)
- One run's board: `/runs/<id>/board`, and a board card on each run page
- Plane itself: http://localhost:8200 — sign in as `admin@poiesis.local`; the password is
  `PLANE_ADMIN_PASSWORD` in `infra/plane/plane.env`
- Code: `services/orchestrator/app/integrations/plane.py` (client and mirror),
  `app/api/plane.py`, `scripts/plane-bootstrap.py`, `infra/plane/`

## What each idea becomes

| Poiesis | Plane | Details |
|---|---|---|
| The run | **Project** | Named `<product> · <run id prefix>`, key = product initials + six characters of the run id (`TRI7FDAD8`). Opens as a board grouped by state |
| Backlog epic | **Module** | The epic's outcome as its description |
| Backlog story | **Work item** in its module | Narrative, acceptance criteria as a list, value, estimate, risk, dependencies; label `<n> pts`, label `high risk`, priority from the story's value (9–10 urgent, 7–8 high, 4–6 medium, else low) |
| Sprint 1 | **Cycle** | Dated today plus the sprint length, holding exactly the sprint's stories, which move to Todo |
| Story being built | **In Progress** | |
| Story green | **Done** | With a comment on what was verified and which files it wrote |
| Story red or dropped | stays **In Progress**, label `poiesis-red` | With the failure in a comment |
| Release | a **Release** work item | Linked to the running app; Done when released, a comment when held or sent back |

States only ever move forward: a replayed node cannot reopen a Done item.

## Two rules the mirror keeps

**It never stops a run.** Every call is wrapped: Plane being down, a bad token or a refused
field costs one warning in the run's activity feed ("Plane sync skipped (…)"), never the run.

**It never duplicates.** LangGraph replays a whole node each time a gate is answered, so
every hook runs several times per run. Every object is created under a `remember()` key
(`plane:project`, `plane:story:s3`, …) stored with the run's checkpoint, and work items and
modules also carry `external_id` = `<run>-<ref>` with `external_source` = `poiesis`, which
Plane refuses to create twice (409 with the existing id, treated as "found").

The hooks are the tracker's (`tracker.on_backlog`, `on_sprint`, `on_story_started`,
`on_story_result`, `on_release`); each calls the Plane mirror first and the Jira mirror
second, independently.

## Setting it up

```powershell
copy infra\plane\plane.env.example infra\plane\plane.env     # set SECRET_KEY and LIVE_SERVER_SECRET_KEY
docker compose -f infra/plane/docker-compose.yml --env-file infra/plane/plane.env -p plane up -d
python scripts\plane-bootstrap.py
docker compose up -d orchestrator
curl -X POST http://localhost:8080/api/plane/sync            # mirror every past run with a backlog
```

Plane v1.4.2 runs as 13 containers (about 3–4 GB of memory) in its own Compose project on
port 8200, so it starts and stops independently of the platform. `plane.env` differs from
Plane's published defaults in three ways: the port, `CERT_ACME_CA` set (Caddy refuses its
configuration without it, even for plain HTTP), and `API_KEY_RATE_LIMIT=6000/minute`
(mirroring every past run at once is thousands of calls).

A fresh Plane wants a person to click through its setup: an instance admin, a workspace, an
API token. `scripts/plane-bootstrap.py` does the same through Plane's own Django models in
its api container, and is safe to run again:

- creates or updates the admin user (password from `plane.env`, generated if empty) and
  marks the instance set up, so the web UI goes straight to sign-in;
- creates the `poiesis` workspace and makes the admin its owner, with onboarding done;
- creates an API token allowed 2000 calls a minute;
- switches every project to the board layout;
- writes `PLANE_URL`, `PLANE_API_URL`, `PLANE_WORKSPACE` and `PLANE_API_TOKEN` into `.env`.

| Setting | Default | Meaning |
|---|---|---|
| `PLANE_URL` | `http://localhost:8200` | What links in the console open |
| `PLANE_API_URL` | `http://host.docker.internal:8200` | What the orchestrator calls |
| `PLANE_WORKSPACE` | `poiesis` | Workspace slug |
| `PLANE_API_TOKEN` | — | Empty = mirror off |
| `PLANE_API_CONTAINER` | `plane-api-1` | Used to switch new projects to a board (below) |
| `PLANE_ADMIN_EMAIL` | `admin@poiesis.local` | Whose board layout is set |

## Boards, not lists

Plane opens a project as a list, and its REST API has no call to change that: the layout is
a per-user setting (`ProjectUserProperty.display_filters`). After mirroring a backlog, the
orchestrator runs one line of Django in Plane's api container (through the Docker socket it
already has) to set the admin's layout to a board grouped by state. Plane writes that
setting only after it answers the project's create call, so the switch runs at the end of
the backlog, not right after the project is made. It is best effort: if it fails, the
project opens as a list, one click from the board.

## The console pages

**Boards** lists every idea with a backlog: its project key, share of items done, a
segmented bar and counts per state, modules, stories, sprint and release; totals across
every board at the top; "Open in Plane", "Board" and, for an idea not yet mirrored,
"Mirror to Plane".

**A run's board** (`/runs/<id>/board`) draws the Plane project as a Kanban board in the
console: five columns by state group, cards with key, priority bars, module and labels, a
filter by module, and "Sync again". Cards open the work item in Plane.

The **board card** on a run page shows the counts per state and links to both.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Boards page: "Plane is not connected" | `PLANE_API_TOKEN` is empty for the orchestrator: run the bootstrap, restart the orchestrator |
| "Plane sync skipped (…): 429" in a run's feed | Throttled. The client backs off and retries; if it still gave up, `POST /api/runs/{id}/plane/sync` (nothing is duplicated) |
| "MODULE_NAME_ALREADY_EXISTS" | Treated like a 409; if it persists, two runs share a project key — keys use six characters of the run id since two AssetHub runs began with the same four |
| Projects open as lists | The orchestrator cannot reach `plane-api-1`: `python scripts/plane-bootstrap.py` |
| A story was fixed after the run but is red in Plane | Move it to Done in Plane with a comment saying what changed and how it was verified (as was done for DupeGuard's S4 and S8). Do not re-sync that run afterwards: a sync re-applies the run's recorded outcomes, and the story's recorded outcome is still red, so its `poiesis-red` label would come back |
| Sign-in page asks to set up an instance | The bootstrap has not run against this Plane (or its volumes were deleted) |
