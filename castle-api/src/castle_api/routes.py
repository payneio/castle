"""API routes for the castle dashboard."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, status

from castle_core.config import GENERATED_DIR
from castle_core.generators.caddyfile import generate_caddyfile_from_registry
from castle_core.manifest import ProgramSpec, JobSpec, ServiceSpec
from castle_core.stacks import available_actions

from castle_api.config import get_castle_root, get_registry
from castle_api.mesh import mesh_state
from castle_api.health import check_all_health
from castle_api.models import (
    ComponentDetail,
    ComponentSummary,
    GatewayInfo,
    GatewayRoute,
    JobDetail,
    JobSummary,
    ProgramDetail,
    ProgramSummary,
    ServiceDetail,
    ServiceSummary,
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
    if deployed.behavior == "tool":
        installed = shutil.which(name) is not None

    category = "job" if deployed.schedule else "service"

    return ComponentSummary(
        id=name,
        category=category,
        description=deployed.description,
        behavior=deployed.behavior,
        stack=deployed.stack,
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
    stack = None
    if svc.component and svc.component in config.programs:
        comp = config.programs[svc.component]
        if not description:
            description = comp.description
        source = comp.source
        stack = comp.stack

    runner = svc.run.runner

    return ComponentSummary(
        id=name,
        category="service",
        description=description,
        behavior="daemon",
        stack=stack,
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
    stack = None
    if job.component and job.component in config.programs:
        comp = config.programs[job.component]
        if not description:
            description = comp.description
        source = comp.source
        stack = comp.stack

    return ComponentSummary(
        id=name,
        category="job",
        description=description,
        behavior="tool",
        stack=stack,
        runner=job.run.runner,
        managed=managed,
        systemd=systemd_info,
        schedule=job.schedule,
        source=source,
    )


def _summary_from_program(name: str, comp: ProgramSpec, root: Path) -> ComponentSummary:
    """Build a ComponentSummary from a ProgramSpec (tools/frontends)."""
    # Determine behavior
    is_tool = bool((comp.install and comp.install.path) or comp.tool)
    is_frontend = bool(comp.build and (comp.build.outputs or comp.build.commands))

    if is_tool:
        behavior = "tool"
    elif is_frontend:
        behavior = "frontend"
    else:
        behavior = None

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
        category="program",
        description=comp.description,
        behavior=behavior,
        stack=comp.stack,
        runner=runner,
        version=comp.tool.version if comp.tool else None,
        source=source,
        system_dependencies=comp.tool.system_dependencies if comp.tool else [],
        installed=installed,
    )


# ---------------------------------------------------------------------------
# Typed builder functions — one per concept
# ---------------------------------------------------------------------------


def _make_systemd_info(name: str, timer: bool = False) -> SystemdInfo:
    unit_name = f"castle-{name}.service"
    unit_path = str(Path("~/.config/systemd/user") / unit_name)
    return SystemdInfo(unit_name=unit_name, unit_path=unit_path, timer=timer)


def _backfill_source(name: str, config: object) -> str | None:
    """Resolve source path from program ref in config."""
    if name in config.programs:
        return config.programs[name].source
    ref = None
    if name in config.services:
        ref = config.services[name].component
    elif name in config.jobs:
        ref = config.jobs[name].component
    if ref and ref in config.programs:
        return config.programs[ref].source
    return None


def _service_from_deployed(name: str, deployed: object) -> ServiceSummary:
    """Build a ServiceSummary from a DeployedComponent."""
    systemd_info = _make_systemd_info(name) if deployed.managed else None
    return ServiceSummary(
        id=name,
        description=deployed.description,
        stack=deployed.stack,
        runner=deployed.runner,
        port=deployed.port,
        health_path=deployed.health_path,
        proxy_path=deployed.proxy_path,
        managed=deployed.managed,
        systemd=systemd_info,
    )


def _service_from_spec(
    name: str, svc: ServiceSpec, config: object
) -> ServiceSummary:
    """Build a ServiceSummary from a ServiceSpec."""
    port = None
    health_path = None
    proxy_path = None
    if svc.expose and svc.expose.http:
        port = svc.expose.http.internal.port
        health_path = svc.expose.http.health_path
    if svc.proxy and svc.proxy.caddy:
        proxy_path = svc.proxy.caddy.path_prefix

    managed = bool(svc.manage and svc.manage.systemd and svc.manage.systemd.enable)
    systemd_info = _make_systemd_info(name) if managed else None

    description = svc.description
    source = None
    stack = None
    if svc.component and svc.component in config.programs:
        comp = config.programs[svc.component]
        if not description:
            description = comp.description
        source = comp.source
        stack = comp.stack

    return ServiceSummary(
        id=name,
        description=description,
        stack=stack,
        runner=svc.run.runner,
        port=port,
        health_path=health_path,
        proxy_path=proxy_path,
        managed=managed,
        systemd=systemd_info,
        source=source,
    )


def _job_from_deployed(name: str, deployed: object) -> JobSummary:
    """Build a JobSummary from a DeployedComponent."""
    systemd_info = (
        _make_systemd_info(name, timer=True) if deployed.managed else None
    )
    return JobSummary(
        id=name,
        description=deployed.description,
        stack=deployed.stack,
        runner=deployed.runner,
        schedule=deployed.schedule,
        managed=deployed.managed,
        systemd=systemd_info,
    )


def _job_from_spec(name: str, job: JobSpec, config: object) -> JobSummary:
    """Build a JobSummary from a JobSpec."""
    managed = bool(job.manage and job.manage.systemd and job.manage.systemd.enable)
    systemd_info = _make_systemd_info(name, timer=True) if managed else None

    description = job.description
    source = None
    stack = None
    if job.component and job.component in config.programs:
        comp = config.programs[job.component]
        if not description:
            description = comp.description
        source = comp.source
        stack = comp.stack

    return JobSummary(
        id=name,
        description=description,
        stack=stack,
        runner=job.run.runner,
        schedule=job.schedule,
        managed=managed,
        systemd=systemd_info,
        source=source,
    )


def _program_from_spec(
    name: str, comp: ProgramSpec, root: Path, config: object | None = None
) -> ProgramSummary:
    """Build a ProgramSummary from a ProgramSpec."""
    is_tool = bool((comp.install and comp.install.path) or comp.tool)
    is_frontend = bool(comp.build and (comp.build.outputs or comp.build.commands))

    if is_tool:
        behavior = "tool"
    elif is_frontend:
        behavior = "frontend"
    else:
        behavior = None

    # Derive behavior from backing service/job
    if behavior is None and config is not None:
        svc_components = {
            s.component for s in config.services.values() if s.component
        }
        job_components = {
            j.component for j in config.jobs.values() if j.component
        }
        if name in svc_components or name in config.services:
            behavior = "daemon"
        elif name in job_components or name in config.jobs:
            behavior = "tool"

    source = comp.source
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
    elif config is not None:
        # Daemons: check if the service's run.tool binary is on PATH
        svc = config.services.get(name)
        if svc and hasattr(svc.run, "tool"):
            installed = shutil.which(svc.run.tool) is not None

    return ProgramSummary(
        id=name,
        description=comp.description,
        behavior=behavior,
        stack=comp.stack,
        runner=runner,
        version=comp.tool.version if comp.tool else None,
        source=source,
        system_dependencies=comp.tool.system_dependencies if comp.tool else [],
        installed=installed,
        actions=available_actions(comp),
    )


# ---------------------------------------------------------------------------
# Typed endpoints — /services, /jobs, /programs
# ---------------------------------------------------------------------------


@router.get("/services", response_model=list[ServiceSummary], tags=["services-data"])
def list_services(include_remote: bool = False) -> list[ServiceSummary]:
    """List all services — deployed from registry, non-deployed from castle.yaml."""
    registry = get_registry()
    hostname = registry.node.hostname
    summaries: list[ServiceSummary] = []
    seen: set[str] = set()

    # Deployed services (non-scheduled)
    for name, deployed in registry.deployed.items():
        if deployed.schedule:
            continue
        s = _service_from_deployed(name, deployed)
        s.node = hostname
        # Backfill source
        root = get_castle_root()
        if root and s.source is None:
            try:
                from castle_core.config import load_config

                config = load_config(root)
                s.source = _backfill_source(name, config)
            except FileNotFoundError:
                pass
        summaries.append(s)
        seen.add(name)

    # Non-deployed from castle.yaml
    root = get_castle_root()
    if root:
        try:
            from castle_core.config import load_config

            config = load_config(root)
            for name, svc in config.services.items():
                if name not in seen:
                    s = _service_from_spec(name, svc, config)
                    s.node = hostname
                    summaries.append(s)
                    seen.add(name)
        except FileNotFoundError:
            pass

    # Remote
    if include_remote:
        for remote_host, remote in mesh_state.all_nodes().items():
            for name, d in remote.registry.deployed.items():
                if not d.schedule and name not in seen:
                    s = _service_from_deployed(name, d)
                    s.node = remote_host
                    summaries.append(s)
                    seen.add(name)

    return summaries


@router.get(
    "/services/{name}",
    response_model=ServiceDetail,
    tags=["services-data"],
)
def get_service(name: str) -> ServiceDetail:
    """Get detailed info for a single service."""
    registry = get_registry()

    if name in registry.deployed and not registry.deployed[name].schedule:
        deployed = registry.deployed[name]
        summary = _service_from_deployed(name, deployed)
        root = get_castle_root()
        if root and summary.source is None:
            try:
                from castle_core.config import load_config

                config = load_config(root)
                summary.source = _backfill_source(name, config)
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
            "behavior": deployed.behavior,
            "stack": deployed.stack,
        }
        return ServiceDetail(**summary.model_dump(), manifest=raw)

    root = get_castle_root()
    if root:
        from castle_core.config import load_config

        config = load_config(root)
        if name in config.services:
            svc = config.services[name]
            summary = _service_from_spec(name, svc, config)
            raw = svc.model_dump(mode="json", exclude_none=True)
            return ServiceDetail(**summary.model_dump(), manifest=raw)

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Service '{name}' not found",
    )


@router.get("/jobs", response_model=list[JobSummary], tags=["jobs-data"])
def list_jobs(include_remote: bool = False) -> list[JobSummary]:
    """List all jobs — deployed from registry, non-deployed from castle.yaml."""
    registry = get_registry()
    hostname = registry.node.hostname
    summaries: list[JobSummary] = []
    seen: set[str] = set()

    # Deployed jobs (scheduled)
    for name, deployed in registry.deployed.items():
        if not deployed.schedule:
            continue
        s = _job_from_deployed(name, deployed)
        s.node = hostname
        root = get_castle_root()
        if root and s.source is None:
            try:
                from castle_core.config import load_config

                config = load_config(root)
                s.source = _backfill_source(name, config)
            except FileNotFoundError:
                pass
        summaries.append(s)
        seen.add(name)

    # Non-deployed from castle.yaml
    root = get_castle_root()
    if root:
        try:
            from castle_core.config import load_config

            config = load_config(root)
            for name, job in config.jobs.items():
                if name not in seen:
                    s = _job_from_spec(name, job, config)
                    s.node = hostname
                    summaries.append(s)
                    seen.add(name)
        except FileNotFoundError:
            pass

    # Remote
    if include_remote:
        for remote_host, remote in mesh_state.all_nodes().items():
            for name, d in remote.registry.deployed.items():
                if d.schedule and name not in seen:
                    s = _job_from_deployed(name, d)
                    s.node = remote_host
                    summaries.append(s)
                    seen.add(name)

    return summaries


@router.get("/jobs/{name}", response_model=JobDetail, tags=["jobs-data"])
def get_job(name: str) -> JobDetail:
    """Get detailed info for a single job."""
    registry = get_registry()

    if name in registry.deployed and registry.deployed[name].schedule:
        deployed = registry.deployed[name]
        summary = _job_from_deployed(name, deployed)
        root = get_castle_root()
        if root and summary.source is None:
            try:
                from castle_core.config import load_config

                config = load_config(root)
                summary.source = _backfill_source(name, config)
            except FileNotFoundError:
                pass
        raw = {
            "runner": deployed.runner,
            "run_cmd": deployed.run_cmd,
            "env": deployed.env,
            "managed": deployed.managed,
            "schedule": deployed.schedule,
            "behavior": deployed.behavior,
            "stack": deployed.stack,
        }
        return JobDetail(**summary.model_dump(), manifest=raw)

    root = get_castle_root()
    if root:
        from castle_core.config import load_config

        config = load_config(root)
        if name in config.jobs:
            job = config.jobs[name]
            summary = _job_from_spec(name, job, config)
            raw = job.model_dump(mode="json", exclude_none=True)
            return JobDetail(**summary.model_dump(), manifest=raw)

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Job '{name}' not found",
    )


@router.get("/programs", response_model=list[ProgramSummary], tags=["programs"])
def list_programs() -> list[ProgramSummary]:
    """List all programs from the software catalog (castle.yaml programs section)."""
    root = get_castle_root()
    if not root:
        return []

    try:
        from castle_core.config import load_config

        config = load_config(root)
    except FileNotFoundError:
        return []

    hostname = get_registry().node.hostname
    summaries: list[ProgramSummary] = []

    for name, comp in config.programs.items():
        summary = _program_from_spec(name, comp, root, config)
        if summary.behavior is None:
            continue
        summary.node = hostname
        summaries.append(summary)

    return summaries


@router.get("/programs/{name}", response_model=ProgramDetail, tags=["programs"])
def get_program(name: str) -> ProgramDetail:
    """Get detailed info for a single program."""
    root = get_castle_root()
    if root:
        from castle_core.config import load_config

        config = load_config(root)
        if name in config.programs:
            comp = config.programs[name]
            summary = _program_from_spec(name, comp, root, config)
            raw = comp.model_dump(mode="json", exclude_none=True)
            return ProgramDetail(**summary.model_dump(), manifest=raw)

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Program '{name}' not found",
    )


# ---------------------------------------------------------------------------
# Legacy /components endpoint (compat shim)
# ---------------------------------------------------------------------------


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

            # Backfill source from program refs for deployed items
            for s in summaries:
                if s.source is None and s.id in config.programs:
                    s.source = config.programs[s.id].source
                elif s.source is None:
                    # Check if a service/job references a program
                    ref = None
                    if s.id in config.services:
                        ref = config.services[s.id].component
                    elif s.id in config.jobs:
                        ref = config.jobs[s.id].component
                    if ref and ref in config.programs:
                        s.source = config.programs[ref].source

            # Programs — always include entries from the programs
            # section as catalog items.  Derive behavior from backing
            # service/job when the program has no install/build spec.
            svc_components = {s.component for s in config.services.values() if s.component}
            job_components = {j.component for j in config.jobs.values() if j.component}

            for name, comp in config.programs.items():
                summary = _summary_from_program(name, comp, root)
                if summary.behavior is None:
                    if name in svc_components or name in config.services:
                        summary.behavior = "daemon"
                    elif name in job_components or name in config.jobs:
                        summary.behavior = "tool"
                    else:
                        continue
                summary.node = local_hostname
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
                            category="job" if d.schedule else "service",
                            description=d.description,
                            behavior=d.behavior,
                            stack=d.stack,
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

        # Backfill source from castle.yaml program ref
        root = get_castle_root()
        if root and summary.source is None:
            try:
                from castle_core.config import load_config

                config = load_config(root)
                if name in config.programs:
                    summary.source = config.programs[name].source
                else:
                    ref = None
                    if name in config.services:
                        ref = config.services[name].component
                    elif name in config.jobs:
                        ref = config.jobs[name].component
                    if ref and ref in config.programs:
                        summary.source = config.programs[ref].source
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
            "behavior": deployed.behavior,
            "stack": deployed.stack,
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

        if name in config.programs:
            comp = config.programs[name]
            summary = _summary_from_program(name, comp, root)
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
