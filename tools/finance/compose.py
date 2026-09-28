"""Compose an application from the scaffold and the enterprise and finance overlays, to try the
finance library without a run. Written into tools/finance/out/app (ignored by git).

    python tools/finance/compose.py                     the scaffold with both overlays, as a run starts from
    python tools/finance/compose.py --sample            plus the standard entities, the library's starting domain, its
                                                        demonstration data in db/init.sql, a screen per dashboard
                                                        blueprint and per worklist, and the component gallery: an
                                                        application that deploys
    python tools/finance/compose.py --sample --tables=cost_center,supplier,invoice     with only those entities

See tools/finance/README.md for deploying it and driving it in a browser.
"""
import datetime as dt
import importlib.util
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
OUT = HERE / "out" / "app"
CHECKS = REPO / "services" / "orchestrator" / "app" / "selftest_data"
SCAFFOLDS = REPO / "scaffolds"
skip = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache")
TODAY = "2026-09-25"

BOARDS = {
    "executive": ("Executive summary", "dollar", "S1"), "spend": ("Spend analysis", "pie", "S2"),
    "budget": ("Budget control", "chart", "S3"), "payables": ("Accounts payable", "inbox", "S4"),
    "procureToPay": ("Purchase to pay", "cart", "S5"), "suppliers": ("Suppliers", "building", "S6"),
    "controls": ("Controls", "shield", "S7"), "savings": ("Savings", "sparkles", "S8"),
}

BOARD = '''import fin from "../finance.js";

export default {
  title: "%(title)s", icon: "%(icon)s", story: "%(story)s",
  async render(root, ctx) {
    window.__fin = fin;
    window.__board = await fin.dashboard(root, ctx, fin.blueprints.%(name)s({ targets: { po_coverage: 95, first_time_match: 85, on_time_payment: 95 } }));
  },
};
'''


WORK = {
    "requisitions": ("My requests", "inbox", "S9"), "approvals": ("Approval queue", "shield", "S10"),
    "ordering": ("Ordering", "cart", "S11"), "receiving": ("Goods in", "truck", "S12"),
    "invoices": ("Invoice desk", "layers", "S13"), "paymentRuns": ("Payment runs", "dollar", "S14"),
    "suppliers": ("Supplier list", "building", "S15"), "contracts": ("Contracts", "file", "S16"),
}

