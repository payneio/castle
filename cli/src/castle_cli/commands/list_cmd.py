"""castle list - show all registered programs, services, and jobs."""

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

BEHAVIOR_COLORS: dict[str, str] = {
    "daemon": GREEN,
    "tool": CYAN,
    "frontend": YELLOW,
}

STACK_DISPLAY: dict[str, str] = {
    "python-fastapi": "python-fastapi",
    "python-cli": "python-cli",
    "react-vite": "react-vite",
    "rust": "rust",
    "go": "go",
    "bash": "bash",
    "container": "container",
    "command": "command",
}


def _load_deployed() -> dict[str, object] | None:
    """Try to load deployed state from registry, return None if unavailable."""
    try:
        from castle_core.registry import load_registry

        registry = load_registry()
        return registry.deployed
    except (FileNotFoundError, ValueError):
        return None


def _resolve_stack(config: object, name: str) -> str | None:
    """Resolve stack from program reference or direct program."""
    # Check services for program ref
    if name in config.services:
        svc = config.services[name]
        comp_name = svc.component
        if comp_name and comp_name in config.programs:
            return config.programs[comp_name].stack
    # Check jobs for program ref
    if name in config.jobs:
        job = config.jobs[name]
        comp_name = job.component
        if comp_name and comp_name in config.programs:
            return config.programs[comp_name].stack
    # Direct program
    if name in config.programs:
        return config.programs[name].stack
    return None


def run_list(args: argparse.Namespace) -> int:
    """List all programs, services, and jobs."""
    config = load_config()
    deployed = _load_deployed()

    filter_behavior = getattr(args, "behavior", None)
    filter_stack = getattr(args, "stack", None)

    if getattr(args, "json", False):
        return _list_json(config, deployed, filter_behavior, filter_stack)

    any_output = False

    # Daemons (services)
    if not filter_behavior or filter_behavior == "daemon":
        services = _filter_by_stack(config.services, config, filter_stack)
        if services:
            any_output = True
            color = BEHAVIOR_COLORS["daemon"]
            print(f"\n{BOLD}{color}Daemons{RESET}")
            print(f"{color}{'─' * 40}{RESET}")
            for name, svc in services.items():
                port_str = ""
                if svc.expose and svc.expose.http:
                    port_str = f"  :{svc.expose.http.internal.port}"

                if deployed is not None:
                    status = f"{GREEN}●{RESET}" if name in deployed else f"{RED}○{RESET}"
                else:
                    status = f"{DIM}?{RESET}"

                stack = _resolve_stack(config, name)
                stack_str = f"  {DIM}{stack}{RESET}" if stack else ""
                desc = f"  {DIM}{svc.description}{RESET}" if svc.description else ""
                print(f"  {status} {BOLD}{name}{RESET}{port_str}{stack_str}{desc}")

    # Scheduled (jobs)
    if not filter_behavior or filter_behavior == "tool":
        jobs = _filter_by_stack(config.jobs, config, filter_stack)
        if jobs:
            any_output = True
            color = MAGENTA
            print(f"\n{BOLD}{color}Scheduled{RESET}")
            print(f"{color}{'─' * 40}{RESET}")
            for name, job in jobs.items():
                if deployed is not None:
                    status = f"{GREEN}●{RESET}" if name in deployed else f"{RED}○{RESET}"
                else:
                    status = f"{DIM}?{RESET}"

                desc = f"  {DIM}{job.description}{RESET}" if job.description else ""
                sched = f"  {DIM}[{job.schedule}]{RESET}"
                print(f"  {status} {BOLD}{name}{RESET}{sched}{desc}")

    # Programs (tools, frontends, etc.)
    show_tools = not filter_behavior or filter_behavior == "tool"
    show_frontends = not filter_behavior or filter_behavior == "frontend"

    if show_tools or show_frontends:
        # Collect non-daemon programs
        comps: dict[str, tuple[str, str | None, str | None]] = {}

        if show_tools:
            for name, comp in config.tools.items():
                if filter_stack and comp.stack != filter_stack:
                    continue
                comps[name] = ("tool", comp.stack, comp.description)

        if show_frontends:
            for name, comp in config.frontends.items():
                if filter_stack and comp.stack != filter_stack:
                    continue
                if name not in comps:
                    comps[name] = ("frontend", comp.stack, comp.description)

        if comps:
            any_output = True
            color = CYAN
            print(f"\n{BOLD}{color}Programs{RESET}")
            print(f"{color}{'─' * 40}{RESET}")
            for name, (behavior, stack, description) in comps.items():
                stack_str = f"  {DIM}{stack}{RESET}" if stack else ""
                behavior_str = f"  {behavior}"
                desc = f"  {DIM}{description}{RESET}" if description else ""
                print(f"  {BOLD}{name}{RESET}{stack_str}{behavior_str}{desc}")

    if not any_output:
        print("No programs found.")

    if deployed is None:
        print(f"\n{DIM}(no registry — run 'castle deploy' to generate){RESET}")

    print()
    return 0


def _filter_by_stack(
    items: dict[str, object],
    config: object,
    filter_stack: str | None,
) -> dict[str, object]:
    """Filter items by stack if a filter is provided."""
    if not filter_stack:
        return items
    return {
        name: item
        for name, item in items.items()
        if _resolve_stack(config, name) == filter_stack
    }


def _list_json(
    config: object,
    deployed: dict | None,
    filter_behavior: str | None,
    filter_stack: str | None,
) -> int:
    """Output JSON list of all entries."""
    output = []

    if not filter_behavior or filter_behavior == "daemon":
        for name, svc in config.services.items():
            stack = _resolve_stack(config, name)
            if filter_stack and stack != filter_stack:
                continue
            entry: dict = {
                "name": name,
                "behavior": "daemon",
                "deployed": deployed is not None and name in deployed,
            }
            if stack:
                entry["stack"] = stack
            if svc.description:
                entry["description"] = svc.description
            if svc.expose and svc.expose.http:
                entry["port"] = svc.expose.http.internal.port
            output.append(entry)

    if not filter_behavior or filter_behavior == "tool":
        for name, job in config.jobs.items():
            stack = _resolve_stack(config, name)
            if filter_stack and stack != filter_stack:
                continue
            entry = {
                "name": name,
                "behavior": "tool",
                "deployed": deployed is not None and name in deployed,
                "schedule": job.schedule,
            }
            if stack:
                entry["stack"] = stack
            if job.description:
                entry["description"] = job.description
            output.append(entry)

    if not filter_behavior or filter_behavior == "tool":
        for name, comp in config.tools.items():
            if filter_stack and comp.stack != filter_stack:
                continue
            entry = {"name": name, "behavior": "tool"}
            if comp.stack:
                entry["stack"] = comp.stack
            if comp.description:
                entry["description"] = comp.description
            output.append(entry)

    if not filter_behavior or filter_behavior == "frontend":
        for name, comp in config.frontends.items():
            if filter_stack and comp.stack != filter_stack:
                continue
            entry = {"name": name, "behavior": "frontend"}
            if comp.stack:
                entry["stack"] = comp.stack
            if comp.description:
                entry["description"] = comp.description
            output.append(entry)

    print(json.dumps(output, indent=2))
    return 0
