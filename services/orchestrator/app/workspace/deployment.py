"""Run a generated application at a URL.

Phase 3 of the Deployable Increment plan. Before this, a run ended with a
compose file in a git workspace and a release note telling the stakeholder what
to type; nothing ever started the application, so there was no URL to open.

Each run's application is its own Compose project (`poiesis-run-<run id>`) with
its own network, its own volume and one published port. It is a sibling of the
Poiesis containers on the host daemon, started through the mounted socket: the
same arrangement as the test sandbox, but long-lived and addressable rather
than throwaway and portless.

Two constraints shape this module:

* The orchestrator runs in a container, so the compose CLI reads the project
  from /workspaces while the daemon runs it on the host. Build contexts are
  uploaded by the CLI and work; host bind mounts do not, because the daemon
  resolves them against a filesystem where /workspaces does not exist, and it
  silently mounts an empty directory instead of failing. `make_portable`
  removes them before anything starts.
* Ports are shared on one laptop. A deployment takes the lowest free port in
  the configured range, and a collision with something outside Poiesis is
  retried on the next port rather than reported as a failure.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import asdict, dataclass
from typing import Any

import yaml

from ..config import settings
from ..db import Deployment, now, session
from .repo import commit, workspace_path

COMPOSE_FILE = "docker-compose.yml"

DB_DOCKERFILE = """# Written by Poiesis at deploy time.
# The schema is baked into the image rather than bind-mounted: the deploy runs on
# the host Docker daemon, which cannot see the orchestrator's /workspaces path.
FROM postgres:16-alpine
COPY init.sql /docker-entrypoint-initdb.d/init.sql
"""

_LOCKS: dict[str, asyncio.Lock] = {}
_BIND_PREFIXES = ("./", "../", "/", "~")
_LEGACY_PORT = re.compile(r"^\$\{APP_PORT(?::-\d+)?\}:(\d+)$")
_PORT_TAKEN = re.compile(r"port is already allocated|address already in use", re.I)


class DeployError(RuntimeError):
    """A deployment that cannot work as configured; the message is for a human."""


@dataclass
class Outcome:
    status: str                 # running | failed | stopped | not_applicable
    url: str = ""
    port: int | None = None
    project: str = ""
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def project_name(run_id: str) -> str:
    return f"poiesis-run-{run_id}"


def _lock(run_id: str) -> asyncio.Lock:
    # One deploy or stop at a time per run; the graph and the Redeploy button can
    # otherwise race to allocate a port for the same project.
    return _LOCKS.setdefault(run_id, asyncio.Lock())


def _tail(text: str, lines: int = 25) -> str:
    return "\n".join((text or "").strip().splitlines()[-lines:])


async def _compose(
    run_id: str, *args: str, env: dict[str, str] | None = None,
    timeout: int = 120, with_file: bool = True,
) -> tuple[int, str]:
    root = workspace_path(run_id)
    cmd = ["docker", "compose", "-p", project_name(run_id)]
    if with_file:
        cmd += ["-f", str(root / COMPOSE_FILE)]
    cmd += list(args)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(root) if root.is_dir() else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env={**os.environ, **(env or {})},
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return -1, f"docker compose {args[0] if args else ''} timed out after {timeout}s"
    code = proc.returncode if proc.returncode is not None else -1
    return code, out.decode(errors="replace")


# --- the compose file ---------------------------------------------------------

def _is_bind(volume: Any) -> bool:
    return isinstance(volume, str) and volume.startswith(_BIND_PREFIXES)


def _load(run_id: str) -> dict[str, Any]:
    path = workspace_path(run_id) / COMPOSE_FILE
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def make_portable(run_id: str) -> list[str]:
    """Rewrite the compose file so it runs on a daemon that cannot see /workspaces.

    The scaffold now generates portable files; this upgrades workspaces created
    before it did, and refuses anything else that still depends on a host path.
    Returns a description of each change made (empty when nothing was needed).
    """
    root = workspace_path(run_id)
    doc = _load(run_id)
    services = doc.get("services") or {}
    changes: list[str] = []

    db = services.get("db")
    if isinstance(db, dict):
        volumes = db.get("volumes") or []
        if any(_is_bind(v) and "docker-entrypoint-initdb.d" in v for v in volumes):
            dockerfile = root / "db" / "Dockerfile"
            if not dockerfile.exists():
                dockerfile.parent.mkdir(parents=True, exist_ok=True)
                dockerfile.write_text(DB_DOCKERFILE, encoding="utf-8", newline="\n")
            db.pop("image", None)
            db["build"] = "./db"
            db["volumes"] = [v for v in volumes if not _is_bind(v)]
            changes.append("database schema baked into its image instead of bind-mounted")

    for name, svc in services.items():
        if not isinstance(svc, dict) or not svc.get("ports"):
            continue
        rewritten = []
        for port in svc["ports"]:
            match = _LEGACY_PORT.match(str(port))
            if match:
                rewritten.append(f"${{APP_BIND:-127.0.0.1}}:${{APP_PORT:-8081}}:{match.group(1)}")
                changes.append(f"{name}: published port bound to APP_BIND")
            else:
                rewritten.append(port)
        svc["ports"] = rewritten

    # Healthchecks must probe 127.0.0.1, not localhost. On Alpine images localhost
    # resolves to ::1 first, and the scaffold's nginx listens on IPv4 only, so a
    # `wget http://localhost/` check is refused by a server that is working
    # perfectly. `up --wait` then fails the whole deployment on a false verdict:
    # observed on a Leave Tracker deploy whose frontend failed thirty consecutive
    # checks while serving every page correctly.
    for name, svc in services.items():
        health = svc.get("healthcheck") if isinstance(svc, dict) else None
        test = health.get("test") if isinstance(health, dict) else None
        if not test:
            continue
        if isinstance(test, list):
            fixed = [t.replace("://localhost", "://127.0.0.1") if isinstance(t, str) else t
                     for t in test]
        else:
            fixed = str(test).replace("://localhost", "://127.0.0.1")
        if fixed != test:
            health["test"] = fixed
            changes.append(f"{name}: healthcheck probes 127.0.0.1 instead of localhost")

    leftover = [
        f"{name}: {v}"
        for name, svc in services.items() if isinstance(svc, dict)
        for v in (svc.get("volumes") or []) if _is_bind(v)
    ]
    if leftover:
        raise DeployError(
            "This application mounts files from the host, which a deploy through the "
            "Docker socket cannot provide: " + "; ".join(leftover)
        )

    if changes:
        (root / COMPOSE_FILE).write_text(
            yaml.safe_dump(doc, sort_keys=False, default_flow_style=False),
            encoding="utf-8", newline="\n",
        )
        commit(run_id, "chore(deploy): make the compose file runnable through the Docker socket")
    return changes


def entry_service(run_id: str) -> tuple[str, int]:
    """The service a person opens, and the container port it listens on."""
    for name, svc in (_load(run_id).get("services") or {}).items():
        if not isinstance(svc, dict):
            continue
        for port in svc.get("ports") or []:
            target = str(port).rsplit(":", 1)[-1].split("/")[0]
            if target.isdigit():
                return name, int(target)
    raise DeployError("No service publishes a port, so there is nothing to open in a browser.")


# --- bookkeeping --------------------------------------------------------------

def _record(run_id: str, **fields: Any) -> None:
    with session() as db:
        row = db.get(Deployment, run_id)
        if row is None:
            row = Deployment(run_id=run_id, project=project_name(run_id))
            db.add(row)
        for key, value in fields.items():
            setattr(row, key, value)
        db.commit()


def _candidate_ports(run_id: str) -> list[int]:
    """Free ports in the range, this run's previous port first so its URL is stable."""
    s = settings()
    with session() as db:
        live = db.query(Deployment).filter(Deployment.status.in_(("starting", "running"))).all()
        taken = {r.port for r in live if r.port and r.run_id != run_id}
        mine = db.get(Deployment, run_id)
        previous = mine.port if mine else None
    ports = [
        p for p in range(s.poiesis_deploy_port_start, s.poiesis_deploy_port_end + 1)
        if p not in taken
    ]
    if previous in ports:
        ports.remove(previous)
        ports.insert(0, previous)
    return ports


