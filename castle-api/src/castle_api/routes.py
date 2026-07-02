"""API routes for the castle dashboard."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException, status

from castle_core.config import SPECS_DIR
from castle_core.generators.caddyfile import generate_caddyfile_from_registry
from castle_core.manifest import (
    ProgramSpec,
    SystemdDeployment,
    kind_for,
)
from castle_core.lifecycle import tool_installed
from castle_core.stacks import available_actions

from castle_api.config import get_castle_root, get_registry
from castle_api.mesh import mesh_state
from castle_api.health import check_all_health
from castle_api.models import (
    DeploymentDetail,
    DeploymentRef,
    DeploymentSummary,
    GatewayConfigRequest,
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


def _declared_commands_dict(comp: ProgramSpec) -> dict[str, list[list[str]]] | None:
    """Serialize a program's declared verbs for the API (build + CommandsSpec)."""
    out: dict[str, list[list[str]]] = {}
    if comp.build and comp.build.commands:
        out["build"] = comp.build.commands
    if comp.commands is not None:
        for verb in (
            "lint",
            "test",
            "type-check",
            "check",
            "run",
            "install",
            "uninstall",
        ):
            cmds = comp.commands.for_verb(verb)
            if cmds:
                out[verb] = cmds
    return out or None


def _summary_from_deployed(name: str, deployed: object) -> DeploymentSummary:
    """Build a DeploymentSummary from a Deployment."""
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

    # A PATH-managed deployment (a tool) is "installed" — and thus active — when
    # it's on PATH. (systemd/caddy liveness comes from the health/status stream.)
    installed: bool | None = None
    active: bool | None = None
    if deployed.manager == "path":
        installed = tool_installed(name)
        active = installed

    category = "job" if deployed.schedule else "service"

    return DeploymentSummary(
        id=name,
        category=category,
        description=deployed.description,
        kind=deployed.kind,
        stack=deployed.stack,
        manager=deployed.manager,
        launcher=deployed.launcher,
        port=deployed.port,
        health_path=deployed.health_path,
        subdomain=deployed.subdomain,
        managed=managed,
        systemd=systemd_info,
        schedule=deployed.schedule,
        installed=installed,
        active=active,
        enabled=deployed.enabled,
    )


def _summary_from_service(
    name: str, svc: SystemdDeployment, config: object
) -> DeploymentSummary:
    """Build a DeploymentSummary from a systemd deployment (service, non-deployed)."""
    port = None
    health_path = None
    if svc.expose and svc.expose.http:
        port = svc.expose.http.internal.port
        health_path = svc.expose.http.health_path
    subdomain = name if svc.proxy else None

    managed = bool(svc.manage and svc.manage.systemd and svc.manage.systemd.enable)

    systemd_info: SystemdInfo | None = None
    if managed:
        unit_name = f"castle-{name}.service"
        unit_path = str(Path("~/.config/systemd/user") / unit_name)
        systemd_info = SystemdInfo(
            unit_name=unit_name, unit_path=unit_path, timer=False
        )

    description = svc.description
    source = None
    stack = None
    if svc.program and svc.program in config.programs:
        comp = config.programs[svc.program]
        if not description:
            description = comp.description
        source = comp.source
        stack = comp.stack

    return DeploymentSummary(
        id=name,
        category="service",
        description=description,
        kind=kind_for(svc),
        stack=stack,
        manager="systemd",
        launcher=svc.run.launcher,
        port=port,
        health_path=health_path,
        subdomain=subdomain,
        managed=managed,
        systemd=systemd_info,
        source=source,
        enabled=svc.enabled,
    )


def _summary_from_job(name: str, job: SystemdDeployment, config: object) -> DeploymentSummary:
    """Build a DeploymentSummary from a systemd deployment (job, non-deployed)."""
    managed = bool(job.manage and job.manage.systemd and job.manage.systemd.enable)

    systemd_info: SystemdInfo | None = None
    if managed:
        unit_name = f"castle-{name}.service"
        unit_path = str(Path("~/.config/systemd/user") / unit_name)
        systemd_info = SystemdInfo(unit_name=unit_name, unit_path=unit_path, timer=True)

    description = job.description
    source = None
    stack = None
    if job.program and job.program in config.programs:
        comp = config.programs[job.program]
        if not description:
            description = comp.description
        source = comp.source
        stack = comp.stack

    return DeploymentSummary(
        id=name,
        category="job",
        description=description,
        kind="job",
        stack=stack,
        manager="systemd",
        launcher=job.run.launcher,
        managed=managed,
        systemd=systemd_info,
        schedule=job.schedule,
        source=source,
        enabled=job.enabled,
    )


