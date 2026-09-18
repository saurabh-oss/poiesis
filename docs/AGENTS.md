# Agent contracts

Eight agents. Each has one job, one system prompt in
`services/orchestrator/app/agents/prompts/`, and a typed JSON output. Changing behaviour
means editing a prompt file, not application code.

| Agent | Model role | Reads | Produces | Refuses to |
|---|---|---|---|---|
| Analyst | reasoning | Evidence fragments | Understanding, contradictions, ranked questions with defaults | Ask more than six questions, or ask what the evidence answers |
| Product Owner | reasoning | Evidence, clarifications | Vision; then Backlog | Assert anything it cannot cite; name a technology in the vision |
| Architect | reasoning | Vision, backlog, knowledge graph | Reuse plan, components, decisions, mermaid diagram | Build new without a written rationale |
| Planner | fast | Backlog, reuse plan | Sprint goal, ranked stories, deferrals | Exceed capacity or violate dependencies |
| Developer | coding | One story, architecture, workspace tree | Complete files, commit message | Implement anything beyond the acceptance criteria; edit tests |
| Tester | coding | One story, the implementation | pytest files, criteria coverage map | Weaken an assertion to make a test pass |
| Reviewer | reasoning | Diff, tests, criteria, reuse plan | Five scored dimensions, findings, verdict | Pass work that fails its criteria |
| Release Manager | fast | Everything | Version, run command, stakeholder release notes | Use internal component names in the notes |

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
