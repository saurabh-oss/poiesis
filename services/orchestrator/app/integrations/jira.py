"""A small Jira Cloud client: exactly the calls the tracker sync makes, no more.

Jira Cloud's REST API v3 for issues and the Agile API 1.0 for boards and sprints,
authenticated with an Atlassian account email and API token.

Three things about Jira shape this file:

* Descriptions and comments in v3 must be Atlassian Document Format (ADF), a JSON
  tree, not a string. A plain string is rejected with a 400, so every body goes
  through `adf()`.
* Workflows differ per project: "In Progress" may be called "Doing", "Done" may be
  "Closed". Transitions are therefore chosen by the target's status *category*
  (new / indeterminate / done), which every workflow has, never by name.
* Fields differ per project too. Story points is a custom field whose id and name
  vary, and a field that is not on the project's create screen is refused. So the
  client discovers what the project has and drops what it refuses, rather than
  failing the whole issue over one optional field.

    python -m app.integrations.jira check     # verify credentials and the project
"""
from __future__ import annotations

import asyncio
import base64
import datetime as dt
import json
import sys
from typing import Any

import httpx

from ..config import settings


class JiraError(RuntimeError):
    def __init__(self, status: int, method: str, path: str, detail: str):
        self.status = status
        # Jira names the offending fields in {"errors": {"customfield_10016": "..."}}.
        try:
            parsed = json.loads(detail)
            self.fields = set((parsed.get("errors") or {}).keys())
        except (ValueError, AttributeError):
            self.fields = set()
        super().__init__(f"Jira {method} {path} returned {status}: {detail[:600]}")


# --- Atlassian Document Format -------------------------------------------------

def _text(value: Any) -> list[dict[str, Any]]:
    s = str(value or "").strip()
    return [{"type": "text", "text": s}] if s else []


def adf(*blocks: dict[str, Any] | None) -> dict[str, Any]:
    """A document from blocks built with para(), heading() and bullets()."""
    content = [b for b in blocks if b]
    return {"type": "doc", "version": 1,
            "content": content or [{"type": "paragraph", "content": []}]}


def para(value: Any) -> dict[str, Any] | None:
    text = _text(value)
    return {"type": "paragraph", "content": text} if text else None


def heading(value: str, level: int = 3) -> dict[str, Any]:
    return {"type": "heading", "attrs": {"level": level}, "content": _text(value)}


def bullets(items: list[Any]) -> dict[str, Any] | None:
    rows = [{"type": "listItem", "content": [{"type": "paragraph", "content": _text(i)}]}
            for i in items if str(i or "").strip()]
    return {"type": "bulletList", "content": rows} if rows else None


def link(label: str, url: str) -> dict[str, Any]:
    return {"type": "paragraph", "content": [{
        "type": "text", "text": label, "marks": [{"type": "link", "attrs": {"href": url}}]}]}


# --- client ----------------------------------------------------------------------

def configured() -> bool:
    s = settings()
    return bool(s.jira_base_url and s.jira_email and s.jira_api_token and s.jira_project_key)


