from __future__ import annotations

import asyncio
import contextlib

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..events import subscribe

router = APIRouter(tags=["stream"])


@router.websocket("/ws/runs/{run_id}")
async def run_stream(websocket: WebSocket, run_id: str):
    await websocket.accept()

    async def pump():
        async for event in subscribe(run_id):
            await websocket.send_json(event)

    task = asyncio.create_task(pump())
    try:
        while True:
            await websocket.receive_text()  # keepalive from the client
    except WebSocketDisconnect:
        pass
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
