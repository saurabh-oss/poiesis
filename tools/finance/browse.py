"""The dashboard kit in a real browser: every blueprint, every component, as the people of the function.

Runs in a Playwright image on the application's network (tools/finance/README.md):
    python browse.py http://frontend /out [light|dark]
Records console errors, page errors, failed API calls, text that should never be shown ("null",
"NaN", "undefined", "[object"), widgets left loading or failed, and a screenshot of each page.
"""
import json
import os
import re
import sys
import urllib.request

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://frontend"
OUT = sys.argv[2] if len(sys.argv) > 2 else "/out"
THEME = sys.argv[3] if len(sys.argv) > 3 else "light"
os.makedirs(OUT, exist_ok=True)
problems: list[str] = []
passed: list[str] = []
BAD_TEXT = re.compile(r"\b(null|undefined|NaN)\b|\[object |Infinity|£-|--£")
BOARDS = ["executive", "spend", "budget", "payables", "procuretopay", "suppliers", "controls", "savings", "example_finance"]


def expect(what: str, ok: bool, detail: str = "") -> None:
    (passed if ok else problems).append(what if ok else f"{what}: {detail}"[:600])
    print(("  ok   " if ok else "  FAIL ") + what + ("" if ok else f"\n         {detail[:500]}"), flush=True)


