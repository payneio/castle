"""SSE stream — pushes health updates and service action events to connected clients."""

from __future__ import annotations

import asyncio
import json
import logging
import time

from castle_cli.config import load_config

from dashboard_api.config import settings
from dashboard_api.health import check_all_health

logger = logging.getLogger(__name__)

# All connected SSE clients receive events through this queue-based broadcast.
_subscribers: list[asyncio.Queue[str]] = []


def subscribe() -> asyncio.Queue[str]:
    """Register a new SSE client. Returns a queue to read events from."""
    q: asyncio.Queue[str] = asyncio.Queue(maxsize=64)
    _subscribers.append(q)
    return q


def unsubscribe(q: asyncio.Queue[str]) -> None:
    """Remove a disconnected SSE client."""
    try:
        _subscribers.remove(q)
    except ValueError:
        pass


def close_all_subscribers() -> None:
    """Unblock all SSE generators so they exit during shutdown."""
    for q in list(_subscribers):
        try:
            q.put_nowait("")
        except asyncio.QueueFull:
            pass
    _subscribers.clear()


async def broadcast(event_type: str, data: dict) -> None:
    """Send an event to all connected SSE clients."""
    payload = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
    dead: list[asyncio.Queue[str]] = []
    for q in _subscribers:
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        unsubscribe(q)


async def health_poll_loop(interval: float = 10.0) -> None:
    """Background task that polls health and broadcasts updates."""
    while True:
        try:
            config = load_config(settings.castle_root)
            statuses = await check_all_health(config)
            await broadcast("health", {
                "statuses": [s.model_dump() for s in statuses],
                "timestamp": time.time(),
            })
        except Exception:
            logger.exception("Health poll failed")
        await asyncio.sleep(interval)
