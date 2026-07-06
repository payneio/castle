"""castle list - the program catalog plus every deployment view (services, jobs,
tools, static)."""

from __future__ import annotations

import argparse
import json
import logging

from castle_cli.config import load_config

log = logging.getLogger(__name__)


def _deployments_of_kind(config: object, kind: str) -> dict:
    """The deployments whose derived kind matches (a lens over config.deployments)."""
    return config.store_for(kind)


# Terminal colors
BOLD = "\033[1m"
RESET = "\033[0m"
DIM = "\033[2m"
GREEN = "\033[92m"
RED = "\033[91m"
CYAN = "\033[96m"
MAGENTA = "\033[95m"
YELLOW = "\033[93m"

KIND_COLORS: dict[str, str] = {
    "service": GREEN,
    "job": MAGENTA,
    "tool": CYAN,
    "static": YELLOW,
    "reference": DIM,
}

STACK_DISPLAY: dict[str, str] = {
    "python-fastapi": "python-fastapi",
    "python-cli": "python-cli",
    "react-vite": "react-vite",
    "supabase": "supabase",
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

    Two orthogonal axes: the **Programs** catalog (filtered by derived `kind`)
    and the **Services**/**Jobs** deployment views. `--kind` filters the catalog
    by a program's derived kind (service/job/tool/static/reference).
    """
    from castle_core.lifecycle import is_active

    config = load_config()

    filter_kind = getattr(args, "kind", None)
    filter_stack = getattr(args, "stack", None)
    resource = getattr(args, "resource", None)  # scope to one section, or all

    if getattr(args, "json", False):
        return _list_json(config, filter_kind, filter_stack)

    def dot(name: str, kind: str = "service") -> str:
        return f"{GREEN}●{RESET}" if is_active(name, kind, config) else f"{RED}○{RESET}"

    any_output = False

    # A program's kinds are the kinds of its deployments (a program has no kind
    # of its own). Sorted, de-duplicated.
    def prog_kinds(name: str) -> list[str]:
        return sorted({kind for _, kind in config.deployments_of(name)})

    # Programs (the catalog) — filtered by a deployment kind + stack.
    progs = (
        {
            name: comp
            for name, comp in config.programs.items()
            if (not filter_kind or filter_kind in prog_kinds(name))
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
            kinds = prog_kinds(name)
            kinds_str = "".join(f"  {KIND_COLORS.get(k, '')}{k}{RESET}" for k in kinds)
            stack_str = f"  {DIM}{comp.stack}{RESET}" if comp.stack else ""
            desc = f"  {DIM}{comp.description}{RESET}" if comp.description else ""
            pk = (prog_kinds(name) or ["service"])[0]
            print(f"  {dot(name, pk)} {BOLD}{name}{RESET}{kinds_str}{stack_str}{desc}")

    # Services + Jobs (deployment views) — independent of behavior, so only shown
    # when no behavior filter is applied. Each gated by its own resource scope.
    if not filter_kind and resource in (None, "service"):
        services = _filter_by_stack(config.services, config, filter_stack)
        if services:
            any_output = True
            color = KIND_COLORS["service"]
            print(f"\n{BOLD}{color}Services{RESET}")
            print(f"{color}{'─' * 40}{RESET}")
            for name, svc in services.items():
                port_str = ""
                if svc.expose and svc.expose.http:
                    port_str = f"  :{svc.expose.http.internal.port}"
                stack = _resolve_stack(config, name)
                stack_str = f"  {DIM}{stack}{RESET}" if stack else ""
                desc = f"  {DIM}{svc.description}{RESET}" if svc.description else ""
                print(f"  {dot(name, 'service')} {BOLD}{name}{RESET}{port_str}{stack_str}{desc}")

    if not filter_kind and resource in (None, "job"):
        jobs = _filter_by_stack(config.jobs, config, filter_stack)
        if jobs:
            any_output = True
            print(f"\n{BOLD}{MAGENTA}Jobs{RESET}")
            print(f"{MAGENTA}{'─' * 40}{RESET}")
            for name, job in jobs.items():
                sched = f"  {DIM}[{job.schedule}]{RESET}"
                desc = f"  {DIM}{job.description}{RESET}" if job.description else ""
                print(f"  {dot(name, 'job')} {BOLD}{name}{RESET}{sched}{desc}")

    if not filter_kind and resource in (None, "tool"):
        tools = _filter_by_stack(_deployments_of_kind(config, "tool"), config, filter_stack)
        if tools:
            any_output = True
            color = KIND_COLORS["tool"]
            print(f"\n{BOLD}{color}Tools{RESET}")
            print(f"{color}{'─' * 40}{RESET}")
            for name, d in tools.items():
                stack = _resolve_stack(config, name)
                stack_str = f"  {DIM}{stack}{RESET}" if stack else ""
                desc = f"  {DIM}{d.description}{RESET}" if d.description else ""
                print(f"  {dot(name, 'tool')} {BOLD}{name}{RESET}{stack_str}{desc}")

    if not filter_kind and resource in (None, "static"):
        statics = _filter_by_stack(_deployments_of_kind(config, "static"), config, filter_stack)
        if statics:
            any_output = True
            color = KIND_COLORS["static"]
            print(f"\n{BOLD}{color}Static{RESET}")
            print(f"{color}{'─' * 40}{RESET}")
            for name, d in statics.items():
                sub = f"  {DIM}{name}.<domain>{RESET}"
                desc = f"  {DIM}{d.description}{RESET}" if d.description else ""
                print(f"  {dot(name, 'static')} {BOLD}{name}{RESET}{sub}{desc}")

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
        name: item for name, item in items.items() if _resolve_stack(config, name) == filter_stack
    }


def _list_json(
    config: object,
    filter_kind: str | None,
    filter_stack: str | None,
) -> int:
    """Output JSON: the program catalog (kind-filterable) plus deployments."""
    from castle_core.lifecycle import is_active

    output = []

    # Programs (catalog) — a program's kinds are its deployments' kinds.
    for name, comp in config.programs.items():
        kinds = sorted({kind for _, kind in config.deployments_of(name)})
        if filter_kind and filter_kind not in kinds:
            continue
        if filter_stack and comp.stack != filter_stack:
            continue
        entry: dict = {
            "name": name,
            "kinds": kinds,
            "active": is_active(name, (kinds or ["service"])[0], config),
        }
        if comp.stack:
            entry["stack"] = comp.stack
        if comp.description:
            entry["description"] = comp.description
        output.append(entry)

    # Services + Jobs (deployments) — only when not filtering by kind
    if not filter_kind:
        for name, svc in config.services.items():
            stack = _resolve_stack(config, name)
            if filter_stack and stack != filter_stack:
                continue
            entry = {"name": name, "kind": "service", "active": is_active(name, "service", config)}
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
                "active": is_active(name, "job", config),
                "schedule": job.schedule,
            }
            if stack:
                entry["stack"] = stack
            if job.description:
                entry["description"] = job.description
            output.append(entry)

        for kind in ("tool", "static"):
            for name, d in _deployments_of_kind(config, kind).items():
                stack = _resolve_stack(config, name)
                if filter_stack and stack != filter_stack:
                    continue
                entry = {"name": name, "kind": kind, "active": is_active(name, kind, config)}
                if stack:
                    entry["stack"] = stack
                if d.description:
                    entry["description"] = d.description
                output.append(entry)

    print(json.dumps(output, indent=2))
    return 0
