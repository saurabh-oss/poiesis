"""Live verification: the deployed application, opened in a real browser.

Health checks proved only that the backend answered. A released app threw on
load and showed the scaffold placeholder, and every platform check passed,
because nothing had ever looked at the page a person sees. This opens the
running app in headless Chromium on the app's own Docker network, visits every
screen the shell registers, and records what went wrong: uncaught errors,
failing API calls, error panels, screens that render nothing, and scaffold
placeholders still showing. It also keeps a screenshot of each screen.

The result feeds the review as blocking findings, attributed to the story whose
screen failed, so a broken screen drives a rework round and blocks release.
"""
from __future__ import annotations

import asyncio
import json
import re
import shutil
from typing import Any

from .deployment import entry_service, project_name
from .repo import workspace_path
from .runner import mount_source

IMAGE = "poiesis-browser:1"

# Playwright's image ships the browsers but not the Python package; one small
# derived image, built once and cached by the daemon, saves an install per check.
DOCKERFILE = (
    "FROM mcr.microsoft.com/playwright/python:v1.49.0-noble\n"
    "RUN pip install --no-cache-dir --break-system-packages playwright==1.49.0\n"
)

PROBE = r'''
import json, os, sys
from playwright.sync_api import sync_playwright

base, out = sys.argv[1], sys.argv[2]
os.makedirs(f"{out}/shots", exist_ok=True)
result = {"ok": False, "problems": [], "screens": []}
PLACEHOLDERS = ("Scaffold is running", "No screens yet")

def short(url):
    return url.split(base.rstrip("/"), 1)[-1] or "/"


def values_of(item):
    """Strings from one API item distinctive enough to look for on the page.

    Ids and timestamps are skipped: they are either absent from the rendering or
    reformatted by it, so neither their presence nor their absence proves
    anything about whether the screen displayed what it fetched.
    """
    if not isinstance(item, dict):
        return []
    out = []
    for k, v in item.items():
        if k.lower() == "id" or k.lower().endswith("_id") or k.lower().endswith("_at"):
            continue
        if isinstance(v, str) and 3 <= len(v) <= 120 and not v[:4].isdigit():
            out.append(v)
    # Longest first: a title is far better evidence than a status everything shares.
    return sorted(out, key=len, reverse=True)[:5]

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1280, "height": 860})
    errors = []
    page.on("pageerror", lambda e: errors.append(f"Uncaught error: {e}"))
    page.on("console", lambda m: errors.append(f"Console error: {m.text}")
            if m.type == "error" and "Failed to load resource" not in m.text else None)
    page.on("response", lambda r: errors.append(f"{r.request.method} {short(r.url)} returned {r.status}")
            if "/api/" in r.url and r.status >= 400 else None)
    page.on("requestfailed", lambda r: errors.append(f"{r.method} {short(r.url)} failed")
            if "/api/" in r.url else None)

    # What each screen fetched, so the check can ask the only question that
    # matters to someone looking at the page: did what it fetched reach the screen?
    fetched = []

    def record(r):
        if "/api/" not in r.url or r.status >= 400 or r.request.method != "GET":
            return
        try:
            body = r.json()
        except Exception:
            return
        if isinstance(body, list):
            # Values from the first few items: a screen may sort or page them
            # client-side, so the API's first row is not always on the first page.
            sample = list(dict.fromkeys(v for item in body[:6] for v in values_of(item)))[:12]
            fetched.append({"path": short(r.url), "count": len(body), "sample": sample})
        elif isinstance(body, dict):
            fetched.append({"path": short(r.url), "count": None, "sample": values_of(body)})

    page.on("response", record)

    try:
        page.goto(base, wait_until="load", timeout=30000)
    except Exception as e:
        result["problems"].append(f"The page did not load: {e}")

    state = None
    for _ in range(60):
        state = page.evaluate("() => window.__poiesis ? JSON.parse(JSON.stringify(window.__poiesis)) : null")
        if state and state.get("ready"):
            break
        page.wait_for_timeout(250)
    if not state:
        result["problems"].append(
            "The application shell never started (window.__poiesis is missing): app.js failed before it "
            "could render anything, so the page shows only its static HTML.")
    result["problems"] += list(dict.fromkeys(errors))
    del errors[:]

    screens = (state or {}).get("screens", [])
    real = [s for s in screens if not s.get("example")]
    if state and not real:
        result["problems"].append(
            "No story screens are registered: the page shows only the scaffold example or nothing at all.")

    for s in screens:
        start = len(errors)
        seen_before = len(fetched)
        page.evaluate("h => { location.hash = h; }", s["hash"])
        for _ in range(60):
            cur = page.evaluate("() => window.__poiesis && window.__poiesis.current")
            if cur and cur.get("hash") == s["hash"] and cur.get("done"):
                break
            page.wait_for_timeout(250)
        page.wait_for_timeout(700)
        text = page.inner_text("#app")
        panel = page.evaluate(
            "() => [...document.querySelectorAll('#app .poiesis-error')].map(e => e.innerText).join(' | ')")
        problems = []
        if panel:
            problems.append(f"The screen shows an error: {panel[:400]}")
        problems += list(dict.fromkeys(errors[start:]))[:6]
        if len(text.strip()) < 25:
            problems.append("The screen renders (almost) nothing.")
        for ph in PLACEHOLDERS:
            if ph in text:
                problems.append(f"The screen still shows '{ph}'.")

        calls = fetched[seen_before:]
        controls = page.evaluate(
            "() => document.querySelectorAll("
            "'#app input, #app select, #app textarea, #app button, #app a[href^=\"#\"]').length")
        # A screen that neither reads the application's data nor offers a control
        # is inert: it renders, it passes every other check, and it is of no use.
        if not calls and not controls:
            problems.append(
                "The screen never called the API and has no controls: it shows only text it "
                "had built in. Load the story's data in render() and show it.")
        for c in calls:
            if c["count"] == 0 or not c["sample"]:
                continue
            # A dashboard that fetched 150 rows and shows "150" has displayed them too.
            counted = c["count"] is not None and c["count"] >= 5 and (
                f"{c['count']:,}" in text or str(c["count"]) in text)
            if not counted and not any(v in text for v in c["sample"]):
                how_many = "1 record" if c["count"] is None else f"{c['count']} item(s)"
                problems.append(
                    f"GET {c['path']} returned {how_many}, but none of it appears on the "
                    f"screen (looked for {', '.join(repr(v) for v in c['sample'][:3])}). "
                    "The data was fetched and then not displayed — this is what an empty "
                    "table over a full database looks like.")
                break

        shot = f"{s['id']}.png"
        page.screenshot(path=f"{out}/shots/{shot}", full_page=True)
        result["screens"].append({
            "id": s["id"], "title": s.get("title"), "story": s.get("story", ""),
            "example": bool(s.get("example")), "ok": not problems, "problems": problems,
            "text": text.strip()[:300], "shot": shot,
            "fetched": [{"path": c["path"], "count": c["count"]} for c in calls],
            "controls": controls,
        })

    result["ok"] = (not result["problems"] and bool(real)
                    and all(x["ok"] for x in result["screens"] if not x["example"]))
    browser.close()

with open(f"{out}/result.json", "w") as f:
    json.dump(result, f, indent=2)
print("ok" if result["ok"] else "problems")
'''