def as_row(row: Deployment, title: str = "") -> dict[str, Any]:
    return {
        "run_id": row.run_id, "title": title, "project": row.project, "port": row.port,
        "url": row.url, "status": row.status, "detail": row.detail,
        "started_at": row.started_at, "updated_at": row.updated_at,
    }


# --- lifecycle ----------------------------------------------------------------

async def _gateway_up(run_id: str, entry: str) -> bool:
    """Is the entry service running and healthy, whatever the others are doing?"""
    code, out = await _compose(run_id, "ps", "--format", "{{.Service}} {{.State}} {{.Health}}", timeout=60)
    if code != 0:
        return False
    for line in out.splitlines():
        parts = line.split()
        if parts and parts[0] == entry:
            return "running" in parts[1:2] and (len(parts) < 3 or parts[2] in ("healthy", ""))
    return False


async def _probe(run_id: str, service: str, port: int) -> tuple[str | None, str]:
    """Walk the front door from inside the entry container.

    Returns (failure message or None, a note on the database check). /health is
    required: it proves nginx reaches the API. /api/status additionally proves the
    API reaches Postgres, but a story may legitimately have removed that route, so
    it is reported rather than enforced.
    """
    code, out = await _compose(
        run_id, "exec", "-T", service, "wget", "-qO-", f"http://127.0.0.1:{port}/health",
        timeout=60,
    )
    if code == 127 or "executable file not found" in out:
        return None, "front-door probe skipped: the entry image has no wget"
    if code != 0:
        return f"/health did not answer through the {service} service:\n{_tail(out, 8)}", ""

    code, out = await _compose(
        run_id, "exec", "-T", service, "wget", "-qO-", f"http://127.0.0.1:{port}/api/status",
        timeout=60,
    )
    return None, "database reachable" if code == 0 and "connected" in out else (
        "database check did not pass (/api/status)"
    )


