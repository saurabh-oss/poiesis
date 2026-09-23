"""Demonstration data from a declarative spec, expanded by the platform.

The Data Designer was first asked for a Python generator. A local model got it
right about one time in three: an apostrophe inside a single-quoted string, a
keyword argument its own function did not take, and — most often — the rows
written out as literals until the reply was cut off. Each failure cost minutes.

So the model now writes a *spec*, decoded under a JSON schema so it cannot be
malformed, and this module turns it into rows: catalogues of realistic text,
weighted choices, references between tables, time windows, look-ups, and a few
built-in generators (names, companies, e-mails) so the model spends its tokens
on the words only a person can write. Nothing here can raise a SyntaxError.

    {
      "tables": [
        {"table": "agent", "count": 5,
         "columns": {"name": {"kind": "person_name"}}},
        {"table": "customer", "count": 25,
         "columns": {"name": {"kind": "company_name"},
                     "plan": {"kind": "choices", "choices": {"Free": 5, "Business": 3, "Enterprise": 2}}}},
        {"table": "ticket", "count": 150,
         "records": [{"subject": "Charged twice for the March invoice",
                      "body": "My card shows two charges of $249 on 3 March...",
                      "product_line": "Billing"}, ...],
         "columns": {"customer_id": {"kind": "ref", "table": "customer"},
                     "customer_name": {"kind": "lookup", "via": "customer_id", "field": "name"},
                     "status": {"kind": "choices", "choices": {"open": 4, "triaged": 5, "resolved": 3}},
                     "priority": {"kind": "choices", "choices": {"P1": 1, "P2": 3, "P3": 5, "P4": 2}},
                     "arrival_time": {"kind": "time", "days_back": 30},
                     "triaged_at": {"kind": "time", "after": "arrival_time", "hours_min": 0.2, "hours_max": 8,
                                    "only_when": {"column": "status", "in": ["triaged", "resolved"]}},
                     "assignee_id": {"kind": "ref", "table": "agent",
                                     "only_when": {"column": "status", "in": ["triaged", "resolved"]}}}}
      ]
    }

A row starts from one of the table's `records` (each used at least once, then
reused with fresh generated columns), and every other column comes from its
spec. Ids are 1..N in order; a `ref` is a 1-based id into a table generated
earlier in the list.
"""
from __future__ import annotations

import datetime as dt
import random
import re
from typing import Any

SPEC_FILE = "db/seed_spec.json"

KINDS = ["catalogue", "choices", "ref", "lookup", "time", "date", "int", "float", "bool", "const",
         "person_name", "company_name", "email", "sequence", "text"]

FIRST_NAMES = [
    "Priya", "Tomasz", "Aisha", "Diego", "Mei", "Lars", "Fatima", "Noah", "Ines", "Kwame", "Hana", "Mateo",
    "Zara", "Ivan", "Leila", "Ravi", "Sofia", "Kenji", "Amara", "Jonas", "Nadia", "Omar", "Elena", "Tariq",
    "Greta", "Luca", "Yuki", "Samuel", "Chloe", "Arjun", "Maya", "Felix", "Rosa", "Dmitri", "Ayesha", "Ben",
    "Camila", "Hugo", "Ingrid", "Malik", "Nora", "Oscar", "Parvati", "Quinn", "Rania", "Stefan", "Talia", "Umar",
    "Vera", "Wei", "Ximena", "Yara", "Zain", "Anika", "Bruno", "Dalia", "Emil", "Farah", "Gabriel", "Hiro",
]
LAST_NAMES = [
    "Nair", "Kowalski", "Okafor", "Ramirez", "Chen", "Berg", "Haddad", "Fischer", "Costa", "Mensah", "Sato",
    "Rossi", "Patel", "Petrov", "Karimi", "Iyer", "Almeida", "Tanaka", "Diallo", "Lindqvist", "Hussain",
    "Farouk", "Novak", "Rahman", "Weber", "Moretti", "Nakamura", "Osei", "Dubois", "Sharma", "Silva",
    "Andersen", "Vargas", "Volkov", "Khan", "Murphy", "Herrera", "Schmidt", "Larsen", "Abdi", "Jensen",
    "Ortega", "Reddy", "Doyle", "Mahmoud", "Novotny", "Ferreira", "Yilmaz", "Nilsson", "Zhang", "Delgado",
]
COMPANY_A = [
    "Northwind", "Halcyon", "Brightpath", "Cobalt", "Meridian", "Larkspur", "Summit", "Harbor", "Quartz",
    "Evergreen", "Beacon", "Atlas", "Juniper", "Vantage", "Orchard", "Pioneer", "Redwood", "Silverline",
    "Tidewater", "Umbra", "Vertex", "Willowbrook", "Zenith", "Arcadia", "Bluefin", "Crestline", "Dunmore",
    "Elmhurst", "Falcon", "Granite",
]
COMPANY_B = [
    "Logistics", "Health", "Learning", "Analytics", "Foods", "Robotics", "Partners", "Media", "Labs",
    "Energy", "Financial", "Systems", "Studios", "Freight", "Retail", "Insurance", "Mobility", "Bank",
    "Software", "Hospitality", "Biotech", "Consulting", "Textiles", "Marine", "Aviation", "Ventures",
]


