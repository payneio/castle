"""castle service / castle services - manage systemd service units."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

from castle_cli.config import (
    GENERATED_DIR,
    CastleConfig,
    ensure_dirs,
    load_config,
    resolve_env_vars,
)
from castle_cli.manifest import ComponentManifest, RestartPolicy

SYSTEMD_USER_DIR = Path.home() / ".config" / "systemd" / "user"
UNIT_PREFIX = "castle-"


def _unit_name(service_name: str) -> str:
    """Get the systemd unit name for a service."""
    return f"{UNIT_PREFIX}{service_name}.service"


def _timer_name(service_name: str) -> str:
    """Get the systemd timer name for a scheduled service."""
    return f"{UNIT_PREFIX}{service_name}.timer"


def _get_schedule_trigger(manifest: ComponentManifest) -> object | None:
    """Return the schedule trigger if one exists, else None."""
    for t in manifest.triggers:
        if getattr(t, "type", None) == "schedule":
            return t
    return None


def _cron_to_oncalendar(cron: str) -> str:
    """Best-effort conversion of cron expression to systemd OnCalendar.

    Handles common patterns; falls back to using OnUnitActiveSec for the rest.
    """
    parts = cron.strip().split()
    if len(parts) != 5:
        return ""

    minute, hour, dom, month, dow = parts

    # */N minutes → run every N minutes
    if minute.startswith("*/") and hour == "*" and dom == "*" and month == "*" and dow == "*":
        return ""  # Use OnUnitActiveSec instead

    # Specific time daily: "0 2 * * *" → "*-*-* 02:00:00"
    if dom == "*" and month == "*" and dow == "*":
        h = hour.zfill(2) if hour != "*" else "*"
        m = minute.zfill(2) if minute != "*" else "*"
        return f"*-*-* {h}:{m}:00"

    return ""


def _cron_to_interval_sec(cron: str) -> int | None:
    """Extract interval seconds from */N cron patterns."""
    parts = cron.strip().split()
    if len(parts) != 5:
        return None
    minute, hour, dom, month, dow = parts
    if minute.startswith("*/") and hour == "*" and dom == "*" and month == "*" and dow == "*":
        try:
            return int(minute[2:]) * 60
        except ValueError:
            return None
    return None


def _manifest_to_exec_start(manifest: ComponentManifest, root: Path) -> str:
    """Convert a manifest's RunSpec to a systemd ExecStart command."""
    run = manifest.run
    if run is None:
        raise ValueError(f"Component '{manifest.id}' has no run spec")

    match run.runner:
        case "python_uv_tool":
            uv_path = shutil.which("uv") or "uv"
            args_str = " ".join(run.args) if run.args else ""
            cmd = f"{uv_path} run {run.tool}"
            if args_str:
                cmd += f" {args_str}"
            return cmd
        case "python_module":
            python = run.python or shutil.which("python3") or "python3"
            args_str = " ".join(run.args) if run.args else ""
            cmd = f"{python} -m {run.module}"
            if args_str:
                cmd += f" {args_str}"
            return cmd
        case "command":
            argv = list(run.argv)
            resolved = shutil.which(argv[0])
            if resolved:
                argv[0] = resolved
            return " ".join(argv)
        case "container":
            return _build_podman_command(manifest)
        case "node":
            pm = run.package_manager
            cmd = f"{pm} run {run.script}"
            if run.args:
                cmd += " " + " ".join(run.args)
            return cmd
        case _:
            raise ValueError(f"Unsupported runner '{run.runner}' for systemd unit")


def _build_podman_command(manifest: ComponentManifest) -> str:
    """Build a podman/docker run command from a container RunSpec."""
    run = manifest.run
    podman = shutil.which("podman") or shutil.which("docker") or "podman"
    parts = [podman, "run", "--rm", f"--name=castle-{manifest.id}"]

    for container_port, host_port in run.ports.items():
        parts.append(f"-p {host_port}:{container_port}")
    for vol in run.volumes:
        parts.append(f"-v {vol}")
    for key, val in run.env.items():
        parts.append(f"-e {key}={val}")
    if run.workdir:
        parts.append(f"-w {run.workdir}")

    parts.append(run.image)
    if run.command:
        parts.extend(run.command)
    if run.args:
        parts.extend(run.args)

    return " ".join(parts)


