"""Async health checker — fans out HTTP requests to service health endpoints."""

from __future__ import annotations

import asyncio
import time

import httpx

from castle_cli.config import CastleConfig

from castle_api.models import HealthStatus


async def check_all_health(config: CastleConfig) -> list[HealthStatus]:
    """Check health of all components with expose.http and a health_path."""
    targets: list[tuple[str, str]] = []
    for name, manifest in config.components.items():
        if not (manifest.expose and manifest.expose.http):
            continue
        http = manifest.expose.http
        if not http.health_path:
            continue
        host = http.internal.host or "127.0.0.1"
        port = http.internal.port
        url = f"http://{host}:{port}{http.health_path}"
        targets.append((name, url))

    if not targets:
        return []

    async with httpx.AsyncClient(timeout=3.0) as client:
        tasks = [_check_one(client, name, url) for name, url in targets]
        return await asyncio.gather(*tasks)


async def _check_one(client: httpx.AsyncClient, name: str, url: str) -> HealthStatus:
    """Check a single service's health endpoint."""
    start = time.monotonic()
    try:
        resp = await client.get(url)
        latency = int((time.monotonic() - start) * 1000)
        if resp.status_code < 300:
            return HealthStatus(id=name, status="up", latency_ms=latency)
        return HealthStatus(id=name, status="down", latency_ms=latency)
    except httpx.HTTPError:
        latency = int((time.monotonic() - start) * 1000)
        return HealthStatus(id=name, status="down", latency_ms=latency)
