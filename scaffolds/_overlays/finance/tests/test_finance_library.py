"""Proof of the finance and procurement library. Written by Poiesis, and read-only.

Every rule is proven by tests named after it (`test_fin_02_…` proves FIN-02), on both
sides of each threshold, so the application's Business rules screen shows the library's
rules as tested. Pure, except the workflow tests, which run on the kernel over a private
in-memory database.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from types import SimpleNamespace as Rec

import pytest
from sqlalchemy import DateTime, Float, Integer, String, create_engine
from sqlalchemy.orm import Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

from app import connectors
from app.db import Base
from app.finance import analytics as fa
from app.finance import demo, money, periods, personas, standard
from app.finance import rules as fin
from app.finance import workflows as flows
from app.kernel import audit, transition
from app.kernel.context import Actor, acting_as
from app.kernel.models import Approval, AuditEvent
from app.kernel.rules import RULES, RuleViolation
from app.kernel.workflow import decide, register

D = Decimal
TODAY = dt.date(2026, 9, 25)


@pytest.fixture(autouse=True)
def library_defaults():
    """These tests state the library's own numbers. An application sets its own (fin.configure),
    and its tests run in the same process: each test here starts from the defaults and puts the
    application's back."""
    kept = {name: getattr(fin.POLICY, name) for name in fin.Policy.__dataclass_fields__}
    fin.reset()
    yield
    fin.configure(**kept)


# =============================================================================== money

def test_money_floats_are_read_as_written():
    assert money.D(0.1) + money.D(0.2) == D("0.3")
    assert money.total([0.1, 0.2, 0.3]) == D("0.60")
    assert money.D(None) == 0 and money.D("1,250.50") == D("1250.50")


def test_money_rounds_half_up_to_the_minor_unit():
    assert money.quantize("2.345") == D("2.35")
    assert money.quantize("2.344") == D("2.34")
    assert money.quantize(1234.5, "JPY") == D("1235")
    assert money.quantize("1.2345", "KWD") == D("1.235")


def test_money_allocation_loses_nothing():
    parts = money.allocate(1000, [1, 1, 1])
    assert parts == [D("333.34"), D("333.33"), D("333.33")] and sum(parts) == D("1000.00")
    assert sum(money.allocate("0.05", [50, 30, 20])) == D("0.05")
    assert money.allocate(-100, [1, 3]) == [D("-25.00"), D("-75.00")]


def test_money_formats_for_people():
    assert money.fmt(1234567.5, "GBP") == "£1,234,567.50"
    assert money.fmt(1234567.5, "GBP", compact=True) == "£1.23M"
    assert money.fmt(48250, "EUR", compact=True) == "€48.3k"
    assert money.fmt(-420, "GBP", accounting=True) == "(£420.00)"
    assert money.fmt(120, "GBP", signed=True) == "+£120.00"
    assert money.fmt(None) == "—"


def test_money_does_not_add_pounds_to_euros():
    assert str(money.Money.of(10, "GBP") + money.Money.of("2.50", "GBP")) == "£12.50"
    with pytest.raises(ValueError):
        money.Money.of(10, "GBP") + money.Money.of(10, "EUR")


def test_money_tax_both_ways():
    assert money.add_tax(1250, 20) == (D("1250.00"), D("250.00"), D("1500.00"))
    assert money.remove_tax(1500, 20) == (D("1250.00"), D("250.00"), D("1500.00"))


# ============================================================================== periods

def test_periods_an_april_year():
    cal = periods.FiscalCalendar(4)
    assert cal.fiscal_year(dt.date(2026, 9, 25)) == 2027 and cal.fiscal_year(dt.date(2026, 3, 31)) == 2026
    assert cal.quarter(dt.date(2026, 9, 25)) == 2 and cal.period(dt.date(2026, 4, 1)) == 1
    assert cal.bounds("quarter", dt.date(2026, 9, 25)) == (dt.date(2026, 7, 1), dt.date(2026, 9, 30))
    assert cal.bounds("year", dt.date(2026, 9, 25)) == (dt.date(2026, 4, 1), dt.date(2027, 3, 31))
    assert cal.label("quarter", dt.date(2026, 9, 25)) == "Q2 FY2027"


def test_periods_a_calendar_year_and_comparisons():
    cal = periods.CALENDAR_YEAR
    assert cal.fiscal_year(dt.date(2026, 9, 25)) == 2026 and cal.quarter(dt.date(2026, 9, 25)) == 3
    assert cal.prior("month", dt.date(2026, 3, 15)) == (dt.date(2026, 2, 1), dt.date(2026, 2, 28))
    assert cal.to_date("year", dt.date(2026, 9, 25)) == (dt.date(2026, 1, 1), dt.date(2026, 9, 25))
    assert cal.year_ago(dt.date(2024, 2, 29), dt.date(2024, 3, 31)) == (dt.date(2023, 2, 28), dt.date(2023, 3, 31))
    assert [cal.label("month", s) for s, _ in cal.last("month", 3, dt.date(2026, 1, 10))] == ["Nov 2025", "Dec 2025", "Jan 2026"]


def test_periods_ageing_buckets():
    assert periods.aging_bucket(dt.date(2026, 9, 25), TODAY) == "Not due"
    assert periods.aging_bucket(dt.date(2026, 9, 24), TODAY) == "1-30"
    assert periods.aging_bucket(dt.date(2026, 8, 26), TODAY) == "1-30"
    assert periods.aging_bucket(dt.date(2026, 8, 25), TODAY) == "31-60"
    assert periods.aging_bucket(dt.date(2026, 6, 26), TODAY) == "90+"
    assert periods.aging_buckets() == ["Not due", "1-30", "31-60", "61-90", "90+"]


