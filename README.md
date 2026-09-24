# Poiesis — Autonomous Engineering Platform

One user. One input. A working, tested, deployed increment — with an audit trail back to the sentence that asked for it.

Poiesis takes whatever a business stakeholder already has (a document, a whiteboard photo, a recorded call, a link, three lines of text) and runs it through a governed agent value stream: understand → clarify → vision → backlog → architecture → sprint → build → test → review → release. Humans are not in the loop for every token; they are in the loop at **typed gates** where a decision actually changes the outcome.

The thing that makes Poiesis different from every "prompt to app" tool is the **Portfolio Knowledge Graph**. Before any agent designs or writes anything, it must ask the graph what already exists. Reuse is enforced by architecture, not encouraged by a prompt.

## Documentation

| Document | Read it to |
|---|---|
| [docs/SETUP-WINDOWS.md](docs/SETUP-WINDOWS.md) | Install and start Poiesis on a Windows laptop with a GPU |
| [docs/FIRST-RUN.md](docs/FIRST-RUN.md) | Take one brief from submission to a running app, and know where to look |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | Start everything after a reboot, run the self-tests, find logs, fix what breaks |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Understand the design positions, the graph and the components |
| [docs/AGENTS.md](docs/AGENTS.md) | See what each agent reads, produces and refuses to do |
| [docs/CHECKS.md](docs/CHECKS.md) | Know how an increment is verified, and why a story went red |
| [docs/API.md](docs/API.md) | Script the platform: runs, gates, deployments, maps, boards, knowledge, observability |
| [docs/CODEMAPS.md](docs/CODEMAPS.md) | Understand the ArchiLens codebase maps |
| [docs/PLANE.md](docs/PLANE.md) | Set up and understand the Plane boards |
| [docs/CASE-STUDY-DUPEGUARD.md](docs/CASE-STUDY-DUPEGUARD.md) | Read one full run: what the platform built, what it got wrong, what changed |

Sample briefs: [docs/samples/](docs/samples/) — BRD-ITAM-2026-014 (AssetHub, IT asset management)
and BRD-SUP-2026-021 (DupeGuard, duplicate-ticket auto-triage).

---

## Business capabilities

| Capability | What it means to the business | Where it lives |
|---|---|---|
| Intent capture from any source | Stakeholders don't write requirements docs; they talk, sketch, and forward links | `ingest/` + Analyst agent |
| Adversarial clarification | The platform interrogates gaps and contradictions before spending build cycles | Analyst agent, `clarify` gate |
| Traceable product definition | Every story traces to a captured stakeholder statement; every commit traces to a story | Product Owner agent + KG |
| Enforced reuse | New work is checked against an indexed portfolio before it is designed | Portfolio Knowledge Graph |
| Governed autonomy | Agents run unattended between gates; gates are typed, logged, and reversible | Orchestrator interrupts |
| Verified, not just tested | Every increment is deployed and opened in a real browser — every screen opened, a row opened, tabs switched, its "New…" dialog pressed — before a human ever sees the release decision; the release gate cannot offer "release" for an app that is not proven working | `deploy` stage, `workspace/browser_check.py`, [docs/CHECKS.md](docs/CHECKS.md) |
| A guaranteed base to hand off | Rework and human rebuilds are bounded; if the increment still isn't fully working when that budget runs out, the release gate can ship a smaller *base app* — dropping only what's broken — instead of ending in pure iteration | `approve_release` gate |
| Evidence-backed release | A release verdict is a computed artifact, not an opinion | Reviewer + Release agents |
| Full local sovereignty, or hosted quality | `local` keeps every brief and every line of generated code on your machine, on models whose replies are constrained to each agent's schema; `cloud` routes the agents to a hosted model when that matters more than sovereignty | `llm.py`: native Ollama client, LiteLLM for hosted profiles |
| Compounding memory | Every finished run adds what it built, decided and learned; the next run's Architect and Developer are shown the components, decisions and lessons that apply, by word and by meaning | Neo4j graph + Qdrant vector index |
| Work tracked where the organisation tracks it | Every idea becomes its own project and board in a self-hosted Plane (modules, work items, a sprint cycle, cards moving as stories pass or fail); the same in Jira Cloud when configured; branch, tag and pull request on the Git remote, as the run goes | `integrations/plane.py`, `integrations/tracker.py`, `integrations/gitremote.py` |
| Every codebase readable as pictures | ArchiLens draws each generated app's runtime topology, modules grouped by story, data model and request flows, explained by the local model; a reviewer sees what was built without opening a file | `workspace/codemap.py`, `/codebases` |
| Explainable, measurable | Every model call kept with its prompt and reply; every stage, sandbox run and deploy timed; traces to Jaeger, metrics to Prometheus and Grafana | `telemetry.py`, `/api/runs/{id}/traces`, `/metrics` |
| A demonstrable MVP in one sitting | Under the `mvp` pack the platform lays the whole data model and generated, believable demonstration data first, serves every table through a generic data API, and has the Developer build only polished screens on a UI kit; no test loop, verification is the real browser | `packs/mvp.yaml`, `foundation` stage, `routers/resources.py`, `frontend/ui.js` |

