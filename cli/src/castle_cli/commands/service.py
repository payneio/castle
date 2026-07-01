"""castle service / castle job — manage systemd service & timer units."""

from __future__ import annotations

import argparse
import subprocess

from castle_core.generators.systemd import (
    SYSTEMD_USER_DIR,
    generate_timer,
    generate_unit_from_deployed,
    timer_name,
    unit_name,
)
from castle_core.manifest import kind_for
from castle_core.registry import REGISTRY_PATH, load_registry

from castle_cli.config import (
    CastleConfig,
    ensure_dirs,
    load_config,
)

# Re-export for use by other commands
UNIT_PREFIX = "castle-"


def _install_unit(uname: str, content: str) -> None:
    """Write a systemd unit file."""
    SYSTEMD_USER_DIR.mkdir(parents=True, exist_ok=True)
    unit_path = SYSTEMD_USER_DIR / uname
    unit_path.write_text(content)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)


def _remove_unit(uname: str) -> None:
    """Remove a systemd unit file."""
    unit_path = SYSTEMD_USER_DIR / uname
    if unit_path.exists():
        unit_path.unlink()
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)


_PAST = {"start": "started", "stop": "stopped", "restart": "restarted"}


def run_service_cmd(args: argparse.Namespace) -> int:
    """`castle service <enable|disable|start|stop|restart> <name>`."""
    sub = args.service_command
    config = load_config()
    if sub == "enable":
        if getattr(args, "dry_run", False):
            return _service_dry_run(config, args.name)
        return _service_enable(config, args.name)
    if sub == "disable":
        return _service_disable(config, args.name)
    if sub in ("start", "stop", "restart"):
        return _unit_action(config, args.name, sub, is_job=False)
    return 1


def run_job_cmd(args: argparse.Namespace) -> int:
    """`castle job <enable|disable|start|stop|restart> <name>` (acts on the timer)."""
    sub = args.job_command
    config = load_config()
    if sub == "enable":
        return _service_enable(config, args.name)  # enable_service handles timers
    if sub == "disable":
        return _service_disable(config, args.name)
    if sub in ("start", "stop", "restart"):
        return _unit_action(config, args.name, sub, is_job=True)
    return 1


def run_platform(args: argparse.Namespace) -> int:
    """Top-level `castle start|stop|restart` — the whole platform."""
    config = load_config()
    action = args.command
    if action == "start":
        return _services_start(config)
    if action == "stop":
        return _services_stop(config)
    if action == "restart":
        return _services_restart(config)
    return 1


_GATEWAY_NAME = "castle-gateway"


def _unit_action(config: CastleConfig, name: str, action: str, is_job: bool) -> int:
    """start/stop/restart one service or job, dispatched by its manager.

    systemd (a process/timer) → `systemctl`; caddy (static) → reload the gateway;
    path (a tool) → install/uninstall; none (remote) → nothing to do.
    """
    dep = config.deployments.get(name)
    if dep is None:
        print(f"Error: no deployment '{name}'.")
        return 1
    manager = dep.manager
    if manager != "systemd":
        return _managed_lifecycle(config, name, action, manager)
    # A scheduled systemd deployment (a job) is driven by its .timer.
    unit = timer_name(name) if kind_for(dep) == "job" else unit_name(name)
    result = subprocess.run(["systemctl", "--user", action, unit], check=False)
    if result.returncode != 0:
        print(f"Error: failed to {action} {unit}")
        return 1
    print(f"  {name}: {_PAST[action]}")
    return 0


def _managed_lifecycle(config: CastleConfig, name: str, action: str, manager: str) -> int:
    """Lifecycle for non-systemd managers (no unit to systemctl)."""
    if manager == "caddy":
        if action == "stop":
            print(f"  {name}: gateway-served — disable or remove it to drop the route.")
            return 0
        # start/restart → reload the gateway so current routes take effect.
        subprocess.run(
            ["systemctl", "--user", "reload", unit_name(_GATEWAY_NAME)], check=False
        )
        print(f"  {name}: gateway reloaded ({_PAST[action]}).")
        return 0
    if manager == "path":
        return _path_lifecycle(config, name, action)
    # none (remote): external, nothing local to act on.
    print(f"  {name}: external ({manager}) — nothing to {action}.")
    return 0


def _path_lifecycle(config: CastleConfig, name: str, action: str) -> int:
    """A `path` (tool) deployment's lifecycle is install/uninstall on PATH."""
    import asyncio

    from castle_core.lifecycle import activate, deactivate

    # stop → uninstall; start/restart → ensure installed (activate skips if on PATH).
    coro = deactivate if action == "stop" else activate
    res = asyncio.run(coro(name, config, config.root))
    print(f"  {res.output}")
    return 0 if res.status == "ok" else 1


def _services_restart(config: CastleConfig) -> int:
    """Restart every systemd-managed deployment (service or job) unit.

    caddy/path/none deployments have no unit — they ride along with the gateway
    restart (static) or are stateless (remote), so we don't systemctl them here.
    """
    for name, dep in config.deployments.items():
        if dep.manager != "systemd":
            continue
        if kind_for(dep) == "job":
            subprocess.run(["systemctl", "--user", "restart", timer_name(name)], check=False)
            print(f"  {name}: restarted (timer)")
        else:
            subprocess.run(["systemctl", "--user", "restart", unit_name(name)], check=False)
            print(f"  {name}: restarted")
    return 0


