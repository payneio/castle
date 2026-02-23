"""API routes for the castle dashboard."""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, status

from castle_core.generators.caddyfile import generate_caddyfile_from_registry

from castle_api.config import get_castle_root, get_registry
from castle_api.health import check_all_health
from castle_api.models import (
    ComponentDetail,
    ComponentSummary,
    GatewayInfo,
    StatusResponse,
    SystemdInfo,
)

router = APIRouter(tags=["dashboard"])


def _summary_from_deployed(name: str, deployed: object) -> ComponentSummary:
    """Build a ComponentSummary from a DeployedComponent."""
    managed = deployed.managed

    systemd_info: SystemdInfo | None = None
    if managed:
        unit_name = f"castle-{name}.service"
        unit_path = str(Path("~/.config/systemd/user") / unit_name)
        has_timer = deployed.schedule is not None
        systemd_info = SystemdInfo(
            unit_name=unit_name,
            unit_path=unit_path,
            timer=has_timer,
        )

    # Check if tool is installed on PATH
    installed: bool | None = None
    if "tool" in deployed.roles:
        installed = shutil.which(name) is not None

    return ComponentSummary(
        id=name,
        description=deployed.description,
        roles=deployed.roles,
        runner=deployed.runner,
        port=deployed.port,
        health_path=deployed.health_path,
        proxy_path=deployed.proxy_path,
        managed=managed,
        systemd=systemd_info,
        schedule=deployed.schedule,
        installed=installed,
    )


def _summary_from_manifest(name: str, manifest: object, root: Path) -> ComponentSummary:
    """Build a ComponentSummary from a manifest (for non-deployed components)."""
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

    systemd_info: SystemdInfo | None = None
    if managed:
        unit_name = f"castle-{name}.service"
        unit_path = str(Path("~/.config/systemd/user") / unit_name)
        has_timer = any(
            getattr(t, "type", None) == "schedule" for t in manifest.triggers
        )
        systemd_info = SystemdInfo(
            unit_name=unit_name,
            unit_path=unit_path,
            timer=has_timer,
        )

    schedule = None
    for t in manifest.triggers:
        if t.type == "schedule":
            schedule = t.cron
            break

    runner = manifest.run.runner if manifest.run else None
    if runner is None and manifest.tool and manifest.tool.source:
        source_dir = root / manifest.tool.source
        if (source_dir / "pyproject.toml").exists():
            runner = "python_uv_tool"
        elif source_dir.is_file():
            runner = "command"

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
    """List all components — deployed from registry, non-deployed from castle.yaml."""
    registry = get_registry()
    summaries: list[ComponentSummary] = []
    seen: set[str] = set()

    # Deployed components from registry
    for name, deployed in registry.deployed.items():
        summaries.append(_summary_from_deployed(name, deployed))
        seen.add(name)

    # Non-deployed components from castle.yaml (if repo available)
    root = get_castle_root()
    if root:
        try:
            from castle_core.config import load_config

            config = load_config(root)
            for name, manifest in config.components.items():
                if name not in seen:
                    summaries.append(_summary_from_manifest(name, manifest, root))
        except FileNotFoundError:
            pass

    return summaries


@router.get("/components/{name}", response_model=ComponentDetail)
def get_component(name: str) -> ComponentDetail:
    """Get detailed info for a single component."""
    registry = get_registry()

    if name in registry.deployed:
        deployed = registry.deployed[name]
        summary = _summary_from_deployed(name, deployed)
        raw = {
            "runner": deployed.runner,
            "run_cmd": deployed.run_cmd,
            "env": deployed.env,
            "port": deployed.port,
            "health_path": deployed.health_path,
            "proxy_path": deployed.proxy_path,
            "managed": deployed.managed,
            "roles": deployed.roles,
        }
        return ComponentDetail(**summary.model_dump(), manifest=raw)

    # Fall back to castle.yaml
    root = get_castle_root()
    if root:
        from castle_core.config import load_config

        config = load_config(root)
        if name in config.components:
            manifest = config.components[name]
            summary = _summary_from_manifest(name, manifest, root)
            raw = manifest.model_dump(mode="json", exclude_none=True)
            return ComponentDetail(**summary.model_dump(), manifest=raw)

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Component '{name}' not found",
    )


@router.get("/status", response_model=StatusResponse)
async def get_status() -> StatusResponse:
    """Get live health status for all deployed services."""
    registry = get_registry()
    statuses = await check_all_health(registry)
    return StatusResponse(statuses=statuses)


@router.get("/gateway", response_model=GatewayInfo)
def get_gateway() -> GatewayInfo:
    """Get gateway configuration summary."""
    registry = get_registry()
    deployed_count = len(registry.deployed)
    service_count = sum(1 for d in registry.deployed.values() if d.port is not None)
    managed_count = sum(1 for d in registry.deployed.values() if d.managed)
    return GatewayInfo(
        port=registry.node.gateway_port,
        component_count=deployed_count,
        service_count=service_count,
        managed_count=managed_count,
    )


@router.get("/gateway/caddyfile")
def get_caddyfile() -> dict[str, str]:
    """Return the generated Caddyfile content."""
    registry = get_registry()
    return {"content": generate_caddyfile_from_registry(registry)}
