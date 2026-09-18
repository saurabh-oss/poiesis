# Your first run, end to end

Use the `groq` profile for this. A full local run on 14B models takes 45–90 minutes; on Groq
it takes about six, which is the right speed for seeing whether the pipeline behaves.

## The brief

Paste this into the box on the home page and title it "Application drop-off":

> We keep losing candidates part-way through the job application form. Recruiters say people
> call the helpdesk asking to carry on where they left off and we tell them to start again.
> Legal will not let us store a half-finished application for more than 30 days. I want this
> fixed before the graduate intake in March.

## What happens, and where you are interrupted

**Intake** splits the brief into cited fragments. Four sentences becomes two or three
fragments, each with an id that everything downstream must cite.

**Discovery** is the first gate. The Analyst should come back with something close to: who
counts as a candidate, whether "carry on" means the same device or any device, what happens
on day 31, and whether the March date is a hard constraint. Each question has a proposed
default. Answer the ones you have a view on and let the defaults carry the rest — that
choice is recorded either way.

**Vision** is the second gate. Read it as a stakeholder, not as an architect. If it has
drifted, send it back with a note; the Product Owner gets two revision rounds.

**Backlog** is the third gate. Note that stories with fewer than two acceptance criteria are
rejected internally before you ever see them.

**Architecture** is the fourth gate, and the one worth watching. The right panel shows a
reuse verdict per capability. If the graph has been indexed, you should see it reaching for
existing portfolio components rather than proposing everything fresh. When it says
"build new" without a convincing rationale, use "Reject a build-new decision" and say which
component it should have used — that feedback is binding on the redesign.

**Sprint** is auto-approved under the default pack. Change `approve_sprint` to `require` in
`packs/default.yaml` if you want to cut scope yourself.

**Build** runs without you unless a story fails after three repair attempts. Watch the event
tape: you will see the Developer commit, the Tester write tests, pytest run in the sandbox,
and the repair loop close the gap. Each commit is real git history in `workspaces/<run-id>`.

**Review** produces a weighted score. **Release** is the last gate and never auto-approves.

## Reading the result

```powershell
cd workspaces\<run-id>
git log --oneline
type RELEASE_NOTES.md
```

The commit history is the audit trail: one commit per implementation, one per test suite,
one per repair attempt, one for the release.

## What to look at when it disappoints you

The first run on a fresh graph tends to over-build, because an empty knowledge graph gives
the Architect nothing to reuse. Run the indexer, then run the same brief again and compare
the reuse plans. That difference is the whole thesis of the platform, and it is worth
measuring on your own portfolio before you trust it with anything real.
