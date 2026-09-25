# Poiesis architecture

## The business problem this exists to solve

An organisation with a competent engineering function still loses most of its cycle time
before anyone writes code: turning a stakeholder's intent into something buildable, deciding
what already exists, agreeing what "done" means, and getting a decision when the answer is
genuinely ambiguous. Coding assistants attack the smallest and cheapest part of that.

Poiesis automates the expensive part and keeps the human at exactly the points where a human
changes the outcome.

## Design positions

**One user.** The business stakeholder. There is no product owner seat, no scrum master
seat, no engineer seat. If a role is needed, it is an agent, and its output is an artifact
the stakeholder can read.

**Reuse is an architectural constraint, not a prompt.** The Architect agent cannot design
until it has queried the portfolio knowledge graph, and it must return a verdict per
capability: reuse, extend, or build new — with a written rationale for build new. That
rationale is stored as a `Decision` node and surfaces on the next run.

**Gates are typed records, not chat.** A gate has a kind, a schema, a stated default, and a
recorded response with an actor. This is what makes an autonomous pipeline auditable. Policy
for which gates block lives in a domain pack, so the same engine runs at different autonomy
levels for different parts of an organisation.

**The Tester is not the Developer.** They are separate agents with separate context. The
Tester never sees the Developer's reasoning, so it cannot be argued into accepting the
implementation. The repair loop feeds only pytest output back to the Developer, and the
Developer is forbidden from editing tests.

**The verdict is computed.** The Reviewer scores five weighted dimensions; the ship decision
is arithmetic against a threshold plus a blocker check, not the model's opinion. A model
that wants to ship failing work cannot. The weights and the threshold both come from the
domain pack, so a stricter part of the organisation raises the bar without a code change.

**Rework is scoped, and it carries the reason.** A `rework` verdict returns to build with
the Reviewer's findings attached to the Developer's prompt, and rebuilds only the stories
that pytest or the Reviewer actually faulted — the rest are carried forward. A rework round
that re-sends the original prompt is just a retry, and produces the same code.

**A local model's reply is constrained, not hoped for.** On the local profile every
agent reply is decoded against its JSON Schema (`agents/schemas.py`), so "the model returned
malformed JSON" stops being a failure mode at all. Thinking is per role: on for the agents
that judge (Analyst, Architect, Reviewer), off for the ones that write files. A reply that
spends its whole budget thinking is retried without, and one that runs out of budget is
reported as too long rather than as malformed, because those need different repairs.

**Everything is traced without the nodes knowing.** The engine sets the run in a context
variable before the graph moves; `remember()` sets the memo step; `Agent.json()` sets the
agent; `set_stage()` opens and closes stage spans. A model call deep inside a repair loop is
stored with all four attached, so a bad file is explainable from what the Developer was
shown, and a run's cost is a query.

**Nothing generated runs in the orchestrator.** Every execution is a throwaway container
with no network by default, a memory and CPU cap, a pid limit and a hard timeout. Because
those containers are siblings launched through the Docker socket rather than children, the
workspace bind mount is resolved by the host daemon — so the host path is configured
explicitly and the build stage proves the mount before it trusts a test result.

**A green test suite is not evidence the app works.** pytest builds its database from the
SQLAlchemy models directly; the deployed app runs on `db/init.sql` alone, and a Tester can
seed data in its own fixture that nothing seeds in production. So the build's repair loop
also runs `db/init.sql` against a throwaway Postgres, diffs model columns against the real
schema, and statically checks the frontend (no bundler, no framework — plain JS a Node
sandbox can parse and import) — all before the increment is ever deployed. Then it *is*
deployed, and a headless browser opens every screen against the running API and screenshots
it. The Reviewer is shown what each screen actually displays to a first-time visitor, not
just the code that produced it, and the release gate cannot offer "release" for an app that
is not proven working — only "send it back," "release a smaller base app and drop what
isn't ready," or "hold."

## Component map

