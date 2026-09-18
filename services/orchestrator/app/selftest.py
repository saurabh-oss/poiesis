"""Self-test for the web-app scaffold and the platform's checks. Makes no model calls.

Scaffolds a throwaway run, then proves each layer:
  1. the bare scaffold passes pytest, and the checks demand a screen for S1;
  2. a screen broken the way a released app's once was is caught by the checks;
  3. a correct screen passes pytest and the checks;
  4. deployed, the browser check passes the good screen and fails a broken one.

    docker compose exec orchestrator python -m app.selftest

Everything it creates (workspace, containers, volume, database rows) is removed
at the end, pass or fail.
"""
from __future__ import annotations

import asyncio
import json
import subprocess

from .config import scaffold_root
from .db import Deployment, Run, session
from .graph.memo import _forget
from .graph.nodes.build import _verify
from .graph.nodes.scaffold import materialise
from .graph.nodes.ship import _attribute_to_last_writer, _sole_owned_files
from .workspace import browser_check, checks, deployment, repo
from .workspace.interface import import_contract, route_contract
from .workspace.runner import pytest_command, run_in_sandbox

ROUTER = '''from fastapi import APIRouter

router = APIRouter()


@router.get("/llm-overview")
def overview():
    return [{"name": "GPT-4", "summary": "A large language model from OpenAI."},
            {"name": "Claude", "summary": "A large language model from Anthropic."}]
'''

GOOD = '''export default {
  title: "LLM overview",
  story: "S1",
  async render(root, { api, h }) {
    const rows = await api("/llm-overview");
    root.append(
      h("section", { class: "panel stack" },
        h("h2", {}, "Large language models"),
        h("ul", { class: "list" }, rows.map((r) => h("li", {}, h("strong", {}, r.name), " - ", r.summary)))),
    );
  },
};
'''

# The failure modes of a released app that showed only the scaffold placeholder.
BAD_STATIC = '''// Placeholder for navigation
window.onload = () => { api('GET', '/api/llm-overviews').then((d) => alert(d)); };
export default { title: "Broken", story: "S2", render() {} };
'''

JSX = '''export default {
  title: "Feedback",
  story: "S3",
  render(root) { return (<div>Feedback</div>); },
};
'''

# Passes every static check, but throws when it renders against the real API.
BAD_RUNTIME = '''export default {
  title: "Model count",
  story: "S2",
  async render(root, { api, h }) {
    const data = await api("/llm-overview");
    root.append(h("p", {}, data.items.length + " models"));
  },
};
'''

# Declared at "/" (served at /api/) while its screen calls /items.
BARE_ROUTER = '''from fastapi import APIRouter

router = APIRouter()


@router.get("/")
def list_items():
    return [{"name": "first item"}, {"name": "second item"}]


@router.get("/{item_id}")
def get_item(item_id: int):
    return {"name": f"item {item_id}"}
'''

ITEMS = '''export default {
  title: "Items",
  story: "S4",
  async render(root, { api, h }) {
    const rows = await api("/items");
    root.append(h("section", { class: "panel stack" }, h("h2", {}, "Items"),
      h("ul", { class: "list" }, rows.map((r) => h("li", {}, r.name)))));
  },
};
'''

# A GET endpoint no story test calls, with a slip that only shows when it runs.
CRASHING = '''from fastapi import APIRouter

router = APIRouter()


def _lookup():
    value = value + 1
    return value


@router.get("/crashing")
def crashing():
    return {"value": _lookup()}
'''

# Queries the scaffold's own Example table, which nothing ever seeds — the
# empty-content-on-a-fresh-deployment pattern, reusing a model that already exists.
UNSEEDED_ROUTER = '''from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..db import get_session
from ..models import Example
from ..schemas import ExampleOut

router = APIRouter()


@router.get("/reference-facts", response_model=list[ExampleOut])
def get_reference_facts(db: Session = Depends(get_session)):
    return db.query(Example).all()
'''

UNSEEDED_SCREEN = '''export default {
  title: "Reference facts",
  story: "S5",
  async render(root, { api, h }) {
    const rows = await api("/reference-facts");
    root.append(h("ul", { class: "list" }, rows.map((r) => h("li", {}, r.label))));
  },
};
'''

failures: list[str] = []


def show(label: str, value: object) -> None:
    print(f"\n===== {label} =====\n{value}")


def expect(label: str, condition: bool) -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {label}")
    if not condition:
        failures.append(label)


