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
    SECRETS_DIR,
    SPECS_DIR,
    CastleConfig,
    ensure_dirs,
    load_config,
    resolve_env_split,
)
from castle_core.generators.caddyfile import (
    _DNS_TOKEN_ENV,
    generate_caddyfile_from_registry,
)
from castle_core.generators.tunnel import (
    generate_tunnel_config,
    public_hostnames,
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
from castle_core.manifest import (
    CaddyDeployment,
    DeploymentBase,
    DeploymentSpec,
    PathDeployment,
    RemoteDeployment,
    kind_for,
)
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
    node = NodeConfig(
        castle_root=str(config.root),
        gateway_port=config.gateway.port,
        gateway_tls=config.gateway.tls,
        gateway_domain=config.gateway.domain,
        acme_email=config.gateway.acme_email,
        acme_dns_provider=config.gateway.acme_dns_provider,
        public_domain=config.gateway.public_domain,
        tunnel_id=config.gateway.tunnel_id,
    )

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

    # Deploy every deployment, dispatched by its manager (systemd/caddy/path/none).
    for name, dep in config.deployments.items():
        if target_name and name != target_name:
            continue
        deployed = _build_deployed(config, name, dep, result.messages)
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

    # Generate the cloudflared tunnel ingress from the registry's public services.
    _write_tunnel_config(registry, result.messages)

    # acme mode needs a domain + a DNS-provider token; warn (don't fail) if the
    # prerequisites the operator must set up by hand are missing.
    if (config.gateway.tls or "").lower() == "acme":
        _acme_preflight(config, result.messages)

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


def _acme_preflight(config: CastleConfig, messages: list[str]) -> None:
    """Warn (never fail, never write) if acme-mode prerequisites are missing.

    acme mode needs a `gateway.domain`, the DNS-provider token mapped into the
    castle-gateway service env, and the matching secret on disk — all operator
    steps (castle never rewrites the user-authored gateway service YAML)."""
    gw = config.gateway
    if not gw.domain:
        messages.append(
            "Warning: gateway.tls=acme but gateway.domain is unset — host routes "
            "won't get a wildcard cert (serving plain HTTP on the gateway port)."
        )
        return
    token_env = _DNS_TOKEN_ENV.get(gw.acme_dns_provider or "cloudflare", "CLOUDFLARE_API_TOKEN")
    svc = config.services.get(_GATEWAY_NAME)
    env = dict(svc.defaults.env) if (svc and svc.defaults and svc.defaults.env) else {}
    if token_env not in env:
        messages.append(
            f"Warning: acme mode needs {token_env} in the {_GATEWAY_NAME} service env. "
            f"Add to services/{_GATEWAY_NAME}.yaml → defaults.env: "
            f"{token_env}: ${{secret:{token_env}}}"
        )
    if not (SECRETS_DIR / token_env).exists():
        messages.append(
            f"Warning: secret '{token_env}' not found in {SECRETS_DIR} — place the "
            f"DNS-provider API token there (Cloudflare token scope: Zone:DNS:Edit)."
        )


_TUNNEL_NAME = "tunnel"  # the cloudflared service is castle-tunnel


def _write_tunnel_config(registry: NodeRegistry, messages: list[str]) -> None:
    """Write the cloudflared ingress config from the registry's public services.

    No public services (or no tunnel configured) → remove any stale config and
    leave the tunnel down. Otherwise write it, list the hostnames that still need a
    DNS route, and restart the tunnel service if it's running so it takes effect.
    """
    config_path = SPECS_DIR / "cloudflared.yml"
    content = generate_tunnel_config(registry)
    if content is None:
        if config_path.exists():
            config_path.unlink()
            messages.append("No public services — removed cloudflared config.")
        return

    config_path.write_text(content)
    hosts = public_hostnames(registry)
    messages.append(f"Tunnel config written: {config_path} ({len(hosts)} public)")
    # DNS is not automatic: each public host needs a CNAME → the tunnel. Surface the
    # exact commands rather than silently assuming they're routed.
    tid = registry.node.tunnel_id
    for h in hosts:
        messages.append(f"  public: {h}  (route once: cloudflared tunnel route dns {tid} {h})")

    tunnel_unit = unit_name(_TUNNEL_NAME)
    active = subprocess.run(
        ["systemctl", "--user", "is-active", tunnel_unit], capture_output=True, text=True
    )
    if active.stdout.strip() == "active":
        subprocess.run(["systemctl", "--user", "restart", tunnel_unit], check=False)
        messages.append("Tunnel reloaded.")
    else:
        messages.append(
            "Tunnel not running — enable it with 'castle service enable tunnel'."
        )


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


def _public_url(
    config: CastleConfig, name: str, exposed: bool, port: int | None
) -> str | None:
    """The service's publicly-reachable base URL — the ``${public_url}`` placeholder.

    When the service is exposed through the gateway under acme TLS, this is its
    trusted subdomain ``https://<name>.<gateway.domain>`` — the origin an app must
    allowlist for CORS/WebSocket/secure-context to work behind the gateway. It
    tracks ``gateway.domain`` automatically, so a domain change needs no app edit.
    Off mode / port-only falls back to the node-local ``http://localhost:<port>``;
    ``None`` when there's no port to reach it on (nothing to interpolate).
    """
    gw = config.gateway
    if exposed and str(gw.tls or "").lower() == "acme" and gw.domain:
        return f"https://{name}.{gw.domain}"
    if port is not None:
        return f"http://localhost:{port}"
    return None


def _env_context(
    name: str, config_key: str, port: int | None, public_url: str | None = None
) -> dict[str, str]:
    """Placeholder values for defaults.env: ${name}/${data_dir}/${port}/${public_url}."""
    ctx = {"name": name, "data_dir": str(DATA_DIR / config_key)}
    if port is not None:
        ctx["port"] = str(port)
    if public_url is not None:
        ctx["public_url"] = public_url
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
    config: CastleConfig, spec: DeploymentBase
) -> str | None:
    """Get description, falling through to program if referenced."""
    if spec.description:
        return spec.description
    if spec.program and spec.program in config.programs:
        return config.programs[spec.program].description
    return None