# The story each work screen is written for. The screen is the one the library gives the platform
# for that story (finance/screens.py), so what is driven in a browser here is what a run is handed.
STORIES = {
    "requisitions": "Raise a purchase requisition and see the budget and who approves it",
    "approvals": "Approve or reject what waits in my queue",
    "ordering": "Create purchase orders from approved requisitions and send to supplier",
    "receiving": "Confirm receipt of goods against a purchase order",
    "invoices": "Three-way match of supplier invoices",
    "paymentRuns": "Propose the weekly payment run",
    "suppliers": "Supplier onboarding and the approved supplier list",
    "contracts": "Contract renewals to decide on",
}


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def sql_value(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return repr(value)
    return "'" + str(value).replace("'", "''") + "'"


def main() -> None:
    sample = "--sample" in sys.argv
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SCAFFOLDS / "web-app", OUT, ignore=skip)
    for overlay in ("enterprise", "finance"):
        root = SCAFFOLDS / "_overlays" / overlay
        for part in ("backend", "frontend", "tests"):
            if (root / part).exists():
                shutil.copytree(root / part, OUT / part, dirs_exist_ok=True, ignore=skip)
    for path in [p for p in OUT.rglob("*") if p.is_file() and p.suffix in (".py", ".js", ".html", ".css", ".yml", ".sql", ".md")]:
        text = path.read_text(encoding="utf-8")
        if "{{project_" in text:
            path.write_text(text.replace("{{project_name}}", "Finance Test").replace("{{project_slug}}", "fintest"),
                            encoding="utf-8", newline="\n")
    if sample:
        sys.path.insert(0, str(OUT / "backend/app/finance"))
        standard = load(OUT / "backend/app/finance/standard.py", "standard")
        demo = load(OUT / "backend/app/finance/demo.py", "demo")
        models = OUT / "backend/app/models.py"
        text = models.read_text(encoding="utf-8")
        text = text.replace("from sqlalchemy import DateTime, Float, Integer, String",
                            "from sqlalchemy import Boolean, Date, DateTime, Float, Integer, String, Text")
        text += "\n\ndef _now() -> dt.datetime:\n    return dt.datetime.now(dt.timezone.utc)\n"
        only = [a.split("=", 1)[1].split(",") for a in sys.argv if a.startswith("--tables=")]
        order = [t for t in standard.ORDER if not only or t in only[0]]
        for table in order:
            text += "\n\n" + standard.model_class(table) + "\n"
        models.write_text(text, encoding="utf-8", newline="\n")
        load(OUT / "backend/app/finance/personas.py", "personas")
        starter = load(OUT / "backend/app/finance/starter.py", "starter")
        tables = {t: ["id"] + [c[0] for c in standard.ENTITIES[t]["columns"]] for t in order}
        for rel, body in starter.domain(tables, {t: standard.class_name(t) for t in order}).items():
            (OUT / rel).write_text(body, encoding="utf-8", newline="\n")

        rows = demo.rows(tables, today=TODAY)
        sql = (OUT / "db/init.sql").read_text(encoding="utf-8")
        sql += "\n" + "\n\n".join(standard.create_table(t) for t in order) + "\n\n-- demonstration data\n"
        for table in order:
            data = rows[table]
            columns = list(dict.fromkeys(k for r in data for k in r))
            for start in range(0, len(data), 50):
                values = ",\n".join("  (" + ", ".join(sql_value(r.get(c)) for c in columns) + ")" for r in data[start:start + 50])
                sql += f"INSERT INTO {table} ({', '.join(columns)}) VALUES\n{values};\n"
        (OUT / "db/init.sql").write_text(sql, encoding="utf-8", newline="\n")
        (OUT.parent / "demo_rows.json").write_text(json.dumps(rows), encoding="utf-8")

        screens = OUT / "frontend/screens"
        entries = []
        for name, (title, icon, story) in BOARDS.items():
            (screens / f"{name.lower()}.js").write_text(BOARD % {"name": name, "title": title, "icon": icon, "story": story},
                                                        encoding="utf-8", newline="\n")
            entries.append(name.lower())
        library = load(OUT / "backend/app/finance/screens.py", "screens")
        for name, (title, icon, story) in WORK.items():
            found = library.suggest({"id": story, "title": STORIES[name]}, order)
            if found is None or (found["kind"], found["name"]) != ("worklist", name):
                raise SystemExit(f"the library gives {found and found['name']} for the story of {name}: {STORIES[name]}")
            body = library.content("worklist", name, {"id": story}, title=title, icon=icon, options=found["options"])
            (screens / f"work_{name.lower()}.js").write_text(body, encoding="utf-8", newline="\n")
            entries.append(f"work_{name.lower()}")
        for extra in HERE.glob("screen_*.js"):
            shutil.copy(extra, screens / extra.name[len("screen_"):])
            entries.append(extra.stem[len("screen_"):])
        entries.extend(["example_finance", "example_worklist"])
        (screens / "index.js").write_text(
            "const entries = [\n" + "".join(f'  {{ id: "{e}", example: false, load: () => import("./{e}.js") }},\n' for e in entries)
            + "];\n\nexport default await Promise.all(entries.map(async (e) => {\n  try {\n"
              "    return { id: e.id, example: e.example, module: (await e.load()).default };\n  } catch (err) {\n"
              "    return { id: e.id, example: e.example, module: null, error: String((err && err.message) || err) };\n  }\n}));\n",
            encoding="utf-8", newline="\n")
        (OUT / "app.env").write_text(f"APP_SECRET=fintest-secret-not-for-production-0123456789\nPOIESIS_SERVICE_TOKEN=fintest-token\n"
                                     f"FINANCE_AS_OF={TODAY}\n", encoding="utf-8", newline="\n")
    for extra in CHECKS.glob("finance_*_check.py"):
        shutil.copy(extra, OUT / extra.name)
    print("composed", OUT, sum(1 for _ in OUT.rglob("*.py")), "python files", dt.datetime.now().strftime("%H:%M:%S"))


main()
