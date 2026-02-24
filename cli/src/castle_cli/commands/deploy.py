"""castle deploy — bridge spec (castle.yaml) to runtime (~/.castle/)."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

from castle_core.config import (
    GENERATED_DIR,
    STATIC_DIR,
    CastleConfig,
    ensure_dirs,
    load_config,
    resolve_env_vars,
)
from castle_core.generators.caddyfile import generate_caddyfile_from_registry
from castle_core.generators.systemd import (
    generate_timer,
    generate_unit_from_deployed,
    timer_name,
    unit_name,
)
from castle_core.manifest import JobSpec, ServiceSpec
from castle_core.registry import (
    REGISTRY_PATH,
    DeployedComponent,
    NodeConfig,
    NodeRegistry,
    load_registry,
    save_registry,
)

DATA_ROOT = Path("/data/castle")
SYSTEMD_USER_DIR = Path.home() / ".config" / "systemd" / "user"


def run_deploy(args: argparse.Namespace) -> int:
    """Deploy components from castle.yaml to ~/.castle/."""
    config = load_config()
    target_name = getattr(args, "component", None)

    ensure_dirs()

    # Build node config
    node = NodeConfig(castle_root=str(config.root), gateway_port=config.gateway.port)

    # Load existing registry to preserve components not being redeployed,
    # or start fresh if deploying all
    if target_name and REGISTRY_PATH.exists():
        try:
            existing = load_registry()
            registry = NodeRegistry(node=node, deployed=dict(existing.deployed))
        except (FileNotFoundError, ValueError):
            registry = NodeRegistry(node=node)
    else:
        registry = NodeRegistry(node=node)

    deployed_count = 0

    # Deploy services
    for name, svc in config.services.items():
        if target_name and name != target_name:
            continue
        deployed = _build_deployed_service(config, name, svc)
        registry.deployed[name] = deployed
        deployed_count += 1
        _print_deployed(name, deployed)

    # Deploy jobs
    for name, job in config.jobs.items():
        if target_name and name != target_name:
            continue
        deployed = _build_deployed_job(config, name, job)
        registry.deployed[name] = deployed
        deployed_count += 1
        _print_deployed(name, deployed)

    # Handle castle-app build artifacts
    _copy_app_static(config)

    # Save registry
    save_registry(registry)
    print(f"\nRegistry written: {REGISTRY_PATH}")

    # Generate systemd units from registry
    _generate_systemd_units(config, registry)

    # Generate Caddyfile from registry
    caddyfile_path = GENERATED_DIR / "Caddyfile"
    caddyfile_content = generate_caddyfile_from_registry(registry)
    caddyfile_path.write_text(caddyfile_content)
    print(f"Caddyfile written: {caddyfile_path}")

    # Reload systemd daemon
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)

    print(f"\nDeployed {deployed_count} component(s).")
    print("Run 'castle services start' to start all services.")
    return 0


def _env_prefix(name: str) -> str:
    """Derive env var prefix from component name: central-context → CENTRAL_CONTEXT."""
    return name.replace("-", "_").upper()


def _resolve_description(
    config: CastleConfig, spec: ServiceSpec | JobSpec
) -> str | None:
    """Get description, falling through to component if referenced."""
    if spec.description:
        return spec.description
    if spec.component and spec.component in config.components:
        return config.components[spec.component].description
    return None


def _build_deployed_service(
    config: CastleConfig, name: str, svc: ServiceSpec
) -> DeployedComponent:
    """Build a DeployedComponent from a ServiceSpec."""
    run = svc.run
    prefix = _env_prefix(name)
    env: dict[str, str] = {}

    # Data dir convention (for managed services)
    managed = True  # Services are always managed by default
    if svc.manage and svc.manage.systemd and not svc.manage.systemd.enable:
        managed = False
    if managed:
        env[f"{prefix}_DATA_DIR"] = str(DATA_ROOT / name)

    # Port convention (if exposed)
    port = None
    health_path = None
    if svc.expose and svc.expose.http:
        port = svc.expose.http.internal.port
        env[f"{prefix}_PORT"] = str(port)
        health_path = svc.expose.http.health_path

    # Merge defaults.env (overrides conventions)
    if svc.defaults and svc.defaults.env:
        env.update(svc.defaults.env)

    # Resolve secrets
    env = resolve_env_vars(env)

    # Build run_cmd
    run_cmd = _build_run_cmd(run, env)

    # Proxy path
    proxy_path = None
    if svc.proxy and svc.proxy.caddy and svc.proxy.caddy.enable:
        proxy_path = svc.proxy.caddy.path_prefix or f"/{name}"

    # Resolve stack from referenced component
    stack = None
    if svc.component and svc.component in config.components:
        stack = config.components[svc.component].stack

    return DeployedComponent(
        runner=run.runner,
        run_cmd=run_cmd,
        env=env,
        description=_resolve_description(config, svc),
        behavior="daemon",
        stack=stack,
        port=port,
        health_path=health_path,
        proxy_path=proxy_path,
        managed=managed,
    )


def _build_deployed_job(
    config: CastleConfig, name: str, job: JobSpec
) -> DeployedComponent:
    """Build a DeployedComponent from a JobSpec."""
    run = job.run
    prefix = _env_prefix(name)
    env: dict[str, str] = {}

    # Data dir convention
    env[f"{prefix}_DATA_DIR"] = str(DATA_ROOT / name)

    # Merge defaults.env (overrides conventions)
    if job.defaults and job.defaults.env:
        env.update(job.defaults.env)

    # Resolve secrets
    env = resolve_env_vars(env)

    # Build run_cmd
    run_cmd = _build_run_cmd(run, env)

    # Resolve stack from referenced component
    stack = None
    if job.component and job.component in config.components:
        stack = config.components[job.component].stack

    return DeployedComponent(
        runner=run.runner,
        run_cmd=run_cmd,
        env=env,
        description=_resolve_description(config, job),
        behavior="tool",
        stack=stack,
        schedule=job.schedule,
        managed=True,
    )


def _build_run_cmd(run: object, env: dict[str, str]) -> list[str]:
    """Build a run command list from a RunSpec."""
    match run.runner:
        case "python":
            resolved = shutil.which(run.tool)
            if not resolved:
                print(
                    f"  Warning: '{run.tool}' not on PATH. "
                    f"Install with: uv tool install --editable <source>"
                )
            cmd = [resolved or run.tool]
            if run.args:
                cmd.extend(run.args)
            return cmd
        case "command":
            cmd = list(run.argv)
            resolved = shutil.which(cmd[0])
            if resolved:
                cmd[0] = resolved
            return cmd
        case "container":
            runtime = shutil.which("docker") or shutil.which("podman") or "docker"
            image_name = run.image.split("/")[-1].split(":")[0]
            cmd = [runtime, "run", "--rm", f"--name=castle-{image_name}"]
            for container_port, host_port in run.ports.items():
                cmd.extend(["-p", f"{host_port}:{container_port}"])
            for vol in run.volumes:
                cmd.extend(["-v", vol])
            for key, val in run.env.items():
                cmd.extend(["-e", f"{key}={val}"])
            for key, val in env.items():
                cmd.extend(["-e", f"{key}={val}"])
            if run.workdir:
                cmd.extend(["-w", run.workdir])
            cmd.append(run.image)
            if run.command:
                cmd.extend(run.command)
            if run.args:
                cmd.extend(run.args)
            return cmd
        case "node":
            cmd = [run.package_manager, "run", run.script]
            if run.args:
                cmd.extend(run.args)
            return cmd
        case _:
            raise ValueError(f"Unsupported runner: {run.runner}")


def _print_deployed(name: str, deployed: DeployedComponent) -> None:
    """Print deployment summary for a component."""
    parts = [f"  {name}"]
    if deployed.port:
        parts.append(f"port={deployed.port}")
    if deployed.schedule:
        parts.append(f"schedule={deployed.schedule}")
    if deployed.proxy_path:
        parts.append(f"proxy={deployed.proxy_path}")
    print(" ".join(parts))


def _copy_app_static(config: CastleConfig) -> None:
    """Copy castle-app build output to ~/.castle/static/castle-app/."""
    if "castle-app" not in config.components:
        return

    comp = config.components["castle-app"]
    if not (comp.build and comp.build.outputs):
        return

    source_dir = comp.source_dir or "app"
    for output in comp.build.outputs:
        src = config.root / source_dir / output
        if src.exists():
            dest = STATIC_DIR / "castle-app"
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(src, dest)
            print(f"  Static: {src} → {dest}")


def _generate_systemd_units(config: CastleConfig, registry: NodeRegistry) -> None:
    """Generate systemd units from the registry."""
    SYSTEMD_USER_DIR.mkdir(parents=True, exist_ok=True)

    for name, deployed in registry.deployed.items():
        if not deployed.managed:
            continue

        # Get systemd spec from config (services or jobs)
        systemd_spec = None
        if name in config.services:
            svc = config.services[name]
            if svc.manage and svc.manage.systemd:
                systemd_spec = svc.manage.systemd
        elif name in config.jobs:
            job = config.jobs[name]
            if job.manage and job.manage.systemd:
                systemd_spec = job.manage.systemd

        # Generate and write service unit
        svc_name = unit_name(name)
        svc_content = generate_unit_from_deployed(name, deployed, systemd_spec)
        (SYSTEMD_USER_DIR / svc_name).write_text(svc_content)

        # Generate timer for jobs
        if deployed.schedule:
            timer_content = generate_timer(
                name,
                schedule=deployed.schedule,
                description=deployed.description,
            )
            tmr_name = timer_name(name)
            (SYSTEMD_USER_DIR / tmr_name).write_text(timer_content)

    print(f"Systemd units written: {SYSTEMD_USER_DIR}")
