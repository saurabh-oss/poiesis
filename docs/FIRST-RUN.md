# Your first run, end to end

This walks through one run on local models under the `mvp` pack (the default in `.env`):
a brief and a BRD in, a working, data-filled application out, in about two hours on a 12 GB
laptop GPU. Everything stays on the machine.

Before you start: the platform is up, Ollama was started with `scripts\restart-ollama.ps1`,
and http://localhost:3000/observability shows every dependency green (`OPERATIONS.md`).

## The brief

Use the sample BRD that ships with the repository,
`docs/samples/BRD-SUP-2026-021_DupeGuard_v1.2.docx` — a duplicate-ticket auto-triage tool
for a broadband provider's support desk, with scoring rules, ten screens, demonstration data
volumes and acceptance criteria. On the home page:

1. **Name it** `DupeGuard`.
2. **Say it in your own words** — the Director's three sentences are enough:

   > Our support desk wastes a quarter of Tier 1 capacity on duplicate tickets: the same
   > customer chasing the same problem, or hundreds of customers reporting one outage. We
   > want duplicates detected as they arrive, the obvious ones closed automatically with a
   > reply naming the original, uncertain ones sent to review, big clusters turned into known
   > issues that deflect new duplicates at intake, and every automatic action recorded and
   > reversible. The attached BRD has the rules, screens and data we need.

3. **Add what you already have** — drop the BRD. DOCX tables are read in document order, so
   the scoring table and the volume table reach the agents intact.
4. **Start the run.**

For a smaller first try, the home page's "Team leave tracker" example is a short brief
with no attachment.

## What happens

| Stage | Who | What to watch | Typical time |
|---|---|---|---|
| Intake | — | The BRD becomes cited fragments (DupeGuard: 19, plus the brief) | seconds |
| Discovery | Analyst | Questions and contradictions, each with a default | 3 min |
| Vision, backlog | Product Owner | 10 stories at most, each a screen or visible action, two criteria each | 5 min |
| Architecture, sprint | Architect, Planner | Reuse verdicts from the knowledge graph; the sprint order | 3 min |
| Scaffold | — | A working app skeleton, no model call | seconds |
| Foundation | Foundation Developer, Data Designer | Every table at once, then demonstration data, checked and loaded into `init.sql` | 30–40 min |
| Build | Developer | One story after another; each checked, repaired up to three times, committed | 3–15 min a story |
| API smoke | — | Every GET against a throwaway Postgres; a failing one gets one repair | ~5 min |
| Deploy | Release Manager | The app starts on its own port and every screen is opened and used in a browser | 1 min |
| Review | Reviewer | Five weighted dimensions and blockers | 3 min |
| Rework | Developer | One round for what the browser or the Reviewer found | 10–15 min |
| Release | **you** | The only gate that stops for you under the `mvp` pack | — |

Under the `mvp` pack every gate but the release is answered by policy, so the run needs you
once. Switch a gate to `require` in `packs/mvp.yaml` to be asked (for example
`approve_backlog` to cut scope yourself).

While it runs:

- the **run page** shows the stage rail, the live activity feed and, per stage, what was
  produced; **Model traces** shows every model call with its prompt and reply;
- the **Boards** page shows the backlog as a Plane board as soon as it is approved (if Plane
  is running), and cards move as stories pass;
- the **Codebases** page draws the app after the first deploy.

## The release gate

It arrives with the app already running and a link to it. Open it and try it before you
decide. The gate offers:

- **Release** — only if every story is green and the app works in the browser;
- **Release a base app** — drop whatever is broken (only files a single broken story owns),
  redeploy what remains on a fresh database and release that;
- **Send it back** — another build round with your notes (bounded by `max_human_rebuilds`);
- **Hold** — keep it running for inspection.

## Reading the result

| Where | What |
|---|---|
| The app (Apps page, or the run page's link) | The increment itself, with its demonstration data |
| Run page → Deploy stage | What the browser check saw on every screen, with screenshots |
| Run page → Review stage | The score, per dimension, and every finding |
| `/runs/<id>/codebase` | Topology, modules by story, data model, request flows |
| `/runs/<id>/board` and Plane | The backlog and what happened to every story |
| `workspaces\<run-id>` | The repository: one commit per story and repair, a `README.md`, and `RELEASE_NOTES.md` once it is released |

`POST /api/runs/<id>/deploy?fresh=true` restarts the app on its original data at any time,
which resets a demo.

## When it disappoints you

- **A story is red but its screen works.** Read the finding. If it names something the
  Developer could not change, it is a check's false positive (`CHECKS.md`).
- **Screens work but the logic is not what the brief says.** Test the brief's rules against
  the running app; the platform does not yet do this for you. The DupeGuard case study shows
  what that found and how it was fixed (`CASE-STUDY-DUPEGUARD.md`).
- **The data is thin.** `POST /api/runs/<id>/reseed`, then a fresh deploy.
- **It over-builds.** An empty knowledge graph gives the Architect nothing to reuse. Index
  your repositories (`scripts\bootstrap.ps1`), run the same brief again and compare the reuse
  plans — that difference is the thesis of the platform.