def spec_schema(tables: list[str]) -> dict[str, Any]:
    """The JSON schema the Data Designer's reply is decoded under."""
    condition = {"type": "object", "properties": {
        "column": {"type": "string"}, "in": {"type": "array", "items": {"type": ["string", "number", "boolean", "null"]}}},
        "required": ["column", "in"]}
    column = {"type": "object", "properties": {
        "kind": {"type": "string", "enum": KINDS},
        "values": {"type": "array", "items": {"type": ["string", "number", "boolean", "null"]}},
        "unique": {"type": "boolean"},
        "choices": {"type": "object", "additionalProperties": {"type": "number"}},
        "table": {"type": "string"},
        "via": {"type": "string"}, "field": {"type": "string"},
        "days_back": {"type": "number"}, "after": {"type": "string"},
        "hours_min": {"type": "number"}, "hours_max": {"type": "number"},
        "min": {"type": "number"}, "max": {"type": "number"}, "decimals": {"type": "integer"},
        "true_share": {"type": "number"}, "null_share": {"type": "number"},
        "value": {"type": ["string", "number", "boolean", "null"]},
        "prefix": {"type": "string"}, "start": {"type": "integer"},
        "from": {"type": "string"},
        "only_when": condition,
    }, "required": ["kind"]}
    table = {"type": "object", "properties": {
        "table": {"type": "string", "enum": tables} if tables else {"type": "string"},
        "count": {"type": "integer", "minimum": 0},
        "records": {"type": "array", "items": {"type": "object",
                                                "additionalProperties": {"type": ["string", "number", "boolean", "null"]}}},
        "columns": {"type": "object", "additionalProperties": column},
    }, "required": ["table", "count", "columns"]}
    return {"type": "object", "properties": {
        "tables": {"type": "array", "items": table},
        "reasoning": {"type": "string"},
    }, "required": ["tables"]}


SPEC_CONTRACT = """\
THE SPEC YOU WRITE (JSON, one entry per table that needs rows, in dependency order — a table
after the tables it references):
  {"tables": [{"table": "<name>", "count": <rows>, "records": [...], "columns": {...}}], "reasoning": "..."}

`records`: a catalogue of partial rows, the words only a person can write — for tickets, 30-40
objects each with its subject, body (two or three sentences the customer would write) and product
line; for incidents, one object per incident with its title and status. Every record is used at
least once; when count is larger, records are reused with fresh generated columns (other
customers, other dates), so 40 records make 150 distinct-looking rows. Near-duplicate clusters:
3-6 records describing the same problem in different words with the same "incident_id" (the
1-based position of that incident in the incident table's records).

`columns`: how every column NOT covered by the records is filled. One spec per column, `kind`:
  catalogue     {"kind":"catalogue","values":["Billing","Mobile App"],"unique":false}   pick from the list ("unique": in order, no repeats)
  choices       {"kind":"choices","choices":{"open":4,"triaged":5,"resolved":3}}         weighted pick — the weights are the shape of the data
  ref           {"kind":"ref","table":"agent","null_share":0.4}                          a 1-based id of a row in an earlier table; None on a share
  lookup        {"kind":"lookup","via":"customer_id","field":"name"}                     copy a field from the row a ref column points at
  time          {"kind":"time","days_back":30}                                           a timestamp in the last N days, spread evenly
                {"kind":"time","after":"arrival_time","hours_min":0.2,"hours_max":8}     a timestamp after another column of the same row
  date          {"kind":"date","days_back":90}                                           a date
  int / float   {"kind":"int","min":1,"max":5}  {"kind":"float","min":0,"max":100,"decimals":2}
  bool          {"kind":"bool","true_share":0.15}
  const         {"kind":"const","value":"open"}
  person_name   {"kind":"person_name"}     company_name {"kind":"company_name"}     email {"kind":"email","from":"name"}
  sequence      {"kind":"sequence","prefix":"INV-","start":20400}                        INV-20400, INV-20401, …
  text          {"kind":"text","values":["…","…"]}                                      like catalogue, for longer prose
Any spec may add "only_when": {"column":"status","in":["triaged","resolved"]} — the value is None unless
that other column of the same row has one of those values; and "null_share": 0.3 — None on that share.

RULES: never include "id". Every NOT NULL column without a DEFAULT needs a record value or a column
spec. Use only column names the tables define. Counts must meet what the brief asks for. The shape
matters: a queue needs untriaged, unassigned rows (status open, assignee None, triaged_at None) on a
real share; a status board needs rows in every status; an incident with linked tickets needs
tickets whose incident_id points at it.
"""