def _generate_unit(config: CastleConfig, name: str, manifest: ComponentManifest) -> str:
    """Generate a systemd user unit file for a component."""
    run = manifest.run
    if run is None:
        raise ValueError(f"Component '{name}' has no run spec")

    working_dir = config.root / (run.cwd or name)
    exec_start = _manifest_to_exec_start(manifest, config.root)

    resolved_env = resolve_env_vars(run.env, manifest)
    env_lines = ""
    for key, value in resolved_env.items():
        env_lines += f"Environment={key}={value}\n"

    # Add PATH so tools are findable
    env_lines += f'Environment="PATH={Path.home() / ".local/bin"}:/usr/local/bin:/usr/bin:/bin"\n'

    sd = None
    if manifest.manage and manifest.manage.systemd:
        sd = manifest.manage.systemd

    description = (sd and sd.description) or manifest.description or name
    after = " ".join(sd.after) if sd and sd.after else "network.target"
    wanted_by = " ".join(sd.wanted_by) if sd else "default.target"

    is_scheduled = _get_schedule_trigger(manifest) is not None

    if is_scheduled:
        # Oneshot service for timer-driven jobs
        unit = f"""[Unit]
Description=Castle: {description}
After={after}

[Service]
Type=oneshot
WorkingDirectory={working_dir}
ExecStart={exec_start}
{env_lines}"""
    else:
        restart = (sd.restart if sd else RestartPolicy.ON_FAILURE).value
        restart_sec = sd.restart_sec if sd else 5
        unit = f"""[Unit]
Description=Castle: {description}
After={after}

[Service]
Type=simple
WorkingDirectory={working_dir}
ExecStart={exec_start}
{env_lines}Restart={restart}
RestartSec={restart_sec}
"""

    if sd and sd.no_new_privileges:
        unit += "NoNewPrivileges=true\n"

    unit += f"""
[Install]
WantedBy={wanted_by}
"""
    return unit


def _generate_timer(name: str, manifest: ComponentManifest) -> str | None:
    """Generate a systemd timer unit if the component has a schedule trigger."""
    trigger = _get_schedule_trigger(manifest)
    if trigger is None:
        return None

    description = manifest.description or name

    # Try to convert cron to OnCalendar, fall back to OnUnitActiveSec
    on_calendar = _cron_to_oncalendar(trigger.cron)
    interval_sec = _cron_to_interval_sec(trigger.cron)

    timer_lines = ""
    if on_calendar:
        timer_lines = f"OnCalendar={on_calendar}\n"
    elif interval_sec:
        timer_lines = f"OnBootSec=60\nOnUnitActiveSec={interval_sec}s\n"
    else:
        timer_lines = "OnBootSec=60\nOnUnitActiveSec=300\n"

    return f"""[Unit]
Description=Castle timer: {description}

[Timer]
{timer_lines}Persistent=false

[Install]
WantedBy=timers.target
"""


def _generate_gateway_unit(config: CastleConfig) -> str:
    """Generate a systemd unit for the Caddy gateway."""
    caddy_path = shutil.which("caddy") or "caddy"
    caddyfile = GENERATED_DIR / "Caddyfile"

    return f"""[Unit]
Description=Castle Gateway (Caddy)
After=network.target

[Service]
Type=simple
ExecStart={caddy_path} run --config {caddyfile} --adapter caddyfile
ExecReload={caddy_path} reload --config {caddyfile} --adapter caddyfile
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
"""


def _install_unit(unit_name: str, content: str) -> None:
    """Write a systemd unit file."""
    SYSTEMD_USER_DIR.mkdir(parents=True, exist_ok=True)
    unit_path = SYSTEMD_USER_DIR / unit_name
    unit_path.write_text(content)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)


