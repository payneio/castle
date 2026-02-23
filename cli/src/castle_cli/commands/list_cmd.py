"""castle list - show all registered components."""

from __future__ import annotations

import argparse
import json
import logging

from castle_cli.config import load_config
from castle_cli.manifest import Role

log = logging.getLogger(__name__)

# Terminal colors
BOLD = "\033[1m"
RESET = "\033[0m"
DIM = "\033[2m"
GREEN = "\033[92m"
RED = "\033[91m"

ROLE_COLORS: dict[str, str] = {
    Role.SERVICE: "\033[92m",  # green
    Role.TOOL: "\033[96m",  # cyan
    Role.WORKER: "\033[94m",  # blue
    Role.JOB: "\033[95m",  # magenta
    Role.FRONTEND: "\033[93m",  # yellow
    Role.REMOTE: "\033[90m",  # dim
    Role.CONTAINERIZED: "\033[33m",  # orange
}


def _load_deployed() -> dict[str, object] | None:
    """Try to load deployed state from registry, return None if unavailable."""
    try:
        from castle_core.registry import load_registry

        registry = load_registry()
        return registry.deployed
    except (FileNotFoundError, ValueError):
        return None


def run_list(args: argparse.Namespace) -> int:
    """List all components."""
    config = load_config()
    deployed = _load_deployed()

    components = config.components

    filter_role = getattr(args, "role", None)
    if filter_role:
        components = {k: v for k, v in components.items() if filter_role in v.roles}

    if getattr(args, "json", False):
        output = []
        for name, manifest in components.items():
            entry: dict = {
                "name": name,
                "roles": [r.value for r in manifest.roles],
                "deployed": deployed is not None and name in deployed,
            }
            if manifest.description:
                entry["description"] = manifest.description
            if manifest.expose and manifest.expose.http:
                entry["port"] = manifest.expose.http.internal.port
            if deployed and name in deployed:
                dep = deployed[name]
                if dep.port is not None:
                    entry["port"] = dep.port
            output.append(entry)
        print(json.dumps(output, indent=2))
        return 0

    if not components:
        print("No components found.")
        return 0

    # Group by primary role (first in sorted list)
    by_role: dict[str, list[tuple[str, object]]] = {}
    for name, manifest in components.items():
        primary_role = manifest.roles[0].value if manifest.roles else "other"
        by_role.setdefault(primary_role, []).append((name, manifest))

    # Display order
    role_order = ["service", "tool", "worker", "job", "frontend", "remote", "containerized"]
    for role_name in role_order:
        items = by_role.get(role_name, [])
        if not items:
            continue
        color = ROLE_COLORS.get(role_name, "")
        print(f"\n{BOLD}{color}{role_name}s{RESET}")
        print(f"{color}{'─' * 40}{RESET}")
        for name, manifest in items:
            port_str = ""
            if manifest.expose and manifest.expose.http:
                port_str = f"  :{manifest.expose.http.internal.port}"

            # Show deployed status indicator
            if deployed is not None:
                status = f"{GREEN}●{RESET}" if name in deployed else f"{RED}○{RESET}"
            else:
                status = f"{DIM}?{RESET}"

            desc = f"  {DIM}{manifest.description}{RESET}" if manifest.description else ""
            print(f"  {status} {BOLD}{name}{RESET}{port_str}{desc}")

    if deployed is None:
        print(f"\n{DIM}(no registry — run 'castle deploy' to generate){RESET}")

    print()
    return 0