## MVP mode: screens first

`POIESIS_PACK=packs/mvp.yaml` (the default in `.env`) trades backend rigour for a product a
visitor can be impressed by within an hour on local models:

1. **Foundation stage** (after scaffold, before any story). The Foundation Developer writes
   `models.py`, `schemas.py` and the `CREATE TABLE`s for every entity in the whole backlog at
   once. The Data Designer then writes a JSON *spec* for the demonstration data, decoded
   under a schema built from those tables: catalogues of realistic subjects and bodies,
   weighted choices, references between tables, look-ups, time windows, near-duplicate
   clusters. The platform expands it deterministically (`workspace/seedspec.py`), checks
   the rows (every column exists, NOT NULL filled, text varied, every state present, the
   counts the brief asks for), renders them into a section of `db/init.sql` it owns, and
   proves the file executes on Postgres. A story's rewrite of init.sql can never thin
   them. `POST /api/runs/{id}/reseed` regenerates the data for a run;
   `POST /api/runs/{id}/deploy?fresh=true` restarts its app on it.
2. **A generic data API.** `backend/app/routers/resources.py` serves every table without a
   router: list with `?q=`, `?column=value`, `?sort=-column`, paging; read, create, update,
   delete; `GET /api/resources` describes them. A story writes a router only for what that
   cannot do (a computed suggestion, an aggregate, a multi-row action), and its own paths win.
3. **A UI kit.** `frontend/ui.js` gives every screen headline stats, searchable, sortable,
   paged tables with keyboard navigation, badges, avatars, relative times, key/value details,
   list-and-detail layouts, forms, bar and time-series charts and toasts, all on the design
   system in `styles.css`. The Developer composes; it does not draw.
4. **No Tester and no pytest.** A story is implemented, compiled, checked statically (a
   screen that gives up without an id, a render argument never taken, a router without a
   router, a stray root route, a call to a path nothing serves), then every GET is answered
   against a throwaway Postgres loaded from the app's own `init.sql` before deploy, and the
   app is opened — and used — in a real browser. Three repairs per story, each told to fix
   everything listed; one automatic rework round; every gate but the release
   auto-approved. The Reviewer is told tests are absent by design and judges what a visitor
   sees. [docs/CHECKS.md](docs/CHECKS.md) lists every check.

**The same service topology for every generated app.** A gateway (nginx) serves the UI
and routes /api; an api service runs the story endpoints plus the generic data API; a data
service runs the generic data API alone, with no story code; Postgres holds the seeded
data. The gateway resolves services per request and falls back to the data service when
the api is down, it waits for the database and data service but not for the api, and
every service restarts on failure. A story module that fails to import is left out of the
api and reported at `/api/platform/modules` instead of stopping it. Verified by breaking a
module and stopping the api service on a live stack: the UI kept loading and reads and
writes kept working through the data service.

**The experience is platform-owned.** Every generated app ships the same shell and UI kit
(`frontend/app.js`, `ui.js`, `styles.css`): icon navigation, breadcrumbs, a progress bar on
every call, skeleton loading, a command palette (Ctrl K) over screens and every record,
light and dark themes, keyboard shortcuts, and components that animate on their own:
count-up stats with trends, donut, line, column and bar charts, rings and meters, tables
with filters, CSV export and a slide-over drawer per row, drag-and-drop boards, timelines,
tabs, dialogs, toasts and a confetti burst for real successes. The Developer composes them,
guided by `agents/prompts/ux_playbook.md` (appended to its instructions): the bar every
screen clears, a recipe per screen type, and how to show names instead of ids. The worked
example screen uses every recipe on seeded rows. Before deploy, every GET is exercised on a
throwaway Postgres loaded from the app's own `init.sql`.

