"""Push every run's workspace to a Git remote as the build goes.

Each run already has a git repository with a commit per story, repair and
release. This module gives that history a home outside the laptop:

    scaffold laid down   -> the remote exists (created on GitHub if it does not),
                            branch run/<id> pushed
    every story result   -> run/<id> pushed (the commits so far)
    release              -> tag v<version> pushed; on GitHub a pull request from
                            run/<id> to the default branch carries the release
                            notes, or, for a brand-new empty repository, the
                            default branch is created from the release itself

Two rules, the same as Jira's: it never stops a run (a push that fails is a
warning in the log), and it never duplicates (repository creation and the pull
request are memoised per run and checked against the remote first).

Configuration (all in .env, see .env.example):

    GIT_REMOTE_TEMPLATE  https://github.com/acme/poiesis-{slug}.git
                         {slug} is the product name; {run_id} and {short} are
                         also available, so one repo per run is a template away.
    GIT_TOKEN            a token with push rights (and repo creation on GitHub)
    GITHUB_OWNER         set to create missing repositories under this user or org

    python -m app.integrations.gitremote push <run_id>     # push a run by hand
"""
from __future__ import annotations

import asyncio
import base64
import os
import re
import sys
from typing import Any, Awaitable, Callable
from urllib.parse import urlsplit, urlunsplit

import httpx

from .. import telemetry
from ..config import settings
from ..db import NodeCache, session
from ..events import emit
from ..graph.memo import remember
from ..workspace.repo import workspace_path

# Tests swap in a fake GitHub here.
_transport: httpx.AsyncBaseTransport | None = None


def use_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    global _transport
    _transport = transport


def configured() -> bool:
    return bool(settings().git_remote_template.strip())


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug[:60] or "poiesis-app"


def remote_url(run_id: str, state: dict[str, Any]) -> str:
    product = (state.get("vision") or {}).get("product_name") or state.get("title") or run_id
    return settings().git_remote_template.strip().format(
        slug=_slug(product), run_id=run_id, short=run_id[:8])


def branch_for(run_id: str) -> str:
    return f"run/{run_id[:12]}"


def web_url(url: str) -> str:
    """A link a person can open, from either transport's URL."""
    m = re.match(r"^(?:ssh://)?git@([^:/]+)[:/](.+?)(?:\.git)?$", url)
    if m:
        return f"https://{m.group(1)}/{m.group(2)}"
    parts = urlsplit(url)
    if parts.scheme in ("http", "https"):
        host = parts.hostname or ""
        path = re.sub(r"\.git$", "", parts.path)
        return urlunsplit((parts.scheme, host, path, "", ""))
    return url


def _authed(url: str) -> str:
    """The push URL with the token in it. Never written to .git/config."""
    s = settings()
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not s.git_token:
        return url
    user = s.git_username or "x-access-token"
    host = parts.hostname or ""
    if parts.port:
        host += f":{parts.port}"
    return urlunsplit((parts.scheme, f"{user}:{s.git_token}@{host}", parts.path, "", ""))


def _redact(text: str) -> str:
    token = settings().git_token
    return text.replace(token, "***") if token else text


