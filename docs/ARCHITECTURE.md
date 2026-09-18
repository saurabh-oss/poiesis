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
| Orchestrator | The value stream graph, gates, agent invocation, event emission | FastAPI, LangGraph, Postgres checkpointer |
| Model router | Role-to-model mapping; one env var moves the platform between local and hosted | LiteLLM |
| Intake | Documents, images, audio, URLs and text into cited evidence fragments | pypdf, python-docx, faster-whisper, vision model |
| Portfolio graph | Projects, components, capabilities, technologies, decisions, reuse edges | Neo4j |
| Indexer | Repository → component-level graph nodes | tree-sitter, GitPython |
| Workspace | Per-run git repository; commits are the build audit trail | GitPython |
| Sandbox runner | Isolated execution of generated code and tests | Docker |
| Event bus | Agent narration to the live tape and the audit log | Redis pub/sub, Postgres |
| Control room | Value stream visualisation, artifact rendering, gate resolution | Next.js 14 |

## The graph

```
intake → discovery → vision → backlog → architecture → sprint → build → deploy → review
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

`deploy` starts the increment as its own Compose project on the host — every automated pass
resets its database to a fresh volume first, since `db/init.sql` only ever runs against an
empty one and a stale schema from an earlier round would otherwise survive silently — then
opens every screen in a real browser before `review` ever sees the diff.

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

`harvest` writes the run's capabilities, technologies, stories and architecture decisions
back into the knowledge graph. The next run's Architect queries a graph that now contains
this one. Reuse quality compounds with usage, and that compounding is the part a competitor
cannot copy by writing better prompts.

## Where existing projects plug in

| Project | Role inside Poiesis | Status |
|---|---|---|
| ArchiLens | Replace the indexer's AST walker with ArchiLens's parser; use its diagram generation for the architecture artifact | Direct fit |
| TestLoom | Replace the Tester agent's generation step; it already does requirements-to-traceable-tests | Direct fit |
| ForgeAI | The weighted verdict model in `ship.py` is ForgeAI's scoring approach applied to an increment rather than a pipeline | Pattern reused |
| TraceGuard AI | Replace the inline repair loop with TraceGuard's failure-to-PR remediation | Phase 2 |
| GEPA LangChain Lab | Optimise the eight agent prompts against run outcomes as the eval signal | Phase 3 — the highest-leverage integration |
| SentinelShield | Runtime anomaly detection on released increments | Phase 4 |
| AgentAxis | Its Domain Pack format is the pattern `packs/` follows | Pattern reused |

## Deliberately not built yet

- Multi-tenant SaaS. Local first; the seams (workspace root, pack selection, run ownership)
  are placed for it but nothing is multi-tenant today.
- Parallel story execution. Sequential builds are slower but the failure modes are legible,
  which matters more while the pipeline is being tuned.
- Deployment beyond one machine. Each run starts its application locally before the release
  decision (compose project `poiesis-run-<id>`, a port from 8100-8199, bound to 127.0.0.1) and
  a proven-working app is a ship blocker, but nothing is reachable from other machines or
  authenticated (Phase 5), and there is no remote hosting.
- Vector recall over past runs. Qdrant is wired into the stack and unused; the graph is
  carrying retrieval on its own until there is enough run history to justify embeddings.
- Object storage for artifacts. MinIO is in the compose file and unused; artifacts are JSON
  columns in Postgres, which is the right answer until something binary needs storing.
