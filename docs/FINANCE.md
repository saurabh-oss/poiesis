# Finance and procurement

The `finance` pack builds an application a finance or procurement team runs its work on. It is
the [enterprise pack](ENTERPRISE.md) with the **finance library** laid over it: what every such
application shares, written once, tested, and handed to each run ready to use. A run then spends
its effort on what this organisation does differently — its own rules and thresholds, its own
records, the dashboards its people asked for.

It is the first **department library**. The mechanism that carries it (an overlay with a
manifest) is how the next department is added; [Adding a department](#adding-a-department) says how.

```ini
# .env
POIESIS_PACK=packs/finance.yaml
```

## What a run gets, and what is left for it to do

| The platform brings | A run adds |
|---|---|
| The standard entities (supplier, requisition, purchase order, goods receipt, invoice, payment run, contract, budget line…), written by the platform itself in `models.py`, `init.sql` and `schemas.py` | The brief's own entities, and columns of its own on a standard one |
| More than two years of coherent demonstration data for them | Data for its own tables, referring to the library's rows |
| 22 tested rules with ids, in the rule catalogue | The brief's rules under the brief's ids, calling the library's with the brief's numbers |
| The lifecycle of each record, with approval by amount | The brief's roles, limits, SLAs and consequences, passed to the factory |
| The roles of the function, a persona for each, their permissions | The brief's own role names |
| Operations: match an invoice, receive goods, propose a payment run, check a budget | The brief's own operations |
| An insight API: figures, breakdowns, trends, budget, ageing, funnel, cross-tabs, controls, scorecards, the rows behind every number | Routers only for what the API does not give |
| A dashboard kit: whole dashboards from a description, and every chart and record component | The description of each dashboard: what it shows, to whom |
| An ERP connector, sandboxed until credentials are set | The calls, at the moments the brief names |

## Where it lives

```
scaffolds/_overlays/finance/
  overlay.yaml                     what the overlay owns, says and brings (read by the platform)
  prompts/                         what each agent is told: architect, foundation, domain, data, developer
  backend/app/finance/             the library (platform-owned, read-only in an application)
    standard.py                    the standard entities and their columns; which a brief needs
    money.py                       exact amounts: Decimal arithmetic, rounding, allocation, tax, formatting
    periods.py                     the fiscal calendar, to-date ranges, comparisons, ageing buckets
    rules.py                       FIN-01…11, PROC-01…11
    workflows.py                   the lifecycles, as factories over an application's models
    personas.py                    roles, personas, permissions, segregation of duties
    operations.py                  match_invoice, receive_goods, propose_payment_run, budget_position, check_request
    analytics.py                   the numbers behind a dashboard, as pure functions over rows
    api.py                         the insight API and the operations, under /api/finance/
    demo.py                        the demonstration data
    starter.py                     the business logic an application starts with
  backend/app/connectors/erp.py    the ERP connector
  frontend/finance.js, finance.css the dashboard kit
  frontend/screens/example_finance.js   the worked example the Developer is shown
  tests/test_finance_library.py    83 tests: every rule on both sides of its thresholds
packs/finance.yaml                 the pack
services/orchestrator/app/
  workspace/overlays.py            reads an overlay's manifest
  workspace/standards.py           merges the standard entities into the data model
  selftest_finance.py              the platform's self-test of all of it
tools/finance/                     compose an application without a run; drive the kit in a browser
```

## The standard entities

`standard.py` defines sixteen tables: `cost_center`, `gl_account`, `spend_category`, `supplier`,
`exchange_rate`, `budget_line`, `contract`, `requisition`, `purchase_order`,
`purchase_order_line`, `goods_receipt`, `payment_run`, `payment`, `invoice`,
`savings_initiative`, `budget_change`. One definition serves four uses: the data model, the
demonstration data, the analytics and the dashboards all read the same column names.

An application has the ones its brief speaks of. At the foundation stage the platform reads
the brief, the backlog and the architecture for each entity's words ("purchase order", "PO",
"vendor", "three-way match"…), adds the entities those cannot do without (an invoice needs a
supplier), tells the Developer they exist, and **writes them itself** into the three files the
Developer returns. The Developer writes only the brief's own entities. Where it wrote a
standard entity anyway, the platform's definition stands and any column of its own is kept:

```python
class Invoice(Base):                      # what the Developer returned
    __tablename__ = "invoice"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dispute_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
```
becomes the standard `invoice` with `dispute_reason` as its last column, in `models.py`,
`init.sql` and `schemas.py` alike.

