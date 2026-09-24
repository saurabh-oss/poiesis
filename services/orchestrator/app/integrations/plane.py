"""Mirror every run into Plane, the self-hosted open-source tracker: one project per idea.

    run             -> Project       (named after the product; its own board)
    backlog epic    -> Module        (the epic's outcome as its description)
    backlog story   -> Work item     (narrative, acceptance criteria, points, priority)
    sprint          -> Cycle         (dated, holding exactly the sprint's stories)
    story building  -> In Progress
    story green     -> Done, with what was verified
    story red       -> stays In Progress, labelled poiesis-red, with the failure
    release         -> a "Release" work item, linked to the running app

The same two rules as the Jira mirror (tracker.py) hold here. It never stops a run:
Plane being down costs a warning in the run's log. It never duplicates: LangGraph
replays whole nodes when a gate is answered, so every object is created under a
remember() key, and work items and modules also carry an external id, which Plane
refuses to create twice (it answers 409 with the existing id).

Plane is set up by scripts/plane-bootstrap.py, which writes PLANE_* into .env.

    python -m app.integrations.plane check              # verify the connection
    python -m app.integrations.plane backfill <run_id>  # mirror a past run
"""
from __future__ import annotations

import asyncio
import datetime as dt
import html
import re
import sys
from typing import Any, Awaitable, Callable

import httpx

from ..config import settings  # noqa: F401 — also used by api/plane.py
from ..db import Artifact, NodeCache, Run, session
from ..events import emit
from ..graph.memo import remember

SOURCE = "poiesis"
_transport: httpx.AsyncBaseTransport | None = None


def use_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    global _transport
    _transport = transport


def configured() -> bool:
    s = settings()
    return bool(s.plane_api_token and (s.plane_api_url or s.plane_url) and s.plane_workspace)


class PlaneError(RuntimeError):
    def __init__(self, status: int, method: str, path: str, detail: str):
        self.status = status
        super().__init__(f"Plane {method} {path} returned {status}: {detail[:400]}")


class Plane:
    """The handful of Plane REST v1 calls the mirror makes."""

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        s = settings()
        base = (s.plane_api_url or s.plane_url).rstrip("/")
        self.slug = s.plane_workspace
        self.web = (s.plane_url or base).rstrip("/")
        self.http = httpx.AsyncClient(
            base_url=f"{base}/api/v1/workspaces/{self.slug}", transport=transport, timeout=30,
            headers={"X-API-Key": s.plane_api_token, "Content-Type": "application/json"})
        # A project's states and labels change only when we add one; asking for them
        # before every write tripled the calls and ran into Plane's per-key throttle.
        self.cache: dict[str, Any] = {}

    async def close(self) -> None:
        await self.http.aclose()

    async def call(self, method: str, path: str, json: Any = None, ok_conflict: bool = False) -> Any:
        for attempt in range(6):
            r = await self.http.request(method, path, json=json)
            if r.status_code != 429:
                break
            # Throttled: Plane counts calls per API key per minute. Wait it out.
            await asyncio.sleep(min(60, 5 * (attempt + 1)))
        if ok_conflict and (r.status_code == 409 or (r.status_code == 400 and "ALREADY_EXISTS" in r.text)):
            body = r.json()
            if body.get("id"):
                return body
        if r.status_code >= 400:
            raise PlaneError(r.status_code, method, path, r.text)
        return r.json() if r.content else None

    async def all(self, path: str) -> list[dict[str, Any]]:
        out, cursor = [], None
        for _ in range(50):
            sep = "&" if "?" in path else "?"
            page = await self.call("GET", f"{path}{sep}per_page=100" + (f"&cursor={cursor}" if cursor else ""))
            if isinstance(page, list):
                return page
            out += page.get("results", [])
            if not page.get("next_page_results"):
                break
            cursor = page.get("next_cursor")
        return out

    # -- links a person opens ----------------------------------------------------
    def project_url(self, pid: str) -> str:
        return f"{self.web}/{self.slug}/projects/{pid}/issues/"

    def item_url(self, identifier: str, seq: int) -> str:
        return f"{self.web}/{self.slug}/browse/{identifier}-{seq}/"

    def cycle_url(self, pid: str, cid: str) -> str:
        return f"{self.web}/{self.slug}/projects/{pid}/cycles/{cid}/"

    def module_url(self, pid: str, mid: str) -> str:
        return f"{self.web}/{self.slug}/projects/{pid}/modules/{mid}/"


