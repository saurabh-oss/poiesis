# Operating Poiesis day to day

How to start, stop, check and repair a local Poiesis installation. `SETUP-WINDOWS.md` covers
the first install; this covers everything after it.

## What runs where

Poiesis is three groups of processes that start separately. Knowing which group a problem
lives in is most of the diagnosis.

| Group | What | How it runs | Started by |
|---|---|---|---|
| The platform | orchestrator, control room (ui), Postgres, Redis, Neo4j, Qdrant, MinIO, Jaeger, Prometheus, Grafana | Compose project `poiesis` (`docker-compose.yml`) | `docker compose up -d` |
| The models | Ollama and its model runners | Native Windows process on the host | `scripts\restart-ollama.ps1` |
| The tracker | Plane: web, api, workers, its own Postgres, Valkey, RabbitMQ, MinIO, Caddy proxy | Compose project `plane` (`infra/plane/`) | `docker compose -p plane … up -d` (below) |
| Generated apps | one Compose project per run: gateway, api, data, db | `poiesis-run-<run id>` | the deploy stage, or `POST /api/runs/{id}/deploy` |

### Ports

| Port | What |
|---|---|
| 3000 | Control room (Next.js) |
| 8080 | Orchestrator API (`/docs` for OpenAPI) |
| 8100–8199 | Generated applications, one port per run, bound to 127.0.0.1 |
| 8200 | Plane web UI and API |
| 11434 | Ollama |
| 7474 / 7687 | Neo4j browser / Bolt |
| 6333 | Qdrant |
| 16686 | Jaeger |
| 3030 | Grafana (`poiesis` / `poiesisdev`) |
| 9090 | Prometheus |
| 5432, 6379 | Postgres, Redis (platform) |
| 9000 / 9001 | MinIO API / console (unused) |

## Starting everything after a reboot

Docker Desktop does not start on its own on this machine, and Ollama must be started by the
script rather than the tray app. In order:

```powershell
# 1. Docker Desktop (wait until `docker info` answers)
Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"

# 2. Ollama: kills the tray app and any orphaned runners, starts `ollama serve` with the
#    settings Poiesis needs (see below)
powershell -ExecutionPolicy Bypass -File scripts\restart-ollama.ps1

# 3. The platform
docker compose up -d

# 4. Plane (optional: only if you use the Boards page)
docker compose -f infra/plane/docker-compose.yml --env-file infra/plane/plane.env -p plane up -d
```

Generated apps that were running come back by themselves: every service has
`restart: unless-stopped`, and the orchestrator brings running deployments back at startup
(`POIESIS_RESTART_DEPLOYMENTS_ON_BOOT`, in the background so `/health` answers at once). A
run that was mid-build resumes from its last checkpoint; a run parked on a gate waits for
you.

Check it is all there:

```powershell
curl http://localhost:8080/health/deep       # Postgres, Redis, Neo4j, Ollama, Docker, Qdrant
curl http://localhost:11434/api/version
docker compose -p plane ps                    # every Plane service Up
```

or open http://localhost:3000/observability, whose health strip probes the same dependencies.

## Ollama: why the restart script exists

`scripts\restart-ollama.ps1` is the only supported way to start the models. It:

- **kills orphaned `llama-server` processes.** Killing `ollama.exe` leaves its model runners
  alive, each holding GPU memory. Three orphans once cut prompt processing from about 1,200
  to 60 tokens a second and finally stopped the model loading at all.
- **starts without `OLLAMA_KV_CACHE_TYPE` and `OLLAMA_FLASH_ATTENTION`.** The tray app sets
  them; both slow the Qwen3.6 35B-A3B hybrid model on this card.
- **binds to `0.0.0.0:11434`** so the containers can reach it.
- **keeps one model loaded for 30 minutes** (`OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_KEEP_ALIVE=30m`).
- **leaves 1.5 GB of VRAM to the display driver** (`OLLAMA_GPU_OVERHEAD=1610612736`). With
  the GPU filled to the brim the driver bugchecked three times during long runs (0x116
  VIDEO_TDR_FAILURE, the last with STATUS_INSUFFICIENT_RESOURCES).

All model calls from the platform go through one gate (`llm._LOCAL_GATE`), so a code map
explanation, a reseed and a build never ask the GPU for two things at once.

## Plane: first start and reset

```powershell
copy infra\plane\plane.env.example infra\plane\plane.env   # then set SECRET_KEY and LIVE_SERVER_SECRET_KEY
docker compose -f infra/plane/docker-compose.yml --env-file infra/plane/plane.env -p plane up -d
python scripts\plane-bootstrap.py       # admin, workspace, API token -> .env; prints the sign-in
docker compose up -d orchestrator       # picks up PLANE_* from .env
curl -X POST http://localhost:8080/api/plane/sync   # mirror every past run
```

The bootstrap is idempotent: run it again at any time to reset the admin password to the one
in `plane.env`, recreate a lost token, or switch every project back to the board layout.

To start Plane from nothing (all projects gone), delete its volumes and the orchestrator's
memo of what it created, then mirror again:

```powershell
docker compose -p plane down -v
docker compose exec orchestrator python -c "from app.db import NodeCache, session; s=session().__enter__(); s.query(NodeCache).filter(NodeCache.key.like('plane:%')).delete(synchronize_session=False); s.commit()"
```

then the four commands above. See `PLANE.md` for how the mirror works.

## Everyday tasks