Switch to `packs/default.yaml` for the full build: Tester, repair loops, regressions.

**A lesson from the DupeGuard run** ([case study](docs/CASE-STUDY-DUPEGUARD.md)): every
screen worked and the Reviewer scored it 90.8, yet three stories had each implemented the
BRD's duplicate-scoring rule differently, because each story is built in its own context.
Screens are verified; business rules that several stories share are not yet. A shared
domain module written by the foundation stage is the proposed fix.

## Architecture at a glance

```
                    ┌──────────────────────────────────────────┐
  business user ───►│  Intake: docs, images, audio, URLs, text  │
                    └────────────────────┬─────────────────────┘
                                         ▼
        ┌────────────────────────────────────────────────────────────┐
        │  ORCHESTRATOR  (FastAPI + LangGraph, Postgres checkpoints)  │
        │                                                             │
        │  Analyst → PO → Architect → Planner → Developer → Tester    │
        │            → Deploy (real browser check) → Reviewer         │
        │            → Release (ship / base app / send back / hold)   │
        │                                                             │
        │  every edge can raise a typed HITL interrupt                │
        └───┬─────────────┬──────────────┬──────────────┬────────────┘
            │             │              │              │
       ┌────▼────┐   ┌────▼─────┐   ┌────▼─────┐   ┌────▼─────┐
       │ Neo4j   │   │ Postgres │   │ git      │   │ Docker   │
       │portfolio│   │ runs,    │   │workspace │   │ sandbox  │
       │ graph   │   │artifacts,│   │ per run  │   │ per test │
       │         │   │ gates,   │   │          │   │ run      │
       │         │   │checkpoint│   │          │   │          │
       └─────────┘   └──────────┘   └──────────┘   └──────────┘
            ▲
            │  indexed from your existing repos
       ┌────┴──────────────────────────────────────┐
       │ INDEXER: tree-sitter AST + embeddings     │
       │ ForgeAI · ArchiLens · TestLoom · TraceGuard│
       └───────────────────────────────────────────┘

  events ──► Redis pub/sub ──► WebSocket ──► UI (Next.js, light theme)
  spans  ──► Postgres (spans, llm_calls) ──► run page "Model traces"
         └─► OTLP ──► Jaeger            metrics ──► /metrics ──► Prometheus ──► Grafana
  harvest ──► Neo4j (stories, decisions, lessons) + Qdrant (the same, by meaning)
  build   ──► Plane (project, modules, work items, cycle) · Jira (initiative, epics,
              stories, sprint) · Git remote (branch, tag, PR)
  deploy  ──► the app as its own compose project (gateway, api, data, db) on 127.0.0.1:81xx
          └─► ArchiLens code map (topology, modules, data model, flows; local-model notes)

  (MinIO is in the compose file but not yet used — see
   "Deliberately not built yet" in docs/ARCHITECTURE.md)
```

## Quick start (Windows)

See `docs/SETUP-WINDOWS.md`. Short version:

```powershell
git clone <this repo> poiesis; cd poiesis
copy .env.example .env      # set POIESIS_LLM_PROFILE and POIESIS_WORKSPACE_HOST_ROOT
powershell -ExecutionPolicy Bypass -File scripts\restart-ollama.ps1   # Ollama with the settings Poiesis needs
docker compose up -d
.\scripts\bootstrap.ps1     # pulls the models, indexes your portfolio
start http://localhost:3000
```

Optional, for the Boards page: start Plane and run `python scripts\plane-bootstrap.py`
([docs/PLANE.md](docs/PLANE.md)). After a reboot, follow the start order in
[docs/OPERATIONS.md](docs/OPERATIONS.md).

Two settings decide whether the first run works. `POIESIS_WORKSPACE_HOST_ROOT` must be the
absolute path to this repo's `workspaces` folder as **Windows** sees it — the test sandbox
is a sibling container, so the Docker daemon resolves that bind mount on the host, not
inside the orchestrator. And the repo URLs in `services/indexer/portfolio.yaml` must be
real, or the knowledge graph stays empty and every architecture verdict comes back
"build new".

## The control room

http://localhost:3000, in the Adobe Spectrum look shared by every generated app.