# ---- helpers ---------------------------------------------------------------------

def _e(text: Any) -> str:
    return html.escape(str(text or ""))


def _ul(items: list[Any]) -> str:
    items = [i for i in items if i not in (None, "")]
    return "<ul>" + "".join(f"<li><p>{_e(_line(i))}</p></li>" for i in items) + "</ul>" if items else ""


def _line(item: Any) -> str:
    if not isinstance(item, dict):
        return str(item)
    return " — ".join(str(v) for v in item.values() if v not in (None, "", [], {}))


def _identifier(run_id: str, product: str) -> str:
    """Plane's short project key: product initials plus six characters of the run id.

    Four were not enough: two AssetHub runs began a3a2 and shared a project.
    """
    words = re.findall(r"[A-Za-z0-9]+", product) or ["P"]
    initials = "".join(w[0] for w in words)[:3] if len(words) > 1 else words[0][:3]
    return (initials + run_id[:6]).upper()[:12]


def _priority(story: dict[str, Any]) -> str:
    value = story.get("value")
    if isinstance(value, (int, float)):
        return "urgent" if value >= 9 else "high" if value >= 7 else "medium" if value >= 4 else "low"
    return "medium"


def _known(run_id: str, key: str) -> dict | None:
    with session() as s:
        row = s.get(NodeCache, (run_id, key))
        return None if row is None else (row.value or {}).get("__value__")


async def _safely(run_id: str, stage: str, what: str, work: Callable[[Plane], Awaitable[Any]]) -> Any:
    if not configured():
        return None
    p = Plane(transport=_transport)
    try:
        return await work(p)
    except Exception as exc:  # noqa: BLE001 — a mirror must never take the run down
        await emit(run_id, f"Plane sync skipped ({what}): {exc}", agent="tracker", stage=stage, level="warn")
        return None
    finally:
        await p.close()


async def _states(p: Plane, pid: str) -> dict[str, str]:
    """group -> state id (backlog, unstarted, started, completed, cancelled)."""
    key = f"states:{pid}"
    if key not in p.cache:
        out: dict[str, str] = {}
        for st in await p.all(f"/projects/{pid}/states/"):
            out.setdefault(st["group"], st["id"])
        p.cache[key] = out
    return p.cache[key]


async def _label(p: Plane, pid: str, name: str, color: str) -> str:
    key = f"labels:{pid}"
    if key not in p.cache:
        p.cache[key] = {lb["name"]: lb["id"] for lb in await p.all(f"/projects/{pid}/labels/")}
    labels = p.cache[key]
    if name not in labels:
        made = await p.call("POST", f"/projects/{pid}/labels/", {"name": name, "color": color}, ok_conflict=True)
        labels[name] = made["id"]
    return labels[name]


async def _item(p: Plane, pid: str, external_id: str, body: dict[str, Any]) -> dict[str, Any]:
    made = await p.call("POST", f"/projects/{pid}/work-items/",
                        {**body, "external_id": external_id, "external_source": SOURCE}, ok_conflict=True)
    if "error" in made and made.get("id"):
        made = await p.call("GET", f"/projects/{pid}/work-items/{made['id']}/")
    return made


# ---- the plan --------------------------------------------------------------------

async def _project(run_id: str, p: Plane, state: dict[str, Any]) -> dict[str, Any]:
    vision = state.get("vision") or {}
    product = vision.get("product_name") or state.get("title") or "Poiesis run"

    async def produce() -> dict:
        ident = _identifier(run_id, product)
        for proj in await p.all("/projects/"):
            # Found only after a crash between Plane answering and the key being stored.
            if proj.get("identifier") == ident and proj.get("name", "").endswith(run_id[:6]):
                return {"id": proj["id"], "identifier": ident, "name": proj["name"], "url": p.project_url(proj["id"])}
        desc = " ".join(x for x in (vision.get("problem_statement"), vision.get("value_proposition")) if x)
        made = await p.call("POST", "/projects/", {
            "name": f"{product} · {run_id[:6]}"[:80], "identifier": ident,
            "description": (desc or f"Planned and built by Poiesis, run {run_id}.")[:1000],
            "module_view": True, "cycle_view": True, "issue_views_view": True, "page_view": True,
        })
        return {"id": made["id"], "identifier": ident, "name": made["name"], "url": p.project_url(made["id"])}
    return await remember(run_id, "plane:project", produce)