def test_periods_business_days_skip_weekends_and_holidays():
    friday = dt.date(2026, 9, 25)
    assert periods.add_business_days(friday, 1) == dt.date(2026, 9, 28)
    assert periods.add_business_days(friday, 1, holidays=[dt.date(2026, 9, 28)]) == dt.date(2026, 9, 29)
    assert periods.business_days_between(friday, dt.date(2026, 10, 2)) == 5


# ============================================================================ finance rules

def test_fin_01_requester_cannot_approve():
    with pytest.raises(RuleViolation) as err:
        fin.check_segregation({"request": "Nadia Rahman", "approve": "nadia rahman "})
    assert err.value.rule_id == "FIN-01"


def test_fin_01_different_people_pass():
    fin.check_segregation({"request": "Nadia Rahman", "approve": "Tom Ashworth", "order": "Daniel Moreau",
                           "receive": "Nadia Rahman"})


def test_fin_01_supplier_maintenance_and_payment_are_separate():
    with pytest.raises(RuleViolation):
        fin.check_segregation({"maintain_supplier": "Daniel Moreau", "release_payment": "Daniel Moreau"})


def test_fin_02_budget_position_and_warning_at_90():
    p = fin.budget_position(100_000, actual=60_000, committed=20_000, requested=9_999)
    assert (p.available, p.remaining, p.status) == (D(20_000), D(10_001), "ok")
    assert fin.budget_position(100_000, 60_000, 20_000, 10_000).status == "warning"      # exactly 90%


def test_fin_02_a_request_over_budget_is_refused():
    assert fin.budget_position(100_000, 60_000, 20_000, 20_000).status == "warning"      # exactly the budget
    with pytest.raises(RuleViolation) as err:
        fin.check_budget(100_000, 60_000, 20_000, "20000.01")
    assert err.value.rule_id == "FIN-02"


def test_fin_03_net_and_end_of_month_terms():
    assert fin.due_date(dt.date(2026, 9, 10), "NET30") == dt.date(2026, 10, 10)
    assert fin.due_date(dt.date(2026, 9, 10), "Net 45") == dt.date(2026, 10, 25)
    assert fin.due_date(dt.date(2026, 9, 10), "EOM30") == dt.date(2026, 10, 30)
    assert fin.due_date(dt.date(2026, 9, 10), "COD") == dt.date(2026, 9, 10)


def test_fin_03_discount_terms_parse():
    t = fin.parse_terms("2/10 net 30")
    assert (t.days, t.discount_pct, t.discount_days, t.end_of_month) == (30, 2.0, 10, False)
    assert fin.due_date(dt.date(2026, 9, 10), t) == dt.date(2026, 10, 10)
    assert fin.parse_terms("").days == 30 and fin.parse_terms("something odd").days == 30


def test_fin_04_discount_inside_the_window():
    d = fin.early_payment_discount(10_000, dt.date(2026, 9, 1), "2/10NET30", as_of=dt.date(2026, 9, 11))
    assert d.available and d.amount == D("200.00") and d.pay == D("9800.00") and d.last_day == dt.date(2026, 9, 11)
    assert d.annualised_pct == 37.2


def test_fin_04_discount_lost_after_the_window_or_without_terms():
    late = fin.early_payment_discount(10_000, dt.date(2026, 9, 1), "2/10NET30", as_of=dt.date(2026, 9, 12))
    assert not late.available and late.amount == 0 and late.pay == D("10000.00")
    assert not fin.early_payment_discount(10_000, dt.date(2026, 9, 1), "NET30").available


def test_fin_05_interest_by_the_day():
    assert fin.late_interest(10_000, dt.date(2026, 8, 26), TODAY, annual_rate_pct=8) == D("65.75")     # 30 days


def test_fin_05_nothing_until_it_is_overdue():
    assert fin.late_interest(10_000, TODAY, TODAY) == 0
    assert fin.late_interest(10_000, dt.date(2026, 9, 24), TODAY, annual_rate_pct=8) == D("2.19")


def test_fin_06_tax_from_net_and_from_gross():
    t = fin.tax(1250, rate="standard")
    assert (t.net, t.tax, t.gross, t.rate_pct) == (D("1250.00"), D("250.00"), D("1500.00"), 20.0)
    assert fin.tax(gross=1500, rate=20).net == D("1250.00")
    assert fin.tax(99.99, rate="reduced").tax == D("5.00")


def test_fin_06_reverse_charge_and_a_wrong_invoice():
    assert fin.tax(1250, rate="standard", reverse_charge=True).tax == 0
    fin.check_tax(1250, 250, 1500)
    with pytest.raises(RuleViolation) as err:
        fin.check_tax(1250, 245, 1495)
    assert err.value.rule_id == "FIN-06"


def test_fin_07_under_budget_on_a_cost_is_favourable():
    v = fin.variance(94_000, 100_000)
    assert (v.amount, v.pct, v.favourable, v.material) == (D(-6000), -6.0, True, True)


def test_fin_07_materiality_needs_both_the_share_and_the_amount():
    assert fin.variance(104_999, 100_000).material is False       # 4.999%
    assert fin.variance(105_000, 100_000).material is True and fin.variance(105_000, 100_000).favourable is False
    assert fin.variance(1_900, 1_000).material is False           # 90%, but only 900
    assert fin.variance(110, 100, kind="revenue").favourable is True


