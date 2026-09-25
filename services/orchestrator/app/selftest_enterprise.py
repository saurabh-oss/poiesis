"""Self-test for the enterprise overlay: connectors, kernel and domain layer.

No model calls and no internet. Live mode is proved against local stand-ins: one
HTTP server that answers like Jira, ServiceNow, Plane, Slack and Teams, and a
minimal SMTP server. The kernel is exercised on SQLite through FastAPI's test
client with the worked-example domain the overlay ships.

    docker compose exec orchestrator python -m app.selftest_enterprise
"""
from __future__ import annotations

import base64
import importlib
import json
import shutil
import socket
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .config import scaffold_root
# Imported now: the kernel test builds a generated app whose package is also called
# `app`, and it evicts this one from sys.modules while it runs.
from .graph.nodes import domain as domain_stage
from .workspace import checks as ws_checks
from .workspace import interface as ws_interface
from .workspace import repo as ws_repo

PASSED: list[str] = []
FAILED: list[str] = []


def expect(label: str, condition: bool, detail: str = "") -> None:
    (PASSED if condition else FAILED).append(label)
    print(("  ok   " if condition else "  FAIL ") + label + (f"  -- {detail}" if detail and not condition else ""))


OVERLAY = scaffold_root() / "_overlays" / "enterprise"


# ---- local stand-ins for the vendors --------------------------------------------------

