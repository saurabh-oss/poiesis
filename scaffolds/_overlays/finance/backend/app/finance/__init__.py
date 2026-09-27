"""The finance and procurement library. Written by Poiesis, and read-only.

What every application for a finance or procurement team needs, written once and
tested, so a story composes it instead of re-deciding it:

    money       amounts that add up: Decimal arithmetic, rounding, allocation, tax, formatting
    periods     the fiscal calendar: years, quarters, periods, to-date ranges, ageing buckets
    rules       22 rules with ids (FIN-01…11, PROC-01…11): three-way match, delegation of
                authority, segregation of duties, budget availability, duplicate invoices,
                payment terms and discounts, tax, variance, supplier risk, contract renewal…
    workflows   lifecycles ready to register: requisition, purchase order, invoice, payment
                run, supplier, contract, budget change — with approvals by amount
    analytics   the numbers behind a dashboard: spend by anything, trends, budget against
                actual, ageing, concentration, cycle times, pivots, procurement KPIs
    operations  what people do to their records: match an invoice, receive goods, propose a
                payment run, check a budget — each through the record's workflow
    personas    the roles of the function, a demonstration persona for each, and permissions
    standard    the standard entities (supplier, purchase_order, invoice…) and their columns
    demo        a coherent year of demonstration data for the standard entities

    from ..finance import money, periods, analytics, rules as fin, workflows as flows, operations as ops, personas

The screens have their half in frontend/finance.js (`import fin from "../finance.js"`).
"""
from . import analytics, money, operations, periods, personas, rules, standard, workflows
from .money import D, Money
from .periods import FiscalCalendar
from .rules import POLICY, Tolerance, configure
from .workflows import ByAmount

__all__ = ["analytics", "money", "operations", "periods", "personas", "rules", "standard", "workflows",
           "D", "Money", "FiscalCalendar", "Tolerance", "ByAmount", "POLICY", "configure"]
