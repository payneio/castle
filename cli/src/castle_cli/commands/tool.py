"""castle tool — the tools lens (programs installed on PATH).

A *tool* is a program with a `path` (manager) deployment: a CLI on your PATH.
This lens is what coding assistants use to discover what's available — so the
listing surfaces the *executable* to invoke (which can differ from the program
name, e.g. `litellm-intent-router` installs `intent-router`), the description,
and whether it's installed. `--json` gives a machine-readable context payload.
"""

from __future__ import annotations

import argparse
import json
import tomllib
from pathlib import Path

from castle_cli.config import load_config

BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"
GREEN = "\033[92m"
GREY = "\033[90m"
CYAN = "\033[96m"


def _is_tool(config: object, name: str) -> bool:
    return any(kind == "tool" for _, kind in config.deployments_of(name))


def _tool_programs(config: object) -> dict:
    """Programs with a tool (path) deployment, name-sorted."""
    return {name: comp for name, comp in sorted(config.programs.items()) if _is_tool(config, name)}


def _executables(comp: object) -> list[str]:
    """The console scripts a tool exposes, from its pyproject `[project.scripts]`.

    This is the command(s) to actually run — the source of truth even when the
    tool isn't installed. Falls back to the program name when none are declared
    (e.g. a non-python tool).
    """
    src = getattr(comp, "source", None)
    if src:
        pyproject = Path(src) / "pyproject.toml"
        if pyproject.exists():
            try:
                data = tomllib.loads(pyproject.read_text())
                scripts = data.get("project", {}).get("scripts", {})
                if scripts:
                    return sorted(scripts.keys())
            except (OSError, tomllib.TOMLDecodeError):
                pass
    return [comp.id]


def _tool_record(config: object, name: str, comp: object, installed: bool) -> dict:
    return {
        "name": name,
        "executables": _executables(comp),
        "description": comp.description,
        "installed": installed,
        "stack": comp.stack,
        "source": comp.source,
        "system_dependencies": comp.system_dependencies,
    }


def run_tool_list(args: argparse.Namespace) -> int:
    """List tools (programs on PATH) with their executable + description."""
    from castle_core.lifecycle import tool_installed

    config = load_config()
    tools = _tool_programs(config)
    records = [
        _tool_record(config, name, comp, tool_installed(name)) for name, comp in tools.items()
    ]

    if getattr(args, "json", False):
        print(json.dumps(records, indent=2))
        return 0

    if not records:
        print("No tools.")
        return 0

    print(f"\n{BOLD}Tools{RESET}")
    print("─" * 60)
    width = max(len(r["name"]) for r in records)
    for r in records:
        dot = f"{GREEN}●{RESET}" if r["installed"] else f"{GREY}○{RESET}"
        exes = ", ".join(r["executables"])
        exe_str = f"  {CYAN}{exes}{RESET}" if exes and exes != [r["name"]] else ""
        # Only show the executable when it differs from the name (the useful case).
        if r["executables"] == [r["name"]]:
            exe_str = ""
        desc = f"  {DIM}{r['description']}{RESET}" if r["description"] else ""
        print(f"  {dot} {BOLD}{r['name']:<{width}}{RESET}{exe_str}{desc}")
    print()
    return 0


def run_tool_info(args: argparse.Namespace) -> int:
    """Show one tool's details — executable, description, install state, source."""
    from castle_core.lifecycle import tool_installed

    config = load_config()
    name = args.name
    if name not in config.programs or not _is_tool(config, name):
        print(f"Error: no tool '{name}'.")
        return 1

    comp = config.programs[name]
    installed = tool_installed(name)
    record = _tool_record(config, name, comp, installed)

    if getattr(args, "json", False):
        print(json.dumps(record, indent=2))
        return 0

    exes = record["executables"]
    print(f"\n{BOLD}{name}{RESET}")
    print("─" * 40)
    if comp.description:
        print(f"  {BOLD}description{RESET}: {comp.description}")
    print(f"  {BOLD}run{RESET}:         {', '.join(exes)}")
    print(f"  {BOLD}installed{RESET}:   {'yes' if installed else 'no'}")
    if comp.source:
        print(f"  {BOLD}source{RESET}:      {comp.source}")
    if comp.stack:
        print(f"  {BOLD}stack{RESET}:       {comp.stack}")
    if comp.system_dependencies:
        print(f"  {BOLD}requires{RESET}:    {', '.join(comp.system_dependencies)}")
    if not installed:
        print(f"\n  {DIM}enable it in its deployment, then: castle apply{RESET}")
    else:
        print(f"\n  {DIM}run `{exes[0]} --help` for arguments{RESET}")
    print()
    return 0
