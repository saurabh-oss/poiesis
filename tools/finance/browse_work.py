"""The work screens in a real browser: a purchase from the request to the payment run, each step by
the person whose job it is.

Runs in a Playwright image on the application's network, after browse.py or on its own
(tools/finance/README.md):
    python browse_work.py http://frontend /out [light|dark]
It changes the application's records: run it against a fresh deployment.
"""
import json
import urllib.request

from browse import BASE, Session, expect, passed, problems, token_for
from playwright.sync_api import sync_playwright

DESKS = {"work_requisitions": 5, "work_approvals": 2, "work_ordering": 5, "work_receiving": 4, "work_invoices": 6,
         "work_paymentruns": 4, "work_suppliers": 4, "work_contracts": 4, "example_worklist": 4}
TITLE = "Label printers for goods in"


def ask(user: str, path: str) -> dict:
    req = urllib.request.Request(BASE + "/api" + path, headers={"Authorization": "Bearer " + token_for(user)})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def desk(s: Session) -> dict:
    return s.page.evaluate("""() => ({
        tabs: Object.fromEntries([...document.querySelectorAll('.fin-view')].map((t) => [t.dataset.view, t.querySelector('.fin-view-count').innerText.trim()])),
        on: (document.querySelector('.fin-view.on') || { dataset: {} }).dataset.view,
        rows: document.querySelectorAll('.fin-work-body table tbody tr').length,
        empty: !!document.querySelector('.fin-work-body .empty-state:not([hidden]), .fin-work-body .fin-empty'),
        failed: [...document.querySelectorAll('.fin-work .notice-down, .fin-work .notice-warn')].map((n) => n.innerText),
        wide: document.documentElement.scrollWidth > window.innerWidth + 2,
        spill: [...document.querySelectorAll('.fin-views, .fin-work-bar')].some((e) => e.scrollWidth > e.clientWidth + 2) })""")


def count(s: Session, view: str) -> int:
    return int(desk(s)["tabs"][view].replace(",", ""))


def desk_ok(s: Session, views: int) -> None:
    d = desk(s)
    numbers = all(v.replace(",", "").isdigit() for v in d["tabs"].values())
    expect(f"{s.where}: {len(d['tabs'])} tabs, each with its count, and rows or a reason there are none",
           len(d["tabs"]) == views and numbers and (d["rows"] > 0 or d["empty"]) and not d["failed"] and not d["wide"] and not d["spill"],
           json.dumps(d))


def tab(s: Session, view: str) -> None:
    s.page.locator(f".fin-view[data-view='{view}']").click()
    s.page.wait_for_function(f"() => (document.querySelector('.fin-view.on') || {{ dataset: {{}} }}).dataset.view === '{view}'", timeout=15000)
    s.settle()


def toast(s: Session) -> str:
    s.page.wait_for_selector(".toast", timeout=15000)
    return s.page.locator(".toast").last.inner_text()


