"""Stage: the business logic, once, from the whole backlog (enterprise pack).

DupeGuard's MVP run showed why this exists. Its brief had one duplicate score (55/20/15/10
with six named rules) and the run shipped three different ones: each story implemented
the score inside its own router, from its own reading of the brief, and each screen showed
its own numbers. Nothing was wrong in any single file; the rule simply had no home.

Here the rule gets one. After the data model and before the demonstration data, the
Developer writes the application's domain layer — policy (roles, personas, permissions),
rules (every business rule with its id and source), workflows (each record's lifecycle,
approvals, SLAs) and services — plus a test file with at least two tests per rule. The
platform imports it, checks it against the data model (every role, table and state spelled
as it exists), runs the rule tests in the sandbox, and hands every failure back until it
holds, up to build.domain_repairs times. The result is baked into the application for its
Business rules screen: which rules exist, where each lives, and what its tests proved.

Stories then import the domain instead of re-deciding it, and may not edit policy, rules
or workflows; services.py stays theirs to extend.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from typing import Any

from ... import requirements as req
from ...agents.base import DOMAIN
from ...config import pack
from ...events import emit
from ...llm import ReplyTruncated, UnparseableReply
from ...workspace import repo
from ...workspace.interface import import_contract
from ...workspace.runner import run_in_sandbox
from ..memo import remember
from ..state import RunState

FILES = ("backend/app/domain/policy.py", "backend/app/domain/rules.py", "backend/app/domain/workflows.py",
         "backend/app/domain/services.py", "tests/test_rules.py")
# Designed once for the whole product; a story extends services.py, never these.
PROTECTED = ("backend/app/domain/__init__.py", "backend/app/domain/policy.py", "backend/app/domain/rules.py",
             "backend/app/domain/workflows.py", "tests/test_rules.py", "backend/app/domain/rule_results.json")
RESULTS = "backend/app/domain/rule_results.json"

CHECK_SCRIPT = r'''
import json, re, sys, traceback
sys.path.insert(0, "backend")
out = {"error": "", "problems": [], "rules": [], "workflows": [], "roles": {}, "personas": [], "services": []}
try:
    from app import models  # noqa: F401
    from app.db import Base
    import app.kernel  # noqa: F401 — the kernel's tables and registries
    import app.domain  # policy, rules, workflows: importing registers them
    import app.domain.services as services
    from app.kernel import rules as R, workflow as W
    from app.kernel.policy import POLICY
    POLICY.loaded = False
    P = POLICY.load()
    if P.error:
        out["problems"].append(f"domain/policy.py: {P.error}")
    tables = {t.name for t in Base.metadata.sorted_tables}
    platform = {"audit", "rules", "integrations", "users", "*"}
    roles = set(P.roles)
    for role, perms in P.permissions.items():
        if role not in roles:
            out["problems"].append(f"PERMISSIONS names the role '{role}', which ROLES does not define")
        for perm in perms:
            entity = perm.split(":", 1)[0]
            if entity not in tables and entity not in platform:
                out["problems"].append(f"PERMISSIONS['{role}'] has '{perm}': there is no table '{entity}' "
                                       f"(tables: {', '.join(sorted(t for t in tables if not t.startswith('sys_')))})")
    for p in P.personas:
        for r in p.get("roles", []):
            if r not in roles:
                out["problems"].append(f"persona {p.get('username')} has the role '{r}', which ROLES does not define")
    covered = {r for p in P.personas for r in p.get("roles", [])}
    for r in roles - covered - {"admin"}:
        out["problems"].append(f"no persona holds the role '{r}': add one, or the role can never be shown")
    for w in W.iter_workflows():
        if w.model.__tablename__ == "example" or w.name == "example":
            out["problems"].append("the worked example's workflow is still registered: replace workflows.py entirely")
            continue
        states = set(w.states)
        if w.initial not in states:
            out["problems"].append(f"workflow {w.name}: initial state '{w.initial}' is not one of its states {sorted(states)}")
        column = w.model.__table__.columns.get(w.field)
        if column is None:
            out["problems"].append(f"workflow {w.name}: {w.model.__tablename__} has no column '{w.field}'")
        for t in w.transitions:
            for s in t.sources():
                if s != "*" and s not in states:
                    out["problems"].append(f"workflow {w.name}, transition {t.name}: from '{s}' is not a state")
            if t.target not in states:
                out["problems"].append(f"workflow {w.name}, transition {t.name}: to '{t.target}' is not a state")
            for r in list(t.roles) + ([t.approval] if t.approval else []) + list(t.notify):
                if r not in roles:
                    out["problems"].append(f"workflow {w.name}, transition {t.name}: role '{r}' is not in ROLES")
            for f in t.fields:
                if w.model.__table__.columns.get(f) is None:
                    out["problems"].append(f"workflow {w.name}, transition {t.name}: {w.model.__tablename__} has no column '{f}'")
        for s, r in w.escalate.items():
            if r not in roles:
                out["problems"].append(f"workflow {w.name}: escalate role '{r}' is not in ROLES")
        out["workflows"].append(w.describe())
    rules = [r for r in R.catalogue() if not r["id"].startswith("WF-")]
    if any(r["id"].startswith("EX-") for r in rules):
        out["problems"].append("the worked example's EX- rules are still there: replace rules.py entirely")
    if not rules:
        out["problems"].append("rules.py registers no rules: every business rule of the brief needs a @rule function")
    out["rules"] = rules
    out["roles"] = P.roles
    out["personas"] = [{k: p.get(k) for k in ("username", "full_name", "title", "roles")} for p in P.personas]
    out["services"] = [n for n in dir(services) if not n.startswith("_") and callable(getattr(services, n))
                       and getattr(getattr(services, n), "__module__", "") == services.__name__]
except Exception:
    tb = traceback.format_exc()
    lines = [l for l in tb.splitlines() if "site-packages" not in l and "<frozen" not in l]
    out["error"] = "\n".join(lines[-14:])
print("POIESIS_DOMAIN_JSON")
print(json.dumps(out, default=str))
'''

# The rule tests are pure, so they run without the app's test fixtures (--noconftest,
# backend on the path): tests/conftest.py builds a test client and needs httpx, and a
# failure there is in a file the Developer may not edit — the first enterprise run spent
# a repair on exactly that.
COMMAND = (
    "pip install --quiet --disable-pip-version-check --root-user-action=ignore -r backend/requirements.txt pytest httpx >/dev/null 2>&1; "
    "python .poiesis/domain_check.py; "
    "PYTHONPATH=backend python -m pytest -q -p no:cacheprovider --noconftest --tb=line tests/test_rules.py "
    "--junitxml=.poiesis/rules.xml 2>&1 | tail -25"
)


def enabled(run_id: str) -> bool:
    return bool(pack().get("build", {}).get("domain", False)) \
        and (repo.workspace_path(run_id) / "backend" / "app" / "kernel").is_dir()


def _stories(state: RunState) -> str:
    return "\n".join(
        f"- {s.get('id')}: {s.get('title')}" + (f" (as {s.get('role')})" if s.get("role") else "") + "\n"
        + "\n".join(f"    · {c}" for c in s.get("acceptance_criteria") or [])
        for s in (state.get("backlog") or {}).get("stories") or [])


def _current(run_id: str) -> str:
    blocks = []
    for rel in FILES:
        body = repo.read(run_id, rel, 12000)
        if body:
            blocks.append(f"--- {rel} ---\n{body}")
    return "\n".join(blocks)


def _prompt(state: RunState, run_id: str) -> str:
    root = repo.workspace_path(run_id)
    vision = state.get("vision") or {}
    models = (root / "backend" / "app" / "models.py").read_text(encoding="utf-8", errors="replace")
    sql = _schema(root)
    return (
        (f"PRODUCT: {vision.get('product_name', '')}\n{vision.get('value_proposition', '')}\n\n" if vision else "")
        + "BRIEF (find every rule, role, lifecycle, approval and SLA in it):\n"
        + str(state.get("brief") or "")[:26000]
        + _required(state)
        + f"\n\nEVERY STORY AND ITS ACCEPTANCE CRITERIA:\n{_stories(state)}\n"
        + f"\nbackend/app/models.py (table names and columns, exactly):\n{models[:9000]}\n"
        + f"\ndb/init.sql tables (the comments list each status column's allowed values):\n{sql[:7000]}\n"
        + import_contract(run_id)
        + "\nTHE WORKED EXAMPLE NOW IN THE WORKSPACE (its shape is what you follow; its content is what you replace):\n"
        + _current(run_id)[:12000]
        + "\n\nWrite the five files."
    )


def _required(state: RunState) -> str:
    """The brief's rules, roles, lifecycles and integrations, from the requirements inventory."""
    inv = state.get("requirements") or []
    rules = [it for it in inv if it["kind"] in req.RULE_KINDS]
    other = [it for it in inv if it["kind"] in ("role", "workflow", "integration", "notification")]
    out = ""
    if rules:
        out += ("\n\nRULES THE BRIEF STATES — register each with @rule under exactly this id (declare() it when a "
                "workflow or service implements it), implement it as written with no simplification, and state "
                "every listed number as a literal in its tests:\n" + req.describe(rules, limit=80))
    if other:
        out += "\n\nROLES, LIFECYCLES, INTEGRATIONS AND NOTIFICATIONS THE BRIEF STATES:\n" + req.describe(other, limit=40)
    return out