async def main() -> int:
    with session() as s:
        run = Run(title="Poiesis self-test (scaffold)")
        s.add(run)
        s.commit()
        rid = run.id
    print("run id", rid)
    try:
        repo.init_workspace(rid)
        materialise(scaffold_root() / "web-app", repo.workspace_path(rid),
                    {"project_name": "Selftest", "project_slug": "selftest", "description": "x"})
        checks.regenerate_registry(rid)
        repo.commit(rid, "scaffold")
        show("route contract", route_contract(rid))
        show("import contract", import_contract(rid))

        t = await run_in_sandbox(rid, pytest_command(), timeout=600, network=True)
        expect("bare scaffold passes pytest", t.ok)
        c = await checks.platform_checks(rid, "S1", True)
        show("checks for S1 on the bare scaffold", c.stdout)
        expect("a story with no screen fails the checks", not c.ok and "has no screen" in c.stdout)

        repo.write_files(rid, {"backend/app/routers/llm_overview.py": ROUTER,
                               "frontend/screens/llm_overview.js": GOOD,
                               "frontend/screens/broken.js": BAD_STATIC,
                               "frontend/screens/feedback.js": JSX})
        checks.regenerate_registry(rid)
        c = await checks.platform_checks(rid, "S2", True)
        show("checks for S2", c.stdout)
        expect("placeholder, dialog, page startup and wrong path are all caught",
               not c.ok and all(k in c.stdout for k in
                                ("Placeholder", "alert()", "page startup", "/api/llm-overviews")))
        expect("S2's report does not include S3's files", "feedback.js" not in c.stdout
               and "Unexpected token" not in c.stdout)
        c = await checks.platform_checks(rid, "S3", True)
        show("checks for S3", c.stdout)
        expect("JSX is caught", not c.ok and "JSX" in c.stdout)

        # A reply truncated mid-statement — the exact shape of a real failure: a
        # deployment's db container crash-looped on this, and every test had
        # passed, because pytest builds its tables from the models, never from
        # this file.
        sql_path = repo.workspace_path(rid) / "db" / "init.sql"
        good_sql = sql_path.read_text(encoding="utf-8")
        sql = await checks.validate_init_sql(rid)
        expect("a correct init.sql runs cleanly against real Postgres", sql.ok)
        sql_path.write_text(
            good_sql + "\nCREATE TABLE app_user (\n    id SERIAL PRIMARY KEY,\n"
            "    manager_id INTEGER REFERENC\n",
            encoding="utf-8",
        )
        sql = await checks.validate_init_sql(rid)
        show("init.sql truncated mid-statement", sql.stdout)
        expect("a syntax error in init.sql is caught by actually running it",
               not sql.ok and "REFERENC" in sql.stdout)
        c = await checks.platform_checks(rid, "S1", True)
        expect("the broken init.sql shows up in the combined platform check",
               not c.ok and "init.sql" in c.stdout and "pytest never catches this" in c.stdout)
        sql_path.write_text(good_sql, encoding="utf-8")

        # A column the model declares that the real table doesn't have — invisible
        # to pytest, since its database is built from the model directly, and
        # exactly what crashed a live deployment with "column ... does not exist".
        models_path = repo.workspace_path(rid).joinpath("backend", "app", "models.py")
        good_models = models_path.read_text(encoding="utf-8")
        models_path.write_text(
            good_models.replace(
                'label: Mapped[str] = mapped_column(String(200))',
                'label: Mapped[str] = mapped_column(String(200))\n'
                '    owner_id: Mapped[int] = mapped_column(Integer)',
                1,
            ),
            encoding="utf-8",
        )
        drift = checks.schema_drift_issues(rid)
        show("schema drift", drift)
        expect("a model column missing from init.sql's table is caught",
               any("owner_id" in i and "example" in i for i in drift))
        models_path.write_text(good_models, encoding="utf-8")

        # A deploy failure has no story_id of its own; attribute it to whichever
        # story most recently touched a file that could plausibly break the
        # whole app, so a rework round rebuilds one story instead of the sprint.
        synthetic_state = {"test_report": {"stories": [
            {"story_id": "S1", "status": "green", "files": ["frontend/screens/llm_overview.js"]},
            {"story_id": "S2", "status": "red", "files": ["db/init.sql", "backend/app/models.py"]},
            {"story_id": "S3", "status": "green", "files": ["frontend/screens/other.js"]},
        ]}}
        expect("a deploy failure is attributed to the last story that touched a risky file",
               _attribute_to_last_writer(synthetic_state) == "S2")
        expect("no attribution when nothing touched a shared file",
               _attribute_to_last_writer({"test_report": {"stories": [
                   {"story_id": "S1", "status": "green", "files": ["frontend/screens/x.js"]}]}}) is None)

        # Only a story's OWN, exclusively-owned files are safe to drop outright.
        # Screens name their story in the file; routers don't, so ownership comes
        # from the build's own record of who wrote what.
        owned_state = {"run_id": rid, "test_report": {"stories": [
            {"story_id": "S1", "status": "green", "files": ["backend/app/routers/llm_overview.py"]},
        ]}}
        owned = _sole_owned_files(owned_state, "S1")
        expect("a story's sole-owned router and screen are found",
               "backend/app/routers/llm_overview.py" in owned and "frontend/screens/llm_overview.js" in owned)
        expect("the shared worked example is never treated as sole-owned",
               not any("example" in f for f in owned))

        repo.workspace_path(rid).joinpath("frontend/screens/broken.js").unlink()
        repo.workspace_path(rid).joinpath("frontend/screens/feedback.js").unlink()
        checks.regenerate_registry(rid)
        c = await checks.platform_checks(rid, "S1", True)
        expect("a correct screen passes the checks", c.ok)
        t = await run_in_sandbox(rid, pytest_command(), timeout=600, network=True)
        expect("pytest passes with a story router mounted", t.ok)

        # The build loop's own check, end to end: scoped pytest plus the frontend
        # checks. Exercised here because a NameError inside it once killed a run.
        r, pytest_ok = await _verify(rid, "selftest:a0", 600, "S1", True,
                                     {"frontend/screens/llm_overview.js"}, [])
        expect("the build loop's check passes a correct story", r.ok and pytest_ok)

        repo.write_files(rid, {"backend/app/routers/crashing.py": CRASHING})
        t = await run_in_sandbox(rid, pytest_command(), timeout=600, network=True)
        expect("a GET endpoint no test calls still fails the build when it crashes",
               not t.ok and "UnboundLocalError" in t.stdout and "/api/crashing" in t.stdout)
        repo.workspace_path(rid).joinpath("backend/app/routers/crashing.py").unlink()

        repo.write_files(rid, {"backend/app/routers/unseeded.py": UNSEEDED_ROUTER,
                               "frontend/screens/unseeded.js": UNSEEDED_SCREEN})
        checks.regenerate_registry(rid)
        c = await checks.platform_checks(rid, "S5", True)
        show("checks for a GET on an unseeded table", c.stdout)
        expect("a GET endpoint over an unseeded table is caught",
               not c.ok and "nothing seeds the `example` table" in c.stdout)
        repo.workspace_path(rid).joinpath("backend/app/routers/unseeded.py").unlink()
        repo.workspace_path(rid).joinpath("frontend/screens/unseeded.js").unlink()
        checks.regenerate_registry(rid)

        repo.write_files(rid, {"backend/app/routers/items.py": BARE_ROUTER,
                               "frontend/screens/items.js": ITEMS})
        notes = checks.mount_bare_routers(rid)
        contract = route_contract(rid)
        show("router declared at '/'", "\n".join(notes) + "\n" + contract)
        expect("a router declared at '/' is moved to the path its screen calls",
               bool(notes) and "GET    /api/items " in contract and "/api/items/{item_id}" in contract)
        c = await checks.platform_checks(rid, "S4", True)
        expect("the moved router satisfies its screen's checks", c.ok)

        repo.write_files(rid, {"frontend/screens/model_count.js": BAD_RUNTIME})
        checks.regenerate_registry(rid)
        repo.commit(rid, "stories")
        out = await deployment.deploy(rid)
        show("deploy", out.as_dict())
        expect("the app deploys", out.status == "running")
        if out.status == "running":
            v = await browser_check.verify(rid)
            show("browser check", json.dumps(v, indent=1))
            by_id = {s["id"]: s for s in v.get("screens", [])}
            expect("the browser check fails the app overall", not v.get("ok"))
            expect("the working screen is reported working", by_id.get("llm_overview", {}).get("ok") is True)
            expect("the throwing screen is reported broken", by_id.get("model_count", {}).get("ok") is False)
            expect("the moved router's screen works in the browser", by_id.get("items", {}).get("ok") is True)
    finally:
        subprocess.run(["docker", "compose", "-p", deployment.project_name(rid), "down", "-v",
                        "--remove-orphans"], capture_output=True)
        repo.destroy(rid)
        _forget(rid, "")
        with session() as s:
            for model in (Deployment, Run):
                row = s.get(model, rid)
                if row is not None:
                    s.delete(row)
            s.commit()
        print("\ncleaned up", rid)
    print(f"\n{'ALL PASSED' if not failures else f'{len(failures)} FAILED: ' + '; '.join(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
