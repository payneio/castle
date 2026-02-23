"""castle service / castle services - manage systemd service units."""

from __future__ import annotations

import argparse
import subprocess

from castle_cli.config import (
    CastleConfig,
    ensure_dirs,
    load_config,
)
from castle_core.generators.systemd import (
    SYSTEMD_USER_DIR,
    generate_timer,
    generate_unit,
    get_schedule_trigger,
    timer_name,
    unit_name,
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
    managed = config.managed
    if name not in managed:
        print(f"Error: '{name}' is not a managed service")
        return 1

    manifest = managed[name]
    if not manifest.run:
        print(f"Error: '{name}' has no run spec defined")
        return 1

    ensure_dirs()

    # Generate and install the service unit
    svc_unit = unit_name(name)
    svc_content = generate_unit(config, name, manifest)
    _install_unit(svc_unit, svc_content)

    # Check for timer
    timer_content = generate_timer(name, manifest)
    if timer_content:
        tmr_unit = timer_name(name)
        _install_unit(tmr_unit, timer_content)

        print(f"Enabling {name} (scheduled)...")
        subprocess.run(["systemctl", "--user", "enable", tmr_unit], check=False)
        subprocess.run(["systemctl", "--user", "start", tmr_unit], check=False)

        result = subprocess.run(
            ["systemctl", "--user", "is-active", tmr_unit],
            capture_output=True, text=True,
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
            capture_output=True, text=True,
        )
        status = result.stdout.strip()
        port_str = ""
        if manifest.expose and manifest.expose.http:
            port_str = f" (port {manifest.expose.http.internal.port})"
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
                capture_output=True, text=True,
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
                capture_output=True, text=True,
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
    managed = config.managed
    if name not in managed:
        print(f"Error: '{name}' is not a managed service")
        return 1

    manifest = managed[name]
    if not manifest.run:
        print(f"Error: '{name}' has no run spec defined")
        return 1

    svc_unit = unit_name(name)
    svc_content = generate_unit(config, name, manifest)
    print(f"# {svc_unit}")
    print(svc_content)

    timer_content = generate_timer(name, manifest)
    if timer_content:
        print(f"# {timer_name(name)}")
        print(timer_content)

    return 0


def _services_start(config: CastleConfig) -> int:
    """Start all managed services and gateway."""
    ensure_dirs()

    # Generate Caddyfile before starting gateway
    from castle_cli.commands.gateway import _write_generated_files

    print("Generating gateway configuration...")
    _write_generated_files(config)

    for name, manifest in config.managed.items():
        if not manifest.run:
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