APP_ENV = "app.env"
# Settings the operator gives every enterprise app, from the orchestrator's own
# environment: APPS_JIRA_BASE_URL becomes JIRA_BASE_URL inside the app. Only the
# connectors' own variables pass, so nothing else of the platform's leaks in.
_APP_SETTINGS = ("JIRA_", "SERVICENOW_", "PLANE_", "SMTP_", "EMAIL_", "SLACK_", "TEAMS_", "AUTH_", "JOB_SECONDS")


def service_token(run_id: str) -> str:
    """The platform's own bearer token for this app (its checks), stable per run."""
    path = workspace_path(run_id) / ".poiesis" / "service_token"
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    import secrets
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    path.write_text(token, encoding="utf-8")
    return token


def write_app_env(run_id: str) -> list[str]:
    """app.env for an enterprise application: its secret, the check token, connector settings.

    Returns the names of the connector settings it passed on (never their values).
    """
    import os
    import secrets
    root = workspace_path(run_id)
    if not (root / "backend" / "app" / "kernel").is_dir():
        return []
    existing: dict[str, str] = {}
    path = root / APP_ENV
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and not key.startswith("#"):
                existing[key.strip()] = value
    values = {
        "APP_SECRET": existing.get("APP_SECRET") or secrets.token_urlsafe(48),
        "POIESIS_SERVICE_TOKEN": service_token(run_id),
    }
    passed = []
    for key, value in sorted(os.environ.items()):
        if key.startswith("APPS_") and key[5:].startswith(_APP_SETTINGS) and value.strip():
            values[key[5:]] = value.strip()
            passed.append(key[5:])
    body = "# Written by Poiesis at each deployment. Not committed: it holds secrets.\n" + "".join(
        f"{k}={v}\n" for k, v in values.items())
    path.write_text(body, encoding="utf-8", newline="\n")
    ignore = root / ".gitignore"
    if ignore.is_file() and APP_ENV not in ignore.read_text(encoding="utf-8").split():
        with ignore.open("a", encoding="utf-8", newline="\n") as f:
            f.write(f"\n{APP_ENV}\n")
    return passed


async def deploy(run_id: str, *, fresh: bool = False) -> Outcome:
    """`fresh=True` drops any existing database volume before starting.

    Postgres only ever runs db/init.sql against a brand-new data directory; a
    volume left over from an earlier deploy in this same run freezes whatever
    schema init.sql had at that moment; every later change to it — a column a
    subsequent story added — is silently ignored, and the app keeps failing
    with "column ... does not exist" no matter how correct init.sql becomes on
    disk. A run that is still iterating has no real user data worth keeping, so
    the automated deploy inside the build/review loop always passes `fresh`;
    a stakeholder's own "start it again" on an already-released app does not.
    """
    async with _lock(run_id):
        return await _deploy(run_id, fresh=fresh)


