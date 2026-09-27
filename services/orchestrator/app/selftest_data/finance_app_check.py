"""The finance library inside an application: the insight API and the operations over the
demonstration data, as the people of the function. Written by Poiesis.

Run from the root of an application that has every standard entity, its backend on the path:

    PYTHONPATH=backend python finance_app_check.py

The platform's self-test (app/selftest_finance.py) composes such an application and runs this in
it; tools/finance/compose.py does the same on a developer's machine. No model calls, no network.
"""
import datetime as dt
import json
import os
import sys

DB_FILE = os.environ.get("FIN_DB", "/tmp/fin.db")
os.environ["DATABASE_URL"] = "sqlite:///" + DB_FILE
os.environ.setdefault("FINANCE_AS_OF", "2026-09-25")
os.environ.setdefault("JOB_SECONDS", "3600")
os.environ.setdefault("APP_NAME", "Finance Test")

from sqlalchemy import Date, DateTime  # noqa: E402

from app import models  # noqa: E402,F401
from app.db import Base, engine  # noqa: E402
from app.finance import demo, standard  # noqa: E402

TODAY = os.environ["FINANCE_AS_OF"]
FAILED: list[str] = []
PASSED: list[str] = []


def expect(what: str, ok: bool, detail: str = "") -> None:
    (PASSED if ok else FAILED).append(what)
    print(("  ok   " if ok else "  FAIL ") + what + ("" if ok else f"\n         {detail}"))


def load() -> dict:
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
    Base.metadata.create_all(engine())
    data = demo.rows(None, today=TODAY)
    with engine().begin() as conn:
        for table in standard.ORDER:
            t = Base.metadata.tables[table]
            rows = []
            for row in data[table]:
                out = dict(row)
                for col in t.columns:
                    v = out.get(col.key)
                    if isinstance(v, str) and isinstance(col.type, DateTime):
                        out[col.key] = dt.datetime.fromisoformat(v.replace("Z", "+00:00"))
                    elif isinstance(v, str) and isinstance(col.type, Date):
                        out[col.key] = dt.date.fromisoformat(v[:10])
                rows.append(out)
            if rows:
                conn.execute(t.insert(), rows)
    return data


