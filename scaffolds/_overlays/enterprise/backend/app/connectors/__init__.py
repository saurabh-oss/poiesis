"""Enterprise connectors, platform-owned and read-only.

Every generated enterprise application carries these, and a story calls one instead
of writing HTTP, SMTP or webhook code of its own:

    from ..connectors import jira, servicenow, plane, email, slack, teams

    r = jira().create_issue("Checkout fails for EU cards", "14 reports since 09:10", idempotency_key=f"cluster-{c.id}")
    r.ok, r.key, r.url, r.mode, r.error      # SUP-104, its link, "sandbox" or "live"

With no credentials configured each one runs in its sandbox: nothing leaves the app,
every call is kept in the outbox (the Integrations screen shows it) and the stand-in
keeps state, so a demonstration works end to end on a laptop. Setting the connector's
environment variables makes the same call live. See each module for its settings.

An operation never raises for a remote failure: it returns a Result with ok=False and
an error a person can read, and a retryable failure is queued and tried again.
"""
from __future__ import annotations

from typing import Any

from .base import Connector, ConnectorError, MemoryStore, Result, Setting, redact, set_store, store
from .chat import Slack, Teams
from .jira import Jira
from .mail import Email
from .plane import Plane
from .servicenow import ServiceNow

CONNECTORS: dict[str, type[Connector]] = {c.name: c for c in (Jira, ServiceNow, Plane, Email, Slack, Teams)}


def jira() -> Jira:
    return Jira()


def servicenow() -> ServiceNow:
    return ServiceNow()


def plane() -> Plane:
    return Plane()


def email() -> Email:
    return Email()


def slack() -> Slack:
    return Slack()


def teams() -> Teams:
    return Teams()


def get(name: str) -> Connector:
    """A connector by name ("jira", "servicenow", "plane", "email", "slack", "teams")."""
    try:
        return CONNECTORS[name.lower()]()
    except KeyError:
        raise KeyError(f"no connector {name!r}; there are: {', '.join(CONNECTORS)}") from None


def catalogue() -> list[dict[str, Any]]:
    """Every connector with its mode and settings (secrets never shown)."""
    return [cls().status() for cls in CONNECTORS.values()]


def replay(event: dict[str, Any]) -> Result:
    """Run a failed or deferred outbox event again, from what it recorded.

    Used by the application's scheduler and by the Integrations screen's Retry. The
    recorded request is the one the operation was called with, secrets aside, and
    operations take their secrets from settings, so it is enough to call it again.
    """
    connector = get(event["connector"])
    request = dict(event.get("request") or {})
    op = event["operation"]
    key = event.get("idempotency_key")
    if isinstance(connector, Jira):
        if op == "create_issue":
            f = request.get("fields", {})
            return connector.create_issue(f.get("summary", ""), f.get("description", ""),
                                          issue_type=(f.get("issuetype") or {}).get("name"),
                                          priority=(f.get("priority") or {}).get("name"), labels=f.get("labels"),
                                          idempotency_key=key, ref=event.get("ref"))
        if op == "add_comment":
            return connector.add_comment(request["key"], request.get("body", ""), idempotency_key=key)
        if op == "transition":
            return connector.transition(request["key"], request["to"])
    if isinstance(connector, ServiceNow):
        if op == "create_incident":
            return connector.create_incident(request.get("short_description", ""), request.get("description", ""),
                                             urgency=int(request.get("urgency", 3)), impact=int(request.get("impact", 3)),
                                             category=request.get("category"), idempotency_key=key, ref=event.get("ref"))
        if op in ("update_incident", "resolve_incident"):
            number = request.pop("number")
            return connector.update_incident(number, request)
        if op == "add_work_note":
            number = request.pop("number")
            customer = "comments" in request
            return connector.add_work_note(number, request.get("comments") or request.get("work_notes") or "",
                                           customer_visible=customer)
    if isinstance(connector, Plane):
        if op == "create_work_item":
            return connector.create_work_item(request.get("name", ""), request.get("description_html", ""),
                                              priority=request.get("priority", "none"), idempotency_key=key,
                                              ref=event.get("ref"))
        if op == "add_comment":
            return connector.add_comment(request["id"], request.get("comment", ""), idempotency_key=key)
        if op == "move":
            return connector.move(request["id"], request["state"])
    if isinstance(connector, Email) and op == "send":
        return connector.send(request.get("to", []), request.get("subject", ""), request.get("text", ""),
                              html=request.get("html"), cc=request.get("cc"), reply_to=request.get("reply_to"),
                              idempotency_key=key, ref=event.get("ref"))
    if isinstance(connector, (Slack, Teams)) and op == "post":
        kwargs: dict[str, Any] = {"facts": request.get("facts"), "idempotency_key": key, "ref": event.get("ref")}
        if isinstance(connector, Slack):
            kwargs["channel"] = request.get("channel")
        return connector.post(request.get("title", ""), request.get("text", ""), **kwargs)
    return Result(False, connector.name, op, connector.mode, error=f"{op} cannot be replayed")


__all__ = [
    "CONNECTORS", "Connector", "ConnectorError", "MemoryStore", "Result", "Setting", "catalogue", "email", "get",
    "jira", "plane", "redact", "replay", "servicenow", "set_store", "slack", "store", "teams",
]
