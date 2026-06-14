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
        return _service_disable(args.name)
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
        return _service_disable(args.name)
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


def _unit_action(config: CastleConfig, name: str, action: str, is_job: bool) -> int:
    """systemctl start/stop/restart one service (unit) or job (timer)."""
    section = config.jobs if is_job else config.services
    if name not in section:
        print(f"Error: no {'job' if is_job else 'service'} '{name}'.")
        return 1
    unit = timer_name(name) if is_job else unit_name(name)
    result = subprocess.run(["systemctl", "--user", action, unit], check=False)
    if result.returncode != 0:
        print(f"Error: failed to {action} {unit}")
        return 1
    print(f"  {name}: {_PAST[action]}")
    return 0


def _services_restart(config: CastleConfig) -> int:
    """Restart every managed service and job unit."""
    for name in config.jobs:
        subprocess.run(["systemctl", "--user", "restart", timer_name(name)], check=False)
        print(f"  {name}: restarted (timer)")
    for name in config.services:
        subprocess.run(["systemctl", "--user", "restart", unit_name(name)], check=False)
        print(f"  {name}: restarted")
    return 0


def run_status(args: argparse.Namespace) -> int:
    """Unified status across the platform: services + jobs + programs."""
    from castle_core.lifecycle import is_active

    config = load_config()

    # Services + jobs (deployment state); the gateway appears here as a service.
    _service_status(config)

    # Programs (catalog activation: tools on PATH, static frontends served)
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
            print(f"  {color}{label:10s}\033[0m  {name}  ({comp.behavior or 'program'})")
        print()
    return 0


def _service_enable(config: CastleConfig, name: str) -> int:
    """Enable and start a single service (or timer for scheduled jobs)."""
    from castle_core.lifecycle import enable_service

    ensure_dirs()
    result = enable_service(name, config)
    print(result.output)
    return 0 if result.status == "ok" else 1


def _service_disable(name: str) -> int:
    """Stop and disable a service (and timer if present)."""
    from castle_core.lifecycle import disable_service

    print(f"Disabling {name}...")
    result = disable_service(name)
    print(f"  {result.output}")
    return 0


def _service_status(config: CastleConfig) -> int:
    """Show status of all managed services and jobs."""
    print("\nCastle Services")
    print("=" * 50)

    for name, svc in config.services.items():
        svc_unit = unit_name(name)
        result = subprocess.run(
            ["systemctl", "--user", "is-active", svc_unit],
            capture_output=True,
            text=True,
        )
        status = result.stdout.strip()
        if status == "active":
            color = "\033[92m"
        elif status == "inactive":
            color = "\033[90m"
        else:
            color = "\033[91m"
        reset = "\033[0m"

        port_str = ""
        if svc.expose and svc.expose.http:
            port_str = f":{svc.expose.http.internal.port}"
        print(f"  {color}{status:10s}{reset}  {name}{port_str}")

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
            if name in config.services:
                svc = config.services[name]
                if svc.manage and svc.manage.systemd:
                    systemd_spec = svc.manage.systemd
            elif name in config.jobs:
                job = config.jobs[name]
                if job.manage and job.manage.systemd:
                    systemd_spec = job.manage.systemd

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

    for name in config.services:
        if name not in registry.deployed:
            print(f"  {name}: skipped (not in registry, run 'castle deploy')")
            continue
        _service_enable(config, name)

    for name in config.jobs:
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