def _summary_from_program(
    name: str, comp: ProgramSpec, root: Path
) -> DeploymentSummary:
    """Build a DeploymentSummary from a ProgramSpec (legacy unified view).

    A program has no single kind (kind is a deployment property), so the legacy
    entry carries none — the typed /programs view exposes its deployment list.
    """
    source = comp.source

    installed: bool | None = None
    if comp.source and (comp.stack or comp.commands):
        installed = tool_installed(name)

    return DeploymentSummary(
        id=name,
        category="program",
        description=comp.description,
        kind=None,
        stack=comp.stack,
        version=comp.version,
        source=source,
        repo=comp.repo,
        ref=comp.ref,
        commands=_declared_commands_dict(comp),
        system_dependencies=comp.system_dependencies,
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
        ref = config.services[name].program
    elif name in config.jobs:
        ref = config.jobs[name].program
    if ref and ref in config.programs:
        return config.programs[ref].source
    return None


def _run_target(run: object) -> str | None:
    """A human label for what a run spec executes (program / argv / image / …)."""
    if run is None:
        return None
    for attr in ("program", "image", "script", "base_url"):
        val = getattr(run, attr, None)
        if val:
            return str(val)
    argv = getattr(run, "argv", None)
    if argv:
        return " ".join(argv)
    return None


def _service_from_deployed(name: str, deployed: object) -> ServiceSummary:
    """Build a ServiceSummary from a Deployment."""
    systemd_info = _make_systemd_info(name) if deployed.managed else None
    run_target = " ".join(deployed.run_cmd) if deployed.run_cmd else None
    return ServiceSummary(
        id=name,
        description=deployed.description,
        stack=deployed.stack,
        kind=deployed.kind,
        manager=deployed.manager,
        launcher=deployed.launcher,
        run_target=run_target,
        port=deployed.port,
        health_path=deployed.health_path,
        subdomain=deployed.subdomain,
        managed=deployed.managed,
        systemd=systemd_info,
        enabled=deployed.enabled,
    )


def _service_from_spec(name: str, svc: SystemdDeployment, config: object) -> ServiceSummary:
    """Build a ServiceSummary from a systemd deployment."""
    port = None
    health_path = None
    if svc.expose and svc.expose.http:
        port = svc.expose.http.internal.port
        health_path = svc.expose.http.health_path
    # Exposed at <name>.<domain> when the proxy checkbox is on.
    subdomain = name if svc.proxy else None

    managed = bool(svc.manage and svc.manage.systemd and svc.manage.systemd.enable)
    systemd_info = _make_systemd_info(name) if managed else None

    description = svc.description
    source = None
    stack = None
    if svc.program and svc.program in config.programs:
        comp = config.programs[svc.program]
        if not description:
            description = comp.description
        source = comp.source
        stack = comp.stack

    return ServiceSummary(
        id=name,
        description=description,
        stack=stack,
        kind="service",
        manager="systemd",
        launcher=svc.run.launcher,
        run_target=_run_target(svc.run),
        port=port,
        health_path=health_path,
        subdomain=subdomain,
        managed=managed,
        systemd=systemd_info,
        program=svc.program,
        source=source,
        enabled=svc.enabled,
    )


def _job_from_deployed(name: str, deployed: object) -> JobSummary:
    """Build a JobSummary from a Deployment."""
    systemd_info = _make_systemd_info(name, timer=True) if deployed.managed else None
    run_target = " ".join(deployed.run_cmd) if deployed.run_cmd else None
    return JobSummary(
        id=name,
        description=deployed.description,
        stack=deployed.stack,
        launcher=deployed.launcher,
        run_target=run_target,
        schedule=deployed.schedule,
        managed=deployed.managed,
        systemd=systemd_info,
        enabled=deployed.enabled,
    )


def _job_from_spec(name: str, job: SystemdDeployment, config: object) -> JobSummary:
    """Build a JobSummary from a systemd deployment (job)."""
    managed = bool(job.manage and job.manage.systemd and job.manage.systemd.enable)
    systemd_info = _make_systemd_info(name, timer=True) if managed else None

    description = job.description
    source = None
    stack = None
    if job.program and job.program in config.programs:
        comp = config.programs[job.program]
        if not description:
            description = comp.description
        source = comp.source
        stack = comp.stack

    return JobSummary(
        id=name,
        description=description,
        stack=stack,
        launcher=job.run.launcher,
        run_target=_run_target(job.run),
        schedule=job.schedule,
        managed=managed,
        systemd=systemd_info,
        program=job.program,
        source=source,
        enabled=job.enabled,
    )


def _program_from_spec(
    name: str, comp: ProgramSpec, root: Path, config: object | None = None
) -> ProgramSummary:
    """Build a ProgramSummary from a ProgramSpec."""
    source = comp.source

    installed: bool | None = None
    if comp.source and (comp.stack or comp.commands):
        installed = tool_installed(name)

    # Uniform lifecycle state (on PATH / running / served) — needs full config.
    active: bool | None = None
    deployments: list[DeploymentRef] = []
    if config is not None:
        from castle_core.lifecycle import is_active

        active = is_active(name, config)
        # A program → 0-N deployments, each with its own kind.
        deployments = [
            DeploymentRef(name=dname, kind=kind)
            for dname, kind in config.deployments_of(name)
        ]

    return ProgramSummary(
        id=name,
        description=comp.description,
        stack=comp.stack,
        version=comp.version,
        source=source,
        repo=comp.repo,
        ref=comp.ref,
        commands=_declared_commands_dict(comp),
        system_dependencies=comp.system_dependencies,
        installed=installed,
        active=active,
        actions=available_actions(comp),
        deployments=deployments,
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

    # Services page shows services (systemd) AND statics (caddy) — both are
    # exposed, URL-reachable "services". Not jobs, tools, or remotes.
    for name, deployed in registry.deployed.items():
        if deployed.kind not in ("service", "static"):
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
    """Get detailed info for a single service.

    The `manifest` is the editable castle.yaml ServiceSpec whenever the service
    is declared there — that's the source of truth the config editor reads and
    writes. Only services that exist *only* in the runtime registry (e.g. infra
    not in castle.yaml) fall back to the flat deployed shape (display-only).
    """
    root = get_castle_root()
    config = None
    if root:
        try:
            from castle_core.config import load_config

            config = load_config(root)
        except FileNotFoundError:
            pass

    if config is not None and name in config.services:
        svc = config.services[name]
        summary = _service_from_spec(name, svc, config)
        manifest = svc.model_dump(mode="json", exclude_none=True)
        return ServiceDetail(**summary.model_dump(), manifest=manifest)

    registry = get_registry()
    if name in registry.deployed and not registry.deployed[name].schedule:
        deployed = registry.deployed[name]
        summary = _service_from_deployed(name, deployed)
        if config is not None and summary.source is None:
            summary.source = _backfill_source(name, config)
        manifest = {
            "manager": deployed.manager,
            "launcher": deployed.launcher,
            "run_cmd": deployed.run_cmd,
            "env": deployed.env,
            "secret_env_keys": deployed.secret_env_keys,
            "port": deployed.port,
            "health_path": deployed.health_path,
            "subdomain": deployed.subdomain,
            "managed": deployed.managed,
            "kind": deployed.kind,
            "stack": deployed.stack,
        }
        return ServiceDetail(**summary.model_dump(), manifest=manifest)

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
    """Get detailed info for a single job. `manifest` is the editable castle.yaml
    JobSpec when declared there; falls back to the runtime registry otherwise."""
    root = get_castle_root()
    config = None
    if root:
        try:
            from castle_core.config import load_config

            config = load_config(root)
        except FileNotFoundError:
            pass

    if config is not None and name in config.jobs:
        job = config.jobs[name]
        summary = _job_from_spec(name, job, config)
        manifest = job.model_dump(mode="json", exclude_none=True)
        return JobDetail(**summary.model_dump(), manifest=manifest)

    registry = get_registry()
    if name in registry.deployed and registry.deployed[name].schedule:
        deployed = registry.deployed[name]
        summary = _job_from_deployed(name, deployed)
        if config is not None and summary.source is None:
            summary.source = _backfill_source(name, config)
        manifest = {
            "manager": deployed.manager,
            "launcher": deployed.launcher,
            "run_cmd": deployed.run_cmd,
            "env": deployed.env,
            "secret_env_keys": deployed.secret_env_keys,
            "managed": deployed.managed,
            "schedule": deployed.schedule,
            "kind": deployed.kind,
            "stack": deployed.stack,
        }
        return JobDetail(**summary.model_dump(), manifest=manifest)

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Job '{name}' not found",
    )


@router.get("/programs", response_model=list[ProgramSummary], tags=["programs"])
def list_programs(kind: str | None = None) -> list[ProgramSummary]:
    """List all programs from the software catalog (castle.yaml programs section).

    Optionally filter by derived kind: service, job, tool, static, or reference.
    """
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
        # A program's kinds are the kinds of its deployments; filter by membership.
        if kind and kind not in {d.kind for d in summary.deployments}:
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


@router.get("/deployments", response_model=list[DeploymentSummary])
def list_components(include_remote: bool = False) -> list[DeploymentSummary]:
    """List all components — deployed from registry, non-deployed from castle.yaml.

    Pass ?include_remote=true to include components from remote mesh nodes.
    """
    registry = get_registry()
    local_hostname = registry.node.hostname
    summaries: list[DeploymentSummary] = []
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
                        ref = config.services[s.id].program
                    elif s.id in config.jobs:
                        ref = config.jobs[s.id].program
                    if ref and ref in config.programs:
                        s.source = config.programs[ref].source

            # Programs from the software catalog (legacy unified view)
            for name, comp in config.programs.items():
                summary = _summary_from_program(name, comp, root)
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
                        DeploymentSummary(
                            id=name,
                            category="job" if d.schedule else "service",
                            description=d.description,
                            kind=d.kind,
                            stack=d.stack,
                            manager=d.manager,
                            launcher=d.launcher,
                            port=d.port,
                            health_path=d.health_path,
                            subdomain=d.subdomain,
                            managed=d.managed,
                            schedule=d.schedule,
                            node=hostname,
                        )
                    )
                    seen.add(name)

    return summaries


