"""ServiceNow (Table API). Written by Poiesis, and read-only.

    from ..connectors import servicenow
    r = servicenow().create_incident("Checkout outage: EU cards", "14 duplicate reports since 09:10",
                                     urgency=1, impact=2, category="software", idempotency_key=f"issue-{i.id}")
    if r.ok: issue.incident_number = r.key            # INC0010042

Live when SERVICENOW_INSTANCE is set with SERVICENOW_USERNAME and SERVICENOW_PASSWORD
(basic auth) or SERVICENOW_TOKEN (an OAuth bearer token). Incidents are the default
table; `query` reads any table the account may read.
"""
from __future__ import annotations

from typing import Any

from .base import Connector, ConnectorError, Result, Setting, basic_auth, http_json

SANDBOX_START = 10001
STATES = {"new": "1", "in progress": "2", "on hold": "3", "resolved": "6", "closed": "7", "canceled": "8"}
_STATE_NAMES = {v: k.title() for k, v in STATES.items()}


class ServiceNow(Connector):
    name = "servicenow"
    title = "ServiceNow"
    category = "Ticketing"
    description = "Raise, update, annotate and resolve ServiceNow incidents; query any table."
    vendor_url = "https://developer.servicenow.com/dev.do#!/reference/api/latest/rest/c_TableAPI"
    settings = (
        Setting("SERVICENOW_INSTANCE", "Instance URL", required=True, help="https://your-instance.service-now.com"),
        Setting("SERVICENOW_USERNAME", "Integration user"),
        Setting("SERVICENOW_PASSWORD", "Password", secret=True),
        Setting("SERVICENOW_TOKEN", "OAuth token", secret=True, help="Instead of user and password"),
        Setting("SERVICENOW_ASSIGNMENT_GROUP", "Default assignment group", help="sys_id or name"),
    )
    live_when_any = (("SERVICENOW_INSTANCE", "SERVICENOW_USERNAME", "SERVICENOW_PASSWORD"),
                     ("SERVICENOW_INSTANCE", "SERVICENOW_TOKEN"))
    operations = {
        "create_incident": "Raise an incident",
        "get_incident": "Read an incident by number",
        "update_incident": "Change an incident's fields",
        "add_work_note": "Add a work note (internal) or a comment (customer-visible)",
        "resolve_incident": "Resolve an incident with a close code and notes",
        "query": "Read records from any table with an encoded query",
    }

    def _base(self) -> str:
        instance = self.setting("SERVICENOW_INSTANCE").rstrip("/")
        return instance if instance.startswith("http") else f"https://{instance}.service-now.com"

    def _headers(self) -> dict[str, str]:
        if self.setting("SERVICENOW_TOKEN"):
            return {"Authorization": f"Bearer {self.setting('SERVICENOW_TOKEN')}"}
        return {"Authorization": basic_auth(self.setting("SERVICENOW_USERNAME"), self.setting("SERVICENOW_PASSWORD"))}

    def _api(self, method: str, path: str, body: Any = None) -> Any:
        data = http_json(method, f"{self._base()}/api/now{path}", headers=self._headers(), body=body)[1] or {}
        return data.get("result", data) if isinstance(data, dict) else data

    def record_url(self, number: str, sys_id: str | None = None, table: str = "incident") -> str:
        if self.mode != "live":
            return self._sandbox_url(number)
        return f"{self._base()}/nav_to.do?uri={table}.do?sys_id={sys_id}" if sys_id else \
            f"{self._base()}/nav_to.do?uri={table}_list.do?sysparm_query=number={number}"

    @staticmethod
    def _incident(row: dict[str, Any]) -> dict[str, Any]:
        state = str(row.get("state", ""))
        return {"number": row.get("number"), "sys_id": row.get("sys_id"),
                "short_description": row.get("short_description"),
                "state": _STATE_NAMES.get(state, state), "urgency": row.get("urgency"), "impact": row.get("impact"),
                "priority": row.get("priority"), "assigned_to": row.get("assigned_to"),
                "updated": row.get("sys_updated_on")}

    def _find(self, number: str) -> dict[str, Any]:
        rows = self._api("GET", f"/table/incident?sysparm_query=number={number}&sysparm_limit=1")
        if not rows:
            raise ConnectorError(f"ServiceNow has no incident {number}")
        return rows[0]

    # -- operations ----------------------------------------------------------------
    def create_incident(self, short_description: str, description: str = "", *, urgency: int = 3, impact: int = 3,
                        category: str | None = None, caller: str | None = None, assignment_group: str | None = None,
                        fields: dict[str, Any] | None = None, idempotency_key: str | None = None,
                        ref: str | None = None) -> Result:
        body = {"short_description": short_description[:160], "description": description,
                "urgency": str(urgency), "impact": str(impact),
                **({"category": category} if category else {}), **({"caller_id": caller} if caller else {}),
                **({"assignment_group": assignment_group or self.setting("SERVICENOW_ASSIGNMENT_GROUP")}
                   if (assignment_group or self.setting("SERVICENOW_ASSIGNMENT_GROUP")) else {}),
                **(fields or {})}

        def live() -> Result:
            row = self._api("POST", "/table/incident", body)
            number = row.get("number")
            if not number:
                raise ConnectorError(f"ServiceNow created nothing: {row}")
            return Result(True, self.name, "create_incident", "live", key=number,
                          url=self.record_url(number, row.get("sys_id")), data=self._incident(row))

        def sandbox() -> Result:
            number = f"INC{self.store.next_number(self.name, 'incident', SANDBOX_START):07d}"
            priority = str(min(5, max(1, (urgency + impact) - 1)))
            row = {"number": number, "sys_id": f"sbx{number.lower()}", "short_description": short_description,
                   "description": description, "state": "New", "urgency": str(urgency), "impact": str(impact),
                   "priority": priority, "category": category, "work_notes": [], "comments": []}
            self._remember(number, "incident", row)
            return Result(True, self.name, "create_incident", "sandbox", key=number, url=self._sandbox_url(number),
                          data={"number": number, "state": "New", "priority": priority})

        return self._call("create_incident", body, live=live, sandbox=sandbox, idempotency_key=idempotency_key, ref=ref)

    def get_incident(self, number: str) -> Result:
        def live() -> Result:
            row = self._find(number)
            return Result(True, self.name, "get_incident", "live", key=number,
                          url=self.record_url(number, row.get("sys_id")), data=self._incident(row))

        def sandbox() -> Result:
            return Result(True, self.name, "get_incident", "sandbox", key=number, url=self._sandbox_url(number),
                          data=self._recall(number))

        return self._call("get_incident", {"number": number}, live=live, sandbox=sandbox, ref=number)

    def update_incident(self, number: str, fields: dict[str, Any]) -> Result:
        def live() -> Result:
            row = self._api("PATCH", f"/table/incident/{self._find(number)['sys_id']}", fields)
            return Result(True, self.name, "update_incident", "live", key=number,
                          url=self.record_url(number, row.get("sys_id")), data=self._incident(row))

        def sandbox() -> Result:
            row = {**self._recall(number), **{k: v for k, v in fields.items() if k != "state"}}
            if "state" in fields:
                row["state"] = _STATE_NAMES.get(str(fields["state"]), str(fields["state"]).title())
            self._remember(number, "incident", row)
            return Result(True, self.name, "update_incident", "sandbox", key=number, url=self._sandbox_url(number),
                          data={"state": row.get("state")})

        return self._call("update_incident", {"number": number, **fields}, live=live, sandbox=sandbox, ref=number)

    def add_work_note(self, number: str, text: str, *, customer_visible: bool = False) -> Result:
        field = "comments" if customer_visible else "work_notes"

        def live() -> Result:
            self._api("PATCH", f"/table/incident/{self._find(number)['sys_id']}", {field: text})
            return Result(True, self.name, "add_work_note", "live", key=number, url=self.record_url(number))

        def sandbox() -> Result:
            row = self._recall(number)
            row[field] = [*row.get(field, []), text]
            self._remember(number, "incident", row)
            return Result(True, self.name, "add_work_note", "sandbox", key=number, url=self._sandbox_url(number),
                          data={field: len(row[field])})

        return self._call("add_work_note", {"number": number, field: text}, live=live, sandbox=sandbox, ref=number)

    def resolve_incident(self, number: str, close_notes: str, *, close_code: str = "Solved (Permanently)") -> Result:
        fields = {"state": STATES["resolved"], "close_code": close_code, "close_notes": close_notes}
        result = self.update_incident(number, fields)
        result.operation = "resolve_incident"
        return result

    def query(self, table: str, encoded_query: str = "", *, limit: int = 50, fields: list[str] | None = None) -> Result:
        def live() -> Result:
            params = f"sysparm_limit={limit}" + (f"&sysparm_query={encoded_query}" if encoded_query else "") \
                + (f"&sysparm_fields={','.join(fields)}" if fields else "")
            rows = self._api("GET", f"/table/{table}?{params}")
            return Result(True, self.name, "query", "live", data={"records": rows or []})

        def sandbox() -> Result:
            rows = self.store.objects(self.name, table if table != "incident" else "incident")[-limit:]
            return Result(True, self.name, "query", "sandbox", data={"records": rows})

        return self._call("query", {"table": table, "query": encoded_query}, live=live, sandbox=sandbox)
