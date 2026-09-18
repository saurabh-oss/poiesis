from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from ..db import Run, session
from ..ingest.pipeline import ingest_file

router = APIRouter(prefix="/api/runs/{run_id}/uploads", tags=["intake"])


@router.post("")
async def upload(run_id: str, files: list[UploadFile] = File(...)):
    with session() as s:
        run = s.get(Run, run_id)
        if run is None:
            raise HTTPException(404, "run not found")
        if run.status != "queued":
            # Intake has already been read into the brief; a late file would be
            # silently ignored by every downstream agent.
            raise HTTPException(409, "the run has already started; intake is closed")

    results = []
    for upload_file in files:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / (upload_file.filename or "upload.bin")
            path.write_bytes(await upload_file.read())
            count = await ingest_file(run_id, path, upload_file.filename or path.name)
        results.append({"file": upload_file.filename, "fragments": count})
    return {"ingested": results}
