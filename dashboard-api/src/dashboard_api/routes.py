"""API routes for the castle dashboard."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from castle_cli.config import load_config

from dashboard_api.config import settings
from dashboard_api.health import check_all_health
from dashboard_api.models import (
    ComponentDetail,
    ComponentSummary,
    GatewayInfo,
    StatusResponse,
)

router = APIRouter(tags=["dashboard"])


def _summary_from_manifest(name: str, manifest: object) -> ComponentSummary:
    """Build a ComponentSummary from a manifest."""
    port = None
    health_path = None
    proxy_path = None
    if manifest.expose and manifest.expose.http:
        port = manifest.expose.http.internal.port
        health_path = manifest.expose.http.health_path
    if manifest.proxy and manifest.proxy.caddy:
        proxy_path = manifest.proxy.caddy.path_prefix

    managed = bool(
        manifest.manage and manifest.manage.systemd and manifest.manage.systemd.enable
    )

    return ComponentSummary(
        id=name,
        description=manifest.description,
        roles=[r.value for r in manifest.roles],
        runner=manifest.run.runner if manifest.run else None,
        port=port,
        health_path=health_path,
        proxy_path=proxy_path,
        managed=managed,
        category=manifest.tool.category if manifest.tool else None,
        version=manifest.tool.version if manifest.tool else None,
        tool_type=manifest.tool.tool_type.value if manifest.tool else None,
    )


@router.get("/components", response_model=list[ComponentSummary])
def list_components() -> list[ComponentSummary]:
    """List all registered components."""
    config = load_config(settings.castle_root)
    return [
        _summary_from_manifest(name, m)
        for name, m in config.components.items()
    ]


@router.get("/components/{name}", response_model=ComponentDetail)
def get_component(name: str) -> ComponentDetail:
    """Get detailed info for a single component."""
    config = load_config(settings.castle_root)
    if name not in config.components:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Component '{name}' not found",
        )
    manifest = config.components[name]
    summary = _summary_from_manifest(name, manifest)
    raw = manifest.model_dump(mode="json", exclude_none=True)
    return ComponentDetail(**summary.model_dump(), manifest=raw)


@router.get("/status", response_model=StatusResponse)
async def get_status() -> StatusResponse:
    """Get live health status for all exposed services."""
    config = load_config(settings.castle_root)
    statuses = await check_all_health(config)
    return StatusResponse(statuses=statuses)


@router.get("/gateway", response_model=GatewayInfo)
def get_gateway() -> GatewayInfo:
    """Get gateway configuration summary."""
    config = load_config(settings.castle_root)
    return GatewayInfo(
        port=config.gateway.port,
        component_count=len(config.components),
        service_count=len(config.services),
        managed_count=len(config.managed),
    )
