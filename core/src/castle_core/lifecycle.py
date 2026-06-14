"""Unified program lifecycle — a program is `active` when it's reachable in its mode.

`activate`/`deactivate` dispatch the right mechanism by behavior:
  - tool                          → on PATH (uv tool install / uninstall)
  - daemon / self-serving frontend / job → systemd enable+start / stop+disable
  - static frontend               → served via the gateway (build + content present)

`is_active` reports the uniform state regardless of mechanism. The CLI/API verbs
`install`/`uninstall` route through here (the words stay; the meaning is activate).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from castle_core.config import CONTENT_DIR, CastleConfig
from castle_core.generators.systemd import (
    SYSTEMD_USER_DIR,
    generate_timer,
    generate_unit_from_deployed,
    timer_name,
    unit_name,
)
from castle_core.registry import REGISTRY_PATH, load_registry
from castle_core.stacks import ActionResult, run_action


def _systemctl_active(unit: str) -> bool:
    result = subprocess.run(
        ["systemctl", "--user", "is-active", unit], capture_output=True, text=True
    )
    return result.stdout.strip() in ("active", "waiting")


def _on_path(name: str) -> bool:
    """Whether a tool's console script is installed (PATH-independent).

    uv tool install places scripts in ~/.local/bin; checking it directly avoids
    depending on the caller's PATH (the API/CLI may not have it exported).
    """
    if shutil.which(name) is not None:
        return True
    return (Path.home() / ".local" / "bin" / name).exists()


def _is_static_frontend(name: str, config: CastleConfig) -> bool:
    """A frontend with no service/job of its own — served as static assets."""
    comp = config.programs.get(name)
    return (
        comp is not None
        and comp.behavior == "frontend"
        and name not in config.services
        and name not in config.jobs
    )


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


def is_active(name: str, config: CastleConfig) -> bool:
    """Whether a program is reachable in its mode (uniform across behaviors)."""
    if name in config.services:
        return _systemctl_active(unit_name(name))
    if name in config.jobs:
        return _systemctl_active(timer_name(name))
    if _is_static_frontend(name, config):
        return (CONTENT_DIR / name).is_dir()
    comp = config.programs.get(name)
    if comp is not None and comp.source:
        return _on_path(name)
    return False


# ---------------------------------------------------------------------------
# Systemd enable/disable (extracted core; the CLI service command calls these)
# ---------------------------------------------------------------------------


def enable_service(name: str, config: CastleConfig) -> ActionResult:
    """Generate+install the unit (and timer) from the registry, enable and start it."""
    if not REGISTRY_PATH.exists():
        return ActionResult(name, "activate", "error", "No registry. Run 'castle deploy' first.")
    registry = load_registry()
    if name not in registry.deployed:
        return ActionResult(name, "activate", "error", f"'{name}' not in registry; run 'castle deploy'.")
    deployed = registry.deployed[name]
    if not deployed.managed:
        return ActionResult(name, "activate", "error", f"'{name}' is not a managed service.")

    systemd_spec = None
    if name in config.services and config.services[name].manage:
        systemd_spec = config.services[name].manage.systemd
    elif name in config.jobs and config.jobs[name].manage:
        systemd_spec = config.jobs[name].manage.systemd

    SYSTEMD_USER_DIR.mkdir(parents=True, exist_ok=True)
    svc_unit = unit_name(name)
    (SYSTEMD_USER_DIR / svc_unit).write_text(generate_unit_from_deployed(name, deployed, systemd_spec))
    primary = svc_unit
    if deployed.schedule:
        tmr_unit = timer_name(name)
        (SYSTEMD_USER_DIR / tmr_unit).write_text(
            generate_timer(name, schedule=deployed.schedule, description=deployed.description)
        )
        primary = tmr_unit

    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    subprocess.run(["systemctl", "--user", "enable", primary], check=False)
    subprocess.run(["systemctl", "--user", "start", primary], check=False)
    status = "active" if _systemctl_active(primary) else "inactive"
    return ActionResult(name, "activate", "ok" if status == "active" else "error",
                        f"{name}: {status}")


def disable_service(name: str) -> ActionResult:
    """Stop, disable, and remove the unit (and timer) for a service/job."""
    for unit in (timer_name(name), unit_name(name)):
        path = SYSTEMD_USER_DIR / unit
        if path.exists():
            subprocess.run(["systemctl", "--user", "stop", unit], check=False)
            subprocess.run(["systemctl", "--user", "disable", unit], check=False)
            path.unlink()
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    return ActionResult(name, "deactivate", "ok", f"{name}: deactivated")


# ---------------------------------------------------------------------------
# Activate / deactivate (dispatch by behavior)
# ---------------------------------------------------------------------------


async def activate(name: str, config: CastleConfig, root: Path) -> ActionResult:
    """Make a program reachable in its mode."""
    comp = config.programs.get(name)

    # Process-backed: daemon, self-serving frontend, or job.
    if name in config.services or name in config.jobs:
        # Ensure the program's binary is on PATH first (python programs).
        if comp is not None and (comp.stack or comp.commands):
            res = await run_action("install", name, comp, root)
            if res.status != "ok":
                return res
        return enable_service(name, config)

    # Static frontend: build the assets (publish handled by the build/serve path).
    if comp is not None and comp.behavior == "frontend":
        return await run_action("install", name, comp, root)

    # Tool: install to PATH.
    if comp is not None:
        return await run_action("install", name, comp, root)
    return ActionResult(name, "activate", "error", f"'{name}' not found")


async def deactivate(name: str, config: CastleConfig, root: Path) -> ActionResult:
    """Take a program offline in its mode."""
    comp = config.programs.get(name)
    if name in config.services or name in config.jobs:
        return disable_service(name)
    if comp is not None:
        return await run_action("uninstall", name, comp, root)
    return ActionResult(name, "deactivate", "error", f"'{name}' not found")