_KANBAN = """
from plane.db.models import ProjectUserProperty
for prop in ProjectUserProperty.objects.filter(user__email=__EMAIL__):
    df = dict(prop.display_filters or {})
    if df.get("layout") != "kanban":
        df.update({"layout": "kanban", "group_by": "state", "order_by": "sort_order"})
        prop.display_filters = df
        prop.save(update_fields=["display_filters"])
"""


async def _open_as_board() -> None:
    """Make the admin's projects open as a board grouped by state, not Plane's default list.

    Plane keeps the layout per user and project, and its REST API has no call for
    it, so this runs a line of Django in Plane's api container. Best effort: a
    project that still opens as a list is one click from a board.
    """
    s = settings()
    if not s.plane_api_container:
        return
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", "-i", s.plane_api_container, "python", "manage.py", "shell",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        try:
            await asyncio.wait_for(proc.communicate(_KANBAN.replace("__EMAIL__", repr(s.plane_admin_email)).encode()), 60)
        finally:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
    except Exception:  # noqa: BLE001 — cosmetic; never worth failing a mirror over
        pass


def _story_html(run_id: str, story: dict[str, Any]) -> str:
    details = [f"Poiesis story {story.get('id')}"]
    for label, key in (("Value", "value"), ("Estimate", "estimate"), ("Risk", "risk")):
        if story.get(key) not in (None, ""):
            details.append(f"{label}: {story[key]}")
    if story.get("depends_on"):
        details.append("Depends on: " + ", ".join(map(str, story["depends_on"])))
    return (f"<p>{_e(story.get('narrative'))}</p><h3>Acceptance criteria</h3>{_ul(story.get('acceptance_criteria') or [])}"
            f"<h3>Details</h3>{_ul(details)}<p><em>Planned by Poiesis, run {_e(run_id)}.</em></p>")


async def on_backlog(run_id: str, state: dict[str, Any], backlog: dict[str, Any]) -> None:
    """The approved backlog becomes a project with a module per epic and a work item per story."""
    async def work(p: Plane) -> None:
        proj = await _project(run_id, p, state)
        pid = proj["id"]
        states = await _states(p, pid)
        tag = await _label(p, pid, "poiesis", "#0265dc")

        modules: dict[str, str] = {}
        for epic in backlog.get("epics", []):
            async def make_module(e=epic) -> dict:
                made = await p.call("POST", f"/projects/{pid}/modules/", {
                    "name": f"{e['id']} · {e.get('title') or e['id']}"[:255],
                    "description": e.get("outcome") or "",
                    "external_id": f"{run_id}-{e['id']}", "external_source": SOURCE,
                }, ok_conflict=True)
                if not made.get("id"):  # a conflict that did not name the module
                    made = next(m for m in await p.all(f"/projects/{pid}/modules/")
                                if m.get("external_id") == f"{run_id}-{e['id']}")
                return {"id": made["id"], "url": p.module_url(pid, made["id"])}
            modules[epic["id"]] = (await remember(run_id, f"plane:epic:{epic['id'].lower()}", make_module))["id"]

        stories = backlog.get("stories", [])
        for story in stories:
            async def make_item(s=story) -> dict:
                labels = [tag]
                if isinstance(s.get("estimate"), (int, float)):
                    labels.append(await _label(p, pid, f"{s['estimate']:g} pts", "#7e84fa"))
                if str(s.get("risk", "")).lower() == "high":
                    labels.append(await _label(p, pid, "high risk", "#e68619"))
                made = await _item(p, pid, f"{run_id}-{s['id']}", {
                    "name": f"{s['id']} · {s.get('title') or s['id']}"[:255],
                    "description_html": _story_html(run_id, s),
                    "priority": _priority(s), "labels": labels, "state": states.get("backlog"),
                })
                mid = modules.get(s.get("epic_id", ""))
                if mid:
                    await p.call("POST", f"/projects/{pid}/modules/{mid}/module-issues/", {"issues": [made["id"]]})
                return {"id": made["id"], "seq": made.get("sequence_id"),
                        "key": f"{proj['identifier']}-{made.get('sequence_id')}",
                        "url": p.item_url(proj["identifier"], made.get("sequence_id"))}
            await remember(run_id, f"plane:story:{story['id'].lower()}", make_item)

        # Plane creates the project's per-user view settings after answering the
        # create call, so the board layout is set once the backlog is in.
        await _open_as_board()
        await emit(run_id, f"Plane: project {proj['identifier']} with {len(modules)} module(s) and "
                           f"{len(stories)} work item(s) — {proj['url']}",
                   agent="tracker", stage="backlog", data={"plane": {"project": proj}})
    await _safely(run_id, "backlog", "backlog", work)


