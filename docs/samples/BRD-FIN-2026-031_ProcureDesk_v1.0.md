# BRD-FIN-2026-031 — ProcureDesk: procure-to-pay workbench

| | |
|---|---|
| Document | Business Requirements Document, v1.0 |
| Sponsor | Rachel Whitmore, Financial Controller, Northwind Logistics Ltd |
| Prepared by | Finance Transformation, with Procurement and Accounts Payable |
| Date | 22 September 2026 |
| Status | Approved for build |

## 1. Background

Northwind Logistics spends about £6 million a year with some sixty suppliers, across fourteen
cost centres. Purchase requests arrive by e-mail, approvals are chased by hand, purchase orders
live in the ERP, and supplier invoices are matched in a spreadsheet. Month end takes nine working
days, of which four are spent finding out what was received and not yet invoiced. In the last
audit, 11% of invoiced value named no purchase order, and two pairs of requests had been split to
stay under an approval limit.

Finance wants one workbench where a request becomes an order, an order a receipt, a receipt a
matched invoice and a matched invoice a payment, with the budget visible at every step, and
dashboards that answer each role's questions without a spreadsheet.

## 2. Objectives

| Id | Objective | Measure |
|---|---|---|
| OBJ-1 | Every purchase above the threshold is on a purchase order | Spend on a purchase order at 95% or more |
| OBJ-2 | Invoices match first time | First-time match at 85% or more |
| OBJ-3 | Suppliers are paid on time, and discounts are taken | Paid on time at 95% or more |
| OBJ-4 | Budget holders see their position before they commit | No cost centre over budget without an approved budget change |
| OBJ-5 | Month-end accruals in one day | Accruals listed per open order, at any time |

## 3. People

| Role | Who | What they do |
|---|---|---|
| Requester | Any employee | Raises purchase requisitions, confirms what was received |
| Budget holder | Cost centre managers | Approves requisitions of their cost centre up to their limit; watches the budget |
| Head of department | Department heads | Approves larger requisitions |
| Buyer | Procurement team | Turns approved requisitions into purchase orders; manages suppliers and contracts |
| Accounts payable specialist | Finance | Matches invoices, resolves exceptions, proposes payment runs |
| Financial controller | Finance | Approves payment runs and budget changes; owns the controls |
| Chief financial officer | Executive | Approves the largest requisitions; reads the executive dashboard |

## 4. Business rules

| Id | Rule |
|---|---|
| BR-01 | A requisition is approved by amount: up to £2,000 by the budget holder; above £2,000 and up to £20,000 by the head of department; above £20,000 by the chief financial officer. |
| BR-02 | Nobody approves their own requisition. |
| BR-03 | A requisition that would take its cost centre's spend and commitments above 90% of the year's budget shows a warning; one that would take it above 100% cannot be submitted without an approved budget change. |
| BR-04 | A purchase order can only be raised with a supplier whose status is approved or active. |
| BR-05 | An invoice matches when it is within 1% of the value received and the difference is no more than £25. Otherwise it is held as an exception with the reason. |
| BR-06 | An invoice above £500 that names no purchase order is held, unless its category is rent, utilities or telecoms. |
| BR-07 | An invoice with the same supplier and the same supplier invoice number as an earlier one is held as a possible duplicate. |
| BR-08 | An approved invoice is paid in the first weekly payment run on or after its due date, or earlier when an early payment discount of 1% or more can still be taken. |
| BR-09 | A requisition of more than £10,000 needs three quotes, or a single-source justification. |
| BR-10 | A contract is flagged for a decision 90 days before it ends, and earlier by its notice period. |
| BR-11 | An exception not resolved within 3 working days (72 hours) is escalated to the financial controller. |

## 5. What people need to see and do

### 5.1 Requisitions
A requester raises a requisition with a title, a justification, a cost centre, a category, a
suggested supplier, an amount and the date it is needed by. Before submitting they see who will
approve it, what it leaves of the budget, and how many quotes it needs. Approvers see the
requisitions waiting for them, oldest first, with the budget position of each, and approve or
reject with a reason. A rejected requisition can be revised and submitted again.

### 5.2 Purchase orders and receipts
A buyer sees approved requisitions and raises an order for each. Requesters confirm what
arrived against an order, in full or in part; the order moves to partly received or received.

### 5.3 Invoice workbench
An accounts payable specialist sees invoices by status. Matching an invoice compares it with its
order and receipts (BR-05), and checks BR-06 and BR-07. Each held invoice shows why, how much and
for how long; the specialist resolves it with a reason or rejects it. The workbench shows the
three-way match of any invoice: ordered, received, invoiced and the differences.

### 5.4 Payment runs
Accounts payable proposes a run of what is due (BR-08). The financial controller approves it;
treasury releases it. Released payments are sent to the ERP.

### 5.5 Dashboards

| Dashboard | For | Shows |
|---|---|---|
| Executive summary | CFO, financial controller | Spend against last year and budget; budget used; open commitments; open and overdue payables; spend on a purchase order (target 95%); first-time match (target 85%); paid on time (target 95%); spend by month with budget; spend by category family; budget against actual by cost centre; the controls |
| My budget | Budget holder | For their department only: budget against actual by cost centre, for the period and for the full year with commitments; the forecast for the year; the walk from budget to actual; requisitions waiting for their approval |
| Spend analysis | Procurement manager, buyer | Spend by supplier (Pareto) and by category; spend under contract; maverick spend; price variance; cost centre by month; down to the invoice |
| Accounts payable | Accounts payable, financial controller | Open payables by age; invoices held by reason; days payable outstanding; discounts captured and missed; how long each step takes |
| Suppliers and contracts | Procurement manager | Supplier concentration and risk; a scorecard per supplier; contracts to decide on in the next 180 days |

Every dashboard lets a person choose the period (this month, this quarter, the fiscal year to
date, the last twelve months, or a range) and what to compare it with (the same period last year,
or the period before); filter by cost centre, category and supplier; open the rows behind any
number; and export what they see. The fiscal year starts on 1 April.

## 6. Integrations

| System | What |
|---|---|
| ERP | Purchase orders are created in the ERP when they are sent; approved invoices are posted; released payments are sent. |
| E-mail | Approvers are told when something waits for them, and requesters when it is decided. |
| Microsoft Teams | The finance channel is told when an exception is escalated (BR-11). |

## 7. Demonstration data

At least 60 suppliers, 14 cost centres, 300 purchase orders and 300 invoices over the last
eighteen months, in pounds sterling, with requisitions waiting for approval, invoices held for
each reason, overdue invoices, a payment run to approve and contracts coming up for renewal.

## 8. Out of scope

Supplier self-service, tax filing, fixed assets, payroll, multi-entity consolidation.
