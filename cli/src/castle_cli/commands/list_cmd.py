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


def _resolve_stack(config: object, name: str) -> str | None:
    """Resolve stack from program reference or direct program."""
    # Check services for program ref
    if name in config.services:
        svc = config.services[name]
        comp_name = svc.program
        if comp_name and comp_name in config.programs:
            return config.programs[comp_name].stack
    # Check jobs for program ref
    if name in config.jobs:
        job = config.jobs[name]
        comp_name = job.program
        if comp_name and comp_name in config.programs:
            return config.programs[comp_name].stack
    # Direct program
    if name in config.programs:
        return config.programs[name].stack
    return None


def run_list(args: argparse.Namespace) -> int:
    """List all programs, services, and jobs.

    Two orthogonal axes: the **Programs** catalog (filtered by real `behavior`)
    and the **Services**/**Jobs** deployment views. `--behavior` filters the
    catalog only — it's a property of a program, not of a deployment.
    """
    from castle_core.lifecycle import is_active

    config = load_config()

    filter_behavior = getattr(args, "behavior", None)
    filter_stack = getattr(args, "stack", None)
    resource = getattr(args, "resource", None)  # scope to one section, or all

    if getattr(args, "json", False):
        return _list_json(config, filter_behavior, filter_stack)

    def dot(name: str) -> str:
        return f"{GREEN}●{RESET}" if is_active(name, config) else f"{RED}○{RESET}"

    any_output = False

    # Programs (the catalog) — filtered by real behavior + stack
    progs = (
        {
            name: comp
            for name, comp in config.programs.items()
            if (not filter_behavior or comp.behavior == filter_behavior)
            and (not filter_stack or comp.stack == filter_stack)
        }
        if resource in (None, "program")
        else {}
    )
    if progs:
        any_output = True
        print(f"\n{BOLD}{CYAN}Programs{RESET}")
        print(f"{CYAN}{'─' * 40}{RESET}")
        for name, comp in progs.items():
            behavior = comp.behavior or "program"
            bcolor = BEHAVIOR_COLORS.get(behavior, "")
            behavior_str = f"  {bcolor}{behavior}{RESET}"
            stack_str = f"  {DIM}{comp.stack}{RESET}" if comp.stack else ""
            desc = f"  {DIM}{comp.description}{RESET}" if comp.description else ""
            print(f"  {dot(name)} {BOLD}{name}{RESET}{behavior_str}{stack_str}{desc}")

    # Services + Jobs (deployment views) — independent of behavior, so only shown
    # when no behavior filter is applied. Each gated by its own resource scope.
    if not filter_behavior and resource in (None, "service"):
        services = _filter_by_stack(config.services, config, filter_stack)
        if services:
            any_output = True
            color = BEHAVIOR_COLORS["daemon"]
            print(f"\n{BOLD}{color}Services{RESET}")
            print(f"{color}{'─' * 40}{RESET}")
            for name, svc in services.items():
                port_str = ""
                if svc.expose and svc.expose.http:
                    port_str = f"  :{svc.expose.http.internal.port}"
                stack = _resolve_stack(config, name)
                stack_str = f"  {DIM}{stack}{RESET}" if stack else ""
                desc = f"  {DIM}{svc.description}{RESET}" if svc.description else ""
                print(f"  {dot(name)} {BOLD}{name}{RESET}{port_str}{stack_str}{desc}")

    if not filter_behavior and resource in (None, "job"):
        jobs = _filter_by_stack(config.jobs, config, filter_stack)
        if jobs:
            any_output = True
            print(f"\n{BOLD}{MAGENTA}Jobs{RESET}")
            print(f"{MAGENTA}{'─' * 40}{RESET}")
            for name, job in jobs.items():
                sched = f"  {DIM}[{job.schedule}]{RESET}"
                desc = f"  {DIM}{job.description}{RESET}" if job.description else ""
                print(f"  {dot(name)} {BOLD}{name}{RESET}{sched}{desc}")

    if not any_output:
        print(f"No {resource or 'program'}s found.")

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
    filter_behavior: str | None,
    filter_stack: str | None,
) -> int:
    """Output JSON: the program catalog (behavior-filterable) plus deployments."""
    from castle_core.lifecycle import is_active

    output = []

    # Programs (catalog) — filtered by real behavior + stack
    for name, comp in config.programs.items():
        if filter_behavior and comp.behavior != filter_behavior:
            continue
        if filter_stack and comp.stack != filter_stack:
            continue
        entry: dict = {
            "name": name,
            "kind": "program",
            "behavior": comp.behavior,
            "active": is_active(name, config),
        }
        if comp.stack:
            entry["stack"] = comp.stack
        if comp.description:
            entry["description"] = comp.description
        output.append(entry)

    # Services + Jobs (deployments) — only when not filtering by behavior
    if not filter_behavior:
        for name, svc in config.services.items():
            stack = _resolve_stack(config, name)
            if filter_stack and stack != filter_stack:
                continue
            entry = {"name": name, "kind": "service", "active": is_active(name, config)}
            if stack:
                entry["stack"] = stack
            if svc.description:
                entry["description"] = svc.description
            if svc.expose and svc.expose.http:
                entry["port"] = svc.expose.http.internal.port
            output.append(entry)

        for name, job in config.jobs.items():
            stack = _resolve_stack(config, name)
            if filter_stack and stack != filter_stack:
                continue
            entry = {
                "name": name,
                "kind": "job",
                "active": is_active(name, config),
                "schedule": job.schedule,
            }
            if stack:
                entry["stack"] = stack
            if job.description:
                entry["description"] = job.description
            output.append(entry)

    print(json.dumps(output, indent=2))
    return 0
