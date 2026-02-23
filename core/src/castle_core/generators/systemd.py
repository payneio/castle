"""Systemd unit and timer generation."""

from __future__ import annotations

import shutil
from pathlib import Path

from castle_core.manifest import ComponentManifest, RestartPolicy, SystemdSpec
from castle_core.registry import DeployedComponent

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
    if (
        minute.startswith("*/")
        and hour == "*"
        and dom == "*"
        and month == "*"
        and dow == "*"
    ):
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
    if (
        minute.startswith("*/")
        and hour == "*"
        and dom == "*"
        and month == "*"
        and dow == "*"
    ):
        try:
            return int(minute[2:]) * 60
        except ValueError:
            return None
    return None


def generate_unit_from_deployed(
    name: str,
    deployed: DeployedComponent,
    systemd_spec: SystemdSpec | None = None,
) -> str:
    """Generate a systemd unit from a deployed component (registry-based).

    No repo-relative paths — uses only resolved run_cmd and env from the registry.
    """
    exec_start = " ".join(deployed.run_cmd)

    env_lines = ""
    for key, value in deployed.env.items():
        env_lines += f"Environment={key}={value}\n"
    env_lines += f'Environment="PATH={Path.home() / ".local/bin"}:/usr/local/bin:/usr/bin:/bin"\n'

    sd = systemd_spec
    description = deployed.description or name
    after = " ".join(sd.after) if sd and sd.after else "network.target"
    wanted_by = " ".join(sd.wanted_by) if sd else "default.target"

    if deployed.schedule:
        unit = f"""[Unit]
Description=Castle: {description}
After={after}

[Service]
Type=oneshot
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
