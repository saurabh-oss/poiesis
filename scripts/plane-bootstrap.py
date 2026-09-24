"""Make a fresh self-hosted Plane ready for Poiesis, without clicking through its setup.

Plane's first start wants a human: an instance admin, a workspace and an API token,
each made in its web UI. This does the same through Plane's own Django models, in
its api container, and is safe to run again (it finds what already exists).

It then writes the connection into the platform's .env:

    PLANE_URL           http://localhost:8200             what the browser opens
    PLANE_API_URL       http://host.docker.internal:8200  what the orchestrator calls
    PLANE_WORKSPACE     poiesis
    PLANE_API_TOKEN     plane_api_...

and prints the sign-in for the web UI.

    python scripts/plane-bootstrap.py
"""
from __future__ import annotations

import json
import re
import secrets
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLANE_ENV = ROOT / "infra" / "plane" / "plane.env"
DOTENV = ROOT / ".env"
COMPOSE = ["docker", "compose", "-f", str(ROOT / "infra/plane/docker-compose.yml"),
           "--env-file", str(PLANE_ENV), "-p", "plane"]


def read_env(path: Path) -> dict[str, str]:
    out = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^([A-Z0-9_]+)=(.*)$", line.strip())
            if m:
                out[m.group(1)] = m.group(2)
    return out


def set_env(path: Path, values: dict[str, str]) -> None:
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    for key, value in values.items():
        line = f"{key}={value}"
        if re.search(rf"^{key}=.*$", text, flags=re.M):
            text = re.sub(rf"^{key}=.*$", line, text, flags=re.M)
        else:
            text = text.rstrip("\n") + ("\n" if text else "") + line + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")


SHELL = r'''
import json
from django.utils import timezone
from plane.db.models import User, Workspace, WorkspaceMember, APIToken, Profile
from plane.license.models import Instance, InstanceAdmin

EMAIL, PASSWORD, SLUG = __EMAIL__, __PASSWORD__, __SLUG__

user = User.objects.filter(email=EMAIL).first()
if user is None:
    user = User(email=EMAIL, username="poiesis", first_name="Poiesis", last_name="Admin",
                display_name="poiesis")
user.set_password(PASSWORD)
user.is_active = True
user.is_email_verified = True
user.is_password_autoset = False
user.is_password_expired = False
user.save()

inst = Instance.objects.first()
if inst:
    inst.is_setup_done = True
    inst.is_signup_screen_visited = True
    inst.is_telemetry_enabled = False
    inst.save()
    InstanceAdmin.objects.get_or_create(instance=inst, user=user, defaults={"role": 20, "is_verified": True})

ws = Workspace.objects.filter(slug=SLUG).first()
if ws is None:
    ws = Workspace.objects.create(name="Poiesis", slug=SLUG, owner=user, organization_size="1-10")
WorkspaceMember.objects.get_or_create(workspace=ws, member=user, defaults={"role": 20})

profile, _ = Profile.objects.get_or_create(user=user)
profile.is_onboarded = True
profile.is_tour_completed = True
profile.is_navigation_tour_completed = True
profile.last_workspace_id = ws.id
step = dict(profile.onboarding_step or {})
step.update({"profile_complete": True, "workspace_create": True, "workspace_invite": True, "workspace_join": True})
profile.onboarding_step = step
profile.save()

token = APIToken.objects.filter(user=user, workspace=ws, label="poiesis", is_active=True).first()
if token is None:
    token = APIToken.objects.create(user=user, workspace=ws, label="poiesis",
                                    description="Poiesis mirrors every run here",
                                    allowed_rate_limit="2000/min")

from plane.db.models import ProjectUserProperty
for prop in ProjectUserProperty.objects.filter(user__email=EMAIL):
    df = dict(prop.display_filters or {})
    if df.get("layout") != "kanban":
        df.update({"layout": "kanban", "group_by": "state", "order_by": "sort_order"})
        prop.display_filters = df
        prop.save(update_fields=["display_filters"])
print("POIESIS_JSON" + json.dumps({"token": token.token, "workspace": ws.slug, "email": EMAIL}))
'''


def main() -> int:
    plane = read_env(PLANE_ENV)
    port = plane.get("LISTEN_HTTP_PORT", "8200")
    email = plane.get("PLANE_ADMIN_EMAIL") or "admin@poiesis.local"
    password = plane.get("PLANE_ADMIN_PASSWORD") or secrets.token_urlsafe(12)
    set_env(PLANE_ENV, {"PLANE_ADMIN_EMAIL": email, "PLANE_ADMIN_PASSWORD": password})

    code = (SHELL.replace("__EMAIL__", json.dumps(email)).replace("__PASSWORD__", json.dumps(password))
            .replace("__SLUG__", json.dumps("poiesis")))
    proc = subprocess.run([*COMPOSE, "exec", "-T", "api", "python", "manage.py", "shell"],
                          input=code, capture_output=True, text=True, encoding="utf-8")
    found = re.search(r"POIESIS_JSON(\{.*\})", proc.stdout)
    if proc.returncode or not found:
        print(proc.stdout[-2000:], proc.stderr[-2000:], sep="\n")
        print("Plane bootstrap failed. Is Plane up? docker compose -p plane ps")
        return 1
    made = json.loads(found.group(1))
    set_env(DOTENV, {
        "PLANE_URL": f"http://localhost:{port}",
        "PLANE_API_URL": f"http://host.docker.internal:{port}",
        "PLANE_WORKSPACE": made["workspace"],
        "PLANE_API_TOKEN": made["token"],
    })
    print(f"Plane is ready at http://localhost:{port}")
    print(f"  sign in as {email} / {password}")
    print(f"  workspace '{made['workspace']}', API token written to .env; every project opens as a board")
    print("Restart the orchestrator to pick it up: docker compose up -d orchestrator")
    return 0


if __name__ == "__main__":
    sys.exit(main())
