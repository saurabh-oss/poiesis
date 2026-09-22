"""Sandboxed execution.

Generated code never runs in the orchestrator process. It runs in a throwaway
container with no network, a CPU/memory cap and a hard timeout, mounted at the
run's workspace. This is the difference between an agent platform you can point
at a corporate laptop and one you cannot.
"""
from __future__ import annotations

import asyncio

from dataclasses import dataclass

from ..config import pack, settings
from .repo import SENTINEL

DEFAULT_IMAGE = "python:3.12-slim"


@dataclass
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


def sandbox_image() -> str:
    return pack().get("build", {}).get("sandbox_image") or DEFAULT_IMAGE


def sandbox_timeout() -> int:
    return int(pack().get("build", {}).get("test_timeout_seconds") or 900)


def mount_source(run_id: str) -> str:
    """The bind-mount source as the *host* Docker daemon will resolve it.

    Sandbox containers are siblings launched through the mounted docker socket, so
    the daemon reads this path on the host — not inside the orchestrator, where the
    workspace is at /workspaces. On Docker Desktop those are different filesystems,
    and mounting the container path silently yields an empty directory instead of
    an error, which is why this is configured explicitly.
    """
    s = settings()
    root = (s.poiesis_workspace_host_root.strip() or s.poiesis_workspace_root).rstrip("/\\")
    # Keep whatever separator the configured root already uses; Docker Desktop
    # accepts C:/code/poiesis/workspaces as readily as C:\code\poiesis\workspaces,
    # but not the two mixed in one path.
    sep = "\\" if ("\\" in root and "/" not in root) else "/"
    return f"{root}{sep}{run_id}"


async def preflight(run_id: str) -> str | None:
    """Prove the sandbox sees the real workspace. Returns an error string, or None.

    Without this a misconfigured mount presents as 'pytest collected no tests', and
    the build stage burns every repair attempt trying to fix code it cannot see.
    """
    probe = await run_in_sandbox(
        run_id, f"test -f {SENTINEL} && echo MOUNT_OK", timeout=120, network=False
    )
    if "MOUNT_OK" in probe.stdout:
        return None
    return (
        f"The sandbox cannot see the run workspace. It bind-mounted "
        f"'{mount_source(run_id)}', which the host Docker daemon resolved to an empty "
        "directory. Set POIESIS_WORKSPACE_HOST_ROOT in .env to the workspaces folder "
        "as the host sees it (on Windows, e.g. C:\\code\\poiesis\\workspaces), then "
        "restart the orchestrator."
    )


async def run_in_sandbox(
    run_id: str,
    command: str,
    *,
    image: str | None = None,
    timeout: int = 600,
    network: bool = False,
    memory: str = "2g",
    cpus: str = "2",
    shell: str = "bash",
) -> ExecResult:
    """`shell` is "sh" for Alpine images such as node:20-alpine, which have no bash."""
    host_path = mount_source(run_id)
    docker_cmd = [
        "docker", "run", "--rm",
        "--network", "bridge" if network else "none",
        "--memory", memory, "--cpus", cpus,
        "--pids-limit", "512",
        "-v", f"{host_path}:/work",
        "-w", "/work",
        image or sandbox_image(), shell, "-lc", command,
    ]
    proc = await asyncio.create_subprocess_exec(
        *docker_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return ExecResult(-1, "", f"timed out after {timeout}s", True)

    return ExecResult(
        exit_code=proc.returncode or 0,
        stdout=out.decode(errors="replace")[-20000:],
        stderr=err.decode(errors="replace")[-20000:],
        timed_out=False,
    )


def pytest_command(extra: str = "") -> str:
    """Dependency install needs egress, so the test stage runs with network=True.
    Everything else stays air-gapped."""
    return (
        "if [ -f requirements.txt ]; then "
        "pip install --quiet --disable-pip-version-check --root-user-action=ignore -r requirements.txt; fi; "
        "pip install --quiet --disable-pip-version-check --root-user-action=ignore pytest; "
        # --continue-on-collection-errors: one unimportable test file must not hide
        # every other result. Without it a single bad import reports as a total
        # failure, masking the scaffold's own passing smoke tests and giving the
        # repair loop a traceback instead of an assertion to work from.
        f"python -m pytest -q --tb=short -p no:warnings --continue-on-collection-errors {extra}".strip()
    )