async def _deploy(run_id: str, *, fresh: bool = False) -> Outcome:
    s = settings()
    project = project_name(run_id)
    if not (workspace_path(run_id) / COMPOSE_FILE).is_file():
        return Outcome("not_applicable", project=project,
                       detail="This run produced no docker-compose.yml, so there is nothing to start.")

    _record(run_id, status="starting", detail="", url="", started_at=now())
    try:
        changes = await asyncio.to_thread(make_portable, run_id)
        entry, container_port = await asyncio.to_thread(entry_service, run_id)
        passed = await asyncio.to_thread(write_app_env, run_id)
        if passed:
            changes = [*changes, "connector settings passed to the app: " + ", ".join(passed)]
    except (DeployError, yaml.YAMLError, OSError) as exc:
        _record(run_id, status="failed", detail=str(exc))
        return Outcome("failed", project=project, detail=str(exc))

    if fresh:
        await _compose(run_id, "down", "-v", "--remove-orphans", timeout=120)

    chosen: int | None = None
    last = ""
    for port in _candidate_ports(run_id)[:6]:
        _record(run_id, port=port)
        code, out = await _compose(
            run_id, "up", "-d", "--build", "--remove-orphans",
            "--wait", "--wait-timeout", str(s.poiesis_deploy_timeout),
            env={"APP_PORT": str(port), "APP_BIND": s.poiesis_deploy_bind},
            timeout=s.poiesis_deploy_timeout + 300,
        )
        if code == 0:
            chosen = port
            break
        if not _PORT_TAKEN.search(out) and await _gateway_up(run_id, entry):
            # The standard topology keeps the gateway and the data service up when
            # the api service is not: the app is reachable and every table is
            # served, so it is deployed, degraded, and the browser check says which
            # screens that costs rather than "the application did not start".
            chosen = port
            _, logs = await _compose(run_id, "logs", "backend", "--no-color", "--tail", "40", timeout=60)
            changes = [*changes, "DEGRADED: the api service is not healthy; the gateway is serving the "
                                 "data service instead. api logs:\n" + _tail(logs, 25)]
            break
        last = out
        if _PORT_TAKEN.search(out):
            # Something outside Poiesis holds this port. Clear what we half-created
            # and take the next one rather than failing the deployment.
            await _compose(run_id, "down", "--remove-orphans", timeout=120)
            continue
        break

    if chosen is None:
        _, logs = await _compose(run_id, "logs", "--no-color", "--tail", "30", timeout=60)
        detail = (_tail(last) or "No free port in the configured range.") + (
            f"\n\n--- recent logs ---\n{_tail(logs, 30)}" if logs.strip() else ""
        )
        _record(run_id, status="failed", detail=detail)
        return Outcome("failed", project=project, detail=detail)

    url = f"http://{s.poiesis_deploy_public_host}:{chosen}"
    failure, db_note = await _probe(run_id, entry, container_port)
    if failure:
        _record(run_id, status="failed", url=url, detail=failure)
        return Outcome("failed", url=url, port=chosen, project=project, detail=failure)

    detail = "; ".join([db_note, *changes]).strip("; ")
    _record(run_id, status="running", url=url, detail=detail)
    return Outcome("running", url=url, port=chosen, project=project, detail=detail)


async def restart_running() -> list[str]:
    """Redeploy every app whose deployment row still says "running".

    A host-wide Docker restart — Docker Desktop restarting, the machine
    rebooting, the whole compose stack going down together — takes every
    generated app's containers with it, uncleanly: nothing had the chance to
    mark them "stopped" first. Without this, a released application that was
    working perfectly is simply unreachable after the next restart, with
    nothing in the UI explaining why — silently breaking the one promise the
    platform makes, a working app at a URL, for a reason that has nothing to
    do with the run itself.

    "running" is read as it was left before shutdown, which is exactly the set
    that should come back — an explicit Stop sets status to "stopped" and nothing
    here resurrects those. Each redeploy reuses its previous port, so an open
    bookmark or a note in RELEASE_NOTES.md still resolves correctly.
    """
    with session() as db:
        run_ids = [
            r.run_id for r in
            db.query(Deployment).filter(Deployment.status == "running").all()
        ]
    restarted: list[str] = []
    for run_id in run_ids:
        try:
            outcome = await deploy(run_id)
        except Exception:  # noqa: BLE001 — one bad workspace must not block the rest
            continue
        if outcome.status == "running":
            restarted.append(run_id)
    return restarted


async def stop(run_id: str) -> Outcome:
    """Stop the application and keep its data volume, so a restart finds it intact."""
    async with _lock(run_id):
        has_file = (workspace_path(run_id) / COMPOSE_FILE).is_file()
        code, out = await _compose(
            run_id, "down", "--remove-orphans", timeout=180, with_file=has_file
        )
        status = "stopped" if code == 0 else "failed"
        detail = "" if code == 0 else _tail(out)
        _record(run_id, status=status, detail=detail)
        return Outcome(status, project=project_name(run_id), detail=detail)


async def live_projects() -> dict[str, str]:
    """Compose projects the daemon knows about, by name -> status ("running(3)")."""
    proc = await asyncio.create_subprocess_exec(
        "docker", "compose", "ls", "--all", "--format", "json",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        items = json.loads(out or b"[]")
    except (asyncio.TimeoutError, json.JSONDecodeError):
        return {}
    return {i.get("Name", ""): i.get("Status", "") for i in items if isinstance(i, dict)}


async def sync_statuses() -> None:
    """Keep the table honest about apps that stopped outside Poiesis.

    Docker Desktop does not restart these containers after a reboot, so without
    this the Apps page would go on advertising URLs that no longer answer.
    """
    live = await live_projects()
    with session() as db:
        for row in db.query(Deployment).filter(Deployment.status == "running").all():
            if not live.get(row.project, "").startswith("running"):
                row.status = "stopped"
                row.detail = ("Not running any more: Docker was restarted, or the "
                              "containers were stopped outside Poiesis.")
        db.commit()