async def _run(*cmd: str, stdin: bytes | None = None, timeout: int = 300) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE if stdin is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(stdin), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return -1, f"{cmd[0]} {cmd[1] if len(cmd) > 1 else ''} timed out after {timeout}s"
    return (proc.returncode if proc.returncode is not None else -1), out.decode(errors="replace")


_LOG_PREFIX = re.compile(r"^[\w.-]+\s+\|\s?")
_TB_START = "Traceback (most recent call last):"
_SERVER_ERROR = re.compile(r"(returned|failed with) 5\d\d")


def has_server_errors(v: dict[str, Any]) -> bool:
    texts = list(v.get("problems", [])) + [p for s in v.get("screens", []) for p in s.get("problems", [])]
    return any(_SERVER_ERROR.search(t) for t in texts)


async def backend_errors(run_id: str, limit: int = 3) -> list[str]:
    """The backend's own tracebacks, trimmed to the application's frames.

    A screen that gets a 500 tells the Developer nothing about why. The backend's
    log does — "UnboundLocalError in routers/llm_overviews.py, line 8, in get_db" —
    and without it a rework round is a guess.
    """
    code, out = await _run("docker", "compose", "-p", project_name(run_id), "logs", "backend",
                           "--no-color", "--tail", "400", timeout=60)
    if code != 0:
        return []
    blocks: list[str] = []
    frames: list[str] | None = None
    for raw in out.splitlines():
        line = _LOG_PREFIX.sub("", raw, count=1)
        if line.startswith(_TB_START):
            frames = []
            continue
        if frames is None:
            continue
        if line.startswith((" ", "\t")) or not line.strip():
            frames.append(line)
            continue
        kept: list[str] = []
        for i, frame in enumerate(frames):
            if frame.strip().startswith('File "/srv/app/'):
                kept.append("  " + frame.strip().replace("/srv/app/", "backend/app/"))
                following = frames[i + 1].strip() if i + 1 < len(frames) else ""
                if following and not following.startswith(("File ", "^")):
                    kept.append("    " + following)
        blocks.append("\n".join(kept + [line.strip()]))
        frames = None
    return list(dict.fromkeys(blocks))[-limit:]


