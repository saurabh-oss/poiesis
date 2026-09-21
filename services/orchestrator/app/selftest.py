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
from .workspace.interface import excerpt, import_contract, route_contract
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

# The failure that passed every check and shipped: fetches its data, renders an
# empty state anyway. Nothing throws, the shell is fine, there is plenty of text.
HOLLOW = '''export default {
  title: "Hollow",
  story: "S4",
  async render(root, { api, h }) {
    const rows = await api("/items");
    const body = h("tbody", {});
    root.append(h("section", { class: "panel stack" },
      h("h2", {}, "Everything we hold"),
      h("div", { class: "table-wrap" }, h("table", {}, body)),
      h("div", { class: "empty-state" },
        h("strong", {}, "Nothing to show yet"),
        "Records will appear here once they have been added to the system.")));
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

# A screen that renders, throws nothing, passes the browser check — and shows the
# user an empty table over an API that has three rows in it. Taken verbatim in
# shape from run 17c61ded260a4fed, where every other check called it working.
CLICK_ONLY_SCREEN = '''export default {
  title: "Staff directory",
  story: "S6",
  async render(root, { api, h }) {
    const search = h("input", { type: "text", class: "field" });
    const table = h("table", { class: "table-wrap" }, h("tbody", {}));
    const empty = h("div", { class: "empty-state" }, h("strong", {}, "No staff found"));

    async function load() {
      const rows = await api("/staff", { search: search.value });
      table.querySelector("tbody").innerHTML = "";
      rows.forEach((r) => table.querySelector("tbody").append(h("tr", {}, h("td", {}, r.name))));
      empty.hidden = rows.length > 0;
    }

    root.append(search, h("button", { onclick: () => load() }, "Search"), table, empty);
  },
};
'''

# The five Python mistakes that accounted for about half of every red story.
BAD_BACKEND = '''from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from backend.app.db import get_session
from ..models import Example
from .. import db


router = APIRouter()


def get_db():
    db = db.get_session()
    try:
        yield db
    finally:
        db.close()


@router.get("/broken-things", response_model=Example)
def list_things(session: Session = Depends(get_db)):
    return session.query(Example).all()
'''

# Tests that cannot pass however correct the implementation is.
IMPOSSIBLE_TESTS = '''def test_posts_to_a_get_only_path(client):
    response = client.post("/api/llm-overview", json={})
    assert response.status_code == 422


def test_expects_rows_in_an_empty_database(client):
    body = client.get("/api/llm-overview").json()
    assert len(body) > 0


def test_asserts_markup(client):
    body = client.get("/api/llm-overview").json()
    assert "<a href=\\'#next\\'>Next</a>" in body["content"]


def test_asserts_a_button_label(client):
    body = client.get("/api/llm-overview").json()
    assert "Learn More" in body["content"]
'''

# Correct, idiomatic SQLAlchemy that an earlier version of the shadowing check
# flagged: `query = query.filter(...)` is the same shape as the bug, and only
# differs in whether the name already holds a value. A check that sends the
# Developer to "fix" this is worse than no check at all.
GOOD_BACKEND = '''from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Example
from ..schemas import ExampleOut

router = APIRouter()


@router.get("/staff", response_model=list[ExampleOut])
def list_staff(team: str | None = None, db: Session = Depends(get_session)):
    query = db.query(Example)
    if team:
        query = query.filter(Example.label == team)
    return query.order_by(Example.id).all()