Amounts are stored as `DOUBLE PRECISION` (the platform's convention for every application) and
computed with `Decimal` through `money.py`; moving storage to `NUMERIC` is a change to
`standard.py` and the scaffold's conventions together.

## The demonstration data

`demo.rows(tables, today=…)` tells one story, twenty-seven months long, of a mid-sized
organisation buying things: 640 orders to sixty-odd suppliers, their receipts and 720 invoices,
weekly payment runs, contracts coming up for renewal, a budget per cost centre and category
family. It is shaped the way the real thing is — ten suppliers carry half the spend; nine
invoices in ten match first time; two cost centres are over budget — and every screen has work
to do on day one: requisitions waiting for approval, invoice exceptions of every kind, overdue
invoices in every ageing bucket, a payment run to approve, a pair of requests that look like
one purchase split in two. Every month has the same month a year earlier to be compared with.

Rows are produced for the standard tables an application has, holding only the columns each
has; a reference to a table the application lacks is left empty. The Data Designer writes a
spec only for the remaining tables, whose references resolve into the library's rows. When
every table is a standard one, no model is asked at all.

The dates are fixed when the data is generated. `FINANCE_AS_OF=2026-09-25` in an application's
environment freezes "today" for the figures, for a demonstration that must read the same
next month.

## The rules

| Id | Rule | Id | Rule |
|---|---|---|---|
| FIN-01 | Segregation of duties | PROC-01 | Three-way match, with tolerance |
| FIN-02 | Budget availability | PROC-02 | Delegation of authority by amount |
| FIN-03 | Payment terms and due date | PROC-03 | Duplicate invoices |
| FIN-04 | Early payment discount | PROC-04 | Savings against a baseline |
| FIN-05 | Late payment interest | PROC-05 | Supplier risk score |
| FIN-06 | Tax, and an invoice's arithmetic | PROC-06 | No order, no pay |
| FIN-07 | Variance and materiality | PROC-07 | Contract renewal and notice |
| FIN-08 | Accruals (received, not invoiced) | PROC-08 | Purchase price variance |
| FIN-09 | Allocation that sums back exactly | PROC-09 | Approved suppliers only |
| FIN-10 | Closed periods | PROC-10 | Quotes by value |
| FIN-11 | Exchange differences | PROC-11 | Split orders |

Each is a pure function registered with `@rule`, so it appears in the application's Business
rules screen with its statement and its test results. A threshold is compared on the amounts,
never on a rounded percentage: 89.999% of a budget is not the 90% that warns.

**The organisation's numbers have one home.** An application sets them once, where its rules
are written, and the library's rules, lifecycles, operations and insight API all read them from
there, so the approval a requisition waits for, the match an invoice gets and the control a
dashboard flags agree:

```python
fin.configure(
    doa=[(2_000, "budget_holder"), (20_000, "head_of_department"), (None, "cfo")],     # BR-01
    tolerance=fin.Tolerance(price_pct=1, quantity_pct=0, amount_abs=25),                 # BR-05
    po_required_above=500,                                                               # BR-06
)

@rule("BR-05", "An invoice matches within 1% and 25", source="BRD 4", kind="validation")
def match(order, receipts, invoice):
    return fin.three_way_match(order, receipts, invoice)
```

Settings: `doa`, `tolerance`, `po_required_above`, `po_exempt_categories`, `quote_bands`,
`budget_warning_pct`, `material_pct`, `material_amount`, `expiring_days`, `duplicate_days`,
`split_days`, `orderable`, `late_interest_pct`, `tax_rates`. A name the library does not have is
refused, so a misspelt one is not silently ignored. Any rule still takes a number of its own
as an argument. The library's tests state the library's defaults and restore the
application's after each.

## The lifecycles

`workflows.py` has a factory per record: `requisition`, `purchase_order`, `invoice`,
`payment_run`, `supplier`, `contract`, `budget_change`. Each takes the application's model and
returns the kernel `Workflow`: who may move the record, which moves wait for an approval and
whose, what a refusal does, how long it may wait.

```python
REQUISITION = register(flows.requisition(Requisition, approval_hours=24, escalate_to="head_of_department"))
INVOICE = register(flows.invoice(Invoice, clerk=("ap_specialist",), doa="finance_controller", exception_hours=72))
```

Two things the kernel learned for this: an approval's approver can be **decided by the
record** (`ByAmount`, which follows the configured delegation of authority, PROC-02), and a record can sit
in a **state of its own while it waits** (`pending="submitted"`): a requisition is "submitted",
not still "draft", until someone decides. A move sets only the columns the application's table
has, so an application that left `discount_taken` out still gets the invoice lifecycle.

## The business logic an application starts with

Before the domain stage asks a model for anything, `starter.domain(tables, classes)` writes the
five domain files for the tables the application has: the roles those records need and a
persona for each, permissions over the tables that exist, a registered lifecycle per record, the
library's rules, and the operations as services. It imports and passes the domain stage's check
as written. The Developer is shown it as *the domain now in the workspace* together with what
the brief still lacks ("BR-03 is not registered"), and adds that. No attempt of its that scores
worse takes the starter's place, and a domain that never imports falls back to the starter
rather than to an empty one. When the brief states no rules of its own, no model is asked.

## The insight API

Served under `/api/finance/` by every application of the pack, over whichever standard
entities it has. A figure that needs a table the application lacks is empty
(`"available": false`), never an error; one that needs a table a person may not read is left out.

| Endpoint | Gives |
|---|---|
| `GET calendar` | Today, the fiscal year, the period presets, which entities exist, roles, approval matrix |
| `GET dimensions` | Cost centres, departments, families, categories, suppliers, countries, for filters |
| `GET kpis` | 24 headline figures against the comparison period, each with direction, trend and drill |
| `GET breakdown` | A measure by a dimension, with shares and the comparison |
| `GET concentration` | The Pareto, the top-10 share, the Herfindahl index |
| `GET trend` | A measure per month, quarter or year, with budget and the year before |
| `GET pivot` | A cross-tab with totals |
| `GET budget`, `waterfall` | Budget against actual: the period's variance, the year's position, the forecast |
| `GET aging` | Open payables by age, and who is owed the most overdue |
| `GET funnel`, `cycle-times` | Purchase to pay: how many reach each step, how long each takes |
| `GET exceptions`, `accruals`, `renewals`, `controls` | The worklists of the function |
| `GET suppliers/{id}/scorecard` | One supplier: spend, delivery, risk by factor, contracts |
| `GET documents` | The rows behind any number, with the names of what they refer to |
| `POST invoices/{id}/match` | Three-way match, duplicates, no order no pay; moves the invoice |
| `POST purchase-orders/{id}/receive` | Posts a receipt, moves the order |
| `POST payment-runs/propose`, `GET payment-runs/payable` | A run of what is due, discounts worth taking taken |
| `GET budget/position`, `requisitions/{id}/advice` | What is left; what to tell a requester before they submit |

Every `GET` takes the same scope: `period` (a preset) or `from` and `to`; `compare`
(`prior_year`, `prior_period`, `none`); and the filters `cost_center_id`, `spend_category_id`,
`supplier_id`, `family`, `department`, `region`, `country`, `currency`.

**Budget has two questions**, and the API answers them separately. For the period: what was
spent against its budget (`variance`, `status`: over, watch, on track; FIN-07). For the fiscal
year: what is left once what is spent and what is committed are taken off the year's budget
(`available`, `position`; FIN-02), and where the year is heading at this rate (`forecast`).
Setting open commitments against a year-to-date budget makes every cost centre look overspent.

Rows are read into memory and summed exactly, which is right for a department's volumes (tens
of thousands of documents); beyond that, the measures move into SQL behind the same endpoints.

