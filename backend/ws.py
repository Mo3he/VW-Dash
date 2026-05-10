"""WebSocket connection manager and broadcaster."""
import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)

_connections: set[WebSocket] = set()
_lock = asyncio.Lock()


async def connect(ws: WebSocket) -> None:
    await ws.accept()
    async with _lock:
        _connections.add(ws)
    logger.debug("WS client connected (%d total)", len(_connections))


async def disconnect(ws: WebSocket) -> None:
    async with _lock:
        _connections.discard(ws)
    logger.debug("WS client disconnected (%d total)", len(_connections))


async def broadcast(payload: dict[str, Any]) -> None:
    text = json.dumps(payload)
    async with _lock:
        snapshot = set(_connections)
    dead: set[WebSocket] = set()
    for ws in snapshot:
        try:
            await ws.send_text(text)
        except Exception:
            dead.add(ws)
    if dead:
        async with _lock:
            _connections -= dead
