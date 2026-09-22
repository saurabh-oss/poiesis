"""Persistence helpers shared by nodes: artifacts, run status, evidence."""
from __future__ import annotations

import asyncio
from typing import Any

from .. import telemetry
from ..db import Artifact, Run, session


def _save(run_id: str, kind: str, stage: str, body: dict[str, Any]) -> str:
    with session() as s:
        prior = (
            s.query(Artifact)
            .filter(Artifact.run_id == run_id, Artifact.kind == kind)
            .order_by(Artifact.version.desc())
            .first()
        )
        if prior is not None and prior.body == body:
            # A replayed node re-saves what it already saved. Versions should mark
            # real revisions the stakeholder can diff, not checkpoint replays.
            return prior.id
        art = Artifact(
            run_id=run_id, kind=kind, stage=stage,
            version=(prior.version + 1) if prior else 1, body=body,
        )
        s.add(art)
        s.commit()
        return art.id


async def save_artifact(run_id: str, kind: str, stage: str, body: dict[str, Any]) -> str:
    return await asyncio.to_thread(_save, run_id, kind, stage, body)


def _title(run_id: str, title: str) -> None:
    with session() as s:
        run = s.get(Run, run_id)
        if run is not None and title:
            run.title = title[:240]
            s.commit()


async def set_title(run_id: str, title: str) -> None:
    """The stakeholder's working title is replaced by the product name once the
    Product Owner has named it, so run lists read like products, not like notes."""
    await asyncio.to_thread(_title, run_id, title)


def _stage(run_id: str, stage: str, status: str | None = None,
           summary: dict[str, Any] | None = None) -> None:
    with session() as s:
        run = s.get(Run, run_id)
        if run is None:
            return
        run.stage = stage
        if status:
            run.status = status
        if summary:
            run.summary = {**(run.summary or {}), **summary}
        s.commit()


async def set_stage(run_id: str, stage: str, status: str | None = None,
                    summary: dict[str, Any] | None = None) -> None:
    await asyncio.to_thread(_stage, run_id, stage, status, summary)
    try:
        await telemetry.stage_changed(run_id, stage, status)
    except Exception:  # noqa: BLE001 — a stage span is never worth a run
        pass
