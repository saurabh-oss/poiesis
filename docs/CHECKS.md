# How an increment is verified

A model-written story is not trusted because the model says it is done, nor because its own
tests pass. Every story goes through several layers of checks before a person sees it, and
the whole app is opened in a real browser before the Reviewer scores it. This page lists
the layers, what each one catches, and what we learned from the checks that were wrong.

All of it lives in `services/orchestrator/app/workspace/`: `checks.py` (static checks, the
API smoke run, the frontend check), `seeding.py` (demonstration data), `browser_check.py`
(the real browser) and `failures.py` (turning findings into repair instructions).

## The layers, in the order a story meets them

| # | Layer | Runs | Catches | Time |
|---|---|---|---|---|
| 1 | Compile | every story | Python that does not parse, with the line | < 1 s |
| 2 | Static checks, backend | every story | the problems in "Backend" below | < 1 s |
| 3 | Static checks, frontend | every story | the problems in "Screens" below | < 1 s |
| 4 | Frontend check (Node) | every story | a file that does not parse; a screen that touches the DOM on import or exports no `render` | seconds |
| 5 | `db/init.sql` on Postgres | every story that changes it | SQL that does not execute; model columns the schema lacks | seconds |
| 6 | pytest in a sandbox | default pack only | failing tests; tests that could never fail (see "Tests") | minutes |
| 7 | API smoke run | MVP pack, after all stories | any GET that errors against a throwaway Postgres loaded from `init.sql` | ~1 min |
| 8 | Browser check | after deploy, every round | a screen that shows an error, shows nothing, shows seeded data nowhere, or breaks when used | ~1 min |
| 9 | Review | after deploy | criteria not met, unsafe code, missing controls; a weighted score and blockers | minutes |

A finding from layers 1–6 goes back to the Developer as a repair instruction naming the file
and saying what to do, up to `build.max_repair_attempts` times (3 in the MVP pack, 5 in the
default pack). A failure in the API smoke run (7) goes to the story that owns the path for
one repair, then the smoke run is repeated; a path that still fails marks its story red.
Findings from 8 and 9 drive a rework round (`build.max_rework_rounds`: 1 in the MVP pack,
2 in the default pack).

## Backend

| Check | Why it exists |
|---|---|
| A router file that uses `@router.get` but never creates `router` | `NameError` at import, which used to take the whole api down |
| Routes declared at the root (`/` or `/{id}`) | served at `/api/{id}`, they swallowed every other story's GET and answered 422. Such routes are also rewritten automatically (`neutralise_bare_routes`) |
| The same method and path declared twice | the second silently never runs |
| Model columns that `init.sql` does not create | pytest builds tables from the models, the deployed app from `init.sql`; the app fails where the tests passed |
| A GET that returns rows nothing seeds | an empty screen on first open |
| Imports of modules or names that do not exist at runtime | caught before the container fails to start |
| `response_model=` naming a SQLAlchemy model | FastAPI cannot serialise it |
| `strptime()` on a field the schema already types as a date | a 500 on the first real row |
| Constructing a model without a column the table requires | an IntegrityError at runtime |
| `init.sql` that does not execute on Postgres | the app starts with no tables |
| A generic-API filter on a column the table lacks | now a 422 from the data API too |

## Screens

| Check | Why it exists |
|---|---|
| No `export default { title, story, render }` | the shell cannot load the screen |
| No `story:` tag | the platform cannot tell which story a screen belongs to |
| JSX | there is no bundler; screens are plain JavaScript built with `h()` |
| A comment saying placeholder, TODO, stub, coming soon | a placeholder is not an implementation |
| The browser's `alert()`, `confirm()` or `prompt()` | use `ui.confirm()`, `ui.formModal()` or `ui.toast()`. A screen's *own* function with one of those names is allowed (see below) |
| `fetch()` directly | use the `api()` that `render()` receives: it adds `/api`, sends JSON and reports failures |
| Reaching outside the screen's root, or wiring page startup | the shell owns the page |
| Importing a package | there is no bundler |
| A call to a method and path the API does not serve | the commonest cause of an empty screen |
| A screen that gives up without an id | the navigation opens every screen without parameters |
| `render()` using an argument it never receives (`actions`, `ui`, …) | a ReferenceError on open |
| `render()` that loads nothing | the screen is empty until a button is pressed |

## Demonstration data

The foundation stage's Data Designer writes a spec; the platform expands it into rows and
checks them before they go into `init.sql`:

- every column exists and every NOT NULL column is filled (gaps are filled on the last attempt);
- prose varies: descriptions are not one sentence copied over many rows;
- every state a screen filters on has rows, and no small category column is lopsided —
  more than 80% of rows sharing one value is rejected, **90%** for a column with only two
  values, since a split like 48 Residential / 12 Business is often exactly what the brief asks;
- the counts in the brief's volume table are met.

## Tests (default pack)

A Tester that seeds its own fixture data, builds its own session, asserts HTML from an API,
compares against copied text, or requests a path the API does not serve writes tests that
cannot tell a working story from a broken one. Each of these is a finding for the Tester,
not the Developer.

