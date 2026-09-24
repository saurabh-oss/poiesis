# Case study: DupeGuard, duplicate-ticket auto-triage

A record of one run from brief to working application, what the platform got right, what
it got wrong, and what was changed as a result. Run `b6c296c04f9d4b02`, 24 September 2026,
local models only (Qwen3.6 35B-A3B on an RTX 5070 Ti laptop), `mvp` pack.

## The brief

A realistic business requirements document for a fictional broadband provider's support
desk: `docs/samples/BRD-SUP-2026-021_DupeGuard_v1.2.docx` (about 4,000 words, 17 tables).
It asks for an internal tool that:

- **detects** duplicate tickets as they arrive, with an explainable 0–100 confidence score
  (text similarity 55, same customer 20, same product area 15, time proximity 10);
- **closes** the obvious ones automatically (score 85 or more) with a customer reply naming
  the original ticket, and sends uncertain ones (70–84) to a review queue — never closing a
  P1 automatically, and following chains to the earliest original;
- **prevents** repeat waves: a cluster of duplicates is promoted to a known issue whose
  keyword rule shows a message at intake, so the customer need not raise a ticket;
- **monitors and records** every automatic action in an append-only audit log with undo,
  and reports precision honestly (undone closures count against it — compliance rule COMP-02).

It defines ten MVP screens, the demonstration data (volumes, clusters, known issues,
prevented tickets, audit history) and eight Given/When/Then acceptance criteria. It was
attached to the run with a three-sentence brief in the Director's words.

## The run

| Stage | Took | What happened |
|---|---|---|
| Intake | seconds | 20 cited fragments (19 from the BRD, tables included) |
| Discovery → sprint | 9 min | 6 questions, 2 contradictions; 1 epic, 10 stories, 54 points; every gate but release auto-approved by the pack |
| Foundation | 38 min | 11 tables in one pass after one correction; demonstration data on the third attempt — attempt 1 left required dates empty, attempt 2 was rejected by an over-strict rule (below) |
| Build | 37 min | 9 of 10 stories green, 7 of them with no repair; S4 (the scan) red |
| API smoke | 7 min | 3 GETs failed; 2 fixed by one repair each; S8 (intake) marked red |
| Deploy + browser | 1 min | 7 of 10 screens working |
| Review | 3 min | 61.5/100, 6 blockers, rework |
| Rework round | 13 min | Inbox, review queue and intake repaired; S4 red again |
| Deploy + browser | 1 min | **10 of 10 screens working** |
| Review | 4 min | **90.8/100, 0 blockers**; release held: 2 stories red |

1 hour 52 minutes from start to the release gate, all on the local GPU.

The ten stories: S1 Command Center dashboard, S2 ticket inbox, S3 ticket detail with likely
duplicates, S4 duplicate scan and auto-close, S5 review queue, S6 clusters and promotion,
S7 known issues and deflection rules, S8 intake with deflection, S9 audit log with undo,
S10 accuracy and thresholds.

## What was wrong

### The two red stories were the platform's fault

Both red stories worked. Two platform checks flagged things no Developer could change:

- **S4**: the review panel had its own `async function confirm(id)` behind its Confirm
  button; the check against the browser's `confirm()` dialog flagged it three times per round.
- **S8**: the smoke run called `/api/intake/deflection` without its required `subject`; the
  endpoint correctly answered 422, which was reported as a 500.

A third, the data rule that rejected 49 of 60 customers being Residential (the BRD asked
for 48 of 60), cost twelve minutes. All three are fixed in the checks and covered by
self-tests (`CHECKS.md`, "When a check was wrong").

### The logic did not follow the BRD

Every screen opened and showed data, and the Reviewer scored the increment 90.8. Testing the
business logic against the BRD's acceptance criteria told a different story:

- **Three scoring models.** Each story wrote its own: the scan compared subjects by word
  overlap only; ticket detail used a 40/30/30 mix that ignored the customer; intake matched
  titles by fuzzy string similarity. None was the BRD's model, and the score a user saw on
  one screen was not the score the scan acted on.
- **Rules missing**: no P1 rule, no chains, no time window, no settings read, no customer
  reply on closure, no false positive recorded on rejection, preventions never counted,
  promotion not linking the cluster's tickets.
