"""castle service / castle job — manage systemd service & timer units."""

from __future__ import annotations

import argparse
import subprocess

from castle_core.generators.systemd import (
    SYSTEMD_USER_DIR,
    timer_name,
    unit_name,
)

from castle_cli.config import (
    CastleConfig,
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


_PAST = {"start": "started", "stop": "stopped", "restart": "restarted"}


def run_service_cmd(args: argparse.Namespace) -> int:
    """`castle service restart <name>` — the imperative bounce (only verb left).

    Lifecycle (deploy/enable/disable/start/stop) is now convergence: `castle apply`.
    """
    config = load_config()
    return _unit_action(config, args.name, "restart", "service")


def run_job_cmd(args: argparse.Namespace) -> int:
    """`castle job restart <name>` — bounce the job's timer."""
    config = load_config()
    return _unit_action(config, args.name, "restart", "job")


def run_restart(args: argparse.Namespace) -> int:
    """Top-level `castle restart [name]` — bounce one deployment, or all of them.

    An imperative op: it re-actualizes current desired state, it does not change it
    (that's `castle apply`). A bare name bounces every kind sharing it.
    """
    config = load_config()
    name = getattr(args, "name", None)
    if not name:
        return _services_restart(config)
    named = config.deployments_named(name)
    if not named:
        print(f"Error: no deployment '{name}'.")
        return 1
    rc = 0
    for kind, _spec in named:
        rc |= _unit_action(config, name, "restart", kind)
    return rc


_GATEWAY_NAME = "castle-gateway"


def _unit_action(config: CastleConfig, name: str, action: str, kind: str) -> int:
    """start/stop/restart one deployment (name, kind), dispatched by its manager.

    systemd (a process/timer) → `systemctl`; caddy (static) → reload the gateway;
    path (a tool) → install/uninstall; none (remote) → nothing to do.
    """
    dep = config.deployment(kind, name)
    if dep is None:
        print(f"Error: no {kind} '{name}'.")
        return 1
    manager = dep.manager
    if manager != "systemd":
        return _managed_lifecycle(config, name, action, manager, kind)
    # A scheduled systemd deployment (a job) is driven by its .timer.
    unit = timer_name(name) if kind == "job" else unit_name(name, kind)
    result = subprocess.run(["systemctl", "--user", action, unit], check=False)
    if result.returncode != 0:
        print(f"Error: failed to {action} {unit}")
        return 1
    print(f"  {name}: {_PAST[action]}")
    return 0


def _managed_lifecycle(
    config: CastleConfig, name: str, action: str, manager: str, kind: str
) -> int:
    """Lifecycle for non-systemd managers (no unit to systemctl)."""
    if manager == "caddy":
        if action == "stop":
            print(f"  {name}: gateway-served — disable or remove it to drop the route.")
            return 0
        # start/restart → reload the gateway so current routes take effect.
        subprocess.run(["systemctl", "--user", "reload", unit_name(_GATEWAY_NAME)], check=False)
        print(f"  {name}: gateway reloaded ({_PAST[action]}).")
        return 0
    if manager == "path":
        return _path_lifecycle(config, name, action, kind)
    # none (remote): external, nothing local to act on.
    print(f"  {name}: external ({manager}) — nothing to {action}.")
    return 0


def _path_lifecycle(config: CastleConfig, name: str, action: str, kind: str) -> int:
    """A `path` (tool) deployment's lifecycle is install/uninstall on PATH."""
    import asyncio

    from castle_core.lifecycle import activate, deactivate

    # stop → uninstall; start/restart → ensure installed (activate skips if on PATH).
    coro = deactivate if action == "stop" else activate
    res = asyncio.run(coro(name, kind, config, config.root))
    print(f"  {res.output}")
    return 0 if res.status == "ok" else 1


def _services_restart(config: CastleConfig) -> int:
    """Restart every systemd-managed deployment (service or job) unit.

    caddy/path/none deployments have no unit — they ride along with the gateway
    restart (static) or are stateless (remote), so we don't systemctl them here.
    """
    for kind, name, dep in config.all_deployments():
        if dep.manager != "systemd":
            continue
        if kind == "job":
            subprocess.run(["systemctl", "--user", "restart", timer_name(name)], check=False)
            print(f"  {name}: restarted (timer)")
        else:
            subprocess.run(["systemctl", "--user", "restart", unit_name(name, kind)], check=False)
            print(f"  {name}: restarted")
    return 0


def run_status(args: argparse.Namespace) -> int:
    """Unified status across the platform: services + jobs + programs."""
    from castle_core.lifecycle import is_active

    config = load_config()

    # Services + jobs (deployment state); the gateway appears here as a service.
    _service_status(config)

    # Programs (catalog activation: tools on PATH, statics served by the gateway)
    catalog = {
        n: c
        for n, c in config.programs.items()
        if n not in config.services and n not in config.jobs
    }
    if catalog:
        print(f"{'─' * 50}")
        print("Programs")
        for name, _comp in catalog.items():
            _pk = sorted({k for _, k in config.deployments_of(name)})
            on = is_active(name, _pk[0] if _pk else "tool", config)
            color = "\033[92m" if on else "\033[90m"
            label = "active" if on else "inactive"
            kinds = sorted({k for _, k in config.deployments_of(name)})
            tag = ", ".join(kinds) if kinds else "program"
            print(f"  {color}{label:10s}\033[0m  {name}  ({tag})")
        print()
    return 0


def _service_status(config: CastleConfig) -> int:
    """Show status of all services and jobs, dispatched by manager."""
    from castle_core.lifecycle import is_active

    print("\nCastle Services")
    print("=" * 50)

    for name, svc in config.services.items():
        active = is_active(name, "service", config)  # manager-aware
        manager = svc.manager
        color = "\033[92m" if active else "\033[90m"
        reset = "\033[0m"
        label = "active" if active else "inactive"

        port_str = ""
        if svc.expose and svc.expose.http:
            port_str = f":{svc.expose.http.internal.port}"
        print(f"  {color}{label:10s}{reset}  {name}{port_str}  \033[90m[{manager}]{reset}")

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
