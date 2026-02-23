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
    get_schedule_trigger,
    timer_name,
    unit_name,
)
from castle_core.manifest import ComponentManifest
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
    component_name = getattr(args, "component", None)

    if component_name:
        if component_name not in config.components:
            print(f"Error: component '{component_name}' not found in castle.yaml")
            return 1
        names = [component_name]
    else:
        names = list(config.components.keys())

    ensure_dirs()

    # Build node config
    node = NodeConfig(castle_root=str(config.root), gateway_port=config.gateway.port)

    # Load existing registry to preserve components not being redeployed,
    # or start fresh if deploying all
    if component_name and REGISTRY_PATH.exists():
        try:
            existing = load_registry()
            registry = NodeRegistry(node=node, deployed=dict(existing.deployed))
        except (FileNotFoundError, ValueError):
            registry = NodeRegistry(node=node)
    else:
        registry = NodeRegistry(node=node)

    deployed_count = 0
    for name in names:
        manifest = config.components[name]

        # Only deploy components with a run spec
        if not manifest.run:
            continue

        deployed = _build_deployed(config, name, manifest)
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


def _build_deployed(
    config: CastleConfig, name: str, manifest: ComponentManifest
) -> DeployedComponent:
    """Build a DeployedComponent from a manifest spec."""
    run = manifest.run
    assert run is not None

    # 1. Convention-based env vars
    prefix = _env_prefix(name)
    env: dict[str, str] = {}

    # Data dir convention (for all managed components)
    if manifest.manage and manifest.manage.systemd:
        env[f"{prefix}_DATA_DIR"] = str(DATA_ROOT / name)

    # Port convention (if exposed)
    if manifest.expose and manifest.expose.http:
        env[f"{prefix}_PORT"] = str(manifest.expose.http.internal.port)

    # 2. Merge defaults.env (overrides conventions)
    if manifest.defaults and manifest.defaults.env:
        env.update(manifest.defaults.env)

    # 3. Resolve secrets
    env = resolve_env_vars(env, manifest)

    # 4. Build run_cmd
    run_cmd = _build_run_cmd(run, env)

    # 5. Extract metadata
    port = None
    health_path = None
    if manifest.expose and manifest.expose.http:
        port = manifest.expose.http.internal.port
        health_path = manifest.expose.http.health_path

    proxy_path = None
    if manifest.proxy and manifest.proxy.caddy and manifest.proxy.caddy.enable:
        proxy_path = manifest.proxy.caddy.path_prefix or f"/{name}"

    schedule = None
    sched_trigger = get_schedule_trigger(manifest)
    if sched_trigger:
        schedule = sched_trigger.cron

    managed = bool(manifest.manage and manifest.manage.systemd and manifest.manage.systemd.enable)

    roles = [r.value for r in manifest.roles]

    return DeployedComponent(
        runner=run.runner,
        run_cmd=run_cmd,
        env=env,
        description=manifest.description,
        roles=roles,
        port=port,
        health_path=health_path,
        proxy_path=proxy_path,
        schedule=schedule,
        managed=managed,
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
            runtime = shutil.which("podman") or shutil.which("docker") or "podman"
            image_name = run.image.split("/")[-1].split(":")[0]
            cmd = [runtime, "run", "--rm", f"--name=castle-{image_name}"]
            for container_port, host_port in run.ports.items():
                cmd.extend(["-p", f"{host_port}:{container_port}"])
            for vol in run.volumes:
                cmd.extend(["-v", vol])
            # Container env comes from both run.env (container-specific) and deployed env
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

    manifest = config.components["castle-app"]
    if not (manifest.build and manifest.build.outputs):
        return

    # Find the source dist directory
    source_dir = manifest.source_dir or "app"
    for output in manifest.build.outputs:
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

        # Get systemd spec from manifest (for restart policy, exec_reload, etc.)
        systemd_spec = None
        if name in config.components:
            manifest = config.components[name]
            if manifest.manage and manifest.manage.systemd:
                systemd_spec = manifest.manage.systemd

        # Generate and write service unit
        svc_name = unit_name(name)
        svc_content = generate_unit_from_deployed(name, deployed, systemd_spec)
        (SYSTEMD_USER_DIR / svc_name).write_text(svc_content)

        # Generate timer if scheduled
        if name in config.components:
            timer_content = generate_timer(name, config.components[name])
            if timer_content:
                tmr_name = timer_name(name)
                (SYSTEMD_USER_DIR / tmr_name).write_text(timer_content)

    print(f"Systemd units written: {SYSTEMD_USER_DIR}")