- **Precision simulated**: the accuracy screen computed it from a heuristic over review
  scores ("we simulate this"), the opposite of what COMP-02 requires.
- **Opening the scan screen ran the scan**, and again after every review decision.
- **Thin data**: every ticket had no product area, customer or channel, and every ticket was
  P3, so the customer and product signals, the P1 rule and the outage cluster could not be
  shown at all.
- A gap in the BRD itself: two different customers can never score 85, because they never
  get the 20 same-customer points, so an outage could never be closed automatically by
  score. Known issues are the mechanism for that; the logic has to treat them first.

This is the most important finding of the run. **Each story is built in its own context, so
business logic that several stories share is implemented several times, differently.** The
platform's checks verify that screens work; nothing verified that the rules were the BRD's.

## What was changed after the run

Made by Claude Code working locally in the run's workspace (commit `13fb49e` in the run's
repository); the platform's agents were not involved.

1. **One duplicate engine** (`backend/app/dedupe.py`): BRD section 6 in one place — the
   weighted score with each signal's contribution and plain-language reasons, BR-01 to
   BR-06, and BR-12 checked first (a ticket matching an active known issue is linked to the
   issue's original ticket, whatever its pairwise score).
2. **One way to become a duplicate** (`backend/app/duplicates.py`): link to the earliest
   original, reply naming it, record the suggestion, the audit entry and the cluster.
3. **Every endpoint moved onto it**: scan (only tickets since the last scan), likely
   duplicates, review confirm and reject, manual mark, cluster promotion (with a keyword rule
   generated from what the cluster's subjects share), intake deflection (known issue or the
   customer's own open ticket), prevention, undo, the dashboard, precision by week and the
   threshold what-if.
4. **History replayed through the engine** (`db/seed_generator.py`): 331 tickets over 30
   days — everyday problems with each customer's own details, same-customer chasers (some
   reworded, landing in the review band), a Manchester fibre outage, a billing run, P1s from
   business customers, known issues promoted and deflecting, reviews decided, six automatic
   closures undone. Timestamps are relative to `now()`, and the newest 22 tickets are left
   for "Scan now", so every fresh deploy is a live demo.
5. **Screens**: the scan screen reads without changing anything and has a real "Scan now"
   with a per-ticket result (rule and score); the audit log shows ticket references and
   undoes in place; accuracy previews a threshold before saving it; the dashboard shows
   duplicates per day, by product area and the largest clusters.

## Verification

- **29 of 29** acceptance checks against the running app (`AC-1`–`AC-8`), including: the scan
  closes same-customer chasers at 97.5 and 99, links Glasgow and Android reports through
  their known issues, queues 70–84 pairs and closes no P1; every closure has a reply naming
  its original; a second scan finds nothing; confirming and rejecting behave as specified; a
  promoted cluster's rule reads `internet router, flashing red, lights`; intake deflects a
  matching draft and not an unrelated one; undo reopens and lowers precision; the threshold
  preview shows 7 more closures (and 1 more false positive) at 80.
- **10 of 10** screens pass the platform's browser check, and a scripted tour (open, scan,
  review, type into intake, filter the audit log) raised no console errors.
- All four services healthy; no broken router modules.

Headline numbers on a fresh deploy: 331 tickets, 100 duplicates (30%), 74 closed
automatically, 13 in review, 32 prevented, precision 91.9% with 6 undone, 35 hours saved.

## Lessons for the platform

1. **Shared business rules need one home.** The foundation stage already writes the data
   model for every story at once; it should also write a domain module for the rules the
   BRD states (scoring, thresholds, state changes), with the stories required to import it.
   This is the next platform change proposed.
2. **Checks must only flag what a Developer can change.** Three false positives made working
   stories red; the rule is now in `CHECKS.md` with a self-test for each.
3. **A working screen is not a working rule.** The browser check and the Reviewer judged the
   experience; neither tested the BRD's logic. Acceptance criteria stated as numbers and
   rules ("score ≥ 85 closes", "precision counts undone closures") should become executable
   checks against the running app, as `AC-1`–`AC-8` were here by hand.
4. **Demonstration data should be replayed, not listed.** Data generated by running the
   app's own rules over a simulated month is consistent across every screen in a way a list
   of rows is not.