@router.get("/deployments/{name}", response_model=DeploymentDetail)
def get_component(name: str) -> DeploymentDetail:
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
                        ref = config.services[name].program
                    elif name in config.jobs:
                        ref = config.jobs[name].program
                    if ref and ref in config.programs:
                        summary.source = config.programs[ref].source
            except FileNotFoundError:
                pass

        raw = {
            "manager": deployed.manager,
            "launcher": deployed.launcher,
            "run_cmd": deployed.run_cmd,
            "env": deployed.env,
            "secret_env_keys": deployed.secret_env_keys,
            "port": deployed.port,
            "health_path": deployed.health_path,
            "subdomain": deployed.subdomain,
            "managed": deployed.managed,
            "kind": deployed.kind,
            "stack": deployed.stack,
        }
        return DeploymentDetail(**summary.model_dump(), manifest=raw)

    # Fall back to castle.yaml
    root = get_castle_root()
    if root:
        from castle_core.config import load_config

        config = load_config(root)

        if name in config.services:
            svc = config.services[name]
            summary = _summary_from_service(name, svc, config)
            raw = svc.model_dump(mode="json", exclude_none=True)
            return DeploymentDetail(**summary.model_dump(), manifest=raw)

        if name in config.jobs:
            job = config.jobs[name]
            summary = _summary_from_job(name, job, config)
            raw = job.model_dump(mode="json", exclude_none=True)
            return DeploymentDetail(**summary.model_dump(), manifest=raw)

        if name in config.programs:
            comp = config.programs[name]
            summary = _summary_from_program(name, comp, root)
            raw = comp.model_dump(mode="json", exclude_none=True)
            return DeploymentDetail(**summary.model_dump(), manifest=raw)

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"'{name}' not found",
    )