class Vendor(BaseHTTPRequestHandler):
    """Answers the handful of endpoints the connectors call, like the real services do."""
    calls: list[dict[str, Any]] = []
    fail_next: list[int] = []          # status codes to answer before behaving

    def log_message(self, *args: Any) -> None:  # quiet
        pass

    def _reply(self, status: int, body: Any, headers: dict[str, str] | None = None) -> None:
        raw = (json.dumps(body) if not isinstance(body, str) else body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json" if not isinstance(body, str) else "text/plain")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _handle(self, method: str) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"null") if length else None
        Vendor.calls.append({"method": method, "path": self.path, "body": body,
                             "auth": self.headers.get("Authorization"), "key": self.headers.get("X-API-Key")})
        if Vendor.fail_next:
            status = Vendor.fail_next.pop(0)
            return self._reply(status, {"error": "try later"}, {"Retry-After": "0"} if status == 429 else None)
        p = self.path
        if p.startswith("/rest/api/2/issue") and p.endswith("/transitions") and method == "GET":
            return self._reply(200, {"transitions": [{"id": "31", "name": "Done", "to": {"name": "Done"}}]})
        if p.startswith("/rest/api/2/issue") and p.endswith("/transitions"):
            return self._reply(204, "")
        if p == "/rest/api/2/issue" and method == "POST":
            return self._reply(201, {"id": "10042", "key": "SUP-42", "self": "x"})
        if p.startswith("/rest/api/2/issue/SUP-42/comment"):
            return self._reply(201, {"id": "9"})
        if p.startswith("/rest/api/2/issue/SUP-42"):
            return self._reply(200, {"key": "SUP-42", "fields": {"summary": "s", "status": {"name": "To Do"}}})
        if p.startswith("/api/now/table/incident") and method == "POST":
            return self._reply(201, {"result": {"number": "INC0012345", "sys_id": "abc", "state": "1"}})
        if p.startswith("/api/now/table/incident?"):
            return self._reply(200, {"result": [{"number": "INC0012345", "sys_id": "abc", "state": "1"}]})
        if p.startswith("/api/now/table/incident/abc"):
            return self._reply(200, {"result": {"number": "INC0012345", "sys_id": "abc", "state": "6"}})
        if "/work-items/" in p and method == "POST" and p.endswith("/work-items/"):
            return self._reply(201, {"id": "uuid-1", "sequence_id": 7})
        if p.endswith("/states/"):
            return self._reply(200, {"results": [{"id": "st-done", "name": "Done", "group": "completed"}]})
        if "/work-items/" in p:
            return self._reply(200, {"id": "uuid-1"})
        if p == "/slack-hook":
            return self._reply(200, "ok")
        if p == "/teams-hook":
            return self._reply(202, "")
        return self._reply(404, {"error": f"no {method} {p}"})

    def do_GET(self) -> None:
        self._handle("GET")

    def do_POST(self) -> None:
        self._handle("POST")

    def do_PATCH(self) -> None:
        self._handle("PATCH")


class TinySMTP(threading.Thread):
    """Enough of RFC 5321 for smtplib's send_message: EHLO, MAIL, RCPT, DATA, QUIT."""

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(4)
        self.port = self.sock.getsockname()[1]
        self.messages: list[str] = []

    def run(self) -> None:
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                f = conn.makefile("rwb")
                f.write(b"220 tiny\r\n"); f.flush()
                data, in_data = [], False
                for raw in f:
                    line = raw.decode(errors="replace").rstrip("\r\n")
                    if in_data:
                        if line == ".":
                            self.messages.append("\n".join(data)); data, in_data = [], False
                            f.write(b"250 queued\r\n")
                        else:
                            data.append(line)
                    elif line.upper().startswith(("EHLO", "HELO")):
                        f.write(b"250 tiny\r\n")
                    elif line.upper() == "DATA":
                        in_data = True; f.write(b"354 go\r\n")
                    elif line.upper() == "QUIT":
                        f.write(b"221 bye\r\n"); f.flush(); break
                    else:
                        f.write(b"250 ok\r\n")
                    f.flush()


def _import_overlay(tmp: Path, package: str = "app") -> Any:
    """A throwaway `app` package made of the overlay, importable in this process."""
    root = tmp / "pkg"
    shutil.copytree(OVERLAY / "backend" / "app", root / package, dirs_exist_ok=True)
    (root / package / "__init__.py").touch()
    sys.path.insert(0, str(root))
    for name in list(sys.modules):
        if name == package or name.startswith(package + "."):
            del sys.modules[name]
    return root


# ---- connectors ------------------------------------------------------------------------

def test_connectors(tmp: Path) -> None:
    print("connectors")
    _import_overlay(tmp, "ovl")
    c = importlib.import_module("ovl.connectors")
    base = importlib.import_module("ovl.connectors.base")
    sleeps: list[float] = []

    # sandbox by default, stateful stand-ins
    store = c.MemoryStore()
    c.set_store(store)
    j = c.Jira(env={})
    expect("with no settings a connector runs in its sandbox", j.mode == "sandbox", j.mode)
    r = j.create_issue("Checkout fails", "14 reports", priority="High", idempotency_key="cluster-1")
    expect("sandbox Jira creates an issue with a project key", r.ok and r.key == "SBX-101" and r.mode == "sandbox", str(r))
    again = j.create_issue("Checkout fails", "14 reports", idempotency_key="cluster-1")
    expect("an idempotency key returns the first result instead of a second issue",
           again.replayed and again.key == "SBX-101" and len(store.objects("jira", "issue")) == 1)
    j.add_comment("SBX-101", "Linked 3 more reports")
    moved = j.transition("SBX-101", "Done")
    got = j.get_issue("SBX-101")
    expect("the sandbox keeps state: comment and transition are read back",
           moved.ok and got.data.get("status") == "Done" and got.data.get("comments") == ["Linked 3 more reports"], str(got.data))
    missing = j.get_issue("SBX-999")
    expect("an unknown key fails with a readable error, not an exception", not missing.ok and "SBX-999" in (missing.error or ""))

    sn = c.ServiceNow(env={})
    inc = sn.create_incident("EU card outage", "details", urgency=1, impact=2)
    sn.add_work_note(inc.key, "Cluster grew to 14")
    sn.resolve_incident(inc.key, "Fixed by payments")
    expect("sandbox ServiceNow numbers incidents INC00xxxxx and resolves them",
           inc.key == "INC0010001" and sn.get_incident(inc.key).data.get("state") == "Resolved", str(sn.get_incident(inc.key).data))

    mail = c.Email(env={})
    sent = mail.send("lead@example.com; ops@example.com", "3 duplicates closed", "Body", html="<p>Body</p>")
    expect("sandbox e-mail builds the real message and keeps it in the outbox",
           sent.ok and sent.data["to"] == "lead@example.com, ops@example.com" and sent.data["html"] == "<p>Body</p>")
    s = c.Slack(env={}).post("Auto-close paused", "Precision fell", facts={"Threshold": 85}, link=("Open", "https://x.test"))
    t = c.Teams(env={}).post("Auto-close paused", "Precision fell", facts={"Threshold": 85}, link=("Open", "https://x.test"))
    expect("sandbox Slack renders Block Kit and Teams an Adaptive Card",
           s.data["blocks"][0]["type"] == "header" and s.data["blocks"][-1]["type"] == "actions"
           and t.data["card"]["attachments"][0]["content"]["type"] == "AdaptiveCard")
    off = c.Jira(env={"JIRA_MODE": "off"}).create_issue("x")
    expect("<NAME>_MODE=off switches a connector off without raising", not off.ok and off.mode == "off")
    events = [e for e in store.events if e["connector"] == "email"]
    expect("every call is an outbox event, sent", events and events[-1]["status"] == "sent")
    cat = {x["name"]: x for x in c.catalogue()}
    expect("the catalogue lists all six connectors with their modes",
           set(cat) == {"jira", "servicenow", "plane", "email", "slack", "teams"})
    red = c.redact({"password": "p", "api_key": "k", "nested": {"token": "t", "ok": 1}})
    expect("secrets are redacted from what is recorded", red == {"password": "•••", "api_key": "•••", "nested": {"token": "•••", "ok": 1}})

    # live mode, against the local stand-ins
    server = ThreadingHTTPServer(("127.0.0.1", 0), Vendor)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        env = {"JIRA_BASE_URL": url, "JIRA_PROJECT": "SUP", "JIRA_EMAIL": "bot@x.test", "JIRA_API_TOKEN": "tok"}
        jl = c.Jira(env=env, sleep=sleeps.append)
        expect("Jira is live once site, project and credentials are set", jl.mode == "live", str(jl.missing()))
        Vendor.fail_next = [503, 429]
        made = jl.create_issue("Checkout fails", "desc", labels=["duplicate cluster"])
        create_calls = [x for x in Vendor.calls if x["path"] == "/rest/api/2/issue"]
        expect("a 503 and a 429 are retried with backoff, then the issue is created",
               made.ok and made.key == "SUP-42" and made.url == f"{url}/browse/SUP-42" and len(create_calls) == 3
               and len(sleeps) == 2, f"{made} calls={len(create_calls)} sleeps={sleeps}")
        expect("Jira Cloud authenticates with the e-mail and API token",
               create_calls[-1]["auth"] == "Basic " + base64.b64encode(b"bot@x.test:tok").decode())
        expect("labels are sent without spaces", create_calls[-1]["body"]["fields"]["labels"] == ["duplicate-cluster"])
        done = jl.transition("SUP-42", "done", comment="Closed by DupeGuard")
        expect("a transition is found by its target status and posted", done.ok and done.data["status"] == "Done", str(done))
        bad = c.Jira(env={**env, "JIRA_BASE_URL": url + "/nowhere"}).get_issue("SUP-1")
        expect("a 404 is not retried and comes back as a readable failure", not bad.ok and "404" in (bad.error or ""))

        snl = c.ServiceNow(env={"SERVICENOW_INSTANCE": url, "SERVICENOW_USERNAME": "u", "SERVICENOW_PASSWORD": "p"})
        inc = snl.create_incident("EU outage", urgency=1, impact=1)
        res = snl.resolve_incident("INC0012345", "fixed")
        expect("ServiceNow live: incident raised and resolved through the Table API",
               inc.ok and inc.key == "INC0012345" and res.ok and res.data.get("state") == "Resolved", f"{inc} {res}")

        pl = c.Plane(env={"PLANE_BASE_URL": url, "PLANE_API_KEY": "k", "PLANE_WORKSPACE": "w", "PLANE_PROJECT_ID": "p",
                          "PLANE_PROJECT_IDENTIFIER": "SUP"})
        item = pl.create_work_item("Cluster", "line one\nline two", priority="HIGH")
        mv = pl.move(item.data["id"], "Done")
        plane_post = next(x for x in Vendor.calls if x["path"].endswith("/work-items/") and x["method"] == "POST")
        expect("Plane live: work item created with the API key, HTML paragraphs, and moved",
               item.ok and item.key == "SUP-7" and mv.ok and plane_post["key"] == "k"
               and plane_post["body"]["description_html"] == "<p>line one</p><p>line two</p>", f"{item} {mv}")

        expect("Slack live through an incoming webhook", c.Slack(env={"SLACK_WEBHOOK_URL": f"{url}/slack-hook"}).post("t", "x").ok)
        expect("Teams live through a Workflows webhook", c.Teams(env={"TEAMS_WEBHOOK_URL": f"{url}/teams-hook"}).post("t", "x").ok)

        # the breaker: five failing calls in a row pause the connector
        c.Connector._breakers.clear()
        dead = {"SLACK_WEBHOOK_URL": "http://127.0.0.1:9/hook"}
        for _ in range(5):
            c.Slack(env=dead, sleep=lambda s: None).post("t")
        paused = c.Slack(env=dead, sleep=lambda s: None).post("t")
        last = store.events[-1]
        expect("after five failures the connector pauses and queues calls as deferred",
               not paused.ok and last["status"] == "deferred" and last.get("retry_at") is not None, str(last))
        c.Connector._breakers.clear()
        failed = next(e for e in reversed(store.events) if e["status"] == "failed" and e["connector"] == "slack")
        expect("a failed call is kept with a retry time for the scheduler", failed.get("retry_at") is not None)
    finally:
        server.shutdown()

    smtp = TinySMTP()
    smtp.start()
    live_mail = c.Email(env={"SMTP_HOST": "127.0.0.1", "SMTP_PORT": str(smtp.port), "SMTP_SECURITY": "none",
                             "SMTP_FROM": "DupeGuard <no-reply@x.test>", "EMAIL_REDIRECT_TO": "qa@x.test"})
    ok = live_mail.send(["lead@x.test"], "Subject line", "Plain body", html="<b>Rich</b>")
    got = smtp.messages[-1] if smtp.messages else ""
    expect("e-mail live over SMTP, redirected to the test inbox with the original recipients kept",
           ok.ok and "To: qa@x.test" in got and "X-Original-To: lead@x.test" in got and "Rich" in got, ok.error or got[:200])
    relay = c.Email(env={"EMAIL_SANDBOX_RELAY": f"127.0.0.1:{smtp.port}"}).send("a@x.test", "Relayed", "x")
    expect("the sandbox hands a copy to a local mail catcher when one is configured",
           relay.mode == "sandbox" and relay.data.get("relayed") is True)
    retried = c.replay({"connector": "email", "operation": "send", "request": {"to": ["b@x.test"], "subject": "Again", "text": "t"}})
    expect("an outbox event can be replayed from what it recorded", retried.ok and retried.data["subject"] == "Again")
    smtp.sock.close()


# ---- kernel -----------------------------------------------------------------------------

def build_app(tmp: Path, name: str = "entapp") -> Path:
    """The web-app scaffold with the enterprise overlay on top, as an importable `app` package."""
    root = tmp / name
    web = scaffold_root() / "web-app"
    shutil.copytree(web / "backend" / "app", root / "app", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(OVERLAY / "backend" / "app", root / "app", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__"))
    for py in (root / "app").rglob("*.py"):
        py.write_text(py.read_text(encoding="utf-8").replace("{{project_name}}", "Kernel Test"), encoding="utf-8")
    return root


def _fresh_import(root: Path) -> None:
    for mod in list(sys.modules):
        if mod == "app" or mod.startswith("app."):
            del sys.modules[mod]
    sys.path.insert(0, str(root))


def test_kernel(tmp: Path) -> None:
    import os
    print("kernel")
    root = build_app(tmp)
    db_file = tmp / "kernel.db"
    os.environ.update({"DATABASE_URL": f"sqlite:///{db_file.as_posix()}", "APP_NAME": "Kernel Test",
                       "JOB_SECONDS": "3600", "POIESIS_SERVICE_TOKEN": "svc-token-123"})
    for k in ("JIRA_BASE_URL", "SMTP_HOST", "TEAMS_WEBHOOK_URL", "SLACK_WEBHOOK_URL"):
        os.environ.pop(k, None)
    _fresh_import(root)
    from fastapi.testclient import TestClient

    main = importlib.import_module("app.main")
    kernel = importlib.import_module("app.kernel")
    with TestClient(main.app) as client:
        expect("the profile is public and says the app is enterprise",
               client.get("/api/platform/profile").json().get("enterprise") is True)
        expect("without a token the data API answers 401", client.get("/api/examples").status_code == 401)
        people = client.get("/api/auth/personas").json()
        expect("the personas from domain/policy.py are offered on the sign-in screen",
               [p["username"] for p in people["personas"]] == ["sam", "rina", "alex"], str(people)[:300])

        def as_(user: str) -> dict[str, str]:
            token = client.post("/api/auth/sign-in", json={"username": user}).json()["token"]
            return {"Authorization": f"Bearer {token}"}

        sam, rina, alex = as_("sam"), as_("rina"), as_("alex")
        me = client.get("/api/auth/me", headers=sam).json()
        expect("a signed-in member is known with roles and permissions",
               me["name"] == "Sam Okafor" and me["roles"] == ["member"] and "example:submit" in me["permissions"])

        made = client.post("/api/examples", json={"label": "Laptop refresh", "amount": 24000}, headers=sam)
        item = made.json()
        expect("a new record starts in its workflow's initial state", made.status_code == 201 and item["status"] == "open",
               made.text[:300])
        forced = client.post("/api/examples", json={"label": "Sneaky", "status": "done"}, headers=sam)
        expect("a new record cannot be created in a later state", forced.status_code == 409 and forced.json()["rule"] == "WF-00",
               forced.text[:300])
        patched = client.patch(f"/api/examples/{item['id']}", json={"status": "done"}, headers=sam)
        expect("writing a governed status directly is refused with WF-00",
               patched.status_code == 409 and patched.json()["rule"] == "WF-00", patched.text[:300])
        gone = client.delete(f"/api/examples/{item['id']}", headers=sam)
        expect("a member without example:delete is refused", gone.status_code == 403, gone.text[:200])

        base = f"/api/platform/workflows/example/{item['id']}"
        expect("start moves open → in_progress", client.post(f"{base}/start", headers=sam).json().get("state") == "in_progress")
        rv = importlib.import_module("app.kernel.rules").RuleViolation("EX-02", "Assign an owner")
        expect("a violation's text carries its rule id", str(rv) == "EX-02: Assign an owner" and rv.message == "Assign an owner")
        no_owner = client.post(f"{base}/submit", headers=sam)
        expect("the guard enforces EX-02 (no owner, no review) with the rule's message",
               no_owner.status_code == 409 and no_owner.json()["rule"] == "EX-02" and "owner" in no_owner.json()["detail"])
        client.patch(f"/api/examples/{item['id']}", json={"owner": "Sam Okafor"}, headers=sam)
        expect("with an owner it goes to review", client.post(f"{base}/submit", headers=sam).json().get("state") == "review")
        state = client.get(base, headers=rina).json()
        options = {o["name"]: o for o in state["available"]}
        expect("the record says what this person may do next, and why not",
               options["finish"]["allowed"] is False and "10,000" in options["finish"]["why_not"]
               and options["finish_large"]["allowed"] is True, str(options)[:400])
        expect("entering review started its 24 h SLA clock", state["clocks"][-1]["state"] == "review" and state["clocks"][-1]["due_at"])
        wrong_role = client.post(f"{base}/finish_large", headers=sam)
        expect("a member may not take a reviewer's transition (WF-01)",
               wrong_role.status_code == 409 and wrong_role.json()["rule"] == "WF-01", wrong_role.text[:200])
        asked = client.post(f"{base}/finish_large", json={"reason": "Budget confirmed"}, headers=rina).json()
        expect("a transition with an approver opens an approval instead of moving",
               asked.get("status") == "pending_approval" and client.get(base, headers=rina).json()["state"] == "review", str(asked))
        inbox = client.get("/api/platform/notifications", headers=alex).json()
        expect("the approver is notified in the app", inbox["unread"] >= 1 and "Approval needed" in inbox["items"][0]["title"])
        refused = client.post(f"/api/platform/approvals/{asked['approval_id']}/approve", headers=rina)
        expect("someone without the approver role cannot decide", refused.status_code == 409 and refused.json()["rule"] == "WF-01")
        ok = client.post(f"/api/platform/approvals/{asked['approval_id']}/approve", json={"note": "Fine"}, headers=alex).json()
        expect("the approver approves and the transition happens", ok.get("status") == "approved" and ok.get("state") == "done", str(ok))

        own = client.post("/api/examples", json={"label": "Own", "amount": 50000, "owner": "Alex"}, headers=alex).json()
        for t in ("start", "submit"):
            client.post(f"/api/platform/workflows/example/{own['id']}/{t}", headers=alex)
        mine = client.post(f"/api/platform/workflows/example/{own['id']}/finish_large", json={"reason": "x"}, headers=alex).json()
        four_eyes = client.post(f"/api/platform/approvals/{mine['approval_id']}/approve", headers=alex)
        expect("nobody approves their own request (WF-02)", four_eyes.status_code == 409 and four_eyes.json()["rule"] == "WF-02",
               four_eyes.text[:200])
        # A request that is itself the record (a proposed change) ends when rejected: `on_reject`.
        finish_large = importlib.import_module("app.domain.workflows").EXAMPLE.get("finish_large")
        finish_large.on_reject = "in_progress"
        svc_headers = {"Authorization": "Bearer svc-token-123"}
        rejected = client.post(f"/api/platform/approvals/{mine['approval_id']}/reject", json={"note": "Not this quarter"},
                               headers=svc_headers).json()
        after = client.get(f"/api/platform/workflows/example/{own['id']}", headers=alex).json()
        expect("a rejected request moves the record to its transition's on_reject state, with an audit entry",
               rejected.get("status") == "rejected" and after["state"] == "in_progress"
               and any("Rejected by" in e["summary"] for e in after["history"]), str(after)[:300])
        finish_large.on_reject = None
        # One transition serving several rules: the caller names the one that took the move.
        context = importlib.import_module("app.kernel.context")
        with context.acting_as(context.SYSTEM), importlib.import_module("app.db")._sessionmaker()() as s:
            kernel.transition(s, s.get(importlib.import_module("app.models").Example, own["id"]), "submit", rule="EX-99")
        moves = [r for r in client.get(f"/api/platform/audit?entity=example&entity_id={own['id']}", headers=alex).json()
                 if r["action"] == "transition"]
        expect("a transition records the rule its caller names over the transition's own",
               moves and moves[0]["rule"] == "EX-99", str(moves[:2])[:300])

        trail = client.get(f"/api/platform/audit?entity=example&entity_id={item['id']}", headers=sam).json()
        actions = [r["action"] for r in trail]
        expect("the record's history holds its creation, edits, transitions and the approval",
               {"create", "update", "transition", "approval"} <= set(actions), str(actions))
        created = next(r for r in trail if r["action"] == "create")
        expect("audit entries name who did it (the actor reaches the ORM listener)", created["actor"] == "Sam Okafor", created["actor"])
        owner_change = next(r for r in trail if r["action"] == "update" and "owner" in (r["changes"] or {}))
        expect("a transition is recorded once, by the transition, not again as a plain update",
               not any(r["action"] == "update" and "status" in (r["changes"] or {}) for r in trail))
        expect("an update records the field before and after", owner_change["changes"].get("owner") == [None, "Sam Okafor"],
               str(owner_change["changes"]))
        expect("the whole trail needs audit:read", client.get("/api/platform/audit", headers=sam).status_code == 403
               and client.get("/api/platform/audit", headers=rina).status_code == 200)
        stats = client.get("/api/platform/audit/stats", headers=rina).json()
        expect("audit statistics count actions", stats["total"] > 5 and dict(stats["by_action"]).get("transition", 0) >= 3)

        cat = client.get("/api/platform/rules", headers=sam).json()
        ids = [r["id"] for r in cat["rules"]]
        expect("the rule catalogue lists the domain's rules and the platform's, in order",
               ids[:3] == ["EX-01", "EX-02", "EX-03"] and "WF-02" in ids, str(ids))
        ex01 = next(r for r in cat["rules"] if r["id"] == "EX-01")
        expect("a rule a workflow transition names keeps the domain's own title and kind",
               ex01["kind"] == "decision" and ex01["title"].startswith("Items over 10,000"), str(ex01))
        ex02 = next(r for r in cat["rules"] if r["id"] == "EX-02")
        expect("the catalogue says where a rule lives and how often it fired or refused",
               ex02["where"].endswith("ready_for_review") and ex02["calls"] >= 2 and ex02["violations"] >= 1, str(ex02))

        outbox = client.get("/api/platform/integrations/events", headers=rina).json()
        kinds = {(e["connector"], e["mode"]) for e in outbox}
        expect("the approval request went out through e-mail and Teams, in their sandboxes",
               ("email", "sandbox") in kinds and ("teams", "sandbox") in kinds, str(kinds))
        expect("testing a connector needs integrations:manage",
               client.post("/api/platform/integrations/jira/test", headers=rina).status_code == 403
               and client.post("/api/platform/integrations/jira/test", headers=alex).json()["key"].endswith("-101"))
        objects = client.get("/api/platform/integrations/jira/objects", headers=rina).json()
        expect("the Jira sandbox holds the issue the test created", objects and objects[0]["status"] == "To Do", str(objects)[:200])

        # SLA: push the open review clock into the past and let the scheduler run
        from app.db import _sessionmaker
        from app.kernel.models import WorkflowClock
        import datetime as dt
        with _sessionmaker()() as s:
            clock = s.query(WorkflowClock).filter_by(entity_id=own["id"], left_at=None).first()
            clock.due_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)
            s.commit()
        done = importlib.import_module("app.kernel.jobs").run_once()
        breach = client.get(f"/api/platform/audit?entity=example&entity_id={own['id']}&action=sla", headers=alex).json()
        expect("a clock past its SLA is escalated by the scheduler and recorded",
               done["sla"] == 1 and breach and "SLA breached" in breach[0]["summary"], f"{done} {breach}")
        rina_inbox = client.get("/api/platform/notifications", headers=rina).json()
        expect("the escalation role hears about the breach", any("SLA breached" in n["title"] for n in rina_inbox["items"]))

        svc = client.get("/api/examples", headers={"Authorization": "Bearer svc-token-123"})
        expect("the platform's service token reads everything (its checks)", svc.status_code == 200 and len(svc.json()) >= 2)
        tables = [t["table"] for t in client.get("/api/resources", headers=sam).json()]
        expect("the kernel's tables are not served by the generic data API",
               not any(t.startswith("sys_") for t in tables) and client.get("/api/sys-users", headers=alex).status_code == 404,
               str(tables))
        bad = client.get("/api/examples", headers={"Authorization": "Bearer forged.token"})
        expect("a forged token is refused", bad.status_code == 401)
    expect("the kernel exposes its API names", all(hasattr(kernel, n) for n in ("rule", "check", "transition", "require", "notify")))

    data_main = importlib.import_module("app.data_main")
    with TestClient(data_main.app) as data_client:
        expect("the data service enforces sign-in too", data_client.get("/api/examples").status_code == 401)
        tok = data_client.post("/api/auth/sign-in", json={"username": "sam"}).json()["token"]
        expect("and serves a signed-in person", data_client.get("/api/examples", headers={"Authorization": f"Bearer {tok}"}).status_code == 200)


# ---- the domain stage's own machinery --------------------------------------------------

TICKET_MODEL = '''

class Ticket(Base):
    __tablename__ = "ticket"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subject: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(40), default="new")  # new|open|closed
    priority: Mapped[str] = mapped_column(String(10), default="P3")
    duplicate_of_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
'''

GOOD_DOMAIN = {
    "policy.py": '''ROLES = {"agent": "Support agent", "lead": "Team lead", "admin": "Administrator"}
PERSONAS = [{"username": "kim", "full_name": "Kim Lee", "title": "Agent", "roles": ["agent"]},
            {"username": "ana", "full_name": "Ana Ruiz", "title": "Lead", "roles": ["lead"]},
            {"username": "alex", "full_name": "Alex Moreau", "title": "Owner", "roles": ["admin"]}]
PERMISSIONS = {"agent": ["ticket:read", "ticket:update", "ticket:open"], "lead": ["ticket:*", "audit:read"], "admin": ["*"]}
SCREENS = {}
CHANNELS = {"approval_requested": ["email"]}
''',
    "rules.py": '''from ..kernel.rules import check, rule

AUTO_CLOSE = 85  # BR-01


@rule("BR-01", "Close automatically at 85 or more", source="BRD 6.1")
def auto_close(score: float) -> bool:
    return score >= AUTO_CLOSE


@rule("BR-04", "A P1 ticket is never closed automatically", source="BRD 6.2", kind="validation")
def not_p1(ticket, ctx=None):
    check(getattr(ticket, "priority", "") != "P1", "BR-04", "P1 tickets are closed by a person")
''',
    "workflows.py": '''from ..kernel.workflow import Transition, Workflow, register
from ..models import Ticket
from . import rules

TICKET = register(Workflow("ticket", Ticket, field="status", states={"new": "New", "open": "Open", "closed": "Closed"},
    initial="new", transitions=[
        Transition("open", "new", "open", roles=("agent", "lead")),
        Transition("close_as_duplicate", ("new", "open"), "closed", roles=("lead",), guard=rules.not_p1,
                   rule="BR-04", fields=("duplicate_of_id",)),
    ], sla={"new": 4}, escalate={"new": "lead"}))
''',
    "services.py": '''from sqlalchemy.orm import Session

from ..kernel import transition
from ..models import Ticket


def close_duplicate(db: Session, ticket_id: int, original_id: int) -> dict:
    t = db.get(Ticket, ticket_id)
    return transition(db, t, "close_as_duplicate", fields={"duplicate_of_id": original_id})
''',
}


def test_domain_stage(tmp: Path) -> None:
    import os
    import subprocess
    print("domain stage")
    stage, checks, interface = domain_stage, ws_checks, ws_interface

    root = tmp / "domainapp"
    web = scaffold_root() / "web-app"
    shutil.copytree(web / "backend", root / "backend", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(OVERLAY / "backend", root / "backend", dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
    for py in (root / "backend").rglob("*.py"):
        py.write_text(py.read_text(encoding="utf-8").replace("{{project_name}}", "Domain Test"), encoding="utf-8")
    (root / ".poiesis").mkdir()
    (root / ".poiesis" / "domain_check.py").write_text(stage.CHECK_SCRIPT, encoding="utf-8")
    env = {**os.environ, "DATABASE_URL": "sqlite://", "PYTHONPATH": ""}

    def run_check() -> dict[str, Any]:
        out = subprocess.run([sys.executable, ".poiesis/domain_check.py"], cwd=root, capture_output=True, text=True,
                             env=env, timeout=120)
        return json.loads(out.stdout.split("POIESIS_DOMAIN_JSON\n", 1)[1].splitlines()[0])

    left = run_check()
    expect("the check flags a worked example left in place",
           any("worked example" in p for p in left["problems"]), str(left["problems"])[:300])

    models = root / "backend" / "app" / "models.py"
    models.write_text(models.read_text(encoding="utf-8") + TICKET_MODEL, encoding="utf-8")
    for name, body in GOOD_DOMAIN.items():
        (root / "backend" / "app" / "domain" / name).write_text(body, encoding="utf-8")
    good = run_check()
    expect("a consistent domain imports and passes every check",
           not good["error"] and not good["problems"], (good["error"] or str(good["problems"]))[:400])
    expect("the check reports the rules, the workflow, the roles and the services",
           [r["id"] for r in good["rules"]] == ["BR-01", "BR-04"] and good["workflows"][0]["name"] == "ticket"
           and set(good["roles"]) == {"agent", "lead", "admin"} and good["services"] == ["close_duplicate"],
           json.dumps(good)[:400])

    bad_policy = GOOD_DOMAIN["policy.py"].replace('"ticket:open"]', '"tickets:open"]').replace('["lead"]}', '["leader"]}')
    (root / "backend" / "app" / "domain" / "policy.py").write_text(bad_policy, encoding="utf-8")
    bad_flow = GOOD_DOMAIN["workflows.py"].replace('"closed", roles=("lead",)', '"resolved", roles=("manager",)')
    (root / "backend" / "app" / "domain" / "workflows.py").write_text(bad_flow, encoding="utf-8")
    bad = run_check()
    joined = " | ".join(bad["problems"])
    expect("misspelt tables, unknown roles and states are each named",
           "no table 'tickets'" in joined and "'leader'" in joined and "to 'resolved' is not a state" in joined
           and "role 'manager' is not in ROLES" in joined, joined[:500])
    (root / "backend" / "app" / "domain" / "rules.py").write_text("from ..kernel.rules import rule\nimport nothing_here\n", encoding="utf-8")
    broken = run_check()
    expect("a domain that does not import is reported with its traceback",
           "nothing_here" in broken["error"], broken["error"][:300])

    cases = [{"name": "test_br_01_at_threshold", "passed": True, "message": ""},
             {"name": "test_br_01_below", "passed": False, "message": "assert False"},
             {"name": "test_something_else", "passed": True, "message": ""}]
    mapped = stage.results_by_rule([{"id": "BR-01"}, {"id": "BR-04"}, {"id": "BR-10"}], cases)
    expect("tests map to rules by name, and untested rules are listed",
           mapped["rules"]["BR-01"] == {"total": 2, "passed": 1, "names": ["test_br_01_at_threshold", "test_br_01_below"]}
           and mapped["untested"] == ["BR-04", "BR-10"] and mapped["failed"] == 1, json.dumps(mapped)[:300])
    good_try = stage._score({"error": "", "problems": []}, [{"passed": True}] * 20, {"untested": ["BR-13"]})
    worse_try = stage._score({"error": "", "problems": []}, [{"passed": True}] * 18 + [{"passed": False}] * 2, {"untested": []})
    broken_try = stage._score({"error": "Traceback", "problems": []}, [], {})
    expect("attempts are ranked: failing tests weigh more than an untested rule, not importing most",
           good_try > worse_try > broken_try, f"{good_try} {worse_try} {broken_try}")
    mapped10 = stage.results_by_rule([{"id": "BR-1"}, {"id": "BR-10"}], [{"name": "test_br_10_x", "passed": True, "message": ""}])
    expect("BR-10's tests are not taken for BR-1's", "BR-10" in mapped10["rules"] and "BR-1" not in mapped10["rules"])

    # the static checks, through a throwaway run workspace
    ws = ws_repo
    rid = f"selftest-domain-{os.getpid()}"
    wroot = ws.workspace_path(rid)
    try:
        shutil.copytree(root / "backend", wroot / "backend")
        for name, body in GOOD_DOMAIN.items():
            (wroot / "backend" / "app" / "domain" / name).write_text(body, encoding="utf-8")
        (wroot / "backend" / "app" / "routers" / "tickets.py").write_text('''import requests
from fastapi import APIRouter, Depends
from ..db import get_session
from ..models import Ticket
router = APIRouter()

@router.post("/tickets/{ticket_id}/close")
def close(ticket_id: int, db=Depends(get_session)):
    t = db.get(Ticket, ticket_id)
    t.status = "closed"
    db.commit()
    return {"ok": True}
''', encoding="utf-8")
        expect("governed columns are read from workflows.py", checks.governed_columns(rid) == {"Ticket": ("status", "ticket")},
               str(checks.governed_columns(rid)))
        found = checks.enterprise_issues(rid)
        expect("a router that writes a governed status, or calls out with requests, is flagged before it runs",
               any("governs" in f and "line 10" in f for f in found) and any("`requests`" in f for f in found), str(found)[:400])
        contract = interface.import_contract(rid)
        expect("the Developer's import contract lists the domain, the kernel and the connectors",
               "from ..domain.rules import" in contract and "auto_close" in contract
               and "from ..kernel import" in contract and "transition" in contract
               and "from ..connectors import" in contract and "jira" in contract, contract[:600])
    finally:
        shutil.rmtree(wroot, ignore_errors=True)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="poiesis-enterprise-"))
    try:
        test_connectors(tmp)
        for extra in ("test_domain_stage", "test_kernel"):
            fn = globals().get(extra)
            if fn:
                fn(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    for f in FAILED:
        print("  FAILED:", f)
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
