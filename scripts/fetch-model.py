"""Fetch an Ollama model's layers straight from the registry and install them.

A fallback for when `ollama pull` stalls. Ollama's chunked downloader can hang
silently on a flaky link and trickle at kilobytes a second after a resume; the
registry itself serves plain HTTPS blobs with Range support. This pulls each
blob with several resumable connections (it survives disconnects and can be
re-run to continue), verifies its SHA-256, drops it into Ollama's blob store
and writes the manifest. `ollama list` then shows the model as if `ollama pull`
had run. Stop any running `ollama pull` for the same model first.

    python scripts/fetch-model.py qwen3.6 35b-a3b-coding [connections=4]

Parts are kept next to this script under blobs/ until a blob is complete.
Honours OLLAMA_MODELS; defaults to ~/.ollama/models.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import threading
import time
import urllib.request
from pathlib import Path

REGISTRY = "https://registry.ollama.ai/v2/library"
MODELS = Path(os.environ.get("OLLAMA_MODELS", Path.home() / ".ollama" / "models"))
WORK = Path(__file__).parent / "blobs"   # gitignored: partial downloads
WORK.mkdir(exist_ok=True)

name, tag = sys.argv[1], sys.argv[2]
connections = int(sys.argv[3]) if len(sys.argv) > 3 else 4


def log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def manifest() -> dict:
    req = urllib.request.Request(f"{REGISTRY}/{name}/manifests/{tag}", headers={
        "Accept": "application/vnd.docker.distribution.manifest.v2+json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def fetch_range(url: str, dest: Path, start: int, end: int, progress: list[int], idx: int) -> None:
    """Download bytes [start, end] into dest, resuming from what dest already holds."""
    while True:
        have = dest.stat().st_size if dest.exists() else 0
        if start + have > end:
            return
        req = urllib.request.Request(url, headers={"Range": f"bytes={start + have}-{end}",
                                                   "User-Agent": "poiesis-fetch/1"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r, dest.open("ab") as f:
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    progress[idx] += len(chunk)
            if dest.stat().st_size >= end - start + 1:
                return
        except Exception as exc:  # noqa: BLE001 — retry forever; the link is flaky, not broken
            log(f"  part {idx} retry after: {type(exc).__name__}: {str(exc)[:80]}")
            time.sleep(3)


def fetch_blob(digest: str, size: int) -> Path:
    hexd = digest.split(":", 1)[1]
    final = WORK / f"sha256-{hexd}"
    if final.exists() and final.stat().st_size == size:
        return final
    url = f"{REGISTRY}/{name}/blobs/{digest}"
    n = connections if size > 64 << 20 else 1
    bounds = [(i * size // n, (i + 1) * size // n - 1) for i in range(n)]
    parts = [WORK / f"sha256-{hexd}.part{i}" for i in range(n)]
    progress = [p.stat().st_size if p.exists() else 0 for p in parts]
    threads = [threading.Thread(target=fetch_range, args=(url, parts[i], a, b, progress, i), daemon=True)
               for i, (a, b) in enumerate(bounds)]
    for t in threads:
        t.start()
    last, t0 = sum(progress), time.time()
    while any(t.is_alive() for t in threads):
        time.sleep(30)
        done = sum(progress)
        rate = (done - last) / 30 / 1e6
        last = done
        eta = (size - done) / max(rate * 1e6, 1) / 60
        log(f"  {hexd[:12]} {done / 1e9:.2f}/{size / 1e9:.2f} GB  {rate:.2f} MB/s  eta {eta:.0f} min")
    with final.open("wb") as out:
        for p in parts:
            with p.open("rb") as f:
                shutil.copyfileobj(f, out, 1 << 24)
    for p in parts:
        p.unlink()
    return final


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 24), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    m = manifest()
    layers = [m["config"], *m["layers"]]
    log(f"{name}:{tag}: {len(layers)} layers, {sum(l['size'] for l in layers) / 1e9:.2f} GB")
    blobs = MODELS / "blobs"
    for layer in layers:
        digest, size = layer["digest"], layer["size"]
        hexd = digest.split(":", 1)[1]
        target = blobs / f"sha256-{hexd}"
        if target.exists() and target.stat().st_size == size:
            log(f"  {hexd[:12]} already in the store")
            continue
        log(f"  fetching {layer['mediaType'].split('.')[-1]} {hexd[:12]} ({size / 1e9:.2f} GB)")
        path = fetch_blob(digest, size)
        log(f"  verifying {hexd[:12]}")
        got = sha256(path)
        if got != hexd:
            log(f"  DIGEST MISMATCH for {hexd[:12]}: got {got[:12]}; deleting and retrying")
            path.unlink()
            return 1
        for stale in blobs.glob(f"sha256-{hexd}-partial*"):
            stale.unlink()
        shutil.move(str(path), str(target))
        log(f"  installed {hexd[:12]}")
    mdir = MODELS / "manifests" / "registry.ollama.ai" / "library" / name
    mdir.mkdir(parents=True, exist_ok=True)
    (mdir / tag).write_text(json.dumps(m), encoding="utf-8")
    log(f"manifest written: {name}:{tag}")
    return 0


if __name__ == "__main__":
    while True:
        code = main()
        if code == 0:
            break
    print("FETCH_DONE", flush=True)