| Page | What it is for |
|---|---|
| **Runs** (home) | Describe a problem, attach documents and links, start a run; the eight agents as tiles; the value stream; recent runs |
| **A run** (`/runs/<id>`) | The stage rail, the open gate and its decision, the running app with its screenshots, the board and codebase-map cards, integrations, model traces, the activity feed |
| **Apps** | Every generated app with its address and status; start, redeploy, stop |
| **Boards** | Every idea's Plane project: progress per state, sprint, release; a Kanban board per run at `/runs/<id>/board` |
| **Codebases** | Every generated codebase drawn by ArchiLens; a full map per run at `/runs/<id>/codebase` |
| **Portfolio** | What the knowledge graph knows: recall by word and meaning, projects and their capabilities, lessons learned, the house stack |
| **Observability** | Dependency health, model calls and tokens over time, response times, GPU busy, model time by agent, where the time goes, runs, recent errors |

## Models

The `local` profile runs everything on your own GPU through Ollama, and it is the profile
the platform is tuned for. The defaults in `.env.example`:

| Role | Model | Why |
|---|---|---|
| reasoning (Analyst, Product Owner, Architect, Reviewer) | `qwen3.6:35b-a3b` | 35B mixture-of-experts with 3B active: strong reasoning, runs split across a 12 GB GPU and system RAM at a usable speed; allowed to think before it answers |
| coding (Developer, Tester) | `qwen3.6:35b-a3b-coding` | the same family tuned for agentic coding, 256K context; thinking off, the reply is the files |
| fast (Planner, Release Manager, term extraction) | `qwen3.6:35b-a3b` | one model loaded means no swapping between stages |
| embeddings | `nomic-embed-text` | the vector index over the graph |
| vision (whiteboard photos, diagrams) | `gemma4:12b` | fits the GPU whole |

The orchestrator talks to Ollama directly. Each agent's reply is **constrained to its JSON
schema** (`agents/schemas.py`) at decode time, so a local model cannot return malformed
JSON or omit a required key; the context window (`POIESIS_LOCAL_NUM_CTX`, 32k by default)
is sent with every request; replies stream with an idle timeout rather than a fixed one,
so a long reply from a model split across GPU and RAM is not killed mid-file; and which
roles may *think* first is a setting (`POIESIS_LOCAL_THINK_ROLES`). A model that spends
its whole budget thinking is asked again without.

`.\scripts\bootstrap.ps1` pulls whatever `.env` names. Expect ~55 GB the first time.

## Observability

Every model call is kept — prompt, reply, thinking, tokens, duration, the agent that asked
and the memo step it was for — and every stage, sandbox run, platform check, deploy,
browser check and integration call is timed. The run page shows them under **Model
traces**; `/observability` shows the platform: a health strip with each dependency's
latency; model calls, tokens and model time with a trend line each; median, p90 and p99
response time; how busy the GPU was; model activity over the window; model time by agent;
where the time goes by kind of work; runs with their status; and recent errors grouped by
run. The window is 6 hours to 7 days and the page refreshes every 15 seconds. The same spans go to Jaeger over OTLP and the same counters to
Prometheus, with a Grafana dashboard provisioned:

| URL | What |
|---|---|
| http://localhost:3000/observability | The platform's own view, from Postgres |
| http://localhost:16686 | Jaeger: traces per run, stage and model call |
| http://localhost:3030 | Grafana (`poiesis` / `poiesisdev`): the "Poiesis platform" dashboard |
| http://localhost:9090 | Prometheus |
| http://localhost:8080/health/deep | Postgres, Redis, Neo4j, Ollama, Docker, Qdrant, probed |
| http://localhost:8080/metrics | The Prometheus exposition |

`GET /api/runs/{id}/traces` lists a run's calls and spans, `/traces/{call_id}` returns one
call with its full prompt and reply, and `/usage` adds a run up. Set `POIESIS_LOG_FORMAT=json`
for a log shipper; every line carries the run and stage it belongs to.

## Git

Set `GIT_REMOTE_TEMPLATE` (and `GIT_TOKEN` for HTTPS) and every run's workspace is pushed as
it is built: branch `run/<id>` after the scaffold and after every story, a tag `v<version>`
at release. On GitHub, with `GITHUB_OWNER` set, a repository that does not exist is created,
and the release opens a pull request into the default branch — or becomes the default
branch, for a repository the run created. `{slug}` in the template is the product name, so
one repository per product is the default and one per run is `{run_id}` away. A push that
fails is a warning in the run's log, never a failed run.

## Knowledge