def run_status(args: argparse.Namespace) -> int:
    """Unified status across the platform: services + jobs + programs."""
    from castle_core.lifecycle import is_active

    config = load_config()

    # Services + jobs (deployment state); the gateway appears here as a service.
    _service_status(config)

    # Programs (catalog activation: tools on PATH, statics served by the gateway)
    catalog = {
        n: c
        for n, c in config.programs.items()
        if n not in config.services and n not in config.jobs
    }
    if catalog:
        print(f"{'─' * 50}")
        print("Programs")
        for name, comp in catalog.items():
            on = is_active(name, config)
            color = "\033[92m" if on else "\033[90m"
            label = "active" if on else "inactive"
            kinds = sorted({k for _, k in config.deployments_of(name)})
            tag = ", ".join(kinds) if kinds else "program"
            print(f"  {color}{label:10s}\033[0m  {name}  ({tag})")
        print()
    return 0


def _service_enable(config: CastleConfig, name: str) -> int:
    """Enable a service in its mode (systemd unit / gateway route / PATH install)."""
    import asyncio

    from castle_core.lifecycle import activate

    ensure_dirs()
    result = asyncio.run(activate(name, config, config.root))
    print(result.output)
    return 0 if result.status == "ok" else 1


def _service_disable(config: CastleConfig, name: str) -> int:
    """Disable a service in its mode (stop unit / drop route / uninstall)."""
    import asyncio

    from castle_core.lifecycle import deactivate

    print(f"Disabling {name}...")
    result = asyncio.run(deactivate(name, config, config.root))
    print(f"  {result.output}")
    return 0


def _service_status(config: CastleConfig) -> int:
    """Show status of all services and jobs, dispatched by manager."""
    from castle_core.lifecycle import is_active

    print("\nCastle Services")
    print("=" * 50)

    for name, svc in config.services.items():
        active = is_active(name, config)  # manager-aware (systemd/caddy/path/none)
        manager = svc.manager
        color = "\033[92m" if active else "\033[90m"
        reset = "\033[0m"
        label = "active" if active else "inactive"

        port_str = ""
        if svc.expose and svc.expose.http:
            port_str = f":{svc.expose.http.internal.port}"
        print(f"  {color}{label:10s}{reset}  {name}{port_str}  \033[90m[{manager}]{reset}")

    if config.jobs:
        print(f"\n{'─' * 50}")
        print("Jobs")
        for name in config.jobs:
            tmr_unit = timer_name(name)
            result = subprocess.run(
                ["systemctl", "--user", "is-active", tmr_unit],
                capture_output=True,
                text=True,
            )
            status = result.stdout.strip()
            if status in ("active", "waiting"):
                color = "\033[92m"
            elif status == "inactive":
                color = "\033[90m"
            else:
                color = "\033[91m"
            reset = "\033[0m"
            print(f"  {color}{status:10s}{reset}  {name} (timer)")

    print()
    return 0


def _service_dry_run(config: CastleConfig, name: str) -> int:
    """Print the generated systemd unit(s) without installing."""
    if REGISTRY_PATH.exists():
        registry = load_registry()
        if name in registry.deployed:
            deployed = registry.deployed[name]
            systemd_spec = None
            dep = config.deployments.get(name)
            manage = getattr(dep, "manage", None)
            if manage and manage.systemd:
                systemd_spec = manage.systemd

            svc_unit = unit_name(name)
            svc_content = generate_unit_from_deployed(name, deployed, systemd_spec)
            print(f"# {svc_unit}")
            print(svc_content)

            if deployed.schedule:
                timer_content = generate_timer(
                    name,
                    schedule=deployed.schedule,
                    description=deployed.description,
                )
                print(f"# {timer_name(name)}")
                print(timer_content)
            return 0

    print(f"Error: '{name}' not found in registry. Run 'castle deploy' first.")
    return 1


def _services_start(config: CastleConfig) -> int:
    """Start all managed services and gateway."""
    if not REGISTRY_PATH.exists():
        print("Error: no registry found. Run 'castle deploy' first.")
        return 1

    ensure_dirs()

    from castle_core.config import SPECS_DIR
    from castle_core.generators.caddyfile import generate_caddyfile_from_registry

    registry = load_registry()
    caddyfile_path = SPECS_DIR / "Caddyfile"
    caddyfile_path.write_text(generate_caddyfile_from_registry(registry))
    print(f"Generated {caddyfile_path}")

    # Activate every deployment in its mode: systemd unit / timer, gateway route
    # (static), or PATH install (tool). activate() dispatches by manager.
    for name in config.deployments:
        if name not in registry.deployed:
            print(f"  {name}: skipped (not in registry, run 'castle deploy')")
            continue
        _service_enable(config, name)

    print(f"\nDashboard: http://localhost:{config.gateway.port}")
    return 0


def _services_stop(config: CastleConfig) -> int:
    """Stop all managed services and jobs."""
    for name in config.jobs:
        tmr_unit = timer_name(name)
        subprocess.run(["systemctl", "--user", "stop", tmr_unit], check=False)
        svc_unit = unit_name(name)
        subprocess.run(["systemctl", "--user", "stop", svc_unit], check=False)
        print(f"  {name}: stopped")

    for name in config.services:
        svc_unit = unit_name(name)
        subprocess.run(["systemctl", "--user", "stop", svc_unit], check=False)
        print(f"  {name}: stopped")

    return 0