def test_fin_08_received_not_invoiced_is_accrued():
    assert fin.grni(12_000, 7_500) == D("4500.00")
    rows = fin.accruals([Rec(id=1, reference="PO-1", supplier_id=3, cost_center_id=2, status="received",
                             received_amount=12_000, invoiced_amount=7_500),
                         Rec(id=2, reference="PO-2", supplier_id=3, cost_center_id=2, status="received",
                             received_amount=500, invoiced_amount=500)])
    assert [r["accrual"] for r in rows] == [4500.0]


def test_fin_08_never_below_zero():
    assert fin.grni(5_000, 5_400) == 0


def test_fin_09_shares_sum_to_the_amount():
    parts = fin.allocate("1000.01", {"CC-100": 60, "CC-200": 25, "CC-300": 15})
    assert parts == {"CC-100": D("600.01"), "CC-200": D("250.00"), "CC-300": D("150.00")}
    assert sum(parts.values()) == D("1000.01")


def test_fin_09_refuses_empty_or_negative_shares():
    for shares in ({}, {"CC-100": -1, "CC-200": 2}, {"CC-100": 0}):
        with pytest.raises(RuleViolation) as err:
            fin.allocate(100, shares)
        assert err.value.rule_id == "FIN-09"


def test_fin_10_a_posting_into_a_closed_period_is_refused():
    with pytest.raises(RuleViolation) as err:
        fin.check_period_open(dt.date(2026, 8, 31), closed_through=dt.date(2026, 8, 31))
    assert err.value.rule_id == "FIN-10"


def test_fin_10_the_first_open_day_posts():
    fin.check_period_open(dt.date(2026, 9, 1), closed_through=dt.date(2026, 8, 31))
    fin.check_period_open(dt.date(2020, 1, 1), closed_through=None)


def test_fin_11_paying_at_a_worse_rate_is_a_loss():
    r = fin.fx_difference(11_700, booking_rate="1.17", settlement_rate="1.15")
    assert (r.booked, r.settled, r.difference, r.gain) == (D("10000.00"), D("10173.91"), D("173.91"), False)


def test_fin_11_a_better_rate_is_a_gain_and_a_rate_must_be_positive():
    assert fin.fx_difference(11_700, 1.17, 1.20).gain is True
    assert fin.to_base(1_170, 1.17) == D("1000.00")
    with pytest.raises(RuleViolation):
        fin.fx_difference(100, 0, 1.2)


# ======================================================================== procurement rules

def order(amount=10_000):
    return Rec(id=1, amount=amount, status="received")


def receipt(amount, status="posted"):
    return Rec(amount=amount, status=status)


def test_proc_01_an_invoice_that_agrees_matches():
    m = fin.three_way_match(order(), [receipt(10_000)], Rec(net_amount=10_000, amount=12_000))
    assert m.ok and m.status == "matched" and m.discrepancies == []


def test_proc_01_inside_tolerance_matches_and_outside_does_not():
    assert fin.three_way_match(order(2_000), [receipt(2_000)], Rec(net_amount=2_040)).ok          # 2%, and 40 ≤ 50
    over = fin.three_way_match(order(2_000), [receipt(2_000)], Rec(net_amount="2040.01"))
    assert not over.ok and over.status == "price_variance" and over.price_delta == D("40.01")
    capped = fin.three_way_match(order(10_000), [receipt(10_000)], Rec(net_amount=10_051))         # 0.5%, but over 50
    assert not capped.ok
    assert fin.three_way_match(order(10_000), [receipt(10_000)], Rec(net_amount=10_051),
                               fin.Tolerance(price_pct=2, amount_abs=None)).ok


def test_proc_01_more_than_was_received():
    m = fin.three_way_match(order(10_000), [receipt(6_000), receipt(1_000, "reversed")], Rec(net_amount=9_000))
    assert not m.ok and m.status == "quantity_variance" and m.quantity_delta == D("3000.00")
    part = fin.three_way_match(order(10_000), [receipt(6_000)], Rec(net_amount=6_000))
    assert part.ok


def test_proc_01_no_order_and_no_receipt():
    assert fin.three_way_match(None, [], Rec(net_amount=500)).status == "no_po"
    assert fin.three_way_match(order(), [], Rec(net_amount=500)).status == "no_receipt"


def test_proc_01_a_second_invoice_counts_what_the_first_took():
    second = fin.three_way_match(order(10_000), [receipt(10_000)], Rec(net_amount=5_000), already_invoiced=6_000)
    assert not second.ok and second.price_delta == D("1000.00")


def test_proc_01_by_line():
    assert fin.match_line(10, 100, 10, 10, 102).ok                                                 # 2% on price
    assert fin.match_line(10, 100, 10, 10, "102.01").status == "price_variance"
    assert fin.match_line(10, 100, 8, 10, 100).status == "quantity_variance"
    assert fin.match_line(10, 100, 0, 10, 100).status == "no_receipt"
    assert fin.match_line(10, 100, 100, 102, 100, fin.Tolerance(quantity_pct=2, amount_abs=None)).ok


def test_proc_02_the_amount_decides_who_approves():
    assert fin.approver_for(5_000) == "budget_holder"
    assert fin.approver_for("5000.01") == "head_of_department"
    assert fin.approver_for(25_000) == "head_of_department"
    assert fin.approver_for(100_000) == "finance_director"
    assert fin.approver_for(100_001) == "cfo"
    assert fin.approver_for(7_500, [(1_000, "lead"), (None, "director")]) == "director"