def _brief_gaps(state: RunState, run_id: str, report: dict[str, Any]) -> list[str]:
    """What the domain leaves out of the brief: rules missing, numbers untested, shortcuts admitted."""
    inv = state.get("requirements") or []
    if not inv or report.get("error"):
        return []
    files = {rel: repo.read(run_id, rel, 400000) for rel in FILES if rel.startswith("backend/")}
    return req.domain_gaps(inv, [r.get("id", "") for r in report.get("rules", [])],
                           repo.read(run_id, "tests/test_rules.py", 400000), files)


def _schema(root: Any) -> str:
    """init.sql without its INSERT rows, keeping the comments that list allowed values."""
    text = (root / "db" / "init.sql").read_text(encoding="utf-8", errors="replace")
    keep, skipping = [], False
    for line in text.splitlines():
        if line.lstrip().upper().startswith("INSERT INTO"):
            skipping = not line.rstrip().endswith(";")
            continue
        if skipping:
            skipping = not line.rstrip().endswith(";")
            continue
        keep.append(line)
    return "\n".join(keep)


def _junit(run_id: str) -> list[dict[str, Any]]:
    path = repo.workspace_path(run_id) / ".poiesis" / "rules.xml"
    if not path.is_file():
        return []
    try:
        tree = ET.parse(path)
    except ET.ParseError:
        return []
    out = []
    for case in tree.iter("testcase"):
        failed = case.find("failure") if case.find("failure") is not None else case.find("error")
        skipped = case.find("skipped") is not None
        out.append({"name": case.get("name", ""), "passed": failed is None and not skipped,
                    "message": ((failed.get("message") or failed.text or "")[:400] if failed is not None else "")})
    return out


