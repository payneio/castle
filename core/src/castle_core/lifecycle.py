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

from castle_core.config import CastleConfig
from castle_core.generators.systemd import (
    SYSTEMD_USER_DIR,
    generate_timer,
    generate_unit_from_deployed,
    secret_env_path,
    timer_name,
    unit_env_file,
    unit_name,
)
from castle_core.manifest import manager_for
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


def _svc_manager(name: str, config: CastleConfig) -> str | None:
    """The manager for a deployed name (service/job), or None if not deployed."""
    if name in config.services:
        return manager_for(config.services[name].run.runner)
    if name in config.jobs:
        return "systemd"
    return None


def _static_built(name: str, config: CastleConfig) -> bool:
    """Whether a static service's served dir exists (assets are built)."""
    svc = config.services.get(name)
    if svc is None:
        return False
    comp = config.programs.get(svc.program or name)
    root = getattr(svc.run, "root", "dist")
    return bool(comp and comp.source and (Path(comp.source) / root).is_dir())


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


def is_active(name: str, config: CastleConfig) -> bool:
    """Whether a deployment is available in its mode, dispatched by its manager."""
    manager = _svc_manager(name, config)
    if manager == "systemd":
        unit = timer_name(name) if name in config.jobs else unit_name(name)
        return _systemctl_active(unit)
    if manager == "caddy":
        return _static_built(name, config)  # served once its assets exist
    if manager == "path":
        return _on_path(name)
    if manager == "none":
        return True  # remote: external, treated as available
    # No deployment — a bare program (e.g. a tool not yet given a path service).
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
        return ActionResult(
            name, "activate", "error", "No registry. Run 'castle deploy' first."
        )
    registry = load_registry()
    if name not in registry.deployed:
        return ActionResult(
            name, "activate", "error", f"'{name}' not in registry; run 'castle deploy'."
        )
    deployed = registry.deployed[name]
    if not deployed.managed:
        return ActionResult(
            name, "activate", "error", f"'{name}' is not a managed service."
        )

    systemd_spec = None
    if name in config.services and config.services[name].manage:
        systemd_spec = config.services[name].manage.systemd
    elif name in config.jobs and config.jobs[name].manage:
        systemd_spec = config.jobs[name].manage.systemd

    SYSTEMD_USER_DIR.mkdir(parents=True, exist_ok=True)
    svc_unit = unit_name(name)
    (SYSTEMD_USER_DIR / svc_unit).write_text(
        generate_unit_from_deployed(
            name, deployed, systemd_spec, env_file=unit_env_file(deployed, name)
        )
    )
    primary = svc_unit
    if deployed.schedule:
        tmr_unit = timer_name(name)
        (SYSTEMD_USER_DIR / tmr_unit).write_text(
            generate_timer(
                name, schedule=deployed.schedule, description=deployed.description
            )
        )
        primary = tmr_unit

    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    subprocess.run(["systemctl", "--user", "enable", primary], check=False)
    subprocess.run(["systemctl", "--user", "start", primary], check=False)
    status = "active" if _systemctl_active(primary) else "inactive"
    return ActionResult(
        name, "activate", "ok" if status == "active" else "error", f"{name}: {status}"
    )


def disable_service(name: str) -> ActionResult:
    """Stop, disable, and remove the unit (and timer) for a service/job."""
    for unit in (timer_name(name), unit_name(name)):
        path = SYSTEMD_USER_DIR / unit
        if path.exists():
            subprocess.run(["systemctl", "--user", "stop", unit], check=False)
            subprocess.run(["systemctl", "--user", "disable", unit], check=False)
            path.unlink()
    # Drop the generated secret env file alongside the unit.
    secret_env_path(name).unlink(missing_ok=True)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    return ActionResult(name, "deactivate", "ok", f"{name}: deactivated")


# ---------------------------------------------------------------------------
# Activate / deactivate (dispatch by behavior)
# ---------------------------------------------------------------------------


def _program_for(name: str, config: CastleConfig):
    """The program a deployment runs (its `program` ref, defaulting to the name)."""
    prog = name
    if name in config.services:
        prog = config.services[name].program or name
    return prog, config.programs.get(prog)


async def activate(name: str, config: CastleConfig, root: Path) -> ActionResult:
    """Make a deployment available in its mode, dispatched by its manager."""
    manager = _svc_manager(name, config)

    if manager == "systemd":
        # Ensure the program's binary is on PATH first (python), then enable the
        # unit. Skip the editable reinstall if it's already there.
        comp = config.programs.get(name)
        if comp is not None and (comp.stack or comp.commands) and not _on_path(name):
            res = await run_action("install", name, comp, root)
            if res.status != "ok":
                return res
        return enable_service(name, config)

    if manager == "caddy":
        # Served by the gateway — reload it so the route is live. Building the
        # assets is `castle program build` (the program's concern), not activation.
        subprocess.run(
            ["systemctl", "--user", "reload", unit_name("castle-gateway")], check=False
        )
        return ActionResult(name, "activate", "ok", f"{name}: served via gateway")

    if manager == "path":
        prog, comp = _program_for(name, config)
        if comp is None:
            return ActionResult(name, "activate", "error", f"unknown program '{prog}'")
        if _on_path(prog):  # already installed — skip the (slow) editable reinstall
            return ActionResult(name, "activate", "ok", f"{name}: on PATH")
        return await run_action("install", prog, comp, root)

    if manager == "none":
        return ActionResult(name, "activate", "ok", f"{name}: external")

    # No deployment — a bare tool program: install to PATH.
    comp = config.programs.get(name)
    if comp is not None:
        return await run_action("install", name, comp, root)
    return ActionResult(name, "activate", "error", f"'{name}' not found")


async def deactivate(name: str, config: CastleConfig, root: Path) -> ActionResult:
    """Take a deployment offline in its mode, dispatched by its manager."""
    manager = _svc_manager(name, config)

    if manager == "systemd":
        return disable_service(name)
    if manager == "caddy":
        return ActionResult(
            name, "deactivate", "ok",
            f"{name}: gateway-served — remove/disable the service to drop the route.",
        )
    if manager == "path":
        prog, comp = _program_for(name, config)
        if comp is None:
            return ActionResult(name, "deactivate", "error", f"unknown program '{prog}'")
        return await run_action("uninstall", prog, comp, root)
    if manager == "none":
        return ActionResult(name, "deactivate", "ok", f"{name}: external")

    comp = config.programs.get(name)
    if comp is not None:
        return await run_action("uninstall", name, comp, root)
    return ActionResult(name, "deactivate", "error", f"'{name}' not found")
