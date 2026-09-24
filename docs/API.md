# Orchestrator API

Everything the control room does goes through this API, so everything it does can be
scripted. The live OpenAPI description is at http://localhost:8080/docs; this page groups
the endpoints by what you would use them for and says what they do that the schema cannot.

There is no authentication. The orchestrator is meant to be reached from the same machine
(see "Deliberately not built yet" in `ARCHITECTURE.md`).

## Runs

| Method | Path | What it does |
|---|---|---|
| POST | `/api/runs` | Create a run and ingest inline sources. Does **not** start it. Body: `{"title": "...", "sources": [{"kind": "text" \| "url", "value": "...", "label": "..."}]}` |
| POST | `/api/runs/{id}/uploads` | Attach files (multipart, field `files`): PDF, DOCX (tables read in order), images (vision model), audio (Whisper). Returns the fragments each file became |
| POST | `/api/runs/{id}/start` | Start the graph. Queues if another run holds the engine |
| GET | `/api/runs` | Every run, newest first |
| GET | `/api/runs/{id}` | One run: status, stage, summary, every artifact, the workspace file list, the deployment |
| GET | `/api/runs/{id}/events?limit=1500` | The activity feed, oldest first. Each event has `stage`, `agent`, `level` (`info`, `warn`, `error`, `gate`) and `data` |
| GET | `/api/runs/{id}/evidence` | The cited fragments intake produced |
| GET | `/api/runs/{id}/file?path=...` | One file from the run's workspace |
| POST | `/api/runs/{id}/cancel` | Stop where it is; everything built is kept |
| POST | `/api/runs/{id}/retry` | Continue a `failed` or `cancelled` run from its last checkpoint. Memoised model calls are not repeated |
| POST | `/api/runs/{id}/reseed` | Regenerate the demonstration data (Data Designer, local model); the next `fresh` deploy starts from it |
| GET | `/api/runs/stages` | The value stream: stages, agents, which gate each can raise and its mode in the active pack |
| WS | `/ws/runs/{id}` | Live events as they are emitted |

A minimal run from a script:

```bash
RID=$(curl -s -X POST localhost:8080/api/runs -H 'Content-Type: application/json' \
  -d '{"title":"DupeGuard","sources":[{"kind":"text","value":"We waste a quarter of Tier 1 on duplicate tickets..."}]}' | jq -r .id)
curl -s -X POST localhost:8080/api/runs/$RID/uploads -F files=@docs/samples/BRD-SUP-2026-021_DupeGuard_v1.2.docx
curl -s -X POST localhost:8080/api/runs/$RID/start
```

## Gates

| Method | Path | What it does |
|---|---|---|
| GET | `/api/runs/{id}/gates/open` | The gate the graph is actually blocked on, read from the checkpoint: kind, question, the artifact to judge, `options`, `fields` and the `default` answer |
| POST | `/api/runs/{id}/gates/resolve` | Answer it. Body: `{"decision": "...", "notes": "...", "answers": {...}, "actor": "stakeholder"}` — `decision` is one of the gate's `options[].value` |
| GET | `/api/runs/{id}/gates` | Every gate the run raised and how it was answered |

Answering while a previous answer is still being processed returns 409 rather than
starting a second driver on the same run.

## Running applications

| Method | Path | What it does |
|---|---|---|
| GET | `/api/deployments` | Every app with its URL and status (`running`, `starting`, `failed`, `stopped`) |
| GET | `/api/runs/{id}/deployment` | One run's app |
| POST | `/api/runs/{id}/deploy?fresh=false` | Start or restart the app in the background, then open every screen in a browser. `fresh=true` drops its database volume first so `db/init.sql` runs again. 409 while the run is being built |
| POST | `/api/runs/{id}/deployment/stop` | Stop it; its data is kept |
| GET | `/api/runs/{id}/shots/{name}.png` | A screenshot the browser check took |

Every generated app also serves, behind its gateway:

| Path | What |
|---|---|
| `/health` | 200 from the api service, or from the data service when the api is down |
| `/api/platform/modules` | Which story routers failed to import and were left out (`{"broken": {...}}`) |
| `/api/resources` | Every table with its path and columns |
| `/api/<table plural>` | The generic data API: list (`?q=`, `?column=value`, `?sort=-column`, `?limit=`, `?page=`), read, create, update, delete. A filter on a column the table lacks is a 422 |

