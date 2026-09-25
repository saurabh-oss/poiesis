"""Plane (open-source project tracker, cloud or self-hosted). Written by Poiesis, and read-only.

    from ..connectors import plane
    r = plane().create_work_item("Reduce duplicate reports for checkout", "<p>Cluster of 14 tickets</p>",
                                 priority="high", idempotency_key=f"cluster-{c.id}")

Live when PLANE_BASE_URL, PLANE_API_KEY, PLANE_WORKSPACE and PLANE_PROJECT_ID are set.
A self-hosted Plane on the same machine is reached from inside the application's
containers at http://host.docker.internal:<port>.
"""
from __future__ import annotations

import html
from typing import Any

from .base import Connector, ConnectorError, Result, Setting, http_json

SANDBOX_START = 1
PRIORITIES = ("urgent", "high", "medium", "low", "none")
_GROUP_OF = {"backlog": "Backlog", "unstarted": "Todo", "started": "In Progress", "completed": "Done", "cancelled": "Cancelled"}


class Plane(Connector):
    name = "plane"
    title = "Plane"
    category = "Ticketing"
    description = "Create and update Plane work items, comment on them and move them across the board."
    vendor_url = "https://developers.plane.so/api-reference/introduction"
    settings = (
        Setting("PLANE_BASE_URL", "Plane URL", required=True, help="https://app.plane.so or http://host.docker.internal:8200"),
        Setting("PLANE_API_KEY", "API key", required=True, secret=True, help="Profile settings → API tokens"),
        Setting("PLANE_WORKSPACE", "Workspace slug", required=True),
        Setting("PLANE_PROJECT_ID", "Project id", required=True),
        Setting("PLANE_PROJECT_IDENTIFIER", "Project identifier", default="", help="Shown in keys, e.g. SUP"),
    )
    operations = {
        "create_work_item": "Create a work item in the project",
        "get_work_item": "Read a work item",
        "add_comment": "Comment on a work item",
        "move": "Move a work item to a state (Todo, In Progress, Done…)",
        "list_work_items": "List the project's work items",
    }

    def _root(self) -> str:
        return f"{self.setting('PLANE_BASE_URL').rstrip('/')}/api/v1/workspaces/{self.setting('PLANE_WORKSPACE')}" \
               f"/projects/{self.setting('PLANE_PROJECT_ID')}"

    def _api(self, method: str, path: str, body: Any = None) -> Any:
        return http_json(method, f"{self._root()}{path}", headers={"X-API-Key": self.setting("PLANE_API_KEY")}, body=body)[1]

    def _prefix(self) -> str:
        return self.setting("PLANE_PROJECT_IDENTIFIER") or "PLN"

    def item_url(self, item_id: str) -> str:
        if self.mode != "live":
            return self._sandbox_url(item_id)
        return f"{self.setting('PLANE_BASE_URL').rstrip('/')}/{self.setting('PLANE_WORKSPACE')}/projects/" \
               f"{self.setting('PLANE_PROJECT_ID')}/issues/{item_id}"

    def _states(self) -> dict[str, str]:
        data = self._api("GET", "/states/") or {}
        rows = data.get("results", data) if isinstance(data, dict) else data
        return {r["name"].lower(): r["id"] for r in rows or []} | \
               {_GROUP_OF.get(r.get("group", ""), "").lower(): r["id"] for r in rows or [] if r.get("group") in _GROUP_OF}

    @staticmethod
    def _paragraphs(text: str) -> str:
        return text if text.lstrip().startswith("<") else "".join(f"<p>{html.escape(p)}</p>" for p in text.split("\n") if p.strip())

    def create_work_item(self, name: str, description: str = "", *, priority: str = "none",
                         idempotency_key: str | None = None, ref: str | None = None) -> Result:
        """`r.key` is the human key (SUP-12); later calls take the item's id, `r.data["id"]`
        (the same string in the sandbox)."""
        priority = priority.lower() if priority and priority.lower() in PRIORITIES else "none"
        body = {"name": name[:255], "description_html": self._paragraphs(description), "priority": priority}

        def live() -> Result:
            made = self._api("POST", "/work-items/", body) or {}
            if not made.get("id"):
                raise ConnectorError(f"Plane created nothing: {made}")
            key = f"{self._prefix()}-{made.get('sequence_id')}" if made.get("sequence_id") else made["id"]
            return Result(True, self.name, "create_work_item", "live", key=key, url=self.item_url(made["id"]),
                          data={"id": made["id"], "sequence_id": made.get("sequence_id")})

        def sandbox() -> Result:
            key = f"{self._prefix()}-{self.store.next_number(self.name, 'item', SANDBOX_START)}"
            self._remember(key, "work_item", {"id": key, "name": name, "description": description, "state": "Todo",
                                              "priority": priority, "comments": []})
            return Result(True, self.name, "create_work_item", "sandbox", key=key, url=self._sandbox_url(key),
                          data={"id": key, "state": "Todo"})

        return self._call("create_work_item", body, live=live, sandbox=sandbox, idempotency_key=idempotency_key, ref=ref)

    def get_work_item(self, item_id: str) -> Result:
        def live() -> Result:
            data = self._api("GET", f"/work-items/{item_id}/") or {}
            return Result(True, self.name, "get_work_item", "live", key=item_id, url=self.item_url(item_id),
                          data={k: data.get(k) for k in ("id", "name", "priority", "state", "sequence_id", "updated_at")})

        def sandbox() -> Result:
            return Result(True, self.name, "get_work_item", "sandbox", key=item_id, url=self._sandbox_url(item_id),
                          data=self._recall(item_id))

        return self._call("get_work_item", {"id": item_id}, live=live, sandbox=sandbox, ref=item_id)

    def add_comment(self, item_id: str, text: str, *, idempotency_key: str | None = None) -> Result:
        def live() -> Result:
            self._api("POST", f"/work-items/{item_id}/comments/", {"comment_html": self._paragraphs(text)})
            return Result(True, self.name, "add_comment", "live", key=item_id, url=self.item_url(item_id))

        def sandbox() -> Result:
            item = self._recall(item_id)
            item["comments"] = [*item.get("comments", []), text]
            self._remember(item_id, "work_item", item)
            return Result(True, self.name, "add_comment", "sandbox", key=item_id, url=self._sandbox_url(item_id),
                          data={"comments": len(item["comments"])})

        return self._call("add_comment", {"id": item_id, "comment": text}, live=live, sandbox=sandbox,
                          idempotency_key=idempotency_key, ref=item_id)

    def move(self, item_id: str, state: str) -> Result:
        wanted = state.strip().lower()

        def live() -> Result:
            states = self._states()
            if wanted not in states:
                raise ConnectorError(f"Plane has no state {state}; it has: {', '.join(sorted(k for k in states if k))}")
            self._api("PATCH", f"/work-items/{item_id}/", {"state": states[wanted]})
            return Result(True, self.name, "move", "live", key=item_id, url=self.item_url(item_id), data={"state": state})

        def sandbox() -> Result:
            item = self._recall(item_id)
            item["state"] = state.title()
            self._remember(item_id, "work_item", item)
            return Result(True, self.name, "move", "sandbox", key=item_id, url=self._sandbox_url(item_id),
                          data={"state": item["state"]})

        return self._call("move", {"id": item_id, "state": state}, live=live, sandbox=sandbox, ref=item_id)

    def list_work_items(self, *, limit: int = 100) -> Result:
        def live() -> Result:
            data = self._api("GET", f"/work-items/?per_page={min(limit, 100)}") or {}
            rows = data.get("results", data) if isinstance(data, dict) else data
            return Result(True, self.name, "list_work_items", "live",
                          data={"items": [{k: r.get(k) for k in ("id", "name", "priority", "state", "sequence_id")} for r in rows or []]})

        def sandbox() -> Result:
            return Result(True, self.name, "list_work_items", "sandbox",
                          data={"items": self.store.objects(self.name, "work_item")[-limit:]})

        return self._call("list_work_items", {"limit": limit}, live=live, sandbox=sandbox)