class Jira:
    """One project on one site. Discovery results are cached on the instance."""

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        s = settings()
        self.base = s.jira_base_url.rstrip("/")
        self.project_key = s.jira_project_key
        token = base64.b64encode(f"{s.jira_email}:{s.jira_api_token}".encode()).decode()
        self._http = httpx.AsyncClient(
            base_url=self.base, transport=transport, timeout=30,
            headers={"Authorization": f"Basic {token}", "Accept": "application/json",
                     "Content-Type": "application/json"},
        )
        self._project: dict[str, Any] | None = None
        self._points: str | None | bool = False  # False = not looked up yet

    async def close(self) -> None:
        await self._http.aclose()

    def browse(self, key: str) -> str:
        return f"{self.base}/browse/{key}"

    async def _call(self, method: str, path: str, **kwargs: Any) -> Any:
        # Jira Cloud rate-limits with 429 and a Retry-After; 5xx are usually transient.
        for attempt in range(4):
            r = await self._http.request(method, path, **kwargs)
            if r.status_code == 429 or r.status_code >= 500:
                if attempt < 3:
                    wait = float(r.headers.get("Retry-After") or 2 ** attempt)
                    await asyncio.sleep(min(wait, 20))
                    continue
            if r.status_code >= 400:
                raise JiraError(r.status_code, method, path, r.text)
            return r.json() if r.content else None
        raise JiraError(r.status_code, method, path, r.text)

    # discovery ------------------------------------------------------------------

    async def myself(self) -> dict[str, Any]:
        return await self._call("GET", "/rest/api/3/myself")

    async def project(self) -> dict[str, Any]:
        if self._project is None:
            self._project = await self._call("GET", f"/rest/api/3/project/{self.project_key}")
        return self._project

    async def issue_types(self) -> dict[str, dict[str, Any] | None]:
        """The project's types for each level of the Initiative > Epic > Story tree."""
        types = [t for t in (await self.project()).get("issueTypes", []) if not t.get("subtask")]
        by_name = {t["name"].lower(): t for t in types}
        by_level: dict[int, list[dict[str, Any]]] = {}
        for t in types:
            by_level.setdefault(int(t.get("hierarchyLevel", 0)), []).append(t)
        wanted = settings().jira_initiative_type.lower()
        initiative = by_name.get(wanted) or next(iter(by_level.get(2, [])), None)
        epic = by_name.get("epic") or next(iter(by_level.get(1, [])), None)
        story = by_name.get("story") or by_name.get("task") or next(iter(by_level.get(0, [])), None)
        return {"initiative": initiative, "epic": epic, "story": story}

    async def story_points_field(self) -> str | None:
        if self._points is False:
            fields = await self._call("GET", "/rest/api/3/field")
            names = ("story point estimate", "story points")
            self._points = next((f["id"] for f in fields
                                 if str(f.get("name", "")).lower() in names), None)
        return self._points or None

    async def scrum_board(self) -> dict[str, Any] | None:
        configured_id = settings().jira_board_id
        if configured_id:
            return await self._call("GET", f"/rest/agile/1.0/board/{configured_id}")
        boards = await self._call("GET", "/rest/agile/1.0/board",
                                  params={"projectKeyOrId": self.project_key, "type": "scrum"})
        return next(iter((boards or {}).get("values", [])), None)

    # issues -----------------------------------------------------------------------

    async def find_by_label(self, label: str) -> dict[str, Any] | None:
        body = {"jql": f'project = "{self.project_key}" AND labels = "{label}"',
                "fields": ["summary", "status"], "maxResults": 5}
        found = await self._call("POST", "/rest/api/3/search/jql", json=body)
        return next(iter((found or {}).get("issues", [])), None)

    async def create_issue(self, *, type_id: str, summary: str, description: dict[str, Any],
                           labels: list[str], parent: str | None = None,
                           extra: dict[str, Any] | None = None) -> tuple[dict[str, Any], list[str]]:
        """Create an issue, dropping optional fields the project refuses.

        Returns the created issue and the names of anything that had to be left
        off (a parent the hierarchy does not allow, a field not on the screen).
        """
        fields: dict[str, Any] = {
            "project": {"key": self.project_key}, "issuetype": {"id": type_id},
            "summary": summary[:250], "description": description, "labels": labels,
            **(extra or {}),
        }
        if parent:
            fields["parent"] = {"key": parent}
        dropped: list[str] = []
        while True:
            try:
                return await self._call("POST", "/rest/api/3/issue", json={"fields": fields}), dropped
            except JiraError as exc:
                if exc.status != 400:
                    raise
                refused = [k for k in exc.fields if k in fields and k not in _REQUIRED]
                if not refused:
                    raise
                for k in refused:
                    fields.pop(k)
                    dropped.append(k)

    async def status_category(self, key: str) -> str:
        issue = await self._call("GET", f"/rest/api/3/issue/{key}", params={"fields": "status"})
        return issue["fields"]["status"]["statusCategory"]["key"]

    async def move_to(self, key: str, category: str) -> bool:
        """Transition to any status in `category` ("indeterminate" or "done").

        A no-op when the issue is already there, so it is safe to repeat.
        """
        if await self.status_category(key) == category:
            return False
        if await self._step(key, category):
            return True
        # Many workflows only reach Done by way of In Progress.
        if category == "done" and await self._step(key, "indeterminate"):
            return await self._step(key, "done")
        return False

    async def _step(self, key: str, category: str) -> bool:
        options = (await self._call("GET", f"/rest/api/3/issue/{key}/transitions")).get("transitions", [])
        target = next((t for t in options
                       if t.get("to", {}).get("statusCategory", {}).get("key") == category), None)
        if target is None:
            return False
        await self._call("POST", f"/rest/api/3/issue/{key}/transitions",
                         json={"transition": {"id": target["id"]}})
        return True

    async def add_labels(self, key: str, labels: list[str]) -> None:
        await self._call("PUT", f"/rest/api/3/issue/{key}",
                         json={"update": {"labels": [{"add": label} for label in labels]}})

    async def comment(self, key: str, body: dict[str, Any]) -> None:
        await self._call("POST", f"/rest/api/3/issue/{key}/comment", json={"body": body})

    async def remote_link(self, key: str, url: str, title: str) -> None:
        # globalId makes this an upsert, so the same link is never added twice.
        await self._call("POST", f"/rest/api/3/issue/{key}/remotelink",
                         json={"globalId": url, "object": {"url": url, "title": title}})

    # sprints ------------------------------------------------------------------------

    async def find_sprint(self, board_id: int, name: str) -> dict[str, Any] | None:
        found = await self._call("GET", f"/rest/agile/1.0/board/{board_id}/sprint",
                                 params={"state": "future,active"})
        return next((s for s in (found or {}).get("values", []) if s.get("name") == name), None)

    async def create_sprint(self, board_id: int, name: str, goal: str) -> dict[str, Any]:
        return await self._call("POST", "/rest/agile/1.0/sprint",
                                json={"name": name[:30], "originBoardId": board_id, "goal": goal[:500]})

    async def add_to_sprint(self, sprint_id: int, keys: list[str]) -> None:
        for i in range(0, len(keys), 50):  # the API takes at most 50 per call
            await self._call("POST", f"/rest/agile/1.0/sprint/{sprint_id}/issue",
                             json={"issues": keys[i:i + 50]})

    async def start_sprint(self, sprint_id: int, days: int) -> None:
        start = dt.datetime.now(dt.timezone.utc)
        await self._call("POST", f"/rest/agile/1.0/sprint/{sprint_id}", json={
            "state": "active", "startDate": start.isoformat(),
            "endDate": (start + dt.timedelta(days=days)).isoformat()})

    async def close_sprint(self, sprint_id: int) -> None:
        await self._call("POST", f"/rest/agile/1.0/sprint/{sprint_id}", json={"state": "closed"})


