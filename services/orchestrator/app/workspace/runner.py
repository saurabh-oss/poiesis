"""Sandboxed execution.

Generated code never runs in the orchestrator process. It runs in a throwaway
container with no network, a CPU/memory cap and a hard timeout, mounted at the
run's workspace. This is the difference between an agent platform you can point
at a corporate laptop and one you cannot.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import shlex
import time
from dataclasses import dataclass

from ..config import pack, scaffold_root, settings
from .repo import SENTINEL

DEFAULT_IMAGE = "python:3.12-slim"
log = logging.getLogger(__name__)

# Every check used to install the scaffold's packages afresh, from the internet, before it
# looked at anything: a minute each time, and a run's business logic was once judged "does
# not import" because the package index could not be reached. The sandbox image is prepared
# once, with what every generated application needs already in it; a check then installs
# only what a story added.
SANDBOX_EXTRAS = ("pytest", "httpx")
_PREPARED: dict[str, tuple[str, float]] = {}      # base image -> (the image to use, when that was decided)
_RETRY_AFTER = 600                                # seconds before a failed preparation is tried again
_PREPARING = asyncio.Lock()


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


def _baseline() -> list[str]:
    path = scaffold_root() / "web-app" / "backend" / "requirements.txt"
    try:
        lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    except OSError:
        lines = []
    return [line for line in lines if line and not line.startswith("#")] + list(SANDBOX_EXTRAS)


def prepared_tag(base: str) -> str:
    digest = hashlib.sha1("\n".join(_baseline()).encode()).hexdigest()[:10]
    return "poiesis-sandbox:" + base.replace(":", "-").replace("/", "-") + "-" + digest


async def _docker(*args: str, stdin: bytes | None = None, timeout: int = 60) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        "docker", *args, stdin=asyncio.subprocess.PIPE if stdin is not None else None,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(stdin), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return -1, f"timed out after {timeout}s"
    return proc.returncode if proc.returncode is not None else -1, out.decode(errors="replace")


async def prepared_image(base: str) -> str:
    """`base` with the scaffold's requirements, pytest and httpx installed, built once and kept
    by the daemon. `base` itself when it is not a Python image or cannot be prepared now."""
    if not base.startswith("python:"):
        return base
    known = _PREPARED.get(base)
    if known and (known[0] != base or time.time() - known[1] < _RETRY_AFTER):
        return known[0]
    async with _PREPARING:
        tag = prepared_tag(base)
        code, _ = await _docker("image", "inspect", tag, timeout=30)
        if code != 0:
            packages = " ".join(shlex.quote(r) for r in _baseline())
            dockerfile = (f"FROM {base}\n"
                          "RUN pip install --no-cache-dir --disable-pip-version-check --root-user-action=ignore "
                          f"--retries 10 --timeout 60 {packages}\n")
            code, out = await _docker("build", "-t", tag, "-", stdin=dockerfile.encode(), timeout=1800)
            if code != 0:
                log.warning("the sandbox image could not be prepared; using %s as it is: %s", base,
                            " | ".join(out.strip().splitlines()[-3:]))
                _PREPARED[base] = (base, time.time())
                return base
        _PREPARED[base] = (tag, time.time())
        return tag


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
    network_name: str | None = None,
    env: dict[str, str] | None = None,
) -> ExecResult:
    """`shell` is "sh" for Alpine images such as node:20-alpine, which have no bash.

    `network_name` joins a named Docker network (a throwaway database's), with egress.
    """
    host_path = mount_source(run_id)
    docker_cmd = [
        "docker", "run", "--rm",
        "--network", network_name or ("bridge" if network else "none"),
        "--memory", memory, "--cpus", cpus,
        "--pids-limit", "512",
        "-v", f"{host_path}:/work",
        "-w", "/work",
    ]
    for k, v in (env or {}).items():
        docker_cmd += ["-e", f"{k}={v}"]
    docker_cmd += [image or await prepared_image(sandbox_image()), shell, "-lc", command]
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
