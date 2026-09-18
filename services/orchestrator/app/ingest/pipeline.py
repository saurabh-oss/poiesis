"""Intake pipeline: sources in, cited Evidence rows out."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from ..db import Evidence, session
from ..events import emit
from . import loaders

TEXT_EXT = {".md", ".txt", ".csv", ".json", ".yaml", ".yml", ".log"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".mp4", ".webm"}


def _persist(run_id: str, kind: str, ref: str, chunks: list[loaders.Chunk]) -> int:
    with session() as s:
        for c in chunks:
            if c.content.strip():
                s.add(Evidence(run_id=run_id, source_kind=kind, source_ref=ref,
                               locator=c.locator, content=c.content))
        s.commit()
    return len(chunks)


async def ingest_sources(run_id: str, sources: list[dict[str, Any]]) -> int:
    total = 0
    for src in sources:
        kind, value = src["kind"], src["value"]
        ref = src.get("label") or value[:80]
        try:
            if kind == "text":
                chunks = loaders.load_text(value)
            elif kind == "url":
                chunks = await loaders.load_url(value)
            else:
                continue
            total += await asyncio.to_thread(_persist, run_id, kind, ref, chunks)
            await emit(run_id, f"Ingested {kind}: {ref}", agent="intake", stage="intake",
                       data={"fragments": len(chunks)})
        except Exception as exc:  # noqa: BLE001
            await emit(run_id, f"Could not read {ref}: {exc}", agent="intake",
                       stage="intake", level="error")
    return total


async def ingest_file(run_id: str, path: Path, label: str) -> int:
    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf":
            chunks = await asyncio.to_thread(loaders.load_pdf, path.read_bytes())
        elif suffix == ".docx":
            chunks = await asyncio.to_thread(loaders.load_docx, path.read_bytes())
        elif suffix in AUDIO_EXT:
            await emit(run_id, f"Transcribing {label} locally", agent="intake", stage="intake")
            chunks = await asyncio.to_thread(loaders.load_audio, path)
        elif suffix in IMAGE_EXT:
            await emit(run_id, f"Reading the diagram in {label}", agent="intake", stage="intake")
            chunks = await loaders.describe_image(path)
        elif suffix in TEXT_EXT:
            chunks = loaders.load_text(path.read_text(encoding="utf-8", errors="replace"))
        else:
            await emit(run_id, f"Unsupported file type {suffix} for {label}",
                       agent="intake", stage="intake", level="warn")
            return 0
        kind = ("audio" if suffix in AUDIO_EXT else
                "image" if suffix in IMAGE_EXT else "file")
        count = await asyncio.to_thread(_persist, run_id, kind, label, chunks)
        await emit(run_id, f"Ingested {label}: {count} fragments",
                   agent="intake", stage="intake", data={"fragments": count})
        return count
    except Exception as exc:  # noqa: BLE001
        await emit(run_id, f"Could not read {label}: {exc}", agent="intake",
                   stage="intake", level="error")
        return 0