async def on_sprint(run_id: str, state: dict[str, Any], sprint: dict[str, Any]) -> None:
    """The cut sprint becomes a dated cycle holding exactly its stories, moved to Todo."""
    async def work(p: Plane) -> None:
        proj = _known(run_id, "plane:project") or await _project(run_id, p, state)
        pid = proj["id"]
        items = [m for m in (_known(run_id, f"plane:story:{e['id'].lower()}") for e in sprint.get("stories", [])) if m]
        states = await _states(p, pid)

        async def produce() -> dict:
            today = dt.date.today()
            made = await p.call("POST", f"/projects/{pid}/cycles/", {
                "name": "Sprint 1", "description": sprint.get("sprint_goal", ""),
                "start_date": today.isoformat(),
                "end_date": (today + dt.timedelta(days=settings().jira_sprint_days)).isoformat(),
                "external_id": f"{run_id}-sprint1", "external_source": SOURCE,
            }, ok_conflict=True)
            if items:
                await p.call("POST", f"/projects/{pid}/cycles/{made['id']}/cycle-issues/",
                             {"issues": [m["id"] for m in items]})
            return {"id": made["id"], "name": "Sprint 1", "url": p.cycle_url(pid, made["id"]),
                    "stories": [m["key"] for m in items]}
        cycle = await remember(run_id, "plane:sprint:1", produce)
        for m in items:
            await _forward(p, pid, m["id"], "unstarted", states)
        await emit(run_id, f"Plane: cycle '{cycle['name']}' with {len(items)} work item(s) — {cycle['url']}",
                   agent="tracker", stage="sprint", data={"plane": {"sprint": cycle}})
    await _safely(run_id, "sprint", "sprint", work)


# ---- progress --------------------------------------------------------------------

_ORDER = {"backlog": 0, "unstarted": 1, "started": 2, "completed": 3, "cancelled": 3}


async def _forward(p: Plane, pid: str, item_id: str, group: str, states: dict[str, str]) -> None:
    """Move a work item towards `group`, never backwards: a replay must not reopen Done."""
    item = await p.call("GET", f"/projects/{pid}/work-items/{item_id}/")
    current = next((g for g, sid in states.items() if sid == item.get("state")), "backlog")
    if _ORDER.get(current, 0) < _ORDER[group] and states.get(group):
        await p.call("PATCH", f"/projects/{pid}/work-items/{item_id}/", {"state": states[group]})


async def on_story_started(run_id: str, story_id: str) -> None:
    async def work(p: Plane) -> None:
        proj, known = _known(run_id, "plane:project"), _known(run_id, f"plane:story:{story_id.lower()}")
        if proj and known:
            await _forward(p, proj["id"], known["id"], "started", await _states(p, proj["id"]))
    await _safely(run_id, "build", f"{story_id} started", work)


