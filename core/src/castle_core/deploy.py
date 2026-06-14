"""Deploy logic — bridge castle.yaml spec to runtime (~/.castle/).

This module contains the core deploy logic shared by the CLI and API.
It reads castle.yaml, resolves services/jobs into Deployments,
writes the registry, generates systemd units and the Caddyfile, and
copies frontend build outputs.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from castle_core.config import (
    DATA_DIR,
    SPECS_DIR,
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
    Deployment,
    NodeConfig,
    NodeRegistry,
    load_registry,
    save_registry,
)

SYSTEMD_USER_DIR = Path.home() / ".config" / "systemd" / "user"


@dataclass
class DeployResult:
    """Result of a deploy operation."""

    deployed_count: int = 0
    messages: list[str] = field(default_factory=list)
    registry: NodeRegistry | None = None


def deploy(target_name: str | None = None, root: Path | None = None) -> DeployResult:
    """Deploy from castle.yaml to ~/.castle/.

    Args:
        target_name: Deploy a single service/job by name, or None for all.
        root: Config root path. If None, uses find_castle_root().

    Returns:
        DeployResult with deployed count, messages, and the registry.
    """
    config = load_config(root)
    result = DeployResult()

    ensure_dirs()

    # Build node config
    node = NodeConfig(castle_root=str(config.root), gateway_port=config.gateway.port)

    # Load existing registry to preserve entries not being redeployed,
    # or start fresh if deploying all
    if target_name and REGISTRY_PATH.exists():
        try:
            existing = load_registry()
            registry = NodeRegistry(node=node, deployed=dict(existing.deployed))
        except (FileNotFoundError, ValueError):
            registry = NodeRegistry(node=node)
    else:
        registry = NodeRegistry(node=node)

    # Deploy services
    for name, svc in config.services.items():
        if target_name and name != target_name:
            continue
        deployed = _build_deployed_service(config, name, svc, result.messages)
        registry.deployed[name] = deployed
        result.deployed_count += 1
        result.messages.append(_format_deployed(name, deployed))

    # Deploy jobs
    for name, job in config.jobs.items():
        if target_name and name != target_name:
            continue
        deployed = _build_deployed_job(config, name, job, result.messages)
        registry.deployed[name] = deployed
        result.deployed_count += 1
        result.messages.append(_format_deployed(name, deployed))

    # Static frontends are served in place from their repo build output
    # (the Caddyfile roots directly at <source>/<dist>) — no copy step.

    # Save registry
    save_registry(registry)
    result.messages.append(f"Registry written: {REGISTRY_PATH}")

    # Generate systemd units from registry
    _generate_systemd_units(config, registry)
    result.messages.append(f"Systemd units written: {SYSTEMD_USER_DIR}")

    # Converge: prune orphan units (full deploy only — partial deploys preserve siblings)
    if target_name is None:
        _prune_orphans(registry, result.messages)

    # Generate Caddyfile from registry
    caddyfile_path = SPECS_DIR / "Caddyfile"
    caddyfile_content = generate_caddyfile_from_registry(registry)
    caddyfile_path.write_text(caddyfile_content)
    result.messages.append(f"Caddyfile written: {caddyfile_path}")

    # Reload systemd daemon
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)

    # Reload the gateway so the freshly written Caddyfile takes effect. Without
    # this, new/changed proxy routes sit on disk but the running Caddy keeps the
    # old config (a deployed service's route is silently dead until reload).
    _reload_gateway(result.messages)

    result.registry = registry
    return result


# Gateway service name in the registry → its systemd unit (castle-castle-gateway).
_GATEWAY_NAME = "castle-gateway"


def _reload_gateway(messages: list[str]) -> None:
    """Reload Caddy if the gateway is running, so new routes take effect."""
    gw_unit = unit_name(_GATEWAY_NAME)
    active = subprocess.run(
        ["systemctl", "--user", "is-active", gw_unit],
        capture_output=True,
        text=True,
    )
    if active.stdout.strip() != "active":
        messages.append("Gateway not running — skipped reload (start it with 'castle gateway start').")
        return
    result = subprocess.run(["systemctl", "--user", "reload", gw_unit], capture_output=True, text=True)
    if result.returncode == 0:
        messages.append("Gateway reloaded.")
    else:
        messages.append(f"Warning: gateway reload failed: {result.stderr.strip()}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _env_prefix(name: str) -> str:
    """Derive env var prefix from name: central-context → CENTRAL_CONTEXT."""
    return name.replace("-", "_").upper()


def _resolve_description(config: CastleConfig, spec: ServiceSpec | JobSpec) -> str | None:
    """Get description, falling through to program if referenced."""
    if spec.description:
        return spec.description
    if spec.program and spec.program in config.programs:
        return config.programs[spec.program].description
    return None


def _build_deployed_service(
    config: CastleConfig, name: str, svc: ServiceSpec, messages: list[str]
) -> Deployment:
    """Build a Deployment from a ServiceSpec."""
    run = svc.run
    # Env prefix and data dir are keyed by the program (component) the service
    # runs, not the service name — that's the prefix the program's settings read
    # (e.g. job `protonmail-sync` runs program `protonmail` → PROTONMAIL_DATA_DIR).
    # Falls back to the service name when no component is referenced.
    config_key = svc.program or name
    prefix = _env_prefix(config_key)
    env: dict[str, str] = {}

    # Data dir convention (for managed services). Skipped for container runners:
    # they use volume mounts, not a data-dir env var, and the injected name can
    # collide with an image's own env namespace (e.g. neo4j claims NEO4J_*).
    managed = run.runner != "remote"
    if svc.manage and svc.manage.systemd and not svc.manage.systemd.enable:
        managed = False
    if managed and run.runner != "container":
        env[f"{prefix}_DATA_DIR"] = str(DATA_DIR / config_key)

    # Port convention (if exposed)
    port = None
    health_path = None
    if svc.expose and svc.expose.http:
        port = svc.expose.http.internal.port
        env[f"{prefix}_PORT"] = str(port)
        # If the program reads a non-convention port var, set that too so castle
        # actually controls the bind (e.g. adopted lakehoused → LAKEHOUSED_DAEMON_PORT).
        if svc.expose.http.internal.port_env:
            env[svc.expose.http.internal.port_env] = str(port)
        health_path = svc.expose.http.health_path

    # Merge defaults.env (overrides conventions)
    if svc.defaults and svc.defaults.env:
        env.update(svc.defaults.env)

    # Resolve secrets
    env = resolve_env_vars(env)

    # Ensure python tool is installed before resolving binary
    _ensure_python_tool(config, svc.program, messages)

    # Build run_cmd
    run_cmd = _build_run_cmd(name, run, env, messages)

    # Proxy: a path prefix (handle_path on the gateway) and/or a hostname (a
    # dedicated host site block, so a root-based app serves unchanged).
    proxy_path = None
    proxy_host = None
    if svc.proxy and svc.proxy.caddy and svc.proxy.caddy.enable:
        caddy = svc.proxy.caddy
        proxy_host = caddy.host
        if caddy.path_prefix:
            proxy_path = caddy.path_prefix
        elif not caddy.host:
            # No explicit path and no host → default to /<name>.
            proxy_path = f"/{name}"

    # Resolve stack from referenced program
    stack = None
    if svc.program and svc.program in config.programs:
        stack = config.programs[svc.program].stack

    # Remote services proxy to an external base_url
    base_url = getattr(run, "base_url", None)

    return Deployment(
        runner=run.runner,
        run_cmd=run_cmd,
        env=env,
        description=_resolve_description(config, svc),
        behavior="daemon",
        stack=stack,
        port=port,
        health_path=health_path,
        proxy_path=proxy_path,
        proxy_host=proxy_host,
        base_url=base_url,
        managed=managed,
    )


def _build_deployed_job(
    config: CastleConfig, name: str, job: JobSpec, messages: list[str]
) -> Deployment:
    """Build a Deployment from a JobSpec."""
    run = job.run
    # Keyed by the program (component) the job runs, not the job name — see
    # _build_deployed_service for rationale. Falls back to the job name.
    config_key = job.program or name
    prefix = _env_prefix(config_key)
    env: dict[str, str] = {}

    env[f"{prefix}_DATA_DIR"] = str(DATA_DIR / config_key)

    if job.defaults and job.defaults.env:
        env.update(job.defaults.env)

    env = resolve_env_vars(env)
    _ensure_python_tool(config, job.program, messages)
    run_cmd = _build_run_cmd(name, run, env, messages)

    stack = None
    if job.program and job.program in config.programs:
        stack = config.programs[job.program].stack

    return Deployment(
        runner=run.runner,
        run_cmd=run_cmd,
        env=env,
        description=_resolve_description(config, job),
        behavior="tool",
        stack=stack,
        schedule=job.schedule,
        managed=True,
    )


def _python_tool_needs_install(program: str) -> bool:
    """Check if a Python tool's editable install is broken."""
    if not shutil.which(program):
        return True
    tool_dir = Path.home() / ".local" / "share" / "uv" / "tools" / program
    if not tool_dir.exists():
        return True
    for pth_file in tool_dir.glob("lib/python*/site-packages/*.pth"):
        if pth_file.name == "_virtualenv.pth":
            continue
        try:
            target = pth_file.read_text().strip()
        except OSError:
            continue
        if not target or target.startswith("import "):
            continue
        if not Path(target).exists():
            return True
    return False