def _weighted(rng: random.Random, choices: dict[str, float]) -> Any:
    items = [(k, float(v)) for k, v in choices.items() if float(v) > 0]
    if not items:
        return None
    total = sum(w for _, w in items)
    r = rng.uniform(0, total)
    upto = 0.0
    for k, w in items:
        upto += w
        if r <= upto:
            return k
    return items[-1][0]


def _person(rng: random.Random) -> str:
    return f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"


def _company(rng: random.Random) -> str:
    return f"{rng.choice(COMPANY_A)} {rng.choice(COMPANY_B)}"


def _email(name: str, rng: random.Random) -> str:
    slug = re.sub(r"[^a-z]+", ".", str(name or "user").lower()).strip(".") or "user"
    return f"{slug}@{rng.choice(COMPANY_A).lower()}.example.com"


def _iso(t: dt.datetime) -> str:
    return t.replace(microsecond=0).isoformat()


def _condition_holds(row: dict[str, Any], cond: dict[str, Any] | None) -> bool:
    if not cond:
        return True
    return row.get(cond.get("column")) in list(cond.get("in") or [])


class _Expander:
    def __init__(self, spec: dict[str, Any], tables: dict[str, dict[str, bool]], seed: int = 42):
        self.spec = spec
        self.tables = tables
        self.rng = random.Random(seed)
        self.now = dt.datetime.now(dt.timezone.utc)
        self.rows: dict[str, list[dict[str, Any]]] = {}
        self.issues: list[str] = []
        self.specs: dict[str, dict[str, dict[str, Any]]] = {}

    def run(self) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
        for entry in self.spec.get("tables") or []:
            self._table(entry)
        return self.rows, list(dict.fromkeys(self.issues))

    def _table(self, entry: dict[str, Any]) -> None:
        name = str(entry.get("table") or "").lower()
        if name not in self.tables:
            self.issues.append(f"`{name}` is not a table in db/init.sql (tables: {', '.join(sorted(self.tables))})")
            return
        count = int(entry.get("count") or 0)
        records = [r for r in (entry.get("records") or []) if isinstance(r, dict)]
        columns: dict[str, dict[str, Any]] = {k: v for k, v in (entry.get("columns") or {}).items() if isinstance(v, dict)}
        self.specs[name] = columns
        spec_cols = self.tables[name]
        for col in list(columns) + [k for r in records for k in r]:
            if col.lower() not in spec_cols and col != "id":
                self.issues.append(f"{name}: `{col}` is not a column of its CREATE TABLE (columns: {', '.join(spec_cols)})")
        covered = set(columns) | {k for r in records for k in r}
        for col, required in spec_cols.items():
            if required and col not in covered and col != "id":
                self.issues.append(f"{name}.{col} is NOT NULL and has neither a record value nor a column spec")
        if count <= 0:
            return
        if count < len(records):
            count = len(records)
        out: list[dict[str, Any]] = []
        unique_pos: dict[str, int] = {}
        seq_pos: dict[str, int] = {}
        for i in range(count):
            row: dict[str, Any] = {}
            if records:
                row.update(records[i] if i < len(records) else self.rng.choice(records))
            row.pop("id", None)
            pending = [c for c in columns if c not in row]
            for _ in range(4):  # dependent specs (after / via / from) resolve in later passes
                still: list[str] = []
                for col in pending:
                    ok, value = self._value(name, col, columns[col], row, unique_pos, seq_pos, len(out) + 1)
                    if ok:
                        row[col] = value
                    else:
                        still.append(col)
                pending = still
                if not pending:
                    break
            for col in pending:
                self.issues.append(f"{name}.{col}: its spec depends on a column that has no value")
                row[col] = None
            out.append(row)
        self.rows[name] = out

    def _value(self, table: str, col: str, spec: dict[str, Any], row: dict[str, Any],
               unique_pos: dict[str, int], seq_pos: dict[str, int], row_no: int) -> tuple[bool, Any]:
        """(resolved?, value). Unresolved means a dependency column has no value yet."""
        kind = str(spec.get("kind") or "")
        cond = spec.get("only_when")
        if cond and cond.get("column") not in row and cond.get("column") in self.specs.get(table, {}):
            return False, None
        if not _condition_holds(row, cond):
            return True, None
        share = spec.get("null_share")
        if share and self.rng.random() < float(share):
            return True, None
        rng = self.rng
        if kind in ("catalogue", "text"):
            values = list(spec.get("values") or [])
            if not values:
                self.issues.append(f"{table}.{col}: a catalogue needs `values`")
                return True, None
            if spec.get("unique"):
                pos = unique_pos.get(col, 0)
                unique_pos[col] = pos + 1
                return True, values[pos % len(values)]
            return True, rng.choice(values)
        if kind == "choices":
            choices = spec.get("choices") or {}
            if not choices:
                self.issues.append(f"{table}.{col}: `choices` needs value: weight pairs")
                return True, None
            return True, _weighted(rng, choices)
        if kind == "ref":
            target = str(spec.get("table") or "").lower()
            n = len(self.rows.get(target) or [])
            if n == 0:
                self.issues.append(f"{table}.{col}: refers to `{target}`, which has no rows yet — put that "
                                   "table earlier in the list")
                return True, None
            return True, rng.randint(1, n)
        if kind == "lookup":
            via, field = str(spec.get("via") or ""), str(spec.get("field") or "")
            if via not in row:
                return False, None
            ref_id = row.get(via)
            if ref_id is None:
                return True, None
            target = str((self.specs.get(table, {}).get(via) or {}).get("table") or "").lower()
            rows = self.rows.get(target) or []
            if not target or not (1 <= int(ref_id) <= len(rows)):
                self.issues.append(f"{table}.{col}: lookup via `{via}` needs `{via}` to be a ref to an earlier table")
                return True, None
            return True, rows[int(ref_id) - 1].get(field)
        if kind in ("time", "date"):
            after = spec.get("after")
            if after:
                if after not in row:
                    return False, None
                base_raw = row.get(after)
                if base_raw is None:
                    return True, None
                try:
                    base = dt.datetime.fromisoformat(str(base_raw).replace("Z", "+00:00"))
                except ValueError:
                    return True, None
                if base.tzinfo is None:
                    base = base.replace(tzinfo=dt.timezone.utc)
                hours = rng.uniform(float(spec.get("hours_min", 0.1)), float(spec.get("hours_max", 24)))
                t = base + dt.timedelta(hours=hours)
            else:
                days = float(spec.get("days_back", 30))
                t = self.now - dt.timedelta(hours=rng.uniform(0, days * 24))
            if kind == "date":
                return True, t.date().isoformat()
            return True, _iso(t)
        if kind == "int":
            return True, rng.randint(int(spec.get("min", 0)), int(spec.get("max", 100)))
        if kind == "float":
            return True, round(rng.uniform(float(spec.get("min", 0)), float(spec.get("max", 100))), int(spec.get("decimals", 2)))
        if kind == "bool":
            return True, rng.random() < float(spec.get("true_share", 0.5))
        if kind == "const":
            return True, spec.get("value")
        if kind == "person_name":
            return True, _person(rng)
        if kind == "company_name":
            return True, _company(rng)
        if kind == "email":
            src = spec.get("from")
            if src and src not in row:
                return False, None
            return True, _email(row.get(src) if src else _person(rng), rng)
        if kind == "sequence":
            pos = seq_pos.get(col, int(spec.get("start", 1)))
            seq_pos[col] = pos + 1
            return True, f"{spec.get('prefix', '')}{pos}"
        self.issues.append(f"{table}.{col}: unknown kind `{kind}`")
        return True, None


def expand_spec(spec: dict[str, Any], tables: dict[str, dict[str, bool]], seed: int = 42,
                ) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    """Rows per table from a spec, and what is wrong with the spec."""
    if not isinstance(spec, dict) or not isinstance(spec.get("tables"), list):
        return {}, ["the spec must be an object with a `tables` list"]
    return _Expander(spec, tables, seed).run()
