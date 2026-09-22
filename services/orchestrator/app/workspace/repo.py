"""Each run owns a git workspace. Commits are the audit trail of the build stage."""
from __future__ import annotations

import shutil
from pathlib import Path

from git import Actor, Repo

from ..config import settings

AUTHOR = Actor("Poiesis Agents", "agents@poiesis.local")

# Written by init_workspace and used by the sandbox preflight to prove the bind
# mount reached the real workspace rather than an empty directory.
SENTINEL = ".poiesis-workspace"

# Build artefacts the sandbox leaves behind. They are not part of the increment,
# and they are expensive: tree() feeds the Developer's file list on a 12k context
# and the Reviewer samples the first 25 entries, so cache files crowd out code.
NOISE_DIRS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
              "node_modules", ".venv", "venv", ".tox", "htmlcov", ".eggs",
              # The platform's own check scripts, results and screenshots.
              ".poiesis"}
NOISE_SUFFIXES = (".pyc", ".pyo", ".coverage", ".egg-info")

GITIGNORE = """__pycache__/
*.py[cod]
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
htmlcov/
.venv/
venv/
*.egg-info/
*.db
*.sqlite
*.sqlite3
.env
.poiesis/
"""


def _is_noise(rel_parts: tuple[str, ...], name: str) -> bool:
    return bool(NOISE_DIRS & set(rel_parts)) or name.endswith(NOISE_SUFFIXES)


def workspace_path(run_id: str) -> Path:
    return Path(settings().poiesis_workspace_root) / run_id


def _resolve(run_id: str, rel: str) -> Path | None:
    """Confine a caller-supplied relative path to the run's workspace."""
    root = workspace_path(run_id).resolve()
    try:
        target = (root / rel.lstrip("/\\")).resolve()
        target.relative_to(root)
    except (ValueError, OSError):
        return None
    return target


def init_workspace(run_id: str) -> Path:
    path = workspace_path(run_id)
    path.mkdir(parents=True, exist_ok=True)
    if not (path / ".git").exists():
        repo = Repo.init(path)
        (path / "README.md").write_text(f"# Poiesis run {run_id}\n", encoding="utf-8")
        (path / SENTINEL).write_text(run_id, encoding="utf-8")
        (path / ".gitignore").write_text(GITIGNORE, encoding="utf-8")
        repo.index.add(["README.md", SENTINEL, ".gitignore"])
        repo.index.commit("chore: initialise workspace", author=AUTHOR, committer=AUTHOR)
    return path


def write_files(run_id: str, files: dict[str, str]) -> list[str]:
    written: list[str] = []
    for rel, content in files.items():
        target = _resolve(run_id, rel)
        if target is None:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        written.append(str(target.relative_to(workspace_path(run_id).resolve())))
    return written


def remove(run_id: str, rel: str) -> bool:
    """Delete one file inside the workspace; the next commit records the deletion."""
    target = _resolve(run_id, rel)
    if target is None or not target.is_file():
        return False
    target.unlink()
    return True


def history(run_id: str, rel: str, limit: int = 12) -> list[str]:
    """Commits that touched `rel`, newest first."""
    repo = Repo(workspace_path(run_id))
    try:
        return [c.hexsha for c in repo.iter_commits(paths=rel, max_count=limit)]
    except Exception:  # noqa: BLE001 — an unborn branch or a path never committed
        return []


def show(run_id: str, sha: str, rel: str) -> str:
    """The content of `rel` at commit `sha`, or "" if it did not exist there."""
    try:
        return Repo(workspace_path(run_id)).git.show(f"{sha}:{rel}")
    except Exception:  # noqa: BLE001
        return ""


def commit(run_id: str, message: str) -> str | None:
    repo = Repo(workspace_path(run_id))
    repo.git.add(A=True)
    if not repo.index.diff("HEAD") and not repo.untracked_files:
        return None
    sha = repo.index.commit(message, author=AUTHOR, committer=AUTHOR).hexsha
    return sha[:10]


def tree(run_id: str, limit: int = 200) -> list[str]:
    root = workspace_path(run_id)
    if not root.exists():
        return []
    out = [
        str(rel)
        for rel in (p.relative_to(root) for p in sorted(root.rglob("*")) if p.is_file())
        if not _is_noise(rel.parts, rel.name) and rel.name != SENTINEL
    ]
    return out[:limit]


def read(run_id: str, rel: str, max_chars: int = 20000) -> str:
    target = _resolve(run_id, rel)
    if target is None or not target.is_file():
        return ""
    return target.read_text(encoding="utf-8", errors="replace")[:max_chars]


def destroy(run_id: str) -> None:
    shutil.rmtree(workspace_path(run_id), ignore_errors=True)
