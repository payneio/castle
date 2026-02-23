"""API routes for the castle dashboard."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, status

from castle_core.config import GENERATED_DIR
from castle_core.generators.caddyfile import generate_caddyfile_from_registry
from castle_core.manifest import ComponentSpec, JobSpec, ServiceSpec

from castle_api.config import get_castle_root, get_registry
from castle_api.mesh import mesh_state
from castle_api.health import check_all_health
from castle_api.models import (
    ComponentDetail,
    ComponentSummary,
    GatewayInfo,
    GatewayRoute,
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
    if deployed.category == "tool":
        installed = shutil.which(name) is not None

    return ComponentSummary(
        id=name,
        description=deployed.description,
        category=deployed.category,
        runner=deployed.runner,
        port=deployed.port,
        health_path=deployed.health_path,
        proxy_path=deployed.proxy_path,
        managed=managed,
        systemd=systemd_info,
        schedule=deployed.schedule,
        installed=installed,
    )


def _summary_from_service(name: str, svc: ServiceSpec, config: object) -> ComponentSummary:
    """Build a ComponentSummary from a ServiceSpec (non-deployed)."""
    port = None
    health_path = None
    proxy_path = None
    if svc.expose and svc.expose.http:
        port = svc.expose.http.internal.port
        health_path = svc.expose.http.health_path
    if svc.proxy and svc.proxy.caddy:
        proxy_path = svc.proxy.caddy.path_prefix

    managed = bool(svc.manage and svc.manage.systemd and svc.manage.systemd.enable)

    systemd_info: SystemdInfo | None = None
    if managed:
        unit_name = f"castle-{name}.service"
        unit_path = str(Path("~/.config/systemd/user") / unit_name)
        systemd_info = SystemdInfo(unit_name=unit_name, unit_path=unit_path, timer=False)

    description = svc.description
    source = None
    if svc.component and svc.component in config.components:
        comp = config.components[svc.component]
        if not description:
            description = comp.description
        source = comp.source

    runner = svc.run.runner

    return ComponentSummary(
        id=name,
        description=description,
        category="service",
        runner=runner,
        port=port,
        health_path=health_path,
        proxy_path=proxy_path,
        managed=managed,
        systemd=systemd_info,
        source=source,
    )


def _summary_from_job(name: str, job: JobSpec, config: object) -> ComponentSummary:
    """Build a ComponentSummary from a JobSpec (non-deployed)."""
    managed = bool(job.manage and job.manage.systemd and job.manage.systemd.enable)

    systemd_info: SystemdInfo | None = None
    if managed:
        unit_name = f"castle-{name}.service"
        unit_path = str(Path("~/.config/systemd/user") / unit_name)
        systemd_info = SystemdInfo(unit_name=unit_name, unit_path=unit_path, timer=True)

    description = job.description
    source = None
    if job.component and job.component in config.components:
        comp = config.components[job.component]
        if not description:
            description = comp.description
        source = comp.source

    return ComponentSummary(
        id=name,
        description=description,
        category="job",
        runner=job.run.runner,
        managed=managed,
        systemd=systemd_info,
        schedule=job.schedule,
        source=source,
    )


def _summary_from_component(name: str, comp: ComponentSpec, root: Path) -> ComponentSummary:
    """Build a ComponentSummary from a ComponentSpec (tools/frontends)."""
    # Determine category
    is_tool = bool((comp.install and comp.install.path) or comp.tool)
    is_frontend = bool(comp.build and (comp.build.outputs or comp.build.commands))

    if is_tool:
        category = "tool"
    elif is_frontend:
        category = "frontend"
    else:
        category = "component"

    source = comp.source

    # Infer runner from source directory
    runner = None
    if source:
        source_dir = root / source
        if (source_dir / "pyproject.toml").exists():
            runner = "python"
        elif source_dir.is_file():
            runner = "command"

    installed: bool | None = None
    if comp.install and comp.install.path:
        alias = comp.install.path.alias or name
        installed = shutil.which(alias) is not None

    return ComponentSummary(
        id=name,
        description=comp.description,
        category=category,
        runner=runner,
        version=comp.tool.version if comp.tool else None,
        source=source,
        system_dependencies=comp.tool.system_dependencies if comp.tool else [],
        installed=installed,
    )


@router.get("/components", response_model=list[ComponentSummary])
def list_components(include_remote: bool = False) -> list[ComponentSummary]:
    """List all components — deployed from registry, non-deployed from castle.yaml.

    Pass ?include_remote=true to include components from remote mesh nodes.
    """
    registry = get_registry()
    local_hostname = registry.node.hostname
    summaries: list[ComponentSummary] = []
    seen: set[str] = set()

    # Deployed components from registry
    for name, deployed in registry.deployed.items():
        s = _summary_from_deployed(name, deployed)
        s.node = local_hostname
        summaries.append(s)
        seen.add(name)

    # Non-deployed from castle.yaml (if repo available)
    root = get_castle_root()
    if root:
        try:
            from castle_core.config import load_config

            config = load_config(root)

            # Services not in registry
            for name, svc in config.services.items():
                if name not in seen:
                    s = _summary_from_service(name, svc, config)
                    s.node = local_hostname
                    summaries.append(s)
                    seen.add(name)

            # Jobs not in registry
            for name, job in config.jobs.items():
                if name not in seen:
                    s = _summary_from_job(name, job, config)
                    s.node = local_hostname
                    summaries.append(s)
                    seen.add(name)

            # Backfill source from component refs for deployed items
            for s in summaries:
                if s.source is None and s.id in config.components:
                    s.source = config.components[s.id].source
                elif s.source is None:
                    # Check if a service/job references a component
                    ref = None
                    if s.id in config.services:
                        ref = config.services[s.id].component
                    elif s.id in config.jobs:
                        ref = config.jobs[s.id].component
                    if ref and ref in config.components:
                        s.source = config.components[ref].source

            # Components (tools/frontends) — always listed, even if a
            # service/job with the same name exists.  A component is
            # "what software exists", services/jobs are "how it runs".
            for name, comp in config.components.items():
                summary = _summary_from_component(name, comp, root)
                summary.node = local_hostname
                # Skip if this exact category is already represented
                # (e.g. a deployed tool already in the list)
                if not any(s.id == name and s.category == summary.category for s in summaries):
                    summaries.append(summary)
        except FileNotFoundError:
            pass

    # Remote components from mesh (local wins on name conflicts)
    if include_remote:
        for hostname, remote in mesh_state.all_nodes().items():
            for name, d in remote.registry.deployed.items():
                if name not in seen:
                    summaries.append(
                        ComponentSummary(
                            id=name,
                            description=d.description,
                            category=d.category,
                            runner=d.runner,
                            port=d.port,
                            health_path=d.health_path,
                            proxy_path=d.proxy_path,
                            managed=d.managed,
                            schedule=d.schedule,
                            node=hostname,
                        )
                    )
                    seen.add(name)

    return summaries


@router.get("/components/{name}", response_model=ComponentDetail)
def get_component(name: str) -> ComponentDetail:
    """Get detailed info for a single component."""
    registry = get_registry()

    if name in registry.deployed:
        deployed = registry.deployed[name]
        summary = _summary_from_deployed(name, deployed)

        # Backfill source from castle.yaml component ref
        root = get_castle_root()
        if root and summary.source is None:
            try:
                from castle_core.config import load_config

                config = load_config(root)
                if name in config.components:
                    summary.source = config.components[name].source
                else:
                    ref = None
                    if name in config.services:
                        ref = config.services[name].component
                    elif name in config.jobs:
                        ref = config.jobs[name].component
                    if ref and ref in config.components:
                        summary.source = config.components[ref].source
            except FileNotFoundError:
                pass

        raw = {
            "runner": deployed.runner,
            "run_cmd": deployed.run_cmd,
            "env": deployed.env,
            "port": deployed.port,
            "health_path": deployed.health_path,
            "proxy_path": deployed.proxy_path,
            "managed": deployed.managed,
            "category": deployed.category,
        }
        return ComponentDetail(**summary.model_dump(), manifest=raw)

    # Fall back to castle.yaml
    root = get_castle_root()
    if root:
        from castle_core.config import load_config

        config = load_config(root)

        if name in config.services:
            svc = config.services[name]
            summary = _summary_from_service(name, svc, config)
            raw = svc.model_dump(mode="json", exclude_none=True)
            return ComponentDetail(**summary.model_dump(), manifest=raw)

        if name in config.jobs:
            job = config.jobs[name]
            summary = _summary_from_job(name, job, config)
            raw = job.model_dump(mode="json", exclude_none=True)
            return ComponentDetail(**summary.model_dump(), manifest=raw)

        if name in config.components:
            comp = config.components[name]
            summary = _summary_from_component(name, comp, root)
            raw = comp.model_dump(mode="json", exclude_none=True)
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

    # Local routes
    routes: list[GatewayRoute] = [
        GatewayRoute(
            path=d.proxy_path,
            target_port=d.port,
            component=name,
            node=registry.node.hostname,
        )
        for name, d in registry.deployed.items()
        if d.proxy_path and d.port
    ]

    # Remote routes from mesh (local paths take precedence)
    local_paths = {r.path for r in routes}
    for hostname, remote in mesh_state.all_nodes().items():
        for name, d in remote.registry.deployed.items():
            if d.proxy_path and d.port and d.proxy_path not in local_paths:
                routes.append(
                    GatewayRoute(
                        path=d.proxy_path,
                        target_port=d.port,
                        component=name,
                        node=hostname,
                    )
                )

    routes.sort(key=lambda r: r.path)

    return GatewayInfo(
        port=registry.node.gateway_port,
        hostname=registry.node.hostname,
        component_count=deployed_count,
        service_count=service_count,
        managed_count=managed_count,
        routes=routes,
    )


@router.get("/gateway/caddyfile")
def get_caddyfile() -> dict[str, str]:
    """Return the generated Caddyfile content."""
    registry = get_registry()
    return {"content": generate_caddyfile_from_registry(registry)}


@router.post("/gateway/reload")
async def reload_gateway() -> dict[str, str]:
    """Regenerate Caddyfile and reload Caddy."""
    registry = get_registry()
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    caddyfile_path = GENERATED_DIR / "Caddyfile"

    # Include remote registries for cross-node routing
    remote_regs = {h: n.registry for h, n in mesh_state.all_nodes().items()}
    caddyfile_path.write_text(
        generate_caddyfile_from_registry(registry, remote_registries=remote_regs or None)
    )

    proc = await asyncio.create_subprocess_exec(
        "systemctl", "--user", "reload", "castle-castle-gateway.service",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=f"Reload failed: {(stderr or b'').decode().strip()}",
        )

    return {"status": "ok"}
