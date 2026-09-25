"""The contract every connector keeps. Written by Poiesis, and read-only.

A connector is one external system (Jira, ServiceNow, Plane, e-mail, Slack, Teams)
behind a small set of named operations. Every operation goes through `_call`, which
gives all of them the same behaviour:

  mode       live when the connector's required settings are present, sandbox when
             they are not, off when <NAME>_MODE=off. <NAME>_MODE=sandbox forces the
             sandbox even with credentials, for a demo on a machine that has them.
  sandbox    nothing leaves the application. The call is recorded in the outbox and
             answered by a stand-in that keeps state, so an issue created in the
             Jira sandbox can be read, commented on and transitioned afterwards.
  outbox     every call, live or sandbox, is one event: what was asked (secrets
             removed), what came back, how many attempts, and the error if any.
  retries    a timeout, a refused connection, 429 or 5xx is retried with backoff
             (Retry-After honoured, capped), up to three attempts in the request.
             A call that still fails is kept as `failed` with `retry_at`, and the
             application's scheduler tries it again later.
  idempotent an operation given an idempotency key runs once: asking again returns
             the first result instead of creating a second ticket.
  breaker    after five consecutive failures a connector stops calling out for a
             minute and records calls as `deferred`, so one dead system does not
             slow every request that touches it.

Only the standard library is used, so the connectors add nothing to an image and
behave the same in tests, in the sandbox and in production.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Protocol

MAX_ATTEMPTS = 3
BREAKER_THRESHOLD = 5
BREAKER_SECONDS = 60
RETRY_LATER_SECONDS = 300
_SECRET = re.compile(r"pass|secret|token|api[_-]?key|authorization|cookie|webhook", re.I)


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


# --------------------------------------------------------------------------- results

@dataclass
class Result:
    """What an operation returns, live or sandbox. `key` is the remote identifier a
    person recognises (SUP-42, INC0010042, a message id); `url` opens it."""
    ok: bool
    connector: str
    operation: str
    mode: str
    key: str | None = None
    url: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    event_id: int | None = None
    replayed: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class ConnectorError(Exception):
    """A failed call. `retryable` says whether trying again could succeed."""

    def __init__(self, message: str, *, status: int | None = None, retryable: bool = False,
                 retry_after: float | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable
        self.retry_after = retry_after


@dataclass(frozen=True)
class Setting:
    env: str
    label: str
    required: bool = False
    secret: bool = False
    default: str = ""
    help: str = ""


# --------------------------------------------------------------------------- the outbox

class Store(Protocol):
    def find_sent(self, connector: str, operation: str, idempotency_key: str) -> dict[str, Any] | None: ...
    def record(self, event: dict[str, Any]) -> int: ...
    def update(self, event_id: int, **fields: Any) -> None: ...
    def get_object(self, connector: str, key: str) -> dict[str, Any] | None: ...
    def put_object(self, connector: str, key: str, kind: str, data: dict[str, Any]) -> None: ...
    def objects(self, connector: str, kind: str | None = None) -> list[dict[str, Any]]: ...
    def next_number(self, connector: str, scope: str, start: int) -> int: ...


class MemoryStore:
    """The outbox when no database is attached: tests, scripts, the data service."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.remote: dict[tuple[str, str], dict[str, Any]] = {}
        self.counters: dict[tuple[str, str], int] = {}
        self._lock = threading.Lock()

    def find_sent(self, connector, operation, idempotency_key):
        for e in reversed(self.events):
            if (e["connector"], e["operation"], e.get("idempotency_key")) == (connector, operation, idempotency_key) \
                    and e.get("status") == "sent":
                return e
        return None

    def record(self, event):
        with self._lock:
            event = {**event, "id": len(self.events) + 1}
            self.events.append(event)
            return event["id"]

    def update(self, event_id, **fields):
        self.events[event_id - 1].update(fields)

    def get_object(self, connector, key):
        found = self.remote.get((connector, key))
        return dict(found["data"]) if found else None

    def put_object(self, connector, key, kind, data):
        self.remote[(connector, key)] = {"kind": kind, "data": dict(data)}

    def objects(self, connector, kind=None):
        return [dict(v["data"]) for (c, _), v in self.remote.items() if c == connector and (kind is None or v["kind"] == kind)]

    def next_number(self, connector, scope, start):
        with self._lock:
            n = self.counters.get((connector, scope), start - 1) + 1
            self.counters[(connector, scope)] = n
            return n