def _build_deployed(
    config: CastleConfig, name: str, dep: DeploymentSpec, messages: list[str]
) -> Deployment:
    """Build a runtime Deployment from a DeploymentSpec, dispatched by its manager."""
    description = _resolve_description(config, dep)
    kind = kind_for(dep)
    stack = None
    if dep.program and dep.program in config.programs:
        stack = config.programs[dep.program].stack
    source_dir = _program_source_dir(config, dep.program)

    # Non-process managers (caddy/path/none) have no unit and no run_cmd — the
    # gateway, PATH, or another node is their runtime.
    if isinstance(dep, CaddyDeployment):
        # Serves <program-source>/<root> via the gateway; inherently exposed.
        static_root = str(source_dir / dep.root) if source_dir is not None else None
        return Deployment(
            manager="caddy",
            run_cmd=[],
            description=description,
            kind=kind,
            stack=stack,
            subdomain=name,
            public=bool(dep.public),
            static_root=static_root,
            managed=False,
        )
    if isinstance(dep, PathDeployment):
        return Deployment(
            manager="path",
            run_cmd=[],
            description=description,
            kind=kind,
            stack=stack,
            managed=False,
        )
    if isinstance(dep, RemoteDeployment):
        return Deployment(
            manager="none",
            run_cmd=[],
            description=description,
            kind=kind,
            stack=stack,
            base_url=dep.base_url,
            managed=False,
        )

    # systemd: a supervised process (a service, or a job when scheduled).
    run = dep.run
    # ${data_dir} is keyed by the program the deployment runs, not the deployment
    # name (e.g. job `protonmail-sync` runs program `protonmail` →
    # /data/castle/protonmail). Falls back to the deployment name.
    config_key = dep.program or name

    managed = True
    if dep.manage and dep.manage.systemd and not dep.manage.systemd.enable:
        managed = False

    # `proxy` is the exposure checkbox; the subdomain is the deployment name.
    expose = bool(dep.proxy)
    port = None
    health_path = None
    if dep.expose and dep.expose.http:
        port = dep.expose.http.internal.port
        health_path = dep.expose.http.health_path

    # Env is exactly what's in defaults.env — no hidden convention injection.
    # ${port}/${data_dir}/${name}/${public_url} map the program's own env var
    # names to castle's computed values. Secret-bearing vars split out to a
    # mode-0600 file (never in the unit or argv).
    raw_env = dict(dep.defaults.env) if (dep.defaults and dep.defaults.env) else {}
    public_url = _public_url(config, name, expose, port)
    env, secret_env = resolve_env_split(
        raw_env, _env_context(name, config_key, port, public_url)
    )
    secret_env_file = _write_secret_env_file(name, secret_env)

    # `command` launchers resolve a tool on PATH → ensure it's installed.
    # `python` launchers run in place via `uv run` (below) — no tool venv.
    if run.launcher == "command":
        _ensure_python_tool(config, dep.program, messages)

    run_cmd = _build_run_cmd(
        name, run, env, messages, source_dir, secret_env_file=secret_env_file
    )
    stop_cmd = _build_stop_cmd(name, run, source_dir)

    return Deployment(
        manager="systemd",
        launcher=run.launcher,
        run_cmd=run_cmd,
        stop_cmd=stop_cmd,
        env=env,
        secret_env_keys=sorted(secret_env),
        description=description,
        kind=kind,
        stack=stack,
        port=port,
        health_path=health_path,
        subdomain=(name if expose else None),
        public=bool(dep.public and expose),
        schedule=getattr(dep, "schedule", None),
        managed=managed,
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
    """Build a run command list from a LaunchSpec (a systemd deployment's `run`).

    ``env`` holds plain (non-secret) vars only; ``secret_env_file`` is the
    mode-0600 file holding the deployment's secrets. For container runners the
    secrets are passed via ``--env-file`` (keeping them out of the argv);
    systemd-launched runners get them via ``EnvironmentFile=`` on the unit, so
    ``secret_env_file`` is unused here for those.
    """
    match run.launcher:  # type: ignore[union-attr]
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
        case "compose":
            # A whole docker-compose stack supervised as one unit. `up` runs
            # attached (no -d) so systemd Type=simple owns the lifecycle; teardown
            # is a generated ExecStop (`down`, see _build_stop_cmd). Secrets/env
            # reach compose via the unit's Environment=/EnvironmentFile= (compose
            # interpolates from the process env), not argv — so nothing here.
            return [*_compose_base(name, run, source_dir), "up"]
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
        case _:
            raise ValueError(f"Unsupported launcher: {run.launcher}")  # type: ignore[union-attr]


def _compose_base(name: str, run: object, source_dir: Path | None) -> list[str]:
    """The shared ``docker compose -p <project> -f <file>`` prefix for a stack.

    The compose file is resolved against the program source (like the node runner
    uses ``--dir``) so the unit — which carries no WorkingDirectory — finds it. The
    project name defaults to the unit name so a stack's containers/networks are
    namespaced and collision-free.
    """
    runtime = shutil.which("docker") or shutil.which("podman") or "docker"
    project = run.project_name or f"castle-{name}"  # type: ignore[union-attr]
    compose_file = Path(run.file)  # type: ignore[union-attr]
    if not compose_file.is_absolute() and source_dir is not None:
        compose_file = source_dir / compose_file
    return [runtime, "compose", "-p", project, "-f", str(compose_file)]


def _build_stop_cmd(name: str, run: object, source_dir: Path | None) -> list[str]:
    """The ExecStop teardown command for a runner, or [] if a plain SIGTERM suffices.

    Compose stacks need an explicit ``down`` so networks/anonymous volumes are
    reclaimed rather than left dangling when the unit stops.
    """
    if run.launcher == "compose":  # type: ignore[union-attr]
        return [*_compose_base(name, run, source_dir), "down"]
    return []


def _format_deployed(name: str, deployed: Deployment) -> str:
    """Format deployment summary for a component."""
    parts = [name]
    if deployed.port:
        parts.append(f"port={deployed.port}")
    if deployed.schedule:
        parts.append(f"schedule={deployed.schedule}")
    if deployed.subdomain:
        parts.append(f"subdomain={deployed.subdomain}")
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
        dep = config.deployments.get(name)
        manage = getattr(dep, "manage", None)
        if manage and manage.systemd:
            systemd_spec = manage.systemd

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
