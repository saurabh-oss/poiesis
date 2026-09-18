"""Portfolio indexer.

Clones (or refreshes) every repo listed in portfolio.yaml, walks it with tree-sitter,
and writes a graph of Projects → Components → Capabilities → Technologies.

The component-level detail is what makes the reuse check useful. Telling the
architect "TestLoom exists" is nearly worthless; telling it
"TestLoom.generators.gherkin.from_requirement(req) -> list[Scenario]" is actionable.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import typer
import yaml
from git import Repo
from neo4j import GraphDatabase
from rich.console import Console
from rich.progress import track

console = Console()
app = typer.Typer(add_completion=False)

LANGS = {
    ".py": "python", ".js": "javascript", ".ts": "typescript", ".tsx": "tsx",
    ".java": "java", ".go": "go", ".rs": "rust",
}

QUERIES = {
    "python": """
        (function_definition name: (identifier) @name) @node
        (class_definition name: (identifier) @name) @node
    """,
    "javascript": """
        (function_declaration name: (identifier) @name) @node
        (class_declaration name: (identifier) @name) @node
    """,
    "typescript": """
        (function_declaration name: (identifier) @name) @node
        (class_declaration name: (type_identifier) @name) @node
        (interface_declaration name: (type_identifier) @name) @node
    """,
    "java": """
        (class_declaration name: (identifier) @name) @node
        (method_declaration name: (identifier) @name) @node
        (interface_declaration name: (identifier) @name) @node
    """,
    "go": """
        (function_declaration name: (identifier) @name) @node
        (type_declaration (type_spec name: (type_identifier) @name)) @node
    """,
    "rust": """
        (function_item name: (identifier) @name) @node
        (struct_item name: (type_identifier) @name) @node
    """,
}

SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "dist", "build", "target",
             "__pycache__", ".next", "vendor", "site-packages"}

# Test code is excluded from the portfolio graph on purpose. A reuse candidate is
# something the Architect can call; a test method named testResultParser_validJson
# matches every query about parsing or results and crowds out the module it covers.
SKIP_TEST_DIRS = {"test", "tests", "testing", "__tests__", "spec", "specs", "e2e"}


def is_test_file(root: Path, file: Path) -> bool:
    parts = {p.lower() for p in file.relative_to(root).parts[:-1]}
    if parts & SKIP_TEST_DIRS:
        return True
    stem = file.stem.lower()
    return (
        stem.startswith("test_")
        or stem.endswith(("_test", "_tests", "_spec"))
        or stem.endswith((".test", ".spec"))
        or stem in {"conftest", "setup"}
    )


@dataclass
class Component:
    project: str
    name: str
    kind: str
    path: str
    line: int
    signature: str
    purpose: str

    @property
    def id(self) -> str:
        return f"{self.project}:{self.path}:{self.name}"


def parse_file(project: str, root: Path, file: Path) -> list[Component]:
    from tree_sitter_language_pack import get_language, get_parser

    lang_name = LANGS.get(file.suffix.lower())
    if lang_name is None or lang_name not in QUERIES:
        return []
    try:
        source = file.read_bytes()
        parser = get_parser(lang_name)
        tree = parser.parse(source)
        query = get_language(lang_name).query(QUERIES[lang_name])
        captures = query.captures(tree.root_node)
    except Exception:
        return []

    names = captures.get("name", [])
    nodes = captures.get("node", [])
    out: list[Component] = []
    for name_node, node in zip(names, nodes):
        text = source[node.start_byte : node.end_byte].decode("utf-8", "replace")
        signature = text.splitlines()[0].strip()[:240]
        purpose = _docstring(text)
        out.append(Component(
            project=project,
            name=source[name_node.start_byte : name_node.end_byte].decode("utf-8", "replace"),
            kind=node.type.replace("_definition", "").replace("_declaration", ""),
            path=str(file.relative_to(root)),
            line=node.start_point[0] + 1,
            signature=signature,
            purpose=purpose,
        ))
    return out


def _docstring(text: str) -> str:
    for marker in ('"""', "'''"):
        if marker in text:
            after = text.split(marker, 2)
            if len(after) >= 3:
                return " ".join(after[1].split())[:300]
    lines = [l.strip(" /*#") for l in text.splitlines()[:6] if l.strip().startswith(("//", "#", "*"))]
    return " ".join(lines)[:300]


def walk(project: str, root: Path) -> list[Component]:
    comps: list[Component] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in LANGS:
            continue
        if SKIP_DIRS & set(path.parts) or is_test_file(root, path):
            continue
        comps.extend(parse_file(project, root, path))
    return comps


def _reason(exc: Exception) -> str:
    """Pull the useful line out of a GitPython error.

    Its str() is a multi-line dump of the command it ran, and the last line is
    usually just a stray quote — so surface git's own message instead.
    """
    lines = [l.strip().strip("'\"") for l in str(exc).splitlines()]
    for line in lines:
        low = line.lower()
        if low.startswith(("fatal:", "error:", "remote:")) or "not found" in low:
            return line[:200]
    meaningful = [l for l in lines if l]
    return (meaningful[0] if meaningful else repr(exc))[:200]