def row_of(s: Session, text: str):
    return s.page.locator(".fin-work-body table tbody tr", has_text=text).first


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()

        # ---- every worklist opens, for someone who may see them all
        admin = Session(browser, "alex")
        for name, views in DESKS.items():
            admin.open(name)
            desk_ok(admin, views)
            admin.text_ok()
            admin.shot(name)
        for width, label in ((430, "narrow"), (1024, "medium")):
            small = Session(browser, "alex", width, 900)
            for name, views in DESKS.items():
                small.open(name)
                small.where = f"{name} at {width}px"
                desk_ok(small, views)
                small.shot(f"{name}-{label}")

        # ---- a requester raises a request and submits it
        nadia = Session(browser, "nadia")
        nadia.open("work_requisitions")
        desk_ok(nadia, 5)
        drafts, waiting = count(nadia, "draft"), count(nadia, "waiting")
        everyone = ask("nadia", "/finance/worklist?entity=requisition")["count"]
        mine = sum(count(nadia, k) for k in DESKS and ("draft", "waiting", "approved", "ordered", "cancelled"))
        expect("a requester starts with her own requests", 0 < mine < everyone
               and nadia.page.locator(".fin-work-bar .segmented button.on").inner_text().strip() == "My requests", f"{mine} of {everyone}")
        nadia.page.locator(".fin-work-bar button", has_text="New requisition").click()
        nadia.page.wait_for_selector(".modal form")
        nadia.page.locator(".modal [name=title]").fill(TITLE)
        nadia.page.locator(".modal [name=amount]").fill("1800")
        nadia.page.locator(".modal [name=cost_center_id]").select_option(index=7)
        nadia.page.wait_for_selector(".modal .fin-live .fin-finding", timeout=15000)
        live = nadia.page.locator(".modal .fin-live").inner_text()
        expect("while she fills it in she is told who approves it and what it leaves of the budget",
               "Budget holder" in live and "FIN-02" in live and "£" in live, live[:400])
        nadia.text_ok(".modal")
        nadia.shot("new-requisition")
        nadia.page.locator(".modal [name=amount]").fill("0")
        nadia.allowed = {"/finance/requisitions"}
        nadia.page.locator(".modal button[type=submit]").click()
        nadia.page.wait_for_selector(".modal .error-text:not(:empty)", timeout=15000)
        refused = nadia.page.locator(".modal .error-text").inner_text()
        expect("a request for nothing is refused in the form, with its rule", refused.startswith("PROC-02"), refused)
        nadia.allowed = set()
        nadia.page.locator(".modal [name=amount]").fill("1800")
        nadia.page.locator(".modal button[type=submit]").click()
        said = toast(nadia)
        nadia.page.wait_for_selector(".drawer .wf-panel button", timeout=15000)
        nadia.settle()
        drawer = nadia.page.locator(".drawer").inner_text()
        expect("the draft is saved with its reference, and opens with what the rules say and what she may do next",
               "PR-" in said and "saved as a draft" in said and TITLE in drawer + nadia.page.locator(".drawer-head").inner_text()
               and nadia.page.locator(".drawer .fin-finding").count() >= 1
               and nadia.page.locator(".drawer button", has_text="Submit").count() >= 1, said + " | " + drawer[:300])
        nadia.text_ok(".drawer")
        nadia.shot("draft-requisition")
        nadia.close_overlay()
        nadia.settle()
        expect("the draft is counted", count(nadia, "draft") == drafts + 1 and row_of(nadia, TITLE).count() == 1, json.dumps(desk(nadia)))
        row_of(nadia, TITLE).locator("button[data-action=submit]").click()
        nadia.page.wait_for_selector(".modal .fin-finding", timeout=15000)
        nadia.page.locator(".modal textarea[name=reason]").fill("The old printers fail at peak")
        nadia.shot("submit-requisition")
        nadia.page.locator(".modal button[type=submit]").click()
        said = toast(nadia)
        nadia.settle()
        expect("submitting it sends it to its approver, and it moves to the next tab",
               "Budget holder" in said and count(nadia, "draft") == drafts and count(nadia, "waiting") == waiting + 1, said)
        nadia.page.reload()
        nadia.page.wait_for_selector(".sidebar")
        nadia.settle()
        tab(nadia, "waiting")
        nadia.page.reload()
        nadia.page.wait_for_selector(".sidebar")
        nadia.settle()
        expect("the tab she was on is remembered", desk(nadia)["on"] == "waiting" and row_of(nadia, TITLE).count() == 1)
        nadia.page.locator(".fin-work-bar .segmented button", has_text="Everyone").click()
        nadia.settle()
        expect("everyone's requests are one choice away", sum(int(v.replace(",", "")) for v in desk(nadia)["tabs"].values()) == everyone + 1,
               json.dumps(desk(nadia)["tabs"]))
        nadia.page.locator(".fin-work-bar .segmented button", has_text="My requests").click()
        nadia.settle()

        # ---- the budget holder decides
        tom = Session(browser, "tom")
        tom.open("work_approvals")
        desk_ok(tom, 2)
        mine, every = count(tom, "mine"), count(tom, "all")
        expect("an approver sees what waits for him, and how much waits for anyone", 1 <= mine <= every, f"{mine} {every}")
        row_of(tom, TITLE).click()
        tom.page.wait_for_selector(".drawer .drawer-foot button", timeout=15000)
        tom.settle()
        text = tom.page.locator(".drawer").inner_text()
        expect("a request opens with who asked, why, its approver, its budget and the rules",
               "Nadia Rahman" in text and "The old printers fail at peak" in text and "FIN-02" in text
               and tom.page.locator(".drawer .fin-chain").count() == 1
               and [b.strip() for b in tom.page.locator(".drawer .drawer-foot button").all_inner_texts()] == ["Approve", "Reject"], text[:500])
        tom.text_ok(".drawer")
        tom.shot("approval")
        tom.page.locator(".drawer .drawer-foot button", has_text="Approve").click()
        tom.page.wait_for_selector(".modal textarea[name=note]")
        tom.page.locator(".modal textarea[name=note]").fill("Needed for peak")
        tom.page.locator(".modal button[type=submit]").click()
        said = toast(tom)
        tom.page.wait_for_function("() => !document.querySelector('.drawer, .modal')", timeout=15000)
        tom.settle()
        expect("approving it takes it off his list", "approved" in said and count(tom, "mine") == mine - 1 and row_of(tom, TITLE).count() == 0, said)
        other = tom.page.locator(".fin-work-body table tbody tr").first
        title = other.locator("td").nth(1).inner_text()
        other.locator("button[data-action=reject]").click()
        tom.page.wait_for_selector(".modal textarea[name=note]")
        tom.page.locator(".modal button[type=submit]").click()
        tom.page.wait_for_selector(".modal .field-error", timeout=5000)
        tom.page.locator(".modal textarea[name=note]").fill("Not in this year's plan")
        tom.page.locator(".modal button[type=submit]").click()
        said = toast(tom)
        tom.settle()
        expect("rejecting one needs a reason, and takes it off his list too", "rejected" in said and count(tom, "mine") == mine - 2, f"{said} ({title})")
        expect("a requester has nothing to decide", ask("nadia", "/finance/approvals")["count"] == 0)

        # ---- the buyer raises the order and sends it
        suspended = ask("daniel", "/finance/documents?entity=supplier&status=suspended&dated=false")["rows"][0]
        good = ask("daniel", "/finance/documents?entity=supplier&status=active&dated=false")["rows"][0]
        daniel = Session(browser, "daniel")
        daniel.open("work_ordering")
        desk_ok(daniel, 5)
        to_order, to_send = count(daniel, "to_order"), count(daniel, "to_send")
        row_of(daniel, TITLE).locator("button[data-action=order]").click()
        daniel.page.wait_for_selector(".modal [name=supplier_id]")
        daniel.page.locator(".modal [name=supplier_id]").select_option(str(suspended["id"]))
        daniel.allowed = {"/order"}
        daniel.page.locator(".modal button[type=submit]").click()
        daniel.page.wait_for_selector(".modal .error-text:not(:empty)", timeout=15000)
        refused = daniel.page.locator(".modal .error-text").inner_text()
        expect("an order to a suspended supplier is refused in the form, with its rule", refused.startswith("PROC-09") and suspended["name"] in refused, refused)
        daniel.allowed = set()
        daniel.page.locator(".modal [name=supplier_id]").select_option(str(good["id"]))
        daniel.shot("raise-order")
        daniel.page.locator(".modal button[type=submit]").click()
        said = toast(daniel)
        daniel.settle()
        reference = said.split(" ")[0]
        expect("the order is raised with an approved supplier, and the request leaves the list",
               reference.startswith("PO-") and good["name"] in said and count(daniel, "to_order") == to_order - 1
               and count(daniel, "to_send") == to_send + 1, said)
        tab(daniel, "to_send")
        row_of(daniel, reference).locator("button[data-action=send]").click()
        daniel.page.wait_for_selector(".modal")
        daniel.page.locator(".modal button", has_text="Send").last.click()
        said = toast(daniel)
        daniel.settle()
        expect("sending it puts it in the ERP", reference in said and "ERP" in said and count(daniel, "to_send") == to_send, said)
        tab(daniel, "with_suppliers")
        daniel.page.locator(".fin-work-body input[type=search], .fin-work-body .search input").first.fill(reference)
        daniel.page.wait_for_timeout(600)
        row_of(daniel, reference).click()
        daniel.page.wait_for_selector(".drawer .wf-panel", timeout=15000)
        daniel.settle()
        trail = daniel.page.locator(".drawer").inner_text()
        expect("the order's history says it was approved as a requisition and that the ERP has it",
               "Approved as requisition PR-" in trail and "created in the ERP" in trail, trail[-700:])
        daniel.text_ok(".drawer")
        daniel.shot("order-sent")
        daniel.close_overlay()

        # ---- goods in
        nadia.open("work_receiving")
        desk_ok(nadia, 4)
        due = count(nadia, "due")
        late = count(nadia, "late")
        expect("what is late is counted apart", 0 <= late <= due, f"{late} {due}")
        nadia.page.locator(".fin-work-body input[type=search], .fin-work-body .search input").first.fill(reference)
        nadia.page.wait_for_timeout(600)
        row_of(nadia, reference).locator("button[data-action=receive]").click()
        nadia.page.wait_for_selector(".modal [name=amount]")
        offered = nadia.page.locator(".modal [name=amount]").input_value()
        by = nadia.page.locator(".modal [name=received_by]").input_value()
        nadia.shot("receive")
        nadia.page.locator(".modal button[type=submit]").click()
        said = toast(nadia)
        nadia.settle()
        expect("receiving offers what is still to come, in her name, and the order leaves the list",
               float(offered) == 1800 and by == "Nadia Rahman" and "received in full" in said and count(nadia, "due") == due - 1, f"{offered} {by} {said}")

        # ---- accounts payable
        kofi = Session(browser, "kofi")
        kofi.open("work_invoices")
        desk_ok(kofi, 6)
        to_match, held, to_approve = count(kofi, "to_match"), count(kofi, "held"), count(kofi, "to_approve")
        kofi.page.locator(".fin-work-body table tbody tr button[data-action=match]").first.click()
        kofi.page.wait_for_selector(".modal .fin-match", timeout=15000)
        kofi.text_ok(".modal")
        kofi.shot("match")
        agrees = kofi.page.locator(".modal .modal-foot button").last.inner_text().strip() == "Match"
        kofi.page.locator(".modal .modal-foot button").last.click()
        said = toast(kofi)
        kofi.settle()
        expect("matching an invoice moves it on, or holds it with the reason",
               count(kofi, "to_match") == to_match - 1 and ((agrees and "matched" in said and count(kofi, "to_approve") == to_approve + 1)
                                                            or (not agrees and "held" in said and count(kofi, "held") == held + 1)), said)
        tab(kofi, "held")
        kofi.page.locator(".fin-work-body table tbody tr").first.click()
        kofi.page.wait_for_selector(".drawer .fin-match", timeout=15000)
        kofi.settle()
        expect("a held invoice opens with its match and what can be done",
               kofi.page.locator(".drawer button", has_text="Resolve").count() >= 1)
        kofi.text_ok(".drawer")
        kofi.close_overlay()
        tab(kofi, "overdue")
        expect("overdue invoices are a tab of their own, counted", count(kofi, "overdue") == desk(kofi)["rows"] or desk(kofi)["rows"] == 12, json.dumps(desk(kofi)))

        kofi.open("work_paymentruns")
        desk_ok(kofi, 4)
        payable, proposed = count(kofi, "payable"), count(kofi, "proposed")
        kofi.page.locator(".fin-work-bar button", has_text="Propose a payment run").click()
        kofi.page.wait_for_selector(".modal [name=due_by]")
        kofi.page.locator(".modal [name=due_by]").fill("2026-12-31")
        kofi.shot("propose-run")
        kofi.page.locator(".modal button[type=submit]").click()
        said = toast(kofi)
        kofi.settle()
        expect("a payment run is proposed from what is due", "proposed" in said and "£" in said and count(kofi, "proposed") == proposed + 1
               and count(kofi, "payable") < max(payable, 1), f"{said} {payable}")
        kofi.text_ok()
        mei = Session(browser, "mei")
        mei.open("work_paymentruns")
        desk_ok(mei, 4)
        expect("someone who may not propose a run is not offered it", mei.page.locator(".fin-work-bar button", has_text="Propose").count() == 0)
        nadia.open("work_ordering")
        expect("someone who may not order is not offered it", nadia.page.locator("button[data-action=order], button[data-action=send]").count() == 0
               and desk(nadia)["rows"] > 0)

        # ---- suppliers and contracts
        ingrid = Session(browser, "ingrid")
        ingrid.open("work_suppliers")
        desk_ok(ingrid, 4)
        tab(ingrid, "active")
        ingrid.page.locator(".fin-work-body table tbody tr button[data-action=scorecard]").first.click()
        ingrid.page.wait_for_selector(".drawer .fin-gauge", timeout=15000)
        ingrid.settle()
        expect("a supplier's scorecard is one press away", ingrid.page.locator(".drawer .fin-figure").count() == 10)
        ingrid.text_ok(".drawer")
        ingrid.close_overlay()
        ingrid.open("work_contracts")
        desk_ok(ingrid, 4)
        expect("the contracts to decide on come first", desk(ingrid)["on"] == "decide" and desk(ingrid)["rows"] > 0)
        ingrid.page.locator(".fin-work-body table tbody tr").first.click()
        ingrid.page.wait_for_selector(".drawer .kv", timeout=15000)
        ingrid.settle()
        ingrid.text_ok(".drawer")
        ingrid.shot("contract")
        browser.close()

    print(f"\n{len(passed)} passed, {len(problems)} problems")
    for line in problems:
        print("  PROBLEM:", line)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