## The dashboard kit

```js
import fin from "../finance.js";

export default {
  title: "Spend overview", story: "S3", icon: "pie",
  async render(root, ctx) {
    await fin.dashboard(root, ctx, fin.blueprints.spend({
      period: { value: "this_quarter", compare: "prior_year" },
      fixed: { department: "Operations" },                 // one team's own dashboard
      kpis: ["spend", "po_coverage", "maverick_spend"], targets: { po_coverage: 95 },
      remove: ["pivot"],
      add: [{ type: "budget", by: "cost_center", span: 6 }],
    }));
  },
};
```

A dashboard is a description. With it come the period picker (fiscal presets and a range of
one's own), the comparison, the filters, the headline figures coloured by whether a move is
favourable (up is bad on a cost), the rows behind every number in a slide-over, a record's
drawer with its three-way match and its workflow panel, CSV export per widget, and each
person's own arrangement (which widgets, in what order, which period and filters), remembered
on their device.

- **Blueprints**: `executive`, `spend`, `budget`, `payables`, `procureToPay`, `suppliers`,
  `controls`, `savings`.
- **Widgets**: `kpis`, `trend`, `breakdown` (bars, donut, treemap, pareto), `budget`,
  `waterfall`, `aging`, `funnel`, `pivot`, `cycle`, `exceptions`, `accruals`, `renewals`,
  `controls`, `documents`, `suppliers`, and `custom` with its own `load` and `draw`. An
  application registers a kind of its own in `fin.WIDGETS`.
- **Components**, for screens that are not dashboards: `kpis`, `delta`, `varianceBadge`,
  `gauge`, `trend`, `budgetBars`, `waterfall`, `pareto`, `treemap`, `donut`, `aging`, `funnel`,
  `pivot`, `cycleTimes`, `matchStatus`, `approvalChain`, `lifecycle`, `scorecard`,
  `controlList`, `renewalList`, `documents`, `drill`, `periodPicker`, `filterBar`, `exportCsv`.
- **Text**: `money`, `percent`, `number`, `days`, `date`, `format`, `variance`, `calendar`.

Charts are drawn at the width they are given, in real pixels, and again when it changes, so
text stays the size it was written at; rows rearrange by the width of their container, so the
same component works in a widget, a drawer and on a phone. Everything is built on the
scaffold's Spectrum tokens and follows the light and dark themes. Nothing is ever written as
"null", "NaN" or "undefined": a figure that is not there is a dash.

## The ERP connector

`erp()` keeps the contract of every connector ([CONNECTORS.md](CONNECTORS.md)): sandboxed
without credentials, every call in the outbox, idempotent, retried, behind a circuit breaker.
Operations: `sync_supplier`, `create_purchase_order`, `get_purchase_order`, `post_invoice`,
`invoice_status`, `release_payments`, `payment_status`, `gl_balances`, `exchange_rates`. Its
sandbox keeps a ledger, so a demonstration posts an invoice, releases a payment and reads the
balance back. Settings: `ERP_BASE_URL`, `ERP_TOKEN`, `ERP_SYSTEM`, `ERP_COMPANY`,
`ERP_BASE_CURRENCY` (as `APPS_ERP_BASE_URL`… in the platform's `.env`).

Connectors are now discovered: any module an overlay adds to `backend/app/connectors/` that
defines a `Connector` is listed on the Integrations screen, replayed by the scheduler and
reached as `connectors.<name>()`.

## Settings inside a finance application

| Setting | Default | Meaning |
|---|---|---|
| `FISCAL_YEAR_START_MONTH` | `4` | The month the fiscal year starts in; a year is named after the year it ends in |
| `BASE_CURRENCY` | `GBP` | The currency figures are reported in; other currencies convert at the latest `exchange_rate` |
| `FINANCE_AS_OF` | today | Freezes "today" for the figures |
| `ERP_*` | none | The ERP connector's credentials; without them it runs in its sandbox |

Set `APPS_<SETTING>` in the platform's `.env`; it reaches each deployed application.

## Verification

```
docker compose exec orchestrator python -m app.selftest_finance      58 checks, no model calls
```
covers the overlay's manifest, the standard-entity merge, the demonstration data (loaded as
SQL), the starting domain under the domain stage's own check, the contracts a Developer is
shown, the insight API and the operations as the people of the function (54 checks of their
own), every `GET` answering without an error in applications with all, some and none of the
entities, and the library's 83 rule tests.

The kit in a real browser, without a run:

```
python tools/finance/compose.py --sample
cd tools/finance/out/app && APP_PORT=8130 docker compose -p fintest up -d --build
docker run --rm --network fintest_default -v "$PWD/../..:/t" -v "$PWD/../shots:/out" \
    poiesis-browser:1 python /t/browse.py http://frontend /out light
```
opens every blueprint and the component gallery as the CFO and as accounts payable, at three
widths and in both themes, and reports console errors, failed calls, text that should never be
shown, and widgets that are empty, failed or spilling (78 checks), with a screenshot of each.

## Adding a department

1. `scaffolds/_overlays/<name>/` with the department's library under `backend/app/<name>/`,
   its kit under `frontend/`, its tests under `tests/test_<name>_library.py`.
2. `overlay.yaml`: what it owns, its prompts by agent, and the modules the platform calls —
   `standard` (`ENTITIES`, `ORDER`, `needed(text)`, `summary()`, `gaps()`, `model_class()`,
   `create_table()`, `schema_classes()`, `column_names()`, `class_name()`), `demo`
   (`rows(tables, today=)`) and `starter` (`domain(tables, classes)`). Each is optional.
3. An `api.py` with a `router` in the library's package is served under `/api` by the kernel.
   A connector module in `backend/app/connectors/` is discovered.
4. `packs/<name>.yaml` with `build.overlays: [enterprise, <name>]` and the product guidance.

Nothing in the orchestrator names `finance`.