The Architect's reuse check searches the graph by word (Neo4j full-text) and by meaning
(Qdrant, embedded with `nomic-embed-text`): components from your indexed portfolio, plus
what past runs built, the decisions they recorded and the **lessons** they learned — one
actionable sentence per story that failed or needed repairs, distilled at harvest. The
Developer is shown the lessons that apply to each story before it writes it. `/knowledge`
searches all of it; `POST /api/knowledge/reindex` embeds the portfolio after the indexer runs.

## Engine

One run drives at a time by default (`POIESIS_MAX_CONCURRENT_RUNS`); the rest queue with a
visible position and start as slots free. A run can be stopped from its page and continued
later from its last checkpoint. Everything non-deterministic is memoised per step, so a
replay after a gate, a restart or a retry never re-spends a model call.

## Seeing what a run built

Every run starts its application before the release decision, so the release gate arrives
with a link — and by then a headless browser has already opened every screen against the
running API and screenshotted it, so you are deciding on evidence, not a promise. The run
page shows it under **Running application**, and every app is listed at
http://localhost:3000/apps with Stop and Redeploy. Apps take a port from 8100-8199 and bind
to 127.0.0.1: they are unauthenticated, model-written code, so they stay off your network
until access control exists. Runs that finished before this existed can be started from
their run page.

Generated frontends share one design system (`scaffolds/web-app/frontend/styles.css`) —
color, elevation and motion tokens, dark-mode aware, no external fonts or CDNs, since a
generated app runs with no internet access. Stories compose it (`panel`, `card`, `badge`,
`empty-state`, `spinner`, …) rather than writing their own CSS, so every generated app looks
like a finished product on day one, not a wireframe.

### Codebase maps (ArchiLens)

Details: [docs/CODEMAPS.md](docs/CODEMAPS.md).

