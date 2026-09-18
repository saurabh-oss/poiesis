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
| Full local sovereignty, or hosted quality | `local` keeps every brief and every line of generated code on your machine; `cloud` routes the reasoning-heavy agents to a hosted model when convergence quality matters more than sovereignty | LiteLLM model router |

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

  (Qdrant and MinIO are in the compose file but not yet used — see
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

## Repository layout

```
services/orchestrator   FastAPI + LangGraph agent value stream
services/indexer        Portfolio scanner → knowledge graph
services/ui             Next.js control room
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