def test_proc_02_an_approval_above_the_limit_is_refused():
    fin.check_authority(5_000, "budget_holder")
    fin.check_authority(5_000, "cfo")
    with pytest.raises(RuleViolation) as err:
        fin.check_authority(5_001, "budget_holder")
    assert err.value.rule_id == "PROC-02" and err.value.details["needs"] == "head_of_department"
    assert fin.approval_chain(30_000) == ["budget_holder", "head_of_department", "finance_director"]


def invoice_(id, number, amount, date, supplier=7, status="approved"):
    return Rec(id=id, supplier_id=supplier, supplier_invoice_number=number, amount=amount,
               invoice_date=date, status=status)


def test_proc_03_the_same_number_written_differently():
    assert fin.normalise_invoice_number("INV-00123") == fin.normalise_invoice_number("inv 123") == "123"
    assert fin.normalise_invoice_number("AB/O1O") == fin.normalise_invoice_number("ab-010")
    found = fin.duplicate_invoices(invoice_(2, "INV-0123", 1200, dt.date(2026, 9, 20)),
                                   [invoice_(1, "inv 123", 1200, dt.date(2026, 9, 1))])
    assert [f["confidence"] for f in found] == ["exact"]


def test_proc_03_same_amount_within_45_days_and_not_after():
    new = invoice_(3, "B-77", 880.5, dt.date(2026, 9, 20))
    near = invoice_(1, "B-12", 880.5, dt.date(2026, 8, 6))          # 45 days before
    far = invoice_(2, "B-09", 880.5, dt.date(2026, 8, 5))           # 46 days before
    other_supplier = invoice_(4, "B-77", 880.5, dt.date(2026, 9, 20), supplier=8)
    rejected = invoice_(5, "B-77", 880.5, dt.date(2026, 9, 19), status="rejected")
    found = fin.duplicate_invoices(new, [near, far, other_supplier, rejected, new])
    assert [(f["invoice"].id, f["confidence"]) for f in found] == [(1, "possible")]


def test_proc_04_saving_against_the_baseline():
    s = fin.saving(baseline_price=120, negotiated_price=105, quantity=1_000)
    assert (s.baseline, s.negotiated, s.amount, s.pct) == (D("120000.00"), D("105000.00"), D("15000.00"), 12.5)


def test_proc_04_realised_as_the_volume_is_bought():
    assert fin.realised_saving(15_000, bought_quantity=400, planned_quantity=1_000) == D("6000.00")
    assert fin.realised_saving(15_000, 1_400, 1_000) == D("15000.00")
    assert fin.realised_saving(15_000, 10, 0) == 0


def test_proc_05_a_sound_supplier_is_low_risk():
    r = fin.supplier_risk(otif_pct=98, quality_pct=99, financial_health_pct=95, compliance_pct=100, spend_share_pct=5)
    assert r.rating == "low" and r.score == 8.8
    assert r.parts == {"delivery": 2.0, "quality": 0.8, "financial": 5.0, "compliance": 0.0, "dependency": 1.0}


def test_proc_05_bands_at_34_and_67():
    assert fin.supplier_risk(otif_pct=75, quality_pct=100, financial_health_pct=91.1).rating == "low"       # 33.9
    assert fin.supplier_risk(otif_pct=75, quality_pct=100, financial_health_pct=91).rating == "medium"      # 34.0
    assert fin.supplier_risk(otif_pct=70, quality_pct=80, financial_health_pct=70, compliance_pct=60,
                             spend_share_pct=60).rating == "high"


def test_proc_05_the_demonstration_data_scores_the_same_way():
    for args in ((91.2, 96.5, 84.0, 100, 12.0), (62.0, 80.0, 45.0, 70, 55.0), (99.5, 99.9, 98.0, 100, 0.0)):
        r = fin.supplier_risk(*args)
        assert demo.risk(*args) == (r.score, r.rating)


def test_proc_06_above_the_threshold_an_order_is_needed():
    assert fin.po_required(1_000) is False and fin.po_required("1000.01") is True
    assert fin.po_required(50_000, exempt=True) is False
    with pytest.raises(RuleViolation) as err:
        fin.check_po(Rec(amount=1_500, purchase_order_id=None))
    assert err.value.rule_id == "PROC-06"


def test_proc_06_an_invoice_with_an_order_passes():
    fin.check_po(Rec(amount=1_500, purchase_order_id=12))
    fin.check_po(Rec(amount=900, purchase_order_id=None))


def test_proc_07_expiring_within_90_days():
    assert fin.renewal(dt.date(2026, 12, 25), TODAY).status == "active"             # 91 days
    r = fin.renewal(dt.date(2026, 12, 24), TODAY, notice_days=30)                   # 90 days
    assert r.status == "expiring" and r.decide_by == dt.date(2026, 11, 24) and r.days_left == 90


def test_proc_07_after_the_notice_date_and_after_the_end():
    late = fin.renewal(dt.date(2026, 11, 1), TODAY, notice_days=60, auto_renew=True)
    assert late.status == "notice_due" and "renews automatically" in late.note
    assert fin.renewal(dt.date(2026, 9, 24), TODAY).status == "expired"


def test_proc_08_paying_less_than_standard_is_favourable():
    v = fin.price_variance(standard_price=10, actual_price="9.40", quantity=5_000)
    assert v.amount == D("-3000.00") and v.favourable and v.pct == -6.0