@router.get("/status", response_model=StatusResponse)
async def get_status() -> StatusResponse:
    """Get live health status for all deployed services."""
    registry = get_registry()
    statuses = await check_all_health(registry)
    return StatusResponse(statuses=statuses)


@router.get("/gateway", response_model=GatewayInfo)
def get_gateway() -> GatewayInfo:
    """Get gateway configuration summary, including the full route table.

    Routes are computed by the same function that generates the Caddyfile, so
    the table matches reality: static-served frontends, path/host proxies, and
    cross-node routes all appear, each tagged with its kind and target.
    """
    from castle_core.generators.caddyfile import compute_routes

    registry = get_registry()
    deployed_count = len(registry.deployed)
    service_count = sum(1 for d in registry.deployed.values() if d.port is not None)
    managed_count = sum(1 for d in registry.deployed.values() if d.managed)

    config = None
    root = get_castle_root()
    if root:
        try:
            from castle_core.config import load_config

            config = load_config(root)
        except FileNotFoundError:
            pass

    # Which local services are public → their public URL (<name>.<public_domain>).
    public_domain = registry.node.public_domain
    public_names = {
        name for name, svc in (config.services.items() if config else [])
        if getattr(svc, "public", False)
    }

    remote = {h: r.registry for h, r in mesh_state.all_nodes().items()}
    routes = [
        GatewayRoute(
            address=r.address,
            kind=r.kind,
            target=r.target,
            name=r.name,
            node=r.node or registry.node.hostname,
            public_url=(
                f"https://{r.name}.{public_domain}"
                if public_domain and r.name in public_names
                else None
            ),
        )
        for r in compute_routes(registry, config, remote or None)
    ]
    # Caddyfile order is precedence-sensitive; the displayed table is alphabetical.
    routes.sort(key=lambda r: r.address)

    tunnel_connected = (
        subprocess.run(
            ["systemctl", "--user", "is-active", "castle-castle-tunnel.service"],
            capture_output=True, text=True,
        ).stdout.strip()
        == "active"
    )

    return GatewayInfo(
        port=registry.node.gateway_port,
        hostname=registry.node.hostname,
        deployment_count=deployed_count,
        service_count=service_count,
        managed_count=managed_count,
        routes=routes,
        tls=registry.node.gateway_tls,
        domain=registry.node.gateway_domain,
        public_domain=public_domain,
        tunnel_id=registry.node.tunnel_id,
        tunnel_connected=tunnel_connected,
    )


