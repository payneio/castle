"""Deploy logic — bridge castle.yaml spec to runtime (~/.castle/).

This module contains the core deploy logic shared by the CLI and API.
It reads castle.yaml, resolves services/jobs into Deployments,
writes the registry, generates systemd units and the Caddyfile, and
copies frontend build outputs.
"""

from __future__ import annotations

import os
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
    resolve_env_split,
)
from castle_core.generators.caddyfile import (
    generate_caddyfile_from_registry,
    service_proxy_targets,
)
from castle_core.generators.systemd import (
    SECRET_ENV_DIR,
    generate_timer,
    generate_unit_from_deployed,
    secret_env_path,
    timer_name,
    unit_env_file,
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
        messages.append(
            "Gateway not running — skipped reload (start it with 'castle gateway start')."
        )
        return
    result = subprocess.run(
        ["systemctl", "--user", "reload", gw_unit], capture_output=True, text=True
    )
    if result.returncode == 0:
        messages.append("Gateway reloaded.")
    else:
        messages.append(f"Warning: gateway reload failed: {result.stderr.strip()}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _env_context(name: str, config_key: str, port: int | None) -> dict[str, str]:
    """Placeholder values for defaults.env: ${name}/${data_dir}/${port}."""
    ctx = {"name": name, "data_dir": str(DATA_DIR / config_key)}
    if port is not None:
        ctx["port"] = str(port)
    return ctx


def _write_secret_env_file(name: str, secret_env: dict[str, str]) -> Path | None:
    """Write a deployment's resolved secrets to a mode-0600 env file.

    Keeps secrets out of the generated unit file and the process argv: systemd
    loads it via ``EnvironmentFile=`` and docker via ``--env-file``. Returns the
    path, or ``None`` (after removing any stale file) when there are no secrets,
    so a service that drops its last secret doesn't leave a dangling file.
    """
    path = secret_env_path(name)
    if not secret_env:
        path.unlink(missing_ok=True)
        return None
    SECRET_ENV_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(SECRET_ENV_DIR, 0o700)
    # O_TRUNC keeps a pre-existing file's mode, so chmod explicitly afterwards.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        for key, value in secret_env.items():
            f.write(f"{key}={value}\n")
    os.chmod(path, 0o600)
    return path


def _resolve_description(
    config: CastleConfig, spec: ServiceSpec | JobSpec
) -> str | None:
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
    # The data-dir placeholder is keyed by the program the service runs, not the
    # service name (e.g. job `protonmail-sync` runs program `protonmail` →
    # /data/castle/protonmail). Falls back to the service name.
    config_key = svc.program or name

    managed = run.runner != "remote"
    if svc.manage and svc.manage.systemd and not svc.manage.systemd.enable:
        managed = False

    # Routing fields (port/proxy_path/proxy_host/base_url) come from the shared
    # deriver, so the registry written here and the Caddyfile computed from
    # castle.yaml stay in lockstep.
    proxy_path, proxy_host, port, base_url = service_proxy_targets(name, svc)
    health_path = None
    if svc.expose and svc.expose.http:
        health_path = svc.expose.http.health_path

    # Env is exactly what's declared in defaults.env — no hidden convention
    # injection. ${port}/${data_dir}/${name} let the program's own env var names
    # map to castle's computed values without hardcoding them. Secret-bearing vars
    # are split out so they never land in the unit file or process argv — they're
    # written to a mode-0600 env file referenced via EnvironmentFile=/--env-file.
    raw_env = dict(svc.defaults.env) if (svc.defaults and svc.defaults.env) else {}
    env, secret_env = resolve_env_split(raw_env, _env_context(name, config_key, port))
    secret_env_file = _write_secret_env_file(name, secret_env)

    # `command`-runner services resolve a tool on PATH → ensure it's installed.
    # `python`-runner services run in place via `uv run` (below) — no tool venv.
    if run.runner == "command":
        _ensure_python_tool(config, svc.program, messages)

    # Build run_cmd (container runners get --env-file for the secrets).
    run_cmd = _build_run_cmd(
        name,
        run,
        env,
        messages,
        _program_source_dir(config, svc.program),
        secret_env_file=secret_env_file,
    )

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
        secret_env_keys=sorted(secret_env),
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
    # ${data_dir} is keyed by the program the job runs, not the job name — see
    # _build_deployed_service. Falls back to the job name.
    config_key = job.program or name
    raw_env = dict(job.defaults.env) if (job.defaults and job.defaults.env) else {}
    env, secret_env = resolve_env_split(raw_env, _env_context(name, config_key, None))
    secret_env_file = _write_secret_env_file(name, secret_env)
    if run.runner == "command":
        _ensure_python_tool(config, job.program, messages)
    run_cmd = _build_run_cmd(
        name,
        run,
        env,
        messages,
        _program_source_dir(config, job.program),
        secret_env_file=secret_env_file,
    )

    stack = None
    if job.program and job.program in config.programs:
        stack = config.programs[job.program].stack

    return Deployment(
        runner=run.runner,
        run_cmd=run_cmd,
        env=env,
        secret_env_keys=sorted(secret_env),
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


def _program_source_dir(config: CastleConfig, program: str | None) -> Path | None:
    """The absolute source dir of a referenced program, if any.

    `load_config` has already resolved `source` to an absolute path (repo: and
    relative forms included), so this is a plain lookup."""
    if program and program in config.programs:
        src = config.programs[program].source
        if src:
            return Path(src)
    return None


def _ensure_python_tool(
    config: CastleConfig, program: str | None, messages: list[str]
) -> None:
    """Ensure a Python program's editable install is current.

    Only the `command` runner needs this — it resolves a tool on PATH. The
    `python` runner runs in place via `uv run` and never touches a tool venv."""
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
        messages.append(
            f"Error: {program} install failed:\n{result.stdout}{result.stderr}"
        )
    else:
        messages.append(f"Installed {program}")


def _build_run_cmd(
    name: str,
    run: object,
    env: dict[str, str],
    messages: list[str],
    source_dir: Path | None = None,
    secret_env_file: Path | None = None,
) -> list[str]:
    """Build a run command list from a RunSpec.

    ``env`` holds plain (non-secret) vars only; ``secret_env_file`` is the
    mode-0600 file holding the deployment's secrets. For container runners the
    secrets are passed via ``--env-file`` (keeping them out of the argv);
    systemd-launched runners get them via ``EnvironmentFile=`` on the unit, so
    ``secret_env_file`` is unused here for those.
    """
    match run.runner:  # type: ignore[union-attr]
        case "python":
            # Run the program in place from its own project venv via `uv run`,
            # which syncs the env to the lockfile before launching. One venv per
            # program (no separate tool venv); restart picks up both code and
            # dependency changes. Falls back to a PATH lookup only when there's no
            # resolvable source (a service that declares run.program without a
            # catalog program).
            if source_dir and source_dir.is_dir():
                uv = shutil.which("uv") or "uv"
                cmd = [uv, "run", "--project", str(source_dir), "--no-dev", run.program]  # type: ignore[union-attr]
            else:
                resolved = shutil.which(run.program)  # type: ignore[union-attr]
                if not resolved:
                    messages.append(
                        f"Warning: '{run.program}' has no source dir and is not on "  # type: ignore[union-attr]
                        f"PATH. Declare a program source, or install it."
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
            # env is plain-only; secrets go via --env-file so they never hit argv.
            for key, val in env.items():
                cmd.extend(["-e", f"{key}={val}"])
            if secret_env_file is not None:
                cmd.extend(["--env-file", str(secret_env_file)])
            if run.workdir:  # type: ignore[union-attr]
                cmd.extend(["-w", run.workdir])  # type: ignore[union-attr]
            cmd.append(run.image)  # type: ignore[union-attr]
            if run.command:  # type: ignore[union-attr]
                cmd.extend(run.command)  # type: ignore[union-attr]
            if run.args:  # type: ignore[union-attr]
                cmd.extend(run.args)  # type: ignore[union-attr]
            return cmd
        case "node":
            # Like the python runner bakes `--project <source>` into `uv run`, the
            # node runner bakes `--dir <source>` so the package manager runs the
            # script in the program's source dir — the systemd unit carries no
            # WorkingDirectory, so a bare `pnpm run` would otherwise execute in the
            # service's (wrong) cwd. Resolve the package manager to an absolute path.
            pm = shutil.which(run.package_manager) or run.package_manager  # type: ignore[union-attr]
            cmd = [pm]
            if source_dir and source_dir.is_dir():
                cmd.extend(["--dir", str(source_dir)])
            cmd.extend(["run", run.script])  # type: ignore[union-attr]
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
    # Remove the matching secret env file (only services have one; not timers).
    if unit_file.endswith(".service"):
        (SECRET_ENV_DIR / f"{unit_file}.env").unlink(missing_ok=True)


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
        svc_content = generate_unit_from_deployed(
            name, deployed, systemd_spec, env_file=unit_env_file(deployed, name)
        )
        (SYSTEMD_USER_DIR / svc_name).write_text(svc_content)

        if deployed.schedule:
            timer_content = generate_timer(
                name,
                schedule=deployed.schedule,
                description=deployed.description,
            )
            tmr_name = timer_name(name)
            (SYSTEMD_USER_DIR / tmr_name).write_text(timer_content)
