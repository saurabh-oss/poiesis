# Running Poiesis on a Windows gaming laptop

Everything runs locally. With `POIESIS_LLM_PROFILE=local` no brief, no document and no line of
generated code leaves the machine — which is the reason this is worth running on your own
hardware rather than as a hosted trial.

## 1. Prerequisites

| Component | Why | Install |
|---|---|---|
| WSL2 | Docker's Linux backend, and where the containers actually run | `wsl --install` in an elevated PowerShell, then reboot |
| Docker Desktop | Runs the stack, and the sandbox the generated code executes in | https://docs.docker.com/desktop/install/windows-install/ |
| Ollama for Windows | The models. Runs **natively on the host**, not in Compose | https://ollama.com/download/windows |
| NVIDIA driver ≥ 550 | CUDA for Ollama | GeForce Experience or the NVIDIA site |
| Git | Cloning your repos for the indexer | https://git-scm.com/download/win |

In Docker Desktop → Settings → Resources, give WSL2 at least **8 CPUs, 24 GB RAM, 120 GB disk**.
Under Settings → General, confirm "Use the WSL 2 based engine" is on.

### Ollama runs on the host, not in a container

Native Ollama gets direct CUDA access without WSL2 GPU passthrough, so there is no `ollama`
service in `docker-compose.yml`. One setting makes it reachable from the containers:

```powershell
setx OLLAMA_HOST 0.0.0.0:11434
```

By default Ollama binds to `127.0.0.1`, which containers cannot reach — everything looks
fine from PowerShell and fails from inside Docker. After setting it, **fully quit Ollama
from the system tray** and relaunch, then confirm:

```powershell
[Environment]::GetEnvironmentVariable("OLLAMA_HOST","User")   # 0.0.0.0:11434
```

If containers still cannot reach it, allow `ollama.exe` through Windows Firewall on private
networks. `scripts\bootstrap.ps1` checks all of this and tells you which half is wrong.

## 2. Clone and configure

```powershell
git clone <your-fork> poiesis
cd poiesis
copy .env.example .env
```

Set `POIESIS_WORKSPACE_HOST_ROOT` to the absolute Windows path of this repo's
`workspaces` folder, e.g. `C:/code/poiesis/workspaces`.

This one is easy to skip and impossible to diagnose from the symptom. Generated tests run
in a throwaway container that the orchestrator launches through the mounted Docker socket —
so it is a *sibling*, and the daemon resolves its bind mount on the host. The orchestrator's
own `/workspaces` path means nothing there; Docker would silently create an empty directory,
pytest would collect no tests, and every story would exhaust its repair attempts trying to
fix code the sandbox cannot see. The build stage now runs a mount preflight and fails with
this explanation instead.

Pick a profile in `.env`:

- `local` — Ollama on your GPU. Nothing leaves the laptop. Use this for anything real.
- `groq` — hosted, free tier, fast. Best for iterating on the pipeline itself, because a
  full run takes minutes instead of an hour. Set `GROQ_API_KEY`.
- `cloud` — Anthropic. Highest quality output for the reasoning agents. Set `ANTHROPIC_API_KEY`.

A practical pattern: develop the pipeline on `groq`, run stakeholder work on `local`.

## 3. Start

```powershell
docker compose up -d
.\scripts\bootstrap.ps1
```

The bootstrap checks the Ollama bridge, pulls the base models (roughly 20 GB, once), builds
the `poiesis-*` variants from `modelfiles/` with a 12k context window, waits for the
orchestrator, and indexes the repositories listed in `services/indexer/portfolio.yaml`.

**Fix those repo URLs before you run it.** They ship as placeholders. The indexer now names
every entry it could not read and exits non-zero, because an empty knowledge graph disables
the reuse check that is the whole point of the platform — silently.

Add anything not on GitHub yet:

```powershell
.\scripts\index-local.ps1 -Path C:\src\meridian -Name "Meridian"
```

## 4. Use it

