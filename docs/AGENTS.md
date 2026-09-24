# Agent contracts

Ten agents: the eight a stakeholder meets on the home page, and two the foundation stage
adds (`build.foundation: true`, as in `packs/mvp.yaml`). Each has one job, one system prompt
in `services/orchestrator/app/agents/prompts/`, and a typed JSON output whose shape is also a
JSON Schema in `agents/schemas.py`. On the local profile the model's reply is decoded against
that schema, so it cannot be malformed or miss a key. Changing behaviour means editing a
prompt file, not application code; changing the shape of an output means editing the prompt
and the schema together.

| Agent | Model role | Reads | Produces | Refuses to |
|---|---|---|---|---|
| Analyst | reasoning | Evidence fragments | Understanding, contradictions, ranked questions with defaults | Ask more than six questions, or ask what the evidence answers |
| Product Owner | reasoning | Evidence, clarifications | Vision; then Backlog | Assert anything it cannot cite; name a technology in the vision |
| Architect | reasoning | Vision, backlog, knowledge graph | Reuse plan, components, decisions, mermaid diagram | Build new without a written rationale |
| Planner | fast | Backlog, reuse plan | Sprint goal, ranked stories, deferrals | Exceed capacity or violate dependencies |
| Developer | coding | One story, architecture, workspace tree, the routes and tables that exist, the lessons that apply | Complete files, commit message | Implement anything beyond the acceptance criteria; edit tests; use the browser's dialogs, `fetch()` or a package |
| Tester | coding | One story, the implementation (default pack only; the `mvp` pack verifies with the platform's checks and a real browser instead) | pytest files, criteria coverage map | Weaken an assertion to make a test pass |
| Foundation Developer | coding | Brief, architect's data model, every story's criteria | models.py, schemas.py and the CREATE TABLEs for the whole product | Invent a column no criterion needs; declare relationships or enums a screen cannot filter |
| Data Designer | coding | Brief, the screens, the tables as written, the spec contract | A JSON spec (catalogues, choices, references, time windows) the platform expands into demonstration data | Write rows or code; number the copies; repeat a sentence; include ids |
| Reviewer | reasoning | Diff, tests, criteria, reuse plan | Five scored dimensions, findings, verdict | Pass work that fails its criteria |
| Release Manager | fast | Everything | Version, run command, stakeholder release notes | Use internal component names in the notes |

## The Developer's instructions

The Developer's system prompt is two files: `developer.md` (the scaffold, the contracts it
must keep, how to repair) and `ux_playbook.md`, appended to it. The playbook is the bar every
screen clears and the recipes for meeting it: the UI kit's components by screen type,
showing names instead of ids, and "logic the story asks for" — suggestions from rules,
likely duplicates, cascades in one transaction, aggregates for charts — so that an MVP's
logic is real rather than a random number. Changing how generated apps look or behave usually
means editing the playbook, not code.

A repair prompt lists every finding from the platform's checks (`CHECKS.md`) and tells the
Developer to fix all of them in one reply; a syntax error means rewriting that file whole.

## Model calls that are not agents

- **Codebase map explanations.** ArchiLens's module summaries, request flows and pattern
  detection are answered by the local model in the `fast` role, schema-constrained to
  ArchiLens's tool schemas, after a run goes idle (`CODEMAPS.md`).
- **Lessons.** At harvest, one sentence per story that failed or needed repairs.
- **Term extraction** for knowledge recall.

All of them, and every agent, share one gate: the local model answers one call at a time.

## Why the Developer and Tester are split

If one agent writes both the code and its tests in one context, it writes tests that pass.
Splitting the context is the cheapest available guarantee that a green build means something.
The Tester also gets an explicit instruction to test a failure path the Developer did not
mention, which is where most of the real defects surface.

## Why the Analyst is adversarial

The default failure of an autonomous pipeline is fluent agreement: it builds a coherent
version of the wrong thing very quickly. The Analyst's prompt is written to make it argue
with the brief, and its questions are ranked by cost of being wrong so the stakeholder's
attention goes to the expensive ambiguities.

## Tuning

The prompts are the product. When output quality drops, in order:

1. Check the model role — the Developer on a 7B model is the usual culprit.
2. Tighten the output schema before adding instructions. Small models follow schemas better
   than they follow prose.
3. Add a negative example to the prompt for the specific failure you saw.
4. Only then change the graph.

One limit prompts cannot fix: each story is built in its own context, so a business rule
several stories need (DupeGuard's duplicate score) is written several times, differently.
That needs a shared module written once by the foundation stage (`ARCHITECTURE.md`, "What the
DupeGuard run taught").