async def _git(run_id: str, *args: str, timeout: int = 180) -> tuple[int, str]:
    root = workspace_path(run_id)
    proc = await asyncio.create_subprocess_exec(
        "git", "-C", str(root), *args,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return -1, f"git {args[0]} timed out after {timeout}s"
    return proc.returncode or 0, _redact(out.decode(errors="replace"))


# ---- GitHub ------------------------------------------------------------------------

def _github_repo(url: str) -> tuple[str, str] | None:
    """(owner, name) when the remote is on github.com, else None."""
    m = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?/?$", url)
    return (m.group(1), m.group(2)) if m else None


class GitHub:
    def __init__(self) -> None:
        s = settings()
        self._client = httpx.AsyncClient(
            base_url=s.github_api.rstrip("/"), transport=_transport, timeout=30,
            headers={"Authorization": f"Bearer {s.git_token}",
                     "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "poiesis"},
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def repo(self, owner: str, name: str) -> dict[str, Any] | None:
        r = await self._client.get(f"/repos/{owner}/{name}")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    async def create(self, owner: str, name: str, description: str) -> dict[str, Any]:
        s = settings()
        body = {"name": name, "description": description[:350], "private": s.github_private,
                "auto_init": False}
        me = await self._client.get("/user")
        login = me.json().get("login", "") if me.status_code == 200 else ""
        path = "/user/repos" if login.lower() == owner.lower() else f"/orgs/{owner}/repos"
        r = await self._client.post(path, json=body)
        if r.status_code == 422 and "already exists" in r.text:
            existing = await self.repo(owner, name)
            if existing:
                return existing
        r.raise_for_status()
        return r.json()

    async def branch_exists(self, owner: str, name: str, branch: str) -> bool:
        r = await self._client.get(f"/repos/{owner}/{name}/branches/{branch}")
        return r.status_code == 200

    async def find_pull(self, owner: str, name: str, head: str) -> dict[str, Any] | None:
        r = await self._client.get(f"/repos/{owner}/{name}/pulls",
                                   params={"head": f"{owner}:{head}", "state": "all"})
        r.raise_for_status()
        pulls = r.json()
        return pulls[0] if pulls else None

    async def open_pull(self, owner: str, name: str, head: str, base: str,
                        title: str, body: str) -> dict[str, Any]:
        r = await self._client.post(f"/repos/{owner}/{name}/pulls",
                                    json={"title": title[:250], "head": head, "base": base,
                                          "body": body[:60000]})
        r.raise_for_status()
        return r.json()


# ---- the hooks ---------------------------------------------------------------------

async def _safely(run_id: str, stage: str, what: str,
                  work: Callable[[], Awaitable[Any]]) -> Any:
    if not configured():
        return None
    try:
        async with telemetry.span("git", what):
            return await work()
    except Exception as exc:  # noqa: BLE001 — a mirror must never take the run down
        await emit(run_id, f"Git push skipped ({what}): {_redact(str(exc))[:400]}",
                   agent="tracker", stage=stage, level="warn")
        return None


def _known(run_id: str, key: str) -> dict | None:
    with session() as s:
        row = s.get(NodeCache, (run_id, f"git:{key}"))
        return None if row is None else (row.value or {}).get("__value__")


async def _ensure_remote(run_id: str, state: dict[str, Any]) -> dict[str, Any]:
    """The remote for this run: created on GitHub if it does not exist. Memoised."""
    async def produce() -> dict[str, Any]:
        url = remote_url(run_id, state)
        record: dict[str, Any] = {"url": url, "web_url": web_url(url), "branch": branch_for(run_id),
                                  "created": False, "github": False, "empty": False}
        gh = _github_repo(url)
        s = settings()
        if gh and s.git_token and s.github_owner:
            owner, name = gh
            api = GitHub()
            try:
                existing = await api.repo(owner, name)
                if existing is None:
                    product = (state.get("vision") or {}).get("product_name") or state.get("title") or ""
                    vision = (state.get("vision") or {}).get("value_proposition") or ""
                    created = await api.create(owner, name, f"{product}: {vision}".strip(": "))
                    record.update(created=True, empty=True,
                                  web_url=created.get("html_url") or record["web_url"])
                else:
                    record.update(web_url=existing.get("html_url") or record["web_url"],
                                  empty=bool(existing.get("size") == 0 and not existing.get("default_branch_exists", True)))
                    record["default_branch"] = existing.get("default_branch") or s.git_default_branch
                record["github"] = True
            finally:
                await api.close()
        code, out = await _git(run_id, "remote", "get-url", "origin")
        if code != 0:
            await _git(run_id, "remote", "add", "origin", url)
        elif out.strip() != url:
            await _git(run_id, "remote", "set-url", "origin", url)
        return record
    return await remember(run_id, "git:remote", produce)


async def _push(run_id: str, refspec: str, *extra: str) -> str:
    url = _authed(_known(run_id, "remote")["url"]) if _known(run_id, "remote") else None
    if not url:
        raise RuntimeError("no remote recorded for this run")
    code, out = await _git(run_id, "push", *extra, url, refspec)
    if code != 0:
        raise RuntimeError(out.strip()[-600:] or f"git push exited {code}")
    return out


async def on_workspace_ready(run_id: str, state: dict[str, Any]) -> None:
    """After the scaffold: the remote exists and holds the skeleton."""
    async def work() -> None:
        record = await _ensure_remote(run_id, state)
        await _push(run_id, f"HEAD:refs/heads/{record['branch']}")
        await emit(run_id, f"Workspace pushed to {record['web_url']} on branch {record['branch']}"
                           + (" (repository created)" if record.get("created") else ""),
                   agent="tracker", stage="scaffold", data=record)
    await _safely(run_id, "scaffold", "initial push", work)


async def on_story_result(run_id: str, state: dict[str, Any], result: dict[str, Any]) -> None:
    """After each story: everything committed so far is on the remote."""
    if not settings().git_push_each_story:
        return
    async def work() -> None:
        record = await _ensure_remote(run_id, state)
        await _push(run_id, f"HEAD:refs/heads/{record['branch']}")
        await emit(run_id, f"{result.get('story_id')}: pushed to {record['branch']}",
                   agent="tracker", stage="build")
    await _safely(run_id, "build", f"push after {result.get('story_id')}", work)


async def on_release(run_id: str, state: dict[str, Any], notes: dict[str, Any]) -> None:
    """At release: the final push, a tag, and a pull request or the default branch."""
    if notes.get("status") not in ("released", None) and "version" not in notes:
        return  # held or sent back: nothing to tag
    async def work() -> None:
        s = settings()
        record = await _ensure_remote(run_id, state)
        await _push(run_id, f"HEAD:refs/heads/{record['branch']}")
        version = str(notes.get("version") or "0.1.0")
        tag = f"v{version}-{run_id[:8]}"
        code, _ = await _git(run_id, "tag", "-f", tag)
        if code == 0:
            await _push(run_id, f"refs/tags/{tag}", "-f")
        outcome: dict[str, Any] = {"tag": tag, "branch": record["branch"], "web_url": record["web_url"]}

        base = record.get("default_branch") or s.git_default_branch
        gh = _github_repo(record["url"])
        if gh and record.get("github") and s.git_token:
            owner, name = gh
            api = GitHub()
            try:
                if not await api.branch_exists(owner, name, base):
                    # A repository created for this run has no default branch yet:
                    # the first release is the default branch.
                    await _push(run_id, f"HEAD:refs/heads/{base}")
                    outcome["default_branch"] = base
                elif s.git_open_pull_request:
                    async def produce() -> dict[str, Any]:
                        found = await api.find_pull(owner, name, record["branch"])
                        if found:
                            return {"number": found["number"], "url": found["html_url"], "found": True}
                        product = (state.get("vision") or {}).get("product_name") or state.get("title") or run_id
                        body = (notes.get("release_notes_markdown") or "") + (
                            f"\n\n---\nBuilt by Poiesis, run `{run_id}`. Tag `{tag}`.")
                        try:
                            pr = await api.open_pull(owner, name, record["branch"], base,
                                                     f"{product} {version}", body)
                        except httpx.HTTPStatusError as exc:
                            if exc.response.status_code == 422 and "No commits between" in exc.response.text:
                                return {"number": 0, "url": "", "empty": True}
                            raise
                        return {"number": pr["number"], "url": pr["html_url"]}
                    outcome["pull_request"] = await remember(run_id, "git:pr", produce)
            finally:
                await api.close()
        else:
            # A plain remote: fast-forward the default branch when that is all it takes.
            code, out = await _git(run_id, "push", _authed(record["url"]), f"HEAD:refs/heads/{base}")
            outcome["default_branch"] = base if code == 0 else ""
            if code != 0:
                outcome["default_branch_note"] = out.strip()[-300:]
        await asyncio.to_thread(_remember_plain, run_id, "release", outcome)
        pr = outcome.get("pull_request") or {}
        await emit(run_id, f"Release pushed: tag {tag} on {record['web_url']}"
                           + (f"; pull request {pr['url']}" if pr.get("url") else "")
                           + (f"; {outcome['default_branch']} updated" if outcome.get("default_branch") else ""),
                   agent="tracker", stage="release", data=outcome)
    await _safely(run_id, "release", "release push", work)


def _remember_plain(run_id: str, key: str, value: dict[str, Any]) -> None:
    with session() as s:
        row = s.get(NodeCache, (run_id, f"git:{key}"))
        payload = {"__value__": value}
        if row is None:
            s.add(NodeCache(run_id=run_id, key=f"git:{key}", value=payload))
        else:
            row.value = payload
        s.commit()


def mapping(run_id: str) -> dict[str, Any]:
    """Where this run lives on the remote, for the API and the control room."""
    remote = _known(run_id, "remote") or {}
    return {
        "configured": configured(),
        "url": remote.get("web_url", ""), "branch": remote.get("branch", ""),
        "created": bool(remote.get("created")),
        "pull_request": _known(run_id, "pr") or {},
        "release": _known(run_id, "release") or {},
    }


# ---- CLI ---------------------------------------------------------------------------

async def _cli(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "push":
        from ..db import Artifact
        run_id = argv[1]
        with session() as s:
            rows = s.query(Artifact).filter(Artifact.run_id == run_id, Artifact.kind == "vision").all()
        state = {"run_id": run_id, "vision": rows[-1].body if rows else {}}
        await on_workspace_ready(run_id, state)
        print(mapping(run_id))
        return 0
    print("usage: python -m app.integrations.gitremote push <run_id>")
    return 2


if __name__ == "__main__":
    sys.exit(asyncio.run(_cli(sys.argv[1:])))