def test_proc_08_paying_more_is_adverse():
    assert fin.price_variance(10, 10.5, 100).favourable is False


def test_proc_09_only_approved_or_active_suppliers():
    fin.check_supplier(Rec(name="Calder Freight Ltd", status="active"))
    fin.check_supplier({"name": "Calder Freight Ltd", "status": "approved"})


def test_proc_09_a_suspended_supplier_is_refused():
    for status in ("suspended", "under_review", "prospective", "retired", ""):
        with pytest.raises(RuleViolation) as err:
            fin.check_supplier(Rec(name="Calder Freight Ltd", status=status))
        assert err.value.rule_id == "PROC-09"


def test_proc_10_quotes_by_amount():
    assert fin.quotes_needed(5_000) == {"quotes": 1, "tender": False}
    assert fin.quotes_needed("5000.01") == {"quotes": 3, "tender": False}
    assert fin.quotes_needed(25_001) == {"quotes": 3, "tender": True}


def test_proc_10_too_few_quotes_need_a_justification():
    fin.check_quotes(12_000, 3)
    fin.check_quotes(12_000, 1, single_source_justification="The only licensed distributor")
    with pytest.raises(RuleViolation) as err:
        fin.check_quotes(12_000, 2)
    assert err.value.rule_id == "PROC-10"


def request_(amount, day, who="Ben Thackeray", supplier=4, status="submitted"):
    return Rec(amount=amount, created_at=dt.date(2026, 9, day), requester_name=who, supplier_id=supplier, status=status)


def test_proc_11_requests_that_together_cross_the_limit():
    found = fin.split_orders([request_(4_800, 1), request_(4_900, 3), request_(300, 20)], limit=5_000)
    assert len(found) == 1 and found[0]["total"] == 9700.0 and len(found[0]["requests"]) == 2


def test_proc_11_apart_in_time_or_by_different_people_is_not_a_split():
    assert fin.split_orders([request_(4_800, 1), request_(4_900, 9)], limit=5_000) == []            # 8 days apart
    assert fin.split_orders([request_(4_800, 1), request_(4_900, 2, who="Chloe Martin")], limit=5_000) == []
    assert fin.split_orders([request_(2_000, 1), request_(2_900, 2)], limit=5_000) == []            # together inside it


def test_policy_an_organisation_sets_its_numbers_once():
    fin.configure(doa=[(2_000, "budget_holder"), (20_000, "head_of_department"), (None, "cfo")],
                  tolerance=fin.Tolerance(price_pct=1, quantity_pct=0, amount_abs=25), po_required_above=500,
                  budget_warning_pct=80, expiring_days=120)
    assert fin.approver_for(2_000) == "budget_holder" and fin.approver_for("2000.01") == "head_of_department"
    assert fin.approver_for(20_001) == "cfo" and fin.first_limit() == 2_000
    assert flows.ByAmount()(Rec(amount=15_000)) == "head_of_department"
    assert flows.ByAmount().roles == ("budget_holder", "head_of_department", "cfo")
    assert fin.three_way_match(order(2_000), [receipt(2_000)], Rec(net_amount=2_020)).ok                 # 1%, and 20 <= 25
    assert not fin.three_way_match(order(2_000), [receipt(2_000)], Rec(net_amount=2_021)).ok
    assert fin.po_required(500) is False and fin.po_required("500.01") is True
    assert fin.budget_position(100_000, 60_000, 0, 20_000).status == "warning"                          # 80%
    assert fin.renewal(dt.date(2027, 1, 23), TODAY).status == "expiring"                                # 120 days
    assert fin.split_orders([request_(1_500, 1), request_(1_200, 3)]) != []                              # together above 2,000
    fin.reset()
    assert fin.approver_for(5_000) == "budget_holder" and fin.po_required(1_000) is False


def test_policy_refuses_what_it_does_not_know():
    with pytest.raises(TypeError) as err:
        fin.configure(tolerence=fin.Tolerance())
    assert "tolerence" in str(err.value) and "tolerance" in str(err.value)
    with pytest.raises(ValueError):
        fin.configure(doa=[(2_000, "budget_holder"), (20_000, "cfo")])          # nobody approves above 20,000
    assert fin.configure(tolerance={"price_pct": 3}).tolerance == fin.Tolerance(price_pct=3)


def test_every_library_rule_is_in_the_catalogue():
    ids = {f"FIN-{i:02d}" for i in range(1, 12)} | {f"PROC-{i:02d}" for i in range(1, 12)}
    assert ids <= set(RULES), sorted(ids - set(RULES))
    assert all(RULES[i].source == fin.SOURCE for i in ids)


# ============================================================================ analytics

INVOICES = [
    Rec(id=1, supplier_id=1, cost_center_id=10, amount=600.10, invoice_date=dt.date(2026, 7, 3), due_date=dt.date(2026, 8, 2),
        purchase_order_id=5, match_status="matched", paid_at=dt.date(2026, 8, 1), discount_available=12, discount_taken=12),
    Rec(id=2, supplier_id=1, cost_center_id=10, amount=300.20, invoice_date=dt.date(2026, 9, 3), due_date=dt.date(2026, 10, 3),
        purchase_order_id=6, match_status="price_variance", paid_at=None, discount_available=0, discount_taken=0),
    Rec(id=3, supplier_id=2, cost_center_id=20, amount=99.70, invoice_date=dt.date(2026, 9, 20), due_date=dt.date(2026, 8, 20),
        purchase_order_id=None, match_status="no_po", paid_at=dt.date(2026, 9, 1), discount_available=8, discount_taken=0),
]


