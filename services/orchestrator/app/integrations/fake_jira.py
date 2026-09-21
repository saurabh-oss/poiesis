"""An in-memory Jira Cloud, strict in the places the real one is strict.

It exists so the tracker sync can be proved without a Jira site, a token or a
network — and, more usefully, so it can be proved against the ways real projects
differ: no Initiative type, a hierarchy that refuses initiative > epic, a story
points field missing from the create screen, a workflow with no direct path from
To Do to Done, one active sprint per board, a rate limit, a revoked token.
"""
from __future__ import annotations

import itertools
import json
import re
from typing import Any

import httpx

NEW, DOING, DONE = ("10000", "To Do", "new"), ("10001", "In Progress", "indeterminate"), ("10002", "Done", "done")


class FakeJira:
    def __init__(self, *, initiative: bool = True, hierarchy: bool = True,
                 points_on_screen: bool = True, scrum_board: bool = True,
                 rate_limit_first_create: bool = False, auth_ok: bool = True):
        self.initiative, self.hierarchy = initiative, hierarchy
        self.points_on_screen, self.scrum_board = points_on_screen, scrum_board
        self.rate_limit_first_create, self.auth_ok = rate_limit_first_create, auth_ok
        self.issues: dict[str, dict[str, Any]] = {}
        self.sprints: dict[int, dict[str, Any]] = {}
        self.comments: dict[str, list[dict[str, Any]]] = {}
        self.links: dict[str, dict[str, dict[str, Any]]] = {}
        self.calls: list[str] = []
        self._seq = itertools.count(1)
        self._sprint_seq = itertools.count(1)
        self.types = [
            {"id": "1", "name": "Story", "hierarchyLevel": 0, "subtask": False},
            {"id": "2", "name": "Task", "hierarchyLevel": 0, "subtask": False},
            {"id": "3", "name": "Epic", "hierarchyLevel": 1, "subtask": False},
            {"id": "5", "name": "Subtask", "hierarchyLevel": -1, "subtask": True},
        ] + ([{"id": "4", "name": "Initiative", "hierarchyLevel": 2, "subtask": False}] if initiative else [])

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    # helpers --------------------------------------------------------------------------

    def of_type(self, name: str) -> list[dict[str, Any]]:
        tid = next(t["id"] for t in self.types if t["name"] == name)
        return [i for i in self.issues.values() if i["issuetype"] == tid]

    def _level(self, type_id: str) -> int:
        return next(t["hierarchyLevel"] for t in self.types if t["id"] == type_id)

    @staticmethod
    def _json(status: int, body: Any = None, headers: dict[str, str] | None = None) -> httpx.Response:
        return httpx.Response(status, json=body, headers=headers) if body is not None \
            else httpx.Response(status, headers=headers)

    @staticmethod
    def _bad(errors: dict[str, str]) -> httpx.Response:
        return httpx.Response(400, json={"errorMessages": [], "errors": errors})

    @staticmethod
    def _is_adf(doc: Any) -> bool:
        return isinstance(doc, dict) and doc.get("type") == "doc" and doc.get("version") == 1 \
            and isinstance(doc.get("content"), list)

    # routing ----------------------------------------------------------------------------

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        self.calls.append(f"{method} {path}")
        if not self.auth_ok:
            return httpx.Response(401, text="Client must be authenticated to access this resource.")
        body = json.loads(request.content) if request.content else {}

        if path == "/rest/api/3/myself":
            return self._json(200, {"displayName": "Poiesis Bot", "emailAddress": "bot@example.com"})
        if m := re.fullmatch(r"/rest/api/3/project/(\w+)", path):
            return self._json(200, {"id": "10000", "key": m.group(1), "name": "Helix", "simplified": False,
                                    "issueTypes": self.types})
        if path == "/rest/api/3/field":
            return self._json(200, [{"id": "summary", "name": "Summary"},
                                    {"id": "customfield_10016", "name": "Story point estimate"}])
        if path == "/rest/agile/1.0/board":
            return self._json(200, {"values": [{"id": 7, "name": "HEL board", "type": "scrum"}]
                                    if self.scrum_board else []})
        if path == "/rest/api/3/search/jql":
            label = re.search(r'labels = "([^"]+)"', body.get("jql", ""))
            hits = [{"id": i["id"], "key": k} for k, i in self.issues.items()
                    if label and label.group(1) in i["labels"]]
            return self._json(200, {"issues": hits})
        if path == "/rest/api/3/issue" and method == "POST":
            return self._create(body["fields"])
        if m := re.fullmatch(r"/rest/api/3/issue/([A-Z]+-\d+)", path):
            issue = self.issues.get(m.group(1))
            if issue is None:
                return self._json(404, {"errorMessages": ["Issue does not exist"]})
            if method == "PUT":
                for op in body.get("update", {}).get("labels", []):
                    if "add" in op and op["add"] not in issue["labels"]:
                        issue["labels"].append(op["add"])
                return self._json(204)
            _, name, cat = issue["status"]
            return self._json(200, {"key": m.group(1), "fields": {"status": {
                "name": name, "statusCategory": {"key": cat}}}})
        if m := re.fullmatch(r"/rest/api/3/issue/([A-Z]+-\d+)/transitions", path):
            issue = self.issues[m.group(1)]
            # To Do -> In Progress -> Done; no direct To Do -> Done, as in many real workflows.
            nxt = {NEW[0]: [DOING], DOING[0]: [DONE, NEW], DONE[0]: [DOING]}[issue["status"][0]]
            if method == "GET":
                return self._json(200, {"transitions": [
                    {"id": f"t{s[0]}", "name": s[1], "to": {"statusCategory": {"key": s[2]}}} for s in nxt]})
            target = body["transition"]["id"][1:]
            chosen = next((s for s in nxt if s[0] == target), None)
            if chosen is None:
                return self._bad({"transition": "Transition is not valid from this status"})
            issue["status"] = chosen
            return self._json(204)
        if m := re.fullmatch(r"/rest/api/3/issue/([A-Z]+-\d+)/comment", path):
            if not self._is_adf(body.get("body")):
                return self._bad({"comment": "Comment body is not valid ADF"})
            self.comments.setdefault(m.group(1), []).append(body["body"])
            return self._json(201, {"id": str(next(self._seq))})
        if m := re.fullmatch(r"/rest/api/3/issue/([A-Z]+-\d+)/remotelink", path):
            self.links.setdefault(m.group(1), {})[body["globalId"]] = body["object"]
            return self._json(201, {"id": 1})
        if m := re.fullmatch(r"/rest/agile/1.0/board/(\d+)/sprint", path):
            states = request.url.params.get("state", "").split(",")
            return self._json(200, {"values": [s for s in self.sprints.values() if s["state"] in states]})
        if path == "/rest/agile/1.0/sprint" and method == "POST":
            if len(body.get("name", "")) > 30:
                return self._bad({"name": "Sprint name must be 30 characters or fewer"})
            sid = next(self._sprint_seq)
            self.sprints[sid] = {"id": sid, "name": body["name"], "goal": body.get("goal", ""),
                                 "state": "future", "issues": []}
            return self._json(201, self.sprints[sid])
        if m := re.fullmatch(r"/rest/agile/1.0/sprint/(\d+)/issue", path):
            sprint = self.sprints[int(m.group(1))]
            for key in body["issues"]:
                if key not in sprint["issues"]:
                    sprint["issues"].append(key)
            return self._json(204)
        if m := re.fullmatch(r"/rest/agile/1.0/sprint/(\d+)", path):
            sprint = self.sprints[int(m.group(1))]
            want = body.get("state")
            if want == "active":
                if any(s["state"] == "active" for s in self.sprints.values()):
                    return self._bad({"state": "There is already an active sprint on this board"})
                if not (body.get("startDate") and body.get("endDate")):
                    return self._bad({"startDate": "A sprint needs start and end dates to start"})
            if want == "closed" and sprint["state"] != "active":
                return self._bad({"state": "Only an active sprint can be closed"})
            sprint["state"] = want
            return self._json(200, sprint)
        return self._json(404, {"errorMessages": [f"fake Jira has no route {method} {path}"]})

    def _create(self, fields: dict[str, Any]) -> httpx.Response:
        if self.rate_limit_first_create:
            self.rate_limit_first_create = False
            return httpx.Response(429, headers={"Retry-After": "0"}, text="Rate limit exceeded")
        errors: dict[str, str] = {}
        if not str(fields.get("summary", "")).strip():
            errors["summary"] = "You must specify a summary of the issue."
        if not self._is_adf(fields.get("description")):
            errors["description"] = "Operation value must be an Atlassian Document"
        if any(" " in label for label in fields.get("labels", [])):
            errors["labels"] = "Labels cannot contain spaces"
        if "customfield_10016" in fields and not self.points_on_screen:
            errors["customfield_10016"] = ("Field 'customfield_10016' cannot be set. It is not on "
                                           "the appropriate screen, or unknown.")
        type_id = fields["issuetype"]["id"]
        if parent := fields.get("parent"):
            p = self.issues.get(parent["key"])
            if p is None:
                errors["parent"] = "The parent issue does not exist"
            elif self._level(p["issuetype"]) != self._level(type_id) + 1 or (
                    self._level(type_id) == 1 and not self.hierarchy):
                errors["parent"] = "Given parent issue does not belong to appropriate hierarchy."
        if errors:
            return self._bad(errors)
        n = next(self._seq)
        key = f"{fields['project']['key']}-{n}"
        self.issues[key] = {"id": str(10000 + n), "key": key, "issuetype": type_id,
                            "summary": fields["summary"], "description": fields["description"],
                            "labels": list(fields.get("labels", [])),
                            "parent": (fields.get("parent") or {}).get("key"),
                            "points": fields.get("customfield_10016"), "status": NEW}
        return self._json(201, {"id": self.issues[key]["id"], "key": key,
                                "self": f"https://fake/rest/api/3/issue/{key}"})
