"""castle service / castle services - manage systemd service units."""

from __future__ import annotations

import argparse
import subprocess

from castle_core.generators.systemd import (
    SYSTEMD_USER_DIR,
    generate_timer,
    generate_unit_from_deployed,
    get_schedule_trigger,
    timer_name,
    unit_name,
)
from castle_core.registry import REGISTRY_PATH, load_registry

from castle_cli.config import (
    CastleConfig,
    ensure_dirs,
    load_config,
)


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
        print("Usage: castle service {enable|disable|status}")
        return 1

    config = load_config()

    if args.service_command == "enable":
        if getattr(args, "dry_run", False):
            return _service_dry_run(config, args.name)
        return _service_enable(config, args.name)
    elif args.service_command == "disable":
        return _service_disable(args.name)
    elif args.service_command == "status":
        return _service_status(config)

    return 1


def run_services(args: argparse.Namespace) -> int:
    """Manage all services together."""
    if not args.services_command:
        print("Usage: castle services {start|stop}")
        return 1

    config = load_config()

    if args.services_command == "start":
        return _services_start(config)
    elif args.services_command == "stop":
        return _services_stop(config)

    return 1


def _service_enable(config: CastleConfig, name: str) -> int:
    """Enable and start a single service (or timer for scheduled jobs)."""
    # Require registry
    if not REGISTRY_PATH.exists():
        print("Error: no registry found. Run 'castle deploy' first.")
        return 1

    registry = load_registry()
    if name not in registry.deployed:
        print(f"Error: '{name}' not found in registry. Run 'castle deploy' first.")
        return 1

    deployed = registry.deployed[name]
    if not deployed.managed:
        print(f"Error: '{name}' is not a managed service")
        return 1

    ensure_dirs()

    # Get systemd spec from manifest for restart policy etc.
    systemd_spec = None
    if name in config.components:
        manifest = config.components[name]
        if manifest.manage and manifest.manage.systemd:
            systemd_spec = manifest.manage.systemd

    # Generate and install the service unit from registry
    svc_unit = unit_name(name)
    svc_content = generate_unit_from_deployed(name, deployed, systemd_spec)
    _install_unit(svc_unit, svc_content)

    # Check for timer (still uses manifest for schedule config)
    manifest = config.components.get(name)
    timer_content = generate_timer(name, manifest) if manifest else None
    if timer_content:
        tmr_unit = timer_name(name)
        _install_unit(tmr_unit, timer_content)

        print(f"Enabling {name} (scheduled)...")
        subprocess.run(["systemctl", "--user", "enable", tmr_unit], check=False)
        subprocess.run(["systemctl", "--user", "start", tmr_unit], check=False)

        result = subprocess.run(
            ["systemctl", "--user", "is-active", tmr_unit],
            capture_output=True,
            text=True,
        )
        status = result.stdout.strip()
        if status in ("active", "waiting"):
            print(f"  {name}: timer active")
        else:
            print(f"  {name}: timer {status}")
    else:
        print(f"Enabling {name}...")
        subprocess.run(["systemctl", "--user", "enable", svc_unit], check=False)
        subprocess.run(["systemctl", "--user", "start", svc_unit], check=False)

        result = subprocess.run(
            ["systemctl", "--user", "is-active", svc_unit],
            capture_output=True,
            text=True,
        )
        status = result.stdout.strip()
        port_str = ""
        if deployed.port:
            port_str = f" (port {deployed.port})"
        if status == "active":
            print(f"  {name}: running{port_str}")
        else:
            print(f"  {name}: {status}")
            print(f"  Check logs: journalctl --user -u {svc_unit}")

    return 0


def _service_disable(name: str) -> int:
    """Stop and disable a service (and timer if present)."""
    svc_unit = unit_name(name)
    tmr_unit = timer_name(name)

    print(f"Disabling {name}...")

    # Stop and disable timer if exists
    timer_path = SYSTEMD_USER_DIR / tmr_unit
    if timer_path.exists():
        subprocess.run(["systemctl", "--user", "stop", tmr_unit], check=False)
        subprocess.run(["systemctl", "--user", "disable", tmr_unit], check=False)
        _remove_unit(tmr_unit)

    subprocess.run(["systemctl", "--user", "stop", svc_unit], check=False)
    subprocess.run(["systemctl", "--user", "disable", svc_unit], check=False)
    _remove_unit(svc_unit)
    print(f"  {name}: disabled")

    return 0


def _service_status(config: CastleConfig) -> int:
    """Show status of all managed services."""
    print("\nCastle Services")
    print("=" * 50)

    for name, manifest in config.managed.items():
        is_scheduled = get_schedule_trigger(manifest) is not None

        if is_scheduled:
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
        else:
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
            if manifest.expose and manifest.expose.http:
                port_str = f":{manifest.expose.http.internal.port}"
            print(f"  {color}{status:10s}{reset}  {name}{port_str}")

    print()
    return 0


def _service_dry_run(config: CastleConfig, name: str) -> int:
    """Print the generated systemd unit(s) without installing."""
    # Try registry first, fall back to showing what deploy would generate
    if REGISTRY_PATH.exists():
        registry = load_registry()
        if name in registry.deployed:
            deployed = registry.deployed[name]
            systemd_spec = None
            if name in config.components:
                manifest = config.components[name]
                if manifest.manage and manifest.manage.systemd:
                    systemd_spec = manifest.manage.systemd

            svc_unit = unit_name(name)
            svc_content = generate_unit_from_deployed(name, deployed, systemd_spec)
            print(f"# {svc_unit}")
            print(svc_content)

            manifest = config.components.get(name)
            if manifest:
                timer_content = generate_timer(name, manifest)
                if timer_content:
                    print(f"# {timer_name(name)}")
                    print(timer_content)
            return 0

    print(f"Error: '{name}' not found in registry. Run 'castle deploy' first.")
    return 1


def _services_start(config: CastleConfig) -> int:
    """Start all managed services and gateway."""
    # Require registry
    if not REGISTRY_PATH.exists():
        print("Error: no registry found. Run 'castle deploy' first.")
        return 1

    ensure_dirs()

    # Generate Caddyfile from registry
    from castle_core.config import GENERATED_DIR
    from castle_core.generators.caddyfile import generate_caddyfile_from_registry

    registry = load_registry()
    caddyfile_path = GENERATED_DIR / "Caddyfile"
    caddyfile_path.write_text(generate_caddyfile_from_registry(registry))
    print(f"Generated {caddyfile_path}")

    for name in config.managed:
        if name not in registry.deployed:
            print(f"  {name}: skipped (not in registry, run 'castle deploy')")
            continue
        _service_enable(config, name)

    print(f"\nDashboard: http://localhost:{config.gateway.port}")
    return 0


def _services_stop(config: CastleConfig) -> int:
    """Stop all managed services and gateway."""
    for name, manifest in config.managed.items():
        is_scheduled = get_schedule_trigger(manifest) is not None
        if is_scheduled:
            tmr_unit = timer_name(name)
            subprocess.run(["systemctl", "--user", "stop", tmr_unit], check=False)
        svc_unit = unit_name(name)
        subprocess.run(["systemctl", "--user", "stop", svc_unit], check=False)
        print(f"  {name}: stopped")

    return 0