_REQUIRED = {"project", "issuetype", "summary"}


# --- setup check -----------------------------------------------------------------

async def check() -> int:
    """Say plainly whether this Jira project can take a run, and what will degrade."""
    if not configured():
        print("Jira is not configured. Set JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN and "
              "JIRA_PROJECT_KEY in .env, then restart the orchestrator.")
        return 1
    j = Jira()
    try:
        me = await j.myself()
        print(f"OK    signed in as {me.get('displayName')} ({me.get('emailAddress', 'email hidden')})")
        p = await j.project()
        style = "team-managed" if p.get("simplified") else "company-managed"
        print(f"OK    project {p['key']} - {p['name']} ({style})")
        types = await j.issue_types()
        for level in ("initiative", "epic", "story"):
            t = types[level]
            if t:
                print(f"OK    {level:10s} -> issue type '{t['name']}'")
            elif level == "initiative":
                print(f"WARN  no '{settings().jira_initiative_type}' issue type in {p['key']}. "
                      "Epics will be created without a parent. Initiatives need Jira Premium "
                      "with the hierarchy configured, or set JIRA_INITIATIVE_TYPE to a type "
                      "this project has above Epic.")
            else:
                print(f"FAIL  no {level} issue type in {p['key']} - stories cannot be created")
                return 1
        points = await j.story_points_field()
        print(f"OK    story points field {points}" if points
              else "WARN  no story points field - estimates go in the description only")
        board = await j.scrum_board()
        print(f"OK    scrum board {board['id']} - {board['name']}" if board
              else "WARN  no scrum board for this project - sprints will be skipped "
                   "(a kanban board has no sprints; or set JIRA_BOARD_ID)")
        return 0
    except JiraError as exc:
        hint = {401: "the email or API token is wrong",
                403: "this account cannot see or edit the project",
                404: "the site URL or project key is wrong"}.get(exc.status, "")
        print(f"FAIL  {exc}" + (f"\n      likely cause: {hint}" if hint else ""))
        return 1
    finally:
        await j.close()


if __name__ == "__main__":
    if sys.argv[1:] == ["check"]:
        raise SystemExit(asyncio.run(check()))
    print(__doc__)
