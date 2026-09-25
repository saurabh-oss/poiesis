"""Jira (Cloud or Data Center). Written by Poiesis, and read-only.

    from ..connectors import jira
    r = jira().create_issue("Checkout fails for EU cards", "Seen by 14 customers since 09:10",
                            priority="High", labels=["duplicate-cluster"], idempotency_key=f"cluster-{c.id}")
    if r.ok: ticket.jira_key, ticket.jira_url = r.key, r.url

Live when JIRA_BASE_URL, JIRA_PROJECT and credentials are set: JIRA_EMAIL with
JIRA_API_TOKEN for Cloud, or JIRA_PAT (a personal access token) for Data Center.
REST API v2 is used because both editions accept it with plain-text descriptions.
"""
from __future__ import annotations

from typing import Any

from .base import Connector, ConnectorError, Result, Setting, basic_auth, http_json

SANDBOX_START = 101
_DONE = {"done", "closed", "resolved"}


class Jira(Connector):
    name = "jira"
    title = "Jira"
    category = "Ticketing"
    description = "Create, read, comment on, transition and search Jira issues."
    vendor_url = "https://developer.atlassian.com/cloud/jira/platform/rest/v2/"
    settings = (
        Setting("JIRA_BASE_URL", "Site URL", required=True, help="https://your-company.atlassian.net"),
        Setting("JIRA_PROJECT", "Project key", required=True, default="", help="SUP"),
        Setting("JIRA_EMAIL", "Account e-mail", help="Jira Cloud: the account the API token belongs to"),
        Setting("JIRA_API_TOKEN", "API token", secret=True, help="Jira Cloud: id.atlassian.com → Security → API tokens"),
        Setting("JIRA_PAT", "Personal access token", secret=True, help="Jira Data Center instead of e-mail + token"),
        Setting("JIRA_ISSUE_TYPE", "Default issue type", default="Task"),
    )
    live_when_any = (("JIRA_BASE_URL", "JIRA_PROJECT", "JIRA_EMAIL", "JIRA_API_TOKEN"),
                     ("JIRA_BASE_URL", "JIRA_PROJECT", "JIRA_PAT"))
    operations = {
        "create_issue": "Create an issue in the project",
        "get_issue": "Read an issue's status, summary and assignee",
        "add_comment": "Comment on an issue",
        "transition": "Move an issue to a status (Done, In Progress…)",
        "search": "Find issues with JQL",
    }

    # -- plumbing ---------------------------------------------------------------
    def _base(self) -> str:
        return self.setting("JIRA_BASE_URL").rstrip("/")

    def _project(self) -> str:
        return self.setting("JIRA_PROJECT") or "SBX"

    def _headers(self) -> dict[str, str]:
        if self.setting("JIRA_PAT"):
            return {"Authorization": f"Bearer {self.setting('JIRA_PAT')}"}
        return {"Authorization": basic_auth(self.setting("JIRA_EMAIL"), self.setting("JIRA_API_TOKEN"))}

    def _api(self, method: str, path: str, body: Any = None) -> Any:
        return http_json(method, f"{self._base()}/rest/api/2{path}", headers=self._headers(), body=body)[1]

    def browse_url(self, key: str) -> str:
        return f"{self._base()}/browse/{key}" if self.mode == "live" else self._sandbox_url(key)

    @staticmethod
    def _issue(data: dict[str, Any]) -> dict[str, Any]:
        f = data.get("fields") or {}
        return {"key": data.get("key"), "summary": f.get("summary"),
                "status": (f.get("status") or {}).get("name"),
                "priority": (f.get("priority") or {}).get("name"),
                "assignee": (f.get("assignee") or {}).get("displayName"),
                "labels": f.get("labels") or [], "updated": f.get("updated")}

    # -- operations ---------------------------------------------------------------
    def create_issue(self, summary: str, description: str = "", *, issue_type: str | None = None,
                     priority: str | None = None, labels: list[str] | None = None,
                     fields: dict[str, Any] | None = None, idempotency_key: str | None = None,
                     ref: str | None = None) -> Result:
        issue_type = issue_type or self.setting("JIRA_ISSUE_TYPE") or "Task"
        body: dict[str, Any] = {"fields": {"project": {"key": self._project()}, "summary": summary[:250],
                                           "description": description, "issuetype": {"name": issue_type},
                                           **({"priority": {"name": priority}} if priority else {}),
                                           **({"labels": [l.replace(" ", "-") for l in labels]} if labels else {}),
                                           **(fields or {})}}

        def live() -> Result:
            made = self._api("POST", "/issue", body) or {}
            key = made.get("key")
            if not key:
                raise ConnectorError(f"Jira created nothing: {made}")
            return Result(True, self.name, "create_issue", "live", key=key, url=self.browse_url(key), data=made)

        def sandbox() -> Result:
            key = f"{self._project()}-{self.store.next_number(self.name, self._project(), SANDBOX_START)}"
            self._remember(key, "issue", {"key": key, "summary": summary, "description": description,
                                          "status": "To Do", "priority": priority or "Medium",
                                          "labels": labels or [], "issue_type": issue_type, "comments": []})
            return Result(True, self.name, "create_issue", "sandbox", key=key, url=self._sandbox_url(key),
                          data={"key": key, "status": "To Do"})

        return self._call("create_issue", body, live=live, sandbox=sandbox, idempotency_key=idempotency_key, ref=ref)

    def get_issue(self, key: str) -> Result:
        def live() -> Result:
            data = self._issue(self._api("GET", f"/issue/{key}?fields=summary,status,priority,assignee,labels,updated") or {})
            return Result(True, self.name, "get_issue", "live", key=key, url=self.browse_url(key), data=data)

        def sandbox() -> Result:
            return Result(True, self.name, "get_issue", "sandbox", key=key, url=self._sandbox_url(key),
                          data=self._recall(key))

        return self._call("get_issue", {"key": key}, live=live, sandbox=sandbox, ref=key)

    def add_comment(self, key: str, text: str, *, idempotency_key: str | None = None) -> Result:
        def live() -> Result:
            made = self._api("POST", f"/issue/{key}/comment", {"body": text}) or {}
            return Result(True, self.name, "add_comment", "live", key=key, url=self.browse_url(key),
                          data={"id": made.get("id")})

        def sandbox() -> Result:
            issue = self._recall(key)
            issue["comments"] = [*issue.get("comments", []), text]
            self._remember(key, "issue", issue)
            return Result(True, self.name, "add_comment", "sandbox", key=key, url=self._sandbox_url(key),
                          data={"comments": len(issue["comments"])})

        return self._call("add_comment", {"key": key, "body": text}, live=live, sandbox=sandbox,
                          idempotency_key=idempotency_key, ref=key)

    def transition(self, key: str, to_status: str, *, comment: str | None = None) -> Result:
        """Move an issue to the status named `to_status` (matched on the transition's
        target status or the transition's own name, case-insensitively)."""
        wanted = to_status.strip().lower()

        def live() -> Result:
            options = (self._api("GET", f"/issue/{key}/transitions") or {}).get("transitions", [])
            match = next((t for t in options if (t.get("to") or {}).get("name", "").lower() == wanted
                          or t.get("name", "").lower() == wanted), None)
            if match is None:
                names = ", ".join(sorted({(t.get("to") or {}).get("name", t.get("name", "")) for t in options}))
                raise ConnectorError(f"{key} cannot move to {to_status}; it can move to: {names or 'nothing'}")
            body: dict[str, Any] = {"transition": {"id": match["id"]}}
            if comment:
                body["update"] = {"comment": [{"add": {"body": comment}}]}
            self._api("POST", f"/issue/{key}/transitions", body)
            return Result(True, self.name, "transition", "live", key=key, url=self.browse_url(key),
                          data={"status": (match.get("to") or {}).get("name", to_status)})

        def sandbox() -> Result:
            issue = self._recall(key)
            issue["status"] = to_status.title() if wanted not in _DONE else "Done"
            if comment:
                issue["comments"] = [*issue.get("comments", []), comment]
            self._remember(key, "issue", issue)
            return Result(True, self.name, "transition", "sandbox", key=key, url=self._sandbox_url(key),
                          data={"status": issue["status"]})

        return self._call("transition", {"key": key, "to": to_status}, live=live, sandbox=sandbox, ref=key)

    def search(self, jql: str, *, limit: int = 50) -> Result:
        def live() -> Result:
            data = self._api("POST", "/search", {"jql": jql, "maxResults": limit,
                                                 "fields": ["summary", "status", "priority", "assignee", "labels", "updated"]}) or {}
            return Result(True, self.name, "search", "live",
                          data={"total": data.get("total", 0), "issues": [self._issue(i) for i in data.get("issues", [])]})

        def sandbox() -> Result:
            issues = self.store.objects(self.name, "issue")[-limit:]
            return Result(True, self.name, "search", "sandbox", data={"total": len(issues), "issues": issues})

        return self._call("search", {"jql": jql, "limit": limit}, live=live, sandbox=sandbox)