async def ensure_image() -> str | None:
    """Build the browser image once. Returns an error message, or None when ready."""
    code, _ = await _run("docker", "image", "inspect", IMAGE, timeout=30)
    if code == 0:
        return None
    code, out = await _run("docker", "build", "-t", IMAGE, "-", stdin=DOCKERFILE.encode(), timeout=900)
    if code != 0:
        return "The browser-check image could not be built:\n" + "\n".join(out.strip().splitlines()[-12:])
    return None


def _probe_mount(run_id: str) -> str:
    base = mount_source(run_id)
    sep = "\\" if ("\\" in base and "/" not in base) else "/"
    return f"{base}{sep}.poiesis"


def _failed(message: str) -> dict[str, Any]:
    return {"ok": False, "problems": [message], "screens": []}


async def verify(run_id: str) -> dict[str, Any]:
    """Open every screen of the running app. Returns {ok, problems, screens}."""
    root = workspace_path(run_id)
    if not (root / "frontend").is_dir():
        return {"ok": True, "skipped": True, "problems": [], "screens": []}

    error = await ensure_image()
    if error:
        return _failed(error)

    tools = root / ".poiesis"
    tools.mkdir(exist_ok=True)
    shutil.rmtree(tools / "shots", ignore_errors=True)
    (tools / "result.json").unlink(missing_ok=True)
    (tools / "browser_probe.py").write_text(PROBE, encoding="utf-8", newline="\n")

    try:
        service, port = entry_service(run_id)
    except Exception as exc:  # noqa: BLE001 — a compose file with no published port
        return _failed(str(exc))

    code, out = await _run(
        "docker", "run", "--rm",
        "--network", f"{project_name(run_id)}_default",
        "-v", f"{_probe_mount(run_id)}:/probe",
        IMAGE, "python", "/probe/browser_probe.py", f"http://{service}:{port}/", "/probe",
        timeout=300,
    )
    result_file = tools / "result.json"
    if not result_file.is_file():
        return _failed("The browser check did not produce a result:\n"
                       + "\n".join(out.strip().splitlines()[-12:]))
    try:
        result = json.loads(result_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return _failed("The browser check wrote an unreadable result.")
    # A screen whose module failed to load could not name its story; the file can.
    from .checks import stories_in
    for screen in result.get("screens", []):
        if not screen.get("story"):
            path = root / "frontend" / "screens" / f"{screen.get('id')}.js"
            if path.is_file():
                screen["story"] = ", ".join(stories_in(path.read_text(encoding="utf-8", errors="replace")))
    if has_server_errors(result):
        result["backend_errors"] = await backend_errors(run_id)
    return result