Every generated codebase is drawn by [ArchiLens](https://github.com/saurabh-oss/archilens)
(`archilens` on PyPI) at http://localhost:3000/codebases, and each run page links to its
own map. A map has four views:

- **Runtime topology**, read from `docker-compose.yml` and the gateway's `nginx.conf`.
- **Modules & stories**: every screen and story API grouped by the story it delivers, with
  the HTTP calls between them. Click a box for its endpoints, its calls and its source files;
  calls to endpoints nobody serves are flagged.
- **Data model**, drawn from `db/init.sql`: declared foreign keys are solid lines, and
  `*_id` columns that name a table are dashed.
- **Request flows**: sequence diagrams from each story endpoint down to the database.

ArchiLens on its own groups files by their top two folders. Poiesis hands it the app's real
shape instead (`app/workspace/codemap.py`), and ArchiLens does the analysis and draws the
module, component (L2) and flow (L3) diagrams.

Its AI features (module summaries, request flows, pattern detection) run on the platform's
local model, through the same one-call-at-a-time gate as every agent. No hosted model is
called.

When maps are drawn:

- The static map is redrawn after every deploy, which takes seconds.
- The model's explanations wait until the run goes idle. They take about 6 minutes for a
  10-story app. They are turned on by `codemap.ai` in `packs/mvp.yaml` and can be run from
  the map page with **Explain with local AI**.
- Explanations of modules whose code has not changed are reused.
- The raw ArchiLens snapshot is served at `/api/runs/{id}/codemap/snapshot`.

## Plane boards (self-hosted, open source)

Details and troubleshooting: [docs/PLANE.md](docs/PLANE.md).

Every idea gets its own project in [Plane](https://plane.so), an open-source tracker that
works like Jira and runs on this machine. The console's **Boards** page
(http://localhost:3000/boards) shows every idea's board, and each run page has a board card.

The mapping:

| Poiesis | Plane |
|---|---|
| The run | a **Project**, which opens as a board grouped by state |
| Backlog epic | a **Module** |
| Backlog story (narrative, acceptance criteria, points, priority) | a **Work item** in its module |
| Sprint one | a dated **Cycle** holding exactly its stories, which move to Todo |
| Story being built / green / red | **In Progress** / **Done** with what was verified / stays in progress, labelled `poiesis-red`, with the failure |
| Release | a **Release** work item linked to the running app |

Plane runs as its own compose project on http://localhost:8200:

```bash
cp infra/plane/plane.env.example infra/plane/plane.env        # then set the two secret keys
docker compose -f infra/plane/docker-compose.yml --env-file infra/plane/plane.env -p plane up -d
python scripts/plane-bootstrap.py      # admin, workspace, API token -> .env; prints the sign-in
docker compose up -d orchestrator
curl -X POST localhost:8080/api/plane/sync                      # mirror every past run
```

New runs mirror themselves. Like the Jira mirror, Plane is never a dependency: if it is
down or refuses a call, the run's log gets a warning and the run carries on. Nothing is
duplicated when a gate replays a stage, because every object is created once under a
remembered key, and work items and modules carry an external id that Plane will not
accept twice.

Plane's API cannot choose how a project opens, so new projects are switched to a board
through Plane's api container (`PLANE_API_CONTAINER`, default `plane-api-1`).

## Jira

Set `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN` and `JIRA_PROJECT_KEY` in `.env`
(see `.env.example`) and every run is mirrored into that Jira Cloud project as it happens:

| Poiesis | Jira |
|---|---|
| The run (product vision, scope, metrics) | **Initiative** |
| Backlog epic | **Epic**, under the initiative |
| Backlog story (acceptance criteria, estimate) | **Story**, under its epic, with story points |
| Sprint one | A **Sprint** on the project's scrum board, started, holding exactly its stories |
| Story being built / green / red | **In Progress** / **Done** with what was verified / stays open, labelled `poiesis-red`, with the failure |
| Release | Comment and a link to the running app on the initiative; sprint closed |

Status changes follow each workflow's status *categories*, so a project whose "Done" is
called "Closed" still works. Initiatives need Jira Premium with the hierarchy configured;
without them epics are created with no parent and the run's log says so. Jira is a mirror,
never a dependency: an outage, a revoked token or a refused field costs a warning, not the
run. Nothing is duplicated when a gate replays a stage.

```bash
docker compose exec orchestrator python -m app.integrations.jira check          # verify the project
docker compose exec orchestrator python -m app.integrations.tracker backfill <run_id>   # mirror a past run
docker compose exec orchestrator python -m app.integrations.selftest            # no Jira needed
docker compose exec orchestrator python -m app.selftest_core                    # engine, model client, traces, git, vectors
```

`GET /api/runs/{id}/tracker` returns a run's Jira keys and links;
`POST /api/runs/{id}/tracker/sync` mirrors a past run. Neither makes a model call.

## Repository layout

```
services/orchestrator        FastAPI + LangGraph agent value stream
  app/main.py                API assembly, startup recovery
  app/api/                   HTTP routes: runs, gates, uploads, deployments, codemap, plane, knowledge, observability
  app/graph/                 The value stream: nodes (discovery … ship), engine, checkpoint memo
  app/agents/                Agent classes; prompts/ (one file per agent, plus ux_playbook.md); schemas.py
  app/ingest/                PDF, DOCX (tables in order), images, audio, URLs → cited fragments
  app/workspace/             Per-run repository, sandbox runner, checks, seeding, deployment,
                             browser check, codemap (ArchiLens)
  app/integrations/          Plane (plane.py), Jira (jira.py, tracker.py), Git remote (gitremote.py)
  app/kg/                    Neo4j client and the Qdrant vector index
  app/llm.py                 Native Ollama client (schema-constrained, one call at a time), LiteLLM for hosted profiles
  app/telemetry.py           Spans, model-call traces, Prometheus metrics, OTLP export
  app/selftest*.py           Self-tests: build-time checks; engine, model client, maps, Plane
services/indexer             Portfolio scanner → knowledge graph
services/ui                  Next.js control room
infra/plane/                 Self-hosted Plane (compose file, env example)
scripts/                     restart-ollama.ps1, bootstrap.ps1, plane-bootstrap.py, index-local.ps1,
                             fetch-model.py, raise-gpu-timeout.ps1
observability/               Prometheus config, Grafana datasource and dashboard
scaffolds/web-app/           What every generated app starts from: gateway, api, data, db, UI kit
                             (ui.js), shell (app.js), design system (styles.css)
packs/                       Domain packs: gates, build and review policy, definition of done
                             (both are mounted into the orchestrator by the compose file; the copies
                             under services/orchestrator/ are what its image carries without the mount —
                             keep them in step)
docs/                        Setup, operations, architecture, agents, checks, API, maps, boards, case study
workspaces/                  One git repository per run (not committed)
```

## The name

Aristotle separated *praxis* from *poiesis*. Praxis is action whose end is the doing
itself. Poiesis is action that brings something into being outside the maker — the word
behind *poetry*, but it meant making of any kind.

The distinction maps onto the two projects. Praxis Linux is the system you work through.
Poiesis is the system that produces. If a third ever needs naming, *theoria* is still free.

## Licence

Apache-2.0.
