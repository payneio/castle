"""Systemd unit and timer generation."""

from __future__ import annotations

import shutil
from pathlib import Path

from castle_core.config import SECRETS_DIR, USER_TOOL_PATH_DIRS
from castle_core.manifest import RestartPolicy, SystemdSpec
from castle_core.registry import Deployment

SYSTEMD_USER_DIR = Path.home() / ".config" / "systemd" / "user"
UNIT_PREFIX = "castle-"

# Generated mode-0600 env files holding a deployment's resolved secrets, kept out
# of the unit file and the process argv (loaded via EnvironmentFile= / --env-file).
SECRET_ENV_DIR = SECRETS_DIR / "env"


def runtime_path(path_prepend: list[str] | tuple[str, ...] = ()) -> str:
    """The PATH a castle service runs with: resolved toolchain dirs (e.g. a pinned
    node bin) + the user tool dirs that exist + system bins. This is the single
    definition of a service's runtime PATH — the unit generator writes it into
    ``Environment=PATH`` and the dependency checker (``relations``) probes tools
    against it, so the two can never disagree about where a service finds its tools.
    """
    dirs = list(path_prepend)
    dirs += [str(d) for d in USER_TOOL_PATH_DIRS if d.exists()]
    dirs += ["/usr/local/bin", "/usr/bin", "/bin"]
    return ":".join(dirs)


def unit_basename(name: str, kind: str = "service") -> str:
    """The systemd unit stem for a deployment. Jobs carry a ``-job`` marker so a
    service and a job can share a name (`castle-<name>.service` vs
    `castle-<name>-job.{service,timer}`); everything else is `castle-<name>`."""
    return f"{UNIT_PREFIX}{name}-job" if kind == "job" else f"{UNIT_PREFIX}{name}"


def unit_name(service_name: str, kind: str = "service") -> str:
    """Get the systemd `.service` unit name for a deployment of the given kind."""
    return f"{unit_basename(service_name, kind)}.service"


def timer_name(service_name: str, kind: str = "job") -> str:
    """Get the systemd `.timer` unit name (timers exist only for jobs)."""
    return f"{unit_basename(service_name, kind)}.timer"


def secret_env_path(service_name: str, kind: str = "service") -> Path:
    """Path to a deployment's generated secret env file (1:1 with its unit name)."""
    return SECRET_ENV_DIR / f"{unit_name(service_name, kind)}.env"


def unit_env_file(deployed: Deployment, name: str) -> Path | None:
    """The ``EnvironmentFile=`` path for a systemd-launched runner, or None.

    Container runners load secrets via docker ``--env-file`` (baked into run_cmd),
    so systemd must not also read them — return None there. Only deployments that
    actually have secrets get a file.
    """
    if deployed.launcher == "container" or not deployed.secret_env_keys:
        return None
    return secret_env_path(name, deployed.kind)


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
    deployed: Deployment,
    systemd_spec: SystemdSpec | None = None,
    env_file: Path | None = None,
) -> str:
    """Generate a systemd unit from a deployed component (registry-based).

    No repo-relative paths — uses only resolved run_cmd and env from the registry.
    Secrets are never inlined as ``Environment=`` lines: ``env_file`` (when set)
    is loaded via ``EnvironmentFile=`` so the values stay out of the unit. The
    path is referenced fail-loud (no ``-`` prefix): a missing file blocks start.
    """
    exec_start = " ".join(deployed.run_cmd)

    env_lines = ""
    for key, value in deployed.env.items():
        env_lines += f"Environment={key}={value}\n"
    # Castle supplies a sensible default PATH (tool dirs + system bins). It is an
    # escape hatch, not a mandate: if the service pins its own PATH in defaults.env
    # (e.g. to add a versioned nvm node the tool dirs intentionally omit), respect
    # it rather than clobbering it with a trailing Environment=PATH line that would
    # win under systemd's last-assignment-wins rule. systemd does NOT expand
    # ${PATH} across Environment= lines, so a service that overrides PATH must
    # spell out the full value, tool dirs included.
    if "PATH" not in deployed.env:
        env_lines += f'Environment="PATH={runtime_path(deployed.path_prepend)}"\n'
    if env_file is not None:
        env_lines += f"EnvironmentFile={env_file}\n"

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
        # Explicit teardown (e.g. compose `down`) so the stack's networks/volumes
        # are reclaimed on stop rather than left dangling.
        if deployed.stop_cmd:
            unit += f"ExecStop={' '.join(deployed.stop_cmd)}\n"

    if sd and sd.exec_reload:
        reload_argv = sd.exec_reload.split()
        resolved_reload = shutil.which(reload_argv[0])
        if resolved_reload:
            reload_argv[0] = resolved_reload
        unit += f"ExecReload={' '.join(reload_argv)}\n"

    # Post-start hooks (e.g. OpenBao auto-unseal). `-` prefix → failure is ignored,
    # so a hiccup in the hook never fails the unit.
    for cmd in sd.exec_start_post if sd else []:
        argv = cmd.split()
        resolved = shutil.which(argv[0])
        if resolved:
            argv[0] = resolved
        unit += f"ExecStartPost=-{' '.join(argv)}\n"

    if sd and sd.no_new_privileges:
        unit += "NoNewPrivileges=true\n"

    unit += f"""
[Install]
WantedBy={wanted_by}
"""
    return unit


def generate_timer(
    name: str,
    schedule: str,
    description: str | None = None,
) -> str:
    """Generate a systemd timer unit from a cron schedule string."""
    description = description or name

    # Try to convert cron to OnCalendar, fall back to OnUnitActiveSec
    on_calendar = cron_to_oncalendar(schedule)
    interval_sec = cron_to_interval_sec(schedule)

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