## The API smoke run

Every GET the app declares is called against a throwaway Postgres (its own Docker network,
loaded from the app's `init.sql`), with `1` substituted for path parameters:

- a path with parameters fails on 5xx (a 404 for id 1 is fine);
- a path without parameters fails on any 4xx or 5xx — a 422 there is usually a stray root
  route swallowing it — **except** a 422 whose every complaint is a missing *query*
  parameter: that endpoint needs input (a deflection check wants the draft's subject) and
  answering 422 to a bare call is correct;
- a router that fails to import is reported by name.

Failures are grouped by the file that owns the path; each owning story gets one repair and
the run is smoked again.

## The browser check

After every deploy a headless Chromium on the app's own network opens every screen and:

- waits for the screen to finish drawing, then looks for the error panel;
- fails a screen that renders almost nothing, still shows a placeholder, or shows the words
  `undefined`, `null`, `NaN` or `[object Object]`;
- compares what the API returned with what is on the screen: data fetched and not shown is
  "an empty table over a full database";
- **uses** the screen: opens the first row (drawer or detail screen), switches up to two
  tabs, presses the first "New…/Add…/Create…" button and closes what opens — any error
  thrown while doing so is a finding;
- records console errors and screenshots every screen (`/api/runs/{id}/shots/…`).

The Reviewer is shown what each screen displayed, not only the code.

## Enterprise applications

With the `enterprise` pack ([ENTERPRISE.md](ENTERPRISE.md)) the layers change in four places.

- **The domain stage** runs before any story: the domain must import, agree with the data model
  (roles, tables, workflow states and fields, a persona for every role, no worked example left)
  and pass its rule tests, with every failure handed back up to three times. The results are
  baked into the app as `domain/rule_results.json`.
- **Two static checks** (`enterprise_issues` in `checks.py`) on a story's routers and on
  `domain/services.py`: a call out with `requests`, `httpx`, `urllib`, `smtplib` or `aiohttp`
  ("use a connector"), and a write to a column a workflow governs ("use `transition()`"). The
  kernel refuses the second at runtime too (409, rule `WF-00`); found here it costs no repair round.
- **The API smoke run** calls every GET with the platform's service token, since the app answers
  401 without a session.
- **The browser check** screenshots the sign-in page, checks it offers personas, signs in as the
  profile's check persona and opens every screen with a real session, the platform's four screens
  included. A platform screen that fails is reported as a platform problem, never as a story's —
  no story could fix it.

## When a check was wrong

A check that flags something the Developer cannot change turns a working story red after
every repair attempt. Three did so in the DupeGuard run (see `CASE-STUDY-DUPEGUARD.md`),
and each was fixed in the check:

| False positive | What it cost | Fix |
|---|---|---|
| `confirm(r.id)` flagged as the browser dialog, though the screen had its own `async function confirm(id)` for the review queue's Confirm button | the core story, the duplicate scan, red after three repairs in two rounds | a banned name the screen itself declares is allowed (`_defines`) |
| `/api/intake/deflection` called bare answered 422 "missing query subject", reported as a 500 | the intake story red twice | a 422 made only of missing query parameters is an endpoint that needs input (`_needs_query`) |
| 49 of 60 customers "Residential" rejected as lopsided | a wasted data attempt (about 12 minutes of model time) | two-value columns may split up to 90/10 |
| `` api(`/api/audit-entries${params}`) `` read as a call to `/api/audit-entriesx` | the enterprise run's audit screen red after three repairs | an expression glued to the end of a path segment is a suffix (a query string), not part of the path |
| The domain stage's rule tests imported the app's `tests/conftest.py`, which needs `httpx` | a repair spent on a file the Developer may not edit | the rule tests run with `--noconftest` and `backend` on the path; they are pure |
| `ticket.original_ticket_id` refers to `ticket`; the seed expander demanded "put that table earlier" | four data attempts that could never pass | a table that refers to itself points at its own earlier rows |

Earlier ones of the same kind: `ui.confirm()` was once flagged as `confirm()` (fixed with a
look-behind), a history table's foreign key was required to be set on every row, ISO dates
and job titles counted as copied prose, and the 30-records rule applied to tables the brief
never sized.

The rule that came out of them: **a finding must name something the Developer can change,
in words it can act on.** When a story is red and its screen works, suspect the check first.

The same run found two platform gaps of the opposite kind — things nothing checked:

- A seed spec that filled one table (81 KB of customers) and left ten empty passed. Every table
  except the scaffold example must now get rows, with the missing ones named.
- A story could delete another story's router by returning it empty: three repairs did, and
  four screens answered 404. A router another story's screen still calls is now kept whole.

## Adding a check

1. Put it in the layer that sees the problem earliest (static before smoke before browser).
2. Word the finding as an instruction: the file, what is wrong, what to do instead.
3. Add a case to `app/selftest.py` (build-time checks) or `app/selftest_core.py`, with at
   least one input that must **not** be flagged. `test_check_rules` in `selftest_core.py`
   holds one for each false positive above.
4. `docker compose exec orchestrator python -m app.selftest` before and after.