def test_analytics_group_sum_with_shares_and_other():
    rows = fa.group_sum(INVOICES, "supplier_id", names={1: "Calder Freight", 2: "Ashby Legal"})
    assert [(r["label"], r["value"], r["count"], r["share_pct"]) for r in rows] == [
        ("Calder Freight", 900.3, 2, 90.0), ("Ashby Legal", 99.7, 1, 10.0)]
    assert [r["label"] for r in fa.group_sum(INVOICES, "id", top=1)] == ["1", "Other"]
    assert fa.total(INVOICES) == 1000.0


def test_analytics_trend_has_every_period():
    points = fa.trend(INVOICES, "invoice_date", kind="month", periods=4, end=TODAY)
    assert [(p["label"], p["value"], p["count"]) for p in points] == [
        ("Jun 2026", 0.0, 0), ("Jul 2026", 600.1, 1), ("Aug 2026", 0.0, 0), ("Sep 2026", 399.9, 2)]
    assert fa.cumulative(points)[-1]["cumulative"] == 1000.0
    quarters = fa.trend(INVOICES, "invoice_date", kind="quarter", periods=2, end=TODAY, calendar=periods.APRIL_YEAR)
    assert [q["label"] for q in quarters] == ["Q1 FY2027", "Q2 FY2027"]


def test_analytics_budget_against_actual():
    budgets = [Rec(cost_center_id=10, amount=1_000), Rec(cost_center_id=20, amount=50)]
    orders = [Rec(cost_center_id=10, amount=50)]
    rows = {r["key"]: r for r in fa.budget_vs_actual(budgets, INVOICES, committed=orders)}
    assert rows[10]["actual"] == 900.3 and rows[10]["committed"] == 50 and rows[10]["available"] == 49.7
    assert rows[10]["status"] == "warning" and rows[10]["favourable"] is True
    assert rows[20]["status"] == "exceeded" and rows[20]["variance"] == 49.7 and rows[20]["favourable"] is False


def test_analytics_ageing_keeps_empty_buckets():
    rows = fa.aging([i for i in INVOICES if i.paid_at is None] + [Rec(due_date=dt.date(2026, 6, 1), amount=40)], as_of=TODAY)
    assert [(r["label"], r["value"], r["count"]) for r in rows] == [
        ("Not due", 300.2, 1), ("1-30", 0.0, 0), ("31-60", 0.0, 0), ("61-90", 0.0, 0), ("90+", 40.0, 1)]


def test_analytics_concentration_and_pivot():
    c = fa.concentration(INVOICES, "supplier_id")
    assert c["groups_for_cut"] == 1 and c["hhi"] == 8200 and c["items"][1]["cumulative_pct"] == 100.0
    p = fa.pivot(INVOICES, "cost_center_id", lambda r: r.invoice_date.strftime("%b"), column_order=["Jul", "Sep"])
    assert p["rows"][0] == {"key": 10, "label": "10", "total": 900.3, "cells": [600.1, 300.2]}
    assert p["totals"] == [600.1, 399.9] and p["total"] == 1000.0


def test_analytics_procurement_kpis():
    assert fa.po_coverage(INVOICES) == 90.0
    assert fa.first_time_match_rate(INVOICES) == 33.3 and fa.exception_rate(INVOICES) == 66.7
    assert fa.contracted_spend(INVOICES, [1]) == 90.0 and fa.maverick_spend(INVOICES, [1]) == 10.0
    assert fa.on_time_payment(INVOICES) == 50.0
    assert fa.discount_capture(INVOICES) == {"offered": 20.0, "taken": 12.0, "missed": 8.0, "capture_pct": 60.0}
    assert fa.days_payable_outstanding(300.2, 1000, days_in_period=90) == 27.0
    assert fa.cycle_time(INVOICES, "invoice_date", "paid_at")["count"] == 1
    assert fa.otif([Rec(on_time=True, in_full=True), Rec(on_time=True, in_full=False)]) == 50.0
    assert fa.funnel([("Requested", [1, 2, 3, 4]), ("Ordered", [1, 2, 3])], amount=None)[1]["of_first_pct"] == 75.0
    assert fa.compare(110, 100)["change_pct"] == 10.0


# ============================================================ standard entities and data

def test_standard_entities_render_as_the_platform_writes_them():
    sql = standard.create_table("invoice")
    assert "CREATE TABLE IF NOT EXISTS invoice (" in sql and "id SERIAL PRIMARY KEY" in sql
    assert "status VARCHAR(30) NOT NULL DEFAULT 'received',  -- received|matched|exception|approved|scheduled|paid|rejected" in sql
    model = standard.model_class("purchase_order")
    assert 'class PurchaseOrder(Base):' in model and '__tablename__ = "purchase_order"' in model
    assert "supplier_id: Mapped[int] = mapped_column(Integer)" in model
    assert set(flows.FACTORIES) <= set(standard.STATES)


def test_standard_gaps_name_the_missing_core_columns():
    assert standard.gaps({"invoice": ["id", "reference", "supplier_id", "amount", "status", "invoice_date"],
                          "widget": ["id"]}) and "due_date" in standard.gaps({"invoice": ["reference"]})[0]
    assert standard.gaps({"supplier": ["code", "name", "status", "extra"]}) == []


