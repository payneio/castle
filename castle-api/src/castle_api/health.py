"""Async health checker — fans out HTTP requests to service health endpoints."""

from __future__ import annotations

import asyncio
import time

import httpx

from castle_core.registry import NodeRegistry

from castle_api.models import HealthStatus


async def check_all_health(registry: NodeRegistry) -> list[HealthStatus]:
    """Check health of all deployed components.

    Services with a port + health_path are checked via HTTP.
    Managed services without an HTTP health endpoint fall back to systemd unit status.
    """
    http_targets: list[tuple[str, str]] = []
    systemd_targets: list[str] = []

    for name, deployed in registry.deployed.items():
        if deployed.port and deployed.health_path:
            url = f"http://127.0.0.1:{deployed.port}{deployed.health_path}"
            http_targets.append((name, url))
        elif deployed.managed and not deployed.schedule:
            # Managed service with no HTTP health endpoint — use systemd
            systemd_targets.append(name)

    tasks: list[asyncio.Task[HealthStatus]] = []
    async with httpx.AsyncClient(timeout=3.0) as client:
        for name, url in http_targets:
            tasks.append(asyncio.ensure_future(_check_http(client, name, url)))
        for name in systemd_targets:
            tasks.append(asyncio.ensure_future(_check_systemd(name)))
        if not tasks:
            return []
        return list(await asyncio.gather(*tasks))


async def _check_http(client: httpx.AsyncClient, name: str, url: str) -> HealthStatus:
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


async def _check_systemd(name: str) -> HealthStatus:
    """Check a managed service's health via its systemd unit state."""
    unit = f"castle-{name}.service"
    proc = await asyncio.create_subprocess_exec(
        "systemctl", "--user", "is-active", unit,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    state = (stdout or b"").decode().strip()
    return HealthStatus(id=name, status="up" if state == "active" else "down")