| Task | How |
|---|---|
| Start a run | Home page, or `POST /api/runs` then `POST /api/runs/{id}/start` (see `API.md`) |
| Answer a gate from a script | `GET /api/runs/{id}/gates/open`, then `POST /api/runs/{id}/gates/resolve` with `{"decision": …, "notes": …}` |
| Continue a failed or cancelled run | `POST /api/runs/{id}/retry` — keeps everything already done |
| Restart an app on a fresh database | `POST /api/runs/{id}/deploy?fresh=true` (drops its volume; `init.sql` runs again) |
| Restart an app keeping its data | Apps page → Redeploy, or `POST /api/runs/{id}/deploy` |
| Regenerate an app's demonstration data | `POST /api/runs/{id}/reseed`, then deploy with `fresh=true` |
| Redraw a codebase map | Codebases page → Draw map, or `POST /api/runs/{id}/codemap?ai=false` (seconds); `ai=true` adds the local model's explanations |
| Mirror a run into Plane | Boards page → Mirror to Plane, or `POST /api/runs/{id}/plane/sync` |
| Stop an app | Apps page → Stop, or `POST /api/runs/{id}/deployment/stop` |
| Build enterprise apps instead of MVPs | `POIESIS_PACK=packs/enterprise.yaml` in `.env`, then `docker compose up -d orchestrator`; applies to runs started afterwards ([ENTERPRISE.md](ENTERPRISE.md)) |
| Make connectors live for every enterprise app | `APPS_JIRA_BASE_URL=…` and the rest in `.env` ([CONNECTORS.md](CONNECTORS.md#going-live)), restart the orchestrator, redeploy the app |
| Sign in to an enterprise app | One-click personas on its sign-in page; `AUTH_PERSONAS=off` and `AUTH_ADMIN_PASSWORD` for passwords |

A fresh redeploy resets a demo: DupeGuard, for example, comes back with 22 unscanned tickets
for "Scan now" every time.

## Self-tests

Run these after changing orchestrator code, and whenever a run behaves as if an old bug is
back (see "stale image" below):

```powershell
docker compose exec orchestrator python -m app.selftest_core           # engine, model client, traces, git, vectors, code maps, check rules, Plane helpers (182 checks)
docker compose exec orchestrator python -m app.selftest                # every build-time check, no model calls
docker compose exec orchestrator python -m app.selftest_enterprise     # connectors (live, against local stand-ins), the kernel through three personas, the domain stage's checks (78 checks)
docker compose exec orchestrator python -m app.integrations.selftest   # the Jira mirror against a fake Jira
docker compose exec orchestrator python -m app.integrations.plane check  # Plane answers with the configured token
```

`selftest_core` and the Jira self-test blank `PLANE_API_TOKEN` for their duration: they drive
the tracker hooks with made-up runs, which must never reach the real Plane.

## Logs and traces

| Question | Where to look |
|---|---|
| What did a run do, in order? | Its run page's activity feed, or `GET /api/runs/{id}/events` |
| Which model call produced this file? | Run page → Model traces; `GET /api/runs/{id}/traces/{call_id}` has the full prompt and reply |
| Where does the time go? | http://localhost:3000/observability; Jaeger for one run's trace tree |
| Why did the orchestrator return 500? | `docker compose logs orchestrator --since 10m` |
| Why is a generated app down? | `docker compose -p poiesis-run-<id> ps` and `… logs backend` |
| Is Plane healthy? | `docker compose -p plane ps`; `docker compose -p plane logs api --since 10m` |

## Troubleshooting

**The machine bugchecked during a run.** Start everything again in the order above. Check
that Ollama was started by the script (`OLLAMA_GPU_OVERHEAD` is only set there). Then
`POST /api/runs/{id}/retry` for any run that shows `failed` with a connection error; it
continues from its last checkpoint and memoised model calls are not repeated.

**Prompt processing is suddenly slow, or the model will not load.** Orphaned runners. Run
`scripts\restart-ollama.ps1`; it refuses to start while any `llama-server` survives.

**A run shows "Ollama is not reachable".** Ollama was started from the tray (bound to
127.0.0.1) or not at all. Run the restart script, then retry the run.

**A bug you fixed is back.** Docker can silently revert to an older orchestrator image
after idle days. `docker inspect poiesis-orchestrator-1 --format '{{.Created}}'`; if it
predates your last change, `docker compose build orchestrator && docker compose up -d orchestrator`.

**A story is red but its screen works.** Read the reason in the build stage. Three platform
checks produced false positives this way and were fixed (see `CHECKS.md`); if you find a
fourth, the fix belongs in the check, not in the story.

**The Boards page says Plane is not connected.** `PLANE_API_TOKEN` is empty in the
orchestrator's environment: run `scripts\plane-bootstrap.py`, then
`docker compose up -d orchestrator`.

**Plane sync warnings with 429.** Plane throttles per API key. The client backs off and
retries, and `plane.env` raises the limit to 6000/minute; if you lowered it, a bulk sync of
many runs can still hit it. Run `POST /api/plane/sync` again; nothing is duplicated.

**A Plane project opens as a list, not a board.** The orchestrator could not reach Plane's
api container (`PLANE_API_CONTAINER`, default `plane-api-1`). Run
`python scripts\plane-bootstrap.py`; it switches every project to the board layout.

**A code map says "ArchiLens is not installed".** The orchestrator image predates the
dependency: `docker compose build orchestrator`.

**A release is held although the app works.** The release gate will not offer "release"
while any story is red. Either fix the story and redeploy, or answer the gate with the
"release a base app" option, which drops only what is broken. The run page explains which
stories hold it.

## Backups

Platform state lives in bind mounts under `data/` (Postgres, Neo4j, Qdrant) and in
`workspaces/` (one git repository per run). Plane keeps its data in Docker volumes of the
`plane` project (`plane_pgdata`, `plane_uploads`, …). Stop the stacks, then copy `data/` and
`workspaces/`; for Plane, `docker run --rm -v plane_pgdata:/v -v %cd%:/b alpine tar czf /b/plane-pg.tgz -C /v .`.