## Codebase maps (ArchiLens)

| Method | Path | What it does |
|---|---|---|
| GET | `/api/codemaps` | Every run with a codebase, with its map's stats, topology preview and state |
| GET | `/api/runs/{id}/codemap` | The map (views, modules, flows, patterns) and the job's live state |
| POST | `/api/runs/{id}/codemap?ai=true` | Redraw in the background. `ai=false` takes seconds; `ai=true` then asks the local model for summaries, flows and patterns once the run is idle |
| GET | `/api/runs/{id}/codemap/snapshot` | The raw ArchiLens snapshot (nodes, edges, flows) for other tools |

See `CODEMAPS.md` for the document's shape.

## Plane boards

| Method | Path | What it does |
|---|---|---|
| GET | `/api/plane` | Every idea with a backlog: its Plane project, sprint, release item and work items per state group |
| GET | `/api/runs/{id}/plane` | One run's board: columns by state, cards with key, priority, labels, module and link |
| POST | `/api/runs/{id}/plane/sync` | Mirror a past run (safe to repeat, no model calls). 409 while it is being built |
| POST | `/api/plane/sync` | Mirror every past run with a backlog, in the background |

See `PLANE.md`.

## Jira and Git

| Method | Path | What it does |
|---|---|---|
| GET | `/api/runs/{id}/tracker` | Where the run lives in Jira: initiative, epics, stories, sprint |
| POST | `/api/runs/{id}/tracker/sync` | Mirror a past run into Jira |
| GET | `/api/runs/{id}/git` | The run's repository on the Git remote and its pull request |
| GET | `/api/runs/{id}/integrations` | Jira and Git mappings together |

## Knowledge

| Method | Path | What it does |
|---|---|---|
| GET | `/api/knowledge/recall?q=...&limit=8` | What the Architect and Developer would be shown: components by word and by meaning, past stories with their outcome, lessons, decisions |
| GET | `/api/knowledge/search?q=...` | Word match over the graph only |
| POST | `/api/knowledge/preview-reuse` | Body `{"brief": "..."}`: what the Architect would find for this brief now |
| GET | `/api/knowledge/capabilities` | Every capability and the projects that have it |
| GET | `/api/knowledge/stack` | Every technology and how many projects use it |
| GET | `/api/knowledge/lessons` | Lessons distilled from failed or repaired stories |
| GET | `/api/knowledge/stats` | Node counts by type and vectors per collection |
| GET | `/api/knowledge/runs/{id}/graph` | What one run added to the graph |
| POST / GET | `/api/knowledge/reindex` | Embed every component into the vector index (background) / its progress |

## Observability

| Method | Path | What it does |
|---|---|---|
| GET | `/health` | Liveness, profile, pack and engine slots |
| GET | `/health/deep` | Postgres, Redis, Neo4j, models, Docker and Qdrant probed, each with latency and detail |
| GET | `/api/observability/summary?hours=24` | The Observability page's data (below) |
| GET | `/api/runs/{id}/traces` | A run's model calls and spans; `/traces/{call_id}` returns one call with its full prompt, reply and thinking |
| GET | `/api/runs/{id}/usage` | A run's tokens, model time and stage durations |
| GET | `/metrics` | Prometheus exposition |

`/api/observability/summary` returns:

| Field | Meaning |
|---|---|
| `usage` | Calls, tokens in and out, model seconds, tokens per second, errors, truncations; broken down `by_model`, `by_agent` and `spans_by_kind` |
| `activity.series` | The window in 24 equal buckets: calls, errors, tokens and model seconds per bucket |
| `activity.latency` | Model-call duration percentiles in seconds: `p50`, `p90`, `p99`, `max` |
| `activity.gpu_busy_pct` | Model seconds as a share of the window. One local model answers one call at a time, so this is how busy the GPU was |
| `per_run` | Runs with model calls in the window, with title, status, calls, tokens and model seconds |
| `recent_errors` | The last 12 error events |
| `runs_by_status`, `engine` | Run counts by status; active and queued runs and the slot limit |
| `models` | Profile, the model per role, context window, which roles think, and any model not pulled |
| `integrations`, `links` | Which of Jira, Git, Plane, OTLP and vectors are on; URLs of Jaeger, Grafana, Prometheus, Neo4j and Plane |
