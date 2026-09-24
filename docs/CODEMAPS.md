# Codebase maps (ArchiLens)

Every codebase Poiesis generates is drawn as pictures a stakeholder or reviewer can read
without opening a file: how the services connect, which screens and APIs deliver which
story, what the data model holds, and how a request travels from a click to the database.
The drawing is done by [ArchiLens](https://github.com/saurabh-oss/archilens) (`archilens`
on PyPI, 0.2.0), with Poiesis supplying what it knows better than a parser can.

- Gallery of every codebase: http://localhost:3000/codebases
- One run's map: `/runs/<id>/codebase`, and a card on each run page
- Code: `services/orchestrator/app/workspace/codemap.py`, `app/api/codemap.py`,
  console `app/codebases/`, `app/runs/[id]/codebase/`, `components/Mermaid.tsx`

## The four views

| View | Drawn by | From | Shows |
|---|---|---|---|
| **Runtime topology** | Poiesis | `docker-compose.yml`, the gateway's `nginx.conf` | Visitor → gateway (nginx) → api service, with the fallback to the data service; both Python services → PostgreSQL |
| **Modules & stories** | ArchiLens (L1), from Poiesis's module graph | the workspace | Every screen and story API grouped by the story it delivers; the generic data API, data model, shell and database; HTTP calls (dotted, animated), imports, SQL (thick) |
| **Data model** | Poiesis | `db/init.sql` | An entity-relationship diagram: tables, column types, primary keys; declared foreign keys solid, `*_id` columns that name another table dashed |
| **Request flows** | ArchiLens (L3), with the local model | each story router | A sequence diagram per story endpoint, from the request to the database and back |

Clicking a module opens a panel with its summary (from the local model), what it calls,
what it serves, its tables, its request flows, its source files, and its component diagram
(ArchiLens L2: the classes in the module, with each model's columns and each schema's fields
as members). A call to an endpoint nobody serves is shown in red. The map also shows what a
screen does *not* call: on TriageDesk it made plain at a glance why story S10 failed — the
Agent Switch screen never called its own Agent Switch API.

## Why Poiesis hands ArchiLens the module graph

Out of the box ArchiLens groups files by their top two folders. A generated app has
`backend/app/…` and `frontend/screens/…`, so that gives three boxes and no arrows. Poiesis
knows the real shape, and builds it before ArchiLens draws:

1. `analyze_repository()` runs as usual: file discovery, tree-sitter parsing of Python and
   JavaScript, classes, inheritance, metrics.
2. Its folder modules are replaced with the app's parts: one module per screen (titled from
   the screen's `title`), one per story router, and the platform's own groups (shell & UI
   kit, API core, generic data API, data model, database).
3. Edges come from what Poiesis already parses for its checks: every `api()` call in a screen
   is matched to the route that serves it (method included, from `{ method: "POST" }`), each
   router's imports of the models, and the model's SQL to the database.
4. Each story becomes an ArchiLens **capability**: its screen plus the routers only it
   calls. ArchiLens draws capabilities as groups.
5. ArchiLens's generators draw the result; Poiesis restyles it in the Spectrum palette (one
   colour per kind of box) and turns the module view top-to-bottom so ten story groups sit
   side by side instead of in one tall column.

## The local model explains, ArchiLens asks

ArchiLens's AI features — a one-line summary per module, request-flow inference and
architecture pattern detection — accept any client with `complete_with_tool(prompt, tool)`.
Poiesis passes `_LocalModel`, which answers through the platform's own local model
(`llm.complete_json`, schema-constrained to the tool's input schema, the `fast` role) and
through the same one-call-at-a-time gate every agent uses. No hosted model is called, and
ArchiLens's own Anthropic client is never constructed.

The explanations run only once the run is idle (`engine.is_busy` false), so they never slow
a build. For a ten-story app they take about six minutes on the RTX 5070 Ti laptop: 20 module
summaries, 6 flows and the pattern list. A second explanation reuses every summary and flow
whose module's files and size have not changed.

Model-written flows are cleaned before drawing: participant names become valid Mermaid ids
("Database (ticket table)" broke the diagram), statement-ending characters are replaced, and
ArchiLens's open-ended activation bars are dropped. The raw flow is kept, so a flow can be
redrawn without asking the model again.

## When maps are drawn

| Trigger | What |
|---|---|
| Every deploy in the pipeline | The static map (seconds), and — when the pack sets `codemap.ai: true`, as `packs/mvp.yaml` does — the explanations once the run is idle |
| Codebases page → Draw map / Draw every map | Static map |
| Run's map → Redraw / Explain with local AI | Static / with explanations |
| `POST /api/runs/{id}/codemap?ai=...` | Either, from a script |

## The document

One JSON document per run at `workspaces/<run>/.poiesis/codemap.json`, served by
`GET /api/runs/{id}/codemap` (without the snapshot) and `…/codemap/snapshot` (the raw
ArchiLens snapshot only):

| Field | Contents |
|---|---|
| `engine`, `git_ref`, `generated_at` | ArchiLens version, the commit drawn, when |
| `stats` | files, lines, modules, screens, endpoints (story and generic), tables, classes, lines per language, calls to unserved endpoints |
| `views` | Mermaid source of `topology`, `modules` and `data` |
| `modules[]` | id, Mermaid id, name, kind (`screen`, `api`, `generic`, `model`, `db`, `shell`, `core`), files, lines, story capability, summary and responsibility (local model), endpoints served, calls made (with the route matched or `null`), tables, flows, L2 diagram |
| `flows[]` | name, trigger, description, module, step count, Mermaid, raw flow |
| `patterns` | e.g. `layered`, `mvc`, `microservices`, `repository` |
| `capabilities` | story → module ids |
| `ai` | `off`, `running`, `done` or `failed`, the model, when it finished |
| `snapshot` | ArchiLens's `ArchSnapshot` (nodes, edges, flows) |

## Limitations

- Wide module maps open zoomed to fit; the labels need zooming in (scroll wheel or +).
- ArchiLens's own L0 "system context" drawing is not used: generated apps have no external
  systems, so it was a single box. The runtime topology replaces it.
- Class diagrams of unconnected classes lay out in one row; the panel lists the class names
  and shows the diagram in the main canvas on request.
- Only Python and JavaScript are parsed, which is all a generated app contains.
