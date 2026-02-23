"""castle list - show all registered components."""

from __future__ import annotations

import argparse
import json
import logging

from castle_cli.config import load_config

log = logging.getLogger(__name__)

# Terminal colors
BOLD = "\033[1m"
RESET = "\033[0m"
DIM = "\033[2m"
GREEN = "\033[92m"
RED = "\033[91m"
CYAN = "\033[96m"
MAGENTA = "\033[95m"
YELLOW = "\033[93m"

CATEGORY_COLORS: dict[str, str] = {
    "service": GREEN,
    "job": MAGENTA,
    "tool": CYAN,
    "frontend": YELLOW,
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
    """List all components, services, and jobs."""
    config = load_config()
    deployed = _load_deployed()

    filter_type = getattr(args, "type", None)

    if getattr(args, "json", False):
        return _list_json(config, deployed, filter_type)

    any_output = False

    # Services
    if not filter_type or filter_type == "service":
        if config.services:
            any_output = True
            color = CATEGORY_COLORS["service"]
            print(f"\n{BOLD}{color}Services{RESET}")
            print(f"{color}{'─' * 40}{RESET}")
            for name, svc in config.services.items():
                port_str = ""
                if svc.expose and svc.expose.http:
                    port_str = f"  :{svc.expose.http.internal.port}"

                if deployed is not None:
                    status = f"{GREEN}●{RESET}" if name in deployed else f"{RED}○{RESET}"
                else:
                    status = f"{DIM}?{RESET}"

                desc = f"  {DIM}{svc.description}{RESET}" if svc.description else ""
                print(f"  {status} {BOLD}{name}{RESET}{port_str}{desc}")

    # Jobs
    if not filter_type or filter_type == "job":
        if config.jobs:
            any_output = True
            color = CATEGORY_COLORS["job"]
            print(f"\n{BOLD}{color}Jobs{RESET}")
            print(f"{color}{'─' * 40}{RESET}")
            for name, job in config.jobs.items():
                if deployed is not None:
                    status = f"{GREEN}●{RESET}" if name in deployed else f"{RED}○{RESET}"
                else:
                    status = f"{DIM}?{RESET}"

                desc = f"  {DIM}{job.description}{RESET}" if job.description else ""
                sched = f"  {DIM}[{job.schedule}]{RESET}"
                print(f"  {status} {BOLD}{name}{RESET}{sched}{desc}")

    # Tools
    if not filter_type or filter_type == "tool":
        tools = config.tools
        if tools:
            any_output = True
            color = CATEGORY_COLORS["tool"]
            print(f"\n{BOLD}{color}Tools{RESET}")
            print(f"{color}{'─' * 40}{RESET}")
            for name, comp in tools.items():
                desc = f"  {DIM}{comp.description}{RESET}" if comp.description else ""
                print(f"  {BOLD}{name}{RESET}{desc}")

    # Frontends
    if not filter_type or filter_type == "frontend":
        frontends = config.frontends
        if frontends:
            any_output = True
            color = CATEGORY_COLORS["frontend"]
            print(f"\n{BOLD}{color}Frontends{RESET}")
            print(f"{color}{'─' * 40}{RESET}")
            for name, comp in frontends.items():
                desc = f"  {DIM}{comp.description}{RESET}" if comp.description else ""
                print(f"  {BOLD}{name}{RESET}{desc}")

    if not any_output:
        print("No components found.")

    if deployed is None:
        print(f"\n{DIM}(no registry — run 'castle deploy' to generate){RESET}")

    print()
    return 0


def _list_json(
    config: object, deployed: dict | None, filter_type: str | None
) -> int:
    """Output JSON list of all entries."""
    output = []

    if not filter_type or filter_type == "service":
        for name, svc in config.services.items():
            entry: dict = {
                "name": name,
                "category": "service",
                "deployed": deployed is not None and name in deployed,
            }
            if svc.description:
                entry["description"] = svc.description
            if svc.expose and svc.expose.http:
                entry["port"] = svc.expose.http.internal.port
            output.append(entry)

    if not filter_type or filter_type == "job":
        for name, job in config.jobs.items():
            entry = {
                "name": name,
                "category": "job",
                "deployed": deployed is not None and name in deployed,
                "schedule": job.schedule,
            }
            if job.description:
                entry["description"] = job.description
            output.append(entry)

    if not filter_type or filter_type == "tool":
        for name, comp in config.tools.items():
            entry = {"name": name, "category": "tool"}
            if comp.description:
                entry["description"] = comp.description
            output.append(entry)

    if not filter_type or filter_type == "frontend":
        for name, comp in config.frontends.items():
            entry = {"name": name, "category": "frontend"}
            if comp.description:
                entry["description"] = comp.description
            output.append(entry)

    print(json.dumps(output, indent=2))
    return 0
