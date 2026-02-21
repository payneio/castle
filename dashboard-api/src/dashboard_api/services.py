"""Service management — start/stop/restart systemd-managed components."""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, HTTPException, status
from starlette.responses import JSONResponse

from castle_cli.config import load_config

from dashboard_api.config import settings
from dashboard_api.health import check_all_health
from dashboard_api.models import HealthStatus
from dashboard_api.stream import broadcast

router = APIRouter(prefix="/services", tags=["services"])

UNIT_PREFIX = "castle-"
SELF_NAME = "dashboard-api"


async def _systemctl(action: str, unit: str) -> tuple[bool, str]:
    """Run a systemctl --user command. Returns (success, output)."""
    proc = await asyncio.create_subprocess_exec(
        "systemctl", "--user", action, unit,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    output = (stdout or stderr or b"").decode().strip()
    return proc.returncode == 0, output


async def _get_unit_status(unit: str) -> str:
    """Get the active status of a systemd unit."""
    proc = await asyncio.create_subprocess_exec(
        "systemctl", "--user", "is-active", unit,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    return (stdout or b"").decode().strip()


def _validate_managed(name: str) -> None:
    """Raise 404 if the component isn't systemd-managed."""
    config = load_config(settings.castle_root)
    if name not in config.managed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"'{name}' is not a managed service",
        )


async def _broadcast_health_with_override(
    override_name: str, override_status: str
) -> None:
    """Run health checks but override one component's status from systemd."""
    config = load_config(settings.castle_root)
    statuses = await check_all_health(config)

    # Replace the overridden component's status with the systemd truth
    result = []
    for s in statuses:
        if s.id == override_name:
            result.append(HealthStatus(
                id=override_name,
                status="down" if override_status != "active" else "up",
                latency_ms=None,
            ))
        else:
            result.append(s)

    await broadcast("health", {
        "statuses": [s.model_dump() for s in result],
        "timestamp": time.time(),
    })


async def _deferred_systemctl(action: str, unit: str, delay: float = 0.5) -> None:
    """Run a systemctl action after a delay, allowing the HTTP response to flush."""
    await asyncio.sleep(delay)
    await _systemctl(action, unit)


async def _do_action(name: str, action: str) -> JSONResponse:
    """Execute a systemctl action and broadcast updated health."""
    _validate_managed(name)
    unit = f"{UNIT_PREFIX}{name}.service"

    # Self-restart: defer the systemctl call so the response can be sent first
    if name == SELF_NAME and action in ("restart", "stop"):
        asyncio.create_task(_deferred_systemctl(action, unit))
        return JSONResponse(
            status_code=202,
            content={"component": name, "action": action, "status": "accepted"},
        )

    ok, output = await _systemctl(action, unit)
    unit_status = await _get_unit_status(unit)

    if not ok:
        raise HTTPException(status_code=500, detail=output or f"Failed to {action}")

    # Broadcast immediately with systemd status as the source of truth
    await _broadcast_health_with_override(name, unit_status)

    return JSONResponse(
        content={"component": name, "action": action, "status": unit_status},
    )


@router.post("/{name}/start")
async def start_service(name: str) -> JSONResponse:
    """Start a systemd-managed service."""
    return await _do_action(name, "start")


@router.post("/{name}/stop")
async def stop_service(name: str) -> JSONResponse:
    """Stop a systemd-managed service."""
    return await _do_action(name, "stop")


@router.post("/{name}/restart")
async def restart_service(name: str) -> JSONResponse:
    """Restart a systemd-managed service."""
    return await _do_action(name, "restart")