Open http://localhost:3000 and submit a brief. You will be interrupted roughly five times
across a run — that is the design, not friction. Each interruption is a decision the agents
genuinely cannot make for you.

Other endpoints:

| URL | What |
|---|---|
| http://localhost:3000 | The control room |
| http://localhost:8080/docs | Orchestrator API |
| http://localhost:7474 | Neo4j browser — `neo4j` / `poiesisdev` |
| http://localhost:9001 | MinIO console — `poiesis` / `poiesisdev` (not used yet) |
| http://localhost:6333/dashboard | Qdrant (not used yet) |

## 5. Model sizing on a 16 GB GPU

The default 14B models fit comfortably in 16 GB VRAM at Q4. On 8 GB, point the two heavy
roles at 7B builds — create the variants first so they keep the larger context window:

```powershell
"FROM qwen2.5:7b-instruct`nPARAMETER num_ctx 12288" | Out-File -Encoding ascii modelfiles\reasoning-7b
ollama create poiesis-reasoning-7b -f modelfiles\reasoning-7b
```

then in `.env`:

```
POIESIS_MODEL_REASONING=ollama/poiesis-reasoning-7b
POIESIS_MODEL_CODING=ollama/poiesis-coding-7b
```

The Developer agent is the one that degrades most on smaller models. If build stages keep
hitting the repair loop, that is the first thing to raise.

## 6. Troubleshooting

**"The sandbox cannot see the run workspace."** `POIESIS_WORKSPACE_HOST_ROOT` is wrong or
unset. It must be the `workspaces` folder as *Windows* sees it, not as the orchestrator
does. See section 2.

**Build stage fails immediately with a Docker permission error.** The orchestrator launches
sandbox containers through the mounted Docker socket. On Windows, confirm Docker Desktop
exposes the daemon and that the `/var/run/docker.sock` mount in `docker-compose.yml` is present.

**Runs stall with status `waiting`.** A gate is open. The right panel on the run page has it.
Gates survive restarts — the graph is checkpointed in Postgres, so `docker compose restart
orchestrator` resumes exactly where it stopped.

**A run was mid-build when the orchestrator restarted.** It resumes on its own: startup
looks for runs still marked `running`, and continues each from its last checkpointed node.
Runs parked on a gate are left alone, because they are waiting on you rather than on the
process. Note that the compose file runs uvicorn with `--reload`, so editing orchestrator
code mid-run triggers exactly this path.

**Agents return malformed JSON on local models.** Expected occasionally with 7B models. The
JSON parser recovers from fenced and prefixed output; if it still fails, the retry decorator
gives it three attempts. Persistent failures mean the model is too small for that agent role.

**Neo4j will not start.** Usually a stale volume. `docker compose down` then delete
`data\neo4j`.

**A bug you already fixed keeps recurring, unchanged, days later.** After several idle
days Docker's own image store can revert to an older build without any error — the
containers restart fine, `docker compose up -d` reports success, but the orchestrator is
silently running code from before your last several fixes. Postgres and Neo4j data survive
(bind-mounted to `data/` on the host); *images* do not, because they live inside Docker's
own VM. Compare `docker inspect poiesis-orchestrator --format '{{.Created}}'` against the
last time you edited `services/orchestrator`, and if the image predates it,
`docker compose build --no-cache orchestrator` before doing anything else. This is what
`python -m app.selftest` (inside the orchestrator container) is for: it exercises every
build-time check with no model calls, in seconds, so you can confirm the running image
actually behaves the way the source says it should before trusting any run's output.

**A deployed app answers "column ... does not exist" even though the model looks right.**
Postgres only ever runs `db/init.sql` against a brand-new data directory. If a run's app was
deployed before in this same run and the database volume survived, a later story's schema
change never reaches it — the volume is still running whatever `init.sql` said the first
time. The automated deploy inside the build/review loop resets the volume on every pass for
exactly this reason; a manual "redeploy" from the Apps page does not, because that path is
for restarting an already-released app without losing its data.
