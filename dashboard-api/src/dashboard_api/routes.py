"""API routes for the castle dashboard."""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, status

from castle_cli.config import load_config

from dashboard_api.config import settings
from dashboard_api.health import check_all_health
from dashboard_api.models import (
    ComponentDetail,
    ComponentSummary,
    GatewayInfo,
    StatusResponse,
    SystemdInfo,
)

router = APIRouter(tags=["dashboard"])


def _summary_from_manifest(name: str, manifest: object, root: Path) -> ComponentSummary:
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

    # Systemd info for managed components
    systemd_info: SystemdInfo | None = None
    if managed:
        unit_name = f"castle-{name}.service"
        unit_path = str(Path("~/.config/systemd/user") / unit_name)
        has_timer = any(getattr(t, "type", None) == "schedule" for t in manifest.triggers)
        systemd_info = SystemdInfo(
            unit_name=unit_name,
            unit_path=unit_path,
            timer=has_timer,
        )

    # Extract cron schedule from first schedule trigger, if any
    schedule = None
    for t in manifest.triggers:
        if t.type == "schedule":
            schedule = t.cron
            break

    # Infer runner — from run block or from tool source
    runner = manifest.run.runner if manifest.run else None
    if runner is None and manifest.tool and manifest.tool.source:
        source_dir = root / manifest.tool.source
        if (source_dir / "pyproject.toml").exists():
            runner = "python_uv_tool"
        elif source_dir.is_file():
            runner = "command"

    # Check if tool is actually installed on PATH
    installed: bool | None = None
    if manifest.install and manifest.install.path:
        alias = manifest.install.path.alias or name
        installed = shutil.which(alias) is not None

    return ComponentSummary(
        id=name,
        description=manifest.description,
        roles=[r.value for r in manifest.roles],
        runner=runner,
        port=port,
        health_path=health_path,
        proxy_path=proxy_path,
        managed=managed,
        systemd=systemd_info,
        version=manifest.tool.version if manifest.tool else None,
        source=manifest.tool.source if manifest.tool else None,
        system_dependencies=manifest.tool.system_dependencies if manifest.tool else [],
        schedule=schedule,
        installed=installed,
    )


@router.get("/components", response_model=list[ComponentSummary])
def list_components() -> list[ComponentSummary]:
    """List all registered components."""
    config = load_config(settings.castle_root)
    return [
        _summary_from_manifest(name, m, config.root)
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
    summary = _summary_from_manifest(name, manifest, config.root)
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


@router.get("/gateway/caddyfile")
def get_caddyfile() -> dict[str, str]:
    """Return the generated Caddyfile content."""
    from castle_cli.commands.gateway import _generate_caddyfile

    config = load_config(settings.castle_root)
    return {"content": _generate_caddyfile(config)}