def test_demo_data_is_coherent():
    data = demo.rows(None, today=TODAY)
    assert list(data) == standard.ORDER and demo.rows(None, today=TODAY) == data          # deterministic
    for table, rows in data.items():
        assert rows, table
        columns = {c[0]: c for c in standard.ENTITIES[table]["columns"]}
        for row in rows:
            assert set(row) <= set(columns)
            for name, (_, kind, required, note) in columns.items():
                value = row.get(name)
                assert value is not None or not required, (table, name)
                if value is not None and kind.startswith("ref:"):
                    assert 1 <= value <= len(data[kind[4:]]), (table, name, value)
                if value is not None and standard.allowed_values(note):
                    assert value in standard.allowed_values(note), (table, name, value)
    statuses = {r["status"] for r in data["invoice"]}
    assert {"received", "matched", "exception", "approved", "scheduled", "paid"} <= statuses
    assert {r["status"] for r in data["requisition"]} == set(standard.STATES["requisition"])
    for inv in data["invoice"]:
        assert abs(inv["net_amount"] + inv["tax_amount"] - inv["amount"]) < 0.011
        assert (inv["status"] == "paid") == (inv["paid_at"] is not None)


def test_demo_data_fits_the_tables_an_application_has():
    data = demo.rows({"supplier": ["id", "code", "name", "status"], "invoice": ["id", "reference", "supplier_id", "amount",
                                                                               "status", "purchase_order_id"],
                      "ticket": ["id", "subject"]}, today=TODAY)
    assert list(data) == ["supplier", "invoice"]
    assert set(data["supplier"][0]) == {"code", "name", "status"}
    assert all(r["purchase_order_id"] is None for r in data["invoice"])       # there is no purchase_order table to point at


# ============================================================================== people

def test_personas_cover_every_role_and_keep_duties_apart():
    assert [p["roles"][0] for p in personas.people()] == list(personas.ROLES)
    grants = personas.permissions()
    assert "invoice:approve" not in grants["requester"] and "requisition:submit" in grants["requester"]
    assert not any(g.startswith("payment_run:release") for g in grants["ap_clerk"])
    assert "payment_run:release" in grants["treasury"] and grants["admin"] == ["*"]
    some = personas.roles("requester", "buyer")
    assert list(some) == ["requester", "buyer", "admin"] and len(personas.people(some)) == 3
    with pytest.raises(KeyError):
        personas.roles("wizard")


# ============================================================================ workflows

class FinRequisition(Base):
    __tablename__ = "fin_test_requisition"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(100), default="")
    amount: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(30), default="draft")
    purchase_order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FinInvoice(Base):
    __tablename__ = "fin_test_invoice"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    amount: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(30), default="received")
    match_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    exception_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    approver_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    approved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payment_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    discount_taken: Mapped[float | None] = mapped_column(Float, nullable=True)


REQUISITION = register(flows.requisition(FinRequisition, name="fin_test_requisition"))
INVOICE = register(flows.invoice(FinInvoice, doa=[(10_000, "budget_holder"), (None, "finance_director")],
                                 name="fin_test_invoice"))

NADIA = Actor(1, "nadia", "Nadia Rahman", ("requester",))
TOM = Actor(2, "tom", "Tom Ashworth", ("budget_holder", "requester"))
ARJUN = Actor(3, "arjun", "Arjun Mehta", ("finance_director",))
DANIEL = Actor(4, "daniel", "Daniel Moreau", ("buyer",))
KOFI = Actor(5, "kofi", "Kofi Mensah", ("ap_clerk",))


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    audit.install()
    connectors.set_store(connectors.MemoryStore())
    session = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def new(db, model, **values):
    row = model(**values)
    db.add(row)
    db.commit()
    return row


def test_workflow_a_request_waits_as_submitted_for_the_approver_its_amount_calls_for(db):
    small, large = new(db, FinRequisition, title="Monitors", amount=3_000), new(db, FinRequisition, title="Fit-out", amount=60_000)
    with acting_as(NADIA):
        out = transition(db, small, "submit")
        transition(db, large, "submit")
    assert out["status"] == "pending_approval" and small.status == "submitted" and large.status == "submitted"
    roles = {a.entity_id: a.approver_role for a in db.query(Approval).all()}
    assert roles == {small.id: "budget_holder", large.id: "finance_director"}
    moves = db.query(AuditEvent).filter_by(entity="fin_test_requisition", entity_id=small.id, action="transition").all()
    assert len(moves) == 1 and moves[0].rule_id == "PROC-02" and "Awaiting approval" in moves[0].summary


def test_workflow_approval_is_four_eyes_and_moves_it_on(db):
    req = new(db, FinRequisition, title="Laptops", amount=4_000)
    with acting_as(TOM):                                   # a budget holder raising their own request
        transition(db, req, "submit")
    approval = db.query(Approval).one()
    with acting_as(TOM), pytest.raises(RuleViolation) as err:
        decide(db, approval.id, True)
    assert err.value.rule_id == "WF-02"
    with acting_as(NADIA), pytest.raises(RuleViolation) as err:
        decide(db, approval.id, True)
    assert err.value.rule_id == "WF-01"
    other = Actor(9, "fiona", "Fiona MacLeod", ("budget_holder",))
    with acting_as(other):
        decide(db, approval.id, True)
    db.refresh(req)
    assert req.status == "approved"
    with acting_as(DANIEL):
        transition(db, req, "order", fields={"purchase_order_id": 77})
    assert req.status == "ordered" and req.purchase_order_id == 77


