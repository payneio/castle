"""Systemd unit and timer generation from castle manifests."""

from __future__ import annotations

import shutil
from pathlib import Path

from castle_core.config import CastleConfig, resolve_env_vars
from castle_core.manifest import ComponentManifest, RestartPolicy

SYSTEMD_USER_DIR = Path.home() / ".config" / "systemd" / "user"
UNIT_PREFIX = "castle-"


def unit_name(service_name: str) -> str:
    """Get the systemd unit name for a service."""
    return f"{UNIT_PREFIX}{service_name}.service"


def timer_name(service_name: str) -> str:
    """Get the systemd timer name for a scheduled service."""
    return f"{UNIT_PREFIX}{service_name}.timer"


def get_schedule_trigger(manifest: ComponentManifest) -> object | None:
    """Return the schedule trigger if one exists, else None."""
    for t in manifest.triggers:
        if getattr(t, "type", None) == "schedule":
            return t
    return None


def cron_to_oncalendar(cron: str) -> str:
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


def cron_to_interval_sec(cron: str) -> int | None:
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


def manifest_to_exec_start(manifest: ComponentManifest, root: Path) -> str:
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
            return build_podman_command(manifest)
        case "node":
            pm = run.package_manager
            cmd = f"{pm} run {run.script}"
            if run.args:
                cmd += " " + " ".join(run.args)
            return cmd
        case _:
            raise ValueError(f"Unsupported runner '{run.runner}' for systemd unit")


def build_podman_command(manifest: ComponentManifest) -> str:
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


def generate_unit(config: CastleConfig, name: str, manifest: ComponentManifest) -> str:
    """Generate a systemd user unit file for a component."""
    run = manifest.run
    if run is None:
        raise ValueError(f"Component '{name}' has no run spec")

    working_dir = config.root / (run.working_dir or name)
    exec_start = manifest_to_exec_start(manifest, config.root)

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

    is_scheduled = get_schedule_trigger(manifest) is not None

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
SuccessExitStatus=143
"""

    if sd and sd.exec_reload:
        reload_argv = sd.exec_reload.split()
        resolved_reload = shutil.which(reload_argv[0])
        if resolved_reload:
            reload_argv[0] = resolved_reload
        unit += f"ExecReload={' '.join(reload_argv)}\n"

    if sd and sd.no_new_privileges:
        unit += "NoNewPrivileges=true\n"

    unit += f"""
[Install]
WantedBy={wanted_by}
"""
    return unit


def generate_timer(name: str, manifest: ComponentManifest) -> str | None:
    """Generate a systemd timer unit if the component has a schedule trigger."""
    trigger = get_schedule_trigger(manifest)
    if trigger is None:
        return None

    description = manifest.description or name

    # Try to convert cron to OnCalendar, fall back to OnUnitActiveSec
    on_calendar = cron_to_oncalendar(trigger.cron)
    interval_sec = cron_to_interval_sec(trigger.cron)

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
