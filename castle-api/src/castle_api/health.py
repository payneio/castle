"""Async health checker — fans out HTTP requests to service health endpoints."""

from __future__ import annotations

import asyncio
import time

import httpx

from castle_core.registry import NodeRegistry

from castle_api.models import HealthStatus


async def check_all_health(registry: NodeRegistry) -> list[HealthStatus]:
    """Check health of all deployed components with a port and health_path."""
    targets: list[tuple[str, str]] = []
    for name, deployed in registry.deployed.items():
        if not deployed.port or not deployed.health_path:
            continue
        url = f"http://127.0.0.1:{deployed.port}{deployed.health_path}"
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