def test_workflow_a_refusal_ends_as_rejected_and_can_be_revised(db):
    req = new(db, FinRequisition, title="Stand build", amount=20_000)
    with acting_as(NADIA):
        transition(db, req, "submit")
    with acting_as(Actor(8, "helen", "Helen Okoro", ("head_of_department",))):
        decide(db, db.query(Approval).one().id, False, "Not this quarter")
    db.refresh(req)
    assert req.status == "rejected"
    with acting_as(NADIA):
        transition(db, req, "revise")
    assert req.status == "draft"


def test_workflow_guards_and_roles(db):
    empty = new(db, FinRequisition, title="Nothing", amount=0)
    with acting_as(NADIA), pytest.raises(RuleViolation) as err:
        transition(db, empty, "submit")
    assert err.value.rule_id == "PROC-02" and "amount" in err.value.message
    req = new(db, FinRequisition, title="Chairs", amount=900)
    with acting_as(KOFI), pytest.raises(RuleViolation) as err:
        transition(db, req, "submit")
    assert err.value.rule_id == "WF-01"
    req.status = "approved"
    with pytest.raises(RuleViolation) as err:
        db.commit()
    db.rollback()
    assert err.value.rule_id == "WF-00"


def test_workflow_an_invoice_from_receipt_to_payment(db):
    inv = new(db, FinInvoice, amount=12_000)
    with acting_as(KOFI):
        transition(db, inv, "flag", fields={"match_status": "price_variance", "exception_reason": "Surcharge not on the order"})
        assert inv.status == "exception" and inv.match_status == "price_variance"
        transition(db, inv, "resolve", reason="Credit note received", fields={"match_status": "matched"})
        out = transition(db, inv, "approve")
    assert out["status"] == "pending_approval" and inv.status == "matched"
    assert db.query(Approval).one().approver_role == "finance_director"
    with acting_as(ARJUN):
        decide(db, db.query(Approval).one().id, True)
    db.refresh(inv)
    assert inv.status == "approved"
    with acting_as(KOFI):
        transition(db, inv, "schedule", fields={"payment_id": 5})
    with acting_as(Actor(6, "mei", "Mei Tanaka", ("treasury",))):
        transition(db, inv, "pay", fields={"discount_taken": 0})
    assert inv.status == "paid"


def test_workflow_every_lifecycle_is_well_formed():
    model = FinRequisition
    for name, factory in flows.FACTORIES.items():
        flow = factory(model, name=f"check_{name}")
        assert list(flow.states) == standard.STATES[name] and flow.initial == standard.STATES[name][0]
        for t in flow.transitions:
            assert t.target in flow.states and all(s in flow.states for s in t.sources()), (name, t.name)
            assert t.pending is None or t.pending in flow.states
            assert t.on_reject is None or t.on_reject in flow.states
            assert set(t.roles) | set(t.approvers()) <= set(personas.ROLES), (name, t.name)
        assert flows.states(name)[flow.initial]
    by_amount = flows.ByAmount()
    assert by_amount(Rec(amount=26_000)) == "finance_director" and "cfo above" in str(by_amount)


# ============================================================================ the ERP

def test_erp_sandbox_keeps_a_ledger():
    connectors.set_store(connectors.MemoryStore())
    erp = connectors.get("erp")
    assert erp.mode == "sandbox" and "erp" in connectors.CONNECTORS
    po = erp.create_purchase_order("PO-1", "SUP-1", 1000, lines=[{"description": "Cartons", "quantity": 10,
                                                                   "unit_price": 100, "amount": 1000}],
                                   cost_center="CC-3200", idempotency_key="po-1")
    again = erp.create_purchase_order("PO-1", "SUP-1", 1000, idempotency_key="po-1")
    assert po.ok and po.key == "4500012001" and again.key == po.key and again.replayed
    inv = erp.post_invoice("INV-1", "SUP-1", 1200, net=1000, tax=200, invoice_date=dt.date(2026, 9, 3), po_number=po.key,
                           lines=[{"gl_account": "5120", "cost_center": "CC-3200", "amount": 1000}])
    assert inv.ok and erp.get_purchase_order(po.key).data["invoiced"] == 1000.0
    batch = erp.release_payments("RUN-2026-39", [{"reference": "PAY-1", "supplier": "SUP-1", "amount": 1200,
                                                  "documents": [inv.key]}], value_date=dt.date(2026, 9, 24))
    assert batch.ok and batch.key == "PB-2026-0001" and erp.invoice_status(inv.key).data["status"] == "paid"
    assert erp.gl_balances("2026-09").data["balances"] == [
        {"gl_account": "5120", "cost_center": "CC-3200", "amount": 1000.0, "currency": "GBP"}]
    assert erp.exchange_rates(dt.date(2026, 9, 24)).data["rates"]["EUR"] == 1.17


def test_erp_refuses_what_the_ledger_would():
    connectors.set_store(connectors.MemoryStore())
    erp = connectors.get("erp")
    bad = erp.post_invoice("INV-2", "SUP-1", 1200, net=1000, tax=200, lines=[{"gl_account": "5120", "amount": 900}])
    assert not bad.ok and "add up" in bad.error
    assert not erp.release_payments("RUN-1", []).ok
    assert not erp.invoice_status("5199999999").ok
    assert {"create_purchase_order", "post_invoice", "release_payments"} <= set(erp.status()["operations"])