def _remove_unit(unit_name: str) -> None:
    """Remove a systemd unit file."""
    unit_path = SYSTEMD_USER_DIR / unit_name
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
    svc_unit = _unit_name(name)
    svc_content = _generate_unit(config, name, manifest)
    _install_unit(svc_unit, svc_content)

    # Check for timer
    timer_content = _generate_timer(name, manifest)
    if timer_content:
        timer_unit = _timer_name(name)
        _install_unit(timer_unit, timer_content)

        print(f"Enabling {name} (scheduled)...")
        subprocess.run(["systemctl", "--user", "enable", timer_unit], check=False)
        subprocess.run(["systemctl", "--user", "start", timer_unit], check=False)

        result = subprocess.run(
            ["systemctl", "--user", "is-active", timer_unit],
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
    svc_unit = _unit_name(name)
    timer_unit = _timer_name(name)

    print(f"Disabling {name}...")

    # Stop and disable timer if exists
    timer_path = SYSTEMD_USER_DIR / timer_unit
    if timer_path.exists():
        subprocess.run(["systemctl", "--user", "stop", timer_unit], check=False)
        subprocess.run(["systemctl", "--user", "disable", timer_unit], check=False)
        _remove_unit(timer_unit)

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
        is_scheduled = _get_schedule_trigger(manifest) is not None

        if is_scheduled:
            timer_unit = _timer_name(name)
            result = subprocess.run(
                ["systemctl", "--user", "is-active", timer_unit],
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
            unit_name = _unit_name(name)
            result = subprocess.run(
                ["systemctl", "--user", "is-active", unit_name],
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

    # Gateway status
    gw_unit = f"{UNIT_PREFIX}gateway.service"
    result = subprocess.run(
        ["systemctl", "--user", "is-active", gw_unit],
        capture_output=True, text=True,
    )
    gw_status = result.stdout.strip()
    color = "\033[92m" if gw_status == "active" else "\033[90m"
    reset = "\033[0m"
    print(f"  {color}{gw_status:10s}{reset}  gateway :{config.gateway.port}")

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

    svc_unit = _unit_name(name)
    svc_content = _generate_unit(config, name, manifest)
    print(f"# {svc_unit}")
    print(svc_content)

    timer_content = _generate_timer(name, manifest)
    if timer_content:
        print(f"# {_timer_name(name)}")
        print(timer_content)

    return 0


def _services_start(config: CastleConfig) -> int:
    """Start all managed services and gateway."""
    ensure_dirs()

    from castle_cli.commands.gateway import _write_generated_files

    print("Generating gateway configuration...")
    _write_generated_files(config)

    if shutil.which("caddy"):
        gw_unit_name = f"{UNIT_PREFIX}gateway.service"
        gw_content = _generate_gateway_unit(config)
        _install_unit(gw_unit_name, gw_content)
        subprocess.run(["systemctl", "--user", "enable", gw_unit_name], check=False)
        subprocess.run(["systemctl", "--user", "start", gw_unit_name], check=False)
        print(f"Gateway: started on port {config.gateway.port}")
    else:
        print("Warning: caddy not installed, skipping gateway")

    for name, manifest in config.managed.items():
        if not manifest.run:
            continue
        _service_enable(config, name)

    print(f"\nDashboard: http://localhost:{config.gateway.port}")
    return 0


def _services_stop(config: CastleConfig) -> int:
    """Stop all managed services and gateway."""
    for name, manifest in config.managed.items():
        is_scheduled = _get_schedule_trigger(manifest) is not None
        if is_scheduled:
            timer_unit = _timer_name(name)
            subprocess.run(["systemctl", "--user", "stop", timer_unit], check=False)
        unit_name = _unit_name(name)
        subprocess.run(["systemctl", "--user", "stop", unit_name], check=False)
        print(f"  {name}: stopped")

    gw_unit = f"{UNIT_PREFIX}gateway.service"
    subprocess.run(["systemctl", "--user", "stop", gw_unit], check=False)
    print("  gateway: stopped")

    return 0
