"""castle service / castle services - manage systemd service units."""

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


def run_service(args: argparse.Namespace) -> int:
    """Manage individual services."""
    if not args.service_command:
        print("Usage: castle service {enable|disable}")
        return 1

    config = load_config()

    if args.service_command == "enable":
        if getattr(args, "dry_run", False):
            return _service_dry_run(config, args.name)
        return _service_enable(config, args.name)
    elif args.service_command == "disable":
        return _service_disable(args.name)

    return 1


def run_services(args: argparse.Namespace) -> int:
    """Manage all services together."""
    if not args.services_command:
        print("Usage: castle services {start|stop|status}")
        return 1

    config = load_config()

    if args.services_command == "start":
        return _services_start(config)
    elif args.services_command == "stop":
        return _services_stop(config)
    elif args.services_command == "status":
        return _service_status(config)

    return 1


def run_restart(args: argparse.Namespace) -> int:
    """Restart a single deployed service or job."""
    config = load_config()
    name = args.name
    if name not in config.services and name not in config.jobs:
        print(f"Error: '{name}' is not a known service or job.")
        return 1
    # Jobs are driven by their timer; services by the service unit.
    unit = timer_name(name) if name in config.jobs else unit_name(name)
    result = subprocess.run(["systemctl", "--user", "restart", unit], check=False)
    if result.returncode != 0:
        print(f"Error: failed to restart {unit}")
        return 1
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


def run_up(args: argparse.Namespace) -> int:
    """Bring everything online: deploy from castle.yaml, then start all services."""
    from castle_cli.commands.deploy import run_deploy

    config = load_config()
    print("Deploying from castle.yaml...")
    run_deploy(argparse.Namespace(name=None))
    print("\nStarting services and gateway...")
    return _services_start(config)


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
