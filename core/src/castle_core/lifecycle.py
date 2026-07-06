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
import time
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
from castle_core.manifest import CaddyDeployment
from castle_core.registry import REGISTRY_PATH, load_registry
from castle_core.stacks import ActionResult, run_action


def _systemctl_active(unit: str) -> bool:
    result = subprocess.run(
        ["systemctl", "--user", "is-active", unit], capture_output=True, text=True
    )
    return result.stdout.strip() in ("active", "waiting")


_UV_TOOLS_CACHE: tuple[float, set[str]] | None = None


def _uv_tool_packages() -> set[str]:
    """Package names uv has installed as tools (`uv tool list`), briefly cached.

    Authoritative for install detection: a program's *package* name can differ
    from the console script it exposes (e.g. `litellm-intent-router` installs the
    `intent-router` executable), so a `which(<program>)` check misses it.
    """
    global _UV_TOOLS_CACHE
    now = time.monotonic()
    if _UV_TOOLS_CACHE is not None and now - _UV_TOOLS_CACHE[0] < 2.0:
        return _UV_TOOLS_CACHE[1]
    pkgs: set[str] = set()
    try:
        out = subprocess.run(
            ["uv", "tool", "list"], capture_output=True, text=True, timeout=5
        )
        for line in out.stdout.splitlines():
            # Package lines start at column 0 ("<name> vX.Y"); executables are
            # indented "- <exe>".
            if line and not line[0].isspace() and not line.startswith("-"):
                pkgs.add(line.split()[0])
    except Exception:
        pass
    _UV_TOOLS_CACHE = (now, pkgs)
    return pkgs


def _on_path(name: str) -> bool:
    """Whether a tool is installed, PATH-independent and script-name-independent.

    Checks, in order: the console script on PATH, the script in ~/.local/bin
    (uv's install dir), and finally `uv tool list` by *package* name — the last
    catches tools whose executable is named differently from the program.
    """
    if shutil.which(name) is not None:
        return True
    if (Path.home() / ".local" / "bin" / name).exists():
        return True
    return name in _uv_tool_packages()


def tool_installed(name: str) -> bool:
    """Public: whether a tool (by program/package name) is installed on PATH."""
    return _on_path(name)


def _svc_manager(name: str, kind: str, config: CastleConfig) -> str | None:
    """The manager for a deployment (name, kind), or None if not in config."""
    dep = config.deployment(kind, name)
    return dep.manager if dep is not None else None


def _static_built(name: str, config: CastleConfig) -> bool:
    """Whether a static (caddy) deployment's served dir exists (assets are built)."""
    dep = config.statics.get(name)
    if not isinstance(dep, CaddyDeployment):
        return False
    comp = config.programs.get(dep.program or name)
    return bool(comp and comp.source and (Path(comp.source) / dep.root).is_dir())


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


def is_active(name: str, kind: str, config: CastleConfig) -> bool:
    """Whether a deployment (name, kind) is available in its mode, by manager."""
    manager = _svc_manager(name, kind, config)
    if manager == "systemd":
        unit = timer_name(name) if kind == "job" else unit_name(name, kind)
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


def enable_service(name: str, kind: str, config: CastleConfig) -> ActionResult:
    """Generate+install the unit (and timer) from the registry, enable and start it."""
    if not REGISTRY_PATH.exists():
        return ActionResult(
            name, "activate", "error", "No registry. Run 'castle deploy' first."
        )
    registry = load_registry()
    deployed = registry.get(kind, name)
    if deployed is None:
        return ActionResult(
            name, "activate", "error", f"'{name}' not in registry; run 'castle deploy'."
        )
    if not deployed.managed:
        return ActionResult(
            name, "activate", "error", f"'{name}' is not a managed service."
        )

    systemd_spec = None
    dep = config.deployment(kind, name)
    manage = getattr(dep, "manage", None)
    if manage:
        systemd_spec = manage.systemd

    SYSTEMD_USER_DIR.mkdir(parents=True, exist_ok=True)
    svc_unit = unit_name(name, kind)
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


def disable_service(name: str, kind: str) -> ActionResult:
    """Stop, disable, and remove the unit (and timer) for a service/job of a kind."""
    units = [unit_name(name, kind)]
    if kind == "job":
        units.append(timer_name(name))
    for unit in units:
        path = SYSTEMD_USER_DIR / unit
        if path.exists():
            subprocess.run(["systemctl", "--user", "stop", unit], check=False)
            subprocess.run(["systemctl", "--user", "disable", unit], check=False)
            path.unlink()
    # Drop the generated secret env file alongside the unit.
    secret_env_path(name, kind).unlink(missing_ok=True)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    return ActionResult(name, "deactivate", "ok", f"{name}: deactivated")


# ---------------------------------------------------------------------------
# Activate / deactivate (dispatch by behavior)
# ---------------------------------------------------------------------------


def _program_for(name: str, kind: str, config: CastleConfig):
    """The program a deployment runs (its `program` ref, defaulting to the name)."""
    dep = config.deployment(kind, name)
    prog = (dep.program if dep else None) or name
    return prog, config.programs.get(prog)


async def activate(name: str, kind: str, config: CastleConfig, root: Path) -> ActionResult:
    """Make a deployment (name, kind) available in its mode, dispatched by manager."""
    manager = _svc_manager(name, kind, config)

    if manager == "systemd":
        # Ensure the program's binary is on PATH first (python), then enable the
        # unit. Skip the editable reinstall if it's already there.
        comp = config.programs.get(name)
        if comp is not None and (comp.stack or comp.commands) and not _on_path(name):
            res = await run_action("install", name, comp, root)
            if res.status != "ok":
                return res
        return enable_service(name, kind, config)

    if manager == "caddy":
        # Served by the gateway — reload it so the route is live. Building the
        # assets is `castle program build` (the program's concern), not activation.
        subprocess.run(
            ["systemctl", "--user", "reload", unit_name("castle-gateway")], check=False
        )
        return ActionResult(name, "activate", "ok", f"{name}: served via gateway")

    if manager == "path":
        prog, comp = _program_for(name, kind, config)
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


async def deactivate(name: str, kind: str, config: CastleConfig, root: Path) -> ActionResult:
    """Take a deployment (name, kind) offline in its mode, dispatched by manager."""
    manager = _svc_manager(name, kind, config)

    if manager == "systemd":
        return disable_service(name, kind)
    if manager == "caddy":
        return ActionResult(
            name, "deactivate", "ok",
            f"{name}: gateway-served — remove/disable the service to drop the route.",
        )
    if manager == "path":
        prog, comp = _program_for(name, kind, config)
        if comp is None:
            return ActionResult(name, "deactivate", "error", f"unknown program '{prog}'")
        return await run_action("uninstall", prog, comp, root)
    if manager == "none":
        return ActionResult(name, "deactivate", "ok", f"{name}: external")

    comp = config.programs.get(name)
    if comp is not None:
        return await run_action("uninstall", name, comp, root)
    return ActionResult(name, "deactivate", "error", f"'{name}' not found")