async def on_story_result(run_id: str, result: dict[str, Any], rnd: int) -> None:
    sid, status = result.get("story_id", ""), result.get("status", "")

    async def work(p: Plane) -> None:
        proj, known = _known(run_id, "plane:project"), _known(run_id, f"plane:story:{sid.lower()}")
        if not (proj and known):
            return
        pid = proj["id"]
        if status == "green":
            await _forward(p, pid, known["id"], "completed", await _states(p, pid))
            files = result.get("files") or []
            body = (f"<p>Built and verified by Poiesis in round {rnd + 1}: its checks pass and its screen was "
                    f"opened in a browser, after {result.get('repair_attempts', 0)} repair attempt(s).</p>"
                    + (f"<h3>Files</h3>{_ul(files)}" if files else ""))
        else:
            await _forward(p, pid, known["id"], "started", await _states(p, pid))
            item = await p.call("GET", f"/projects/{pid}/work-items/{known['id']}/")
            red = await _label(p, pid, f"poiesis-{status}", "#d31510")
            if red not in (item.get("labels") or []):
                await p.call("PATCH", f"/projects/{pid}/work-items/{known['id']}/",
                             {"labels": [*(item.get("labels") or []), red]})
            why = result.get("reason") or "It still fails its checks after the repair budget."
            tail = str(result.get("test_output") or "")[-1500:]
            body = (f"<p>Poiesis could not finish this story in round {rnd + 1} ({_e(status)}). {_e(why)}</p>"
                    + (f"<pre><code>{_e(tail)}</code></pre>" if tail else ""))

        async def post() -> bool:
            await p.call("POST", f"/projects/{pid}/work-items/{known['id']}/comments/", {"comment_html": body})
            return True
        await remember(run_id, f"plane:note:{sid.lower()}:r{rnd}:{status}", post)
    await _safely(run_id, "build", f"{sid} {status}", work)


async def on_release(run_id: str, state: dict[str, Any], release: dict[str, Any]) -> None:
    status = release.get("status", "")
    rounds = state.get("human_rebuilds", 0)

    async def work(p: Plane) -> None:
        proj = _known(run_id, "plane:project")
        if not proj:
            return
        pid = proj["id"]
        states = await _states(p, pid)
        url = release.get("url") or (state.get("deployment") or {}).get("url") or ""
        version = release.get("version") or "v0.1"

        async def make() -> dict:
            made = await _item(p, pid, f"{run_id}-release", {
                "name": f"Release {version}", "priority": "high",
                "description_html": f"<p>The increment Poiesis built for this idea.</p>"
                                    + (f'<p><a href="{_e(url)}">Open the running application</a></p>' if url else ""),
                "labels": [await _label(p, pid, "release", "#eb1000")], "state": states.get("unstarted"),
            })
            return {"id": made["id"], "key": f"{proj['identifier']}-{made.get('sequence_id')}",
                    "url": p.item_url(proj["identifier"], made.get("sequence_id"))}
        item = await remember(run_id, "plane:release", make)
        if status == "released":
            await _forward(p, pid, item["id"], "completed", states)
            if url.startswith("http"):
                async def link() -> bool:
                    await p.call("POST", f"/projects/{pid}/work-items/{item['id']}/links/",
                                 {"url": url, "title": f"{version} — running app"})
                    return True
                await remember(run_id, "plane:release:link", link)
        line = {"released": f"Released {version}" + (" as a partial base app" if release.get("partial") else "") + ".",
                "held": "The release was held at the release gate.",
                "rebuild": "Sent back from the release gate for another build round."}.get(status, f"Release status: {status}.")

        async def post() -> bool:
            notes = release.get("notes") if isinstance(release.get("notes"), str) else ""
            await p.call("POST", f"/projects/{pid}/work-items/{item['id']}/comments/",
                         {"comment_html": f"<p>{_e(line)}</p>" + (f"<p>{_e(notes)}</p>" if notes else "")})
            return True
        await remember(run_id, f"plane:note:release:{rounds}:{status}", post)
        await emit(run_id, f"Plane: release {status} recorded on {item['key']}", agent="tracker", stage="release")
    await _safely(run_id, "release", f"release {status}", work)


# ---- reading it back ---------------------------------------------------------------

def mapping(run_id: str) -> dict[str, Any]:
    with session() as s:
        rows = s.query(NodeCache).filter(NodeCache.run_id == run_id, NodeCache.key.like("plane:%")).all()
    out: dict[str, Any] = {"enabled": configured(), "url": settings().plane_url, "project": None,
                           "epics": {}, "stories": {}, "sprint": None, "release": None}
    for row in rows:
        value = (row.value or {}).get("__value__")
        ref = row.key.split(":", 1)[1]
        if ref == "project":
            out["project"] = value
        elif ref == "sprint:1":
            out["sprint"] = value
        elif ref == "release":
            out["release"] = value
        elif ref.startswith("epic:"):
            out["epics"][ref.split(":")[1].upper()] = value
        elif ref.startswith("story:"):
            out["stories"][ref.split(":")[1].upper()] = value
    return out