def ensure_repo(entry: dict, clone_root: Path, failures: list[str]) -> Path | None:
    """Resolve one portfolio entry to a directory on disk.

    An entry may carry `path:` (a directory mounted into this container) instead of
    `repo:`, so projects that are not on GitHub yet can be indexed in the same pass.
    """
    if entry.get("path"):
        local = Path(entry["path"])
        if not local.is_dir():
            failures.append(f"{entry['name']}: path '{local}' is not mounted in the indexer")
            return None
        console.print(f"  reading [cyan]{entry['name']}[/] from {local}")
        return local

    if not entry.get("repo"):
        failures.append(f"{entry['name']}: entry has neither 'repo' nor 'path'")
        return None

    target = clone_root / entry["name"].lower().replace(" ", "-")
    try:
        if target.exists():
            console.print(f"  refreshing [cyan]{entry['name']}[/]")
            Repo(target).remotes.origin.pull()
        else:
            console.print(f"  cloning [cyan]{entry['name']}[/]")
            Repo.clone_from(entry["repo"], target, depth=1)
        return target
    except Exception as exc:
        if target.exists():
            console.print(f"  [yellow]{entry['name']}: using the existing clone ({exc})[/]")
            return target
        failures.append(f"{entry['name']}: {_reason(exc)}")
        return None


def write(driver, entry: dict, components: list[Component]) -> None:
    with driver.session() as s:
        s.run(
            "MERGE (p:Project {name:$name}) "
            "SET p.repo_url=$repo, p.kind='portfolio', p.indexed_at=timestamp()",
            name=entry["name"], repo=entry["repo"],
        )
        for cap in entry.get("capabilities", []):
            s.run(
                "MERGE (c:Capability {name:$cap}) "
                "WITH c MATCH (p:Project {name:$name}) MERGE (p)-[:PROVIDES]->(c)",
                cap=cap, name=entry["name"],
            )
        for tech in entry.get("technologies", []):
            s.run(
                "MERGE (t:Technology {name:$tech}) SET t.category=coalesce(t.category,'unknown') "
                "WITH t MATCH (p:Project {name:$name}) MERGE (p)-[:USES]->(t)",
                tech=tech, name=entry["name"],
            )
        # Re-indexing is authoritative: drop components that no longer exist (or are
        # no longer eligible) so a deleted function stops being offered for reuse.
        s.run(
            """
            MATCH (p:Project {name:$name})-[:CONTAINS]->(c:Component)
            WHERE NOT c.id IN $keep
            DETACH DELETE c
            """,
            name=entry["name"], keep=[c.id for c in components],
        )
        batch = [c.__dict__ | {"id": c.id} for c in components]
        for i in range(0, len(batch), 500):
            s.run(
                """
                UNWIND $rows AS row
                MERGE (c:Component {id: row.id})
                SET c.name=row.name, c.kind=row.kind, c.path=row.path,
                    c.line=row.line, c.signature=row.signature, c.purpose=row.purpose
                WITH c, row
                MATCH (p:Project {name: row.project})
                MERGE (p)-[:CONTAINS]->(c)
                """,
                rows=batch[i : i + 500],
            )
        # Attach components to the capabilities their project provides, so a
        # capability query returns concrete entry points rather than repo names.
        s.run(
            """
            MATCH (p:Project {name:$name})-[:PROVIDES]->(cap:Capability)
            MATCH (p)-[:CONTAINS]->(c:Component)
            WHERE any(w IN split(toLower(cap.name),' ')
                      WHERE size(w) > 3 AND toLower(c.name+' '+coalesce(c.purpose,'')) CONTAINS w)
            MERGE (c)-[:IMPLEMENTS]->(cap)
            """,
            name=entry["name"],
        )


@app.command()
def main(
    config: Path = typer.Option("portfolio.yaml"),
    uri: str = typer.Option(os.getenv("NEO4J_URI", "bolt://localhost:7687")),
    user: str = typer.Option(os.getenv("NEO4J_USER", "neo4j")),
    password: str = typer.Option(os.getenv("NEO4J_PASSWORD", "poiesisdev")),
    local: Path = typer.Option(None, help="Index a local directory instead of cloning"),
    name: str = typer.Option(None, help="Project name when using --local"),
):
    cfg = yaml.safe_load(config.read_text())
    clone_root = Path(cfg.get("clone_root", "/repos"))
    clone_root.mkdir(parents=True, exist_ok=True)
    driver = GraphDatabase.driver(uri, auth=(user, password))

    entries = cfg["projects"]
    if local:
        entries = [{"name": name or local.name, "repo": f"file://{local}",
                    "capabilities": [], "technologies": []}]

    total = 0
    indexed = 0
    failures: list[str] = []
    empty: list[str] = []
    for entry in entries:
        root = Path(local) if local else ensure_repo(entry, clone_root, failures)
        if root is None:
            continue
        components = walk(entry["name"], root)
        write(driver, entry, components)
        total += len(components)
        indexed += 1
        if components:
            console.print(f"  [green]{entry['name']}: {len(components)} components indexed[/]")
        else:
            empty.append(entry["name"])
            console.print(f"  [yellow]{entry['name']}: 0 components - no parseable source found[/]")

    driver.close()

    console.print(f"\n[bold]{total} components across {indexed}/{len(entries)} projects.[/]")

    # An empty graph is the failure mode that matters: the Architect silently loses
    # its reuse check and returns 'build_new' for everything. Say so loudly.
    if failures:
        console.print("\n[bold red]Could not read these projects:[/]")
        for f in failures:
            console.print(f"  [red]- {f}[/]")
        console.print(
            "\n[yellow]Fix the 'repo' URLs in portfolio.yaml, or give an entry a 'path:'\n"
            "pointing at a directory mounted into the indexer container.[/]"
        )
    if empty:
        console.print(f"\n[yellow]No source parsed for: {', '.join(empty)}[/]")

    if total == 0:
        console.print(
            "\n[bold red]The knowledge graph has no components. Enforced reuse is the\n"
            "point of this platform; until this succeeds every architecture verdict\n"
            "will be 'build new'.[/]"
        )
        raise typer.Exit(code=1)
    if failures:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