def _ensure_python_tool(
    config: CastleConfig, program: str | None, messages: list[str]
) -> None:
    """Ensure a Python program's editable install is current."""
    if not program or program not in config.programs:
        return
    comp = config.programs[program]
    if not comp.source or not comp.stack or not comp.stack.startswith("python"):
        return
    source_dir = Path(comp.source)
    if not source_dir.is_dir():
        messages.append(f"Warning: source not found: {source_dir}")
        return
    if not _python_tool_needs_install(program):
        return
    pkg_spec = str(source_dir)
    if comp.install_extras:
        pkg_spec += "[" + ",".join(comp.install_extras) + "]"
    messages.append(f"Installing {program} from {source_dir}...")
    result = subprocess.run(
        ["uv", "tool", "install", "--editable", pkg_spec, "--force"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        messages.append(f"Error: {program} install failed:\n{result.stdout}{result.stderr}")
    else:
        messages.append(f"Installed {program}")


def _build_run_cmd(name: str, run: object, env: dict[str, str], messages: list[str]) -> list[str]:
    """Build a run command list from a RunSpec."""
    match run.runner:  # type: ignore[union-attr]
        case "python":
            resolved = shutil.which(run.program)  # type: ignore[union-attr]
            if not resolved:
                messages.append(
                    f"Warning: '{run.program}' not on PATH. "  # type: ignore[union-attr]
                    f"Install with: uv tool install --editable <source>"
                )
            cmd = [resolved or run.program]  # type: ignore[union-attr]
            if run.args:  # type: ignore[union-attr]
                cmd.extend(run.args)  # type: ignore[union-attr]
            return cmd
        case "command":
            cmd = list(run.argv)  # type: ignore[union-attr]
            resolved = shutil.which(cmd[0])
            if resolved:
                cmd[0] = resolved
            return cmd
        case "container":
            runtime = shutil.which("docker") or shutil.which("podman") or "docker"
            # Container name derives from the SERVICE name (matches the systemd unit),
            # not the image name — so `castle-<service>` is stable and collision-free.
            cmd = [runtime, "run", "--rm", f"--name=castle-{name}"]
            for container_port, host_port in run.ports.items():  # type: ignore[union-attr]
                cmd.extend(["-p", f"{host_port}:{container_port}"])
            for vol in run.volumes:  # type: ignore[union-attr]
                cmd.extend(["-v", vol])
            for key, val in run.env.items():  # type: ignore[union-attr]
                cmd.extend(["-e", f"{key}={val}"])
            for key, val in env.items():
                cmd.extend(["-e", f"{key}={val}"])
            if run.workdir:  # type: ignore[union-attr]
                cmd.extend(["-w", run.workdir])  # type: ignore[union-attr]
            cmd.append(run.image)  # type: ignore[union-attr]
            if run.command:  # type: ignore[union-attr]
                cmd.extend(run.command)  # type: ignore[union-attr]
            if run.args:  # type: ignore[union-attr]
                cmd.extend(run.args)  # type: ignore[union-attr]
            return cmd
        case "node":
            cmd = [run.package_manager, "run", run.script]  # type: ignore[union-attr]
            if run.args:  # type: ignore[union-attr]
                cmd.extend(run.args)  # type: ignore[union-attr]
            return cmd
        case "remote":
            return []
        case _:
            raise ValueError(f"Unsupported runner: {run.runner}")  # type: ignore[union-attr]


def _format_deployed(name: str, deployed: Deployment) -> str:
    """Format deployment summary for a component."""
    parts = [name]
    if deployed.port:
        parts.append(f"port={deployed.port}")
    if deployed.schedule:
        parts.append(f"schedule={deployed.schedule}")
    if deployed.proxy_path:
        parts.append(f"proxy={deployed.proxy_path}")
    return " ".join(parts)


def _desired_unit_files(registry: NodeRegistry) -> set[str]:
    """Exact set of unit filenames that should exist on disk for this registry."""
    files: set[str] = set()
    for name, deployed in registry.deployed.items():
        if not deployed.managed:
            continue
        files.add(unit_name(name))
        if deployed.schedule:
            files.add(timer_name(name))
    return files


def _teardown_unit(unit_file: str, messages: list[str]) -> None:
    """Stop, disable, and unlink a systemd unit file. Caller batches daemon-reload."""
    path = SYSTEMD_USER_DIR / unit_file
    if not path.exists():
        return
    subprocess.run(["systemctl", "--user", "stop", unit_file], check=False)
    subprocess.run(["systemctl", "--user", "disable", unit_file], check=False)
    path.unlink()
    messages.append(f"Pruned orphan unit: {unit_file}")


def _prune_orphans(registry: NodeRegistry, messages: list[str]) -> None:
    """Remove castle-* units no longer backed by a managed registry entry.

    The `castle-` prefix is the ownership namespace: any castle-*.service/.timer on
    disk that isn't in the desired set is an orphan (a removed/unmanaged/unscheduled
    component) and is torn down. Only call on a FULL deploy — the desired set must
    reflect the whole registry, not a single --target.
    """
    desired = _desired_unit_files(registry)
    if not SYSTEMD_USER_DIR.is_dir():
        return
    for pattern in ("castle-*.service", "castle-*.timer"):
        for path in sorted(SYSTEMD_USER_DIR.glob(pattern)):
            if path.name not in desired:
                _teardown_unit(path.name, messages)


def _generate_systemd_units(config: CastleConfig, registry: NodeRegistry) -> None:
    """Generate systemd units from the registry."""
    SYSTEMD_USER_DIR.mkdir(parents=True, exist_ok=True)

    for name, deployed in registry.deployed.items():
        if not deployed.managed:
            continue

        systemd_spec = None
        if name in config.services:
            svc = config.services[name]
            if svc.manage and svc.manage.systemd:
                systemd_spec = svc.manage.systemd
        elif name in config.jobs:
            job = config.jobs[name]
            if job.manage and job.manage.systemd:
                systemd_spec = job.manage.systemd

        svc_name = unit_name(name)
        svc_content = generate_unit_from_deployed(name, deployed, systemd_spec)
        (SYSTEMD_USER_DIR / svc_name).write_text(svc_content)

        if deployed.schedule:
            timer_content = generate_timer(
                name,
                schedule=deployed.schedule,
                description=deployed.description,
            )
            tmr_name = timer_name(name)
            (SYSTEMD_USER_DIR / tmr_name).write_text(timer_content)