"""WebSocket connection manager and broadcaster."""
import json
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)

_connections: list[WebSocket] = []


async def connect(ws: WebSocket) -> None:
    await ws.accept()
    _connections.append(ws)
    logger.debug("WS client connected (%d total)", len(_connections))


def disconnect(ws: WebSocket) -> None:
    _connections.remove(ws)
    logger.debug("WS client disconnected (%d total)", len(_connections))


async def broadcast(payload: dict[str, Any]) -> None:
    text = json.dumps(payload)
    dead: list[WebSocket] = []
    for ws in list(_connections):
        try:
            await ws.send_text(text)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _connections.remove(ws)