def main() -> int:
    data = load()
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        def as_(user: str) -> dict:
            r = client.post("/api/auth/sign-in", json={"username": user})
            assert r.status_code == 200, r.text
            return {"Authorization": f"Bearer {r.json()['token']}"}

        cfo, clerk = as_("sofia"), as_("kofi")

        def get(path: str, who: dict = cfo, status: int = 200) -> dict:
            r = client.get("/api/finance" + path, headers=who)
            if r.status_code != status:
                raise AssertionError(f"GET {path} -> {r.status_code} {r.text[:400]}")
            return r.json()

        profile = client.get("/api/platform/profile").json()
        expect("the profile names the finance library and no errors", profile.get("libraries") == ["finance"]
               and not profile.get("errors"), json.dumps(profile)[:400])
        expect("the ERP connector is in the catalogue, in its sandbox", profile["connectors"].get("erp") == "sandbox",
               str(profile["connectors"]))
        expect("the library's rules are in the catalogue", profile["rules"] >= 22, str(profile["rules"]))
        expect("the library's lifecycles are registered", set(profile["workflows"]) >= {"requisition", "invoice", "purchase_order"},
               str(profile["workflows"]))
        expect("without signing in, the figures answer 401", client.get("/api/finance/kpis").status_code == 401)

        # ---- what was loaded waiting for a decision can be decided
        from app.db import _sessionmaker  # noqa: E402
        from app.kernel import workflow as wf_  # noqa: E402
        from app.kernel.context import SYSTEM, acting_as  # noqa: E402
        with _sessionmaker()() as db, acting_as(SYSTEM):
            adopted, again = wf_.adopt(db), wf_.adopt(db)
        asked_ = [q for q in data["requisition"] if q["status"] == "submitted"]
        queue = get("/approvals?mine=false&entity=requisition")
        expect("requisitions loaded as submitted are given their approval request, once",
               len(asked_) > 0 and adopted >= len(asked_) and again == 0 and queue["count"] == len(asked_)
               and all(r["approver"] and r["requested_by"] and r["status"] == "submitted" for r in queue["rows"])
               and abs(queue["amount"] - round(sum(q["amount"] for q in asked_), 2)) < 0.01, f"{adopted} {again} {queue['count']} {len(asked_)}")
        by_role = {}
        for r in queue["rows"]:
            by_role[r["approver_role"]] = by_role.get(r["approver_role"], 0) + 1
        print("        waiting, by approver:", by_role)

        cal = get("/calendar")
        expect("the calendar is an April year, in its second quarter", cal["fiscal_year"] == 2027 and cal["quarter"] == 2
               and cal["fiscal_year_label"] == "FY2027" and cal["today"] == TODAY, json.dumps(cal)[:300])
        by_key = {p["key"]: p for p in cal["presets"]}
        expect("year to date runs from 1 April to today", (by_key["fy_to_date"]["from"], by_key["fy_to_date"]["to"])
               == ("2026-04-01", TODAY) and by_key["last_quarter"]["from"] == "2026-04-01"
               and by_key["last_quarter"]["to"] == "2026-06-30", json.dumps(by_key)[:500])
        expect("every standard entity is there", all(cal["entities"].values()), str(cal["entities"]))

        dims = get("/dimensions")["dimensions"]
        expect("the filters offer cost centres, families, categories and suppliers",
               {"cost_center_id", "family", "spend_category_id", "supplier_id", "department"} <= set(dims)
               and len(dims["supplier_id"]["options"]) == len(data["supplier"]), str(list(dims)))

        # ---- the figures, checked against the rows
        inv = [i for i in data["invoice"] if i["status"] != "rejected"]
        ytd = [i for i in inv if "2026-04-01" <= i["invoice_date"] <= TODAY]
        spend = round(sum(i["net_amount"] for i in ytd), 2)
        k = get("/kpis")
        kpis = {x["key"]: x for x in k["kpis"]}
        expect("spend year to date is the sum of the invoices", abs(kpis["spend"]["value"] - spend) < 0.01,
               f"{kpis['spend']['value']} vs {spend}")
        expect("every figure is there", len(kpis) == 31, f"{len(kpis)}: {sorted(kpis)}")
        bad = [x["key"] for x in k["kpis"] if x["value"] is None]
        expect("every figure has a value", not bad, str(bad))
        expect("a figure carries its comparison, direction and trend",
               kpis["spend"]["prior"] is not None and kpis["spend"]["change_pct"] is not None
               and len(kpis["spend"]["spark"]) == 6 and kpis["po_coverage"]["favourable"] in (True, False)
               and kpis["payables"]["position"] and kpis["payables"]["spark"] == [], json.dumps(kpis["spend"])[:400])
        print("       ", {x["key"]: x["value"] for x in k["kpis"]})
        few = get("/kpis?keys=spend,overdue&period=last_quarter&compare=prior_period&spark=0")
        expect("figures can be asked for by name, for another period",
               [x["key"] for x in few["kpis"]] == ["spend", "overdue"] and few["scope"]["from"] == "2026-04-01"
               and few["scope"]["prior"] == {"from": "2026-01-01", "to": "2026-03-30"} or few["scope"]["prior"]["from"] == "2026-01-01",
               json.dumps(few["scope"]))
        odd = get("/kpis?keys=spend,variance,forecast,nonsense,Open_Payables&spark=0")
        expect("figures go by other names too, and one the library does not have is left out and named",
               [x["key"] for x in odd["kpis"]] == ["spend", "budget_variance", "forecast", "payables"]
               and odd["unknown"] == ["nonsense"] and "budget_used" in odd["known"], json.dumps(odd)[:300])
        year = {x["key"]: x["value"] for x in get("/kpis?keys=budget,budget_variance,budget_available,forecast,forecast_pct")["kpis"]}
        expect("the budget figures agree with the budget endpoint",
               abs(year["budget_variance"] - get("/budget")["totals"]["variance"]) < 0.01
               and abs(year["budget_available"] - get("/budget")["totals"]["available"]) < 0.01
               and abs(year["forecast"] - get("/budget")["totals"]["forecast"]) < 0.01, json.dumps(year))
        get("/kpis?period=whenever", status=422)
        get("/kpis?from=2026-13-01", status=422)

        b = get("/breakdown?measure=spend&by=supplier&top=10")
        expect("spend by supplier: ten and the rest, adding up to the total",
               len(b["items"]) == 11 and b["items"][-1]["other"] and abs(b["total"] - spend) < 0.01
               and abs(sum(i["value"] for i in b["items"]) - spend) < 0.02 and b["items"][0]["label"]
               and b["items"][0]["value"] >= b["items"][1]["value"], json.dumps(b["items"][:2]))
        fam = get("/breakdown?measure=spend&by=family")
        expect("spend by category family", len(fam["items"]) >= 5 and all(i["label"] for i in fam["items"])
               and abs(fam["total"] - spend) < 0.01, json.dumps(fam["items"][:3]))
        st = get("/breakdown?measure=invoiced&by=match_status")
        expect("a status is shown in words", {"Matched", "Price variance"} <= {i["label"] for i in st["items"]},
               str([i["label"] for i in st["items"]]))
        mo = get("/breakdown?measure=spend&by=month")
        expect("by month, in order, with names", [i["label"] for i in mo["items"]][:2] == ["Apr 2026", "May 2026"]
               and len(mo["items"]) == 6, str([i["label"] for i in mo["items"]]))
        one = get(f"/breakdown?measure=spend&by=category&cost_center_id={data['invoice'][0]['cost_center_id']}")
        mine = round(sum(i["net_amount"] for i in ytd if i["cost_center_id"] == data["invoice"][0]["cost_center_id"]), 2)
        expect("a filter narrows every figure", abs(one["total"] - mine) < 0.01, f"{one['total']} vs {mine}")
        it = get("/breakdown?measure=spend&by=supplier&family=IT")
        expect("a filter reached through a reference (family)", 0 < it["total"] < spend, str(it["total"]))
        get("/breakdown?measure=spend&by=colour", status=422)
        get("/breakdown?measure=profit", status=422)

        t = get("/trend?measure=spend&kind=month&periods=12")
        expect("twelve months of spend with budget and last year",
               len(t["points"]) == 12 and t["points"][-1]["label"] == "Sep 2026" and t["points"][-1]["partial"]
               and t["has_budget"] and all(p["budget"] > 0 for p in t["points"]) and t["points"][-1]["prior"] > 0,
               json.dumps(t["points"][-1]))
        q = get("/trend?measure=orders&kind=quarter&span=range&period=fiscal_year")
        expect("the quarters of the fiscal year, the ones to come included",
               [p["label"] for p in q["points"]] == ["Q1 FY2027", "Q2 FY2027", "Q3 FY2027", "Q4 FY2027"]
               and q["points"][-1]["future"] and q["points"][-1]["value"] == 0, json.dumps(q["points"][-1]))

        bud = get("/budget?by=cost_center")
        over = [r["label"] for r in bud["rows"] if r["status"] == "over"]
        tot = bud["totals"]
        expect("budget against actual by cost centre, the ones over first",
               len(bud["rows"]) == len(data["cost_center"]) and bud["rows"][0]["status"] == "over" and 1 <= len(over) <= 4
               and abs(tot["actual"] - spend) < 0.01 and tot["year_budget"] > tot["budget"], json.dumps(tot))
        expect("what is left is the year's budget less spend and commitments",
               abs(tot["available"] - (tot["year_budget"] - tot["year_actual"] - tot["committed"])) < 0.01
               and tot["position"] in ("ok", "warning") and 40 < tot["elapsed_pct"] < 60
               and 0.8 < tot["forecast"] / tot["year_budget"] < 1.2, json.dumps(tot))
        print("        over budget:", over, "used", tot["used_pct"], "year utilisation", tot["utilisation_pct"],
              "forecast", tot["forecast_pct"])
        bf = get("/budget?by=family")
        expect("budget by family lines up with spend by family",
               abs(bf["totals"]["budget"] - bud["totals"]["budget"]) < 0.01
               and all(r["budget"] > 0 for r in bf["rows"]), json.dumps(bf["rows"][:2]))
        w = get("/waterfall?by=cost_center")
        walked = w["start"]["value"] + sum(s["value"] for s in w["steps"])
        expect("the walk from budget to actual arrives", abs(walked - w["end"]["value"]) < 0.05 and len(w["steps"]) >= 3,
               f"{walked} vs {w['end']['value']}")

        a = get("/aging")
        open_ = [i for i in data["invoice"] if i["status"] in ("received", "matched", "exception", "approved", "scheduled")]
        expect("open payables by age, every bucket, adding up",
               [x["label"] for x in a["buckets"]] == ["Not due", "1-30", "31-60", "61-90", "90+"]
               and abs(a["total"] - round(sum(i["amount"] for i in open_), 2)) < 0.01 and a["count"] == len(open_)
               and a["suppliers"] and a["suppliers"][0]["overdue"] >= a["suppliers"][-1]["overdue"], json.dumps(a["buckets"]))
        f = get("/funnel")
        counts = [s["count"] for s in f["stages"]]
        expect("purchase-to-pay narrows step by step",
               [s["label"] for s in f["stages"]] == ["Requested", "Approved", "Ordered", "Received", "Invoiced", "Paid"]
               and counts == sorted(counts, reverse=True) and counts[-1] > 0, json.dumps(f["stages"]))
        p = get("/pivot?measure=spend&rows=cost_center&columns=month")
        expect("a cross-tab of cost centre by month with totals",
               len(p["columns"]) == 6 and p["columns"][0]["label"] == "Apr 2026" and abs(p["total"] - spend) < 0.01
               and abs(sum(p["totals"]) - spend) < 0.05 and len(p["rows"][0]["cells"]) == 6, json.dumps(p["rows"][0]))
        c = get("/concentration?measure=spend&by=supplier")
        expect("concentration: a Pareto ending at 100", c["items"][-1]["cumulative_pct"] == 100.0
               and 0 < c["groups_for_cut"] < c["groups"] and 30 < c["top10_share_pct"] < 80, str(c["top10_share_pct"]))
        ct = get("/cycle-times")
        expect("cycle times for each step", len(ct["steps"]) == 5 and all(s["average_days"] is not None for s in ct["steps"]),
               json.dumps(ct["steps"]))
        print("        cycle:", {s["label"]: s["average_days"] for s in ct["steps"]})

        ex = get("/exceptions")
        held = [i for i in data["invoice"] if i["status"] == "exception"]
        expect("invoices held, with why and for how long", ex["count"] == len(held) and ex["rows"][0]["supplier_name"]
               and ex["rows"][0]["days_held"] >= ex["rows"][-1]["days_held"] and ex["reasons"], json.dumps(ex["reasons"]))
        ac = get("/accruals")
        expect("accruals: received and not invoiced", ac["count"] > 0 and ac["amount"] > 0 and ac["rows"][0]["supplier_name"],
               json.dumps(ac["rows"][:1], default=str))
        rn = get("/renewals?within=180")
        expect("contracts to decide on, soonest first", rn["count"] > 0 and rn["rows"][0]["decide_by"] <= rn["rows"][-1]["decide_by"]
               and rn["rows"][0]["supplier_name"], json.dumps(rn["by_status"]))
        co = get("/controls")
        found = {x["key"]: x["count"] for x in co["controls"]}
        expect("the controls each report", set(found) == {"duplicates", "no_order", "splits", "self_approval",
                                                         "unapproved_supplier", "over_budget"}, str(found))
        print("        controls:", found)

        top = b["items"][0]["key"]
        sc = get(f"/suppliers/{top}/scorecard")
        expect("a supplier's scorecard", sc["supplier"]["id"] == top and abs(sc["kpis"]["spend"] - b["items"][0]["value"]) < 0.01
               and len(sc["trend"]) == 12 and sc["risk"]["rating"] in ("low", "medium", "high")
               and set(sc["risk"]["parts"]) == {"delivery", "quality", "financial", "compliance", "dependency"},
               json.dumps(sc["kpis"]))
        get("/suppliers/99999/scorecard", status=404)

        d = get(f"/documents?entity=invoice&supplier_id={top}")
        expect("the rows behind a number", d["count"] == sc["kpis"]["invoices"] + sum(
            1 for i in data["invoice"] if i["supplier_id"] == top and i["status"] == "rejected"
            and "2026-04-01" <= i["invoice_date"] <= TODAY) and d["rows"][0]["supplier_name"] == b["items"][0]["label"]
               and d["rows"][0]["invoice_date"] >= d["rows"][-1]["invoice_date"], f"{d['count']} {sc['kpis']['invoices']}")
        od = get("/documents?entity=invoice&overdue=true&dated=false&sort=-amount")
        expect("overdue invoices, largest first", od["count"] == sum(1 for i in open_ if i["due_date"] < TODAY)
               and od["rows"][0]["amount"] >= od["rows"][1]["amount"] and od["rows"][0]["days_overdue"] > 0,
               f"{od['count']}")
        bk = get("/documents?entity=invoice&bucket=31-60&dated=false")
        expect("the invoices of one ageing bucket", bk["count"] == a["buckets"][2]["count"]
               and abs(bk["amount"] - a["buckets"][2]["value"]) < 0.01, f"{bk['count']} vs {a['buckets'][2]}")
        wh = get("/documents?entity=invoice&where=match_status:price_variance")
        expect("rows by any dimension", wh["count"] > 0 and all(r["match_status"] == "price_variance" for r in wh["rows"]))
        po = get("/documents?entity=purchase_order&q=" + data["purchase_order"][5]["reference"] + "&dated=false")
        expect("search finds a reference", po["count"] == 1, str(po["count"]))
        get("/documents?entity=widget", status=404)

        # ---- what people do to their records
        nadia, mei = as_("nadia"), as_("mei")

        def post(path: str, who: dict, body: dict | None = None, status: int = 200) -> dict:
            r = client.post("/api/finance" + path, headers=who, json=body or {})
            if r.status_code != status:
                raise AssertionError(f"POST {path} -> {r.status_code} {r.text[:400]}")
            return r.json()

        waiting = [(n + 1, i) for n, i in enumerate(data["invoice"]) if i["status"] == "received" and i["purchase_order_id"]]
        inv_id, inv = waiting[0]
        seen = get(f"/invoices/{inv_id}/match", clerk)
        expect("what matching would find, without moving the invoice",
               seen["status"] in ("matched", "price_variance", "quantity_variance", "no_receipt", "duplicate_suspect")
               and seen["moved"] is None and seen["invoiced"] == inv["net_amount"], json.dumps(seen))
        post(f"/invoices/{inv_id}/match", mei, status=403)
        done = post(f"/invoices/{inv_id}/match", clerk)
        now_ = client.get(f"/api/invoices/{inv_id}", headers=clerk).json()
        expect("accounts payable matches an invoice, and it moves to matched or to exception with the reason",
               done["moved"] == ("matched" if done["ok"] else "exception") and now_["status"] == done["moved"]
               and now_["match_status"] == done["status"] and (done["ok"] or now_["exception_reason"]), json.dumps(done))
        trail = client.get(f"/api/platform/audit?entity=invoice&entity_id={inv_id}", headers=clerk).json()
        expect("the audit trail says which rule decided", any(e["rule"] in ("PROC-01", "PROC-03", "PROC-06") for e in trail),
               json.dumps(trail)[:300])
        bare = next(n + 1 for n, i in enumerate(data["invoice"]) if i["status"] == "exception" and i["match_status"] == "no_po")
        expect("an invoice above the limit with no order is no_po (PROC-06)",
               get(f"/invoices/{bare}/match", clerk)["rule"] == "PROC-06")

        po_id, po = next((n + 1, o) for n, o in enumerate(data["purchase_order"]) if o["status"] == "sent")
        half = post(f"/purchase-orders/{po_id}/receive", nadia, {"amount": round(po["amount"] / 2, 2), "quantity": 1})
        rest = post(f"/purchase-orders/{po_id}/receive", nadia, {"amount": round(po["amount"] - round(po["amount"] / 2, 2), 2)})
        expect("goods received in two parts move the order to partly received, then received",
               half["status"] == "partially_received" and not half["in_full"] and rest["status"] == "received" and rest["in_full"]
               and abs(rest["received_so_far"] - po["amount"]) < 0.01 and rest["goods_receipt_id"] == half["goods_receipt_id"] + 1
               and rest["on_time"] in (True, False), json.dumps(rest, default=str))
        r = client.post(f"/api/finance/purchase-orders/{po_id}/receive", headers=nadia, json={"amount": 5})
        expect("an order already received takes no more (409, PROC-01)", r.status_code == 409 and r.json().get("rule") == "PROC-01",
               r.text[:300])

        due = get("/payment-runs/payable?due_by=2026-12-31", clerk)
        approved = [i for i in data["invoice"] if i["status"] == "approved" and not i["payment_id"]]
        expect("what a payment run would pay", due["count"] >= 1 and due["count"] <= len(approved) and due["amount"] > 0
               and due["rows"][0]["supplier_name"], json.dumps(due)[:300])
        post("/payment-runs/propose", nadia, {"due_by": "2026-12-31"}, status=403)
        run = post("/payment-runs/propose", clerk, {"due_by": "2026-12-31", "run_date": "2026-10-01"})
        paid_for = client.get(f"/api/invoices/{due['rows'][0]['invoice_id']}", headers=clerk).json()
        expect("a proposed run holds a payment per supplier and schedules its invoices",
               run["status"] == "proposed" and run["invoices"] == due["count"] and abs(run["total_amount"] - due["amount"]) < 0.01
               and len(run["payments"]) <= run["invoices"] and paid_for["status"] == "scheduled"
               and paid_for["payment_id"] in [p["payment_id"] for p in run["payments"]], json.dumps(run, default=str)[:400])
        r = client.post("/api/finance/payment-runs/propose", headers=clerk, json={"due_by": "2026-12-31"})
        expect("with nothing left to pay, a second run is refused (409, FIN-03)", r.status_code == 409
               and r.json().get("rule") == "FIN-03", r.text[:300])

        pos = get("/budget/position?cost_center_id=7&requested=5000", nadia)
        expect("what is left of a cost centre's budget, and what a request would leave",
               pos["has_budget"] is True and pos["status"] in ("ok", "warning", "exceeded") and "£" in pos["message"]
               and abs(pos["remaining"] - (pos["budget"] - pos["actual"] - pos["committed"] - 5000)) < 0.01, json.dumps(pos))
        expect("without a cost centre the question is answered, not refused", get("/budget/position")["has_budget"] is False)
        second = next(n + 1 for n, q in enumerate(data["requisition"]) if q["title"].endswith("second batch"))
        advice = get(f"/requisitions/{second}/advice", nadia)
        rules_ = {f["rule"]: f for f in advice["findings"]}
        expect("a requester is told who approves, and that this looks like a split",
               advice["approver"] == "budget_holder" and "PROC-11" in rules_ and "PROC-02" in rules_
               and advice["level"] in ("warn", "down"), json.dumps(advice["findings"]))

        # ---- a purchase from the request to the supplier
        tom, daniel = as_("tom"), as_("daniel")
        good = next(n + 1 for n, s in enumerate(data["supplier"]) if s["status"] in ("active", "approved"))
        barred = next(n + 1 for n, s in enumerate(data["supplier"]) if s["status"] == "suspended")
        asked = post("/requisitions", nadia, {"title": "Label printers for goods in", "amount": 1800, "cost_center_id": 7,
                                              "spend_category_id": 1, "supplier_id": good, "needed_by": "2026-10-20"}, status=201)
        expect("a requester raises a requisition: a draft with its reference and their name",
               asked["status"] == "draft" and asked["reference"].startswith("PR-") and asked["requester_name"] == "Nadia Rahman"
               and asked["needed_by"] == "2026-10-20" and asked["supplier_name"], json.dumps(asked, default=str)[:400])
        post("/requisitions", clerk, {"title": "Not mine to ask", "amount": 10}, status=403)
        r = client.post("/api/finance/requisitions", headers=nadia, json={"title": "Nothing", "amount": 0})
        expect("a requisition for nothing is refused with its rule", r.status_code == 409 and r.json().get("rule") == "PROC-02",
               r.text[:300])
        r = client.post(f"/api/finance/requisitions/{asked['id']}/order", headers=daniel, json={})
        expect("no order before the requisition is approved (409, PROC-02)", r.status_code == 409
               and r.json().get("rule") == "PROC-02" and "draft" in r.text, r.text[:300])
        sent = client.post(f"/api/platform/workflows/requisition/{asked['id']}/submit", headers=nadia, json={})
        assert sent.status_code == 200, sent.text
        theirs = get("/approvals", tom)
        hers = get("/approvals", nadia)
        every = get("/approvals?mine=false&entity=requisition", nadia)
        item = next((x for x in theirs["rows"] if x["entity"] == "requisition" and x["id"] == asked["id"]), None)
        expect("what waits for the budget holder: the request, who asked, and that they may decide it",
               item is not None and item["can_decide"] and item["requested_by"] == "Nadia Rahman" and item["approval_id"]
               and item["approver"] == "Budget holder" and item["reference"] == asked["reference"] and theirs["amount"] > 0,
               json.dumps(theirs, default=str)[:500])
        expect("nothing waits for the requester, who sees her own request when she asks for every one",
               not any(x["id"] == asked["id"] and x["entity"] == "requisition" for x in hers["rows"])
               and any(x["id"] == asked["id"] and not x["can_decide"] for x in every["rows"]), json.dumps(hers, default=str)[:300])
        ok_ = client.post(f"/api/platform/approvals/{item['approval_id']}/approve", headers=tom, json={"note": "Needed for peak"})
        assert ok_.status_code == 200, ok_.text
        post(f"/requisitions/{asked['id']}/order", nadia, {}, status=403)
        r = client.post(f"/api/finance/requisitions/{asked['id']}/order", headers=daniel, json={"supplier_id": barred})
        expect("no order to a suspended supplier (409, PROC-09)", r.status_code == 409 and r.json().get("rule") == "PROC-09",
               r.text[:300])
        order = post(f"/requisitions/{asked['id']}/order", daniel, {})
        po_ = client.get(f"/api/purchase_orders/{order['purchase_order_id']}", headers=daniel)
        po_ = po_.json() if po_.status_code == 200 else client.get(
            f"/api/purchase-orders/{order['purchase_order_id']}", headers=daniel).json()
        expect("the buyer raises the order of an approved requisition: approved as the requisition was, and the requisition ordered",
               order["status"] == "approved" and order["requisition_status"] == "ordered" and order["reference"].startswith("PO-")
               and po_["requisition_id"] == asked["id"] and po_["supplier_id"] == good and abs(po_["amount"] - 1800) < 0.01
               and po_["buyer_name"] == "Daniel Moreau", json.dumps(order, default=str))
        r = client.post(f"/api/finance/requisitions/{asked['id']}/order", headers=daniel, json={})
        expect("a requisition is ordered once", r.status_code == 409, r.text[:200])
        gone = post(f"/purchase-orders/{order['purchase_order_id']}/send", daniel)
        expect("the order is sent, and created in the ERP's sandbox", gone["status"] == "sent" and gone["erp"]
               and gone["erp"]["ok"] and gone["erp"]["mode"] == "sandbox" and gone["erp"]["key"], json.dumps(gone, default=str))
        r = client.post(f"/api/finance/purchase-orders/{order['purchase_order_id']}/send", headers=daniel)
        expect("an order is sent once", r.status_code == 409, r.text[:200])
        trail = client.get(f"/api/platform/audit?entity=purchase_order&entity_id={order['purchase_order_id']}", headers=daniel).json()
        expect("the order's trail says it was approved as a requisition, and that the ERP has it",
               any(asked["reference"] in (e.get("summary") or "") + json.dumps(e.get("changes") or {}) for e in trail)
               and any(e["action"] == "connector" for e in trail), json.dumps(trail, default=str)[:500])

        # ---- what a work screen asks: how many in each state, and which are mine
        wl = get("/worklist?entity=requisition", daniel)
        by_state = {x["key"]: x for x in wl["statuses"]}
        mine_ = get("/worklist?entity=requisition&mine=true", nadia)
        hers_ = get("/documents?entity=requisition&mine=true&dated=false", nadia)
        expect("how many requisitions are in each state, in the order of the lifecycle, whatever the period",
               wl["count"] == len(data["requisition"]) + 1 and sum(x["count"] for x in wl["statuses"]) == wl["count"]
               and by_state["ordered"]["label"] == "Ordered" and by_state["ordered"]["amount"] > 0
               and [x["key"] for x in wl["statuses"]] == [k for k in ("draft", "submitted", "approved", "rejected", "ordered", "cancelled")
                                                         if k in by_state], json.dumps(wl)[:400])
        expect("my own records: the ones I raised", 0 < mine_["count"] < wl["count"] and hers_["count"] == mine_["count"]
               and all(r["requester_name"] == "Nadia Rahman" for r in hers_["rows"]), f"{mine_['count']} {hers_['count']}")
        expect("an entity with no owner is counted whole, and one the library does not have is refused",
               get("/worklist?entity=invoice&mine=true", clerk)["count"] == len(data["invoice"])
               and client.get("/api/finance/worklist?entity=widget", headers=clerk).status_code == 404)

        as_clerk = get("/kpis", clerk)
        expect("everyone who may read sees the same figures", len(as_clerk["kpis"]) == 31)

        # ---- the same figures as functions, for a router
        from app.db import _sessionmaker  # noqa: E402
        from app.finance import insight, operations as ops_  # noqa: E402
        from app.kernel.context import Actor, acting_as  # noqa: E402
        with _sessionmaker()() as db, acting_as(Actor(None, "system", "System", ("admin",), kind="system")):
            mine = insight.budget(db, by="cost_center", period="fy_to_date")
            few_ = insight.kpis(db, keys=["spend", "overdue"], period="last_quarter", compare="none")
            docs = insight.documents(db, entity="invoice", overdue=True, dated=False, sort="-amount", limit=5)
            expect("a router asks for the figures by the same names",
                   abs(mine["totals"]["actual"] - spend) < 0.01 and [x["key"] for x in few_["kpis"]] == ["spend", "overdue"]
                   and few_["scope"]["from"] == "2026-04-01" and len(docs["rows"]) == 5 and docs["rows"][0]["days_overdue"] > 0,
                   json.dumps(few_["scope"]))
            try:
                ops_.budget_position(cost_center_id=7, requested=100)
                said = ""
            except TypeError as exc:
                said = str(exc)
            expect("an operation called without its session says so", "session" in said or "db" in said, said)

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    for f_ in FAILED:
        print("  FAILED:", f_)
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