def _slug(rule_id: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", rule_id.lower()).strip("_")


def results_by_rule(rules: list[dict[str, Any]], cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Map `test_br_04_…` to BR-04. Returns the rule_results.json document."""
    by_rule: dict[str, dict[str, Any]] = {}
    ids = sorted((r["id"] for r in rules), key=lambda i: -len(_slug(i)))
    for case in cases:
        name = case["name"].lower()
        rid = next((i for i in ids if name.startswith(f"test_{_slug(i)}_") or name == f"test_{_slug(i)}"), None)
        if rid is None:
            continue
        entry = by_rule.setdefault(rid, {"total": 0, "passed": 0, "names": []})
        entry["total"] += 1
        entry["passed"] += 1 if case["passed"] else 0
        entry["names"].append(case["name"])
    return {"ran_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "total": len(cases), "passed": sum(1 for c in cases if c["passed"]),
            "failed": sum(1 for c in cases if not c["passed"]), "rules": by_rule,
            "untested": [r["id"] for r in rules if r["id"] not in by_rule]}


async def _check(run_id: str) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    tools = repo.workspace_path(run_id) / ".poiesis"
    tools.mkdir(exist_ok=True)
    (tools / "domain_check.py").write_text(CHECK_SCRIPT, encoding="utf-8", newline="\n")
    (tools / "rules.xml").unlink(missing_ok=True)
    result = await run_in_sandbox(run_id, COMMAND, timeout=600, network=True)
    marker = "POIESIS_DOMAIN_JSON\n"
    report: dict[str, Any] = {"error": "the domain check produced no report", "problems": [], "rules": []}
    if marker in result.stdout:
        try:
            report = json.loads(result.stdout.split(marker, 1)[1].splitlines()[0])
        except (ValueError, IndexError):
            pass
    else:
        report["error"] += ":\n" + "\n".join((result.stderr or result.stdout).strip().splitlines()[-12:])
    tail = result.stdout.split(marker, 1)[1].split("\n", 2)[-1] if marker in result.stdout else ""
    return report, _junit(run_id), tail


def _feedback(report: dict[str, Any], cases: list[dict[str, Any]], results: dict[str, Any], tail: str) -> list[str]:
    problems: list[str] = []
    if report.get("error"):
        problems.append("The domain does not import. The traceback:\n" + report["error"])
        return problems
    problems += report.get("problems", [])
    failing = [c for c in cases if not c["passed"]]
    for c in failing[:10]:
        problems.append(f"test {c['name']} fails: {c['message']}")
    if failing:
        problems.append("For each failing test decide from the brief which side is wrong: if the rule computes "
                        "what the brief says, correct the test's expected value; if not, correct the rule. "
                        "Check a refusal with `err.value.rule_id == \"BR-04\"`.")
    if not cases:
        problems.append("tests/test_rules.py ran no tests" + (f":\n{tail[-800:]}" if tail.strip() else ""))
    untested = results.get("untested") or []
    if untested and cases:
        problems.append("rules with no test named after them (name each test test_<id>_…, e.g. "
                        f"test_{_slug(untested[0])}_…): " + ", ".join(untested[:12]))
    return problems


def _score(report: dict[str, Any], cases: list[dict[str, Any]], results: dict[str, Any]) -> tuple[int, ...]:
    """How good an attempt is, for keeping the best one: importing, then consistency, then
    passing tests, then coverage. A later attempt can be worse than an earlier one."""
    if report.get("error"):
        return (0, 0, 0, 0, 0)
    failing = sum(1 for c in cases if not c["passed"])
    return (1, -len(report.get("problems", [])), 0 if cases else -1, -failing,
            -len(results.get("untested") or []))


FALLBACK_POLICY = '''"""Who may do what. The domain stage could not produce a working policy, so this is the
platform's general one: everyone reads and works on everything; managers also delete and
oversee. Replace it with the application's own roles."""

ROLES = {"user": "User", "manager": "Manager", "admin": "Administrator"}
PERSONAS = [
    {"username": "jordan", "full_name": "Jordan Ellis", "title": "Coordinator", "team": "Operations", "roles": ["user"]},
    {"username": "priya", "full_name": "Priya Raman", "title": "Operations manager", "team": "Operations", "roles": ["manager"]},
    {"username": "alex", "full_name": "Alex Moreau", "title": "Platform owner", "team": "IT", "roles": ["admin"]},
]
PERMISSIONS = {
    "user": ["*:read", "*:create", "*:update"],
    "manager": ["*:read", "*:create", "*:update", "*:delete", "audit:read", "rules:read", "integrations:read", "users:read"],
    "admin": ["*"],
}
SCREENS: dict = {}
CHANNELS = {"approval_requested": ["email"], "sla_breached": ["email"]}
'''
FALLBACK_EMPTY = {
    "backend/app/domain/rules.py": '"""Business rules. The domain stage did not produce working rules; none are registered."""\n',
    "backend/app/domain/workflows.py": '"""Lifecycles. The domain stage did not produce working workflows; none are registered."""\n',
    "backend/app/domain/services.py": '"""Operations over the database. None yet."""\n',
    "tests/test_rules.py": '"""Rule tests. The domain stage did not produce working rules."""\n',
}


async def design_domain(state: RunState, run_id: str) -> dict[str, Any]:
    """Write, check and test the domain layer. Returns the record kept in state['domain']."""
    repairs = int(pack().get("build", {}).get("domain_repairs", 3))
    await emit(run_id, "Designing the business logic once, from the whole backlog: roles, rules, lifecycles",
               agent="developer", stage="foundation")
    # The check imports the workspace's copy of the kernel: bring it up to date first, so
    # a run in flight is checked against the platform as it is now.
    from .scaffold import refresh_platform_files
    refresh_platform_files(run_id, state)
    base = _prompt(state, run_id)
    feedback = ""
    report: dict[str, Any] = {}
    results: dict[str, Any] = {}
    problems: list[str] = ["not attempted"]
    reply: dict[str, Any] = {}
    best: dict[str, Any] | None = None
    for attempt in range(repairs + 1):
        # Keyed by what the attempt was told as well: a resumed run whose checks changed
        # must not replay a reply written against the old feedback.
        key = f"domain:{attempt}:{hashlib.sha1(feedback.encode()).hexdigest()[:10]}"
        try:
            reply = await remember(run_id, key, lambda: DOMAIN.json(base + feedback, max_tokens=16000))
        except (ReplyTruncated, UnparseableReply) as exc:
            problems = [f"your reply could not be read ({type(exc).__name__}): keep each file compact — "
                        "no docstrings beyond one line per function, no comments except the rules' sources"]
            feedback = "\n\nYOUR PREVIOUS REPLY WAS UNUSABLE: " + problems[0] + "\nReturn all five files."
            await emit(run_id, f"Business logic, attempt {attempt + 1}: the reply was unreadable",
                       agent="developer", stage="foundation", level="warn")
            continue
        files = {k: v for k, v in (reply.get("files") or {}).items() if k in FILES and isinstance(v, str) and v.strip()}
        if files:
            repo.write_files(run_id, files)
        report, cases, tail = await _check(run_id)
        results = results_by_rule(report.get("rules", []), cases)
        problems = _feedback(report, cases, results, tail) + _brief_gaps(state, run_id, report)
        rules_n, flows_n = len(report.get("rules", [])), len(report.get("workflows", []))
        score = _score(report, cases, results)
        if best is None or score > best["score"]:
            best = {"score": score, "files": {rel: repo.read(run_id, rel, 400000) for rel in FILES},
                    "report": report, "results": results, "problems": problems, "reply": reply, "attempt": attempt + 1}
        if not problems:
            await emit(run_id, f"Business logic in place: {rules_n} rule(s), {flows_n} workflow(s), "
                               f"{len(report.get('roles', {}))} role(s); {results['passed']}/{results['total']} rule tests pass",
                       agent="developer", stage="foundation",
                       data={"rules": [r["id"] for r in report.get("rules", [])], "tests": results["total"]})
            break
        await emit(run_id, f"Business logic, attempt {attempt + 1}: " + "; ".join(p.splitlines()[0][:150] for p in problems[:4]),
                   agent="developer", stage="foundation", level="warn", data={"problems": problems[:20]})
        feedback = ("\n\nYOUR PREVIOUS FILES ARE IN THE WORKSPACE ABOVE AND WERE CHECKED. Fix every problem:\n"
                    + "\n".join(f"- {p}" for p in problems[:16])
                    + "\nReturn all five files, complete.")
        base = _prompt(state, run_id)
    if best is not None and problems and best["problems"] != problems:
        # A repair can make things worse; keep the attempt that was best.
        repo.write_files(run_id, {rel: body for rel, body in best["files"].items() if body})
        report, results, problems, reply = best["report"], best["results"], best["problems"], best["reply"]
        await emit(run_id, f"Kept attempt {best['attempt']}, the best of them: "
                           + ("; ".join(p.splitlines()[0][:120] for p in problems[:3]) or "no problems"),
                   agent="developer", stage="foundation", level="info")
    imports = not report.get("error")
    if not imports:
        # A domain that does not import takes sign-in with it; the general policy keeps
        # the application usable, and the failure stays on the record.
        repo.write_files(run_id, {"backend/app/domain/policy.py": FALLBACK_POLICY, **FALLBACK_EMPTY})
        report, cases, _ = await _check(run_id)
        results = results_by_rule(report.get("rules", []), cases)
        await emit(run_id, "The business logic never imported; the application runs on the platform's general "
                           "policy, with no rules or workflows", agent="developer", stage="foundation", level="error",
                   data={"problems": problems[:20]})
    elif problems:
        await emit(run_id, f"The business logic has remaining problems after {repairs + 1} attempt(s); carrying on with it",
                   agent="developer", stage="foundation", level="warn", data={"problems": problems[:20]})
    repo.write_files(run_id, {RESULTS: json.dumps(results, indent=1)})
    sha = repo.commit(run_id, reply.get("commit_message") or "feat(domain): business rules, workflows and policy")
    return {
        "imports": imports,
        "rules": [{k: r.get(k) for k in ("id", "title", "kind", "source", "where")} for r in report.get("rules", [])],
        "workflows": [{"name": w["name"], "entity": w["entity"], "field": w.get("field", "status"),
                       "states": [s["key"] for s in w["states"]],
                       "transitions": [t["name"] for t in w["transitions"]]} for w in report.get("workflows", [])],
        "roles": report.get("roles", {}),
        "personas": report.get("personas", []),
        "services": report.get("services", []),
        "tests": {k: results.get(k) for k in ("total", "passed", "failed", "untested")},
        "problems": problems if problems != ["not attempted"] else [],
        "protected": list(PROTECTED),
        "commit": sha,
    }


def note_for_developer(state: RunState) -> str:
    """What the build stage tells every story about the domain it must use."""
    d = state.get("domain") or {}
    if not d or not d.get("imports"):
        return ""
    rules = "\n".join(f"  {r['id']}: {r['title']}  → {r.get('where') or ''}" for r in d.get("rules", [])[:40])
    flows = "\n".join(f"  {w['name']} ({w['entity']}): states {', '.join(w['states'])}; transitions {', '.join(w['transitions'])}"
                      for w in d.get("workflows", []))
    roles = ", ".join(f"{k} ({v})" for k, v in (d.get("roles") or {}).items())
    return (
        "\n\nTHE BUSINESS LOGIC ALREADY EXISTS (backend/app/domain/). Use it; never re-implement a rule:\n"
        f"RULES (import from ..domain.rules):\n{rules or '  (none)'}\n"
        f"WORKFLOWS (move records only with transition(), or the screen's workflow.panel):\n{flows or '  (none)'}\n"
        f"SERVICES (from ..domain.services import …): {', '.join(d.get('services') or []) or '(none yet)'}\n"
        f"ROLES: {roles}\n"
        "policy.py, rules.py, workflows.py and tests/test_rules.py are read-only for stories; add an operation to "
        "services.py when your story needs one.\n"
    )