'''

SOUND_TESTS = '''def test_lists_overviews(client):
    response = client.get("/api/llm-overview")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
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

        # The Developer's five recurring Python mistakes, caught by AST before
        # pytest ever runs — each one used to cost a whole repair round.
        repo.write_files(rid, {"backend/app/routers/broken_backend.py": BAD_BACKEND})
        backend = checks.backend_issues(rid, {"backend/app/routers/broken_backend.py"})
        show("backend mistakes", "\n".join(backend))
        expect("`from backend...` is caught", any("does not exist at runtime" in i for i in backend))
        expect("a helper shadowing its own module is caught",
               any("UnboundLocalError" in i for i in backend))
        expect("a SQLAlchemy model used as response_model is caught",
               any("response_model=Example" in i for i in backend))
        expect("another story's backend file is not reported to this one",
               checks.backend_issues(rid, {"backend/app/routers/somebody_else.py"}) == [])
        repo.workspace_path(rid).joinpath("backend/app/routers/broken_backend.py").unlink()

        repo.write_files(rid, {"backend/app/routers/good_backend.py": GOOD_BACKEND})
        clean = checks.backend_issues(rid, {"backend/app/routers/good_backend.py"})
        show("correct SQLAlchemy", "\n".join(clean) or "(no findings)")
        expect("building a query incrementally is not mistaken for shadowing", clean == [])
        repo.workspace_path(rid).joinpath("backend/app/routers/good_backend.py").unlink()

        # Tests that no implementation could satisfy. The Developer may not edit
        # tests, so these used to deadlock a story into a permanent red.
        repo.write_files(rid, {"tests/test_impossible.py": IMPOSSIBLE_TESTS,
                               "tests/test_sound.py": SOUND_TESTS})
        bad = checks.test_issues(rid, ["tests/test_impossible.py"])
        show("impossible tests", "\n".join(bad))
        expect("a POST to a GET-only path is caught", any("only GET" in i for i in bad))
        expect("expecting rows in an empty database is caught",
               any("never creates the data" in i for i in bad))
        expect("markup asserted in an API response is caught", any("asserts HTML" in i for i in bad))
        expect("a button label asserted in a payload is caught",
               any("Learn More" in i and "label" in i for i in bad))
        expect("a sound test file is left alone", checks.test_issues(rid, ["tests/test_sound.py"]) == [])
        for name in ("tests/test_impossible.py", "tests/test_sound.py"):
            repo.workspace_path(rid).joinpath(name).unlink()

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

        repo.write_files(rid, {"frontend/screens/staff.js": CLICK_ONLY_SCREEN})
        checks.regenerate_registry(rid)
        c = await checks.platform_checks(rid, "S6", True)
        show("checks for a screen that only loads on click", c.stdout)
        expect("a screen that never loads in render() is caught",
               not c.ok and "never loads anything" in c.stdout)
        expect("query parameters passed as request options are caught",
               "silently drops search" in c.stdout)
        expect("the wrapper classes are caught on the elements they wrap",
               'class "table-wrap" on the <table>' in c.stdout
               and 'class "field" on the <input>' in c.stdout)
        repo.workspace_path(rid).joinpath("frontend/screens/staff.js").unlink()
        checks.regenerate_registry(rid)

        example = scaffold_root() / "web-app" / "frontend" / "screens" / "example.js"
        expect("the scaffold's own example screen breaks none of those rules",
               checks._screen_shell_issues("example.js", example.read_text(encoding="utf-8")) == [])

        # A later story rewriting init.sql keeps the tables and drops the rows: the
        # app still deploys, every screen still opens, and the demonstration data
        # the stakeholder asked for is gone with nothing going red.
        # One INSERT with a tuple per line, under a comment: the shape a model
        # actually writes, and the shape that defeated the first version of this.
        schema = "CREATE TABLE crews (id SERIAL PRIMARY KEY, name TEXT);\n"
        seeded = schema + (
            "-- Seed data: 4 crews; every one of them named\n"
            "INSERT INTO crews (name) VALUES\n"
            "    ('Blue'),\n"
            "    ('Red; the second one'),\n"
            "    ('Green'),\n"
            "    ('Gold');\n")
        repo.write_files(rid, {"db/init.sql": seeded})
        expect("a seed block under a comment is still found, and counted by row",
               checks._seed_rows(checks._inserts_by_table(seeded)["crews"]) == 4)

        kept, notes = checks.preserve_shared(rid, {"db/init.sql": schema})
        show("init.sql after a rewrite that dropped every seed row", kept["db/init.sql"])
        expect("seed rows dropped wholesale are put back",
               "'Gold'" in kept["db/init.sql"]
               and any("4 seed row(s) for crews" in n for n in notes))
        expect("a semicolon inside a seeded string does not split the statement",
               "'Red; the second one'" in kept["db/init.sql"])

        kept, notes = checks.preserve_shared(rid, {"db/init.sql": schema + (
            "INSERT INTO crews (name) VALUES\n    ('Blue');\n")})
        expect("seed rows the story rewrote are left alone, and reported by row count",
               kept["db/init.sql"].count("('Gold')") == 0
               and any("thinned the seed data for crews (1 left of 4)" in n for n in notes))

        # Why the rows kept being dropped in the first place: the Developer was shown
        # init.sql clipped to 900 characters and told to return it complete.
        repo.write_files(rid, {"db/init.sql": seeded})

        block = excerpt(rid, [("db/init.sql", 900)])
        show("what the Developer is shown of a seeded init.sql", block)
        expect("the Developer sees every table definition",
               "CREATE TABLE crews" in block)
        expect("the Developer is shown no seed rows to copy",
               "('Gold')" not in block and "('Blue')" not in block)
        expect("and is told the rows are held for it",
               "4 in crews" in block and "must NOT reproduce them" in block)

        repo.write_files(rid, {"backend/app/routers/items.py": BARE_ROUTER,
                               "frontend/screens/items.js": ITEMS})
        notes = checks.mount_bare_routers(rid)
        contract = route_contract(rid)
        show("router declared at '/'", "\n".join(notes) + "\n" + contract)
        expect("a router declared at '/' is moved to the path its screen calls",
               bool(notes) and "GET    /api/items " in contract and "/api/items/{item_id}" in contract)
        c = await checks.platform_checks(rid, "S4", True)
        expect("the moved router satisfies its screen's checks", c.ok)

        repo.write_files(rid, {"frontend/screens/model_count.js": BAD_RUNTIME,
                               "frontend/screens/hollow.js": HOLLOW})
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
            hollow = by_id.get("hollow", {})
            show("the hollow screen's verdict", json.dumps(hollow, indent=1))
            expect("a screen that fetches its data and shows an empty state is reported broken",
                   hollow.get("ok") is False
                   and any("fetched and then not displayed" in p for p in hollow.get("problems", [])))
            expect("the working screen's fetches are recorded for the Reviewer",
                   any(f.get("count") == 2 for f in by_id.get("items", {}).get("fetched", [])))
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