| Component | Responsibility | Technology |
|---|---|---|
| Orchestrator | The value stream graph, gates, agent invocation, event emission, one driver per run and a queue for the rest | FastAPI, LangGraph, Postgres checkpointer |
| Model layer | Role-to-model mapping; on `local`, a native Ollama client with schema-constrained decoding, per-role thinking, streaming with an idle timeout; LiteLLM for hosted profiles | `llm.py`, Ollama, LiteLLM |
| Telemetry | Every model call and every stage, sandbox run, deploy and integration call as a stored span; Prometheus metrics; OTLP export | `telemetry.py`, Postgres, Jaeger, Prometheus, Grafana |
| Vector index | Components, past stories, decisions and lessons, recalled by meaning alongside the graph's word match | Qdrant, `nomic-embed-text` |
| Integrations | A project per idea in self-hosted Plane and, when configured, the same in Jira Cloud: the plan and its progress as they happen; Git remote with branch per run, tag and pull request at release | `integrations/plane.py`, `tracker.py`, `gitremote.py`; [PLANE.md](PLANE.md) |
| Code maps | Every generated codebase drawn at four levels — runtime topology, modules by story, data model, request flows — with module summaries and flows written by the local model | ArchiLens 0.2.0, `workspace/codemap.py`, Mermaid; [CODEMAPS.md](CODEMAPS.md) |
| Verification | Static checks, `init.sql` on Postgres, an API smoke run on a throwaway Postgres, a Node check of every screen, and a real browser that opens and uses every screen | `workspace/checks.py`, `browser_check.py`, Playwright; [CHECKS.md](CHECKS.md) |
| Intake | Documents, images, audio, URLs and text into cited evidence fragments | pypdf, python-docx, faster-whisper, vision model |
| Portfolio graph | Projects, components, capabilities, technologies, decisions, reuse edges | Neo4j |
| Indexer | Repository → component-level graph nodes | tree-sitter, GitPython |
| Workspace | Per-run git repository; commits are the build audit trail | GitPython |
| Sandbox runner | Isolated execution of generated code and tests | Docker |
| Event bus | Agent narration to the live tape and the audit log | Redis pub/sub, Postgres |
| Control room | Briefs and runs, gates, running apps, boards, codebase maps, the portfolio and observability | Next.js 14, Tailwind in the Spectrum palette, Mermaid |

## The graph

```
intake → discovery → vision → backlog → architecture → sprint → scaffold → foundation → build → deploy → review
                                            ▲                                        │
                                            │                          ┌── rework ◄──┤ (bounded rounds)
                                            │                          ▼             │
                                            └────────────────────── build            ▼
                                                                                   release → harvest
                                                                                      │
                                                                       ┌── rebuild ◄──┤ (bounded, human-triggered)
                                                                       ▼
                                                                     build
```

`scaffold` renders a working skeleton without a model call; `foundation` (when the pack
enables it, as `packs/mvp.yaml` does) then lays the whole data model from every story at once
and generates the demonstration data through a checked `db/seed.py`, so every story that
follows builds a screen over tables that exist, hold believable rows, and are already served
by the generic data API. A rework round returns to `build`, never to `foundation`.

`deploy` starts the increment as its own Compose project on the host — every automated pass
resets its database to a fresh volume first, since `db/init.sql` only ever runs against an
empty one and a stale schema from an earlier round would otherwise survive silently — then
opens every screen in a real browser before `review` ever sees the diff. It also redraws the
run's codebase map; the local model's explanations of it wait until the run is idle, so they
never compete with a build for the GPU.

Gates, and what each actually decides:

| Gate | Stage | The decision only a human can make |
|---|---|---|
| `clarify` | discovery | What the brief left ambiguous, where guessing wastes days |
| `approve_vision` | vision | Whether the platform understood the problem at all |
| `approve_backlog` | backlog | Priority, and what is deliberately out of scope |
| `approve_architecture` | architecture | Whether a "build new" verdict is acceptable |
| `approve_sprint` | sprint | Scope of the first increment (auto by default) |
| `failed_story` | build | Carry on, drop the story, or stop the sprint |
| `approve_release` | release | Release it, release a smaller *base app* dropping whatever isn't ready (a guaranteed non-empty outcome — see below), send it back for another bounded build round, or hold. Never auto. |

Every gate raises a LangGraph `interrupt` against a Postgres checkpoint, so the pipeline can
sit paused for a week, survive a restart, and resume at the exact node.

## A run always has a base to hand off

Automatic rework is bounded (`build.max_rework_rounds`), and so is how many times a human
can send an increment back from the release gate (`review.max_human_rebuilds`) — an
autonomous pipeline that can loop without limit is not autonomous, it is unsupervised spend.
When those rounds are exhausted and the increment still is not fully working, the release
gate's "release a base app" option drops whatever stories are broken — but only files a
single story exclusively owns; anything a healthy story still shares with a broken one is
left in place rather than removed out from under it — redeploys what remains on a fresh
database, and re-verifies it before calling it released. If what is left still does not
work, it says so and holds rather than pretend. Dropped stories are named in the release
notes as follow-up work for the next run, so the stakeholder always gets *something* to open
and hand off, never just an audit trail of iterations that consumed budget and produced
nothing runnable.