@router.put("/gateway/config")
def save_gateway_config(request: GatewayConfigRequest) -> dict[str, str]:
    """Update the gateway's routing/exposure settings in castle.yaml.

    Saves only; the caller runs deploy to regenerate the Caddyfile + tunnel config.
    An empty string clears a field.
    """
    root = get_castle_root()
    if root is None:
        raise HTTPException(status_code=404, detail="No castle root found.")
    from castle_core.config import load_config, save_config

    config = load_config(root)
    norm = lambda v: (v or None)  # noqa: E731 — empty string clears
    config.gateway.tls = norm(request.tls)
    config.gateway.domain = norm(request.domain)
    config.gateway.public_domain = norm(request.public_domain)
    config.gateway.tunnel_id = norm(request.tunnel_id)
    save_config(config)
    return {"status": "saved", "message": "Saved. Run deploy to apply."}


@router.get("/gateway/caddyfile")
def get_caddyfile() -> dict[str, str]:
    """Return the generated Caddyfile content."""
    registry = get_registry()
    return {"content": generate_caddyfile_from_registry(registry)}


@router.post("/gateway/reload")
async def reload_gateway() -> dict[str, str]:
    """Regenerate Caddyfile and reload Caddy."""
    registry = get_registry()
    SPECS_DIR.mkdir(parents=True, exist_ok=True)
    caddyfile_path = SPECS_DIR / "Caddyfile"

    # Include remote registries for cross-node routing
    remote_regs = {h: n.registry for h, n in mesh_state.all_nodes().items()}
    caddyfile_path.write_text(
        generate_caddyfile_from_registry(
            registry, remote_registries=remote_regs or None
        )
    )

    proc = await asyncio.create_subprocess_exec(
        "systemctl",
        "--user",
        "reload",
        "castle-castle-gateway.service",
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