_store: Store = MemoryStore()


def set_store(store: Store) -> None:
    """The kernel attaches its database-backed outbox here at start-up."""
    global _store
    _store = store


def store() -> Store:
    return _store


def redact(value: Any) -> Any:
    """A copy with every secret-looking field replaced, for the outbox and the logs."""
    if isinstance(value, dict):
        return {k: ("•••" if _SECRET.search(str(k)) and v not in (None, "") else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


# --------------------------------------------------------------------------- HTTP

def http_json(method: str, url: str, *, headers: dict[str, str] | None = None, body: Any = None,
              timeout: float = 15) -> tuple[int, Any]:
    """One JSON request. Raises ConnectorError, retryable for 429, 5xx and network errors."""
    data = None
    hdrs = {"Accept": "application/json", "User-Agent": "poiesis-connectors/1.0", **(headers or {})}
    if body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        hdrs.setdefault("Content-Type", "application/json")
    request = urllib.request.Request(url, data=data, method=method.upper(), headers=hdrs)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        raw = exc.read() if hasattr(exc, "read") else b""
        detail = raw.decode(errors="replace")[:500]
        after = exc.headers.get("Retry-After") if exc.headers else None
        raise ConnectorError(f"{method.upper()} {_host(url)} answered {exc.code}: {detail}", status=exc.code,
                             retryable=exc.code == 429 or exc.code >= 500,
                             retry_after=float(after) if after and after.replace(".", "", 1).isdigit() else None) from None
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise ConnectorError(f"{method.upper()} {_host(url)} unreachable: {reason}", retryable=True) from None
    text = raw.decode(errors="replace")
    if not text.strip():
        return status, None
    try:
        return status, json.loads(text)
    except ValueError:
        return status, text


def _host(url: str) -> str:
    return urllib.parse.urlsplit(url).netloc or url


def basic_auth(user: str, secret: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{secret}".encode()).decode()


# --------------------------------------------------------------------------- the base class

class Connector:
    name = "base"
    title = "Connector"
    category = ""
    description = ""
    vendor_url = ""
    settings: tuple[Setting, ...] = ()
    # Settings of which at least one group must be complete for live mode, when there
    # is a choice (a webhook URL, or a bot token and a channel). Empty: every
    # required setting.
    live_when_any: tuple[tuple[str, ...], ...] = ()
    operations: dict[str, str] = {}

    _breakers: dict[str, dict[str, float]] = {}

    def __init__(self, env: dict[str, str] | None = None, store_: Store | None = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self._env = env
        self._store = store_
        self._sleep = sleep

    # -- configuration ---------------------------------------------------------
    @property
    def store(self) -> Store:
        return self._store or store()

    def env(self, key: str, default: str = "") -> str:
        source = self._env if self._env is not None else os.environ
        value = source.get(key)
        return value.strip() if isinstance(value, str) and value.strip() else default

    def setting(self, key: str) -> str:
        for s in self.settings:
            if s.env == key:
                return self.env(key, s.default)
        return self.env(key)

    def missing(self) -> list[str]:
        if self.live_when_any:
            groups = [[k for k in group if not self.setting(k)] for group in self.live_when_any]
            best = min(groups, key=len)
            return best
        return [s.env for s in self.settings if s.required and not self.setting(s.env)]

    @property
    def mode(self) -> str:
        forced = self.env(f"{self.name.upper()}_MODE").lower()
        if forced in ("off", "sandbox"):
            return forced
        if forced == "live":
            return "live" if not self.missing() else "sandbox"
        return "live" if not self.missing() else "sandbox"

    def status(self) -> dict[str, Any]:
        """For the Integrations screen: what this connector is, how it is set up."""
        return {
            "name": self.name, "title": self.title, "category": self.category,
            "description": self.description, "vendor_url": self.vendor_url,
            "mode": self.mode, "missing": self.missing(),
            "settings": [{"env": s.env, "label": s.label, "required": s.required, "secret": s.secret,
                          "set": bool(self.env(s.env)),  # given explicitly, not a default
                          "value": ("•••" if s.secret else self.setting(s.env)) if self.setting(s.env) else "",
                          "help": s.help} for s in self.settings],
            "operations": self.operations,
            "breaker_open": self._breaker_open(),
        }

    # -- the breaker -----------------------------------------------------------
    def _breaker(self) -> dict[str, float]:
        return Connector._breakers.setdefault(self.name, {"failures": 0, "open_until": 0.0})

    def _breaker_open(self) -> bool:
        return self._breaker()["open_until"] > time.time()

    # -- the call --------------------------------------------------------------
    def _call(self, operation: str, payload: dict[str, Any], *,
              live: Callable[[], Result | dict[str, Any]], sandbox: Callable[[], Result | dict[str, Any]],
              idempotency_key: str | None = None, ref: str | None = None) -> Result:
        mode = self.mode
        if mode == "off":
            return Result(False, self.name, operation, "off",
                          error=f"{self.title} is switched off ({self.name.upper()}_MODE=off)")
        if idempotency_key:
            prior = self.store.find_sent(self.name, operation, idempotency_key)
            if prior:
                response = prior.get("response") or {}
                return Result(True, self.name, operation, prior.get("mode") or mode,
                              key=prior.get("remote_key"), url=prior.get("url"),
                              data=response if isinstance(response, dict) else {"response": response},
                              event_id=prior.get("id"), replayed=True)
        event_id = self.store.record({
            "connector": self.name, "operation": operation, "mode": mode, "status": "pending",
            "request": redact(payload), "idempotency_key": idempotency_key, "ref": ref,
            "attempts": 0, "created_at": now(),
        })
        if mode == "live" and self._breaker_open():
            self.store.update(event_id, status="deferred", error=f"{self.title} is failing; calls paused for a minute",
                              retry_at=now() + dt.timedelta(seconds=BREAKER_SECONDS))
            return Result(False, self.name, operation, mode, event_id=event_id,
                          error=f"{self.title} is failing repeatedly; the call is queued and will be retried")
        attempts, last_error = 0, None
        runner = live if mode == "live" else sandbox
        while attempts < (MAX_ATTEMPTS if mode == "live" else 1):
            attempts += 1
            try:
                out = runner()
                result = out if isinstance(out, Result) else Result(True, self.name, operation, mode, data=out or {})
                result.connector, result.operation, result.mode, result.event_id = self.name, operation, mode, event_id
                self._breaker()["failures"] = 0
                self.store.update(event_id, status="sent" if result.ok else "failed", attempts=attempts,
                                  response=result.data, remote_key=result.key, url=result.url, error=result.error,
                                  sent_at=now())
                return result
            except ConnectorError as exc:
                last_error = exc
                if not exc.retryable or attempts >= MAX_ATTEMPTS or mode != "live":
                    break
                self._sleep(min(exc.retry_after or (0.5 * 3 ** (attempts - 1)), 10))
            except Exception as exc:  # noqa: BLE001 — a connector bug must not become a 500 in the app
                last_error = ConnectorError(f"{type(exc).__name__}: {exc}")
                break
        breaker = self._breaker()
        if mode == "live" and last_error is not None and last_error.retryable:
            breaker["failures"] += 1
            if breaker["failures"] >= BREAKER_THRESHOLD:
                breaker["open_until"] = time.time() + BREAKER_SECONDS
        retry_at = now() + dt.timedelta(seconds=RETRY_LATER_SECONDS) if last_error and last_error.retryable else None
        message = str(last_error) if last_error else "unknown error"
        self.store.update(event_id, status="failed", attempts=attempts, error=message, retry_at=retry_at)
        return Result(False, self.name, operation, mode, error=message, event_id=event_id)

    # -- sandbox helpers ---------------------------------------------------------
    def _sandbox_url(self, key: str) -> str:
        return f"#/integrations/{self.name}/{urllib.parse.quote(key)}"

    def _remember(self, key: str, kind: str, data: dict[str, Any]) -> dict[str, Any]:
        self.store.put_object(self.name, key, kind, data)
        return data

    def _recall(self, key: str) -> dict[str, Any]:
        found = self.store.get_object(self.name, key)
        if found is None:
            raise ConnectorError(f"{self.title} sandbox has no {key}")
        return found