_GROUP_ORDER = ["backlog", "unstarted", "started", "completed", "cancelled"]


async def board(run_id: str) -> dict[str, Any]:
    """The run's project as a board: columns by state, cards with their labels and module."""
    m = mapping(run_id)
    if not (configured() and m["project"]):
        return {**m, "columns": []}
    p = Plane(transport=_transport)
    try:
        pid = m["project"]["id"]
        states = await p.all(f"/projects/{pid}/states/")
        labels = {lb["id"]: lb for lb in await p.all(f"/projects/{pid}/labels/")}
        items = await p.all(f"/projects/{pid}/work-items/")
        modules = {mod["id"]: mod["name"] for mod in await p.all(f"/projects/{pid}/modules/")}
        in_module: dict[str, str] = {}
        for mid in modules:
            for link in await p.all(f"/projects/{pid}/modules/{mid}/module-issues/"):
                in_module[link.get("issue") or link.get("id")] = modules[mid]
        cols = []
        for st in sorted(states, key=lambda s: (_GROUP_ORDER.index(s["group"]) if s["group"] in _GROUP_ORDER else 9,
                                                s.get("sequence") or 0)):
            cards = [{
                "id": it["id"], "key": f"{m['project']['identifier']}-{it.get('sequence_id')}",
                "name": it["name"], "priority": it.get("priority"),
                "labels": [{"name": labels[l]["name"], "color": labels[l].get("color")} for l in it.get("labels") or [] if l in labels],
                "module": in_module.get(it["id"]),
                "url": p.item_url(m["project"]["identifier"], it.get("sequence_id")),
            } for it in sorted(items, key=lambda i: i.get("sequence_id") or 0) if it.get("state") == st["id"]]
            cols.append({"id": st["id"], "name": st["name"], "group": st["group"], "color": st.get("color"), "cards": cards})
        return {**m, "columns": cols, "total": len(items)}
    finally:
        await p.close()


def _latest(run_id: str, kind: str) -> dict[str, Any] | None:
    with session() as s:
        row = (s.query(Artifact).filter(Artifact.run_id == run_id, Artifact.kind == kind)
               .order_by(Artifact.version.desc(), Artifact.created_at.desc()).first())
        return None if row is None else row.body


async def backfill(run_id: str) -> dict[str, Any]:
    """Mirror a run that already happened. No model calls; safe to repeat."""
    from .tracker import _outcomes_from_events
    if not configured():
        return {"ok": False, "reason": "Plane is not configured (run scripts/plane-bootstrap.py)"}
    vision, backlog, sprint = (_latest(run_id, k) for k in ("vision", "backlog", "sprint"))
    if not backlog:
        return {"ok": False, "reason": "this run has no approved backlog yet"}
    with session() as s:
        run = s.get(Run, run_id)
        title = run.title if run else ""
    state = {"run_id": run_id, "vision": vision or {}, "title": (vision or {}).get("product_name") or title}
    await on_backlog(run_id, state, backlog)
    if sprint:
        await on_sprint(run_id, state, sprint)
    report = _latest(run_id, "test_report")
    for result in (report or {}).get("stories") or _outcomes_from_events(run_id):
        await on_story_started(run_id, result["story_id"])
        await on_story_result(run_id, result, 0)
    release = _latest(run_id, "release")
    if release:
        dep = _latest(run_id, "deployment") or {}
        await on_release(run_id, {**state, "deployment": dep}, release)
    return {"ok": True, **mapping(run_id)}


async def check() -> int:
    if not configured():
        print("Plane is not configured. Run: python scripts/plane-bootstrap.py")
        return 1
    p = Plane()
    try:
        projects = await p.all("/projects/")
        print(f"Plane workspace '{p.slug}' answers: {len(projects)} project(s). Web: {p.web}")
        return 0
    finally:
        await p.close()


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "backfill":
        print(asyncio.run(backfill(sys.argv[2])))
    elif len(sys.argv) == 2 and sys.argv[1] == "check":
        raise SystemExit(asyncio.run(check()))
    else:
        print(__doc__)
