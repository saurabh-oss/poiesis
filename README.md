# Poiesis — Autonomous Engineering Platform

One user. One input. A working, tested, deployed increment — with an audit trail back to the sentence that asked for it.

Poiesis takes whatever a business stakeholder already has (a document, a whiteboard photo, a recorded call, a link, three lines of text) and runs it through a governed agent value stream: understand → clarify → vision → backlog → architecture → sprint → build → test → review → release. Humans are not in the loop for every token; they are in the loop at **typed gates** where a decision actually changes the outcome.

The thing that makes Poiesis different from every "prompt to app" tool is the **Portfolio Knowledge Graph**. Before any agent designs or writes anything, it must ask the graph what already exists. Reuse is enforced by architecture, not encouraged by a prompt.

---

## Business capabilities

| Capability | What it means to the business | Where it lives |
|---|---|---|
| Intent capture from any source | Stakeholders don't write requirements docs; they talk, sketch, and forward links | `ingest/` + Analyst agent |
| Adversarial clarification | The platform interrogates gaps and contradictions before spending build cycles | Analyst agent, `clarify` gate |
| Traceable product definition | Every story traces to a captured stakeholder statement; every commit traces to a story | Product Owner agent + KG |
| Enforced reuse | New work is checked against an indexed portfolio before it is designed | Portfolio Knowledge Graph |
| Governed autonomy | Agents run unattended between gates; gates are typed, logged, and reversible | Orchestrator interrupts |
| Verified, not just tested | Every increment is deployed and opened in a real browser before a human ever sees the release decision; the release gate cannot offer "release" for an app that is not proven working | `deploy` stage, headless-browser check |
| A guaranteed base to hand off | Rework and human rebuilds are bounded; if the increment still isn't fully working when that budget runs out, the release gate can ship a smaller *base app* — dropping only what's broken — instead of ending in pure iteration | `approve_release` gate |
| Evidence-backed release | A release verdict is a computed artifact, not an opinion | Reviewer + Release agents |
| Full local sovereignty, or hosted quality | `local` keeps every brief and every line of generated code on your machine, on models whose replies are constrained to each agent's schema; `cloud` routes the agents to a hosted model when that matters more than sovereignty | `llm.py`: native Ollama client, LiteLLM for hosted profiles |
| Compounding memory | Every finished run adds what it built, decided and learned; the next run's Architect and Developer are shown the components, decisions and lessons that apply, by word and by meaning | Neo4j graph + Qdrant vector index |
| Work tracked where the organisation tracks it | Initiative, epics, stories and sprint in Jira; branch, tag and pull request on the Git remote, as the run goes | `integrations/tracker.py`, `integrations/gitremote.py` |
| Explainable, measurable | Every model call kept with its prompt and reply; every stage, sandbox run and deploy timed; traces to Jaeger, metrics to Prometheus and Grafana | `telemetry.py`, `/api/runs/{id}/traces`, `/metrics` |

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
  build   ──► Jira (initiative, epics, stories, sprint) + Git remote (branch, tag, PR)

  (MinIO is in the compose file but not yet used — see
   "Deliberately not built yet" in docs/ARCHITECTURE.md)
```

## Quick start (Windows)

See `docs/SETUP-WINDOWS.md`. Short version:

```powershell
git clone <this repo> poiesis; cd poiesis
copy .env.example .env      # set POIESIS_LLM_PROFILE and POIESIS_WORKSPACE_HOST_ROOT
docker compose up -d
.\scripts\bootstrap.ps1     # builds the poiesis-* models, indexes your portfolio
start http://localhost:3000
```

Two settings decide whether the first run works. `POIESIS_WORKSPACE_HOST_ROOT` must be the
absolute path to this repo's `workspaces` folder as **Windows** sees it — the test sandbox
is a sibling container, so the Docker daemon resolves that bind mount on the host, not
inside the orchestrator. And the repo URLs in `services/indexer/portfolio.yaml` must be
real, or the knowledge graph stays empty and every architecture verdict comes back
"build new".

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
traces**; `/observability` shows the platform: dependency health, calls, tokens, where the
time goes, recent errors. The same spans go to Jaeger over OTLP and the same counters to
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
services/orchestrator   FastAPI + LangGraph agent value stream
  app/llm.py            Native Ollama client (schema-constrained), LiteLLM for hosted profiles
  app/telemetry.py      Spans, model-call traces, Prometheus metrics, OTLP export
  app/integrations/     Jira (tracker.py) and Git remote (gitremote.py)
  app/kg/               Neo4j client and the Qdrant vector index
services/indexer        Portfolio scanner → knowledge graph
services/ui             Next.js control room
observability/          Prometheus config, Grafana datasource and dashboard
packs/                  Domain packs: gates, DoD, agent policy
docs/                   Setup, architecture decisions, agent contracts
```

## The name

Aristotle separated *praxis* from *poiesis*. Praxis is action whose end is the doing
itself. Poiesis is action that brings something into being outside the maker — the word
behind *poetry*, but it meant making of any kind.

The distinction maps onto the two projects. Praxis Linux is the system you work through.
Poiesis is the system that produces. If a third ever needs naming, *theoria* is still free.

## Licence

Apache-2.0.