def token_for(user: str) -> str:
    req = urllib.request.Request(BASE + "/api/auth/sign-in", method="POST", data=json.dumps({"username": user}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())["token"]


class Session:
    def __init__(self, browser, user: str, width: int = 1440, height: int = 1000):
        self.user = user
        self.ctx = browser.new_context(viewport={"width": width, "height": height}, accept_downloads=True)
        self.page = self.ctx.new_page()
        self.allowed: set[str] = set()
        self.page.on("console", lambda m: m.type == "error" and self.err(f"console: {m.text[:300]}"))
        self.page.on("pageerror", lambda e: self.err(f"page error: {str(e)[:300]}"))
        self.page.on("response", lambda r: "/api/" in r.url and r.status >= 400 and not any(a in r.url for a in self.allowed)
                     and self.err(f"{r.status} {r.request.method} {r.url.split('/api', 1)[1][:200]}"))
        self.ctx.add_init_script(f"try {{ localStorage.setItem('poiesis-token', {json.dumps(token_for(user))}); "
                                 f"localStorage.setItem('theme', '{THEME}'); }} catch (e) {{}}")
        self.where = ""

    def err(self, text: str) -> None:
        if "Failed to load resource" in text:
            return                              # the response listener names the URL; this only repeats it
        problems.append(f"[{self.user} {self.where}] {text}")
        print(f"  FAIL [{self.user} {self.where}] {text}", flush=True)

    def open(self, screen: str) -> None:
        self.where = screen
        self.page.goto("about:blank")          # one whole load of the screen: nothing in flight is cut short
        self.page.goto(f"{BASE}/#/{screen}")
        self.page.wait_for_selector(".sidebar", timeout=20000)
        self.settle()

    def settle(self, timeout: int = 20000) -> None:
        """Until no widget is still loading and the animations have run."""
        self.page.wait_for_function(
            "() => !document.querySelector('#view .skeleton, .fin-widget .skeleton, .drawer .skeleton') "
            "&& (document.querySelector('.fin-widget, .panel, .empty-state') !== null)", timeout=timeout)
        self.page.wait_for_timeout(2300)

    def shot(self, name: str) -> None:
        self.page.screenshot(path=f"{OUT}/{THEME}-{name}.png", full_page=True)

    def text_ok(self, scope: str = "main, .content") -> None:
        text = self.page.locator(scope).first.inner_text()
        bad = sorted({m.group(0) for m in BAD_TEXT.finditer(text)})
        where = ""
        if bad:
            i = BAD_TEXT.search(text).start()
            where = text[max(0, i - 80): i + 40].replace("\n", " | ")
        expect(f"{self.where}: nothing reads null, NaN or undefined", not bad, f"{bad} near: {where}")

    def widgets_ok(self, least: int) -> None:
        state = self.page.evaluate("""() => [...document.querySelectorAll('.fin-widget')].map((w) => ({
            id: w.dataset.widget, failed: !!w.querySelector('.notice-down, .notice-warn'),
            empty: !!w.querySelector('.fin-empty, .empty-state:not([hidden])') && !w.querySelector('svg.donut, .fin-chart, table tbody tr, .fin-kpi, .fin-budget-row, .fin-control, .fin-renewal, .fin-funnel-row, .fin-cycle-row, .fin-stack'),
            height: Math.round(w.getBoundingClientRect().height), overflow: w.scrollWidth > w.clientWidth + 2 }))""")
        failed = [w["id"] for w in state if w["failed"]]
        empty = [w["id"] for w in state if w["empty"]]
        flat = [w["id"] for w in state if w["height"] < 60]
        wide = [w["id"] for w in state if w["overflow"]]
        expect(f"{self.where}: {len(state)} widgets drawn, none failed, empty or spilling",
               len(state) >= least and not failed and not empty and not flat and not wide,
               f"count {len(state)} failed {failed} empty {empty} flat {flat} overflowing {wide}")
        page_wide = self.page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth + 2")
        expect(f"{self.where}: the page does not scroll sideways", not page_wide)

    def close_overlay(self) -> None:
        for _ in range(3):
            if self.page.locator(".drawer, .modal").count() == 0:
                return
            self.page.keyboard.press("Escape")
            self.page.wait_for_timeout(400)


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        cfo = Session(browser, "sofia")

        # ---- every blueprint opens full
        for board in BOARDS:
            cfo.open(board)
            cfo.widgets_ok(4)
            cfo.text_ok()
            cfo.shot(board)

        # ---- the gallery: every component from fixed data
        cfo.open("gallery")
        cfo.text_ok()
        cfo.shot("gallery")
        texts = cfo.page.locator("#text code").all_inner_texts()
        expect("amounts, shares and days are written for people", texts == [
            "£1,234,567.50", "£1.23M", "(£420.00)", "€48.3k", "—", "—", "—", "12.3%", "-2.1%", "—", "1 day", "10.6 days", "—",
            "+3.2 pts", "25 Sep 2026", "—", "Price variance"], str(texts))
        classes = cfo.page.evaluate("() => [...document.querySelectorAll('.panel:nth-of-type(2) .fin-delta')].map((e) => e.className.replace('fin-delta ', '') + ':' + e.innerText.replace(/\\s+/g, ' ').trim())")
        expect("up on a cost is adverse, down is favourable, no move is neither",
               classes[:4] == ["fin-bad:+4.2%", "fin-good:+4.2%", "fin-good:-3.0% vs last year", "fin-flat:0.0%"]
               and classes[4].startswith("fin-flat") and "fin-bad:£4k (4.0%) over" in classes and "fin-good:£6k (6.0%) under" in classes,
               str(classes))
        cfo.page.locator(".fin-kpi.interactive").first.click()
        expect("a figure with rows behind it can be opened", '"key":"spend"' in cfo.page.locator("#chosen").inner_text())
        cfo.page.locator(".fin-budget-row.clickable").first.click()
        expect("a budget bar can be opened", "Software Engineering" in cfo.page.locator("#chosen").inner_text())
        cfo.page.locator(".fin-pivot td.clickable").first.click()
        expect("a cell of the cross-tab can be opened", '"column":"Apr 2026"' in cfo.page.locator("#chosen").inner_text())
        cfo.page.locator(".fin-period select").first.select_option("custom")
        cfo.page.wait_for_timeout(200)
        expect("a range of one's own shows two dates, filled in",
               cfo.page.locator(".fin-range input").first.input_value() == "2026-04-01"
               and '"period":"custom"' in cfo.page.locator("#chosen").inner_text(), cfo.page.locator("#chosen").inner_text())
        tip = cfo.page.locator(".fin-chart").first
        tip.locator(".fin-hit").nth(3).hover()
        cfo.page.wait_for_timeout(300)
        shown = tip.locator(".fin-tip.on").inner_text()
        expect("hovering a month shows actual, budget, last year and the variance",
               "Jul 2026" in shown and "£502,000.00" in shown and "Budget" in shown and "Variance" in shown, shown)
        with cfo.page.expect_download() as got:
            cfo.page.locator(".fin-pivot-wrap").locator("xpath=..").locator("button", has_text="Export").click()
        body = open(got.value.path(), encoding="utf-8-sig").read().splitlines()
        expect("the cross-tab exports with its totals", body[0].startswith("Cost center,Apr 2026") and body[-1].startswith("Total,100000")
               and len(body) == 4, str(body))

        # ---- a dashboard in use
        cfo.open("spend")
        first = cfo.page.locator(".fin-kpi-value").first.inner_text()
        cfo.page.locator(".fin-period select").first.select_option("last_quarter")
        cfo.settle()
        second = cfo.page.locator(".fin-kpi-value").first.inner_text()
        expect("choosing another period changes the figures", first != second and second.startswith("£"), f"{first} -> {second}")
        cfo.page.locator(".fin-filters select").nth(1).select_option("IT")
        cfo.settle()
        third = cfo.page.locator(".fin-kpi-value").first.inner_text()
        expect("a filter narrows them, and can be cleared", third != second and cfo.page.locator(".fin-filters button", has_text="Clear").count() == 1,
               f"{second} -> {third}")
        cfo.text_ok()
        cfo.shot("spend-filtered")
        cfo.page.reload()
        cfo.page.wait_for_selector(".sidebar")
        cfo.settle()
        expect("the period and the filter are remembered", cfo.page.locator(".fin-period select").first.input_value() == "last_quarter"
               and cfo.page.locator(".fin-filters select").nth(1).input_value() == "IT"
               and cfo.page.locator(".fin-kpi-value").first.inner_text() == third)
        cfo.page.locator(".fin-filters button", has_text="Clear").click()
        cfo.page.locator(".fin-period select").first.select_option("fy_to_date")
        cfo.settle()

        cfo.page.locator(".fin-kpi.interactive").first.click()
        cfo.page.wait_for_selector(".drawer table tbody tr", timeout=15000)
        cfo.settle()
        head = cfo.page.locator(".drawer .fin-drill-head").inner_text()
        expect("a figure opens the rows behind it, with their total", "rows" in head and "£" in head
               and cfo.page.locator(".drawer table tbody tr").count() == 10, head)
        cfo.text_ok(".drawer")
        cfo.shot("drill")
        cfo.page.locator(".drawer table tbody tr").first.click()
        cfo.page.wait_for_timeout(1500)
        cfo.settle()
        expect("a row opens the record: its lifecycle, its match and its history",
               cfo.page.locator(".drawer .kv").count() >= 1 and cfo.page.locator(".drawer .fin-match, .drawer .fin-life, .drawer .wf-panel, .drawer [class*=wf]").count() >= 1, "")
        cfo.text_ok(".drawer >> nth=-1")
        cfo.shot("record")
        cfo.close_overlay()

        cfo.page.locator("[data-widget^='breakdown-spend-supplier'] rect.chart-col").first.click()
        cfo.page.wait_for_selector(".drawer .fin-gauge", timeout=15000)
        cfo.settle()
        expect("a supplier's bar opens its scorecard", cfo.page.locator(".drawer .fin-figure").count() == 10
               and cfo.page.locator(".drawer .fin-part").count() == 5)
        cfo.text_ok(".drawer")
        cfo.shot("scorecard")
        cfo.close_overlay()

        with cfo.page.expect_download() as got:
            w = cfo.page.locator("[data-widget^='trend-spend']")
            w.hover()
            w.locator(".icon-btn").click()
        lines = open(got.value.path(), encoding="utf-8-sig").read().splitlines()
        expect("a widget exports what it shows", lines[0] == "Period,From,To,Value,Budget,Last year,Documents" and len(lines) == 13, str(lines[:2]))

        cfo.page.locator("button", has_text="Customise").click()
        cfo.page.wait_for_selector(".modal .fin-custom-row")
        rows = cfo.page.locator(".modal .fin-custom-row")
        count = rows.count()
        rows.nth(1).locator("input").uncheck()
        rows.nth(3).locator(".icon-btn").first.click()
        cfo.shot("customise")
        cfo.page.locator(".modal button", has_text="Save").click()
        cfo.settle()
        ids = cfo.page.evaluate("() => [...document.querySelectorAll('.fin-widget')].map((w) => w.dataset.widget)")
        expect("a person hides and reorders widgets", len(ids) == count - 1 and not any(i.startswith("trend-spend") for i in ids)
               and ids[1].startswith("breakdown-spend-supplier"), str(ids))
        cfo.page.reload()
        cfo.page.wait_for_selector(".sidebar")
        cfo.settle()
        again = cfo.page.evaluate("() => [...document.querySelectorAll('.fin-widget')].map((w) => w.dataset.widget)")
        expect("and finds the arrangement again", again == ids, str(again))
        cfo.page.locator("button", has_text="Customise").click()
        cfo.page.locator(".modal button", has_text="Reset").click()
        cfo.settle()
        expect("or goes back to the standard one", cfo.page.locator(".fin-widget").count() == count)

        cfo.open("budget")
        cfo.page.locator("[data-widget^='budget-'] .segmented button", has_text="Full year").first.click()
        cfo.page.wait_for_timeout(1300)
        expect("the budget can be read for the full year, with what is committed",
               cfo.page.locator("[data-widget^='budget-'] .fin-committed").count() >= 5
               and "left" in cfo.page.locator("[data-widget^='budget-'] .fin-budget-row").first.inner_text())
        cfo.shot("budget-year")

        cfo.open("controls")
        cfo.page.locator(".fin-control.clickable").first.click()
        cfo.page.wait_for_selector(".drawer table tbody tr", timeout=15000)
        expect("a control lists what it found", cfo.page.locator(".drawer table tbody tr").count() >= 1)
        cfo.text_ok(".drawer")
        cfo.shot("control")
        cfo.close_overlay()

        # ---- the application's own guide
        nadia = Session(browser, "nadia")
        nadia.open("guide")
        nadia.page.wait_for_selector(".guide-flow .guide-step", timeout=20000)
        seen = nadia.page.evaluate("""() => ({
            steps: [...document.querySelectorAll('.guide-flow .guide-step')].map((g) => g.getAttribute('aria-label')),
            lanes: [...document.querySelectorAll('.guide-flow .guide-lane-label')].map((t) => t.textContent).join(' '),
            yours: document.querySelectorAll('.guide-flow .guide-lane.yours').length,
            absent: document.querySelectorAll('.guide-flow .guide-step.absent').length,
            cards: document.querySelectorAll('.guide-card').length, roles: document.querySelectorAll('.guide-role').length,
            mine: [...document.querySelectorAll('.guide-me-steps li')].map((l) => l.innerText.split(String.fromCharCode(10)).join(' ').trim()),
            myScreens: [...document.querySelectorAll('.guide-me .guide-chips button')].map((b) => b.innerText.trim()),
            screens: document.querySelectorAll('.guide-screen').length, tabs: document.querySelectorAll('.guide .tabs button').length,
            numbers: document.querySelectorAll('.guide-numbers dt').length, help: [...document.querySelectorAll('.sidebar .nav-label')].map((l) => l.innerText.trim()),
            spill: document.documentElement.scrollWidth > window.innerWidth + 2 })""")
        expect("the guide draws the process: a lane for each role, a box for each step, the person's own lane marked",
               len(seen["steps"]) == 7 and seen["steps"][0] == "Step 1: Raise a requisition" and "Requester" in seen["lanes"]
               and "Accounts payable" in seen["lanes"] and seen["yours"] == 1 and seen["absent"] == 0 and seen["cards"] == 7, json.dumps(seen))
        expect("it says what is this person's part, and where",
               any("Raise a requisition" in m for m in seen["mine"]) and any("Receive the goods" in m for m in seen["mine"])
               and "My requests" in seen["myScreens"] and "Goods in" in seen["myScreens"], json.dumps(seen))
        expect("it has every role, every screen, every lifecycle and the organisation's numbers, under Help",
               seen["roles"] >= 11 and seen["screens"] >= 16 and seen["tabs"] == 7 and seen["numbers"] >= 5
               and seen["help"][-1].upper() == "HELP" and not seen["spill"], json.dumps(seen))
        nadia.text_ok()
        nadia.shot("guide")
        nadia.page.locator(".guide-flow .guide-step").nth(3).click()
        nadia.page.wait_for_selector("#guide-step-receive.flash", timeout=5000)
        expect("a step of the diagram leads to how it is done", "Choose Receive" in nadia.page.locator("#guide-step-receive").inner_text())
        nadia.page.locator("#guide-step-receive footer button", has_text="Goods in").first.click()
        nadia.page.wait_for_function("() => location.hash === '#/work_receiving'", timeout=10000)
        nadia.settle()
        expect("and from there to the screen it is done on", nadia.page.locator(".fin-view").count() == 4)
        nadia.open("guide")
        nadia.page.wait_for_selector(".guide-flow .guide-step", timeout=20000)
        with nadia.page.expect_download() as got:
            nadia.page.locator("#page-actions button", has_text="Download").click()
        body = open(got.value.path(), encoding="utf-8").read()
        expect("the guide downloads as a document with its diagrams", got.value.suggested_filename == "USER-GUIDE.md"
               and body.startswith("# ") and "flowchart LR" in body and "stateDiagram-v2" in body and "the **Goods in** screen" in body, body[:300])
        cfo.open("guide")
        cfo.page.wait_for_selector(".guide-flow .guide-step", timeout=20000)
        expect("someone with no part in the process is told what their role reads",
               cfo.page.locator(".guide-flow .guide-lane.yours").count() == 0 and cfo.page.locator(".guide-role.yours").count() == 1)
        cfo.text_ok()
        small = Session(browser, "tom", 430, 900)
        small.open("guide")
        small.page.wait_for_selector(".guide-flow .guide-step", timeout=20000)
        small.where = "guide at 430px"
        expect("guide at 430px: the page does not scroll sideways; the diagram scrolls inside its frame",
               not small.page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth + 2")
               and small.page.evaluate("() => { const w = document.querySelector('.guide-flow-wrap'); return w.scrollWidth > w.clientWidth; }"))
        small.shot("guide-narrow")

        # ---- a narrow screen
        for width, name in ((430, "narrow"), (1024, "medium")):
            small = Session(browser, "sofia", width, 900)
            for board in ("executive", "budget", "payables", "procuretopay", "suppliers"):
                small.open(board)
                small.where = f"{board} at {width}px"
                small.widgets_ok(4)
                small.shot(f"{board}-{name}")

        # ---- someone who may read everything but decide little, and the record's actions
        clerk = Session(browser, "kofi")
        clerk.open("payables")
        clerk.widgets_ok(4)
        clerk.text_ok()
        clerk.page.locator("[data-widget^='exceptions'] table tbody tr").first.click()
        clerk.page.wait_for_selector(".drawer .fin-match", timeout=15000)
        clerk.settle()
        expect("accounts payable opens a held invoice and sees what can be done",
               clerk.page.locator(".drawer .fin-match").count() == 1 and clerk.page.locator(".drawer button", has_text="Resolve").count() >= 1,
               clerk.page.locator(".drawer").inner_text()[:400])
        clerk.text_ok(".drawer")
        clerk.shot("held-invoice")
        browser.close()

    print(f"\n{len(passed)} passed, {len(problems)} problems")
    for line in problems:
        print("  PROBLEM:", line)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