## The closing loop

`harvest` writes the run's capabilities, technologies, stories, architecture decisions and
outcome (score, verdict, which stories shipped) back into the knowledge graph, embeds the
stories and decisions into the vector index, and distils one **lesson** per story that
failed or needed repairs: a sentence in the imperative that would have prevented it. The
next run's Architect queries a graph that now contains this one, by word and by meaning,
and its Developer is shown the lessons that apply to each story before writing it. Reuse
quality and build quality both compound with usage, and that compounding is the part a
competitor cannot copy by writing better prompts.

## Where the work is tracked

The plan and its progress are mirrored where the organisation already looks:

- **Plane**, self-hosted and open source: every idea its own project and board — epics as
  modules, stories as work items with acceptance criteria, points and priority, sprint one as
  a cycle, cards moving to In Progress and Done as stories are built and go green, red ones
  labelled with the failure. See [PLANE.md](PLANE.md).
- **Jira Cloud**, when configured: initiative, epics, stories, a started sprint.
- **A Git remote**: branch `run/<id>` pushed after the scaffold and every story, tag at
  release, pull request on GitHub.

All three follow the same two rules: never stop a run — an outage is a warning in the log —
and never duplicate, however many times a gate replays a node.

## Where existing projects plug in

| Project | Role inside Poiesis | Status |
|---|---|---|
| ArchiLens | Draws every generated codebase (module, component and flow diagrams), fed Poiesis's module graph and explained by the local model through its pluggable AI client. Replacing the indexer's AST walker with its parser is still open | **Integrated** — [CODEMAPS.md](CODEMAPS.md) |
| TestLoom | Replace the Tester agent's generation step; it already does requirements-to-traceable-tests | Direct fit |
| ForgeAI | The weighted verdict model in `ship.py` is ForgeAI's scoring approach applied to an increment rather than a pipeline | Pattern reused |
| TraceGuard AI | Replace the inline repair loop with TraceGuard's failure-to-PR remediation | Phase 2 |
| GEPA LangChain Lab | Optimise the eight agent prompts against run outcomes as the eval signal | Phase 3 — the highest-leverage integration |
| SentinelShield | Runtime anomaly detection on released increments | Phase 4 |
| AgentAxis | Its Domain Pack format is the pattern `packs/` follows | Pattern reused |

## What the DupeGuard run taught

Every screen of the DupeGuard app worked and the Reviewer scored it 90.8, yet three stories
had each implemented the BRD's duplicate-scoring rule differently
([case study](CASE-STUDY-DUPEGUARD.md)). Two consequences for the design:

- **Business rules that several stories share need one home.** A story is built in its own
  context; nothing today makes two stories agree on a rule. The foundation stage already
  writes the data model for every story at once, and should likewise write the domain module
  for the rules the brief states, which stories import rather than restate.
- **A working screen is not a working rule.** The browser check and the Reviewer judge the
  experience. Acceptance criteria that state numbers and rules ("a score of 85 or more
  closes the ticket", "precision counts undone closures") should become executable checks
  against the running app, as they were written by hand for DupeGuard.

Both are now built: the domain stage of the enterprise pack writes the rules once
([ENTERPRISE.md](ENTERPRISE.md)), and acceptance checks run against the deployed app
([CHECKS.md](CHECKS.md#acceptance-checks)). The enterprise run then taught a third lesson: a
backlog can quietly leave out a screen the brief names, so the backlog and the domain are
checked against an inventory of the brief's requirements ([CHECKS.md](CHECKS.md#requirements-coverage)).

## Deliberately not built yet

- Multi-tenant SaaS. Local first; the seams (workspace root, pack selection, run ownership)
  are placed for it but nothing is multi-tenant today.
- Parallel story execution. Sequential builds are slower but the failure modes are legible,
  which matters more while the pipeline is being tuned.
- Deployment beyond one machine. Each run starts its application locally before the release
  decision (compose project `poiesis-run-<id>`, a port from 8100-8199, bound to 127.0.0.1) and
  a proven-working app is a ship blocker, but nothing is reachable from other machines or
  authenticated (Phase 5), and there is no remote hosting.
- Authentication on the orchestrator API and the control room. Local first; put it behind
  a reverse proxy with SSO before exposing it beyond one machine.
- Object storage for artifacts. MinIO is in the compose file and unused; artifacts are JSON
  columns in Postgres, which is the right answer until something binary needs storing.
