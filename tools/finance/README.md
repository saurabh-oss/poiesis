# Trying the finance library without a run

The finance library ([docs/FINANCE.md](../../docs/FINANCE.md)) lives in
`scaffolds/_overlays/finance/`. These tools compose an application from it the way a run
does, so a change to a rule, an endpoint or a chart can be seen in minutes. Nothing here calls
a model. Everything they write goes to `tools/finance/out/`, which git ignores.

## Compose

```
python tools/finance/compose.py --sample
```
writes `tools/finance/out/app`: the web-app scaffold, the enterprise overlay and the finance
overlay; every standard entity as models, tables and schemas; the library's starting domain;
its demonstration data in `db/init.sql` (as of 2026-09-25, and `FINANCE_AS_OF` in `app.env`
holds the figures there); a screen per dashboard blueprint and per worklist; and
`screen_gallery.js`, every component of the kit on one page from fixed data.

`--tables=cost_center,supplier,invoice` composes an application with only those entities.

## Check the API and the operations

```
cd tools/finance/out/app
docker run --rm -v "$PWD:/work" -w /work -e PYTHONPATH=backend python:3.12-slim sh -c \
  "pip install -q -r backend/requirements.txt httpx pytest && python finance_app_check.py \
   && python finance_sparse_check.py \
   && python -m pytest -q --noconftest tests/test_finance_library.py tests/test_rules.py"
```
`finance_app_check.py` signs in as the people of the function and checks the figures against
the rows, and take a purchase from the request to the ERP (77 checks); `finance_sparse_check.py`
calls every `GET` bare, as the platform's
smoke check does. The platform's self-test runs both: `python -m app.selftest_finance`.

## Deploy it and drive it in a browser

```
cd tools/finance/out/app
APP_PORT=8130 docker compose -p fintest up -d --build        # http://localhost:8130
cd ../..
docker run --rm --network fintest_default -v "$PWD:/t" -v "$PWD/out/shots:/out" \
    poiesis-browser:1 python /t/browse.py http://frontend /out light      # and again with: dark
docker compose -p fintest down -v
```
and, against a deployment no one has worked in yet (`down -v`, then `up -d` again):
```
docker run --rm --network fintest_default -v "$PWD:/t" -v "$PWD/out/shots:/out" -w /t \
    poiesis-browser:1 python /t/browse_work.py http://frontend /out light   # and again with: dark
```
`browse.py` opens every blueprint and the gallery as the CFO (sofia) and as accounts payable
(kofi), at 1440, 1024 and 430 pixels: it changes the period and a filter, opens the rows behind
a figure, a record, a supplier's scorecard and a control, exports a widget, rearranges a
dashboard, and matches a held invoice. It fails on a console error, a failed call, a widget that
is empty, failed or spilling, or any text reading "null", "NaN" or "undefined". A screenshot
of each page is left in `out/shots`.

`browse_work.py` opens every worklist at the same three widths, then takes one purchase through
the application, each step as the person whose job it is: nadia raises a request (told who
approves it and what it leaves of the budget) and submits it; tom approves it and rejects
another; daniel is refused an order to a suspended supplier, raises it with an approved one and
sends it to the ERP; nadia receives it; kofi matches an invoice and proposes a payment run. It
changes records, which is why it wants a fresh deployment.

On Git Bash for Windows, prefix the `docker run` commands with `MSYS_NO_PATHCONV=1` and use
`$(pwd -W)` for `$PWD`.
